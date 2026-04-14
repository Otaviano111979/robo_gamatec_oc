import pandas as pd
from normalizador import enriquecer_descricao


CAMINHO_ARQUIVO = r"C:\robo_gamatec_oc\dados\FONTE DE DADOS KRONA.xlsx"
NOME_ABA = "DADOS DE PRODUTOS"


def carregar_fonte_krona():
    df = pd.read_excel(CAMINHO_ARQUIVO, sheet_name=NOME_ABA)

    colunas_originais = list(df.columns)
    print("Colunas encontradas:", colunas_originais)

    df = df.rename(columns={
        "CODIGO": "codigo_krona",
        "Descrição": "descricao_krona"
    })

    df = df[["codigo_krona", "descricao_krona"]].copy()

    enriquecidos = df["descricao_krona"].apply(enriquecer_descricao).apply(pd.Series)
    df = pd.concat([df, enriquecidos], axis=1)

    return df


if __name__ == "__main__":
    df = carregar_fonte_krona()

    print("\n=== PRIMEIRAS LINHAS ===")
    print(df.head(20).to_string(index=False))

    caminho_saida = r"C:\robo_gamatec_oc\saida\base_krona_enriquecida.csv"
    df.to_csv(caminho_saida, index=False, sep=";", encoding="utf-8-sig")

    print("\nArquivo salvo em:")
    print(caminho_saida)