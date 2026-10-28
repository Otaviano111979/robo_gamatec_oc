import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import iniciar_sistema as iniciar


class ArranqueUnico(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vortex arranque teste ")
        self.raiz = Path(self.temp.name)
        self.socket = socket.socket()
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.bind(("0.0.0.0", 0))
        self.porta = self.socket.getsockname()[1]
        self.env = patch.dict(os.environ, {"GAMATEC_PORT": str(self.porta)})
        self.env.start()
        self.config = patch.multiple(iniciar, RAIZ=str(self.raiz), ENV=str(self.raiz / ".env"))
        self.config.start()

    def tearDown(self):
        self.socket.close()
        self.config.stop()
        self.env.stop()
        self.temp.cleanup()

    def main(self, *args):
        with patch.object(sys, "argv", ["iniciar_sistema.py", *args]):
            return iniciar.main()

    def test_porta_ocupada_nao_toca_env_nem_atualiza(self):
        self.socket.listen()
        with patch.object(iniciar, "garantir_env") as env, \
                patch.object(iniciar, "dependencias_em_falta") as deps, \
                patch.object(iniciar.subprocess, "run") as atualizar, \
                patch.object(iniciar, "abrir_navegador") as navegador:
            self.assertEqual(self.main("--atualizar", "--abrir-navegador"), 2)
        for mock in (env, deps, atualizar, navegador):
            mock.assert_not_called()
        self.assertFalse((self.raiz / ".env").exists())

    def test_preflight_livre_sem_mutacao(self):
        self.socket.close()
        with patch.object(iniciar, "garantir_env") as env, \
                patch.object(iniciar.subprocess, "run") as atualizar:
            self.assertEqual(self.main("--preflight"), 0)
        env.assert_not_called()
        atualizar.assert_not_called()
        self.assertFalse((self.raiz / ".env").exists())

    def test_arranque_livre_preserva_porta_e_caminho_com_espacos(self):
        self.socket.close()
        (self.raiz / "web").mkdir()
        (self.raiz / "web/app_web.py").write_text("", encoding="utf-8")
        with patch.object(iniciar, "garantir_env") as env, \
                patch.object(iniciar, "dependencias_em_falta", return_value=False), \
                patch.object(iniciar, "iniciar_web", return_value=0) as web:
            self.assertEqual(self.main(), 0)
        env.assert_called_once()
        self.assertEqual(web.call_args.args[0], self.porta)
        self.assertFalse(web.call_args.args[2])
        self.assertEqual(os.environ["GAMATEC_PORT"], str(self.porta))

    def test_portas_invalidas(self):
        for valor in ("0", "65536", "abc", "-1"):
            with patch.dict(os.environ, {"GAMATEC_PORT": valor}), \
                    patch.object(iniciar, "garantir_env") as env:
                self.assertEqual(self.main(), 1)
                env.assert_not_called()

    def test_bloqueio_concorrente_e_reutilizacao_confirmada(self):
        self.socket.listen()
        codigo = (
            "import sys; sys.path.insert(0, sys.argv[1]); import iniciar_sistema as i; "
            "i.RAIZ=sys.argv[2]; "
            "\nwith i.bloqueio_arranque(int(sys.argv[3])) as (f, pronto):"
            "\n assert f is not None"
            "\n f.write(__import__('os').path.normcase(i.RAIZ).encode('utf-8')); f.flush()"
            "\n print('BLOQUEADO', flush=True); sys.stdin.readline()"
        )
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", codigo, str(RAIZ), str(self.raiz), str(self.porta)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8",
        )
        try:
            self.assertEqual(proc.stdout.readline().strip(), "BLOQUEADO")
            with patch.object(iniciar, "garantir_env") as env, \
                    patch.object(iniciar, "abrir_navegador") as navegador:
                self.assertEqual(self.main("--atualizar", "--abrir-navegador"), 2)
            env.assert_not_called()
            navegador.assert_called_once_with(self.porta)
        finally:
            proc.communicate("terminar\n", timeout=10)
        self.assertEqual(proc.returncode, 0)
        with iniciar.bloqueio_arranque(self.porta) as (arquivo, pronto):
            self.assertIsNotNone(arquivo)
            self.assertFalse(pronto)

    def test_bloqueio_sem_servidor_nao_abre_navegador(self):
        self.socket.close()
        with iniciar.bloqueio_arranque(self.porta):
            with patch.object(iniciar, "abrir_navegador") as navegador:
                self.assertEqual(self.main("--abrir-navegador"), 2)
            navegador.assert_not_called()

    def test_instancia_outra_pasta_nao_e_reutilizada(self):
        self.socket.listen()
        with patch.object(iniciar, "RAIZ", str(self.raiz / "outra")):
            with iniciar.bloqueio_arranque(self.porta) as (arquivo, _):
                arquivo.write(os.path.normcase(iniciar.RAIZ).encode("utf-8"))
                arquivo.flush()
                with patch.object(iniciar, "RAIZ", str(self.raiz)), \
                        patch.object(iniciar, "abrir_navegador") as navegador:
                    self.assertEqual(self.main("--abrir-navegador"), 2)
                navegador.assert_not_called()

    def test_atualizacao_protegida_pelo_bloqueio(self):
        self.socket.close()
        (self.raiz / "web").mkdir()
        (self.raiz / "web/app_web.py").write_text("", encoding="utf-8")
        def atualizar(comando):
            self.assertEqual(comando, [sys.executable, str(self.raiz / "instalador/atualizador.py")])
            with iniciar.bloqueio_arranque(self.porta) as (arquivo, _):
                self.assertIsNone(arquivo)
        with patch.object(iniciar.subprocess, "run", side_effect=atualizar) as update, \
                patch.object(iniciar, "garantir_env"), \
                patch.object(iniciar, "dependencias_em_falta", return_value=False), \
                patch.object(iniciar, "iniciar_web", return_value=0):
            self.assertEqual(self.main("--atualizar"), 0)
        update.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
