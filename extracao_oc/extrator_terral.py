# -*- coding: utf-8 -*-
"""Extrator do layout Terral/SPE (PEDIDO DE COMPRA).

O PDF tem a descricao em duas linhas a direita e colunas fixas: item, codigo
alternativo, quantidade, unidade, valor unitario e valor total. O extrator
generico perde a primeira pagina e nao le o valor unitario; aqui lemos as
palavras por coordenadas e reconstruimos cada linha.

Deteccao por marcadores do proprio layout (PEDIDO DE COMPRA + ALTERNATIVO +
KRONA + SPE), sem IA.
"""
import re
import unicodedata
from collections import defaultdict

try:
    import fitz
except ImportError:  # pragma: no cover - ambiente sem PyMuPDF
    fitz = None

_MARCADORES = ("PEDIDO DE COMPRA", "ALTERNATIVO", "KRONA")

# faixas x das colunas (pagina A4 de 595 pontos)
_FAIXAS = {
    "item": (0, 60),
    "codigo": (90, 140),
    "quantidade": (150, 200),
    "unidade": (205, 225),
    "valor_unitario": (425, 470),
    "valor_total": (535, 580),
}


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def _texto_limpo(texto):
    texto = str(texto or "").replace("\ufffd", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _num_br(texto):
    texto = _texto_limpo(texto).replace("R$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _coluna(colunas, nome):
    inicio, fim = _FAIXAS[nome]
    return " ".join(t for x0, _y0, t in colunas if inicio <= x0 < fim).strip()


def detectar_formato_terral(caminho_pdf):
    """True quando o PDF e o layout de PEDIDO DE COMPRA da Terral."""
    if fitz is None:
        return False
    try:
        doc = fitz.open(caminho_pdf)
        texto = "\n".join(
            doc[i].get_text() for i in range(min(2, doc.page_count)))
        doc.close()
    except Exception:
        return False
    norm = _normalizar(texto)
    return all(marcador in norm for marcador in _MARCADORES) and "SPE" in norm


def _descricao_da_linha(linhas, y):
    partes = []
    for y2 in sorted(linhas):
        if not (y - 2 <= y2 <= y + 20):
            continue
        for x0, _y0, texto in linhas[y2]:
            if not texto.startswith("=>") and 228 <= x0 < 420:
                partes.append((y2, x0, texto))
    partes.sort(key=lambda p: (p[0], p[1]))
    return _texto_limpo(" ".join(p[2] for p in partes))


def extrair_itens_terral(caminho_pdf):
    """Itens normalizados do layout Terral, na ordem do PDF."""
    if fitz is None:
        return []
    doc = fitz.open(caminho_pdf)
    itens = []
    try:
        for numero_pagina, pagina in enumerate(doc, start=1):
            linhas = defaultdict(list)
            for palavra in pagina.get_text("words"):
                x0, y0, _x1, _y1, texto = palavra[:5]
                linhas[round(y0, 1)].append((x0, y0, texto))
            for y in sorted(linhas):
                colunas = linhas[y]
                item = _coluna(colunas, "item")
                quantidade_txt = _coluna(colunas, "quantidade")
                if not re.fullmatch(r"\d{3,6}", item) or not quantidade_txt:
                    continue
                quantidade = _num_br(quantidade_txt)
                valor_unitario = _num_br(_coluna(colunas, "valor_unitario"))
                valor_total = _num_br(_coluna(colunas, "valor_total"))
                if not quantidade or quantidade <= 0:
                    continue
                codigo = _coluna(colunas, "codigo")
                descricao = _descricao_da_linha(linhas, y)
                if not descricao:
                    continue
                itens.append({
                    "idx_item": str(len(itens) + 1).zfill(5),
                    "codigo_interno_oc": codigo,
                    "codigo_cliente": codigo,
                    "descricao_original": descricao,
                    "descricao_reconstruida": descricao,
                    "quantidade": quantidade,
                    "quantidade_oc": quantidade,
                    "unidade_original": _coluna(colunas, "unidade") or "UN",
                    "unidade_normalizada": _coluna(colunas, "unidade") or "UN",
                    "valor_unitario": valor_unitario,
                    "preco_unitario": valor_unitario,
                    "valor_total": valor_total,
                    "preco_total": valor_total,
                    "pagina": numero_pagina,
                    "score_extracao": 0.99,
                    "status_extracao": "extraido",
                    "observacoes": ["formato_terral"],
                })
    finally:
        doc.close()
    return itens
