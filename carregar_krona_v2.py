import os
import pandas as pd

from normalizador import enriquecer_descricao
from config import CAMINHO_FONTE_KRONA_PRINCIPAL, CAMINHO_BASE_KRONA_FINAL


CAMINHO_ARQUIVO = CAMINHO_FONTE_KRONA_PRINCIPAL
ABA_INFO = "informações de produtos"
ABA_MATRIZ = "DADOS MATRIZ"
CAMINHO_SAIDA = CAMINHO_BASE_KRONA_FINAL


def limpar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def carregar_aba_info(caminho_arquivo: str) -> pd.DataFrame:
    df = pd.read_excel(
        caminho_arquivo,
        sheet_name=ABA_INFO,
        header=1
    )

    df = limpar_colunas(df)
    df = df.loc[:, ~df.columns.str.contains(r"^Unnamed", case=False, regex=True)].copy()

    colunas_esperadas = [
        "Produto",
        "Descrição",
        "Linha",
        "Função",
        "Aplicação",
        "Características técnicas",
        "Normas de referência",
        "Benefícios",
    ]

    faltando = [c for c in colunas_esperadas if c not in df.columns]
    if faltando:
        print("\nColunas encontradas na aba informações de produtos:")
        print(list(df.columns))
        raise ValueError(f"Aba '{ABA_INFO}' sem colunas esperadas: {faltando}")

    df = df.rename(columns={
        "Produto": "codigo_krona",
        "Descrição": "descricao_krona",
        "Linha": "linha_krona",
        "Função": "funcao_krona",
        "Aplicação": "aplicacao_krona",
        "Características técnicas": "caracteristicas_tecnicas",
        "Normas de referência": "normas_referencia",
        "Benefícios": "beneficios",
    })

    df = df[[
        "codigo_krona",
        "descricao_krona",
        "linha_krona",
        "funcao_krona",
        "aplicacao_krona",
        "caracteristicas_tecnicas",
        "normas_referencia",
        "beneficios",
    ]].copy()

    return df


def carregar_aba_matriz(caminho_arquivo: str) -> pd.DataFrame:
    df = pd.read_excel(
        caminho_arquivo,
        sheet_name=ABA_MATRIZ,
        header=2
    )

    df = limpar_colunas(df)
    df = df.loc[:, ~df.columns.str.contains(r"^Unnamed", case=False, regex=True)].copy()

    colunas_esperadas = [
        "Produto",
        "Descrição",
        "Linha",
        "Família",
        "Unidade",
        "Tipo Embalagem",
        "Comprimento",
        "Altura",
        "Largura",
        "Código de Barras",
        "Quantidade Embalagem",
        "Pos.IPI/NCM",
    ]

    faltando = [c for c in colunas_esperadas if c not in df.columns]
    if faltando:
        print("\nColunas encontradas na aba DADOS MATRIZ:")
        print(list(df.columns))
        raise ValueError(f"Aba '{ABA_MATRIZ}' sem colunas esperadas: {faltando}")

    col_barras = [c for c in df.columns if str(c).startswith("Código de Barras")]

    coluna_barras_produto = col_barras[0] if len(col_barras) >= 1 else None
    coluna_barras_emb = col_barras[1] if len(col_barras) >= 2 else None
    coluna_barras_reemb = col_barras[2] if len(col_barras) >= 3 else None

    rename_map = {
        "Produto": "codigo_krona",
        "Descrição": "descricao_matriz",
        "Linha": "linha_matriz",
        "Família": "familia_krona",
        "Unidade": "unidade_venda",
        "Tipo Embalagem": "tipo_embalagem",
        "Comprimento": "comprimento_matriz",
        "Altura": "altura_matriz",
        "Largura": "largura_matriz",
        "Quantidade Embalagem": "quantidade_embalagem",
        "Pos.IPI/NCM": "ncm_krona",
    }

    if coluna_barras_produto:
        rename_map[coluna_barras_produto] = "codigo_barras_produto"
    if coluna_barras_emb:
        rename_map[coluna_barras_emb] = "codigo_barras_embalagem"
    if coluna_barras_reemb:
        rename_map[coluna_barras_reemb] = "codigo_barras_reembalagem"

    df = df.rename(columns=rename_map)

    colunas_desejadas = [
        "codigo_krona",
        "descricao_matriz",
        "linha_matriz",
        "familia_krona",
        "unidade_venda",
        "tipo_embalagem",
        "comprimento_matriz",
        "altura_matriz",
        "largura_matriz",
        "quantidade_embalagem",
        "ncm_krona",
        "codigo_barras_produto",
        "codigo_barras_embalagem",
        "codigo_barras_reembalagem",
    ]

    colunas_presentes = [c for c in colunas_desejadas if c in df.columns]
    df = df[colunas_presentes].copy()

    return df


def padronizar_campos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "codigo_krona" in df.columns:
        df["codigo_krona"] = df["codigo_krona"].astype(str).str.strip()
        df["codigo_krona"] = df["codigo_krona"].str.replace(r"\.0$", "", regex=True)
        df = df[df["codigo_krona"] != ""].copy()

    colunas_texto = [
        "descricao_krona",
        "linha_krona",
        "funcao_krona",
        "aplicacao_krona",
        "caracteristicas_tecnicas",
        "normas_referencia",
        "beneficios",
        "descricao_matriz",
        "linha_matriz",
        "familia_krona",
        "unidade_venda",
        "tipo_embalagem",
        "ncm_krona",
        "codigo_barras_produto",
        "codigo_barras_embalagem",
        "codigo_barras_reembalagem",
    ]

    for col in colunas_texto:
        if col in df.columns:
            df[col] = df[col].where(pd.notna(df[col]), None)
            df[col] = df[col].apply(lambda x: str(x).strip() if x is not None else None)

    colunas_numericas = [
        "comprimento_matriz",
        "altura_matriz",
        "largura_matriz",
        "quantidade_embalagem",
    ]

    for col in colunas_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def consolidar_bases(df_info: pd.DataFrame, df_matriz: pd.DataFrame) -> pd.DataFrame:
    df_info = padronizar_campos(df_info)
    df_matriz = padronizar_campos(df_matriz)

    df_info = df_info.drop_duplicates(subset=["codigo_krona"]).copy()
    df_matriz = df_matriz.drop_duplicates(subset=["codigo_krona"]).copy()

    df = pd.merge(
        df_info,
        df_matriz,
        on="codigo_krona",
        how="outer"
    )

    if "descricao_matriz" in df.columns:
        df["descricao_krona"] = df["descricao_krona"].combine_first(df["descricao_matriz"])

    if "linha_matriz" in df.columns:
        df["linha_krona"] = df["linha_krona"].combine_first(df["linha_matriz"])

    df = df[df["descricao_krona"].notna()].copy()
    df = df[df["descricao_krona"].astype(str).str.strip() != ""].copy()

    enriquecidos = df["descricao_krona"].apply(enriquecer_descricao).apply(pd.Series)
    df = pd.concat([df.reset_index(drop=True), enriquecidos.reset_index(drop=True)], axis=1)

    if "comprimento_matriz" in df.columns:
        df["comprimento_matriz_m"] = df["comprimento_matriz"] / 1000.0

    if "comprimento_matriz_m" in df.columns:
        df["comprimento_final_m"] = df["comprimento_detectado_m"].combine_first(df["comprimento_matriz_m"])
    else:
        df["comprimento_final_m"] = df["comprimento_detectado_m"]

    df["diametro_final_mm"] = df["diametro_mm"]

    return df


def carregar_krona_v2() -> pd.DataFrame:
    if not os.path.exists(CAMINHO_ARQUIVO):
        raise FileNotFoundError(f"Arquivo não encontrado: {CAMINHO_ARQUIVO}")

    df_info = carregar_aba_info(CAMINHO_ARQUIVO)
    df_matriz = carregar_aba_matriz(CAMINHO_ARQUIVO)

    df_final = consolidar_bases(df_info, df_matriz)
    return df_final


if __name__ == "__main__":
    df = carregar_krona_v2()

    print("\n=== RESUMO BASE KRONA V2 ===")
    print(f"Total de registros: {len(df)}")

    print("\n=== COLUNAS FINAIS ===")
    print(list(df.columns))

    print("\n=== PRIMEIRAS LINHAS ===")
    print(df.head(20).to_string(index=False))

    os.makedirs(os.path.dirname(CAMINHO_SAIDA), exist_ok=True)
    df.to_csv(CAMINHO_SAIDA, index=False, sep=";", encoding="utf-8-sig")

    print("\nArquivo salvo em:")
    print(CAMINHO_SAIDA)