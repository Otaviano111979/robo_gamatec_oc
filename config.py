import os
from dotenv import load_dotenv

# carrega o .env da raiz do projeto
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# diretorio raiz do projeto — lido do .env, com fallback para a propria pasta do arquivo
BASE_DIR = os.environ.get(
    "GAMATEC_BASE_DIR",
    os.path.abspath(os.path.dirname(__file__))
)

PASTA_DADOS = os.path.join(BASE_DIR, "dados")
PASTA_OC = os.path.join(PASTA_DADOS, "oc")
PASTA_SAIDA = os.path.join(BASE_DIR, "saida")

CAMINHO_FONTE_KRONA_PRINCIPAL = os.path.join(
    PASTA_DADOS,
    "DADOS DE PRODUTOS KRONA(1).xlsx"
)

CAMINHO_BASE_KRONA_FINAL = os.path.join(
    PASTA_SAIDA,
    "base_krona_final.csv"
)

# Catálogo PDF fica como auxiliar futuro, fora do pipeline principal
CAMINHO_CATALOGO_PDF = os.path.join(
    PASTA_DADOS,
    "Krona cataologo KRONA - GERAL.pdf"
)

USAR_CATALOGO_PDF_NO_MATCHER = False

CAMINHO_OC_EXEMPLO = os.path.join(
    PASTA_OC,
    "teste.pdf"
)

CAMINHO_RESULTADO_PROCESSADO = os.path.join(
    PASTA_SAIDA,
    "resultado_processado.csv"
)

CAMINHO_RESULTADO_VALIDADO = os.path.join(
    PASTA_SAIDA,
    "resultado_validado.csv"
)

CAMINHO_APROVADOS = os.path.join(
    PASTA_SAIDA,
    "itens_aprovados_automatico.csv"
)

CAMINHO_REVISAO = os.path.join(
    PASTA_SAIDA,
    "itens_revisao_manual.csv"
)
