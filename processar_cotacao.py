# -*- coding: utf-8 -*-
"""
processar_cotacao.py

Fluxo de Cotações de Preços — separado do fluxo de OC.

Cotação chega SEM preço de propósito: o objetivo é gerar a planilha
(DESCRICAO, CODIGO, QUANTIDADE) para subir no sistema e lá recolher o preço.
O match serve apenas para descobrir o código; não há comparação de preços,
não há aviso de preço divergente e não há aviso de "preço não confirmado".

Não toca no pipeline de OC: importa as mesmas etapas (matching e unidade)
e recusa qualquer documento classificado como OC.
"""

import argparse
import os

import pandas as pd

from app import etapa_matching, etapa_unidade
from config import BASE_DIR
from extracao_oc.classificador_documento import (
    COTACAO, UI, classificar_documento, tipo_definido_manualmente,
)
from extracao_oc.extrator_cotacao import extrair_cotacao
from processar_oc_individual_pasta_ajustado import (
    gerar_planilha_enxuta_individual,
    limpar_nome_arquivo,
    mover_arquivo_seguro,
    texto_limpo,
)


PASTA_SAIDA_COTACAO = os.path.join(BASE_DIR, "saida", "cotacoes_individuais")
PASTA_COTACAO_PROCESSADOS = os.path.join(BASE_DIR, "processados_cotacao")


def montar_saida_cotacao(nome_base: str) -> dict:
    pasta = os.path.join(PASTA_SAIDA_COTACAO, nome_base)
    os.makedirs(pasta, exist_ok=True)
    return {
        "pasta": pasta,
        "planilha_csv": os.path.join(pasta, f"{nome_base}_planilha_cotacao.csv"),
        "planilha_xlsx": os.path.join(pasta, f"{nome_base}_planilha_cotacao.xlsx"),
        "resumo_txt": os.path.join(pasta, f"{nome_base}_resumo_cotacao.txt"),
    }


def _df_de_itens(itens: list) -> pd.DataFrame:
    df = pd.DataFrame(itens)
    df["descricao_oc"] = df["descricao"]
    df["quantidade_oc"] = df["quantidade"]
    df["unidade_oc"] = df["unidade"]
    df["codigo_oc"] = df["codigo_cliente"]
    df["preco_unit"] = None  # cotação não traz preço; match não compara preço
    df["idx_item"] = range(1, len(df) + 1)
    return df


def _escrever_resumo(caminho: str, extra: dict, df_final: pd.DataFrame, nome_arquivo: str) -> None:
    total = len(df_final)
    com_match = int(df_final["match_encontrado"].sum()) if "match_encontrado" in df_final else 0
    linhas = [
        "COTAÇÃO DE PREÇOS — RESUMO DO PROCESSAMENTO",
        f"Arquivo: {nome_arquivo}",
        f"Cliente: {extra.get('cliente') or '(não identificado)'}",
        f"Nº cotação: {extra.get('numero_oc') or '(não encontrado)'}",
        f"Data: {extra.get('data') or '(não encontrada)'}",
        f"Layout: {extra.get('layout') or '(não detectado)'}",
        f"Páginas: {extra.get('paginas')}",
        "",
        f"Itens extraídos: {total}",
        f"Itens com código encontrado: {com_match}",
        f"Itens sem código: {total - com_match}",
        "",
        "Planilha gerada SEM preços — o preço é recolhido no sistema.",
    ]
    sem_quantidade = int(extra.get("sem_quantidade") or 0)
    if sem_quantidade:
        linhas.insert(11, f"Linhas sem quantidade (não incluídas): {sem_quantidade}")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


def processar_cotacao_individual(caminho: str, cliente_tabela: str = None) -> dict:
    nome_arquivo = os.path.basename(caminho)
    classificacao = classificar_documento(caminho)
    tipo = tipo_definido_manualmente(nome_arquivo) or classificacao.tipo
    if tipo != COTACAO:
        motivo = "CLASSIFICACAO_PENDENTE" if tipo == UI else "NAO_E_COTACAO"
        return {
            "ok": False,
            "motivo": motivo,
            "classificacao": tipo,
            "detalhe": classificacao.motivo,
            "itens": 0,
        }

    if classificacao.sem_texto:
        return {
            "ok": False,
            "motivo": "SEM_TEXTO",
            "classificacao": tipo,
            "detalhe": "PDF digitalizado (só imagem) — precisa de OCR para extrair os itens",
            "itens": 0,
        }

    extra = extrair_cotacao(caminho)
    if not extra["ok"]:
        return {"ok": False, "motivo": "ERRO_EXTRACAO", "detalhe": extra.get("erro"), "itens": 0}
    if not extra["itens"]:
        return {
            "ok": False,
            "motivo": "LAYOUT_NAO_SUPORTADO",
            "detalhe": f"layout detetado: {extra.get('layout') or 'nenhum'}",
            "itens": 0,
        }

    nome_base = limpar_nome_arquivo(os.path.splitext(nome_arquivo)[0])
    caminhos = montar_saida_cotacao(nome_base)

    df = _df_de_itens(extra["itens"])
    df_match = etapa_matching(df, cliente_tabela=cliente_tabela)
    df_final = etapa_unidade(df_match)

    gerar_planilha_enxuta_individual(
        df_final,
        caminhos["planilha_csv"],
        caminhos["planilha_xlsx"],
        modo_cotacao=True,
    )
    _escrever_resumo(caminhos["resumo_txt"], extra, df_final, nome_arquivo)

    return {
        "ok": True,
        "motivo": "",
        "classificacao": tipo,
        "layout": extra.get("layout"),
        "cliente": extra.get("cliente"),
        "numero": extra.get("numero_oc"),
        "itens": len(df_final),
        "com_match": int(df_final["match_encontrado"].sum()) if "match_encontrado" in df_final else 0,
        "planilha_csv": caminhos["planilha_csv"],
        "planilha_xlsx": caminhos["planilha_xlsx"],
        "resumo_txt": caminhos["resumo_txt"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Processa 1 cotação por vez e gera planilha enxuta sem preço.")
    parser.add_argument("--arquivo", dest="arquivo", required=True, help="Caminho completo do PDF da cotação.")
    parser.add_argument("--cliente", dest="cliente", default=None, help="Tabela de preço do cliente (opcional).")
    args = parser.parse_args()

    os.makedirs(PASTA_SAIDA_COTACAO, exist_ok=True)
    os.makedirs(PASTA_COTACAO_PROCESSADOS, exist_ok=True)

    caminho = os.path.abspath(args.arquivo.strip())
    resultado = processar_cotacao_individual(caminho, cliente_tabela=args.cliente)

    if not resultado["ok"]:
        print(f"COTACAO NAO PROCESSADA: {resultado['motivo']}")
        if resultado.get("detalhe"):
            print(f"Detalhe: {resultado['detalhe']}")
        raise SystemExit(2)

    move_ok, destino_ou_erro = mover_arquivo_seguro(caminho, PASTA_COTACAO_PROCESSADOS)
    if move_ok:
        print(f"Arquivo movido para: {destino_ou_erro}")
    else:
        print(f"AVISO: PDF processado, mas nao foi possivel mover: {destino_ou_erro}")

    print(f"Layout: {resultado['layout']}")
    print(f"Itens na planilha: {resultado['itens']}")
    print(f"Planilha CSV: {resultado['planilha_csv']}")
    print(f"Planilha XLSX: {resultado['planilha_xlsx']}")
    print(f"Resumo: {resultado['resumo_txt']}")


if __name__ == "__main__":
    main()
