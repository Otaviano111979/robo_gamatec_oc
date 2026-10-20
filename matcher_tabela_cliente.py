# -*- coding: utf-8 -*-
"""Match de itens de OC contra a tabela de preco do proprio cliente.

Sem IA: reutiliza o motor de descricao do matcher (categoria, diametro,
material, serie) restrito aos itens contratados do cliente. O preco entra
depois, so como confirmacao: o desconto varia por obra e por item, por isso
nunca exclui candidatos nem decide sozinho.

Corre so quando o cliente tem tabela importada (ver tabelas_clientes.py);
MRV/Brasal seguem o fluxo de sempre.
"""
import re
import unicodedata

JANELA_CONFIRMA = 0.05   # preco confere se estiver a +-5% do fator da OC
FATOR_MINIMO = 0.5       # fora de [0.5x, 2x] o preco e considerado divergente
FATOR_MAXIMO = 2.0

# tipo de produto: rede de seguranca para categorias que o matcher principal
# nao conhece (ANEL, BOCAL...). Impede TUBO de casar com LUVA, por exemplo.
_TIPOS = [
    "TUBO", "CAP", "JOELHO", "CURVA", "TE", "LUVA", "REDUCAO", "ADAPTADOR",
    "BUCHA", "REGISTRO", "VALVULA", "FITA", "TORNEIRA", "ADESIVO", "COLA",
    "PASTA", "FLANGE", "UNIAO", "JUNCAO", "ANEL", "BOCAL", "SIFAO", "RALO",
    "CAIXA", "TAMPA", "GRELHA", "SOLUCAO", "CONEXAO", "ESPUMA",
]
_RX_TIPOS = re.compile(r"\b(" + "|".join(_TIPOS) + r")\b")
_RX_ELETRODUTO = re.compile(r"\bELETROD(?:UTO)?\b")
_RX_ANGULO = re.compile(r"(?<!\d)(45|90)(?!\d)")
_RX_ROSCA = re.compile(r"\bROSCA|\bLR\b|\(LR\)")


def _codigo(valor):
    texto = str(valor if valor is not None else "").strip()
    try:
        return str(int(float(texto)))
    except ValueError:
        return texto


def _sem_acento(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def _tipo_de(texto):
    texto = _sem_acento(texto)
    if _RX_ELETRODUTO.search(texto):
        return "ELETRODUTO"
    # o catalogo abrevia "CX." (CX.SIFONADA); sem isto a caixa fica fora do
    # filtro de tipo e sobra so o "CORPO CAIXA SIFONADA".
    if re.search(r"\bCX\.?\b", texto):
        return "CAIXA"
    achado = _RX_TIPOS.search(texto)
    return achado.group(1) if achado else None


def _assinatura_produto(descricao):
    """Traços que distinguem variantes do mesmo tipo (45 vs 90, LR, reducao)."""
    texto = _sem_acento(_repara_texto(descricao))
    angulos = tuple(sorted({int(a) for a in _RX_ANGULO.findall(texto)}))
    return (_tipo_de(texto), angulos, _e_reducao(texto), bool(_RX_ROSCA.search(texto)))


def _mesmo_produto(desc_oc, desc_alt):
    """So permite troca por preco entre variantes do mesmo produto."""
    assinatura_oc = _assinatura_produto(desc_oc)
    if not assinatura_oc[0]:
        return False
    return assinatura_oc == _assinatura_produto(desc_alt)


def _preco_unitario_item(item):
    """Preco unitario da linha da OC, qualquer que seja o extrator.

    UAU/MRV trazem valor_unitario; Sienge dedicado traz preco_total; o
    extrator generico da EBM poe o total da linha em preco_unit.
    """
    def _num(valor):
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return None
        return valor if valor > 0 else None

    unitario = _num(item.get("valor_unitario"))
    if unitario:
        return unitario
    quantidade = _num(item.get("quantidade_oc")) or _num(item.get("quantidade"))
    total = _num(item.get("preco_total"))
    if total and quantidade:
        return total / quantidade
    preco = _num(item.get("preco_unit")) or _num(item.get("preco_unitario"))
    if preco and quantidade:
        return preco / quantidade
    return None


_RX_PARES_DIAMETRO = (
    re.compile(r"\bDN\s*(\d{1,3})\s*X\s*(\d{1,3})\b"),
    re.compile(r"\b(\d{1,3})\s*X\s*(\d{1,3})\s*MM\b"),
    re.compile(r"\bD\s*=?\s*(\d{1,3})\s*X\s*(\d{1,3})\b"),
)
# "DN40X6M" (metros) nao termina em fronteira de palavra, entao o \b falha
_RX_DN_SIMPLES = re.compile(r"\bD\.?N\.?\s*(\d{2,3})(?!\d)")


def _completar_diametros(base):
    """Preenche diametros que a base deixou vazios em descricoes 'DN 100X50'.

    Sem isso o filtro por diametro nao acha a reducao certa e sobra um item
    de medida unica, que casa por engano.
    """
    vazios = base["diametro_mm"].isna() & base["diametro_final_mm"].isna()
    for posicao in base.index[vazios]:
        texto = _sem_acento(base.at[posicao, "descricao_krona"])
        for padrao in _RX_PARES_DIAMETRO:
            achado = padrao.search(texto)
            if achado:
                maior, menor = sorted(
                    (int(achado.group(1)), int(achado.group(2))), reverse=True)
                base.at[posicao, "diametro_mm"] = float(maior)
                base.at[posicao, "diametro_final_mm"] = float(menor)
                break
        else:
            achado = _RX_DN_SIMPLES.search(texto)
            if achado:
                base.at[posicao, "diametro_mm"] = float(int(achado.group(1)))


def preparar_indice(itens, base_krona):
    """Subconjunto da base Krona com os itens da tabela do cliente + precos."""
    if base_krona is None or base_krona.empty or not itens:
        return None
    tabela = {}
    for item in itens:
        codigo = _codigo(item.get("codigo_krona"))
        preco = item.get("preco")
        if codigo and preco:
            tabela[codigo] = item
    if not tabela:
        return None
    base = base_krona.copy()
    base["_codigo"] = base["codigo_krona"].map(_codigo)
    base = base[base["_codigo"].isin(tabela)].drop_duplicates("_codigo").copy()
    if base.empty:
        return None
    base["preco_tabela"] = base["_codigo"].map(lambda c: float(tabela[c]["preco"]))
    base["descricao_tabela"] = base["_codigo"].map(
        lambda c: tabela[c].get("descricao") or "")
    base["codigo_cliente"] = base["_codigo"].map(
        lambda c: str(tabela[c].get("codigo_cliente") or ""))
    _completar_diametros(base)
    return base


_REPAROS_CHARS = ("\ufffd", "ø", "Ø")
_REPAROS_TEXTO = str.maketrans({c: " " for c in _REPAROS_CHARS})
_RX_SERIE_R = re.compile(r"\bS\s*[ÉE]RIE\s*R\b", re.IGNORECASE)


def _repara_texto(descricao):
    """Conserta marcas de PDF que escondem medida/serie do item.

    'ø100MM' colado ao numero impede o regex de achar o diametro; e a
    'SERIE R' da Krona e a linha reforcada, que o extrator de subcategoria
    so reconhece por 'REFORC'.
    """
    texto = str(descricao or "").translate(_REPAROS_TEXTO)
    texto = _RX_SERIE_R.sub("SERIE REFORCADA", texto)
    return re.sub(r"\bRECUCAO\b", "REDUCAO", texto)


def _texto_reparado(item):
    descricao = str(item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
    reparada = _repara_texto(descricao)
    if reparada == descricao:
        return item
    reparado = {**item}
    if item.get("descricao_oc"):
        reparado["descricao_oc"] = _repara_texto(item["descricao_oc"])
    if item.get("descricao_reconstruida"):
        reparado["descricao_reconstruida"] = _repara_texto(item["descricao_reconstruida"])
    return reparado


_RX_REDUCAO = re.compile(r"\bRED(U|\.|\b)")
_RX_REFORCADA = re.compile(r"REFORC|\bSR\b")
_RX_NORMAL = re.compile(r"SERIE\s*NORMAL|\bPRIM\b|\bSEC\b")


def _e_reducao(descricao):
    return bool(_RX_REDUCAO.search(_sem_acento(descricao)))


def _serie_de(descricao):
    """Serie de esgoto declarada na descricao (REFORCADA/NORMAL) ou None."""
    texto = _sem_acento(_repara_texto(descricao))
    if _RX_REFORCADA.search(texto):
        return "REFORCADA"
    if _RX_NORMAL.search(texto):
        return "NORMAL"
    return None


def _oc_pede_reducao(item):
    from matcher import _diametros_de

    descricao = _sem_acento(item.get("descricao_oc") or item.get("descricao_reconstruida"))
    return bool(_RX_REDUCAO.search(descricao)) or len(_diametros_de(descricao)) >= 2


_RX_NUMERO = re.compile(r"\d{1,3}")


def _numeros_descricao(descricao):
    return {int(n) for n in _RX_NUMERO.findall(_sem_acento(descricao)) if int(n) >= 10}


_RX_PAR_LOCAL = re.compile(r"(\d{2,3})\s*X\s*(\d{2,3})")


def _medidas_oc(item):
    from matcher import _diametros_de

    descricao = item.get("descricao_oc") or item.get("descricao_reconstruida") or ""
    medidas = set(_diametros_de(descricao))
    # 'NORMAL100x50' nao tem \b antes do 100; o par local recupera a medida
    for primeiro, segundo in _RX_PAR_LOCAL.findall(_sem_acento(descricao)):
        medidas.update((int(primeiro), int(segundo)))
    return {m for m in medidas if m >= 10}


def _indice_do_tipo(indice, item):
    """Restringe ao mesmo tipo de produto quando a OC e a tabela o permitem."""
    tipo = _tipo_de(item.get("descricao_oc") or item.get("descricao_reconstruida"))
    if not tipo:
        return indice
    mascara = indice["descricao_krona"].map(_tipo_de) == tipo
    if mascara.any():
        return indice[mascara]
    return indice


def _match_no_indice(item, indice):
    from matcher import extrair_material_da_descricao, match_por_descricao, _conflito_hard

    item = _texto_reparado(item)
    alvo = _indice_do_tipo(indice, item)
    material = extrair_material_da_descricao(
        item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
    if material:
        alvo = alvo[alvo["descricao_krona"].map(
            lambda descricao: extrair_material_da_descricao(descricao) == material)]
        if alvo.empty:
            return None
    if not _oc_pede_reducao(item):
        retas = alvo[~alvo["descricao_krona"].map(_e_reducao)]
        if not retas.empty:
            alvo = retas
    medidas = _medidas_oc(item)
    if medidas:
        filtrado = alvo[alvo["descricao_krona"].map(
            lambda descricao: medidas <= _numeros_descricao(descricao))]
        if filtrado.empty:
            return None
        alvo = filtrado

    # o topo pode violar uma restricao dura (medida/material/serie); nesse
    # caso tenta o proximo colocado antes de desistir do item
    tipo_oc = _tipo_de(item.get("descricao_oc"))
    for _ in range(4):
        resultado = match_por_descricao(item, alvo)
        if not resultado.get("match_encontrado"):
            return None
        tipo_cand = _tipo_de(resultado.get("descricao_krona"))
        mesmo_tipo = not tipo_oc or not tipo_cand or tipo_oc == tipo_cand
        if mesmo_tipo and not _conflito_hard(item, resultado):
            return resultado
        restante = alvo[alvo["_codigo"] != _codigo(resultado.get("codigo_krona"))]
        if len(restante) == len(alvo):
            return None
        alvo = restante
    return None


def _preco_tabela_de(indice, codigo):
    linhas = indice.loc[indice["_codigo"] == _codigo(codigo), "preco_tabela"]
    return float(linhas.iloc[0]) if len(linhas) else None


def _avaliar_preco(razao, fator):
    """True confirma, False divergente, None sem dados para decidir."""
    referencia = fator or 1.0
    relativo = razao / referencia
    if JANELA_CONFIRMA >= abs(relativo - 1):
        return True
    if relativo < FATOR_MINIMO or relativo > FATOR_MAXIMO:
        return False
    return None


def _tentativa_por_preco(item, indice, fator, referencia):
    """Entre os itens com preco compativel, tenta um match tao bom quanto o atual.

    So serve para desempatar versoes do mesmo produto (ex.: TE soldavel com e
    sem rosca) quando o preco da OC aponta para uma delas. Nunca troca a serie
    de esgoto que a OC declara: nesse caso devolve conflito para revisao.
    """
    preco_oc = _preco_unitario_item(item)
    if not preco_oc:
        return None, False
    base_fator = fator or 1.0
    razao = preco_oc / indice["preco_tabela"]
    alvo = indice[((razao / base_fator) - 1).abs() <= 0.10]
    if alvo.empty:
        return None, False
    alternativo = _match_no_indice(item, alvo)
    if not alternativo:
        return None, False

    serie_oc = _serie_de(item.get("descricao_oc") or item.get("descricao_reconstruida"))
    serie_alt = _serie_de(alternativo.get("descricao_krona"))
    if (serie_oc
            and serie_alt is not None
            and serie_alt != serie_oc
            and _serie_de(referencia.get("descricao_krona")) == serie_oc):
        return None, True

    # a serie acima gera revisao de proposito; aqui so travamos trocas entre
    # produtos diferentes (45 vs 90, luva vs eletroduto, com/sem rosca)
    if not _mesmo_produto(
            item.get("descricao_oc") or item.get("descricao_reconstruida"),
            alternativo.get("descricao_krona")):
        return None, False

    score_alternativo = alternativo.get("score_total", 0)
    preco_alternativo = _preco_tabela_de(indice, alternativo.get("codigo_krona"))
    confirma = bool(
        preco_alternativo
        and abs(preco_oc / preco_alternativo / (fator or 1.0) - 1) <= JANELA_CONFIRMA
    )
    score_referencia = referencia.get("score_total", 0)
    if score_alternativo >= score_referencia - 0.10 or (confirma and score_alternativo >= 0.55):
        return alternativo, False
    return None, False


def _preferir_preco_exato(item, indice, resultado, fator):
    """Troca por candidato de preco praticamente igual quando o atual diverge.

    Variantes do mesmo produto (ex.: CAP serie normal vs reforcada, caixa
    completa vs corpo) tem descricoes quase iguais e precos proximos; o preco
    da OC desempata sem nunca sobrepor uma serie que a OC declare.
    """
    preco_oc = _preco_unitario_item(item)
    codigo_atual = _codigo(resultado.get("codigo_krona"))
    preco_atual = _preco_tabela_de(indice, codigo_atual)
    if not preco_oc or not preco_atual:
        return resultado, False
    referencia = fator or 1.0
    razoes = preco_oc / indice["preco_tabela"].astype(float)
    alvo = indice[((razoes / referencia) - 1).abs() <= 0.01]
    alvo = alvo[alvo["_codigo"] != codigo_atual]
    if alvo.empty:
        return resultado, False

    alternativo = _match_no_indice(item, alvo)
    if not alternativo:
        return resultado, False
    if not _mesmo_produto(
            item.get("descricao_oc") or item.get("descricao_reconstruida"),
            alternativo.get("descricao_krona")):
        return resultado, False
    serie_oc = _serie_de(item.get("descricao_oc") or item.get("descricao_reconstruida"))
    serie_alt = _serie_de(alternativo.get("descricao_krona"))
    if serie_oc and serie_alt and serie_alt != serie_oc:
        return resultado, False

    desvio_atual = abs(preco_oc / preco_atual / referencia - 1)
    score_atual = resultado.get("score_total", 0)
    score_alternativo = alternativo.get("score_total", 0)
    if desvio_atual > 0.01 and (
            score_alternativo >= score_atual - 0.05
            or (desvio_atual > 0.20 and score_alternativo >= 0.45)):
        return alternativo, True
    return resultado, False


def match_tabela_cliente(item, indice, fator_preco=None):
    """Devolve o resultado do match na tabela do cliente ou None."""
    if indice is None or indice.empty:
        return None
    resultado = _match_no_indice(item, indice)
    if resultado is None:
        return None

    preco_oc = _preco_unitario_item(item)
    preco_tabela = _preco_tabela_de(indice, resultado.get("codigo_krona"))
    preco_confirmado = None
    conflito_serie = False
    if preco_oc and preco_tabela:
        preco_confirmado = _avaliar_preco(preco_oc / preco_tabela, fator_preco)
        if preco_confirmado is not True:
            alternativo, conflito_serie = _tentativa_por_preco(
                item, indice, fator_preco, resultado)
            if alternativo:
                resultado = alternativo
                preco_tabela = _preco_tabela_de(indice, resultado.get("codigo_krona"))
                preco_confirmado = _avaliar_preco(preco_oc / preco_tabela, fator_preco)
        if not conflito_serie:
            alternativo, trocado = _preferir_preco_exato(
                item, indice, resultado, fator_preco)
            if trocado:
                resultado = alternativo
                preco_tabela = _preco_tabela_de(indice, resultado.get("codigo_krona"))
                preco_confirmado = _avaliar_preco(preco_oc / preco_tabela, fator_preco)

    score = resultado.get("score_total", 0)
    revisar = (
        conflito_serie
        or preco_confirmado is False
        or (bool(resultado.get("revisao_manual")) and preco_confirmado is not True)
        or (score < 0.65 and preco_confirmado is not True)
    )
    motivo = f"TABELA_CLIENTE(desc={score:.2f}"
    if preco_confirmado:
        motivo += ", preco confere"
    elif preco_confirmado is False:
        motivo += ", preco diverge"
    if conflito_serie:
        motivo += ", preco aponta outra serie"
    motivo += ")"

    return {
        **resultado,
        "tipo_match": "MATCH_TABELA_CLIENTE_REVISAR" if revisar else "MATCH_TABELA_CLIENTE",
        "revisao_manual": revisar,
        "motivo_match": motivo,
        "preco_tabela": round(preco_tabela, 4) if preco_tabela else None,
        "preco_oc": round(preco_oc, 4) if preco_oc else None,
    }


def estimar_fator_preco(df_oc, indice):
    """Fator preco_oc/preco_tabela mais frequente na OC (desconto da obra)."""
    if indice is None or indice.empty or df_oc is None or df_oc.empty:
        return None
    razoes = []
    for _, row in df_oc.iterrows():
        item = row.to_dict()
        preco = _preco_unitario_item(item)
        if not preco:
            continue
        candidato = _match_no_indice(item, indice)
        if not candidato or candidato.get("score_total", 0) < 0.60:
            continue
        preco_tabela = _preco_tabela_de(indice, candidato.get("codigo_krona"))
        if preco_tabela:
            razoes.append(preco / preco_tabela)

    if len(razoes) < 2:
        return None
    razoes.sort()
    melhor_grupo = []
    for razao in razoes:
        grupo = [x for x in razoes if razao / 1.015 <= x <= razao * 1.015]
        if len(grupo) > len(melhor_grupo):
            melhor_grupo = grupo
    if len(melhor_grupo) < max(2, int(0.3 * len(razoes))):
        return None
    melhor_grupo.sort()
    return melhor_grupo[len(melhor_grupo) // 2]
