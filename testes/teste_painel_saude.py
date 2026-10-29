# -*- coding: utf-8 -*-
"""Saúde do sistema: backup diario, integridade das bases, cache e disco."""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "web"))

import app_web


def criar_banco(caminho, tabela="t"):
    with closing(sqlite3.connect(caminho)) as db:
        db.execute(f'CREATE TABLE "{tabela}" (id INTEGER PRIMARY KEY)')
        db.execute(f'INSERT INTO "{tabela}" VALUES (1)')
        db.commit()


class PainelSaudeTeste(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vortex-saude-teste-")
        cls.base = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        for nome in ("dados", "backups"):
            shutil.rmtree(self.base / nome, ignore_errors=True)
        (self.base / "dados").mkdir()
        (self.base / "backups" / "diario" / "2026-10-29").mkdir(parents=True)
        criar_banco(self.base / "dados" / "crm.db", "clientes")
        criar_banco(self.base / "dados" / "revisoes.db", "itens_revisao")
        (self.base / "dados" / "cache_tipos_documentos.json").write_text(
            json.dumps({"a.pdf": {}, "b.pdf": {}}), encoding="utf-8")

        self.patch = [
            patch.object(app_web, "BASE_DIR", str(self.base)),
            patch.object(app_web, "PASTA_DADOS", str(self.base / "dados")),
            patch.object(app_web, "CACHE_TIPOS_DOCUMENTO_FILE",
                         str(self.base / "dados" / "cache_tipos_documentos.json")),
        ]
        for p in self.patch:
            p.start()
        app_web._CACHE_INTEGRIDADE.update({"em": 0.0, "dados": None})
        app_web.app.config.update(TESTING=True)
        self.cliente = app_web.app.test_client()
        with self.cliente.session_transaction() as sessao:
            sessao["user"] = "teste"; sessao["tipo"] = "admin"

    def tearDown(self):
        for p in self.patch:
            p.stop()

    def escrever_estado(self, ok=True, quando=None, erro=None):
        pasta = self.base / "backups" / "diario" / "2026-10-29"
        (pasta / "crm.db").write_bytes(b"copia")
        estado = {"dia": "2026-10-29", "quando": quando or time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "ok": ok, "bases": {"crm.db": {}}}
        if erro:
            estado["erro"] = erro
        (pasta / "estado.json").write_text(json.dumps(estado), encoding="utf-8")

    def saude(self):
        resposta = self.cliente.get("/api/painel/saude")
        self.assertEqual(resposta.status_code, 200)
        return resposta.get_json()

    def test_painel_expoe_backup_bases_cache_e_disco(self):
        self.escrever_estado()
        dados = self.saude()

        self.assertTrue(dados["ok"])
        self.assertTrue(dados["backup"]["ok"])
        self.assertEqual(dados["backup"]["dia"], "2026-10-29")
        self.assertEqual(dados["backup"]["copias"], 1)
        self.assertLess(dados["backup"]["idade_horas"], 1)

        nomes = [item["nome"] for item in dados["sqlite"]]
        self.assertEqual(nomes, ["crm.db", "revisoes.db"])
        for item in dados["sqlite"]:
            self.assertTrue(item["existe"])
            self.assertTrue(item["ok"])
            self.assertEqual(item["integridade"], "ok")
            self.assertEqual(item["tabelas"], 1)

        self.assertTrue(dados["cache_tipos"]["existe"])
        self.assertEqual(dados["cache_tipos"]["entradas"], 2)
        self.assertEqual(dados["processando"]["total"], 0)
        self.assertGreater(dados["disco"]["livre_gb"], 0)
        self.assertGreater(dados["disco"]["total_gb"], 0)

    def test_backup_falhado_e_sem_copias(self):
        self.escrever_estado(ok=False, erro="nenhuma base encontrada em dados/")
        dados = self.saude()
        self.assertFalse(dados["backup"]["ok"])
        self.assertEqual(dados["backup"]["erro"], "nenhuma base encontrada em dados/")

        shutil.rmtree(self.base / "backups" / "diario" / "2026-10-29")
        dados = self.saude()
        self.assertFalse(dados["backup"]["ok"])
        self.assertEqual(dados["backup"]["erro"], "sem copias")

    def test_base_corrompida_aparece_como_nao_ok(self):
        (self.base / "dados" / "revisoes.db").write_bytes(b"isto nao e um banco sqlite")
        dados = self.saude()
        revisoes = [item for item in dados["sqlite"] if item["nome"] == "revisoes.db"][0]
        self.assertFalse(revisoes["ok"])

    def test_pagina_do_painel_inclui_os_novos_indicadores(self):
        self.escrever_estado()
        resposta = self.cliente.get("/painel")
        self.assertEqual(resposta.status_code, 200)
        pagina = resposta.get_data(as_text=True)
        for texto in ("Backup diário", "Bases SQLite", "Cache de classificação", "Disco"):
            self.assertIn(texto, pagina)


if __name__ == "__main__":
    unittest.main()
