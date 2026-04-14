import os
import re
import pandas as pd
from rapidfuzz import fuzz as rapidfuzz_fuzz

from config import CAMINHO_BASE_KRONA_FINAL, BASE_DIR
from base_mrv_loader import carregar_base_mrv
from matcher_mrv import match_por_codigo_mrv
from regra_quantidade import ajustar_quantidade_tubo


CAMINHO_BASE_KRONA = CAMINHO_BASE_KRONA_FINAL
# caminho lido do config, sem valor fixo no codigo
CAMINHO_BASE_MRV = os.path.join(BASE_DIR, "dados", "base_mrv.csv")


# ============================================================
# BASES
# ============================================================

def carregar_base_krona():
    if not os.path.exists(CAMINHO_BASE_KRONA):
        raise FileNotFoundError(f"Base Krona final não encontrada: {CAMINHO_BASE_KRONA}")

    df = pd.read_csv(CAMINHO_BASE_KRONA, sep=";", encoding="utf-8-sig")

    colunas_obrigatorias = [
        "codigo_krona",
        "descricao_krona",
        "descricao_normalizada",
        "categoria_detectada",
        "eh_tubo",
    ]

    faltando = [c for c in colunas_obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas obrigatórias ausentes: {faltando}")

    return df


def carregar_indice_mrv():
    if not os.path.exists(CAMINHO_BASE_MRV):
        return None

    try:
        return carregar_base_mrv(CAMINHO_BASE_MRV)
    except Exception:
        return None


def buscar_cadastro_krona_por_codigo(codigo_krona, base_krona):
    if base_krona is None or base_krona.empty:
        return None

    if codigo_krona is None:
        return None

    codigo = str(codigo_krona).strip()

    encontrados = base_krona[
        base_krona["codigo_krona"].astype(str).str.strip() == codigo
    ]

    if encontrados.empty:
        return None

    return encontrados.iloc[0].to_dict()


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def tokenizar(texto):
    return set(re.findall(r"[A-Z0-9]+", str(texto or "").upper()))


def texto_ratio(a, b):
    # rapidfuzz retorna 0-100, normalizamos para 0-1
    return rapidfuzz_fuzz.ratio(str(a).upper(), str(b).upper()) / 100.0


def token_score(a, b):
    # token_sort_ratio lida bem com palavras fora de ordem (ex: "TUBO PVC 20MM" vs "20MM PVC TUBO")
    return rapidfuzz_fuzz.token_sort_ratio(str(a).upper(), str(b).upper()) / 100.0


def numero_igual(a, b, tolerancia=0.0001):
    try:
        return abs(float(a) - float(b)) <= tolerancia
    except:
        return False


def obter_diametro_krona(c):
    return c.get("diametro_final_mm") or c.get("diametro_mm")


def obter_comprimento_krona(c):
    return (
        c.get("comprimento_final_m")
        or c.get("comprimento_detectado_m")
        or c.get("comprimento_matriz_m")
    )


# ============================================================
# SCORING
# ============================================================

def score_estrutura(item, cand):
    score = 0

    if item.get("categoria_detectada") == cand.get("categoria_detectada"):
        score += 0.20

    if item.get("eh_tubo") == cand.get("eh_tubo"):
        score += 0.20

    if numero_igual(item.get("diametro_mm"), obter_diametro_krona(cand)):
        score += 0.30

    if numero_igual(item.get("comprimento_detectado_m"), obter_comprimento_krona(cand)):
        score += 0.20

    return round(score, 4)


def score_textual(item, cand):
    d1 = item.get("descricao_normalizada") or item.get("descricao_oc")
    d2 = cand.get("descricao_normalizada") or cand.get("descricao_krona")

    return round((texto_ratio(d1, d2) * 0.65) + (token_score(d1, d2) * 0.35), 4)


def score_total(item, cand):
    se = score_estrutura(item, cand)
    st = score_textual(item, cand)
    return {
        "score_estrutura": se,
        "score_textual": st,
        "score_total": round((se * 0.6) + (st * 0.4), 4),
    }


# ============================================================
# MATCH PRINCIPAL
# ============================================================

def match_item_oc(item, base_krona=None, indice_mrv=None):
    if base_krona is None:
        base_krona = carregar_base_krona()

    if indice_mrv is None:
        indice_mrv = carregar_indice_mrv()

    # =========================================================
    # PRIORIDADE 1 — MRV
    # =========================================================
    if indice_mrv:
        match_mrv = match_por_codigo_mrv(item, indice_mrv)

        if match_mrv:
            cod_krona = match_mrv.get("codigo_krona")
            cadastro = buscar_cadastro_krona_por_codigo(cod_krona, base_krona) or {}

            return {
                "match_encontrado": True,
                "codigo_krona": cod_krona,
                "descricao_krona": cadastro.get("descricao_krona"),
                "descricao_krona_normalizada": cadastro.get("descricao_normalizada"),
                "linha_krona_match": cadastro.get("linha_krona"),
                "familia_krona_match": cadastro.get("familia_krona"),
                "unidade_venda_krona": cadastro.get("unidade_venda"),
                "quantidade_embalagem_krona": cadastro.get("quantidade_embalagem"),
                "score_estrutura": 1.0,
                "score_textual": 1.0,
                "score_total": 1.0,
                "tipo_match": "MATCH_CODIGO_MRV",
                "revisao_manual": False,
                "motivo_match": "MATCH_DIRETO_CODIGO_MRV",
                "categoria_krona": cadastro.get("categoria_detectada"),
                "eh_tubo_krona": cadastro.get("eh_tubo"),
                "diametro_krona_mm": obter_diametro_krona(cadastro),
                "comprimento_krona_m": obter_comprimento_krona(cadastro),
            }

    # =========================================================
    # FALLBACK TRADICIONAL
    # =========================================================
    # score minimo para aceitar um match automatico
    # abaixo disso o item vai para revisao manual sem codigo krona
    SCORE_MINIMO = 0.30

    registros = []

    for _, row in base_krona.iterrows():
        cand = row.to_dict()
        scores = score_total(item, cand)

        registros.append({**cand, **scores})

    df = pd.DataFrame(registros).sort_values(
        by=["score_total"], ascending=False
    )

    melhor = df.iloc[0].to_dict()
    score_melhor = melhor.get("score_total", 0)

    # se o melhor resultado nao atinge o minimo, nao força o match
    if score_melhor < SCORE_MINIMO:
        return {
            "match_encontrado": False,
            "codigo_krona": None,
            "descricao_krona": None,
            "descricao_krona_normalizada": None,
            "linha_krona_match": None,
            "familia_krona_match": None,
            "unidade_venda_krona": None,
            "quantidade_embalagem_krona": None,
            "score_estrutura": melhor.get("score_estrutura"),
            "score_textual": melhor.get("score_textual"),
            "score_total": score_melhor,
            "tipo_match": "SEM_MATCH",
            "revisao_manual": True,
            "motivo_match": f"SCORE_ABAIXO_DO_MINIMO({score_melhor:.2f}<{SCORE_MINIMO})",
            "categoria_krona": None,
            "eh_tubo_krona": None,
            "diametro_krona_mm": None,
            "comprimento_krona_m": None,
        }

    return {
        "match_encontrado": True,
        "codigo_krona": melhor.get("codigo_krona"),
        "descricao_krona": melhor.get("descricao_krona"),
        "descricao_krona_normalizada": melhor.get("descricao_normalizada"),
        "linha_krona_match": melhor.get("linha_krona"),
        "familia_krona_match": melhor.get("familia_krona"),
        "unidade_venda_krona": melhor.get("unidade_venda"),
        "quantidade_embalagem_krona": melhor.get("quantidade_embalagem"),
        "score_estrutura": melhor.get("score_estrutura"),
        "score_textual": melhor.get("score_textual"),
        "score_total": score_melhor,
        "tipo_match": "TRADICIONAL",
        "revisao_manual": False,
        "motivo_match": "FALLBACK",
        "categoria_krona": melhor.get("categoria_detectada"),
        "eh_tubo_krona": melhor.get("eh_tubo"),
        "diametro_krona_mm": obter_diametro_krona(melhor),
        "comprimento_krona_m": obter_comprimento_krona(melhor),
    }


# ============================================================
# LOTE + REGRA DE QUANTIDADE
# ============================================================

def match_lote_itens(df_oc, base_krona=None, indice_mrv=None):
    if base_krona is None:
        base_krona = carregar_base_krona()

    if indice_mrv is None:
        indice_mrv = carregar_indice_mrv()

    resultados = []

    for _, row in df_oc.iterrows():
        item = row.to_dict()

        resultado = match_item_oc(item, base_krona, indice_mrv)

        final = {**item, **resultado}

        # 🔥 REGRA DE NEGÓCIO
        final = ajustar_quantidade_tubo(final)

        resultados.append(final)

    return pd.DataFrame(resultados)