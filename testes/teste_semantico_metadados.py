import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pandas as pd

import matcher
import motor_semantico
from regra_quantidade import ajustar_quantidade_tubo


BASE_TESTE = pd.DataFrame([
    {
        "codigo_krona": 24,
        "descricao_krona": "TUBO PVC SOLDAVEL - 6M - 25MM",
        "linha_krona": "SOLDAVEL",
        "familia_krona": "TUBO",
        "unidade_venda": "BR",
        "quantidade_embalagem": 1,
        "eh_tubo": True,
        "categoria_detectada": "TUBO",
        "comprimento_final_m": 6.0,
        "diametro_final_mm": 25,
    },
    {
        "codigo_krona": 500,
        "descricao_krona": "LUVA PVC SOLDAVEL 25MM",
        "linha_krona": "SOLDAVEL",
        "familia_krona": "LUVA",
        "unidade_venda": "PC",
        "quantidade_embalagem": 1,
        "eh_tubo": False,
        "categoria_detectada": "LUVA",
        "comprimento_final_m": 0.134,
        "diametro_final_mm": 25,
    },
])


class MotorFalso:
    pronto = True

    def __init__(self, resultado):
        self.resultado = resultado

    def match(self, descricao):
        return dict(self.resultado)


def resultado_semantico(codigo, descricao, categoria, diametro):
    return {
        "match_encontrado": True,
        "codigo_krona": codigo,
        "descricao_krona": descricao,
        "score_textual": 0.90,
        "score_total": 0.90,
        "tipo_match": "MATCH_SEMANTICO",
        "revisao_manual": False,
        "motivo_match": "SEMANTICO",
        "categoria_krona": categoria,
        "diametro_krona_mm": diametro,
    }


def tentar(descricao_oc, resultado):
    original = motor_semantico.obter_motor
    motor_semantico.obter_motor = lambda: MotorFalso(resultado)
    try:
        return matcher._tentar_semantico({"descricao_oc": descricao_oc}, BASE_TESTE)
    finally:
        motor_semantico.obter_motor = original


def aplicar(item_oc, resultado):
    return ajustar_quantidade_tubo({**item_oc, **resultado})


# tubo matched so pelo semantico: cadastro fornece tubo/6 m -> 1200 m = 200 barras
tubo_res = tentar(
    "TUBO PVC SOLDAVEL 25MM",
    resultado_semantico(24, "TUBO PVC SOLDAVEL - 6M - 25MM", "TUBO", 25),
)
assert tubo_res and tubo_res.get("via_motor_semantico") is True
assert bool(tubo_res["eh_tubo_krona"]) is True
assert tubo_res["comprimento_krona_m"] == 6.0
assert tubo_res["unidade_venda_krona"] == "BR"
tubo = aplicar({"quantidade": 1200, "unidade_oc": "M"}, tubo_res)
assert tubo["quantidade_ajustada"] == 200
assert tubo["tipo_quantidade"] == "CONVERTIDO_METRO_PARA_BARRA_CEIL"

# OC ja em barras: a coluna unidade manda e nao ha dupla conversao
tubo_br = aplicar({"quantidade": 1200, "unidade_oc": "BR", "unidade": "M"}, tubo_res)
assert tubo_br["quantidade_ajustada"] == 1200
assert tubo_br["tipo_quantidade"] == "BARRA_DIRETA_OC_BAR"

# luva matched pelo semantico: nao e tubo, mantem metros e nunca divide por 0,134 m
# o indice pode trazer categoria antiga (TUBO); o cadastro corrigido manda
luva_res = tentar(
    "LUVA PVC SOLDAVEL 25MM",
    resultado_semantico(500, "LUVA PVC SOLDAVEL 25MM", "TUBO", 25),
)
assert luva_res and bool(luva_res["eh_tubo_krona"]) is False
assert luva_res["categoria_krona"] == "LUVA"
luva = aplicar({"quantidade": 432, "unidade_oc": "M"}, luva_res)
assert luva["quantidade_ajustada"] == 432
assert luva["tipo_quantidade"] == "ORIGINAL_NAO_TUBO_METRO"

# codigo fora do cadastro: sem metadados, mantem quantidade (nunca converte as cegas)
orfa_res = tentar(
    "TUBO PVC SOLDAVEL 25MM",
    resultado_semantico(999999, "TUBO PVC SOLDAVEL - 6M - 25MM", "TUBO", 25),
)
assert orfa_res and "eh_tubo_krona" not in orfa_res
orfa = aplicar({"quantidade": 432, "unidade_oc": "M"}, orfa_res)
assert orfa["quantidade_ajustada"] == 432
assert orfa["tipo_quantidade"] == "ORIGINAL_NAO_TUBO_METRO"

print("OK: semantico enriquece tubo/luva pelo cadastro; M converte, BR mantem, orfao nao converte")
