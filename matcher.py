import os
import re
import pandas as pd
from rapidfuzz import fuzz as rapidfuzz_fuzz

from config import CAMINHO_BASE_KRONA_FINAL, BASE_DIR
from base_mrv_loader import carregar_base_mrv
from matcher_mrv import match_por_codigo_mrv
from base_brasal_loader import carregar_base_brasal
from matcher_brasal import match_por_codigo_brasal
from regra_quantidade import ajustar_quantidade_tubo

# ── IA Helper — fallback seguro se modulo nao disponivel ──────────────────
try:
    from ia_helper import ia_disponivel, sugerir_match as ia_sugerir_match
    IA_DISPONIVEL = True
except ImportError:
    IA_DISPONIVEL = False
    ia_disponivel    = lambda: False
    ia_sugerir_match = lambda *a, **k: None


CAMINHO_BASE_KRONA = CAMINHO_BASE_KRONA_FINAL
# caminho lido do config, sem valor fixo no codigo
CAMINHO_BASE_MRV = os.path.join(BASE_DIR, "dados", "base_mrv.csv")

# ============================================================
# CÓDIGOS EXCLUÍDOS DO MATCH AUTOMÁTICO
# Produtos que não existem mais no catálogo ativo ou que causam
# matches incorretos. Adicione aqui quando identificar problemas.
# ============================================================
CODIGOS_EXCLUIDOS_MATCH = {
    "784",   # TORNEIRA PARA JARDIM PRETA/PRETA — nao existe no XLSX de produtos
             # o correto e 786 (SLIM) ou 781 (ESF)
    "1758",  # TUBO PVC ESG DN40 PY — linha PY especial
    "1759",  # TUBO PVC ESG DN50 PY — linha PY especial
    "1761",  # TUBO PVC ESG DN100 PY — linha PY especial
    # 1750 removido — era TUBO PVC SOLD 25MM PY, mas sem alternativa na base
    # o sistema agora pode encontrar o código correto para linha normal
}

# ============================================================
# THRESHOLD PARA CORREÇÕES APRENDIDAS
# ============================================================
# Valor em percentual (0-100) para aceitar uma correção aprendida
# via correspondência aproximada. 85% é conservador, evita falsos positivos.
# Ajustar conforme necessário: 80% para mais flexibilidade, 90% para mais rigor.
THRESHOLD_CORRECAO_APRENDIDA = 85


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

    # remove produtos excluidos do match automatico
    if CODIGOS_EXCLUIDOS_MATCH:
        antes = len(df)
        df = df[~df["codigo_krona"].astype(str).isin(CODIGOS_EXCLUIDOS_MATCH)]
        excluidos = antes - len(df)
        if excluidos > 0:
            print(f"[MATCHER] {excluidos} produto(s) excluido(s) do match: {CODIGOS_EXCLUIDOS_MATCH}")

    # correcao em runtime: preencher categoria_detectada para produtos sem categoria
    # JUNCAO nao estava no normalizador original — corrigido aqui sem precisar regenerar a base
    sem_cat = df["categoria_detectada"].isna()
    if sem_cat.sum() > 0:
        desc = df.loc[sem_cat, "descricao_krona"].fillna("").str.upper()
        df.loc[sem_cat & desc.str.contains("JUNCAO|JUNC", na=False), "categoria_detectada"] = "JUNCAO"

        sem_cat2 = df["categoria_detectada"].isna()
        desc2 = df.loc[sem_cat2, "descricao_krona"].fillna("").str.upper()
        df.loc[sem_cat2 & desc2.str.contains("REDUC", na=False), "categoria_detectada"] = "REDUCAO"

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

    # normaliza: remove zeros à esquerda para bater com base que armazena como int
    # ex: "0024" → "24", "024" → "24", "24" → "24"
    codigo = str(codigo_krona).strip().lstrip("0") or "0"

    encontrados = base_krona[
        base_krona["codigo_krona"].astype(str).str.strip().str.lstrip("0").replace("", "0") == codigo
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
# MATCH POR DESCRICAO — para clientes sem tabela DE/PARA
# ============================================================

_PREFIXOS_RUIDO = re.compile(
    r"^\s*(?:FVM|FV|REF|COD|PROD|MAT|ART|ITEM)\s*[-:]\s*",
    re.IGNORECASE
)

_NORMAS = re.compile(
    r"\s*[-\u2013]?\s*NBR\s*\d+",
    re.IGNORECASE
)


# Mapa de expansão de abreviações comuns nos PDFs de clientes
_ABREV_EXPANSAO = [
    # categoria
    (r"\bTUB\b",      "TUBO"),
    (r"\bJOE\b",      "JOELHO"),
    (r"\bJOEL\b",     "JOELHO"),
    (r"\bLUV\b",      "LUVA"),
    (r"\bADAP\b",     "ADAPTADOR"),
    (r"\bREG\b",      "REGISTRO"),
    (r"\bRED\b",      "REDUCAO"),
    (r"\bCAP\b",      "CAP"),
    (r"\bJUNC\b",     "JUNCAO"),
    (r"\bJUN\b",      "JUNCAO"),
    # material/linha
    (r"\bSOLD\b",     "SOLDAVEL"),
    (r"\bSOLDAV\b",   "SOLDAVEL"),
    (r"\bESG\b",      "ESGOTO"),
    (r"\bESGT\b",     "ESGOTO"),
    (r"\bPRIM\b",     "ESGOTO"),
    # serie normal Krona
    # diametro colado ex: "25MM" → "25 MM", "DN100" → "DN 100"
    (r"(\d)(MM)\b",   r"\1 MM"),
    (r"\bDN(\d)",     r"DN \1"),
    # angulo colado ex: "45X25" → "45 X 25"
    (r"(\d)X(\d)",    r"\1 X \2"),
    # separadores extras
    (r"[-–/|;]+",     " "),
]

def limpar_descricao_para_match(descricao, formato=None):
    """
    Limpa e expande a descricao para melhorar o match.
    formato: 'SIENGE' | 'UAU' | 'MRV' | 'BRASAL' | None
    """
    texto = str(descricao or "").upper().strip()
    texto = _PREFIXOS_RUIDO.sub("", texto)
    texto = _NORMAS.sub("", texto)

    # expansao de abreviacoes — maior impacto em PDFs UAU e SIENGE
    for padrao, substituto in _ABREV_EXPANSAO:
        texto = re.sub(padrao, substituto, texto)

    # grau como separador
    texto = texto.replace("°", " ")

    # remove parenteses e colchetes mas mantem o conteudo
    texto = re.sub(r"[()\[\]]", " ", texto)

    # normaliza espacos
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def extrair_diametro_da_descricao(descricao):
    texto = str(descricao or "").upper()
    padroes = [r"\bDN\s*(\d{1,3})\b", r"\b(\d{1,3})\s*MM\b", r"\b(\d{1,3})MM\b"]
    for p in padroes:
        m = re.search(p, texto)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return None


def extrair_categoria_da_descricao(descricao):
    texto = str(descricao or "").upper()
    categorias = [
        ("TUBO",      [r"\bTUBO\b"]),
        ("CAP",       [r"\bCAP\b"]),
        ("JOELHO",    [r"\bJOELHO\b", r"\bCURVA\b"]),
        ("TE",        [r"\bT[EE]\b"]),
        ("LUVA",      [r"\bLUVA\b"]),
        ("REDUCAO",   [r"\bREDU[C]"]),
        ("ADAPTADOR", [r"\bADAPTADOR\b"]),
        ("BUCHA",     [r"\bBUCHA\b"]),
        ("REGISTRO",  [r"\bREGISTRO\b"]),
        ("VALVULA",   [r"\bVALVULA\b"]),
        ("FITA",      [r"\bFITA\b"]),
        ("TORNEIRA",  [r"\bTORNEIRA\b"]),
        ("ADESIVO",   [r"\bADESIVO\b", r"\bCOLA\b"]),
        ("PASTA",     [r"\bPASTA\b"]),
        ("FLANGE",    [r"\bFLANGE\b"]),
        ("UNIAO",     [r"\bUNIAO\b"]),
        ("JUNCAO",    [r"\bJUN[CÇ][AÃ]O\b", r"\bJUNC\.?\b"]),
    ]
    for categoria, padroes in categorias:
        for padrao in padroes:
            if re.search(padrao, texto):
                return categoria
    return None


def extrair_material_da_descricao(descricao):
    texto = str(descricao or "").upper()
    if re.search(r"\bPPR\b", texto):        return "PPR"
    if re.search(r"\bCPVC\b", texto):       return "CPVC"
    if re.search(r"\bPEAD\b", texto):       return "PEAD"
    if re.search(r"\bPOLIETILENO\b", texto): return "PEAD"
    # PVC nao e suficiente para diferenciar — nao filtra por material PVC
    # pois na base Krona os produtos PVC nem sempre tem "PVC" no nome
    return None


def extrair_subcategoria_da_descricao(descricao):
    """
    Detecta subcategoria do produto para filtrar candidatos na base Krona.

    Padrão base Krona:
    - Série Reforçada  → produtos com código 1400+ tem 'SERIE REFORCADA' no nome
    - Série Normal     → produtos mais antigos usam PRIM (DN>=50) ou SEC (DN40)
    - Água fria soldável → SOLDAVEL
    """
    texto = str(descricao or "").upper()

    # serie reforcada (nova linha Krona 1400+)
    if re.search(r"REFOR[CÇ]", texto):
        return "REFORCADA"

    # esgoto serie normal → busca PRIM e SEC (ambos usados na Krona)
    if re.search(r"ESGOTO|\bESG\.?\b|\bPRIM\.?\b|\bSEC\.?\b", texto):
        return "ESGOTO"

    if re.search(r"\bSOLD[AV]\b|\bSOLDAVEL\b", texto):
        return "SOLDAVEL"
    if re.search(r"\bROSC[AV]\b|\bROSCAVEL\b", texto):
        return "ROSCAVEL"
    if re.search(r"\bULTRATERM\b", texto):
        return "ULTRATERM"
    return None


def filtrar_candidatos_krona(base_krona, categoria, diametro_mm, material=None, subcategoria=None, item_descricao=None):
    MIN_CANDIDATOS = 3

    # filtro mais preciso: categoria + diametro + subcategoria
    if categoria and diametro_mm is not None and subcategoria:
        mask_cat = base_krona["categoria_detectada"].fillna("").str.upper() == categoria.upper()
        mask_dia = (
            (base_krona["diametro_final_mm"].notna() & (base_krona["diametro_final_mm"] == diametro_mm)) |
            (base_krona["diametro_mm"].notna() & (base_krona["diametro_mm"] == diametro_mm))
        )
        # mapeia subcategoria para termos usados na base Krona
        termos_sub = {
            "REFORCADA": ["REFORCADA", "REFORC", "REFORÇ"],  # serie reforcada nova
            "ESGOTO":    ["ESGOTO", "PRIM", "SEC", "ESG"],   # esgoto serie normal
            "SOLDAVEL":  ["SOLD"],
            "ROSCAVEL":  ["ROSC"],
            "ULTRATERM": ["ULTRA"],
        }.get(subcategoria, [subcategoria[:4]])

        mask_sub = pd.Series([False] * len(base_krona), index=base_krona.index)
        for termo in termos_sub:
            mask_sub = mask_sub | base_krona["descricao_krona"].fillna("").str.upper().str.contains(termo)
        candidatos = base_krona[mask_cat & mask_dia & mask_sub]
        if len(candidatos) >= 1:
            return candidatos

    # filtro: categoria + diametro + material
    if categoria and diametro_mm is not None and material:
        mask_cat = base_krona["categoria_detectada"].fillna("").str.upper() == categoria.upper()
        mask_dia = (
            (base_krona["diametro_final_mm"].notna() & (base_krona["diametro_final_mm"] == diametro_mm)) |
            (base_krona["diametro_mm"].notna() & (base_krona["diametro_mm"] == diametro_mm))
        )
        mask_mat = base_krona["descricao_krona"].fillna("").str.upper().str.contains(material)
        candidatos = base_krona[mask_cat & mask_dia & mask_mat]
        if len(candidatos) >= 1:
            return candidatos

    # filtro: categoria + diametro
    if categoria and diametro_mm is not None:
        mask_cat = base_krona["categoria_detectada"].fillna("").str.upper() == categoria.upper()
        mask_dia = (
            (base_krona["diametro_final_mm"].notna() & (base_krona["diametro_final_mm"] == diametro_mm)) |
            (base_krona["diametro_mm"].notna() & (base_krona["diametro_mm"] == diametro_mm))
        )
        # se tiver material, filtra por ele mesmo com poucos candidatos
        if material:
            mask_mat = base_krona["descricao_krona"].fillna("").str.upper().str.contains(material)
            candidatos = base_krona[mask_cat & mask_dia & mask_mat]
            if len(candidatos) >= 1:
                return candidatos
        candidatos = base_krona[mask_cat & mask_dia]
        if len(candidatos) >= MIN_CANDIDATOS:
            return candidatos

    # filtro: so categoria
    if categoria:
        mask_cat = base_krona["categoria_detectada"].fillna("").str.upper() == categoria.upper()
        if material:
            mask_mat = base_krona["descricao_krona"].fillna("").str.upper().str.contains(material)
            candidatos = base_krona[mask_cat & mask_mat]
            if len(candidatos) >= MIN_CANDIDATOS:
                return candidatos
        candidatos = base_krona[mask_cat]
        if len(candidatos) >= MIN_CANDIDATOS:
            return candidatos

    # segurança: nunca retorna linha PY como candidato
    # a menos que a descricao da OC mencione explicitamente PY
    _desc_upper = str(item_descricao or "").upper() if item_descricao else ""
    if "PY" not in _desc_upper:
        mask_nao_py = ~base_krona["descricao_krona"].fillna("").str.upper().str.contains(r"\bPY\b", na=False, regex=True)
        if mask_nao_py.sum() > 0:
            base_krona = base_krona[mask_nao_py]

    return base_krona


def match_por_descricao(item, base_krona):
    descricao_raw = (
        item.get("descricao_oc")
        or item.get("descricao_reconstruida")
        or ""
    )

    # detecta o formato de origem do item para passar ao limpador
    obs = item.get("observacoes") or []
    if isinstance(obs, str):
        obs = [obs]
    formato_origem = None
    for o in obs:
        o_up = str(o).upper()
        if "SIENGE"  in o_up: formato_origem = "SIENGE";  break
        if "UAU"     in o_up: formato_origem = "UAU";     break
        if "BRASAL"  in o_up: formato_origem = "BRASAL";  break
        if "MRV"     in o_up: formato_origem = "MRV";     break

    descricao_limpa = limpar_descricao_para_match(descricao_raw, formato=formato_origem)
    categoria    = extrair_categoria_da_descricao(descricao_limpa)
    diametro     = extrair_diametro_da_descricao(descricao_limpa)
    material     = extrair_material_da_descricao(descricao_limpa)
    subcategoria = extrair_subcategoria_da_descricao(descricao_limpa)

    # score mínimo adaptativo:
    # descrições curtas/quebradas (< 4 tokens) recebem threshold menor
    # pois PDFs UAU/SIENGE frequentemente chegam com texto truncado
    tokens_desc = [t for t in descricao_limpa.split() if len(t) > 1]
    if len(tokens_desc) < 4:
        SCORE_MINIMO_DESCRICAO = 0.32   # texto curto/quebrado — mais tolerante
    elif categoria and diametro is not None:
        SCORE_MINIMO_DESCRICAO = 0.40   # categoria + diâmetro detectados — confiança média
    else:
        SCORE_MINIMO_DESCRICAO = 0.45   # descrição completa — threshold original

    candidatos = filtrar_candidatos_krona(base_krona, categoria, diametro, material, subcategoria, descricao_limpa)

    # exclui linha PY a menos que a OC peça explicitamente
    if "PY" not in descricao_limpa:
        mask_sem_py = ~candidatos["descricao_krona"].fillna("").str.upper().str.contains(r"\bPY\b", na=False, regex=True)
        if mask_sem_py.sum() > 0:
            candidatos = candidatos[mask_sem_py]

    # para JUNCAO com dois diametros (ex: 100X75), diametro_final_mm eh NaN na base
    # refinar candidatos por texto dos dois numeros da descricao OC
    if categoria == "JUNCAO" and diametro is not None:
        nums_oc = re.findall(r"\b(\d{2,3})\b", descricao_limpa)
        if len(nums_oc) >= 2:
            mask_sem_diam = candidatos["diametro_final_mm"].isna() & candidatos["diametro_mm"].isna()
            candidatos_sem_diam = candidatos[mask_sem_diam]
            candidatos_com_diam = candidatos[~mask_sem_diam]
            if not candidatos_sem_diam.empty:
                mask_num = pd.Series([False] * len(candidatos_sem_diam), index=candidatos_sem_diam.index)
                for num in nums_oc[:2]:
                    mask_num = mask_num | candidatos_sem_diam["descricao_krona"].fillna("").str.upper().str.contains(rf"\b{num}\b", regex=True, na=False)
                candidatos_filtrados = candidatos_sem_diam[mask_num]
                if not candidatos_filtrados.empty:
                    candidatos = pd.concat([candidatos_com_diam, candidatos_filtrados])
                elif not candidatos_com_diam.empty:
                    candidatos = candidatos_com_diam

    if candidatos.empty:
        return {"match_encontrado": False, "tipo_match": "SEM_MATCH",
                "motivo_match": "sem_candidatos_krona"}

    # filtro critico: distingue serie REFORCADA vs NORMAL
    # na base Krona: serie reforcada usa REFORC ou SR (para tubos)
    # serie normal usa PRIM ou SEC — nunca REFORC nem SR
    if subcategoria == "REFORCADA":
        # OC pede REFORCADA — manter apenas produtos com REFORC ou SR no nome
        mask_ref = (
            candidatos["descricao_krona"].fillna("").str.upper().str.contains("REFORC", na=False) |
            candidatos["descricao_krona"].fillna("").str.upper().str.contains(r" SR ", na=False, regex=True)
        )
        if mask_ref.sum() > 0:
            candidatos = candidatos[mask_ref]
    elif subcategoria == "ESGOTO":
        # OC pede serie NORMAL — excluir produtos com REFORC, SR ou PY no nome
        mask_nao_ref = ~(
            candidatos["descricao_krona"].fillna("").str.upper().str.contains("REFORC", na=False) |
            candidatos["descricao_krona"].fillna("").str.upper().str.contains(r" SR ", na=False, regex=True) |
            candidatos["descricao_krona"].fillna("").str.upper().str.contains(r" PY$", na=False, regex=True)
        )
        if mask_nao_ref.sum() > 0:
            candidatos = candidatos[mask_nao_ref]

    if candidatos.empty:
        return {"match_encontrado": False, "tipo_match": "SEM_MATCH",
                "motivo_match": "sem_candidatos_apos_filtro_serie"}

    registros = []
    for _, row in candidatos.iterrows():
        cand = row.to_dict()
        desc_krona = str(cand.get("descricao_normalizada") or cand.get("descricao_krona") or "").upper()

        score_txt = rapidfuzz_fuzz.token_sort_ratio(descricao_limpa, desc_krona) / 100.0
        score_str = rapidfuzz_fuzz.ratio(descricao_limpa, desc_krona) / 100.0
        score_base = round((score_txt * 0.70) + (score_str * 0.30), 4)

        # bônus estrutural: categoria e diâmetro já confirmados pelo filtro
        # recompensam candidatos que chegaram pela rota mais precisa
        bonus = 0.0
        if categoria and str(cand.get("categoria_detectada", "")).upper() == categoria.upper():
            bonus += 0.06
        if diametro is not None:
            diam_cand = cand.get("diametro_final_mm") or cand.get("diametro_mm")
            try:
                if abs(float(diam_cand) - diametro) < 0.01:
                    bonus += 0.08
            except (TypeError, ValueError):
                pass
        if subcategoria and subcategoria in str(desc_krona):
            bonus += 0.04

        score_final = round(min(1.0, score_base + bonus), 4)
        registros.append({**cand, "score_total": score_final, "score_textual": score_txt})

    df_scores = pd.DataFrame(registros).sort_values("score_total", ascending=False)
    melhor = df_scores.iloc[0].to_dict()
    score_melhor = melhor.get("score_total", 0)

    if score_melhor < SCORE_MINIMO_DESCRICAO:
        return {
            "match_encontrado": False,
            "codigo_krona": None,
            "descricao_krona": None,
            "descricao_krona_normalizada": None,
            "linha_krona_match": None,
            "familia_krona_match": None,
            "unidade_venda_krona": None,
            "quantidade_embalagem_krona": None,
            "score_estrutura": 0,
            "score_textual": melhor.get("score_textual", 0),
            "score_total": score_melhor,
            "tipo_match": "SEM_MATCH",
            "revisao_manual": True,
            "motivo_match": f"SCORE_DESCRICAO_ABAIXO({score_melhor:.2f}<{SCORE_MINIMO_DESCRICAO})",
            "categoria_krona": categoria,
            "eh_tubo_krona": None,
            "diametro_krona_mm": None,
            "comprimento_krona_m": None,
        }

    # verifica se ha empate proximo entre os top candidatos
    # se a diferenca entre o 1o e o 2o for menor que 0.05, marca para revisao
    MARGEM_EMPATE = 0.02  # diferenca menor que 2% = empate real
    revisao_por_empate = False
    if len(df_scores) >= 2:
        segundo = df_scores.iloc[1].to_dict()
        score_segundo = segundo.get("score_total", 0)
        diferenca = score_melhor - score_segundo
        if diferenca < MARGEM_EMPATE:
            revisao_por_empate = True

    return {
        "match_encontrado": True,
        "codigo_krona": melhor.get("codigo_krona"),
        "descricao_krona": melhor.get("descricao_krona"),
        "descricao_krona_normalizada": melhor.get("descricao_normalizada"),
        "linha_krona_match": melhor.get("linha_krona"),
        "familia_krona_match": melhor.get("familia_krona"),
        "unidade_venda_krona": melhor.get("unidade_venda"),
        "quantidade_embalagem_krona": melhor.get("quantidade_embalagem"),
        "score_estrutura": 0,
        "score_textual": melhor.get("score_textual", 0),
        "score_total": score_melhor,
        "tipo_match": "MATCH_DESCRICAO" if not revisao_por_empate else "MATCH_DESCRICAO_REVISAR",
        "revisao_manual": revisao_por_empate,
        "motivo_match": (
            f"MATCH_POR_DESCRICAO(cat={categoria},diam={diametro})"
            if not revisao_por_empate
            else f"MATCH_EMPATE_PROXIMO(dif={score_melhor - df_scores.iloc[1].get('score_total',0):.2f})"
        ),
        "categoria_krona": melhor.get("categoria_detectada"),
        "eh_tubo_krona": melhor.get("eh_tubo"),
        "diametro_krona_mm": obter_diametro_krona(melhor),
        "comprimento_krona_m": obter_comprimento_krona(melhor),
    }

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

def match_item_oc(item, base_krona=None, indice_mrv=None, indice_brasal=None):
    if base_krona is None:
        base_krona = carregar_base_krona()

    if indice_mrv is None:
        indice_mrv = carregar_indice_mrv()

    if indice_brasal is None:
        indice_brasal = carregar_base_brasal()

    # ── PRIORIDADE MÁXIMA: código Krona já presente na OC ────────────────────
    codigo_direto = str(item.get("codigo_krona_oc") or "").strip()
    if codigo_direto:
        cadastro = buscar_cadastro_krona_por_codigo(codigo_direto, base_krona)
        if cadastro:
            return {
                "match_encontrado": True,
                "codigo_krona": codigo_direto,
                "descricao_krona": cadastro.get("descricao_krona", ""),
                "descricao_krona_normalizada": cadastro.get("descricao_normalizada", ""),
                "score_estrutura": 0,
                "score_textual": 1.0,
                "score_total": 1.0,
                "tipo_match": "MATCH_CODIGO_DIRETO_OC",
                "revisao_manual": False,
                "motivo_match": "CODIGO_KRONA_PRESENTE_NA_OC",
                "categoria_krona": cadastro.get("categoria_detectada"),
                "eh_tubo_krona": cadastro.get("eh_tubo"),
            }

    # ── CONSULTAR CORRECOES APRENDIDAS (com correspondência aproximada) ──
    try:
        import json
        correcoes_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "dados", "correcoes_aprendidas.json"
        )
        if os.path.exists(correcoes_path):
            with open(correcoes_path, encoding='utf-8') as f:
                correcoes = json.load(f)
            descricao_item = str(item.get('descricao_oc', '') or
                                 item.get('descricao_reconstruida', '') or '').upper().strip()
            
            # usa rapidfuzz para correspondência aproximada (threshold configurável)
            try:
                melhor_correcao = None
                melhor_score = 0
                for c in correcoes:
                    desc_correcao = str(c.get('descricao_oc', '')).upper().strip()
                    if not desc_correcao:
                        continue
                    # token_sort_ratio ignora ordem das palavras
                    similaridade = rapidfuzz_fuzz.token_sort_ratio(descricao_item, desc_correcao)
                    if similaridade > melhor_score:
                        melhor_score = similaridade
                        melhor_correcao = c
                
                # threshold para aceitar a correção
                if melhor_correcao and melhor_score >= THRESHOLD_CORRECAO_APRENDIDA:
                    return {
                        "match_encontrado": True,
                        "codigo_krona": melhor_correcao.get('codigo_krona'),
                        "descricao_krona": melhor_correcao.get('descricao_krona'),
                        "score_estrutura": 0,
                        "score_textual": round(melhor_score / 100, 2),
                        "score_total": round(melhor_score / 100, 2),
                        "tipo_match": "MATCH_CORRECAO_APRENDIDA",
                        "revisao_manual": False,
                        "motivo_match": f"CORRECAO_HUMANA_APRENDIDA(sim={melhor_score}%)",
                    }
            except ImportError:
                # fallback para igualdade exata se rapidfuzz nao disponível
                for c in correcoes:
                    desc_correcao = str(c.get('descricao_oc', '')).upper().strip()
                    if desc_correcao and desc_correcao == descricao_item:
                        return {
                            "match_encontrado": True,
                            "codigo_krona": c.get('codigo_krona'),
                            "descricao_krona": c.get('descricao_krona'),
                            "score_estrutura": 0,
                            "score_textual": 1.0,
                            "score_total": 1.0,
                            "tipo_match": "MATCH_CORRECAO_APRENDIDA",
                            "revisao_manual": False,
                            "motivo_match": "CORRECAO_HUMANA_APRENDIDA",
                        }
    except Exception:
        pass  # nao bloqueia o fluxo principal

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
    # PRIORIDADE 1.5 — BRASAL
    # Match direto por código Brasal usando tabela DE/PARA
    # Equivalente ao MRV mas para OCs da Brasal/Closer
    # =========================================================
    if indice_brasal:
        match_brasal = match_por_codigo_brasal(item, indice_brasal)
        if match_brasal:
            return match_brasal

    # =========================================================
    # PRIORIDADE 2 — MATCH POR DESCRICAO
    # Para clientes sem tabela DE/PARA (ex: UAU/GPL, Krona direto)
    # Usa limpeza de descricao + filtro por categoria e diametro
    # =========================================================
    match_desc = match_por_descricao(item, base_krona)
    if match_desc.get("match_encontrado"):
        score_desc = match_desc.get("score_total", 0)
        # se score alto, retorna direto
        if score_desc >= 0.80:
            return match_desc
        # score baixo — tenta motor semantico antes
        try:
            from motor_semantico import obter_motor
            motor = obter_motor()
            if not motor.pronto:
                motor.indexar(base_krona)
            descricao = (item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
            descricao = str(descricao).replace("\n", " ").strip()
            if descricao:
                resultado_semantico = motor.match(descricao)
                score_sem = resultado_semantico.get("score_total", 0)
                # usa semantico se for melhor que o fuzzy
                if resultado_semantico.get("match_encontrado") and score_sem > score_desc:
                    resultado_semantico["via_motor_semantico"] = True
                    return resultado_semantico
        except Exception as e:
            print(f"[MATCHER] Motor semantico indisponivel: {e}")
        # semantico nao melhorou — retorna fuzzy mesmo
        return match_desc

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
        # PRIORIDADE IA — tentar Claude API antes de desistir
        if IA_DISPONIVEL and ia_disponivel():
            descricao_busca = (
                item.get("descricao_oc")
                or item.get("descricao_reconstruida")
                or ""
            )
            # montar lista de candidatos para o Claude
            candidatos_ia = df.head(MAX_CANDIDATOS_IA if "MAX_CANDIDATOS_IA" in dir() else 15).apply(
                lambda r: {
                    "codigo_krona":   str(r.get("codigo_krona", "")),
                    "descricao_krona": str(r.get("descricao_krona", "")),
                }, axis=1
            ).tolist()

            sugestao_ia = ia_sugerir_match(descricao_busca, candidatos_ia)

            if sugestao_ia:
                cod_ia    = sugestao_ia.get("codigo_krona")
                confianca = sugestao_ia.get("confianca", "media")
                cadastro  = buscar_cadastro_krona_por_codigo(cod_ia, base_krona) if cod_ia else None

                # confiança "nenhuma" → não há sugestão válida, cai no SEM_MATCH
                if confianca == "nenhuma" or not cadastro:
                    pass  # continua para o bloco SEM_MATCH abaixo
                else:
                    return {
                        "match_encontrado": True,
                        "codigo_krona": cadastro.get("codigo_krona"),
                        "descricao_krona": cadastro.get("descricao_krona"),
                        "descricao_krona_normalizada": cadastro.get("descricao_normalizada"),
                        "linha_krona_match": cadastro.get("linha_krona"),
                        "familia_krona_match": cadastro.get("familia_krona"),
                        "unidade_venda_krona": cadastro.get("unidade_venda"),
                        "quantidade_embalagem_krona": cadastro.get("quantidade_embalagem"),
                        "score_estrutura": score_melhor,
                        "score_textual": score_melhor,
                        "score_total": score_melhor,
                        "tipo_match": "MATCH_IA",
                        "revisao_manual": True,  # operador SEMPRE confirma
                        "motivo_match": sugestao_ia.get("justificativa", "MATCH_IA"),
                        "confianca_ia": confianca,
                        "justificativa_ia": sugestao_ia.get("justificativa", ""),
                        "categoria_krona": cadastro.get("categoria_detectada"),
                        "eh_tubo_krona": cadastro.get("eh_tubo"),
                        "diametro_krona_mm": obter_diametro_krona(cadastro),
                        "comprimento_krona_m": obter_comprimento_krona(cadastro),
                    }

        _resultado_sem_match = {
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

        # tenta motor semantico antes de retornar SEM_MATCH
        try:
            from motor_semantico import obter_motor
            motor = obter_motor()
            if not motor.pronto:
                motor.indexar(base_krona)
            descricao = (item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
            descricao = str(descricao).replace("\n", " ").strip()
            if descricao:
                resultado_semantico = motor.match(descricao)
                if resultado_semantico.get("match_encontrado"):
                    resultado_semantico["via_motor_semantico"] = True
                    return resultado_semantico
        except Exception as e:
            print(f"[MATCHER] Motor semantico indisponivel: {e}")

        # shadow mode (fallback)
        try:
            from shadow_mode import registrar_shadow
            registrar_shadow(item, _resultado_sem_match, base_krona)
        except Exception:
            pass
        return _resultado_sem_match

    _resultado_tradicional = {
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

    # se score baixo, tenta motor semantico antes de retornar TRADICIONAL
    if score_melhor < 0.70:
        try:
            from motor_semantico import obter_motor
            motor = obter_motor()
            if not motor.pronto:
                motor.indexar(base_krona)
            descricao = (item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
            descricao = str(descricao).replace("\n", " ").strip()
            if descricao:
                resultado_semantico = motor.match(descricao)
                if resultado_semantico.get("match_encontrado"):
                    resultado_semantico["via_motor_semantico"] = True
                    return resultado_semantico
        except Exception as e:
            print(f"[MATCHER] Motor semantico indisponivel: {e}")

    return _resultado_tradicional


# ============================================================
# LOTE + REGRA DE QUANTIDADE
# ============================================================

def match_lote_itens(df_oc, base_krona=None, indice_mrv=None, indice_brasal=None):
    if base_krona is None:
        base_krona = carregar_base_krona()

    if indice_mrv is None:
        indice_mrv = carregar_indice_mrv()

    if indice_brasal is None:
        indice_brasal = carregar_base_brasal()

    resultados = []

    for _, row in df_oc.iterrows():
        item = row.to_dict()

        resultado = match_item_oc(item, base_krona, indice_mrv, indice_brasal)

        final = {**item, **resultado}

        # 🔥 REGRA DE NEGÓCIO
        final = ajustar_quantidade_tubo(final)

        resultados.append(final)

    return pd.DataFrame(resultados)