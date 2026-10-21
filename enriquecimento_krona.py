# -*- coding: utf-8 -*-
"""Camada aditiva de enriquecimento do catalogo Krona.

Le dois ficheiros opcionais gerados pelos importadores:
  - dados/aliases_krona.csv         (nomes Revit/imagens por codigo)
  - dados/catalogo_pdf_atributos.csv (bitola/embalagem do catalogo PDF)

Acrescenta colunas derivadas a base em memoria. Nunca altera codigo,
descricao, preco nem cria produtos. Se os ficheiros nao existirem, devolve
a base com as colunas vazias — o matcher continua a funcionar como antes.
"""
import os
from collections import Counter, defaultdict

import pandas as pd

import config

CAMINHO_ALIASES = os.path.join(config.PASTA_DADOS, "aliases_krona.csv")
CAMINHO_PDF = os.path.join(config.PASTA_DADOS, "catalogo_pdf_atributos.csv")

_MAPA_TIPO_CATEGORIA = {
    "TUBO": "TUBO",
    "JOELHO": "JOELHO",
    "CURVA": "JOELHO",
    "TE": "TE",
    "LUVA": "LUVA",
    "CAP": "CAP",
    "REDUCAO": "REDUCAO",
    "BUCHA": "BUCHA",
    "ADAPTADOR": "ADAPTADOR",
    "REGISTRO": "REGISTRO",
    "VALVULA": "VALVULA",
    "JUNCAO": "JUNCAO",
    "FLANGE": "FLANGE",
    "UNIAO": "UNIAO",
    "QUADRO": "QUADRO",
    "CAIXA": "CAIXA",
    "ELETRODUTO": "ELETRODUTO",
    "TORNEIRA": "TORNEIRA",
    "FITA": "FITA",
    "ENGATE": "ENGATE",
    "COLAR": "COLAR",
    "PROLONGAMENTO": "PROLONGAMENTO",
    "RALO": "RALO",
    "SIFAO": "SIFAO",
    "ASSENTO": "ASSENTO",
    "LAVATORIO": "LAVATORIO",
    "ADESIVO": "ADESIVO",
}

_JA_RELATOU = False


def _codigo(valor):
    texto = str(valor if valor is not None else "").strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto.lstrip("0") or "0"


def _numero(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if pd.isna(numero) or numero <= 0:
        return None
    return numero


def carregar_aliases():
    if not os.path.exists(CAMINHO_ALIASES):
        return pd.DataFrame(columns=["codigo_krona", "alias", "linha", "tipo", "consistente"])
    try:
        df = pd.read_csv(CAMINHO_ALIASES, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=["codigo_krona", "alias", "linha", "tipo", "consistente"])
    if "codigo_krona" not in df.columns:
        return pd.DataFrame(columns=["codigo_krona", "alias", "linha", "tipo", "consistente"])
    df["codigo_krona"] = df["codigo_krona"].map(_codigo)
    return df


def carregar_atributos_pdf():
    if not os.path.exists(CAMINHO_PDF):
        return pd.DataFrame(columns=["codigo_krona", "diametro_1_mm", "diametro_2_mm", "embalagem_pdf", "pagina"])
    try:
        df = pd.read_csv(CAMINHO_PDF, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=["codigo_krona", "diametro_1_mm", "diametro_2_mm", "embalagem_pdf", "pagina"])
    if "codigo_krona" not in df.columns:
        return pd.DataFrame(columns=["codigo_krona", "diametro_1_mm", "diametro_2_mm", "embalagem_pdf", "pagina"])
    df["codigo_krona"] = df["codigo_krona"].map(_codigo)
    return df


def _categoria_do_tipo(tipo):
    return _MAPA_TIPO_CATEGORIA.get(str(tipo or "").strip().upper(), "")


def _agregar_aliases(df):
    aliases = defaultdict(list)
    tipos = defaultdict(set)
    linhas = defaultdict(Counter)
    for _, row in df.iterrows():
        codigo = row["codigo_krona"]
        alias = str(row.get("alias") or "").strip()
        if alias:
            aliases[codigo].append(alias)
        tipo = str(row.get("tipo") or "").strip().upper()
        if tipo:
            tipos[codigo].add(tipo)
        linha = str(row.get("linha") or "").strip()
        if linha:
            linhas[codigo][linha] += 1
    texto_alias = {}
    tipo_unico = {}
    linha_unica = {}
    for codigo in set(aliases) | set(tipos) | set(linhas):
        nomes = sorted(set(aliases.get(codigo, [])), key=lambda a: (-len(a), a))
        texto_alias[codigo] = " | ".join(nomes)
        tipos_codigo = tipos.get(codigo, set())
        tipo_unico[codigo] = next(iter(tipos_codigo)) if len(tipos_codigo) == 1 else ""
        linha_unica[codigo] = linhas[codigo].most_common(1)[0][0] if linhas.get(codigo) else ""
    return texto_alias, tipo_unico, linha_unica


def enriquecer_base_krona(base):
    if base is None or base.empty:
        return base

    global _JA_RELATOU
    base = base.copy()
    codigos = base["codigo_krona"].map(_codigo)

    aliases = carregar_aliases()
    texto_alias, tipo_unico, linha_unica = _agregar_aliases(aliases) if not aliases.empty else ({}, {}, {})

    pdf = carregar_atributos_pdf()
    pdf_por_codigo = {}
    if not pdf.empty:
        for _, row in pdf.iterrows():
            pdf_por_codigo[row["codigo_krona"]] = row

    base["descricao_aliases"] = codigos.map(lambda c: texto_alias.get(c, ""))
    base["tipo_alias"] = codigos.map(lambda c: tipo_unico.get(c, ""))
    base["linha_alias"] = codigos.map(lambda c: linha_unica.get(c, ""))
    base["diametro_pdf_mm"] = codigos.map(
        lambda c: _numero(pdf_por_codigo[c].get("diametro_1_mm")) if c in pdf_por_codigo else None)
    base["diametro_pdf_2_mm"] = codigos.map(
        lambda c: _numero(pdf_por_codigo[c].get("diametro_2_mm")) if c in pdf_por_codigo else None)
    base["embalagem_pdf"] = codigos.map(
        lambda c: str(pdf_por_codigo[c].get("embalagem_pdf") or "") if c in pdf_por_codigo else "")
    base["pagina_pdf"] = codigos.map(
        lambda c: str(pdf_por_codigo[c].get("pagina") or "") if c in pdf_por_codigo else "")

    base["categoria_enriquecida"] = base["categoria_detectada"]
    vazias = base["categoria_enriquecida"].isna() | (
        base["categoria_enriquecida"].astype(str).str.strip().isin(["", "nan", "None"]))
    categoria_alias = base["tipo_alias"].map(_categoria_do_tipo)
    base.loc[vazias, "categoria_enriquecida"] = categoria_alias[vazias]
    base["categoria_enriquecida"] = base["categoria_enriquecida"].fillna("")

    if not _JA_RELATOU:
        _JA_RELATOU = True
        preenchidas = int((vazias & (categoria_alias != "")).sum())
        print(
            f"[ENRIQUECIMENTO] aliases: {len(texto_alias)} codigos | "
            f"pdf: {len(pdf_por_codigo)} codigos | "
            f"categorias preenchidas: {preenchidas}"
        )

    return base
