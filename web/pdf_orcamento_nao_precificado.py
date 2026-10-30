# -*- coding: utf-8 -*-
"""PDF de orçamento da comparação documento × tabela do cliente.

Usa PyMuPDF (já instalado) e a Arial do Windows para acentos.
A primeira página traz o bloco do orçamento; as seguintes repetem o cabeçalho
da tabela. O rodapé traz o selo Vortex Sync com data e local, as notas da
proposta e a numeração das páginas.
"""
import json
import os
import tempfile
from datetime import date

import fitz

_FONTE = r"C:\Windows\Fonts\arial.ttf"
_FONTE_NEGRITO = r"C:\Windows\Fonts\arialbd.ttf"

_A4_RETRATO = (595, 842)
_MARGEM = 34
_FAIXA_RODAPE = 78
_AZUL = (0.114, 0.306, 0.847)

_COLUNAS = (
    ("CÓD. CLIENTE", 52, "left"),
    ("CÓD. KRONA", 48, "left"),
    ("DESCRIÇÃO", 239, "left"),
    ("QTDE", 34, "right"),
    ("UN", 34, "center"),
    ("PREÇO", 56, "right"),
    ("TOTAL", 64, "right"),
)
_LARGURA_TABELA = sum(coluna[1] for coluna in _COLUNAS)
_LARGURA_DESC = _COLUNAS[2][1] - 6

_CINZA = (0.36, 0.38, 0.42)
_CLARO = (0.62, 0.64, 0.68)
_ESCURO = (0.12, 0.14, 0.18)
_AMBAR = (0.992, 0.902, 0.541)
_VERMELHO = (0.863, 0.149, 0.149)
_BRANCO = (1.0, 1.0, 1.0)

_TEXTO_RODAPE = ("Preços conforme a tabela do cliente; o preço do documento, "
                 "quando existe, não é usado.")


def _caminho_fonte(preferido, alternativa):
    for caminho in (preferido, alternativa):
        if caminho and os.path.exists(caminho):
            return caminho
    return None


def _codepoints(dados):
    """Todos os caracteres que podem aparecer no PDF."""
    texto = json.dumps(dados, ensure_ascii=False)
    codigos = {ord(caractere) for caractere in texto}
    codigos |= set(range(32, 127))
    codigos |= set(range(160, 256)) - {0x00A0, 0x00AD}
    codigos |= {0x2013, 0x2014, 0x2018, 0x2019, 0x201A,
                0x201C, 0x201D, 0x2022, 0x2026, 0x20AC, 0x2122}
    return sorted(codigos)


def _fontes_reduzidas(regular, negrito, codigos, pasta):
    """Reduz a Arial aos caracteres usados.

    Sem isto o PyMuPDF mapeia os glifos partilhados da Arial para o primeiro
    caractere do cmap (espaço → U+00A0, hífen → U+00AD) e o texto do PDF sai
    corrompido ao copiar. A redução mantém as métricas e corrige o mapeamento.
    """
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    caminhos = []
    for origem, nome in ((regular, "regular.ttf"), (negrito, "negrito.ttf")):
        fonte = TTFont(origem)
        opcoes = subset.Options()
        opcoes.drop_tables += ["meta"]
        redutor = subset.Subsetter(opcoes)
        redutor.populate(unicodes=codigos)
        redutor.subset(fonte)
        destino = os.path.join(pasta, nome)
        fonte.save(destino)
        caminhos.append(destino)
    return tuple(caminhos)


def _fontes(page, caminhos=None):
    """Registra a fonte na página e devolve (Font regular, Font negrito, nomes)."""
    if caminhos:
        page.insert_font(fontname="txt", fontfile=caminhos[0])
        page.insert_font(fontname="txtb", fontfile=caminhos[1])
        return fitz.Font(fontfile=caminhos[0]), fitz.Font(fontfile=caminhos[1]), "txt", "txtb"
    regular = _caminho_fonte(_FONTE, r"C:\Windows\Fonts\segoeui.ttf")
    negrito = _caminho_fonte(_FONTE_NEGRITO, r"C:\Windows\Fonts\seguisb.ttf")
    if regular and negrito:
        page.insert_font(fontname="txt", fontfile=regular)
        page.insert_font(fontname="txtb", fontfile=negrito)
        return fitz.Font(fontfile=regular), fitz.Font(fontfile=negrito), "txt", "txtb"
    return fitz.Font("helv"), fitz.Font("hebo"), "helv", "hebo"


def _moeda(valor, casas=2):
    if valor is None:
        return "—"
    texto = f"{float(valor):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _quantidade(valor):
    if valor is None:
        return "—"
    valor = float(valor)
    if abs(valor - round(valor)) < 1e-9:
        return f"{int(round(valor)):,}".replace(",", ".")
    return f"{valor:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _quebrar(texto, medidor, tamanho, largura):
    linhas, atual = [], ""
    for palavra in str(texto or "").split():
        teste = f"{atual} {palavra}".strip()
        if medidor.text_length(teste, fontsize=tamanho) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas or [""]


def _limpo(texto):
    return str(texto or "").replace("\xa0", " ").replace("\u00ad", "")


def _texto(page, x, y, texto, fonte, tamanho=7.4, cor=_ESCURO):
    page.insert_text((x, y), _limpo(texto), fontname=fonte, fontsize=tamanho, color=cor)


def _texto_direita(page, x_fim, y, texto, fonte, medidor, tamanho=7.4, cor=_ESCURO):
    texto = _limpo(texto)
    largura = medidor.text_length(texto, fontsize=tamanho)
    page.insert_text((x_fim - largura, y), texto, fontname=fonte, fontsize=tamanho, color=cor)


def _texto_centro(page, x_ini, largura_coluna, y, texto, fonte, medidor, tamanho=7.4, cor=_ESCURO):
    texto = _limpo(texto)
    x = x_ini + largura_coluna / 2 - medidor.text_length(texto, fontsize=tamanho) / 2
    page.insert_text((x, y), texto, fontname=fonte, fontsize=tamanho, color=cor)


def _encolher(texto, medidor, tamanho, largura):
    if medidor.text_length(texto, fontsize=tamanho) <= largura:
        return texto
    texto = texto.rstrip(" .")
    while texto and medidor.text_length(f"{texto}…", fontsize=tamanho) > largura:
        texto = texto[:-1].rstrip()
    return f"{texto}…"


def _resumo(dados):
    registros = dados.get("registros") or []
    contagem = {"OK": 0, "REVISAR": 0, "SEM": 0}
    for registro in registros:
        chave = registro.get("STATUS")
        contagem[chave] = contagem.get(chave, 0) + 1
    total = sum((registro.get("TOTAL") or 0) for registro in registros)
    return contagem, total


def _bloco_titulo(page, dados, fontes):
    regular, negrito, nome_regular, nome_negrito = fontes
    largura = _A4_RETRATO[0] - 2 * _MARGEM
    _texto(page, _MARGEM, 52, "ORÇAMENTO", nome_negrito, 19, _ESCURO)
    _texto_direita(page, _MARGEM + largura, 50, f"Data: {date.today():%d/%m/%Y}",
                   nome_regular, regular, 9, _CINZA)

    cliente = dados.get("cliente") or ""
    vigencia = dados.get("vigencia") or ""
    _texto(page, _MARGEM, 68, f"Tabela de preços: {cliente} — vigência {vigencia}",
           nome_regular, 9, _ESCURO)

    documento = dados.get("nome_arquivo") or "documento"
    layout = dados.get("layout") or ""
    numero = dados.get("numero")
    detalhe = f"Documento: {documento} ({layout})" if layout else f"Documento: {documento}"
    if numero:
        detalhe += f" · Nº {numero}"
    _texto(page, _MARGEM, 81, detalhe, nome_regular, 8, _CINZA)

    contagem, total = _resumo(dados)
    itens = len(dados.get("registros") or [])
    resumo = f"{itens} itens · {itens - contagem['SEM']} com preço · {contagem['SEM']} sem preço"
    _texto(page, _MARGEM, 97, resumo, nome_regular, 8.5, _CINZA)
    _texto_direita(page, _MARGEM + largura, 98, f"Total pela tabela: {_moeda(total)}",
                   nome_negrito, negrito, 10, _ESCURO)
    page.draw_line(fitz.Point(_MARGEM, 104), fitz.Point(_MARGEM + largura, 104),
                   color=(0.80, 0.82, 0.85), width=0.8)
    return 116


def _continuacao(page, dados, fontes):
    regular, _, nome_regular, nome_negrito = fontes
    largura = _A4_RETRATO[0] - 2 * _MARGEM
    _texto(page, _MARGEM, 42, "ORÇAMENTO", nome_negrito, 10, _ESCURO)
    _texto_direita(page, _MARGEM + largura, 42,
                   f"{dados.get('cliente') or ''} — vigência {dados.get('vigencia') or ''}",
                   nome_regular, regular, 8, _CINZA)
    return 52


def _cabecalho_tabela(page, y, fontes):
    regular, negrito, nome_regular, nome_negrito = fontes
    x = _MARGEM
    page.draw_rect(fitz.Rect(_MARGEM, y - 10, _MARGEM + _LARGURA_TABELA, y + 4),
                   color=None, fill=(0.93, 0.94, 0.96))
    for titulo, largura, alinhamento in _COLUNAS:
        if alinhamento == "right":
            _texto_direita(page, x + largura - 3, y, titulo, nome_negrito, negrito, 7, _ESCURO)
        elif alinhamento == "center":
            _texto_centro(page, x, largura, y, titulo, nome_negrito, negrito, 7, _ESCURO)
        else:
            _texto(page, x + 3, y, titulo, nome_negrito, 7, _ESCURO)
        x += largura
    return y + 13


def _linhas_item(registro, regular):
    descricao = (registro.get("DESCRICAO") or "").strip()
    if not descricao:
        descricao = "— descrição não indicada no documento"
    linhas = _quebrar(descricao, regular, 7.4, _LARGURA_DESC)
    if len(linhas) > 4:
        linhas = linhas[:4]
        linhas[-1] = f"{linhas[-1]}…"
    return linhas


def _desenhar_item(page, y, registro, fontes, faixa):
    regular, negrito, nome_regular, nome_negrito = fontes
    linhas = _linhas_item(registro, regular)
    altura = 4.5 + 8.5 * len(linhas)

    status = registro.get("STATUS")
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
    _texto(page, x + 3, base, str(registro.get("CODIGO_CLIENTE") or "—"),
           nome_regular, 7.2, cor_secundaria)
    x += _COLUNAS[0][1]
    _texto(page, x + 3, base, str(registro.get("CODIGO_KRONA") or "—"),
           nome_regular, 7.2, cor_texto)
    x += _COLUNAS[1][1]

    linha_y = base
    for indice, linha in enumerate(linhas):
        _texto(page, x + 3, linha_y, linha, nome_regular, 7.4, cor_texto)
        linha_y += 8.5
    x += _COLUNAS[2][1]

    _texto_direita(page, x + _COLUNAS[3][1] - 3, base,
                   _quantidade(registro.get("QUANTIDADE")), nome_regular, regular, 7.2, cor_texto)
    x += _COLUNAS[3][1]
    _texto_centro(page, x, _COLUNAS[4][1], base, str(registro.get("UNIDADE") or "—"),
                  nome_regular, regular, 7.2, cor_secundaria)
    x += _COLUNAS[4][1]
    _texto_direita(page, x + _COLUNAS[5][1] - 3, base,
                   _moeda(registro.get("PRECO_TABELA"), 3), nome_regular, regular, 7.2, cor_texto)
    x += _COLUNAS[5][1]
    _texto_direita(page, x + _COLUNAS[6][1] - 3, base,
                   _moeda(registro.get("TOTAL")), nome_negrito, negrito, 7.2, cor_texto)

    page.draw_line(fitz.Point(_MARGEM, y + altura),
                   fitz.Point(_MARGEM + _LARGURA_TABELA, y + altura),
                   color=(0.88, 0.89, 0.91), width=0.4)
    return y + altura


def _bloco_rodape(page, dados, fontes):
    """Selo Vortex Sync com data e local, notas da proposta e numeração."""
    regular, negrito, nome_regular, nome_negrito = fontes
    direita = _MARGEM + _LARGURA_TABELA
    page.draw_line(fitz.Point(_MARGEM, 770), fitz.Point(direita, 770),
                   color=(0.88, 0.89, 0.91), width=0.6)

    cliente = dados.get("cliente") or "cliente"
    vigencia = dados.get("vigencia") or ""
    validade = f"Proposta válida conforme a tabela {cliente}"
    if vigencia:
        validade += f" — vigência {vigencia}"
    largura_nota = direita - 170 - 12 - _MARGEM
    _texto(page, _MARGEM, 782,
           _encolher(f"{validade}.", regular, 6.8, largura_nota), nome_regular, 6.8, _CINZA)
    _texto(page, _MARGEM, 791,
           _encolher("Itens sem preço não foram cotados; quantidades conforme o "
                     "documento do cliente.", regular, 6.8, largura_nota),
           nome_regular, 6.8, _CLARO)
    _texto(page, _MARGEM, 800,
           _encolher("Âmbar: item a confirmar · Vermelho: sem correspondência na tabela.",
                     regular, 6.8, largura_nota),
           nome_regular, 6.8, _CLARO)

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


def gerar_pdf(dados):
    registros = list(dados.get("registros") or [])
    regular = _caminho_fonte(_FONTE, r"C:\Windows\Fonts\segoeui.ttf")
    negrito = _caminho_fonte(_FONTE_NEGRITO, r"C:\Windows\Fonts\seguisb.ttf")

    with tempfile.TemporaryDirectory(prefix="pdf_orcamento_") as pasta:
        caminhos = None
        if regular and negrito:
            try:
                caminhos = _fontes_reduzidas(regular, negrito, _codepoints(dados), pasta)
            except Exception:
                caminhos = None

        doc = fitz.open()
        page = doc.new_page(width=_A4_RETRATO[0], height=_A4_RETRATO[1])
        fontes = _fontes(page, caminhos)
        y = _bloco_titulo(page, dados, fontes)
        y = _cabecalho_tabela(page, y + 10, fontes)
        faixa = 0

        for registro in registros:
            altura = 4.5 + 8.5 * len(_linhas_item(registro, fontes[0]))
            if y + altura > _A4_RETRATO[1] - _FAIXA_RODAPE:
                page = doc.new_page(width=_A4_RETRATO[0], height=_A4_RETRATO[1])
                fontes = _fontes(page, caminhos)
                y = _continuacao(page, dados, fontes)
                y = _cabecalho_tabela(page, y + 8, fontes)
                faixa = 0
            y = _desenhar_item(page, y, registro, fontes, faixa)
            faixa += 1

        contagem, total = _resumo(dados)
        largura = _A4_RETRATO[0] - 2 * _MARGEM
        if y + 40 > _A4_RETRATO[1] - _FAIXA_RODAPE:
            page = doc.new_page(width=_A4_RETRATO[0], height=_A4_RETRATO[1])
            fontes = _fontes(page, caminhos)
            y = _continuacao(page, dados, fontes)
        regular, negrito, nome_regular, nome_negrito = fontes
        y += 16
        page.draw_line(fitz.Point(_MARGEM, y - 8), fitz.Point(_MARGEM + largura, y - 8),
                       color=(0.80, 0.82, 0.85), width=0.8)
        _texto(page, _MARGEM, y + 4,
               f"Itens sem preço: {contagem['SEM']} (sem correspondência na tabela).",
               nome_regular, 7.5, _CINZA)
        _texto_direita(page, _MARGEM + largura, y + 6, f"Total pela tabela: {_moeda(total)}",
                       nome_negrito, negrito, 11, _ESCURO)

        total_paginas = len(doc)
        for numero, pagina in enumerate(doc, start=1):
            _bloco_rodape(pagina, dados, fontes)
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
