# -*- coding: utf-8 -*-
"""
comparador_oc_orcamento.py — Compara OC processada com orçamento Gamatec

Regra de negócio:
  - preço final (após desconto) deve ser <= preço da OC
  - desconto = ((preco_orcamento - preco_oc) / preco_orcamento) * 100
  - se preco_orcamento <= preco_oc → desconto = 0 (já está OK)
  - arredonda desconto para 5 casas decimais

Status por item:
  OK       → desconto calculado, preço final <= OC
  ABAIXO   → preço orçamento já <= OC (desconto = 0, ok)
  SEM_OC   → item do orçamento não encontrado na OC
  SEM_ORC  → item da OC não encontrado no orçamento
"""

import os
import io
import pandas as pd
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, InvalidOperation


def _parse_num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None  # nan check
    s = str(v).strip().replace(' ', '')
    if not s or s.lower() in ('nan', 'none', ''):
        return None
    s = s.replace('.', '').replace(',', '.') if ',' in s else s
    try:
        return float(s)
    except Exception:
        return None


def _to_decimal(v) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def preco_seguro_ate_oc(preco_calculado, preco_oc) -> Decimal | None:
    preco_calculado_dec = _to_decimal(preco_calculado)
    preco_oc_dec = _to_decimal(preco_oc)
    if preco_calculado_dec is None or preco_oc_dec is None:
        return None

    preco_oc_cents = preco_oc_dec.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    if preco_calculado_dec >= preco_oc_dec:
        return preco_oc_cents

    candidato = preco_calculado_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if candidato > preco_oc_cents:
        return preco_oc_cents
    return candidato


def _norm_codigo(v) -> str:
    """Normaliza código Krona: remove zeros à esquerda."""
    s = str(v or '').strip()
    try:
        return str(int(float(s)))
    except Exception:
        return s.lstrip('0') or '0'


def calcular_desconto(preco_orcamento: float, preco_oc: float) -> tuple[float, str]:
    """
    Retorna (desconto_percentual, status).
    Regra: preço final deve ser <= preço_oc.
    desconto = ((preco_orcamento - preco_oc) / preco_orcamento) * 100
    """
    orc_dec = _to_decimal(preco_orcamento)
    oc_dec = _to_decimal(preco_oc)
    if orc_dec is None or oc_dec is None:
        return None, 'SEM_PRECO'
    if orc_dec <= 0:
        return None, 'SEM_PRECO'
    if orc_dec <= oc_dec:
        return 0.0, 'ABAIXO'

    desconto_dec = ((orc_dec - oc_dec) / orc_dec) * Decimal("100")
    if desconto_dec < 0:
        desconto_dec = Decimal("0")
    desconto_dec = desconto_dec.quantize(Decimal("0.00001"), rounding=ROUND_UP)
    return float(desconto_dec), 'OK'


def comparar_oc_orcamento(
    df_oc: pd.DataFrame,
    itens_orcamento: list[dict],
) -> pd.DataFrame:
    """
    df_oc: DataFrame com colunas mínimas:
        codigo_krona, descricao_krona, quantidade_final, valor_unitario_oc

    itens_orcamento: lista de dicts com:
        codigo, descricao, qtde, preco_orcamento

    Retorna DataFrame com comparação completa.
    """

    # ── Normalizar OC ────────────────────────────────────────────────────────
    col_codigo = _localizar_col(df_oc, ['codigo_krona', 'codigo', 'cod_krona'])
    col_desc   = _localizar_col(df_oc, ['descricao_krona', 'descricao', 'descricao_oc', 'descricao_reconstruida'])
    col_qtde   = _localizar_col(df_oc, ['quantidade_final', 'quantidade_convertida', 'quantidade'])
    col_preco  = _localizar_col(df_oc, ['valor_unitario_oc', 'valor_unitario', 'preco_alvo', 'preco_unitario', 'preco_cliente'])

    # Montar mapa OC: codigo_norm → {descricao, qtde, preco_oc}
    mapa_oc = {}
    for _, row in df_oc.iterrows():
        cod = _norm_codigo(row.get(col_codigo)) if col_codigo else ''
        if not cod:
            continue
        mapa_oc[cod] = {
            'descricao_oc': str(row.get(col_desc, '') or ''),
            'quantidade':   _parse_num(row.get(col_qtde)) if col_qtde else None,
            'preco_oc':     _parse_num(row.get(col_preco)) if col_preco else None,
        }

    # ── Montar mapa orçamento: codigo_norm → {descricao, qtde, preco_orc} ───
    mapa_orc = {}
    for it in itens_orcamento:
        cod = _norm_codigo(it.get('codigo', ''))
        if not cod:
            continue
        mapa_orc[cod] = {
            'descricao_orc':  it.get('descricao', ''),
            'qtde_orc':       it.get('qtde'),
            'preco_orcamento': it.get('preco_orcamento'),
        }

    # ── Cruzar ───────────────────────────────────────────────────────────────
    registros = []
    codigos_vistos = set()

    # Itens da OC
    for cod, oc in mapa_oc.items():
        codigos_vistos.add(cod)
        orc = mapa_orc.get(cod)

        preco_orc = orc['preco_orcamento'] if orc else None
        preco_oc  = oc['preco_oc']

        desconto, status = calcular_desconto(preco_orc, preco_oc)

        if orc is None:
            status = 'SEM_ORC'

        obs = None
        preco_final = None
        preco_orc_dec = _to_decimal(preco_orc)
        preco_oc_dec = _to_decimal(preco_oc)

        if preco_orc_dec is not None and desconto is not None:
            desconto_dec = _to_decimal(desconto)
            if desconto_dec is None:
                desconto_dec = Decimal("0")

            preco_final_calc = preco_orc_dec * (Decimal("1") - (desconto_dec / Decimal("100")))
            preco_final_safe_dec = preco_seguro_ate_oc(preco_final_calc, preco_oc_dec) if preco_oc_dec is not None else None

            if preco_oc_dec is not None and preco_final_calc > preco_oc_dec:
                obs = "Limitado pela OC"

            if preco_final_safe_dec is not None:
                preco_final = f"{preco_final_safe_dec:.2f}"

        registros.append({
            'CODIGO':           cod,
            'DESCRICAO':        oc['descricao_oc'] or (orc['descricao_orc'] if orc else ''),
            'QUANTIDADE':       oc['quantidade'],
            'PRECO_OC':         preco_oc,
            'PRECO_ORCAMENTO':  preco_orc,
            'DESCONTO':         desconto,
            'PRECO_FINAL':      preco_final,
            'OBS':              obs,
            'STATUS':           status,
        })

    # Itens do orçamento que não estão na OC
    for cod, orc in mapa_orc.items():
        if cod in codigos_vistos:
            continue
        registros.append({
            'CODIGO':           cod,
            'DESCRICAO':        orc['descricao_orc'],
            'QUANTIDADE':       orc['qtde_orc'],
            'PRECO_OC':         None,
            'PRECO_ORCAMENTO':  orc['preco_orcamento'],
            'DESCONTO':         None,
            'PRECO_FINAL':      None,
            'OBS':              None,
            'STATUS':           'SEM_OC',
        })

    return pd.DataFrame(registros)


def gerar_planilha_desconto(
    df_comparacao: pd.DataFrame,
    caminho_xlsx: str,
    caminho_csv: str | None = None,
) -> None:
    """
    Gera planilha Excel formatada para digitação no GAMATEC.
    Colunas: DESCRICAO | CODIGO | QUANTIDADE | DESCONTO
    Só inclui itens com status OK ou ABAIXO (que têm match em ambos os lados).
    """
    df_gamatec = df_comparacao[
        df_comparacao['STATUS'].isin(['OK', 'ABAIXO'])
    ][['DESCRICAO', 'CODIGO', 'QUANTIDADE', 'DESCONTO']].copy()

    os.makedirs(os.path.dirname(caminho_xlsx) or '.', exist_ok=True)

    df_gamatec.to_excel(caminho_xlsx, index=False)

    if caminho_csv:
        df_gamatec.to_csv(caminho_csv, index=False, sep=';', encoding='utf-8-sig')


def _localizar_col(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    mapa = {str(c).strip().lower(): c for c in df.columns}
    return next((mapa[c] for c in candidatos if c in mapa), None)
