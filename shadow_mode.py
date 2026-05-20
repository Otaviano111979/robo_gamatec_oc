# -*- coding: utf-8 -*-
"""
shadow_mode.py — Vortex Shadow Mode

Executa o motor semantico em paralelo ao motor atual.
Resultado apenas logado em saida/shadow_mode.jsonl.
Nunca afeta o resultado que vai para o cliente.
"""

import json
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("vortex.shadow")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHADOW_LOG_PATH   = os.path.join(_BASE_DIR, "saida", "shadow_mode.jsonl")
SHADOW_ERROR_PATH = os.path.join(_BASE_DIR, "saida", "shadow_errors.log")


def _rodar_shadow(item: dict, resultado_atual: dict, base_krona):
    try:
        from motor_semantico import obter_motor

        motor = obter_motor()
        if not motor.pronto:
            motor.indexar(base_krona)

        descricao = (
            item.get("descricao_oc")
            or item.get("descricao_reconstruida")
            or item.get("descricao_original")
            or ""
        )
        # limpa quebras de linha e espacos extras
        descricao = str(descricao).replace("\n", " ").replace("\r", " ").strip()
        if not descricao:
            return

        t0 = time.time()
        resultado_novo = motor.match(descricao)
        elapsed_ms = round((time.time() - t0) * 1000, 1)

        cod_atual = str(resultado_atual.get("codigo_krona") or "")
        cod_novo  = str(resultado_novo.get("codigo_krona") or "")
        concordam = cod_atual == cod_novo and cod_atual != ""

        registro = {
            "ts":           time.strftime("%Y-%m-%d %H:%M:%S"),
            "descricao_oc": descricao[:120],
            "motor_atual": {
                "codigo":     cod_atual,
                "tipo_match": resultado_atual.get("tipo_match"),
                "score":      resultado_atual.get("score_total"),
            },
            "motor_novo": {
                "codigo":     cod_novo,
                "tipo_match": resultado_novo.get("tipo_match"),
                "score":      resultado_novo.get("score_total"),
            },
            "concordam":  concordam,
            "elapsed_ms": elapsed_ms,
        }

        os.makedirs(os.path.dirname(SHADOW_LOG_PATH), exist_ok=True)
        with open(SHADOW_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

        status = "OK" if concordam else "DIVERGE"
        logger.debug(f"[SHADOW] {status} | '{descricao[:40]}' | atual={cod_atual} novo={cod_novo}")

    except Exception as e:
        import traceback
        try:
            os.makedirs(os.path.dirname(SHADOW_ERROR_PATH), exist_ok=True)
            with open(SHADOW_ERROR_PATH, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERRO: {e}\n")
                f.write(traceback.format_exc())
                f.write("\n---\n")
        except Exception:
            pass
        logger.debug(f"[SHADOW] Erro (nao critico): {e}")


def registrar_shadow(item: dict, resultado_atual: dict, base_krona):
    """
    Dispara motor novo em thread separada.
    Nao bloqueia. Nao afeta resultado que vai para o cliente.
    Ativa apenas para itens sem tabela.
    """
    tipo = resultado_atual.get("tipo_match", "")
    if "CODIGO_MRV" in tipo or "CODIGO_BRASAL" in tipo:
        return

    t = threading.Thread(
        target=_rodar_shadow,
        args=(item, resultado_atual, base_krona),
        daemon=True,
    )
    t.start()
    t.join(timeout=30)  # aguarda ate 30s (primeira vez faz download do modelo)
