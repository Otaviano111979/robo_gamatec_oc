# -*- coding: utf-8 -*-
"""comparador_nao_precificado.py — Compara documento sem preço com a tabela do cliente

Fluxo:
    GET  /comparador/documento-nao-precificado            → envio do documento e escolha da tabela
    POST /comparador/documento-nao-precificado/processar  → lê o documento e compara
    GET  /comparador/documento-nao-precificado/resultado  → resultado (sessão em disco)
    GET  /comparador/documento-nao-precificado/download   → planilha Excel
    GET  /comparador/documento-nao-precificado/pdf        → orçamento em PDF
    GET  /comparador/documento-nao-precificado/modelo.xlsx→ modelo para preencher

Não toca no comparador de documento precificado nem no fluxo das OCs.
"""

import json
import os
import re
import secrets
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

import pandas as pd
from flask import (
    Blueprint, abort, flash, redirect, render_template, request,
    send_file, session, url_for,
)

from extrator_documento_nao_precificado import extrair_documento_nao_precificado
from match_documento_tabela import comparar_documento_tabela, resumo
from matcher import carregar_base_krona
from matcher_tabela_cliente import preparar_indice
from tabelas_clientes import carregar_tabela, clientes_disponiveis

_HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_TMP_DIR = os.path.join(_HERE, "tmp_session")
os.makedirs(SESSION_TMP_DIR, exist_ok=True)

_FORMATOS = (".pdf", ".xlsx", ".xls")
_RX_ID = re.compile(r"sess_nao_precificado_[0-9a-f]{32}\.json")
_COLUNAS = [
    "CODIGO CLIENTE", "CODIGO KRONA", "DESCRICAO", "DESCRICAO TABELA",
    "QUANTIDADE", "UNIDADE", "PRECO TABELA", "TOTAL",
    "PRECO DOCUMENTO", "STATUS", "VIA", "OBS",
]

nao_precificado_bp = Blueprint(
    "nao_precificado",
    __name__,
    url_prefix="/comparador",
    template_folder=os.path.join(_HERE, "templates"),
    static_folder=os.path.join(_HERE, "static"),
)


@nao_precificado_bp.before_request
def _exigir_sessao():
    if request.endpoint and request.endpoint.startswith("nao_precificado."):
        if "user" not in session:
            return redirect("/")


@nao_precificado_bp.errorhandler(413)
def _upload_grande(erro):
    flash("O documento ultrapassa o limite de upload. Envie um arquivo menor.")
    return redirect(url_for("nao_precificado.upload"))


def _tabelas_disponiveis():
    tabelas = []
    for cliente in sorted(clientes_disponiveis()):
        itens, vigencia = carregar_tabela(cliente)
        if not itens:
            continue
        tabelas.append({
            "cliente": cliente,
            "vigencia": vigencia,
            "itens": len(itens),
        })
    return tabelas


def _erro(mensagem, status=422):
    flash(mensagem)
    return render_template(
        "comparador/nao_precificado_upload.html",
        csrf_token=session.get("nao_precificado_csrf", ""),
        tabelas=_tabelas_disponiveis(),
        selecionada=request.form.get("tabela", ""),
    ), status


def _dados():
    file_id = request.args.get("id", "")
    if file_id != session.get("comparador_nao_precificado") or not _RX_ID.fullmatch(file_id):
        return None
    caminho = os.path.join(SESSION_TMP_DIR, file_id)
    if not os.path.exists(caminho):
        return None
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except (OSError, ValueError):
        return None


@nao_precificado_bp.get("/documento-nao-precificado")
def upload():
    if "nao_precificado_csrf" not in session:
        session["nao_precificado_csrf"] = secrets.token_urlsafe(32)
    return render_template(
        "comparador/nao_precificado_upload.html",
        csrf_token=session["nao_precificado_csrf"],
        tabelas=_tabelas_disponiveis(),
        selecionada="",
    )


@nao_precificado_bp.get("/documento-nao-precificado/modelo.<formato>")
def modelo(formato):
    if formato != "xlsx":
        abort(404)
    nome = "modelo_documento_nao_precificado.xlsx"
    return send_file(
        Path(_HERE) / "modelos" / nome,
        as_attachment=True, download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@nao_precificado_bp.post("/documento-nao-precificado/processar")
def processar():
    token = session.get("nao_precificado_csrf", "")
    recebido = request.form.get("_csrf", "")
    if not token or not secrets.compare_digest(token.encode("utf-8"), recebido.encode("utf-8")):
        return _erro("Atualize a página e tente novamente: validação da sessão falhou.", 400)

    cliente = request.form.get("tabela", "").strip().upper()
    if cliente not in clientes_disponiveis():
        return _erro("Escolha a tabela de preços do cliente.")

    arquivo = request.files.get("documento")
    if not arquivo or not arquivo.filename:
        return _erro("Selecione o documento sem preço.")
    if not arquivo.filename.lower().endswith(_FORMATOS):
        return _erro("O documento deve ser um PDF ou uma folha Excel (.xlsx).")

    try:
        documento = extrair_documento_nao_precificado(arquivo.read(), arquivo.filename)
    except ValueError as erro:
        return _erro(str(erro))

    itens_tabela, vigencia = carregar_tabela(cliente)
    if not itens_tabela:
        return _erro(f"A tabela do cliente {cliente} não tem itens.")

    try:
        base = carregar_base_krona()
        indice = preparar_indice(itens_tabela, base)
        registros = comparar_documento_tabela(documento["itens"], indice, base)
    except ValueError as erro:
        return _erro(str(erro))
    except Exception as erro:
        return _erro(f"Não foi possível comparar o documento com a tabela: {erro}", 500)

    dados = {
        "cliente": cliente,
        "vigencia": vigencia,
        "nome_arquivo": documento["nome_arquivo"],
        "layout": documento["layout"],
        "numero": documento["numero"],
        "cliente_documento": documento["cliente"],
        "registros": registros,
        "stats": resumo(registros),
        "tabela_itens": len(itens_tabela),
    }
    for registro in registros:
        for chave, valor in registro.items():
            if isinstance(valor, float) and valor != valor:
                registro[chave] = None

    file_id = f"sess_nao_precificado_{uuid.uuid4().hex}.json"
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=SESSION_TMP_DIR, suffix=".tmp", delete=False,
        ) as saida:
            temporario = Path(saida.name)
            json.dump(dados, saida, ensure_ascii=False, allow_nan=False)
        os.replace(temporario, os.path.join(SESSION_TMP_DIR, file_id))
    except OSError:
        return _erro("Não foi possível guardar o resultado. Tente novamente.", 503)
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)

    session["comparador_nao_precificado"] = file_id
    return redirect(url_for("nao_precificado.resultado", id=file_id), code=303)


@nao_precificado_bp.get("/documento-nao-precificado/resultado")
def resultado():
    dados = _dados()
    if not dados:
        flash("Comparação indisponível ou sessão expirada. Envie o documento novamente.")
        return redirect(url_for("nao_precificado.upload"))
    return render_template(
        "comparador/nao_precificado_resultado.html",
        dados=dados, registros=dados["registros"], stats=dados["stats"],
        file_id=request.args["id"],
    )


@nao_precificado_bp.get("/documento-nao-precificado/download")
def download():
    dados = _dados()
    if not dados:
        flash("Comparação indisponível ou sessão expirada. Envie o documento novamente.")
        return redirect(url_for("nao_precificado.upload"))

    df = pd.DataFrame(dados["registros"]).rename(columns={
        "CODIGO_CLIENTE": "CODIGO CLIENTE",
        "CODIGO_KRONA": "CODIGO KRONA",
        "DESCRICAO": "DESCRICAO",
        "DESCRICAO_TABELA": "DESCRICAO TABELA",
        "QUANTIDADE": "QUANTIDADE",
        "UNIDADE": "UNIDADE",
        "PRECO_TABELA": "PRECO TABELA",
        "TOTAL": "TOTAL",
        "PRECO_DOCUMENTO": "PRECO DOCUMENTO",
        "STATUS": "STATUS",
        "VIA": "VIA",
        "OBS": "OBS",
    })[_COLUNAS]

    saida = BytesIO()
    with pd.ExcelWriter(
        saida, engine="xlsxwriter",
        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
    ) as writer:
        df.to_excel(writer, index=False, sheet_name="comparacao")
        livro = writer.book
        planilha = writer.sheets["comparacao"]
        moeda = livro.add_format({"num_format": "0.00"})
        planilha.freeze_panes(1, 0)
        planilha.set_column("A:A", 16)
        planilha.set_column("B:B", 14)
        planilha.set_column("C:D", 46)
        planilha.set_column("E:E", 12, livro.add_format({"num_format": "0.###"}))
        planilha.set_column("F:F", 10)
        planilha.set_column("G:H", 14, moeda)
        planilha.set_column("I:I", 16, moeda)
        planilha.set_column("J:K", 16)
        planilha.set_column("L:L", 52)

    saida.seek(0)
    nome = f"comparacao_{dados['cliente'].lower()}.xlsx"
    return send_file(
        saida, as_attachment=True, download_name=nome,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@nao_precificado_bp.get("/documento-nao-precificado/pdf")
def download_pdf():
    dados = _dados()
    if not dados:
        flash("Comparação indisponível ou sessão expirada. Envie o documento novamente.")
        return redirect(url_for("nao_precificado.upload"))

    try:
        from pdf_orcamento_nao_precificado import gerar_pdf
        pdf = gerar_pdf(dados)
    except Exception as erro:
        flash(f"Não foi possível gerar o PDF do orçamento: {erro}")
        return redirect(url_for("nao_precificado.resultado", id=request.args["id"]))

    nome = f"orcamento_{dados['cliente'].lower()}.pdf"
    return send_file(BytesIO(pdf), as_attachment=True, download_name=nome,
                     mimetype="application/pdf")
