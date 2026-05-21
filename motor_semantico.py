# -*- coding: utf-8 -*-
"""
motor_semantico.py — Vortex Matching Engine v2

Motor de matching semantico para clientes sem tabela DE/PARA.
Roda em shadow mode: processa em paralelo ao motor atual,
resultado apenas logado — nunca enviado ao cliente ate validacao.
"""

import os
import re
import json
import logging
import time
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("vortex.motor_semantico")

_BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
_INDEX_PATH = os.path.join(_BASE_DIR, "dados", "faiss_krona.index")
_RECS_PATH  = os.path.join(_BASE_DIR, "dados", "faiss_krona_registros.json")

# ================================================================
# DICIONARIO TECNICO KRONA
# ================================================================

DICIONARIO_TECNICO = {
    # categorias
    r"\bTUB\b":       "TUBO",
    r"\bTUBS\b":      "TUBO",
    r"\bJOE\b":       "JOELHO",
    r"\bJOEL\b":      "JOELHO",
    r"\bJOELH\b":     "JOELHO",
    r"\bCURV\b":      "CURVA",
    r"\bLUV\b":       "LUVA",
    r"\bADAP\b":      "ADAPTADOR",
    r"\bADAPT\b":     "ADAPTADOR",
    r"\bREG\b":       "REGISTRO",
    r"\bREGIST\b":    "REGISTRO",
    r"\bRED\b":       "REDUCAO",
    r"\bREDUC\b":     "REDUCAO",
    r"\bJUNC\b":      "JUNCAO",
    r"\bJUN\b":       "JUNCAO",
    r"\bBUCH\b":      "BUCHA",
    r"\bFLANG\b":     "FLANGE",
    r"\bUNI\b":       "UNIAO",
    r"\bVALV\b":      "VALVULA",
    r"\bTAMP\b":      "TAMPA",
    # material / linha
    r"\bSOLD\b":      "SOLDAVEL",
    r"\bSOLDAV\b":    "SOLDAVEL",
    r"\bROSC\b":      "ROSCAVEL",
    r"\bROSCAV\b":    "ROSCAVEL",
    r"\bESG\b":       "ESGOTO",
    r"\bESGT\b":      "ESGOTO",
    r"\bPRIM\b":      "PRIMARIO",
    r"\bSEC\b":       "SECUNDARIO",
    r"\bSR\b":        "SERIE REFORCADA",
    r"\bREFORC\b":    "SERIE REFORCADA",
    r"\bULTRA\b":     "ULTRATERM",
    # conversao de polegadas para MM
    r"\b1/4\s*[\"']?\b":      "6MM",
    r"\b3/8\s*[\"']?\b":      "10MM",
    r"\b1/2\s*[\"']?\b":      "15MM",
    r"\b3/4\s*[\"']?\b":      "20MM",
    r"\b(?<!\d)1\s*[\"']\b":  "25MM",
    r"\b1\s*1/4\s*[\"']?\b":  "32MM",
    r"\b1\s*1/2\s*[\"']?\b":  "40MM",
    r"\b(?<!\d)2\s*[\"']\b":  "50MM",
    r"\b(?<!\d)3\s*[\"']\b":  "75MM",
    r"\b(?<!\d)4\s*[\"']\b":  "100MM",
    # unidades coladas
    r"(\d)(MM)\b":    r"\1 MM",
    r"\bDN(\d)":      r"DN \1",
    r"(\d)X(\d)":     r"\1 X \2",
    # separadores
    r"[-–/|;]+":      " ",
}

# ================================================================
# ATRIBUTOS EXTRAIVEIS
# ================================================================

_PADROES_CATEGORIA = [
    ("TUBO",       [r"\bTUBO\b"]),
    ("JOELHO",     [r"\bJOELHO\b", r"\bCURVA\b"]),
    ("TE",         [r"\bT[EÊ]\b"]),
    ("LUVA",       [r"\bLUVA\b"]),
    ("CAP",        [r"\bCAP\b"]),
    ("REDUCAO",    [r"\bREDU[CÇ]"]),
    ("ADAPTADOR",  [r"\bADAPTADOR\b"]),
    ("BUCHA",      [r"\bBUCHA\b"]),
    ("REGISTRO",   [r"\bREGISTRO\b"]),
    ("VALVULA",    [r"\bVALVULA\b"]),
    ("JUNCAO",     [r"\bJUN[CÇ][AÃ]O\b"]),
    ("UNIAO",      [r"\bUNI[AÃ]O\b"]),
    ("FLANGE",     [r"\bFLANGE\b"]),
    ("GRELHA",     [r"\bGRELHA\b", r"\bPORTA[\s-]*GRELHA\b"]),
    ("ADESIVO",    [r"\bADESIVO\b", r"\bCOLA\b"]),
    ("PASTA",      [r"\bPASTA\b"]),
    ("FITA",       [r"\bFITA\b"]),
    ("TORNEIRA",   [r"\bTORNEIRA\b"]),
]

_PADROES_DIAMETRO = [
    r"\bDN\s*(\d{1,3}(?:[.,]\d+)?)\b",
    r"\b(\d{1,3}(?:[.,]\d+)?)\s*MM\b",
    r"\b(\d{1,3}(?:[.,]\d+)?)MM\b",
]

_PADROES_COMPRIMENTO = [
    r"\b(\d{1,2}(?:[.,]\d+)?)\s*M\b",
    r"\b(\d{1,2}(?:[.,]\d+)?)M\b",
]

_PADROES_SERIE = {
    "REFORCADA": [r"REFOR[CÇ]", r"\bSR\b", r"SERIE REFORCADA"],
    "ESGOTO":    [r"\bESGOTO\b", r"\bPRIM\b", r"\bSEC\b"],
    "SOLDAVEL":  [r"\bSOLDAVEL\b"],
    "ROSCAVEL":  [r"\bROSCAVEL\b"],
    "ULTRATERM": [r"\bULTRATERM\b"],
}


def normalizar_tecnico(texto: str) -> str:
    t = str(texto or "").upper().strip()
    for orig, sub in [("Ã","A"),("Á","A"),("À","A"),("Â","A"),
                      ("É","E"),("Ê","E"),("Í","I"),("Ó","O"),
                      ("Ô","O"),("Ú","U"),("Ç","C"),("Ã","A"),("Õ","O")]:
        t = t.replace(orig, sub)
    t = re.sub(r"^\s*(?:FVM|FV|REF|COD|PROD|MAT|ART|ITEM)\s*[-:]\s*", "", t)
    t = re.sub(r"\s*-?\s*NBR\s*\d+", "", t)
    t = t.replace("°", " ")
    t = re.sub(r"[()\[\]]", " ", t)
    for padrao, substituto in DICIONARIO_TECNICO.items():
        t = re.sub(padrao, substituto, t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ================================================================
# ENRIQUECEDOR DE DESCRICOES KRONA
# Adiciona sinonimos para aproximar vocabulario Krona ao das OCs
# ================================================================

_ENRIQUECIMENTOS = {
    # PORTA GRELHA — traduz nomenclatura interna para linguagem cliente
    r"PORTA\s*GRELHA.*?CX\.?SIF\.?\s*100":
        "PORTA GRELHA PVC QUADRADA BRANCA 100MM 100X100MM CAIXA SIFONADA",
    r"PORTA\s*GRELHA.*?CX\.?SIF\.?\s*150":
        "PORTA GRELHA PVC QUADRADA BRANCA 150MM 150X150MM CAIXA SIFONADA",
    r"PORTA\s*GRELHA.*?100X100":
        "PORTA GRELHA PVC QUADRADA BRANCA 100MM 100X100MM",
    r"PORTA\s*GRELHA.*?150X150":
        "PORTA GRELHA PVC QUADRADA BRANCA 150MM 150X150MM",
    r"GRELHA.*?QUADR.*?100":
        "GRELHA QUADRADA BRANCA PVC 100MM CAIXA SIFONADA",
    r"GRELHA.*?QUADR.*?150":
        "GRELHA QUADRADA BRANCA PVC 150MM CAIXA SIFONADA",
    # ELETRODUTO — detecta MM ou polegadas e adiciona variante
    r"ELETRODUTO.*?RIGIDO.*?SOLDAVEL\s*20MM":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 20MM 3/4 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?SOLDAVEL\s*25MM":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 25MM 1 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?SOLDAVEL\s*32MM":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 32MM 1.1/4 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?SOLDAVEL\s*40MM":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 40MM 1.1/2 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?SOLDAVEL\s*50MM":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 50MM 2 POLEGADAS",
    # ELETRODUTO RIGIDO com polegadas (detecta 3/4, 1, 1.1/4, etc antes da conversao)
    r"ELETRODUTO.*?RIGIDO.*?[^\d]3/4\b":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 20MM 3/4 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?[\s\D]1[\s'\"]":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 25MM 1 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?1\s*1/4":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 32MM 1.1/4 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?1\s*1/2":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 40MM 1.1/2 POLEGADA",
    r"ELETRODUTO.*?RIGIDO.*?[\s\D]2[\s'\"]":
        "ELETRODUTO PVC RIGIDO SOLDAVEL 50MM 2 POLEGADAS",
    # ELETRODUTO FLEX — adiciona bitola em polegadas
    r"ELETRODUTO.*?FLEX.*?20MM":
        "ELETRODUTO PVC FLEXIVEL CORRUGADO 20MM 3/4 POLEGADA",
    r"ELETRODUTO.*?FLEX.*?25MM":
        "ELETRODUTO PVC FLEXIVEL CORRUGADO 25MM 1 POLEGADA",
    r"ELETRODUTO.*?FLEX.*?32MM":
        "ELETRODUTO PVC FLEXIVEL CORRUGADO 32MM 1.1/4 POLEGADA",
    # TE REDUCAO — adiciona variantes de nomenclatura
    r"TE\s*RED.*?SOLD.*?25\s*X\s*20":
        "TE REDUCAO PVC SOLDAVEL 25X20MM MARROM CLASSE 15 90 GRAUS",
    r"TE\s*RED.*?SOLD.*?32\s*X\s*25":
        "TE REDUCAO PVC SOLDAVEL 32X25MM MARROM CLASSE 15 90 GRAUS",
}


def enriquecer_descricao_krona(descricao: str) -> str:
    """
    Enriquece descricao Krona com sinonimos para melhorar matching semantico.
    Retorna descricao original + termos adicionais quando houver match.
    """
    desc_upper = str(descricao or "").upper()
    for padrao, enriquecimento in _ENRIQUECIMENTOS.items():
        if re.search(padrao, desc_upper):
            return f"{descricao} {enriquecimento}"
    return descricao


def extrair_atributos(descricao_normalizada: str) -> dict:
    t = descricao_normalizada
    categoria = None
    for cat, padroes in _PADROES_CATEGORIA:
        for p in padroes:
            if re.search(p, t):
                categoria = cat
                break
        if categoria:
            break

    diametro = None
    for p in _PADROES_DIAMETRO:
        m = re.search(p, t)
        if m:
            try:
                diametro = float(m.group(1).replace(",", "."))
                break
            except Exception:
                pass

    comprimento = None
    for p in _PADROES_COMPRIMENTO:
        m = re.search(p, t)
        if m:
            try:
                v = float(m.group(1).replace(",", "."))
                if 0.3 <= v <= 12:
                    comprimento = v
                    break
            except Exception:
                pass

    material = None
    if re.search(r"\bPPR\b", t):      material = "PPR"
    elif re.search(r"\bCPVC\b", t):   material = "CPVC"
    elif re.search(r"\bPEAD\b", t):   material = "PEAD"

    serie = None
    for nome_serie, padroes in _PADROES_SERIE.items():
        for p in padroes:
            if re.search(p, t):
                serie = nome_serie
                break
        if serie:
            break

    return {
        "categoria":     categoria,
        "diametro_mm":   diametro,
        "comprimento_m": comprimento,
        "material":      material,
        "serie":         serie,
    }


def validar_atributos(atributos_oc: dict, candidato: dict) -> float:
    bonus = 0.0
    cat_oc   = atributos_oc.get("categoria")
    cat_cand = str(candidato.get("categoria_detectada", "") or "").upper()
    if cat_oc and cat_oc.upper() == cat_cand:
        bonus += 0.10

    diam_oc   = atributos_oc.get("diametro_mm")
    diam_cand = candidato.get("diametro_final_mm") or candidato.get("diametro_mm")
    if diam_oc is not None and diam_cand is not None:
        try:
            if abs(float(diam_oc) - float(diam_cand)) < 0.01:
                bonus += 0.12
        except Exception:
            pass

    comp_oc   = atributos_oc.get("comprimento_m")
    comp_cand = (candidato.get("comprimento_final_m")
                 or candidato.get("comprimento_detectado_m")
                 or candidato.get("comprimento_matriz_m"))
    if comp_oc is not None and comp_cand is not None:
        try:
            if abs(float(comp_oc) - float(comp_cand)) < 0.01:
                bonus += 0.08
        except Exception:
            pass

    return round(min(bonus, 0.30), 4)


class MotorSemantico:
    MODELO_NOME = "paraphrase-multilingual-MiniLM-L12-v2"
    SCORE_MINIMO = 0.45
    TOP_K = 10

    def __init__(self):
        self._modelo     = None
        self._index      = None
        self._registros  = []
        self._indexado   = False
        self._carregando = False

    def _carregar_modelo(self):
        if self._modelo is not None:
            return
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer
        logger.info(f"[MOTOR] Carregando modelo {self.MODELO_NOME}...")
        self._modelo = SentenceTransformer(self.MODELO_NOME)
        logger.info("[MOTOR] Modelo carregado.")

    def indexar(self, base_krona: pd.DataFrame, forcar_reindexar: bool = False):
        """
        Indexa o catalogo Krona para busca vetorial.
        Se o indice ja existir em disco, carrega sem reprocessar.
        Use forcar_reindexar=True quando a base Krona for atualizada.
        """
        import faiss, json

        # carrega do disco se existir e nao forcar reindexar
        if not forcar_reindexar and os.path.exists(_INDEX_PATH) and os.path.exists(_RECS_PATH):
            try:
                logger.info("[MOTOR] Carregando indice FAISS do disco...")
                self._carregar_modelo()
                self._index     = faiss.read_index(_INDEX_PATH)
                with open(_RECS_PATH, "r", encoding="utf-8") as f:
                    self._registros = json.load(f)
                self._indexado  = True
                logger.info(f"[MOTOR] Indice carregado: {len(self._registros)} produtos.")
                return
            except Exception as e:
                logger.warning(f"[MOTOR] Erro ao carregar indice do disco: {e}. Reindexando...")

        # indexa do zero
        self._carregando = True
        try:
            self._carregar_modelo()
            logger.info(f"[MOTOR] Indexando {len(base_krona)} produtos Krona...")
            t0 = time.time()

            descricoes = []
            registros  = []
            for _, row in base_krona.iterrows():
                r    = row.to_dict()
                desc = str(r.get("descricao_normalizada") or r.get("descricao_krona") or "")
                desc_enriquecida = enriquecer_descricao_krona(desc)
                descricoes.append(normalizar_tecnico(desc_enriquecida))
                registros.append(r)

            embeddings = self._modelo.encode(
                descricoes, batch_size=64,
                show_progress_bar=False, normalize_embeddings=True,
            )
            embeddings = np.array(embeddings, dtype="float32")

            dim   = embeddings.shape[1]
            index = faiss.IndexFlatIP(dim)
            index.add(embeddings)

            self._index     = index
            self._registros = registros
            self._indexado  = True

            # salva em disco
            os.makedirs(os.path.dirname(_INDEX_PATH), exist_ok=True)
            faiss.write_index(index, _INDEX_PATH)
            with open(_RECS_PATH, "w", encoding="utf-8") as f:
                recs_serial = []
                for r in registros:
                    recs_serial.append({
                        k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
                        for k, v in r.items()
                    })
                json.dump(recs_serial, f, ensure_ascii=False)

            elapsed = round(time.time() - t0, 2)
            logger.info(f"[MOTOR] Indexacao concluida em {elapsed}s — indice salvo em disco.")

        finally:
            self._carregando = False

    def match(self, descricao_oc: str) -> dict:
        if not self._indexado:
            return {"match_encontrado": False, "motivo_match": "MOTOR_NAO_INDEXADO"}
        desc_enriquecida = enriquecer_descricao_krona(descricao_oc)
        desc_norm = normalizar_tecnico(desc_enriquecida)
        atributos = extrair_atributos(desc_norm)
        vetor = self._modelo.encode([desc_norm], normalize_embeddings=True)
        vetor = np.array(vetor, dtype="float32")
        scores_cosine, indices = self._index.search(vetor, self.TOP_K)
        scores_cosine = scores_cosine[0]
        indices       = indices[0]
        candidatos = []
        for score_cos, idx in zip(scores_cosine, indices):
            if idx < 0:
                continue
            cand  = self._registros[idx]
            bonus = validar_atributos(atributos, cand)
            candidatos.append((round(min(1.0, float(score_cos)+bonus), 4), float(score_cos), cand))
        if not candidatos:
            return {"match_encontrado": False, "tipo_match": "SEM_MATCH_SEMANTICO"}
        candidatos.sort(key=lambda x: x[0], reverse=True)
        score_final, score_cos, melhor = candidatos[0]
        revisao_empate = (
            len(candidatos) >= 2 and (score_final - candidatos[1][0]) < 0.05
        )
        if score_final < self.SCORE_MINIMO:
            return {
                "match_encontrado": False,
                "score_total":      score_final,
                "tipo_match":       "SEM_MATCH_SEMANTICO",
                "revisao_manual":   True,
                "motivo_match":     f"SCORE_ABAIXO({score_final:.2f})",
            }
        return {
            "match_encontrado":  True,
            "codigo_krona":      melhor.get("codigo_krona"),
            "descricao_krona":   melhor.get("descricao_krona"),
            "score_textual":     score_cos,
            "score_total":       score_final,
            "tipo_match":        "MATCH_SEMANTICO" if not revisao_empate else "MATCH_SEMANTICO_REVISAR",
            "revisao_manual":    revisao_empate,
            "motivo_match":      f"SEMANTICO(cat={atributos['categoria']},diam={atributos['diametro_mm']})",
            "categoria_krona":   melhor.get("categoria_detectada"),
            "diametro_krona_mm": melhor.get("diametro_final_mm") or melhor.get("diametro_mm"),
        }

    @property
    def pronto(self) -> bool:
        return self._indexado and not self._carregando


_instancia_global: Optional[MotorSemantico] = None


def obter_motor() -> MotorSemantico:
    global _instancia_global
    if _instancia_global is None:
        _instancia_global = MotorSemantico()
    return _instancia_global
