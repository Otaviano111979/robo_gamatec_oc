# -*- coding: utf-8 -*-
"""Extrai codigo -> bitola/embalagem do catalogo geral Krona em PDF.

Fonte: dados/Krona cataologo KRONA - GERAL.pdf (texto selecionavel, edicao 01/2024).
Saida aditiva: dados/catalogo_pdf_atributos.csv. Nao altera o catalogo.

Uso:
  GAMATEC_BASE_DIR=<sandbox> python importar_catalogo_pdf.py
"""
import argparse
import os
import re
import sys

import pandas as pd
from pypdf import PdfReader

import config

CAMPOS = [
    "codigo_krona", "bitola_pdf", "diametro_1_mm", "diametro_2_mm", "unidade_bitola",
    "embalagem_pdf", "pagina", "no_catalogo", "confere_diametro", "observacao",
]

_RX_LINHA = re.compile(r"^(0\d{3}|1\d{3})\s+(.+)$")
_RX_TELEFONE = re.compile(r"^0?800\s+\d{3}\s+\d{4}$")
_RX_EMBALAGEM = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:/\d{1,3}(?:\.\d{3})*)?$")
_RX_EMB_METRO = re.compile(r"^\d{1,3}(?:\.\d{3})*\s*m$", re.IGNORECASE)
_RX_MM = re.compile(r"^(\d{1,3})$")
_RX_PREFIXO_TIPO = re.compile(r"^(?:T\d|U\d)\s*[-–]?\s*")

# polegadas que aparecem no catalogo (notacao Krona: 1.1/4 = 1 1/4)
_RX_POL = re.compile(r'^(\d)(?:\.(\d+))?/(\d+)"?$')
_RX_POL_INTEIRO = re.compile(r'^(\d)"$')


def _num(texto):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return None


def _lado_bitola(lado):
    """Retorna (valor_mm, eh_polegada) para um lado da bitola."""
    lado = lado.strip()
    m = _RX_MM.match(lado)
    if m:
        return float(m.group(1)), False
    if _RX_POL.match(lado):
        return None, True
    if _RX_POL_INTEIRO.match(lado):
        return None, True
    return None, None


def _interpretar_bitola(bitola):
    """Retorna (d1_mm, d2_mm, unidade). unidade em {mm, pol, mm_pol, texto}."""
    texto = bitola.strip().replace("”", '"').replace("″", '"').replace("\ufffd", '"')
    texto = _RX_PREFIXO_TIPO.sub("", texto)
    texto = re.sub(r"\([^)]*\)", " ", texto)
    texto = texto.replace("*", " ")
    texto = re.sub(r"\s+", " ", texto).strip(" -–")
    if not texto:
        return None, None, "texto"

    lados = re.split(r"\s*[xX×]\s*", texto)
    if len(lados) > 2:
        return None, None, "texto"
    valores = [_lado_bitola(l) for l in lados]
    if any(v[1] is None for v in valores):
        return None, None, "texto"

    mm = [v[0] for v in valores]
    pol = [v[1] for v in valores]
    if all(not p for p in pol):
        return mm[0], (mm[1] if len(mm) > 1 else None), "mm"
    if all(pol) and not any(m is not None for m in mm):
        return None, None, "pol"
    if any(m is not None for m in mm) and any(pol):
        # misto: guarda apenas o lado em mm
        return next(m for m in mm if m is not None), None, "mm_pol"
    return None, None, "texto"


def _separar_linha(resto):
    """Separa bitola e embalagem. Retorna (bitola, embalagem)."""
    partes = resto.split()
    if len(partes) >= 3 and partes[-1].lower() == "m" and _RX_EMBALAGEM.match(partes[-2]):
        return " ".join(partes[:-2]).strip(), f"{partes[-2]} m"
    if len(partes) >= 2 and _RX_EMBALAGEM.match(partes[-1]):
        return " ".join(partes[:-1]).strip(), partes[-1]
    if len(partes) >= 2:
        return " ".join(partes[:-1]).strip(), partes[-1]
    return "", ""


def _ler_linhas(caminho_pdf):
    leitor = PdfReader(caminho_pdf)
    for numero, pagina in enumerate(leitor.pages, start=1):
        for linha in (pagina.extract_text() or "").splitlines():
            yield numero, linha.strip()


def _diametro_catalogo(catalogo):
    valor = catalogo.get("diametro_mm")
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    if texto == "" or texto.lower() == "nan":
        return None
    return _num(texto)


def _extrair(caminho_pdf, base):
    por_codigo_catalogo = {
        str(r["codigo_krona"]).strip(): r for _, r in base.iterrows()
    }
    registos = {}
    for pagina, linha in _ler_linhas(caminho_pdf):
        if _RX_TELEFONE.match(linha):
            continue
        m = _RX_LINHA.match(linha)
        if not m:
            continue
        codigo = m.group(1).lstrip("0") or "0"
        bitola, embalagem = _separar_linha(m.group(2))
        if not bitola and not embalagem:
            continue
        d1, d2, unidade = _interpretar_bitola(bitola)

        catalogo = por_codigo_catalogo.get(codigo)
        no_catalogo = "sim" if catalogo is not None else "nao"
        confere = ""
        observacao = ""
        if unidade == "texto":
            observacao = "bitola nao numerica"
        if catalogo is not None:
            diametro_catalogo = _diametro_catalogo(catalogo)
            if diametro_catalogo is None:
                confere = "preenche" if (d1 is not None or d2 is not None) else "sem_dado"
            elif any(
                abs(diametro_catalogo - valor) < 0.01
                for valor in (d1, d2) if valor is not None
            ):
                confere = "sim"
            elif d1 is None and d2 is None:
                confere = "sem_dado"
            else:
                confere = "nao"
                observacao = (observacao + f" | catalogo={diametro_catalogo:g}mm").strip(" |")
        else:
            confere = "fora_catalogo"

        if codigo in registos:
            anterior = registos[codigo]
            if anterior["bitola_pdf"] != bitola:
                anterior["observacao"] = (anterior["observacao"] + " | bitola repetida: " + bitola).strip(" |")
            continue
        registos[codigo] = {
            "codigo_krona": codigo,
            "bitola_pdf": bitola,
            "diametro_1_mm": int(d1) if d1 is not None else "",
            "diametro_2_mm": int(d2) if d2 is not None else "",
            "unidade_bitola": unidade,
            "embalagem_pdf": embalagem,
            "pagina": pagina,
            "no_catalogo": no_catalogo,
            "confere_diametro": confere,
            "observacao": observacao,
        }
    return sorted(registos.values(), key=lambda r: int(r["codigo_krona"]) if r["codigo_krona"].isdigit() else 10**9)


def _ler_anterior(caminho):
    if not os.path.exists(caminho):
        return {}
    try:
        df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
        return {str(r["codigo_krona"]): r for _, r in df.iterrows()}
    except Exception:
        return {}


def _delta(anterior, atual):
    antigos = set(anterior)
    novos = {r["codigo_krona"] for r in atual}
    print(f"[DELTA] novos: {len(novos - antigos)} | removidos: {len(antigos - novos)} | inalterados: {len(novos & antigos)}")
    for codigo in sorted(novos - antigos, key=lambda x: int(x) if x.isdigit() else 10**9)[:15]:
        r = next(x for x in atual if x["codigo_krona"] == codigo)
        print(f"   + {codigo:>5} bitola={r['bitola_pdf']} embal={r['embalagem_pdf']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default=config.CAMINHO_CATALOGO_PDF)
    parser.add_argument("--saida", default=os.path.join(config.PASTA_DADOS, "catalogo_pdf_atributos.csv"))
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"[ERRO] PDF ausente: {args.pdf}")
        return 1

    base = pd.read_csv(config.CAMINHO_BASE_KRONA_FINAL, sep=";", encoding="utf-8-sig", dtype=str)
    base["codigo_krona"] = base["codigo_krona"].astype(str).str.strip()

    atual = _extrair(args.pdf, base)
    _delta(_ler_anterior(args.saida), atual)

    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    pd.DataFrame(atual, columns=CAMPOS).to_csv(args.saida, index=False, sep=";", encoding="utf-8-sig")

    dentro = [r for r in atual if r["no_catalogo"] == "sim"]
    fora = [r for r in atual if r["no_catalogo"] == "nao"]
    pares = [r for r in atual if r["diametro_2_mm"] != ""]
    preenche = [r for r in atual if r["confere_diametro"] == "preenche"]
    divergem = [r for r in atual if r["confere_diametro"] == "nao"]
    confirmam = [r for r in atual if r["confere_diametro"] == "sim"]
    sem_dado = [r for r in atual if r["confere_diametro"] == "sem_dado"]

    print(f"[SAIDA] {args.saida}")
    print(f"[TOTAL] {len(atual)} codigos | no catalogo: {len(dentro)} | fora: {len(fora)}")
    print(f"[DIAMETRO] confirma: {len(confirmam)} | preenche: {len(preenche)} | diverge: {len(divergem)} | sem_dado: {len(sem_dado)} | pares (reducoes): {len(pares)}")
    print("[FORA] " + ", ".join(r["codigo_krona"] for r in fora))
    for r in divergem[:10]:
        print(f"   ! {r['codigo_krona']:>5} pdf={r['bitola_pdf']} {r['observacao']} pg={r['pagina']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
