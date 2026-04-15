# -*- coding: utf-8 -*-
"""
base_brasal_loader.py

Carrega a tabela DE/PARA Brasal → Krona e indexa por código Brasal.
Estrutura do CSV:
    Codigo Krona ; Codigo Brasal ; Unidade ; Descrição ; Valor

Uso:
    from base_brasal_loader import carregar_base_brasal
    indice = carregar_base_brasal()
    # indice["3520"] → {"codigo_krona": "673", "descricao": "ANEL VEDACAO...", ...}
"""

import os
import pandas as pd
from config import BASE_DIR

CAMINHO_BASE_BRASAL = os.path.join(
    BASE_DIR, "dados", "DADOS TABELA BRASAL 01 SEM - 25 (1).csv"
)


def carregar_base_brasal(caminho: str = None) -> dict:
    """
    Lê o CSV da tabela Brasal e retorna um dicionário indexado por código Brasal.
    Retorna {} se o arquivo não existir.
    """
    caminho = caminho or CAMINHO_BASE_BRASAL

    if not os.path.exists(caminho):
        return {}

    try:
        df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", dtype=str)
    except Exception as e:
        print(f"[BRASAL] Erro ao carregar base Brasal: {e}")
        return {}

    # colunas: Codigo Krona | Codigo Brasal | Unidade | Descrição | Valor
    col_krona  = df.columns[0]
    col_brasal = df.columns[1]
    col_unid   = df.columns[2]
    col_desc   = df.columns[3]
    col_valor  = df.columns[4] if len(df.columns) > 4 else None

    indice = {}

    for _, row in df.iterrows():
        cod_brasal = str(row[col_brasal] or "").strip()
        cod_krona  = str(row[col_krona]  or "").strip()

        if not cod_brasal or not cod_krona:
            continue

        # limpa valor monetário: "R$ 0,845" → 0.845
        valor = None
        if col_valor:
            try:
                v = str(row[col_valor] or "").strip()
                v = v.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
                valor = float(v)
            except Exception:
                valor = None

        indice[cod_brasal] = {
            "codigo_krona":  cod_krona,
            "codigo_brasal": cod_brasal,
            "unidade":       str(row[col_unid] or "").strip(),
            "descricao":     str(row[col_desc] or "").strip(),
            "valor_tabela":  valor,
        }

    print(f"[BRASAL] Base carregada: {len(indice)} produtos.")
    return indice
