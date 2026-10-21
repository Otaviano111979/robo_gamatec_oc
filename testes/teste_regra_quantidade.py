import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from regra_quantidade import ajustar_quantidade_tubo


def tubo(**extra):
    item = {"eh_tubo_krona": True, "comprimento_krona_m": 6}
    item.update(extra)
    return item


# tubo vendido por barra: 12 m / 6 m = 2 barras
resultado = ajustar_quantidade_tubo(tubo(quantidade=12, unidade="M"))
assert resultado["quantidade_ajustada"] == 2
assert resultado["tipo_quantidade"] == "CONVERTIDO_METRO_PARA_BARRA_CEIL"

# luva de correr (peca de 0,134 m) nunca divide metros como se fosse barra
resultado = ajustar_quantidade_tubo(
    tubo(quantidade=432, unidade="M", comprimento_krona_m=0.134))
assert resultado["quantidade_ajustada"] == 432
assert resultado["tipo_quantidade"] == "TUBO_COMPRIMENTO_NAO_E_BARRA_REVISAR"
assert resultado["revisao_unidade"] is True
assert resultado["revisao_manual"] is True

# cliente ja converteu: unidade BR, quantidade ja em barras -> nunca divide
resultado = ajustar_quantidade_tubo(tubo(quantidade=72, unidade="BR"))
assert resultado["quantidade_ajustada"] == 72
assert resultado["tipo_quantidade"] == "BARRA_DIRETA_OC_BAR"
assert resultado["fator_conversao_quantidade"] == 1

# tubo em UN/PC tambem ja esta em barras/pecas -> nunca divide
resultado = ajustar_quantidade_tubo(tubo(quantidade=5, unidade="UN"))
assert resultado["quantidade_ajustada"] == 5
assert resultado["tipo_quantidade"] == "BARRA_DIRETA_OC_UN"

# a coluna consolidada unidade_oc manda, mesmo com unidade antiga divergente
resultado = ajustar_quantidade_tubo(
    tubo(quantidade=72, unidade_oc="BR", unidade="M"))
assert resultado["quantidade_ajustada"] == 72
assert resultado["tipo_quantidade"] == "BARRA_DIRETA_OC_BAR"

resultado = ajustar_quantidade_tubo(
    tubo(quantidade=12, unidade_oc="M", unidade="BR"))
assert resultado["quantidade_ajustada"] == 2
assert resultado["tipo_quantidade"] == "CONVERTIDO_METRO_PARA_BARRA_CEIL"

# unidade_oc ausente/NaN nao pode anular a unidade valida de fallback
resultado = ajustar_quantidade_tubo(
    tubo(quantidade=72, unidade_oc=float("nan"), unidade="BR"))
assert resultado["quantidade_ajustada"] == 72
assert resultado["tipo_quantidade"] == "BARRA_DIRETA_OC_BAR"

# unidade desconhecida -> mantem e vai para revisao, nunca assume M
resultado = ajustar_quantidade_tubo(tubo(quantidade=72, unidade="GALAO"))
assert resultado["quantidade_ajustada"] == 72
assert resultado["tipo_quantidade"] == "UNIDADE_OC_NAO_MAPEADA(GALAO)"
assert resultado["revisao_unidade"] is True
assert resultado["revisao_manual"] is True

# tubo em caixa/rolo/kg/litro -> mantem e vai para revisao
resultado = ajustar_quantidade_tubo(tubo(quantidade=10, unidade="CX"))
assert resultado["quantidade_ajustada"] == 10
assert resultado["tipo_quantidade"] == "TUBO_UNIDADE_CAIXA_REVISAR"
assert resultado["revisao_unidade"] is True
assert resultado["revisao_manual"] is True

# unidade vazia -> revisao, sem conversao
resultado = ajustar_quantidade_tubo(tubo(quantidade=72, unidade=""))
assert resultado["quantidade_ajustada"] == 72
assert resultado["tipo_quantidade"] == "UNIDADE_OC_NAO_MAPEADA()"
assert resultado["revisao_manual"] is True

print("OK: M converte; BR/UN mantem; unidade_oc manda; duvida vai para revisao")
