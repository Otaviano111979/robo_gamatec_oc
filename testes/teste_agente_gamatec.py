from pprint import pprint

from agente_gamatec import AgenteGamatec


agente = AgenteGamatec()

plano = [
    {"codigo_krona": "929", "descricao": "LUVA SOLDAVEL 25MM", "preco_alvo": 0.31},
    {"codigo_krona": "331", "descricao": "TE 25MM", "preco_alvo": 0.42},
    {"codigo_krona": "360", "descricao": "BUCHA RED 25X20", "preco_alvo": 0.31},
    {"codigo_krona": "424", "descricao": "JOELHO 20MM", "preco_alvo": 0.32},
]

agente.carregar_plano(plano)

leituras_pagina_1 = [
    {
        "linha": 1,
        "codigo_digitos": "929",
        "descricao_lida": "LUVA SOLDAVEL 25MM",
        "ult_valor": 0.31,
        "final_valor": 0.31642,
    },
    {
        "linha": 2,
        "codigo_digitos": "331",
        "descricao_lida": "TE 25MM",
        "ult_valor": 0.42,
        "final_valor": 0.42880,
    },
    {
        "linha": 3,
        "codigo_digitos": "9999",
        "descricao_lida": "ITEM ESTRANHO",
        "ult_valor": 9.99,
        "final_valor": 10.50,
    },
]

decisoes = agente.analisar_pagina(pagina=1, leituras_pagina=leituras_pagina_1)

print("\n[DECISÕES DA PÁGINA 1]")
pprint(decisoes)

agente.marcar_item_processado("929")
agente.marcar_item_processado("331")
agente.registrar_scroll_resultado(True, assinatura_antes="929|LUVA", assinatura_depois="360|BUCHA")

print("\n[RESUMO DO AGENTE]")
pprint(agente.resumo())

print("\n[DUMP COMPLETO]")
pprint(agente.dump_completo())