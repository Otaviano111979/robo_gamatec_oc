import io
import re
from decimal import Decimal

import pandas as pd
import pdfplumber


_CABECALHO = re.compile(
    r"COD\s+KRONA\s+descri[çc][ãa]o\s+VALOR\s+unit\s+qnd\s+TOTAL",
    re.IGNORECASE,
)
_INTEIRO_BR = r"(?:\d{1,3}(?:\.\d{3})+|\d+)"
_ITEM = re.compile(
    rf"(?P<codigo>\d{{1,4}})\s+(?P<descricao>.+?)\s+"
    rf"(?P<preco>{_INTEIRO_BR},\d{{2,3}})\s+"
    rf"(?P<quantidade>{_INTEIRO_BR}(?:,\d{{1,3}})?)\s+"
    rf"R\$\s+(?P<total>{_INTEIRO_BR},\d{{2}})"
)


def _decimal_br(texto: str) -> Decimal:
    return Decimal(texto.replace(".", "").replace(",", "."))


def extrair_documento_precificado(pdf_bytes: bytes) -> pd.DataFrame:
    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    except Exception as erro:
        raise ValueError("Não foi possível ler o PDF do documento precificado.") from erro

    itens = []
    codigos = set()
    with pdf:
        for pagina, page in enumerate(pdf.pages, start=1):
            texto = page.extract_text() or ""
            if not texto.strip():
                raise ValueError(f"Página {pagina} sem texto: o PDF precisa de OCR.")

            linhas = texto.splitlines()
            inicio = 0
            if pagina == 1:
                cabecalho = next(
                    (i for i, linha in enumerate(linhas) if _CABECALHO.fullmatch(linha.strip())),
                    None,
                )
                if cabecalho is None:
                    raise ValueError(
                        "Layout de documento precificado não suportado: esperado "
                        "COD KRONA, descrição, VALOR unit, qnd e TOTAL."
                    )
                if any(linha.strip() for linha in linhas[:cabecalho]):
                    raise ValueError(
                        "Conteúdo anterior ao cabeçalho do documento precificado; "
                        "a leitura foi interrompida para não omitir itens."
                    )
                inicio = cabecalho + 1

            for numero_linha, linha in enumerate(linhas[inicio:], start=inicio + 1):
                linha = linha.strip()
                if not linha or _CABECALHO.fullmatch(linha):
                    continue

                item = _ITEM.fullmatch(linha)
                if item is None:
                    raise ValueError(
                        f"Página {pagina}, linha {numero_linha}: item incompleto "
                        "ou fora do layout de documento precificado."
                    )

                codigo = str(int(item["codigo"]))
                if codigo in codigos:
                    raise ValueError(
                        f"Código Krona repetido: {codigo}, na página {pagina}; "
                        "os itens não foram agregados para comparação."
                    )

                quantidade = _decimal_br(item["quantidade"])
                if quantidade <= 0:
                    raise ValueError(
                        f"Quantidade inválida para o código {codigo}, na página {pagina}."
                    )

                codigos.add(codigo)
                itens.append({
                    "codigo_krona": codigo,
                    "descricao_krona": item["descricao"],
                    "quantidade_final": quantidade,
                    "valor_unitario_oc": _decimal_br(item["preco"]),
                    "total_documento": _decimal_br(item["total"]),
                    "pagina": pagina,
                })

    if not itens:
        raise ValueError("Nenhum item encontrado no documento precificado.")

    return pd.DataFrame(itens)
