# -*- coding: utf-8 -*-
"""
comparador_bp.py — Blueprint Flask: Comparador OC vs Orçamento Gamatec

Registrar em app_web.py:
    from comparador_bp import comparador_bp
    app.register_blueprint(comparador_bp)

Rotas:
    GET  /comparador/<oc_id>          → tela de upload
    POST /comparador/<oc_id>/processar → processa e mostra resultado
    GET  /comparador/<oc_id>/download  → baixa xlsx para GAMATEC
"""

import os
import io
import json
import pandas as pd
from pathlib import Path
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, send_file, flash, jsonify
)

from extrator_orcamento_gamatec import extrair_orcamento_gamatec
from comparador_oc_orcamento import comparar_oc_orcamento, gerar_planilha_desconto

# ── Config ────────────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
BASE_DIR  = Path(os.environ.get('GAMATEC_BASE_DIR', Path(_HERE).parent))
SAIDA_DIR = BASE_DIR / 'saida' / 'ocs_individuais'

comparador_bp = Blueprint(
    'comparador',
    __name__,
    url_prefix='/comparador',
    template_folder=os.path.join(_HERE, 'templates', 'comparador'),
    static_folder=os.path.join(_HERE, 'static', 'comparador'),
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _csv_oc(oc_id: str) -> Path | None:
    """Localiza o CSV de itens aprovados da OC."""
    pasta = SAIDA_DIR / oc_id
    if not pasta.exists():
        return None
    for sufixo in ['_resultado_processado.csv', '_planilha_digitacao_manual.csv']:
        p = pasta / f'{oc_id}{sufixo}'
        if p.exists():
            return p
    # fallback: qualquer csv da pasta
    csvs = list(pasta.glob('*.csv'))
    return csvs[0] if csvs else None


def _session_key(oc_id: str) -> str:
    return f'comparador_{oc_id}'


# ── Rotas ─────────────────────────────────────────────────────────────────────
@comparador_bp.get('/<oc_id>')
def upload_page(oc_id: str):
    csv_path = _csv_oc(oc_id)
    if not csv_path:
        flash(f'OC "{oc_id}" não encontrada ou sem itens processados.')
        return redirect('/')

    return render_template('upload.html', oc_id=oc_id, csv_path=str(csv_path))


@comparador_bp.post('/<oc_id>/processar')
def processar(oc_id: str):
    csv_path = _csv_oc(oc_id)
    if not csv_path:
        flash('OC não encontrada.')
        return redirect('/')

    if 'orcamento' not in request.files or not request.files['orcamento'].filename:
        flash('Selecione o PDF do orçamento Gamatec.')
        return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    pdf_bytes = request.files['orcamento'].read()

    # ── Extrair orçamento ────────────────────────────────────────────────────
    try:
        orcamento = extrair_orcamento_gamatec(pdf_bytes)
    except Exception as e:
        flash(f'Erro ao ler PDF do orçamento: {e}')
        return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    if not orcamento['itens']:
        flash('Nenhum item encontrado no PDF do orçamento.')
        return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    # ── Ler CSV da OC ────────────────────────────────────────────────────────
    try:
        df_oc = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
    except Exception:
        try:
            df_oc = pd.read_csv(csv_path, encoding='utf-8-sig')
        except Exception as e:
            flash(f'Erro ao ler CSV da OC: {e}')
            return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    # ── Comparar ─────────────────────────────────────────────────────────────
    try:
        df_comp = comparar_oc_orcamento(df_oc, orcamento['itens'])
    except Exception as e:
        flash(f'Erro na comparação: {e}')
        return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    # ── Salvar resultado na sessão ────────────────────────────────────────────
    registros = df_comp.to_dict('records')
    # Converter NaN para None (JSON-safe)
    for r in registros:
        for k, v in r.items():
            if isinstance(v, float) and v != v:
                r[k] = None

    session[_session_key(oc_id)] = {
        'oc_id':            oc_id,
        'numero_orcamento': orcamento['numero_orcamento'],
        'cliente':          orcamento['cliente'],
        'emissao':          orcamento['emissao'],
        'total_orcamento':  orcamento['total_itens'],
        'registros':        registros,
    }

    # ── Salvar xlsx no disco ─────────────────────────────────────────────────
    pasta_saida = SAIDA_DIR / oc_id
    pasta_saida.mkdir(parents=True, exist_ok=True)
    xlsx_path = pasta_saida / f'{oc_id}_desconto_gamatec.xlsx'
    csv_out   = pasta_saida / f'{oc_id}_desconto_gamatec.csv'

    try:
        gerar_planilha_desconto(df_comp, str(xlsx_path), str(csv_out))
    except Exception as e:
        flash(f'Aviso: não foi possível salvar arquivo no disco: {e}')

    return redirect(url_for('comparador.resultado', oc_id=oc_id))


@comparador_bp.get('/<oc_id>/resultado')
def resultado(oc_id: str):
    dados = session.get(_session_key(oc_id))
    if not dados:
        flash('Sessão expirada. Faça o upload novamente.')
        return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    registros = dados['registros']

    # Estatísticas
    total      = len(registros)
    ok         = sum(1 for r in registros if r['STATUS'] == 'OK')
    abaixo     = sum(1 for r in registros if r['STATUS'] == 'ABAIXO')
    sem_orc    = sum(1 for r in registros if r['STATUS'] == 'SEM_ORC')
    sem_oc     = sum(1 for r in registros if r['STATUS'] == 'SEM_OC')

    stats = {
        'total': total,
        'ok': ok,
        'abaixo': abaixo,
        'sem_orc': sem_orc,
        'sem_oc': sem_oc,
        'para_gamatec': ok + abaixo,
    }

    return render_template(
        'resultado.html',
        oc_id=oc_id,
        dados=dados,
        registros=registros,
        stats=stats,
    )


@comparador_bp.get('/<oc_id>/download')
def download(oc_id: str):
    dados = session.get(_session_key(oc_id))
    if not dados:
        flash('Sessão expirada.')
        return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    registros = dados['registros']

    # Montar DataFrame com todas as colunas
    linhas = []
    for r in registros:
        if r['STATUS'] not in ('OK', 'ABAIXO'):
            continue
        qtde     = r.get('QUANTIDADE') or 0
        preco_oc = r.get('PRECO_OC')
        total_oc = round(qtde * preco_oc, 2) if qtde and preco_oc else None
        desconto = r.get('DESCONTO')
        # Desconto com ponto (string formatada)
        desconto_str = f"{desconto:.5f}".replace(',', '.') if desconto is not None else ''
        linhas.append({
            'CODIGO':        r.get('CODIGO', ''),
            'DESCRICAO':     r.get('DESCRICAO', ''),
            'QUANTIDADE':    qtde,
            'PRECO OC':      preco_oc,
            'TOTAL OC':      total_oc,
            'PRECO ORC.':    r.get('PRECO_ORCAMENTO'),
            'DESCONTO %':    desconto_str,
            'PRECO FINAL':   r.get('PRECO_FINAL'),
        })

    df = pd.DataFrame(linhas)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='descontos_gamatec')
        wb = writer.book
        ws = writer.sheets['descontos_gamatec']

        # Formatos
        fmt_header   = wb.add_format({'bold': True, 'bg_color': '#16161f', 'font_color': '#e8e8f0', 'border': 1, 'align': 'center'})
        fmt_cod      = wb.add_format({'font_color': '#00d4ff', 'bold': True})
        fmt_preco_oc = wb.add_format({'bg_color': '#0a1a2a', 'font_color': '#a0d8ff', 'num_format': 'R$ #,##0.000'})
        fmt_total_oc = wb.add_format({'bg_color': '#0a2030', 'font_color': '#00d4ff', 'bold': True, 'num_format': 'R$ #,##0.00'})
        fmt_preco_orc= wb.add_format({'bg_color': '#1a1a0a', 'font_color': '#fde68a', 'num_format': 'R$ #,##0.000'})
        fmt_desconto = wb.add_format({'bg_color': '#0a1a0a', 'font_color': '#4ade80', 'bold': True, 'align': 'center'})
        fmt_final    = wb.add_format({'font_color': '#4ade80', 'num_format': 'R$ #,##0.000'})
        fmt_num      = wb.add_format({'align': 'right'})

        # Largura das colunas
        ws.set_column('A:A', 10)   # CODIGO
        ws.set_column('B:B', 48)   # DESCRICAO
        ws.set_column('C:C', 10)   # QUANTIDADE
        ws.set_column('D:D', 14)   # PRECO OC
        ws.set_column('E:E', 14)   # TOTAL OC
        ws.set_column('F:F', 14)   # PRECO ORC
        ws.set_column('G:G', 14)   # DESCONTO %
        ws.set_column('H:H', 14)   # PRECO FINAL

        # Aplicar formatos por coluna (linha a linha)
        for row_idx, row in enumerate(linhas, start=1):
            ws.write(row_idx, 0, row['CODIGO'],      fmt_cod)
            ws.write(row_idx, 1, row['DESCRICAO'],   None)
            ws.write(row_idx, 2, row['QUANTIDADE'],  fmt_num)
            if row['PRECO OC'] is not None:
                ws.write(row_idx, 3, row['PRECO OC'],   fmt_preco_oc)
            if row['TOTAL OC'] is not None:
                ws.write(row_idx, 4, row['TOTAL OC'],   fmt_total_oc)
            if row['PRECO ORC.'] is not None:
                ws.write(row_idx, 5, row['PRECO ORC.'], fmt_preco_orc)
            ws.write(row_idx, 6, row['DESCONTO %'],  fmt_desconto)
            if row['PRECO FINAL'] is not None:
                ws.write(row_idx, 7, row['PRECO FINAL'], fmt_final)

    output.seek(0)

    nome = f'{oc_id}_desconto_gamatec.xlsx'
    return send_file(
        output,
        as_attachment=True,
        download_name=nome,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
