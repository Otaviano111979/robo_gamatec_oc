"""
catalogo_steck.py — Blueprint Flask do Catálogo Steck/Schneider
Integra ao launcher Vortex em app_web.py com:

    from catalogo_steck import catalogo_bp, init_catalogo
    init_catalogo(app)
    app.register_blueprint(catalogo_bp)

Acesso: http://localhost:5000/catalogo/steck/
"""

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, send_file, flash, jsonify, g
)
from pathlib import Path
import os
import json
import sqlite3
import re
import io
import math
import unicodedata
import pandas as pd
try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

# ── Cache ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

# Cache para acelerar a revisão de importação (evita repetir fuzzy matching)
STECK_REVIEW_CACHE = {}

# Pasta server-side para dados de sessão (evita cookie too large)
SESSION_TMP_DIR = os.path.normpath(os.path.join(_HERE, "..", "flask_sessions"))
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

# ── Utilitários ───────────────────────────────────────────────────────────────
def norm_query(q: str) -> str:
    return (q or "").strip().upper()

def digits_only(q: str) -> str:
    return "".join(re.findall(r"\d+", q or ""))

def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s or "") if unicodedata.category(ch) != "Mn")

def normalize_code(code: str) -> str:
    s = norm_query(code)
    s = _strip_accents(s)
    s = re.sub(r"[\s\.\-/_\\]+", "", s)
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s

def _safe_cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none") else s

def parse_number_ptbr(x):
    if x is None:
        return None
    s = str(x).strip().replace(" ", "")
    if s.lower() in ("", "nan", "none", "sim", "nao", "não", "-"):
        return None
    # Tenta float direto (ex: "6.0", "4", "12")
    try:
        v = float(s.replace(",", "."))
        return v if v > 0 else None
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
    q = query.strip().upper()
    t = target.strip().upper()
    if fuzz:
        return float(fuzz.token_set_ratio(q, t))
    qt = set(re.findall(r"[A-Z0-9]+", q))
    tt = set(re.findall(r"[A-Z0-9]+", t))
    if not qt or not tt:
        return 0.0
    return 100.0 * (len(qt & tt) / max(len(qt), len(tt)))

def best_by_description(query: str, candidates):
    best, best_score = None, 0.0
    for row in candidates:
        s = _score_desc(query, row["descricao"])
        if s > best_score:
            best_score = s
            best = row
    return best, best_score

# ── Busca ─────────────────────────────────────────────────────────────────────
def ranked_search(conn, q: str, page: int = 1, per_page: int = 50):
    qn = norm_query(q)
    q_code = normalize_code(qn)
    cur = conn.cursor()

    page = max(1, int(page or 1))
    per_page = max(1, min(int(per_page or 50), 100))
    offset = (page - 1) * per_page

    def run(where, params, limit, offset):
        cur.execute(f"""
            SELECT id, produto_raw, descricao, ean13, lote_minimo
            FROM produtos WHERE {where}
            LIMIT ? OFFSET ?
        """, tuple(params) + (limit, offset))
        return cur.fetchall()

    def count(where, params):
        cur.execute(f"SELECT COUNT(*) FROM produtos WHERE {where}", params)
        return int(cur.fetchone()[0])

    looks_like_code = (" " not in qn) and (
        q_code.isdigit() or re.match(r"^[A-Z]{1,4}\d+[A-Z0-9]*$", q_code)
    )

    if looks_like_code:
        where = "produto_norm = ?"
        rows = run(where, (q_code,), 1, 0)
        if rows:
            return {"rows": rows, "total": len(rows), "page": 1, "pages": 1}

        where = "produto_norm LIKE ?"
        prefix = q_code + "%"
        total = count(where, (prefix,))
        rows = run(where, (prefix,), per_page, offset)
        if rows:
            return {"rows": rows, "total": total, "page": page, "pages": max(1, math.ceil(total / per_page))}

        if q_code.isdigit():
            where = "produto_digits = ?"
            rows = run(where, (q_code,), 1, 0)
            if rows:
                return {"rows": rows, "total": len(rows), "page": 1, "pages": 1}

            where = "produto_digits LIKE ?"
            prefix = q_code + "%"
            total = count(where, (prefix,))
            rows = run(where, (prefix,), per_page, offset)
            if rows:
                return {"rows": rows, "total": total, "page": page, "pages": max(1, math.ceil(total / per_page))}

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
        return {"rows": [], "total": 0, "page": 1, "pages": 1}

    for t in tokens:
        where_parts.append("descricao LIKE ?")
        params.append(f"%{t}%")

    where = " AND ".join(where_parts)
    total = count(where, tuple(params))
    rows = run(where, tuple(params), per_page, offset)
    if rows:
        return {"rows": rows, "total": total, "page": page, "pages": max(1, math.ceil(total / per_page))}

    # fallback OR
    where_or, params_or = [], []
    if curva_letter:
        where_or.append("descricao LIKE ?")
        params_or.append(f"%CURVA {curva_letter}%")
    for t in tokens:
        where_or.append("descricao LIKE ?")
        params_or.append(f"%{t}%")
    if not where_or:
        return {"rows": [], "total": 0, "page": 1, "pages": 1}
    where = " OR ".join(where_or)
    total = count(where, tuple(params_or))
    return {"rows": run(where, tuple(params_or), per_page, offset), "total": total, "page": page, "pages": max(1, math.ceil(total / per_page))}

def find_by_code_any(conn, code: str):
    code = normalize_code(code)
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

# ── Carrinho (armazenado em flask_sessions/carrinho_steck_{user}.json) ────────
# Chaves legadas — mantidas apenas para limpar o cookie, não são mais lidas
_CART_KEY        = "steck_cart_id"
_CART_LEGACY_KEY = "steck_cart"

def _cart_user() -> str:
    """Retorna o usuário logado, ou 'anonimo' como fallback seguro."""
    return session.get("user") or session.get("username") or "anonimo"

def _cart_path() -> str:
    """Caminho do JSON do carrinho — derivado do usuário, nunca do cookie."""
    return os.path.join(SESSION_TMP_DIR, f"carrinho_steck_{_cart_user()}.json")

def obter_carrinho() -> list:
    """Lê o carrinho do arquivo JSON no servidor. Ignora cookies e tmp_session/."""
    path = _cart_path()
    print(f"[CART] obter_carrinho user={_cart_user()!r} path={path} existe={os.path.exists(path)}")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"[CART] formato invalido no arquivo ({type(data)}), ignorando")
            return []
        print(f"[CART] lidos {len(data)} itens")
        return data
    except Exception as e:
        print(f"[CART] erro ao ler arquivo: {e}")
        return []

def _salvar_carrinho(cart: list):
    path = _cart_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cart if isinstance(cart, list) else [], f, ensure_ascii=False)
    # Verifica gravação
    size = os.path.getsize(path)
    print(f"[CART] gravado {len(cart)} itens em {path} ({size}b)")

def adicionar_ao_carrinho(codigo, descricao, lote_minimo, quantidade_str) -> list:
    """Adiciona ou soma item no carrinho e persiste no arquivo JSON."""
    if not codigo:
        return obter_carrinho()
    cart = obter_carrinho()
    lot = parse_number_ptbr(lote_minimo)
    qty = parse_number_ptbr(quantidade_str) or 1.0
    qty = adjust_to_multiple(qty, lot)
    for item in cart:
        if not isinstance(item, dict):
            continue
        if item.get("codigo") == codigo:
            current = parse_number_ptbr(item.get("quantidade")) or 0.0
            item["quantidade"] = format_qty(adjust_to_multiple(current + qty, lot))
            item["lote_minimo"] = lote_minimo or item.get("lote_minimo", "")
            _salvar_carrinho(cart)
            return cart
    cart.append({
        "codigo":      codigo,
        "descricao":   descricao,
        "lote_minimo": lote_minimo or "",
        "quantidade":  format_qty(qty),
    })
    _salvar_carrinho(cart)
    return cart

def limpar_carrinho():
    """Zera o carrinho gravando lista vazia (não deleta o arquivo)."""
    _salvar_carrinho([])

# Aliases de compatibilidade — rotas existentes não precisam mudar
def get_cart() -> list:
    """Limpa chaves legadas do cookie e retorna o carrinho do disco."""
    session.pop(_CART_KEY, None)
    session.pop(_CART_LEGACY_KEY, None)
    return obter_carrinho()

def save_cart(cart):
    _salvar_carrinho(cart if isinstance(cart, list) else [])
    session.pop(_CART_KEY, None)
    session.pop(_CART_LEGACY_KEY, None)

def cart_summary(cart):
    total_qtd = sum(
        (parse_number_ptbr(i.get("quantidade")) or 0) for i in (cart or [])
    )
    return {"total_itens": len(cart or []), "total_quantidade": format_qty(total_qtd)}

def cart_add_or_sum(codigo, descricao, lote_minimo, quantidade_str):
    """Alias de compatibilidade — lê, modifica e retorna sem salvar (save_cart separa)."""
    cart = obter_carrinho()
    if not isinstance(cart, list):
        cart = []
    lot = parse_number_ptbr(lote_minimo)
    qty = parse_number_ptbr(quantidade_str) or 1.0
    qty = adjust_to_multiple(qty, lot)
    for item in cart:
        if not isinstance(item, dict):
            continue
        if item.get("codigo") == codigo:
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
    original_cols = list(df.columns)
    norm_map = {}
    for c in original_cols:
        sc = str(c or "").strip().upper()
        sc = _strip_accents(sc)
        sc = re.sub(r"[^A-Z0-9]+", "", sc)
        norm_map[sc] = c

    def pick(*cands):
        for cand in cands:
            cc = _strip_accents(str(cand)).upper()
            cc = re.sub(r"[^A-Z0-9]+", "", cc)
            if cc in norm_map:
                return norm_map[cc]
        return None

    col_code = pick("CODIGO", "CÓDIGO", "PRODUTO", "ITEM", "SKU", "COD", "REF")
    col_desc = pick("DESCRICAO", "DESCRIÇÃO", "DESC", "ESPECIFICACAO", "ESPECIFICAÇÃO", "NOME", "PRODUTODESCRICAO")
    col_qty  = pick("QTDE", "QUANTIDADE", "QTD", "QT", "QUANT")
    return col_code, col_desc, col_qty

def import_list_to_review(df):
    col_code, col_desc, col_qty = _detect_columns(df)
    if not col_code and not col_desc:
        raise ValueError("Não achei coluna de CÓDIGO nem de DESCRIÇÃO na planilha.")

    conn = get_conn(_empresa_id())
    found, not_found = [], []

    # Limpa cache antes de começar nova importação
    STECK_REVIEW_CACHE.clear()

    for _, row in df.iterrows():
        raw_code = _safe_cell_str(row.get(col_code) if col_code else "")
        raw_desc = _safe_cell_str(row.get(col_desc) if col_desc else "")
        raw_qty  = _safe_cell_str(row.get(col_qty)  if col_qty  else "")

        if not raw_code and not raw_desc:
            continue

        # Chave do cache combina código e descrição
        cache_key = f"{raw_code}|||{raw_desc}"
        if cache_key in STECK_REVIEW_CACHE:
            cached = STECK_REVIEW_CACHE[cache_key]
            if cached:
                item = cached.copy()
                item["quantidade"] = raw_qty or "1"
                found.append(item)
            else:
                not_found.append({
                    "entrada_codigo":    raw_code,
                    "entrada_descricao": raw_desc,
                    "quantidade": raw_qty or "1",
                })
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
            item = {
                "entrada_codigo":   raw_code,
                "entrada_descricao": raw_desc,
                "codigo":     matched["produto_raw"],
                "descricao":  matched["descricao"],
                "lote_minimo": matched["lote_minimo"] or "",
                "quantidade": raw_qty or "1",
            }
            found.append(item)
            STECK_REVIEW_CACHE[cache_key] = item
        else:
            not_found.append({
                "entrada_codigo":    raw_code,
                "entrada_descricao": raw_desc,
                "quantidade": raw_qty or "1",
            })
            STECK_REVIEW_CACHE[cache_key] = None

    conn.close()
    return found, not_found

# ── Rotas ─────────────────────────────────────────────────────────────────────
@catalogo_bp.get("/")
def index():
    return render_template("index.html")

@catalogo_bp.get("/search")
def search():
    q = request.args.get("q", "").strip()
    cart = get_cart()
    summary = cart_summary(cart)
    results = []
    total = 0
    pages = 1
    page = 1

    if q:
        try:
            page = int(request.args.get("page", "1") or "1")
        except Exception:
            page = 1
        page = max(1, page)
        conn = get_conn(_empresa_id())
        r = ranked_search(conn, q, page=page, per_page=50)
        conn.close()
        results = r.get("rows", []) if isinstance(r, dict) else (r or [])
        total = int(r.get("total", len(results))) if isinstance(r, dict) else len(results)
        pages = int(r.get("pages", 1)) if isinstance(r, dict) else 1

    return render_template("results.html", q=q, results=results,
                           cart=cart, summary=summary, page=page, pages=pages, total=total)

@catalogo_bp.post("/add")
def add():
    produto_raw  = request.form.get("produto_raw", "").strip()
    descricao    = request.form.get("descricao", "").strip()
    lote_minimo  = request.form.get("lote_minimo", "").strip()
    quantidade   = request.form.get("quantidade", "").strip()

    print(f"[ADD] iniciando, user: {session.get('user')!r}  codigo={produto_raw!r}  qty={quantidade!r}")
    try:
        cart = cart_add_or_sum(produto_raw, descricao, lote_minimo, quantidade)
        print(f"[ADD] carrinho apos add ({len(cart)} itens): {cart}")
        save_cart(cart)
        print(f"[ADD] salvo com sucesso em: {_cart_path()}")
        cart_path = _cart_path()
        print(f"[ADD-VERIFY] arquivo={cart_path} existe={os.path.exists(cart_path)}")
        if os.path.exists(cart_path):
            print(f"[ADD-VERIFY] conteudo={open(cart_path, encoding='utf-8').read()}")
        else:
            print("[ADD-VERIFY] ARQUIVO NAO FOI CRIADO")
    except Exception as e:
        import traceback
        print(f"[ADD] ERRO: {e}")
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

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
    return render_template("cart.html", cart=get_cart())

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
    return render_template("import.html")

@catalogo_bp.post("/import")
def import_upload():
    if "file" not in request.files or not request.files["file"].filename:
        flash("Selecione um arquivo Excel.")
        return redirect(url_for("catalogo_steck.import_page"))

    f = request.files["file"]
    filename = (f.filename or "").lower()
    try:
        if filename.endswith(".xls") and not filename.endswith(".xlsx"):
            df = pd.read_excel(f)
        else:
            df = pd.read_excel(f)
    except Exception:
        flash("Não foi possível ler a planilha. Dica: salve como .xlsx e tente novamente.")
        return redirect(url_for("catalogo_steck.import_page"))

    if df is None or df.empty:
        flash("Planilha vazia ou sem linhas.")
        return redirect(url_for("catalogo_steck.import_page"))

    if len(df) > 3000:
        df = df.head(3000).copy()
        flash("Planilha muito grande: processadas apenas as primeiras 3000 linhas.")

    try:
        found, not_found = import_list_to_review(df)
    except Exception as e:
        flash(str(e))
        return redirect(url_for("catalogo_steck.import_page"))
    
    # Salva dados grandes no disco e guarda apenas o ID na session
    session["steck_review_found_id"]     = _save_session_data("review_found", found)
    session["steck_review_not_found_id"] = _save_session_data("review_not_found", not_found)

    return redirect(url_for("catalogo_steck.review_page"))

@catalogo_bp.get("/review")
def review_page():
    # Carrega do disco usando os IDs da session
    found     = _load_session_data(session.get("steck_review_found_id"), [])
    not_found = _load_session_data(session.get("steck_review_not_found_id"), [])
    return render_template("review.html", found=found, not_found=not_found)

@catalogo_bp.post("/review/add_all")
def review_add_all():
    if "user" not in session:
        return redirect("/")

    found = _load_session_data(session.get("steck_review_found_id"), [])
    if not found:
        return redirect(url_for("catalogo_steck.search", q=""))

    # Lê carrinho UMA vez diretamente do disco
    # Não usar get_cart() nem cart_add_or_sum() — ambos chamam obter_carrinho()
    # internamente, e cart_add_or_sum() releria o disco a cada iteração do loop
    cart = obter_carrinho()

    count = 0
    for it in found:
        codigo = it.get("codigo", "")
        if not codigo:
            continue

        lote_str = it.get("lote_minimo") or "1"
        lote = parse_number_ptbr(lote_str) or 1.0
        qty  = parse_number_ptbr(it.get("quantidade")) or lote
        qty  = adjust_to_multiple(qty, lote)

        existing = next(
            (i for i in cart if isinstance(i, dict) and i.get("codigo") == codigo),
            None,
        )
        if existing:
            current = parse_number_ptbr(existing.get("quantidade")) or 0.0
            existing["quantidade"]  = format_qty(adjust_to_multiple(current + qty, lote))
            existing["lote_minimo"] = lote_str or existing.get("lote_minimo", "")
        else:
            cart.append({
                "codigo":      codigo,
                "descricao":   it.get("descricao", ""),
                "lote_minimo": lote_str,
                "quantidade":  format_qty(qty),
            })
        count += 1

    # Grava no disco UMA vez com o carrinho completo
    _salvar_carrinho(cart)
    print(f"[REVIEW] {count}/{len(found)} itens adicionados, carrinho total={len(cart)}")

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

@catalogo_bp.get("/debug-cart")
def debug_cart():
    """Diagnóstico do carrinho — remover depois de resolvido o problema."""
    path = _cart_path()
    cart = obter_carrinho()
    return jsonify({
        "session_user":  session.get("user"),
        "session_keys":  list(session.keys()),
        "cart_file":     path,
        "cart_exists":   os.path.exists(path),
        "cart_size_bytes": os.path.getsize(path) if os.path.exists(path) else 0,
        "cart_items":    len(cart),
        "cart":          cart,
    })
