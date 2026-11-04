# -*- coding: utf-8 -*-
"""Compara o orçamento precificado de retorno (Gamatec) com o processo guardado.

O processo guardado é o mestre: cada item dele recebe o preço do retorno.
  1. código Krona — determinístico, sem depender da descrição;
  2. descrição — para os itens sem código ou cujo código não voltou igual.
O que o retorno traz a mais fica no fim da lista, sem preço de tabela.

Desconto = (preço tabela − preço Gamatec) / preço tabela × 100.
"""
import re
from collections import defaultdict

from rapidfuzz import fuzz

from matcher_tabela_cliente import _sem_acento

STATUS_OK = "OK"
STATUS_REVISAR = "REVISAR"
STATUS_SEM = "SEM"

LIMIAR_OK = 0.80       # descrição abaixo disto nunca é aceite em silêncio
LIMIAR_CODIGO = 0.50   # código certo com descrição muito diferente vai a revisão

VIA_CODIGO = "CÓD. KRONA"
VIA_DESCRICAO = "DESCRIÇÃO"
VIA_SO_RETORNO = "SÓ NO RETORNO"

COMPRIMENTO_BARRA = 6.0  # tubos: tabela em metro, retorno Gamatec em barra de 6 m

_ME_DN = re.compile(r"\bDN\s*(\d{1,4})\b", re.I)
_ME_MM = re.compile(r"\b(\d{1,4}(?:[.,]\d+)?)\s*mm\b", re.I)
_ME_POL = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(?:pol(?:egada)?s?|\")\b", re.I)
_ME_FRAC = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
_ME_DIM = re.compile(r"\b(\d{1,4})\s*[xX]\s*(\d{1,4})(?!\s*/)\b")


def _norm_codigo(valor):
    texto = str(valor if valor is not None else "").strip()
    if not texto:
        return ""
    try:
        return str(int(float(texto)))
    except ValueError:
        return re.sub(r"\s+", "", texto.upper())


def _score(esquerda, direita):
    return fuzz.token_set_ratio(_sem_acento(esquerda or ""),
                                _sem_acento(direita or "")) / 100


def _medidas(texto):
    """Medidas encontradas na descrição: (tipo, valor) para DN, mm, polegada e NxN."""
    encontradas = set()
    for casamento in _ME_DN.finditer(texto or ""):
        encontradas.add(("dn", int(casamento.group(1))))
    for casamento in _ME_MM.finditer(texto or ""):
        encontradas.add(("mm", float(casamento.group(1).replace(",", "."))))
    for casamento in _ME_POL.finditer(texto or ""):
        encontradas.add(("pol", float(casamento.group(1).replace(",", "."))))
    for casamento in _ME_FRAC.finditer(texto or ""):
        numerador, denominador = int(casamento.group(1)), int(casamento.group(2))
        if denominador:
            encontradas.add(("pol", round(numerador / denominador, 3)))
    for casamento in _ME_DIM.finditer(texto or ""):
        encontradas.add(("dim", (int(casamento.group(1)), int(casamento.group(2)))))
    return encontradas


def _medidas_compativeis(esquerda, direita):
    """Com medidas dos dois lados que não se cruzam, o par não casa."""
    if not esquerda or not direita:
        return True
    tamanhos_esq = {valor for tipo, valor in esquerda if tipo in ("dn", "mm")}
    tamanhos_dir = {valor for tipo, valor in direita if tipo in ("dn", "mm")}
    if tamanhos_esq and tamanhos_dir and not (tamanhos_esq & tamanhos_dir):
        return False
    pol_esq = {valor for tipo, valor in esquerda if tipo == "pol"}
    pol_dir = {valor for tipo, valor in direita if tipo == "pol"}
    if pol_esq and pol_dir and not (pol_esq & pol_dir):
        return False
    dim_esq = {valor for tipo, valor in esquerda if tipo == "dim"}
    dim_dir = {valor for tipo, valor in direita if tipo == "dim"}
    if dim_esq and dim_dir and not (dim_esq & dim_dir):
        return False
    return True


def _unidade(valor):
    return str(valor or "").strip().upper() or None


def _float(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _desconto(preco_tabela, preco_gamatec):
    if not preco_tabela or preco_gamatec is None:
        return None
    return round((preco_tabela - preco_gamatec) / preco_tabela * 100, 2)


def _consolidar_retorno(itens):
    """Soma linhas do retorno com o mesmo código; preço fica o da primeira."""
    agrupados = {}
    ordem = []
    for item in itens:
        chave = _norm_codigo(item.get("codigo")) or f"|{id(item)}"
        if chave not in agrupados:
            agrupados[chave] = {
                "codigo": item.get("codigo") or "",
                "descricao": item.get("descricao") or "",
                "qtde": item.get("qtde") or 0,
                "preco_orcamento": item.get("preco_orcamento"),
                "linhas": 1,
            }
            ordem.append(chave)
            continue
        atual = agrupados[chave]
        atual["qtde"] = round(atual["qtde"] + (item.get("qtde") or 0), 3)
        atual["linhas"] += 1
    return [agrupados[chave] for chave in ordem]


def _descricao_registro(registro):
    return (registro.get("DESCRICAO_TABELA") or registro.get("DESCRICAO") or "").strip()


def _linha(registro, item, via, score=None):
    quantidade = _float(registro.get("QUANTIDADE"))
    preco_tabela = _float(registro.get("PRECO_TABELA"))
    total_tabela = _float(registro.get("TOTAL"))
    preco_gamatec = _float(item["preco_orcamento"]) if item else None
    qtde_retorno = _float(item.get("qtde")) if item else None
    total_gamatec = (round(qtde_retorno * preco_gamatec, 2)
                     if item and qtde_retorno is not None and preco_gamatec is not None
                     else None)

    obs = []
    status = STATUS_OK

    tubo = item is not None and _unidade(registro.get("UNIDADE")) in ("BR", "BR.")
    if tubo:
        if preco_tabela is not None:
            preco_tabela = preco_tabela * COMPRIMENTO_BARRA
        if quantidade is not None and preco_tabela is not None:
            total_tabela = round(quantidade * preco_tabela, 2)
        obs.append(f"tubo: tabela em metros; comparado por barra de {COMPRIMENTO_BARRA:g} m")

    if item is None:
        status = STATUS_SEM
        obs.append("sem preço no retorno")
    else:
        if via == VIA_CODIGO and score is not None and score < LIMIAR_CODIGO:
            status = STATUS_REVISAR
            obs.append("código Krona confere, descrição do retorno muito diferente")
        if via == VIA_DESCRICAO:
            if score is None or score < LIMIAR_OK:
                status = STATUS_REVISAR
                obs.append("descrição parecida; confirme o item")
        if (quantidade is not None and qtde_retorno is not None
                and abs(quantidade - qtde_retorno) > 1e-6):
            status = STATUS_REVISAR
            obs.append(f"quantidade difere: processo {quantidade:g}, retorno {qtde_retorno:g}")

    qtde_igual = None
    if quantidade is not None and qtde_retorno is not None:
        qtde_igual = abs(quantidade - qtde_retorno) <= 1e-6

    return {
        "CODIGO_KRONA": str(registro.get("CODIGO_KRONA") or ""),
        "DESCRICAO": _descricao_registro(registro) or (item or {}).get("descricao", ""),
        "QUANTIDADE": quantidade,
        "UNIDADE": _unidade(registro.get("UNIDADE")),
        "PRECO_TABELA": preco_tabela,
        "TOTAL_TABELA": total_tabela,
        "PRECO_GAMATEC": preco_gamatec,
        "TOTAL_GAMATEC": total_gamatec,
        "DESCONTO_PCT": _desconto(preco_tabela, preco_gamatec),
        "QTDE_IGUAL": qtde_igual,
        "STATUS": status,
        "VIA": via or "—",
        "OBS": "; ".join(obs) or None,
    }


def _linha_extra(item):
    qtde = _float(item.get("qtde"))
    preco = _float(item.get("preco_orcamento"))
    total = round(qtde * preco, 2) if qtde is not None and preco is not None else None
    return {
        "CODIGO_KRONA": _norm_codigo(item.get("codigo")),
        "DESCRICAO": item.get("descricao") or "",
        "QUANTIDADE": qtde,
        "UNIDADE": None,
        "PRECO_TABELA": None,
        "TOTAL_TABELA": None,
        "PRECO_GAMATEC": preco,
        "TOTAL_GAMATEC": total,
        "DESCONTO_PCT": None,
        "QTDE_IGUAL": None,
        "STATUS": STATUS_SEM,
        "VIA": VIA_SO_RETORNO,
        "OBS": "não estava no processo guardado",
    }


def comparar_retorno(registros, itens):
    """Devolve uma linha por item do processo (mais os itens só do retorno)."""
    if not registros:
        raise ValueError("O processo não tem itens para comparar.")
    retorno = _consolidar_retorno(itens or [])

    por_codigo = defaultdict(list)
    for item in retorno:
        codigo = _norm_codigo(item.get("codigo"))
        if codigo:
            por_codigo[codigo].append(item)

    usados = set()
    fila_descricao = []
    linhas = []

    for registro in registros:
        codigo = _norm_codigo(registro.get("CODIGO_KRONA") or "")
        item = None
        score_descricao = None
        if codigo:
            candidatos = [candidato for candidato in por_codigo.get(codigo, [])
                          if id(candidato) not in usados]
            if candidatos:
                descricao = _descricao_registro(registro)
                item = max(candidatos, key=lambda c: _score(descricao, c.get("descricao")))
                score_descricao = _score(descricao, item.get("descricao"))
                usados.add(id(item))
        if item is not None:
            linhas.append(_linha(registro, item, VIA_CODIGO, score_descricao))
        else:
            fila_descricao.append(registro)

    livres = [item for item in retorno if id(item) not in usados]
    for registro in fila_descricao:
        item, score = _melhor_descricao(registro, livres)
        if item is None:
            linhas.append(_linha(registro, None, None))
        else:
            livres.remove(item)
            linhas.append(_linha(registro, item, VIA_DESCRICAO, score))

    for item in livres:
        linhas.append(_linha_extra(item))

    return linhas


def _melhor_descricao(registro, livres):
    alvo = _descricao_registro(registro)
    medidas_alvo = _medidas(alvo) | _medidas(registro.get("DESCRICAO") or "")
    melhor, melhor_score = None, 0.0
    for item in livres:
        if not _medidas_compativeis(medidas_alvo, _medidas(item.get("descricao"))):
            continue
        score = max(_score(alvo, item.get("descricao")),
                    _score(registro.get("DESCRICAO") or "", item.get("descricao")))
        if score > melhor_score:
            melhor, melhor_score = item, score
    if melhor is None or melhor_score < LIMIAR_CODIGO:
        return None, None
    return melhor, melhor_score


def resumo_retorno(linhas):
    total = len(linhas)
    ok = sum(1 for linha in linhas if linha["STATUS"] == STATUS_OK)
    revisar = sum(1 for linha in linhas if linha["STATUS"] == STATUS_REVISAR)
    sem = sum(1 for linha in linhas if linha["STATUS"] == STATUS_SEM)
    extras = sum(1 for linha in linhas if linha["VIA"] == VIA_SO_RETORNO)
    sem_retorno = sum(1 for linha in linhas
                      if linha["PRECO_GAMATEC"] is None and linha["VIA"] != VIA_SO_RETORNO)
    com_ambos = [linha for linha in linhas
                 if linha["PRECO_TABELA"] is not None and linha["PRECO_GAMATEC"] is not None]
    no_total = [linha for linha in com_ambos if linha.get("QTDE_IGUAL") is True]
    fora_do_total = sum(1 for linha in com_ambos if linha.get("QTDE_IGUAL") is False)
    total_tabela = round(sum(linha["TOTAL_TABELA"] for linha in no_total
                             if linha["TOTAL_TABELA"] is not None), 2)
    total_gamatec = round(sum(linha["TOTAL_GAMATEC"] for linha in no_total
                              if linha["TOTAL_GAMATEC"] is not None), 2)
    desconto_total = (round((total_tabela - total_gamatec) / total_tabela * 100, 2)
                      if total_tabela else None)
    return {
        "total": total,
        "ok": ok,
        "revisar": revisar,
        "sem": sem,
        "extras": extras,
        "sem_retorno": sem_retorno,
        "fora_do_total": fora_do_total,
        "total_tabela": total_tabela,
        "total_gamatec": total_gamatec,
        "desconto_total": desconto_total,
    }
