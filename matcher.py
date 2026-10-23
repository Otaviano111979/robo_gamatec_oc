import os
import re
import pandas as pd
from rapidfuzz import fuzz as rapidfuzz_fuzz

from config import CAMINHO_BASE_KRONA_FINAL, BASE_DIR, USAR_IA
from base_mrv_loader import carregar_base_mrv
from matcher_mrv import match_por_codigo_mrv
from base_brasal_loader import carregar_base_brasal
from matcher_brasal import match_por_codigo_brasal
from matcher_tabela_cliente import (
    estimar_fator_preco,
    match_tabela_cliente,
)
from regra_quantidade import ajustar_quantidade_tubo
from enriquecimento_krona import enriquecer_base_krona
from normalizador import detectar_categoria, detectar_eh_tubo, normalizar_descricao

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

# correcoes pontuais de comprimento confirmadas contra o catalogo
COMPRIMENTOS_CORRIGIDOS = {
    "164": 3.0,  # TUBO PPR PN25 110MMX3M: matriz 2,98 m, catalogo 3 m
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

    # a base foi gerada quando qualquer descricao com "TUBO" virava tubo;
    # recalcula para luvas/acessorios "P/TUBO" nao entrarem na conversao de metros
    texto_classificacao = df["descricao_normalizada"].fillna("").astype(str)
    sem_texto = texto_classificacao.str.strip().eq("")
    if sem_texto.any():
        texto_classificacao.loc[sem_texto] = df.loc[sem_texto, "descricao_krona"].fillna("").map(normalizar_descricao)
    df["eh_tubo"] = texto_classificacao.map(detectar_eh_tubo)
    df["categoria_detectada"] = texto_classificacao.map(detectar_categoria)

    # comprimento nominal confirmado no catalogo prevalece sobre a matriz
    for codigo, comprimento in COMPRIMENTOS_CORRIGIDOS.items():
        mascara = df["codigo_krona"].astype(str).str.strip().str.lstrip("0").replace("", "0") == codigo
        df.loc[mascara, "comprimento_final_m"] = comprimento

    # correcao em runtime: preencher categoria_detectada para produtos sem categoria
    # JUNCAO nao estava no normalizador original — corrigido aqui sem precisar regenerar a base
    sem_cat = df["categoria_detectada"].isna()
    if sem_cat.sum() > 0:
        desc = df.loc[sem_cat, "descricao_krona"].fillna("").str.upper()
        df.loc[sem_cat & desc.str.contains("JUNCAO|JUNC", na=False), "categoria_detectada"] = "JUNCAO"

        sem_cat2 = df["categoria_detectada"].isna()
        desc2 = df.loc[sem_cat2, "descricao_krona"].fillna("").str.upper()
        df.loc[sem_cat2 & desc2.str.contains("REDUC", na=False), "categoria_detectada"] = "REDUCAO"

    df = enriquecer_base_krona(df)

    # categorias que o normalizador original nao cobria (QUADRO, CAIXA...)
    # sao recuperadas da propria descricao para entrarem nos filtros duros.
    vazias = df["categoria_enriquecida"].fillna("").astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])
    if vazias.any():
        df.loc[vazias, "categoria_enriquecida"] = df.loc[vazias, "descricao_krona"].map(
            lambda d: (extrair_categoria_da_descricao(d) or "").upper())

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

# texto padrao que os PDFs ActiveReports repetem no fim de cada item
_RX_BOILERPLATE = re.compile(
    r"\bDEVERAO SER ENVIADOS JUNTAMENTE COM A NF.*$",
    re.IGNORECASE
)

_TABELA_ACENTOS = str.maketrans(
    "ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ",
    "AAAAAEEEEIIIIOOOOOUUUUCN",
)


def _normalizar_texto(texto):
    """Maiusculas, sem acentos e sem o caractere de substituicao dos PDFs."""
    t = str(texto or "").upper().translate(_TABELA_ACENTOS)
    t = t.replace("\ufffd", " ").replace("º", " ").replace("°", " ")
    return re.sub(r"\s+", " ", t).strip()


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
    texto = _normalizar_texto(descricao)
    texto = _PREFIXOS_RUIDO.sub("", texto)
    texto = _NORMAS.sub("", texto)
    texto = _RX_BOILERPLATE.sub("", texto)

    # expansao de abreviacoes — maior impacto em PDFs UAU e SIENGE
    for padrao, substituto in _ABREV_EXPANSAO:
        texto = re.sub(padrao, substituto, texto)

    # sinonimo de catalogo: CPVC na OC = linha ULTRATERM na Krona
    if re.search(r"\bCPVC\b", texto) and "ULTRATERM" not in texto:
        texto = texto.replace("CPVC", "ULTRATERM")

    # grau como separador
    texto = texto.replace("°", " ")

    # remove parenteses e colchetes mas mantem o conteudo
    texto = re.sub(r"[()\[\]]", " ", texto)

    # normaliza espacos
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


_RX_DIAM_PAR_OC = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:MM)?\s*(?:X|×)\s*(?:DN\s*)?(\d{1,3})(?!\d)"
)
_RX_DIAM_MM_OC = re.compile(r"(?<!\d)(\d{1,3})\s*MM\b")
_RX_DN_OC = re.compile(r"\bD\.?N\.?\s*(\d{2,3})(?!\d)")

_ANGULOS = {45, 90, 180}

# A ordem decide apenas empates na mesma posicao do texto.
_CATEGORIAS_OC = [
    ("QUADRO",      r"\bQUADRO\b"),
    ("CAIXA",       r"\bCAIXA\b|\bCX\.?\b"),
    ("ELETRODUTO",  r"\bELETROD(?:UTO)?\b|\bCORRUGAD[OA]\b"),
    ("TUBO",        r"\bTUBO\b"),
    ("JOELHO",      r"\bJOELHO\b|\bCURVA\b"),
    ("TE",          r"\bTEE?\b"),
    ("LUVA",        r"\bLUVA\b"),
    ("BUCHA",       r"\bBUCHA\b"),
    ("REDUCAO",     r"\bREDU(?:CAO|C)\b|\bRED\.?\b"),
    ("ADAPTADOR",   r"\bADAPTADOR\b|\bADAPT\.?\b"),
    ("CAP",         r"\bCAP\b"),
    ("REGISTRO",    r"\bREGISTRO\b|\bREG\.?\b"),
    ("VALVULA",     r"\bVALVULA\b|\bVALV\.?\b"),
    ("JUNCAO",      r"\bJUNCAO\b|\bJUNC\.?\b"),
    ("UNIAO",       r"\bUNIAO\b"),
    ("FLANGE",      r"\bFLANGE\b"),
    ("CONDULETE",   r"\bCONDULETE\b"),
    ("TAMPA",       r"\bTAMPA\b"),
    ("SIFAO",       r"\bSIFAO\b"),
    ("RALO",        r"\bRALO\b"),
    ("GRELHA",      r"\bGRELHA\b"),
    ("ENGATE",      r"\bENGATE\b"),
    ("COLAR",       r"\bCOLAR\b"),
    ("PROLONGAMENTO", r"\bPROLONGAMENTO\b"),
    ("TORNEIRA",    r"\bTORNEIRA\b"),
    ("FITA",        r"\bFITA\b"),
    ("ADESIVO",     r"\bADESIVO\b|\bCOLA\b"),
    ("PASTA",       r"\bPASTA\b"),
]


def extrair_diametros_da_descricao(descricao, categoria=None):
    """Todos os diametros citados na OC, sem confundir angulo com medida."""
    texto = _normalizar_texto(descricao)
    cat = str(categoria or extrair_categoria_da_descricao(texto) or "").upper()
    diametros = set()

    for m in _RX_DIAM_PAR_OC.finditer(texto):
        a, b = int(m.group(1)), int(m.group(2))
        if cat in ("JOELHO", "CURVA") and a in _ANGULOS and b >= 10:
            diametros.add(b)
        elif cat == "TE" and a == 90 and b >= 10:
            diametros.add(b)
        else:
            diametros.update({a, b})

    for m in _RX_DN_OC.finditer(texto):
        diametros.add(int(m.group(1)))

    for m in _RX_DIAM_MM_OC.finditer(texto):
        valor = int(m.group(1))
        if cat in ("JOELHO", "CURVA") and valor in _ANGULOS:
            continue
        diametros.add(valor)

    return {d for d in diametros if 10 <= d <= 1000}


def extrair_diametro_da_descricao(descricao):
    """Diametro principal: o maior citado (60X50 -> 60)."""
    diametros = extrair_diametros_da_descricao(descricao)
    return float(max(diametros)) if diametros else None


def extrair_angulo_da_descricao(descricao, categoria=None):
    texto = _normalizar_texto(descricao)
    cat = str(categoria or extrair_categoria_da_descricao(texto) or "").upper()
    if cat not in ("JOELHO", "CURVA", "TE"):
        return None
    for angulo in (45, 90, 180):
        if re.search(rf"(?<!\d){angulo}(?!\d)", texto):
            return angulo
    return None


def _quadro_tamanho_do_texto(texto):
    texto = _normalizar_texto(texto)
    padroes = (
        r"(\d{1,3})\s*D\s*/\s*\d{1,3}\s*N",
        r"(\d{1,3})\s*DIN\b",
        r"(\d{1,3})\s*DISJ",
        r"(\d{1,3})\s*D\b",
    )
    for padrao in padroes:
        m = re.search(padrao, texto)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def _barramento_do_texto(texto):
    t = _normalizar_texto(texto)
    if re.search(r"\bSEM\s+BARRAMENTO\b|\bS/\s*BARRAMENTO\b", t):
        return "SEM"
    if re.search(r"\bCOM\s+BARRAMENTO\b|\bC/\s*BARRAMENTO\b|\bC\s+BARRAMENTO\b", t):
        return "COM"
    return None


def _reducao_do_texto(texto):
    t = _normalizar_texto(texto)
    return bool(re.search(r"\bREDU|\bRED\b|\bRED\.", t))


def _curta_longa_do_texto(texto):
    t = _normalizar_texto(texto)
    if re.search(r"\bCURT[OA]\b", t):
        return "CURTA"
    if re.search(r"\bLONG[OA]\b", t):
        return "LONGA"
    return None


def _correr_do_texto(texto):
    return bool(re.search(r"\bCORRER\b", _normalizar_texto(texto)))


def extrair_categoria_da_descricao(descricao):
    texto = _normalizar_texto(descricao)
    achados = []
    for ordem, (categoria, padrao) in enumerate(_CATEGORIAS_OC):
        m = re.search(padrao, texto)
        if m:
            achados.append((m.start(), ordem, categoria))
    return min(achados)[2] if achados else None


def extrair_material_da_descricao(descricao):
    texto = _normalizar_texto(descricao)
    if re.search(r"\bPPR\b|\bPP[\s-]?R\b", texto): return "PPR"
    if re.search(r"\bCPVC\b", texto):       return "CPVC"
    # linha ULTRATERM do catalogo Krona = CPVC
    if re.search(r"ULTRA[\s\-]?TERM", texto): return "CPVC"
    if re.search(r"\bPEAD\b", texto):       return "PEAD"
    if re.search(r"\bPOLIETILENO\b", texto): return "PEAD"
    # PVC nao e suficiente para diferenciar — nao filtra por material PVC
    # pois na base Krona os produtos PVC nem sempre tem "PVC" no nome
    return None


def _linha_do_texto(texto):
    """Linha do produto: esgoto, soldavel, roscavel, ultratech/CPVC ou PPR."""
    t = _normalizar_texto(texto)
    if re.search(r"\bESGOTO\b|\bESG\.?\b|\bPRIM\.?\b|\bSEC\.?\b|\bSN\b", t):
        return "ESGOTO"
    if re.search(r"\bROSC", t):
        return "ROSCAVEL"
    if re.search(r"\bSOLD|\bSOLDAVEL\b", t):
        return "SOLDAVEL"
    if re.search(r"ULTRA[\s-]?TERM|\bCPVC\b", t):
        return "ULTRATERM"
    if re.search(r"\bPPR\b|\bPP[\s-]?R\b", t):
        return "PPR"
    if re.search(r"\bPEAD\b", t):
        return "PEAD"
    return None


def _serie_do_texto(texto):
    t = _normalizar_texto(texto)
    # "REFOR" cobre tambem descricoes antigas com acento corrompido no CSV
    # e o caso "SERIEREFORCADA" (sem espaco antes de REFORCADA)
    if re.search(r"REFOR|\bSR\b", t):
        return "REFORCADA"
    if re.search(r"\bSN\b|\bNORMAL\b|\bPRIM\.?\b|\bSEC\.?\b|\bESGOTO\b|\bESG\.?\b", t):
        return "NORMAL"
    return None


def extrair_subcategoria_da_descricao(descricao):
    """
    Detecta subcategoria do produto para filtrar candidatos na base Krona.

    Série Reforçada → REFORCADA/SR
    Série Normal   → SN, ESGOTO, PRIM (DN>=50) ou SEC (DN40)
    Água fria      → SOLDAVEL / ROSCAVEL / ULTRATERM
    """
    texto = _normalizar_texto(descricao)

    if re.search(r"REFOR|\bSR\b", texto):
        return "REFORCADA"

    linha = _linha_do_texto(texto)
    if linha:
        return linha
    return None


def _categoria_candidato(cand):
    for campo in ("categoria_enriquecida", "categoria_detectada"):
        valor = str(cand.get(campo) or "").strip().upper()
        if valor and valor not in ("NAN", "NONE"):
            return valor
    return extrair_categoria_da_descricao(cand.get("descricao_krona")) or ""


def _familias_compativeis(cat_oc, cat_cand, desc_oc="", desc_cand=""):
    if not cat_oc or not cat_cand:
        return True
    if cat_oc == cat_cand:
        return True
    if cat_oc in ("JOELHO", "CURVA") and cat_cand in ("JOELHO", "CURVA"):
        return True
    if cat_oc in ("REDUCAO", "BUCHA") and cat_cand in ("REDUCAO", "BUCHA"):
        return True
    if {cat_oc, cat_cand} == {"REGISTRO", "VALVULA"}:
        return "ESFERA" in _normalizar_texto(desc_oc) and "ESFERA" in _normalizar_texto(desc_cand)
    return False


def _serie_candidato(cand):
    texto = " ".join(str(cand.get(c) or "") for c in (
        "descricao_krona", "descricao_normalizada", "descricao_aliases"))
    return _serie_do_texto(texto)


def _angulo_candidato(cand):
    texto = " ".join(str(cand.get(c) or "") for c in (
        "descricao_krona", "descricao_normalizada", "descricao_aliases"))
    return extrair_angulo_da_descricao(texto, _categoria_candidato(cand))


def _diametros_candidato(cand):
    categoria = _categoria_candidato(cand)
    diametros = set()
    for campo in ("diametro_final_mm", "diametro_mm", "diametro_pdf_mm", "diametro_pdf_2_mm"):
        try:
            valor = float(cand.get(campo))
        except (TypeError, ValueError):
            continue
        if valor > 0:
            diametros.add(valor)
    for campo in ("descricao_krona", "descricao_normalizada", "descricao_aliases"):
        diametros |= extrair_diametros_da_descricao(cand.get(campo), categoria)
    if categoria in ("JOELHO", "CURVA"):
        diametros -= {float(a) for a in _ANGULOS}
    return diametros


def _candidato_estrutural(cand, categoria=None, diametros=None, subcategoria=None,
                          angulo=None, quadro_tamanho=None, descricao_oc=""):
    """True se o candidato nao contradiz nenhum atributo duro da OC."""
    cat_cand = _categoria_candidato(cand)
    desc_cand = str(cand.get("descricao_krona") or "")
    if not _familias_compativeis(categoria, cat_cand, descricao_oc, desc_cand):
        return False

    linha_oc = _linha_do_texto(descricao_oc)
    linha_cand = _linha_do_texto(desc_cand)
    if linha_oc and linha_cand and linha_oc != linha_cand:
        return False

    diametros = {float(d) for d in (diametros or set()) if d}
    if diametros:
        ds = _diametros_candidato(cand)
        if len(diametros) >= 2:
            if not ds or not diametros <= ds:
                return False
        elif ds and not (diametros & ds):
            return False

    if subcategoria in ("ESGOTO", "REFORCADA"):
        serie = _serie_candidato(cand)
        if subcategoria == "REFORCADA" and serie != "REFORCADA":
            return False
        if subcategoria == "ESGOTO" and serie != "NORMAL":
            return False

    if angulo is not None and categoria in ("JOELHO", "CURVA"):
        angulo_cand = _angulo_candidato(cand)
        if angulo_cand is not None and angulo_cand != angulo:
            return False

    curta_longa_oc = _curta_longa_do_texto(descricao_oc)
    if curta_longa_oc:
        curta_longa_cand = _curta_longa_do_texto(desc_cand)
        if curta_longa_cand and curta_longa_cand != curta_longa_oc:
            return False

    if categoria == "QUADRO":
        texto = " ".join(str(cand.get(c) or "") for c in (
            "descricao_krona", "descricao_aliases"))
        if quadro_tamanho is not None:
            tam_cand = _quadro_tamanho_do_texto(texto)
            if tam_cand is not None and tam_cand != quadro_tamanho:
                return False
        barr_oc = _barramento_do_texto(descricao_oc)
        barr_cand = _barramento_do_texto(texto)
        if barr_oc and barr_cand and barr_oc != barr_cand:
            return False

    return True


def filtrar_candidatos_krona(base_krona, categoria, diametro_mm, material=None,
                             subcategoria=None, item_descricao=None,
                             diametros=None, angulo=None):
    if base_krona is None or base_krona.empty:
        return base_krona

    pool = base_krona.copy()

    # segurança: nunca retorna linha PY como candidato
    # a menos que a descricao da OC mencione explicitamente PY
    if "PY" not in _normalizar_texto(item_descricao):
        mask_nao_py = ~pool["descricao_krona"].fillna("").str.upper().str.contains(
            r"\bPY\b", na=False, regex=True)
        if mask_nao_py.any():
            pool = pool[mask_nao_py]

    # eletroduto/corrugado so entra quando a OC e eletrica
    if not re.search(r"ELETROD|ELETR\b|CORRUGAD|CONDULETE", _normalizar_texto(item_descricao)):
        mask_eletrico = pool["descricao_krona"].fillna("").map(
            lambda d: bool(re.search(r"ELETROD|ELETR\.?\s*CORRUGAD|CORRUGAD", _normalizar_texto(d))))
        filtrado = pool[~mask_eletrico]
        if not filtrado.empty:
            pool = filtrado

    categoria = str(categoria or "").strip().upper()
    if categoria:
        if "categoria_enriquecida" in pool.columns:
            cats = pool["categoria_enriquecida"].fillna("").astype(str).str.upper().str.strip()
        else:
            cats = pool["categoria_detectada"].fillna("").astype(str).str.upper().str.strip()
        vazias = cats.isin(["", "NAN", "NONE"])
        if vazias.any():
            cats = cats.copy()
            cats.loc[vazias] = pool.loc[vazias, "descricao_krona"].map(
                lambda d: (extrair_categoria_da_descricao(d) or "").upper())

        compativeis = {categoria}
        if categoria in ("JOELHO", "CURVA"):
            compativeis |= {"JOELHO", "CURVA"}
        if categoria in ("REDUCAO", "BUCHA"):
            compativeis |= {"REDUCAO", "BUCHA"}

        pool = pool[cats.isin(compativeis)]
        if pool.empty:
            return pool

        if categoria in ("REGISTRO", "VALVULA"):
            exatos = pool[pool["categoria_enriquecida"].fillna("").astype(str).str.upper().str.strip()
                          == categoria]
            if not exatos.empty:
                pool = exatos
            elif "ESFERA" in _normalizar_texto(item_descricao):
                pool = pool[pool["descricao_krona"].fillna("").str.upper().str.contains("ESFERA")]
            if pool.empty:
                return pool

    # luva de correr e luva simples sao produtos diferentes; sem "CORRER"
    # na OC a luva generica/simples e a resposta, nunca a de correr
    if categoria == "LUVA":
        quer_correr = _correr_do_texto(item_descricao)
        tem_correr = pool["descricao_krona"].fillna("").map(_correr_do_texto)
        filtrado = pool[tem_correr] if quer_correr else pool[~tem_correr]
        if not filtrado.empty:
            pool = filtrado

    if diametros is None:
        diametros = extrair_diametros_da_descricao(item_descricao, categoria)
    diametros = {float(d) for d in (diametros or set()) if d}
    if not diametros and diametro_mm is not None:
        try:
            diametros = {float(diametro_mm)}
        except (TypeError, ValueError):
            diametros = set()

    if diametros:
        if len(diametros) >= 2:
            filtrado = pool[pool.apply(
                lambda r: diametros <= _diametros_candidato(r), axis=1)]
        else:
            filtrado = pool[pool.apply(
                lambda r: not _diametros_candidato(r) or bool(diametros & _diametros_candidato(r)),
                axis=1)]
        if not filtrado.empty:
            pool = filtrado

        # OC pede medida unica e nao fala em reducao: peca redutora (25x20)
        # nao substitui a peca reta (25), mesmo com texto parecido
        if (len(diametros) == 1 and categoria in _CATS_DUPLA_MEDIDA
                and not _reducao_do_texto(item_descricao)):
            filtrado = pool[pool.apply(
                lambda r: len(_diametros_candidato(r)) <= 1, axis=1)]
            if not filtrado.empty:
                pool = filtrado

    if material:
        termos = {"CPVC": r"ULTRA|CPVC", "PEAD": r"PEAD|POLIETILENO"}.get(material, material)
        filtrado = pool[pool["descricao_krona"].fillna("").str.upper().str.contains(
            termos, na=False, regex=True)]
        if not filtrado.empty:
            pool = filtrado

    if subcategoria in ("ESGOTO", "REFORCADA"):
        filtrado = pool[pool.apply(
            lambda r: _serie_candidato(r) == ("REFORCADA" if subcategoria == "REFORCADA" else "NORMAL"),
            axis=1)]
        if not filtrado.empty:
            pool = filtrado

    if angulo is not None and categoria in ("JOELHO", "CURVA"):
        filtrado = pool[pool.apply(
            lambda r: _angulo_candidato(r) in (None, angulo), axis=1)]
        if not filtrado.empty:
            pool = filtrado

    curta_longa_oc = _curta_longa_do_texto(item_descricao)
    if curta_longa_oc:
        filtrado = pool[pool.apply(
            lambda r: _curta_longa_do_texto(r.get("descricao_krona")) in (None, curta_longa_oc),
            axis=1)]
        if not filtrado.empty:
            pool = filtrado

    if categoria == "QUADRO":
        tamanho = _quadro_tamanho_do_texto(item_descricao)
        if tamanho is not None:
            filtrado = pool[pool.apply(
                lambda r: _quadro_tamanho_do_texto(
                    " ".join(str(r.get(c) or "") for c in ("descricao_krona", "descricao_aliases"))
                ) in (None, tamanho), axis=1)]
            if not filtrado.empty:
                pool = filtrado

    return pool


def _score_textual_candidato(descricao_limpa, cand):
    melhor = 0.0
    for campo in ("descricao_normalizada", "descricao_krona", "descricao_aliases"):
        texto = _normalizar_texto(cand.get(campo))
        if not texto:
            continue
        score = (
            rapidfuzz_fuzz.token_sort_ratio(descricao_limpa, texto) / 100.0 * 0.70
            + rapidfuzz_fuzz.ratio(descricao_limpa, texto) / 100.0 * 0.30
        )
        melhor = max(melhor, score)
    return round(melhor, 4)


def _resumo_candidatos(registros, limite=3):
    if not registros:
        return ""
    ordenados = sorted(registros, key=lambda r: r.get("score_total", 0), reverse=True)[:limite]
    partes = []
    for r in ordenados:
        codigo = str(r.get("codigo_krona") or "").strip()
        descricao = str(r.get("descricao_krona") or "").strip()
        score = r.get("score_total")
        try:
            score = float(score)
            partes.append(f"{codigo} {descricao} ({score:.2f})")
        except (TypeError, ValueError):
            partes.append(f"{codigo} {descricao}")
    return " | ".join(partes)


def _sugerir_composicao_te(base_krona, diametros):
    """Quando nao existe TE redutor na medida, sugere TE + bucha (nunca aplica)."""
    diametros = {float(d) for d in (diametros or set()) if d}
    if base_krona is None or base_krona.empty or len(diametros) < 2:
        return None

    maior, menor = max(diametros), min(diametros)
    pool = base_krona.copy()
    if "categoria_enriquecida" in pool.columns:
        cats = pool["categoria_enriquecida"].fillna("").astype(str).str.upper().str.strip()
    else:
        cats = pool["categoria_detectada"].fillna("").astype(str).str.upper().str.strip()
    vazias = cats.isin(["", "NAN", "NONE"])
    if vazias.any():
        cats = cats.copy()
        cats.loc[vazias] = pool.loc[vazias, "descricao_krona"].map(
            lambda d: (extrair_categoria_da_descricao(d) or "").upper())

    tes = []
    for _, row in pool[cats == "TE"].iterrows():
        descricao = _normalizar_texto(row.get("descricao_krona"))
        if re.search(r"\bRED\b|REDU", descricao):
            continue
        ds = _diametros_candidato(row)
        if maior in ds and menor not in ds:
            tes.append(row)

    buchas = []
    for _, row in pool[cats == "BUCHA"].iterrows():
        ds = _diametros_candidato(row)
        if {maior, menor} <= ds:
            buchas.append(row)

    if not tes or not buchas:
        return None

    def _ordem_te(row):
        descricao = _normalizar_texto(row.get("descricao_krona"))
        return (0 if "SOLD" in descricao else 1, len(descricao))

    def _ordem_bucha(row):
        descricao = _normalizar_texto(row.get("descricao_krona"))
        return (0 if "CURTA" in descricao else 1, len(descricao))

    te = sorted(tes, key=_ordem_te)[0]
    bucha = sorted(buchas, key=_ordem_bucha)[0]
    cod_te = str(te.get("codigo_krona") or "").strip()
    cod_bucha = str(bucha.get("codigo_krona") or "").strip()
    return {
        "texto": f"{cod_te} {te.get('descricao_krona')} + {cod_bucha} {bucha.get('descricao_krona')}",
        "codigos": [cod_te, cod_bucha],
        "maior": maior,
        "menor": menor,
    }


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
    diametros    = extrair_diametros_da_descricao(descricao_limpa, categoria)
    diametro     = max(diametros) if diametros else None
    material     = extrair_material_da_descricao(descricao_limpa)
    subcategoria = extrair_subcategoria_da_descricao(descricao_limpa)
    angulo       = extrair_angulo_da_descricao(descricao_limpa, categoria)
    linha        = _linha_do_texto(descricao_limpa)
    quadro_tamanho = _quadro_tamanho_do_texto(descricao_limpa) if categoria == "QUADRO" else None

    tokens_desc = [t for t in descricao_limpa.split() if len(t) > 1]
    ancoras = sum((
        categoria is not None,
        bool(diametros),
        subcategoria is not None,
        angulo is not None,
    ))

    candidatos = filtrar_candidatos_krona(
        base_krona, categoria, diametro, material, subcategoria,
        descricao_limpa, diametros=diametros, angulo=angulo,
    )
    if candidatos is None:
        candidatos = base_krona.iloc[0:0]

    if candidatos.empty:
        estruturais = candidatos
    else:
        estruturais = candidatos[candidatos.apply(
            lambda r: _candidato_estrutural(
                r, categoria=categoria, diametros=diametros, subcategoria=subcategoria,
                angulo=angulo, quadro_tamanho=quadro_tamanho, descricao_oc=descricao_limpa,
            ), axis=1)]

    # universo ja restrito pela tabela do cliente: deixa o preco/guarda decidir
    if estruturais.empty and "preco_tabela" in base_krona.columns:
        estruturais = base_krona

    if estruturais.empty:
        registros_revisao = [
            {**row.to_dict(), "score_total": _score_textual_candidato(descricao_limpa, row.to_dict())}
            for _, row in candidatos.head(80).iterrows()
        ]
        composicao = None
        if categoria == "TE" and len(diametros) >= 2:
            composicao = _sugerir_composicao_te(base_krona, diametros)

        resultado = {
            "match_encontrado": False,
            "codigo_krona": None,
            "descricao_krona": None,
            "descricao_krona_normalizada": None,
            "linha_krona_match": None,
            "familia_krona_match": None,
            "unidade_venda_krona": None,
            "quantidade_embalagem_krona": None,
            "score_estrutura": 0,
            "score_textual": 0,
            "score_total": 0,
            "tipo_match": "SEM_MATCH",
            "revisao_manual": True,
            "motivo_match": "SEM_CANDIDATOS_ESTRUTURAIS",
            "categoria_krona": categoria,
            "eh_tubo_krona": None,
            "diametro_krona_mm": None,
            "comprimento_krona_m": None,
            "categoria_oc": categoria,
            "diametros_oc": sorted(diametros),
            "linha_oc": linha,
            "serie_oc": subcategoria,
            "angulo_oc": angulo,
            "quadro_tamanho_oc": quadro_tamanho,
            "candidatos_revisao": _resumo_candidatos(registros_revisao),
            "bloquear_fallback": bool(categoria or subcategoria or angulo),
        }
        if composicao:
            resultado.update({
                "tipo_match": "SUGESTAO_COMPOSICAO",
                "motivo_match": (
                    f"SEM_PRODUTO_UNICO_{composicao['maior']:.0f}X{composicao['menor']:.0f}"
                    "_SUGERIR_COMPOSICAO"
                ),
                "sugestao_composicao": composicao["texto"],
                "candidatos_revisao": composicao["texto"],
            })
        return resultado

    registros = []
    for _, row in estruturais.iterrows():
        cand = row.to_dict()
        score_txt = _score_textual_candidato(descricao_limpa, cand)

        bonus = 0.0
        cat_cand = _categoria_candidato(cand)
        if categoria and cat_cand == categoria:
            bonus += 0.08
        elif categoria and _familias_compativeis(
                categoria, cat_cand, descricao_limpa,
                str(cand.get("descricao_krona") or "")):
            bonus += 0.04
        ds = _diametros_candidato(cand)
        if diametros:
            if diametros <= ds:
                bonus += 0.10 if len(diametros) >= 2 else 0.08
            elif diametros & ds:
                bonus += 0.04
        if angulo is not None and _angulo_candidato(cand) == angulo:
            bonus += 0.06
        if subcategoria in ("ESGOTO", "REFORCADA"):
            serie = _serie_candidato(cand)
            if (subcategoria == "ESGOTO" and serie == "NORMAL") or (
                    subcategoria == "REFORCADA" and serie == "REFORCADA"):
                bonus += 0.04
        if linha and _linha_do_texto(cand.get("descricao_krona")) == linha:
            bonus += 0.04
        if quadro_tamanho is not None:
            tam = _quadro_tamanho_do_texto(" ".join(str(cand.get(c) or "") for c in (
                "descricao_krona", "descricao_aliases")))
            if tam == quadro_tamanho:
                bonus += 0.08

        score_final = round(min(1.0, score_txt + bonus), 4)
        registros.append({**cand, "score_total": score_final, "score_textual": score_txt})

    df_scores = pd.DataFrame(registros).sort_values("score_total", ascending=False)
    melhor = df_scores.iloc[0].to_dict()
    score_melhor = melhor.get("score_total", 0)
    candidato_unico = len(df_scores) == 1

    if candidato_unico and ancoras >= 2:
        SCORE_MINIMO_DESCRICAO = 0.35
    elif len(tokens_desc) < 4:
        SCORE_MINIMO_DESCRICAO = 0.32
    elif categoria and diametros:
        SCORE_MINIMO_DESCRICAO = 0.40
    else:
        SCORE_MINIMO_DESCRICAO = 0.45

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
            "categoria_oc": categoria,
            "diametros_oc": sorted(diametros),
            "linha_oc": linha,
            "serie_oc": subcategoria,
            "angulo_oc": angulo,
            "quadro_tamanho_oc": quadro_tamanho,
            "candidatos_revisao": _resumo_candidatos(registros),
            "bloquear_fallback": bool(categoria or subcategoria or angulo),
        }

    # verifica se ha empate proximo entre os top candidatos
    MARGEM_EMPATE = 0.02
    revisao_por_empate = False
    if len(df_scores) >= 2:
        segundo = df_scores.iloc[1].to_dict()
        diferenca = score_melhor - segundo.get("score_total", 0)
        if diferenca < MARGEM_EMPATE:
            revisao_por_empate = True

    # quadro eletrico sempre passa por revisao: com/sem barramento e sobrepor/embutir
    revisao = revisao_por_empate or categoria == "QUADRO"

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
        "tipo_match": "MATCH_DESCRICAO_REVISAR" if revisao else "MATCH_DESCRICAO",
        "revisao_manual": revisao,
        "motivo_match": (
            f"MATCH_EMPATE_PROXIMO(dif={score_melhor - df_scores.iloc[1].get('score_total', 0):.2f})"
            if revisao_por_empate
            else f"MATCH_POR_DESCRICAO(cat={categoria},diam={sorted(diametros)},serie={subcategoria},ang={angulo})"
        ),
        "categoria_krona": _categoria_candidato(melhor),
        "eh_tubo_krona": melhor.get("eh_tubo"),
        "diametro_krona_mm": obter_diametro_krona(melhor),
        "comprimento_krona_m": obter_comprimento_krona(melhor),
        "categoria_oc": categoria,
        "diametros_oc": sorted(diametros),
        "linha_oc": linha,
        "serie_oc": subcategoria,
        "angulo_oc": angulo,
        "quadro_tamanho_oc": quadro_tamanho,
        "candidato_unico_estrutural": candidato_unico,
        "ancoras_estruturais": ancoras,
        "candidatos_revisao": _resumo_candidatos(registros),
        "bloquear_fallback": False,
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

# ============================================================
# RESTRICOES DUREAS deterministas (sem IA):
# material e diametro nao sao negociaveis — descricao do catalogo
# que CONTRADIZ a OC nunca pode virar match automatico.
# ============================================================
_RX_CPVC  = re.compile(r"\bCPVC\b")
_RX_ULTRATERM = re.compile(r"ULTRA[\s\-]?TERM")
_RX_PPR   = re.compile(r"\bPP[\-\s]?R\b")
_RX_PVC   = re.compile(r"(?<!C)PVC")
_RX_BRAS  = re.compile(r"\bBRASO\b|\bLAT[AÃ]O\b")
# linhas do catalogo Krona que sao PVC por definicao (material nao escrito na descricao)
_RX_LINHA_PVC = re.compile(r"ROSC[ÃA]?VEL|ROSQUE[ÁA]?VEL|SOLDAVEL|\bSOLD\b|ESGOTO|\bESG\b|INCENDIO|\bFVM\b|\bPSM\b")

# "X40MM" e "75X50MM" nao tem fronteira de palavra antes do numero; sem isto
# medidas de joelhos/juncoes ficam vazias e o match cai no candidato errado.
_RX_DIAM_MM  = re.compile(r"(?<!\d)(\d{1,3})\s*MM\b")
_RX_DIAM_PAR = re.compile(r"(?<!\d)(\d{1,3})\s*(?:X|×)\s*(\d{1,3})(?!\d)")
_RX_DN       = re.compile(r"\bD\.?N\.?\s*(\d{2,3})\b")


def _materiais_de(texto) -> set:
    t = str(texto or "").upper()
    mats = set()
    if _RX_CPVC.search(t):  mats.add("CPVC")
    if _RX_ULTRATERM.search(t): mats.add("CPVC")  # ULTRATERM = linha CPVC da Krona
    if _RX_PPR.search(t):   mats.add("PPR")
    if _RX_PVC.search(t):   mats.add("PVC")
    if _RX_BRAS.search(t):  mats.add("BRASO")
    return mats


def _diametros_de(texto) -> set:
    t = str(texto or "").upper()
    ds = set()
    for m in _RX_DIAM_MM.finditer(t):
        ds.add(int(m.group(1)))
    for m in _RX_DIAM_PAR.finditer(t):
        ds.add(int(m.group(1)))
        ds.add(int(m.group(2)))
    for m in _RX_DN.finditer(t):
        ds.add(int(m.group(1)))
    return ds


_CATS_DUPLA_MEDIDA = {"TE", "REDUCAO", "BUCHA", "LUVA", "ADAPTADOR", "JUNCAO", "JOELHO", "CURVA"}


def _conflito_hard(item, res) -> bool:
    """True se o candidato contradiz familia, linha, serie, angulo ou medida da OC."""
    desc_oc = str(
        item.get("descricao_oc")
        or item.get("descricao_reconstruida")
        or item.get("descricao_original")
        or ""
    )
    desc_cand = str(res.get("descricao_krona") or "")
    if not desc_oc or not desc_cand:
        return False

    mo, mc = _materiais_de(desc_oc), _materiais_de(desc_cand)
    if not mc and _RX_LINHA_PVC.search(desc_cand.upper()):
        mc = {"PVC"}  # linha ROSCAVEL/SOLDAVEL/ESGOTO do catalogo e PVC por definicao
    if mo and mc and not (mo & mc):
        return True

    cat_oc = extrair_categoria_da_descricao(desc_oc)
    cat_res = str(res.get("categoria_krona") or "").strip().upper()
    if cat_res in ("NAN", "NONE", "NAT"):
        cat_res = ""
    cat_cand = extrair_categoria_da_descricao(desc_cand) or cat_res
    if not _familias_compativeis(cat_oc, cat_cand, desc_oc, desc_cand):
        return True

    linha_oc = _linha_do_texto(desc_oc)
    linha_cand = _linha_do_texto(desc_cand)
    if linha_oc and linha_cand and linha_oc != linha_cand:
        return True

    comp_oc = _curta_longa_do_texto(desc_oc)
    comp_cand = _curta_longa_do_texto(desc_cand)
    if comp_oc and comp_cand and comp_oc != comp_cand:
        return True

    sub_oc = extrair_subcategoria_da_descricao(desc_oc)
    serie_cand = _serie_do_texto(desc_cand)
    if sub_oc == "REFORCADA" and serie_cand and serie_cand != "REFORCADA":
        return True
    if sub_oc == "ESGOTO" and serie_cand and serie_cand != "NORMAL":
        return True

    angulo_oc = extrair_angulo_da_descricao(desc_oc, cat_oc)
    angulo_cand = extrair_angulo_da_descricao(desc_cand, cat_cand)
    if angulo_oc and angulo_cand and angulo_oc != angulo_cand:
        return True

    do = extrair_diametros_da_descricao(desc_oc, cat_oc)
    dc = extrair_diametros_da_descricao(desc_cand, cat_cand)
    if do and dc and not (do & dc):
        return True

    # reducoes: o candidato tem de conter TODOS os diametros pedidos
    if len(do) >= 2 and cat_oc in _CATS_DUPLA_MEDIDA:
        if dc:
            if not {float(d) for d in do} <= {float(d) for d in dc}:
                return True
        else:
            diam_cand_num = res.get("diametro_krona_mm")
            try:
                diam_val = float(diam_cand_num)
                if diam_val != diam_val:
                    return True
                if diam_val not in {float(d) for d in do}:
                    return True
            except (TypeError, ValueError):
                return True

    # diametro numerico do catalogo (mm) vs conjuntos de diametros da OC
    diam_cand_num = res.get("diametro_krona_mm")
    if do and diam_cand_num not in (None, "", "nan"):
        try:
            dc_val = float(diam_cand_num)
            if dc_val == dc_val and dc_val > 0 and not any(
                abs(dc_val - float(x)) <= max(1.0, 0.05 * float(x)) for x in do
            ):
                return True
        except Exception:
            pass

    if cat_oc == "QUADRO":
        tam_oc = _quadro_tamanho_do_texto(desc_oc)
        tam_cand = _quadro_tamanho_do_texto(desc_cand)
        if tam_oc and tam_cand and tam_oc != tam_cand:
            return True
        barr_oc = _barramento_do_texto(desc_oc)
        barr_cand = _barramento_do_texto(desc_cand)
        if barr_oc and barr_cand and barr_oc != barr_cand:
            return True

    return False


def _tentar_semantico(item, base_krona):
    """Motor semantico sempre submetido as travas duras do matcher."""
    try:
        from motor_semantico import obter_motor
        motor = obter_motor()
        if not motor.pronto:
            motor.indexar(base_krona)
        descricao = (item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
        descricao = str(descricao).replace("\n", " ").strip()
        if not descricao:
            return None
        resultado = motor.match(descricao)
        if resultado.get("match_encontrado") and not _conflito_hard(item, resultado):
            # o motor devolve so codigo/descricao/scores; o cadastro e a fonte
            # dos metadados que a regra de quantidade precisa para converter
            # metros em barras apenas quando o produto e mesmo um tubo
            cadastro = buscar_cadastro_krona_por_codigo(
                resultado.get("codigo_krona"), base_krona)
            if cadastro:
                resultado.setdefault("linha_krona_match", cadastro.get("linha_krona"))
                resultado.setdefault("familia_krona_match", cadastro.get("familia_krona"))
                resultado.setdefault("unidade_venda_krona", cadastro.get("unidade_venda"))
                resultado.setdefault("quantidade_embalagem_krona", cadastro.get("quantidade_embalagem"))
                resultado["eh_tubo_krona"] = cadastro.get("eh_tubo")
                resultado["comprimento_krona_m"] = obter_comprimento_krona(cadastro)
                if cadastro.get("categoria_detectada"):
                    # o indice FAISS pode ter metadados da classificacao antiga
                    resultado["categoria_krona"] = cadastro.get("categoria_detectada")
                if resultado.get("diametro_krona_mm") in (None, ""):
                    resultado["diametro_krona_mm"] = obter_diametro_krona(cadastro)
            resultado["via_motor_semantico"] = True
            return resultado
    except Exception as e:
        print(f"[MATCHER] Motor semantico indisponivel: {e}")
    return None


def _montar_sem_match(motivo="SEM_MATCH", score=0, categoria=None, **extra):
    resultado = {
        "match_encontrado": False,
        "codigo_krona": None,
        "descricao_krona": None,
        "descricao_krona_normalizada": None,
        "linha_krona_match": None,
        "familia_krona_match": None,
        "unidade_venda_krona": None,
        "quantidade_embalagem_krona": None,
        "score_estrutura": 0,
        "score_textual": score,
        "score_total": score,
        "tipo_match": "SEM_MATCH",
        "revisao_manual": True,
        "motivo_match": motivo,
        "categoria_krona": categoria,
        "eh_tubo_krona": None,
        "diametro_krona_mm": None,
        "comprimento_krona_m": None,
    }
    resultado.update(extra)
    return resultado


# ============================================================
# REGRAS DETERMINISTAS DE CATALOGO
# Verdades de negocio confirmadas para qualquer cliente:
# - PLUG PVC soldavel usa o cadastro PLUG ROSCAVEL (nome difere).
# - SOLUCAO LIMPADORA sem tamanho = 521 (1000 ml); 200 ml = 520.
# - PASTA LUBRIFICANTE sem tamanho = 677 (1 kg); 160 g = 675, 400 g = 676.
# Tamanho/bitola fora da tabela nao cai em fallback: vai para revisao.
# ============================================================

_BITOLAS_PLUG = {
    "1/2": "293",
    "3/4": "294",
    "1": "295",
    "1.1/2": "296",
    "1.1/4": "297",
    "2": "298",
}


def _normalizar_bitola_plug(texto):
    t = _normalizar_texto(texto)
    t = re.sub(r"\b1\s*[-.]?\s*1\s*/\s*2\b", "1.1/2", t)
    t = re.sub(r"\b1\s*[-.]?\s*1\s*/\s*4\b", "1.1/4", t)
    return re.sub(r"\s*/\s*", "/", t)


def _bitola_plug_do_texto(texto):
    t = _normalizar_bitola_plug(texto)
    for bitola in ("1.1/2", "1.1/4", "3/4", "1/2", "2", "1"):
        if re.search(rf"(?<![\d.]){re.escape(bitola)}(?![\d/])", t):
            return bitola
    return None


def _codigo_solucao_limpadora(texto):
    t = _normalizar_texto(texto)
    if re.search(r"\b200\s*(?:ML|CM\s*[3³]|CC)(?!\w)", t):
        return "520"
    if re.search(r"\b(?:1000|1\.000)\s*(?:ML|CM\s*[3³]|CC)(?!\w)", t):
        return "521"
    if re.search(r"\b1\s*L\b", t):
        return "521"
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:ML|L|CM\s*[3³]|CC)(?!\w)", t):
        return None
    return "521"


def _codigo_pasta_lubrificante(texto):
    t = _normalizar_texto(texto)
    if re.search(r"\b160\s*G\b", t):
        return "675"
    if re.search(r"\b400\s*G\b", t):
        return "676"
    if re.search(r"\b(?:1000|1\.000)\s*(?:G|KG)\b", t):
        return "677"
    if re.search(r"\b1\s*KG\b", t):
        return "677"
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:G|KG)\b", t):
        return None
    return "677"


def _resultado_regra_catalogo(cadastro, motivo):
    return {
        "match_encontrado": True,
        "codigo_krona": str(cadastro.get("codigo_krona")),
        "descricao_krona": cadastro.get("descricao_krona"),
        "descricao_krona_normalizada": cadastro.get("descricao_normalizada"),
        "linha_krona_match": cadastro.get("linha_krona"),
        "familia_krona_match": cadastro.get("familia_krona"),
        "unidade_venda_krona": cadastro.get("unidade_venda"),
        "quantidade_embalagem_krona": cadastro.get("quantidade_embalagem"),
        "score_estrutura": 1.0,
        "score_textual": 1.0,
        "score_total": 1.0,
        "tipo_match": "MATCH_REGRA_CATALOGO",
        "revisao_manual": False,
        "motivo_match": motivo,
        "categoria_krona": cadastro.get("categoria_detectada"),
        "eh_tubo_krona": cadastro.get("eh_tubo"),
        "diametro_krona_mm": obter_diametro_krona(cadastro),
        "comprimento_krona_m": obter_comprimento_krona(cadastro),
    }


def _regra_catalogo(item, base_krona):
    texto = _normalizar_texto(
        item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
    if not texto:
        return None

    familia = None
    codigo = None
    motivo = None

    if (re.search(r"\bPLUG\b", texto)
            and not re.search(r"\bPPR\b", texto)
            and re.search(r"\bPVC\b|\bSOLD|\bROSC", texto)):
        familia = "PLUG"
        bitola = _bitola_plug_do_texto(texto)
        codigo = _BITOLAS_PLUG.get(bitola) if bitola else None
        motivo = f"REGRA_CATALOGO_PLUG_{bitola}" if bitola else None
    elif re.search(r"\bSOLUCAO\b", texto) and re.search(r"LIMP|PREPARADORA", texto):
        familia = "SOLUCAO"
        codigo = _codigo_solucao_limpadora(texto)
        motivo = "REGRA_CATALOGO_SOLUCAO_LIMPADORA"
    elif re.search(r"\bPASTA\b", texto) and re.search(r"\bLUBRIFICANTE\b", texto):
        familia = "PASTA"
        codigo = _codigo_pasta_lubrificante(texto)
        motivo = "REGRA_CATALOGO_PASTA_LUBRIFICANTE"

    if familia is None:
        return None

    if not codigo:
        return {
            "_regra_bloqueia": True,
            "familia": familia,
            "motivo": f"REGRA_{familia}_TAMANHO_NAO_CADASTRADO",
        }

    cadastro = buscar_cadastro_krona_por_codigo(codigo, base_krona)
    if not cadastro:
        return {
            "_regra_bloqueia": True,
            "familia": familia,
            "motivo": f"REGRA_{familia}_CODIGO_AUSENTE",
        }

    return _resultado_regra_catalogo(cadastro, motivo or f"REGRA_CATALOGO_{familia}")


def match_item_oc(item, base_krona=None, indice_mrv=None, indice_brasal=None,
                  indice_tabela=None, fator_preco=None):
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

    # ── GATE DE CLIENTE ─────────────────────────────────────────────
    # Cliente desconhecido (GENERICO/CLIENTE_NOVO) nao toca nas tabelas
    # de/para MRV nem Brasal — codigos de clientes diferentes nao sao
    # comparaveis. Desconhecido usa: regra aprendida -> lookup -> fuzzy -> SEM_MATCH.
    _fmt_item = str(item.get("formato_oc") or "").strip().upper()
    _obs = item.get("observacoes") or []
    _obs_str = " ".join(str(o) for o in _obs).upper() if isinstance(_obs, (list, tuple)) else str(_obs).upper()
    cliente_desconhecido = (
        _fmt_item in ("GENERICO", "DESCONHECIDO")
        or "CLIENTE_NOVO" in _obs_str
        or "EXTRATOR_GENERICO" in _obs_str
    )

    # =========================================================
    # PRIORIDADE 1 — MRV
    # Match por código interno da OC via tabela DE/PARA.
    # Independente de score — lookup determinístico.
    # So para itens de fluxo conhecido (gate acima).
    # =========================================================
    if indice_mrv and not cliente_desconhecido:
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
    # Match direto por código Brasal usando tabela DE/PARA.
    # Independente de score — lookup determinístico.
    # So para itens de fluxo conhecido (gate acima).
    # =========================================================
    if indice_brasal and not cliente_desconhecido:
        match_brasal = match_por_codigo_brasal(item, indice_brasal)
        if match_brasal:
            return match_brasal

    # =========================================================
    # PRIORIDADE 1.7 — TABELA DE PRECO DO CLIENTE
    # So corre quando o cliente tem tabela importada (CITY, EBM, VEGA...).
    # Restringe a descricao aos itens contratados e confirma pelo preco.
    # Clientes sem tabela (MRV, Brasal...) nunca entram aqui.
    # =========================================================
    if indice_tabela is not None:
        match_tabela = match_tabela_cliente(item, indice_tabela, fator_preco)
        if match_tabela:
            return match_tabela

    # ── CONSULTAR CORRECOES APRENDIDAS (com correspondência aproximada) ──
    # Só chega aqui para clientes sem tabela DE/PARA (ex: UAU, SIENGE, genérico)
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

    # ── REGRAS DETERMINISTAS DE CATALOGO (verdades de negocio) ──
    # Depois de codigo/DE-PARA/tabela/correcao aprendida e antes do
    # match por descricao. Tamanho/bitola fora da tabela nao cai em
    # fallback: devolve SEM_MATCH para revisao humana.
    regra_catalogo = _regra_catalogo(item, base_krona)
    if regra_catalogo:
        if regra_catalogo.get("_regra_bloqueia"):
            return _montar_sem_match(
                motivo=regra_catalogo["motivo"],
                categoria=regra_catalogo["familia"],
                categoria_oc=regra_catalogo["familia"],
                bloquear_fallback=True,
            )
        return regra_catalogo

    # =========================================================
    # PRIORIDADE 2 — MATCH POR DESCRICAO
    # Para clientes sem tabela DE/PARA (ex: UAU/GPL, Krona direto)
    # Usa limpeza de descricao + filtro por categoria e diametro
    # =========================================================
    match_desc = match_por_descricao(item, base_krona)

    if match_desc.get("match_encontrado") and _conflito_hard(item, match_desc):
        return _montar_sem_match(
            motivo="CONFLITO_ESTRUTURAL_APOS_DESCRICAO",
            score=match_desc.get("score_total", 0),
            categoria=match_desc.get("categoria_krona"),
            candidatos_revisao=match_desc.get("candidatos_revisao", ""),
            categoria_oc=match_desc.get("categoria_oc"),
            diametros_oc=match_desc.get("diametros_oc", []),
            bloquear_fallback=True,
        )

    if match_desc.get("match_encontrado"):
        score_desc = match_desc.get("score_total", 0)
        # candidato unico ja passou por todas as travas: nao deixa o
        # motor semantico (que ignora atributos) trocar o resultado
        if score_desc >= 0.80 or match_desc.get("candidato_unico_estrutural"):
            return match_desc
        resultado_semantico = _tentar_semantico(item, base_krona)
        score_sem = resultado_semantico.get("score_total", 0) if resultado_semantico else 0
        if resultado_semantico and score_sem > score_desc:
            return resultado_semantico
        return match_desc

    # composicao sugerida ou familia sem candidato: nao cai no fallback cego
    if match_desc.get("bloquear_fallback"):
        return match_desc

    # =========================================================
    # FALLBACK TRADICIONAL
    # =========================================================
    # score minimo para aceitar um match automatico
    # abaixo disso o item vai para revisao manual sem codigo krona
    SCORE_MINIMO = 0.30

    descricao_limpa = limpar_descricao_para_match(
        item.get("descricao_oc") or item.get("descricao_reconstruida") or "")
    categoria_trad = extrair_categoria_da_descricao(descricao_limpa)
    if not categoria_trad:
        cat_item = item.get("categoria_detectada")
        if cat_item is not None and str(cat_item).strip().upper() not in ("", "NAN", "NONE"):
            categoria_trad = str(cat_item).strip().upper()

    diametros_trad = extrair_diametros_da_descricao(descricao_limpa, categoria_trad)
    if not diametros_trad and item.get("diametro_mm") is not None:
        try:
            diametros_trad = {float(item.get("diametro_mm"))}
        except (TypeError, ValueError):
            diametros_trad = set()
    diametro_trad = max(diametros_trad) if diametros_trad else None
    material_trad = extrair_material_da_descricao(descricao_limpa)
    subcat_trad = extrair_subcategoria_da_descricao(descricao_limpa)
    angulo_trad = extrair_angulo_da_descricao(descricao_limpa, categoria_trad)

    candidatos_trad = filtrar_candidatos_krona(
        base_krona, categoria_trad, diametro_trad, material_trad, subcat_trad,
        descricao_limpa, diametros=diametros_trad, angulo=angulo_trad,
    )
    if candidatos_trad is None or candidatos_trad.empty:
        resultado_semantico = _tentar_semantico(item, base_krona)
        if resultado_semantico:
            return resultado_semantico
        return _montar_sem_match(
            motivo="SEM_CANDIDATOS_ESTRUTURAIS",
            categoria=categoria_trad,
            categoria_oc=categoria_trad,
            diametros_oc=sorted(diametros_trad),
            bloquear_fallback=True,
        )

    if diametro_trad is not None and not item.get("diametro_mm"):
        item = {**item, "diametro_mm": diametro_trad}
    if categoria_trad and not item.get("categoria_detectada"):
        item = {**item, "categoria_detectada": categoria_trad}

    registros = []

    for _, row in candidatos_trad.iterrows():
        cand = row.to_dict()
        scores = score_total(item, cand)

        registros.append({**cand, **scores})

    df = pd.DataFrame(registros).sort_values(
        by=["score_total"], ascending=False
    )

    melhor = df.iloc[0].to_dict()
    score_melhor = melhor.get("score_total", 0)

    # se o melhor resultado nao atinge o minimo, ou CONTRADIZ a OC
    # (material/diametro), nao força o match
    if score_melhor < SCORE_MINIMO or _conflito_hard(item, melhor):
        # PRIORIDADE IA — opcional; desligada por padrao (GAMATEC_USAR_IA=0)
        if USAR_IA and IA_DISPONIVEL and ia_disponivel():
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
        resultado_semantico = _tentar_semantico(item, base_krona)
        if resultado_semantico:
            return resultado_semantico

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
        resultado_semantico = _tentar_semantico(item, base_krona)
        if resultado_semantico:
            return resultado_semantico

    # ultima porta: TRADICIONAL que contradiz material/diametro da OC vira SEM_MATCH
    if _conflito_hard(item, _resultado_tradicional):
        _resultado_tradicional.update({
            "match_encontrado": False,
            "codigo_krona": None,
            "descricao_krona": None,
            "tipo_match": "SEM_MATCH",
            "revisao_manual": True,
            "motivo_match": "CONFLITO_MATERIAL_OU_DIAMETRO",
        })

    return _resultado_tradicional


# ============================================================
# LOTE + REGRA DE QUANTIDADE
# ============================================================

def match_lote_itens(df_oc, base_krona=None, indice_mrv=None, indice_brasal=None,
                     indice_tabela=None):
    if base_krona is None:
        base_krona = carregar_base_krona()

    if indice_mrv is None:
        indice_mrv = carregar_indice_mrv()

    if indice_brasal is None:
        indice_brasal = carregar_base_brasal()

    fator_preco = estimar_fator_preco(df_oc, indice_tabela)

    resultados = []

    for _, row in df_oc.iterrows():
        item = row.to_dict()

        resultado = match_item_oc(item, base_krona, indice_mrv, indice_brasal,
                                  indice_tabela=indice_tabela,
                                  fator_preco=fator_preco)

        final = {**item, **resultado}

        # 🔥 REGRA DE NEGÓCIO
        final = ajustar_quantidade_tubo(final)

        resultados.append(final)

    return pd.DataFrame(resultados)