# -*- coding: utf-8 -*-
"""
matcher_brasal.py

Match direto por código Brasal → código Krona usando a tabela DE/PARA.
Equivalente ao matcher_mrv.py mas para OCs da Brasal/Closer.
"""


def match_por_codigo_brasal(item: dict, indice_brasal: dict) -> dict | None:
    """
    Tenta fazer match do item pelo código Brasal.
    Retorna dict com resultado do match ou None se não encontrado.

    Args:
        item: dicionário do item extraído da OC
        indice_brasal: dicionário indexado por código Brasal (de base_brasal_loader)
    """
    if not indice_brasal:
        return None

    # o código interno da OC Brasal fica em codigo_interno_oc
    codigo_brasal = str(item.get("codigo_interno_oc") or "").strip()

    if not codigo_brasal:
        return None

    entrada = indice_brasal.get(codigo_brasal)
    if not entrada:
        return None

    codigo_krona = entrada.get("codigo_krona")
    if not codigo_krona:
        return None

    return {
        "match_encontrado":          True,
        "codigo_krona":              codigo_krona,
        "descricao_krona":           entrada.get("descricao"),
        "descricao_krona_normalizada": entrada.get("descricao"),
        "linha_krona_match":         None,
        "familia_krona_match":       None,
        "unidade_venda_krona":       entrada.get("unidade"),
        "quantidade_embalagem_krona": None,
        "score_estrutura":           1.0,
        "score_textual":             1.0,
        "score_total":               1.0,
        "tipo_match":                "BRASAL_DIRETO",
        "revisao_manual":            False,
        "motivo_match":              f"TABELA_BRASAL({codigo_brasal}→{codigo_krona})",
        "categoria_krona":           None,
        "eh_tubo_krona":             None,
        "diametro_krona_mm":         None,
        "comprimento_krona_m":       None,
    }
