import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import matcher
from normalizador import detectar_categoria, detectar_eh_tubo, normalizar_descricao
from regra_quantidade import ajustar_quantidade_tubo


def classificar(descricao):
    texto = normalizar_descricao(descricao)
    return detectar_categoria(texto), detectar_eh_tubo(texto)


# acessorio antes de TUBO nunca vira tubo
assert classificar("LUVA DE CORRER P/TUBO SOLD.20MM") == ("LUVA", False)
assert classificar("LUVA CORRER P/ TUBO ESGOTO SERIE REFORCADA DN 100") == ("LUVA", False)
assert classificar("CURVA P/TUBO DE DESCIDA DA CX.DE DESCARGA") == ("JOELHO", False)
assert classificar("MULTISIFAO SIMPLES (TUBO EXTENSIVEL) PRETO")[1] is False
assert classificar("TESOURA PARA CORTE DE TUBO PPR")[1] is False

# tubos reais continuam tubos, mesmo com acessorio depois do nome
assert classificar("TUBO PVC SOLD 6M 20MM") == ("TUBO", True)
assert classificar("TUBO P/CX.DESC.LONGO C/CURVA") == ("TUBO", True)
assert classificar("TUBO PPR PN25 110MMX3M") == ("TUBO", True)

# categoria vale pela posicao, nao pela ordem da lista
assert classificar("T1-TAMPA P/VALVULA PIA E LAVAT.")[0] == "TAMPA"

base = matcher.carregar_base_krona()


def linha(codigo):
    encontrados = base[
        base["codigo_krona"].astype(str).str.lstrip("0") == codigo
    ]
    assert not encontrados.empty, f"codigo {codigo} ausente na base"
    return encontrados.iloc[0]


# luvas de correr: peca vendida por PC, nunca tubo
for codigo in ("444", "445", "446", "447", "448", "449",
               "649", "650", "651", "652", "653", "722",
               "1444", "1445", "1446", "1447", "1448"):
    r = linha(codigo)
    assert bool(r["eh_tubo"]) is False, f"{codigo} ainda marcado como tubo"
    assert str(r["categoria_detectada"]).upper() == "LUVA", f"{codigo} categoria errada"

# multisifoes, tesoura e curva para tubo tambem nao sao tubos
for codigo in ("859", "860", "861", "862", "1209", "1210", "1838", "794"):
    assert bool(linha(codigo)["eh_tubo"]) is False, f"{codigo} ainda marcado como tubo"

assert str(linha("794")["categoria_detectada"]).upper() == "JOELHO"

# tubos reais preservados (barra 6 m, PPR 3 m, linha PY, tubo curto de descida)
for codigo in ("138", "164", "1741", "790", "791", "792", "793"):
    assert bool(linha(codigo)["eh_tubo"]) is True, f"{codigo} deixou de ser tubo"

# luva generica/simples nao pode ser resolvida como luva de correr
pool = matcher.filtrar_candidatos_krona(
    base, "LUVA", 100,
    item_descricao="LUVA DE PVC P/ ESGOTO SERIE REFORCADA D=100MM",
    diametros={100})
codigos = set(pool["codigo_krona"].astype(str))
assert "1441" in codigos and "1447" not in codigos

# quando a OC pede correr, so a luva de correr entra
pool = matcher.filtrar_candidatos_krona(
    base, "LUVA", 100,
    item_descricao="LUVA DE CORRER P/TUBO ESGOTO DN100",
    diametros={100})
codigos = set(pool["codigo_krona"].astype(str))
assert "1447" in codigos and "1441" not in codigos


def aplicar(item_oc, codigo):
    r = linha(codigo)
    item = {
        "eh_tubo_krona": bool(r["eh_tubo"]),
        "comprimento_krona_m": r["comprimento_final_m"],
        "unidade_venda_krona": r["unidade_venda"],
    }
    item.update(item_oc)
    return ajustar_quantidade_tubo(item)


# luva em metros: mantem a quantidade, sem conversao e sem revisao
luva = aplicar({"quantidade": 432, "unidade_oc": "M"}, "1447")
assert luva["quantidade_ajustada"] == 432
assert luva["tipo_quantidade"] == "ORIGINAL_NAO_TUBO_METRO"
assert luva.get("revisao_manual") is not True
assert luva.get("revisao_unidade") is not True

# tubo real em metros: converte pela barra do cadastro (6 m)
tubo = aplicar({"quantidade": 432, "unidade_oc": "M"}, "138")
assert tubo["quantidade_ajustada"] == 72
assert tubo["tipo_quantidade"] == "CONVERTIDO_METRO_PARA_BARRA_CEIL"

# cliente que ja mandou em barras continua intacto
tubo_br = aplicar({"quantidade": 432, "unidade_oc": "BR"}, "138")
assert tubo_br["quantidade_ajustada"] == 432
assert tubo_br["tipo_quantidade"] == "BARRA_DIRETA_OC_BAR"

# tubo curto de descida (0,4 m, vendido PC): mantem e revisa se vier em metros
curto = aplicar({"quantidade": 432, "unidade_oc": "M"}, "790")
assert curto["quantidade_ajustada"] == 432
assert curto["tipo_quantidade"] == "TUBO_COMPRIMENTO_NAO_E_BARRA_REVISAR"
assert curto["revisao_manual"] is True

# 1741: comprimento desconhecido na base; mantem e revisa se vier em metros
py = aplicar({"quantidade": 30, "unidade_oc": "M"}, "1741")
assert py["quantidade_ajustada"] == 30
assert py["tipo_quantidade"] == "TUBO_COMPRIMENTO_NAO_E_BARRA_REVISAR"
assert py["revisao_manual"] is True

print("OK: luvas/acessorios nao sao tubos; tubos reais mantem conversao e travas")
