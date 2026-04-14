import os
import re
import math
import warnings
import logging
import unicodedata
from collections import defaultdict

import pdfplumber
import pandas as pd

from normalizador import enriquecer_descricao


CAMINHO_PDF = r"C:\robo_gamatec_oc\dados\Krona cataologo KRONA - GERAL.pdf"
CAMINHO_SAIDA_CSV = r"C:\robo_gamatec_oc\saida\base_catalogo_krona.csv"


# Silencia parte do barulho do parser PDF
logging.getLogger("pdfminer").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")


PALAVRAS_RUIDO = {
    "CATALOGO DE PRODUTOS",
    "CATÁLOGO DE PRODUTOS",
    "EDICAO 01/2024",
    "EDIÇÃO 01/2024",
    "AGUA FRIA",
    "ÁGUA FRIA",
    "AGUA QUENTE",
    "ÁGUA QUENTE",
    "ESGOTO",
    "ESGOTO SERIE REFORCADA",
    "ESGOTO SÉRIE REFORÇADA",
    "ELETRICA",
    "ELÉTRICA",
    "ACESSORIOS",
    "ACESSÓRIOS",
    "CÓD.",
    "COD.",
    "BITOLA(MM)",
    "BITOLA(MM X POL.)",
    "BITOLA(MM X POL)",
    "BITOLA(POL.)",
    "BITOLA(DN)",
    "EMBAL.",
    "PRODUTO",
    "NUEVO",
}


PALAVRAS_TITULO_RELEVANTES = [
    "TUBO",
    "SOLDAVEL",
    "SOLDÁVEL",
    "ROSCAVEL",
    "ROSCÁVEL",
    "ADAPTADOR",
    "BUCHA",
    "LUVA",
    "CAP",
    "CURVA",
    "JOELHO",
    "TE",
    "TÊ",
    "UNIAO",
    "UNIÃO",
    "REGISTRO",
    "VALVULA",
    "VÁLVULA",
    "REDUCAO",
    "REDUÇÃO",
    "TRANSICAO",
    "TRANSIÇÃO",
]


def remover_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto or ""))
        if unicodedata.category(c) != "Mn"
    )


def normalizar_texto(texto: str) -> str:
    texto = remover_acentos(texto).upper()
    texto = texto.replace("”", '"').replace("“", '"').replace("′", "'")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def limpar_codigo(codigo: str) -> str:
    codigo = re.sub(r"\D", "", str(codigo or ""))
    return codigo.zfill(4) if codigo else ""


def linha_eh_ruido(texto: str) -> bool:
    t = normalizar_texto(texto)

    if not t:
        return True

    if t in PALAVRAS_RUIDO:
        return True

    if re.match(r"^\d+\s*$", t):
        return True

    if re.match(r"^\d+\s+\d+\s*$", t):
        return True

    if t.startswith("*"):
        return True

    if "VENTA MEDIANTE CONSULTA" in t:
        return True

    if "VENDA SOB CONSULTA" in t:
        return True

    return False


def linha_eh_cabecalho_tabela(texto: str) -> bool:
    t = normalizar_texto(texto)
    return "COD" in t and "BITOLA" in t and "EMBAL" in t


def linha_eh_codigo(texto: str) -> bool:
    t = texto.strip()
    return bool(re.match(r"^\d{3,4}\s+", t))


def tem_cara_de_titulo(texto: str) -> bool:
    t = normalizar_texto(texto)

    if linha_eh_ruido(t):
        return False

    if linha_eh_cabecalho_tabela(t):
        return False

    if linha_eh_codigo(t):
        return False

    if len(t) < 3:
        return False

    return any(p in t for p in PALAVRAS_TITULO_RELEVANTES)


def extrair_bitola_mm(bitola_original: str):
    t = normalizar_texto(bitola_original).replace(",", ".")

    m = re.search(r"\bDN\s*(\d+(?:\.\d+)?)\b", t)
    if m:
        return float(m.group(1))

    m = re.match(r"(\d+(?:\.\d+)?)\s*X\s*(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1))

    m = re.match(r"(\d+(?:\.\d+)?)\s*X\s*[\d\./\"]+", t)
    if m:
        return float(m.group(1))

    m = re.match(r"(\d+(?:\.\d+)?)$", t)
    if m:
        return float(m.group(1))

    return None


def extrair_bitola_pol(bitola_original: str):
    t = normalizar_texto(bitola_original)

    m = re.search(r'(\d+(?:\.\d+)?(?:/\d+)?)"', t)
    if m:
        return m.group(1)

    m = re.search(r"\b(\d+(?:\.\d+)?/\d+)\b", t)
    if m:
        return m.group(1)

    return None


def extrair_comprimento_do_titulo(titulo_bloco: str):
    t = normalizar_texto(titulo_bloco).replace(",", ".")
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*M\b", t)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def inferir_secao_catalogo(texto_pagina: str):
    t = normalizar_texto(texto_pagina)

    if "AGUA FRIA" in t:
        return "AGUA FRIA"
    if "AGUA QUENTE" in t:
        return "AGUA QUENTE"
    if "ESGOTO SERIE REFORCADA" in t:
        return "ESGOTO SERIE REFORCADA"
    if "ESGOTO" in t:
        return "ESGOTO"
    if "ELETRICA" in t:
        return "ELETRICA"
    if "ACESSORIOS" in t:
        return "ACESSORIOS"

    return None


def agrupar_linhas_por_y(pagina):
    palavras = pagina.extract_words(
        x_tolerance=2,
        y_tolerance=2,
        keep_blank_chars=False,
        use_text_flow=False
    )

    grupos = defaultdict(list)

    for w in palavras:
        y = round(float(w["top"]), 1)
        grupos[y].append(w)

    linhas = []

    for y in sorted(grupos.keys()):
        itens = sorted(grupos[y], key=lambda x: x["x0"])
        texto = " ".join(i["text"] for i in itens).strip()

        if not texto:
            continue

        x0 = min(i["x0"] for i in itens)
        x1 = max(i["x1"] for i in itens)

        linhas.append({
            "y": y,
            "x0": x0,
            "x1": x1,
            "texto": texto
        })

    return linhas


def parse_linha_codigo(texto: str):
    t = re.sub(r"\s+", " ", texto.strip())

    m = re.match(r"^(\d{3,4})\s+(.+?)\s+([\d\.\/]+)$", t)
    if not m:
        return None

    codigo = limpar_codigo(m.group(1))
    bitola_original = m.group(2).strip()
    embalagem = m.group(3).strip()

    return {
        "codigo_krona": codigo,
        "bitola_original": bitola_original,
        "embalagem": embalagem,
    }


def extrair_titulo_para_linha(linhas, idx_codigo):
    """
    Pega linhas logo acima da linha de código até encontrar o cabeçalho da tabela.
    """
    partes = []
    encontrou_cabecalho = False

    for j in range(idx_codigo - 1, -1, -1):
        txt = linhas[j]["texto"]

        if linha_eh_codigo(txt):
            break

        if linha_eh_cabecalho_tabela(txt):
            encontrou_cabecalho = True
            continue

        if not encontrou_cabecalho:
            continue

        if linha_eh_ruido(txt):
            continue

        if tem_cara_de_titulo(txt):
            partes.append(txt)

        # se já começamos a capturar título e aparecer uma linha estranha, paramos
        elif partes:
            break

    partes = list(reversed(partes))

    titulo = " ".join(normalizar_texto(p) for p in partes)
    titulo = re.sub(r"\s+", " ", titulo).strip()

    if not titulo:
        return None

    # remove duplicações simples
    tokens = titulo.split()
    if len(tokens) > 2:
        dedup = []
        for tok in tokens:
            if not dedup or dedup[-1] != tok:
                dedup.append(tok)
        titulo = " ".join(dedup)

    return titulo


def montar_descricao_catalogo(familia_catalogo: str, bitola_original: str):
    familia = str(familia_catalogo or "").strip()
    bitola = str(bitola_original or "").strip()

    if familia and bitola:
        return f"{familia} - {bitola}"
    return familia or bitola


def extrair_catalogo_pdf(caminho_pdf: str):
    if not os.path.exists(caminho_pdf):
        raise FileNotFoundError(f"PDF não encontrado: {caminho_pdf}")

    registros = []

    with pdfplumber.open(caminho_pdf) as pdf:
        for numero_pagina, pagina in enumerate(pdf.pages, start=1):
            texto_pagina = pagina.extract_text() or ""
            secao = inferir_secao_catalogo(texto_pagina)

            linhas = agrupar_linhas_por_y(pagina)

            for idx, linha in enumerate(linhas):
                texto = linha["texto"]

                if not linha_eh_codigo(texto):
                    continue

                dados = parse_linha_codigo(texto)
                if not dados:
                    continue

                familia_catalogo = extrair_titulo_para_linha(linhas, idx)

                if not familia_catalogo:
                    continue

                descricao_catalogo = montar_descricao_catalogo(
                    familia_catalogo,
                    dados["bitola_original"]
                )

                comprimento_m = extrair_comprimento_do_titulo(familia_catalogo)
                bitola_mm = extrair_bitola_mm(dados["bitola_original"])
                bitola_pol = extrair_bitola_pol(dados["bitola_original"])
                enriquecido = enriquecer_descricao(descricao_catalogo)

                registros.append({
                    "pagina_catalogo": numero_pagina,
                    "secao_catalogo": secao,
                    "familia_catalogo": familia_catalogo,
                    "codigo_krona": dados["codigo_krona"],
                    "bitola_original": dados["bitola_original"],
                    "embalagem": str(dados["embalagem"]),
                    "descricao_catalogo": descricao_catalogo,
                    "comprimento_m": comprimento_m,
                    "bitola_mm": bitola_mm,
                    "bitola_pol": bitola_pol,
                    **enriquecido
                })

    df = pd.DataFrame(registros)

    if not df.empty:
        df = df.drop_duplicates(
            subset=["codigo_krona", "familia_catalogo", "bitola_original"]
        ).reset_index(drop=True)

    return df


def salvar_csv(df: pd.DataFrame, caminho_saida: str):
    os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)

    # força texto para evitar Excel converter embalagem em data
    if "embalagem" in df.columns:
        df["embalagem"] = df["embalagem"].astype(str)

    df.to_csv(caminho_saida, index=False, sep=";", encoding="utf-8-sig")


if __name__ == "__main__":
    df = extrair_catalogo_pdf(CAMINHO_PDF)

    print("\n=== RESUMO EXTRAÇÃO CATÁLOGO ===")
    print(f"Total de registros: {len(df)}")

    if not df.empty:
        print("\n=== PRIMEIRAS LINHAS ===")
        print(df.head(30).to_string(index=False))

    salvar_csv(df, CAMINHO_SAIDA_CSV)

    print("\nArquivo salvo em:")
    print(CAMINHO_SAIDA_CSV)