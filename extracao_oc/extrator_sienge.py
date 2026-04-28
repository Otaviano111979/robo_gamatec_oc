# -*- coding: utf-8 -*-
"""
extracao_oc/extrator_sienge.py

Extrator de OC e Cotacao no formato SIENGE/STARIAN.

Suporta dois layouts de tabela de itens:

Layout A (EBM/antigo):
  Colunas: Quantidade | Un. | Insumo | Preco unitario | ... | Preco final | Total | Data

Layout B (Impulsi/Housi/novo):
  Colunas: Insumo | Quantidade | Unid. | Preco unit. | Desc | %Desc | %IPI | %Acr | Preco final | Data | Ref

A detecção do layout é feita dinamicamente pelo cabeçalho — não depende
da posição fixa das colunas.
"""

import re
import pdfplumber


def detectar_formato_sienge(caminho_pdf: str) -> bool:
    """Detecta se o PDF e no formato SIENGE/STARIAN (OC — nao cotacao)."""
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = pdf.pages[0].extract_text() or ""
            texto_lower = texto.lower()

            # rejeita cotacoes de preco — nao sao OC
            if "cotação de preços" in texto_lower or "cotacao de precos" in texto_lower:
                return False

            return "sienge" in texto_lower or "starian" in texto_lower
    except Exception:
        return False


def detectar_cotacao_sienge(caminho_pdf: str) -> bool:
    """Detecta se o PDF e uma Cotacao de Precos no formato SIENGE/STARIAN."""
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = (pdf.pages[0].extract_text() or "").lower()
            return (
                ("sienge" in texto or "starian" in texto)
                and ("cotação de preços" in texto or "cotacao de precos" in texto)
            )
    except Exception:
        return False


def _limpar_numero(valor: str) -> float:
    """Converte string de numero brasileiro para float."""
    if not valor:
        return 0.0
    try:
        limpo = str(valor).strip().replace(".", "").replace(",", ".")
        return float(limpo)
    except Exception:
        return 0.0


def _extrair_codigo_descricao(texto_insumo: str):
    """
    Extrai codigo SIENGE e descricao do campo Insumo.
    Formato: "5799 - Adesivo\\nPlastico - Para Linha CPVC\\nFrasco 850g"
    Retorna: (codigo, descricao_completa)
    """
    if not texto_insumo:
        return None, ""

    # junta linhas quebradas
    texto = " ".join(texto_insumo.splitlines()).strip()
    # normaliza espacos extras
    texto = re.sub(r"\s+", " ", texto).strip()

    # padrao: numero seguido de " - " seguido de descricao
    match = re.match(r"^(\d+)\s*-\s*(.+)$", texto)
    if match:
        codigo    = match.group(1).strip()
        descricao = match.group(2).strip()
        return codigo, descricao

    return None, texto.strip()


def _extrair_numero_pedido(tabelas: list) -> str:
    """Extrai numero do pedido/cotacao."""
    for tabela in tabelas:
        for row in tabela:
            if row and len(row) >= 2:
                chave = str(row[0]).strip().lower()
                if chave in ("pedido", "cotação", "cotacao"):
                    return str(row[1]).strip()
    return ""


def _extrair_data_pedido(tabelas: list) -> str:
    """Extrai data do pedido."""
    for tabela in tabelas:
        for row in tabela:
            if row and len(row) >= 4:
                chave = str(row[0]).strip().lower()
                if chave in ("pedido", "cotação", "cotacao"):
                    return str(row[3]).strip()
    return ""


def _extrair_cliente(tabelas: list) -> str:
    """Extrai nome do cliente do bloco de Faturamento."""
    em_faturamento = False
    for tabela in tabelas:
        for row in tabela:
            if not row:
                continue
            primeira = str(row[0]).strip().lower()
            if "faturamento" in primeira:
                em_faturamento = True
                continue
            if em_faturamento and "nome" in primeira and len(row) >= 2:
                return str(row[1]).strip()
    return ""


def _encontrar_tabela_itens(tabelas: list) -> list:
    """
    Encontra a tabela de itens pelo cabecalho.
    Aceita qualquer ordem de colunas — detecta por palavras-chave.
    """
    for tabela in tabelas:
        if not tabela:
            continue
        header = tabela[0]
        if not header:
            continue
        textos = [str(c or "").strip().lower() for c in header]
        # precisa ter pelo menos "insumo" ou "quantidade" + algo sobre preco
        tem_insumo    = any("insumo" in t for t in textos)
        tem_quantidade = any("quantidade" in t or "qtd" in t for t in textos)
        if tem_insumo and tem_quantidade:
            return tabela
    return []


def _detectar_indices_colunas(header_row: list) -> dict:
    """
    Detecta os índices das colunas pelo cabeçalho.
    Suporta Layout A (Qtd | Un | Insumo | ...) e
             Layout B (Insumo | Qtd | Unid | Preco | ...).
    Retorna dicionário com os índices encontrados.
    """
    textos = [str(c or "").strip().lower() for c in header_row]

    idx = {}

    # insumo
    idx["insumo"] = next(
        (i for i, t in enumerate(textos) if "insumo" in t), None
    )

    # quantidade
    idx["quantidade"] = next(
        (i for i, t in enumerate(textos) if "quantidade" in t or "qtd" in t), None
    )

    # unidade
    idx["unidade"] = next(
        (i for i, t in enumerate(textos) if "unid" in t or t == "un."), None
    )

    # preço unitário original
    idx["preco_unit"] = next(
        (i for i, t in enumerate(textos)
         if ("preço unit" in t or "preco unit" in t) and "final" not in t), None
    )

    # preço final (após descontos) — preferido
    idx["preco_final"] = next(
        (i for i, t in enumerate(textos)
         if "preço final" in t or "preco final" in t or
            ("final" in t and "preç" in t)), None
    )

    # preço total
    idx["preco_total"] = next(
        (i for i, t in enumerate(textos)
         if "total" in t and "sub" not in t and "insumo" not in t), None
    )

    # data de entrega/previsão
    idx["data"] = next(
        (i for i, t in enumerate(textos)
         if "data" in t or "previs" in t or "entrega" in t), None
    )

    return idx


def _processar_tabela_itens(tabela: list) -> list:
    """
    Processa a tabela de itens detectando os índices de colunas
    dinamicamente. Suporta Layout A e Layout B.
    """
    if not tabela or len(tabela) < 2:
        return []

    # detecta índices pelo cabeçalho
    idx = _detectar_indices_colunas(tabela[0])

    # fallbacks caso algum índice não seja encontrado
    i_insumo  = idx.get("insumo")    or 0
    i_qtd     = idx.get("quantidade") or 1
    i_unid    = idx.get("unidade")   or 2
    # preço: prefere final, senão unit
    i_preco   = idx.get("preco_final") or idx.get("preco_unit") or 3
    i_total   = idx.get("preco_total")
    i_data    = idx.get("data")

    itens = []
    for row in tabela[1:]:
        if not row or len(row) <= i_insumo:
            continue

        insumo_raw = str(row[i_insumo] or "").strip()
        qtd_raw    = str(row[i_qtd]    or "").strip() if len(row) > i_qtd  else ""
        unid       = str(row[i_unid]   or "").strip() if len(row) > i_unid else "UN"
        preco_raw  = str(row[i_preco]  or "").strip() if len(row) > i_preco else ""
        total_raw  = str(row[i_total]  or "").strip() if i_total and len(row) > i_total else ""
        data_raw   = str(row[i_data]   or "").strip() if i_data  and len(row) > i_data  else ""

        # pula linhas sem conteúdo
        if not insumo_raw or not qtd_raw:
            continue

        quantidade = _limpar_numero(qtd_raw)
        if quantidade == 0:
            continue

        codigo_sienge, descricao = _extrair_codigo_descricao(insumo_raw)
        if not descricao:
            continue

        preco_unitario = _limpar_numero(preco_raw)
        preco_total    = _limpar_numero(total_raw)
        if preco_total == 0 and preco_unitario > 0:
            preco_total = round(quantidade * preco_unitario, 2)

        itens.append({
            "codigo_cliente": codigo_sienge or "",
            "descricao":      descricao,
            "quantidade":     quantidade,
            "unidade":        unid.upper() or "UN",
            "preco_unitario": preco_unitario,
            "preco_total":    preco_total,
            "data_entrega":   data_raw,
        })

    return itens


def extrair_oc_sienge(caminho_pdf: str) -> dict:
    """
    Extrai itens de uma OC no formato SIENGE.
    Suporta Layout A (EBM) e Layout B (Impulsi/Housi).
    Retorna dict com: numero_oc, data, cliente, formato, itens, total_itens
    """
    itens      = []
    numero_oc  = ""
    data_oc    = ""
    cliente    = ""

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            todas_tabelas        = []
            tabela_itens_global  = []

            for page in pdf.pages:
                tabelas_pagina = page.extract_tables() or []
                todas_tabelas.extend(tabelas_pagina)

                # coleta itens de CADA página (tabela de itens pode se repetir)
                tabela_pag = _encontrar_tabela_itens(tabelas_pagina)
                if tabela_pag:
                    # adiciona só as linhas de dados (pula cabeçalho repetido)
                    if not tabela_itens_global:
                        tabela_itens_global = tabela_pag
                    else:
                        # nas páginas seguintes pula o cabeçalho
                        for row in tabela_pag[1:]:
                            row_text = " ".join(str(c or "") for c in row).strip()
                            # pula se for linha de cabeçalho repetida
                            if any(k in row_text.lower() for k in ("insumo", "quantidade", "preço")):
                                continue
                            tabela_itens_global.append(row)

            # extrai metadados
            numero_oc = _extrair_numero_pedido(todas_tabelas)
            data_oc   = _extrair_data_pedido(todas_tabelas)
            cliente   = _extrair_cliente(todas_tabelas)

            # processa itens com detecção dinâmica de colunas
            if tabela_itens_global:
                itens = _processar_tabela_itens(tabela_itens_global)

    except Exception as e:
        return {
            "ok":          False,
            "erro":        str(e),
            "numero_oc":   numero_oc,
            "data":        data_oc,
            "cliente":     cliente,
            "formato":     "SIENGE",
            "itens":       [],
            "total_itens": 0,
        }

    return {
        "ok":          True,
        "numero_oc":   numero_oc,
        "data":        data_oc,
        "cliente":     cliente,
        "formato":     "SIENGE",
        "itens":       itens,
        "total_itens": len(itens),
    }


def extrair_cotacao_sienge(caminho_pdf: str) -> dict:
    """
    Extrai itens de uma Cotacao de Precos no formato SIENGE.
    Estrutura da tabela: Código | Descrição | Quantidade | Unid.
    Retorna o mesmo formato de extrair_oc_sienge para compatibilidade.
    """
    itens         = []
    numero_cotacao = ""
    data_cotacao   = ""
    cliente        = ""

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            todas_tabelas          = []
            tabela_itens_encontrada = []

            for page in pdf.pages:
                tabelas_pagina = page.extract_tables() or []
                todas_tabelas.extend(tabelas_pagina)

                if not tabela_itens_encontrada:
                    for tabela in tabelas_pagina:
                        if not tabela:
                            continue
                        header = tabela[0]
                        if not header:
                            continue
                        textos = [str(c).strip().lower() for c in header if c]
                        if "descrição" in textos and "quantidade" in textos:
                            tabela_itens_encontrada = tabela
                            break

            # extrai numero da cotacao e cliente do cabecalho
            for tabela in todas_tabelas:
                for row in tabela:
                    if not row:
                        continue
                    for cell in row:
                        cell_str = str(cell or "").strip()
                        if re.match(r"^\d{4,6}$", cell_str):
                            if not numero_cotacao:
                                numero_cotacao = cell_str
                        if any(p in cell_str.lower() for p in
                               ["cooperativa","construtora","incorporadora","engenharia","spe"]):
                            if not cliente:
                                cliente = cell_str

            texto_pagina0 = (pdf.pages[0].extract_text() or "")
            match_data = re.search(r"(\d{2}/\d{2}/\d{4})", texto_pagina0)
            if match_data:
                data_cotacao = match_data.group(1)

            if tabela_itens_encontrada:
                idx = _detectar_indices_colunas(tabela_itens_encontrada[0])
                i_cod  = idx.get("insumo")    or 0
                i_desc = next(
                    (i for i, t in enumerate(
                        [str(c or "").strip().lower() for c in tabela_itens_encontrada[0]]
                    ) if "descri" in t), 1
                )
                i_qtd  = idx.get("quantidade") or 2
                i_unid = idx.get("unidade")    or 3

                for row in tabela_itens_encontrada[1:]:
                    if not row or len(row) < 3:
                        continue

                    codigo_raw = str(row[i_cod]  or "").strip() if len(row) > i_cod  else ""
                    desc_raw   = str(row[i_desc] or "").strip() if len(row) > i_desc else ""
                    qtd_raw    = str(row[i_qtd]  or "").strip() if len(row) > i_qtd  else ""
                    unid_raw   = str(row[i_unid] or "").strip() if len(row) > i_unid else "UN"

                    if not desc_raw or not qtd_raw:
                        continue

                    quantidade = _limpar_numero(qtd_raw)
                    if quantidade == 0:
                        continue

                    itens.append({
                        "codigo_cliente": codigo_raw,
                        "descricao":      desc_raw,
                        "quantidade":     quantidade,
                        "unidade":        unid_raw.upper() or "UN",
                        "preco_unitario": 0.0,
                        "preco_total":    0.0,
                        "data_entrega":   "",
                    })

    except Exception as e:
        return {
            "ok":          False,
            "erro":        str(e),
            "numero_oc":   numero_cotacao,
            "data":        data_cotacao,
            "cliente":     cliente,
            "formato":     "SIENGE_COTACAO",
            "itens":       [],
            "total_itens": 0,
        }

    return {
        "ok":          True,
        "numero_oc":   numero_cotacao,
        "data":        data_cotacao,
        "cliente":     cliente,
        "formato":     "SIENGE_COTACAO",
        "itens":       itens,
        "total_itens": len(itens),
    }
