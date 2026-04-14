def calcular_quantidade_convertida(unidade_oc, quantidade_oc, unidade_venda, comprimento_barra=None):
    """
    Converte a quantidade da OC para a unidade de venda interna.
    """

    unidade_oc = (unidade_oc or "").strip().lower()
    unidade_venda = (unidade_venda or "").strip().upper()

    resultado = {
        "quantidade_convertida": quantidade_oc,
        "conversao_aplicada": False,
        "observacao": "",
        "revisao_manual": False,
    }

    if unidade_oc in ("un", "pc", "jg", "kg", "l", "rl") and unidade_venda in ("UN", "PC"):
        return resultado

    if unidade_oc in ("m", "mt", "mts") and unidade_venda == "M":
        return resultado

    if unidade_oc in ("m", "mt", "mts") and unidade_venda == "BARRA":
        if not comprimento_barra or comprimento_barra <= 0:
            resultado["revisao_manual"] = True
            resultado["observacao"] = "COMPRIMENTO_BARRA_NAO_INFORMADO"
            return resultado

        qtd = quantidade_oc / comprimento_barra

        if abs(qtd - round(qtd)) < 0.000001:
            resultado["quantidade_convertida"] = round(qtd)
            resultado["conversao_aplicada"] = True
            resultado["observacao"] = f"METRO_PARA_BARRA_{comprimento_barra}M"
            return resultado

        resultado["quantidade_convertida"] = qtd
        resultado["conversao_aplicada"] = True
        resultado["revisao_manual"] = True
        resultado["observacao"] = f"CONVERSAO_FRACIONADA_METRO_PARA_BARRA_{comprimento_barra}M"
        return resultado

    resultado["revisao_manual"] = True
    resultado["observacao"] = f"REGRA_NAO_MAPEADA_OC_{unidade_oc}_INTERNA_{unidade_venda}"
    return resultado