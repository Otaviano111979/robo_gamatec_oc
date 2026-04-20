# -*- coding: utf-8 -*-
import os
import pandas as pd

try:
    from config import BASE_DIR as _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))

PASTA_SAIDA = os.path.join(os.environ.get("GAMATEC_BASE_DIR", _BASE_DIR), "saida")
CAMINHO_APROVADOS = os.path.join(PASTA_SAIDA, "itens_aprovados_automatico.csv")
CAMINHO_DESCONTOS_GAMATEC = os.path.join(PASTA_SAIDA, "descontos_gamatec.csv")
CAMINHO_PLANILHA_MANUAL_CSV = os.path.join(PASTA_SAIDA, "planilha_digitacao_manual.csv")
CAMINHO_PLANILHA_MANUAL_XLSX = os.path.join(PASTA_SAIDA, "planilha_digitacao_manual.xlsx")


def valor_numerico(v):
    if pd.isna(v):
        return None

    if isinstance(v, (int, float)):
        return float(v)

    texto = str(v).strip()
    if not texto:
        return None

    texto = texto.replace(" ", "")
    texto = texto.replace("%", "")

    if texto.count(",") == 1 and texto.count(".") >= 1:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return None


def normalizar_codigo(v):
    if pd.isna(v):
        return ""

    texto = str(v).strip()
    if not texto:
        return ""

    try:
        return str(int(float(texto)))
    except Exception:
        return texto.lstrip("0") or "0"


def carregar_mapa_descontos():
    mapa = {}

    if not os.path.exists(CAMINHO_DESCONTOS_GAMATEC):
        return mapa

    try:
        df_desc = pd.read_csv(CAMINHO_DESCONTOS_GAMATEC, sep=";", encoding="utf-8-sig")
    except Exception:
        return mapa

    if df_desc.empty or "codigo_krona" not in df_desc.columns:
        return mapa

    for _, row in df_desc.iterrows():
        codigo = normalizar_codigo(row.get("codigo_krona"))
        if not codigo:
            continue

        desconto = valor_numerico(row.get("desconto_calculado"))
        if desconto is None:
            continue

        mapa[codigo] = round(desconto, 5)

    return mapa


def resolver_desconto(item, mapa_descontos):
    candidatos = [
        item.get("desconto_calculado"),
        item.get("desconto_percentual"),
    ]

    codigo = normalizar_codigo(item.get("codigo_krona"))
    if codigo in mapa_descontos:
        candidatos.append(mapa_descontos[codigo])

    for valor in candidatos:
        desconto = valor_numerico(valor)
        if desconto is None:
            continue
        if desconto < 0:
            continue
        return round(desconto, 5)

    return None


def gerar_planilha_digitacao_manual():
    if not os.path.exists(CAMINHO_APROVADOS):
        raise FileNotFoundError(f"Arquivo não encontrado: {CAMINHO_APROVADOS}")

    df = pd.read_csv(CAMINHO_APROVADOS, sep=";", encoding="utf-8-sig")

    if df.empty:
        raise ValueError("O arquivo itens_aprovados_automatico.csv está vazio.")

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    mapa_descontos = carregar_mapa_descontos()
    registros = []

    for _, row in df.iterrows():
        item = row.to_dict()

        descricao = (
            item.get("descricao_krona")
            or item.get("descricao_oc")
            or item.get("descricao_reconstruida")
            or ""
        )

        quantidade = item.get("quantidade_final")
        if quantidade is None or str(quantidade).strip() == "":
            quantidade = item.get("quantidade_convertida")

        registros.append({
            "DESCRICAO": descricao,
            "CODIGO": normalizar_codigo(item.get("codigo_krona")),
            "QUANTIDADE": quantidade,
            "DESCONTO": resolver_desconto(item, mapa_descontos),
        })

    df_saida = pd.DataFrame(registros, columns=[
        "DESCRICAO",
        "CODIGO",
        "QUANTIDADE",
        "DESCONTO",
    ])

    df_saida.to_csv(
        CAMINHO_PLANILHA_MANUAL_CSV,
        index=False,
        sep=";",
        encoding="utf-8-sig"
    )

    df_saida.to_excel(
        CAMINHO_PLANILHA_MANUAL_XLSX,
        index=False
    )

    print("\n[PLANILHA DIGITAÇÃO MANUAL]")
    print(f"Arquivo CSV: {CAMINHO_PLANILHA_MANUAL_CSV}")
    print(f"Arquivo XLSX: {CAMINHO_PLANILHA_MANUAL_XLSX}")
    print(f"Total de itens: {len(df_saida)}")
    print(f"Itens com desconto preenchido: {int(df_saida['DESCONTO'].notna().sum())}")

    return df_saida


if __name__ == "__main__":
    gerar_planilha_digitacao_manual()
