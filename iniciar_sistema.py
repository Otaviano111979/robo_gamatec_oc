# -*- coding: utf-8 -*-
"""Arranque do Vortex Sync sem comandos manuais.

Chamado pelo rodar_gamatec.bat (duplo clique). Garante o .env, confere as
dependencias e inicia web/app_web.py no mesmo processo, para que o Ctrl+C e
o fecho da janela encerrem o servidor.
"""

import argparse
from contextlib import contextmanager
import os
import runpy
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import webbrowser

RAIZ = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(RAIZ, ".env")
ENV_EXEMPLO = os.path.join(RAIZ, ".env.example")
CHAVE_EXEMPLO = "coloque_aqui_uma_chave_longa_e_aleatoria"
MODULOS = ("flask", "pandas", "pdfplumber", "rapidfuzz", "openpyxl", "bcrypt", "dotenv")


def porta_disponivel(porta):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as teste:
        if os.name == "nt":
            teste.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            teste.bind(("0.0.0.0", porta))
        except OSError:
            return False
    return True


@contextmanager
def bloqueio_arranque(porta):
    caminho = os.path.join(tempfile.gettempdir(), f"vortex-gamatec-{porta}.lock")
    with open(caminho, "a+b") as arquivo:
        if arquivo.seek(0, os.SEEK_END) == 0:
            arquivo.write(b"\0")
            arquivo.flush()
        arquivo.seek(0)
        if os.name == "nt":
            import msvcrt
            travar = lambda: msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            destravar = lambda: msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            travar = lambda: fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            destravar = lambda: fcntl.flock(arquivo, fcntl.LOCK_UN)
        try:
            travar()
        except OSError:
            arquivo.seek(1)
            pronto = arquivo.read().decode("utf-8", errors="replace") == os.path.normcase(RAIZ)
            yield None, pronto
            return
        try:
            arquivo.truncate(1)
            arquivo.flush()
            yield arquivo, False
        finally:
            arquivo.truncate(1)
            arquivo.flush()
            arquivo.seek(0)
            destravar()
    # Nao apagar: outro processo pode estar a abrir o mesmo ficheiro.


def abrir_navegador(porta):
    webbrowser.open(f"http://127.0.0.1:{porta}/ocs")


def garantir_env():
    """Cria o .env na primeira execucao e troca a chave de exemplo."""
    if not os.path.exists(ENV):
        if not os.path.exists(ENV_EXEMPLO):
            return
        with open(ENV_EXEMPLO, encoding="utf-8") as f:
            conteudo = f.read()
        with open(ENV, "w", encoding="utf-8") as f:
            f.write(conteudo.replace(CHAVE_EXEMPLO, secrets.token_hex(32)))
        print("[INICIAR] .env criado com chave de sessao aleatoria.")
        return

    with open(ENV, encoding="utf-8") as f:
        conteudo = f.read()
    if CHAVE_EXEMPLO in conteudo:
        with open(ENV, "w", encoding="utf-8") as f:
            f.write(conteudo.replace(CHAVE_EXEMPLO, secrets.token_hex(32)))
        print("[INICIAR] .env tinha a chave de exemplo — gerada uma chave aleatoria.")


def dependencias_em_falta():
    faltando = []
    for modulo in MODULOS:
        try:
            __import__(modulo)
        except ImportError:
            faltando.append(modulo)
    return faltando


def instalar_dependencias():
    print("[INICIAR] Instalando dependencias do requirements.txt ...")
    requisitos = os.path.join(RAIZ, "requirements.txt")
    for extra in ([], ["--user"]):
        comando = [sys.executable, "-m", "pip", "install", "-r", requisitos, "--quiet"]
        if subprocess.run(comando + extra).returncode == 0:
            return True
    return False


def iniciar_web(porta, arquivo, navegador):
    from werkzeug import serving

    original = serving.make_server

    def criar_servidor(*args, **kwargs):
        servidor = original(*args, **kwargs)
        # So identifica o Vortex depois de o seu servidor conseguir escutar.
        if servidor.server_address[1] == porta:
            arquivo.write(os.path.normcase(RAIZ).encode("utf-8"))
            arquivo.flush()
            if navegador:
                threading.Thread(target=abrir_navegador, args=(porta,), daemon=True).start()
        return servidor

    pasta_web = os.path.join(RAIZ, "web")
    os.chdir(pasta_web)
    if RAIZ not in sys.path:
        sys.path.insert(0, RAIZ)
    serving.make_server = criar_servidor
    try:
        runpy.run_path(os.path.join(pasta_web, "app_web.py"), run_name="__main__")
    finally:
        serving.make_server = original
    return 0


def main():
    parser = argparse.ArgumentParser(description="Arranque seguro do Vortex Sync.")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--atualizar", action="store_true")
    parser.add_argument("--abrir-navegador", action="store_true")
    args = parser.parse_args()
    try:
        porta = int(os.environ.get("GAMATEC_PORT", "5000"))
        if not 1 <= porta <= 65535:
            raise ValueError
    except ValueError:
        print("[INICIAR] ERRO: GAMATEC_PORT deve ser uma porta entre 1 e 65535.")
        return 1

    print(f"[INICIAR] Projeto: {RAIZ} | Porta: {porta}")
    with bloqueio_arranque(porta) as (arquivo, pronto):
        livre = porta_disponivel(porta)
        if arquivo is None:
            if pronto and not livre:
                print(f"[INICIAR] Vortex ja em execucao na porta {porta}; nao sera atualizado nem reiniciado.")
                if args.abrir_navegador:
                    abrir_navegador(porta)
            else:
                print(f"[INICIAR] Arranque ja em curso ou bloqueio indisponivel na porta {porta}; nao sera iniciado outro servidor.")
            return 2
        if not livre:
            print(f"[INICIAR] Porta {porta} ocupada ou indisponivel; nao sera atualizado nem iniciado outro servidor.")
            print("[INICIAR] Vortex nao confirmado; navegador nao aberto. Nenhum processo foi encerrado.")
            return 2
        if args.preflight:
            return 0

        # Mantem a porta verificada mesmo depois de load_dotenv.
        os.environ["GAMATEC_PORT"] = str(porta)
        if args.atualizar:
            subprocess.run([sys.executable, os.path.join(RAIZ, "instalador", "atualizador.py")])
        if not porta_disponivel(porta):
            print(f"[INICIAR] Porta {porta} ocupada durante o arranque; servidor nao iniciado.")
            return 2
        garantir_env()
        if dependencias_em_falta() and not instalar_dependencias():
            print("[INICIAR] ERRO: nao foi possivel instalar as dependencias.")
            print(f"[INICIAR] Execute manualmente: {sys.executable} -m pip install -r requirements.txt")
            return 1
        if not os.path.exists(os.path.join(RAIZ, "web", "app_web.py")):
            print(f"[INICIAR] ERRO: app_web.py nao encontrado em {RAIZ}")
            return 1
        return iniciar_web(porta, arquivo, args.abrir_navegador)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[INICIAR] Sistema encerrado.")
