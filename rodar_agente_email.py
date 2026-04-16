# -*- coding: utf-8 -*-
"""
rodar_agente_email.py

Script principal do agente de monitoramento de email.
Fica rodando em loop e verifica novos emails a cada N minutos.

Como usar:
    python rodar_agente_email.py

Para rodar em segundo plano no Windows:
    pythonw rodar_agente_email.py
"""

import os
import sys
import time
import traceback

# garante que o projeto está no path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "agente_email"))

from config import BASE_DIR as CONFIG_BASE_DIR

PASTA_ENTRADA  = os.path.join(CONFIG_BASE_DIR, "entrada_oc")
INTERVALO_MIN  = 5   # verificar a cada 5 minutos
LOG_PATH       = os.path.join(CONFIG_BASE_DIR, "web", "logs", "agente_email.log")

# labels que o agente aplica automaticamente
LABEL_OC        = "Vortex/Ordem de Compra"
LABEL_COTACAO   = "Vortex/Cotação"
LABEL_REVISAO   = "Vortex/Aguardando Revisão"
LABEL_PROCESSADO = "Vortex/Processado"
LABEL_IGNORADO  = "Vortex/Ignorado"


def log(msg: str):
    """Escreve no log e no console."""
    linha = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linha, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def verificar_emails(servico):
    """
    Verifica novos emails e processa os relevantes.
    """
    from gmail_monitor import (
        listar_emails_nao_lidos,
        obter_detalhes_email,
        classificar_email,
        aplicar_label,
        marcar_como_lido,
        enviar_resposta,
    )
    from processador_email import (
        ja_processado,
        registrar_processado,
        registrar_revisao,
        registrar_erro,
        processar_anexo_email,
    )

    mensagens = listar_emails_nao_lidos(servico, max_results=20)

    if not mensagens:
        log("Nenhum email novo.")
        return

    log(f"{len(mensagens)} email(s) não lido(s) encontrado(s).")

    for msg_ref in mensagens:
        msg_id = msg_ref["id"]

        # pula se já processado
        if ja_processado(msg_id):
            continue

        email_info = obter_detalhes_email(servico, msg_id)
        if not email_info:
            continue

        remetente = email_info["remetente"]
        assunto   = email_info["assunto"]
        anexos    = email_info["anexos"]

        log(f"Analisando: '{assunto}' de {remetente}")

        # classificar
        classificacao = classificar_email(assunto, anexos)

        if classificacao == "ignorar":
            log(f"  → Ignorado (sem anexo relevante)")
            marcar_como_lido(servico, msg_id)
            aplicar_label(servico, msg_id, LABEL_IGNORADO)
            registrar_processado(msg_id, {
                "remetente": remetente,
                "assunto": assunto,
                "classificacao": "ignorado",
            })
            continue

        if classificacao == "revisar":
            log(f"  → Fila de revisão manual")
            aplicar_label(servico, msg_id, LABEL_REVISAO)
            registrar_revisao(msg_id, {
                "remetente": remetente,
                "assunto": assunto,
                "anexos": [a["nome"] for a in anexos],
            })
            continue

        # OC ou cotação confirmada
        label_tipo = LABEL_OC if classificacao == "oc" else LABEL_COTACAO
        aplicar_label(servico, msg_id, label_tipo)

        log(f"  → Classificado como: {classificacao.upper()}")
        log(f"  → {len(anexos)} anexo(s) encontrado(s)")

        # processar cada anexo
        resultados = []
        for anexo in anexos:
            log(f"  → Processando anexo: {anexo['nome']}")
            resultado = processar_anexo_email(
                servico=servico,
                email_info=email_info,
                anexo=anexo,
                base_dir=CONFIG_BASE_DIR,
                pasta_entrada=PASTA_ENTRADA,
                classificacao=classificacao,
            )
            resultados.append(resultado)

            if resultado["ok"]:
                log(f"     ✅ Salvo em: {resultado['pasta_doc']}")
            else:
                log(f"     ❌ Erro: {resultado['erro']}")

        # enviar resposta automática
        try:
            enviar_resposta(
                servico=servico,
                thread_id=email_info["thread_id"],
                para=email_info["reply_to"],
                assunto=assunto,
                tipo=classificacao,
            )
        except Exception as e:
            log(f"  ⚠️ Falha ao enviar resposta automática: {e}")

        # aplicar label processado e marcar como lido
        aplicar_label(servico, msg_id, LABEL_PROCESSADO)
        marcar_como_lido(servico, msg_id)

        # registrar estado
        registrar_processado(msg_id, {
            "remetente":     remetente,
            "assunto":       assunto,
            "classificacao": classificacao,
            "anexos":        [r.get("nome") for r in resultados],
            "ok":            all(r.get("ok") for r in resultados),
        })

        log(f"  ✅ Email processado com sucesso.")


def main():
    log("=" * 50)
    log("VORTEX — Agente de Email iniciado")
    log(f"Intervalo de verificação: {INTERVALO_MIN} minuto(s)")
    log(f"Pasta de entrada: {PASTA_ENTRADA}")
    log("=" * 50)

    # importa depois de garantir o path
    from gmail_monitor import autenticar_gmail

    # autenticar (abre navegador na primeira vez)
    log("Autenticando com Gmail...")
    try:
        servico = autenticar_gmail()
        log("✅ Autenticado com sucesso!")
    except Exception as e:
        log(f"❌ Falha na autenticação: {e}")
        sys.exit(1)

    os.makedirs(PASTA_ENTRADA, exist_ok=True)

    # loop principal
    while True:
        try:
            log("Verificando emails...")
            verificar_emails(servico)
        except Exception as e:
            log(f"❌ Erro durante verificação: {e}")
            traceback.print_exc()

        log(f"Próxima verificação em {INTERVALO_MIN} minuto(s).")
        time.sleep(INTERVALO_MIN * 60)


if __name__ == "__main__":
    main()
