# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from pprint import pprint

import pyautogui

from agente_gamatec import AgenteGamatec
from orquestrador_agente_gamatec import OrquestradorAgenteGamatec
from percepcao_gamatec import PercepcaoGamatec
from planejador_execucao_gamatec import localizar_arquivo_planejamento, carregar_plano_execucao


PASTA_SAIDA = r"C:\robo_gamatec_oc\saida"
ARQUIVO_DUMP = os.path.join(PASTA_SAIDA, "dump_agente_gamatec_leitura.json")


def log(msg: str):
    print(f"\n{msg}", flush=True)


def pausar(msg: str = "Pressione ENTER para continuar..."):
    print(f"\n{msg}", flush=True)
    input("> ")


def capturar_posicao(msg):
    log(msg)
    pausar("Posicione o mouse e pressione ENTER no CMD...")
    x, y = pyautogui.position()
    print(f"Capturado: ({x}, {y})", flush=True)
    return x, y


def calibrar_percepcao_real():
    log("=== CALIBRAÇÃO REAL DO GAMATEC ===")
    print("Abra a tela 'Itens com Mix' e deixe a grade visível.", flush=True)
    print("ATENÇÃO: sempre volte o foco para o CMD antes de apertar ENTER.", flush=True)

    x_codigo_1, y_codigo_1 = capturar_posicao("1) Centro do CÓDIGO da PRIMEIRA linha")
    x_codigo_2, y_codigo_2 = capturar_posicao("2) Centro do CÓDIGO da SEGUNDA linha")
    x_desc, y_desc = capturar_posicao("3) Centro da DESCRIÇÃO da PRIMEIRA linha")
    x_ult, y_ult = capturar_posicao("4) Centro do campo ÚLT. PREÇO da PRIMEIRA linha")
    x_final, y_final = capturar_posicao("5) Centro do campo FINAL da PRIMEIRA linha")
    x_desc_campo, y_desc_campo = capturar_posicao("6) Centro do campo % DESC da PRIMEIRA linha")
    x_scroll, y_scroll = capturar_posicao("7) Ponto seguro da ÁREA DA GRADE para SCROLL")

    passo_linha = y_codigo_2 - y_codigo_1
    if passo_linha <= 0:
        raise ValueError("Passo de linha inválido. Refaça a calibração.")

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
	
	# ===== PARÂMETROS DE PERFORMANCE OCR =====
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

        # ===== AJUSTE FINO DE ROI OCR =====
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

    log("[CALIBRAÇÃO GERADA]")
    pprint(calibracao)
    print(f"[PASSO DE LINHA] {passo_linha}", flush=True)

    return calibracao


def salvar_dump(dados):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    with open(ARQUIVO_DUMP, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def aguardar_preparacao_tela(segundos: int = 5):
    log(f"Prepare a tela do GAMATEC. A leitura começará em {segundos} segundos...")
    for i in range(segundos, 0, -1):
        print(f"Iniciando em {i}...", flush=True)
        time.sleep(1)


def main():
    log("=== AGENTE GAMATEC - MODO LEITURA/DECISÃO ===")
    print("Este modo NÃO aplica desconto.", flush=True)
    print("Ele lê a grade, compara com o plano e mostra a decisão do agente.", flush=True)

    log("[ETAPA 1] Localizando arquivo de planejamento...")
    caminho = localizar_arquivo_planejamento()
    plano = carregar_plano_execucao(caminho)

    print(f"[PLANO] Arquivo: {caminho}", flush=True)
    print(f"[PLANO] Total de itens: {len(plano)}", flush=True)

    pausar("[ETAPA 2] Pressione ENTER para iniciar a calibração...")

    log("[ETAPA 3] Iniciando calibração...")
    calibracao = calibrar_percepcao_real()

    log("[ETAPA 4] Inicializando módulos...")
    percepcao = PercepcaoGamatec(calibracao=calibracao, debug=True, salvar_crops_debug=False)
    agente = AgenteGamatec(debug=True, pasta_debug=PASTA_SAIDA)
    _ = OrquestradorAgenteGamatec(
        calibracao=calibracao,
        debug=True,
        pasta_debug=PASTA_SAIDA,
        quantidade_linhas_visiveis=6,
        max_scrolls_por_item=5,
        max_releituras_por_item=3,
        pausa_curta=0.15,
        pausa_media=0.35,
        pausa_longa=0.60,
    )

    log("[ETAPA 5] Preparação para leitura da grade")
    print("Agora deixe a grade do GAMATEC posicionada.", flush=True)
    print("NÃO precisa apertar ENTER imediatamente na tela do GAMATEC.", flush=True)
    print("Volte o foco para o CMD e pressione ENTER uma única vez.", flush=True)
    pausar("Pressione ENTER no CMD para iniciar a contagem de leitura...")

    aguardar_preparacao_tela(segundos=5)

    log("[ETAPA 6] Lendo grade visível...")
    linhas = percepcao.ler_grade(
        quantidade_linhas=6,
        auto_ancorar_primeira_linha=True
    )

    log("[LINHAS PERCEBIDAS]")
    dump_linhas = []
    for linha in linhas:
        registro = linha.to_dict()
        dump_linhas.append(registro)

        print("-" * 100, flush=True)
        print(f"Linha: {linha.indice_linha} | y={linha.y_base}", flush=True)
        print(
            f"Codigo    : lido={linha.codigo.valor} | "
            f"normalizado={linha.codigo.valor_normalizado} | "
            f"bruto={linha.codigo.bruto} | conf={linha.codigo.confianca:.2f}",
            flush=True
        )
        print(
            f"Descricao : {linha.descricao.valor} | bruto={linha.descricao.bruto} | conf={linha.descricao.confianca:.2f}",
            flush=True
        )
        print(
            f"Ult. Preco: {linha.ult_preco.valor} | bruto={linha.ult_preco.bruto} | conf={linha.ult_preco.confianca:.2f}",
            flush=True
        )
        print(
            f"Final     : {linha.final.valor} | bruto={linha.final.bruto} | conf={linha.final.confianca:.2f}",
            flush=True
        )

    log("[ETAPA 7] Decidindo para o primeiro item do plano...")
    item_planejado = plano[0]
    pprint(item_planejado)

    decisao = agente.decidir_em_grade_visivel(linhas, item_planejado)

    log("[DECISÃO DO AGENTE]")
    pprint(decisao)

    dump = {
        "arquivo_plano": caminho,
        "item_planejado": item_planejado,
        "linhas_percebidas": dump_linhas,
        "decisao": decisao.__dict__,
        "calibracao": calibracao,
    }

    salvar_dump(dump)

    log("[DUMP SALVO EM]")
    print(ARQUIVO_DUMP, flush=True)

    log("[TESTE CONCLUÍDO]")
    print("Se a decisão estiver coerente, no próximo passo ligamos a aplicação real do desconto.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INTERROMPIDO PELO USUÁRIO]", flush=True)
        raise
    except Exception as e:
        print(f"\n\n[ERRO] {type(e).__name__}: {e}", flush=True)
        raise