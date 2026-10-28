# -*- coding: utf-8 -*-
"""
config.py — Vortex Platform

Suporta dois modos:
  1. MODO LEGADO (atual): BASE_DIR aponta para C:\\robo_gamatec_oc
     Compatível 100% com o que existe hoje — nada quebra.

  2. MODO MULTI-EMPRESA (launcher):
     VORTEX_EMPRESA_ID definido → carrega config de
     C:\\Vortex\\empresas\\{empresa_id}\\config.json

Transição suave: hoje roda em modo legado.
Quando o launcher for ativado, define VORTEX_EMPRESA_ID e pronto.
"""

import json
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ============================================================
# DETECTAR MODO
# ============================================================

EMPRESA_ID  = os.environ.get("VORTEX_EMPRESA_ID", "").strip()
VORTEX_ROOT = os.environ.get("VORTEX_ROOT", "C:\\Vortex").strip()


def _carregar_config_empresa(empresa_id):
    caminho = os.path.join(VORTEX_ROOT, "empresas", empresa_id, "config.json")
    if not os.path.exists(caminho):
        raise FileNotFoundError(
            f"Config da empresa '{empresa_id}' nao encontrada em: {caminho}\n"
            f"Execute: python launcher.py --criar-empresa {empresa_id}"
        )
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# RESOLVER BASE_DIR
# ============================================================

def _resolver_base_dir():
    """GAMATEC_BASE_DIR se existir; senao a pasta deste arquivo.

    Uma maquina instalada noutra pasta pode ter um .env copiado de outra
    maquina apontando para um caminho inexistente — nesse caso avisa e usa
    a pasta do proprio projeto, em vez de falhar ou escrever no lugar errado.
    """
    pasta_projeto = os.path.abspath(os.path.dirname(__file__))
    configurado = os.environ.get("GAMATEC_BASE_DIR", "").strip().strip('"')
    if not configurado:
        return pasta_projeto
    if not os.path.isdir(configurado):
        print(
            f"[CONFIG] GAMATEC_BASE_DIR='{configurado}' nao existe nesta maquina "
            f"— usando a pasta do projeto: {pasta_projeto}"
        )
        return pasta_projeto
    return os.path.abspath(configurado)


if EMPRESA_ID:
    _cfg = _carregar_config_empresa(EMPRESA_ID)
    BASE_DIR        = os.path.join(VORTEX_ROOT, "empresas", EMPRESA_ID)
    _EMPRESA_NOME   = _cfg.get("nome", EMPRESA_ID)
    _MODULOS_ATIVOS = _cfg.get("modulos_ativos", ["oc"])
    _MODULOS_TRIAL  = _cfg.get("modulos_trial", [])
    _VERSAO_SISTEMA = _cfg.get("versao", "1.0")
else:
    # MODO LEGADO — compativel com estrutura atual
    BASE_DIR = _resolver_base_dir()
    _EMPRESA_NOME   = "UNE Representacoes"
    _MODULOS_ATIVOS = ["oc", "email"]
    _MODULOS_TRIAL  = []
    _VERSAO_SISTEMA = "1.0"


# ============================================================
# CAMINHOS — iguais nos dois modos
# ============================================================

PASTA_DADOS  = os.path.join(BASE_DIR, "dados")
PASTA_OC     = os.path.join(PASTA_DADOS, "oc")
PASTA_SAIDA  = os.path.join(BASE_DIR, "saida")

CAMINHO_FONTE_KRONA_PRINCIPAL = os.path.join(
    PASTA_DADOS, "DADOS DE PRODUTOS KRONA(1).xlsx"
)
CAMINHO_BASE_KRONA_FINAL = os.path.join(
    PASTA_SAIDA, "base_krona_final.csv"
)
CAMINHO_CATALOGO_PDF = os.path.join(
    PASTA_DADOS, "Krona cataologo KRONA - GERAL.pdf"
)
USAR_CATALOGO_PDF_NO_MATCHER = False

CAMINHO_OC_EXEMPLO           = os.path.join(PASTA_OC, "teste.pdf")
# Flag unica para desligar IA no fluxo de OC (matcher + auto-detector).
# Default OFF — pipeline 100% deterministico. Ligar: GAMATEC_USAR_IA=1
USAR_IA = os.environ.get("GAMATEC_USAR_IA", "0").strip() == "1"
CAMINHO_RESULTADO_PROCESSADO = os.path.join(PASTA_SAIDA, "resultado_processado.csv")
CAMINHO_RESULTADO_VALIDADO   = os.path.join(PASTA_SAIDA, "resultado_validado.csv")
CAMINHO_APROVADOS            = os.path.join(PASTA_SAIDA, "itens_aprovados_automatico.csv")
CAMINHO_REVISAO              = os.path.join(PASTA_SAIDA, "itens_revisao_manual.csv")


# ============================================================
# INFO PUBLICA
# ============================================================

EMPRESA_NOME   = _EMPRESA_NOME
MODULOS_ATIVOS = _MODULOS_ATIVOS
MODULOS_TRIAL  = _MODULOS_TRIAL
VERSAO_SISTEMA = _VERSAO_SISTEMA
MODO_LAUNCHER  = bool(EMPRESA_ID)


def modulo_ativo(modulo_id):
    return modulo_id in MODULOS_ATIVOS or modulo_id in MODULOS_TRIAL
