# -*- coding: utf-8 -*-
"""
agente_email/gmail_monitor.py

Conecta ao Gmail via OAuth2 e monitora a caixa de entrada.
Filtra emails com anexos PDF/XLSX e aplica tags automaticamente.
"""

import os
import re
import base64
import json
import time
import pickle
from typing import List, Dict, Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# escopos necessários
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

DIR_AGENTE          = os.path.dirname(os.path.abspath(__file__))
CAMINHO_CREDENTIALS = os.path.join(DIR_AGENTE, "credentials.json")
CAMINHO_TOKEN       = os.path.join(DIR_AGENTE, "token.pickle")

# ================================================================
# CLIENTES QUE NÃO RECEBEM RESPOSTA AUTOMÁTICA
# MRV usa sistema automatizado — resposta não é necessária nem útil
# ================================================================
CLIENTES_SEM_RESPOSTA = {"mrv"}

# ================================================================
# IDENTIFICADORES KRONA
# Busca em assunto, corpo e nome do anexo
# ================================================================
TERMOS_KRONA = [
    "krona",
    "00.145.602",        # CNPJ Krona
    "krona tubos",
    "krona conexoes",
    "kronatubos",
]

# ================================================================
# PALAVRAS-CHAVE OC / COTAÇÃO
# ================================================================
PALAVRAS_OC = [
    "ordem de compra",
    "order",
    "pedido de compra",
    "fornecimento",
    " oc ",
    "oc:",
    "oc nº",
    "oc n°",
    "pedido nº",
    "pedido n°",
]

PALAVRAS_COTACAO = [
    "cotação",
    "cotacao",
    "cotar",
    "solicitação de preço",
    "solicitacao de preco",
    "proposta",
    "orçamento",
    "orcamento",
    "price",
    "quote",
    "rfq",
    "solicito preço",
    "solicito preco",
]

# prefixos que indicam resposta/encaminhamento — não são OCs novas
PREFIXOS_RESPOSTA = [
    "re:", "res:", "rес:",
    "fwd:", "fw:", "enc:",
    "encaminhado:", "respondido:",
]

# extensões aceitas
EXTENSOES_ACEITAS = {".pdf", ".xlsx", ".xls"}


# ================================================================
# AUTENTICAÇÃO
# ================================================================
def autenticar_gmail():
    creds = None

    if os.path.exists(CAMINHO_TOKEN):
        with open(CAMINHO_TOKEN, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CAMINHO_CREDENTIALS):
                raise FileNotFoundError(
                    f"credentials.json não encontrado em: {CAMINHO_CREDENTIALS}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CAMINHO_CREDENTIALS, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(CAMINHO_TOKEN, "wb") as f:
            pickle.dump(creds, f)

    return build("gmail", "v1", credentials=creds)


# ================================================================
# LEITURA DE EMAILS
# ================================================================
def listar_emails_nao_lidos(servico, max_results: int = 20) -> List[Dict]:
    try:
        resultado = servico.users().messages().list(
            userId="me",
            labelIds=["INBOX", "UNREAD"],
            maxResults=max_results
        ).execute()
        return resultado.get("messages", [])
    except HttpError as e:
        print(f"[GMAIL] Erro ao listar emails: {e}")
        return []


def obter_detalhes_email(servico, msg_id: str) -> Optional[Dict]:
    try:
        msg = servico.users().messages().get(
            userId="me",
            id=msg_id,
            format="full"
        ).execute()

        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

        remetente  = headers.get("from", "")
        assunto    = headers.get("subject", "") or ""
        data_email = headers.get("date", "")
        reply_to   = headers.get("reply-to", remetente)

        # extrai anexos
        anexos = []
        _extrair_anexos(msg.get("payload", {}), msg_id, anexos)

        # extrai corpo do email (texto puro)
        corpo = _extrair_corpo(msg.get("payload", {}))

        return {
            "id":        msg_id,
            "thread_id": msg.get("threadId", ""),
            "remetente": remetente,
            "assunto":   assunto,
            "data":      data_email,
            "reply_to":  reply_to,
            "anexos":    anexos,
            "corpo":     corpo,
            "labels":    msg.get("labelIds", []),
        }

    except HttpError as e:
        print(f"[GMAIL] Erro ao obter email {msg_id}: {e}")
        return None


def _extrair_corpo(payload: dict) -> str:
    """Extrai texto puro do corpo do email recursivamente."""
    corpo = ""

    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if body_data:
        try:
            texto = base64.urlsafe_b64decode(body_data.encode("utf-8")).decode("utf-8", errors="ignore")
            if "text/plain" in mime_type:
                corpo += texto
            elif "text/html" in mime_type:
                # remove tags HTML
                corpo += re.sub(r"<[^>]+>", " ", texto)
        except Exception:
            pass

    for parte in payload.get("parts", []):
        corpo += _extrair_corpo(parte)

    return corpo[:3000]  # limita para não sobrecarregar


def _extrair_anexos(payload: dict, msg_id: str, lista: list):
    """Percorre recursivamente o payload e extrai anexos."""
    nome = payload.get("filename", "")
    body = payload.get("body", {})

    if nome:
        ext = os.path.splitext(nome.lower())[1]
        if ext in EXTENSOES_ACEITAS:
            lista.append({
                "nome":          nome,
                "extensao":      ext,
                "attachment_id": body.get("attachmentId", ""),
                "size":          body.get("size", 0),
            })

    for parte in payload.get("parts", []):
        _extrair_anexos(parte, msg_id, lista)


# ================================================================
# IDENTIFICAÇÃO DE CLIENTE
# ================================================================

import json as _json

_CLIENTES_PATH = os.path.join(DIR_AGENTE, "..", "dados", "clientes_conhecidos.json")


def carregar_clientes_conhecidos() -> dict:
    try:
        with open(_CLIENTES_PATH, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {"clientes": [], "cnpj_krona": [], "config": {}}


def identificar_cliente(remetente: str, assunto: str, corpo: str, anexos: list) -> dict:
    dados    = carregar_clientes_conhecidos()
    clientes = dados.get("clientes", [])
    sistemas = dados.get("sistemas", [])

    texto_completo = (remetente + " " + assunto + " " + corpo).lower()
    texto_limpo    = texto_completo.replace(".", "").replace("/", "").replace("-", "")
    nomes_anexos   = " ".join(a["nome"] for a in anexos).lower()

    # ── DETECÇÃO POR SISTEMA PROVEDOR ──────────────────────
    # Qualquer cliente que use SIENGE ou UAU é processado automaticamente
    # sem precisar cadastrar o cliente individualmente
    for sistema in sistemas:
        if not sistema.get("ativo", True):
            continue
        for marcador in sistema.get("marcadores_sistema", []):
            if marcador.lower() in texto_completo or marcador.lower() in remetente.lower():
                return {
                    "identificado":  True,
                    "id":            sistema["id"],
                    "nome":          f"Cliente via {sistema['nome']}",
                    "formato_oc":    sistema["formato_oc"],
                    "score":         5,
                    "usar_reply_to": sistema.get("usar_reply_to", False),
                    "via_sistema":   True,
                }

    # ── DETECÇÃO POR CLIENTE CADASTRADO ────────────────────
    melhor_cliente = None
    melhor_score   = 0

    for cliente in clientes:
        if not cliente.get("ativo", True):
            continue

        score = 0

        for dominio in cliente.get("dominios_email", []):
            if dominio.lower() in remetente.lower():
                score += 3
                break

        for cnpj in cliente.get("cnpjs", []):
            if cnpj in texto_limpo:
                score += 3
                break

        for palavra in cliente.get("palavras_cabecalho", []):
            if palavra.lower() in texto_completo:
                score += 2
                break

        for marcador in cliente.get("marcadores_pdf", []):
            if marcador.lower() in nomes_anexos:
                score += 1
                break

        if score > melhor_score:
            melhor_score   = score
            melhor_cliente = cliente

    score_minimo = dados.get("config", {}).get("score_minimo_identificacao", 2)

    if melhor_cliente and melhor_score >= score_minimo:
        return {
            "identificado":  True,
            "id":            melhor_cliente["id"],
            "nome":          melhor_cliente["nome"],
            "formato_oc":    melhor_cliente["formato_oc"],
            "score":         melhor_score,
            "usar_reply_to": melhor_cliente.get("usar_reply_to", False),
            "via_sistema":   False,
        }

    return {
        "identificado":  False,
        "id":            "desconhecido",
        "nome":          "Cliente nao identificado",
        "formato_oc":    None,
        "score":         melhor_score,
        "usar_reply_to": False,
        "via_sistema":   False,
    }


# ================================================================
# CLASSIFICAÇÃO
# ================================================================
def _contem_termos(texto: str, termos: list) -> bool:
    """Verifica se o texto contém algum dos termos (case insensitive)."""
    texto_lower = texto.lower()
    return any(t in texto_lower for t in termos)


def _e_resposta_ou_encaminhamento(assunto: str) -> bool:
    """Verifica se o assunto indica resposta ou encaminhamento."""
    assunto_lower = assunto.lower().strip()
    return any(assunto_lower.startswith(p) for p in PREFIXOS_RESPOSTA)


def _e_email_krona(assunto: str, corpo: str, anexos: list) -> bool:
    """
    Verifica se o email é relacionado à Krona.
    Busca em 3 lugares: assunto, corpo e nome dos anexos.
    """
    if _contem_termos(assunto, TERMOS_KRONA):
        return True
    if _contem_termos(corpo, TERMOS_KRONA):
        return True
    for anexo in anexos:
        if _contem_termos(anexo["nome"], TERMOS_KRONA):
            return True
    return False


def obter_cache_labels(servico) -> dict:
    """Retorna dicionário {label_id: label_name} para lookup rápido."""
    try:
        resultado = servico.users().labels().list(userId="me").execute()
        return {
            label["id"]: label["name"]
            for label in resultado.get("labels", [])
        }
    except Exception:
        return {}


def ja_tem_label_vortex(labels_do_email: list, labels_cache: dict) -> bool:
    """
    Verifica se o email já tem alguma label Vortex aplicada.
    Se sim, o agente já processou antes — deve ser ignorado.
    """
    for label_id in labels_do_email:
        nome = labels_cache.get(label_id, "").lower()
        if nome.startswith("vortex"):
            return True
    return False


def classificar_email(assunto: str, corpo: str, anexos: list) -> tuple:
    """
    Classifica o email em: 'oc', 'cotacao', 'revisar' ou 'ignorar'.
    Retorna (classificacao, motivo).
    """
    tem_pdf = any(a["extensao"] == ".pdf" for a in anexos)

    # regra 1: sem PDF → ignora
    if not anexos:
        return "ignorar", "sem_anexo"

    if not tem_pdf:
        return "revisar", "anexo_sem_pdf"

    # regra 2: resposta ou encaminhamento → revisão
    if _e_resposta_ou_encaminhamento(assunto):
        return "revisar", "resposta_ou_encaminhamento"

    # regra 3: não é Krona → revisão
    if not _e_email_krona(assunto, corpo, anexos):
        return "revisar", "nao_identificado_como_krona"

    # regra 4: identifica OC ou cotação
    texto_completo = (assunto + " " + corpo).lower()

    tem_oc      = any(p in texto_completo for p in PALAVRAS_OC)
    tem_cotacao = any(p in texto_completo for p in PALAVRAS_COTACAO)

    if tem_oc and not tem_cotacao:
        return "oc", "palavras_chave_oc"

    if tem_cotacao and not tem_oc:
        return "cotacao", "palavras_chave_cotacao"

    if tem_oc and tem_cotacao:
        return "revisar", "ambiguo_oc_e_cotacao"

    return "revisar", "krona_sem_tipo_definido"


# ================================================================
# LABELS
# ================================================================
def obter_ou_criar_label(servico, nome_label: str) -> Optional[str]:
    try:
        resultado = servico.users().labels().list(userId="me").execute()
        for label in resultado.get("labels", []):
            nome_existente = label["name"].lower().strip()
            nome_buscado   = nome_label.lower().strip()
            if nome_existente == nome_buscado:
                return label["id"]

        nova = servico.users().labels().create(
            userId="me",
            body={
                "name": nome_label,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show"
            }
        ).execute()
        return nova["id"]

    except HttpError as e:
        print(f"[GMAIL] Erro ao obter/criar label '{nome_label}': {e}")
        return None


def aplicar_label(servico, msg_id: str, nome_label: str):
    try:
        label_id = obter_ou_criar_label(servico, nome_label)
        if not label_id:
            return
        servico.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"addLabelIds": [label_id]}
        ).execute()
    except HttpError as e:
        print(f"[GMAIL] Erro ao aplicar label '{nome_label}': {e}")


def marcar_como_lido(servico, msg_id: str):
    try:
        servico.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
    except HttpError as e:
        print(f"[GMAIL] Erro ao marcar como lido {msg_id}: {e}")


# ================================================================
# RESPOSTA AUTOMÁTICA
# ================================================================

def deve_enviar_resposta(cliente_id: str) -> bool:
    """
    Define se o cliente recebe resposta automatica.
    MRV usa sistema automatizado — nao precisa de confirmacao por email.
    Adicione outros clientes em CLIENTES_SEM_RESPOSTA se necessario.
    """
    return cliente_id.lower() not in CLIENTES_SEM_RESPOSTA


def enviar_resposta(
    servico,
    thread_id: str,
    para: str,
    assunto: str,
    tipo: str,
    cliente_id: str = "",
):
    """
    Envia resposta automatica ao cliente.

    Regras:
    - MRV (e clientes em CLIENTES_SEM_RESPOSTA): nao envia resposta
    - OC geral: confirma recebimento, prazo 15 dias uteis
    - Cotacao: confirma recebimento, retorno em 2 dias uteis
    """
    import email.mime.text

    # seguranca: nunca envia para MRV ou clientes sem resposta
    if cliente_id and not deve_enviar_resposta(cliente_id):
        print(f"[GMAIL] Resposta suprimida — cliente '{cliente_id}' nao recebe resposta automatica.")
        return

    # extrai nome do campo "De: Nome <email@>"
    nome = para.split("<")[0].strip().strip('"')
    if not nome or "@" in nome:
        nome = "Prezado(a)"

    if tipo == "oc":
        corpo = (
            f"Ola, {nome}!\n\n"
            "Confirmamos o recebimento da sua Ordem de Compra e ja iniciamos o processamento.\n\n"
            "Prazo de entrega: 15 dias uteis apos a confirmacao do pedido.\n\n"
            "Em breve nossa equipe entrara em contato com as informacoes necessarias.\n\n"
            "Atenciosamente,\n"
            "UNE Representacoes\n"
            "Representante Oficial KRONA Tubos e Conexoes"
        )
    elif tipo == "cotacao":
        corpo = (
            f"Ola, {nome}!\n\n"
            "Recebemos sua solicitacao de Cotacao de Precos e ja estamos trabalhando nos valores.\n\n"
            "Prazo de retorno: em ate 2 dias uteis com os precos preenchidos.\n\n"
            "Em breve retornaremos com as informacoes completas.\n\n"
            "Atenciosamente,\n"
            "UNE Representacoes\n"
            "Representante Oficial KRONA Tubos e Conexoes"
        )
    else:
        # fallback para tipos inesperados
        corpo = (
            f"Ola, {nome}!\n\n"
            "Confirmamos o recebimento do seu documento e ja estamos analisando.\n\n"
            "Em breve nossa equipe entrara em contato.\n\n"
            "Atenciosamente,\n"
            "UNE Representacoes\n"
            "Representante Oficial KRONA Tubos e Conexoes"
        )

    msg = email.mime.text.MIMEText(corpo, "plain", "utf-8")
    msg["To"]      = para
    msg["Subject"] = f"Re: {assunto}"

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        servico.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": thread_id}
        ).execute()
        print(f"[GMAIL] Resposta enviada para: {para} (tipo: {tipo})")
    except HttpError as e:
        print(f"[GMAIL] Erro ao enviar resposta: {e}")


# ================================================================
# DOWNLOAD DE ANEXO
# ================================================================
def baixar_anexo(servico, msg_id: str, attachment_id: str,
                 nome_arquivo: str, pasta_destino: str) -> Optional[str]:
    try:
        anexo = servico.users().messages().attachments().get(
            userId="me",
            messageId=msg_id,
            id=attachment_id
        ).execute()

        dados = base64.urlsafe_b64decode(anexo["data"].encode("utf-8"))
        os.makedirs(pasta_destino, exist_ok=True)
        caminho = os.path.join(pasta_destino, nome_arquivo)

        with open(caminho, "wb") as f:
            f.write(dados)

        return caminho

    except Exception as e:
        print(f"[GMAIL] Erro ao baixar anexo {nome_arquivo}: {e}")
        return None
