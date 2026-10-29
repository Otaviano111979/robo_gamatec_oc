# -*- coding: utf-8 -*-
"""Consulta e download das pastas de OCs; apenas leitura, sem sair delas."""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "web"))


class PastasTeste(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vortex-pastas-teste-")
        cls.base = Path(cls.temp.name)
        cls.env = patch.dict(os.environ, {
            "GAMATEC_BASE_DIR": str(cls.base),
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
        for pasta in (self.web.PASTA_ENTRADA, self.web.PASTA_PROCESSADOS):
            for nome in os.listdir(pasta):
                caminho = Path(pasta) / nome
                if caminho.is_file():
                    caminho.unlink()
        saida = Path(self.web.PASTA_SAIDA_OCS)
        if saida.exists():
            shutil.rmtree(saida)
        saida.mkdir(parents=True, exist_ok=True)

        agora = time.time()
        self.criar(self.web.PASTA_ENTRADA, "alfa 20.pdf", agora - 50)
        self.criar(self.web.PASTA_ENTRADA, "Zeta 100.pdf", agora - 10)
        self.criar(self.web.PASTA_ENTRADA, "LEIAME.txt", agora - 5, b"texto")
        self.criar(self.web.PASTA_PROCESSADOS, "Pedido Mãe.pdf", agora - 30)
        self.criar(self.web.PASTA_PROCESSADOS, "Antigo.pdf", agora - 60)
        self.criar(self.base, "segredo.pdf", agora - 5)

        pasta_planilha = saida / "Pedido_Mãe"
        pasta_planilha.mkdir()
        (pasta_planilha / "Pedido_Mãe_planilha_digitacao_manual.xlsx").write_bytes(b"PK")

        self.client = self.web.app.test_client()
        with self.client.session_transaction() as sessao:
            sessao["user"] = "teste"
            sessao["tipo"] = "admin"

    def criar(self, pasta, nome, mtime, conteudo=b"%PDF-1.4 teste"):
        caminho = Path(pasta) / nome
        caminho.write_bytes(conteudo)
        os.utime(caminho, (mtime, mtime))
        return caminho

    def linhas(self, html):
        return html.count('class="arquivo-celula"')

    def test_anonimo_redireciona_para_entrada(self):
        anonimo = self.web.app.test_client()
        for url in ("/pastas", "/pastas/ver/entrada/alfa%2020.pdf",
                    "/pastas/baixar/entrada/alfa%2020.pdf"):
            resposta = anonimo.get(url)
            self.assertEqual(resposta.status_code, 302, url)
            self.assertTrue(resposta.headers["Location"].endswith("/"), url)

    def test_lista_apenas_pdfs_do_mais_recente_para_o_mais_antigo(self):
        corpo = self.client.get("/pastas").get_data(as_text=True)
        self.assertEqual(self.linhas(corpo), 2)
        self.assertIn("Zeta 100.pdf", corpo)
        self.assertIn("alfa 20.pdf", corpo)
        self.assertNotIn("LEIAME.txt", corpo)
        self.assertLess(corpo.index("Zeta 100.pdf"), corpo.index("alfa 20.pdf"))

    def test_contagens_e_separadores(self):
        self.assertEqual(self.web.contar_pdfs_pasta(self.web.PASTA_ENTRADA), 2)
        self.assertEqual(self.web.contar_pdfs_pasta(self.web.PASTA_PROCESSADOS), 2)
        corpo = self.client.get("/pastas?pasta=processados").get_data(as_text=True)
        self.assertIn("Entrada", corpo)
        self.assertIn("Processados", corpo)
        self.assertIn("Antigo.pdf", corpo)
        self.assertIn("Pedido Mãe.pdf", corpo)

    def test_pasta_desconhecida_mostra_entrada(self):
        corpo = self.client.get("/pastas?pasta=qualquer").get_data(as_text=True)
        self.assertEqual(self.linhas(corpo), 2)
        self.assertIn("alfa 20.pdf", corpo)

    def test_busca_ignora_caixa_e_acentos(self):
        corpo = self.client.get("/pastas?pasta=processados&q=mae").get_data(as_text=True)
        self.assertEqual(self.linhas(corpo), 1)
        self.assertIn("Pedido Mãe.pdf", corpo)
        vazio = self.client.get("/pastas?pasta=processados&q=inexistente").get_data(as_text=True)
        self.assertEqual(self.linhas(vazio), 0)
        self.assertIn("Nenhum ficheiro", vazio)

    def test_planilha_so_aparece_nos_processados_que_a_tem(self):
        entrada = self.client.get("/pastas?pasta=entrada").get_data(as_text=True)
        self.assertNotIn("baixar-planilha", entrada)
        processados = self.client.get("/pastas?pasta=processados").get_data(as_text=True)
        self.assertEqual(processados.count("baixar-planilha"), 1)
        linha_mae = processados[processados.index("Pedido Mãe.pdf"):]
        linha_antigo = processados[processados.index("Antigo.pdf"):]
        self.assertIn("baixar-planilha", linha_mae.split("</tr>")[0])
        self.assertNotIn("baixar-planilha", linha_antigo.split("</tr>")[0])

    def test_paginacao_de_cem_e_limites(self):
        for nome in os.listdir(self.web.PASTA_ENTRADA):
            (Path(self.web.PASTA_ENTRADA) / nome).unlink()
        agora = time.time()
        for indice in range(101):
            self.criar(self.web.PASTA_ENTRADA, f"lote {indice:03d}.pdf", agora - indice)
        primeira = self.client.get("/pastas").get_data(as_text=True)
        self.assertEqual(self.linhas(primeira), 100)
        self.assertIn("Página 1 de 2", primeira)
        segunda = self.client.get("/pastas?pagina=2").get_data(as_text=True)
        self.assertEqual(self.linhas(segunda), 1)
        limite = self.client.get("/pastas?pagina=999").get_data(as_text=True)
        self.assertIn("Página 2 de 2", limite)
        invalida = self.client.get("/pastas?pagina=abc").get_data(as_text=True)
        self.assertIn("Página 1 de 2", invalida)

    def test_ver_pdf_no_navegador(self):
        resposta = self.client.get("/pastas/ver/entrada/alfa%2020.pdf")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.mimetype, "application/pdf")
        self.assertIn("inline", resposta.headers["Content-Disposition"])
        self.assertTrue(resposta.get_data().startswith(b"%PDF-"))
        resposta.close()

    def test_descarregar_pdf_como_anexo(self):
        resposta = self.client.get("/pastas/baixar/processados/Pedido%20M%C3%A3e.pdf")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("attachment", resposta.headers["Content-Disposition"])
        resposta.close()

    def test_bloqueia_caminhos_fora_das_pastas_e_nao_pdf(self):
        casos = [
            "/pastas/ver/entrada/..%2Fsegredo.pdf",
            "/pastas/ver/entrada/%2e%2e%2fsegredo.pdf",
            "/pastas/ver/entrada/..%5Csegredo.pdf",
            "/pastas/ver/entrada/LEIAME.txt",
            "/pastas/ver/entrada/inexistente.pdf",
            "/pastas/ver/outra/alfa%2020.pdf",
            "/pastas/baixar/entrada/%2Fetc%2Fpasswd",
            "/pastas/baixar/processados/..%2Fentrada%2Falfa%2020.pdf",
        ]
        for url in casos:
            resposta = self.client.get(url, follow_redirects=True)
            self.assertEqual(resposta.status_code, 404, url)
            self.assertNotIn(b"passwd", resposta.get_data())
        resposta = self.client.get("/pastas/ver/entrada/segredo.pdf")
        self.assertEqual(resposta.status_code, 404)

    def test_consulta_nao_escreve_nem_altera_sessao(self):
        def instantaneo():
            registos = []
            for raiz in (self.web.PASTA_ENTRADA, self.web.PASTA_PROCESSADOS,
                         self.web.PASTA_SAIDA_OCS):
                for caminho in sorted(Path(raiz).rglob("*")):
                    if caminho.is_file():
                        info = caminho.stat()
                        registos.append((str(caminho), info.st_size, info.st_mtime_ns))
            return registos

        with self.client.session_transaction() as sessao:
            antes_sessao = dict(sessao)
        antes = instantaneo()
        for url in ("/pastas", "/pastas?pasta=processados", "/pastas?q=pedido",
                    "/pastas/ver/entrada/alfa%2020.pdf",
                    "/pastas/baixar/processados/Antigo.pdf"):
            self.client.get(url).close()
        self.assertEqual(instantaneo(), antes)
        with self.client.session_transaction() as sessao:
            self.assertEqual(dict(sessao), antes_sessao)

    def test_entrada_na_barra_lateral_e_na_pagina(self):
        pastas = self.client.get("/pastas").get_data(as_text=True)
        self.assertIn('href="/pastas"', pastas)
        self.assertIn('<a href="/pastas" class="is-active">', pastas)
        ocs = self.client.get("/ocs").get_data(as_text=True)
        self.assertIn('href="/pastas"', ocs)


if __name__ == "__main__":
    unittest.main()
