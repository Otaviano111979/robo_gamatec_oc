import os
import pandas as pd

from config import BASE_DIR


# caminhos lidos do config, sem valor fixo no codigo
PASTA_SAIDA = os.path.join(BASE_DIR, "saida")
CAMINHO_APROVADOS = os.path.join(PASTA_SAIDA, "itens_aprovados_automatico.csv")
CAMINHO_REVISAO = os.path.join(PASTA_SAIDA, "itens_revisao_manual.csv")


TIPOS_MATCH_APROVADOS = {
    "MATCH_CODIGO_MRV",
    "MATCH_CODIGO_BRASAL",
    "MATCH_FORTE",
    "MATCH_BOM",
    "MATCH_FRACO",
    "MATCH_DESCRICAO",          # match por descricao — aprovado automaticamente
    "MATCH_DESCRICAO_REVISAR",  # match por descricao com empate — aprovado mas sinalizado
}


def valor_bool(v):
    if isinstance(v, bool):
        return v
    if pd.isna(v):
        return False
    if isinstance(v, str):
        return v.strip().lower() in ["true", "1", "sim", "yes"]
    return bool(v)


def valor_numerico(v):
    if pd.isna(v):
        return None
    try:
        return float(v)
    except Exception:
        return None


def validar_item(item: dict):
    motivos = []

    match_encontrado = valor_bool(item.get("match_encontrado"))
    tipo_match = str(item.get("tipo_match") or "").strip().upper()
    revisao_match = valor_bool(item.get("revisao_manual"))
    revisao_unidade = valor_bool(item.get("revisao_unidade"))

    codigo_krona = item.get("codigo_krona")

    # prioridade para quantidade_final
    quantidade_final = valor_numerico(item.get("quantidade_final"))
    quantidade_convertida = valor_numerico(item.get("quantidade_convertida"))
    quantidade_validada = (
        quantidade_final if quantidade_final is not None else quantidade_convertida
    )

    desconto_percentual = valor_numerico(item.get("desconto_percentual"))
    desconto_valido = item.get("desconto_valido")

    if not match_encontrado:
        motivos.append("SEM_MATCH")

    if tipo_match not in TIPOS_MATCH_APROVADOS:
        motivos.append(f"TIPO_MATCH_NAO_APROVADO:{tipo_match or 'VAZIO'}")

    # Mantido flexível nesta fase
    # Não bloqueia por revisão do match nem por revisão de unidade
    # para não impedir automação enquanto a arquitetura está sendo ajustada.
    # if revisao_match:
    #     motivos.append("REVISAO_MATCH")
    #
    # if revisao_unidade:
    #     motivos.append("REVISAO_UNIDADE")

    if codigo_krona is None or str(codigo_krona).strip() == "":
        motivos.append("SEM_CODIGO_KRONA")

    if quantidade_validada is None:
        motivos.append("SEM_QUANTIDADE_FINAL")
    elif quantidade_validada <= 0:
        motivos.append("QUANTIDADE_FINAL_INVALIDA")

    if desconto_percentual is not None:
        if desconto_percentual < 0:
            motivos.append("DESCONTO_NEGATIVO")

    if desconto_valido is not None:
        desconto_valido_bool = valor_bool(desconto_valido)
        if not desconto_valido_bool and desconto_percentual is not None:
            motivos.append("DESCONTO_INVALIDO")

    aprovado = len(motivos) == 0

    return {
        **item,
        "aprovado_automatico": aprovado,
        "revisao_manual": not aprovado,
        "motivo_validacao": " | ".join(motivos) if motivos else "OK",
        "tipo_match_validado": tipo_match,
        "quantidade_validada_final": quantidade_validada,
    }


def validar_lote(df: pd.DataFrame):
    registros = []

    for _, row in df.iterrows():
        item = row.to_dict()
        validado = validar_item(item)
        registros.append(validado)

    df_validado = pd.DataFrame(registros)
    df_aprovados = df_validado[df_validado["aprovado_automatico"] == True].copy()
    df_revisao = df_validado[df_validado["aprovado_automatico"] == False].copy()

    return df_validado, df_aprovados, df_revisao


def salvar_validacao(df_aprovados: pd.DataFrame, df_revisao: pd.DataFrame):
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    df_aprovados.to_csv(CAMINHO_APROVADOS, index=False, sep=";", encoding="utf-8-sig")
    df_revisao.to_csv(CAMINHO_REVISAO, index=False, sep=";", encoding="utf-8-sig")

    return {
        "qtd_aprovados": len(df_aprovados),
        "qtd_revisao": len(df_revisao),
        "caminho_aprovados": CAMINHO_APROVADOS,
        "caminho_revisao": CAMINHO_REVISAO,
    }