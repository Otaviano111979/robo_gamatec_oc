from regra_quantidade import ajustar_quantidade_tubo

item = {
    "quantidade": 12,
    "unidade": "M",
    "eh_tubo_krona": True,
    "comprimento_krona_m": 6
}

resultado = ajustar_quantidade_tubo(item)

print(resultado)