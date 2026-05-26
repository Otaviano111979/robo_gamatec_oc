from flask import Flask, render_template, request, redirect, session, send_file, jsonify, flash
import os
import sys

# ── Garante que a pasta raiz do projeto (onde fica config.py) está no path ──
# Funciona rodando de qualquer pasta: web\, raiz, ou atalho
_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import json
import subprocess
import shutil
import time
import threading
import subprocess as _subprocess_email
import re
import bcrypt

# carrega variaveis do arquivo .env (fora do codigo-fonte)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

from datetime import timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("GAMATEC_SECRET_KEY", "chave_fallback_local")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# ── Catálogo Steck/Schneider ─────────────────────────────────────────────────
# Integração gerada a partir de INTEGRACAO_VORTEX.py
try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from catalogo_steck import catalogo_bp, init_catalogo
    init_catalogo(app)
    app.register_blueprint(catalogo_bp)
    print("[CATALOGO STECK] Módulo carregado — /catalogo/steck/")
except ImportError:
    print("[CATALOGO STECK] catalogo_steck.py não encontrado — módulo desativado")

# ── Comparador de Orçamento ──────────────────────────────────────────────────
try:
    from comparador_bp import comparador_bp
    app.register_blueprint(comparador_bp)
    print("[COMPARADOR] Módulo carregado — /comparador/")
except ImportError:
    print("[COMPARADOR] comparador_bp.py não encontrado — módulo desativado")

# diretorio raiz do projeto — lido do .env, com fallback para a pasta pai deste arquivo
BASE_DIR = os.environ.get(
    "GAMATEC_BASE_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

# sessao expira apos 8 horas de inatividade
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

# limite maximo de upload: 20MB (protege contra arquivos gigantes)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

PASTA_ENTRADA = os.path.join(BASE_DIR, "entrada_oc")
PASTA_LOGS = os.path.join(BASE_DIR, "web", "logs")
PASTA_PROCESSADOS = os.path.join(BASE_DIR, "processados_oc")
PASTA_SAIDA_OCS = os.path.join(BASE_DIR, "saida", "ocs_individuais")
PASTA_DADOS = os.path.join(BASE_DIR, "dados")

USUARIOS_FILE = os.path.join(PASTA_DADOS, "usuarios.json")
CLIENTES_FILE = os.path.join(PASTA_DADOS, "clientes.json")
OCS_REMOVIDAS_FILE = os.path.join(PASTA_DADOS, "ocs_removidas_dashboard.json")

os.makedirs(PASTA_LOGS, exist_ok=True)
os.makedirs(PASTA_ENTRADA, exist_ok=True)
os.makedirs(PASTA_PROCESSADOS, exist_ok=True)
os.makedirs(PASTA_DADOS, exist_ok=True)

PROCESSOS_ATIVOS = {}
LOCK_PROCESSOS = threading.Lock()


def verificar_estado_ao_iniciar():
    # Executada uma vez quando o servidor sobe.
    # Detecta arquivos que ficaram em estado inconsistente
    # por causa de um restart ou crash anterior e registra no log.
    try:
        if not os.path.exists(PASTA_ENTRADA):
            return

        arquivos = [
            nome for nome in os.listdir(PASTA_ENTRADA)
            if os.path.isfile(os.path.join(PASTA_ENTRADA, nome))
            and nome.lower().endswith(".pdf")
        ]

        if not arquivos:
            return

        pendentes = []
        ja_processados = []

        for nome in arquivos:
            caminho_planilha = localizar_planilha_xlsx(nome)
            if caminho_planilha and os.path.exists(caminho_planilha):
                ja_processados.append(nome)
            else:
                pendentes.append(nome)

        log_init = os.path.join(PASTA_LOGS, "inicializacao_servidor.txt")
        os.makedirs(PASTA_LOGS, exist_ok=True)

        with open(log_init, "w", encoding="utf-8") as f:
            f.write("INICIALIZACAO DO SERVIDOR\n")
            f.write(f"Data/Hora: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Arquivos na entrada_oc: {len(arquivos)}\n")
            f.write(f"  Pendentes (sem planilha): {len(pendentes)}\n")
            for nome in pendentes:
                f.write(f"    - {nome}\n")
            f.write(f"  Ja processados (planilha existe): {len(ja_processados)}\n")
            for nome in ja_processados:
                f.write(f"    - {nome} [planilha disponivel - pode mover manualmente]\n")

        if ja_processados:
            print(f"[INIT] {len(ja_processados)} arquivo(s) na entrada_oc ja tem planilha gerada.")
            print(f"[INIT] Verifique o log: {log_init}")

        if pendentes:
            print(f"[INIT] {len(pendentes)} arquivo(s) na entrada_oc aguardando processamento.")

    except Exception as e:
        print(f"[INIT] Aviso: falha na verificacao de estado inicial: {e}")

# =========================
# PROTEÇÃO FORÇA BRUTA
# =========================
# estrutura: { "ip": {"tentativas": N, "bloqueado_ate": timestamp} }
TENTATIVAS_LOGIN = {}
LOCK_TENTATIVAS = threading.Lock()

MAX_TENTATIVAS = 5        # erros antes de bloquear
TEMPO_BLOQUEIO = 5 * 60   # segundos de bloqueio (5 minutos)


def ip_esta_bloqueado(ip):
    with LOCK_TENTATIVAS:
        dados = TENTATIVAS_LOGIN.get(ip)
        if not dados:
            return False
        if dados.get("bloqueado_ate", 0) > time.time():
            return True
        # bloqueio expirou — limpa o registro
        del TENTATIVAS_LOGIN[ip]
        return False


def registrar_tentativa_falha(ip):
    with LOCK_TENTATIVAS:
        dados = TENTATIVAS_LOGIN.setdefault(ip, {"tentativas": 0, "bloqueado_ate": 0})
        dados["tentativas"] += 1
        if dados["tentativas"] >= MAX_TENTATIVAS:
            dados["bloqueado_ate"] = time.time() + TEMPO_BLOQUEIO


def limpar_tentativas(ip):
    with LOCK_TENTATIVAS:
        TENTATIVAS_LOGIN.pop(ip, None)


# =========================
# UTIL
# =========================
def carregar_json(caminho_arquivo, default):
    if not os.path.exists(caminho_arquivo):
        return default
    try:
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def salvar_json(caminho_arquivo, dados):
    pasta = os.path.dirname(caminho_arquivo)
    os.makedirs(pasta, exist_ok=True)
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def usuario_logado():
    return "user" in session


def usuario_admin():
    return session.get("tipo") == "admin"


def usuario_supervisor():
    return session.get("tipo") in ("admin", "supervisor")


def usuario_operador():
    return session.get("tipo") in ("admin", "supervisor", "operador")


def nivel_acesso():
    return session.get("tipo", "operador")


# =========================
# SENHAS COM BCRYPT
# =========================
def gerar_hash_senha(senha_texto):
    """Gera o hash bcrypt de uma senha em texto puro."""
    return bcrypt.hashpw(senha_texto.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha_texto, hash_salvo):
    """
    Verifica se a senha digitada bate com o hash salvo.
    Tambem aceita senhas antigas em texto puro (para migracao automatica).
    Retorna (True/False, precisa_migrar).
    """
    # senha ja esta em hash bcrypt
    if hash_salvo.startswith("$2b$") or hash_salvo.startswith("$2a$"):
        ok = bcrypt.checkpw(senha_texto.encode("utf-8"), hash_salvo.encode("utf-8"))
        return ok, False

    # senha ainda esta em texto puro — aceita no login e sinaliza para migrar
    if senha_texto == hash_salvo:
        return True, True

    return False, False


def carregar_usuarios():
    usuarios = carregar_json(USUARIOS_FILE, {})
    if not usuarios:
        # primeiro acesso: cria admin padrao com senha JA em hash
        senha_hash = gerar_hash_senha("admin123")
        usuarios = {
            "admin": {
                "senha": senha_hash,
                "tipo": "admin"
            }
        }
        salvar_json(USUARIOS_FILE, usuarios)
    return usuarios


def salvar_usuarios(usuarios):
    salvar_json(USUARIOS_FILE, usuarios)


def migrar_senha_para_hash(user, senha_texto):
    """
    Chamada automaticamente no login quando a senha ainda esta em texto puro.
    Substitui o valor no arquivo por um hash bcrypt silenciosamente.
    """
    usuarios = carregar_usuarios()
    if user in usuarios:
        usuarios[user]["senha"] = gerar_hash_senha(senha_texto)
        salvar_usuarios(usuarios)


def carregar_clientes():
    clientes = carregar_json(CLIENTES_FILE, [])
    if not isinstance(clientes, list):
        return []
    return clientes


def salvar_clientes(clientes):
    salvar_json(CLIENTES_FILE, clientes)


def carregar_ocs_removidas():
    dados = carregar_json(OCS_REMOVIDAS_FILE, [])
    if not isinstance(dados, list):
        return []
    return dados


def salvar_ocs_removidas(arquivos):
    salvar_json(OCS_REMOVIDAS_FILE, sorted(list(set(arquivos)), key=str.lower))


def nome_base_arquivo(nome_arquivo):
    base, _ = os.path.splitext(nome_arquivo)
    return base.replace(" ", "_")


def pasta_saida_oc(nome_arquivo):
    return os.path.join(PASTA_SAIDA_OCS, nome_base_arquivo(nome_arquivo))


def listar_arquivos_pasta(pasta):
    if not os.path.exists(pasta):
        return []
    return sorted([
        nome for nome in os.listdir(pasta)
        if os.path.isfile(os.path.join(pasta, nome))
    ])


def listar_todos_arquivos():
    removidas = set(carregar_ocs_removidas())
    nomes = set()

    for nome in listar_arquivos_pasta(PASTA_ENTRADA):
        if nome not in removidas:
            nomes.add(nome)

    for nome in listar_arquivos_pasta(PASTA_PROCESSADOS):
        if nome not in removidas:
            nomes.add(nome)

    return sorted(nomes)


def arquivo_em_entrada(nome_arquivo):
    return os.path.exists(os.path.join(PASTA_ENTRADA, nome_arquivo))


def arquivo_em_processados(nome_arquivo):
    return os.path.exists(os.path.join(PASTA_PROCESSADOS, nome_arquivo))


def localizar_planilha_xlsx(nome_arquivo):
    pasta_oc = pasta_saida_oc(nome_arquivo)
    if not os.path.exists(pasta_oc):
        return None

    for nome in os.listdir(pasta_oc):
        if nome.endswith("_planilha_digitacao_manual.xlsx"):
            return os.path.join(pasta_oc, nome)

    return None


def localizar_resumo_txt(nome_arquivo):
    pasta_oc = pasta_saida_oc(nome_arquivo)
    if not os.path.exists(pasta_oc):
        return None

    for nome in os.listdir(pasta_oc):
        if nome.endswith("_resumo_processamento.txt"):
            return os.path.join(pasta_oc, nome)

    return None


def localizar_debug_txt(nome_arquivo):
    pasta_oc = pasta_saida_oc(nome_arquivo)
    if not os.path.exists(pasta_oc):
        return None

    for nome in os.listdir(pasta_oc):
        if nome.endswith("_debug_extracao.txt"):
            return os.path.join(pasta_oc, nome)

    return None


def oc_tem_saida(nome_arquivo):
    return localizar_planilha_xlsx(nome_arquivo) is not None


def caminho_log(nome_arquivo):
    return os.path.join(PASTA_LOGS, f"log_{nome_arquivo}.txt")


def escrever_log(nome_arquivo, mensagem):
    with open(caminho_log(nome_arquivo), "a", encoding="utf-8", errors="ignore") as log:
        log.write(mensagem + "\n")


def esta_processando(nome_arquivo):
    with LOCK_PROCESSOS:
        proc = PROCESSOS_ATIVOS.get(nome_arquivo)
        if not proc:
            return False

        if proc.poll() is None:
            return True

        del PROCESSOS_ATIVOS[nome_arquivo]
        return False


# tempo maximo permitido para processar uma OC (segundos)
TIMEOUT_PROCESSAMENTO = 10 * 60  # 10 minutos


def registrar_fim_processo(nome_arquivo, processo, log_handle):
    inicio = time.time()
    encerrado_por_timeout = False

    try:
        try:
            processo.wait(timeout=TIMEOUT_PROCESSAMENTO)
        except subprocess.TimeoutExpired:
            encerrado_por_timeout = True
            escrever_log(nome_arquivo, f"[WEB] TIMEOUT: processo ultrapassou {TIMEOUT_PROCESSAMENTO//60} minutos. Encerrando forcadamente.")
            processo.kill()
            processo.wait()
    finally:
        duracao = int(time.time() - inicio)
        returncode = processo.returncode

        try:
            log_handle.close()
        except Exception:
            pass

        with LOCK_PROCESSOS:
            atual = PROCESSOS_ATIVOS.get(nome_arquivo)
            if atual is processo:
                del PROCESSOS_ATIVOS[nome_arquivo]

        if encerrado_por_timeout:
            escrever_log(nome_arquivo, f"[WEB] Processo encerrado por timeout apos {duracao}s. Arquivo movido para erro_oc se possivel.")
        elif returncode == 0:
            escrever_log(nome_arquivo, f"[WEB] Processo finalizado com SUCESSO em {duracao}s (returncode=0).")
        else:
            escrever_log(nome_arquivo, f"[WEB] Processo finalizado com ERRO em {duracao}s (returncode={returncode}).")

        if arquivo_em_processados(nome_arquivo):
            escrever_log(nome_arquivo, "[WEB] PDF localizado em processados.")
        elif arquivo_em_entrada(nome_arquivo):
            escrever_log(nome_arquivo, "[WEB] PDF permaneceu na entrada.")
        else:
            escrever_log(nome_arquivo, "[WEB] PDF não localizado nem na entrada nem em processados.")


def iniciar_processamento(nome_arquivo):
    if esta_processando(nome_arquivo):
        return False, "Arquivo já está em processamento."

    caminho = os.path.join(PASTA_ENTRADA, nome_arquivo)
    if not os.path.exists(caminho):
        return False, "Arquivo não encontrado na pasta de entrada."

    log_file = caminho_log(nome_arquivo)
    log_handle = open(log_file, "w", encoding="utf-8", errors="ignore")

    processo = subprocess.Popen(
        ["python", os.path.join(BASE_DIR, "processar_oc_individual_pasta_ajustado.py"), "--arquivo", caminho],
        stdout=log_handle,
        stderr=log_handle,
        text=True
    )

    with LOCK_PROCESSOS:
        PROCESSOS_ATIVOS[nome_arquivo] = processo

    thread = threading.Thread(
        target=registrar_fim_processo,
        args=(nome_arquivo, processo, log_handle),
        daemon=True
    )
    thread.start()

    escrever_log(nome_arquivo, "[WEB] Processamento iniciado.")
    return True, "Processamento iniciado com sucesso."


def tentar_mover_para_processados(nome_arquivo, tentativas=3, espera=1.0):
    origem = os.path.join(PASTA_ENTRADA, nome_arquivo)
    destino = os.path.join(PASTA_PROCESSADOS, nome_arquivo)

    if arquivo_em_processados(nome_arquivo):
        return True, "Arquivo já está na pasta de processados."

    if esta_processando(nome_arquivo):
        return False, "Arquivo ainda está em processamento."

    if not os.path.exists(origem):
        return False, "Arquivo não encontrado na pasta de entrada."

    ultima_excecao = None

    for _ in range(tentativas):
        try:
            shutil.move(origem, destino)
            return True, f"Arquivo movido para processados: {destino}"
        except Exception as e:
            ultima_excecao = e
            time.sleep(espera)

    return False, f"Falha ao mover arquivo: {ultima_excecao}"


def extrair_numero_oc(nome_arquivo):
    """
    Extrai um número de OC do nome do arquivo.
    Prioriza sequências de 4+ dígitos.
    """
    if not nome_arquivo:
        return ""

    base = os.path.splitext(nome_arquivo)[0]
    grupos = re.findall(r"\d{4,}", base)

    if grupos:
        grupos.sort(key=len, reverse=True)
        return grupos[0]

    grupos = re.findall(r"\d+", base)
    if grupos:
        grupos.sort(key=len, reverse=True)
        return grupos[0]

    return ""


def obter_timestamp_referencia(nome_arquivo):
    """
    Usa o timestamp mais recente entre os artefatos ligados à OC
    para permitir ordenação por mais recente / mais antigo.
    """
    caminhos = [
        os.path.join(PASTA_ENTRADA, nome_arquivo),
        os.path.join(PASTA_PROCESSADOS, nome_arquivo),
        localizar_planilha_xlsx(nome_arquivo),
        localizar_resumo_txt(nome_arquivo),
        localizar_debug_txt(nome_arquivo),
        caminho_log(nome_arquivo)
    ]

    timestamps = []
    for caminho in caminhos:
        if caminho and os.path.exists(caminho):
            try:
                timestamps.append(os.path.getmtime(caminho))
            except Exception:
                pass

    if not timestamps:
        return 0

    return int(max(timestamps))


def extrair_metricas_resumo(texto):
    """
    Tenta extrair contadores operacionais a partir de resumo/log/debug sem
    exigir alteração no core do processamento.
    """
    if not texto:
        return {
            "itens_lidos": None,
            "matches_encontrados": None,
            "pendentes": None
        }

    base = str(texto)
    base_lower = base.lower()

    def _capturar(padroes):
        for padrao in padroes:
            m = re.search(padrao, base_lower, re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    continue
        return None

    itens_lidos = _capturar([
        r"(\d+)\s*itens?\s*(?:lidos|extra[ií]dos|extraidos|identificados)",
        r"(\d+)\s*iten[s]?\b"
    ])

    matches_encontrados = _capturar([
        r"(\d+)\s*matches?\s*(?:encontrados|confirmados)?",
        r"(\d+)\s*match\b",
        r"(\d+)\s*correspond[eê]ncias?\s*(?:encontradas|confirmadas)?"
    ])

    pendentes = _capturar([
        r"(\d+)\s*pendentes?\b",
        r"(\d+)\s*itens?\s*pendentes?\b"
    ])

    if itens_lidos is not None and matches_encontrados is not None and pendentes is None:
        pendentes = max(itens_lidos - matches_encontrados, 0)

    return {
        "itens_lidos": itens_lidos,
        "matches_encontrados": matches_encontrados,
        "pendentes": pendentes
    }


def inferir_progresso_oc(nome_arquivo, processando, tem_planilha, em_processados, resumo, log_file):
    """
    Infere etapa e progresso sem mexer no pipeline principal.
    Mantém compatibilidade com o front atual e adiciona metadados novos.
    """
    texto = (resumo or "").strip()

    if not texto and log_file and os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                texto = "".join(f.readlines()[-80:]).strip()
        except Exception:
            texto = ""

    texto_lower = texto.lower()

    etapa = "aguardando"
    progresso = 0
    mensagem_progresso = "Aguardando processamento."
    erro_processamento = False

    marcadores_erro = [
        "traceback", "[web] processo finalizado com erro", "erro ao",
        "exception", "falha ao", "encerrado por timeout", "timeout"
    ]

    if any(m in texto_lower for m in marcadores_erro):
        etapa = "erro"
        progresso = 100
        mensagem_progresso = "Processamento finalizado com erro."
        erro_processamento = True
    elif processando:
        if any(m in texto_lower for m in ["planilha", "excel", "gerando planilha", "montando planilha", "xlsx"]):
            etapa = "planilha"
            progresso = 85
            mensagem_progresso = "Gerando planilha Excel."
        elif any(m in texto_lower for m in ["match", "comparando", "descri", "correspond", "similaridade", "código", "codigo"]):
            etapa = "match"
            progresso = 60
            mensagem_progresso = "Comparando itens com a base de dados."
        else:
            etapa = "extracao"
            progresso = 20
            mensagem_progresso = "Extraindo itens do documento."
    elif tem_planilha:
        etapa = "concluido"
        progresso = 100
        mensagem_progresso = "Planilha gerada com sucesso."
    elif em_processados and not tem_planilha:
        etapa = "movido_sem_planilha"
        progresso = 100
        mensagem_progresso = "Documento movido, mas sem planilha detectada."
    else:
        etapa = "aguardando"
        progresso = 0
        mensagem_progresso = "Aguardando processamento."

    return {
        "etapa": etapa,
        "progresso": progresso,
        "mensagem_progresso": mensagem_progresso,
        "erro_processamento": erro_processamento
    }


def montar_status_oc(nome_arquivo):
    tem_planilha = oc_tem_saida(nome_arquivo)
    em_entrada = arquivo_em_entrada(nome_arquivo)
    em_processados = arquivo_em_processados(nome_arquivo)
    processando = esta_processando(nome_arquivo)

    resumo = ""
    resumo_path = localizar_resumo_txt(nome_arquivo)
    debug_path = localizar_debug_txt(nome_arquivo)
    log_file = caminho_log(nome_arquivo)

    if resumo_path and os.path.exists(resumo_path):
        try:
            with open(resumo_path, "r", encoding="utf-8", errors="ignore") as f:
                resumo = f.read().strip()
        except Exception:
            resumo = ""

    if not resumo and debug_path and os.path.exists(debug_path):
        try:
            with open(debug_path, "r", encoding="utf-8", errors="ignore") as f:
                resumo = "".join(f.readlines()[:25]).strip()
        except Exception:
            resumo = ""

    if not resumo and os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                resumo = "".join(f.readlines()[-30:]).strip()
        except Exception:
            resumo = ""

    progresso_info = inferir_progresso_oc(
        nome_arquivo=nome_arquivo,
        processando=processando,
        tem_planilha=tem_planilha,
        em_processados=em_processados,
        resumo=resumo,
        log_file=log_file
    )

    metricas = extrair_metricas_resumo(resumo)

    if processando:
        status_label = "Processando"
        status_classe = "status-running"
    elif tem_planilha and em_processados:
        status_label = "Concluído"
        status_classe = "status-ok"
    elif tem_planilha and em_entrada:
        status_label = "Concluído / aguardando mover"
        status_classe = "status-warning"
    elif em_entrada:
        status_label = "Na entrada"
        status_classe = "status-pending"
    elif em_processados and not tem_planilha:
        status_label = "Movido sem planilha detectada"
        status_classe = "status-warning"
    else:
        status_label = "Sem localização definida"
        status_classe = "status-warning"

    if progresso_info["etapa"] == "erro":
        status_label = "Erro no processamento"
        status_classe = "status-warning"

    if tem_planilha:
        planilha_label = "Disponível para subir no GAMATEC"
    else:
        planilha_label = "Ainda não gerada"

    if processando:
        movimento_label = "Em processamento"
    elif em_processados:
        movimento_label = "PDF em processados"
    elif em_entrada:
        movimento_label = "PDF na entrada"
    else:
        movimento_label = "PDF não localizado"

    if not resumo:
        resumo = "Sem resumo disponível no momento."

    ts = obter_timestamp_referencia(nome_arquivo)
    data_ref = ""
    data_ref_iso = ""

    if ts > 0:
        data_ref = time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
        data_ref_iso = time.strftime("%Y-%m-%d", time.localtime(ts))

    # lê flag cliente_novo do email_meta.json se existir
    cliente_novo = False
    if nome_arquivo.startswith("EMAIL_"):
        nome_base = nome_base_arquivo(nome_arquivo)
        meta_path = os.path.join(BASE_DIR, "saida", "documentos", nome_base, "email_meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                cliente_novo = bool(meta.get("cliente_novo", False))
            except Exception:
                pass

    return {
        "nome": nome_arquivo,
        "nome_base": nome_base_arquivo(nome_arquivo),
        "numero_oc": extrair_numero_oc(nome_arquivo),
        "timestamp_ref": ts,
        "data_ref": data_ref,
        "data_ref_iso": data_ref_iso,
        "tem_planilha": tem_planilha,
        "status_label": status_label,
        "status_classe": status_classe,
        "planilha_label": planilha_label,
        "movimento_label": movimento_label,
        "resumo": resumo,
        "em_entrada": em_entrada,
        "em_processados": em_processados,
        "processando": processando,
        "etapa": progresso_info["etapa"],
        "progresso": progresso_info["progresso"],
        "mensagem_progresso": progresso_info["mensagem_progresso"],
        "erro_processamento": progresso_info["erro_processamento"],
        "itens_lidos": metricas["itens_lidos"],
        "matches_encontrados": metricas["matches_encontrados"],
        "pendentes": metricas["pendentes"],
        "cliente_novo": cliente_novo,
    }


@app.after_request
def desabilitar_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.errorhandler(413)
def arquivo_muito_grande(e):
    # disparado quando o upload ultrapassa MAX_CONTENT_LENGTH
    return redirect("/dashboard?erro=arquivo_grande")


# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    erro = None
    ip = request.remote_addr

    if ip_esta_bloqueado(ip):
        erro = "Muitas tentativas incorretas. Aguarde 5 minutos e tente novamente."
        return render_template("login.html", erro=erro)

    if request.method == "POST":
        user = request.form.get("user", "").strip()
        senha = request.form.get("senha", "").strip()

        usuarios = carregar_usuarios()

        if user in usuarios:
            hash_salvo = usuarios[user].get("senha", "")
            ok, precisa_migrar = verificar_senha(senha, hash_salvo)

            if ok:
                # migracao automatica silenciosa: substitui texto puro por hash
                if precisa_migrar:
                    migrar_senha_para_hash(user, senha)

                limpar_tentativas(ip)  # login ok: zera o contador
                session.permanent = True  # ativa o timeout configurado
                session["user"] = user
                session["tipo"] = usuarios[user].get("tipo", "user")
                return redirect("/launcher")

        registrar_tentativa_falha(ip)
        erro = "Usuário ou senha incorretos."

    return render_template("login.html", erro=erro)


# =========================
# LAUNCHER
# =========================
@app.route("/launcher")
def launcher():
    if "user" not in session:
        return redirect("/")

    try:
        from launcher import listar_empresas, VORTEX_ROOT
        empresas_raw = listar_empresas()
    except Exception:
        # modo legado — monta empresa UNE direto
        empresas_raw = [{
            "id": "une", "nome": "UNE Representações",
            "modulos_ativos": ["oc", "email"], "modulos_trial": [],
            "ativo": True,
        }]

    # paleta de avatars
    av_classes = ["av-blue", "av-teal", "av-amber", "av-blue"]
    empresas = []
    for i, e in enumerate(empresas_raw):
        nome  = e["nome"]
        sigla = "".join(p[0].upper() for p in nome.split()[:3])
        empresas.append({
            "id":           e["id"],
            "nome":         nome,
            "sigla":        sigla,
            "avatar_class": av_classes[i % len(av_classes)],
            "ativo":        e.get("ativo", True),
            "meta":         f"módulos: {', '.join(e.get('modulos_ativos',[]))}",
        })

    import json as _json
    modulos_json = _json.dumps({
        e["id"]: {
            "ativos": e.get("modulos_ativos", []),
            "trial":  e.get("modulos_trial",  []),
        }
        for e in empresas_raw
    })

    # urls por empresa (porta pode variar no futuro)
    empresa_urls = _json.dumps({e["id"]: "" for e in empresas_raw})

    try:
        from config import VERSAO_SISTEMA
    except ImportError:
        VERSAO_SISTEMA = "1.0"
    return render_template(
        "launcher.html",
        empresas=empresas,
        modulos_json=modulos_json,
        empresa_urls=empresa_urls,
        versao=VERSAO_SISTEMA,
    )


# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():
    if not usuario_logado():
        return redirect("/")

    arquivos = [montar_status_oc(nome) for nome in listar_todos_arquivos()]
    arquivos.sort(key=lambda x: x.get("timestamp_ref", 0), reverse=True)

    # contadores para os cartoes de resumo no topo
    total_entrada    = sum(1 for a in arquivos if a.get("em_entrada") and not a.get("processando"))
    total_processando = sum(1 for a in arquivos if a.get("processando"))
    total_concluidos = sum(1 for a in arquivos if a.get("tem_planilha") and a.get("em_processados"))
    
    # total de itens pendentes de revisão
    try:
        from dados.revisao_store import contar_pendentes
        total_revisao = contar_pendentes()
    except Exception:
        total_revisao = 0

    return render_template(
        "dashboard.html",
        arquivos=arquivos,
        total_entrada=total_entrada,
        total_processando=total_processando,
        total_concluidos=total_concluidos,
        total_revisao=total_revisao,
    )


# =========================
# DASHBOARD V2 (redesign clean)
# =========================
@app.route("/dashboard_v2")
def dashboard_v2():
    if not usuario_logado():
        return redirect("/")

    arquivos = [montar_status_oc(nome) for nome in listar_todos_arquivos()]
    arquivos.sort(key=lambda x: x.get("timestamp_ref", 0), reverse=True)

    total_entrada     = sum(1 for a in arquivos if a.get("em_entrada") and not a.get("processando"))
    total_processando = sum(1 for a in arquivos if a.get("processando"))
    total_concluidos  = sum(1 for a in arquivos if a.get("tem_planilha") and a.get("em_processados"))

    # itens de revisão: divergências do shadow mode com score abaixo de 0.80
    itens_revisao = []
    shadow_path = os.path.join(BASE_DIR, "saida", "shadow_mode.jsonl")
    if os.path.exists(shadow_path):
        try:
            seen = set()
            with open(shadow_path, "r", encoding="utf-8") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        reg = json.loads(linha)
                    except Exception:
                        continue
                    if reg.get("concordam"):
                        continue
                    score = float(reg.get("motor_atual", {}).get("score") or 0)
                    desc  = reg.get("descricao_oc", "")
                    if not desc or desc in seen:
                        continue
                    seen.add(desc)
                    itens_revisao.append({
                        "descricao_oc": desc,
                        "tipo_match":   reg.get("motor_atual", {}).get("tipo_match") or "—",
                        "arquivo":      reg.get("ts", "")[:10],
                        "score_total":  score,
                    })
            itens_revisao.sort(key=lambda x: x["score_total"])
        except Exception:
            itens_revisao = []

    return render_template(
        "dashboard_v2.html",
        arquivos=arquivos,
        total_entrada=total_entrada,
        total_processando=total_processando,
        total_concluidos=total_concluidos,
        itens_revisao=itens_revisao,
    )


# =========================
# PROCESSAR OC
# =========================
@app.route("/processar/<path:arquivo>")
def processar(arquivo):
    if not usuario_logado():
        return redirect("/")

    ok, mensagem = iniciar_processamento(arquivo)
    escrever_log(arquivo, f"[AÇÃO PROCESSAR] {mensagem}")
    return redirect("/dashboard")


@app.route("/api/processar-oc/<path:arquivo>", methods=["POST"])
def api_processar_oc(arquivo):
    if not usuario_logado():
        return jsonify({
            "ok": False,
            "mensagem": "Acesso negado."
        }), 403

    ok, mensagem = iniciar_processamento(arquivo)
    escrever_log(arquivo, f"[AÇÃO PROCESSAR API] {mensagem}")

    return jsonify({
        "ok": ok,
        "mensagem": mensagem,
        "arquivo": arquivo,
        "status": montar_status_oc(arquivo)
    })


# =========================
# REMOVER DA LISTA
# =========================
@app.route("/api/remover-da-lista/<path:arquivo>", methods=["POST"])
def api_remover_da_lista(arquivo):
    if not usuario_logado():
        return jsonify({
            "ok": False,
            "mensagem": "Acesso negado."
        }), 403

    existe = arquivo_em_entrada(arquivo) or arquivo_em_processados(arquivo)
    if not existe:
        return jsonify({
            "ok": False,
            "mensagem": "Arquivo não encontrado."
        }), 404

    removidas = carregar_ocs_removidas()
    if arquivo not in removidas:
        removidas.append(arquivo)
        salvar_ocs_removidas(removidas)

    escrever_log(arquivo, "[AÇÃO WEB] OC removida da lista do dashboard.")

    return jsonify({
        "ok": True,
        "mensagem": "OC removida da lista do dashboard.",
        "arquivo": arquivo
    })


# =========================
# STATUS OC
# =========================
@app.route("/status-oc/<path:arquivo>")
def status_oc(arquivo):
    if not usuario_logado():
        return jsonify({"erro": "Acesso negado."}), 403

    return jsonify(montar_status_oc(arquivo))


# =========================
# BAIXAR PLANILHA
# =========================
@app.route("/api/ia/status")
def api_ia_status():
    """Status da IA para o painel."""
    try:
        from ia_helper import status_ia
        return jsonify(status_ia())
    except Exception:
        return jsonify({"disponivel": False, "modo": "SIMULADO", "modelo": "-"})


@app.route("/api/ia/configurar", methods=["POST"])
def api_ia_configurar():
    """Salva a chave API da IA. Chamada pelo painel do operador."""
    try:
        from ia_helper import salvar_chave
        dados = request.get_json(force=True) or {}
        chave = str(dados.get("chave") or "").strip()
        if not chave:
            return jsonify({"ok": False, "erro": "Chave não informada"}), 400
        if not chave.startswith("sk-ant-"):
            return jsonify({"ok": False, "erro": "Chave inválida — deve começar com sk-ant-"}), 400
        salvar_chave(chave)
        return jsonify({"ok": True, "mensagem": "Chave salva! Reinicie o servidor para ativar."})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/aprendizado/stats")
def api_aprendizado_stats():
    """Estatísticas do sistema de aprendizado para o painel."""
    try:
        from aprendizado_regras import stats_aprendizado, carregar_regras
        stats = stats_aprendizado()
        regras = carregar_regras()
        # ultimas 5 regras promovidas
        ultimas = sorted(regras.items(),
                         key=lambda x: x[1].get("promovido_em",""),
                         reverse=True)[:5]
        stats["ultimas_regras"] = [
            {"descricao": v["descricao_original"][:60],
             "codigo": v["codigo_krona"],
             "confirmacoes": v["confirmacoes"]}
            for _, v in ultimas
        ]
        return jsonify(stats)
    except Exception as e:
        return jsonify({"total_correcoes": 0, "total_regras": 0,
                        "total_clientes": 0, "ultimas_regras": []})


@app.route("/api/registrar-correcao", methods=["POST"])
def api_registrar_correcao():
    """
    Registra uma correcao manual do operador no historico de aprendizado.
    Chamada quando o operador corrige um codigo na planilha.
    Payload JSON: {
        descricao_oc, codigo_krona_correto, cliente_id, cliente_nome,
        codigo_krona_sugerido (opcional), motivo (opcional)
    }
    """
    try:
        from historico_aprendizado import registrar_validacao_manual, inicializar_banco
        from base_krona_loader import buscar_cadastro_krona_por_codigo, carregar_base_krona
        inicializar_banco()

        dados = request.get_json(force=True) or {}
        descricao_oc   = str(dados.get("descricao_oc") or "").strip()
        codigo_correto = str(dados.get("codigo_krona_correto") or "").strip()
        cliente_id     = str(dados.get("cliente_id") or "").strip() or None
        cliente_nome   = str(dados.get("cliente_nome") or "").strip() or None
        motivo         = str(dados.get("motivo") or "").strip() or None

        if not descricao_oc or not codigo_correto:
            return jsonify({"ok": False, "erro": "descricao_oc e codigo_krona_correto sao obrigatorios"}), 400

        # buscar descricao krona para o codigo corrigido
        base = carregar_base_krona()
        cadastro = buscar_cadastro_krona_por_codigo(codigo_correto, base)
        desc_krona = cadastro.get("descricao_krona") if cadastro else None

        registrar_validacao_manual(
            cliente_id=cliente_id,
            cliente_nome=cliente_nome,
            descricao_oc_original=descricao_oc,
            descricao_oc_normalizada=descricao_oc.upper().strip(),
            codigo_krona_aprovado=codigo_correto,
            descricao_krona_aprovada=desc_krona,
            tipo_match_final="CORRECAO_MANUAL",
            observacoes=motivo,
        )

        return jsonify({"ok": True, "mensagem": f"Correcao registrada: {descricao_oc} → {codigo_correto}"})

    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/baixar-planilha/<path:arquivo>")
def baixar_planilha(arquivo):
    if not usuario_logado():
        return redirect("/")

    planilha = localizar_planilha_xlsx(arquivo)
    if not planilha or not os.path.exists(planilha):
        return redirect("/dashboard")

    return send_file(planilha, as_attachment=True)


# =========================
# LOGS
# =========================
@app.route("/logs/<path:arquivo>")
def logs(arquivo):
    if not usuario_logado():
        return "Acesso negado."

    log_file = caminho_log(arquivo)

    if not os.path.exists(log_file):
        return "Sem logs ainda."

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


# =========================
# UPLOAD
# =========================
@app.route("/upload", methods=["POST"])
def upload():
    if not usuario_logado():
        return redirect("/")

    file = request.files.get("file")

    if file and file.filename:
        # seguranca: aceita apenas arquivos .pdf
        nome_original = file.filename
        extensao = os.path.splitext(nome_original)[1].lower()

        if extensao != ".pdf":
            flash("error:Apenas arquivos PDF são aceitos.")
            return redirect("/dashboard")

        # seguranca: limpa o nome para evitar path traversal
        from werkzeug.utils import secure_filename
        nome_seguro = secure_filename(nome_original)

        if not nome_seguro:
            flash("error:Nome de arquivo inválido.")
            return redirect("/dashboard")

        caminho = os.path.join(PASTA_ENTRADA, nome_seguro)
        file.save(caminho)
        flash(f"ok:{nome_seguro} enviado com sucesso para a fila.")
    else:
        flash("error:Nenhum arquivo selecionado.")

    return redirect("/dashboard")


# =========================
# MOVER PROCESSADO
# =========================
@app.route("/mover-processado/<path:arquivo>")
def mover_processado(arquivo):
    if not usuario_logado():
        return redirect("/")

    escrever_log(arquivo, "[AÇÃO] Solicitação manual para mover arquivo.")
    ok, mensagem = tentar_mover_para_processados(arquivo)
    escrever_log(arquivo, f"[RESULTADO] {mensagem}")

    return redirect("/dashboard")


# =========================
# ADMIN CLIENTES
# =========================
@app.route("/admin/clientes", methods=["GET", "POST"])
def admin_clientes():
    if not usuario_logado():
        return redirect("/")

    if not usuario_admin():
        return redirect("/dashboard")

    clientes = carregar_clientes()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()

        if nome:
            ja_existe = any(
                c.get("nome", "").strip().lower() == nome.lower()
                for c in clientes
            )

            if not ja_existe:
                clientes.append({"nome": nome})
                clientes.sort(key=lambda x: x.get("nome", "").lower())
                salvar_clientes(clientes)

        return redirect("/admin/clientes")

    return render_template("admin_clientes.html", clientes=clientes)


# =========================
# ADMIN USUÁRIOS
# =========================
@app.route("/admin/usuarios", methods=["GET", "POST"])
def admin_usuarios():
    if not usuario_logado():
        return redirect("/")

    if not usuario_admin():
        return redirect("/dashboard")

    usuarios = carregar_usuarios()

    if request.method == "POST":
        user = request.form.get("user", "").strip()
        senha = request.form.get("senha", "").strip()
        tipo = request.form.get("tipo", "user").strip().lower()

        if user and senha:
            if tipo not in ("admin", "supervisor", "operador"):
                tipo = "user"

            if user not in usuarios:
                # seguranca: salva o hash da senha, nunca o texto puro
                usuarios[user] = {
                    "senha": gerar_hash_senha(senha),
                    "tipo": tipo
                }
                salvar_usuarios(usuarios)

        return redirect("/admin/usuarios")

    usuarios_lista = []
    for nome, dados in usuarios.items():
        usuarios_lista.append({
            "user": nome,
            "tipo": dados.get("tipo", "user")
        })

    usuarios_lista.sort(key=lambda x: x["user"].lower())

    return render_template("admin_usuarios.html", usuarios=usuarios_lista)


# =========================
# EXCLUIR USUÁRIO
# =========================
@app.route("/admin/usuarios/excluir/<user_alvo>", methods=["POST"])
def excluir_usuario(user_alvo):
    if not usuario_logado():
        return redirect("/")

    if not usuario_admin():
        return redirect("/dashboard")

    # protecao: admin nao pode excluir a si mesmo
    if user_alvo == session.get("user"):
        return redirect("/admin/usuarios")

    usuarios = carregar_usuarios()

    if user_alvo in usuarios:
        del usuarios[user_alvo]
        salvar_usuarios(usuarios)

    return redirect("/admin/usuarios")


# =========================
# ALTERAR SENHA DE USUÁRIO
# =========================
@app.route("/admin/usuarios/alterar-senha/<user_alvo>", methods=["POST"])
def alterar_senha_usuario(user_alvo):
    if not usuario_logado():
        return redirect("/")

    if not usuario_admin():
        return redirect("/dashboard")

    nova_senha = request.form.get("nova_senha", "").strip()

    if not nova_senha:
        return redirect("/admin/usuarios")

    usuarios = carregar_usuarios()

    if user_alvo in usuarios:
        usuarios[user_alvo]["senha"] = gerar_hash_senha(nova_senha)
        salvar_usuarios(usuarios)

    return redirect("/admin/usuarios")


# =========================
# AUTOMAÇÃO GAMATEC
# =========================

AUTOMACAO_ATIVA = {}
LOCK_AUTOMACAO = threading.Lock()


def status_automacao(nome_oc):
    caminho = os.path.join(BASE_DIR, "saida", "ocs_individuais",
                           nome_oc.replace(" ", "_").replace(".pdf", ""),
                           "automacao_status.json")
    if not os.path.exists(caminho):
        return None
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def esta_automatizando(nome_oc):
    with LOCK_AUTOMACAO:
        proc = AUTOMACAO_ATIVA.get(nome_oc)
        if not proc:
            return False
        if proc.poll() is None:
            return True
        del AUTOMACAO_ATIVA[nome_oc]
        return False


# =========================
# CALIBRAÇÃO VIA INTERFACE
# =========================

CALIBRACAO_EM_ANDAMENTO = {}
CALIBRACAO_DADOS = {}
LOCK_CALIBRACAO = threading.Lock()

# =========================
# ESTADO AGENTE EMAIL
# =========================
_agente_email_proc   = None
_agente_email_lock   = threading.Lock()
_agente_email_status = {
    "ativo":            False,
    "iniciado_em":      None,
    "ultimo_check":     None,
    "emails_hoje":      0,
    "erro":             None,
    "token_expirado":   False,
}


def _atualizar_status_email():
    log_path = os.path.join(BASE_DIR, "web", "logs", "agente_email.log")
    if not os.path.exists(log_path):
        return
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            linhas = f.readlines()

        hoje = time.strftime("%Y-%m-%d")
        emails_hoje = sum(
            1 for l in linhas
            if hoje in l and "✅ Processado com sucesso" in l
        )
        _agente_email_status["emails_hoje"] = emails_hoje

        # ultima linha com timestamp
        for linha in reversed(linhas):
            if linha.strip():
                _agente_email_status["ultimo_check"] = linha[:19]
                break

        # verifica token expirado
        token_exp = any(
            "token" in l.lower() and ("expir" in l.lower() or "invalid" in l.lower())
            for l in linhas[-20:]
        )
        _agente_email_status["token_expirado"] = token_exp

    except Exception:
        pass


def iniciar_agente_email():
    global _agente_email_proc
    with _agente_email_lock:
        if _agente_email_proc and _agente_email_proc.poll() is None:
            return False, "Agente já está rodando."

        script = os.path.join(BASE_DIR, "rodar_agente_email.py")
        if not os.path.exists(script):
            return False, "Script do agente não encontrado."

        token_path = os.path.join(BASE_DIR, "agente_email", "token.pickle")
        if not os.path.exists(token_path):
            return False, "token_nao_encontrado"

        log_path = os.path.join(BASE_DIR, "web", "logs", "agente_email.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        try:
            log_handle = open(log_path, "a", encoding="utf-8", errors="ignore")
            _agente_email_proc = _subprocess_email.Popen(
                ["python", script],
                stdout=log_handle,
                stderr=log_handle,
                text=True,
                cwd=BASE_DIR
            )
            _agente_email_status["ativo"]       = True
            _agente_email_status["iniciado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _agente_email_status["erro"]        = None
            _agente_email_status["token_expirado"] = False
            return True, "Agente iniciado com sucesso."
        except Exception as e:
            return False, str(e)


def parar_agente_email():
    global _agente_email_proc
    with _agente_email_lock:
        if not _agente_email_proc or _agente_email_proc.poll() is not None:
            _agente_email_status["ativo"] = False
            return False, "Agente não está rodando."
        try:
            _agente_email_proc.terminate()
            _agente_email_proc.wait(timeout=5)
        except Exception:
            try:
                _agente_email_proc.kill()
            except Exception:
                pass
        _agente_email_status["ativo"] = False
        return True, "Agente parado."


def status_agente_email() -> dict:
    global _agente_email_proc
    with _agente_email_lock:
        rodando = _agente_email_proc is not None and _agente_email_proc.poll() is None
        _agente_email_status["ativo"] = rodando
    _atualizar_status_email()
    return dict(_agente_email_status)

PONTOS_CALIBRACAO = [
    {"id": "codigo_1",    "label": "Centro do CÓDIGO da PRIMEIRA linha"},
    {"id": "codigo_2",    "label": "Centro do CÓDIGO da SEGUNDA linha"},
    {"id": "desc",        "label": "Centro da DESCRIÇÃO da PRIMEIRA linha"},
    {"id": "ult_preco",   "label": "Centro do campo ÚLT. PREÇO da PRIMEIRA linha"},
    {"id": "final",       "label": "Centro do campo FINAL da PRIMEIRA linha"},
    {"id": "desc_campo",  "label": "Centro do campo % DESC da PRIMEIRA linha"},
    {"id": "scroll",      "label": "Ponto seguro da ÁREA DA GRADE para scroll"},
]


@app.route("/api/calibracao/pontos")
def api_calibracao_pontos():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403
    return jsonify({"ok": True, "pontos": PONTOS_CALIBRACAO})


@app.route("/api/calibracao/capturar/<ponto_id>", methods=["POST"])
def api_calibracao_capturar(ponto_id):
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    espera = int(request.json.get("espera", 3)) if request.is_json else 3

    try:
        import pyautogui

        # aguarda o operador posicionar o mouse no GAMATEC
        # quando espera=0 a contagem ja foi feita no frontend
        if espera > 0:
            for i in range(espera, 0, -1):
                time.sleep(1)

        x, y = pyautogui.position()

        with LOCK_CALIBRACAO:
            if "pontos" not in CALIBRACAO_DADOS:
                CALIBRACAO_DADOS["pontos"] = {}
            CALIBRACAO_DADOS["pontos"][ponto_id] = {"x": x, "y": y}

        return jsonify({
            "ok": True,
            "ponto_id": ponto_id,
            "x": x,
            "y": y,
            "mensagem": f"Capturado: ({x}, {y})"
        })

    except Exception as e:
        return jsonify({"ok": False, "mensagem": f"Erro ao capturar posição: {e}"}), 500


@app.route("/api/calibracao/salvar", methods=["POST"])
def api_calibracao_salvar():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    with LOCK_CALIBRACAO:
        pontos = CALIBRACAO_DADOS.get("pontos", {})

    ids_necessarios = [p["id"] for p in PONTOS_CALIBRACAO]
    faltando = [pid for pid in ids_necessarios if pid not in pontos]

    if faltando:
        return jsonify({
            "ok": False,
            "mensagem": f"Pontos não capturados: {', '.join(faltando)}"
        }), 400

    try:
        p = pontos

        x_codigo_1 = p["codigo_1"]["x"]
        y_codigo_1 = p["codigo_1"]["y"]
        x_codigo_2 = p["codigo_2"]["x"]
        y_codigo_2 = p["codigo_2"]["y"]

        passo_linha = y_codigo_2 - y_codigo_1
        if passo_linha <= 0:
            return jsonify({
                "ok": False,
                "mensagem": "Passo de linha inválido. A segunda linha deve estar abaixo da primeira."
            }), 400

        calibracao = {
            "x_codigo":           x_codigo_1 - 24,
            "y_codigo_linha1":    y_codigo_1 - 14,
            "y_codigo_linha2":    y_codigo_2 - 14,
            "x_desc":             p["desc"]["x"] - 180,
            "x_ult_preco":        p["ult_preco"]["x"] - 80,
            "x_final":            p["final"]["x"] - 80,
            "w_codigo": 95,  "h_codigo": 30,
            "w_desc": 430,   "h_desc": 30,
            "w_ult_preco": 170, "h_ult_preco": 30,
            "w_final": 170,  "h_final": 30,
            "offset_y_codigo": 0, "offset_y_desc": 0,
            "offset_y_ult": 0,    "offset_y_final": 0,
            "x_desc_campo":           p["desc_campo"]["x"],
            "y_desc_campo_linha1":    p["desc_campo"]["y"],
            "x_area_scroll":          p["scroll"]["x"],
            "y_area_scroll":          p["scroll"]["y"],
            "scroll_click_antes": True,
            "scroll_quantidade": -650,
            "separador_decimal_desconto": ".",
            "casas_decimais_desconto": 2,
            "usar_ctrl_a_para_limpar": True,
            "confirmar_com_enter": True,
            "duplo_clique_campo_desc": True,
            "max_tentativas_aplicar_desconto": 2,
            "max_varredura_linhas": 3,
            "raio_x_codigo": 2, "raio_y_codigo": 2, "passo_busca_codigo": 2,
            "raio_x_desc": 2,   "raio_y_desc": 2,   "passo_busca_desc": 2,
            "raio_x_preco": 2,  "raio_y_preco": 2,  "passo_busca_preco": 2,
            "max_variantes_codigo": 2, "max_variantes_desc": 1, "max_variantes_preco": 2,
            "crop_left_codigo": 2,  "crop_top_codigo": 3,
            "crop_right_codigo": 4, "crop_bottom_codigo": 3,
            "crop_left_desc": 4,    "crop_top_desc": 3,
            "crop_right_desc": 8,   "crop_bottom_desc": 3,
            "crop_left_preco": 8,   "crop_top_preco": 3,
            "crop_right_preco": 12, "crop_bottom_preco": 3,
            "exigir_descricao_min_chars": 4,
            "ancorar_com_descricao": True,
            "ancorar_com_preco": True,
            "log_ocr": False,
        }

        caminho = os.path.join(BASE_DIR, "saida", "calibracao_gamatec.json")
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(calibracao, f, ensure_ascii=False, indent=2)

        # limpa dados temporários
        with LOCK_CALIBRACAO:
            CALIBRACAO_DADOS.clear()

        return jsonify({
            "ok": True,
            "mensagem": "Calibração salva com sucesso!",
            "passo_linha": passo_linha,
            "caminho": caminho
        })

    except Exception as e:
        return jsonify({"ok": False, "mensagem": f"Erro ao salvar calibração: {e}"}), 500


@app.route("/api/calibracao/resetar", methods=["POST"])
def api_calibracao_resetar():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    with LOCK_CALIBRACAO:
        CALIBRACAO_DADOS.clear()

    caminho = os.path.join(BASE_DIR, "saida", "calibracao_gamatec.json")
    if os.path.exists(caminho):
        os.remove(caminho)

    return jsonify({"ok": True, "mensagem": "Calibração resetada."})


@app.route("/api/verificar-calibracao")
def api_verificar_calibracao():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    caminho = os.path.join(BASE_DIR, "saida", "calibracao_gamatec.json")
    existe = os.path.exists(caminho)

    return jsonify({
        "ok": True,
        "calibrado": existe,
        "caminho": caminho if existe else None,
        "mensagem": "Calibracao encontrada." if existe else "Calibracao nao encontrada. Execute calibrar_gamatec.py primeiro."
    })


@app.route("/api/iniciar-automacao/<path:arquivo>", methods=["POST"])
def api_iniciar_automacao(arquivo):
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    if esta_automatizando(arquivo):
        return jsonify({"ok": False, "mensagem": "Automação já está em andamento para esta OC."}), 409

    # localizar a planilha individual da OC
    planilha = localizar_planilha_xlsx(arquivo)
    if not planilha or not os.path.exists(planilha):
        return jsonify({"ok": False, "mensagem": "Planilha desta OC não encontrada. Processe a OC primeiro."}), 404

    script = os.path.join(BASE_DIR, "rodar_agente_gamatec_web.py")
    if not os.path.exists(script):
        return jsonify({"ok": False, "mensagem": "Script de automação não encontrado."}), 500

    log_automacao = os.path.join(BASE_DIR, "web", "logs", f"automacao_{arquivo}.txt")

    try:
        log_handle = open(log_automacao, "w", encoding="utf-8", errors="ignore")
        processo = subprocess.Popen(
            ["python", script, "--planilha", planilha, "--oc", arquivo],
            stdout=log_handle,
            stderr=log_handle,
            text=True
        )

        with LOCK_AUTOMACAO:
            AUTOMACAO_ATIVA[arquivo] = processo

        escrever_log(arquivo, f"[AUTOMAÇÃO] Iniciada para planilha: {planilha}")

        return jsonify({
            "ok": True,
            "mensagem": "Automação iniciada.",
            "arquivo": arquivo
        })
    except Exception as e:
        return jsonify({"ok": False, "mensagem": f"Falha ao iniciar automação: {e}"}), 500


@app.route("/api/status-automacao/<path:arquivo>")
def api_status_automacao(arquivo):
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    automatizando = esta_automatizando(arquivo)
    status = status_automacao(arquivo)

    log_automacao = os.path.join(BASE_DIR, "web", "logs", f"automacao_{arquivo}.txt")
    log_texto = ""
    if os.path.exists(log_automacao):
        try:
            with open(log_automacao, "r", encoding="utf-8", errors="ignore") as f:
                linhas = f.readlines()
                log_texto = "".join(linhas[-50:]).strip()
        except Exception:
            log_texto = ""

    return jsonify({
        "ok": True,
        "automatizando": automatizando,
        "status": status,
        "log": log_texto
    })


@app.route("/logs-automacao/<path:arquivo>")
def logs_automacao(arquivo):
    if not usuario_logado():
        return "Acesso negado."

    log_automacao = os.path.join(BASE_DIR, "web", "logs", f"automacao_{arquivo}.txt")
    if not os.path.exists(log_automacao):
        return "Sem logs de automação ainda."

    with open(log_automacao, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


# =========================
# PAINEL DE ERROS
# =========================
@app.route("/api/listar-erros")
def api_listar_erros():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    pasta_erro = os.path.join(BASE_DIR, "erro_oc")

    if not os.path.exists(pasta_erro):
        return jsonify({"ok": True, "arquivos": []})

    arquivos = sorted([
        nome for nome in os.listdir(pasta_erro)
        if os.path.isfile(os.path.join(pasta_erro, nome))
        and nome.lower().endswith(".pdf")
    ])

    resultado = []
    for nome in arquivos:
        caminho = os.path.join(pasta_erro, nome)
        try:
            ts = int(os.path.getmtime(caminho))
            data = time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
        except Exception:
            ts = 0
            data = ""

        resultado.append({
            "nome": nome,
            "data_ref": data,
            "timestamp_ref": ts,
        })

    return jsonify({"ok": True, "arquivos": resultado})


@app.route("/api/reenviar-erro", methods=["POST"])
def api_reenviar_erro():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    # recebe o nome via JSON no body — evita problemas com pontos e caracteres especiais na URL
    dados = request.get_json(silent=True) or {}
    arquivo = dados.get("arquivo", "").strip()

    if not arquivo:
        return jsonify({"ok": False, "mensagem": "Nome do arquivo não informado."}), 400

    pasta_erro = os.path.join(BASE_DIR, "erro_oc")
    origem = os.path.join(pasta_erro, arquivo)

    if not os.path.exists(origem):
        return jsonify({"ok": False, "mensagem": "Arquivo não encontrado na pasta de erros."}), 404

    destino = os.path.join(PASTA_ENTRADA, arquivo)

    # se ja existe na entrada, nao sobrescreve
    if os.path.exists(destino):
        return jsonify({"ok": False, "mensagem": "Arquivo já existe na pasta de entrada."}), 409

    try:
        shutil.move(origem, destino)
        escrever_log(arquivo, "[WEB] Arquivo reenviado da pasta de erros para a entrada.")
        return jsonify({"ok": True, "mensagem": f"{arquivo} reenviado para a fila de entrada."})
    except Exception as e:
        return jsonify({"ok": False, "mensagem": f"Falha ao mover arquivo: {e}"}), 500


@app.route("/api/excluir-erro", methods=["POST"])
def api_excluir_erro():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

    # recebe o nome via JSON no body — evita problemas com pontos e caracteres especiais na URL
    dados = request.get_json(silent=True) or {}
    arquivo = dados.get("arquivo", "").strip()

    if not arquivo:
        return jsonify({"ok": False, "mensagem": "Nome do arquivo não informado."}), 400

    pasta_erro = os.path.join(BASE_DIR, "erro_oc")
    caminho = os.path.join(pasta_erro, arquivo)

    if not os.path.exists(caminho):
        return jsonify({"ok": False, "mensagem": "Arquivo não encontrado."}), 404

    try:
        os.remove(caminho)
        return jsonify({"ok": True, "mensagem": f"{arquivo} excluído permanentemente."})
    except Exception as e:
        return jsonify({"ok": False, "mensagem": f"Falha ao excluir: {e}"}), 500


# =========================
# PAINEL DE CONTROLE
# =========================

@app.route("/painel")
def painel():
    if not usuario_logado():
        return redirect("/")
    if not usuario_supervisor():
        return redirect("/dashboard")
    return render_template("painel.html", nivel=nivel_acesso())


@app.route("/api/painel/saude")
def api_painel_saude():
    if not usuario_logado() or not usuario_supervisor():
        return jsonify({"ok": False}), 403

    import glob

    # bases de dados
    def info_arquivo(caminho):
        if not os.path.exists(caminho):
            return {"existe": False, "registros": 0, "atualizado": None}
        try:
            import pandas as pd
            ext = os.path.splitext(caminho)[1].lower()
            if ext == ".csv":
                df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig")
            else:
                df = pd.read_excel(caminho)
            ts = os.path.getmtime(caminho)
            return {
                "existe": True,
                "registros": len(df),
                "atualizado": time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
            }
        except Exception as e:
            return {"existe": True, "registros": 0, "atualizado": None, "erro": str(e)}

    base_krona  = info_arquivo(os.path.join(BASE_DIR, "saida", "base_krona_final.csv"))
    base_brasal = info_arquivo(os.path.join(BASE_DIR, "dados", "DADOS TABELA BRASAL 01 SEM - 25 (1).csv"))
    base_mrv    = info_arquivo(os.path.join(BASE_DIR, "dados", "base_mrv.csv"))

    # fila de entrada
    pasta_entrada = os.path.join(BASE_DIR, "entrada_oc")
    fila_entrada  = len([f for f in os.listdir(pasta_entrada) if f.endswith(".pdf")]) if os.path.exists(pasta_entrada) else 0

    # erros
    pasta_erro = os.path.join(BASE_DIR, "erro_oc")
    total_erros = len([f for f in os.listdir(pasta_erro) if f.endswith(".pdf")]) if os.path.exists(pasta_erro) else 0

    # calibracao gamatec
    cal_path = os.path.join(BASE_DIR, "saida", "calibracao_gamatec.json")
    calibrado = os.path.exists(cal_path)
    cal_data  = None
    if calibrado:
        try:
            cal_data = time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(cal_path)))
        except Exception:
            pass

    # agente email
    email_status = status_agente_email()

    return jsonify({
        "ok": True,
        "bases": {
            "krona":  base_krona,
            "brasal": base_brasal,
            "mrv":    base_mrv,
        },
        "fila_entrada":  fila_entrada,
        "total_erros":   total_erros,
        "calibrado":     calibrado,
        "cal_data":      cal_data,
        "agente_email":  email_status,
    })


@app.route("/api/painel/metricas")
def api_painel_metricas():
    if not usuario_logado() or not usuario_supervisor():
        return jsonify({"ok": False}), 403

    import glob
    from datetime import datetime, timedelta

    hoje      = time.strftime("%Y-%m-%d")
    semana    = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    pasta_proc   = os.path.join(BASE_DIR, "processados_oc")
    pasta_saida  = os.path.join(BASE_DIR, "saida", "ocs_individuais")

    total_hoje   = 0
    total_semana = 0
    total_geral  = 0
    por_cliente  = {}
    por_formato  = {}
    taxa_match   = []

    if os.path.exists(pasta_saida):
        for pasta_oc in os.listdir(pasta_saida):
            caminho = os.path.join(pasta_saida, pasta_oc)
            if not os.path.isdir(caminho):
                continue

            total_geral += 1

            ts = os.path.getmtime(caminho)
            data_oc = time.strftime("%Y-%m-%d", time.localtime(ts))

            if data_oc == hoje:
                total_hoje += 1
            if data_oc in semana:
                total_semana += 1

            # tenta ler resumo
            resumo_path = os.path.join(caminho, "resumo.json")
            if os.path.exists(resumo_path):
                try:
                    with open(resumo_path, "r", encoding="utf-8") as f:
                        resumo = json.load(f)
                    cliente = resumo.get("cliente", "Desconhecido")
                    formato = resumo.get("formato", "Desconhecido")
                    por_cliente[cliente] = por_cliente.get(cliente, 0) + 1
                    por_formato[formato] = por_formato.get(formato, 0) + 1
                    total = resumo.get("total_itens", 0)
                    match = resumo.get("itens_com_match", 0)
                    if total > 0:
                        taxa_match.append(match / total * 100)
                except Exception:
                    pass

    taxa_media = round(sum(taxa_match) / len(taxa_match), 1) if taxa_match else 0

    return jsonify({
        "ok": True,
        "total_hoje":   total_hoje,
        "total_semana": total_semana,
        "total_geral":  total_geral,
        "taxa_match":   taxa_media,
        "por_cliente":  por_cliente,
        "por_formato":  por_formato,
    })


@app.route("/api/painel/revisao-emails")
def api_painel_revisao_emails():
    if not usuario_logado() or not usuario_supervisor():
        return jsonify({"ok": False}), 403

    estado_path = os.path.join(BASE_DIR, "agente_email", "estado_emails.json")
    if not os.path.exists(estado_path):
        return jsonify({"ok": True, "emails": []})

    try:
        with open(estado_path, "r", encoding="utf-8") as f:
            estado = json.load(f)
        return jsonify({"ok": True, "emails": estado.get("revisao", [])})
    except Exception as e:
        return jsonify({"ok": False, "mensagem": str(e)}), 500


@app.route("/api/painel/revisao-emails/processar", methods=["POST"])
def api_painel_revisao_processar():
    if not usuario_logado():
        return jsonify({"ok": False}), 403

    dados   = request.get_json(silent=True) or {}
    msg_id  = dados.get("id", "").strip()
    acao    = dados.get("acao", "").strip()  # "processar" ou "ignorar"
    limpar_motivo = dados.get("limpar_motivo", "").strip()  # limpa todos de um motivo

    estado_path = os.path.join(BASE_DIR, "agente_email", "estado_emails.json")
    try:
        with open(estado_path, "r", encoding="utf-8") as f:
            estado = json.load(f)

        if limpar_motivo:
            # remove todos os emails com determinado motivo da fila
            antes = len(estado.get("revisao", []))
            estado["revisao"] = [
                r for r in estado.get("revisao", [])
                if r.get("motivo") != limpar_motivo
            ]
            removidos = antes - len(estado["revisao"])
            with open(estado_path, "w", encoding="utf-8") as f:
                json.dump(estado, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True, "mensagem": f"{removidos} email(s) removidos da fila.", "removidos": removidos})

        if not msg_id or acao not in ("processar", "ignorar"):
            return jsonify({"ok": False, "mensagem": "Dados invalidos."}), 400

        estado["revisao"] = [r for r in estado.get("revisao", []) if r.get("id") != msg_id]

        with open(estado_path, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)

        return jsonify({"ok": True, "mensagem": f"Email {acao}do com sucesso."})
    except Exception as e:
        return jsonify({"ok": False, "mensagem": str(e)}), 500


@app.route("/api/painel/upload-base", methods=["POST"])
def api_painel_upload_base():
    if not usuario_logado() or not usuario_admin():
        return jsonify({"ok": False, "mensagem": "Apenas administradores."}), 403

    tipo = request.form.get("tipo", "").strip()
    if "arquivo" not in request.files:
        return jsonify({"ok": False, "mensagem": "Nenhum arquivo enviado."}), 400

    arquivo = request.files["arquivo"]
    nome    = secure_filename(arquivo.filename)

    destinos = {
        "krona":  os.path.join(BASE_DIR, "dados", "DADOS DE PRODUTOS KRONA(1).xlsx"),
        "brasal": os.path.join(BASE_DIR, "dados", "DADOS TABELA BRASAL 01 SEM - 25 (1).csv"),
        "mrv":    os.path.join(BASE_DIR, "dados", "base_mrv.csv"),
    }

    if tipo not in destinos:
        return jsonify({"ok": False, "mensagem": f"Tipo desconhecido: {tipo}"}), 400

    try:
        destino = destinos[tipo]
        os.makedirs(os.path.dirname(destino), exist_ok=True)

        # backup do arquivo anterior
        if os.path.exists(destino):
            backup = destino + ".bak"
            import shutil as _shutil
            _shutil.copy2(destino, backup)

        arquivo.save(destino)

        return jsonify({
            "ok": True,
            "mensagem": f"Base {tipo.upper()} atualizada com sucesso.",
            "arquivo": nome
        })
    except Exception as e:
        return jsonify({"ok": False, "mensagem": f"Erro ao salvar: {e}"}), 500


# =========================
# AGENTE EMAIL — ROTAS
# =========================

@app.route("/api/agente-email/status")
def api_agente_email_status():
    if not usuario_logado():
        return jsonify({"ok": False}), 403
    return jsonify({"ok": True, **status_agente_email()})


@app.route("/api/agente-email/iniciar", methods=["POST"])
def api_agente_email_iniciar():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403
    ok, msg = iniciar_agente_email()
    if not ok and msg == "token_nao_encontrado":
        return jsonify({
            "ok": False,
            "mensagem": "Token não encontrado. Execute python rodar_agente_email.py no terminal uma vez para autenticar.",
            "token_pendente": True
        }), 400
    return jsonify({"ok": ok, "mensagem": msg})


@app.route("/api/agente-email/parar", methods=["POST"])
def api_agente_email_parar():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403
    ok, msg = parar_agente_email()
    return jsonify({"ok": ok, "mensagem": msg})


@app.route("/api/agente-email/log")
def api_agente_email_log():
    if not usuario_logado():
        return jsonify({"ok": False}), 403
    log_path = os.path.join(BASE_DIR, "web", "logs", "agente_email.log")
    if not os.path.exists(log_path):
        return jsonify({"ok": True, "log": "Sem logs ainda."})
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            linhas = f.readlines()
        return jsonify({"ok": True, "log": "".join(linhas[-60:])})
    except Exception as e:
        return jsonify({"ok": False, "log": str(e)})


# =========================
# SHADOW MODE — STATS
# =========================

@app.route("/api/shadow/stats")
def api_shadow_stats():
    """Retorna estatisticas do shadow mode para acompanhamento."""
    if not usuario_logado():
        return jsonify({"ok": False}), 403

    shadow_path = os.path.join(BASE_DIR, "saida", "shadow_mode.jsonl")
    if not os.path.exists(shadow_path):
        return jsonify({"ok": True, "total": 0, "concordancia": 0, "registros": []})

    try:
        registros = []
        with open(shadow_path, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    registros.append(json.loads(linha))

        total     = len(registros)
        concordam = sum(1 for r in registros if r.get("concordam"))
        divergem  = total - concordam
        pct       = round((concordam / total * 100), 1) if total else 0

        # ultimos 20 para exibicao
        ultimos = registros[-20:][::-1]

        return jsonify({
            "ok":           True,
            "total":        total,
            "concordam":    concordam,
            "divergem":     divergem,
            "concordancia": pct,
            "registros":    ultimos,
        })
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


# =========================
# AGENTE EMAIL — CONFIG
# =========================

CONFIG_AGENTE_EMAIL_PATH = os.path.join(BASE_DIR, "dados", "config_agente_email.json")

CONFIG_AGENTE_EMAIL_FALLBACK = {
    "geral": {"intervalo_minutos": 5, "max_emails_por_ciclo": 20},
    "respostas": {
        "oc":              {"ativo": True,  "corpo": ""},
        "cotacao":         {"ativo": True,  "corpo": ""},
        "nao_identificado":{"ativo": False, "corpo": ""},
    },
    "assinatura": "Atenciosamente,\nUNE Representacoes\nRepresentante Oficial KRONA Tubos e Conexoes",
    "clientes_sem_resposta": ["mrv"],
}


def _ler_config_agente_email() -> dict:
    try:
        with open(CONFIG_AGENTE_EMAIL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return CONFIG_AGENTE_EMAIL_FALLBACK


def _salvar_config_agente_email(config: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(CONFIG_AGENTE_EMAIL_PATH), exist_ok=True)
        with open(CONFIG_AGENTE_EMAIL_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


@app.route("/agente-email/config")
def pagina_config_agente_email():
    if not usuario_logado():
        return redirect("/")
    config = _ler_config_agente_email()
    return render_template("config_agente_email.html", config=config)


@app.route("/api/agente-email/config", methods=["GET"])
def api_agente_email_config_get():
    if not usuario_logado():
        return jsonify({"ok": False}), 403
    return jsonify({"ok": True, "config": _ler_config_agente_email()})


@app.route("/api/agente-email/config", methods=["POST"])
def api_agente_email_config_post():
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403
    try:
        data = request.get_json(force=True)
        config_atual = _ler_config_agente_email()

        # geral
        if "geral" in data:
            config_atual["geral"]["intervalo_minutos"]    = int(data["geral"].get("intervalo_minutos", 5))
            config_atual["geral"]["max_emails_por_ciclo"] = int(data["geral"].get("max_emails_por_ciclo", 20))

        # respostas
        if "respostas" in data:
            for tipo in ("oc", "cotacao", "nao_identificado"):
                if tipo in data["respostas"]:
                    config_atual["respostas"][tipo]["ativo"] = bool(data["respostas"][tipo].get("ativo", False))
                    config_atual["respostas"][tipo]["corpo"] = str(data["respostas"][tipo].get("corpo", ""))

        # assinatura
        if "assinatura" in data:
            config_atual["assinatura"] = str(data["assinatura"])

        # clientes sem resposta — lista de strings lowercase
        if "clientes_sem_resposta" in data:
            raw = data["clientes_sem_resposta"]
            if isinstance(raw, list):
                config_atual["clientes_sem_resposta"] = [str(c).lower().strip() for c in raw if str(c).strip()]
            elif isinstance(raw, str):
                config_atual["clientes_sem_resposta"] = [
                    c.strip().lower() for c in raw.split(",") if c.strip()
                ]

        ok = _salvar_config_agente_email(config_atual)
        if ok:
            return jsonify({"ok": True, "mensagem": "Configuracoes salvas com sucesso."})
        else:
            return jsonify({"ok": False, "mensagem": "Erro ao salvar arquivo de configuracao."}), 500

    except Exception as e:
        return jsonify({"ok": False, "mensagem": str(e)}), 500


# =================================================================
# REVISAO DE ITENS
# =================================================================

@app.route("/revisao")
def pagina_revisao():
    """Página de revisão humana de itens com score baixo."""
    if not usuario_logado():
        return redirect("/")
    
    from dados.revisao_store import listar_pendentes
    itens = listar_pendentes()
    
    return render_template(
        "revisao.html",
        itens=itens,
        total=len(itens),
        usuario=session.get('user', 'admin')
    )


@app.route("/api/revisao/pendentes")
def api_revisao_pendentes():
    """API: retorna contagem e top 5 itens pendentes."""
    if not usuario_logado():
        return jsonify({"ok": False}), 403
    
    from dados.revisao_store import listar_pendentes, contar_pendentes
    
    return jsonify({
        "ok": True,
        "total": contar_pendentes(),
        "itens": listar_pendentes(limite=5)
    })


@app.route("/api/revisao/resolver", methods=["POST"])
def api_revisao_resolver():
    """API: marca um item como resolvido com a correção do usuário."""
    if not usuario_logado():
        return jsonify({"ok": False}), 403
    
    try:
        data = request.get_json(force=True)
        item_id = data.get("id")
        codigo = str(data.get("codigo_krona", "")).strip()
        descricao = str(data.get("descricao_krona", "")).strip()
        usuario = session.get('user', 'admin')
        
        if not item_id or not codigo:
            return jsonify({
                "ok": False,
                "mensagem": "ID do item e código Krona são obrigatórios."
            })
        
        from dados.revisao_store import resolver_item, salvar_correcao_aprendizado
        
        resolver_item(item_id, codigo, descricao, usuario)
        
        # salva para aprendizado se houver descrição
        if descricao:
            salvar_correcao_aprendizado(
                data.get("descricao_oc", ""),
                codigo,
                descricao
            )
        
        return jsonify({"ok": True, "mensagem": "Item resolvido com sucesso."})
    
    except Exception as e:
        return jsonify({
            "ok": False,
            "mensagem": f"Erro ao resolver item: {str(e)}"
        })


@app.route("/api/revisao/buscar-krona")
def api_buscar_krona():
    """API: busca produtos na base Krona para o operador selecionar."""
    if not usuario_logado():
        return jsonify({"ok": False}), 403
    
    termo = request.args.get("q", "").strip().upper()
    
    if len(termo) < 2:
        return jsonify({"ok": True, "resultados": []})
    
    try:
        import pandas as pd
        
        base_path = os.path.join(BASE_DIR, "saida", "base_krona_final.csv")
        if not os.path.exists(base_path):
            return jsonify({
                "ok": False,
                "erro": "Base de dados Krona não encontrada."
            })
        
        df = pd.read_csv(
            base_path,
            sep=";",
            encoding="utf-8-sig",
            usecols=["codigo_krona", "descricao_krona"],
            dtype={"codigo_krona": str, "descricao_krona": str}
        )
        
        # busca por codigo OU descricao
        mask = (
            df["descricao_krona"].str.upper().str.contains(termo, na=False, regex=False) |
            df["codigo_krona"].astype(str).str.contains(termo, na=False, regex=False)
        )
        
        resultados = df[mask].drop_duplicates().head(10).to_dict(orient="records")
        
        return jsonify({
            "ok": True,
            "resultados": resultados
        })
    
    except Exception as e:
        return jsonify({
            "ok": False,
            "erro": f"Erro na busca: {str(e)}"
        })


@app.route("/api/revisao/reprocessar", methods=["POST"])
def api_revisao_reprocessar():
    if not usuario_logado():
        return jsonify({"ok": False}), 403
    data = request.get_json(force=True)
    arquivo = data.get("arquivo", "").strip()
    if not arquivo:
        return jsonify({"ok": False, "mensagem": "Arquivo nao informado."})
    try:
        import shutil
        origem = os.path.join(BASE_DIR, "processados_oc", arquivo)
        destino = os.path.join(BASE_DIR, "entrada_oc", arquivo)
        if not os.path.exists(origem):
            return jsonify({"ok": False, "mensagem": "Arquivo nao encontrado em processados_oc."})
        shutil.copy2(origem, destino)
        return jsonify({"ok": True, "mensagem": f"{arquivo} movido para entrada_oc. Processe pelo dashboard."})
    except Exception as e:
        return jsonify({"ok": False, "mensagem": str(e)})


# =========================
# LOGOUT
# ========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# RUN
# =========================
if __name__ == "__main__":
    verificar_estado_ao_iniciar()

    # inicia agente de email automaticamente se token existir
    token_path = os.path.join(BASE_DIR, "agente_email", "token.pickle")
    if os.path.exists(token_path):
        ok, msg = iniciar_agente_email()
        print(f"[AGENTE EMAIL] {msg}")
    else:
        print("[AGENTE EMAIL] Token não encontrado — autentique primeiro com: python rodar_agente_email.py")

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
