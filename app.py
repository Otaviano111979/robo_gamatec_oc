import os
import pandas as pd

from extrator_oc import extrair_itens_oc
from matcher import match_lote_itens, carregar_base_krona
from validacao import validar_lote, salvar_validacao
from config import (
    CAMINHO_OC_EXEMPLO,
    CAMINHO_RESULTADO_PROCESSADO,
    CAMINHO_RESULTADO_VALIDADO,
)


CAMINHO_OC = CAMINHO_OC_EXEMPLO
CAMINHO_SAIDA_PROCESSADO = CAMINHO_RESULTADO_PROCESSADO
CAMINHO_SAIDA_VALIDADO = CAMINHO_RESULTADO_VALIDADO

PASTA_SAIDA = os.path.dirname(CAMINHO_SAIDA_PROCESSADO)
CAMINHO_PLANILHA_GAMATEC_CSV = os.path.join(PASTA_SAIDA, "planilha_gamatec.csv")
CAMINHO_PLANILHA_GAMATEC_XLSX = os.path.join(PASTA_SAIDA, "planilha_gamatec.xlsx")


def etapa_extracao(caminho_oc):
    print("\n[1/6] EXTRAINDO ITENS DA OC...")

    if not os.path.exists(caminho_oc):
        raise FileNotFoundError(f"Arquivo da OC não encontrado: {caminho_oc}")

    caminho_debug = os.path.join(
        os.path.dirname(CAMINHO_SAIDA_PROCESSADO),
        "debug_extracao_oc.txt"
    )

    itens = extrair_itens_oc(caminho_oc, caminho_debug=caminho_debug)

    if not itens:
        print("Nenhum item encontrado na extração.")
        return pd.DataFrame()

    df = pd.DataFrame(itens)

    df["descricao_oc"] = df["descricao_reconstruida"]
    df["quantidade_oc"] = df["quantidade"]
    df["unidade_oc"] = df["unidade_normalizada"]
    df["codigo_oc"] = df["codigo_interno_oc"]

    print(f"Itens extraídos: {len(df)}")
    print(f"Debug da extração salvo em: {caminho_debug}")

    if "status_extracao" in df.columns:
        resumo = df["status_extracao"].value_counts(dropna=False).to_dict()
        print(f"Resumo status extração: {resumo}")

    return df


def etapa_matching(df):
    print("\n[2/6] REALIZANDO MATCH HÍBRIDO (MRV + KRONA)...")

    base_krona = carregar_base_krona()
    df_match = match_lote_itens(df, base_krona=base_krona)

    print(f"Itens processados no matching: {len(df_match)}")

    if "tipo_match" in df_match.columns:
        resumo_match = df_match["tipo_match"].value_counts(dropna=False).to_dict()
        print(f"Resumo tipos de match: {resumo_match}")

    if "tipo_quantidade" in df_match.columns:
        resumo_qtd = df_match["tipo_quantidade"].value_counts(dropna=False).to_dict()
        print(f"Resumo regras de quantidade: {resumo_qtd}")

    return df_match


def etapa_unidade(df):
    print("\n[3/6] CONSOLIDANDO QUANTIDADE FINAL...")

    resultados = []

    for _, row in df.iterrows():
        item = row.to_dict()

        quantidade_original = item.get("quantidade_oc")
        quantidade_ajustada = item.get("quantidade_ajustada")

        quantidade_final = (
            quantidade_ajustada
            if quantidade_ajustada is not None and str(quantidade_ajustada).strip() != ""
            else quantidade_original
        )

        unidade_venda = item.get("unidade_venda_krona") or "UN"

        resultados.append({
            **item,
            "unidade_venda_considerada": unidade_venda,
            "quantidade_convertida": quantidade_final,
            "conversao_aplicada": item.get("tipo_quantidade"),
            "observacao_conversao": item.get("tipo_quantidade"),
            "revisao_unidade": False,
            "quantidade_final": quantidade_final,
        })

    df_final = pd.DataFrame(resultados)

    print(f"Itens com quantidade consolidada: {len(df_final)}")

    if "conversao_aplicada" in df_final.columns:
        resumo_conv = df_final["conversao_aplicada"].value_counts(dropna=False).to_dict()
        print(f"Resumo conversão aplicada: {resumo_conv}")

    return df_final


def etapa_salvar_processado(df):
    print("\n[4/6] SALVANDO RESULTADO PROCESSADO...")

    os.makedirs(os.path.dirname(CAMINHO_SAIDA_PROCESSADO), exist_ok=True)
    df.to_csv(CAMINHO_SAIDA_PROCESSADO, index=False, sep=";", encoding="utf-8-sig")

    print(f"Arquivo salvo em: {CAMINHO_SAIDA_PROCESSADO}")
    print(f"Total de linhas: {len(df)}")


def etapa_salvar_planilha_gamatec(df):
    """
    Gera planilha simples para inserção no GAMATEC com cabeçalho:
    DESCRICAO | UM | CODIGO_KRONA | QUANTIDADE
    """
    print("\n[5/6] GERANDO PLANILHA SIMPLES PARA GAMATEC...")

    os.makedirs(PASTA_SAIDA, exist_ok=True)

    registros = []

    for _, row in df.iterrows():
        item = row.to_dict()

        descricao = (
            item.get("descricao_krona")
            or item.get("descricao_oc")
            or item.get("descricao_reconstruida")
            or ""
        )

        unidade_final = (
            item.get("unidade_venda_considerada")
            or item.get("unidade_venda_krona")
            or item.get("unidade_oc")
            or "UN"
        )

        quantidade_final = (
            item.get("quantidade_final")
            if item.get("quantidade_final") is not None and str(item.get("quantidade_final")).strip() != ""
            else item.get("quantidade_convertida")
        )

        registros.append({
            "DESCRICAO": descricao,
            "UM": unidade_final,
            "CODIGO_KRONA": item.get("codigo_krona"),
            "QUANTIDADE": quantidade_final,
        })

    df_gamatec = pd.DataFrame(registros, columns=[
        "DESCRICAO",
        "UM",
        "CODIGO_KRONA",
        "QUANTIDADE",
    ])

    df_gamatec.to_csv(
        CAMINHO_PLANILHA_GAMATEC_CSV,
        index=False,
        sep=";",
        encoding="utf-8-sig"
    )

    df_gamatec.to_excel(
        CAMINHO_PLANILHA_GAMATEC_XLSX,
        index=False
    )

    print(f"Planilha GAMATEC CSV salva em: {CAMINHO_PLANILHA_GAMATEC_CSV}")
    print(f"Planilha GAMATEC XLSX salva em: {CAMINHO_PLANILHA_GAMATEC_XLSX}")
    print(f"Total de linhas da planilha GAMATEC: {len(df_gamatec)}")

    return df_gamatec


def etapa_validacao(df):
    print("\n[6/6] VALIDANDO ITENS PARA AUTOMAÇÃO...")

    df_validado, df_aprovados, df_revisao = validar_lote(df)

    os.makedirs(os.path.dirname(CAMINHO_SAIDA_VALIDADO), exist_ok=True)
    df_validado.to_csv(CAMINHO_SAIDA_VALIDADO, index=False, sep=";", encoding="utf-8-sig")

    info = salvar_validacao(df_aprovados, df_revisao)

    print(f"Resultado validado salvo em: {CAMINHO_SAIDA_VALIDADO}")
    print(f"Aprovados automático: {info['qtd_aprovados']}")
    print(f"Revisão manual: {info['qtd_revisao']}")

    return df_validado, df_aprovados, df_revisao


def main():
    print("\n==============================")
    print("PROCESSADOR DE OC - GAMATEC")
    print("==============================")

    df = etapa_extracao(CAMINHO_OC)

    if df.empty:
        print("Nenhum item encontrado.")
        return

    df = etapa_matching(df)
    df = etapa_unidade(df)

    etapa_salvar_processado(df)
    etapa_salvar_planilha_gamatec(df)
    _, df_aprovados, df_revisao = etapa_validacao(df)

    print("\nPROCESSAMENTO FINALIZADO")
    print(f"Itens prontos para automação: {len(df_aprovados)}")
    print(f"Itens para revisão manual: {len(df_revisao)}")


if __name__ == "__main__":
    main()