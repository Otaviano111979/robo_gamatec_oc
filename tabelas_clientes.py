# -*- coding: utf-8 -*-
"""Tabelas de preco por cliente (aditivo ao crm.db).

Guarda, por cliente e vigencia, os itens contratados (codigo Krona, codigo do
cliente quando existe, descricao, unidade e preco). Nada aqui altera as tabelas
existentes do CRM.

CLI:
    python tabelas_clientes.py importar CITY "dados/TABELA CITY - 2 SEM - 2026.xlsx"
    python tabelas_clientes.py listar
    python tabelas_clientes.py identificar <ficheiro.pdf>
"""
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime

import pandas as pd

from config import PASTA_DADOS

CAMINHO_CRM = os.path.join(PASTA_DADOS, "crm.db")

# Layout de cada tabela de cliente. `linha_inicio` e o indice (0-based) da
# primeira linha de dados; as colunas sao posicoes fixas nessa linha em diante.
LAYOUTS = {
    "CITY": {
        "nome": "City Inc",
        "sheet": 0,
        "linha_inicio": 2,
        "col": {"codigo_krona": 3, "codigo_cliente": 2, "descricao": 4,
                "unidade": 5, "preco": 7},
        "vigencia": "2 SEM - 2026",
    },
    "EBM": {
        "nome": "EBM Incorporacoes",
        "sheet": 0,
        "linha_inicio": 3,
        "col": {"codigo_krona": 0, "descricao": 3, "unidade": 2, "preco": 9},
        "vigencia": "1 SEM - 2026",
    },
    "VEGA": {
        "nome": "Grupo Vega",
        "sheet": "Construtora Grande",
        "linha_inicio": 3,
        "col": {"codigo_krona": 0, "descricao": 1, "familia": 2,
                "linha": 3, "preco": 4},
        "vigencia": "2 SEM - 2026",
    },
    "CONSTRUAPP": {
        "nome": "Contruapp",
        "sheet": 0,
        "linha_inicio": 5,
        "col": {"codigo_krona": 0, "descricao": 1, "preco": 5},
        "vigencia": "2 SEM - 2026",
    },
    "TERRAL": {
        "nome": "Terral",
        "sheet": "Planilha4",
        "linha_inicio": 3,
        "exigir_codigo": True,
        "col": {"codigo_krona": 0, "unidade": 2, "descricao": 3, "preco": 9},
        "vigencia": "2 SEM - 2026",
    },
}

# Identificacao do cliente pelo texto da OC. Dominios primeiro; termos so como
# reforco (evitam falsos positivos como "SENSIA CITY GALLERIA" do MRV).
IDENTIDADES = {
    "CITY": {"dominios": ["cityinc.com.br"],
             "termos": ["SPE RESIDENCIAL CITY", "CITY INC"]},
    "EBM": {"dominios": ["ebm.com.br"],
            "termos": ["BRASIL INCORPORACAO", "BRASIL INCORPORAÇÃO"]},
    "VEGA": {"dominios": ["grupovega.com.br"], "termos": ["GRUPO VEGA"]},
    "CONSTRUAPP": {"dominios": [], "termos": ["CONTRUAPP", "CONSTRUAPP"]},
    # 13 SPEs do comunicado de compras da Terral (25/02/2026); todas usam a
    # mesma tabela. O CNPJ e o sinal mais forte quando o e-mail nao aparece.
    "TERRAL": {
        "dominios": ["terral.com.br"],
        "termos": ["TERRAL", "SPE TSA"],
        "cnpjs": [
            "13.070.562/0001-53", "36.728.929/0001-89", "43.682.805/0001-75",
            "23.347.748/0001-60", "40.461.517/0001-00", "40.830.478/0001-63",
            "40.370.325/0001-80", "30.133.519/0001-09", "35.072.756/0001-20",
            "40.213.294/0001-54", "42.824.872/0001-14", "40.458.900/0001-00",
            "53.462.257/0001-21",
        ],
    },
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clientes_tabelas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente      TEXT NOT NULL,
    nome         TEXT NOT NULL,
    vigencia     TEXT NOT NULL,
    vigencia_ordem INTEGER NOT NULL DEFAULT 0,
    arquivo      TEXT,
    importado_em TEXT NOT NULL,
    UNIQUE(cliente, vigencia)
);
CREATE TABLE IF NOT EXISTS clientes_tabela_itens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tabela_id      INTEGER NOT NULL REFERENCES clientes_tabelas(id) ON DELETE CASCADE,
    codigo_krona   TEXT,
    codigo_cliente TEXT,
    descricao      TEXT NOT NULL,
    unidade        TEXT,
    preco          REAL,
    familia        TEXT,
    linha          TEXT
);
CREATE INDEX IF NOT EXISTS idx_cti_tabela ON clientes_tabela_itens(tabela_id);
"""


def conectar(caminho=None):
    conn = sqlite3.connect(caminho or CAMINHO_CRM)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def _texto(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def _codigo(valor):
    txt = _texto(valor)
    if not txt:
        return ""
    try:
        return str(int(float(txt.replace(",", "."))))
    except ValueError:
        return txt


def _preco(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip().replace("R$", "").replace(" ", "")
    if not txt:
        return None
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _ordem_vigencia(vigencia):
    m = re.search(r"(\d)\s*SEM.*?(\d{2,4})", vigencia.upper())
    if not m:
        return 0
    ano = int(m.group(2))
    if ano < 100:
        ano += 2000
    return ano * 10 + int(m.group(1))


def importar(cliente, caminho, vigencia=None, conn=None):
    cliente = cliente.strip().upper()
    layout = LAYOUTS.get(cliente)
    if not layout:
        raise ValueError(f"Cliente sem layout de tabela: {cliente}. "
                         f"Disponiveis: {', '.join(sorted(LAYOUTS))}")
    if not os.path.exists(caminho):
        raise FileNotFoundError(caminho)
    vigencia = vigencia or layout["vigencia"]

    bruto = pd.read_excel(caminho, sheet_name=layout["sheet"], header=None)
    dados = bruto.iloc[layout["linha_inicio"]:]
    col = layout["col"]

    def cel(row, chave):
        idx = col.get(chave)
        return row[idx] if idx is not None and idx < len(row) else None

    itens = []
    for _, row in dados.iterrows():
        descricao = _texto(cel(row, "descricao"))
        preco = _preco(cel(row, "preco"))
        codigo = _codigo(cel(row, "codigo_krona"))
        if not descricao or preco is None or preco <= 0:
            continue
        if layout.get("exigir_codigo") and (not codigo or codigo == "-"):
            continue
        itens.append({
            "codigo_krona": codigo,
            "codigo_cliente": _codigo(cel(row, "codigo_cliente")),
            "descricao": descricao,
            "unidade": _texto(cel(row, "unidade")).upper(),
            "preco": preco,
            "familia": _texto(cel(row, "familia")),
            "linha": _texto(cel(row, "linha")),
        })
    if not itens:
        raise ValueError(f"Nenhum item valido lido de {caminho}")

    proprio = conn is None
    conn = conn or conectar()
    try:
        with conn:
            conn.execute(
                """INSERT INTO clientes_tabelas
                   (cliente, nome, vigencia, vigencia_ordem, arquivo, importado_em)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(cliente, vigencia) DO UPDATE SET
                     nome=excluded.nome, vigencia_ordem=excluded.vigencia_ordem,
                     arquivo=excluded.arquivo, importado_em=excluded.importado_em""",
                (cliente, layout["nome"], vigencia, _ordem_vigencia(vigencia),
                 os.path.basename(caminho), datetime.now().isoformat(timespec="seconds")),
            )
            tabela_id = conn.execute(
                "SELECT id FROM clientes_tabelas WHERE cliente=? AND vigencia=?",
                (cliente, vigencia)).fetchone()["id"]
            conn.execute("DELETE FROM clientes_tabela_itens WHERE tabela_id=?", (tabela_id,))
            conn.executemany(
                """INSERT INTO clientes_tabela_itens
                   (tabela_id, codigo_krona, codigo_cliente, descricao, unidade,
                    preco, familia, linha)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [(tabela_id, i["codigo_krona"], i["codigo_cliente"], i["descricao"],
                  i["unidade"], i["preco"], i["familia"], i["linha"]) for i in itens],
            )
    finally:
        if proprio:
            conn.close()

    return {"cliente": cliente, "vigencia": vigencia, "itens": len(itens)}


def carregar_tabela(cliente, conn=None):
    """Itens da vigencia mais recente do cliente, ou lista vazia."""
    propria = conn is None
    conn = conn or conectar()
    try:
        linha = conn.execute(
            """SELECT id, vigencia FROM clientes_tabelas WHERE cliente=?
               ORDER BY vigencia_ordem DESC, id DESC LIMIT 1""",
            (cliente.strip().upper(),)).fetchone()
        if not linha:
            return [], None
        itens = [dict(r) for r in conn.execute(
            """SELECT codigo_krona, codigo_cliente, descricao, unidade, preco,
                      familia, linha
               FROM clientes_tabela_itens WHERE tabela_id=? ORDER BY id""",
            (linha["id"],))]
        return itens, linha["vigencia"]
    finally:
        if propria:
            conn.close()


def clientes_disponiveis(conn=None):
    propria = conn is None
    conn = conn or conectar()
    try:
        return {r["cliente"] for r in conn.execute(
            "SELECT DISTINCT cliente FROM clientes_tabelas")}
    finally:
        if propria:
            conn.close()


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def identificar_cliente(texto, conn=None):
    """Cliente com tabela importada reconhecido no texto da OC (ou None)."""
    if not texto:
        return None
    norm = _normalizar(texto)
    digitos = re.sub(r"\D", "", norm)
    emails = " ".join(re.findall(r"@([\w.-]+)", norm.lower()))
    disponiveis = clientes_disponiveis(conn)
    if not disponiveis:
        return None
    for cliente in sorted(disponiveis):
        ident = IDENTIDADES.get(cliente, {})
        for cnpj in ident.get("cnpjs", []):
            if re.sub(r"\D", "", cnpj) in digitos:
                return cliente
    for cliente in sorted(disponiveis):
        ident = IDENTIDADES.get(cliente, {})
        for dominio in ident.get("dominios", []):
            if dominio.upper() in emails.upper():
                return cliente
    for cliente in sorted(disponiveis):
        ident = IDENTIDADES.get(cliente, {})
        for termo in ident.get("termos", []):
            if _normalizar(termo) in norm:
                return cliente
    return None


def identificar_cliente_arquivo(caminho):
    try:
        import fitz
        doc = fitz.open(caminho)
        texto = "\n".join(doc[i].get_text() for i in range(min(3, doc.page_count)))
        doc.close()
    except Exception:
        return None
    return identificar_cliente(texto)


def _main(argv):
    if len(argv) < 2:
        print(__doc__)
        return
    acao = argv[1]
    if acao == "importar":
        if len(argv) < 4:
            print('Uso: python tabelas_clientes.py importar CITY "ficheiro.xlsx" [vigencia]')
            return
        print(importar(argv[2], argv[3], argv[4] if len(argv) > 4 else None))
    elif acao == "listar":
        conn = conectar()
        for r in conn.execute(
                """SELECT t.cliente, t.nome, t.vigencia, t.importado_em,
                          (SELECT COUNT(*) FROM clientes_tabela_itens i
                            WHERE i.tabela_id=t.id) AS itens
                   FROM clientes_tabelas t ORDER BY t.cliente, t.vigencia_ordem DESC"""):
            print(f"{r['cliente']:<11} {r['vigencia']:<12} {r['itens']:>4} itens  "
                  f"importado {r['importado_em']}  ({r['nome']})")
        conn.close()
    elif acao == "identificar" and len(argv) >= 3:
        print(identificar_cliente_arquivo(argv[2]))
    else:
        print(__doc__)


if __name__ == "__main__":
    _main(sys.argv)
