from typing import List, Dict, Any

from extracao_oc.pdf_reader import extrair_linhas_pdf, extrair_linhas_pdf_uau
from extracao_oc.normalizador_oc import normalizar_linhas
from extracao_oc.segmentador_documento import classificar_linhas_documento, detectar_formato_documento
from extracao_oc.agrupador_itens import agrupar_blocos_itens
from extracao_oc.estruturador_item import estruturar_blocos_em_itens
from extracao_oc.validacao_extracao_oc import validar_itens_extraidos
from extracao_oc.debug_extracao import gerar_relatorio_extracao


def extrair_itens_oc(caminho_pdf: str, caminho_debug: str | None = None) -> List[Dict[str, Any]]:
    # pre-leitura para detectar o formato sem usar o extrator definitivo ainda
    linhas_probe = extrair_linhas_pdf(caminho_pdf)
    linhas_probe = normalizar_linhas(linhas_probe)
    formato = detectar_formato_documento(linhas_probe)

    # UAU usa extract_tables() para preservar a estrutura de colunas
    # MRV e Krona continuam usando o extrator de texto original
    if formato == "UAU":
        linhas = extrair_linhas_pdf_uau(caminho_pdf)
    else:
        linhas = linhas_probe

    linhas = normalizar_linhas(linhas) if formato == "UAU" else linhas
    linhas = classificar_linhas_documento(linhas)

    blocos = agrupar_blocos_itens(linhas)
    itens = estruturar_blocos_em_itens(blocos)
    itens = validar_itens_extraidos(itens)

    if caminho_debug:
        gerar_relatorio_extracao(itens, caminho_debug)

    resultado = []
    for item in itens:
        resultado.append({
            "idx_item": item.idx_item,
            "codigo_interno_oc": item.codigo_interno_oc,
            "descricao_original": item.descricao_original,
            "descricao_reconstruida": item.descricao_reconstruida,
            "quantidade": item.quantidade,
            "unidade_original": item.unidade_original,
            "unidade_normalizada": item.unidade_normalizada,
            "valor_unitario": item.valor_unitario,
            "valor_total": item.valor_total,
            "pagina": item.pagina,
            "linhas_origem": item.linhas_origem,
            "score_extracao": item.score_extracao,
            "status_extracao": item.status_extracao,
            "observacoes": item.observacoes,
        })

    return resultado