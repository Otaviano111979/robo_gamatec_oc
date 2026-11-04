# -*- coding: utf-8 -*-
"""Historico persistente dos processos do comparador nao precificado.

Tabela aditiva no crm.db (nao altera tabelas existentes). Cada processo fica
guardado com os registros completos para receber depois o orcamento
precificado de volta e calcular o percentual de desconto.
"""
import json
import os
import sqlite3
from datetime import datetime

from config import PASTA_DADOS

CAMINHO_CRM = os.path.join(PASTA_DADOS, "crm.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS historico_comparador (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em    TEXT NOT NULL,
    cliente      TEXT NOT NULL,
    vigencia     TEXT,
    numero       TEXT,
    nome_arquivo TEXT,
    layout       TEXT,
    stats        TEXT,
    registros    TEXT NOT NULL,
    estado       TEXT NOT NULL DEFAULT 'aguardando_retorno',
    retorno      TEXT,
    retorno_em   TEXT
);
CREATE INDEX IF NOT EXISTS idx_hc_criado ON historico_comparador(criado_em);
"""

# colunas adicionadas depois da primeira publicação: aditivas, nunca destrutivas
_MIGRACOES = (
    ("retorno", "TEXT"),
    ("retorno_em", "TEXT"),
)


def _aplicar_migracoes(conn):
    colunas = {linha["name"]
               for linha in conn.execute("PRAGMA table_info(historico_comparador)")}
    for nome, tipo in _MIGRACOES:
        if nome not in colunas:
            conn.execute(f"ALTER TABLE historico_comparador ADD COLUMN {nome} {tipo}")

_ESTADOS = {
    "aguardando_retorno": "Aguardando retorno",
    "retorno_comparado": "Retorno comparado",
}


def conectar():
    conn = sqlite3.connect(CAMINHO_CRM)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _aplicar_migracoes(conn)
    return conn


def gravar_processo(dados):
    conn = conectar()
    try:
        cur = conn.execute(
            """INSERT INTO historico_comparador
               (criado_em, cliente, vigencia, numero, nome_arquivo, layout,
                stats, registros)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                dados.get("cliente") or "",
                dados.get("vigencia") or "",
                dados.get("numero") or "",
                dados.get("nome_arquivo") or "",
                dados.get("layout") or "",
                json.dumps(dados.get("stats") or {}, ensure_ascii=False),
                json.dumps(dados.get("registros") or [], ensure_ascii=False),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_processos(limite=100):
    conn = conectar()
    try:
        linhas = conn.execute(
            """SELECT id, criado_em, cliente, numero, nome_arquivo, stats, estado
               FROM historico_comparador
               ORDER BY id DESC LIMIT ?""",
            (limite,),
        ).fetchall()
        saida = []
        for linha in linhas:
            try:
                stats = json.loads(linha["stats"] or "{}")
            except ValueError:
                stats = {}
            saida.append({
                "id": linha["id"],
                "criado_em": linha["criado_em"],
                "cliente": linha["cliente"],
                "numero": linha["numero"] or "",
                "nome_arquivo": linha["nome_arquivo"] or "",
                "estado": linha["estado"],
                "estado_label": _ESTADOS.get(linha["estado"], linha["estado"]),
                "itens": stats.get("total") or 0,
            })
        return saida
    finally:
        conn.close()


def carregar_processo(pid):
    conn = conectar()
    try:
        linha = conn.execute(
            "SELECT * FROM historico_comparador WHERE id = ?", (pid,)
        ).fetchone()
        if not linha:
            return None
        return {
            "id": linha["id"],
            "criado_em": linha["criado_em"],
            "cliente": linha["cliente"],
            "vigencia": linha["vigencia"] or "",
            "numero": linha["numero"] or "",
            "nome_arquivo": linha["nome_arquivo"] or "",
            "layout": linha["layout"] or "",
            "stats": json.loads(linha["stats"] or "{}"),
            "registros": json.loads(linha["registros"] or "[]"),
            "estado": linha["estado"],
            "retorno": json.loads(linha["retorno"]) if linha["retorno"] else None,
            "retorno_em": linha["retorno_em"] or "",
        }
    finally:
        conn.close()


def gravar_retorno(pid, retorno):
    """Guarda o retorno precificado no processo e marca-o como comparado."""
    conn = conectar()
    try:
        cur = conn.execute(
            """UPDATE historico_comparador
               SET estado = 'retorno_comparado', retorno = ?, retorno_em = ?
               WHERE id = ?""",
            (
                json.dumps(retorno, ensure_ascii=False, allow_nan=False),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                pid,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
