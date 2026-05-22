# -*- coding: utf-8 -*-
"""
atualizador.py — Verifica e aplica atualizações do Vortex Sync
Chamado pelo rodar_gamatec.bat antes de iniciar o sistema
"""

import subprocess
import sys
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def verificar_atualizacao():
    """Retorna True se houver commits novos no remote."""
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=APP_DIR, capture_output=True, timeout=10
        )
        result = subprocess.run(
            ["git", "rev-list", "HEAD..origin/main", "--count"],
            cwd=APP_DIR, capture_output=True, text=True, timeout=10
        )
        commits_novos = int(result.stdout.strip() or "0")
        return commits_novos > 0
    except Exception:
        return False


def aplicar_atualizacao():
    """Faz git pull e reinstala dependencias se requirements.txt mudou."""
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD..origin/main", "--name-only"],
            cwd=APP_DIR, capture_output=True, text=True
        )
        req_mudou = "requirements.txt" in diff.stdout

        subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=APP_DIR, check=True, capture_output=True
        )

        if req_mudou:
            req_path = os.path.join(APP_DIR, "requirements.txt")
            resultado = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_path, "--quiet"],
                capture_output=True, text=True
            )
            if resultado.returncode != 0:
                resultado = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", req_path,
                     "--quiet", "--user"],
                    capture_output=True, text=True
                )
            if resultado.returncode != 0:
                raise Exception(f"pip install falhou com codigo {resultado.returncode}")

        return True
    except Exception:
        return False


def main():
    print("[VORTEX] Verificando atualizacoes...")

    if verificar_atualizacao():
        print("[VORTEX] Nova versao disponivel. Atualizando...")
        ok = aplicar_atualizacao()
        if ok:
            print("[VORTEX] Atualizado com sucesso.")
        else:
            print("[VORTEX] Falha na atualizacao. Continuando com versao atual.")
    else:
        print("[VORTEX] Sistema atualizado.")


if __name__ == "__main__":
    main()
