# -*- coding: utf-8 -*-
import os
import re
import time
import math
import threading
from dataclasses import dataclass

import pandas as pd
import pyautogui
import pytesseract
import keyboard

from PIL import Image, ImageOps, ImageEnhance, ImageFilter


# ============================================================
# CONFIGURAÇÕES GERAIS
# ============================================================

try:
    from config import BASE_DIR as _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))

PASTA_SAIDA = os.environ.get("GAMATEC_BASE_DIR", _BASE_DIR)
PASTA_SAIDA = os.path.join(PASTA_SAIDA, "saida")
CAMINHO_DESCONTOS = os.path.join(PASTA_SAIDA, "descontos_gamatec.csv")
CAMINHO_LOG = os.path.join(PASTA_SAIDA, "log_automacao_gamatec.txt")

TESSERACT_PATH = os.environ.get(
    "TESSERACT_PATH",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# Segurança
TECLA_PAUSA = "f8"
TECLA_ABORTAR = "esc"
TEMPO_CONTAGEM = 5
DELAY_CURTO = 0.15
DELAY_MEDIO = 0.30
DELAY_LONGO = 0.60

# Navegação
TECLA_LIMPAR_CAMPO = "ctrl+a"
TECLA_AVANCAR_LINHA = "down"   # ajuste depois se necessário
CLICK_ANTES_DE_DIGITAR = False

# Modo
MODO_TESTE = False   # True = não digita nada, só calcula/loga
AJUSTE_FINO_MAX_TENTATIVAS = 4

# OCR
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


# ============================================================
# ESTADO GLOBAL
# ============================================================

PAUSADO = False
ABORTADO = False


def alternar_pausa():
    global PAUSADO
    PAUSADO = not PAUSADO
    estado = "PAUSADO" if PAUSADO else "RETOMADO"
    print(f"\n[SEGURANÇA] {estado}")


def abortar_execucao():
    global ABORTADO
    ABORTADO = True
    print("\n[SEGURANÇA] ABORTADO PELO USUÁRIO")


keyboard.add_hotkey(TECLA_PAUSA, alternar_pausa)
keyboard.add_hotkey(TECLA_ABORTAR, abortar_execucao)


def aguardar_seguranca():
    global PAUSADO, ABORTADO

    while PAUSADO and not ABORTADO:
        time.sleep(0.2)

    if ABORTADO:
        raise KeyboardInterrupt("Execução abortada pelo usuário.")


def log(msg):
    print(msg)
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    with open(CAMINHO_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# ============================================================
# UTILITÁRIOS
# ============================================================

def normalizar_codigo_krona(valor):
    texto = str(valor or "").strip()
    return texto.zfill(4) if texto.isdigit() and len(texto) <= 4 else texto


def valor_numerico(v):
    if pd.isna(v):
        return None

    if isinstance(v, (int, float)):
        return float(v)

    texto = str(v).strip()
    if not texto:
        return None

    texto = texto.replace(" ", "")
    texto = texto.replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return None


def formatar_desconto(valor):
    if valor is None:
        return None
    return f"{float(valor):.5f}"


def calcular_desconto_percentual(preco_sistema, preco_alvo):
    preco_sistema = valor_numerico(preco_sistema)
    preco_alvo = valor_numerico(preco_alvo)

    if preco_sistema is None or preco_alvo is None:
        return None

    if preco_sistema <= 0:
        return None

    if preco_alvo >= preco_sistema:
        return 0.0

    desconto = ((preco_sistema - preco_alvo) / preco_sistema) * 100.0

    if desconto < 0:
        desconto = 0.0

    return round(desconto, 5)


def calcular_preco_final(preco_sistema, desconto_percentual):
    preco_sistema = valor_numerico(preco_sistema)
    desconto_percentual = valor_numerico(desconto_percentual)

    if preco_sistema is None or desconto_percentual is None:
        return None

    return round(preco_sistema * (1 - desconto_percentual / 100.0), 5)


def extrair_primeiro_codigo(texto):
    texto = str(texto or "")
    m = re.search(r"\b(\d{3,10})\b", texto)
    return m.group(1).zfill(4) if m else None


def extrair_primeiro_numero(texto):
    texto = str(texto or "")
    texto = texto.replace(",", ".")
    encontrados = re.findall(r"\d+(?:\.\d+)?", texto)
    if not encontrados:
        return None
    try:
        return float(encontrados[0])
    except Exception:
        return None


def contagem_regressiva(segundos):
    for i in range(segundos, 0, -1):
        print(f"Iniciando em {i}...")
        time.sleep(1)


# ============================================================
# OCR
# ============================================================

def preprocessar_ocr(img):
    img = ImageOps.grayscale(img)
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.resize((img.width * 2, img.height * 2))
    img = img.filter(ImageFilter.SHARPEN)
    return img


def screenshot_regiao(x, y, w, h):
    return pyautogui.screenshot(region=(x, y, w, h))


def ocr_texto(img, psm=7, whitelist=None):
    config = f"--oem 3 --psm {psm}"
    if whitelist:
        config += f' -c tessedit_char_whitelist="{whitelist}"'
    txt = pytesseract.image_to_string(preprocessar_ocr(img), config=config)
    return txt.strip()


# ============================================================
# CALIBRAÇÃO
# ============================================================

@dataclass
class Calibracao:
    x_codigo: int
    y_codigo_primeira_linha: int
    w_codigo: int
    h_codigo: int

    x_desc: int
    y_desc_primeira_linha: int
    w_desc: int
    h_desc: int

    x_ult: int
    y_ult_primeira_linha: int
    w_ult: int
    h_ult: int

    x_final: int
    y_final_primeira_linha: int
    w_final: int
    h_final: int

    x_desc_field: int
    y_desc_field_primeira_linha: int

    passo_linha: int


def capturar_posicao(msg):
    print(f"\n{msg}")
    print("Posicione o mouse e pressione ENTER aqui no terminal...")
    input()
    x, y = pyautogui.position()
    print(f"Capturado: ({x}, {y})")
    return x, y


def capturar_calibracao():
    print("\n=== CALIBRAÇÃO GAMATEC ===")
    print("Abra a tela 'Itens com Mix' e deixe a primeira linha visível.")
    print("Use zoom/painel do Windows já no formato final.")
    print("Mova o mouse conforme solicitado.")

    x_codigo, y_codigo = capturar_posicao("1) Centro do código da PRIMEIRA linha (ex.: 0338)")
    x_codigo2, y_codigo2 = capturar_posicao("2) Centro do código da SEGUNDA linha")
    x_desc_field, y_desc_field = capturar_posicao("3) Centro do campo % Desc. da PRIMEIRA linha")
    x_ult, y_ult = capturar_posicao("4) Centro do campo Últ. Preço da PRIMEIRA linha")
    x_final, y_final = capturar_posicao("5) Centro do campo Final da PRIMEIRA linha")

    passo_linha = y_codigo2 - y_codigo

    if passo_linha <= 0:
        raise ValueError("Passo da linha inválido. Refaça a calibração.")

    # Regiões OCR
    w_codigo, h_codigo = 260, 28
    w_ult, h_ult = 170, 28
    w_final, h_final = 170, 28

    # Para descrição, pega área maior
    x_desc = x_codigo + 55
    y_desc = y_codigo
    w_desc, h_desc = 420, 28

    calibracao = Calibracao(
        x_codigo=x_codigo - 20,
        y_codigo_primeira_linha=y_codigo - 14,
        w_codigo=w_codigo,
        h_codigo=h_codigo,

        x_desc=x_desc,
        y_desc_primeira_linha=y_codigo - 14,
        w_desc=w_desc,
        h_desc=h_desc,

        x_ult=x_ult - 80,
        y_ult_primeira_linha=y_ult - 14,
        w_ult=w_ult,
        h_ult=h_ult,

        x_final=x_final - 80,
        y_final_primeira_linha=y_final - 14,
        w_final=w_final,
        h_final=h_final,

        x_desc_field=x_desc_field,
        y_desc_field_primeira_linha=y_desc_field,
        passo_linha=passo_linha,
    )

    print("\nCalibração concluída.")
    print(calibracao)
    return calibracao


# ============================================================
# LEITURA DOS DADOS OPERACIONAIS
# ============================================================

def carregar_mapa_descontos():
    if not os.path.exists(CAMINHO_DESCONTOS):
        raise FileNotFoundError(f"Arquivo não encontrado: {CAMINHO_DESCONTOS}")

    df = pd.read_csv(CAMINHO_DESCONTOS, sep=";", encoding="utf-8-sig")

    if df.empty:
        raise ValueError("Arquivo descontos_gamatec.csv está vazio.")

    mapa = {}

    for _, row in df.iterrows():
        codigo = normalizar_codigo_krona(row.get("codigo_krona"))
        if not codigo:
            continue

        mapa[codigo] = {
            "codigo_krona": codigo,
            "descricao": str(row.get("descricao") or "").strip(),
            "preco_alvo_cliente": valor_numerico(row.get("preco_alvo_cliente")),
        }

    return mapa


# ============================================================
# LEITURA DE LINHA NA TELA
# ============================================================

def ler_codigo_linha(cal, indice_linha):
    y = cal.y_codigo_primeira_linha + (indice_linha * cal.passo_linha)
    img = screenshot_regiao(cal.x_codigo, y, cal.w_codigo, cal.h_codigo)
    txt = ocr_texto(img, psm=7, whitelist="0123456789- ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz/.,Xx")
    codigo = extrair_primeiro_codigo(txt)
    return codigo, txt


def ler_descricao_linha(cal, indice_linha):
    y = cal.y_desc_primeira_linha + (indice_linha * cal.passo_linha)
    img = screenshot_regiao(cal.x_desc, y, cal.w_desc, cal.h_desc)
    txt = ocr_texto(img, psm=7)
    return txt


def ler_ult_preco_linha(cal, indice_linha):
    y = cal.y_ult_primeira_linha + (indice_linha * cal.passo_linha)
    img = screenshot_regiao(cal.x_ult, y, cal.w_ult, cal.h_ult)
    txt = ocr_texto(img, psm=7, whitelist="0123456789.,")
    valor = extrair_primeiro_numero(txt)
    return valor, txt


def ler_final_linha(cal, indice_linha):
    y = cal.y_final_primeira_linha + (indice_linha * cal.passo_linha)
    img = screenshot_regiao(cal.x_final, y, cal.w_final, cal.h_final)
    txt = ocr_texto(img, psm=7, whitelist="0123456789.,")
    valor = extrair_primeiro_numero(txt)
    return valor, txt


def clicar_campo_desc_linha(cal, indice_linha):
    x = cal.x_desc_field
    y = cal.y_desc_field_primeira_linha + (indice_linha * cal.passo_linha)
    pyautogui.click(x, y)
    time.sleep(DELAY_CURTO)


def digitar_desconto(valor_desc):
    texto = formatar_desconto(valor_desc)
    if texto is None:
        return

    pyautogui.hotkey("ctrl", "a")
    time.sleep(DELAY_CURTO)
    pyautogui.write(texto, interval=0.02)
    time.sleep(DELAY_CURTO)


# ============================================================
# AJUSTE FINO
# ============================================================

def ajustar_fino(preco_sistema, preco_alvo, desconto_inicial, final_lido):
    """
    Ajusta o desconto para tentar deixar:
    final <= alvo e o mais próximo possível.
    """
    preco_sistema = valor_numerico(preco_sistema)
    preco_alvo = valor_numerico(preco_alvo)
    desconto = valor_numerico(desconto_inicial)
    final_lido = valor_numerico(final_lido)

    if None in [preco_sistema, preco_alvo, desconto, final_lido]:
        return desconto

    if final_lido <= preco_alvo:
        return round(desconto, 5)

    diferenca = final_lido - preco_alvo
    incremento_pct = (diferenca / preco_sistema) * 100.0
    novo = desconto + incremento_pct + 0.00001

    if novo < 0:
        novo = 0.0

    return round(novo, 5)


# ============================================================
# PROCESSAMENTO PRINCIPAL DA GRADE
# ============================================================

def processar_grade(cal, mapa_descontos, max_linhas=100):
    log("\n=== INÍCIO DA AUTOMAÇÃO GAMATEC ===")
    log(f"Tecla pausa/retoma: {TECLA_PAUSA}")
    log(f"Tecla abortar: {TECLA_ABORTAR}")
    log("Leve o mouse para o canto superior esquerdo para fail-safe do PyAutoGUI.")

    for idx in range(max_linhas):
        aguardar_seguranca()

        codigo_lido, texto_codigo = ler_codigo_linha(cal, idx)

        if not codigo_lido:
            log(f"[LINHA {idx+1}] Código não lido. Encerrando varredura.")
            break

        codigo_lido = normalizar_codigo_krona(codigo_lido)

        if codigo_lido not in mapa_descontos:
            log(f"[LINHA {idx+1}] Código {codigo_lido} não está no mapa. Encerrando ou pule manualmente.")
            break

        item = mapa_descontos[codigo_lido]
        preco_alvo = item.get("preco_alvo_cliente")

        ult_preco, txt_ult = ler_ult_preco_linha(cal, idx)
        final_antes, txt_final_antes = ler_final_linha(cal, idx)
        descricao_tela = ler_descricao_linha(cal, idx)

        log(
            f"[LINHA {idx+1}] COD={codigo_lido} | DESC={descricao_tela} | "
            f"ULT={ult_preco} | FINAL_ANTES={final_antes} | ALVO={preco_alvo}"
        )

        if preco_alvo is None:
            log(f"[LINHA {idx+1}] Sem preço alvo. Pulando.")
            continue

        if ult_preco is None or ult_preco <= 0:
            log(f"[LINHA {idx+1}] Últ. Preço inválido. Pulando.")
            continue

        desconto = calcular_desconto_percentual(ult_preco, preco_alvo)

        if desconto is None:
            log(f"[LINHA {idx+1}] Não foi possível calcular desconto. Pulando.")
            continue

        log(f"[LINHA {idx+1}] Desconto inicial calculado: {desconto:.5f}")

        if MODO_TESTE:
            continue

        clicar_campo_desc_linha(cal, idx)
        digitar_desconto(desconto)
        time.sleep(DELAY_MEDIO)

        final_depois, txt_final_depois = ler_final_linha(cal, idx)
        log(f"[LINHA {idx+1}] Final após digitação: {final_depois}")

        tentativas = 0

        while tentativas < AJUSTE_FINO_MAX_TENTATIVAS:
            aguardar_seguranca()

            if final_depois is not None and final_depois <= preco_alvo:
                break

            novo_desc = ajustar_fino(ult_preco, preco_alvo, desconto, final_depois)

            if novo_desc is None or abs(novo_desc - desconto) < 0.00001:
                break

            desconto = novo_desc
            log(f"[LINHA {idx+1}] Ajuste fino tentativa {tentativas+1}: {desconto:.5f}")

            clicar_campo_desc_linha(cal, idx)
            digitar_desconto(desconto)
            time.sleep(DELAY_MEDIO)

            final_depois, txt_final_depois = ler_final_linha(cal, idx)
            log(f"[LINHA {idx+1}] Final após ajuste: {final_depois}")

            tentativas += 1

        # avança para a próxima linha
        pyautogui.press(TECLA_AVANCAR_LINHA)
        time.sleep(DELAY_CURTO)

    log("=== FIM DA AUTOMAÇÃO GAMATEC ===")


# ============================================================
# MAIN
# ============================================================

def main():
    global ABORTADO

    os.makedirs(PASTA_SAIDA, exist_ok=True)

    if not os.path.exists(TESSERACT_PATH):
        print(f"\nATENÇÃO: Tesseract não encontrado em:\n{TESSERACT_PATH}")
        print("Instale o Tesseract OCR ou ajuste o caminho TESSERACT_PATH no script.")
        return

    mapa_descontos = carregar_mapa_descontos()

    print("\n=== AUTOMAÇÃO GAMATEC - ITENS COM MIX ===")
    print(f"Itens no mapa: {len(mapa_descontos)}")
    print(f"Pausa/Retoma: {TECLA_PAUSA}")
    print(f"Abortar: {TECLA_ABORTAR}")
    print(f"Modo teste: {MODO_TESTE}")
    print("\nIMPORTANTE:")
    print("1) Abra o GAMATEC na tela 'Itens com Mix'")
    print("2) Deixe a primeira linha visível")
    print("3) Não mexa no mouse/teclado durante a execução")
    print("4) Para pausar use F8")
    print("5) Para abortar use ESC")
    print("6) Mover o mouse para o canto superior esquerdo também aborta")

    input("\nPressione ENTER para iniciar a calibração...")

    cal = capturar_calibracao()

    print("\nAgora posicione o mouse fora da grade.")
    print("A automação começará após a contagem regressiva.")
    contagem_regressiva(TEMPO_CONTAGEM)

    try:
        processar_grade(cal, mapa_descontos, max_linhas=len(mapa_descontos))
    except KeyboardInterrupt as e:
        log(f"[ABORTADO] {e}")
    except pyautogui.FailSafeException:
        log("[FAILSAFE] Mouse levado ao canto da tela. Execução abortada.")
    except Exception as e:
        log(f"[ERRO] {repr(e)}")

    print("\nExecução encerrada.")
    print(f"Log salvo em: {CAMINHO_LOG}")


if __name__ == "__main__":
    main()