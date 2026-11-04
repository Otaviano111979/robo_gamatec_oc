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
    melhor, melhor_score = None, 0.0
    for item in livres:
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
    total_tabela = round(sum(linha["TOTAL_TABELA"] for linha in com_ambos
                             if linha["TOTAL_TABELA"] is not None), 2)
    total_gamatec = round(sum(linha["TOTAL_GAMATEC"] for linha in com_ambos
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
        "total_tabela": total_tabela,
        "total_gamatec": total_gamatec,
        "desconto_total": desconto_total,
    }
