# -*- coding: utf-8 -*-
from typing import Dict, Any, Optional

from base_mrv_loader import buscar_codigo_mrv


def match_por_codigo_mrv(
    item_oc: Dict[str, Any],
    indice_mrv: Dict[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Realiza match direto via código MRV (codigo_interno_oc).

    Retorna estrutura padronizada de match OU None.
    """

    codigo_oc = (
        item_oc.get("codigo_interno_oc")
        or item_oc.get("codigo_oc")
        or item_oc.get("codigo_cliente")
    )

    if not codigo_oc:
        return None

    registro_mrv = buscar_codigo_mrv(indice_mrv, codigo_oc)

    if not registro_mrv:
        return None

    return {
        "tipo_match": "CODIGO_MRV",
        "codigo_mrv": registro_mrv["codigo_mrv"],
        "codigo_krona": registro_mrv["codigo_krona"],
        "confianca": 1.0,
        "origem": "base_mrv",
        "dados_mrv": registro_mrv
    }