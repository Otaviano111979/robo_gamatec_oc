# -*- coding: utf-8 -*-
"""Leitor de documentos SEM preço para comparação com a tabela do cliente.

Aceita quatro famílias de entrada, por esta ordem:
  - layout de modelo próprio (COD KRONA | DESCRIÇÃO | QUANTIDADE), com ou sem
    colunas de preço — o preço, quando existe, é apenas informativo;
  - folha Excel com cabeçalho reconhecível;
  - documentos de compra que o sistema já lê (Sienge, UAU, MRV, Terral...);
  - cotações/orçamentos com descrição e quantidade.

Nada aqui calcula preço: devolve os itens do documento tal como estão.
"""
import io
import os
import re
import tempfile

import pandas as pd
import pdfplumber

from extracao_oc.extrator_cotacao import extrair_cotacao

LAYOUT_MODELO = "Modelo (código, descrição, quantidade)"
LAYOUT_XLSX = "Excel com cabeçalho"

_UNIDADES = {
    "UN", "UND", "UNID", "PC", "PÇ", "PCS", "PÇS", "M", "MT", "M2", "M²",
    "M3", "M³", "BR", "CX", "KG", "G", "L", "ML", "JG", "PAR", "RL", "SC",
}
_RX_NUMERO_BR = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,4})?$")
_RX_CODIGO = re.compile(r"^\d{1,4}$")
_RX_TITULO = re.compile(r"COD\s*(?:IGO)?\.?\s*(?:KRONA|CLIENTE|CLI)\b", re.IGNORECASE)
_RX_COLUNA_QUANTIDADE = re.compile(r"quant|qtd|qnd", re.IGNORECASE)
_RX_COLUNA_DESCRICAO = re.compile(r"descri", re.IGNORECASE)
_RX_COLUNA_CODIGO = re.compile(r"^c[oó]d|\bcod\b|c[oó]digo", re.IGNORECASE)
_RX_COLUNA_UNIDADE = re.compile(r"^unid|\bun\.?$|\bunidade\b", re.IGNORECASE)


def _num_br(texto):
    if isinstance(texto, (int, float)) and not isinstance(texto, bool):
        return float(texto) if texto == texto else None
    valor = str(texto or "").strip().replace("R$", "").strip()
    if not valor:
        return None
    if _RX_NUMERO_BR.match(valor):
        return float(valor.replace(".", "").replace(",", "."))
    try:
        return float(valor.replace(",", "."))
    except ValueError:
        return None


def _unidade(texto):
    valor = str(texto or "").strip().upper().rstrip(".")
    normalizada = {"PÇ": "PC", "PCS": "PC", "PÇS": "PC", "UNID": "UN",
                   "UND": "UN", "MT": "M", "M²": "M2", "M³": "M3"}
    return normalizada.get(valor, valor or None)


def _e_cabecalho(linha):
    texto = str(linha or "")
    return bool(_RX_TITULO.search(texto)
                and _RX_COLUNA_DESCRICAO.search(texto)
                and _RX_COLUNA_QUANTIDADE.search(texto))


def _parse_linha_modelo(linha):
    """Lê a linha da direita para a esquerda: total, quantidade, unidade, preço.

    Assim o mesmo leitor serve ao modelo sem preço e a documentos que ainda
    tragam o preço de outro fornecedor (guardado só como informação).
    """
    tokens = str(linha or "").split()
    if len(tokens) < 3 or not _RX_CODIGO.match(tokens[0]):
        return None

    corpo = tokens[1:]
    total = None
    preco = None
    unidade = None

    if len(corpo) >= 2 and corpo[-2].upper() == "R$" and _num_br(corpo[-1]) is not None:
        total = _num_br(corpo[-1])
        corpo = corpo[:-2]
    if not corpo:
        return None

    # a unidade pode vir antes ou depois da quantidade (UNIDADE | QTD ou QTD | UNIDADE)
    if _unidade(corpo[-1]) in _UNIDADES:
        unidade = _unidade(corpo[-1])
        corpo = corpo[:-1]
    if not corpo:
        return None
    quantidade = _num_br(corpo[-1])
    if quantidade is None:
        return None
    corpo = corpo[:-1]

    if unidade is None and corpo and _unidade(corpo[-1]) in _UNIDADES:
        unidade = _unidade(corpo[-1])
        corpo = corpo[:-1]
    if corpo and _num_br(corpo[-1]) is not None and re.search(r"[,.]", corpo[-1]):
        preco = _num_br(corpo[-1])
        corpo = corpo[:-1]

    descricao = " ".join(corpo).strip(" -–.")
    if not descricao:
        return None
    return {
        "codigo_cliente": str(int(tokens[0])),
        "descricao": descricao,
        "quantidade": quantidade,
        "unidade": unidade,
        "preco_documento": preco,
        "total_documento": total,
    }


def _colunas_modelo(celulas):
    """Posições das colunas do modelo; None se a linha não for o cabeçalho."""
    textos = [str(celula or "").strip() for celula in celulas]
    if not any(_RX_TITULO.search(texto) for texto in textos):
        return None
    colunas = {
        "desc": next((i for i, t in enumerate(textos) if _RX_COLUNA_DESCRICAO.search(t)), None),
        "qtd": next((i for i, t in enumerate(textos) if _RX_COLUNA_QUANTIDADE.search(t)), None),
        "cod": next((i for i, t in enumerate(textos) if _RX_TITULO.search(t)), None),
        "un": next((i for i, t in enumerate(textos) if _RX_COLUNA_UNIDADE.search(t)), None),
    }
    if colunas["desc"] is None or colunas["qtd"] is None:
        return None
    return colunas


def _ler_modelo_tabelas(pdf):
    """Modelo lido pelas células da tabela: aceita linhas sem código."""
    itens = []
    for pagina, page in enumerate(pdf.pages, start=1):
        colunas = None
        for tabela in page.extract_tables() or []:
            for linha in tabela or []:
                celulas = [str(celula or "").strip() for celula in linha]
                cabecalho = _colunas_modelo(celulas)
                if cabecalho:
                    colunas = cabecalho
                    continue
                if colunas is None or len(celulas) <= max(colunas["desc"], colunas["qtd"]):
                    continue
                descricao = " ".join(celulas[colunas["desc"]].split())
                quantidade = _num_br(celulas[colunas["qtd"]])
                if not descricao or not quantidade:
                    continue
                codigo = celulas[colunas["cod"]] if colunas["cod"] is not None else ""
                if codigo and not _RX_CODIGO.match(codigo):
                    continue
                itens.append({
                    "codigo_cliente": str(int(codigo)) if codigo else "",
                    "descricao": descricao,
                    "quantidade": quantidade,
                    "unidade": (_unidade(celulas[colunas["un"]])
                                if colunas["un"] is not None else None),
                    "preco_documento": None,
                    "total_documento": None,
                    "pagina": pagina,
                    "codigo_confiavel": bool(codigo),
                })
    return _consolidar_linhas(itens)


def _consolidar_linhas(itens):
    """Marcadores de página repetem o último item; junta códigos iguais."""
    vistos = {}
    resultado = []
    for item in itens:
        chave = item["codigo_cliente"]
        if chave and chave in vistos:
            anterior = vistos[chave]
            if anterior["descricao"] == item["descricao"]:
                anterior["quantidade"] = round(anterior["quantidade"] + item["quantidade"], 3)
                continue
        if chave:
            vistos[chave] = item
        resultado.append(item)
    return resultado


def _ler_modelo(pdf):
    itens = []
    codigos = {}
    for pagina, page in enumerate(pdf.pages, start=1):
        texto = page.extract_text() or ""
        if not texto.strip():
            raise ValueError(f"Página {pagina} sem texto: o PDF precisa de OCR.")

        linhas = texto.splitlines()
        inicio = 0
        if pagina == 1:
            cabecalho = next(
                (i for i, linha in enumerate(linhas) if _e_cabecalho(linha)), None)
            if cabecalho is None:
                return None
            if any(linha.strip() for linha in linhas[:cabecalho]):
                raise ValueError(
                    "Conteúdo anterior ao cabeçalho do documento; a leitura foi "
                    "interrompida para não omitir itens."
                )
            inicio = cabecalho + 1

        for numero, linha in enumerate(linhas[inicio:], start=inicio + 1):
            linha = linha.strip()
            if not linha or _e_cabecalho(linha):
                continue
            item = _parse_linha_modelo(linha)
            if item is None:
                raise ValueError(
                    f"Página {pagina}, linha {numero}: item incompleto ou fora do "
                    "layout esperado (código, descrição e quantidade)."
                )
            item["pagina"] = pagina
            item["codigo_confiavel"] = True
            chave = item["codigo_cliente"]
            if chave in codigos:
                item["obs_leitura"] = f"código repetido (linha {codigos[chave]})"
            else:
                codigos[chave] = numero
            itens.append(item)
    return itens


def _coluna(cabecalho, padrao, evitar=None):
    for indice, celula in enumerate(cabecalho):
        texto = str(celula or "").strip()
        if not texto or (evitar and evitar.search(texto)):
            continue
        if padrao.search(texto):
            return indice
    return None


def _celula(valor):
    """Célula vazia do Excel chega como None ou NaN; nunca é texto."""
    if valor is None or (isinstance(valor, float) and valor != valor):
        return ""
    texto = str(valor).strip()
    return "" if texto.lower() == "nan" else texto


def _ler_excel(arquivo):
    """Folha com cabeçalho: procura código, descrição, quantidade e unidade."""
    try:
        bruto = pd.read_excel(arquivo, header=None, dtype=object)
    except Exception as erro:
        raise ValueError("Não foi possível ler a folha Excel.") from erro

    for posicao in range(min(20, len(bruto))):
        cabecalho = list(bruto.iloc[posicao])
        col_desc = _coluna(cabecalho, _RX_COLUNA_DESCRICAO)
        col_qtd = _coluna(cabecalho, _RX_COLUNA_QUANTIDADE)
        if col_desc is None or col_qtd is None:
            continue
        col_cod = _coluna(cabecalho, _RX_COLUNA_CODIGO, evitar=_RX_COLUNA_QUANTIDADE)
        col_un = _coluna(cabecalho, _RX_COLUNA_UNIDADE)
        itens = []
        for _, linha in bruto.iloc[posicao + 1:].iterrows():
            descricao = _celula(linha.iloc[col_desc])
            quantidade = _num_br(linha.iloc[col_qtd])
            if not descricao or not quantidade:
                continue
            codigo = _celula(linha.iloc[col_cod]) if col_cod is not None else ""
            if re.fullmatch(r"\d+\.0", codigo):
                codigo = codigo[:-2]
            itens.append({
                "codigo_cliente": codigo,
                "descricao": descricao,
                "quantidade": quantidade,
                "unidade": _unidade(_celula(linha.iloc[col_un])) if col_un is not None else None,
                "preco_documento": None,
                "total_documento": None,
                "pagina": None,
                "codigo_confiavel": bool(codigo),
            })
        if itens:
            return itens, posicao + 1
    return None, None


def _codigos_confiaveis(itens):
    """Números de linha (1, 2, 3...) não são códigos de produto."""
    codigos = [str(item.get("codigo_cliente") or "").strip() for item in itens]
    preenchidos = [c for c in codigos if c]
    if not preenchidos or len(preenchidos) != len(codigos):
        return False
    if all(re.fullmatch(r"\d{1,4}", c) for c in codigos):
        sequencia = all(c == str(i) for i, c in enumerate(codigos, start=1))
        if sequencia:
            return False
    return True


def _ler_documento_compra(caminho):
    """Layouts que o sistema já lê para OC (Sienge, UAU, MRV, Terral...)."""
    from extrator_oc import extrair_itens_oc

    saida = extrair_itens_oc(caminho)
    formato = ""
    if isinstance(saida, tuple):
        saida, formato = saida
    formato = formato or next(
        (str(b.get("formato_oc") or "") for b in (saida or []) if b.get("formato_oc")), "")
    itens = []
    for bruto in saida or []:
        descricao = str(
            bruto.get("descricao_reconstruida")
            or bruto.get("descricao_original")
            or bruto.get("descricao_oc")
            or ""
        ).strip()
        quantidade = _num_br(bruto.get("quantidade"))
        if not descricao or not quantidade or quantidade <= 0:
            continue
        itens.append({
            "codigo_cliente": str(bruto.get("codigo_interno_oc") or "").strip(),
            "descricao": descricao,
            "quantidade": quantidade,
            "unidade": _unidade(bruto.get("unidade_normalizada")
                                or bruto.get("unidade_original")
                                or bruto.get("unidade")),
            "preco_documento": _num_br(bruto.get("valor_unitario"))
                               or _num_br(bruto.get("preco_unitario")),
            "total_documento": _num_br(bruto.get("valor_total")),
            "pagina": bruto.get("pagina"),
            "codigo_confiavel": False,
        })
    if itens:
        confiavel = _codigos_confiaveis(itens)
        for item in itens:
            item["codigo_confiavel"] = confiavel
    return itens, formato


def _ler_cotacao(caminho):
    """Sienge/UAU/lista simples com descrição e quantidade."""
    resultado = extrair_cotacao(caminho)
    if not resultado.get("ok") or not resultado.get("itens"):
        return [], None, resultado
    itens = [{
        "codigo_cliente": str(item.get("codigo_cliente") or "").strip(),
        "descricao": str(item.get("descricao") or "").strip(),
        "quantidade": float(item.get("quantidade") or 0),
        "unidade": _unidade(item.get("unidade")),
        "preco_documento": None,
        "total_documento": None,
        "pagina": None,
        "codigo_confiavel": False,
    } for item in resultado["itens"]]
    itens = [i for i in itens if i["descricao"] and i["quantidade"] > 0]
    if itens and resultado.get("layout") != "LISTA_SIMPLES":
        confiavel = _codigos_confiaveis(itens)
        for item in itens:
            item["codigo_confiavel"] = confiavel
    return itens, resultado, resultado


def _resumo(nome, itens, layout, numero="", cliente="", paginas=None):
    return {
        "ok": True,
        "nome_arquivo": nome,
        "layout": layout,
        "numero": numero or "",
        "cliente": cliente or "",
        "paginas": paginas,
        "itens": itens,
        "total_itens": len(itens),
        "com_preco": sum(1 for i in itens if i.get("preco_documento")),
        "sem_codigo": sum(1 for i in itens if not i.get("codigo_cliente")),
    }


def _extrair_pdf(conteudo, nome):
    try:
        pdf = pdfplumber.open(io.BytesIO(conteudo))
    except Exception as erro:
        raise ValueError("Não foi possível ler o PDF do documento.") from erro

    with pdf:
        paginas = len(pdf.pages)
        itens = _ler_modelo_tabelas(pdf)
        erro_modelo = None
        if not itens:
            try:
                itens = _ler_modelo(pdf)
            except ValueError as erro:
                itens = None
                erro_modelo = str(erro)
    if itens:
        return _resumo(nome, itens, LAYOUT_MODELO, paginas=paginas)

    temporario = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as arquivo:
            temporario = arquivo.name
            arquivo.write(conteudo)

        itens, formato = _ler_documento_compra(temporario)
        if itens:
            return _resumo(nome, itens, f"Documento de compra {formato}".strip(),
                           paginas=paginas)

        itens, meta, _ = _ler_cotacao(temporario)
        if itens:
            layout = {
                "SIENGE_BLOCOS": "Orçamento Sienge",
                "UAU_COLETA": "Coleta UAU",
                "LISTA_SIMPLES": "Lista simples",
            }.get((meta or {}).get("layout"), (meta or {}).get("layout") or "Cotação")
            return _resumo(nome, itens, layout, numero=(meta or {}).get("numero_oc"),
                           cliente=(meta or {}).get("cliente"),
                           paginas=(meta or {}).get("paginas") or paginas)
    finally:
        if temporario:
            try:
                os.unlink(temporario)
            except OSError:
                pass

    mensagem = (
        "Nenhum item reconhecido. O documento pode ser enviado no layout do "
        "modelo (código, descrição e quantidade), como orçamento ou pedido de "
        "compra, ou como lista com cabeçalho de descrição e quantidade."
    )
    if erro_modelo:
        mensagem = f"{mensagem} Leitura do modelo: {erro_modelo}"
    raise ValueError(mensagem)


def extrair_documento_nao_precificado(conteudo, nome_arquivo=""):
    """Devolve os itens do documento sem preço, com o layout reconhecido."""
    if not conteudo:
        raise ValueError("O arquivo do documento está vazio.")
    nome = str(nome_arquivo or "")
    if nome.lower().endswith((".xlsx", ".xls")):
        itens, linha_cabecalho = _ler_excel(io.BytesIO(conteudo))
        if not itens:
            raise ValueError(
                "A folha Excel não tem um cabeçalho reconhecível (código, descrição "
                "e quantidade) ou não tem itens."
            )
        return _resumo(nome, itens, LAYOUT_XLSX, paginas=linha_cabecalho)
    return _extrair_pdf(conteudo, nome)
