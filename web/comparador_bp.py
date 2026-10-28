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
import math
import re
import secrets
import tempfile
import uuid
import pandas as pd
from pathlib import Path
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, InvalidOperation
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, send_file, flash, jsonify
)

from extrator_orcamento_gamatec import extrair_orcamento_gamatec
from comparador_oc_orcamento import (
    comparar_documento_precificado, comparar_oc_orcamento, gerar_planilha_desconto,
)

# ── Config ────────────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
BASE_DIR  = Path(os.environ.get('GAMATEC_BASE_DIR', Path(_HERE).parent))
SAIDA_DIR = BASE_DIR / 'saida' / 'ocs_individuais'

# Pasta para armazenar dados grandes da sessão no disco
SESSION_TMP_DIR = os.path.join(_HERE, "tmp_session")
os.makedirs(SESSION_TMP_DIR, exist_ok=True)

def _save_session_data(key: str, data: any) -> str:
    """Salva dados no disco e retorna o caminho do arquivo."""
    file_id = f"sess_{session.get('user', 'anon')}_{key}.json"
    path = os.path.join(SESSION_TMP_DIR, file_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return file_id

def _load_session_data(file_id: str, default: any = None) -> any:
    """Carrega dados do disco usando o ID salvo na sessão."""
    if not file_id: return default
    path = os.path.join(SESSION_TMP_DIR, file_id)
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _preco_seguro_ate_oc(preco_calculado, preco_oc) -> str | None:
    try:
        preco_calculado_dec = Decimal(str(preco_calculado))
        preco_oc_dec = Decimal(str(preco_oc))
    except (InvalidOperation, ValueError):
        return None

    preco_oc_cents = preco_oc_dec.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    if preco_calculado_dec >= preco_oc_dec:
        return f"{preco_oc_cents:.2f}"

    candidato = preco_calculado_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if candidato > preco_oc_cents:
        candidato = preco_oc_cents
    return f"{candidato:.2f}"

comparador_bp = Blueprint(
    'comparador',
    __name__,
    url_prefix='/comparador',
    template_folder=os.path.join(_HERE, 'templates', 'comparador'),
    static_folder=os.path.join(_HERE, 'static', 'comparador'),
)

@comparador_bp.before_request
def autenticar_precificado():
    if request.endpoint and request.endpoint.startswith('comparador.precificado_'):
        if 'user' not in session:
            return redirect('/')


@comparador_bp.errorhandler(413)
def precificado_upload_grande(erro):
    if request.endpoint and request.endpoint.startswith('comparador.precificado_'):
        return _precificado_erro('Os dois PDFs ultrapassam o limite de upload. Envie arquivos menores.', 413)
    return redirect('/ocs?erro=arquivo_grande')


def _precificado_erro(mensagem: str, status: int = 422):
    flash(mensagem)
    return render_template(
        'precificado_upload.html', csrf_token=session.get('precificado_csrf', ''),
    ), status


def _dados_precificados():
    file_id = request.args.get('id', '')
    if file_id != session.get('comparador_precificado'):
        return None
    if not re.fullmatch(r'sess_precificado_[0-9a-f]{32}\.json', file_id):
        return None
    return _load_session_data(file_id)


@comparador_bp.get('/documento-precificado')
def precificado_upload():
    if 'precificado_csrf' not in session:
        session['precificado_csrf'] = secrets.token_urlsafe(32)
    return render_template('precificado_upload.html', csrf_token=session['precificado_csrf'])


@comparador_bp.post('/documento-precificado/processar')
def precificado_processar():
    token = session.get('precificado_csrf', '')
    recebido = request.form.get('_csrf', '')
    if not token or not secrets.compare_digest(token.encode('utf-8'), recebido.encode('utf-8')):
        return _precificado_erro('Atualize a página e tente novamente: validação da sessão falhou.', 400)

    for campo, nome in (('documento', 'documento já precificado'), ('orcamento', 'orçamento Gamatec')):
        arquivo = request.files.get(campo)
        if not arquivo or not arquivo.filename:
            return _precificado_erro(f'Selecione o PDF do {nome}.')
        if not arquivo.filename.lower().endswith('.pdf'):
            return _precificado_erro(f'O {nome} deve ser um arquivo PDF.')

    try:
        orcamento = extrair_orcamento_gamatec(request.files['orcamento'].read())
        if not orcamento['itens']:
            return _precificado_erro('Nenhum item encontrado no PDF do orçamento Gamatec.')
        if any(not math.isfinite(item[chave]) for item in orcamento['itens']
               for chave in ('preco_orcamento', 'qtde')):
            return _precificado_erro('O orçamento contém preços ou quantidades inválidos.')
        codigos = [item['codigo'] for item in orcamento['itens']]
        if len(codigos) != len(set(codigos)):
            return _precificado_erro('O orçamento contém código repetido; confira os itens antes de comparar.')
        df = comparar_documento_precificado(request.files['documento'].read(), orcamento['itens'])
    except Exception as erro:
        return _precificado_erro(f'Não foi possível comparar os documentos: {erro}')

    registros = df.to_dict('records')
    for registro in registros:
        for chave, valor in registro.items():
            if isinstance(valor, Decimal):
                registro[chave] = str(valor)
            elif isinstance(valor, float) and valor != valor:
                registro[chave] = None

    stats = {status.lower(): sum(r['STATUS'] == status for r in registros)
             for status in ('OK', 'ABAIXO', 'SEM_ORC', 'SEM_OC', 'SEM_PRECO')}
    stats['total'] = len(registros)
    stats['para_gamatec'] = stats['ok'] + stats['abaixo']
    dados = {
        'nome_documento': request.files['documento'].filename,
        'numero_orcamento': orcamento['numero_orcamento'],
        'emissao': orcamento['emissao'],
        'registros': registros,
        'stats': stats,
        'diferencas_totais': sum(
            r['DIFERENCA_TOTAL'] is not None and Decimal(r['DIFERENCA_TOTAL']) != 0
            for r in registros
        ),
        'total_documento': str(sum(
            Decimal(r['TOTAL_DOCUMENTO']) for r in registros if r['TOTAL_DOCUMENTO'] is not None
        )),
    }
    file_id = f'sess_precificado_{uuid.uuid4().hex}.json'
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=SESSION_TMP_DIR, suffix='.tmp', delete=False,
        ) as arquivo:
            temporario = Path(arquivo.name)
            json.dump(dados, arquivo, ensure_ascii=False, allow_nan=False)
        os.replace(temporario, os.path.join(SESSION_TMP_DIR, file_id))
    except OSError:
        return _precificado_erro('Não foi possível guardar o resultado. Tente novamente.', 503)
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)
    session['comparador_precificado'] = file_id
    return redirect(url_for('comparador.precificado_resultado', id=file_id), code=303)


@comparador_bp.get('/documento-precificado/resultado')
def precificado_resultado():
    dados = _dados_precificados()
    if not dados:
        flash('Comparação indisponível ou sessão expirada. Envie os dois PDFs novamente.')
        return redirect(url_for('comparador.precificado_upload'))
    return render_template(
        'resultado.html', precificado=True, dados=dados, registros=dados['registros'],
        stats=dados['stats'], file_id=request.args['id'],
    )


@comparador_bp.get('/documento-precificado/download')
def precificado_download():
    dados = _dados_precificados()
    if not dados:
        flash('Comparação indisponível ou sessão expirada. Envie os dois PDFs novamente.')
        return redirect(url_for('comparador.precificado_upload'))

    colunas = [
        'CODIGO', 'DESCRICAO', 'QUANTIDADE', 'PRECO_DOCUMENTO', 'TOTAL_DOCUMENTO',
        'TOTAL_CALCULADO', 'DIFERENCA_TOTAL', 'PRECO_ORCAMENTO', 'DESCONTO',
        'PRECO_FINAL', 'STATUS', 'OBS',
    ]
    df = pd.DataFrame(dados['registros']).rename(columns={'PRECO_OC': 'PRECO_DOCUMENTO'})[colunas]
    for coluna in colunas[2:10]:
        df[coluna] = pd.to_numeric(df[coluna])
    aprovados = df[df['STATUS'].isin(['OK', 'ABAIXO'])][
        ['DESCRICAO', 'CODIGO', 'QUANTIDADE', 'DESCONTO']
    ].copy()
    aprovados['DESCONTO'] = aprovados['DESCONTO'].map(lambda valor: f'{valor:.5f}')
    output = io.BytesIO()
    with pd.ExcelWriter(
        output, engine='xlsxwriter',
        engine_kwargs={'options': {'strings_to_formulas': False, 'strings_to_urls': False}},
    ) as writer:
        df.to_excel(writer, index=False, sheet_name='comparacao')
        aprovados.to_excel(writer, index=False, sheet_name='gamatec')
        wb = writer.book
        preco = wb.add_format({'num_format': '0.000'})
        dinheiro = wb.add_format({'num_format': '0.00'})
        desconto = wb.add_format({'num_format': '0.00000'})
        for sheet in writer.sheets.values():
            sheet.freeze_panes(1, 0)
            sheet.set_column('A:A', 14)
            sheet.set_column('B:B', 50)
            sheet.set_column('C:L', 18)
        ws = writer.sheets['comparacao']
        ws.set_column('D:D', 18, preco)
        ws.set_column('E:G', 18, dinheiro)
        ws.set_column('H:H', 18, preco)
        ws.set_column('I:I', 18, desconto)
        ws.set_column('J:J', 18, dinheiro)
        writer.sheets['gamatec'].set_column('A:A', 50)
        writer.sheets['gamatec'].set_column('B:B', 14)
    output.seek(0)
    return send_file(
        output, as_attachment=True, download_name='comparacao_documento_precificado.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
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

    # ── Salvar resultado no DISCO e ID na sessão ───────────────────────────────
    registros = df_comp.to_dict('records')
    # Converter NaN para None (JSON-safe)
    for r in registros:
        for k, v in r.items():
            if isinstance(v, float) and v != v:
                r[k] = None

    dados_comparacao = {
        'oc_id':            oc_id,
        'numero_orcamento': orcamento['numero_orcamento'],
        'cliente':          orcamento['cliente'],
        'emissao':          orcamento['emissao'],
        'total_orcamento':  orcamento['total_itens'],
        'registros':        registros,
    }
    
    # Salva no disco e guarda apenas o ID na session
    session[_session_key(oc_id)] = _save_session_data(f"comp_{oc_id}", dados_comparacao)

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
    # Carrega do disco usando o ID salvo na session
    file_id = session.get(_session_key(oc_id))
    dados = _load_session_data(file_id)
    
    if not dados:
        flash('Sessão expirada. Faça o upload novamente.')
        return redirect(url_for('comparador.upload_page', oc_id=oc_id))

    registros = dados['registros']
    for r in registros:
        if r.get('STATUS') not in ('OK', 'ABAIXO'):
            continue
        preco_final = r.get('PRECO_FINAL')
        preco_oc = r.get('PRECO_OC')
        if preco_final is None or preco_oc is None:
            continue
        preco_final_safe = _preco_seguro_ate_oc(preco_final, preco_oc)
        if preco_final_safe is None:
            continue
        r['PRECO_FINAL'] = preco_final_safe

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
    # Carrega do disco usando o ID salvo na session
    file_id = session.get(_session_key(oc_id))
    dados = _load_session_data(file_id)
    
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
        preco_final = r.get('PRECO_FINAL')
        if preco_final is not None and preco_oc is not None:
            preco_final = _preco_seguro_ate_oc(preco_final, preco_oc) or preco_final
        linhas.append({
            'CODIGO':        r.get('CODIGO', ''),
            'DESCRICAO':     r.get('DESCRICAO', ''),
            'QUANTIDADE':    qtde,
            'PRECO OC':      preco_oc,
            'TOTAL OC':      total_oc,
            'PRECO ORC.':    r.get('PRECO_ORCAMENTO'),
            'DESCONTO %':    desconto_str,
            'PRECO FINAL':   preco_final,
            'OBS':           r.get('OBS') or '',
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
        fmt_final    = wb.add_format({'font_color': '#4ade80'})
        fmt_obs      = wb.add_format({'font_color': '#7dd3fc'})
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
        ws.set_column('I:I', 20)   # OBS

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
            if row.get('OBS'):
                ws.write(row_idx, 8, row['OBS'], fmt_obs)

    output.seek(0)

    nome = f'{oc_id}_desconto_gamatec.xlsx'
    return send_file(
        output,
        as_attachment=True,
        download_name=nome,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
