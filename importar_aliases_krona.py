# -*- coding: utf-8 -*-
"""Importa nomes alternativos por codigo Krona a partir das familias Revit e imagens.

Fontes:
  - fichas .TXT ao lado das familias .rfa (UTF-16, duas linhas CSV)
  - nomes das pastas de imagens ("0135-...-0139 - Tubo de PVC esgoto ...")

O resultado e aditivo: o catalogo (base_krona_final.csv) continua a mandar em
codigo, descricao e preco. Este ficheiro so acrescenta nomes, tipo e imagem.

Uso:
  GAMATEC_BASE_DIR=<sandbox> python importar_aliases_krona.py [--fonte PASTA]
"""
import argparse
import csv
import io
import os
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

import config

FONTE_PADRAO = r"C:\Users\geren\OneDrive\Área de Trabalho\Krona para uso div"
SAIDA_PADRAO = os.path.join(config.PASTA_DADOS, "aliases_krona.csv")

CAMPOS_SAIDA = [
    "codigo_krona", "alias", "linha", "tipo", "medidas",
    "fonte_tipo", "fonte_arquivo", "consistente", "imagem_ref",
]

# Ordem importa: o primeiro tipo que casar vence (ex.: BUCHA antes de REDUCAO).
_TIPOS = [
    ("QUADRO", (r"\bQUADRO\b",)),
    ("PROLONGAMENTO", (r"\bPROLONGAMENTO\b",)),
    ("RALO", (r"\bRALO\b",)),
    ("CAIXA", (r"\bCAIXA\b", r"\bCX\.?\b")),
    ("ELETRODUTO", (r"\bELETROD", r"\bCORRUG")),
    ("JUNCAO", (r"\bJUN[CÇ][AÃ]O\b", r"\bJUNC\b")),
    ("BUCHA", (r"\bBUCHA\b",)),
    ("REGISTRO", (r"\bREGISTRO\b", r"\bREG\.")),
    ("UNIAO", (r"\bUNI[AÃ]O\b",)),
    ("ADAPTADOR", (r"\bADAPTADOR\b", r"\bADAPT\.")),
    ("TUBO", (r"\bTUBO\b",)),
    ("JOELHO", (r"\bJOELHO\b",)),
    ("CURVA", (r"\bCURVA\b",)),
    ("TE", (r"\bTE\b",)),
    ("LUVA", (r"\bLUVA\b",)),
    ("CAP", (r"\bCAP\b",)),
    ("SIFAO", (r"\bSIF[AÃ]O\b", r"\bSIF\b")),
    ("VALVULA", (r"\bV[AÁ]LVULA\b", r"\bVALV\b")),
    ("TERMINAL", (r"\bTERMINAL\b",)),
    ("COLAR", (r"\bCOLAR\b",)),
    ("ADESIVO", (r"\bADESIVO\b", r"\bADESI\b")),
    ("FITA", (r"\bFITA\b",)),
    ("TORNEIRA", (r"\bTORNEIRA\b", r"\bTORN\.")),
    ("ENGATE", (r"\bENGATE\b",)),
    ("ASSENTO", (r"\bASSENTO\b",)),
    ("LAVATORIO", (r"\bLAVAT[OÓ]RIO\b",)),
    ("REDUCAO", (r"\bREDU[CÇ][AÃ]O\b", r"\bRED\.?(?=\s)",)),
]

_RX_CODIGO_FICHEIRO = re.compile(r"_(\d{3,4})\.(?:rfa|txt)$", re.I)
_RX_MEDIDAS = re.compile(r"\b\d{1,3}(?:\s*[X×]\s*\d{1,3})+\s*(?:MM)?\b|\b\d{1,3}\s*MM\b|\bDN\s*\d{1,3}(?:\s*[X×]\s*\d{1,3})?", re.I)


def _sem_acento(texto):
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()


def _tipo(descricao):
    texto = _sem_acento(descricao).upper()
    texto = re.sub(r"\s+", " ", texto)
    achados = []
    for prioridade, (tipo, padroes) in enumerate(_TIPOS):
        for padrao in padroes:
            m = re.search(padrao, texto)
            if m:
                achados.append((m.start(), prioridade, tipo))
                break
    if not achados:
        return ""
    return min(achados)[2]


def _medidas(descricao):
    encontradas = []
    for m in _RX_MEDIDAS.findall(str(descricao or "")):
        normalizada = re.sub(r"\s+", "", m.upper())
        if normalizada not in encontradas:
            encontradas.append(normalizada)
    return "|".join(encontradas)


def _codigo(texto):
    return str(texto or "").strip().lstrip("0") or ""


def _ler_ficha(raw):
    try:
        texto = raw.decode("utf-16")
    except UnicodeDecodeError:
        try:
            texto = raw.decode("latin-1")
        except UnicodeDecodeError:
            return None
    linhas = [r for r in csv.reader(io.StringIO(texto)) if any(c.strip() for c in r)]
    if len(linhas) < 2:
        return None
    dados = dict(zip(linhas[0], linhas[1]))
    codigo = _codigo(dados.get("Model##OTHER##"))
    descricao = _sem_duplicacao((dados.get("Description##OTHER##") or "").strip())
    linha = _linha_canonica(dados.get("Krona: Linha##OTHER##"))
    if not descricao:
        return None
    return {"codigo": codigo, "alias": descricao, "linha": linha}


def _codigos_da_pasta(nome_pasta):
    prefixo = re.split(r"\s+-\s+|\s+(?=[A-Za-zÀ-ÿ])", nome_pasta, maxsplit=1)[0]
    return [_codigo(c) for c in re.findall(r"\b0?(\d{3,4})\b", prefixo)]


def _nome_da_pasta(nome_pasta):
    if " - " in nome_pasta:
        return nome_pasta.split(" - ", 1)[1].strip()
    resto = re.sub(r"^[\d\s\-]+", "", nome_pasta).strip()
    return re.sub(r"^-\s*", "", resto)


def _linha_canonica(linha):
    texto = _sem_acento(linha).upper()
    if "AGUA QUENTE" in texto:
        return "AGUA_QUENTE"
    if "AGUA FRIA" in texto:
        return "AGUA_FRIA"
    if "ESGOTO" in texto:
        return "ESGOTO"
    if any(t in texto for t in ("ELETR", "QUADRO", "CAIXA DE PASSAGEM", "CAIXAS DE ESGOTO", "VDI")):
        return "ELETRICA"
    if "ACESSORIO" in texto:
        return "ACESSORIOS"
    return ""


def _linha_do_caminho(caminho):
    texto = _sem_acento(caminho).upper()
    if "AGUA QUENTE" in texto or "AGUA-QUENTE" in texto:
        return "AGUA_QUENTE"
    if "AGUA FRIA" in texto or "AGUA-FRIA" in texto:
        return "AGUA_FRIA"
    if "ESGOTO" in texto:
        return "ESGOTO"
    if "ELETRIC" in texto:
        return "ELETRICA"
    if "ACESSORIO" in texto:
        return "ACESSORIOS"
    return ""


def _sem_duplicacao(texto):
    partes = re.split(r"\s{2,}", texto.strip())
    if len(partes) == 2 and partes[0].upper() == partes[1].upper():
        return partes[0]
    metade = len(texto) // 2
    if len(texto) % 2 == 0 and texto[:metade].strip().upper() == texto[metade:].strip().upper():
        return texto[:metade].strip()
    return texto


def _registos_zip(caminho_zip):
    registos = []
    with zipfile.ZipFile(caminho_zip) as zf:
        for entrada in zf.namelist():
            if entrada.lower().endswith(".txt"):
                ficha = _ler_ficha(zf.read(entrada))
                if not ficha:
                    continue
                if not ficha["codigo"]:
                    m = _RX_CODIGO_FICHEIRO.search(os.path.basename(entrada))
                    ficha["codigo"] = _codigo(m.group(1)) if m else ""
                if ficha["codigo"]:
                    registos.append({**ficha, "fonte_tipo": "revit_txt",
                                     "fonte_arquivo": f"{os.path.basename(caminho_zip)}:{entrada}",
                                     "imagem_ref": ""})
        pastas = sorted({os.path.dirname(n) for n in zf.namelist()
                         if n.lower().endswith((".png", ".jpg"))})
        for pasta in pastas:
            nome = os.path.basename(pasta)
            alias = _nome_da_pasta(nome)
            if not alias:
                continue
            imagens = [n for n in zf.namelist()
                       if os.path.dirname(n) == pasta and n.lower().endswith((".png", ".jpg"))]
            for codigo in _codigos_da_pasta(nome):
                registos.append({"codigo": codigo, "alias": alias,
                                 "linha": _linha_do_caminho(pasta),
                                 "fonte_tipo": "pasta_imagem",
                                 "fonte_arquivo": os.path.basename(caminho_zip),
                                 "imagem_ref": f"{os.path.basename(caminho_zip)}:{imagens[0]}" if imagens else ""})
    return registos


def _registos_pasta(raiz):
    registos = []
    for pasta_atual, _, ficheiros in os.walk(raiz):
        for nome in ficheiros:
            if not nome.lower().endswith(".txt"):
                continue
            caminho = os.path.join(pasta_atual, nome)
            try:
                with open(caminho, "rb") as f:
                    ficha = _ler_ficha(f.read())
            except OSError:
                continue
            if not ficha:
                continue
            if not ficha["codigo"]:
                m = _RX_CODIGO_FICHEIRO.search(nome)
                ficha["codigo"] = _codigo(m.group(1)) if m else ""
            if ficha["codigo"]:
                registos.append({**ficha, "fonte_tipo": "revit_txt",
                                 "fonte_arquivo": os.path.relpath(caminho, raiz), "imagem_ref": ""})
    for pasta_atual, _, ficheiros in os.walk(raiz):
        imagens = [f for f in ficheiros if f.lower().endswith((".png", ".jpg"))]
        if not imagens:
            continue
        nome = os.path.basename(pasta_atual)
        alias = _nome_da_pasta(nome)
        if not alias:
            continue
        for codigo in _codigos_da_pasta(nome):
            registos.append({"codigo": codigo, "alias": alias,
                             "linha": _linha_do_caminho(pasta_atual),
                             "fonte_tipo": "pasta_imagem",
                             "fonte_arquivo": os.path.relpath(pasta_atual, raiz),
                             "imagem_ref": os.path.relpath(os.path.join(pasta_atual, imagens[0]), raiz)})
    return registos


def _varrer(fonte):
    registos = []
    for raiz, _, ficheiros in os.walk(fonte):
        for nome in ficheiros:
            if nome.lower().endswith(".zip"):
                try:
                    registos.extend(_registos_zip(os.path.join(raiz, nome)))
                except (zipfile.BadZipFile, OSError) as erro:
                    print(f"[AVISO] zip ilegivel {nome}: {erro}")
    registos.extend(_registos_pasta(fonte))
    return registos


def _validar(registos, base):
    por_codigo = {str(r["codigo_krona"]).strip(): r for _, r in base.iterrows()}
    saida = []
    vistos = set()
    for r in registos:
        codigo = _codigo(r["codigo"])
        if not codigo:
            continue
        chave = (codigo, r["alias"].upper(), r["fonte_tipo"])
        if chave in vistos:
            continue
        vistos.add(chave)
        catalogo = por_codigo.get(codigo)
        tipo_alias = _tipo(r["alias"])
        linha = r["linha"] or _linha_do_caminho(r["fonte_arquivo"])
        if catalogo is None:
            consistente = "fora_catalogo"
        else:
            tipo_catalogo = _tipo(catalogo.get("descricao_krona")) or str(catalogo.get("categoria_detectada") or "").strip().upper()
            consistente = "sim" if (not tipo_alias or not tipo_catalogo or tipo_alias == tipo_catalogo) else "nao"
        saida.append({
            "codigo_krona": codigo,
            "alias": r["alias"],
            "linha": linha,
            "tipo": tipo_alias,
            "medidas": _medidas(r["alias"]),
            "fonte_tipo": r["fonte_tipo"],
            "fonte_arquivo": r["fonte_arquivo"],
            "consistente": consistente,
            "imagem_ref": r["imagem_ref"],
        })
    saida.sort(key=lambda x: (int(x["codigo_krona"]) if x["codigo_krona"].isdigit() else 10**9,
                              x["fonte_tipo"], x["alias"]))
    return saida


def _ler_anterior(caminho):
    if not os.path.exists(caminho):
        return {}
    try:
        df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    except Exception:
        return {}
    return {(str(r["codigo_krona"]), r["alias"], r["fonte_tipo"]): r for _, r in df.iterrows()}


def _relatorio_delta(anterior, atual):
    chaves_antigas = set(anterior)
    chaves_novas = {(r["codigo_krona"], r["alias"], r["fonte_tipo"]) for r in atual}
    novos = chaves_novas - chaves_antigas
    removidos = chaves_antigas - chaves_novas
    print(f"[DELTA] novos: {len(novos)} | removidos: {len(removidos)} | inalterados: {len(chaves_novas & chaves_antigas)}")
    for codigo, alias, fonte in sorted(novos)[:20]:
        print(f"   + {codigo:>5} {fonte:12} {alias[:70]}")
    for codigo, alias, fonte in sorted(removidos)[:10]:
        print(f"   - {codigo:>5} {fonte:12} {alias[:70]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fonte", default=FONTE_PADRAO)
    parser.add_argument("--saida", default=SAIDA_PADRAO)
    args = parser.parse_args()

    if not os.path.isdir(args.fonte):
        print(f"[ERRO] pasta de origem inexistente: {args.fonte}")
        return 1

    base = pd.read_csv(config.CAMINHO_BASE_KRONA_FINAL, sep=";", encoding="utf-8-sig", dtype=str)
    base["codigo_krona"] = base["codigo_krona"].astype(str).str.strip()

    print(f"[FONTE] {args.fonte}")
    registos = _varrer(args.fonte)
    print(f"[LIDO] {len(registos)} registos brutos")

    atual = _validar(registos, base)
    anterior = _ler_anterior(args.saida)
    _relatorio_delta(anterior, atual)

    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    pd.DataFrame(atual, columns=CAMPOS_SAIDA).to_csv(
        args.saida, index=False, sep=";", encoding="utf-8-sig"
    )

    codigos = {r["codigo_krona"] for r in atual}
    catalogo = set(base["codigo_krona"])
    fontes = Counter(r["fonte_tipo"] for r in atual)
    conflitos = [r for r in atual if r["consistente"] == "nao"]
    fora = [r for r in atual if r["consistente"] == "fora_catalogo"]

    print(f"[SAIDA] {args.saida}")
    print(f"[TOTAL] {len(atual)} aliases | {len(codigos)} codigos | "
          f"cobre {len(codigos & catalogo)}/{len(catalogo)} = {len(codigos & catalogo)/len(catalogo):.0%} do catalogo")
    print(f"[FONTES] {dict(fontes)}")
    print(f"[CONFLITOS] tipo diferente do catalogo: {len(conflitos)} | fora do catalogo: {len({r['codigo_krona'] for r in fora})} codigos")
    for r in conflitos[:15]:
        print(f"   ! {r['codigo_krona']:>5} {r['tipo']:12} {r['alias'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
