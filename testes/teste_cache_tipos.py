# -*- coding: utf-8 -*-
"""Cache em disco da classificação de tipo de documento (primeira abertura de /ocs)."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "web"))

BASE_TESTE = tempfile.mkdtemp(prefix="vortex-cache-tipos-")
os.environ.setdefault("GAMATEC_BASE_DIR", BASE_TESTE)
os.environ.setdefault("GAMATEC_SECRET_KEY", "sessao-exclusiva-teste")
os.environ.setdefault("VORTEX_EMPRESA_ID", "")

import app_web
from extracao_oc import classificador_documento as classificador


class CacheTiposTeste(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="vortex-cache-caso-"))
        (self.pasta / "entrada_oc").mkdir()
        (self.pasta / "processados_cotacao").mkdir()
        (self.pasta / "dados").mkdir()
        self.pdf = self.pasta / "entrada_oc" / "cotacao_teste.pdf"
        self.pdf.write_bytes(b"primeira versao")
        self.cache = self.pasta / "dados" / "cache_tipos_documentos.json"
        self.manual = self.pasta / "dados" / "tipos_documentos.json"
        app_web._CACHE_TIPO_DOCUMENTO.clear()
        app_web._CACHE_TIPOS_DISCO = None
        self.patches = [
            patch.object(app_web, "BASE_DIR", str(self.pasta)),
            patch.object(app_web, "PASTA_ENTRADA", str(self.pasta / "entrada_oc")),
            patch.object(app_web, "PASTA_PROCESSADOS_COTACAO", str(self.pasta / "processados_cotacao")),
            patch.object(app_web, "CACHE_TIPOS_DOCUMENTO_FILE", str(self.cache)),
            patch.object(app_web, "TIPOS_DOCUMENTO_FILE", str(self.manual)),
            patch.object(classificador, "ARQ_TIPOS_DOCUMENTO", str(self.manual)),
        ]
        for patch_ativo in self.patches:
            patch_ativo.start()
        self.chamadas = 0
        self.original = classificador.classificar_documento
        classificador.classificar_documento = self._classificar

    def tearDown(self):
        classificador.classificar_documento = self.original
        for patch_ativo in reversed(self.patches):
            patch_ativo.stop()
        app_web._CACHE_TIPO_DOCUMENTO.clear()
        app_web._CACHE_TIPOS_DISCO = None
        shutil.rmtree(self.pasta, ignore_errors=True)

    def _classificar(self, caminho, nome=None):
        self.chamadas += 1
        return classificador.Resultado(classificador.COTACAO, "conteudo", "texto de teste")

    def test_classifica_uma_vez_e_reaproveita_entre_arranques(self):
        self.assertEqual(app_web.tipo_documento_arquivo("cotacao_teste.pdf")[0], "COTACAO")
        self.assertEqual(self.chamadas, 1)
        self.assertTrue(self.cache.is_file())
        app_web.tipo_documento_arquivo("cotacao_teste.pdf")
        self.assertEqual(self.chamadas, 1)
        app_web._CACHE_TIPO_DOCUMENTO.clear()
        app_web._CACHE_TIPOS_DISCO = None
        tipo, motivo = app_web.tipo_documento_arquivo("cotacao_teste.pdf")
        self.assertEqual((tipo, motivo), ("COTACAO", "texto de teste"))
        self.assertEqual(self.chamadas, 1)

    def test_ficheiro_alterado_volta_a_ser_classificado(self):
        app_web.tipo_documento_arquivo("cotacao_teste.pdf")
        self.pdf.write_bytes(b"segunda versao, com outro tamanho")
        app_web._CACHE_TIPO_DOCUMENTO.clear()
        app_web._CACHE_TIPOS_DISCO = None
        app_web.tipo_documento_arquivo("cotacao_teste.pdf")
        self.assertEqual(self.chamadas, 2)

    def test_falha_nao_grava_cache(self):
        classificador.classificar_documento = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falhou"))
        tipo, motivo = app_web.tipo_documento_arquivo("cotacao_teste.pdf")
        self.assertEqual(tipo, "OC")
        self.assertIn("indisponível", motivo)
        self.assertFalse(self.cache.is_file())


if __name__ == "__main__":
    unittest.main()
