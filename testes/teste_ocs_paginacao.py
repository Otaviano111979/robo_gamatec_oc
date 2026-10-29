# -*- coding: utf-8 -*-
"""Lista de OCs paginada no servidor: 100 por página, filtros e ordenação."""

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

try:
    from dados import revisao_store
except Exception:  # base de dados ainda não existir nesta máquina
    revisao_store = None


def falso(indice):
    return {
        "nome": f"OC_{indice:04d}.pdf",
        "nome_base": f"OC_{indice:04d}",
        "numero_oc": str(1000 + indice),
        "timestamp_ref": 1000 + indice,
        "data_ref": "01/10/2026 10:00",
        "data_ref_iso": "2026-10-%02d" % (indice % 28 + 1),
        "tem_planilha": False,
        "status_label": "Na entrada",
        "status_classe": "status-pending",
        "planilha_label": "Ainda não gerada",
        "movimento_label": "PDF na entrada",
        "resumo": "",
        "em_entrada": True,
        "em_processados": False,
        "processando": False,
        "etapa": "pendente",
        "progresso": 0,
        "cliente_novo": False,
        "correcao_aplicada": False,
    }


class OcsPaginacaoTeste(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vortex-ocs-teste-")
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
        self.itens = {f"OC_{i:04d}.pdf": falso(i) for i in range(250)}
        self.ativos = [
            patch.object(self.web, "listar_cotacoes", return_value=[]),
            patch.object(self.web, "listar_todos_arquivos", return_value=list(self.itens)),
            patch.object(self.web, "montar_status_oc", side_effect=lambda nome: self.itens[nome]),
        ]
        if revisao_store is not None:
            self.ativos.append(patch.object(revisao_store, "contar_pendentes", return_value=0))
        for ativo in self.ativos:
            ativo.start()
        self.cliente = self.web.app.test_client()
        with self.cliente.session_transaction() as sessao:
            sessao["user"] = "teste"
            sessao["tipo"] = "admin"

    def tearDown(self):
        for ativo in self.ativos:
            ativo.stop()

    def corpo(self, url):
        return self.cliente.get(url).get_data(as_text=True)

    def linhas(self, html):
        return html.count("data-oc-row=")

    def test_anonimo_continua_a_ser_redirecionado(self):
        resposta = self.web.app.test_client().get("/ocs")
        self.assertEqual(resposta.status_code, 302)

    def test_primeira_pagina_tem_cem_ocs_e_avisa_do_total(self):
        html = self.corpo("/ocs")
        self.assertEqual(self.linhas(html), 100)
        self.assertIn("Mostrando 1–100 de 250 OCs.", html)
        self.assertIn("Página 1 de 3", html)
        self.assertIn("OC_0249.pdf", html)
        self.assertNotIn("OC_0149.pdf", html)
        self.assertNotIn("Ver todas", html)
        self.assertNotIn("Mostrar só 10", html)

    def test_segunda_e_terceira_pagina(self):
        segunda = self.corpo("/ocs?pagina=2")
        self.assertEqual(self.linhas(segunda), 100)
        self.assertIn("Mostrando 101–200 de 250 OCs.", segunda)
        self.assertIn("OC_0149.pdf", segunda)
        self.assertNotIn("OC_0049.pdf", segunda)

        terceira = self.corpo("/ocs?pagina=3")
        self.assertEqual(self.linhas(terceira), 50)
        self.assertIn("Mostrando 201–250 de 250 OCs.", terceira)
        self.assertIn("OC_0000.pdf", terceira)
        self.assertIn("Seguinte", segunda)
        self.assertNotIn("Seguinte", terceira)
        self.assertIn("Anterior", terceira)

    def test_pagina_invalida_ou_fora_do_limite(self):
        self.assertIn("Página 3 de 3", self.corpo("/ocs?pagina=999"))
        self.assertIn("Página 1 de 3", self.corpo("/ocs?pagina=abc"))
        self.assertIn("Página 1 de 3", self.corpo("/ocs?pagina=-4"))

    def test_busca_por_numero_e_por_ficheiro(self):
        por_numero = self.corpo("/ocs?q=1123")
        self.assertEqual(self.linhas(por_numero), 1)
        self.assertIn("OC_0123.pdf", por_numero)
        self.assertIn("Mostrando 1–1 de 1 OCs filtradas.", por_numero)

        por_nome = self.corpo("/ocs?q=oc_0249")
        self.assertEqual(self.linhas(por_nome), 1)
        self.assertIn("OC_0249.pdf", por_nome)

    def test_filtro_por_data(self):
        html = self.corpo("/ocs?data=2026-10-05")
        self.assertEqual(self.linhas(html), 9)
        self.assertIn("OCs filtradas", html)
        self.assertIn('value="2026-10-05"', html)

    def test_ordenacao_antigas(self):
        html = self.corpo("/ocs?ordem=antigos")
        self.assertLess(html.index("OC_0000.pdf"), html.index("OC_0099.pdf"))

    def test_filtro_vazio_mostra_mensagem_propria(self):
        html = self.corpo("/ocs?q=nao-existe")
        self.assertEqual(self.linhas(html), 0)
        self.assertIn("Nenhuma OC encontrada com o filtro atual.", html)

    def test_filtro_preservado_nos_links_de_paginacao(self):
        html = self.corpo("/ocs?q=OC")
        self.assertIn("Página 1 de 3", html)
        self.assertIn("q=OC", html)
        self.assertIn("pagina=2", html)

    def test_pagina_nao_leva_o_html_gigante(self):
        html = self.corpo("/ocs")
        tamanho = len(html.encode("utf-8"))
        self.assertLess(tamanho, 1024 * 1024)
        self.assertGreater(tamanho, 50 * 1024)


if __name__ == "__main__":
    unittest.main()
