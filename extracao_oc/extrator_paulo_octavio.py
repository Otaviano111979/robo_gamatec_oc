# -*- coding: utf-8 -*-
"""
extrator_paulo_octavio.py — Extrator para OCs do formato Paulo Octávio / PO Empreendimentos
Identificação: "PEDIDO DE COMPRA" + "Processo Nº:" no cabeçalho
Diferencial: código Krona já vem na OC (linha "KRONA CÓD.XXXX")
"""

import re
import pdfplumber
from typing import List, Dict


# Regex para identificar linha de item.
# Ex: "23445 8,00 UN QUADRO DISTRIBUIÇÃO 36D/27N DE EMBUTIR BRANCO 00862 345,110 0,00 0,0 2.760,88"
PADRAO_ITEM = re.compile(
    r"^(?P<nrm>\d{4,6})\s+"
    r"(?P<quantidade>[\d.,]+)\s+"
    r"(?P<unidade>UN|M|MT|BR|PC|CX|KG|RL|UND)\s+"
    r"(?P<descricao>.+?)\s+"
    r"(?P<cod_interno>\d{4,6})\s+"
    r"(?P<valor_unitario>[\d.,]+)\s+"
    r"[\d.,]+\s+"   # desconto
    r"[\d.,]+\s+"   # ICMS
    r"[\d.,]+\s+"   # IPI
    r"(?P<valor_total>[\d.,]+)$",
    re.IGNORECASE
)

# Regex para linha com código Krona.
# Ex: "KRONA CÓD.1281" ou "KRONA COD. 1281"
PADRAO_KRONA = re.compile(
    r"KRONA\s+C[ÓO]D\.?\s*(?P<codigo_krona>\d+)",
    re.IGNORECASE
)


def _numero_br_para_float(texto: str) -> float:
    try:
        texto = str(texto or "").strip()
        texto = texto.replace(".", "").replace(",", ".")
        return float(texto)
    except Exception:
        return 0.0


def detectar_formato_paulo_octavio(texto_pdf: str) -> bool:
    """Retorna True se o PDF é do formato Paulo Octávio."""
    upper = texto_pdf.upper()
    return (
        "PEDIDO DE COMPRA" in upper
        and "PROCESSO" in upper
        and (
            "PAULO OCTAVIO" in upper
            or "PAULOOCTAVIO" in upper
            or "PO EMPREENDIMENTOS" in upper
            or "PO 827" in upper
        )
    )


def extrair_itens(caminho_pdf: str) -> List[Dict]:
    """Extrai itens de OC no formato Paulo Octávio."""
    itens: List[Dict] = []
    idx = 1

    with pdfplumber.open(caminho_pdf) as pdf:
        linhas_todas = []
        for page in pdf.pages:
            texto = page.extract_text() or ""
            linhas_todas.extend(texto.split("\n"))

    i = 0
    while i < len(linhas_todas):
        linha = linhas_todas[i].strip()
        match_item = PADRAO_ITEM.match(linha)

        if match_item:
            qtd = _numero_br_para_float(match_item.group("quantidade"))
            v_unit = _numero_br_para_float(match_item.group("valor_unitario"))
            v_total = _numero_br_para_float(match_item.group("valor_total"))

            item: Dict = {
                "idx_item": idx,
                "codigo_interno_oc": match_item.group("nrm"),
                "descricao_original": match_item.group("descricao").strip(),
                "descricao_reconstruida": match_item.group("descricao").strip(),
                "quantidade": qtd,
                "unidade_original": match_item.group("unidade").upper(),
                "unidade_normalizada": match_item.group("unidade").upper(),
                "valor_unitario": v_unit,
                "valor_total": v_total,
                "pagina": 1,
                "score_extracao": 0.95,
                "status_extracao": "ok",
                "observacoes": ["formato_paulo_octavio"],
                "codigo_krona_oc": None,
            }

            # se quantidade veio como 0 mas os valores financeiros são coerentes, recalcula
            if (qtd or 0) == 0 and v_unit and v_total:
                try:
                    qtd_calc = round(v_total / v_unit, 4)
                    if qtd_calc > 0:
                        item["quantidade"] = qtd_calc
                        item["observacoes"].append("quantidade_recalculada_por_total_unitario")
                except Exception:
                    pass

            # verifica linha seguinte para código Krona
            if i + 1 < len(linhas_todas):
                proxima = linhas_todas[i + 1].strip()
                match_krona = PADRAO_KRONA.match(proxima)
                if match_krona:
                    item["codigo_krona_oc"] = match_krona.group("codigo_krona")
                    item["observacoes"].append("codigo_krona_na_oc")
                    item["score_extracao"] = 0.99
                    i += 1  # pula linha do código Krona

            itens.append(item)
            idx += 1

        i += 1

    return itens
