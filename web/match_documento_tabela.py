# -*- coding: utf-8 -*-
"""Casa itens de um documento SEM preço com a tabela de preço de um cliente.

Três vias, por esta ordem:
  1. código do cliente, quando o documento o traz e ele existe na tabela;
  2. código Krona;
  3. descrição/medidas, com guardas de família — produto que a tabela não tem
     fica sem correspondência em vez de casar com um vizinho parecido.

O preço que o documento traga (de outro fornecedor) não decide nada: é só
devolvido ao lado do preço da tabela.
"""
import re
from collections import defaultdict

from rapidfuzz import fuzz

from matcher import _regra_catalogo
from matcher_tabela_cliente import (
    _codigo, _sem_acento, _tipo_de, match_tabela_cliente,
)

STATUS_OK = "OK"
STATUS_REVISAR = "REVISAR"
STATUS_SEM = "SEM"

LIMIAR_OK = 0.80       # descrição abaixo disto nunca é aceite em silêncio
LIMIAR_CODIGO = 0.50   # código certo com descrição muito diferente vai a revisão

_SEM_DESCRICAO = "código {via} confere; documento sem descrição para confirmar"

VIA_CLIENTE = "CÓD. CLIENTE"
VIA_KRONA = "CÓD. KRONA"
VIA_DESCRICAO = "DESCRIÇÃO"

# palavras que não identificam família de produto: ligações, cor, linha e o
# contexto de aplicação (a tabela abrevia-a de outra forma e não vale reprovar)
_GENERICAS = {
    "PARA", "COM", "SEM", "POR", "DOS", "DAS", "DE", "DA", "DO", "EM", "TIPO",
    "SERIE", "COR", "REF", "PECA", "MATERIAL", "CANO",
    "AGUA", "ESGOTO", "PVC", "PPR", "CPVC", "ACO",
    "SOLD", "SOLDAVEL", "ROSCA", "ROSCAVEL", "RIGIDO", "RIGIDA", "FLEXIVEL",
    "LEVE", "PESADO", "NORMAL",
    "BRANCO", "PRETO", "CINZA", "AMARELO", "AZUL", "VERDE", "VERMELHO", "MARROM",
    "INCOLOR", "CONEXAO",
}

# o mesmo produto com outro nome: a guarda de vocabulário aceita a alternativa
_SINONIMOS = {
    "BORRACHA": {"VEDACAO"},
    "VEDACAO": {"BORRACHA"},
    "SANITARIO": {"ESGOTO"},
    "ESGOTO": {"SANITARIO"},
}

_RX_PALAVRA = re.compile(r"[A-Z]{2,}")
_RX_FRACAO = re.compile(r"(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])")
_RX_EXTRA_FORTE = re.compile(r"EXTRA\s*FORTE")


def _palavras(texto):
    return _RX_PALAVRA.findall(_sem_acento(texto))


def _raiz(palavra):
    """Singular e género fora: CURTAS, CURTA e CURTO ficam na mesma raiz."""
    if len(palavra) >= 5 and palavra.endswith("S"):
        palavra = palavra[:-1]
    if len(palavra) >= 4 and palavra[-1] in "AO":
        palavra = palavra[:-1]
    return palavra


_GENERICAS_RAIZ = {_raiz(p) for p in _GENERICAS}
_SINONIMOS_RAIZ = {_raiz(chave): {_raiz(valor) for valor in valores}
                   for chave, valores in _SINONIMOS.items()}

# o catálogo usa o segundo termo; só para a chamada ao motor de descrição
_SINONIMOS_MATCH = {"SANITARIO": "ESGOTO", "BORRACHA": "VEDACAO"}
_RX_TERMO = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def _com_sinonimos(descricao):
    def troca(encontrado):
        palavra = _sem_acento(encontrado.group(0))
        return _SINONIMOS_MATCH.get(palavra, encontrado.group(0))
    return _RX_TERMO.sub(troca, descricao)


def _fracoes(texto):
    """Polegadas na descrição: 1/2" e 25 x 1/2 têm de bater com o candidato."""
    fracoes = set()
    for numerador, denominador in _RX_FRACAO.findall(_sem_acento(texto)):
        n, d = int(numerador), int(denominador)
        if n and d and n < d:
            fracoes.add((n, d))
    return fracoes


def _norm_codigo(valor):
    texto = str(valor if valor is not None else "").strip().upper()
    return re.sub(r"\s+", "", texto)


def _score(descricao_documento, descricao_tabela):
    return fuzz.token_set_ratio(
        _sem_acento(descricao_documento), _sem_acento(descricao_tabela)) / 100


def _unidade(valor):
    return str(valor or "").strip().upper() or None


def _vocabulario(descricoes):
    palavras = set()
    for descricao in descricoes:
        palavras.update(_raiz(p) for p in _palavras(descricao))
    return palavras


def _suportado(palavra, vocabulario):
    """A tabela cobre a palavra? Aceita abreviaturas (RED. / REDUÇÃO)."""
    if palavra in vocabulario:
        return True
    return any(
        (len(candidata) >= 3 and palavra.startswith(candidata))
        or (len(palavra) >= 4 and candidata.startswith(palavra))
        for candidata in vocabulario
    )


class _Contexto:
    """Índices e vocabulários calculados uma vez por comparação."""

    def __init__(self, indice):
        self.indice = indice
        self.tipos = indice["descricao_krona"].map(_tipo_de)
        self._vocabularios = {}
        self.por_cliente = defaultdict(list)
        self.por_krona = {}
        for _, linha in indice.iterrows():
            registro = linha.to_dict()
            chave = _norm_codigo(registro.get("codigo_cliente"))
            if chave:
                self.por_cliente[chave].append(registro)
            self.por_krona[str(registro.get("_codigo"))] = registro

    def do_tipo(self, tipo):
        return self.indice[self.tipos == tipo]

    def vocabulario(self, tipo):
        chave = tipo or "__TODOS__"
        if chave not in self._vocabularios:
            base = self.do_tipo(tipo) if tipo else self.indice
            self._vocabularios[chave] = _vocabulario(base["descricao_krona"])
        return self._vocabularios[chave]


def _registro(item, tabela, via, status, obs=None, score=None):
    preco = tabela.get("preco_tabela") if tabela else None
    preco = float(preco) if preco else None
    quantidade = float(item.get("quantidade") or 0)
    registro = {
        "CODIGO_CLIENTE": str(item.get("codigo_cliente") or ""),
        "CODIGO_KRONA": str(tabela.get("_codigo") or "") if tabela else "",
        "DESCRICAO": item.get("descricao") or "",
        "DESCRICAO_TABELA": str(tabela.get("descricao_krona") or "") if tabela else "",
        "QUANTIDADE": quantidade,
        "UNIDADE": _unidade(item.get("unidade")),
        "UNIDADE_TABELA": _unidade(tabela.get("unidade_venda")) if tabela else None,
        "PRECO_TABELA": preco,
        "TOTAL": round(quantidade * preco, 2) if preco else None,
        "PRECO_DOCUMENTO": item.get("preco_documento"),
        "STATUS": status,
        "VIA": via,
        "SCORE": round(score, 3) if score is not None else None,
        "OBS": obs,
        "LINHAS": 1,
    }
    registro["OBS"] = _avaliar_unidade(item, registro, obs)
    if registro["OBS"] and registro["STATUS"] == STATUS_OK:
        registro["STATUS"] = STATUS_REVISAR
    return registro


def _avaliar_unidade(item, registro, obs):
    documento = _unidade(item.get("unidade"))
    tabela = registro.get("UNIDADE_TABELA")
    if not documento or not tabela or documento == tabela:
        return obs
    # só a diferença entre metro e embalagem altera a quantidade a comprar
    if {documento, tabela} & {"M", "MT"} and {documento, tabela} & {"BR", "UN"}:
        aviso = f"unidade difere: documento {documento}, tabela {tabela}"
        return f"{obs}; {aviso}" if obs else aviso
    return obs


def _por_codigo_cliente(item, achados):
    descricao = item.get("descricao") or ""
    escolhido = max(achados, key=lambda t: _score(descricao, t.get("descricao_krona")))
    score = _score(descricao, escolhido.get("descricao_krona"))
    status = STATUS_OK if score >= LIMIAR_CODIGO else STATUS_REVISAR
    obs = None
    if len(achados) > 1:
        obs = f"código do cliente repetido na tabela ({len(achados)} itens)"
    elif status == STATUS_REVISAR:
        obs = (_SEM_DESCRICAO.format(via="do cliente") if not descricao.strip()
               else "código do cliente confere, descrição muito diferente")
    return _registro(item, escolhido, VIA_CLIENTE, status, obs, score)


def _por_codigo_krona(item, tabela):
    descricao = item.get("descricao") or ""
    score = _score(descricao, tabela.get("descricao_krona"))
    status = STATUS_OK if score >= LIMIAR_CODIGO else STATUS_REVISAR
    obs = None
    if status == STATUS_REVISAR:
        obs = (_SEM_DESCRICAO.format(via="Krona") if not descricao.strip()
               else "código Krona confere, descrição muito diferente")
    return _registro(item, tabela, VIA_KRONA, status, obs, score)


def _por_regra_catalogo(item, ctx, base_krona):
    if base_krona is None:
        return None
    regra = _regra_catalogo({"descricao_oc": item.get("descricao") or ""}, base_krona)
    if not regra:
        return None
    if regra.get("_regra_bloqueia"):
        return _registro(
            item, None, VIA_DESCRICAO, STATUS_SEM,
            "produto reconhecido no catálogo, mas o tamanho declarado não está cadastrado",
        )
    tabela = ctx.por_krona.get(_codigo(regra.get("codigo_krona")))
    if tabela is None:
        return _registro(
            item, None, VIA_DESCRICAO, STATUS_SEM,
            f"produto do catálogo (cód. {regra.get('codigo_krona')}) não está nesta tabela",
        )
    status = (STATUS_REVISAR if str(regra.get("tipo_match", "")).endswith("REVISAR")
              else STATUS_OK)
    return _registro(item, tabela, VIA_DESCRICAO, status, "regra de catálogo", 1.0)


def _tokens_ausentes(descricao, vocabulario, tipo):
    raiz_tipo = _raiz(tipo) if tipo else None
    ausentes = []
    for palavra in _palavras(descricao):
        chave = _raiz(palavra)
        if chave == raiz_tipo or chave in _GENERICAS_RAIZ or len(chave) < 4:
            continue
        if _suportado(chave, vocabulario):
            continue
        if any(_suportado(sinonimo, vocabulario)
               for sinonimo in _SINONIMOS_RAIZ.get(chave, ())):
            continue
        if palavra not in ausentes:
            ausentes.append(palavra)
    return ausentes


_RX_ANGULO_X_MEDIDA = re.compile(r"\b(\d{1,3})\s*X\s*(?:45|90)\b", re.IGNORECASE)
_RX_ANGULO_ANTES = re.compile(r"\b(?:45|90)\s*X\s*(\d{1,3})\b", re.IGNORECASE)
_TIPOS_COM_ANGULO = {"JOELHO", "TE", "CURVA"}


def _sem_angulo(descricao):
    """'JOELHO 25 X 90' é joelho de 90° com 25 mm; 90 não é diâmetro."""
    if _tipo_de(descricao) not in _TIPOS_COM_ANGULO:
        return descricao
    texto = _RX_ANGULO_X_MEDIDA.sub(r"\1", descricao)
    return _RX_ANGULO_ANTES.sub(r"\1", texto)


def _por_descricao(item, ctx):
    descricao = item.get("descricao") or ""
    tipo = _tipo_de(descricao)

    if tipo:
        restrito = ctx.do_tipo(tipo)
        if restrito.empty:
            return _registro(
                item, None, VIA_DESCRICAO, STATUS_SEM,
                f"{tipo.title()} não existe nesta tabela de preços",
            )
    else:
        restrito = ctx.indice
        palavras = [p for p in _palavras(descricao)
                    if _raiz(p) not in _GENERICAS_RAIZ and len(_raiz(p)) >= 4]
        if palavras:
            cabeca = _raiz(palavras[0])
            if not _suportado(cabeca, ctx.vocabulario(None)):
                return _registro(
                    item, None, VIA_DESCRICAO, STATUS_SEM,
                    f"{palavras[0].title()} não existe nesta tabela de preços",
                )

    descricao_match = _com_sinonimos(descricao)
    resultado = match_tabela_cliente(
        {"descricao_oc": descricao_match, "quantidade": item.get("quantidade")}, restrito)
    ajuste_angulo = None
    if resultado is None:
        sem_angulo = _sem_angulo(descricao_match)
        if sem_angulo != descricao_match:
            resultado = match_tabela_cliente(
                {"descricao_oc": sem_angulo, "quantidade": item.get("quantidade")},
                restrito)
            if resultado is not None:
                ajuste_angulo = "ângulo lido como medida na descrição; confirme o item"
    if resultado is None:
        return _registro(
            item, None, VIA_DESCRICAO, STATUS_SEM, "sem descrição compatível na tabela")

    score = resultado.get("score_total", 0) or 0
    ausentes = _tokens_ausentes(descricao, ctx.vocabulario(tipo), tipo)
    if ausentes:
        return _registro(
            item, None, VIA_DESCRICAO, STATUS_SEM,
            "sem " + ", ".join(a.lower() for a in ausentes) + " nesta tabela de preços",
        )

    obs = ajuste_angulo
    if resultado.get("revisao_manual") or score < LIMIAR_OK:
        obs = (f"{obs}; descrição parecida; confirme o item" if obs
               else "descrição parecida; confirme o item")

    fracoes_doc = _fracoes(descricao)
    fracoes_tabela = _fracoes(resultado.get("descricao_krona") or "")
    if fracoes_doc != fracoes_tabela:
        aviso = ("medida em polegada difere" if fracoes_tabela
                 else "medida em polegada não confirmada")
        obs = f"{obs}; {aviso}" if obs else aviso

    # extraforte é outra linha de produto (preço diferente); não pode entrar
    # como OK quando o documento não a declara
    if (_RX_EXTRA_FORTE.search(_sem_acento(resultado.get("descricao_krona") or ""))
            and not _RX_EXTRA_FORTE.search(_sem_acento(descricao))):
        aviso = "tabela tem variante extraforte; confirme o item"
        obs = f"{obs}; {aviso}" if obs else aviso

    codigo_tabela = _codigo(resultado.get("codigo_krona"))
    tabela = dict(ctx.por_krona.get(str(codigo_tabela)) or {})
    tabela.setdefault("_codigo", codigo_tabela)
    tabela.setdefault("descricao_krona", resultado.get("descricao_krona"))
    tabela.setdefault("preco_tabela", resultado.get("preco_tabela"))

    status = STATUS_REVISAR if obs else STATUS_OK
    return _registro(item, tabela, VIA_DESCRICAO, status, obs, score)


def _comparar_item(item, ctx, base_krona):
    codigo = _norm_codigo(item.get("codigo_cliente"))
    confiavel = bool(codigo) and item.get("codigo_confiavel", True)
    tem_codigos_cliente = bool(ctx.por_cliente)

    if confiavel:
        if tem_codigos_cliente:
            achados = ctx.por_cliente.get(codigo)
            if achados:
                return _por_codigo_cliente(item, achados)
        tabela = ctx.por_krona.get(_codigo(codigo))
        if tabela is not None:
            return _por_codigo_krona(item, tabela)

    regra = _por_regra_catalogo(item, ctx, base_krona)
    if regra is None:
        regra = _por_descricao(item, ctx)

    # a tabela deste cliente não usa códigos: o código do documento não
    # acrescenta nada e não pode transformar um bom match em revisão
    if confiavel and tem_codigos_cliente:
        prefixo = f"código {codigo} não existe na tabela"
        regra["OBS"] = f"{prefixo}; {regra['OBS']}" if regra["OBS"] else prefixo
        if regra["STATUS"] == STATUS_OK:
            regra["STATUS"] = STATUS_REVISAR
    return regra


def _consolidar(registros):
    """Soma linhas repetidas do documento (mesmo produto) numa só."""
    agrupados = {}
    ordem = []
    for registro in registros:
        chave = (registro["CODIGO_KRONA"]
                 or f"SEM|{registro['CODIGO_CLIENTE']}|{registro['DESCRICAO']}"
                 f"|{registro['UNIDADE'] or ''}")
        if chave not in agrupados:
            agrupados[chave] = dict(registro)
            ordem.append(chave)
            continue
        atual = agrupados[chave]
        atual["QUANTIDADE"] = round(atual["QUANTIDADE"] + registro["QUANTIDADE"], 3)
        atual["LINHAS"] += 1
        if atual["PRECO_TABELA"]:
            atual["TOTAL"] = round(atual["QUANTIDADE"] * atual["PRECO_TABELA"], 2)
        if registro.get("PRECO_DOCUMENTO"):
            atual["PRECO_DOCUMENTO"] = registro["PRECO_DOCUMENTO"]

    consolidados = []
    for chave in ordem:
        registro = agrupados[chave]
        if registro["LINHAS"] > 1:
            aviso = f"{registro['LINHAS']} linhas do documento somadas"
            registro["OBS"] = f"{registro['OBS']}; {aviso}" if registro["OBS"] else aviso
        consolidados.append(registro)
    return consolidados


def comparar_documento_tabela(itens_documento, indice, base_krona=None):
    """Devolve os itens do documento com código, preço e estado de cada um."""
    if not itens_documento:
        raise ValueError("O documento não tem itens para comparar.")
    if indice is None or indice.empty:
        raise ValueError("A tabela de preços do cliente não tem itens utilizáveis.")

    ctx = _Contexto(indice)
    registros = [_comparar_item(item, ctx, base_krona) for item in itens_documento]
    return _consolidar(registros)


def resumo(registros):
    total = len(registros)
    ok = sum(1 for r in registros if r["STATUS"] == STATUS_OK)
    revisar = sum(1 for r in registros if r["STATUS"] == STATUS_REVISAR)
    sem = sum(1 for r in registros if r["STATUS"] == STATUS_SEM)
    com_preco = sum(1 for r in registros if r["PRECO_TABELA"])
    com_preco_documento = sum(1 for r in registros if r["PRECO_DOCUMENTO"])
    valor = sum(r["TOTAL"] for r in registros if r["TOTAL"])
    return {
        "total": total,
        "ok": ok,
        "revisar": revisar,
        "sem": sem,
        "sem_preco": total - com_preco,
        "com_preco_documento": com_preco_documento,
        "valor_total": round(valor, 2),
    }
