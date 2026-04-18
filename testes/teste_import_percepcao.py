from percepcao_gamatec import CalibracaoPercepcao, PercepcaoGamatec

cal = CalibracaoPercepcao(
    x_codigo=10,
    y_codigo_primeira_linha=10,
    w_codigo=58,
    h_codigo=28,
    x_desc=70,
    y_desc_primeira_linha=10,
    w_desc=430,
    h_desc=28,
    x_ult=520,
    y_ult_primeira_linha=10,
    w_ult=170,
    h_ult=28,
    x_final=700,
    y_final_primeira_linha=10,
    w_final=170,
    h_final=28,
    passo_linha=30,
    linhas_visiveis=6,
)

percepcao = PercepcaoGamatec(cal)

print("[OK] Módulo percepcao_gamatec importado com sucesso.")
print("[OK] Instância criada com sucesso.")
print(percepcao.cal)