# -*- coding: utf-8 -*-
"""
extracao_oc/extrator_sienge.py

Extrator de OC no formato SIENGE/STARIAN.
Usado por: EBM Incorporacoes e qualquer cliente que use o sistema SIENGE.

Estrutura do PDF:
- Tabela 2: numero do pedido e data
- Tabela 4: dados do cliente (faturamento)
- Tabela 6: itens da OC
  Colunas: Quantidade | Un. | Insumo | Preco unitario | ... | Preco unit. final | Preco total | Dt. entrega
  Insumo: "CODIGO - Descricao\ncontinuacao da descricao"
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


def _limpar_numero(valor: str) -> float:
    """Converte string de numero brasileiro para float."""
    if not valor:
        return 0.0
    try:
        # remove pontos de milhar e troca virgula por ponto
        limpo = str(valor).strip().replace(".", "").replace(",", ".")
        return float(limpo)
    except Exception:
        return 0.0


def _extrair_codigo_descricao(texto_insumo: str):
    """
    Extrai codigo SIENGE e descricao do campo Insumo.
    Formato: "5799 - Adesivo\nPlastico - Para Linha CPVC\nFrasco 850g"
    Retorna: (codigo, descricao_completa)
    """
    if not texto_insumo:
        return None, ""

    # junta linhas quebradas
    texto = " ".join(texto_insumo.splitlines()).strip()

    # padrao: numero seguido de " - " seguido de descricao
    match = re.match(r"^(\d+)\s*-\s*(.+)$", texto)
    if match:
        codigo = match.group(1).strip()
        descricao = match.group(2).strip()
        return codigo, descricao

    return None, texto.strip()


def _extrair_numero_pedido(tabelas: list) -> str:
    """Extrai numero do pedido da Tabela 2."""
    for tabela in tabelas:
        for row in tabela:
            if row and len(row) >= 2:
                if str(row[0]).strip().lower() == "pedido":
                    return str(row[1]).strip()
    return ""


def _extrair_data_pedido(tabelas: list) -> str:
    """Extrai data do pedido da Tabela 2."""
    for tabela in tabelas:
        for row in tabela:
            if row and len(row) >= 4:
                if str(row[0]).strip().lower() == "pedido":
                    return str(row[3]).strip()
    return ""


def _extrair_cliente(tabelas: list) -> str:
    """Extrai nome do cliente da Tabela 4 (Faturamento)."""
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
    Encontra a tabela de itens (Tabela 6) pelo cabecalho.
    Cabecalho esperado: Quantidade | Un. | Insumo | Preco unitario | ...
    """
    for tabela in tabelas:
        if not tabela:
            continue
        header = tabela[0]
        if not header:
            continue
        textos = [str(c).strip().lower() for c in header if c]
        if "quantidade" in textos and "insumo" in textos:
            return tabela
    return []


def extrair_oc_sienge(caminho_pdf: str) -> dict:
    """
    Extrai itens de uma OC no formato SIENGE/EBM.
    Retorna dict com: numero_oc, data, cliente, formato, itens, total_itens
    """
    itens = []
    numero_oc = ""
    data_oc = ""
    cliente = ""

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            # coleta todas as tabelas de todas as paginas
            # (cabecalho e rodape se repetem, itens so na pag 1)
            todas_tabelas = []
            tabela_itens_encontrada = []

            for page in pdf.pages:
                tabelas_pagina = page.extract_tables() or []
                todas_tabelas.extend(tabelas_pagina)

                # procura tabela de itens apenas se ainda nao encontrou
                if not tabela_itens_encontrada:
                    tabela_itens_encontrada = _encontrar_tabela_itens(tabelas_pagina)

            # extrai metadados
            numero_oc = _extrair_numero_pedido(todas_tabelas)
            data_oc   = _extrair_data_pedido(todas_tabelas)
            cliente   = _extrair_cliente(todas_tabelas)

            # processa itens
            if tabela_itens_encontrada:
                # pula cabecalho (linha 0)
                for row in tabela_itens_encontrada[1:]:
                    if not row or len(row) < 3:
                        continue

                    quantidade_raw = str(row[0]).strip() if row[0] else ""
                    unidade        = str(row[1]).strip() if row[1] else ""
                    insumo_raw     = str(row[2]).strip() if row[2] else ""
                    preco_unit_raw = str(row[3]).strip() if len(row) > 3 and row[3] else ""
                    preco_final_raw = str(row[8]).strip() if len(row) > 8 and row[8] else preco_unit_raw
                    preco_total_raw = str(row[9]).strip() if len(row) > 9 and row[9] else ""
                    data_entrega    = str(row[10]).strip() if len(row) > 10 and row[10] else ""

                    # pula linhas vazias
                    if not insumo_raw or not quantidade_raw:
                        continue

                    quantidade = _limpar_numero(quantidade_raw)
                    if quantidade == 0:
                        continue

                    codigo_sienge, descricao = _extrair_codigo_descricao(insumo_raw)
                    preco_unitario = _limpar_numero(preco_final_raw or preco_unit_raw)
                    preco_total    = _limpar_numero(preco_total_raw)

                    if not descricao:
                        continue

                    itens.append({
                        "codigo_cliente": codigo_sienge or "",
                        "descricao":      descricao,
                        "quantidade":     quantidade,
                        "unidade":        unidade.upper() or "UN",
                        "preco_unitario": preco_unitario,
                        "preco_total":    preco_total if preco_total > 0 else round(quantidade * preco_unitario, 2),
                        "data_entrega":   data_entrega,
                    })

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
