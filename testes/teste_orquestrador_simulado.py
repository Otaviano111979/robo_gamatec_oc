from pprint import pprint

from agente_gamatec import AgenteGamatec
from orquestrador_agente_gamatec import OrquestradorAgenteGamatec


class PercepcaoSimulada:
    def __init__(self):
        self.indice_pagina = 0

        self.paginas = [
            [
                {
                    "linha": 1,
                    "codigo_digitos": "929",
                    "descricao_lida": "CORPO CAIXA SIFONADA NR.31 150 X 150 X 50",
                    "ult_valor": 25.02,
                    "final_valor": 25.30,
                },
                {
                    "linha": 2,
                    "codigo_digitos": "331",
                    "descricao_lida": "ADAPTADOR SOLD CURTO 25MM X 3/4",
                    "ult_valor": 0.45,
                    "final_valor": 0.46,
                },
                {
                    "linha": 3,
                    "codigo_digitos": "9999",
                    "descricao_lida": "ITEM FORA DO PLANO",
                    "ult_valor": 9.99,
                    "final_valor": 10.50,
                },
            ],
            [
                {
                    "linha": 1,
                    "codigo_digitos": "360",
                    "descricao_lida": "BUCHA RED.SOLD.CURTA 25 X 20MM",
                    "ult_valor": 0.31,
                    "final_valor": 0.32,
                },
                {
                    "linha": 2,
                    "codigo_digitos": "424",
                    "descricao_lida": "JOELHO 90 SOLD - 20MM",
                    "ult_valor": 0.32,
                    "final_valor": 0.33,
                },
                {
                    "linha": 3,
                    "codigo_digitos": "331",
                    "descricao_lida": "ADAPTADOR SOLD CURTO 25MM X 3/4",
                    "ult_valor": 0.45,
                    "final_valor": 0.46,
                },
            ],
            [
                {
                    "linha": 1,
                    "codigo_digitos": "360",
                    "descricao_lida": "BUCHA RED.SOLD.CURTA 25 X 20MM",
                    "ult_valor": 0.31,
                    "final_valor": 0.32,
                },
                {
                    "linha": 2,
                    "codigo_digitos": "424",
                    "descricao_lida": "JOELHO 90 SOLD - 20MM",
                    "ult_valor": 0.32,
                    "final_valor": 0.33,
                },
            ],
            [
                {
                    "linha": 1,
                    "codigo_digitos": "360",
                    "descricao_lida": "BUCHA RED.SOLD.CURTA 25 X 20MM",
                    "ult_valor": 0.31,
                    "final_valor": 0.32,
                },
                {
                    "linha": 2,
                    "codigo_digitos": "424",
                    "descricao_lida": "JOELHO 90 SOLD - 20MM",
                    "ult_valor": 0.32,
                    "final_valor": 0.33,
                },
            ],
        ]

    def ler_pagina_visivel(self):
        return self.paginas[self.indice_pagina]

    def rolar_para_proxima_pagina(self):
        assinatura_antes = self._assinatura_da_pagina(self.indice_pagina)

        if self.indice_pagina < len(self.paginas) - 1:
            self.indice_pagina += 1

        assinatura_depois = self._assinatura_da_pagina(self.indice_pagina)

        return {
            "scroll_ok": assinatura_antes != assinatura_depois,
            "assinatura_antes": assinatura_antes,
            "assinatura_depois": assinatura_depois,
            "metodo": "SIMULADO",
        }

    def _assinatura_da_pagina(self, indice):
        pagina = self.paginas[indice]
        if not pagina:
            return ""
        primeira = pagina[0]
        return f"{primeira.get('codigo_digitos', '')}|{primeira.get('descricao_lida', '')}"


plano = [
    {"codigo_krona": "929", "descricao": "CORPO CAIXA SIFONADA NR.31 150 X 150 X 50", "preco_alvo": 25.02},
    {"codigo_krona": "331", "descricao": "ADAPTADOR SOLD CURTO 25MM X 3/4", "preco_alvo": 0.45},
    {"codigo_krona": "360", "descricao": "BUCHA RED.SOLD.CURTA 25 X 20MM", "preco_alvo": 0.31},
    {"codigo_krona": "424", "descricao": "JOELHO 90 SOLD - 20MM", "preco_alvo": 0.32},
]

agente = AgenteGamatec()
agente.carregar_plano(plano)

percepcao = PercepcaoSimulada()

orquestrador = OrquestradorAgenteGamatec(
    agente=agente,
    percepcao=percepcao,
)

orquestrador.executar_varredura(max_paginas=10)

print("\n[RESUMO FINAL]")
pprint(orquestrador.resumo())

print("\n[DUMP FINAL]")
pprint(orquestrador.dump())