import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "web"))


class CotacaoEscolhaEstado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vortex-cotacao-teste-")
        cls.env = patch.dict(os.environ, {
            "GAMATEC_BASE_DIR": cls.temp.name,
            "GAMATEC_SECRET_KEY": "sessao-exclusiva-teste",
            "VORTEX_EMPRESA_ID": "",
        })
        cls.env.start()
        import app_web
        import processar_cotacao
        from extracao_oc.classificador_documento import Resultado
        cls.web = app_web
        cls.cotacao = processar_cotacao
        cls.Resultado = Resultado

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.web.PROCESSOS_ATIVOS.clear()
        self.nome = self.id().rsplit(".", 1)[-1] + ".pdf"
        self.entrada = Path(self.web.PASTA_ENTRADA) / self.nome
        self.entrada.write_bytes(b"PDF de teste")
        self.log = Path(self.web.caminho_log(self.nome))
        Path(self.web.TIPOS_DOCUMENTO_FILE).write_text("{}", encoding="utf-8")
        self.client = self.web.app.test_client()
        with self.client.session_transaction() as session:
            session["user"] = "teste"
            session["tipo"] = "admin"

    def marcar(self, tipo):
        Path(self.web.TIPOS_DOCUMENTO_FILE).write_text(
            json.dumps({self.nome: tipo}), encoding="utf-8",
        )

    def falhar(self):
        self.log.write_text(
            "COTACAO NAO PROCESSADA: SEM_TEXTO\n"
            "Detalhe: PDF digitalizado precisa de OCR\n"
            "[WEB] Processo finalizado com ERRO em 2s (returncode=2).\n",
            encoding="utf-8",
        )

    def test_manual_cotacao_vence_indefinido(self):
        self.marcar("COTACAO")
        indefinido = self.Resultado("UI", "nenhum", "sem sinais", False, 1)
        with patch.object(self.cotacao, "classificar_documento", return_value=indefinido), \
                patch.object(self.cotacao, "extrair_cotacao", return_value={"ok": True, "itens": [], "layout": ""}) as extrair:
            resultado = self.cotacao.processar_cotacao_individual(str(self.entrada))
        self.assertEqual(resultado["motivo"], "LAYOUT_NAO_SUPORTADO")
        extrair.assert_called_once()

    def test_manual_cotacao_nao_esconde_sem_texto(self):
        self.marcar("COTACAO")
        sem_texto = self.Resultado("UI", "nenhum", "sem texto", True, 1)
        with patch.object(self.cotacao, "classificar_documento", return_value=sem_texto):
            resultado = self.cotacao.processar_cotacao_individual(str(self.entrada))
        self.assertEqual(resultado["motivo"], "SEM_TEXTO")
        self.assertEqual(resultado["classificacao"], "COTACAO")

    def test_manual_oc_impede_fluxo_cotacao(self):
        self.marcar("OC")
        cotacao = self.Resultado("COTACAO", "conteudo", "coleta", False, 2)
        with patch.object(self.cotacao, "classificar_documento", return_value=cotacao):
            resultado = self.cotacao.processar_cotacao_individual(str(self.entrada))
        self.assertEqual(resultado["motivo"], "NAO_E_COTACAO")

    def test_indefinido_sem_escolha_permanece_pendente(self):
        indefinido = self.Resultado("UI", "nenhum", "sem sinais", False, 1)
        with patch.object(self.cotacao, "classificar_documento", return_value=indefinido):
            resultado = self.cotacao.processar_cotacao_individual(str(self.entrada))
        self.assertEqual(resultado["motivo"], "CLASSIFICACAO_PENDENTE")

    def test_escolha_gravada_antes_de_iniciar(self):
        def iniciar(nome):
            tipos = json.loads(Path(self.web.TIPOS_DOCUMENTO_FILE).read_text(encoding="utf-8"))
            self.assertEqual(tipos[nome], "COTACAO")
            return True, "Iniciado"
        with patch.object(self.web, "iniciar_processamento_cotacao", side_effect=iniciar):
            resposta = self.client.post("/api/definir-tipo/" + self.nome, data={"tipo": "COTACAO"})
        self.assertEqual(resposta.status_code, 200)

    def test_escolha_pdf_removido_nao_grava(self):
        self.entrada.unlink()
        resposta = self.client.post("/api/definir-tipo/" + self.nome, data={"tipo": "COTACAO"})
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(json.loads(Path(self.web.TIPOS_DOCUMENTO_FILE).read_text()), {})

    def test_status_erro_com_detalhe(self):
        self.falhar()
        resposta = self.client.get("/api/status-cotacao/" + self.nome)
        self.assertEqual(resposta.json["estado"], "erro")
        self.assertEqual(resposta.json["mensagem"], "PDF digitalizado precisa de OCR")

    def test_status_processando_nao_declara_sucesso(self):
        self.falhar()
        self.web.PROCESSOS_ATIVOS[self.nome] = Mock(poll=Mock(return_value=None))
        resposta = self.client.get("/api/status-cotacao/" + self.nome)
        self.assertEqual(resposta.json["estado"], "processando")
        self.assertFalse(resposta.json["erro_processamento"])

    def test_planilha_antiga_nao_esconde_falha_nova(self):
        self.falhar()
        with patch.object(self.web, "localizar_planilha_cotacao", return_value="planilha-antiga.xlsx"):
            status = self.web.montar_status_cotacao(self.nome)
        self.assertEqual(status["estado"], "erro")

    def test_status_sucesso_com_planilha(self):
        with patch.object(self.web, "localizar_planilha_cotacao", return_value="planilha.xlsx"):
            status = self.web.montar_status_cotacao(self.nome)
        self.assertEqual(status["estado"], "concluido")

    def test_pdf_removido_estado_ausente(self):
        self.entrada.unlink()
        status = self.web.montar_status_cotacao(self.nome)
        self.assertEqual(status["estado"], "ausente")

    def test_excluir_entrada_em_erro(self):
        self.falhar()
        resposta = self.client.post("/api/excluir-erro", json={"arquivo": self.nome})
        self.assertTrue(resposta.json["ok"])
        self.assertFalse(self.entrada.exists())

    def test_excluir_entrada_normal_recusado(self):
        resposta = self.client.post("/api/excluir-erro", json={"arquivo": self.nome})
        self.assertEqual(resposta.status_code, 409)
        self.assertTrue(self.entrada.exists())

    def test_excluir_em_processamento_recusado(self):
        self.falhar()
        self.web.PROCESSOS_ATIVOS[self.nome] = Mock(poll=Mock(return_value=None))
        resposta = self.client.post("/api/excluir-erro", json={"arquivo": self.nome})
        self.assertEqual(resposta.status_code, 409)
        self.assertTrue(self.entrada.exists())

    def test_excluir_ausente_idempotente(self):
        self.entrada.unlink()
        resposta = self.client.post("/api/excluir-erro", json={"arquivo": self.nome})
        self.assertTrue(resposta.json["ok"])

    def test_excluir_pasta_erros(self):
        self.entrada.unlink()
        pasta = Path(self.web.BASE_DIR) / "erro_oc"
        pasta.mkdir(exist_ok=True)
        erro = pasta / self.nome
        erro.write_bytes(b"PDF de teste")
        resposta = self.client.post("/api/excluir-erro", json={"arquivo": self.nome})
        self.assertTrue(resposta.json["ok"])
        self.assertFalse(erro.exists())

    def test_reupload_nao_herda_erro_antigo(self):
        self.falhar()
        ts = self.log.stat().st_mtime + 10
        os.utime(self.entrada, (ts, ts))
        self.assertFalse(self.web.erro_processamento_arquivo(self.nome))
        resposta = self.client.post("/api/excluir-erro", json={"arquivo": self.nome})
        self.assertEqual(resposta.status_code, 409)
        self.assertTrue(self.entrada.exists())

    def test_listar_erro_na_entrada(self):
        self.falhar()
        itens = self.client.get("/api/listar-erros").json["arquivos"]
        item = next(i for i in itens if i["nome"] == self.nome)
        self.assertEqual(item["origem"], "entrada")

    def test_nomes_invalidos_e_sessao(self):
        for nome in ("../fora.pdf", "..\\fora.pdf", "C:fora.pdf", "arquivo.txt", None, 123):
            resposta = self.client.post("/api/excluir-erro", json={"arquivo": nome})
            self.assertEqual(resposta.status_code, 400, nome)
        client = self.web.app.test_client()
        self.assertEqual(client.post("/api/excluir-erro", json={"arquivo": self.nome}).status_code, 403)
        self.assertEqual(client.get("/api/status-cotacao/" + self.nome).status_code, 401)

    def test_inicio_duplicado_e_falha_subprocesso(self):
        self.web.PROCESSOS_ATIVOS[self.nome] = Mock(poll=Mock(return_value=None))
        with patch.object(self.web.subprocess, "Popen") as popen:
            ok, _ = self.web.iniciar_processamento_cotacao(self.nome)
            self.assertFalse(ok)
            popen.assert_not_called()
        self.web.PROCESSOS_ATIVOS.clear()
        with patch.object(self.web.subprocess, "Popen", side_effect=OSError("python indisponivel")):
            ok, mensagem = self.web.iniciar_processamento_cotacao(self.nome)
        self.assertFalse(ok)
        self.assertIn("Não foi possível iniciar", mensagem)


if __name__ == "__main__":
    unittest.main(verbosity=2)
