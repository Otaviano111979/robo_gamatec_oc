from pprint import pprint

from planejador_execucao_gamatec import localizar_arquivo_planejamento, carregar_plano_execucao


caminho = localizar_arquivo_planejamento()
print(f"[ARQUIVO] {caminho}")

plano = carregar_plano_execucao(caminho)

print(f"[TOTAL ITENS] {len(plano)}")
print("\n[PRIMEIROS 10 ITENS]")
for item in plano[:10]:
    pprint(item)