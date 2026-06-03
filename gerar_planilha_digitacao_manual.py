# -*- coding: utf-8 -*-
import os
import pandas as pd

try:
    from config import BASE_DIR as _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))

PASTA_SAIDA = os.path.join(os.environ.get("GAMATEC_BASE_DIR", _BASE_DIR), "saida")
CAMINHO_APROVADOS = os.path.join(PASTA_SAIDA, "itens_aprovados_automatico.csv")
CAMINHO_REVISAO = os.path.join(PASTA_SAIDA, "itens_revisao_manual.csv")
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
    """
    Gera planilha de digitação manual combinando:
    1. Itens aprovados automaticamente (com match encontrado)
    2. Itens para revisão manual (sem match) — deixa código/descrição vazios
    
    Nunca falha por arquivo vazio — sempre gera saída mesmo sem matches.
    """
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    
    # ─── Carrega itens aprovados ───
    dfs_para_combinar = []
    
    if os.path.exists(CAMINHO_APROVADOS):
        df_aprovados = pd.read_csv(CAMINHO_APROVADOS, sep=";", encoding="utf-8-sig")
        if not df_aprovados.empty:
            df_aprovados["_tipo_item"] = "APROVADO"
            dfs_para_combinar.append(df_aprovados)
            print(f"Itens aprovados carregados: {len(df_aprovados)}")
    
    # ─── Carrega itens para revisão (sem match) ───
    if os.path.exists(CAMINHO_REVISAO):
        df_revisao = pd.read_csv(CAMINHO_REVISAO, sep=";", encoding="utf-8-sig")
        if not df_revisao.empty:
            df_revisao["_tipo_item"] = "SEM_MATCH"
            dfs_para_combinar.append(df_revisao)
            print(f"Itens para revisão carregados: {len(df_revisao)}")
    
    # ─── Combina os DataFrames ───
    if not dfs_para_combinar:
        print("\n[AVISO] Nenhum arquivo de itens encontrado (aprovados ou revisão).")
        print(f"  Aprovados: {CAMINHO_APROVADOS}")
        print(f"  Revisão:   {CAMINHO_REVISAO}")
        # Retorna planilha vazia em vez de falhar
        df = pd.DataFrame(columns=["DESCRICAO", "CODIGO", "QUANTIDADE", "DESCONTO"])
    else:
        df = pd.concat(dfs_para_combinar, ignore_index=True)
        print(f"\nTotal de itens para planilha: {len(df)}")
    
    mapa_descontos = carregar_mapa_descontos()
    registros = []

    for _, row in df.iterrows():
        item = row.to_dict()
        tipo_item = item.get("_tipo_item", "APROVADO")

        # ─── Para APROVADOS: tenta preencher descrição e código ───
        if tipo_item == "APROVADO":
            descricao = (
                item.get("descricao_krona")
                or item.get("descricao_oc")
                or item.get("descricao_reconstruida")
                or ""
            )
            codigo = normalizar_codigo(item.get("codigo_krona"))
        # ─── Para SEM_MATCH: deixa vazio (o usuário digitará) ───
        else:
            descricao = ""
            codigo = ""

        quantidade = item.get("quantidade_final")
        if quantidade is None or str(quantidade).strip() == "":
            quantidade = item.get("quantidade_convertida")

        # ─── Resolve desconto (só para aprovados) ───
        desconto = None
        if tipo_item == "APROVADO":
            desconto = resolver_desconto(item, mapa_descontos)

        registros.append({
            "DESCRICAO": descricao,
            "CODIGO": codigo,
            "QUANTIDADE": quantidade,
            "DESCONTO": desconto,
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
    itens_com_codigo = int(df_saida['CODIGO'].notna().sum() - int((df_saida['CODIGO'] == "").sum()))
    print(f"Itens com código preenchido: {itens_com_codigo}")
    print(f"Itens sem match (para revisão manual): {int((df_saida['CODIGO'] == "").sum())}")
    print(f"Itens com desconto preenchido: {int(df_saida['DESCONTO'].notna().sum())}")

    return df_saida


if __name__ == "__main__":
    gerar_planilha_digitacao_manual()
