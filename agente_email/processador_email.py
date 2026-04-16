# -*- coding: utf-8 -*-
"""
agente_email/processador_email.py

Orquestra o processamento de emails:
- Baixa anexos
- Aciona o extrator de OC
- Salva PDF original na pasta de documentos
- Registra estado dos emails processados
"""

import os
import json
import shutil
import time
from typing import Dict, Any, Optional

DIR_AGENTE   = os.path.dirname(os.path.abspath(__file__))
ESTADO_PATH  = os.path.join(DIR_AGENTE, "estado_emails.json")


def carregar_estado() -> Dict:
    """Carrega o estado dos emails já processados."""
    if not os.path.exists(ESTADO_PATH):
        return {"processados": {}, "revisao": [], "erros": []}
    try:
        with open(ESTADO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"processados": {}, "revisao": [], "erros": []}


def salvar_estado(estado: Dict):
    """Salva o estado dos emails."""
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def ja_processado(msg_id: str) -> bool:
    """Verifica se o email já foi processado."""
    estado = carregar_estado()
    return msg_id in estado.get("processados", {})


def registrar_processado(msg_id: str, dados: Dict):
    """Registra um email como processado."""
    estado = carregar_estado()
    estado.setdefault("processados", {})[msg_id] = {
        **dados,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    salvar_estado(estado)


def registrar_revisao(msg_id: str, dados: Dict):
    """Adiciona email à fila de revisão manual."""
    estado = carregar_estado()
    estado.setdefault("revisao", [])

    # evita duplicatas
    ids_revisao = [r.get("id") for r in estado["revisao"]]
    if msg_id not in ids_revisao:
        estado["revisao"].append({
            "id": msg_id,
            **dados,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        salvar_estado(estado)


def remover_da_revisao(msg_id: str):
    """Remove email da fila de revisão."""
    estado = carregar_estado()
    estado["revisao"] = [
        r for r in estado.get("revisao", [])
        if r.get("id") != msg_id
    ]
    salvar_estado(estado)


def registrar_erro(msg_id: str, dados: Dict, erro: str):
    """Registra email com erro de processamento."""
    estado = carregar_estado()
    estado.setdefault("erros", []).append({
        "id": msg_id,
        **dados,
        "erro": erro,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    salvar_estado(estado)


def pasta_documentos(base_dir: str, nome_oc: str) -> str:
    """
    Retorna (e cria) a pasta de documentos para uma OC específica.
    Estrutura: saida/documentos/<nome_oc_sem_extensao>/
    """
    base = os.path.splitext(nome_oc)[0].replace(" ", "_")
    pasta = os.path.join(base_dir, "saida", "documentos", base)
    os.makedirs(pasta, exist_ok=True)
    return pasta


def processar_anexo_email(
    servico,
    email_info: Dict,
    anexo: Dict,
    base_dir: str,
    pasta_entrada: str,
    classificacao: str
) -> Dict[str, Any]:
    """
    Processa um anexo de email:
    1. Baixa o arquivo
    2. Salva na pasta de documentos (PDF original)
    3. Copia para pasta de entrada do processador de OC

    Retorna dict com resultado.
    """
    from gmail_monitor import baixar_anexo

    nome_arquivo = anexo["nome"]
    msg_id       = email_info["id"]

    # pasta de documentos desta OC
    pasta_doc = pasta_documentos(base_dir, nome_arquivo)

    # baixa o arquivo na pasta de documentos
    caminho_baixado = baixar_anexo(
        servico,
        msg_id,
        anexo["attachment_id"],
        nome_arquivo,
        pasta_doc
    )

    if not caminho_baixado:
        return {
            "ok": False,
            "erro": f"Falha ao baixar anexo: {nome_arquivo}",
            "nome": nome_arquivo,
        }

    # salva metadados do email junto com o documento
    meta = {
        "email_id":     msg_id,
        "remetente":    email_info["remetente"],
        "assunto":      email_info["assunto"],
        "data_email":   email_info["data"],
        "classificacao": classificacao,
        "arquivo":      nome_arquivo,
        "processado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(pasta_doc, "email_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # copia para pasta de entrada do processador de OC (apenas PDFs)
    if anexo["extensao"] == ".pdf":
        destino_entrada = os.path.join(pasta_entrada, nome_arquivo)

        # evita sobrescrever arquivo existente
        if os.path.exists(destino_entrada):
            base, ext = os.path.splitext(nome_arquivo)
            ts = time.strftime("%H%M%S")
            nome_arquivo = f"{base}_{ts}{ext}"
            destino_entrada = os.path.join(pasta_entrada, nome_arquivo)

        shutil.copy2(caminho_baixado, destino_entrada)

        print(f"[AGENTE] Arquivo enviado para processamento: {nome_arquivo}")

    return {
        "ok":           True,
        "nome":         nome_arquivo,
        "pasta_doc":    pasta_doc,
        "caminho_pdf":  caminho_baixado,
        "classificacao": classificacao,
    }
