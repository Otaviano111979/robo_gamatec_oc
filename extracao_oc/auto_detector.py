# -*- coding: utf-8 -*-
"""
extracao_oc/auto_detector.py

Módulo de auto-detecção de formatos de OC usando Anthropic API.
Detecta automaticamente novos formatos de OC e aprende padrões para reutilização.

Regras absolutas:
- Só ativa se extrator genérico retornar menos de 3 itens
- Try/except total — falha não interrompe processamento
- Formato aprendido é salvo apenas se confiança >= "media"
- Se API indisponível ou sem chave → usa resultado do extrator genérico
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber

from config import BASE_DIR

_CAMINHO_CONFIG = os.path.join(BASE_DIR, "dados", "config_ia.json")
# config_ia.json = só segredo (chave API, ignorado no git).
# config_matching.json = só comportamento (flags versionadas, sem segredo).
_CAMINHO_CONFIG_MATCHING = os.path.join(BASE_DIR, "dados", "config_matching.json")
_CAMINHO_FORMATOS = os.path.join(BASE_DIR, "dados", "formatos_aprendidos.json")
_TIMEOUT_SEGUNDOS = 30
_MODELO_PADRAO = "claude-sonnet-4-20250514"
# tokens separado do matcher: extração de OC em JSON exige respostas bem maiores
_MAX_TOKENS_DETECTOR = 4096


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


def _carregar_config_matching():
    """Flags de comportamento versionadas (sem segredo) — separado de config_ia.json."""
    if os.path.exists(_CAMINHO_CONFIG_MATCHING):
        try:
            with open(_CAMINHO_CONFIG_MATCHING, encoding="utf-8") as f:
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


def _carregar_formatos_aprendidos():
    """Carrega a lista de formatos já aprendidos."""
    if os.path.exists(_CAMINHO_FORMATOS):
        try:
            with open(_CAMINHO_FORMATOS, encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            pass
    return []


def _salvar_formatos_aprendidos(formatos):
    """Salva a lista de formatos aprendidos."""
    os.makedirs(os.path.dirname(_CAMINHO_FORMATOS), exist_ok=True)
    with open(_CAMINHO_FORMATOS, "w", encoding="utf-8") as f:
        json.dump(formatos, f, indent=2, ensure_ascii=False)


def _identificar_formato_conhecido(texto_pdf: str, formatos_aprendidos: list) -> dict:
    """
    Verifica se o texto do PDF atual corresponde a um formato já aprendido
    anteriormente, comparando os "identificadores" salvos (cliente/nome do
    formato) contra o texto do PDF por substring (case-insensitive).

    Não tenta reconstruir o parser posicional — só decide se o formato já é
    conhecido, para permitir logar/pular a chamada de IA (Parte 2a).
    """
    if not texto_pdf or not formatos_aprendidos:
        return None

    texto_upper = texto_pdf.upper()

    for fmt in formatos_aprendidos:
        identificadores = fmt.get("identificadores") or []
        for ident in identificadores:
            ident = str(ident or "").strip()
            # identificadores muito curtos geram falso positivo facilmente
            if len(ident) >= 4 and ident.upper() in texto_upper:
                return fmt

    return None


# ============================================================
# EXTRAÇÃO DE TEXTO DO PDF
# ============================================================

def _extrair_texto_pdf(caminho_pdf: str, max_chars: int = 3000) -> str:
    """Extrai texto do PDF (primeiros max_chars caracteres)."""
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = ""
            for pagina in pdf.pages:
                texto += (pagina.extract_text() or "") + "\n"
                if len(texto) >= max_chars:
                    break
            return texto[:max_chars]
    except Exception as e:
        print(f"[AUTO-DETECTOR] Erro ao extrair texto do PDF: {e}")
        return ""


def _extrair_linhas_candidatas(caminho_pdf: str, max_linhas: int = 20) -> list:
    """Extrai linhas candidatas a itens do PDF."""
    linhas = []
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text() or ""
                for linha in texto.split("\n"):
                    linha = linha.strip()
                    if linha and len(linha) > 10:
                        linhas.append(linha)
                        if len(linhas) >= max_linhas:
                            return linhas
    except Exception as e:
        print(f"[AUTO-DETECTOR] Erro ao extrair linhas: {e}")
    return linhas


# ============================================================
# PROMPT PARA IA
# ============================================================

def _montar_prompt(texto_pdf: str, linhas_candidatas: list) -> str:
    """Monta o prompt para a Anthropic API."""
    
    linhas_texto = "\n".join(f"  {i+1}. {l}" for i, l in enumerate(linhas_candidatas[:20]))
    
    return f"""Você é um especialista em análise de documentos de compra (OC/cotação) da construção civil brasileira.

Analise o texto abaixo extraído de um PDF de Ordem de Compra e extraia todos os itens de material listados.

TEXTO DO PDF:
{texto_pdf}

LINHAS CANDIDATAS À EXTRAÇÃO:
{linhas_texto}

Retorne APENAS JSON válido com a estrutura:
{{
  "formato_detectado": "nome identificador do formato (ex: PRIMECON_OCM)",
  "cliente_detectado": "razão social do cliente ou 'DESCONHECIDO'",
  "colunas": ["lista", "de", "colunas", "identificadas"],
  "itens": [
    {{
      "idx_item": 1,
      "codigo_interno_oc": "código do item na OC ou vazio",
      "descricao_original": "descrição completa do produto",
      "unidade_original": "UN/BR/M/KG/etc ou 'PC'",
      "quantidade": 10,
      "valor_unitario": 123.45,
      "valor_total": 1234.50
    }}
  ],
  "confianca": "alta" | "media" | "baixa",
  "observacoes": "notas sobre o formato detectado"
}}

REGRAS ABSOLUTAS:
- Extrair TODOS os itens visíveis na tabela principal
- quantidade e valores devem ser números (não strings)
- Se não conseguir identificar um campo, usar null
- confianca "alta" = formato claro, todos os campos identificados
- confianca "media" = formato identificado mas alguns campos duvidosos
- confianca "baixa" = formato confuso, extração parcial
- NUNCA incluir linhas de TOTAL, SUBTOTAL, DESCONTO ou FRETE nos itens
- Se houver dúvida sobre um campo, deixar null ao invés de inventar"""


# ============================================================
# CHAMADA À API
# ============================================================

def _chamar_api(prompt: str, chave: str, modelo: str, max_tokens: int) -> str:
    """Chama a Anthropic API."""
    try:
        payload = json.dumps({
            "model": modelo,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": chave,
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
    except urllib.error.URLError as e:
        print(f"[AUTO-DETECTOR] Erro de conexão com API: {e}")
        return None
    except Exception as e:
        print(f"[AUTO-DETECTOR] Erro ao chamar API: {e}")
        return None


def _extrair_json(texto: str) -> dict:
    """Extrai JSON da resposta da IA."""
    if not texto:
        return None
    try:
        m = re.search(r"\{.*\}", texto, re.DOTALL)
        if not m:
            return None
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        print(f"[AUTO-DETECTOR] Erro ao parsear JSON: {e}")
        return None


# ============================================================
# APRENDIZADO DE FORMATOS
# ============================================================

def _salvar_formato_aprendido(resultado_ia: dict, caminho_pdf: str):
    """Salva um novo formato aprendido."""
    try:
        confianca = resultado_ia.get("confianca", "").lower()
        
        # Só salva se confiança >= media
        if confianca not in ("media", "alta"):
            return
        
        formatos = _carregar_formatos_aprendidos()
        
        # Verifica se já existe formato similar
        cliente = (resultado_ia.get("cliente_detectado") or "").strip()
        formato = (resultado_ia.get("formato_detectado") or "").strip()
        
        if not formato:
            return
        
        # Atualiza se formato já existe
        for fmt in formatos:
            if fmt.get("formato") == formato:
                fmt["total_ocs_processadas"] = fmt.get("total_ocs_processadas", 1) + 1
                fmt["ultima_atualizacao"] = datetime.now().isoformat()
                break
        else:
            # Novo formato
            novo_formato = {
                "formato": formato,
                "cliente": cliente if cliente != "DESCONHECIDO" else None,
                "identificadores": [
                    cliente,
                    formato,
                ] if cliente != "DESCONHECIDO" else [formato],
                "colunas_detectadas": resultado_ia.get("colunas", []),
                "aprendido_em": datetime.now().isoformat(),
                "total_ocs_processadas": 1,
                "observacoes": resultado_ia.get("observacoes", ""),
            }
            formatos.append(novo_formato)
        
        _salvar_formatos_aprendidos(formatos)
        print(f"[AUTO-DETECTOR] Formato aprendido: {formato}")
    
    except Exception as e:
        print(f"[AUTO-DETECTOR] Erro ao salvar formato: {e}")


# ============================================================
# CONVERSÃO PARA DATAFRAME
# ============================================================

def _itens_para_dataframe(itens_ia: list) -> pd.DataFrame:
    """Converte itens da IA para DataFrame compatível com o pipeline."""
    if not itens_ia:
        return pd.DataFrame()
    
    registros = []
    for item in itens_ia:
        if not item.get("descricao_original"):
            continue
        
        registros.append({
            "num_item": item.get("idx_item", ""),
            "codigo_interno_oc": item.get("codigo_interno_oc", ""),
            "descricao_oc": item.get("descricao_original", ""),
            "unidade": item.get("unidade_original", "PC"),
            "quantidade": item.get("quantidade"),
            "preco_unitario": item.get("valor_unitario"),
            "observacoes": ["AUTO_DETECTOR"],
        })
    
    if not registros:
        return pd.DataFrame()
    
    return pd.DataFrame(registros)


# ============================================================
# INTERFACE PRINCIPAL
# ============================================================

def auto_detectar(caminho_oc: str) -> pd.DataFrame:
    """
    Detecta automaticamente o formato de uma OC usando IA e retorna os itens.
    
    Deve ser chamada APENAS após extrator genérico retornar < 3 itens.
    
    Args:
        caminho_oc: caminho completo do PDF da OC
    
    Returns:
        pd.DataFrame com itens extraídos, ou None em caso de falha
    """
    if not os.path.exists(caminho_oc):
        return None
    
    try:
        cfg = _carregar_config()
        
        # Verifica se IA está ativada
        if not cfg.get("ia_ativa", True):
            print("[AUTO-DETECTOR] IA desativada na configuração")
            return None
        
        # Verifica se chave está disponível
        chave = _carregar_chave()
        if not chave:
            print("[AUTO-DETECTOR] ANTHROPIC_API_KEY não configurada")
            return None
        
        # Extrai texto e linhas do PDF
        print(f"[AUTO-DETECTOR] Analisando: {Path(caminho_oc).name}")
        texto_pdf = _extrair_texto_pdf(caminho_oc)
        linhas = _extrair_linhas_candidatas(caminho_oc)
        
        if not texto_pdf or not linhas:
            print("[AUTO-DETECTOR] Não foi possível extrair texto do PDF")
            return None

        # ── PARTE 2a: reuso de formato já aprendido (log ou skip conforme flag) ──
        # Aditivo e isolado — qualquer falha aqui cai no fluxo normal (chama a IA).
        try:
            formatos_aprendidos = _carregar_formatos_aprendidos()
            formato_conhecido = _identificar_formato_conhecido(texto_pdf, formatos_aprendidos)
            if formato_conhecido:
                print(
                    f"[AUTO-DETECTOR] Formato '{formato_conhecido.get('formato')}' já conhecido "
                    f"(visto {formato_conhecido.get('total_ocs_processadas', 1)}x) — reuso possível"
                )
                if _carregar_config_matching().get("reusar_formato_aprendido", False):
                    print(
                        "[AUTO-DETECTOR] reusar_formato_aprendido=true — "
                        "pulando chamada de IA para este formato (extrator anterior prevalece)"
                    )
                    return None
        except Exception as _e_reuso:
            print(f"[AUTO-DETECTOR] Aviso: checagem de reuso falhou ({_e_reuso}) — seguindo fluxo normal")
        # ── fim PARTE 2a ──────────────────────────────────────────────────────

        # Monta e envia prompt
        modelo = cfg.get("modelo", _MODELO_PADRAO)
        max_tokens = _MAX_TOKENS_DETECTOR  # fixo: extração de OC precisa de muito mais tokens que o matcher
        
        prompt = _montar_prompt(texto_pdf, linhas)
        resposta = _chamar_api(prompt, chave, modelo, max_tokens)
        
        if not resposta:
            return None
        
        # Parsa resposta
        resultado_ia = _extrair_json(resposta)
        if not resultado_ia:
            print("[AUTO-DETECTOR] Resposta inválida (não-JSON)")
            return None
        
        itens = resultado_ia.get("itens", [])
        if not itens:
            print("[AUTO-DETECTOR] Nenhum item extraído pela IA")
            return None
        
        # Salva formato aprendido
        _salvar_formato_aprendido(resultado_ia, caminho_oc)
        
        # Converte para DataFrame
        df = _itens_para_dataframe(itens)
        
        if df.empty:
            print("[AUTO-DETECTOR] Falha ao converter itens para DataFrame")
            return None
        
        confianca = resultado_ia.get("confianca", "").lower()
        print(f"[AUTO-DETECTOR] {len(df)} itens detectados (confiança: {confianca})")
        
        return df
    
    except Exception as e:
        print(f"[AUTO-DETECTOR] Erro geral: {e}")
        return None
