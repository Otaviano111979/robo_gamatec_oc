# -*- coding: utf-8 -*-
"""
ia_helper.py

Camada de IA para o matcher Vortex.
Pronto para receber a chave Claude API — sem ela, opera em modo simulado.

Fluxo:
  1. Matcher tenta todos os níveis (regras, histórico, MRV, lookup, fuzzy)
  2. Se ainda assim score < mínimo → chama ia_helper.sugerir_match()
  3. ia_helper monta o prompt com a descrição + top candidatos do catálogo
  4. Claude API retorna o código mais provável com justificativa
  5. Resultado entra como tipo_match = "MATCH_IA" com revisao_manual = True

Configuração:
  - Chave em C:\\robo_gamatec_oc\\dados\\config_ia.json
  - Ou variável de ambiente ANTHROPIC_API_KEY
  - Sem chave → modo SIMULADO (retorna None, não quebra o fluxo)
"""

import json
import os
import re
import urllib.request
import urllib.error

from config import BASE_DIR

# ============================================================
# CONFIGURAÇÃO
# ============================================================

CAMINHO_CONFIG_IA = os.path.join(BASE_DIR, "dados", "config_ia.json")

MODELO_PADRAO   = "claude-haiku-4-5-20251001"  # mais barato — ideal para match
MAX_TOKENS      = 256                            # resposta curta — só o código
MAX_CANDIDATOS  = 10                             # top candidatos enviados ao Claude
TIMEOUT_SEGUNDOS = 15


def _carregar_chave():
    """Carrega a chave API de config_ia.json ou variável de ambiente."""
    # 1. variável de ambiente
    chave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if chave:
        return chave

    # 2. arquivo de configuração
    if os.path.exists(CAMINHO_CONFIG_IA):
        try:
            with open(CAMINHO_CONFIG_IA, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            chave = cfg.get("anthropic_api_key", "").strip()
            if chave:
                return chave
        except Exception:
            pass

    return None


def ia_disponivel():
    """Retorna True se a chave API está configurada."""
    return bool(_carregar_chave())


def salvar_chave(chave):
    """
    Salva a chave API em config_ia.json.
    Chamada uma vez pelo operador via painel ou CLI.
    """
    os.makedirs(os.path.dirname(CAMINHO_CONFIG_IA), exist_ok=True)
    cfg = {}
    if os.path.exists(CAMINHO_CONFIG_IA):
        try:
            with open(CAMINHO_CONFIG_IA, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    cfg["anthropic_api_key"] = chave.strip()
    cfg["modelo"] = cfg.get("modelo", MODELO_PADRAO)

    with open(CAMINHO_CONFIG_IA, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    print(f"[IA] Chave salva em {CAMINHO_CONFIG_IA}")


# ============================================================
# PROMPT
# ============================================================

def _montar_prompt(descricao_oc, candidatos):
    """
    Monta o prompt para o Claude com a descrição da OC e os candidatos do catálogo.
    Retorna apenas o código Krona — resposta curta e barata.
    """
    lista = "\n".join(
        f"  {c['codigo_krona']}: {c['descricao_krona']}"
        for c in candidatos[:MAX_CANDIDATOS]
    )

    return f"""Você é um especialista em materiais de construção hidráulica (tubos e conexões PVC).

Descrição da OC (pedido do cliente):
"{descricao_oc}"

Candidatos do catálogo Krona:
{lista}

Qual código do catálogo melhor corresponde à descrição da OC?
Responda APENAS com o número do código, nada mais.
Se nenhum candidato for adequado, responda: NENHUM"""


# ============================================================
# CHAMADA À API
# ============================================================

def _chamar_claude(prompt, chave, modelo=None):
    """
    Chama a Claude API e retorna o texto da resposta.
    Usa urllib para não depender de bibliotecas externas.
    """
    modelo = modelo or MODELO_PADRAO

    payload = json.dumps({
        "model": modelo,
        "max_tokens": MAX_TOKENS,
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

    with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    # extrair texto da resposta
    for bloco in data.get("content", []):
        if bloco.get("type") == "text":
            return bloco["text"].strip()

    return None


# ============================================================
# INTERFACE PRINCIPAL
# ============================================================

def sugerir_match(descricao_oc, candidatos_krona):
    """
    Tenta sugerir um match via Claude API para itens que o fuzzy não resolveu.

    Delega para matcher_ia.chamar_anthropic() que retorna resposta estruturada
    com confiança, código, descrição e justificativa.

    Parâmetros:
        descricao_oc      — descrição original do item da OC
        candidatos_krona  — lista de dicts com codigo_krona e descricao_krona

    Retorna:
        dict com {confianca, codigo_krona, descricao_krona, justificativa} ou None
    """
    try:
        from matcher_ia import chamar_anthropic
        return chamar_anthropic(descricao_oc, candidatos_krona)
    except ImportError:
        pass

    # fallback legado: sem matcher_ia disponível
    if not descricao_oc or not candidatos_krona:
        return None

    chave = _carregar_chave()
    if not chave:
        print(f"[IA] Chave não configurada — item '{descricao_oc[:40]}' vai para revisão manual")
        return None

    try:
        prompt   = _montar_prompt(descricao_oc, candidatos_krona)
        resposta = _chamar_claude(prompt, chave)

        if not resposta or resposta.upper() == "NENHUM":
            return None

        codigo = re.sub(r"[^\d]", "", resposta).lstrip("0") or resposta.strip()

        codigos_validos = {str(c["codigo_krona"]) for c in candidatos_krona}
        if codigo not in codigos_validos:
            print(f"[IA] Código {codigo} retornado não está nos candidatos — ignorando")
            return None

        print(f"[IA] Match sugerido (legado): '{descricao_oc[:40]}' → {codigo}")
        return {
            "confianca":       "media",
            "codigo_krona":    codigo,
            "descricao_krona": None,
            "justificativa":   f"Claude API ({MODELO_PADRAO})",
        }

    except urllib.error.URLError as e:
        print(f"[IA] Erro de conexão: {e}")
        return None
    except Exception as e:
        print(f"[IA] Erro inesperado: {e}")
        return None


# ============================================================
# STATUS
# ============================================================

def status_ia():
    """Retorna dict com status da IA para o painel."""
    chave = _carregar_chave()
    cfg   = {}
    if os.path.exists(CAMINHO_CONFIG_IA):
        try:
            with open(CAMINHO_CONFIG_IA, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    return {
        "disponivel":   bool(chave),
        "modelo":       cfg.get("modelo", MODELO_PADRAO),
        "modo":         "ATIVO" if chave else "SIMULADO",
        "config_path":  CAMINHO_CONFIG_IA,
    }


# ============================================================
# CLI — configurar chave pelo terminal
# ============================================================

if __name__ == "__main__":
    import sys

    print("=== Vortex — Configuração da IA ===\n")

    if len(sys.argv) == 3 and sys.argv[1] == "--salvar-chave":
        salvar_chave(sys.argv[2])
        print("Pronto! Reinicie o servidor para ativar.")
    else:
        s = status_ia()
        print(f"Status  : {s['modo']}")
        print(f"Modelo  : {s['modelo']}")
        print(f"Config  : {s['config_path']}")
        print()
        if not s["disponivel"]:
            print("Para ativar, execute:")
            print("  python ia_helper.py --salvar-chave sk-ant-SUA_CHAVE_AQUI")
        else:
            print("IA ativa! Sistema usando Claude no match.")
