from pprint import pprint

from estado_execucao import EstadoExecucao


estado = EstadoExecucao()

estado.definir_planejamento(["929", "331", "360", "424"])

estado.atualizar_contexto_linha(
    pagina=1,
    linha=1,
    codigo_lido="929",
    descricao_lida="LUVA SOLDAVEL 25MM",
    ult_preco_lido=0.31,
    final_lido=0.31642,
    origem_match="CODIGO",
    score_confianca=1.0,
    item_esperado="929",
    item_resolvido="929",
    status="OK",
    observacao="Leitura coerente",
)

estado.registrar_item_processado("929")

estado.atualizar_contexto_linha(
    pagina=1,
    linha=2,
    codigo_lido="331",
    descricao_lida="TE 25MM",
    ult_preco_lido=0.42,
    final_lido=0.42880,
    origem_match="CODIGO",
    score_confianca=1.0,
    item_esperado="331",
    item_resolvido="331",
    status="OK",
    observacao="Leitura coerente",
)

estado.registrar_item_processado("331")
estado.registrar_scroll(funcionou=True, assinatura_antes="929", assinatura_depois="360")

print("\n[RESUMO]")
pprint(estado.resumo())

print("\n[TODOS OS DADOS]")
pprint(estado.to_dict())