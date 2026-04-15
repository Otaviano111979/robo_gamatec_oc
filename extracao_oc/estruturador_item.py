import re
from typing import List, Optional

from extracao_oc.modelos import BlocoItem, ItemExtraido, LinhaDocumento


# Formato MRV:  idx codigo NCM qtd un frete ipi unit total
PADRAO_INICIO_ITEM = re.compile(
    r"^(?P<idx>\d{3,6})\s+"
    r"(?P<codigo>\d+)\s+"
    r"(?P<ncm>\d{4}\.\d{2}\.\d{2})\s+"
    r"(?P<quantidade>\d[\d.,]*)\s+"
    r"(?P<unidade>[A-Z]{1,5})\s+"
    r"(?P<frete>\d[\d.,]*)\s+"
    r"(?P<ipi>\d[\d.,%]*)\s+"
    r"(?P<valor_unitario>\d[\d.,]*)\s+"
    r"(?P<valor_total>\d[\d.,]*)$",
    re.IGNORECASE
)

# Formato Krona: codigo - descricao... qtd unidade precos... data
# Ex: 1795 - Joelho 45 soldavel de PVC 160,0000 un 0,7990 0,00 ... 01/06/2026
PADRAO_INICIO_ITEM_KRONA = re.compile(
    r"^(?P<codigo>\d{2,6})\s+-\s+"
    r"(?P<descricao>.+?)\s+"
    r"(?P<quantidade>\d[\d.,]*)\s+"
    r"(?P<unidade>[a-z]{1,5}\d?)\s+"
    r"(?P<valor_unitario>[\d.,]+)\s+"
    r"[\d.,]+\s+[\d.,]+\s+[\d.,]+\s+[\d.,]+\s+"
    r"(?P<valor_total>[\d.,]+)\s+"
    r"\d{2}/\d{2}/\d{4}$",
    re.IGNORECASE
)

# Formato UAU: idx descricao unidade quantidade preco_unit total
# Ex: 1 FITA VEDA ROSCA 18X50MT RL 20,000000 5,082000 101,64
_UNIDADES_UAU = r"(?:RL|UN|UND|M|MT|BR|BAR|PC|PCS|CX|KG|LT?)"
PADRAO_INICIO_ITEM_UAU = re.compile(
    r"^(?P<idx>\d{1,4})\s+"
    r"(?P<descricao>.+?)\s+"
    r"(?P<unidade>" + _UNIDADES_UAU + r")\s+"
    r"(?P<quantidade>[\d.,]+)\s+"
    r"(?P<valor_unitario>[\d.,]+)\s+"
    r"(?P<valor_total>[\d.,]+)$",
    re.IGNORECASE
)

# Formato UAU com quantidade quebrada (sem total no final)
PADRAO_INICIO_ITEM_UAU_QUEBRADO = re.compile(
    r"^(?P<idx>\d{1,4})\s+"
    r"(?P<descricao>.+?)\s+"
    r"(?P<unidade>" + _UNIDADES_UAU + r")\s+"
    r"(?P<quantidade_parcial>[\d.,]+)$",
    re.IGNORECASE
)


def numero_brasileiro_para_float(texto: str) -> Optional[float]:
    if not texto:
        return None

    texto = texto.strip()
    texto = texto.replace(".", "").replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        return None


def extrair_linha_inicio(bloco: BlocoItem) -> Optional[LinhaDocumento]:
    for linha in bloco.linhas:
        if linha.classe == "INICIO_ITEM":
            return linha
    return None


def separar_descricao_e_observacao(bloco: BlocoItem) -> tuple[List[str], List[str]]:
    descricao_partes: List[str] = []
    observacao_partes: List[str] = []

    em_observacao = False

    for linha in bloco.linhas:
        texto = linha.texto_normalizado.strip()

        if not texto:
            continue

        if linha.classe == "LINHA_OBSERVACAO":
            em_observacao = True
            continue

        if linha.classe == "SEPARADOR":
            continue

        if linha.classe == "LINHA_ENTREGA":
            continue

        if linha.classe == "INICIO_ITEM":
            continue

        if linha.classe == "DESCRICAO_ITEM":
            texto = re.sub(
                r"^DESCRIÇÃO DETALHADA DO PRODUTO\s*",
                "",
                texto,
                flags=re.IGNORECASE
            )
            texto = re.sub(
                r"^DESCRICAO DETALHADA DO PRODUTO\s*",
                "",
                texto,
                flags=re.IGNORECASE
            )

            if texto:
                descricao_partes.append(texto)
            continue

        if linha.classe == "DESCONHECIDA":
            if em_observacao:
                observacao_partes.append(texto)
            else:
                descricao_partes.append(texto)

    return descricao_partes, observacao_partes


def montar_texto_unico(partes: List[str]) -> str:
    partes_limpas = [p.strip() for p in partes if p.strip()]
    return " ".join(partes_limpas).strip()


def estruturar_bloco_item(bloco: BlocoItem) -> ItemExtraido:
    item = ItemExtraido()
    item.pagina = bloco.pagina_inicial
    item.linhas_origem = [linha.numero_linha for linha in bloco.linhas]

    linha_inicio = extrair_linha_inicio(bloco)

    if linha_inicio is None:
        item.status_extracao = "falhou"
        item.observacoes.append("linha_inicio_item_nao_encontrada")
        return item

    texto_inicio = linha_inicio.texto_normalizado

    # tenta formato MRV primeiro
    match = PADRAO_INICIO_ITEM.match(texto_inicio)
    # (bloco disponivel para formatos que precisam de linhas de continuacao, ex: UAU)

    if match:
        item.idx_item = int(match.group("idx"))
        item.codigo_interno_oc = match.group("codigo")
        item.quantidade = numero_brasileiro_para_float(match.group("quantidade"))
        item.unidade_original = match.group("unidade")
        item.unidade_normalizada = match.group("unidade").upper()
        item.valor_unitario = numero_brasileiro_para_float(match.group("valor_unitario"))
        item.valor_total = numero_brasileiro_para_float(match.group("valor_total"))
        item.observacoes.append("formato_mrv")
    else:
        # tenta formato Krona
        match_krona = PADRAO_INICIO_ITEM_KRONA.match(texto_inicio)

        if match_krona:
            item.idx_item = None  # Krona nao tem idx separado
            item.codigo_interno_oc = match_krona.group("codigo")
            item.quantidade = numero_brasileiro_para_float(match_krona.group("quantidade"))
            item.unidade_original = match_krona.group("unidade")
            item.unidade_normalizada = match_krona.group("unidade").upper()
            item.valor_unitario = numero_brasileiro_para_float(match_krona.group("valor_unitario"))
            item.valor_total = numero_brasileiro_para_float(match_krona.group("valor_total"))

            # no formato Krona a descricao parcial ja vem na linha de inicio
            descricao_inicio = match_krona.group("descricao").strip()
            if descricao_inicio:
                item.observacoes.append(f"descricao_parcial_inicio={descricao_inicio}")

            item.observacoes.append("formato_krona")
        else:
            # tenta formato UAU
            match_uau = PADRAO_INICIO_ITEM_UAU.match(texto_inicio)
            match_uau_q = PADRAO_INICIO_ITEM_UAU_QUEBRADO.match(texto_inicio) if not match_uau else None

            if match_uau:
                item.idx_item    = int(match_uau.group("idx"))
                item.codigo_interno_oc = match_uau.group("idx")
                item.quantidade  = numero_brasileiro_para_float(match_uau.group("quantidade"))
                item.unidade_original   = match_uau.group("unidade")
                item.unidade_normalizada = match_uau.group("unidade").upper()
                item.valor_unitario = numero_brasileiro_para_float(match_uau.group("valor_unitario"))
                item.valor_total    = numero_brasileiro_para_float(match_uau.group("valor_total"))
                # descricao vem diretamente do grupo capturado pelo regex
                desc = match_uau.group("descricao").strip()
                item.descricao_original     = desc
                item.descricao_reconstruida = desc
                item.observacoes.append("formato_uau")

            elif match_uau_q:
                # linha com quantidade quebrada — precisa juntar com a proxima linha
                item.idx_item = int(match_uau_q.group("idx"))
                item.codigo_interno_oc = match_uau_q.group("idx")
                item.unidade_original = match_uau_q.group("unidade")
                item.unidade_normalizada = match_uau_q.group("unidade").upper()

                # descricao vem do grupo capturado pelo regex
                desc_q = match_uau_q.group("descricao").strip()
                item.descricao_original     = desc_q
                item.descricao_reconstruida = desc_q

                # tenta reconstruir quantidade juntando com linhas de continuacao do bloco
                # ex: linha principal tem "3.000,0000" e continuacao tem "00" → "3.000,000000"
                qtd_parcial = match_uau_q.group("quantidade_parcial")
                continuacoes = [
                    l.texto_normalizado.strip()
                    for l in bloco.linhas
                    if l.classe == "DESCRICAO_ITEM"
                    and re.match(r"^\d{1,4}$", l.texto_normalizado.strip())
                ]
                if continuacoes:
                    qtd_texto = qtd_parcial + continuacoes[0]
                    item.quantidade = numero_brasileiro_para_float(qtd_texto)
                else:
                    item.quantidade = numero_brasileiro_para_float(qtd_parcial)

                item.observacoes.append("formato_uau_quebrado")
                item.observacoes.append("quantidade_reconstruida_da_quebra")

            else:
                item.status_extracao = "falhou"
                item.observacoes.append("regex_inicio_item_nao_casou_mrv_nem_krona_nem_uau")
                return item

    descricao_partes, observacao_partes = separar_descricao_e_observacao(bloco)

    # para formatos que ja extrairam a descricao diretamente do regex (UAU),
    # nao sobrescreve com o resultado do separador que seria vazio
    formato_atual = next(
        (obs.replace("formato_", "") for obs in item.observacoes if obs.startswith("formato_")),
        None
    )

    if formato_atual in ("uau", "uau_quebrado"):
        # descricao ja foi atribuida pelo regex — apenas complementa se tiver partes extras
        if not item.descricao_reconstruida:
            item.descricao_original = montar_texto_unico(descricao_partes)
            item.descricao_reconstruida = item.descricao_original
    else:
        item.descricao_original = montar_texto_unico(descricao_partes)
        item.descricao_reconstruida = item.descricao_original

    item.score_extracao = 0.85
    item.status_extracao = "ok"

    if not item.descricao_reconstruida:
        item.status_extracao = "ok_com_ressalvas"
        item.observacoes.append("descricao_vazia_ou_nao_reconstruida")

    if observacao_partes:
        item.observacoes.append("observacao_comercial_detectada")
        item.observacoes.append("texto_observacao=" + montar_texto_unico(observacao_partes))

    if bloco.observacoes:
        item.observacoes.extend(bloco.observacoes)

    if any("bloco_interrompido_por_bloco_administrativo" in obs for obs in bloco.observacoes):
        item.status_extracao = "ok_com_ressalvas"
        item.observacoes.append("item_interrompido_por_bloco_administrativo")

    return item


def estruturar_blocos_em_itens(blocos: List[BlocoItem]) -> List[ItemExtraido]:
    return [estruturar_bloco_item(bloco) for bloco in blocos]