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


CAMINHO_BASE_KRONA = CAMINHO_BASE_KRONA_FINAL
# caminho lido do config, sem valor fixo no codigo
CAMINHO_BASE_MRV = os.path.join(BASE_DIR, "dados", "base_mrv.csv")

# ============================================================
# CÓDIGOS EXCLUÍDOS DO MATCH AUTOMÁTICO
# Produtos que não existem mais no catálogo ativo ou que causam
# matches incorretos. Adicione aqui quando identificar problemas.
# ============================================================

# ============================================================
# MAPA DIRETO DE JUNÇÃO — evita erros do rapidfuzz
# Chave: "JUNCAO {TIPO} {SERIE} {DIAM}" → codigo_krona
# ============================================================
MAPA_JUNCAO_DIRETO = {
    # SÉRIE NORMAL (PRIM/SEC na Krona)
    "JUNCAO SIMPLES NORMAL DN40":        626,
    "JUNCAO SIMPLES NORMAL 40X40":       626,
    "JUNCAO SIMPLES NORMAL DN50":        627,
    "JUNCAO SIMPLES NORMAL 50X50":       627,
    "JUNCAO SIMPLES NORMAL DN75":        628,
    "JUNCAO SIMPLES NORMAL 75X75":       628,
    "JUNCAO SIMPLES NORMAL DN100":       629,
    "JUNCAO SIMPLES NORMAL 100X100":     629,
    "JUNCAO SIMPLES NORMAL DN150":       630,
    "JUNCAO SIMPLES NORMAL 150X150":     630,
    "JUNCAO SIMPLES NORMAL 75X50":       638,
    "JUNCAO SIMPLES NORMAL 100X50":      639,
    "JUNCAO SIMPLES NORMAL 100X75":      640,
    "JUNCAO SIMPLES NORMAL 150X100":     641,
    "JUNCAO INVERTIDA NORMAL 75X50":     700,
    "JUNCAO INVERTIDA NORMAL 100X50":    701,
    "JUNCAO INVERTIDA NORMAL 100X75":    702,
    "JUNCAO INVERTIDA NORMAL 75X75":     704,
    "JUNCAO DUPLA NORMAL 75X75":         708,
    "JUNCAO INVERTIDA NORMAL 100X100":   709,
    "JUNCAO DUPLA NORMAL 100X100":       710,
    # SÉRIE REFORÇADA
    "JUNCAO SIMPLES REFORCADA DN40":    1427,
    "JUNCAO SIMPLES REFORCADA DN50":    1428,
    "JUNCAO SIMPLES REFORCADA DN75":    1429,
    "JUNCAO SIMPLES REFORCADA DN100":   1430,
    "JUNCAO SIMPLES REFORCADA DN150":   1431,
    "JUNCAO SIMPLES REFORCADA 75X50":   1433,
    "JUNCAO SIMPLES REFORCADA 100X50":  1434,
    "JUNCAO SIMPLES REFORCADA 100X75":  1435,
    "JUNCAO SIMPLES REFORCADA 150X100": 1436,
    "JUNCAO DUPLA REFORCADA DN100":     1426,
}


def _normalizar_chave_juncao(descricao):
    """Normaliza descricao de JUNCAO para chave do MAPA_JUNCAO_DIRETO."""
    d = str(descricao or "").upper()
    serie = "REFORCADA" if re.search(r"REFOR[CÇ]|REFOC|\bSR\b", d) else "NORMAL"
    tipo = "SIMPLES"
    if re.search(r"INVERT", d): tipo = "INVERTIDA"
    elif re.search(r"DUPLA", d): tipo = "DUPLA"
    # extrair pares DxD ou D X D primeiro
    pares = re.findall(r"DN(\d{2,3})[Xx](\d{2,3})", d) or re.findall(r"(\d{2,3})\s*[Xx]\s*(\d{2,3})", d)
    if pares:
        nums = [pares[0][0], pares[0][1]]
    else:
        nums = [n for n in re.findall(r"(\d{2,3})(?:MM|\b)", d)
                if n not in ("45", "90") and int(n) <= 300]
    if len(nums) >= 2:
        diam = f"{nums[0]}X{nums[1]}"
    elif len(nums) == 1:
        diam = f"DN{nums[0]}"
    else:
        diam = ""
    return f"JUNCAO {tipo} {serie} {diam}".strip()


# ============================================================
# MAPA DIRETO DE TE ESGOTO — evita erros do rapidfuzz
# ============================================================
MAPA_TE_ESGOTO_DIRETO = {
    # SÉRIE NORMAL (PRIM/SEC)
    "TE SIMPLES NORMAL DN40":       658,
    "TE SIMPLES NORMAL DN50":       659,
    "TE SIMPLES NORMAL 50X50":      659,
    "TE SIMPLES NORMAL DN75":       660,
    "TE SIMPLES NORMAL 75X75":      660,
    "TE SIMPLES NORMAL DN100":      661,
    "TE SIMPLES NORMAL 100X100":    661,
    "TE SIMPLES NORMAL DN150":      662,
    "TE SIMPLES NORMAL 150X150":    662,
    "TE REDUCAO NORMAL 75X50":      663,
    "TE REDUCAO NORMAL 100X50":     664,
    "TE REDUCAO NORMAL 100X75":     665,
    "TE REDUCAO NORMAL 150X100":    666,
    "TE INSPECAO NORMAL 100X75":    728,
    # SÉRIE REFORÇADA
    "TE SIMPLES REFORCADA DN40":   1456,
    "TE SIMPLES REFORCADA DN50":   1457,
    "TE SIMPLES REFORCADA DN75":   1458,
    "TE SIMPLES REFORCADA DN100":  1459,
    "TE SIMPLES REFORCADA DN150":  1460,
    "TE REDUCAO REFORCADA 75X50":  1462,
    "TE REDUCAO REFORCADA 100X50": 1463,
    "TE SIMPLES REFORCADA 100X50":  1463,  # SR sem palavra REDUCAO
    "TE REDUCAO REFORCADA 100X75": 1464,
    "TE REDUCAO REFORCADA 150X100":1465,
    "TE INSPECAO REFORCADA 75X75": 1467,
    "TE INSPECAO REFORCADA 100X75":1468,
    "TE INSPECAO REFORCADA 150X100":1469,
}


# ============================================================
# MAPA DIRETO DE REDUÇÃO EXCÊNTRICA ESGOTO
# ============================================================
MAPA_REDUCAO_ESGOTO_DIRETO = {
    # SÉRIE NORMAL (PRIM)
    "REDUCAO NORMAL 75X50":   654,
    "REDUCAO NORMAL 100X50":  655,
    "REDUCAO NORMAL 100X75":  656,
    "REDUCAO NORMAL 150X100": 657,
    "REDUCAO NORMAL 200X150": 724,
    # SÉRIE REFORÇADA
    "REDUCAO REFORCADA 75X50":   1450,
    "REDUCAO REFORCADA 100X75":  1452,
    "REDUCAO REFORCADA 150X100": 1453,
    "REDUCAO REFORCADA 200X150": 1451,
}


def _normalizar_chave_te_esgoto(descricao):
    """Normaliza descricao de TE ESGOTO para chave do MAPA_TE_ESGOTO_DIRETO."""
    import re
    d = str(descricao or "").upper()
    serie = "REFORCADA" if re.search(r"REFOR[CÇ]|REFOC|\bSR\b", d) else "NORMAL"
    tipo = "SIMPLES"
    if re.search(r"REDU[CÇ]|\bRED\b", d): tipo = "REDUCAO"
    elif re.search(r"INSPEC", d):  tipo = "INSPECAO"
    # pares: DN75X50, 100x50, 100 X 50
    pares = re.findall(r"DN(\d{2,3})[Xx](\d{2,3})", d) or re.findall(r"(\d{2,3})\s*[Xx]\s*(\d{2,3})", d)
    if pares:
        nums = [pares[0][0], pares[0][1]]
    else:
        nums = [n for n in re.findall(r"(\d{2,3})(?:MM|\b)", d)
                if n not in ("45", "90") and int(n) <= 300]
    diam = f"{nums[0]}X{nums[1]}" if len(nums) >= 2 else (f"DN{nums[0]}" if nums else "")
    return f"TE {tipo} {serie} {diam}".strip()


def _normalizar_chave_reducao_esgoto(descricao):
    """Normaliza descricao de REDUÇÃO EXCÊNTRICA ESGOTO para chave do mapa."""
    import re
    d = str(descricao or "").upper()
    serie = "REFORCADA" if re.search(r"REFOR[CÇ]|REFOC|\bSR\b", d) else "NORMAL"
    pares = re.findall(r"DN(\d{2,3})[Xx](\d{2,3})", d) or re.findall(r"(\d{2,3})\s*[Xx]\s*(\d{2,3})", d)
    if pares:
        nums = [pares[0][0], pares[0][1]]
    else:
        nums = [n for n in re.findall(r"(\d{2,3})(?:MM|\b)", d)
                if n not in ("45", "90") and int(n) <= 300]
    diam = f"{nums[0]}X{nums[1]}" if len(nums) >= 2 else ""
    return f"REDUCAO {serie} {diam}".strip()


CODIGOS_EXCLUIDOS_MATCH = {
    "784",   # TORNEIRA PARA JARDIM PRETA/PRETA — nao existe no XLSX de produtos
             # o correto e 786 (SLIM) ou 781 (ESF)
    "1750",  # TUBO PVC SOLD 25MM PY — linha PY especial, nao usar no match
    "1758",  # TUBO PVC ESG DN40 PY — linha PY especial
    "1759",  # TUBO PVC ESG DN50 PY — linha PY especial
    "1761",  # TUBO PVC ESG DN100 PY — linha PY especial
}


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


def limpar_descricao_para_match(descricao):
    texto = str(descricao or "").upper().strip()
    texto = _PREFIXOS_RUIDO.sub("", texto)
    texto = _NORMAS.sub("", texto)
    # trata o grau ° como separador para nao juntar angulo com dimensao
    # ex: "90°X25MM" → "90 X25MM" → tokens "90" e "25" separados
    texto = texto.replace("°", " ")
    texto = re.sub(r"[;/|]+", " ", texto)
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


def filtrar_candidatos_krona(base_krona, categoria, diametro_mm, material=None, subcategoria=None):
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

    return base_krona


def match_por_descricao(item, base_krona):
    SCORE_MINIMO_DESCRICAO = 0.45

    descricao_raw = (
        item.get("descricao_oc")
        or item.get("descricao_reconstruida")
        or ""
    )

    descricao_limpa = limpar_descricao_para_match(descricao_raw)
    categoria    = extrair_categoria_da_descricao(descricao_limpa)
    diametro     = extrair_diametro_da_descricao(descricao_limpa)
    material     = extrair_material_da_descricao(descricao_limpa)
    subcategoria = extrair_subcategoria_da_descricao(descricao_limpa)

    # lookup direto para TE ESGOTO
    if categoria == "TE" and subcategoria in ("ESGOTO", "REFORCADA"):
        chave = _normalizar_chave_te_esgoto(descricao_limpa)
        codigo_direto = MAPA_TE_ESGOTO_DIRETO.get(chave)
        if codigo_direto:
            cadastro = buscar_cadastro_krona_por_codigo(str(codigo_direto), base_krona)
            if cadastro:
                return {
                    "match_encontrado": True,
                    "codigo_krona": cadastro.get("codigo_krona"),
                    "descricao_krona": cadastro.get("descricao_krona"),
                    "descricao_krona_normalizada": cadastro.get("descricao_normalizada"),
                    "linha_krona_match": cadastro.get("linha_krona"),
                    "familia_krona_match": cadastro.get("familia_krona"),
                    "unidade_venda_krona": cadastro.get("unidade_venda"),
                    "quantidade_embalagem_krona": cadastro.get("quantidade_embalagem"),
                    "score_estrutura": 1,
                    "score_textual": 1.0,
                    "score_total": 1.0,
                    "tipo_match": "MATCH_DESCRICAO",
                    "revisao_manual": False,
                    "motivo_match": f"LOOKUP_TE({chave})",
                    "categoria_krona": cadastro.get("categoria_detectada"),
                    "eh_tubo_krona": cadastro.get("eh_tubo"),
                    "diametro_krona_mm": obter_diametro_krona(cadastro),
                    "comprimento_krona_m": obter_comprimento_krona(cadastro),
                }

    # lookup direto para REDUCAO EXCENTRICA ESGOTO
    if categoria == "REDUCAO" and subcategoria in ("ESGOTO", "REFORCADA"):
        chave = _normalizar_chave_reducao_esgoto(descricao_limpa)
        codigo_direto = MAPA_REDUCAO_ESGOTO_DIRETO.get(chave)
        if codigo_direto:
            cadastro = buscar_cadastro_krona_por_codigo(str(codigo_direto), base_krona)
            if cadastro:
                return {
                    "match_encontrado": True,
                    "codigo_krona": cadastro.get("codigo_krona"),
                    "descricao_krona": cadastro.get("descricao_krona"),
                    "descricao_krona_normalizada": cadastro.get("descricao_normalizada"),
                    "linha_krona_match": cadastro.get("linha_krona"),
                    "familia_krona_match": cadastro.get("familia_krona"),
                    "unidade_venda_krona": cadastro.get("unidade_venda"),
                    "quantidade_embalagem_krona": cadastro.get("quantidade_embalagem"),
                    "score_estrutura": 1,
                    "score_textual": 1.0,
                    "score_total": 1.0,
                    "tipo_match": "MATCH_DESCRICAO",
                    "revisao_manual": False,
                    "motivo_match": f"LOOKUP_REDUCAO({chave})",
                    "categoria_krona": cadastro.get("categoria_detectada"),
                    "eh_tubo_krona": cadastro.get("eh_tubo"),
                    "diametro_krona_mm": obter_diametro_krona(cadastro),
                    "comprimento_krona_m": obter_comprimento_krona(cadastro),
                }

    # lookup direto para JUNCAO — evita erros do rapidfuzz em descricoes similares
    if categoria == "JUNCAO":
        chave = _normalizar_chave_juncao(descricao_limpa)
        codigo_direto = MAPA_JUNCAO_DIRETO.get(chave)
        if codigo_direto:
            cadastro = buscar_cadastro_krona_por_codigo(str(codigo_direto), base_krona)
            if cadastro:
                return {
                    "match_encontrado": True,
                    "codigo_krona": cadastro.get("codigo_krona"),
                    "descricao_krona": cadastro.get("descricao_krona"),
                    "descricao_krona_normalizada": cadastro.get("descricao_normalizada"),
                    "linha_krona_match": cadastro.get("linha_krona"),
                    "familia_krona_match": cadastro.get("familia_krona"),
                    "unidade_venda_krona": cadastro.get("unidade_venda"),
                    "quantidade_embalagem_krona": cadastro.get("quantidade_embalagem"),
                    "score_estrutura": 1,
                    "score_textual": 1.0,
                    "score_total": 1.0,
                    "tipo_match": "MATCH_DESCRICAO",
                    "revisao_manual": False,
                    "motivo_match": f"LOOKUP_JUNCAO({chave})",
                    "categoria_krona": cadastro.get("categoria_detectada"),
                    "eh_tubo_krona": cadastro.get("eh_tubo"),
                    "diametro_krona_mm": obter_diametro_krona(cadastro),
                    "comprimento_krona_m": obter_comprimento_krona(cadastro),
                }

    candidatos = filtrar_candidatos_krona(base_krona, categoria, diametro, material, subcategoria)

    # para JUNCAO com dois diametros (ex: 100X75), diametro_final_mm eh NaN na base
    # filtrar por AMBOS os diametros presentes no texto (AND, nao OR)
    if categoria == "JUNCAO":
        # extrair numeros 2-3 digitos da descricao OC, excluindo angulos (45, 90)
        nums_oc = [n for n in re.findall(r"\b(\d{2,3})\b", descricao_limpa)
                   if n not in ("45", "90")]

        mask_sem_diam = candidatos["diametro_final_mm"].isna() & candidatos["diametro_mm"].isna()
        candidatos_sem_diam = candidatos[mask_sem_diam]
        candidatos_com_diam = candidatos[~mask_sem_diam]

        if len(nums_oc) >= 2 and not candidatos_sem_diam.empty:
            # OC tem dois diametros — filtrar por AND (ambos devem estar no texto)
            desc_k = candidatos_sem_diam["descricao_krona"].fillna("").str.upper()
            mask_and = pd.Series([True] * len(candidatos_sem_diam), index=candidatos_sem_diam.index)
            for num in nums_oc[:2]:
                mask_and = mask_and & desc_k.str.contains(rf"\b{num}\b", regex=True, na=False)
            filtrados_and = candidatos_sem_diam[mask_and]

            if not filtrados_and.empty:
                candidatos = filtrados_and  # apenas os que tem ambos os diametros
            else:
                # fallback: pelo menos um diametro
                mask_or = pd.Series([False] * len(candidatos_sem_diam), index=candidatos_sem_diam.index)
                for num in nums_oc[:2]:
                    mask_or = mask_or | desc_k.str.contains(rf"\b{num}\b", regex=True, na=False)
                filtrados_or = candidatos_sem_diam[mask_or]
                if not filtrados_or.empty:
                    candidatos = pd.concat([candidatos_com_diam, filtrados_or])
                elif not candidatos_com_diam.empty:
                    candidatos = candidatos_com_diam

        elif len(nums_oc) == 1 and not candidatos_sem_diam.empty:
            # OC tem um diametro — filtrar sem diametro por texto
            desc_k = candidatos_sem_diam["descricao_krona"].fillna("").str.upper()
            mask_n = desc_k.str.contains(rf"\b{nums_oc[0]}\b", regex=True, na=False)
            filtrados = candidatos_sem_diam[mask_n]
            if not filtrados.empty:
                candidatos = pd.concat([candidatos_com_diam, filtrados])
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
    # extrair diametros da OC para bonus de match exato
    nums_oc_score = set(n for n in re.findall(r"\b(\d{2,3})\b", descricao_limpa)
                        if n not in ("45", "90"))

    for _, row in candidatos.iterrows():
        cand = row.to_dict()
        desc_krona = str(cand.get("descricao_normalizada") or cand.get("descricao_krona") or "").upper()
        score_txt = rapidfuzz_fuzz.token_sort_ratio(descricao_limpa, desc_krona) / 100.0
        score_str = rapidfuzz_fuzz.ratio(descricao_limpa, desc_krona) / 100.0
        score_final = round((score_txt * 0.70) + (score_str * 0.30), 4)

        # bonus para JUNCAO: cada diametro da OC que esta no produto Krona
        if categoria == "JUNCAO" and nums_oc_score:
            nums_krona = set(re.findall(r"\b(\d{2,3})\b", desc_krona))
            matches_diam = len(nums_oc_score & nums_krona)
            bonus = matches_diam * 0.08  # +0.08 por diametro correto
            score_final = round(min(score_final + bonus, 1.0), 4)

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