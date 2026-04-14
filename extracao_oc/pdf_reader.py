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