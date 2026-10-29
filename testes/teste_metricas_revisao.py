# -*- coding: utf-8 -*-
"""Métricas da fila de revisão: pendentes, tempo até resolução e OCs com mais correções."""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "web"))

import app_web
from dados import revisao_store


def inserir(db, arquivo, status, criado_em, resolvido_em=None, tipo="SEM_MATCH"):
    db.execute(
        "INSERT INTO itens_revisao (arquivo, num_item, descricao_oc, tipo_match, status, "
        "criado_em, resolvido_em) VALUES (?,?,?,?,?,?,?)",
        (arquivo, "1", "ITEM DE TESTE", tipo, status, criado_em, resolvido_em),
    )


class MetricasRevisaoTeste(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vortex-metricas-revisao-")
        self.caminho = str(Path(self.temp.name) / "revisoes.db")
        self.patch = patch.object(revisao_store, "DB_PATH", self.caminho)
        self.patch.start()
        revisao_store.init_db()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def escrever(self, linhas):
        with closing(sqlite3.connect(self.caminho)) as db:
            for linha in linhas:
                inserir(db, *linha)
            db.commit()

    def test_tempo_medio_e_mediana_das_resolucoes(self):
        self.escrever([
            ("A.pdf", "resolvido", "2026-10-01 08:00:00", "2026-10-01 10:00:00"),
            ("B.pdf", "resolvido", "2026-10-02 08:00:00", "2026-10-02 14:00:00"),
        ])
        dados = revisao_store.metricas_revisao()

        self.assertEqual(dados["resolvidos"], 2)
        self.assertEqual(dados["amostra_tempo"], 2)
        self.assertEqual(dados["tempo_medio"], "4 h")
        self.assertEqual(dados["tempo_mediano"], "4 h")

    def test_descartados_nao_entram_no_tempo(self):
        self.escrever([
            ("A.pdf", "descartado", "2026-10-01 08:00:00", "2026-10-09 08:00:00"),
        ])
        dados = revisao_store.metricas_revisao()

        self.assertEqual(dados["resolvidos"], 0)
        self.assertEqual(dados["descartados"], 1)
        self.assertIsNone(dados["tempo_medio"])
        self.assertEqual(dados["taxa_correcao"], 0)

    def test_top_ocs_ordena_por_correcoes(self):
        self.escrever([
            ("POUCAS.pdf", "resolvido", "2026-10-01 08:00:00", "2026-10-01 09:00:00"),
            ("MUITAS.pdf", "resolvido", "2026-10-01 08:00:00", "2026-10-01 09:00:00"),
            ("MUITAS.pdf", "resolvido", "2026-10-01 08:00:00", "2026-10-01 09:00:00"),
            ("MUITAS.pdf", "pendente", "2026-10-01 08:00:00"),
            ("SO_DESCARTE.pdf", "descartado", "2026-10-01 08:00:00", "2026-10-01 09:00:00"),
        ])
        dados = revisao_store.metricas_revisao()

        self.assertEqual([oc["arquivo"] for oc in dados["top_ocs"]],
                         ["MUITAS.pdf", "POUCAS.pdf"])
        self.assertEqual(dados["top_ocs"][0]["correcoes"], 2)
        self.assertEqual(dados["top_ocs"][0]["pendentes"], 1)
        self.assertEqual(dados["ocs_com_correcao"], 2)
        self.assertEqual(dados["pendentes"], 1)

    def test_fila_vazia_nao_quebra(self):
        dados = revisao_store.metricas_revisao()

        self.assertEqual(dados["pendentes"], 0)
        self.assertEqual(dados["resolvidos"], 0)
        self.assertIsNone(dados["pendente_mais_antigo_dias"])
        self.assertIsNone(dados["taxa_correcao"])
        self.assertEqual(dados["top_ocs"], [])

    def test_pendente_mais_antigo_conta_em_dias(self):
        self.escrever([
            ("A.pdf", "pendente", "2026-01-01 08:00:00"),
        ])
        dados = revisao_store.metricas_revisao()
        self.assertGreater(dados["pendente_mais_antigo_dias"], 100)

    def test_pagina_de_revisao_mostra_as_metricas(self):
        self.escrever([
            ("MUITAS.pdf", "resolvido", "2026-10-01 08:00:00", "2026-10-01 10:00:00"),
            ("MUITAS.pdf", "resolvido", "2026-10-01 08:00:00", "2026-10-01 12:00:00"),
            ("OUTRA.pdf", "pendente", "2026-10-01 08:00:00"),
        ])
        app_web.app.config.update(TESTING=True)
        cliente = app_web.app.test_client()
        with cliente.session_transaction() as sessao:
            sessao["user"] = "teste"
            sessao["tipo"] = "admin"

        resposta = cliente.get("/revisao")
        self.assertEqual(resposta.status_code, 200)
        pagina = resposta.get_data(as_text=True)
        for texto in ("Tempo até resolução", "OCs com mais correções", "MUITAS.pdf",
                      "3 h", "% corrigidos"):
            self.assertIn(texto, pagina)


if __name__ == "__main__":
    unittest.main()
