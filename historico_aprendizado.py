import os
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher

import pandas as pd


CAMINHO_DB = r"C:\robo_gamatec_oc\dados\historico_aprendizado.db"


def garantir_pasta():
    os.makedirs(os.path.dirname(CAMINHO_DB), exist_ok=True)


def conectar():
    garantir_pasta()
    return sqlite3.connect(CAMINHO_DB)


def inicializar_banco():
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historico_validacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id TEXT,
                cliente_nome TEXT,
                descricao_oc_original TEXT,
                descricao_oc_normalizada TEXT,
                codigo_krona_aprovado TEXT,
                descricao_krona_aprovada TEXT,
                unidade_venda_krona TEXT,
                quantidade_convertida REAL,
                desconto_percentual REAL,
                tipo_match_final TEXT,
                usuario_validou TEXT,
                observacoes TEXT,
                data_validacao TEXT
            )
        """)
        conn.commit()


def normalizar_texto(texto):
    return str(texto or "").strip().upper()


def texto_ratio(a, b):
    a = normalizar_texto(a)
    b = normalizar_texto(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def registrar_validacao_manual(
    cliente_id,
    cliente_nome,
    descricao_oc_original,
    descricao_oc_normalizada,
    codigo_krona_aprovado,
    descricao_krona_aprovada,
    unidade_venda_krona=None,
    quantidade_convertida=None,
    desconto_percentual=None,
    tipo_match_final="MANUAL",
    usuario_validou=None,
    observacoes=None,
):
    inicializar_banco()

    with conectar() as conn:
        conn.execute("""
            INSERT INTO historico_validacoes (
                cliente_id,
                cliente_nome,
                descricao_oc_original,
                descricao_oc_normalizada,
                codigo_krona_aprovado,
                descricao_krona_aprovada,
                unidade_venda_krona,
                quantidade_convertida,
                desconto_percentual,
                tipo_match_final,
                usuario_validou,
                observacoes,
                data_validacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(cliente_id or "").strip() or None,
            str(cliente_nome or "").strip() or None,
            str(descricao_oc_original or "").strip() or None,
            str(descricao_oc_normalizada or "").strip() or None,
            str(codigo_krona_aprovado or "").strip() or None,
            str(descricao_krona_aprovada or "").strip() or None,
            str(unidade_venda_krona or "").strip() or None,
            float(quantidade_convertida) if quantidade_convertida is not None else None,
            float(desconto_percentual) if desconto_percentual is not None else None,
            str(tipo_match_final or "").strip() or None,
            str(usuario_validou or "").strip() or None,
            str(observacoes or "").strip() or None,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        conn.commit()


def carregar_historico(cliente_id=None, cliente_nome=None):
    inicializar_banco()

    query = "SELECT * FROM historico_validacoes WHERE 1=1"
    params = []

    if cliente_id:
        query += " AND cliente_id = ?"
        params.append(str(cliente_id).strip())

    if cliente_nome:
        query += " AND cliente_nome = ?"
        params.append(str(cliente_nome).strip())

    query += " ORDER BY data_validacao DESC"

    with conectar() as conn:
        df = pd.read_sql_query(query, conn, params=params)

    return df


def buscar_sugestoes_historico(
    descricao_oc,
    descricao_oc_normalizada=None,
    cliente_id=None,
    cliente_nome=None,
    score_minimo=0.82,
    top_n=5,
):
    """
    Procura no histórico validado itens parecidos, priorizando o mesmo cliente.
    """
    inicializar_banco()

    descricao_base = descricao_oc_normalizada or descricao_oc or ""
    descricao_base = normalizar_texto(descricao_base)

    if not descricao_base:
        return pd.DataFrame()

    # 1. tenta histórico do cliente
    df_cliente = carregar_historico(cliente_id=cliente_id, cliente_nome=cliente_nome)

    resultados = []

    if not df_cliente.empty:
        for _, row in df_cliente.iterrows():
            score = texto_ratio(descricao_base, row.get("descricao_oc_normalizada"))
            if score >= score_minimo:
                resultados.append({
                    **row.to_dict(),
                    "score_historico": round(score, 4),
                    "origem_historico": "CLIENTE"
                })

    # 2. fallback global
    if not resultados:
        df_global = carregar_historico()

        for _, row in df_global.iterrows():
            score = texto_ratio(descricao_base, row.get("descricao_oc_normalizada"))
            if score >= score_minimo:
                resultados.append({
                    **row.to_dict(),
                    "score_historico": round(score, 4),
                    "origem_historico": "GLOBAL"
                })

    if not resultados:
        return pd.DataFrame()

    df_resultado = pd.DataFrame(resultados).sort_values(
        by=["origem_historico", "score_historico", "data_validacao"],
        ascending=[True, False, False]
    ).reset_index(drop=True)

    return df_resultado.head(top_n).copy()


def obter_melhor_sugestao_historico(
    descricao_oc,
    descricao_oc_normalizada=None,
    cliente_id=None,
    cliente_nome=None,
    score_minimo=0.90,
):
    df = buscar_sugestoes_historico(
        descricao_oc=descricao_oc,
        descricao_oc_normalizada=descricao_oc_normalizada,
        cliente_id=cliente_id,
        cliente_nome=cliente_nome,
        score_minimo=score_minimo,
        top_n=1,
    )

    if df.empty:
        return None

    return df.iloc[0].to_dict()


if __name__ == "__main__":
    inicializar_banco()

    print("Banco inicializado em:")
    print(CAMINHO_DB)

    # exemplo opcional de teste
    exemplo = obter_melhor_sugestao_historico(
        descricao_oc="Tubo PVC Esgoto Primario 75mm 6m",
        descricao_oc_normalizada="TUBO PVC ESGOTO PRIMARIO 75MM 6M",
        cliente_id="CLIENTE_TESTE"
    )

    print("\nMelhor sugestão encontrada:")
    print(exemplo)