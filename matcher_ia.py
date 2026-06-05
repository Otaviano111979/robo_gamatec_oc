# -*- coding: utf-8 -*-
"""
matcher_ia.py

Integração Anthropic API para matching de produtos Krona.
Chamado APENAS após todos os outros motores falharem (SEM_MATCH).

Regras absolutas (ver briefing_ia_matcher.md):
  - Operador sempre confirma — nunca aceitação automática
  - try/except em toda chamada — falha não interrompe processamento
  - Aprendizado só na confirmação humana
  - Chave via variável de ambiente ANTHROPIC_API_KEY (não hardcoded)
"""

import json
import os
import re
import urllib.request
import urllib.error

from config import BASE_DIR

_CAMINHO_CONFIG = os.path.join(BASE_DIR, "dados", "config_ia.json")
_TIMEOUT_SEGUNDOS = 20
_MODELO_PADRAO = "claude-sonnet-4-20250514"

CONFIDENCIAS_VALIDAS = {"alta", "media", "baixa", "nenhuma"}


# ============================================================
# CONFIGURAÇÃO
# ============================================================

def _carregar_config():
    if os.path.exists(_CAMINHO_CONFIG):
        try:
            with open(_CAMINHO_CONFIG, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _carregar_chave():
    chave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if chave:
        return chave
    cfg = _carregar_config()
    return cfg.get("anthropic_api_key", "").strip() or None


# ============================================================
# PROMPT
# ============================================================

def _montar_prompt(descricao_oc, catalogo_krona):
    lista = "\n".join(
        f"  {p['codigo_krona']}: {p['descricao_krona']}"
        for p in catalogo_krona
    )

    return f"""Você é um especialista em produtos hidráulicos e elétricos Krona.

Dado o produto descrito numa Ordem de Compra:
DESCRIÇÃO OC: {descricao_oc}

E o catálogo Krona disponível:
{lista}

Encontre o produto Krona mais adequado.

Responda APENAS em JSON válido:
{{
  "confianca": "alta" | "media" | "baixa" | "nenhuma",
  "codigo_krona": "XXXX ou null",
  "descricao_krona": "descrição ou null",
  "justificativa": "explicação breve"
}}

- "alta": produto claramente idêntico
- "media": produto muito provável mas com alguma dúvida
- "baixa": pode ser este produto mas não tenho certeza
- "nenhuma": não encontrei equivalente no catálogo"""


# ============================================================
# CHAMADA À API
# ============================================================

def _chamar_api(prompt, chave, modelo, max_tokens):
    payload = json.dumps({
        "model": modelo,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         chave,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEGUNDOS) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    for bloco in data.get("content", []):
        if bloco.get("type") == "text":
            return bloco["text"].strip()

    return None


def _extrair_json(texto):
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


# ============================================================
# INTERFACE PRINCIPAL
# ============================================================

def chamar_anthropic(descricao_oc, catalogo_krona):
    """
    Consulta a Anthropic API para identificar o produto Krona mais adequado.

    Deve ser chamada APENAS após todos os outros motores falharem.

    Args:
        descricao_oc:   descrição do produto na OC do cliente
        catalogo_krona: lista de dicts {codigo_krona, descricao_krona}

    Returns:
        dict {confianca, codigo_krona, descricao_krona, justificativa}
        ou None em caso de falha ou IA desativada
    """
    if not descricao_oc or not catalogo_krona:
        return None

    try:
        cfg = _carregar_config()

        if not cfg.get("ia_ativa", True):
            return None

        chave = _carregar_chave()
        if not chave:
            print(f"[IA] ANTHROPIC_API_KEY não configurada — '{descricao_oc[:40]}' vai para revisão manual")
            return None

        modelo    = cfg.get("modelo", _MODELO_PADRAO)
        max_tokens = int(cfg.get("max_tokens", 500))

        prompt  = _montar_prompt(descricao_oc, catalogo_krona)
        resposta = _chamar_api(prompt, chave, modelo, max_tokens)

        if not resposta:
            return None

        resultado = _extrair_json(resposta)
        if not resultado:
            print(f"[IA] Resposta inválida (não-JSON): {resposta[:80]}")
            return None

        confianca = str(resultado.get("confianca", "nenhuma")).lower().strip()
        if confianca not in CONFIDENCIAS_VALIDAS:
            confianca = "nenhuma"

        codigo = resultado.get("codigo_krona")
        if not codigo or str(codigo).strip().lower() in ("null", "xxxx", ""):
            codigo = None
        else:
            codigo = str(codigo).strip()

        descricao = resultado.get("descricao_krona")
        if not descricao or str(descricao).strip().lower() in ("null", ""):
            descricao = None

        justificativa = str(resultado.get("justificativa", "")).strip()

        print(f"[IA] '{descricao_oc[:40]}' → {codigo} (confiança: {confianca})")

        return {
            "confianca":       confianca,
            "codigo_krona":    codigo,
            "descricao_krona": descricao,
            "justificativa":   justificativa,
        }

    except urllib.error.URLError as e:
        print(f"[IA] Erro de conexão: {e}")
        return None
    except Exception as e:
        print(f"[IA] Erro inesperado: {e}")
        return None
