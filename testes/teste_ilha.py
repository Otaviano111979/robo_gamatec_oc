# -*- coding: utf-8 -*-
"""Ilha da sidebar: leitura das fontes, cache, fallback e rota /api/ilha."""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "web"))

import ilha_mercado as ilha


def rss(*itens):
    corpo = "".join(
        "<item><title>{}</title><link>{}</link><pubDate>{}</pubDate></item>".format(*item)
        for item in itens
    )
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss><channel>{}</channel></rss>".format(corpo)).encode("utf-8")


def hoje_mais(dias):
    return (datetime.now(ilha.FUSO).date() + timedelta(days=dias)).isoformat()


class IlhaDadosTeste(unittest.TestCase):
    def setUp(self):
        ilha.limpar_cache()

    def tearDown(self):
        ilha.limpar_cache()

    def test_tempo_arredonda_e_rotula_os_dias(self):
        dados = {
            "current": {
                "temperature_2m": 27.6, "apparent_temperature": 31.4,
                "relative_humidity_2m": 60.6, "wind_speed_10m": 6.4, "weather_code": 3,
            },
            "daily": {
                "time": [hoje_mais(0), hoje_mais(1), hoje_mais(2), hoje_mais(3)],
                "weather_code": [3, 61, 0, 95],
                "temperature_2m_max": [29.4, 28.5, 30.2, 31.0],
                "temperature_2m_min": [20.4, 19.6, 21.2, 22.0],
            },
        }
        with patch.object(ilha, "_obter_json", return_value=dados):
            tempo = ilha._tempo()
        self.assertEqual(tempo["agora"]["temp"], 28)
        self.assertEqual(tempo["agora"]["sensacao"], 31)
        self.assertEqual(tempo["agora"]["descricao"], "Nublado")
        self.assertEqual(tempo["agora"]["icone"], "nublado")
        self.assertEqual([d["rotulo"] for d in tempo["dias"]][:2], ["Hoje", "Amanhã"])
        self.assertEqual(len(tempo["dias"]), 4)
        self.assertEqual(tempo["dias"][1]["icone"], "chuva")
        self.assertEqual(tempo["dias"][3]["descricao"], "Trovoada")

    def test_tempo_com_codigo_desconhecido_nao_quebra(self):
        dados = {
            "current": {"temperature_2m": 20, "apparent_temperature": 20,
                        "relative_humidity_2m": 50, "wind_speed_10m": 1, "weather_code": 999},
            "daily": {"time": [hoje_mais(0)], "weather_code": [999],
                      "temperature_2m_max": [25], "temperature_2m_min": [15]},
        }
        with patch.object(ilha, "_obter_json", return_value=dados):
            tempo = ilha._tempo()
        self.assertEqual(tempo["agora"]["descricao"], "Tempo variável")

    def test_mercado_com_cambio_e_bolsa(self):
        cambio = {
            "USDBRL": {"bid": "5.3873", "pctChange": "0.768771"},
            "EURBRL": {"bid": "5.9987", "pctChange": "-0.25"},
        }
        bolsa = {"results": {"stocks": {"IBOVESPA": {"points": 170188.11, "variation": -0.48}}}}

        def obter(url):
            return cambio if "awesomeapi" in url else bolsa

        with patch.object(ilha, "_obter_json", side_effect=obter):
            mercado = ilha._mercado()
        self.assertEqual([i["nome"] for i in mercado], ["Dólar", "Euro", "IBOV"])
        self.assertAlmostEqual(mercado[0]["valor"], 5.3873)
        self.assertAlmostEqual(mercado[1]["variacao"], -0.25)
        self.assertEqual(mercado[2]["valor"], 170188.11)
        self.assertEqual(mercado[2]["casas"], 0)

    def test_mercado_sem_bolsa_mantem_o_cambio(self):
        cambio = {"USDBRL": {"bid": "5.38", "pctChange": "0.1"}}
        with patch.object(ilha, "_obter_json", side_effect=lambda url: cambio if "awesomeapi" in url else {}):
            mercado = ilha._mercado()
        self.assertEqual([i["nome"] for i in mercado], ["Dólar"])

    def test_noticias_uma_por_fonte_sem_sufixo_do_google(self):
        feeds = {
            "cbic": rss(("Obra avança no 3º trimestre", "https://cbic.org.br/a",
                         "Wed, 28 Oct 2026 13:00:00 +0000"),
                        ("Segunda manchete", "https://cbic.org.br/b",
                         "Wed, 28 Oct 2026 12:00:00 +0000")),
            "itambe": rss(("Juros e crédito em 2027", "https://www.cimentoitambe.com.br/x",
                           "Tue, 27 Oct 2026 17:00:00 +0000")),
            "google": rss(("Pesquisa sobre lodo na construção - Portal Y",
                           "https://news.google.com/rss/articles/abc", "Wed, 28 Oct 2026 14:00:00 GMT")),
        }

        def texto(url):
            for chave, corpo in feeds.items():
                if chave in url:
                    return corpo
            raise AssertionError(url)

        with patch.object(ilha, "_obter_texto", side_effect=texto):
            noticias = ilha._noticias()
        self.assertEqual(len(noticias), 3)
        self.assertEqual(noticias[0]["fonte"], "Portal Y")
        self.assertEqual(noticias[0]["titulo"], "Pesquisa sobre lodo na construção")
        self.assertEqual(noticias[1]["fonte"], "CBIC")
        self.assertEqual(noticias[2]["fonte"], "Cimento Itambé")
        self.assertTrue(noticias[0]["publicada"].startswith("2026-10-28T11:00"))

    def test_noticias_ignora_link_inseguro_e_xml_invalido(self):
        feeds = {
            "cbic": rss(("Má intenção", "javascript:alert(1)", "Wed, 28 Oct 2026 13:00:00 +0000")),
            "itambe": b"<rss><channel><item>",
            "google": rss(("Titulo - Fonte", "https://news.google.com/x", "Wed, 28 Oct 2026 14:00:00 GMT")),
        }

        def texto(url):
            for chave, corpo in feeds.items():
                if chave in url:
                    return corpo
            raise AssertionError(url)

        with patch.object(ilha, "_obter_texto", side_effect=texto):
            noticias = ilha._noticias()
        self.assertEqual([n["titulo"] for n in noticias], ["Titulo"])

    def test_cache_evita_ler_as_fontes_duas_vezes(self):
        chamadas = {"tempo": 0, "mercado": 0, "noticias": 0}

        def tempo():
            chamadas["tempo"] += 1
            return {"cidade": "Goiânia", "agora": {"temp": 28}, "dias": []}

        def mercado():
            chamadas["mercado"] += 1
            return [{"nome": "Dólar", "valor": 5.38, "variacao": 0.1, "casas": 2}]

        def noticias():
            chamadas["noticias"] += 1
            return [{"titulo": "t", "fonte": "f", "url": "https://exemplo.com", "publicada": None}]

        with patch.object(ilha, "_tempo", tempo), \
                patch.object(ilha, "_mercado", mercado), \
                patch.object(ilha, "_noticias", noticias):
            primeira = ilha.coletar()
            segunda = ilha.coletar()
        self.assertFalse(primeira["cache"])
        self.assertTrue(segunda["cache"])
        self.assertEqual(chamadas, {"tempo": 1, "mercado": 1, "noticias": 1})
        self.assertTrue(primeira["ok"])
        self.assertFalse(primeira["desatualizado"])

    def test_falha_usa_ultima_leitura_e_marca_desatualizado(self):
        with patch.object(ilha, "_tempo", return_value={"cidade": "Goiânia", "agora": {"temp": 28}, "dias": []}), \
                patch.object(ilha, "_mercado", return_value=[{"nome": "Dólar", "valor": 5.38,
                                                              "variacao": 0.1, "casas": 2}]), \
                patch.object(ilha, "_noticias", return_value=[]):
            ilha.coletar()
        with patch.object(ilha, "_tempo", side_effect=OSError("sem rede")), \
                patch.object(ilha, "_mercado", side_effect=OSError("sem rede")), \
                patch.object(ilha, "_noticias", side_effect=OSError("sem rede")):
            dados = ilha.coletar(forcar=True)
        self.assertTrue(dados["desatualizado"])
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["tempo"]["agora"]["temp"], 28)
        self.assertTrue(dados["mercado_desatualizado"])
        self.assertEqual(dados["noticias"], [])
        self.assertTrue(dados["noticias_desatualizado"])
        self.assertEqual(ilha._cache["ttl"], ilha.CACHE_TTL_FALHA)

    def test_sem_leitura_anterior_devolve_vazio(self):
        with patch.object(ilha, "_tempo", side_effect=OSError("sem rede")), \
                patch.object(ilha, "_mercado", side_effect=OSError("sem rede")), \
                patch.object(ilha, "_noticias", side_effect=OSError("sem rede")):
            dados = ilha.coletar()
        self.assertFalse(dados["ok"])
        self.assertIsNone(dados["tempo"])
        self.assertEqual(dados["mercado"], [])
        self.assertEqual(dados["noticias"], [])


class IlhaRotaTeste(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vortex-ilha-teste-")
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
        ilha.limpar_cache()
        self.cliente = self.web.app.test_client()
        with self.cliente.session_transaction() as sessao:
            sessao["user"] = "teste"
            sessao["tipo"] = "admin"

    def test_anonimo_recebe_403(self):
        resposta = self.web.app.test_client().get("/api/ilha")
        self.assertEqual(resposta.status_code, 403)

    def test_sessao_recebe_os_dados(self):
        dados = {"ok": True, "atualizado": "2026-10-29T11:00:00-03:00", "tempo": None,
                 "mercado": [], "noticias": [], "desatualizado": False}
        with patch.object(ilha, "coletar", return_value=dados) as coletar:
            resposta = self.cliente.get("/api/ilha")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json()["ok"], True)
        coletar.assert_called_once_with(forcar=False)

    def test_forcar_repassa_para_a_leitura(self):
        with patch.object(ilha, "coletar", return_value={"ok": True}) as coletar:
            resposta = self.cliente.get("/api/ilha?forcar=1")
        self.assertEqual(resposta.status_code, 200)
        coletar.assert_called_once_with(forcar=True)

    def test_pagina_com_sidebar_traz_a_ilha(self):
        corpo = self.cliente.get("/pastas").get_data(as_text=True)
        self.assertIn('id="ilha"', corpo)
        self.assertIn("une_representacoes.png", corpo)
        self.assertIn("une_representacoes_dark.png", corpo)
        self.assertIn("css/pg_ilha.css", corpo)
        self.assertIn("js/ilha.js", corpo)


if __name__ == "__main__":
    unittest.main()
