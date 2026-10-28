# -*- coding: utf-8 -*-
"""
extracao_oc/classificador_documento.py

Decide se um PDF é Ordem de Compra, Cotação de Preços ou documento por
classificar. Hierarquia (decidida pelo utilizador):

  1. conteúdo explícito manda — mesmo contra o nome do ficheiro;
  2. conteúdo omisso -> nome do ficheiro;
  3. nome também omisso -> decisão do utilizador na UI.

Uma escolha feita na UI fica gravada em dados/tipos_documentos.json e vence
o classificador: é a decisão explícita do utilizador sobre aquele ficheiro.

Nunca devolve COTACAO para um documento com "ordem de compra"/"pedido de
compra" no topo: uma OC pode citar "Cotação nº X" como referência.
"""

import json
import os
import re
import unicodedata
from dataclasses import dataclass

import pdfplumber

from config import BASE_DIR

OC = "OC"
COTACAO = "COTACAO"
UI = "UI"

ARQ_TIPOS_DOCUMENTO = os.path.join(BASE_DIR, "dados", "tipos_documentos.json")


def tipo_definido_manualmente(nome_arquivo: str) -> str:
    """Escolha explícita do utilizador para este ficheiro (vazia se não houver)."""
    if not nome_arquivo:
        return ""
    try:
        with open(ARQ_TIPOS_DOCUMENTO, encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return ""
    if not isinstance(dados, dict):
        return ""
    tipo = dados.get(nome_arquivo) or dados.get(os.path.basename(nome_arquivo)) or ""
    return tipo if tipo in (OC, COTACAO) else ""

# titulam o documento como pedido de preço
COTACAO_FORTE = (
    "cotacao de precos",
    "coleta de precos",
    "mapa de cotacao",
    "mapa de cotacoes",
    "solicitacao de cotacao",
    "pedido de cotacao",
    "validade da cotacao",
    "informacoes da cotacao",
    "proposta de precos",
)
# apenas referenciam um número de cotação (aparecem também em OCs)
COTACAO_FRACA = ("cotacao n", "cotacao no", "cotacao numero", "cotacao.:")
COTACAO_TERMOS = COTACAO_FORTE + COTACAO_FRACA

OC_FORTE = ("ordem de compra", "pedido de compra", "dados da ordem de compra")
OC_TERMOS = OC_FORTE + ("dados do pedido", "numero do pedido", "oc n", "oc no")

RE_NOME_COTACAO = re.compile(
    r"(\bcot\b|\bcotacao\b|\bcoleta\b|\bmapa\b|\blista\b|\borcamento\b)"
)
RE_NOME_OC = re.compile(r"(\bo\.?\s?c\b|\bordem\b|\bpedido\b|\bped\b|\bocm\b|\bpc\b)")

LIMIAR_TEXTO = 100
LINHAS_CABECALHO = 20


@dataclass
class Resultado:
    tipo: str
    origem: str
    motivo: str
    sem_texto: bool = False
    paginas: int = 0


def normalizar(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def _nome_normalizado(nome: str) -> str:
    base = os.path.splitext(os.path.basename(nome))[0]
    return normalizar(re.sub(r"[_\-\.]+", " ", base))


def dica_nome(nome: str) -> str:
    """OC, COTACAO ou '' a partir do nome do ficheiro."""
    n = _nome_normalizado(nome)
    if RE_NOME_COTACAO.search(n):
        return COTACAO
    if RE_NOME_OC.search(n):
        return OC
    return ""


def _texto_inicial(caminho: str):
    """Texto da página 1 (e 2, se a 1 for imagem) + nº de páginas e imagens."""
    with pdfplumber.open(caminho) as pdf:
        paginas = len(pdf.pages)
        pagina1 = pdf.pages[0]
        texto = pagina1.extract_text() or ""
        chars = len(texto.strip())
        imagens = len(pagina1.images)
        if chars < LIMIAR_TEXTO and paginas > 1:
            texto2 = pdf.pages[1].extract_text() or ""
            texto = texto + "\n" + texto2
            chars += len(texto2.strip())
    return texto, chars, paginas, imagens


def classificar_documento(caminho: str, nome_arquivo: str = None) -> Resultado:
    nome = nome_arquivo or os.path.basename(caminho)
    dica = dica_nome(nome)

    try:
        texto, chars, paginas, imagens = _texto_inicial(caminho)
    except Exception as e:
        return Resultado(UI, "nenhum", f"leitura falhou: {e}")

    if chars < LIMIAR_TEXTO:
        detalhe = f"{chars} caracteres, {imagens} imagens na pág. 1"
        if dica == COTACAO:
            return Resultado(COTACAO, "nome", f"sem texto ({detalhe}); nome diz cotação", True, paginas)
        if dica == OC:
            return Resultado(OC, "nome", f"sem texto ({detalhe}); nome diz OC", True, paginas)
        return Resultado(UI, "nenhum", f"sem texto ({detalhe}); nome sem dica", True, paginas)

    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    cabecalho = normalizar(" ".join(linhas[:LINHAS_CABECALHO]))
    corpo = normalizar(" ".join(linhas))

    cot_forte_topo = [t for t in COTACAO_FORTE if t in cabecalho]
    oc_forte_topo = [t for t in OC_FORTE if t in cabecalho]
    cot_topo = [t for t in COTACAO_TERMOS if t in cabecalho]
    cot_corpo = [t for t in COTACAO_TERMOS if t in corpo]
    oc_topo = [t for t in OC_TERMOS if t in cabecalho]

    # OC titulada vence uma mera referência a "Cotação nº X"
    if oc_forte_topo and cot_topo and not cot_forte_topo:
        return Resultado(OC, "conteudo",
                         f"OC titulada vence referência a cotação: {oc_forte_topo[0]}", False, paginas)
    if cot_forte_topo:
        return Resultado(COTACAO, "conteudo", f"cotação no topo: {cot_forte_topo[0]}", False, paginas)
    if oc_forte_topo:
        return Resultado(OC, "conteudo", f"OC no topo: {oc_forte_topo[0]}", False, paginas)

    if cot_corpo and not oc_topo:
        achado = cot_topo[0] if cot_topo else cot_corpo[0]
        return Resultado(COTACAO, "conteudo", f"cotação no texto: {achado}", False, paginas)
    if oc_topo and not cot_corpo:
        return Resultado(OC, "conteudo", f"OC no topo: {oc_topo[0]}", False, paginas)

    if cot_corpo and oc_topo:
        if dica:
            return Resultado(dica, "nome (desempate)",
                             f"conteúdo ambíguo: cot={cot_corpo[0]}, oc={oc_topo[0]}", False, paginas)
        return Resultado(UI, "nenhum",
                         f"conteúdo ambíguo: cot={cot_corpo[0]}, oc={oc_topo[0]}", False, paginas)

    if dica:
        return Resultado(dica, "nome", "conteúdo sem sinal; nome decide", False, paginas)
    return Resultado(UI, "nenhum", "sem sinais no conteúdo nem no nome", False, paginas)
