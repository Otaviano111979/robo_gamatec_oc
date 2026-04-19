# -*- coding: utf-8 -*-
"""
launcher.py — Vortex Platform

Ponto de entrada da plataforma multi-empresa.
Abre o servidor Flask para a empresa selecionada.

Uso:
  python launcher.py                        # abre seletor de empresa no browser
  python launcher.py --empresa une          # abre direto a empresa 'une'
  python launcher.py --criar-empresa nova   # cria estrutura para nova empresa
  python launcher.py --listar               # lista empresas cadastradas

Estrutura de pastas:
  C:\\Vortex\\
  ├── launcher.py           ← este arquivo
  ├── core\\                 ← código do sistema (copiado de robo_gamatec_oc)
  └── empresas\\
      ├── une\\
      │   ├── config.json
      │   ├── dados\\
      │   ├── saida\\
      │   ├── entrada_oc\\
      │   ├── processados_oc\\
      │   └── erro_oc\\
      └── empresa_b\\
          └── config.json ...
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

# ============================================================
# PATHS
# ============================================================

LAUNCHER_DIR  = os.path.dirname(os.path.abspath(__file__))
VORTEX_ROOT   = os.environ.get("VORTEX_ROOT", LAUNCHER_DIR)
EMPRESAS_DIR  = os.path.join(VORTEX_ROOT, "empresas")
CORE_DIR      = os.path.join(VORTEX_ROOT, "core")
PORTA_PADRAO  = 5000

MODULOS_DISPONIVEIS = {
    "oc":          {"nome": "Pedidos / OC",      "descricao": "Processar ordens de compra"},
    "email":       {"nome": "Agente de email",   "descricao": "Monitor e resposta automatica"},
    "crm":         {"nome": "CRM",               "descricao": "Clientes e historico"},
    "financeiro":  {"nome": "Financeiro",        "descricao": "Comissoes e receita"},
    "inteligencia":{"nome": "Inteligencia",      "descricao": "Tendencias e analises"},
}


# ============================================================
# LISTAR EMPRESAS
# ============================================================

def listar_empresas():
    """Retorna lista de empresas cadastradas com seus configs."""
    if not os.path.exists(EMPRESAS_DIR):
        return []

    empresas = []
    for pasta in sorted(os.listdir(EMPRESAS_DIR)):
        caminho = os.path.join(EMPRESAS_DIR, pasta)
        config_path = os.path.join(caminho, "config.json")
        if not os.path.isdir(caminho) or not os.path.exists(config_path):
            continue
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            empresas.append({
                "id":             pasta,
                "nome":           cfg.get("nome", pasta),
                "modulos_ativos": cfg.get("modulos_ativos", []),
                "modulos_trial":  cfg.get("modulos_trial", []),
                "ativo":          cfg.get("ativo", True),
                "criado_em":      cfg.get("criado_em", ""),
                "config_path":    config_path,
            })
        except Exception:
            continue

    return empresas


# ============================================================
# CRIAR EMPRESA
# ============================================================

def criar_empresa(empresa_id, nome=None, modulos_ativos=None):
    """Cria estrutura de pastas e config.json para uma nova empresa."""
    empresa_id = empresa_id.lower().strip().replace(" ", "_")
    pasta = os.path.join(EMPRESAS_DIR, empresa_id)

    if os.path.exists(pasta):
        print(f"Empresa '{empresa_id}' ja existe em: {pasta}")
        return pasta

    # criar estrutura de pastas
    subpastas = ["dados", "saida", "entrada_oc", "processados_oc", "erro_oc",
                 "saida/ocs_individuais"]
    for sub in subpastas:
        os.makedirs(os.path.join(pasta, sub), exist_ok=True)

    # config.json inicial
    config = {
        "id":             empresa_id,
        "nome":           nome or empresa_id.upper(),
        "ativo":          True,
        "modulos_ativos": modulos_ativos or ["oc"],
        "modulos_trial":  [],
        "versao":         "1.0",
        "criado_em":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "porta":          PORTA_PADRAO,
        "_instrucoes": (
            "Copie os arquivos de dados para a pasta dados/: "
            "DADOS DE PRODUTOS KRONA(1).xlsx, base_mrv.csv, etc."
        ),
    }

    config_path = os.path.join(pasta, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"Empresa '{empresa_id}' criada em: {pasta}")
    print(f"Proximo passo: copie os dados para {os.path.join(pasta, 'dados')}")
    return pasta


# ============================================================
# INICIAR SERVIDOR PARA EMPRESA
# ============================================================

def iniciar_empresa(empresa_id, porta=None, abrir_browser=True):
    """Inicia o servidor Flask para a empresa selecionada."""
    empresas = {e["id"]: e for e in listar_empresas()}

    if empresa_id not in empresas:
        print(f"Empresa '{empresa_id}' nao encontrada.")
        print(f"Empresas disponiveis: {list(empresas.keys())}")
        sys.exit(1)

    cfg = empresas[empresa_id]
    porta = porta or cfg.get("porta", PORTA_PADRAO)

    print(f"\n{'='*50}")
    print(f"  Vortex Platform — {cfg['nome']}")
    print(f"  Modulos ativos: {', '.join(cfg['modulos_ativos'])}")
    print(f"  Porta: {porta}")
    print(f"{'='*50}\n")

    # definir variáveis de ambiente para o servidor
    env = os.environ.copy()
    env["VORTEX_EMPRESA_ID"] = empresa_id
    env["VORTEX_ROOT"]       = VORTEX_ROOT
    env["FLASK_PORT"]        = str(porta)

    # caminho do app_web.py (core ou pasta atual)
    app_web = os.path.join(CORE_DIR, "web", "app_web.py")
    if not os.path.exists(app_web):
        # fallback: mesma pasta do launcher (modo legado)
        app_web = os.path.join(LAUNCHER_DIR, "web", "app_web.py")

    if not os.path.exists(app_web):
        print(f"app_web.py nao encontrado em: {app_web}")
        sys.exit(1)

    if abrir_browser:
        import threading
        def _abrir():
            import time; time.sleep(2)
            webbrowser.open(f"http://localhost:{porta}/dashboard")
        threading.Thread(target=_abrir, daemon=True).start()

    subprocess.run(
        [sys.executable, app_web, "--port", str(porta)],
        env=env
    )


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Vortex Platform Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python launcher.py                        Abre seletor de empresa
  python launcher.py --empresa une          Inicia direto a UNE
  python launcher.py --criar-empresa nova   Cria estrutura para nova empresa
  python launcher.py --listar               Lista empresas cadastradas
        """
    )
    parser.add_argument("--empresa",        help="ID da empresa para iniciar")
    parser.add_argument("--criar-empresa",  help="Cria estrutura para nova empresa")
    parser.add_argument("--nome",           help="Nome da empresa (usa com --criar-empresa)")
    parser.add_argument("--listar",         action="store_true", help="Lista empresas")
    parser.add_argument("--porta",          type=int, help="Porta do servidor")
    args = parser.parse_args()

    # listar
    if args.listar:
        empresas = listar_empresas()
        if not empresas:
            print("Nenhuma empresa cadastrada.")
            print(f"Use: python launcher.py --criar-empresa une --nome 'UNE Representacoes'")
        else:
            print(f"\n{'='*50}")
            print("  Empresas cadastradas")
            print(f"{'='*50}")
            for e in empresas:
                status = "ATIVO" if e["ativo"] else "inativo"
                print(f"  [{e['id']}] {e['nome']} — {status}")
                print(f"        Modulos: {', '.join(e['modulos_ativos'])}")
        return

    # criar empresa
    if args.criar_empresa:
        criar_empresa(args.criar_empresa, nome=args.nome)
        return

    # iniciar empresa específica
    if args.empresa:
        iniciar_empresa(args.empresa, porta=args.porta)
        return

    # seletor interativo no terminal
    empresas = listar_empresas()
    if not empresas:
        print("\nNenhuma empresa cadastrada. Criando UNE Representacoes...")
        criar_empresa("une", nome="UNE Representacoes", modulos_ativos=["oc", "email"])
        iniciar_empresa("une", porta=args.porta)
        return

    if len(empresas) == 1:
        # uma só empresa — inicia direto
        iniciar_empresa(empresas[0]["id"], porta=args.porta)
        return

    # múltiplas empresas — seletor no terminal
    print(f"\n{'='*50}")
    print("  Vortex Platform")
    print(f"{'='*50}")
    for i, e in enumerate(empresas, 1):
        print(f"  {i}. {e['nome']} [{e['id']}]")
    print(f"{'='*50}")

    try:
        escolha = int(input("\nEscolha a empresa (numero): ").strip())
        empresa_id = empresas[escolha - 1]["id"]
        iniciar_empresa(empresa_id, porta=args.porta)
    except (ValueError, IndexError):
        print("Escolha invalida.")
        sys.exit(1)


if __name__ == "__main__":
    main()
