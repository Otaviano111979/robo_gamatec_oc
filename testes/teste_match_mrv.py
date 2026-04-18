from base_mrv_loader import carregar_base_mrv
from matcher_mrv import match_por_codigo_mrv

# carregar base
indice = carregar_base_mrv(r"C:\robo_gamatec_oc\dados\base_mrv.csv")

# simular item da OC
item_oc = {
    "idx_item": 1,
    "codigo_interno_oc": "1101047",
    "descricao": "qualquer coisa",
    "quantidade": 10
}

resultado = match_por_codigo_mrv(item_oc, indice)

print("\nRESULTADO DO MATCH:")
print(resultado)