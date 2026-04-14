import os
import re
import pandas as pd
import pdfplumber
from config import PASTA_SAIDA
from normalizador import enriquecer_descricao


COLUNAS_SAIDA = [
    "item_oc",
    "descricao_oc",
    "descricao_normalizada",
    "categoria_detectada",
    "eh_tubo",
    "diametro_mm",
    "comprimento_detectado_m",
    "unidade_oc",
    "quantidade_oc",
    "preco_unit_oc",
    "total_oc",
    "observacao_validacao",
]


def extrair_texto_pdf(caminho_pdf: str) -> str:
    textos = []

    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                textos.append(texto)

    return "\n\n".join(textos)


def salvar_texto_extraido(caminho_pdf: str, texto: str) -> str:
    nome_base = os.path.splitext(os.path.basename(caminho_pdf))[0]
    caminho_saida = os.path.join(PASTA_SAIDA, f"{nome_base}_texto_extraido.txt")

    os.makedirs(PASTA_SAIDA, exist_ok=True)

    with open(caminho_saida, "w", encoding="utf-8") as f:
        f.write(texto)

    return caminho_saida


def normalizar_numero_br(valor: str) -> float:
    valor = valor.strip()
    valor = valor.replace(".", "").replace(",", ".")
    return float(valor)


def limpar_descricao(descricao: str) -> str:
    descricao = re.sub(r"\s+", " ", descricao).strip()
    return descricao


def validar_item_extraido(item: dict) -> str:
    observacoes = []

    quantidade = item.get("quantidade_oc", 0)
    preco_unit = item.get("preco_unit_oc", 0)
    total = item.get("total_oc", 0)

    if quantidade > 0 and preco_unit > 0:
        total_calculado = round(quantidade * preco_unit, 2)
        diferenca = abs(total_calculado - total)

        if diferenca > 0.05:
            observacoes.append(
                f"ALERTA_TOTAL_DIVERGENTE: calc={total_calculado} oc={total}"
            )

    if item.get("eh_tubo") and item.get("unidade_oc") not in ("m", "mt", "mts"):
        observacoes.append("TUBO_COM_UNIDADE_NAO_METRO")

    return " | ".join(observacoes)


def extrair_itens_do_texto(texto: str) -> list[dict]:
    itens = []
    linhas = texto.splitlines()

    padrao_item = re.compile(
        r"^\s*(\d+)\s+(.+?)\s+(un|m|mt|mts|rl|pc|jg|sc|l|kg)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)\s*$",
        re.IGNORECASE
    )

    for linha in linhas:
        linha = linha.strip()

        if not linha:
            continue

        if "Item Descrição Un." in linha:
            continue

        if "UAU! Software" in linha:
            continue

        correspondencia = padrao_item.match(linha)
        if correspondencia:
            item_oc = correspondencia.group(1).strip()
            descricao_oc = limpar_descricao(correspondencia.group(2))
            unidade_oc = correspondencia.group(3).lower().strip()
            quantidade_oc = normalizar_numero_br(correspondencia.group(4))
            preco_unit_oc = normalizar_numero_br(correspondencia.group(5))
            total_oc = normalizar_numero_br(correspondencia.group(6))

            dados_desc = enriquecer_descricao(descricao_oc)

            item = {
                "item_oc": item_oc,
                "descricao_oc": descricao_oc,
                "descricao_normalizada": dados_desc["descricao_normalizada"],
                "categoria_detectada": dados_desc["categoria_detectada"],
                "eh_tubo": dados_desc["eh_tubo"],
                "diametro_mm": dados_desc["diametro_mm"],
                "comprimento_detectado_m": dados_desc["comprimento_detectado_m"],
                "unidade_oc": unidade_oc,
                "quantidade_oc": quantidade_oc,
                "preco_unit_oc": preco_unit_oc,
                "total_oc": total_oc,
                "observacao_validacao": "",
            }

            item["observacao_validacao"] = validar_item_extraido(item)
            itens.append(item)

    return itens


def salvar_itens_csv(caminho_pdf: str, itens: list[dict]) -> str:
    nome_base = os.path.splitext(os.path.basename(caminho_pdf))[0]
    caminho_saida = os.path.join(PASTA_SAIDA, f"{nome_base}_itens_extraidos.csv")

    os.makedirs(PASTA_SAIDA, exist_ok=True)

    df = pd.DataFrame(itens, columns=COLUNAS_SAIDA)
    df.to_csv(caminho_saida, index=False, encoding="utf-8-sig", sep=";")

    return caminho_saida


def processar_pdf_oc(caminho_pdf: str) -> None:
    if not os.path.exists(caminho_pdf):
        print("Arquivo nao encontrado.")
        raise SystemExit(1)

    texto = extrair_texto_pdf(caminho_pdf)

    if not texto.strip():
        print("Nenhum texto foi extraido do PDF.")
        raise SystemExit(1)

    caminho_txt = salvar_texto_extraido(caminho_pdf, texto)
    itens = extrair_itens_do_texto(texto)
    caminho_csv = salvar_itens_csv(caminho_pdf, itens)

    print("\n=== TEXTO EXTRAIDO SALVO EM ===")
    print(caminho_txt)

    print("\n=== RESUMO DA EXTRACAO ===")
    print(f"Itens encontrados: {len(itens)}")

    if itens:
        print("\n=== PRIMEIROS ITENS ===")
        for item in itens[:10]:
            print(item)

    print("\n=== CSV SALVO EM ===")
    print(caminho_csv)

def extrair_itens_oc(caminho_pdf: str) -> pd.DataFrame:
    texto = extrair_texto_pdf(caminho_pdf)
    itens = extrair_itens_do_texto(texto)
    return pd.DataFrame(itens, columns=COLUNAS_SAIDA)