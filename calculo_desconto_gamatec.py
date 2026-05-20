# -*- coding: utf-8 -*-
import os
import math
import pandas as pd


PASTA_SAIDA = r"C:\robo_gamatec_oc\saida"
CAMINHO_APROVADOS = os.path.join(PASTA_SAIDA, "itens_aprovados_automatico.csv")
CAMINHO_DESCONTOS_GAMATEC = os.path.join(PASTA_SAIDA, "descontos_gamatec.csv")
CAMINHO_DESCONTOS_GAMATEC_XLSX = os.path.join(PASTA_SAIDA, "descontos_gamatec.xlsx")


def normalizar_texto(valor):
    return str(valor or "").strip().upper()


def valor_numerico(v):
    if pd.isna(v):
        return None

    if isinstance(v, (int, float)):
        return float(v)

    texto = str(v).strip()
    if not texto:
        return None

    texto = texto.replace(".", "").replace(",", ".") if texto.count(",") == 1 and texto.count(".") >= 1 else texto
    texto = texto.replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return None


def localizar_coluna_preco_alvo(df):
    """
    Tenta localizar a coluna de preço alvo unitário.
    Prioridade:
    1) nomes prováveis
    2) coluna H (posição 7)
    """
    candidatos = [
        "valor_unitario_oc",
        "valor_unitario",
        "valor_item",
        "preco_item",
        "preco_unitario",
        "preco_alvo",
        "preco_cliente",
        "valor_unitario_cliente",
    ]

    mapa = {str(c).strip().lower(): c for c in df.columns}

    for nome in candidatos:
        if nome in mapa:
            return mapa[nome]

    # fallback: coluna H = índice 7
    if len(df.columns) >= 8:
        return df.columns[7]

    raise ValueError(
        "Não foi possível localizar a coluna de preço alvo unitário "
        "(nem por nome, nem pela coluna H)."
    )


def localizar_coluna_codigo_krona(df):
    candidatos = [
        "codigo_krona",
        "cod_krona",
        "codigo",
    ]

    mapa = {str(c).strip().lower(): c for c in df.columns}

    for nome in candidatos:
        if nome in mapa:
            return mapa[nome]

    raise ValueError("Coluna codigo_krona não encontrada no arquivo de aprovados.")


def localizar_coluna_descricao(df):
    candidatos = [
        "descricao_krona",
        "descricao",
        "descricao_oc",
        "descricao_reconstruida",
    ]

    mapa = {str(c).strip().lower(): c for c in df.columns}

    for nome in candidatos:
        if nome in mapa:
            return mapa[nome]

    return None


def calcular_desconto_percentual(preco_sistema, preco_alvo):
    """
    desconto % = ((preco_sistema - preco_alvo) / preco_sistema) * 100

    Regras:
    - se preço_sistema <= 0 -> inválido
    - se preço_alvo >= preço_sistema -> desconto = 0
    - resultado com 5 casas decimais
    """
    preco_sistema = valor_numerico(preco_sistema)
    preco_alvo = valor_numerico(preco_alvo)

    if preco_sistema is None or preco_alvo is None:
        return None

    if preco_sistema <= 0:
        return None

    if preco_alvo >= preco_sistema:
        return 0.0

    desconto = ((preco_sistema - preco_alvo) / preco_sistema) * 100.0

    if desconto < 0:
        desconto = 0.0

    return round(desconto, 5)


def estimar_preco_final(preco_sistema, desconto_percentual, preco_alvo=None):
    preco_sistema = valor_numerico(preco_sistema)
    desconto_percentual = valor_numerico(desconto_percentual)

    if preco_sistema is None or desconto_percentual is None:
        return None

    preco_final = preco_sistema * (1 - (desconto_percentual / 100.0))
    preco_final = round(preco_final, 5)
    
    # Trava de segurança: nunca maior que o alvo
    if preco_alvo is not None:
        preco_alvo = valor_numerico(preco_alvo)
        if preco_alvo is not None and preco_final > preco_alvo:
            preco_final = preco_alvo
            
    return preco_final


def preparar_descontos_gamatec():
    if not os.path.exists(CAMINHO_APROVADOS):
        raise FileNotFoundError(f"Arquivo não encontrado: {CAMINHO_APROVADOS}")

    df = pd.read_csv(CAMINHO_APROVADOS, sep=";", encoding="utf-8-sig")

    if df.empty:
        raise ValueError("O arquivo itens_aprovados_automatico.csv está vazio.")

    col_codigo = localizar_coluna_codigo_krona(df)
    col_preco_alvo = localizar_coluna_preco_alvo(df)
    col_desc = localizar_coluna_descricao(df)

    registros = []

    for _, row in df.iterrows():
        codigo_krona = str(row.get(col_codigo) or "").strip()
        descricao = row.get(col_desc) if col_desc else ""

        preco_alvo_cliente = valor_numerico(row.get(col_preco_alvo))

        registros.append({
            "codigo_krona": codigo_krona,
            "descricao": descricao,
            "preco_alvo_cliente": preco_alvo_cliente,
            # esses campos serão confirmados/ajustados na tela do GAMATEC
            "preco_sistema": None,
            "desconto_calculado": None,
            "preco_final_estimado": None,
            "status_desconto": "PENDENTE_LEITURA_PRECO_SISTEMA",
        })

    df_saida = pd.DataFrame(registros)

    os.makedirs(PASTA_SAIDA, exist_ok=True)

    df_saida.to_csv(
        CAMINHO_DESCONTOS_GAMATEC,
        index=False,
        sep=";",
        encoding="utf-8-sig"
    )

    df_saida.to_excel(
        CAMINHO_DESCONTOS_GAMATEC_XLSX,
        index=False
    )

    print("\n[DESCONTO GAMATEC]")
    print(f"Arquivo base de descontos CSV: {CAMINHO_DESCONTOS_GAMATEC}")
    print(f"Arquivo base de descontos XLSX: {CAMINHO_DESCONTOS_GAMATEC_XLSX}")
    print(f"Total de itens: {len(df_saida)}")
    print(f"Coluna código Krona usada: {col_codigo}")
    print(f"Coluna preço alvo usada: {col_preco_alvo}")
    print(f"Coluna descrição usada: {col_desc}")

    return df_saida


if __name__ == "__main__":
    preparar_descontos_gamatec()