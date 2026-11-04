# -*- coding: utf-8 -*-
"""Contrato do retorno precificado: comparação, desconto, gravação e PDF.

Não toca no vivo nem em bases MRV; usa o sandbox (dados/crm.db) só para o
round-trip e apaga o que insere.
"""

import sys

sys.dont_write_bytecode = True

import os
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "web"))

import fitz

import comparador_retorno
from comparador_retorno import comparar_retorno, resumo_retorno
from extrator_orcamento_gamatec import extrair_orcamento_gamatec
from historico_comparador import carregar_processo, gravar_processo, gravar_retorno
import historico_comparador


def pdf_em_memoria(*paginas):
    with fitz.open() as documento:
        for texto in paginas:
            pagina = documento.new_page(width=1200, height=1600)
            if texto:
                pagina.insert_text((40, 55), texto, fontsize=10, fontname="helv")
        return documento.tobytes()


def registrar(codigo, descricao, quantidade, preco_tabela=None, unidade="UN"):
    total = round(quantidade * preco_tabela, 2) if preco_tabela is not None else None
    return {
        "CODIGO_KRONA": codigo,
        "DESCRICAO": descricao,
        "DESCRICAO_TABELA": descricao,
        "QUANTIDADE": quantidade,
        "UNIDADE": unidade,
        "PRECO_TABELA": preco_tabela,
        "TOTAL": total,
        "STATUS": "OK" if preco_tabela is not None else "SEM",
        "VIA": "CÓD. KRONA" if codigo else "—",
        "OBS": None,
    }


def item(codigo, descricao, qtde, preco):
    return {"codigo": codigo, "descricao": descricao, "qtde": qtde,
            "preco_orcamento": preco}


class TestCompararRetorno(unittest.TestCase):

    def test_codigo_direto_e_desconto(self):
        registros = [
            registrar("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 484, 0.652),
            registrar("29", "TUBO PVC SOLDAVEL 6M 75MM", 4, 201.698, "BR"),
        ]
        itens = [
            item("0331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 484, 0.58),
            item("29", "TUBO PVC SOLDAVEL - 6M - 75MM", 4, 180.0),
        ]
        linhas = comparar_retorno(registros, itens)
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0]["VIA"], "CÓD. KRONA")
        self.assertEqual(linhas[0]["STATUS"], "OK")
        self.assertAlmostEqual(linhas[0]["DESCONTO_PCT"], 11.04, places=2)
        self.assertEqual(linhas[0]["TOTAL_GAMATEC"], 280.72)
        self.assertAlmostEqual(linhas[1]["DESCONTO_PCT"], 10.76, places=2)
        self.assertEqual(linhas[1]["TOTAL_TABELA"], 806.79)

    def test_quantidade_difere_vai_a_revisao(self):
        registros = [registrar("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 484, 0.652)]
        linhas = comparar_retorno(
            registros, [item("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 500, 0.58)])
        self.assertEqual(linhas[0]["STATUS"], "REVISAR")
        self.assertIn("quantidade difere", linhas[0]["OBS"])

    def test_sem_codigo_casa_por_descricao(self):
        registros = [registrar("", "JOELHO 90 GRAUS 25MM", 10, None)]
        linhas = comparar_retorno(
            registros, [item("50", "JOELHO 90 GRAUS 25MM", 10, 0.9)])
        self.assertEqual(linhas[0]["VIA"], "DESCRIÇÃO")
        self.assertEqual(linhas[0]["STATUS"], "OK")
        self.assertIsNone(linhas[0]["DESCONTO_PCT"])
        self.assertEqual(linhas[0]["TOTAL_GAMATEC"], 9.0)

    def test_sem_preco_no_retorno_e_extra(self):
        registros = [registrar("555", "ITEM SEM RETORNO", 2, 5.0)]
        linhas = comparar_retorno(
            registros,
            [item("999", "FITA VEDA ROSCA BRANCA 18MM", 3, 7.0)])
        self.assertEqual(len(linhas), 2)
        sem = next(l for l in linhas if l["VIA"] == "—")
        self.assertEqual(sem["STATUS"], "SEM")
        self.assertEqual(sem["OBS"], "sem preço no retorno")
        self.assertIsNone(sem["PRECO_GAMATEC"])
        extra = next(l for l in linhas if l["VIA"] == "SÓ NO RETORNO")
        self.assertEqual(extra["STATUS"], "SEM")
        self.assertIsNone(extra["PRECO_TABELA"])
        self.assertEqual(extra["PRECO_GAMATEC"], 7.0)

    def test_linhas_repetidas_do_retorno_somam(self):
        registros = [registrar("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 484, 0.652)]
        linhas = comparar_retorno(registros, [
            item("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 300, 0.58),
            item("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 184, 0.58),
        ])
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["TOTAL_GAMATEC"], 280.72)

    def test_resumo(self):
        registros = [
            registrar("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 484, 0.652),
            registrar("29", "TUBO PVC SOLDAVEL 6M 75MM", 4, 201.698, "BR"),
            registrar("", "JOELHO 90 GRAUS 25MM", 10, None),
            registrar("555", "ITEM SEM RETORNO", 2, 5.0),
        ]
        itens = [
            item("0331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 484, 0.58),
            item("29", "TUBO PVC SOLDAVEL - 6M - 75MM", 4, 180.0),
            item("50", "JOELHO 90 GRAUS 25MM", 10, 0.9),
            item("999", "FITA VEDA ROSCA BRANCA 18MM", 3, 7.0),
        ]
        stats = resumo_retorno(comparar_retorno(registros, itens))
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["ok"], 3)
        self.assertEqual(stats["sem"], 2)
        self.assertEqual(stats["extras"], 1)
        self.assertEqual(stats["sem_retorno"], 1)
        self.assertEqual(stats["total_tabela"], 1122.36)
        self.assertEqual(stats["total_gamatec"], 1000.72)
        self.assertAlmostEqual(stats["desconto_total"], 10.84, places=2)


class TestGravacaoRetorno(unittest.TestCase):

    def setUp(self):
        self.pid = gravar_processo({
            "cliente": "TESTE RETORNO", "vigencia": "2026", "numero": "",
            "nome_arquivo": "teste.pdf", "layout": "TESTE",
            "stats": {"total": 1, "ok": 1, "revisar": 0, "sem": 0,
                      "sem_preco": 0, "com_preco_documento": 0,
                      "valor_total": 10.0},
            "registros": [registrar("331", "ADAPTADOR SOLD CURTO 25MM X 3/4", 10, 1.0)],
        })

    def tearDown(self):
        import sqlite3
        conn = sqlite3.connect(historico_comparador.CAMINHO_CRM)
        try:
            conn.execute("DELETE FROM historico_comparador WHERE id = ?", (self.pid,))
            conn.commit()
        finally:
            conn.close()

    def test_round_trip(self):
        retorno = {
            "numero_orcamento": "K999", "cliente": "CLI", "emissao": "04/11/2026",
            "nome_arquivo": "retorno.pdf",
            "linhas": [{
                "CODIGO_KRONA": "331", "DESCRICAO": "ADAPTADOR SOLD CURTO 25MM X 3/4",
                "QUANTIDADE": 10, "UNIDADE": "UN", "PRECO_TABELA": 1.0,
                "TOTAL_TABELA": 10.0, "PRECO_GAMATEC": 0.9, "TOTAL_GAMATEC": 9.0,
                "DESCONTO_PCT": 10.0, "STATUS": "OK", "VIA": "CÓD. KRONA", "OBS": None,
            }],
            "stats": {"total": 1, "ok": 1, "revisar": 0, "sem": 0, "extras": 0,
                      "sem_retorno": 0, "total_tabela": 10.0, "total_gamatec": 9.0,
                      "desconto_total": 10.0},
        }
        self.assertTrue(gravar_retorno(self.pid, retorno))
        dados = carregar_processo(self.pid)
        self.assertEqual(dados["estado"], "retorno_comparado")
        self.assertIsNotNone(dados["retorno_em"])
        self.assertEqual(dados["retorno"]["numero_orcamento"], "K999")
        self.assertEqual(dados["retorno"]["stats"]["desconto_total"], 10.0)
        self.assertEqual(dados["retorno"]["linhas"][0]["DESCONTO_PCT"], 10.0)

    def test_gravacao_em_processo_inexistente(self):
        self.assertFalse(gravar_retorno(999999, {}))


class TestFimAFimEBM(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from extrator_documento_nao_precificado import extrair_documento_nao_precificado
        from match_documento_tabela import comparar_documento_tabela
        from matcher import carregar_base_krona
        from matcher_tabela_cliente import preparar_indice
        from tabelas_clientes import carregar_tabela

        caminho = os.path.join(BASE, "processados_cotacao",
                               "CotacaoEnvio3827008403476578550.pdf")
        with open(caminho, "rb") as arquivo:
            documento = extrair_documento_nao_precificado(
                arquivo.read(), "CotacaoEnvio3827008403476578550.pdf")
        itens_tabela, cls.vigencia = carregar_tabela("EBM")
        base = carregar_base_krona()
        indice = preparar_indice(itens_tabela, base)
        cls.registros = comparar_documento_tabela(documento["itens"], indice, base)

    def _numero_br(self, valor):
        texto = f"{valor:.3f}".rstrip("0").rstrip(".").replace(".", ",")
        return texto if "," in texto else f"{texto},0"

    def _valor_br(self, valor):
        return f"{valor:.3f}".replace(".", ",")

    def _qtde_br(self, valor):
        valor = float(valor)
        if valor.is_integer():
            return str(int(valor))
        return f"{valor:.3f}".replace(".", ",")

    def _retorno_linha(self, registro):
        codigo = registro["CODIGO_KRONA"]
        descricao = (registro["DESCRICAO_TABELA"] or registro["DESCRICAO"] or "").strip()
        quantidade = registro["QUANTIDADE"]
        preco = round(registro["PRECO_TABELA"] * 0.9, 3)
        total = round(quantidade * preco, 2)
        return (f"{codigo.zfill(4)} {descricao} 1 "
                f"{self._qtde_br(quantidade)} {self._valor_br(preco)} "
                f"{self._valor_br(total)}")

    def test_fluxo_completo_com_pdf_sintetico(self):
        com_codigo = [r for r in self.registros if r["CODIGO_KRONA"] and r["PRECO_TABELA"]]
        self.assertGreaterEqual(len(com_codigo), 5,
                                "EBM devia ter itens com código e preço")
        escolhidos = com_codigo[:6]
        linhas_pdf = [self._retorno_linha(r) for r in escolhidos]
        linhas_pdf.append("9999 FITA VEDA ROSCA BRANCA 18MM 1 3 7,500 22,50")

        pdf_bytes = pdf_em_memoria(
            "Nº Orçamento: K999  Cliente: 123/456-EMB Emissão: 04/11/2026\n"
            "Produto Emb Qtde Unitário Total\n" + "\n".join(linhas_pdf),
        )
        extraido = extrair_orcamento_gamatec(pdf_bytes)
        self.assertEqual(extraido["numero_orcamento"], "K999")
        self.assertEqual(len(extraido["itens"]), len(escolhidos) + 1)

        linhas = comparar_retorno(self.registros, extraido["itens"])
        stats = resumo_retorno(linhas)

        por_codigo = sum(1 for linha in linhas if linha["VIA"] == "CÓD. KRONA")
        self.assertEqual(por_codigo, len(escolhidos))
        self.assertEqual(stats["extras"], 1)
        self.assertGreater(stats["sem_retorno"], 0)
        for linha in linhas:
            if linha["VIA"] == "CÓD. KRONA":
                self.assertAlmostEqual(linha["DESCONTO_PCT"], 10.0, places=1)
        self.assertAlmostEqual(stats["desconto_total"], 10.0, places=1)

    def test_pdf_do_retorno(self):
        from pdf_retorno_comparador import gerar_pdf_retorno
        dados = {
            "cliente": "EBM", "vigencia": self.vigencia, "numero": "",
            "nome_arquivo": "CotacaoEnvio3827008403476578550.pdf", "layout": "COTACAO",
            "criado_em": "2026-11-04 10:00:00",
        }
        retorno = {
            "numero_orcamento": "K999", "cliente": "EMB", "emissao": "04/11/2026",
            "nome_arquivo": "retorno.pdf",
            "linhas": [{
                "CODIGO_KRONA": "331", "DESCRICAO": "ADAPTADOR SOLD CURTO 25MM X 3/4",
                "QUANTIDADE": 484, "UNIDADE": "UN", "PRECO_TABELA": 0.652,
                "TOTAL_TABELA": 315.57, "PRECO_GAMATEC": 0.58,
                "TOTAL_GAMATEC": 280.72, "DESCONTO_PCT": 11.04,
                "STATUS": "OK", "VIA": "CÓD. KRONA", "OBS": None,
            }, {
                "CODIGO_KRONA": "", "DESCRICAO": "SEM PRECO", "QUANTIDADE": 1,
                "UNIDADE": "UN", "PRECO_TABELA": None, "TOTAL_TABELA": None,
                "PRECO_GAMATEC": None, "TOTAL_GAMATEC": None,
                "DESCONTO_PCT": None, "STATUS": "SEM", "VIA": "—",
                "OBS": "sem preço no retorno",
            }],
            "stats": {"total": 2, "ok": 1, "revisar": 0, "sem": 1, "extras": 0,
                      "sem_retorno": 1, "total_tabela": 315.57,
                      "total_gamatec": 280.72, "desconto_total": 11.04},
        }
        pdf = gerar_pdf_retorno(dados, retorno)
        self.assertTrue(pdf.startswith(b"%PDF"))


class TestRotasRegistradas(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import web.app_web as app_web
        cls.app = app_web.app

    def test_rotas_do_retorno_no_blueprint(self):
        rotas = {regra.rule for regra in self.app.url_map.iter_rules()
                 if "retorno" in regra.rule}
        esperadas = {
            "/comparador/documento-nao-precificado/historico/<int:pid>/retorno",
            "/comparador/documento-nao-precificado/historico/<int:pid>/retorno/ver",
            "/comparador/documento-nao-precificado/historico/<int:pid>/retorno/download",
            "/comparador/documento-nao-precificado/historico/<int:pid>/retorno/pdf",
        }
        self.assertTrue(esperadas.issubset(rotas))

    def test_template_do_resultado_renderiza(self):
        from flask import render_template
        with self.app.test_request_context():
            html = render_template(
                "comparador/nao_precificado_retorno_resultado.html",
                dados={"cliente": "EBM", "vigencia": "2026", "numero": "",
                       "id": 1, "stats": {"valor_total": 10.0}},
                retorno={"nome_arquivo": "retorno.pdf", "numero_orcamento": "K1",
                         "emissao": "04/11/2026"},
                linhas=[{
                    "CODIGO_KRONA": "331", "DESCRICAO": "ADAPTADOR",
                    "QUANTIDADE": 10, "UNIDADE": "UN", "PRECO_TABELA": 1.0,
                    "TOTAL_TABELA": 10.0, "PRECO_GAMATEC": 0.9,
                    "TOTAL_GAMATEC": 9.0, "DESCONTO_PCT": 10.0,
                    "STATUS": "OK", "VIA": "CÓD. KRONA", "OBS": None,
                }],
                stats={"total": 1, "ok": 1, "revisar": 0, "sem": 0,
                       "sem_retorno": 0, "extras": 0, "total_tabela": 10.0,
                       "total_gamatec": 9.0, "desconto_total": 10.0},
            )
        self.assertIn("Retorno comparado", html)
        self.assertIn("10.00%", html)


if __name__ == "__main__":
    unittest.main()
