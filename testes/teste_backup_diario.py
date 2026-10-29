# -*- coding: utf-8 -*-
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import backup_diario


def criar_banco(caminho, tabela, linhas):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with closing(sqlite3.connect(caminho)) as db:
        db.execute(f'CREATE TABLE "{tabela}" (id INTEGER PRIMARY KEY, valor TEXT)')
        db.executemany(f'INSERT INTO "{tabela}" (valor) VALUES (?)', [(v,) for v in linhas])
        db.commit()


def linhas(caminho, tabela):
    with closing(sqlite3.connect(caminho)) as db:
        return db.execute(f'SELECT id, valor FROM "{tabela}" ORDER BY id').fetchall()


def sha(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def dias_guardados(base):
    pasta = Path(base) / "backups" / "diario"
    return sorted(p.name for p in pasta.iterdir() if p.is_dir() and backup_diario.PADRAO_DIA.match(p.name))


class BackupDiarioTeste(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="vortex-backup-"))
        self.base = str(self.pasta)
        self.crm = self.pasta / "dados" / "crm.db"
        self.revisoes = self.pasta / "dados" / "revisoes.db"
        criar_banco(str(self.crm), "clientes", ["a", "b", "c"])
        criar_banco(str(self.revisoes), "revisoes", ["x"])

    def test_copia_verificada_e_uma_vez_por_dia(self):
        antes = (sha(self.crm), sha(self.revisoes))
        resumo = backup_diario.executar_se_necessario(self.base, date(2026, 10, 29))

        self.assertTrue(resumo["ok"])
        destino = self.pasta / "backups" / "diario" / "2026-10-29"
        self.assertEqual(sorted(p.name for p in destino.iterdir()),
                         ["crm.db", "estado.json", "revisoes.db"])
        estado = json.loads((destino / "estado.json").read_text(encoding="utf-8"))
        self.assertTrue(estado["ok"])
        self.assertEqual(estado["dia"], "2026-10-29")
        self.assertEqual(estado["bases"]["crm.db"]["tabelas"], {"clientes": 3})
        self.assertEqual(estado["bases"]["revisoes.db"]["tabelas"], {"revisoes": 1})
        self.assertEqual(linhas(str(destino / "crm.db"), "clientes"), linhas(str(self.crm), "clientes"))
        self.assertEqual(linhas(str(destino / "revisoes.db"), "revisoes"), linhas(str(self.revisoes), "revisoes"))

        self.assertIsNone(backup_diario.executar_se_necessario(self.base, date(2026, 10, 29)))
        self.assertEqual((sha(self.crm), sha(self.revisoes)), antes)

    def test_rotacao_mantem_14_dias_e_nao_mexe_no_resto(self):
        pasta = self.pasta / "backups" / "diario"
        for dia in range(1, 21):
            (pasta / f"2026-09-{dia:02d}").mkdir(parents=True)
        (pasta / "pre-ilha-sidebar-20261029").mkdir()

        backup_diario.executar_se_necessario(self.base, date(2026, 10, 29))

        dias = dias_guardados(self.base)
        self.assertEqual(len(dias), backup_diario.DIAS_A_GUARDAR)
        self.assertEqual(dias[-1], "2026-10-29")
        self.assertTrue((pasta / "pre-ilha-sidebar-20261029").is_dir())

    def test_falha_fica_registada_e_e_repetida(self):
        os.remove(self.crm)
        os.remove(self.revisoes)
        resumo = backup_diario.executar_se_necessario(self.base, date(2026, 10, 29))

        self.assertFalse(resumo["ok"])
        estado = json.loads((self.pasta / "backups" / "diario" / "2026-10-29" / "estado.json")
                            .read_text(encoding="utf-8"))
        self.assertFalse(estado["ok"])
        self.assertIn("nenhuma base", estado["erro"])

        criar_banco(str(self.crm), "clientes", ["a"])
        self.assertTrue(backup_diario.executar_se_necessario(self.base, date(2026, 10, 29))["ok"])
        self.assertTrue((self.pasta / "backups" / "diario" / "2026-10-29" / "crm.db").is_file())

    def test_base_dia_seguinte_nao_aproveita_a_de_ontem(self):
        backup_diario.executar_se_necessario(self.base, date(2026, 10, 29))
        criar_banco(str(self.crm), "novos", ["n"])
        backup_diario.executar_se_necessario(self.base, date(2026, 10, 30))

        estado = json.loads((self.pasta / "backups" / "diario" / "2026-10-30" / "estado.json")
                            .read_text(encoding="utf-8"))
        self.assertIn("novos", estado["bases"]["crm.db"]["tabelas"])


if __name__ == "__main__":
    unittest.main()
