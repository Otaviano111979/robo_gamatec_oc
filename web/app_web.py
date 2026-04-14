from flask import Flask, render_template, request, redirect, session, send_file, jsonify, flash
import os
import json
import subprocess
import shutil
import time
import threading
import re
import bcrypt

# carrega variaveis do arquivo .env (fora do codigo-fonte)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from datetime import timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("GAMATEC_SECRET_KEY", "chave_fallback_local")

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

    return {
        "nome": nome_arquivo,
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
        "processando": processando
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
                return redirect("/dashboard")

        registrar_tentativa_falha(ip)
        erro = "Usuário ou senha incorretos."

    return render_template("login.html", erro=erro)


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

    return render_template(
        "dashboard.html",
        arquivos=arquivos,
        total_entrada=total_entrada,
        total_processando=total_processando,
        total_concluidos=total_concluidos,
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
            if tipo not in ("admin", "user"):
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

    script = os.path.join(BASE_DIR, "rodar_agente_gamatec_leitura.py")
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


@app.route("/api/reenviar-erro/<path:arquivo>", methods=["POST"])
def api_reenviar_erro(arquivo):
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

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


@app.route("/api/excluir-erro/<path:arquivo>", methods=["POST"])
def api_excluir_erro(arquivo):
    if not usuario_logado():
        return jsonify({"ok": False, "mensagem": "Acesso negado."}), 403

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
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# RUN
# =========================
if __name__ == "__main__":
    verificar_estado_ao_iniciar()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
