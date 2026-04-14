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
- tenta mover a OC para processados/ ou erro/
- se o PDF estiver travado por outro processo, NÃO derruba o processamento
  e marca a ocorrência para não reprocessar o mesmo arquivo
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from app import etapa_matching, etapa_unidade
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
        "status_txt": os.path.join(pasta_oc, f"{nome_base}_status_arquivo.txt"),
    }



def oc_ja_processada(caminho_oc: str) -> bool:
    nome_base = limpar_nome_arquivo(Path(caminho_oc).stem)
    caminhos = montar_saida_oc(nome_base)
    return os.path.exists(caminhos["resumo_txt"]) and os.path.exists(caminhos["planilha_csv"])



def escolher_proxima_oc() -> Optional[str]:
    arquivos = []
    for nome in os.listdir(PASTA_OC_ENTRADA):
        caminho = os.path.join(PASTA_OC_ENTRADA, nome)
        if not os.path.isfile(caminho):
            continue
        if Path(nome).suffix.lower() not in EXTENSOES_ACEITAS:
            continue
        if oc_ja_processada(caminho):
            # já gerou saída individual dessa OC; evita reprocessamento se o PDF ficou travado na entrada
            continue
        arquivos.append(caminho)

    if not arquivos:
        return None

    arquivos.sort(key=lambda p: os.path.getmtime(p))
    return arquivos[0]


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
    sep = "-" * 50
    linhas = []

    linhas.append("PROCESSAMENTO INDIVIDUAL DE OC")
    linhas.append(sep)
    linhas.append(f"Data/Hora : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    linhas.append(f"Arquivo   : {caminho_oc}")

    # --------------------------------------------------
    # EXTRAÇÃO
    # --------------------------------------------------
    linhas.append("")
    linhas.append("[ EXTRAÇÃO ]")
    linhas.append(f"  Total extraído  : {len(df_extraido)}")

    if not df_extraido.empty and "status_extracao" in df_extraido.columns:
        contagem = df_extraido["status_extracao"].value_counts(dropna=False).to_dict()
        ok          = contagem.get("ok", 0)
        ressalvas   = contagem.get("ok_com_ressalvas", 0)
        falhou      = contagem.get("falhou", 0)
        duvidoso    = contagem.get("duvidoso", 0)
        linhas.append(f"  OK              : {ok}")
        linhas.append(f"  OK com ressalvas: {ressalvas}")
        linhas.append(f"  Duvidoso        : {duvidoso}")
        linhas.append(f"  Falhou          : {falhou}")

    # --------------------------------------------------
    # MATCH
    # --------------------------------------------------
    linhas.append("")
    linhas.append("[ MATCH ]")
    linhas.append(f"  Total para match: {len(df_final)}")

    if not df_final.empty and "tipo_match" in df_final.columns:
        contagem_match = df_final["tipo_match"].value_counts(dropna=False).to_dict()
        for tipo, qtd in sorted(contagem_match.items(), key=lambda x: -x[1]):
            linhas.append(f"  {tipo:<30}: {qtd}")

    if not df_final.empty and "match_encontrado" in df_final.columns:
        sem_match = int((df_final["match_encontrado"] == False).sum())
        if sem_match > 0:
            linhas.append(f"  ** SEM MATCH (revisão manual): {sem_match} item(ns)")

    # --------------------------------------------------
    # QUANTIDADE
    # --------------------------------------------------
    linhas.append("")
    linhas.append("[ QUANTIDADE ]")

    if not df_final.empty and "tipo_quantidade" in df_final.columns:
        contagem_qtd = df_final["tipo_quantidade"].value_counts(dropna=False).to_dict()
        for tipo, qtd in sorted(contagem_qtd.items(), key=lambda x: -x[1]):
            linhas.append(f"  {tipo:<30}: {qtd}")

        erros_qtd = {k: v for k, v in contagem_qtd.items() if "ERRO" in str(k).upper()}
        if erros_qtd:
            linhas.append(f"  ** Erros de quantidade detectados: {sum(erros_qtd.values())} item(ns)")

    # --------------------------------------------------
    # PLANILHA FINAL
    # --------------------------------------------------
    linhas.append("")
    linhas.append("[ PLANILHA FINAL ]")
    linhas.append(f"  Itens na planilha: {len(df_final)}")

    if not df_final.empty and "CODIGO" in df_final.columns:
        sem_codigo = int(df_final["CODIGO"].isna().sum()) + int((df_final["CODIGO"].astype(str).str.strip() == "").sum())
        if sem_codigo > 0:
            linhas.append(f"  ** Itens sem código Krona: {sem_codigo} (preencher manualmente)")

    linhas.append("")
    linhas.append(sep)

    with open(caminho_resumo, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))



def salvar_status_arquivo(caminho_status: str, caminho_oc: str, status: str, detalhe: str = "") -> None:
    linhas = [
        f"data_hora={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"arquivo_entrada={caminho_oc}",
        f"status={status}",
    ]
    if detalhe:
        linhas.append(f"detalhe={detalhe}")

    with open(caminho_status, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))



def mover_arquivo_seguro(caminho_origem: str, pasta_destino: str, tentativas: int = 5, espera_segundos: float = 1.0) -> tuple[bool, str]:
    os.makedirs(pasta_destino, exist_ok=True)

    if not os.path.exists(caminho_origem):
        return True, "arquivo_origem_inexistente"

    destino = os.path.join(pasta_destino, os.path.basename(caminho_origem))
    if os.path.exists(destino):
        base = Path(caminho_origem).stem
        ext = Path(caminho_origem).suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = os.path.join(pasta_destino, f"{base}_{timestamp}{ext}")

    ultimo_erro = ""
    for tentativa in range(1, tentativas + 1):
        try:
            shutil.move(caminho_origem, destino)
            return True, destino
        except PermissionError as e:
            ultimo_erro = f"tentativa {tentativa}/{tentativas}: {e}"
            time.sleep(espera_segundos)
        except Exception as e:
            return False, str(e)

    return False, ultimo_erro or "falha_ao_mover_arquivo"



def processar_oc(caminho_oc: str) -> dict:
    garantir_pastas()

    nome_base = limpar_nome_arquivo(Path(caminho_oc).stem)
    caminhos = montar_saida_oc(nome_base)

    print("\n==============================")
    print("PROCESSAMENTO INDIVIDUAL DE OC")
    print("==============================")
    print(f"Arquivo selecionado: {caminho_oc}")

    print("\n[1/4] EXTRAINDO ITENS DA OC...")
    df_extraido = extrair_individual(caminho_oc, caminhos["debug_extracao"])
    if df_extraido.empty:
        raise ValueError("Nenhum item encontrado na extração desta OC.")
    print(f"Itens extraídos: {len(df_extraido)}")
    print(f"Debug extração: {caminhos['debug_extracao']}")

    # filtra itens que falharam na extracao — eles nao tem descricao nem quantidade
    # e causariam matches incorretos se entrassem no pipeline
    if "status_extracao" in df_extraido.columns:
        df_falhou = df_extraido[df_extraido["status_extracao"] == "falhou"]
        df_para_match = df_extraido[df_extraido["status_extracao"] != "falhou"].copy()

        if not df_falhou.empty:
            print(f"Itens ignorados (falhou na extração): {len(df_falhou)}")

        if df_para_match.empty:
            raise ValueError("Todos os itens falharam na extração. Nenhum item válido para processar.")
    else:
        df_para_match = df_extraido.copy()

    print(f"Itens válidos para match: {len(df_para_match)}")

    print("\n[2/4] REALIZANDO MATCH...")
    df_match = etapa_matching(df_para_match)
    print(f"Itens após match: {len(df_match)}")

    print("\n[3/4] CONSOLIDANDO QUANTIDADE...")
    df_final = etapa_unidade(df_match)
    print(f"Itens finais: {len(df_final)}")

    print("\n[4/4] GERANDO SAÍDAS INDIVIDUAIS...")
    salvar_resultado_processado_individual(df_final, caminhos["resultado_processado"])
    df_planilha = gerar_planilha_enxuta_individual(
        df_final,
        caminhos["planilha_csv"],
        caminhos["planilha_xlsx"],
    )
    salvar_resumo(caminhos["resumo_txt"], caminho_oc, df_extraido, df_final)

    move_ok, destino_ou_erro = mover_arquivo_seguro(caminho_oc, PASTA_OC_PROCESSADOS)
    if move_ok:
        salvar_status_arquivo(caminhos["status_txt"], caminho_oc, "MOVIDO_PROCESSADOS", destino_ou_erro)
    else:
        salvar_status_arquivo(caminhos["status_txt"], caminho_oc, "PROCESSADO_PDF_NAO_MOVIDO", destino_ou_erro)

    print(f"Resultado processado: {caminhos['resultado_processado']}")
    print(f"Planilha CSV: {caminhos['planilha_csv']}")
    print(f"Planilha XLSX: {caminhos['planilha_xlsx']}")
    print(f"Resumo: {caminhos['resumo_txt']}")
    if move_ok:
        print(f"Arquivo movido para: {destino_ou_erro}")
    else:
        print("AVISO: PDF processado, mas não foi possível mover para processados.")
        print(f"Motivo: {destino_ou_erro}")
        print(f"Status gravado em: {caminhos['status_txt']}")
    print(f"Total de itens na planilha enxuta: {len(df_planilha)}")

    return {
        "arquivo_entrada": caminho_oc,
        "arquivo_processado": destino_ou_erro if move_ok else "NAO_MOVIDO",
        "pasta_saida_oc": caminhos["pasta_oc"],
        "resultado_processado": caminhos["resultado_processado"],
        "planilha_csv": caminhos["planilha_csv"],
        "planilha_xlsx": caminhos["planilha_xlsx"],
        "resumo_txt": caminhos["resumo_txt"],
        "status_txt": caminhos["status_txt"],
        "qtd_itens": len(df_planilha),
        "pdf_movido": move_ok,
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
            move_ok, destino_ou_erro = mover_arquivo_seguro(caminho_oc, PASTA_OC_ERRO)
            if move_ok:
                print(f"Arquivo movido para pasta de erro: {destino_ou_erro}")
            else:
                print("AVISO: não foi possível mover o PDF para a pasta de erro.")
                print(f"Motivo: {destino_ou_erro}")
        raise


if __name__ == "__main__":
    main()
