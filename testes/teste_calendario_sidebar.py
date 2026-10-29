# -*- coding: utf-8 -*-
"""Calendário da sidebar: feriados, datas importantes, efemérides e cache."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "web"))

import calendario


NACIONAIS = [
    {"date": "2026-01-01", "name": "Confraternização mundial", "type": "national"},
    {"date": "2026-10-12", "name": "Nossa Senhora Aparecida", "type": "national"},
]
ESTADUAIS = [
    {"data": "02/07/2026", "nome": "Independência da Bahia", "uf": "BA", "codigo_ibge": None},
]
MUNICIPAIS = [
    {"data": "12/10/2026", "nome": "Nossa Senhora Aparecida", "uf": "GO", "codigo_ibge": 5208707},
    {"data": "24/10/2026", "nome": "Aniversário de Goiânia", "uf": "GO", "codigo_ibge": 5208707},
    {"data": "05/09/2026", "nome": "Feriado de outra cidade", "uf": "GO", "codigo_ibge": 5201405},
]
COMEMORATIVAS = [
    {"data": "12/10/2026", "nome": "Dia das Crianças"},
    {"data": "15/10/2026", "nome": "Dia do Professor"},
]
EFEMERIDES = {
    "events": [
        {"year": 1969, "text": "Acontecimento importante de outubro."},
        {"year": 1923, "text": "Y" * 300},
        {"year": 1801, "text": "Terceiro acontecimento."},
        {"year": 1500, "text": "Quarto acontecimento, que não deve aparecer."},
    ]
}


def fonte(url):
    if "brasilapi" in url:
        return NACIONAIS
    if "estadual" in url:
        return ESTADUAIS
    if "municipal" in url:
        return MUNICIPAIS
    if "comemorativas" in url:
        return COMEMORATIVAS
    if "onthisday" in url:
        return EFEMERIDES
    raise AssertionError(url)


class CalendarioTeste(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vortex-calendario-")
        self.anterior = calendario.CACHE_FILE
        calendario.CACHE_FILE = os.path.join(self.temp.name, "cache_calendario.json")
        calendario.limpar_cache()

    def tearDown(self):
        calendario.CACHE_FILE = self.anterior
        calendario.limpar_cache()
        self.temp.cleanup()

    def test_mes_junta_nacional_go_e_goiania_e_nao_repete(self):
        with patch.object(calendario, "_obter_json", side_effect=fonte):
            dados = calendario.mes(2026, 10)

        self.assertTrue(dados["ok"])
        self.assertTrue(dados["completo"])
        self.assertEqual(list(dados["feriados"]), ["2026-10-12", "2026-10-24"])

        aparecida = dados["feriados"]["2026-10-12"]
        self.assertEqual(len(aparecida), 1)
        self.assertEqual(aparecida[0]["rotulo"], "Nacional")

        aniversario = dados["feriados"]["2026-10-24"]
        self.assertEqual(aniversario[0]["nome"], "Aniversário de Goiânia")
        self.assertEqual(aniversario[0]["rotulo"], "Goiânia")

        self.assertEqual(
            [item["nome"] for item in dados["comemorativas"]["2026-10-12"]],
            ["Dia das Crianças"])
        self.assertNotIn("2026-09-05", dados["feriados"])
        self.assertNotIn("2026-07-02", dados["feriados"])

    def test_dia_traz_feriados_datas_e_ate_tres_acontecimentos(self):
        with patch.object(calendario, "_obter_json", side_effect=fonte):
            dados = calendario.dia("2026-10-12")

        self.assertEqual(dados["data"], "2026-10-12")
        self.assertEqual([item["nome"] for item in dados["feriados"]], ["Nossa Senhora Aparecida"])
        self.assertEqual([item["nome"] for item in dados["comemorativas"]], ["Dia das Crianças"])
        self.assertEqual([item["ano"] for item in dados["efemerides"]], [1969, 1923, 1801])
        self.assertLessEqual(len(dados["efemerides"]), calendario.EFEMERIDES_POR_DIA)
        for item in dados["efemerides"]:
            self.assertLessEqual(len(item["texto"]), calendario.EFEMERIDES_MAX_CARACTERES)

    def test_cache_em_disco_evita_ler_as_fontes_outra_vez(self):
        chamadas = []

        def contar(url):
            chamadas.append(url)
            return fonte(url)

        with patch.object(calendario, "_obter_json", side_effect=contar):
            calendario.mes(2026, 10)
        total = len(chamadas)
        self.assertEqual(total, 4)

        calendario.limpar_cache()
        with patch.object(calendario, "_obter_json", side_effect=contar):
            dados = calendario.mes(2026, 10)
        self.assertEqual(len(chamadas), total)
        self.assertTrue(dados["completo"])

        with open(calendario.CACHE_FILE, encoding="utf-8") as ficheiro:
            guardado = json.load(ficheiro)
        self.assertIn("feriados-nacional-2026", guardado)
        self.assertIn("comemorativas-2026", guardado)

    def test_uma_fonte_em_falha_nao_derruba_as_outras(self):
        def quebrada(url):
            if "brasilapi" in url:
                raise OSError("sem rede")
            return fonte(url)

        with patch.object(calendario, "_obter_json", side_effect=quebrada):
            dados = calendario.mes(2026, 10)

        self.assertFalse(dados["completo"])
        self.assertEqual(list(dados["feriados"]), ["2026-10-12", "2026-10-24"])

    def test_depois_de_guardado_funciona_sem_rede(self):
        with patch.object(calendario, "_obter_json", side_effect=fonte):
            calendario.dia("2026-10-12")
        calendario.limpar_cache()

        with patch.object(calendario, "_obter_json", side_effect=OSError("sem rede")):
            dados = calendario.dia("2026-10-12")

        self.assertTrue(dados["completo"])
        self.assertEqual(len(dados["efemerides"]), 3)
        self.assertEqual(dados["feriados"][0]["nome"], "Nossa Senhora Aparecida")


class CalendarioRotaTeste(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vortex-calendario-rota-")
        cls.env = patch.dict(os.environ, {
            "GAMATEC_BASE_DIR": cls.temp.name,
            "GAMATEC_SECRET_KEY": "sessao-exclusiva-teste",
            "VORTEX_EMPRESA_ID": "",
        })
        cls.env.start()
        import app_web
        cls.web = app_web

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.web.app.config.update(TESTING=True)
        self.cliente = self.web.app.test_client()
        with self.cliente.session_transaction() as sessao:
            sessao["user"] = "teste"
            sessao["tipo"] = "admin"

    def test_anonimo_recebe_403(self):
        anonimo = self.web.app.test_client()
        self.assertEqual(anonimo.get("/api/calendario").status_code, 403)
        self.assertEqual(anonimo.get("/api/calendario/dia?data=2026-10-12").status_code, 403)

    def test_mes_devolve_o_calendario(self):
        with patch.object(calendario, "mes", return_value={"ok": True, "feriados": {}}) as ler:
            resposta = self.cliente.get("/api/calendario?ano=2026&mes=10")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json()["ok"], True)
        ler.assert_called_once_with(2026, 10)

    def test_parametros_invalidos_sao_recusados(self):
        self.assertEqual(self.cliente.get("/api/calendario?ano=2026&mes=13").status_code, 400)
        self.assertEqual(self.cliente.get("/api/calendario?ano=abc&mes=10").status_code, 400)
        self.assertEqual(self.cliente.get("/api/calendario/dia?data=29-10-2026").status_code, 400)
        self.assertEqual(self.cliente.get("/api/calendario/dia").status_code, 400)

    def test_dia_valido_devolve_destaques(self):
        with patch.object(calendario, "dia", return_value={"ok": True, "efemerides": []}) as ler:
            resposta = self.cliente.get("/api/calendario/dia?data=2026-10-12")
        self.assertEqual(resposta.status_code, 200)
        ler.assert_called_once_with("2026-10-12")

    def test_sidebar_tem_calendario_depois_da_pilula(self):
        corpo = self.cliente.get("/pastas").get_data(as_text=True)
        self.assertIn('id="calendario"', corpo)
        self.assertIn("css/pg_calendario.css", corpo)
        self.assertIn("js/calendario.js", corpo)
        self.assertLess(corpo.index('id="ilha"'), corpo.index('id="calendario"'))
        self.assertLess(corpo.index('id="calendario"'), corpo.index('class="sidebar-foot"'))


if __name__ == "__main__":
    unittest.main()
