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


def _detectar_colunas_uau(header_row: list) -> dict:
    """
    Detecta indices das colunas pelo cabecalho da tabela UAU.
    Funciona para GPL, City Inc e qualquer variacao do layout UAU.
    """
    col = {"idx": 0, "desc": 1, "un": -1, "qtd": -1, "preco": -1, "total": -1}
    for i, cell in enumerate(header_row):
        v = _limpar_celula(cell).lower()
        if v in ("item",):
            col["idx"] = i
        elif v in ("descricao", "descrição", "description"):
            col["desc"] = i
        elif v in ("un.", "un", "und", "unidade"):
            col["un"] = i
        elif v in ("qtde", "qtd", "qtd.", "quantidade"):
            col["qtd"] = i
        elif v in ("preco unit.", "preço unit.", "preco unitario", "preço unitário", "vl. unit.", "r$ unit.", "valor unitario"):
            col["preco"] = i
        elif v in ("total", "vl. total", "r$ total", "valor total"):
            col["total"] = i
    return col


def extrair_linhas_pdf_uau(caminho_pdf: str):
    """
    Extrator para PDFs do sistema UAU (GPL, City Inc e similares).
    Detecta colunas dinamicamente pelo cabecalho — funciona com qualquer
    variacao de layout do UAU.
    """
    import pdfplumber
    from extracao_oc.modelos import LinhaDocumento

    linhas_extraidas = []
    numero_linha_global = 0

    with pdfplumber.open(caminho_pdf) as pdf:
        for numero_pagina, pagina in enumerate(pdf.pages, start=1):
            tabelas = pagina.extract_tables()

            for tabela in tabelas:
                if not tabela or len(tabela) < 2:
                    continue

                # detecta cabecalho de itens em qualquer linha da tabela
                col = None
                inicio_dados = 0
                for i, row in enumerate(tabela):
                    textos = [_limpar_celula(c).lower() for c in (row or [])]
                    if "item" in textos and any(t in textos for t in ("descricao", "descrição", "qtde", "qtd")):
                        col = _detectar_colunas_uau(row)
                        inicio_dados = i + 1
                        break

                if not col:
                    continue

                for row in tabela[inicio_dados:]:
                    if not row:
                        continue

                    idx = _limpar_celula(row[col["idx"]]) if col["idx"] < len(row) else ""

                    # idx deve ser numerico para ser item valido
                    if not idx or not _re.sub(r'[^0-9]', '', idx):
                        continue

                    descricao = ""
                    # descricao pode estar espalhada em multiplas colunas
                    if col["desc"] < len(row):
                        descricao = _limpar_celula(row[col["desc"]])
                        # se colunas seguintes forem vazias mas a descricao continuar
                        # em merged cells (common no City), une as colunas
                        if not descricao:
                            for j in range(col["desc"]+1, min(col["desc"]+5, len(row))):
                                v = _limpar_celula(row[j])
                                if v and col.get("un", -1) != j and col.get("qtd", -1) != j:
                                    descricao = v
                                    break

                    unidade = _limpar_celula(row[col["un"]]) if col["un"] >= 0 and col["un"] < len(row) else ""
                    qtd_raw = _limpar_celula(row[col["qtd"]]) if col["qtd"] >= 0 and col["qtd"] < len(row) else ""
                    preco   = _limpar_celula(row[col["preco"]]) if col["preco"] >= 0 and col["preco"] < len(row) else ""
                    total   = _limpar_celula(row[col["total"]]) if col["total"] >= 0 and col["total"] < len(row) else ""

                    if not descricao or not qtd_raw:
                        continue

                    texto = f"{idx} {descricao} {unidade} {qtd_raw} {preco} {total}".strip()

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


def _e_linha_item_brasal(row: list) -> bool:
    """Verifica se a linha e um item valido no formato Brasal/Closer."""
    if not row or len(row) < 4:
        return False
    codigo = _limpar_celula(row[0])
    qtd    = _limpar_celula(row[1])
    un     = _limpar_celula(row[2])
    desc   = _limpar_celula(row[3])
    # codigo deve ser numerico (ex: "8.926" → "8926")
    cod_limpo = _re.sub(r'[.\s]', '', codigo)
    if not cod_limpo.isdigit():
        return False
    # unidade deve ser conhecida
    if un.upper() not in ('M', 'MT', 'UN', 'UND', 'RL', 'BR', 'KG', 'CX', 'PC', 'L', 'LT'):
        return False
    # descricao nao pode ser vazia
    if not desc or desc.upper() in ('KRONA/KRONA', 'DESCRIÇÃO DO PRODUTO', ''):
        return False
    return True


def _limpar_codigo_brasal(codigo: str) -> str:
    """Remove pontos de milhar do codigo: '8.926' → '8926'."""
    return _re.sub(r'[.\s]', '', codigo.strip())


def extrair_linhas_pdf_brasal(caminho_pdf: str):
    """
    Extrator para PDFs do formato Brasal/Closer (INC 27 BRASAL).
    Usa extract_tables() — codigo Krona ja vem na OC.
    Estrutura: [codigo, qtd, unidade, descricao, preco_unit, desconto, icms, ipi, total]
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
                    if not row or not _e_linha_item_brasal(row):
                        continue

                    codigo_raw = _limpar_celula(row[0])
                    qtd_raw    = _limpar_celula(row[1])
                    un         = _limpar_celula(row[2])

                    # descricao pode ter quebras de linha com NBR e KRONA/KRONA
                    # ex: "TUBO PVC ESGOTO SERIE R Ø100MM NBR\n5.688\nKRONA/KRONA"
                    desc_raw = _limpar_celula(row[3]) if len(row) > 3 else ""
                    # remove linha KRONA/KRONA e numero de norma solto
                    desc_limpa = _re.sub(r'KRONA/KRONA', '', desc_raw, flags=_re.IGNORECASE)
                    desc_limpa = _re.sub(r'\b\d{1,2}\.\d{3}\b', '', desc_limpa)  # ex: "5.688" solto
                    desc_limpa = _re.sub(r'[\n\r]+', ' ', desc_limpa).strip()
                    desc_limpa = _re.sub(r'\s+', ' ', desc_limpa).strip()

                    # layout varia por pagina:
                    # pagina 1: 9 colunas  → preco=col[4], total=col[8]
                    # pagina 2: 12 colunas → preco=col[6], total=col[11]
                    ncols = len(row)
                    if ncols >= 12:
                        preco_unit = _limpar_celula(row[6])
                        total      = _limpar_celula(row[11])
                    else:
                        preco_unit = _limpar_celula(row[4]) if ncols > 4 else ""
                        total      = _limpar_celula(row[8]) if ncols > 8 else ""

                    codigo_krona = _limpar_codigo_brasal(codigo_raw)

                    # monta texto no formato que o estruturador reconhece
                    texto = f"{codigo_krona} {un} {qtd_raw} {desc_limpa} {preco_unit} {total}".strip()

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
