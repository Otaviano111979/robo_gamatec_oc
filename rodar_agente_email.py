# -*- coding: utf-8 -*-
"""
rodar_agente_email.py

Script principal do agente de monitoramento de email Vortex.

Uso normal:
    python rodar_agente_email.py

Modo teste (só lê, não baixa nem responde):
    python rodar_agente_email.py --teste
"""

import os
import sys
import time
import argparse
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "agente_email"))

from config import BASE_DIR as CONFIG_BASE_DIR

PASTA_ENTRADA   = os.path.join(CONFIG_BASE_DIR, "entrada_oc")
INTERVALO_MIN   = 5
LOG_PATH        = os.path.join(CONFIG_BASE_DIR, "web", "logs", "agente_email.log")

LABEL_OC         = "Vortex/Ordem de Compra"
LABEL_COTACAO    = "Vortex/Cotação"
LABEL_REVISAO    = "Vortex/Aguardando Revisão"
LABEL_PROCESSADO = "Vortex/Processado"
LABEL_IGNORADO   = "Vortex/Ignorado"


def log(msg: str):
    linha = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linha, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def verificar_emails(servico, modo_teste: bool = False):
    from gmail_monitor import (
        listar_emails_nao_lidos,
        obter_detalhes_email,
        classificar_email,
        aplicar_label,
        marcar_como_lido,
        enviar_resposta,
        obter_cache_labels,
        ja_tem_label_vortex,
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
    if modo_teste:
        log("*** MODO TESTE — nenhuma ação será executada ***")

    # cache de labels para verificação rápida
    labels_cache = obter_cache_labels(servico)

    for msg_ref in mensagens:
        msg_id = msg_ref["id"]

        if ja_processado(msg_id):
            continue

        email_info = obter_detalhes_email(servico, msg_id)
        if not email_info:
            continue

        # ignora emails que já têm label Vortex — já foram processados
        if ja_tem_label_vortex(email_info["labels"], labels_cache):
            log(f"Ignorado (já tem label Vortex): {email_info['assunto']}")
            continue

        remetente = email_info["remetente"]
        assunto   = email_info["assunto"]
        corpo     = email_info["corpo"]
        anexos    = email_info["anexos"]

        log(f"─────────────────────────────────────────")
        log(f"De     : {remetente}")
        log(f"Assunto: {assunto}")
        log(f"Anexos : {[a['nome'] for a in anexos] or 'nenhum'}")

        classificacao, motivo = classificar_email(assunto, corpo, anexos)

        log(f"Classe : {classificacao.upper()} ({motivo})")

        if modo_teste:
            if classificacao == "ignorar":
                log(f"  → [TESTE] Seria ignorado")
            elif classificacao == "revisar":
                log(f"  → [TESTE] Iria para fila de revisão")
                log(f"  → [TESTE] Label: {LABEL_REVISAO}")
            else:
                log(f"  → [TESTE] Seria processado como {classificacao.upper()}")
                log(f"  → [TESTE] Label: {LABEL_OC if classificacao == 'oc' else LABEL_COTACAO}")
                for a in anexos:
                    if a["extensao"] == ".pdf":
                        log(f"  → [TESTE] Baixaria: {a['nome']}")
                log(f"  → [TESTE] Enviaria resposta automática para: {remetente}")
            continue

        # ── EXECUÇÃO REAL ──────────────────────────────────────
        if classificacao == "ignorar":
            marcar_como_lido(servico, msg_id)
            aplicar_label(servico, msg_id, LABEL_IGNORADO)
            registrar_processado(msg_id, {
                "remetente": remetente,
                "assunto": assunto,
                "classificacao": "ignorado",
            })
            log(f"  → Ignorado e marcado como lido.")
            continue

        if classificacao == "revisar":
            aplicar_label(servico, msg_id, LABEL_REVISAO)
            registrar_revisao(msg_id, {
                "remetente": remetente,
                "assunto":   assunto,
                "motivo":    motivo,
                "anexos":    [a["nome"] for a in anexos],
            })
            log(f"  → Enviado para revisão manual no dashboard.")
            continue

        # OC ou cotação confirmada
        label_tipo = LABEL_OC if classificacao == "oc" else LABEL_COTACAO
        aplicar_label(servico, msg_id, label_tipo)

        resultados = []
        for anexo in anexos:
            if anexo["extensao"] != ".pdf":
                continue
            log(f"  → Baixando: {anexo['nome']}")
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

        # resposta automática
        try:
            enviar_resposta(
                servico=servico,
                thread_id=email_info["thread_id"],
                para=email_info["reply_to"],
                assunto=assunto,
                tipo=classificacao,
            )
        except Exception as e:
            log(f"  ⚠️ Falha ao enviar resposta: {e}")

        aplicar_label(servico, msg_id, LABEL_PROCESSADO)
        marcar_como_lido(servico, msg_id)

        registrar_processado(msg_id, {
            "remetente":     remetente,
            "assunto":       assunto,
            "classificacao": classificacao,
            "motivo":        motivo,
            "anexos":        [r.get("nome") for r in resultados],
            "ok":            all(r.get("ok") for r in resultados),
        })

        log(f"  ✅ Processado com sucesso.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--teste",
        action="store_true",
        help="Modo teste: lê emails mas não executa nenhuma ação"
    )
    args = parser.parse_args()

    modo_teste = args.teste

    log("=" * 50)
    log("VORTEX — Agente de Email")
    if modo_teste:
        log("*** MODO TESTE ATIVADO ***")
        log("Nenhuma ação será executada.")
    else:
        log(f"Intervalo: {INTERVALO_MIN} minuto(s)")
        log(f"Entrada  : {PASTA_ENTRADA}")
    log("=" * 50)

    from gmail_monitor import autenticar_gmail

    log("Autenticando com Gmail...")
    try:
        servico = autenticar_gmail()
        log("✅ Autenticado!")
    except Exception as e:
        log(f"❌ Falha na autenticação: {e}")
        sys.exit(1)

    os.makedirs(PASTA_ENTRADA, exist_ok=True)

    if modo_teste:
        # no modo teste roda uma vez e encerra
        try:
            verificar_emails(servico, modo_teste=True)
        except Exception as e:
            log(f"❌ Erro: {e}")
            traceback.print_exc()
        log("=" * 50)
        log("Modo teste concluído. Nenhuma ação foi executada.")
        return

    # loop normal
    while True:
        try:
            log("Verificando emails...")
            verificar_emails(servico, modo_teste=False)
        except Exception as e:
            log(f"❌ Erro: {e}")
            traceback.print_exc()

        log(f"Próxima verificação em {INTERVALO_MIN} minuto(s).")
        time.sleep(INTERVALO_MIN * 60)


if __name__ == "__main__":
    main()
