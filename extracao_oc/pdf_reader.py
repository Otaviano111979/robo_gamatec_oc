from typing import List
import pdfplumber

from extracao_oc.modelos import LinhaDocumento


def extrair_linhas_pdf(caminho_pdf: str) -> List[LinhaDocumento]:
    linhas_extraidas: List[LinhaDocumento] = []

    with pdfplumber.open(caminho_pdf) as pdf:
        for numero_pagina, pagina in enumerate(pdf.pages, start=1):
            texto = pagina.extract_text() or ""

            if not texto.strip():
                continue

            linhas = texto.splitlines()

            for numero_linha, linha in enumerate(linhas, start=1):
                linha_limpa = linha.rstrip()

                if not linha_limpa.strip():
                    continue

                linhas_extraidas.append(
                    LinhaDocumento(
                        pagina=numero_pagina,
                        numero_linha=numero_linha,
                        texto_original=linha_limpa,
                        texto_normalizado=linha_limpa
                    )
                )

    return linhas_extraidas

# ================================================================
# EXTRATOR UAU — usa extract_tables() para PDFs do sistema UAU
# Mantido separado para nao interferir no extrator original
# ================================================================

import re as _re


def _limpar_celula(valor) -> str:
    """Limpa None, newlines e espacos de uma celula da tabela."""
    if valor is None:
        return ""
    # remove quebras de linha dentro da celula (ex: quantidade "3.000,0000\n00")
    return _re.sub(r"[\n\r]+", "", str(valor)).strip()


def _numero_br_para_float(texto: str):
    """Converte numero brasileiro para float. Retorna None se nao conseguir."""
    t = texto.strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except Exception:
        return None


def _e_linha_item_uau(row: list) -> bool:
    """Verifica se a linha da tabela e um item valido (comeca com numero inteiro)."""
    idx = _limpar_celula(row[0] if row else None)
    return bool(_re.match(r"^\d{1,4}$", idx))


def extrair_linhas_pdf_uau(caminho_pdf: str):
    """
    Extrator especifico para PDFs do sistema UAU (GPL Incorporadora e similares).
    Usa extract_tables() que preserva a estrutura de colunas corretamente.
    Retorna lista de LinhaDocumento igual ao extrator original.
    """
    import pdfplumber
    from extracao_oc.modelos import LinhaDocumento

    linhas_extraidas = []
    numero_linha_global = 0

    with pdfplumber.open(caminho_pdf) as pdf:
        for numero_pagina, pagina in enumerate(pdf.pages, start=1):
            tabelas = pagina.extract_tables()

            for tabela in tabelas:
                for row in tabela:
                    if not row or not _e_linha_item_uau(row):
                        continue

                    # colunas esperadas:
                    # [0]=idx [1]=descricao [2..5]=merged [6]=unidade [7]=marca [8]=qtd [9..10]=merged [11]=preco_unit [12]=total
                    idx        = _limpar_celula(row[0])
                    descricao  = _limpar_celula(row[1]) if len(row) > 1 else ""
                    unidade    = _limpar_celula(row[6]) if len(row) > 6 else ""
                    qtd_raw    = _limpar_celula(row[8]) if len(row) > 8 else ""
                    preco_unit = _limpar_celula(row[11]) if len(row) > 11 else ""
                    total      = _limpar_celula(row[12]) if len(row) > 12 else ""

                    # monta texto normalizado no formato que o estruturador UAU espera:
                    # "idx descricao unidade quantidade preco_unit total"
                    texto = f"{idx} {descricao} {unidade} {qtd_raw} {preco_unit} {total}".strip()

                    numero_linha_global += 1
                    linhas_extraidas.append(
                        LinhaDocumento(
                            pagina=numero_pagina,
                            numero_linha=numero_linha_global,
                            texto_original=texto,
                            texto_normalizado=texto
                        )
                    )

    return linhas_extraidas
