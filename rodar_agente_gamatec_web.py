# -*- coding: utf-8 -*-
"""
rodar_agente_gamatec_web.py

Versao NAO INTERATIVA da automacao — chamada pelo dashboard via subprocess.
Nao pede nenhum input do usuario. Carrega calibracao do JSON salvo previamente.

Prerequisito:
    Executar calibrar_gamatec.py uma vez antes de usar este script.

Uso pelo dashboard:
    python rodar_agente_gamatec_web.py --planilha <caminho_planilha> --oc <nome_oc>

Saidas:
    - Log em tempo real via stdout (capturado pelo dashboard)
    - JSON de status em saida/ocs_individuais/<nome_oc>/automacao_status.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from config import BASE_DIR


PASTA_SAIDA = os.path.join(BASE_DIR, "saida")
ARQUIVO_CALIBRACAO = os.path.join(PASTA_SAIDA, "calibracao_gamatec.json")


def log(msg: str):
    print(msg, flush=True)


def salvar_status(caminho_status: str, dados: Dict[str, Any]):
    os.makedirs(os.path.dirname(caminho_status), exist_ok=True)
    with open(caminho_status, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def nome_base_oc(nome_oc: str) -> str:
    base = os.path.splitext(nome_oc)[0]
    return base.replace(" ", "_")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--planilha", required=False, help="Caminho da planilha XLSX da OC")
    parser.add_argument("--oc", required=False, help="Nome do arquivo da OC")
    args = parser.parse_args()

    nome_oc = args.oc or "oc_desconhecida"
    pasta_oc = os.path.join(PASTA_SAIDA, "ocs_individuais", nome_base_oc(nome_oc))
    caminho_status = os.path.join(pasta_oc, "automacao_status.json")

    os.makedirs(pasta_oc, exist_ok=True)

    # salva status inicial
    salvar_status(caminho_status, {
        "estado": "iniciando",
        "oc": nome_oc,
        "inicio": time.strftime("%Y-%m-%d %H:%M:%S"),
        "itens": []
    })

    log("=== AUTOMAÇÃO GAMATEC — MODO WEB ===")
    log(f"OC: {nome_oc}")

    # =========================
    # VERIFICAR CALIBRAÇÃO
    # =========================
    if not os.path.exists(ARQUIVO_CALIBRACAO):
        msg = (
            f"ERRO: Arquivo de calibracao nao encontrado: {ARQUIVO_CALIBRACAO}\n"
            "Execute calibrar_gamatec.py uma vez antes de usar a automacao.\n"
            "No terminal: python calibrar_gamatec.py"
        )
        log(msg)
        salvar_status(caminho_status, {
            "estado": "erro",
            "oc": nome_oc,
            "erro": "calibracao_nao_encontrada",
            "mensagem": msg,
            "itens": []
        })
        sys.exit(1)

    log(f"[OK] Calibracao encontrada: {ARQUIVO_CALIBRACAO}")

    # =========================
    # CARREGAR CALIBRAÇÃO
    # =========================
    try:
        with open(ARQUIVO_CALIBRACAO, "r", encoding="utf-8") as f:
            calibracao = json.load(f)
        log(f"[OK] Calibracao carregada com sucesso.")
    except Exception as e:
        msg = f"ERRO ao carregar calibracao: {e}"
        log(msg)
        salvar_status(caminho_status, {
            "estado": "erro",
            "oc": nome_oc,
            "erro": "calibracao_invalida",
            "mensagem": msg,
            "itens": []
        })
        sys.exit(1)

    # =========================
    # CARREGAR PLANO DE EXECUÇÃO
    # =========================
    log("[ETAPA 1] Carregando plano de execucao...")

    try:
        from planejador_execucao_gamatec import carregar_plano_execucao

        # prioriza planilha individual da OC se fornecida
        caminho_planilha = args.planilha
        if caminho_planilha and os.path.exists(caminho_planilha):
            log(f"[PLANO] Usando planilha da OC: {caminho_planilha}")
            plano = carregar_plano_execucao(caminho_planilha)
        else:
            from planejador_execucao_gamatec import localizar_arquivo_planejamento
            caminho_planilha = localizar_arquivo_planejamento()
            log(f"[PLANO] Usando arquivo padrao: {caminho_planilha}")
            plano = carregar_plano_execucao(caminho_planilha)

        log(f"[PLANO] Total de itens: {len(plano)}")

    except Exception as e:
        msg = f"ERRO ao carregar plano de execucao: {e}"
        log(msg)
        salvar_status(caminho_status, {
            "estado": "erro",
            "oc": nome_oc,
            "erro": "plano_nao_carregado",
            "mensagem": msg,
            "itens": []
        })
        sys.exit(1)

    salvar_status(caminho_status, {
        "estado": "executando",
        "oc": nome_oc,
        "total_itens": len(plano),
        "itens_processados": 0,
        "itens": []
    })

    # =========================
    # INICIALIZAR MÓDULOS
    # =========================
    log("[ETAPA 2] Inicializando modulos de automacao...")

    try:
        from percepcao_gamatec import PercepcaoGamatec
        from agente_gamatec import AgenteGamatec
        from orquestrador_agente_gamatec import OrquestradorAgenteGamatec

        percepcao = PercepcaoGamatec(
            calibracao=calibracao,
            debug=False,
            salvar_crops_debug=False
        )

        agente = AgenteGamatec(
            tolerancia_preco=0.02,
            exigir_preco_final=True,
            exigir_ult_preco=False,
            debug=False,
            pasta_debug=pasta_oc
        )

        orquestrador = OrquestradorAgenteGamatec(
            calibracao=calibracao,
            debug=False,
            pasta_debug=pasta_oc,
            quantidade_linhas_visiveis=6,
            max_scrolls_por_item=20,
            max_releituras_por_item=5,
            pausa_curta=0.15,
            pausa_media=0.35,
            pausa_longa=0.60,
        )

        log("[OK] Modulos inicializados.")

    except Exception as e:
        msg = f"ERRO ao inicializar modulos: {e}"
        log(msg)
        salvar_status(caminho_status, {
            "estado": "erro",
            "oc": nome_oc,
            "erro": "modulos_nao_inicializados",
            "mensagem": msg,
            "itens": []
        })
        sys.exit(1)

    # =========================
    # AGUARDAR 3 SEGUNDOS
    # para o operador focar a tela do GAMATEC
    # =========================
    log("[ETAPA 3] Iniciando em 3 segundos...")
    log("          Certifique-se que o GAMATEC esta na tela Recalculo de Mix!")
    for i in range(3, 0, -1):
        log(f"          {i}...")
        time.sleep(1)

    # =========================
    # EXECUTAR AUTOMAÇÃO
    # =========================
    log("[ETAPA 4] Iniciando automacao...")

    resultados = []

    try:
        for idx, item_planejado in enumerate(plano):
            codigo = item_planejado.get("codigo_krona", "?")
            descricao = item_planejado.get("descricao_krona", "")
            preco_alvo = item_planejado.get("preco_alvo")

            log(f"\n[ITEM {idx+1}/{len(plano)}] Codigo: {codigo} | {descricao[:40]}")

            try:
                resultado = orquestrador.processar_item(
                    item_planejado=item_planejado,
                    percepcao=percepcao,
                    agente=agente
                )

                status_item = asdict(resultado) if hasattr(resultado, '__dataclass_fields__') else resultado

                log(f"  Status: {status_item.get('status', '?')}")
                log(f"  Preco alvo: {preco_alvo} | Final lido: {status_item.get('preco_final_lido', '?')}")
                log(f"  Desconto aplicado: {status_item.get('desconto_aplicado', '?')}%")

                resultados.append({
                    "codigo": codigo,
                    "descricao": descricao[:60],
                    "preco_alvo": preco_alvo,
                    "preco_final": status_item.get("preco_final_lido"),
                    "desconto": status_item.get("desconto_aplicado"),
                    "status": status_item.get("status", "DESCONHECIDO"),
                    "motivo": status_item.get("motivo", ""),
                })

            except Exception as e:
                log(f"  ERRO no item {codigo}: {e}")
                resultados.append({
                    "codigo": codigo,
                    "descricao": descricao[:60],
                    "preco_alvo": preco_alvo,
                    "preco_final": None,
                    "desconto": None,
                    "status": "ERRO",
                    "motivo": str(e),
                })

            # atualiza status em tempo real a cada item
            salvar_status(caminho_status, {
                "estado": "executando",
                "oc": nome_oc,
                "total_itens": len(plano),
                "itens_processados": idx + 1,
                "itens": resultados
            })

    except Exception as e:
        msg = f"ERRO durante execucao: {e}"
        log(msg)
        salvar_status(caminho_status, {
            "estado": "erro",
            "oc": nome_oc,
            "erro": "erro_durante_execucao",
            "mensagem": msg,
            "itens": resultados
        })
        sys.exit(1)

    # =========================
    # RESUMO FINAL
    # =========================
    total = len(resultados)
    ok = sum(1 for r in resultados if r["status"] in ("SUCESSO_VALIDADO", "ITEM_OK_VALIDAR_E_SEGUIR"))
    revisar = total - ok

    log(f"\n=== AUTOMAÇÃO CONCLUÍDA ===")
    log(f"Total de itens : {total}")
    log(f"OK             : {ok}")
    log(f"Revisar        : {revisar}")

    salvar_status(caminho_status, {
        "estado": "concluido",
        "oc": nome_oc,
        "fim": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_itens": total,
        "itens_ok": ok,
        "itens_revisar": revisar,
        "itens": resultados
    })

    log(f"Status salvo em: {caminho_status}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n[INTERROMPIDO PELO USUARIO]")
        sys.exit(0)
    except Exception as e:
        log(f"\n[ERRO FATAL] {type(e).__name__}: {e}")
        sys.exit(1)
