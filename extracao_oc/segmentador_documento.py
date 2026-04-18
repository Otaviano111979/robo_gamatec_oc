import re
from typing import List

from extracao_oc.modelos import LinhaDocumento


# ================================================================
# FORMATO MRV
# Exemplo:
#   10 1101027 4016.99.90 1300 UN 0,00 0,00 0,58 754,00
#   (idx) (codigo) (NCM) (qtd) (un) (frete) (ipi) (unit) (total)
# ================================================================
PADRAO_INICIO_ITEM_MRV = re.compile(
    r"^\d{1,6}\s+\d+\s+\d{4}\.\d{2}\.\d{2}\s+\d[\d.,]*\s+[A-Z]{1,5}\s+[\d.,]+\s+[\d.,%]+\s+[\d.,]+\s+[\d.,]+$",
    re.IGNORECASE
)

# ================================================================
# FORMATO KRONA / L2M
# Exemplo:
#   1795 - Joelho 45° Soldável de PVC Para 160,0000 un 0,7990 0,00 0,00 0,00 0,00 127,84 01/06/2026
#   (codigo) - (descricao...) (qtd) (un) (precos...) (data)
# ================================================================
PADRAO_INICIO_ITEM_KRONA = re.compile(
    r"^\d{2,6}\s+-\s+\S.+?\s+\d[\d.,]*\s+[a-z]{1,5}\d?\s+[\d.,]+\s+[\d.,]+.*\d{2}/\d{2}/\d{4}$",
    re.IGNORECASE
)

# Cabeçalho da tabela de itens no formato Krona
PADRAO_CABECALHO_KRONA = re.compile(
    r"insumo\s+quantidade\s+unid",
    re.IGNORECASE
)

# Linha de continuação do formato Krona (texto descritivo solto, sem números de item)
# Ex: "Água Fria Predial (diâmetro da seção: 25,00"
PADRAO_CONTINUACAO_KRONA = re.compile(
    r"^\s*[a-záéíóúâêôàãõüçA-Z\(\)°\"/,.\s0-9-]+$"
)

# Lixo de codificação do pdfplumber em PDFs Krona
PADRAO_LIXO_CID = re.compile(r"\(cid:\d+\)")

# ================================================================
# FORMATO UAU (GPL / outros clientes)
# Gerado pelo sistema UAU! Software de Automação e Gestão Empresarial
# Ex: "1 FITA VEDA ROSCA 18X50MT RL 20,000000 5,082000 101,64"
# ================================================================
_UN = r"(?:RL|UN|UND|M\b|MT|BR|BAR|PC|PCS|CX|KG|L\b|LT)"

PADRAO_INICIO_ITEM_UAU = re.compile(
    r"^\d{1,4}\s+\S.+?\s+" + _UN + r"\s+[\d.,]+\s+[\d.,]+\s+[\d.,]+$",
    re.IGNORECASE
)

PADRAO_INICIO_ITEM_UAU_QUEBRADO = re.compile(
    r"^\d{1,4}\s+\S.+?\s+" + _UN + r"\s+[\d.,]+$",
    re.IGNORECASE
)

PADRAO_CABECALHO_UAU = re.compile(
    r"item\s+descri",
    re.IGNORECASE
)

PADRAO_RODAPE_UAU = re.compile(
    r"total\s+ipi|total\s+icms|total\s+itens|total\s+geral|total\s+l[ií]quido|aprova|uau!\s+software",
    re.IGNORECASE
)

PADRAO_CONTINUACAO_UAU = re.compile(r"^\d{1,4}$")

# Item quebrado entre paginas — ex: "24 ITEM 24 SEM DESCRICAO - REVISAR MANUALMENTE Un.UN 14,000 ..."
PADRAO_ITEM_QUEBRADO_PAGINA_UAU = re.compile(
    r"^\d{1,4}\s+ITEM\s+\d+\s+SEM\s+DESCRICAO",
    re.IGNORECASE
)

# ================================================================
# FORMATO BRASAL/CLOSER
# Ex: "8926 TUBO PVC ESGOTO SERIE R DN100MM M 66,000 14,55000 960,30"
# Código sem ponto (já limpo), descrição, unidade, qtd, preço, total
# ================================================================
PADRAO_INICIO_ITEM_BRASAL = re.compile(
    r"^\d{4,5}\s+\S.+?\s+(?:RL|UN|UND|M|MT|BR|BAR|PC|PCS|CX|KG|LT?)\s+[\d.,]+\s+[\d.,]+\s+[\d.,]+$",
    re.IGNORECASE
)

PADRAO_CABECALHO_BRASAL = re.compile(
    r"c[oó]digo\s+quantidade\s+unidade",
    re.IGNORECASE
)

PADRAO_RODAPE_BRASAL = re.compile(
    r"base\s+calc|valor\s+do\s+frete|total\s+bruto|total\s+pedido|prazo\s+limite|cond\.\s+pagto|observa|condi[cç][oõ]es\s+gerais|autorizo\s+conforme",
    re.IGNORECASE
)

PADRAO_DATA_QTD = re.compile(
    r"^\d{2}/\d{2}/\d{4}\s+\d[\d.,]*$"
)

PADRAO_SEPARADOR = re.compile(
    r"^[_\-]{10,}$"
)


def detectar_formato_documento(linhas: List[LinhaDocumento]) -> str:
    """
    Analisa as primeiras linhas e decide qual é o formato do documento.
    Retorna 'MRV', 'KRONA' ou 'DESCONHECIDO'.
    """
    votos_mrv = 0
    votos_krona = 0

    votos_uau = 0

    for linha in linhas[:60]:
        texto = linha.texto_normalizado.strip()

        if PADRAO_INICIO_ITEM_MRV.match(texto):
            votos_mrv += 2

        if PADRAO_INICIO_ITEM_KRONA.match(texto):
            votos_krona += 2

        if PADRAO_INICIO_ITEM_UAU.match(texto) or PADRAO_INICIO_ITEM_UAU_QUEBRADO.match(texto):
            votos_uau += 2

        if PADRAO_CABECALHO_KRONA.search(texto):
            votos_krona += 1

        if PADRAO_CABECALHO_UAU.search(texto):
            votos_uau += 1

        texto_upper = texto.upper()
        if "NCM" in texto_upper and "ITEM" in texto_upper and "QUANTIDADE" in texto_upper:
            votos_mrv += 1

        if "PEDIDO DE COMPRA" in texto_upper and "INSUMO" in texto_upper:
            votos_krona += 1

        if "UAU!" in texto_upper or "ORDEM DE COMPRA" in texto_upper and "ITEM" in texto_upper:
            votos_uau += 1

        if "KRONA/KRONA" in texto_upper:
            votos_uau += 3  # Brasal/Closer usa KRONA/KRONA como marcador — detectado como UAU inicialmente

    if votos_uau > votos_krona and votos_uau > votos_mrv:
        return "UAU"
    if votos_krona > votos_mrv:
        return "KRONA"
    if votos_mrv > 0:
        return "MRV"
    return "DESCONHECIDO"


def classificar_linha_mrv(linha: LinhaDocumento) -> LinhaDocumento:
    """Classificação original para o formato MRV."""
    texto = linha.texto_normalizado.strip()
    texto_upper = texto.upper()

    if not texto:
        linha.classe = "RUIDO"
        linha.score = 0.0
        linha.motivos.append("linha_vazia")
        return linha

    if PADRAO_SEPARADOR.match(texto):
        linha.classe = "SEPARADOR"
        linha.score = 1.0
        linha.motivos.append("linha_apenas_separador")
        return linha

    if texto_upper in ("OBSERVAÇÕES", "OBSERVACOES"):
        linha.classe = "LINHA_OBSERVACAO"
        linha.score = 1.0
        linha.motivos.append("titulo_observacoes")
        return linha

    if texto_upper.startswith("PLANEJAMENTO DA ENTREGA"):
        linha.classe = "LINHA_ENTREGA"
        linha.score = 1.0
        linha.motivos.append("titulo_planejamento_entrega")
        return linha

    if PADRAO_DATA_QTD.match(texto):
        linha.classe = "LINHA_ENTREGA"
        linha.score = 0.9
        linha.motivos.append("linha_data_quantidade")
        return linha

    if texto_upper.startswith("DESCRIÇÃO DETALHADA DO PRODUTO") or texto_upper.startswith("DESCRICAO DETALHADA DO PRODUTO"):
        linha.classe = "DESCRICAO_ITEM"
        linha.score = 0.95
        linha.motivos.append("inicio_descricao_detalhada")
        return linha

    if PADRAO_INICIO_ITEM_MRV.match(texto):
        linha.classe = "INICIO_ITEM"
        linha.score = 0.98
        linha.motivos.append("padrao_forte_inicio_item_mrv")
        return linha

    if (
        " FOLHA" in texto_upper
        or texto_upper.startswith("DADOS DA CONTRATANTE")
        or texto_upper.startswith("LOCAL DATA FOLHA")
        or texto_upper.startswith("DADOS PARA FATURAMENTO")
        or texto_upper.startswith("DADOS DE APROVAÇÃO")
        or texto_upper.startswith("ITEM Nº PRODUTO NCM QUANTIDADE")
        or texto_upper.startswith("FRETE IPI PRC.UNITARIO VALOR TOTAL")
    ):
        linha.classe = "CABECALHO_PAGINA"
        linha.score = 0.85
        linha.motivos.append("cabecalho_pagina")
        return linha

    if (
        texto_upper.startswith("DATA ENTREGA:")
        or texto_upper.startswith("Nº PEDIDO DE COMPRA:")
        or texto_upper.startswith("NO PEDIDO DE COMPRA:")
        or texto_upper.startswith("NOTA FISCAL:")
        or texto_upper.startswith("LOCAL DE ENTREGA:")
        or texto_upper.startswith("CONDIÇÃO DE PAGAMENTO")
        or texto_upper.startswith("USUARIO CRIACAO:")
        or texto_upper.startswith("USUÁRIO CRIAÇÃO:")
        or texto_upper.startswith("DADOS DA CONTRATADA")
        or texto_upper.startswith("ENDERECO PARA COBRANÇA:")
        or texto_upper.startswith("ENDEREÇO PARA COBRANÇA:")
        or texto_upper.startswith("FILIAL:")
        or texto_upper.startswith("CNPJ:")
        or texto_upper.startswith("CEP:")
    ):
        linha.classe = "BLOCO_ADMINISTRATIVO"
        linha.score = 0.9
        linha.motivos.append("linha_administrativa_ou_logistica")
        return linha

    linha.classe = "DESCONHECIDA"
    linha.score = 0.1
    linha.motivos.append("sem_regra_especifica")
    return linha


def classificar_linha_krona(linha: LinhaDocumento) -> LinhaDocumento:
    """Classificação para o formato Krona/L2M."""
    texto = linha.texto_normalizado.strip()
    texto_upper = texto.upper()

    if not texto:
        linha.classe = "RUIDO"
        linha.score = 0.0
        linha.motivos.append("linha_vazia")
        return linha

    # lixo de codificação — linha só tem (cid:XX)
    texto_sem_cid = PADRAO_LIXO_CID.sub("", texto).strip()
    if not texto_sem_cid:
        linha.classe = "RUIDO"
        linha.score = 0.0
        linha.motivos.append("linha_apenas_cid")
        return linha

    # cabeçalho da tabela de itens
    if PADRAO_CABECALHO_KRONA.search(texto):
        linha.classe = "CABECALHO_PAGINA"
        linha.score = 0.95
        linha.motivos.append("cabecalho_tabela_krona")
        return linha

    # cabeçalho de página (repete "Pedido de Compra" no topo de cada página)
    if texto_upper in ("PEDIDO DE COMPRA",):
        linha.classe = "CABECALHO_PAGINA"
        linha.score = 0.95
        linha.motivos.append("titulo_pagina_krona")
        return linha

    # blocos administrativos
    if (
        texto_upper.startswith("DADOS DO FATURAMENTO")
        or texto_upper.startswith("DADOS DO FORNECEDOR")
        or texto_upper.startswith("DADOS DA OBRA")
        or texto_upper.startswith("NOME")
        or texto_upper.startswith("ENDEREÇO")
        or texto_upper.startswith("ENDERECO")
        or texto_upper.startswith("CNPJ")
        or texto_upper.startswith("IE ")
        or texto_upper.startswith("VENDEDOR")
        or texto_upper.startswith("HOME PAGE")
        or texto_upper.startswith("E-MAIL")
        or texto_upper.startswith("OBRA")
        or texto_upper.startswith("LOCAL ENTREGA")
        or texto_upper.startswith("PONTO REFER")
        or texto_upper.startswith("Nº PEDIDO")
        or texto_upper.startswith("COTAÇÕES")
        or texto_upper.startswith("SOLICITAÇÕES")
    ):
        linha.classe = "BLOCO_ADMINISTRATIVO"
        linha.score = 0.9
        linha.motivos.append("linha_administrativa_krona")
        return linha

    # linha de início de item no formato Krona
    if PADRAO_INICIO_ITEM_KRONA.match(texto):
        linha.classe = "INICIO_ITEM"
        linha.score = 0.97
        linha.motivos.append("padrao_forte_inicio_item_krona")
        return linha

    # linha de continuação de descrição (texto livre sem número de item no início)
    linha.classe = "DESCRICAO_ITEM"
    linha.score = 0.7
    linha.motivos.append("continuacao_descricao_krona")
    return linha


def classificar_linha_uau(linha: LinhaDocumento) -> LinhaDocumento:
    """Classificação para o formato UAU (GPL Incorporadora e similares)."""
    texto = linha.texto_normalizado.strip()
    texto_upper = texto.upper()

    if not texto:
        linha.classe = "RUIDO"
        linha.score = 0.0
        linha.motivos.append("linha_vazia")
        return linha

    # rodapé — totais, aprovação, assinatura
    if PADRAO_RODAPE_UAU.search(texto):
        linha.classe = "BLOCO_ADMINISTRATIVO"
        linha.score = 0.95
        linha.motivos.append("rodape_uau")
        return linha

    # cabeçalho da tabela
    if PADRAO_CABECALHO_UAU.search(texto):
        linha.classe = "CABECALHO_PAGINA"
        linha.score = 0.95
        linha.motivos.append("cabecalho_tabela_uau")
        return linha

    # blocos administrativos do topo do documento
    if (
        texto_upper.startswith("RIO VERDE")
        or texto_upper.startswith("ORDEM DE COMPRA")
        or texto_upper.startswith("CNO:")
        or texto_upper.startswith("GEROU O.C.")
        or texto_upper.startswith("FATURAR PARA")
        or texto_upper.startswith("FORNECEDOR:")
        or texto_upper.startswith("CNPJ")
        or texto_upper.startswith("INSC.")
        or texto_upper.startswith("CONDIÇÕES")
        or texto_upper.startswith("CONDICOES")
        or texto_upper.startswith("RUA ")
        or texto_upper.startswith("CEP")
        or texto_upper.startswith("E-MAIL")
        or texto_upper.startswith("OBSERVA")
        or texto_upper.startswith("DEPT.")
        or texto_upper.startswith("DIRETORIA")
        or "UAU! SOFTWARE" in texto_upper
        or "PÁGINA" in texto_upper
        or "PAGINA" in texto_upper
    ):
        linha.classe = "BLOCO_ADMINISTRATIVO"
        linha.score = 0.9
        linha.motivos.append("linha_administrativa_uau")
        return linha

    # item completo em uma linha
    if PADRAO_INICIO_ITEM_UAU.match(texto):
        linha.classe = "INICIO_ITEM"
        linha.score = 0.97
        linha.motivos.append("padrao_forte_inicio_item_uau")
        return linha

    # item com quantidade quebrada — ex: "6 FVM - TUBO PVC SOLDAVEL 25MM 6MT - NBR 5648 M 3.000,0000"
    if PADRAO_INICIO_ITEM_UAU_QUEBRADO.match(texto):
        linha.classe = "INICIO_ITEM"
        linha.score = 0.90
        linha.motivos.append("inicio_item_uau_quebrado")
        return linha

    # continuação de quantidade quebrada — ex: "00" ou "0"
    if PADRAO_CONTINUACAO_UAU.match(texto):
        linha.classe = "DESCRICAO_ITEM"
        linha.score = 0.80
        linha.motivos.append("continuacao_quantidade_uau")
        return linha

    # item quebrado entre paginas — sem descricao, vai para revisao manual
    if PADRAO_ITEM_QUEBRADO_PAGINA_UAU.match(texto):
        linha.classe = "INICIO_ITEM"
        linha.score = 0.60
        linha.motivos.append("item_quebrado_entre_paginas_sem_descricao")
        return linha

    # qualquer outra linha — ruído administrativo
    linha.classe = "RUIDO"
    linha.score = 0.1
    linha.motivos.append("ruido_uau")
    return linha


def classificar_linhas_documento(linhas: List[LinhaDocumento]) -> List[LinhaDocumento]:
    """
    Detecta automaticamente o formato do documento e aplica
    a classificação adequada para cada linha.
    """
    formato = detectar_formato_documento(linhas)

    for linha in linhas:
        linha.motivos.append(f"formato_detectado={formato}")

        if formato == "UAU":
            classificar_linha_uau(linha)
        elif formato == "KRONA":
            classificar_linha_krona(linha)
        else:
            # MRV é o padrão — também usado para DESCONHECIDO como melhor esforço
            classificar_linha_mrv(linha)

    return linhas
