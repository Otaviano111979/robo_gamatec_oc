# -*- coding: utf-8 -*-
"""Arranque do Vortex Sync sem comandos manuais.

Chamado pelo rodar_gamatec.bat (duplo clique). Garante o .env, confere as
dependencias e inicia web/app_web.py no mesmo processo, para que o Ctrl+C e
o fecho da janela encerrem o servidor.
"""

import os
import runpy
import secrets
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(RAIZ, ".env")
ENV_EXEMPLO = os.path.join(RAIZ, ".env.example")
CHAVE_EXEMPLO = "coloque_aqui_uma_chave_longa_e_aleatoria"
MODULOS = ("flask", "pandas", "pdfplumber", "rapidfuzz", "openpyxl", "bcrypt", "dotenv")


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


def main():
    print(f"[INICIAR] Projeto: {RAIZ}")
    garantir_env()

    if dependencias_em_falta() and not instalar_dependencias():
        print("[INICIAR] ERRO: nao foi possivel instalar as dependencias.")
        print(f"[INICIAR] Execute manualmente: {sys.executable} -m pip install -r requirements.txt")
        return 1

    pasta_web = os.path.join(RAIZ, "web")
    app_web = os.path.join(pasta_web, "app_web.py")
    if not os.path.exists(app_web):
        print(f"[INICIAR] ERRO: app_web.py nao encontrado em {pasta_web}")
        return 1

    os.chdir(pasta_web)
    if RAIZ not in sys.path:
        sys.path.insert(0, RAIZ)
    runpy.run_path(app_web, run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[INICIAR] Sistema encerrado.")
