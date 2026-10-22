import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import matcher
from regra_quantidade import ajustar_quantidade_tubo

base = matcher.carregar_base_krona()
linha = base[base["codigo_krona"].astype(str).str.lstrip("0") == "164"].iloc[0]
assert float(linha["comprimento_final_m"]) == 3.0

resultado = ajustar_quantidade_tubo({
    "eh_tubo_krona": True,
    "comprimento_krona_m": linha["comprimento_final_m"],
    "quantidade": 30,
    "unidade_oc": "M",
})
assert resultado["quantidade_ajustada"] == 10
assert resultado["tipo_quantidade"] == "CONVERTIDO_METRO_PARA_BARRA_CEIL"

print("OK: 164 PPR normalizado para 3 m; 30 m = 10 barras")
