from pathlib import Path
from typing import List

from extracao_oc.modelos import ItemExtraido


def gerar_relatorio_extracao(itens: List[ItemExtraido], caminho_saida: str) -> str:
    caminho = Path(caminho_saida)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    linhas = []
    linhas.append("RELATORIO DE EXTRAÇÃO DE OC")
    linhas.append("=" * 80)
    linhas.append(f"TOTAL DE ITENS: {len(itens)}")
    linhas.append("")

    total_ok = sum(1 for item in itens if item.status_extracao == "ok")
    total_ressalva = sum(1 for item in itens if item.status_extracao == "ok_com_ressalvas")
    total_duvidoso = sum(1 for item in itens if item.status_extracao == "duvidoso")
    total_falhou = sum(1 for item in itens if item.status_extracao == "falhou")

    linhas.append("RESUMO")
    linhas.append("-" * 80)
    linhas.append(f"OK: {total_ok}")
    linhas.append(f"OK_COM_RESSALVAS: {total_ressalva}")
    linhas.append(f"DUVIDOSO: {total_duvidoso}")
    linhas.append(f"FALHOU: {total_falhou}")
    linhas.append("")

    for i, item in enumerate(itens, start=1):
        linhas.append(f"ITEM {i}")
        linhas.append("-" * 80)
        linhas.append(f"idx_item: {item.idx_item}")
        linhas.append(f"codigo_interno_oc: {item.codigo_interno_oc}")
        linhas.append(f"descricao: {item.descricao_reconstruida}")
        linhas.append(f"quantidade: {item.quantidade}")
        linhas.append(f"unidade: {item.unidade_normalizada}")
        linhas.append(f"valor_unitario: {item.valor_unitario}")
        linhas.append(f"valor_total: {item.valor_total}")
        linhas.append(f"pagina: {item.pagina}")
        linhas.append(f"linhas_origem: {item.linhas_origem}")
        linhas.append(f"status_extracao: {item.status_extracao}")
        linhas.append(f"score_extracao: {item.score_extracao}")

        if item.observacoes:
            linhas.append("observacoes:")
            for obs in item.observacoes:
                linhas.append(f"  - {obs}")
        else:
            linhas.append("observacoes: []")

        linhas.append("")

    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return str(caminho)