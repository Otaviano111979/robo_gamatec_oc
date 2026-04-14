from pprint import pprint
import pyautogui

from percepcao_gamatec import CalibracaoPercepcao, PercepcaoGamatec


def capturar_posicao(msg):
    print(f"\n{msg}")
    input("Posicione o mouse e pressione ENTER...")
    x, y = pyautogui.position()
    print(f"Capturado: ({x}, {y})")
    return x, y


print("=== TESTE DE PERCEPÇÃO GAMATEC ===")
print("Abra a tela do GAMATEC e deixe a primeira página da grade visível.")

x_codigo, y_codigo = capturar_posicao("1) Centro do código da PRIMEIRA linha")
x_codigo2, y_codigo2 = capturar_posicao("2) Centro do código da SEGUNDA linha")
x_ult, y_ult = capturar_posicao("3) Centro do campo Últ. Preço da PRIMEIRA linha")
x_final, y_final = capturar_posicao("4) Centro do campo Final da PRIMEIRA linha")

passo_linha = y_codigo2 - y_codigo

cal = CalibracaoPercepcao(
    x_codigo=x_codigo - 24,
    y_codigo_primeira_linha=y_codigo - 14,
    w_codigo=58,
    h_codigo=28,

    x_desc=x_codigo + 45,
    y_desc_primeira_linha=y_codigo - 14,
    w_desc=430,
    h_desc=28,

    x_ult=x_ult - 80,
    y_ult_primeira_linha=y_ult - 14,
    w_ult=170,
    h_ult=28,

    x_final=x_final - 80,
    y_final_primeira_linha=y_final - 14,
    w_final=170,
    h_final=28,

    passo_linha=passo_linha,
    linhas_visiveis=6,
)

percepcao = PercepcaoGamatec(cal)

print("\n[ASSINATURA DA PRIMEIRA LINHA]")
print(percepcao.assinatura_primeira_linha())

print("\n[PÁGINA VISÍVEL]")
pagina = percepcao.ler_pagina_visivel()
for linha in pagina:
    pprint(linha)

print("\n[TESTE DE SCROLL]")
resultado_scroll = percepcao.rolar_para_proxima_pagina()
pprint(resultado_scroll)

print("\n[NOVA ASSINATURA DA PRIMEIRA LINHA]")
print(percepcao.assinatura_primeira_linha())