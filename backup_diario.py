# -*- coding: utf-8 -*-
"""Copia diaria das bases SQLite, com rotacao e teste de restauro.

Uma pasta por dia em backups/diario/AAAA-MM-DD. A copia e feita pela API de
backup do SQLite (funciona com o sistema a correr) e cada copia e reaberta e
verificada antes de ser dada como boa; o estado.json gravado no fim e o
marcador de "ja feito hoje". Falhas ficam registadas e sao repetidas mais
tarde, sem nunca impedir o arranque.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime

DIAS_A_GUARDAR = 14
BASES = ("crm.db", "revisoes.db")
PADRAO_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_trava = threading.Lock()


def base_dir():
    try:
        from config import BASE_DIR
        return BASE_DIR
    except Exception:
        configurado = os.environ.get("GAMATEC_BASE_DIR", "").strip().strip('"')
        if configurado and os.path.isabs(configurado) and os.path.isdir(configurado):
            return configurado
        return os.path.dirname(os.path.abspath(__file__))


def pasta_diaria(base=None):
    return os.path.join(base or base_dir(), "backups", "diario")


def _sha256(caminho):
    digest = hashlib.sha256()
    with open(caminho, "rb") as ficheiro:
        for bloco in iter(lambda: ficheiro.read(1 << 20), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _copiar_banco(origem, destino):
    origem_db = sqlite3.connect(_uri(origem), uri=True, timeout=30)
    try:
        with closing(sqlite3.connect(destino, timeout=30)) as copia_db:
            origem_db.backup(copia_db)
    finally:
        origem_db.close()


def _uri(caminho):
    from pathlib import Path
    return Path(caminho).as_uri() + "?mode=ro"


def _testar_restauro(caminho):
    """Abre a copia como se fosse restaurar: integridade + contagem por tabela."""
    with closing(sqlite3.connect(_uri(caminho), uri=True, timeout=30)) as db:
        estado = db.execute("PRAGMA integrity_check").fetchone()[0]
        if estado != "ok":
            raise ValueError(f"integridade falhou em {os.path.basename(caminho)}: {estado}")
        tabelas = [linha[0] for linha in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {tabela: db.execute(f'SELECT count(*) FROM "{tabela}"').fetchone()[0]
                for tabela in tabelas}


def _estado(caminho):
    try:
        with open(caminho, "r", encoding="utf-8") as ficheiro:
            dados = json.load(ficheiro)
        return dados if isinstance(dados, dict) else None
    except (OSError, ValueError):
        return None


def _feito_hoje(destino, dia):
    estado = _estado(os.path.join(destino, "estado.json"))
    if not estado or estado.get("dia") != dia or not estado.get("ok"):
        return False
    return all(os.path.isfile(os.path.join(destino, nome)) for nome in estado.get("bases", {}))


def _registar(destino, dia, ok, bases=None, erro=None):
    os.makedirs(destino, exist_ok=True)
    estado = {"dia": dia, "quando": datetime.now().isoformat(timespec="seconds"),
              "ok": ok, "bases": bases or {}}
    if erro is not None:
        estado["erro"] = str(erro)
    temporario = os.path.join(destino, "estado.json.tmp")
    with open(temporario, "w", encoding="utf-8") as ficheiro:
        json.dump(estado, ficheiro, ensure_ascii=False, indent=2)
    os.replace(temporario, os.path.join(destino, "estado.json"))


def _rodar(pasta, dias=DIAS_A_GUARDAR):
    try:
        nomes = sorted(nome for nome in os.listdir(pasta)
                       if PADRAO_DIA.match(nome) and os.path.isdir(os.path.join(pasta, nome)))
    except OSError:
        return []
    removidos = []
    for nome in (nomes[:-dias] if dias > 0 else nomes):
        try:
            shutil.rmtree(os.path.join(pasta, nome))
            removidos.append(nome)
        except OSError:
            pass
    return removidos


def executar_se_necessario(base=None, agora=None):
    """Faz a copia do dia se ainda nao estiver feita. Devolve o resumo ou None."""
    with _trava:
        dia = (agora or date.today()).isoformat()
        pasta = pasta_diaria(base)
        destino = os.path.join(pasta, dia)
        if _feito_hoje(destino, dia):
            return None

        resumo = {}
        try:
            os.makedirs(destino, exist_ok=True)
            for nome in BASES:
                origem = os.path.join(base or base_dir(), "dados", nome)
                if not os.path.isfile(origem):
                    continue
                copia = os.path.join(destino, nome)
                if os.path.exists(copia):
                    os.remove(copia)
                _copiar_banco(origem, copia)
                tabelas = _testar_restauro(copia)
                resumo[nome] = {"bytes": os.path.getsize(copia),
                                "sha256": _sha256(copia),
                                "tabelas": tabelas}
            if not resumo:
                raise FileNotFoundError("nenhuma base encontrada em dados/")
            _registar(destino, dia, True, resumo)
        except Exception as erro:
            _registar(destino, dia, False, resumo, erro)
            print(f"[BACKUP] Falhou a copia de {dia}: {erro}")
            return {"ok": False, "erro": str(erro)}
        else:
            removidos = _rodar(pasta)
            print(f"[BACKUP] Copia de {dia} verificada: "
                  + ", ".join(f"{nome} ({dados['bytes']} B)" for nome, dados in resumo.items()))
            if removidos:
                print(f"[BACKUP] Removidas copias antigas: {', '.join(removidos)}")
            return {"ok": True, "dia": dia, "bases": resumo}


def vigiar(intervalo=6 * 3600, atraso=300):
    """Acorda o verificador para uma instancia que fique dias aberta."""
    def laco():
        time.sleep(atraso)
        while True:
            try:
                executar_se_necessario()
            except Exception as erro:
                print(f"[BACKUP] Verificacao falhou: {erro}")
            time.sleep(intervalo)

    threading.Thread(target=laco, name="backup-diario", daemon=True).start()
