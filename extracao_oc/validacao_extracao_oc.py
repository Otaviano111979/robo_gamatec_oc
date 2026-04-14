from typing import List

from extracao_oc.modelos import ItemExtraido


def quase_igual(a: float, b: float, tolerancia: float = 0.02) -> bool:
    if a is None or b is None:
        return False

    if b == 0:
        return abs(a - b) <= tolerancia

    diferenca_relativa = abs(a - b) / abs(b)
    return diferenca_relativa <= tolerancia


def validar_item_extraido(item: ItemExtraido) -> ItemExtraido:
    observacoes_validacao = []

    descricao_ok = bool(item.descricao_reconstruida and item.descricao_reconstruida.strip())
    quantidade_ok = item.quantidade is not None and item.quantidade > 0
    unidade_ok = bool(item.unidade_normalizada and item.unidade_normalizada.strip())
    valor_unitario_ok = item.valor_unitario is not None and item.valor_unitario >= 0
    valor_total_ok = item.valor_total is not None and item.valor_total >= 0

    if not descricao_ok:
        observacoes_validacao.append("validacao:descricao_ausente")

    if not quantidade_ok:
        observacoes_validacao.append("validacao:quantidade_ausente_ou_invalida")

    if not unidade_ok:
        observacoes_validacao.append("validacao:unidade_ausente")

    if not valor_unitario_ok:
        observacoes_validacao.append("validacao:valor_unitario_ausente_ou_invalido")

    if not valor_total_ok:
        observacoes_validacao.append("validacao:valor_total_ausente_ou_invalido")

    conta_fecha = False

    if quantidade_ok and valor_unitario_ok and valor_total_ok:
        total_calculado = item.quantidade * item.valor_unitario
        conta_fecha = quase_igual(total_calculado, item.valor_total, tolerancia=0.02)

        if not conta_fecha:
            observacoes_validacao.append(
                f"validacao:total_nao_confere_calculado={total_calculado:.2f}_informado={item.valor_total:.2f}"
            )
        else:
            observacoes_validacao.append("validacao:total_confere")

    item.observacoes.extend(observacoes_validacao)

    if (
        descricao_ok
        and quantidade_ok
        and unidade_ok
        and valor_unitario_ok
        and valor_total_ok
        and conta_fecha
        and item.status_extracao == "ok"
    ):
        item.status_extracao = "ok"

    elif descricao_ok and quantidade_ok and unidade_ok:
        item.status_extracao = "ok_com_ressalvas"

    else:
        item.status_extracao = "duvidoso"

    if any("item_interrompido_por_bloco_administrativo" in obs for obs in item.observacoes):
        item.status_extracao = "ok_com_ressalvas"

    if item.status_extracao == "ok":
        item.score_extracao = max(item.score_extracao, 0.92)
    elif item.status_extracao == "ok_com_ressalvas":
        item.score_extracao = min(item.score_extracao, 0.80)
    elif item.status_extracao == "duvidoso":
        item.score_extracao = min(item.score_extracao, 0.55)

    return item


def validar_itens_extraidos(itens: List[ItemExtraido]) -> List[ItemExtraido]:
    return [validar_item_extraido(item) for item in itens]