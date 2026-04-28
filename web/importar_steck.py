"""
importar_steck.py — Importa catálogo Steck/Schneider para o SQLite do Vortex
Usa DUAS fontes de dados e cruza pelo SKU:

  Fonte 1 (obrigatória): catalogo_steck_raw.xlsx
    → SKU, Nome do Produto, NCM, EAN, imagens...

  Fonte 2 (complementar): catalogo_steck_lote.xlsx
    → PRODUTO, DESCRICAO, LOTE MINIMO, CLAS.FISCAL, CST, %ICMS, %IPI, EAN13

Uso:
  cd C:\robo_gamatec_oc\web
  python importar_steck.py
"""

import sqlite3
import re
import pandas as pd
from pathlib import Path

XLSX1 = Path(r"C:\robo_gamatec_oc\instance\catalogo_steck_raw.xlsx")
XLSX2 = Path(r"C:\robo_gamatec_oc\instance\catalogo_steck_lote.xlsx")
DB    = Path(r"C:\robo_gamatec_oc\instance\catalogo_steck.db")


def norm(v):
    return str(v or "").strip().upper()

def digits(v):
    return "".join(re.findall(r"\d+", str(v or "")))

def clean_lote(v):
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in ("", "nan", "none", "sim", "nao", "não", "-", "0", "0.0"):
        return None
    try:
        f = float(s.replace(",", "."))
        return str(int(f)) if f > 0 else None
    except Exception:
        return None

def find_col(df, *candidates):
    cols = set(df.columns)
    return next((c for c in candidates if c in cols), None)


def main():
    # ── Fonte 1 ──────────────────────────────────────────────────────────────
    if not XLSX1.exists():
        print(f"ERRO: Arquivo não encontrado: {XLSX1}")
        return

    df1 = pd.read_excel(XLSX1)
    df1.columns = [str(c).strip().upper() for c in df1.columns]
    print(f"Fonte 1 (catálogo): {len(df1)} linhas")

    col1_sku  = find_col(df1, "SKU", "CODIGO", "CÓDIGO", "COD", "PRODUTO", "REF")
    col1_desc = find_col(df1, "NOME DO PRODUTO", "DESCRICAO", "DESCRIÇÃO", "DESC", "NOME")
    col1_ean  = find_col(df1, "CÓDIGO EAN DO PRODUTO", "EAN", "EAN13", "CODBARRAS", "GTIN")
    col1_ncm  = find_col(df1, "NCM", "CLAS_FISCAL", "CLASS FISCAL")

    print(f"  SKU → {col1_sku} | Desc → {col1_desc} | EAN → {col1_ean} | NCM → {col1_ncm}")

    # ── Fonte 2 ───────────────────────────────────────────────────────────────
    lote_map = {}
    icms_map = {}
    ipi_map  = {}
    cst_map  = {}
    ncm_map  = {}
    ean2_map = {}

    if XLSX2.exists():
        df2 = pd.read_excel(XLSX2)
        df2.columns = [str(c).strip().upper() for c in df2.columns]
        print(f"\nFonte 2 (lote/fiscal): {len(df2)} linhas")

        col2_sku  = find_col(df2, "PRODUTO", "SKU", "CODIGO", "CÓDIGO")
        col2_lote = find_col(df2, "LOTE MINIMO", "LOTE MÍNIMO", "LOTE", "MOQ")
        col2_icms = find_col(df2, "%ICMS", "ICMS")
        col2_ipi  = find_col(df2, "%IPI", "IPI")
        col2_cst  = find_col(df2, "CST")
        col2_ncm  = find_col(df2, "CLAS.FISCAL", "NCM", "CLAS_FISCAL")
        col2_ean  = find_col(df2, "EAN13", "EAN", "CÓDIGO EAN DO PRODUTO")

        print(f"  SKU → {col2_sku} | Lote → {col2_lote} | ICMS → {col2_icms} | IPI → {col2_ipi}")

        if col2_sku:
            for _, row in df2.iterrows():
                sku = norm(row.get(col2_sku))
                if not sku:
                    continue
                if col2_lote: lote_map[sku] = clean_lote(row.get(col2_lote))
                if col2_icms: icms_map[sku] = row.get(col2_icms)
                if col2_ipi:  ipi_map[sku]  = row.get(col2_ipi)
                if col2_cst:  cst_map[sku]  = str(row.get(col2_cst) or "").strip()
                if col2_ncm:  ncm_map[sku]  = str(row.get(col2_ncm) or "").strip()
                if col2_ean:  ean2_map[sku] = str(row.get(col2_ean) or "").strip()

            print(f"  {len(lote_map)} SKUs com lote mínimo carregados")
    else:
        print(f"\nFonte 2 não encontrada ({XLSX2.name}) — sem lote mínimo.")
        print(f"Salve o arquivo de preços/fiscal como: {XLSX2}")

    # ── Banco ─────────────────────────────────────────────────────────────────
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_raw    TEXT NOT NULL,
        produto_norm   TEXT NOT NULL,
        produto_digits TEXT,
        produto_prefix TEXT,
        descricao      TEXT,
        lote_minimo    TEXT,
        clas_fiscal    TEXT,
        cst            TEXT,
        icms           REAL,
        ipi            REAL,
        ean13          TEXT
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pn   ON produtos(produto_norm);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pd   ON produtos(produto_digits);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_desc ON produtos(descricao);")

    cur.execute("DELETE FROM produtos")
    print(f"\nTabela limpa. Importando...")

    inseridos = 0
    pulados   = 0
    com_lote  = 0

    for _, row in df1.iterrows():
        raw = norm(row.get(col1_sku) if col1_sku else "")
        if not raw or raw in ("NAN", "NONE", ""):
            pulados += 1
            continue

        desc = norm(row.get(col1_desc) if col1_desc else "")

        ean = ean2_map.get(raw) or (str(row.get(col1_ean) or "").strip() if col1_ean else "")
        if ean.lower() in ("nan", "none", ""):
            ean = None

        ncm = ncm_map.get(raw) or (str(row.get(col1_ncm) or "").strip() if col1_ncm else "")
        if not ncm or ncm.lower() in ("nan", "none"):
            ncm = None

        lote = lote_map.get(raw)
        if lote:
            com_lote += 1

        try:
            cur.execute("""
                INSERT INTO produtos
                  (produto_raw, produto_norm, produto_digits, produto_prefix,
                   descricao, lote_minimo, clas_fiscal, cst, icms, ipi, ean13)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                raw, norm(raw), digits(raw), raw[:4],
                desc, lote, ncm,
                cst_map.get(raw),
                icms_map.get(raw),
                ipi_map.get(raw),
                ean,
            ))
            inseridos += 1
        except Exception as e:
            print(f"  AVISO linha {_+2}: {e}")
            pulados += 1

    conn.commit()
    conn.close()

    pct = round(com_lote / inseridos * 100) if inseridos else 0
    print(f"\n✓ {inseridos} produtos importados")
    print(f"  {com_lote} com lote mínimo ({pct}%)")
    print(f"  {pulados} linhas puladas")
    print(f"  Banco: {DB}")
    print("\nPronto! Reinicie o servidor Vortex.")


if __name__ == "__main__":
    main()
