# -*- coding: utf-8 -*-
import math
from typing import Dict, Any


# =============================================================
# MAPEAMENTO DE UNIDADES CONHECIDAS
# =============================================================
#
# Cada entrada mapeia variações de escrita para uma categoria:
#
#   UNIDADE  — peça/unidade avulsa (UN, PC, PÇ, PEC, PECA...)
#   METRO    — comprimento em metros (M, MT, METRO...)
#   BARRA    — barra direta (BAR, BR, BARRA...)
#   CAIXA    — embalagem caixa (CX, CXA, CAIXA...)
#   ROLO     — vendido em rolo (RL, ROLO...)
#   KG       — peso (KG, KGS, QUILO...)
#   LITRO    — volume (L, LT, LITRO...)
#
# Se a unidade da OC não estiver em nenhuma lista, cai em
# UNIDADE_OC_NAO_MAPEADA e é sinalizada para revisão manual.
#
UNIDADES_UNIDADE = {"UN", "UND", "UNID", "UNIDADE", "PC", "PÇ", "PEC", "PECA", "PEÇA", "PCS"}
UNIDADES_METRO   = {"M", "MT", "MTR", "METRO", "METROS"}
UNIDADES_BARRA   = {"BAR", "BR", "BARRA", "BARRAS", "BRS"}
UNIDADES_CAIXA   = {"CX", "CXA", "CX.", "CAIXA", "CAIXAS"}
UNIDADES_ROLO    = {"RL", "RLO", "ROLO", "ROLOS"}
UNIDADES_KG      = {"KG", "KGS", "QUILO", "QUILOS", "QUILOGRAMA"}
UNIDADES_LITRO   = {"L", "LT", "LTS", "LITRO", "LITROS"}


def classificar_unidade(unidade_oc: str) -> str:
    u = unidade_oc.strip().upper()
    if u in UNIDADES_UNIDADE:
        return "UNIDADE"
    if u in UNIDADES_METRO:
        return "METRO"
    if u in UNIDADES_BARRA:
        return "BARRA"
    if u in UNIDADES_CAIXA:
        return "CAIXA"
    if u in UNIDADES_ROLO:
        return "ROLO"
    if u in UNIDADES_KG:
        return "KG"
    if u in UNIDADES_LITRO:
        return "LITRO"
    return "DESCONHECIDA"


def ajustar_quantidade_tubo(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ajusta quantidade conforme a unidade da OC e o tipo de produto.

    Regras:
    - Não é tubo               -> mantém quantidade original
    - Tubo em UNIDADE ou BARRA -> já está em barras, mantém
    - Tubo em METRO            -> converte para barras (CEIL)
    - Tubo em CAIXA/ROLO/KG/L  -> mantém e sinaliza para revisão
    - Unidade desconhecida     -> mantém e sinaliza para revisão
    """

    unidade_oc = str(
        item.get("unidade")
        or item.get("unidade_oc")
        or item.get("um")
        or ""
    ).strip().upper()

    quantidade_original = item.get("quantidade")
    eh_tubo = item.get("eh_tubo_krona")
    comprimento_barra = item.get("comprimento_krona_m")

    item["quantidade_original_oc"] = quantidade_original
    item["unidade_original_oc"] = unidade_oc

    classe_unidade = classificar_unidade(unidade_oc)

    # ------------------------------------------------------
    # Não é tubo -> mantém, só classifica a unidade
    # ------------------------------------------------------
    if not eh_tubo:
        item["quantidade_ajustada"] = quantidade_original
        item["fator_conversao_quantidade"] = None

        if classe_unidade == "DESCONHECIDA":
            item["tipo_quantidade"] = "ORIGINAL_NAO_TUBO_UNIDADE_DESCONHECIDA"
        else:
            item["tipo_quantidade"] = f"ORIGINAL_NAO_TUBO_{classe_unidade}"

        return item

    # ------------------------------------------------------
    # Tubo em UNIDADE -> já está em barras
    # ------------------------------------------------------
    if classe_unidade == "UNIDADE":
        item["quantidade_ajustada"] = quantidade_original
        item["tipo_quantidade"] = "BARRA_DIRETA_OC_UN"
        item["fator_conversao_quantidade"] = 1
        return item

    # ------------------------------------------------------
    # Tubo em BARRA -> já está em barras
    # ------------------------------------------------------
    if classe_unidade == "BARRA":
        item["quantidade_ajustada"] = quantidade_original
        item["tipo_quantidade"] = "BARRA_DIRETA_OC_BAR"
        item["fator_conversao_quantidade"] = 1
        return item

    # ------------------------------------------------------
    # Tubo em METRO -> converter para barras (CEIL)
    # ------------------------------------------------------
    if classe_unidade == "METRO":
        if comprimento_barra in [None, 0, "", "0"]:
            item["quantidade_ajustada"] = quantidade_original
            item["tipo_quantidade"] = "ERRO_TUBO_SEM_COMPRIMENTO"
            item["fator_conversao_quantidade"] = None
            return item

        try:
            qtd_metros = float(quantidade_original)
            comp_barra = float(comprimento_barra)

            if comp_barra <= 0:
                item["quantidade_ajustada"] = quantidade_original
                item["tipo_quantidade"] = "ERRO_TUBO_COMPRIMENTO_INVALIDO"
                item["fator_conversao_quantidade"] = None
                return item

            qtd_barras_bruta = qtd_metros / comp_barra
            qtd_barras_ceil = math.ceil(qtd_barras_bruta)

            item["quantidade_em_metros_oc"] = qtd_metros
            item["comprimento_barra_usado"] = comp_barra
            item["quantidade_barras_calculada"] = qtd_barras_bruta
            item["quantidade_ajustada"] = qtd_barras_ceil
            item["tipo_quantidade"] = "CONVERTIDO_METRO_PARA_BARRA_CEIL"
            item["fator_conversao_quantidade"] = comp_barra

            return item

        except Exception:
            item["quantidade_ajustada"] = quantidade_original
            item["tipo_quantidade"] = "ERRO_CONVERSAO_QUANTIDADE_TUBO"
            item["fator_conversao_quantidade"] = None
            return item

    # ------------------------------------------------------
    # Tubo em unidade que precisa de atenção (CX, RL, KG, L)
    # -> mantém quantidade mas sinaliza revisão manual
    # ------------------------------------------------------
    if classe_unidade in ("CAIXA", "ROLO", "KG", "LITRO"):
        item["quantidade_ajustada"] = quantidade_original
        item["tipo_quantidade"] = f"TUBO_UNIDADE_{classe_unidade}_REVISAR"
        item["fator_conversao_quantidade"] = None
        return item

    # ------------------------------------------------------
    # Unidade desconhecida -> mantém e sinaliza
    # ------------------------------------------------------
    item["quantidade_ajustada"] = quantidade_original
    item["tipo_quantidade"] = f"UNIDADE_OC_NAO_MAPEADA({unidade_oc})"
    item["fator_conversao_quantidade"] = None
    return item
