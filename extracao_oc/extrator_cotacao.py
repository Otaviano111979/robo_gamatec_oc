# -*- coding: utf-8 -*-
"""
extracao_oc/extrator_cotacao.py

Extração de itens de Cotações de Preços (documentos que chegam SEM preço,
cujo objetivo é gerar a planilha para o sistema cotar).

Deteta o layout pela estrutura da tabela, não pelo sistema do cliente:
  SIENGE_BLOCOS — tabela repetida por item: Código | Descrição | ... | Quantidade | Unidade
  UAU_COLETA   — Item | Insumo | Descrição | Unid | Quant + colunas de fornecedor
  LISTA_SIMPLES— Nº | Descrição | Unid | Quant (sem título nem sistema)

Cada item devolvido usa o contrato do pipeline:
  codigo_cliente, descricao, quantidade, unidade, data_entrega
Sem preços: cotação não traz preço por definição.
"""

import re

import pdfplumber

LAYOUT_SIENGE_BLOCOS = "SIENGE_BLOCOS"
LAYOUT_UAU_COLETA = "UAU_COLETA"
LAYOUT_LISTA_SIMPLES = "LISTA_SIMPLES"

_CLIENTE_MARCADORES = ("cooperativa", "construtora", "incorporadora", "engenharia", "spe")
_RE_CLIENTE = re.compile(r"\b(?:" + "|".join(_CLIENTE_MARCADORES) + r")\b", re.IGNORECASE)


def _txt(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def _num(valor) -> float:
    if valor is None or valor == "":
        return 0.0
    # Células estreitas quebram o número em duas linhas ("1.100,00000" + "0").
    texto = re.sub(r"\s+", "", str(valor))
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except Exception:
        return 0.0


def _cabecalho(tabela) -> list:
    return [_txt(c).lower() for c in (tabela[0] if tabela else [])]


def _detectar_layout_pagina(tabelas) -> str:
    """O cabeçalho pode não ser a primeira linha da tabela (título/obra antes)."""
    for tabela in tabelas or []:
        for row in (tabela or [])[:40]:
            c = [_txt(x).lower() for x in (row or [])]
            if len(c) < 2:
                continue
            if c[0] in ("código", "codigo") and "descri" in c[1]:
                return LAYOUT_SIENGE_BLOCOS
            if "insumo" in c and any("quant" in x for x in c):
                return LAYOUT_UAU_COLETA
            if any("descri" in x for x in c) and any("quant" in x for x in c) \
                    and any(x.startswith("unid") or x == "un." for x in c):
                return LAYOUT_LISTA_SIMPLES
    return ""


def detectar_layout_cotacao(caminho: str) -> str:
    try:
        with pdfplumber.open(caminho) as pdf:
            for page in pdf.pages:
                layout = _detectar_layout_pagina(page.extract_tables() or [])
                if layout:
                    return layout
    except Exception:
        return ""
    return ""


def _cabecalho_bloco(c) -> tuple:
    """Devolve (i_qtd, i_un) se a linha for cabeçalho de bloco de itens."""
    if len(c) < 3 or c[0] not in ("código", "codigo") or "descri" not in c[1]:
        return None
    i_qtd = next((k for k, v in enumerate(c) if "quantidade" in v), None)
    i_un = next((k for k, v in enumerate(c) if v.startswith("unid") or v == "un."), None)
    if i_qtd is None or i_un is None:
        return None
    return i_qtd, i_un


def _itens_por_cabecalho(tabelas) -> list:
    """Cobre dois variantes do Sienge:

    - cabeçalho repetido por item (EBM): 1 linha de dados por cabeçalho;
    - cabeçalho único e várias linhas (Bela Mares): todos os itens seguem.
    """
    itens = []
    for tabela in tabelas:
        indices = []
        for i, row in enumerate(tabela):
            idx = _cabecalho_bloco([_txt(x).lower() for x in row])
            if idx:
                indices.append((i, idx[0], idx[1]))
        for pos, (inicio, i_qtd, i_un) in enumerate(indices):
            fim = indices[pos + 1][0] if pos + 1 < len(indices) else len(tabela)
            for i in range(inicio + 1, fim):
                d = [_txt(x) for x in tabela[i]]
                if len(d) <= max(i_qtd, i_un) or not re.fullmatch(r"\d{1,5}", d[0] or ""):
                    continue
                quantidade = _num(d[i_qtd])
                if quantidade <= 0:
                    continue

                data_entrega = ""
                for j in range(i + 1, min(i + 4, len(tabela))):
                    extra = [_txt(x) for x in tabela[j]]
                    if extra and re.match(r"^\d{2}/\d{2}/\d{4}", extra[0]):
                        data_entrega = extra[0].split(" - ")[0].strip()
                        break

                itens.append({
                    "codigo_cliente": d[0],
                    "descricao": d[1],
                    "quantidade": quantidade,
                    "unidade": (d[i_un] or "UN").upper(),
                    "data_entrega": data_entrega,
                })
    return itens


def _unidade(txt: str) -> str:
    u = _txt(txt).upper().rstrip(".")
    return {"PÇ": "PC", "PC": "PC", "UNID": "UN", "UND": "UN", "UN": "UN",
            "M²": "M2", "M³": "M3"}.get(u, u or "UN")


def _itens_lista_simples(tabelas) -> tuple:
    """Nº | Descrição | Unid | Quant — o número pode faltar na linha.

    Devolve (itens, linhas descartadas por não terem quantidade).
    """
    itens = []
    sem_quantidade = 0
    for tabela in tabelas:
        colunas = None
        for row in tabela:
            c = [_txt(x).lower() for x in (row or [])]
            if "descri" in " ".join(c) and any("quant" in x for x in c) \
                    and any(x.startswith("unid") or x == "un." for x in c):
                colunas = {
                    "num": next((k for k, v in enumerate(c) if v in ("nº", "n°", "no", "n")), None),
                    "desc": next((k for k, v in enumerate(c) if "descri" in v), None),
                    "un": next((k for k, v in enumerate(c) if v.startswith("unid") or v == "un."), None),
                    "qtd": next((k for k, v in enumerate(c) if "quant" in v), None),
                }
                continue
            if not colunas:
                continue

            linha = [_txt(x) for x in (row or [])]
            if len(linha) <= max(v for v in colunas.values() if v is not None):
                continue
            descricao = linha[colunas["desc"]]
            quantidade = _num(linha[colunas["qtd"]])
            if not descricao:
                continue
            if quantidade <= 0:
                sem_quantidade += 1
                continue

            numero = linha[colunas["num"]] if colunas["num"] is not None else ""
            itens.append({
                "codigo_cliente": numero,
                "descricao": descricao,
                "quantidade": quantidade,
                "unidade": _unidade(linha[colunas["un"]]),
                "data_entrega": "",
            })
    return itens, sem_quantidade


_RE_CAUDA_DESCRICAO = re.compile(
    r"\s*(?:Dever[ãa]o ser|a NF o certificado|juntamente com a NF|"
    r"dos fabricantes/fornecedores|Programa Setorial)",
    re.IGNORECASE,
)


def _limpar_descricao_uau(texto: str) -> str:
    """A célula de descrição arrasta a nota de rodapé do PSQ."""
    return _RE_CAUDA_DESCRICAO.split(texto)[0].strip(" ,;-.")


def _itens_uau_coleta(tabelas) -> tuple:
    """Item | Insumo | Descrição | Unid | Quant + colunas de fornecedor.

    O mesmo relatório sai em duas variantes:
      - com coluna Item: o cabeçalho do início de cada página repete o último
        item da página anterior (célula mesclada) — deduplicação pelo nº;
      - sem coluna Item (a tabela começa no Insumo): deduplicação por
        insumo + quantidade, que é o que o cabeçalho repetido duplicaria.
    Devolve (itens, linhas descartadas por não terem quantidade).
    """
    itens = []
    vistos = set()
    sem_quantidade = 0
    for tabela in tabelas:
        colunas = None
        for row in tabela:
            c = [_txt(x).lower() for x in (row or [])]
            if any("insumo" in x for x in c) and any("quant" in x for x in c):
                colunas = {
                    "item": next((k for k, v in enumerate(c) if v.startswith("item")), None),
                    "insumo": next((k for k, v in enumerate(c) if "insumo" in v), None),
                    "desc": next((k for k, v in enumerate(c) if "descri" in v), None),
                    "un": next((k for k, v in enumerate(c) if v.startswith("unid")), None),
                    "qtd": next((k for k, v in enumerate(c) if "quant" in v), None),
                }
                if any(colunas[k] is None for k in ("insumo", "desc", "un", "qtd")):
                    colunas = None
                continue
            if not colunas:
                continue

            linha = [_txt(x) for x in (row or [])]
            if len(linha) <= max(colunas["qtd"], colunas["un"], colunas["desc"]):
                continue
            insumo = linha[colunas["insumo"]]
            descricao = _limpar_descricao_uau(linha[colunas["desc"]])
            if not descricao or not insumo:
                continue
            numero = linha[colunas["item"]] if colunas["item"] is not None else ""
            if numero and not re.fullmatch(r"\d{1,4}", numero):
                continue
            quantidade = _num(linha[colunas["qtd"]])
            if quantidade <= 0:
                sem_quantidade += 1
                continue
            chave = numero or f"{insumo}|{quantidade}"
            if chave in vistos:
                continue
            vistos.add(chave)
            itens.append({
                "codigo_cliente": insumo,
                "descricao": descricao,
                "quantidade": quantidade,
                "unidade": _unidade(linha[colunas["un"]]),
                "data_entrega": "",
            })
    return itens, sem_quantidade


_RE_CORTE_CLIENTE = re.compile(
    r"\s*(?:N[ºo°]\s*Cota|CNPJ|Data Cota|Avenida|Av\.|Rua |Rodovia|CEP)",
    re.IGNORECASE,
)


def _limpar_cliente(texto: str) -> str:
    return _RE_CORTE_CLIENTE.split(texto)[0].strip(" -|")[:80]


def _metadados(tabelas, texto_pagina1: str) -> dict:
    """Número e cliente aparecem como células soltas no bloco de cabeçalho."""
    numero = ""
    cliente = ""
    m = re.search(r"N[ºo°]?\s*Cota[çc][ãa]o\s*:?\s*(\d{2,6})", texto_pagina1 or "", re.IGNORECASE)
    if m:
        numero = m.group(1)
    for tabela in tabelas:
        for row in (tabela or [])[:15]:
            for cell in row or []:
                s = _txt(cell)
                if not s:
                    continue
                if not numero and re.fullmatch(r"\d{4,6}", s):
                    numero = s
                if not cliente and _RE_CLIENTE.search(s) and len(s) > 8:
                    cliente = _limpar_cliente(s)
    if not cliente:
        # Na variante sem coluna Item o bloco do cliente fica fora da tabela.
        for linha in (texto_pagina1 or "").splitlines():
            if _RE_CLIENTE.search(linha) and len(linha.strip()) > 8:
                cliente = _limpar_cliente(linha)
                break
    m = re.search(r"\d{2}/\d{2}/\d{4}", texto_pagina1 or "")
    return {"numero_oc": numero, "data": m.group(0) if m else "", "cliente": cliente}


def extrair_cotacao(caminho: str) -> dict:
    """Extrai itens e metadados de uma cotação. Não calcula preço nenhum."""
    itens = []
    sem_quantidade = 0
    tabelas = []
    layout = ""
    paginas = 0
    texto_pagina1 = ""
    try:
        with pdfplumber.open(caminho) as pdf:
            paginas = len(pdf.pages)
            for indice, page in enumerate(pdf.pages):
                tabelas_pagina = page.extract_tables() or []
                tabelas.extend(tabelas_pagina)
                if not layout:
                    layout = _detectar_layout_pagina(tabelas_pagina)
                if indice == 0:
                    texto_pagina1 = page.extract_text() or ""
        if layout == LAYOUT_SIENGE_BLOCOS:
            itens = _itens_por_cabecalho(tabelas)
        elif layout == LAYOUT_LISTA_SIMPLES:
            itens, sem_quantidade = _itens_lista_simples(tabelas)
        elif layout == LAYOUT_UAU_COLETA:
            itens, sem_quantidade = _itens_uau_coleta(tabelas)
    except Exception as e:
        return {
            "ok": False,
            "erro": str(e),
            "layout": layout,
            "numero_oc": "",
            "data": "",
            "cliente": "",
            "itens": [],
            "total_itens": 0,
            "sem_quantidade": 0,
            "paginas": paginas,
        }

    meta = _metadados(tabelas, texto_pagina1)
    return {
        "ok": True,
        "layout": layout,
        "numero_oc": meta["numero_oc"],
        "data": meta["data"],
        "cliente": meta["cliente"],
        "itens": itens,
        "total_itens": len(itens),
        "sem_quantidade": sem_quantidade,
        "paginas": paginas,
    }
