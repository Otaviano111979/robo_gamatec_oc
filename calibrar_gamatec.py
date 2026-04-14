# -*- coding: utf-8 -*-
"""
calibrar_gamatec.py

Roda UMA VEZ no terminal para calibrar as coordenadas da tela do GAMATEC.
Salva o resultado em calibracao_gamatec.json na pasta saida/.

Depois disso, a automacao pelo dashboard usa esse JSON diretamente
sem precisar de nenhuma intervencao manual.

Como usar:
    1. Abra o GAMATEC na tela "Itens com Mix"
    2. Abra o CMD na pasta C:\\robo_gamatec_oc
    3. Execute: python calibrar_gamatec.py
    4. Siga as instrucoes na tela
    5. O arquivo calibracao_gamatec.json sera salvo automaticamente
"""

from __future__ import annotations

import json
import os
import sys
from pprint import pprint

import pyautogui

from config import BASE_DIR


PASTA_SAIDA = os.path.join(BASE_DIR, "saida")
ARQUIVO_CALIBRACAO = os.path.join(PASTA_SAIDA, "calibracao_gamatec.json")


def log(msg: str):
    print(f"\n{msg}", flush=True)


def pausar(msg: str = "Pressione ENTER para continuar..."):
    print(f"\n{msg}", flush=True)
    input("> ")


def capturar_posicao(msg):
    log(msg)
    pausar("Posicione o mouse na posicao indicada e pressione ENTER no CMD...")
    x, y = pyautogui.position()
    print(f"Capturado: ({x}, {y})", flush=True)
    return x, y


def calibrar():
    log("=== CALIBRAÇÃO DO GAMATEC ===")
    print("Abra a tela 'Itens com Mix' e deixe a grade visivel.", flush=True)
    print("IMPORTANTE: sempre volte o foco para o CMD antes de apertar ENTER.", flush=True)
    print("           Nao clique no GAMATEC enquanto pressiona ENTER.", flush=True)

    pausar("\nPronto? Pressione ENTER para iniciar a calibracao...")

    x_codigo_1, y_codigo_1 = capturar_posicao("1) Posicione o mouse no CENTRO do CODIGO da PRIMEIRA linha visivel")
    x_codigo_2, y_codigo_2 = capturar_posicao("2) Posicione o mouse no CENTRO do CODIGO da SEGUNDA linha visivel")
    x_desc,     y_desc     = capturar_posicao("3) Posicione o mouse no CENTRO da DESCRICAO da PRIMEIRA linha")
    x_ult,      y_ult      = capturar_posicao("4) Posicione o mouse no CENTRO do campo ULT. PRECO da PRIMEIRA linha")
    x_final,    y_final    = capturar_posicao("5) Posicione o mouse no CENTRO do campo FINAL da PRIMEIRA linha")
    x_desc_campo, y_desc_campo = capturar_posicao("6) Posicione o mouse no CENTRO do campo % DESC da PRIMEIRA linha")
    x_scroll,   y_scroll   = capturar_posicao("7) Posicione o mouse num ponto seguro da AREA DA GRADE para scroll")

    passo_linha = y_codigo_2 - y_codigo_1
    if passo_linha <= 0:
        print("\nERRO: passo de linha invalido. A segunda linha deve estar abaixo da primeira.", flush=True)
        print("Refaca a calibracao.", flush=True)
        sys.exit(1)

    calibracao = {
        "x_codigo": x_codigo_1 - 24,
        "y_codigo_linha1": y_codigo_1 - 14,
        "y_codigo_linha2": y_codigo_2 - 14,

        "x_desc": x_desc - 180,
        "x_ult_preco": x_ult - 80,
        "x_final": x_final - 80,

        "w_codigo": 95,
        "h_codigo": 30,

        "w_desc": 430,
        "h_desc": 30,

        "w_ult_preco": 170,
        "h_ult_preco": 30,

        "w_final": 170,
        "h_final": 30,

        "offset_y_codigo": 0,
        "offset_y_desc": 0,
        "offset_y_ult": 0,
        "offset_y_final": 0,

        "x_desc_campo": x_desc_campo,
        "y_desc_campo_linha1": y_desc_campo,

        "x_area_scroll": x_scroll,
        "y_area_scroll": y_scroll,
        "scroll_click_antes": True,
        "scroll_quantidade": -650,

        "separador_decimal_desconto": ".",
        "casas_decimais_desconto": 2,
        "usar_ctrl_a_para_limpar": True,
        "confirmar_com_enter": True,
        "duplo_clique_campo_desc": True,
        "max_tentativas_aplicar_desconto": 2,

        "max_varredura_linhas": 3,

        "raio_x_codigo": 2,
        "raio_y_codigo": 2,
        "passo_busca_codigo": 2,

        "raio_x_desc": 2,
        "raio_y_desc": 2,
        "passo_busca_desc": 2,

        "raio_x_preco": 2,
        "raio_y_preco": 2,
        "passo_busca_preco": 2,

        "max_variantes_codigo": 2,
        "max_variantes_desc": 1,
        "max_variantes_preco": 2,

        "crop_left_codigo": 2,
        "crop_top_codigo": 3,
        "crop_right_codigo": 4,
        "crop_bottom_codigo": 3,

        "crop_left_desc": 4,
        "crop_top_desc": 3,
        "crop_right_desc": 8,
        "crop_bottom_desc": 3,

        "crop_left_preco": 8,
        "crop_top_preco": 3,
        "crop_right_preco": 12,
        "crop_bottom_preco": 3,

        "exigir_descricao_min_chars": 4,
        "ancorar_com_descricao": True,
        "ancorar_com_preco": True,

        "log_ocr": False,
    }

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    with open(ARQUIVO_CALIBRACAO, "w", encoding="utf-8") as f:
        json.dump(calibracao, f, ensure_ascii=False, indent=2)

    log("=== CALIBRAÇÃO CONCLUÍDA ===")
    print(f"Arquivo salvo em: {ARQUIVO_CALIBRACAO}", flush=True)
    print(f"Passo de linha detectado: {passo_linha}px", flush=True)
    print("\nAgora voce pode usar a automacao pelo dashboard normalmente.", flush=True)

    log("Dados calibrados:")
    pprint(calibracao)

    return calibracao


if __name__ == "__main__":
    try:
        calibrar()
    except KeyboardInterrupt:
        print("\n\n[INTERROMPIDO PELO USUARIO]", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"\n\n[ERRO] {type(e).__name__}: {e}", flush=True)
        raise
