# -*- coding: utf-8 -*-
"""
aprendizado_regras.py

Semana 3 — Aprendizado: correções viram regras automáticas.

Lógica:
- Quando uma mesma descricao_oc recebe a mesma correção 2+ vezes
  (por qualquer operador), ela é promovida para regra permanente.
- As regras geradas ficam em dados/regras_aprendidas.json
- O matcher carrega esse arquivo na inicialização e aplica antes
  do rapidfuzz (Prioridade 0.5 — após MRV/Brasal, antes do fuzzy)
- A promoção é automática: roda após cada registrar_validacao_manual()
"""

import json
import os
import re
import sqlite3
from datetime import datetime

from config import BASE_DIR

CAMINHO_DB      = os.path.join(BASE_DIR, "dados", "historico_aprendizado.db")
CAMINHO_REGRAS  = os.path.join(BASE_DIR, "dados", "regras_aprendidas.json")
LIMITE_PROMOCAO = 2   # quantas correções iguais para virar regra


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def normalizar_desc(texto):
    """Normaliza descrição para comparação e como chave da regra."""
    d = str(texto or "").upper()
    d = re.sub(r"NBR[\s\-]*\d+[\w/]*", "", d)
    d = re.sub(r"[°º\-\./\(\)]", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    return d


# ============================================================
# VERIFICAR E PROMOVER REGRAS
# ============================================================

def verificar_e_promover(descricao_oc_normalizada, codigo_krona):
    """
    Verifica se essa combinação atingiu o limite de promoção.
    Se sim, adiciona/atualiza em regras_aprendidas.json.
    Retorna True se uma nova regra foi criada.
    """
    if not descricao_oc_normalizada or not codigo_krona:
        return False

    chave = normalizar_desc(descricao_oc_normalizada)

    # contar quantas vezes essa combinação aparece no banco
    try:
        conn = sqlite3.connect(CAMINHO_DB)
        row = conn.execute("""
            SELECT COUNT(*) FROM historico_validacoes
            WHERE descricao_oc_normalizada = ?
              AND codigo_krona_aprovado = ?
              AND tipo_match_final IN ('CORRECAO_MANUAL', 'MANUAL')
        """, (descricao_oc_normalizada, str(codigo_krona))).fetchone()
        contagem = row[0] if row else 0
        conn.close()
    except Exception:
        return False

    if contagem < LIMITE_PROMOCAO:
        return False

    # promover para regra
    regras = carregar_regras()
    if chave not in regras or regras[chave]["codigo_krona"] != str(codigo_krona):
        regras[chave] = {
            "codigo_krona":     str(codigo_krona),
            "confirmacoes":     contagem,
            "promovido_em":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "descricao_original": descricao_oc_normalizada,
        }
        salvar_regras(regras)
        print(f"[APRENDIZADO] Nova regra promovida: '{chave[:50]}' → {codigo_krona} ({contagem}x)")
        return True

    return False


# ============================================================
# CARREGAR / SALVAR REGRAS
# ============================================================

def carregar_regras():
    """Carrega regras aprendidas do JSON. Retorna dict vazio se não existir."""
    if not os.path.exists(CAMINHO_REGRAS):
        return {}
    try:
        with open(CAMINHO_REGRAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_regras(regras):
    os.makedirs(os.path.dirname(CAMINHO_REGRAS), exist_ok=True)
    with open(CAMINHO_REGRAS, "w", encoding="utf-8") as f:
        json.dump(regras, f, ensure_ascii=False, indent=2)


def buscar_regra_aprendida(descricao_oc):
    """
    Busca uma regra aprendida para a descrição da OC.
    Retorna o codigo_krona se encontrar, None caso contrário.
    """
    regras = carregar_regras()
    if not regras:
        return None

    chave = normalizar_desc(descricao_oc)

    # 1. match exato
    if chave in regras:
        return regras[chave]["codigo_krona"]

    # 2. match por similaridade (80%+)
    from difflib import SequenceMatcher
    melhor_score = 0.0
    melhor_codigo = None

    for regra_chave, regra_dados in regras.items():
        score = SequenceMatcher(None, chave, regra_chave).ratio()
        if score > melhor_score and score >= 0.88:
            melhor_score = score
            melhor_codigo = regra_dados["codigo_krona"]

    return melhor_codigo


# ============================================================
# ESTATÍSTICAS
# ============================================================

def stats_aprendizado():
    """Retorna estatísticas do aprendizado para o painel."""
    regras = carregar_regras()

    try:
        conn = sqlite3.connect(CAMINHO_DB)
        total_correcoes = conn.execute(
            "SELECT COUNT(*) FROM historico_validacoes WHERE tipo_match_final = 'CORRECAO_MANUAL'"
        ).fetchone()[0]
        total_clientes = conn.execute(
            "SELECT COUNT(DISTINCT cliente_id) FROM historico_validacoes WHERE cliente_id IS NOT NULL"
        ).fetchone()[0]
        conn.close()
    except Exception:
        total_correcoes = 0
        total_clientes = 0

    return {
        "total_correcoes":     total_correcoes,
        "total_regras":        len(regras),
        "total_clientes":      total_clientes,
        "proxima_promocao":    LIMITE_PROMOCAO,
    }


if __name__ == "__main__":
    print("=== REGRAS APRENDIDAS ===")
    regras = carregar_regras()
    if regras:
        for chave, dados in regras.items():
            print(f"  [{dados['codigo_krona']}] {chave[:60]} ({dados['confirmacoes']}x)")
    else:
        print("  Nenhuma regra ainda.")

    print(f"\n=== STATS ===")
    s = stats_aprendizado()
    for k, v in s.items():
        print(f"  {k}: {v}")
