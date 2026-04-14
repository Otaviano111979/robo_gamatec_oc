# -*- coding: utf-8 -*-
"""
Processa 1 OC por vez a partir de uma pasta de entrada, reaproveitando a
extração + match + consolidação já existentes no projeto, sem tocar no fluxo
atual do agente/GAMATEC.

Saídas por OC:
- planilha enxuta para digitação manual (DESCRICAO, CODIGO, QUANTIDADE)
- resultado processado individual
- debug de extração individual

Comportamento:
- pega apenas 1 arquivo por execução
- gera arquivos individualizados pelo nome da OC
- move a OC para processados/ ou erro/
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from app import etapa_extracao, etapa_matching, etapa_unidade
from config import BASE_DIR


PASTA_OC_ENTRADA = os.path.join(BASE_DIR, "entrada_oc")
PASTA_OC_PROCESSADOS = os.path.join(BASE_DIR, "processados_oc")
PASTA_OC_ERRO = os.path.join(BASE_DIR, "erro_oc")
PASTA_SAIDA_INDIVIDUAL = os.path.join(BASE_DIR, "saida", "ocs_individuais")

EXTENSOES_ACEITAS = {".pdf"}


# -------------------------
# utilitários básicos
# -------------------------
def garantir_pastas() -> None:
    os.makedirs(PASTA_OC_ENTRADA, exist_ok=True)
    os.makedirs(PASTA_OC_PROCESSADOS, exist_ok=True)
    os.makedirs(PASTA_OC_ERRO, exist_ok=True)
    os.makedirs(PASTA_SAIDA_INDIVIDUAL, exist_ok=True)


def limpar_nome_arquivo(texto: str) -> str:
    texto = texto.strip()
    texto = re.sub(r"[\\/:*?\"<>|]+", "_", texto)
    texto = re.sub(r"\s+", "_", texto)
    texto = re.sub(r"_+", "_", texto)
    return texto.strip("_.") or "oc"


def normalizar_codigo(v) -> str:
    if pd.isna(v):
        return ""

    texto = str(v).strip()
    if not texto:
        return ""

    try:
        return str(int(float(texto)))
    except Exception:
        return texto.lstrip("0") or "0"


def escolher_proxima_oc() -> Optional[str]:
    arquivos = []
    for nome in os.listdir(PASTA_OC_ENTRADA):
        caminho = os.path.join(PASTA_OC_ENTRADA, nome)
        if not os.path.isfile(caminho):
            continue
        if Path(nome).suffix.lower() not in EXTENSOES_ACEITAS:
            continue
        arquivos.append(caminho)

    if not arquivos:
        return None

    # 1 por vez: pega o mais antigo da pasta
    arquivos.sort(key=lambda p: os.path.getmtime(p))
    return arquivos[0]


def montar_saida_oc(nome_base: str) -> dict[str, str]:
    pasta_oc = os.path.join(PASTA_SAIDA_INDIVIDUAL, nome_base)
    os.makedirs(pasta_oc, exist_ok=True)

    return {
        "pasta_oc": pasta_oc,
        "debug_extracao": os.path.join(pasta_oc, f"{nome_base}_debug_extracao.txt"),
        "resultado_processado": os.path.join(pasta_oc, f"{nome_base}_resultado_processado.csv"),
        "planilha_csv": os.path.join(pasta_oc, f"{nome_base}_planilha_digitacao_manual.csv"),
        "planilha_xlsx": os.path.join(pasta_oc, f"{nome_base}_planilha_digitacao_manual.xlsx"),
        "resumo_txt": os.path.join(pasta_oc, f"{nome_base}_resumo_processamento.txt"),
    }


# -------------------------
# processamento individual
# -------------------------
def extrair_individual(caminho_oc: str, caminho_debug: str) -> pd.DataFrame:
    if not os.path.exists(caminho_oc):
        raise FileNotFoundError(f"Arquivo da OC não encontrado: {caminho_oc}")

    from extrator_oc import extrair_itens_oc

    itens = extrair_itens_oc(caminho_oc, caminho_debug=caminho_debug)
    if not itens:
        return pd.DataFrame()

    df = pd.DataFrame(itens)
    df["descricao_oc"] = df["descricao_reconstruida"]
    df["quantidade_oc"] = df["quantidade"]
    df["unidade_oc"] = df["unidade_normalizada"]
    df["codigo_oc"] = df["codigo_interno_oc"]
    return df


def gerar_planilha_enxuta_individual(df: pd.DataFrame, caminho_csv: str, caminho_xlsx: str) -> pd.DataFrame:
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
        if quantidade is None or str(quantidade).strip() == "":
            quantidade = item.get("quantidade_oc")

        registros.append({
            "DESCRICAO": descricao,
            "CODIGO": normalizar_codigo(item.get("codigo_krona")),
            "QUANTIDADE": quantidade,
        })

    df_saida = pd.DataFrame(registros, columns=["DESCRICAO", "CODIGO", "QUANTIDADE"])
    df_saida.to_csv(caminho_csv, index=False, sep=";", encoding="utf-8-sig")
    df_saida.to_excel(caminho_xlsx, index=False)
    return df_saida


def salvar_resultado_processado_individual(df: pd.DataFrame, caminho_saida: str) -> None:
    os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)
    df.to_csv(caminho_saida, index=False, sep=";", encoding="utf-8-sig")


def salvar_resumo(caminho_resumo: str, caminho_oc: str, df_extraido: pd.DataFrame, df_final: pd.DataFrame) -> None:
    linhas = []
    linhas.append("PROCESSAMENTO INDIVIDUAL DE OC")
    linhas.append(f"Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    linhas.append(f"Arquivo de entrada: {caminho_oc}")
    linhas.append(f"Itens extraídos: {len(df_extraido)}")
    linhas.append(f"Itens finais: {len(df_final)}")

    if not df_extraido.empty and "status_extracao" in df_extraido.columns:
        linhas.append(f"Resumo status extração: {df_extraido['status_extracao'].value_counts(dropna=False).to_dict()}")

    if not df_final.empty and "tipo_match" in df_final.columns:
        linhas.append(f"Resumo tipo match: {df_final['tipo_match'].value_counts(dropna=False).to_dict()}")

    if not df_final.empty and "tipo_quantidade" in df_final.columns:
        linhas.append(f"Resumo quantidade: {df_final['tipo_quantidade'].value_counts(dropna=False).to_dict()}")

    with open(caminho_resumo, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))


def mover_arquivo(caminho_origem: str, pasta_destino: str) -> str:
    os.makedirs(pasta_destino, exist_ok=True)
    destino = os.path.join(pasta_destino, os.path.basename(caminho_origem))

    if not os.path.exists(destino):
        shutil.move(caminho_origem, destino)
        return destino

    base = Path(caminho_origem).stem
    ext = Path(caminho_origem).suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(pasta_destino, f"{base}_{timestamp}{ext}")
    shutil.move(caminho_origem, destino)
    return destino


def processar_oc(caminho_oc: str) -> dict:
    garantir_pastas()

    nome_base = limpar_nome_arquivo(Path(caminho_oc).stem)
    caminhos = montar_saida_oc(nome_base)

    print("\n==============================")
    print("PROCESSAMENTO INDIVIDUAL DE OC")
    print("==============================")
    print(f"Arquivo selecionado: {caminho_oc}")

    # Etapa 1 - extração individual, sem mexer no fluxo atual
    print("\n[1/4] EXTRAINDO ITENS DA OC...")
    df_extraido = extrair_individual(caminho_oc, caminhos["debug_extracao"])
    if df_extraido.empty:
        raise ValueError("Nenhum item encontrado na extração desta OC.")
    print(f"Itens extraídos: {len(df_extraido)}")
    print(f"Debug extração: {caminhos['debug_extracao']}")

    # Etapa 2 - match já existente
    print("\n[2/4] REALIZANDO MATCH...")
    df_match = etapa_matching(df_extraido)
    print(f"Itens após match: {len(df_match)}")

    # Etapa 3 - consolidação já existente
    print("\n[3/4] CONSOLIDANDO QUANTIDADE...")
    df_final = etapa_unidade(df_match)
    print(f"Itens finais: {len(df_final)}")

    # Etapa 4 - saídas individuais
    print("\n[4/4] GERANDO SAÍDAS INDIVIDUAIS...")
    salvar_resultado_processado_individual(df_final, caminhos["resultado_processado"])
    df_planilha = gerar_planilha_enxuta_individual(
        df_final,
        caminhos["planilha_csv"],
        caminhos["planilha_xlsx"],
    )
    salvar_resumo(caminhos["resumo_txt"], caminho_oc, df_extraido, df_final)

    destino = mover_arquivo(caminho_oc, PASTA_OC_PROCESSADOS)

    print(f"Resultado processado: {caminhos['resultado_processado']}")
    print(f"Planilha CSV: {caminhos['planilha_csv']}")
    print(f"Planilha XLSX: {caminhos['planilha_xlsx']}")
    print(f"Resumo: {caminhos['resumo_txt']}")
    print(f"Arquivo movido para: {destino}")
    print(f"Total de itens na planilha enxuta: {len(df_planilha)}")

    return {
        "arquivo_entrada": caminho_oc,
        "arquivo_processado": destino,
        "pasta_saida_oc": caminhos["pasta_oc"],
        "resultado_processado": caminhos["resultado_processado"],
        "planilha_csv": caminhos["planilha_csv"],
        "planilha_xlsx": caminhos["planilha_xlsx"],
        "resumo_txt": caminhos["resumo_txt"],
        "qtd_itens": len(df_planilha),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Processa 1 OC por vez e gera planilha enxuta individual.")
    parser.add_argument("--arquivo", dest="arquivo", help="Caminho completo de uma OC específica para processar.")
    args = parser.parse_args()

    garantir_pastas()

    caminho_oc = args.arquivo.strip() if args.arquivo else escolher_proxima_oc()

    if not caminho_oc:
        print("\nNenhuma OC encontrada para processamento.")
        print(f"Pasta de entrada: {PASTA_OC_ENTRADA}")
        return

    try:
        processar_oc(caminho_oc)
        print("\nPROCESSAMENTO FINALIZADO COM SUCESSO.")
    except Exception as e:
        print(f"\nERRO NO PROCESSAMENTO: {e}")
        if caminho_oc and os.path.exists(caminho_oc):
            destino = mover_arquivo(caminho_oc, PASTA_OC_ERRO)
            print(f"Arquivo movido para pasta de erro: {destino}")
        raise


if __name__ == "__main__":
    main()
