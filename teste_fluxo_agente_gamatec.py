from pprint import pprint

from agente_gamatec import AgenteGamatec
from planejador_execucao_gamatec import localizar_arquivo_planejamento, carregar_plano_execucao


print("=== TESTE FLUXO DO AGENTE GAMATEC ===")

caminho = localizar_arquivo_planejamento()
print("\n[ARQUIVO DE PLANEJAMENTO]")
print(caminho)

plano = carregar_plano_execucao(caminho)

print("\n[TOTAL DE ITENS NO PLANO]")
print(len(plano))

print("\n[PRIMEIROS 10 ITENS DO PLANO]")
for item in plano[:10]:
    pprint(item)

agente = AgenteGamatec()

print("\n[TESTE DE NORMALIZAÇÃO DOS PRIMEIROS 10 ITENS]")
for item in plano[:10]:
    codigo_original = item.get("codigo_krona")
    codigo_normalizado = agente._codigo_planejado_normalizado(item)
    print(
        f"codigo_krona={codigo_original} | "
        f"codigo_normalizado={codigo_normalizado} | "
        f"preco_alvo={item.get('preco_alvo')} | "
        f"desconto_calculado={item.get('desconto_calculado')}"
    )

print("\n[VALIDAÇÃO BÁSICA DO PLANO]")
qtd_com_preco = sum(1 for item in plano if item.get("preco_alvo") is not None)
qtd_com_desconto = sum(1 for item in plano if item.get("desconto_calculado") is not None)
qtd_com_codigo = sum(1 for item in plano if item.get("codigo_krona"))

print({
    "total_itens": len(plano),
    "com_codigo": qtd_com_codigo,
    "com_preco_alvo": qtd_com_preco,
    "com_desconto_calculado": qtd_com_desconto,
})

print("\n[OK] Fluxo básico do plano validado com a API nova do agente.")