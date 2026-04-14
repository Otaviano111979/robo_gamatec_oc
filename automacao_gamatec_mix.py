import time
import pandas as pd
import pyautogui

CAMINHO_ENTRADA = r"C:\robo_gamatec_oc\saida\itens_aprovados_automatico.csv"

MODO_TESTE = True

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2


def carregar_itens():
    df = pd.read_csv(CAMINHO_ENTRADA, sep=";", encoding="utf-8-sig")

    if "desconto_percentual" not in df.columns:
        raise ValueError("Coluna desconto_percentual não encontrada")

    return df


def formatar_desconto(valor):
    try:
        v = float(valor)
        if v < 0 or v > 100:
            return None
        return f"{v:.2f}".replace(".", ",")
    except:
        return None


def clicar_primeiro_campo():
    print("\n⚠️ POSICIONE O MOUSE NO PRIMEIRO CAMPO % DESC. EM 5 SEGUNDOS")
    time.sleep(5)

    x, y = pyautogui.position()

    print(f"Posição capturada: {x}, {y}")

    if not MODO_TESTE:
        pyautogui.click(x, y)

    return x, y


def limpar_campo():
    if MODO_TESTE:
        print("[TESTE] CTRL + A")
    else:
        pyautogui.hotkey("ctrl", "a")


def digitar(texto):
    if MODO_TESTE:
        print(f"[TESTE] Digitar: {texto}")
    else:
        pyautogui.write(texto, interval=0.02)


def proximo_campo():
    if MODO_TESTE:
        print("[TESTE] TAB")
    else:
        pyautogui.press("tab")


def executar():
    print("\n=== AUTOMAÇÃO GAMATEC - ITENS COM MIX ===")
    print(f"MODO_TESTE = {MODO_TESTE}")

    df = carregar_itens()

    print(f"Total de itens: {len(df)}")

    clicar_primeiro_campo()

    for i, row in df.iterrows():
        desconto = formatar_desconto(row.get("desconto_percentual"))

        print(f"\nItem {i+1}: {row.get('descricao_oc')}")
        print(f"Desconto: {desconto}")

        if desconto is None:
            print("⚠️ Desconto inválido - pulando")
            proximo_campo()
            continue

        limpar_campo()
        time.sleep(0.2)

        digitar(desconto)
        time.sleep(0.2)

        # ir para próximo campo/linha
        proximo_campo()
        time.sleep(0.3)

    print("\nFINALIZADO ✔")


if __name__ == "__main__":
    executar()