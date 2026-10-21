import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from regra_quantidade import ajustar_quantidade_tubo

# tubo vendido por barra: 12 m / 6 m = 2 barras
tubo = {
    "quantidade": 12,
    "unidade": "M",
    "eh_tubo_krona": True,
    "comprimento_krona_m": 6,
}
resultado = ajustar_quantidade_tubo(tubo)
assert resultado["quantidade_ajustada"] == 2
assert resultado["tipo_quantidade"] == "CONVERTIDO_METRO_PARA_BARRA_CEIL"

# luva de correr (peca de 0,134 m) nunca divide metros como se fosse barra
luva = {
    "quantidade": 432,
    "unidade": "M",
    "eh_tubo_krona": True,
    "comprimento_krona_m": 0.134,
}
resultado = ajustar_quantidade_tubo(luva)
assert resultado["quantidade_ajustada"] == 432
assert resultado["tipo_quantidade"] == "TUBO_COMPRIMENTO_NAO_E_BARRA_REVISAR"
assert resultado["revisao_unidade"] is True

print("OK: tubo converte por barra; luva mantem metros e vai para revisao")
