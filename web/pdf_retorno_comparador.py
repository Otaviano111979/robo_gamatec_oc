# -*- coding: utf-8 -*-
"""PDF da comparação de retorno: processo guardado × orçamento Gamatec.

Reutiliza os utilitários de fonte, moeda e tabela do PDF do orçamento para
manter o mesmo visual: colunas com código Krona, preço da tabela, preço do
Gamatec e percentual de desconto, com o total no fim e o selo Vortex Sync.
"""
import os
import tempfile
from datetime import date

import fitz

from pdf_orcamento_nao_precificado import (
    _A4_RETRATO, _AMBAR, _AZUL, _BRANCO, _CINZA, _CLARO, _ESCURO,
    _FAIXA_RODAPE, _GRELHA, _MARGEM, _VERMELHO,
    _caminho_fonte, _codepoints, _encolher, _fontes, _fontes_reduzidas,
    _limpo, _moeda, _quantidade, _quebrar, _texto, _texto_centro,
    _texto_direita,
)

_FONTE = r"C:\Windows\Fonts\arial.ttf"
_FONTE_NEGRITO = r"C:\Windows\Fonts\arialbd.ttf"

_COLUNAS = (
    ("CÓD. KRONA", 48, "left"),
    ("DESCRIÇÃO", 244, "left"),
    ("QTDE", 34, "right"),
    ("PREÇO TABELA", 62, "right"),
    ("PREÇO GAMATEC", 62, "right"),
    ("% DESC.", 42, "right"),
)
_LARGURA_TABELA = sum(coluna[1] for coluna in _COLUNAS)
_LARGURA_DESC = _COLUNAS[1][1] - 6

_TEXTO_RODAPE = ("Desconto = (preço da tabela − preço do Gamatec) ÷ preço da tabela. "
                 "Preços do retorno são informativos até confirmação.")


def _percentual(valor):
    if valor is None:
        return "—"
    sinal = "−" if valor < 0 else ""
    return f"{sinal}{abs(valor):,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def _bloco_titulo(page, dados, retorno, fontes):
    regular, negrito, nome_regular, nome_negrito = fontes
    largura = _A4_RETRATO[0] - 2 * _MARGEM
    _texto(page, _MARGEM, 52, "COMPARAÇÃO DE RETORNO", nome_negrito, 17, _ESCURO)
    _texto_direita(page, _MARGEM + largura, 50, f"Data: {date.today():%d/%m/%Y}",
                   nome_regular, regular, 9, _CINZA)

    cliente = dados.get("cliente") or ""
    vigencia = dados.get("vigencia") or ""
    _texto(page, _MARGEM, 68, f"Tabela de preços: {cliente} — vigência {vigencia}",
           nome_regular, 9, _ESCURO)

    detalhe = f"Processo: {dados.get('nome_arquivo') or 'documento'}"
    if dados.get("layout"):
        detalhe += f" ({dados['layout']})"
    if dados.get("numero"):
        detalhe += f" · Nº {dados['numero']}"
    if dados.get("criado_em"):
        detalhe += f" · guardado em {dados['criado_em']}"
    _texto(page, _MARGEM, 81, _encolher(detalhe, regular, 8, largura),
           nome_regular, 8, _CINZA)

    orcamento = f"Orçamento de retorno: {retorno.get('nome_arquivo') or 'Gamatec'}"
    if retorno.get("numero_orcamento"):
        orcamento += f" · Nº {retorno['numero_orcamento']}"
    if retorno.get("emissao"):
        orcamento += f" · emissão {retorno['emissao']}"
    _texto(page, _MARGEM, 93, _encolher(orcamento, regular, 8, largura),
           nome_regular, 8, _CINZA)

    stats = retorno.get("stats") or {}
    _texto(page, _MARGEM, 109,
           f"Desconto total: {_percentual(stats.get('desconto_total'))}",
           nome_negrito, 10, _AZUL)
    _texto_direita(page, _MARGEM + largura, 109,
                   f"Total tabela {_moeda(stats.get('total_tabela'))} · "
                   f"Gamatec {_moeda(stats.get('total_gamatec'))}",
                   nome_regular, regular, 8.5, _ESCURO)
    page.draw_line(fitz.Point(_MARGEM, 116), fitz.Point(_MARGEM + largura, 116),
                   color=(0.80, 0.82, 0.85), width=0.8)
    return 128


def _continuacao(page, dados, fontes):
    regular, _, nome_regular, nome_negrito = fontes
    largura = _A4_RETRATO[0] - 2 * _MARGEM
    _texto(page, _MARGEM, 42, "COMPARAÇÃO DE RETORNO", nome_negrito, 10, _ESCURO)
    _texto_direita(page, _MARGEM + largura, 42,
                   f"{dados.get('cliente') or ''} — vigência {dados.get('vigencia') or ''}",
                   nome_regular, regular, 8, _CINZA)
    return 52


def _verticais(page, y0, y1):
    x = _MARGEM
    page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1), color=_GRELHA, width=0.4)
    for _, largura, _ in _COLUNAS:
        x += largura
        page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1), color=_GRELHA, width=0.4)


def _cabecalho_tabela(page, y, fontes):
    regular, negrito, nome_regular, nome_negrito = fontes
    x = _MARGEM
    page.draw_rect(fitz.Rect(_MARGEM, y - 10, _MARGEM + _LARGURA_TABELA, y + 4),
                   color=_GRELHA, fill=(0.93, 0.94, 0.96), width=0.4)
    for titulo, largura, alinhamento in _COLUNAS:
        if alinhamento == "right":
            _texto_direita(page, x + largura - 3, y, titulo, nome_negrito, negrito, 7, _ESCURO)
        else:
            _texto(page, x + 3, y, titulo, nome_negrito, 7, _ESCURO)
        x += largura
    _verticais(page, y - 10, y + 13)
    page.draw_line(fitz.Point(_MARGEM, y + 13), fitz.Point(_MARGEM + _LARGURA_TABELA, y + 13),
                   color=_GRELHA, width=0.4)
    return y + 13


def _linhas_item(linha, regular):
    descricao = (linha.get("DESCRICAO") or "").strip() or "— descrição não indicada"
    linhas = _quebrar(descricao, regular, 7.4, _LARGURA_DESC)
    if len(linhas) > 4:
        linhas = linhas[:4]
        linhas[-1] = f"{linhas[-1]}…"
    return linhas


def _desenhar_item(page, y, linha, fontes, faixa):
    regular, negrito, nome_regular, nome_negrito = fontes
    linhas = _linhas_item(linha, regular)
    altura = 4.5 + 8.5 * len(linhas)

    status = linha.get("STATUS")
    cor_texto, cor_secundaria = _ESCURO, _CINZA
    fundo = None
    if status == "SEM":
        fundo, cor_texto, cor_secundaria = _VERMELHO, _BRANCO, _BRANCO
    elif status == "REVISAR":
        fundo = _AMBAR
    elif faixa % 2:
        fundo = (0.965, 0.97, 0.975)

    if fundo:
        page.draw_rect(fitz.Rect(_MARGEM, y, _MARGEM + _LARGURA_TABELA, y + altura),
                       color=None, fill=fundo)

    base = y + 8.5
    x = _MARGEM
    _texto(page, x + 3, base, str(linha.get("CODIGO_KRONA") or "—"),
           nome_regular, 7.2, cor_texto)
    x += _COLUNAS[0][1]

    linha_y = base
    for pedaco in linhas:
        _texto(page, x + 3, linha_y, pedaco, nome_regular, 7.4, cor_texto)
        linha_y += 8.5
    x += _COLUNAS[1][1]

    _texto_direita(page, x + _COLUNAS[2][1] - 3, base,
                   _quantidade(linha.get("QUANTIDADE")), nome_regular, regular, 7.2, cor_texto)
    x += _COLUNAS[2][1]
    _texto_direita(page, x + _COLUNAS[3][1] - 3, base,
                   _moeda(linha.get("PRECO_TABELA"), 3), nome_regular, regular, 7.2, cor_texto)
    x += _COLUNAS[3][1]
    _texto_direita(page, x + _COLUNAS[4][1] - 3, base,
                   _moeda(linha.get("PRECO_GAMATEC"), 3), nome_regular, regular, 7.2, cor_texto)
    x += _COLUNAS[4][1]
    _texto_direita(page, x + _COLUNAS[5][1] - 3, base,
                   _percentual(linha.get("DESCONTO_PCT")), nome_negrito, negrito, 7.2, cor_texto)

    obs = linha.get("OBS")
    if obs:
        linha_y = base
        for pedaco in _quebrar(obs, regular, 6.4, _LARGURA_TABELA - 8):
            _texto(page, _MARGEM + 3, linha_y, pedaco, nome_regular, 6.4, cor_secundaria)
            linha_y += 7.5

    page.draw_line(fitz.Point(_MARGEM, y), fitz.Point(_MARGEM + _LARGURA_TABELA, y),
                   color=_GRELHA, width=0.4)
    page.draw_line(fitz.Point(_MARGEM, y + altura), fitz.Point(_MARGEM + _LARGURA_TABELA, y + altura),
                   color=(0.88, 0.89, 0.91), width=0.4)
    _verticais(page, y, y + altura)
    return y + altura


def _bloco_rodape(page, dados, retorno, fontes):
    regular, negrito, nome_regular, nome_negrito = fontes
    direita = _MARGEM + _LARGURA_TABELA
    page.draw_line(fitz.Point(_MARGEM, 770), fitz.Point(direita, 770),
                   color=(0.88, 0.89, 0.91), width=0.6)

    largura_nota = direita - 170 - 12 - _MARGEM
    stats = retorno.get("stats") or {}
    sem = stats.get("sem_retorno") or 0
    extras = stats.get("extras") or 0
    _texto(page, _MARGEM, 782,
           _encolher(f"Âmbar: item a confirmar · Vermelho: sem preço no retorno.",
                     regular, 6.8, largura_nota), nome_regular, 6.8, _CINZA)
    _texto(page, _MARGEM, 791,
           _encolher(f"Sem preço no retorno: {sem} item(ns) · Só no retorno: {extras} item(ns).",
                     regular, 6.8, largura_nota), nome_regular, 6.8, _CLARO)
    _texto(page, _MARGEM, 800,
           _encolher("O desconto de cada item vale para lançar no Gamatec após a conferência.",
                     regular, 6.8, largura_nota), nome_regular, 6.8, _CLARO)

    largura_selo = 170
    x0 = direita - largura_selo
    y0 = _A4_RETRATO[1] - 68
    page.draw_rect(fitz.Rect(x0, y0, direita, y0 + 38),
                   color=(0.86, 0.88, 0.92), fill=(0.975, 0.98, 0.99),
                   width=0.6, radius=0.16)

    chip = fitz.Rect(x0 + 9, y0 + 11, x0 + 25, y0 + 27)
    page.draw_rect(chip, color=None, fill=_AZUL, radius=0.2)
    largura_v = negrito.text_length("V", fontsize=9)
    _texto(page, chip.x0 + (16 - largura_v) / 2, chip.y1 - 4.8, "V",
           nome_negrito, 9, (1, 1, 1))

    x = x0 + 32
    _texto(page, x, y0 + 22, "VORTEX", nome_negrito, 8.4, _ESCURO)
    x += negrito.text_length("VORTEX", fontsize=8.4)
    _texto(page, x + 2.4, y0 + 22, "SYNC", nome_negrito, 8.4, _AZUL)
    _texto(page, x0 + 32, y0 + 32, f"Goiânia — GO · {date.today():%d/%m/%Y}",
           nome_regular, 6.6, _CINZA)


def _totais(page, y, retorno, fontes):
    regular, negrito, nome_regular, nome_negrito = fontes
    stats = retorno.get("stats") or {}
    y += 12
    page.draw_line(fitz.Point(_MARGEM, y - 6), fitz.Point(_MARGEM + _LARGURA_TABELA, y - 6),
                   color=(0.80, 0.82, 0.85), width=0.8)
    x = _MARGEM
    _texto(page, x + 3, y + 4, "TOTAL", nome_negrito, 7.6, _ESCURO)
    x += _COLUNAS[0][1] + _COLUNAS[1][1] + _COLUNAS[2][1]
    _texto_direita(page, x + _COLUNAS[3][1] - 3, y + 4,
                   _moeda(stats.get("total_tabela")), nome_negrito, negrito, 7.6, _ESCURO)
    x += _COLUNAS[3][1]
    _texto_direita(page, x + _COLUNAS[4][1] - 3, y + 4,
                   _moeda(stats.get("total_gamatec")), nome_negrito, negrito, 7.6, _ESCURO)
    x += _COLUNAS[4][1]
    _texto_direita(page, x + _COLUNAS[5][1] - 3, y + 4,
                   _percentual(stats.get("desconto_total")), nome_negrito, negrito, 7.6, _AZUL)
    return y + 12


def gerar_pdf_retorno(dados, retorno):
    linhas = list(retorno.get("linhas") or [])
    regular = _caminho_fonte(_FONTE, r"C:\Windows\Fonts\segoeui.ttf")
    negrito = _caminho_fonte(_FONTE_NEGRITO, r"C:\Windows\Fonts\seguisb.ttf")

    with tempfile.TemporaryDirectory(prefix="pdf_retorno_") as pasta:
        caminhos = None
        if regular and negrito:
            try:
                caminhos = _fontes_reduzidas(regular, negrito, _codepoints(retorno), pasta)
            except Exception:
                caminhos = None

        doc = fitz.open()
        page = doc.new_page(width=_A4_RETRATO[0], height=_A4_RETRATO[1])
        fontes = _fontes(page, caminhos)
        y = _bloco_titulo(page, dados, retorno, fontes)
        y = _cabecalho_tabela(page, y + 10, fontes)
        faixa = 0

        for linha in linhas:
            altura = 4.5 + 8.5 * len(_linhas_item(linha, fontes[0]))
            obs = linha.get("OBS")
            if obs:
                altura += 7.5 * len(_quebrar(obs, fontes[0], 6.4, _LARGURA_TABELA - 8))
            if y + altura > _A4_RETRATO[1] - _FAIXA_RODAPE:
                page = doc.new_page(width=_A4_RETRATO[0], height=_A4_RETRATO[1])
                fontes = _fontes(page, caminhos)
                y = _continuacao(page, dados, fontes)
                y = _cabecalho_tabela(page, y + 8, fontes)
                faixa = 0
            y = _desenhar_item(page, y, linha, fontes, faixa)
            faixa += 1

        if y + 40 > _A4_RETRATO[1] - _FAIXA_RODAPE:
            page = doc.new_page(width=_A4_RETRATO[0], height=_A4_RETRATO[1])
            fontes = _fontes(page, caminhos)
            y = _continuacao(page, dados, fontes)
        y = _totais(page, y, retorno, fontes)

        total_paginas = len(doc)
        largura = _A4_RETRATO[0] - 2 * _MARGEM
        regular, negrito, nome_regular, nome_negrito = fontes
        for numero, pagina in enumerate(doc, start=1):
            _bloco_rodape(pagina, dados, retorno, fontes)
            _texto(pagina, _MARGEM, _A4_RETRATO[1] - 14, _TEXTO_RODAPE,
                   nome_regular, 6.5, _CLARO)
            _texto_direita(pagina, _MARGEM + largura, _A4_RETRATO[1] - 14,
                           f"Página {numero} de {total_paginas}", nome_regular, regular,
                           6.5, _CLARO)

        try:
            doc.subset_fonts()
        except Exception:
            pass
        return doc.tobytes()
