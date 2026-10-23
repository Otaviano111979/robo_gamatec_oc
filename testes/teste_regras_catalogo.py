import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pandas as pd

import matcher
from regra_quantidade import ajustar_quantidade_tubo


def _produto(codigo, descricao, categoria="", linha=None, familia=None,
             unidade="PC", comprimento=0.03):
    return {
        "codigo_krona": codigo,
        "descricao_krona": descricao,
        "descricao_normalizada": descricao,
        "categoria_detectada": categoria,
        "linha_krona": linha,
        "familia_krona": familia,
        "unidade_venda": unidade,
        "quantidade_embalagem": 1,
        "eh_tubo": False,
        "comprimento_final_m": comprimento,
        "diametro_final_mm": None,
    }


BASE_TESTE = pd.DataFrame([
    _produto("293", "PLUG ROSCAVEL 1/2", linha="ROSCAVEL", familia="PLUG"),
    _produto("294", "PLUG ROSCAVEL 3/4", linha="ROSCAVEL", familia="PLUG"),
    _produto("295", "PLUG ROSCAVEL 1", linha="ROSCAVEL", familia="PLUG"),
    _produto("296", "PLUG ROSCAVEL 1.1/2", linha="ROSCAVEL", familia="PLUG"),
    _produto("297", "PLUG ROSCAVEL 1.1/4", linha="ROSCAVEL", familia="PLUG"),
    _produto("298", "PLUG ROSCAVEL 2", linha="ROSCAVEL", familia="PLUG"),
    _produto("520", "SOLUCAO PREPARADORA 200 ML", comprimento=0.05),
    _produto("521", "SOLUCAO PREPARADORA 1000 ML", comprimento=0.098),
    _produto("675", "PASTA LUBRIFICANTE 160 G", categoria="PASTA LUBRIFICANTE", comprimento=0.1),
    _produto("676", "PASTA LUBRIFICANTE 400 G", categoria="PASTA LUBRIFICANTE", comprimento=0.14),
    _produto("677", "PASTA LUBRIFICANTE 1 KG", categoria="PASTA LUBRIFICANTE", comprimento=0.17),
    _produto("516", "ADESIVO PLASTICO 17G.", categoria="ADESIVOS E COMPLEMENTOS"),
    _produto("517", "ADESIVO PLASTICO 75G.", categoria="ADESIVOS E COMPLEMENTOS"),
    _produto("518", "ADESIVO PLASTICO 175G C/ PINCEL", categoria="ADESIVOS E COMPLEMENTOS"),
    _produto("519", "ADESIVO FRASCO 850 G", categoria="ADESIVOS E COMPLEMENTOS"),
    _produto("522", "ADESIVO PLÁSTICO EXTRAFORTE PARA PVC 175g C/ PINCEL APLICADOR",
             categoria="ADESIVOS E COMPLEMENTOS"),
    _produto("523", "ADESIVO PLÁSTICO EXTRAFORTE PARA PVC 850g",
             categoria="ADESIVOS E COMPLEMENTOS"),
    _produto("1389", "ADESIVO PLASTICO ULTRATERM - FRASCO 850G",
             categoria="ADESIVOS E COMPLEMENTOS"),
    _produto("1274", "QUADRO DISTR 24D/18N EMBUTIR SEM BARRAMENTO", familia="QUADRO"),
    _produto("1275", "QUADRO DISTR 36D/27N EMBUTIR SEM BARRAMENTO", familia="QUADRO"),
    _produto("1280", "QUADRO DISTR 24D/18N EMBUTIR COM BARRAMENTO", familia="QUADRO"),
    _produto("1281", "QUADRO DISTR 36D/27N EMBUTIR COM BARRAMENTO", familia="QUADRO"),
    _produto("1288", "QUADRO DISTR 36D/27N SEM BARRAMENTO", familia="QUADRO"),
    _produto("1294", "QUADRO DISTR 36D/27N COM BARRAMENTO", familia="QUADRO"),
])


def regra(descricao):
    return matcher._regra_catalogo({"descricao_oc": descricao}, BASE_TESTE)


def match(descricao, quantidade=1, unidade="UN"):
    item = {
        "descricao_oc": descricao,
        "descricao_reconstruida": descricao,
        "quantidade": quantidade,
        "quantidade_oc": quantidade,
        "unidade_oc": unidade,
    }
    return item, matcher.match_item_oc(item, BASE_TESTE, {}, {})


def codigo(descricao):
    resultado = regra(descricao)
    return resultado.get("codigo_krona") if resultado else None


# PLUG PVC soldavel = PLUG ROSCAVEL; a bitola manda no codigo.
assert codigo("PLUG PVC SOLDAVEL 3/4` - NBR 5648") == "294"
assert codigo("PLUG ROSCAVEL 1.1/2") == "296"
assert codigo("PLUG PVC SOLDAVEL 1 1/2") == "296"
assert codigo("PLUG PVC SOLDAVEL 1.1/4") == "297"
assert codigo("PLUG PVC SOLDAVEL 1/2") == "293"
assert codigo("PLUG PVC SOLDAVEL 2") == "298"

# sem bitola ou bitola fora da tabela: revisao, nunca tubo
assert regra("PLUG PVC SOLDAVEL")["_regra_bloqueia"] is True
assert regra("PLUG PVC SOLDAVEL 3")["_regra_bloqueia"] is True

# PPR segue o caminho normal (1772/1773 existem no catalogo real)
assert regra("PLUG PPR 3/4") is None

# SOLUCAO LIMPADORA: 200 ml e 1000 ml; sem tamanho = 1000 ml
assert codigo("SOLUÇÃO LIMPADORA") == "521"
assert codigo("SOLUCAO LIMPADORA 1000 ML") == "521"
assert codigo("SOLUÇÃO LIMPADORA 1 L") == "521"
assert codigo("SOLUÇÃO LIMPADORA 200 ML") == "520"
assert regra("SOLUÇÃO LIMPADORA 500 ML")["_regra_bloqueia"] is True

# PASTA LUBRIFICANTE: sem tamanho = 1 kg; 160/400 g explicitos
assert codigo("PASTA LUBRIFICANTE 1KG") == "677"
assert codigo("PASTA LUBRIFICANTE") == "677"
assert codigo("PASTA LUBRIFICANTE 1000 G") == "677"
assert codigo("PASTA LUBRIFICANTE 160G") == "675"
assert codigo("PASTA LUBRIFICANTE 400 G") == "676"
assert regra("PASTA LUBRIFICANTE 500 G")["_regra_bloqueia"] is True

# tubo normal nao entra nas regras
assert regra("TUBO PVC SOLDAVEL 25MM") is None

# ADESIVO PVC: sem qualificador -> 519 (850 g); extraforte 850 -> 523; extraforte 175 c/ pincel -> 522
assert codigo("ADESIVO PVC 850GR") == "519"
assert codigo("ADESIVO PLASTICO PARA PVC 850G") == "519"
assert codigo("ADESIVO PVC") == "519"
assert codigo("ADESIVO EXTRAFORTE PVC 850GR") == "523"
assert codigo("ADESIVO PVC EXTRA FORTE 850 G") == "523"
assert codigo("ADESIVO EXTRAFORTE PVC 175G C/ PINCEL") == "522"

# combinacoes que nao existem no catalogo vao a revisao, sem fallback
assert regra("ADESIVO EXTRAFORTE PVC 175G")["_regra_bloqueia"] is True
assert regra("ADESIVO EXTRAFORTE PVC 850G C/ PINCEL")["_regra_bloqueia"] is True
assert regra("ADESIVO PVC 850G C/ PINCEL")["_regra_bloqueia"] is True

# 17/75/175 g padrao seguem o caminho normal
assert regra("ADESIVO PVC 17G") is None
assert regra("ADESIVO PVC 75G") is None
assert regra("ADESIVO PVC 175G C/ PINCEL") is None

# CPVC / ULTRATERM sao outra linha de produto (adesivo para agua quente)
assert regra("ADESIVO PLASTICO PARA LINHA CPVC FRASCO 850G") is None
assert regra("ADESIVO PLASTICO ULTRATERM FRASCO 850G") is None

# QUADRO: a OC quase nunca descreve igual ao catalogo; 36 DIN -> 1288, sempre em revisao
q = regra("QUADRO DE DISTRIBUIÇÃO PVC 36 DIN C/ BARRAMENTO N/T EMBUTIR 27/36 DISJ - KRONA")
assert q["codigo_krona"] == "1288"
assert q["tipo_match"] == "MATCH_REGRA_CATALOGO_REVISAR"
assert q["revisao_manual"] is True
assert "1275" in q["candidatos_revisao"]
assert "1281" in q["candidatos_revisao"]
assert "1294" in q["candidatos_revisao"]
assert regra("QUADRO DE DISTRIBUIÇÃO PVC 36 DIN SEM BARRAMENTO")["codigo_krona"] == "1288"
assert regra("QUADRO DE DISTRIBUIÇÃO PVC 24 DIN") is None

# integracao: codigo, metadados e quantidade intacta
item, res = match("PLUG PVC SOLDAVEL 3/4` - NBR 5648", 200)
assert res["codigo_krona"] == "294"
assert res["tipo_match"] == "MATCH_REGRA_CATALOGO"
assert res["revisao_manual"] is False
assert res["eh_tubo_krona"] is False
assert res["unidade_venda_krona"] == "PC"
final = ajustar_quantidade_tubo({**item, **res})
assert final["quantidade_ajustada"] == 200
assert final["tipo_quantidade"] == "ORIGINAL_NAO_TUBO_UNIDADE"

item, res = match("PASTA LUBRIFICANTE 1KG", 5)
assert res["codigo_krona"] == "677"
assert res["revisao_manual"] is False
assert ajustar_quantidade_tubo({**item, **res})["quantidade_ajustada"] == 5

item, res = match("SOLUÇÃO LIMPADORA", 5)
assert res["codigo_krona"] == "521"
assert res["revisao_manual"] is False
assert ajustar_quantidade_tubo({**item, **res})["quantidade_ajustada"] == 5

item, res = match("ADESIVO PVC 850GR", 5)
assert res["codigo_krona"] == "519"
assert res["tipo_match"] == "MATCH_REGRA_CATALOGO"
assert res["motivo_match"] == "REGRA_CATALOGO_ADESIVO_850"
assert res["revisao_manual"] is False
assert res["unidade_venda_krona"] == "PC"
assert ajustar_quantidade_tubo({**item, **res})["quantidade_ajustada"] == 5

# tamanho nao cadastrado nao cai em fallback: SEM_MATCH para revisao
_, res = match("PASTA LUBRIFICANTE 500 G", 5)
assert res["match_encontrado"] is False
assert res["revisao_manual"] is True
assert res["motivo_match"] == "REGRA_PASTA_TAMANHO_NAO_CADASTRADO"

# integracao QUADRO: 36 DIN sugere 1288, sempre em revisao, quantidade intacta
item, res = match(
    "QUADRO DE DISTRIBUIÇÃO PVC 36 DIN C/ BARRAMENTO N/T EMBUTIR 27/36 DISJ - KRONA", 2)
assert res["codigo_krona"] == "1288"
assert res["categoria_krona"] == "QUADRO"
assert res["categoria_oc"] == "QUADRO"
assert res["quadro_tamanho_oc"] == 36
assert res["tipo_match"] == "MATCH_REGRA_CATALOGO_REVISAR"
assert res["revisao_manual"] is True
assert "1275" in res["candidatos_revisao"]
assert "1281" in res["candidatos_revisao"]
assert "1294" in res["candidatos_revisao"]
assert ajustar_quantidade_tubo({**item, **res})["quantidade_ajustada"] == 2

print("OK: regras de catalogo PLUG/PASTA/SOLUCAO/ADESIVO/QUADRO")
