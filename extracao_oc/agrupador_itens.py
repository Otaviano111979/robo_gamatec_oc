from typing import List, Optional

from extracao_oc.modelos import LinhaDocumento, BlocoItem


CLASSES_QUE_ENTRAM_NO_BLOCO = {
    "INICIO_ITEM",
    "DESCRICAO_ITEM",
    "LINHA_ENTREGA",
    "LINHA_OBSERVACAO",
    "DESCONHECIDA",
    "SEPARADOR",
}

CLASSES_QUE_INTERROMPEM_BLOCO = {
    "CABECALHO_PAGINA",
    "BLOCO_ADMINISTRATIVO",
}


def agrupar_blocos_itens(linhas: List[LinhaDocumento]) -> List[BlocoItem]:
    blocos: List[BlocoItem] = []
    bloco_atual: Optional[BlocoItem] = None

    for linha in linhas:
        classe = linha.classe

        if classe == "INICIO_ITEM":
            if bloco_atual is not None and bloco_atual.linhas:
                bloco_atual.observacoes.append("bloco_fechado_por_novo_inicio_item")
                blocos.append(bloco_atual)

            bloco_atual = BlocoItem(
                pagina_inicial=linha.pagina,
                linhas=[linha],
                score_bloco=0.5,
                observacoes=[]
            )
            continue

        if bloco_atual is None:
            continue

        if classe in CLASSES_QUE_INTERROMPEM_BLOCO:
            bloco_atual.observacoes.append(f"bloco_interrompido_por_{classe.lower()}")
            blocos.append(bloco_atual)
            bloco_atual = None
            continue

        if classe in CLASSES_QUE_ENTRAM_NO_BLOCO:
            bloco_atual.linhas.append(linha)

            if classe == "SEPARADOR":
                bloco_atual.score_bloco = 0.9
                bloco_atual.observacoes.append("bloco_encerrado_por_separador")
                blocos.append(bloco_atual)
                bloco_atual = None

    if bloco_atual is not None and bloco_atual.linhas:
        bloco_atual.observacoes.append("bloco_fechado_no_fim_documento")
        blocos.append(bloco_atual)

    return blocos