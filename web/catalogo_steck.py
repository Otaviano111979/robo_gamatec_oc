"""
catalogo_steck.py — Blueprint Flask do Catálogo Steck/Schneider
Integra ao launcher Vortex em app_web.py com:

    from catalogo_steck import catalogo_bp, init_catalogo
    init_catalogo(app)
    app.register_blueprint(catalogo_bp)

Acesso: http://localhost:5000/catalogo/steck/
"""

from flask import (
    Blueprint, render_template, render_template_string, request, redirect,
    url_for, session, send_file, flash, jsonify, g
)
from pathlib import Path
import os
import sqlite3
import re
import io
import math
import pandas as pd
from rapidfuzz import fuzz
from jinja2 import TemplateNotFound

# ── Blueprint ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

catalogo_bp = Blueprint(
    "catalogo_steck",
    __name__,
    url_prefix="/catalogo/steck",
    template_folder=os.path.join(_HERE, "templates", "steck"),
    static_folder=os.path.join(_HERE, "static", "steck"),
)

# ── Banco de dados ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent      # C:\robo_gamatec_oc\

def _db_path(empresa_id: str = "steck") -> Path:
    """Cada empresa tem seu próprio banco. Default = steck."""
    p = BASE_DIR / "instance" / f"catalogo_{empresa_id}.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def get_conn(empresa_id: str = "steck"):
    conn = sqlite3.connect(_db_path(empresa_id))
    conn.row_factory = sqlite3.Row
    return conn

def init_catalogo(app):
    """Chame uma vez em app_web.py depois de criar o app Flask."""
    _ensure_db("steck")

def _ensure_db(empresa_id: str = "steck"):
    conn = get_conn(empresa_id)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_raw   TEXT NOT NULL,
        produto_norm  TEXT NOT NULL,
        produto_digits TEXT,
        produto_prefix TEXT,
        descricao     TEXT,
        lote_minimo   TEXT,
        clas_fiscal   TEXT,
        cst           TEXT,
        icms          REAL,
        ipi           REAL,
        ean13         TEXT
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pn  ON produtos(produto_norm);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pd  ON produtos(produto_digits);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_desc ON produtos(descricao);")
    conn.commit()
    conn.close()

def _empresa_id() -> str:
    """Pega empresa_id da sessão do Vortex (ou 'steck' como fallback)."""
    return session.get("empresa_id", "steck")


def _render_steck(template_name: str, **context):
    """
    Renderiza template do catálogo.
    Se os arquivos HTML do módulo estiverem ausentes, evita erro 500
    e exibe uma página de aviso para o operador.
    """
    try:
        return render_template(template_name, **context)
    except TemplateNotFound:
        return render_template_string(
            """
            <!doctype html>
            <html lang="pt-BR">
            <head>
              <meta charset="utf-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1" />
              <title>Catálogo Steck indisponível</title>
              <style>
                body { font-family: Arial, sans-serif; background: #0b1020; color: #eaf0ff; margin: 0; padding: 24px; }
                .card { max-width: 760px; margin: 0 auto; background: #111a2e; border: 1px solid #28406f; border-radius: 12px; padding: 18px; }
                h1 { margin-top: 0; font-size: 22px; }
                p { line-height: 1.45; }
                code { background: #0d1630; padding: 2px 6px; border-radius: 6px; }
                a { color: #6ecbff; text-decoration: none; }
              </style>
            </head>
            <body>
              <div class="card">
                <h1>Modulo Catalogo Eletrico temporariamente indisponivel</h1>
                <p>Os templates HTML do modulo nao foram encontrados no servidor.</p>
                <p>Template solicitado: <code>{{ template_name }}</code></p>
                <p>Restaure os arquivos do catalogo em <code>web/templates/steck/</code> (e, se houver, em <code>web/static/steck/</code>).</p>
                <p><a href="/launcher">Voltar ao launcher</a></p>
              </div>
            </body>
            </html>
            """,
            template_name=template_name,
        )

# ── Utilitários ───────────────────────────────────────────────────────────────
def norm_query(q: str) -> str:
    return (q or "").strip().upper()

def digits_only(q: str) -> str:
    return "".join(re.findall(r"\d+", q or ""))

def parse_number_ptbr(x):
    if x is None:
        return None
    s = str(x).strip().replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def adjust_to_multiple(qty: float, lot: float) -> float:
    if qty is None:
        return None
    if lot is None or lot <= 0:
        return qty
    return math.ceil(qty / lot) * lot

def format_qty(q: float) -> str:
    if q is None:
        return ""
    if abs(q - round(q)) < 1e-9:
        return str(int(round(q)))
    return f"{q:.3f}".rstrip("0").rstrip(".")

# ── Fuzzy match ───────────────────────────────────────────────────────────────
def _score_desc(query: str, target: str) -> float:
    if not query or not target:
        return 0.0
    return float(fuzz.token_set_ratio(query.strip().upper(), target.strip().upper()))

def best_by_description(query: str, candidates):
    best, best_score = None, 0.0
    for row in candidates:
        s = _score_desc(query, row["descricao"])
        if s > best_score:
            best_score = s
            best = row
    return best, best_score

# ── Busca ─────────────────────────────────────────────────────────────────────
def ranked_search(conn, q: str):
    qn = norm_query(q)
    cur = conn.cursor()

    def run(where, params):
        cur.execute(f"""
            SELECT id, produto_raw, descricao, ean13, lote_minimo
            FROM produtos WHERE {where} LIMIT 50
        """, params)
        return cur.fetchall()

    looks_like_code = (" " not in qn) and (
        qn.isdigit() or re.match(r"^[A-Z]{1,4}\d+[A-Z0-9]*$", qn)
    )

    if looks_like_code:
        rows = run("produto_norm = ?", (qn,))
        if rows: return rows
        rows = run("produto_norm LIKE ?", (qn + "%",))
        if rows: return rows
        if qn.isdigit():
            rows = run("produto_digits = ?", (qn,))
            if rows: return rows
            rows = run("produto_digits LIKE ?", (qn + "%",))
            if rows: return rows

    raw_tokens = re.findall(r"[A-Z0-9\+]+", qn)
    stop = {"DE", "DA", "DO", "PARA", "COM", "SEM", "EM", "NO", "NA", "E"}
    curva_letter = None
    m = re.search(r"\bCURVA\s*([ABCD])\b", qn)
    if m:
        curva_letter = m.group(1)

    tokens = [t for t in raw_tokens if t not in stop and len(t) >= 2]

    where_parts, params = [], []
    if curva_letter:
        where_parts.append("descricao LIKE ?")
        params.append(f"%CURVA {curva_letter}%")
        tokens = [t for t in tokens if t != "CURVA"]

    if not tokens and not curva_letter:
        return []

    for t in tokens:
        where_parts.append("descricao LIKE ?")
        params.append(f"%{t}%")

    rows = run(" AND ".join(where_parts), tuple(params))
    if rows: return rows

    # fallback OR
    where_or, params_or = [], []
    if curva_letter:
        where_or.append("descricao LIKE ?")
        params_or.append(f"%CURVA {curva_letter}%")
    for t in tokens:
        where_or.append("descricao LIKE ?")
        params_or.append(f"%{t}%")
    if not where_or:
        return []
    return run(" OR ".join(where_or), tuple(params_or))

def find_by_code_any(conn, code: str):
    code = norm_query(code)
    qd = digits_only(code)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, produto_raw, descricao, ean13, lote_minimo
        FROM produtos WHERE produto_norm = ? LIMIT 1
    """, (code,))
    row = cur.fetchone()
    if row: return row
    if qd:
        cur.execute("""
            SELECT id, produto_raw, descricao, ean13, lote_minimo
            FROM produtos WHERE produto_digits = ? LIMIT 50
        """, (qd,))
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0]
    return None

# ── Carrinho (chave de sessão isolada por módulo) ─────────────────────────────
_CART_KEY = "steck_cart"

def get_cart():
    return session.get(_CART_KEY, [])

def save_cart(cart):
    session[_CART_KEY] = cart

def cart_summary(cart):
    total_qtd = sum(
        (parse_number_ptbr(i.get("quantidade")) or 0) for i in cart
    )
    return {"total_itens": len(cart), "total_quantidade": format_qty(total_qtd)}

def cart_add_or_sum(codigo, descricao, lote_minimo, quantidade_str):
    cart = get_cart()
    lot = parse_number_ptbr(lote_minimo)
    qty = parse_number_ptbr(quantidade_str) or 1.0
    qty = adjust_to_multiple(qty, lot)

    for item in cart:
        if item["codigo"] == codigo:
            current = parse_number_ptbr(item.get("quantidade")) or 0.0
            item["quantidade"] = format_qty(adjust_to_multiple(current + qty, lot))
            item["lote_minimo"] = lote_minimo or item.get("lote_minimo", "")
            return cart

    cart.append({
        "codigo":      codigo,
        "descricao":   descricao,
        "lote_minimo": lote_minimo or "",
        "quantidade":  format_qty(qty),
    })
    return cart

# ── Import de lista ───────────────────────────────────────────────────────────
def _detect_columns(df):
    cols = set(df.columns)
    col_code = next((c for c in ["CODIGO","CÓDIGO","PRODUTO","ITEM","SKU"] if c in cols), None)
    col_desc = next((c for c in ["DESCRICAO","DESCRIÇÃO","DESC","ESPECIFICACAO","ESPECIFICAÇÃO"] if c in cols), None)
    col_qty  = next((c for c in ["QTDE","QUANTIDADE","QTD","QT"] if c in cols), None)
    return col_code, col_desc, col_qty

def import_list_to_review(df):
    col_code, col_desc, col_qty = _detect_columns(df)
    if not col_code and not col_desc:
        raise ValueError("Não achei coluna de CÓDIGO nem de DESCRIÇÃO na planilha.")

    conn = get_conn(_empresa_id())
    found, not_found = [], []

    for _, row in df.iterrows():
        raw_code = str(row.get(col_code) if col_code else "").strip()
        raw_desc = str(row.get(col_desc) if col_desc else "").strip()
        raw_qty  = str(row.get(col_qty)  if col_qty  else "").strip()

        if not raw_code and not raw_desc:
            continue

        matched = None
        if raw_code:
            matched = find_by_code_any(conn, raw_code)

        if not matched and raw_code:
            d = digits_only(raw_code)
            if d:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, produto_raw, descricao, ean13, lote_minimo
                    FROM produtos WHERE produto_digits = ? LIMIT 50
                """, (d,))
                cands = cur.fetchall()
                if cands and raw_desc:
                    best, score = best_by_description(raw_desc, cands)
                    if best and score >= 80:
                        matched = best

        if not matched and raw_desc:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, produto_raw, descricao, ean13, lote_minimo
                FROM produtos WHERE descricao LIKE ? LIMIT 50
            """, ("%" + norm_query(raw_desc) + "%",))
            cands = cur.fetchall()
            if cands:
                best, score = best_by_description(raw_desc, cands)
                if best and score >= 85:
                    matched = best

        if matched:
            found.append({
                "entrada_codigo":   raw_code,
                "entrada_descricao": raw_desc,
                "codigo":     matched["produto_raw"],
                "descricao":  matched["descricao"],
                "lote_minimo": matched["lote_minimo"] or "",
                "quantidade": raw_qty or "1",
            })
        else:
            not_found.append({
                "entrada_codigo":    raw_code,
                "entrada_descricao": raw_desc,
                "quantidade": raw_qty or "1",
            })

    conn.close()
    return found, not_found

# ── Rotas ─────────────────────────────────────────────────────────────────────
@catalogo_bp.get("/")
def index():
    return _render_steck("steck/index.html")

@catalogo_bp.get("/search")
def search():
    q = request.args.get("q", "").strip()
    cart = get_cart()
    summary = cart_summary(cart)
    results = []

    if q:
        conn = get_conn(_empresa_id())
        results = ranked_search(conn, q)
        conn.close()

    return _render_steck("steck/results.html", q=q, results=results,
                         cart=cart, summary=summary)

@catalogo_bp.post("/add")
def add():
    produto_raw  = request.form.get("produto_raw", "").strip()
    descricao    = request.form.get("descricao", "").strip()
    lote_minimo  = request.form.get("lote_minimo", "").strip()
    quantidade   = request.form.get("quantidade", "").strip()

    cart = cart_add_or_sum(produto_raw, descricao, lote_minimo, quantidade)
    save_cart(cart)

    is_ajax = (
        request.headers.get("X-Requested-With") == "fetch"
        or "application/json" in (request.headers.get("Accept") or "")
    )
    if is_ajax:
        return jsonify({"ok": True, "cart": cart, "summary": cart_summary(cart)})

    return redirect(request.referrer or url_for("catalogo_steck.index"))

@catalogo_bp.post("/cart/clear")
def cart_clear():
    save_cart([])
    is_ajax = (
        request.headers.get("X-Requested-With") == "fetch"
        or "application/json" in (request.headers.get("Accept") or "")
    )
    if is_ajax:
        return jsonify({"ok": True, "cart": [], "summary": cart_summary([])})
    return redirect(request.referrer or url_for("catalogo_steck.index"))

@catalogo_bp.get("/cart")
def cart():
    return _render_steck("steck/cart.html", cart=get_cart())

@catalogo_bp.get("/export/xlsx")
def export_xlsx():
    cart = get_cart()
    df = pd.DataFrame(cart, columns=["descricao", "codigo", "quantidade"])
    df.columns = ["DESCRIÇÃO", "CÓDIGO", "QUANTIDADE"]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="itens_steck")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="itens_steck.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@catalogo_bp.get("/import")
def import_page():
    return _render_steck("steck/import.html")

@catalogo_bp.post("/import")
def import_upload():
    if "file" not in request.files or not request.files["file"].filename:
        flash("Selecione um arquivo Excel.")
        return redirect(url_for("catalogo_steck.import_page"))

    df = pd.read_excel(request.files["file"])
    df.columns = [str(c).strip().upper() for c in df.columns]

    found, not_found = import_list_to_review(df)
    session["steck_review_found"]     = found
    session["steck_review_not_found"] = not_found

    return redirect(url_for("catalogo_steck.review_page"))

@catalogo_bp.get("/review")
def review_page():
    found     = session.get("steck_review_found", [])
    not_found = session.get("steck_review_not_found", [])
    return _render_steck("steck/review.html", found=found, not_found=not_found)

@catalogo_bp.post("/review/add_all")
def review_add_all():
    found = session.get("steck_review_found", [])
    cart = get_cart()
    for it in found:
        cart = cart_add_or_sum(it["codigo"], it["descricao"],
                               it["lote_minimo"], it["quantidade"])
    save_cart(cart)
    return redirect(url_for("catalogo_steck.search", q=""))

@catalogo_bp.get("/status")
def status():
    """Endpoint para o launcher monitorar se o módulo está ativo."""
    conn = get_conn(_empresa_id())
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM produtos")
    total = cur.fetchone()[0]
    conn.close()
    return jsonify({"modulo": "catalogo_steck", "produtos": total, "ok": True})
