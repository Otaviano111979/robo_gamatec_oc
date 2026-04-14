from __future__ import annotations

import os
import re
from typing import List, Dict, Any, Optional

import pandas as pd


PASTA_SAIDA = r"C:\robo_gamatec_oc\saida"

CAMINHOS_CANDIDATOS = [
    os.path.join(PASTA_SAIDA, "descontos_gamatec.csv"),
    os.path.join(PASTA_SAIDA, "itens_aprovados_automatico.csv"),
    os.path.join(PASTA_SAIDA, "resultado_validado.csv"),
    os.path.join(PASTA_SAIDA, "planilha_gamatec.csv"),
    os.path.join(PASTA_SAIDA, "resultado_processado.csv"),
]


def normalizar_codigo(codigo: Any) -> str:
    if codigo is None:
        return ""

    texto = str(codigo).strip()
    texto = re.sub(r"\D", "", texto)

    if not texto:
        return ""

    return texto.lstrip("0") or "0"


def normalizar_nome_coluna(nome: str) -> str:
    return (
        str(nome or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


def localizar_coluna(df: pd.DataFrame, candidatas: List[str]) -> Optional[str]:
    mapa = {normalizar_nome_coluna(c): c for c in df.columns}

    for cand in candidatas:
        chave = normalizar_nome_coluna(cand)
        if chave in mapa:
            return mapa[chave]

    return None


def localizar_arquivo_planejamento() -> str:
    for caminho in CAMINHOS_CANDIDATOS:
        if os.path.exists(caminho):
            return caminho

    raise FileNotFoundError(
        "Nenhum arquivo de planejamento encontrado em:\n" +
        "\n".join(CAMINHOS_CANDIDATOS)
    )


def ler_csv_robusto(caminho: str) -> pd.DataFrame:
    tentativas = [
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "utf-8"},
        {"sep": ";", "encoding": "latin1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ",", "encoding": "utf-8"},
        {"sep": ",", "encoding": "latin1"},
    ]

    ultimo_erro = None

    for cfg in tentativas:
        try:
            df = pd.read_csv(caminho, dtype=str, **cfg)
            if len(df.columns) >= 1:
                return df
        except Exception as e:
            ultimo_erro = e

    raise ValueError(f"Não foi possível ler o arquivo {caminho}. Erro: {ultimo_erro}")


def valor_float(v: Any) -> Optional[float]:
    if v is None:
        return None

    texto = str(v).strip()
    if not texto:
        return None

    texto = texto.replace("R$", "").replace("r$", "").replace(" ", "")
    texto = re.sub(r"[^0-9,.\-]", "", texto)

    if not texto:
        return None

    if "," in texto:
        if texto.count(",") > 1:
            partes = texto.split(",")
            texto = "".join(partes[:-1]) + "," + partes[-1]
        if "." in texto:
            texto = texto.replace(".", "")
        texto = texto.replace(",", ".")
    else:
        if texto.count(".") > 1:
            partes = texto.split(".")
            texto = "".join(partes[:-1]) + "." + partes[-1]

    try:
        return float(texto)
    except Exception:
        return None


def carregar_plano_execucao(caminho: Optional[str] = None) -> List[Dict[str, Any]]:
    if caminho is None:
        caminho = localizar_arquivo_planejamento()

    df = ler_csv_robusto(caminho)

    if df.empty:
        raise ValueError(f"Arquivo de planejamento vazio: {caminho}")

    col_codigo = localizar_coluna(df, [
        "codigo_krona",
        "codigo",
        "cod_krona",
        "codigo produto",
        "código",
        "código_krona",
    ])

    col_descricao = localizar_coluna(df, [
        "descricao_krona",
        "descricao",
        "descricao_oc",
        "descricao_reconstruida",
        "descrição",
    ])

    col_preco_alvo = localizar_coluna(df, [
        "preco_alvo_cliente",
        "preco_alvo",
        "preco_cliente",
        "valor_unitario",
        "valor_unitario_oc",
        "preco_unitario",
    ])

    col_desconto = localizar_coluna(df, [
        "desconto_calculado",
        "percentual_desconto",
        "desconto",
        "%_desc",
        "%desc",
    ])

    col_quantidade = localizar_coluna(df, [
        "quantidade_consolidada",
        "quantidade",
        "qtde",
    ])

    if not col_codigo:
        raise ValueError(
            f"Coluna de código Krona não encontrada. Colunas disponíveis: {list(df.columns)}"
        )

    plano: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        codigo = normalizar_codigo(row.get(col_codigo))
        if not codigo:
            continue

        descricao = str(row.get(col_descricao) or "").strip() if col_descricao else ""
        preco_alvo = valor_float(row.get(col_preco_alvo)) if col_preco_alvo else None
        desconto_calculado = valor_float(row.get(col_desconto)) if col_desconto else None
        quantidade = valor_float(row.get(col_quantidade)) if col_quantidade else None

        plano.append({
            "codigo_krona": codigo,
            "descricao_krona": descricao,
            "preco_alvo": preco_alvo,
            "desconto_calculado": desconto_calculado,
            "quantidade": quantidade,
            "origem_arquivo": caminho,
        })

    if not plano:
        raise ValueError("Nenhum item válido foi carregado para o plano de execução.")

    return plano


if __name__ == "__main__":
    caminho = localizar_arquivo_planejamento()
    plano = carregar_plano_execucao(caminho)

    print("\n[PLANEJADOR EXECUÇÃO GAMATEC]")
    print(f"Arquivo usado: {caminho}")
    print(f"Total de itens: {len(plano)}")

    print("\n[PRIMEIROS 10 ITENS]")
    for item in plano[:10]:
        print(item)