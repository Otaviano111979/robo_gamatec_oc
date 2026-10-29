# -*- coding: utf-8 -*-
"""Contrato do documento precificado, sem PDFs em disco nem dados externos."""

import sys

sys.dont_write_bytecode = True

import copy
import os
import unittest
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "web"))

import fitz
import pandas as pd
from pandas.testing import assert_frame_equal

import comparador_oc_orcamento as comparador
from extrator_orcamento_gamatec import extrair_orcamento_gamatec


CABECALHO = "COD KRONA descrição VALOR unit qnd TOTAL"
COLUNAS_EXTRACAO = [
    "codigo_krona", "descricao_krona", "quantidade_final",
    "valor_unitario_oc", "total_documento", "pagina",
]
COLUNAS_LEGADAS = [
    "CODIGO", "DESCRICAO", "QUANTIDADE", "PRECO_OC", "PRECO_ORCAMENTO",
    "DESCONTO", "PRECO_FINAL", "OBS", "STATUS",
]
COLUNAS_TOTAIS = ["TOTAL_DOCUMENTO", "TOTAL_CALCULADO", "DIFERENCA_TOTAL"]
LINHA_VALIDA = "0001 ADAPTADOR SOLDAVEL 1/2 1,00 2 R$ 2,00"


def pdf_em_memoria(*paginas):
    """Texto Latin-1 real; None representa uma página só com imagem (OCR)."""
    with fitz.open() as documento:
        for texto in paginas:
            pagina = documento.new_page(width=1200, height=1600)
            if texto is None:
                imagem = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
                imagem.clear_with(220)
                pagina.insert_image(pagina.rect, stream=imagem.tobytes("png"))
            elif texto:
                pagina.insert_text((40, 55), texto, fontsize=10, fontname="helv")
        return documento.tobytes()


def orcamento(codigo, preco, quantidade=2, descricao="DESCRICAO ORCAMENTO"):
    return {
        "codigo": codigo, "descricao": descricao, "qtde": quantidade,
        "preco_orcamento": preco,
    }


def decimal_resultado(valor):
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


class TestExtratorDocumentoPrecificado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from extrator_documento_precificado import extrair_documento_precificado
        cls.extrair = staticmethod(extrair_documento_precificado)

    def extrair_linhas(self, *linhas, cabecalho=CABECALHO):
        return self.extrair(pdf_em_memoria("\n".join((cabecalho, *linhas))))

    def rejeitar_linha_sem_resultado_parcial(self, linha):
        with self.assertRaises(ValueError):
            self.extrair_linhas(
                LINHA_VALIDA, linha, "9999 ULTIMO ITEM 1,00 1 R$ 1,00",
            )

    def test_colunas_tipos_codigos_e_numeros_da_descricao(self):
        descricoes = [
            "TUBO PVC SOLDAVEL 6M", "ROLO ELETRODUTO 25 MT",
            "ADESIVO PVC 1000 ML", "ADAPTADOR SOLDAVEL 1/2",
        ]
        codigos = ["0001", "0029", "0331", "1232"]
        resultado = self.extrair_linhas(*[
            f"{codigo} {descricao} 0,879 1.000 R$ 879,00"
            for codigo, descricao in zip(codigos, descricoes)
        ])
        self.assertIsInstance(resultado, pd.DataFrame)
        self.assertEqual(list(resultado.columns), COLUNAS_EXTRACAO)
        self.assertEqual(resultado["codigo_krona"].tolist(), ["1", "29", "331", "1232"])
        self.assertEqual(resultado["descricao_krona"].tolist(), descricoes)
        for registro in resultado.to_dict("records"):
            self.assertIsInstance(registro["codigo_krona"], str)
            self.assertIsInstance(registro["descricao_krona"], str)
            for coluna in ("quantidade_final", "valor_unitario_oc", "total_documento"):
                self.assertIsInstance(registro[coluna], Decimal)
            self.assertEqual(registro["quantidade_final"], Decimal("1000"))
            self.assertEqual(registro["valor_unitario_oc"], Decimal("0.879"))
            self.assertEqual(registro["total_documento"], Decimal("879.00"))
            self.assertIsInstance(registro["pagina"], int)
            self.assertEqual(registro["pagina"], 1)

    def test_cabecalho_aceita_caixa_e_acentuacao_variadas(self):
        for cabecalho in (CABECALHO, CABECALHO.upper(), CABECALHO.lower(),
                          "cod krona DESCRIÇÃO valor UNIT QND total",
                          "COD KRONA descricao VALOR unit qnd TOTAL"):
            with self.subTest(cabecalho=cabecalho):
                self.assertEqual(len(self.extrair_linhas(LINHA_VALIDA, cabecalho=cabecalho)), 1)

    def test_milhares_e_quantidades_decimais_sem_conversao(self):
        casos = [
            ("2.016", "2016"), ("2016", "2016"),
            ("1.000", "1000"), ("1000", "1000"),
            ("2.016,50", "2016.50"), ("2016,50", "2016.50"),
            ("0,5", "0.5"), ("1.000.000", "1000000"),
        ]
        for quantidade_br, esperado in casos:
            with self.subTest(quantidade=quantidade_br):
                linha = f"1232 TUBO 6M 25 MT 1000 ML 1/2 0,879 {quantidade_br} R$ 438,00"
                registro = self.extrair_linhas(linha).iloc[0]
                self.assertEqual(registro["descricao_krona"], "TUBO 6M 25 MT 1000 ML 1/2")
                self.assertEqual(registro["quantidade_final"], Decimal(esperado))
                self.assertEqual(registro["valor_unitario_oc"], Decimal("0.879"))
                self.assertNotIn("unidade", registro.index)

    def test_precos_duas_tres_casas_e_zero_sao_preservados(self):
        for preco_br, esperado in (("0,00", "0.00"), ("0,000", "0.000"),
                                    ("1,41", "1.41"), ("1,412", "1.412"),
                                    ("1.234,56", "1234.56"), ("1.234,567", "1234.567")):
            with self.subTest(preco=preco_br):
                registro = self.extrair_linhas(f"0001 ITEM 1/2 {preco_br} 1 R$ 0,00").iloc[0]
                self.assertEqual(registro["valor_unitario_oc"], Decimal(esperado))
                self.assertEqual(registro["total_documento"], Decimal("0.00"))

    def test_exemplos_reais_nao_recalculam_o_total_documental(self):
        resultado = self.extrair_linhas(
            "1231 ELETRODUTO CORRUGADO 25 MT 0,879 5000 R$ 4.392,95",
            "1232 ELETRODUTO FLEXIVEL 6M 1,412 750 R$ 1.059,10",
        ).set_index("codigo_krona")
        for codigo, quantidade, preco, total in (
            ("1231", "5000", "0.879", "4392.95"),
            ("1232", "750", "1.412", "1059.10"),
        ):
            with self.subTest(codigo=codigo):
                self.assertEqual(resultado.loc[codigo, "quantidade_final"], Decimal(quantidade))
                self.assertEqual(resultado.loc[codigo, "valor_unitario_oc"], Decimal(preco))
                self.assertEqual(resultado.loc[codigo, "total_documento"], Decimal(total))

    def test_paginas_seguintes_sem_header_e_header_repetido(self):
        resultado = self.extrair(pdf_em_memoria(
            CABECALHO + "\n" + LINHA_VALIDA + "\n" + CABECALHO
            + "\n0029 SEGUNDO ITEM 1,00 2 R$ 2,00",
            "0331 TERCEIRO ITEM 1,00 2 R$ 2,00",
            CABECALHO.upper() + "\n1232 QUARTO ITEM 1,00 2 R$ 2,00",
        ))
        self.assertEqual(resultado["codigo_krona"].tolist(), ["1", "29", "331", "1232"])
        self.assertEqual(resultado["pagina"].tolist(), [1, 1, 2, 3])

    def test_cabecalho_ausente_ou_layout_nao_suportado(self):
        for cabecalho in ("", "COD KRONA descrição qnd VALOR unit TOTAL",
                          "COD KRONA descrição VALOR unit qtd TOTAL",
                          "CODIGO DESCRICAO QUANTIDADE PRECO TOTAL"):
            with self.subTest(cabecalho=cabecalho), self.assertRaises(ValueError):
                self.extrair_linhas(LINHA_VALIDA, cabecalho=cabecalho)

    def test_primeiro_header_obrigatorio_antes_dos_itens(self):
        for paginas in (
            (LINHA_VALIDA + "\n" + CABECALHO + "\n0029 ITEM 1,00 2 R$ 2,00",),
            (LINHA_VALIDA, CABECALHO + "\n0029 ITEM 1,00 2 R$ 2,00"),
        ):
            with self.subTest(paginas=paginas), self.assertRaises(ValueError):
                self.extrair(pdf_em_memoria(*paginas))

    def test_sem_texto_ou_pagina_ocr_nao_retornam_itens_parciais(self):
        texto_valido = CABECALHO + "\n" + LINHA_VALIDA
        for paginas in (("",), (None,), (texto_valido, ""),
                        (texto_valido, None), (None, texto_valido)):
            with self.subTest(paginas=paginas), self.assertRaises(ValueError):
                self.extrair(pdf_em_memoria(*paginas))

    def test_pdf_invalido(self):
        for dados in (b"", b"nao e um PDF", b"%PDF-1.7\nPDF truncado"):
            with self.subTest(dados=dados), self.assertRaises(ValueError):
                self.extrair(dados)

    def test_zero_itens(self):
        with self.assertRaises(ValueError):
            self.extrair(pdf_em_memoria(CABECALHO))

    def test_linhas_incompletas_ou_malformadas_nao_sao_ignoradas(self):
        for linha in (
            "1232 ELETRODUTO 1,412 750 R$", "1232 ELETRODUTO 1,412 750",
            "1232 ELETRODUTO", "1232 1,412 750 R$ 1.059,10",
            "1232 ELETRODUTO 1,412 750 R$ 1.059,10 SOBRA",
            "1232 ELETRODUTO 1,412\n750 R$ 1.059,10",
            "12345 ELETRODUTO 1,412 750 R$ 1.059,10",
            "ABCD ELETRODUTO 1,412 750 R$ 1.059,10",
        ):
            with self.subTest(linha=linha):
                self.rejeitar_linha_sem_resultado_parcial(linha)

    def test_valores_malformados_e_negativos(self):
        casos = [
            ("1,4", "750", "1.059,10"), ("1,4123", "750", "1.059,10"),
            ("1.412", "750", "1.059,10"), ("-1,412", "750", "1.059,10"),
            ("1,412", "-750", "1.059,10"), ("1,412", "1.00", "1.059,10"),
            ("1,412", "2.01.6", "1.059,10"), ("1,412", "QTD", "1.059,10"),
            ("1,412", "750", "-1.059,10"), ("1,412", "750", "1.059,1"),
            ("1,412", "750", "1.059,100"), ("1,412", "750", "1059.10"),
        ]
        for unitario, quantidade, total in casos:
            with self.subTest(unitario=unitario, quantidade=quantidade, total=total):
                self.rejeitar_linha_sem_resultado_parcial(
                    f"1232 ELETRODUTO 25 MT {unitario} {quantidade} R$ {total}",
                )
        self.rejeitar_linha_sem_resultado_parcial("1232 ELETRODUTO 1,412 750 1.059,10")

    def test_quantidade_zero_falha_mesmo_com_preco_total_zero(self):
        for quantidade in ("0", "0,00", "0,000"):
            with self.subTest(quantidade=quantidade):
                self.rejeitar_linha_sem_resultado_parcial(
                    f"1232 ELETRODUTO 0,00 {quantidade} R$ 0,00",
                )

    def test_codigo_duplicado_apos_normalizacao_na_mesma_pagina(self):
        with self.assertRaises(ValueError):
            self.extrair_linhas(
                "0012 PRIMEIRO ITEM 1,00 2 R$ 2,00",
                "12 SEGUNDO ITEM 1,00 3 R$ 3,00",
            )

    def test_codigo_duplicado_apos_normalizacao_entre_paginas(self):
        with self.assertRaises(ValueError):
            self.extrair(pdf_em_memoria(
                CABECALHO + "\n0012 PRIMEIRO ITEM 1,00 2 R$ 2,00",
                CABECALHO + "\n12 SEGUNDO ITEM 1,00 3 R$ 3,00",
            ))


class TestCompararDocumentoPrecificado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from comparador_oc_orcamento import comparar_documento_precificado
        from extrator_documento_precificado import extrair_documento_precificado
        cls.comparar = staticmethod(comparar_documento_precificado)
        cls.extrair = staticmethod(extrair_documento_precificado)

    def test_precos_mais_dez_igual_menos_dez_e_codigos_faltantes(self):
        pdf_bytes = pdf_em_memoria(CABECALHO + "\n" + "\n".join([
            "0001 MAIS DEZ 10,00 2 R$ 20,00",
            "0029 IGUAL 10,00 2 R$ 20,00",
            "0331 MENOS DEZ 10,00 2 R$ 20,00",
            "1232 SEM ORCAMENTO 1,412 750 R$ 1.059,10",
        ]))
        itens = [orcamento("1", 11.0), orcamento("29", 10.0),
                 orcamento("331", 9.0), orcamento("777", 3.0)]
        itens_antes = copy.deepcopy(itens)
        resultado = self.comparar(pdf_bytes, itens)
        self.assertEqual(itens, itens_antes)
        self.assertEqual(pdf_bytes[:5], b"%PDF-")
        self.assertTrue(set(COLUNAS_LEGADAS + COLUNAS_TOTAIS).issubset(resultado.columns))
        self.assertEqual(set(resultado["CODIGO"]), {"1", "29", "331", "1232", "777"})
        registros = resultado.set_index("CODIGO")
        for codigo, preco, desconto, final, status in (
            ("1", 11.0, 9.09091, "10.00", "OK"),
            ("29", 10.0, 0.0, "10.00", "ABAIXO"),
            ("331", 9.0, 0.0, "9.00", "ABAIXO"),
        ):
            with self.subTest(codigo=codigo):
                registro = registros.loc[codigo]
                self.assertEqual(registro["PRECO_OC"], 10.0)
                self.assertEqual(registro["PRECO_ORCAMENTO"], preco)
                self.assertEqual(registro["DESCONTO"], desconto)
                self.assertEqual(registro["PRECO_FINAL"], final)
                self.assertEqual(registro["STATUS"], status)
                self.assertEqual(decimal_resultado(registro["TOTAL_DOCUMENTO"]), Decimal("20.00"))
                self.assertEqual(decimal_resultado(registro["TOTAL_CALCULADO"]), Decimal("20.00"))
                self.assertEqual(decimal_resultado(registro["DIFERENCA_TOTAL"]), Decimal("0.00"))
        self.assertEqual(registros.loc["1232", "STATUS"], "SEM_ORC")
        self.assertEqual(decimal_resultado(registros.loc["1232", "TOTAL_DOCUMENTO"]), Decimal("1059.10"))
        self.assertEqual(decimal_resultado(registros.loc["1232", "TOTAL_CALCULADO"]), Decimal("1059.00"))
        self.assertEqual(decimal_resultado(registros.loc["1232", "DIFERENCA_TOTAL"]), Decimal("0.10"))
        self.assertEqual(registros.loc["777", "STATUS"], "SEM_OC")
        for coluna in COLUNAS_TOTAIS:
            self.assertIsNone(registros.loc["777", coluna])

    def test_totais_reais_usam_preco_explicito_sem_inferencia(self):
        pdf_bytes = pdf_em_memoria(CABECALHO + "\n" + "\n".join([
            "1231 ELETRODUTO 25 MT 0,879 5.000 R$ 4.392,95",
            "1232 ELETRODUTO 6M 1,412 750 R$ 1.059,10",
        ]))
        resultado = self.comparar(pdf_bytes, [orcamento("1231", 0.879),
                                             orcamento("1232", 1.412)]).set_index("CODIGO")
        for codigo, quantidade, preco, total, calculado, diferenca, final in (
            ("1231", "5000", "0.879", "4392.95", "4395.00", "-2.05", "0.87"),
            ("1232", "750", "1.412", "1059.10", "1059.00", "0.10", "1.41"),
        ):
            with self.subTest(codigo=codigo):
                registro = resultado.loc[codigo]
                self.assertEqual(decimal_resultado(registro["QUANTIDADE"]), Decimal(quantidade))
                self.assertEqual(decimal_resultado(registro["PRECO_OC"]), Decimal(preco))
                self.assertEqual(decimal_resultado(registro["TOTAL_DOCUMENTO"]), Decimal(total))
                self.assertEqual(decimal_resultado(registro["TOTAL_CALCULADO"]), Decimal(calculado))
                self.assertEqual(decimal_resultado(registro["DIFERENCA_TOTAL"]), Decimal(diferenca))
                self.assertEqual(registro["DESCONTO"], 0.0)
                self.assertEqual(registro["PRECO_FINAL"], final)
                self.assertLessEqual(Decimal(registro["PRECO_FINAL"]), Decimal(preco))

    def test_total_calculado_round_half_up_em_duas_casas(self):
        pdf_bytes = pdf_em_memoria(CABECALHO + "\n" + "\n".join([
            "0001 MEIO ITEM 0,01 0,5 R$ 0,01",
            "0029 MEIO ITEM 0,879 0,5 R$ 0,44",
        ]))
        resultado = self.comparar(pdf_bytes, []).set_index("CODIGO")
        for codigo, preco, esperado in (("1", "0.01", "0.01"), ("29", "0.879", "0.44")):
            with self.subTest(codigo=codigo):
                calculado = (Decimal(preco) * Decimal("0.5")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                )
                self.assertEqual(calculado, Decimal(esperado))
                self.assertEqual(decimal_resultado(resultado.loc[codigo, "TOTAL_CALCULADO"]), calculado)
                self.assertEqual(decimal_resultado(resultado.loc[codigo, "DIFERENCA_TOTAL"]), Decimal("0.00"))

    def test_preco_zero_e_quantidade_milhar(self):
        pdf_bytes = pdf_em_memoria(CABECALHO + "\n" + "\n".join([
            "0001 TUBO 6M 0,000 2.016 R$ 0,00",
            "0029 ADESIVO 1000 ML 0,879 1.000 R$ 879,00",
        ]))
        resultado = self.comparar(pdf_bytes, [orcamento("1", 1.0),
                                             orcamento("29", 0.879)]).set_index("CODIGO")
        self.assertEqual(resultado.loc["1", "QUANTIDADE"], 2016)
        self.assertEqual(resultado.loc["1", "PRECO_OC"], 0)
        self.assertEqual(resultado.loc["1", "DESCONTO"], 100.0)
        self.assertEqual(resultado.loc["1", "PRECO_FINAL"], "0.00")
        for coluna in COLUNAS_TOTAIS:
            self.assertEqual(decimal_resultado(resultado.loc["1", coluna]), Decimal("0"))
        self.assertEqual(resultado.loc["29", "QUANTIDADE"], 1000)
        self.assertEqual(decimal_resultado(resultado.loc["29", "PRECO_OC"]), Decimal("0.879"))
        self.assertEqual(decimal_resultado(resultado.loc["29", "TOTAL_CALCULADO"]), Decimal("879.00"))

    def test_reutiliza_comparador_existente_e_preserva_resultado_legado(self):
        pdf_bytes = pdf_em_memoria(CABECALHO + "\n" + LINHA_VALIDA)
        itens = [orcamento("0001", 1.1), orcamento("777", 2.0)]
        df_oc = self.extrair(pdf_bytes)
        df_antes = df_oc.copy(deep=True)
        esperado = comparador.comparar_oc_orcamento(df_oc, itens)
        self.assertEqual(list(esperado.columns), COLUNAS_LEGADAS)
        with patch.object(comparador, "comparar_oc_orcamento",
                          wraps=comparador.comparar_oc_orcamento) as legado:
            resultado = self.comparar(pdf_bytes, itens)
        legado.assert_called_once()
        assert_frame_equal(resultado[COLUNAS_LEGADAS].reset_index(drop=True),
                           esperado.reset_index(drop=True))
        assert_frame_equal(df_oc, df_antes)

    def test_wrapper_propaga_valueerror_sem_comparar_lista_parcial(self):
        validos_e_invalidos = pdf_em_memoria(
            CABECALHO + "\n" + LINHA_VALIDA + "\n1232 LINHA INCOMPLETA",
        )
        for pdf_bytes in (b"PDF invalido", pdf_em_memoria(CABECALHO), validos_e_invalidos):
            with self.subTest(inicio=pdf_bytes[:20]):
                with patch.object(comparador, "comparar_oc_orcamento") as legado:
                    with self.assertRaises(ValueError):
                        self.comparar(pdf_bytes, [orcamento("1", 1.0)])
                    legado.assert_not_called()


class TestRegressoesFontesExistentes(unittest.TestCase):
    def test_comparador_antigo_colunas_e_resultados_exatos_sem_totais(self):
        df_oc = pd.DataFrame([
            {"codigo_krona": codigo, "descricao_krona": descricao,
             "quantidade_final": Decimal("2"), "valor_unitario_oc": Decimal(preco)}
            for codigo, descricao, preco in (
                ("0001", "MAIS DEZ", "10.00"), ("0029", "IGUAL", "10.00"),
                ("0331", "MENOS DEZ", "10.00"), ("1231", "FRACIONARIO", "0.879"),
                ("1232", "SEM ORCAMENTO", "1.412"),
            )
        ])
        itens = [orcamento("1", 11.0), orcamento("29", 10.0),
                 orcamento("331", 9.0), orcamento("1231", 0.879),
                 orcamento("777", 3.0)]
        df_antes = df_oc.copy(deep=True)
        itens_antes = copy.deepcopy(itens)
        resultado = comparador.comparar_oc_orcamento(df_oc, itens)
        esperado = pd.DataFrame([
            ["1", "MAIS DEZ", 2.0, 10.0, 11.0, 9.09091, "10.00", None, "OK"],
            ["29", "IGUAL", 2.0, 10.0, 10.0, 0.0, "10.00", None, "ABAIXO"],
            ["331", "MENOS DEZ", 2.0, 10.0, 9.0, 0.0, "9.00", None, "ABAIXO"],
            ["1231", "FRACIONARIO", 2.0, 0.879, 0.879, 0.0, "0.87", None, "ABAIXO"],
            ["1232", "SEM ORCAMENTO", 2.0, 1.412, None, None, None, None, "SEM_ORC"],
            ["777", "DESCRICAO ORCAMENTO", 2.0, None, 3.0, None, None, None, "SEM_OC"],
        ], columns=COLUNAS_LEGADAS)
        self.assertEqual(list(resultado.columns), COLUNAS_LEGADAS)
        self.assertTrue(set(COLUNAS_TOTAIS).isdisjoint(resultado.columns))
        assert_frame_equal(resultado, esperado, check_exact=True)
        assert_frame_equal(df_oc, df_antes)
        self.assertEqual(itens, itens_antes)

    def test_comparador_antigo_nao_expoe_totais_mesmo_se_presentes_na_fonte(self):
        df_oc = pd.DataFrame([{
            "codigo_krona": "0331", "descricao_krona": "ADAPTADOR 1/2",
            "quantidade_final": Decimal("484"), "valor_unitario_oc": Decimal("0.652"),
            "total_documento": Decimal("315.57"), "pagina": 1,
        }])
        resultado = comparador.comparar_oc_orcamento(df_oc, [orcamento("331", 0.652)])
        self.assertEqual(list(resultado.columns), COLUNAS_LEGADAS)
        self.assertEqual(resultado.iloc[0]["PRECO_OC"], 0.652)
        self.assertEqual(resultado.iloc[0]["QUANTIDADE"], 484)
        self.assertEqual(resultado.iloc[0]["PRECO_FINAL"], "0.65")
        self.assertEqual(resultado.iloc[0]["STATUS"], "ABAIXO")

    def test_extrator_gamatec_preserva_triplet_quantidade_preco_total(self):
        for inicio in ("0331 ADAPTADOR", "0331ADAPTADOR"):
            with self.subTest(inicio=inicio):
                pdf_bytes = pdf_em_memoria(
                    inicio + " SOLD CURTO 25MM X 3/4 50 484 0,652 315,57",
                )
                resultado = extrair_orcamento_gamatec(pdf_bytes)
                self.assertEqual(resultado["total_itens"], 1)
                self.assertEqual(len(resultado["itens"]), 1)
                item = resultado["itens"][0]
                self.assertEqual(item["codigo"], "331")
                self.assertEqual(item["descricao"], "ADAPTADOR SOLD CURTO 25MM X 3/4")
                self.assertEqual(item["qtde"], 484.0)
                self.assertEqual(item["preco_orcamento"], 0.652)
                total_triplet = (Decimal(str(item["qtde"]))
                                 * Decimal(str(item["preco_orcamento"]))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                )
                self.assertEqual(total_triplet, Decimal("315.57"))


class TestExtratorOrcamentoGamatec(unittest.TestCase):
    CABECALHOS = {
        8: "Produto Emb Qtde Unitário Total IPI ICMS Ret Unit.Imp Tot.c/Imp",
        4: "Produto Emb Qtde Unitário Total",
        3: "Produto Qtde Unitário Total",
    }
    COLUNAS = {
        8: "10 1.000 2,738 2.738,00 0,00 0,00 2,738 2.738,00",
        4: "10 1.000 2,738 2.738,00",
        3: "1.000 2,738 2.738,00",
    }

    def extrair_linhas(self, *linhas, layout=None):
        cabecalho = [self.CABECALHOS[layout]] if layout is not None else []
        return extrair_orcamento_gamatec(pdf_em_memoria(
            "\n".join([*cabecalho, *linhas]),
        ))

    def verificar_itens(self, resultado, esperados):
        self.assertEqual(resultado["total_itens"], len(esperados))
        self.assertEqual(len(resultado["itens"]), len(esperados))
        for item, (codigo, descricao, quantidade, preco) in zip(
                resultado["itens"], esperados):
            self.assertEqual(item["codigo"], codigo)
            self.assertEqual(item["preco_orcamento"], preco)
            self.assertEqual(item["qtde"], quantidade)
            self.assertEqual(item["descricao"], descricao)

    def test_codigo_0647_oito_colunas_com_sem_header_e_codigo_colado(self):
        for layout in (8, None):
            for separador in (" ", ""):
                with self.subTest(layout=layout, separador=separador):
                    resultado = self.extrair_linhas(
                        f"0647{separador}LUVA ESGOTO PRIM. - DN 100 {self.COLUNAS[8]}",
                        layout=layout,
                    )
                    self.verificar_itens(resultado, [
                        ("647", "LUVA ESGOTO PRIM. - DN 100", 1000.0, 2.738),
                    ])

    def test_oito_colunas_preserva_numeros_e_medidas_da_descricao(self):
        for layout in (8, None):
            for descricao in ("LUVA DN 100", "CAIXA 100 X 52 X 40", "ADESIVO 1 KG"):
                with self.subTest(layout=layout, descricao=descricao):
                    resultado = self.extrair_linhas(
                        f"0647 {descricao} {self.COLUNAS[8]}", layout=layout,
                    )
                    self.verificar_itens(resultado, [("647", descricao, 1000.0, 2.738)])

    def test_unitario_sem_impostos_nao_e_substituido_pelo_unitario_com_ipi(self):
        for layout in (8, None):
            with self.subTest(layout=layout):
                resultado = self.extrair_linhas(
                    "0029 TUBO PVC 1 KG 1 10 57,722 577,22 9,75 0,00 63,350 633,50",
                    layout=layout,
                )
                self.verificar_itens(resultado, [("29", "TUBO PVC 1 KG", 10.0, 57.722)])
                self.assertNotEqual(resultado["itens"][0]["preco_orcamento"], 63.350)

    def test_quatro_colunas_preserva_numero_final_da_descricao(self):
        for layout in (4, None):
            for descricao in ("LUVA DN 100", "CAIXA 100 X 52 X 40", "ADESIVO 1 KG"):
                with self.subTest(layout=layout, descricao=descricao):
                    resultado = self.extrair_linhas(
                        f"0647 {descricao} {self.COLUNAS[4]}", layout=layout,
                    )
                    self.verificar_itens(resultado, [("647", descricao, 1000.0, 2.738)])

    def test_tres_colunas_com_header_preserva_numero_final_da_descricao(self):
        for separador in (" ", ""):
            for descricao in ("LUVA DN 100", "CAIXA 100 X 52 X 40", "ADESIVO 1 KG"):
                with self.subTest(separador=separador, descricao=descricao):
                    resultado = self.extrair_linhas(
                        f"0647{separador}{descricao} {self.COLUNAS[3]}", layout=3,
                    )
                    self.verificar_itens(resultado, [("647", descricao, 1000.0, 2.738)])

    def test_medidas_numericas_nao_criam_colunas_de_impostos(self):
        descricao = "CAIXA 100 150 50 20"
        resultado = self.extrair_linhas(f"0647 {descricao} {self.COLUNAS[4]}")
        self.verificar_itens(resultado, [("647", descricao, 1000.0, 2.738)])

    def test_formatos_compactos_conhecidos_sem_header(self):
        for layout in (8, 4, 3):
            for separador in (" ", ""):
                with self.subTest(layout=layout, separador=separador):
                    resultado = self.extrair_linhas(
                        f"0331{separador}ADAPTADOR 1/2 {self.COLUNAS[layout]}",
                    )
                    self.verificar_itens(resultado, [("331", "ADAPTADOR 1/2", 1000.0, 2.738)])

    def test_header_explicito_define_layout_mesmo_com_cauda_numerica_ambigua(self):
        # O mesmo sufixo tem três ou quatro colunas conforme o cabeçalho.
        linha = "0647 LUVA DN 100 10 2,738 27,38"
        for layout, descricao, quantidade in (
            (3, "LUVA DN 100", 10.0), (4, "LUVA DN", 10.0),
        ):
            with self.subTest(layout=layout):
                resultado = self.extrair_linhas(linha, layout=layout)
                self.verificar_itens(resultado, [("647", descricao, quantidade, 2.738)])

    def test_quantidades_decimais_milhares_e_totais_nao_redefinem_colunas(self):
        casos = (
            ("0,5", "2,738", "1,37", 0.5, 2.738),
            ("1.000", "2,738", "2.738,00", 1000.0, 2.738),
            ("1.000,50", "2,738", "2.739,37", 1000.5, 2.738),
            ("484", "0,652", "315,57", 484.0, 0.652),
            ("5.000", "0,879", "4.392,95", 5000.0, 0.879),
            ("750", "1,412", "1.059,10", 750.0, 1.412),
            ("1.000,50", "1.234,567", "1.234.567,89", 1000.5, 1234.567),
        )
        for layout in (8, 4, 3):
            for quantidade_br, preco_br, total_br, quantidade, preco in casos:
                for com_header in (True, False):
                    with self.subTest(layout=layout, quantidade=quantidade_br,
                                      preco=preco_br, total=total_br, com_header=com_header):
                        colunas = f"{quantidade_br} {preco_br} {total_br}"
                        if layout in (8, 4):
                            colunas = "10 " + colunas
                        if layout == 8:
                            colunas += f" 0,00 0,00 {preco_br} {total_br}"
                        # Sem cabeçalho, a cauda numérica de três colunas é inequívoca.
                        descricao = "LUVA DN 100" if com_header or layout != 3 else "LUVA 1 KG"
                        resultado = self.extrair_linhas(
                            f"0647 {descricao} {colunas}",
                            layout=layout if com_header else None,
                        )
                        self.verificar_itens(resultado, [("647", descricao, quantidade, preco)])

    def test_header_persiste_em_paginas_seguintes_sem_header(self):
        for layout in (8, 4, 3):
            with self.subTest(layout=layout):
                colunas = self.COLUNAS[layout]
                resultado = extrair_orcamento_gamatec(pdf_em_memoria(
                    self.CABECALHOS[layout] + f"\n0647 LUVA DN 100 {colunas}",
                    f"0029CAIXA 100 X 52 X 40 {colunas}",
                    f"0331 ADESIVO 1 KG {colunas}",
                    self.CABECALHOS[layout] + f"\n1232 TUBO DN 100 {colunas}",
                ))
                self.verificar_itens(resultado, [
                    ("647", "LUVA DN 100", 1000.0, 2.738),
                    ("29", "CAIXA 100 X 52 X 40", 1000.0, 2.738),
                    ("331", "ADESIVO 1 KG", 1000.0, 2.738),
                    ("1232", "TUBO DN 100", 1000.0, 2.738),
                ])

    def test_coluna_invalida_rejeita_linha_sem_preco_alternativo_ou_omissao(self):
        for layout in (8, 4, 3):
            for indice in range(layout):
                for invalido in ("INVALIDO", "1,0,00"):
                    for com_header in (True, False):
                        with self.subTest(layout=layout, coluna=indice,
                                          invalido=invalido, com_header=com_header):
                            colunas = self.COLUNAS[layout].split()
                            colunas[indice] = invalido
                            with self.assertRaises(ValueError):
                                self.extrair_linhas(
                                    f"0001 PRIMEIRO ITEM {self.COLUNAS[layout]}",
                                    "0647 LUVA ESGOTO " + " ".join(colunas),
                                    f"0331 ULTIMO ITEM {self.COLUNAS[layout]}",
                                    layout=layout if com_header else None,
                                )

    def test_linha_numerica_incompleta_com_header_nao_retorna_itens_parciais(self):
        for layout in (8, 4, 3):
            for indice in range(layout):
                with self.subTest(layout=layout, coluna_ausente=indice):
                    colunas = self.COLUNAS[layout].split()
                    del colunas[indice]
                    with self.assertRaises(ValueError):
                        self.extrair_linhas(
                            f"0001 PRIMEIRO ITEM {self.COLUNAS[layout]}",
                            "0647 LUVA ESGOTO " + " ".join(colunas),
                            f"0331 ULTIMO ITEM {self.COLUNAS[layout]}",
                            layout=layout,
                        )

    def test_linha_invalida_na_pagina_seguinte_nao_e_silenciosamente_omitida(self):
        for layout in (8, 4, 3):
            with self.subTest(layout=layout):
                colunas = self.COLUNAS[layout].split()
                colunas[-2] = "INVALIDO"
                with self.assertRaises(ValueError):
                    extrair_orcamento_gamatec(pdf_em_memoria(
                        self.CABECALHOS[layout] + f"\n0001 PRIMEIRO ITEM {self.COLUNAS[layout]}",
                        "0647 LUVA ESGOTO " + " ".join(colunas),
                        f"0331 ULTIMO ITEM {self.COLUNAS[layout]}",
                    ))


CABECALHO_MODELO = "COD KRONA DESCRIÇÃO VALOR UNIT QUANTIDADE TOTAL"
ITENS_MODELO = [
    ("0647", "LUVA ESGOTO PRIM. - DN 100", "2.226", "1000", "2226.00"),
    ("1231", "ELETRODUTO CORRUGADO 25 MT", "0.879", "500", "439.50"),
    ("0023", "TUBO PVC SOLDÁVEL - 6M - DN 20", "11.485", "24", "275.64"),
]


class TestCabecalhoQuantidade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from extrator_documento_precificado import extrair_documento_precificado
        cls.extrair = staticmethod(extrair_documento_precificado)

    def test_quantidade_aceita_caixa_e_acentos_no_cabecalho(self):
        esperado = self.extrair(pdf_em_memoria(CABECALHO + "\n" + LINHA_VALIDA))
        for cabecalho in (
            CABECALHO_MODELO, CABECALHO_MODELO.lower(),
            "cod krona Descrição valor Unit Quantidade total",
            "COD KRONA DESCRICAO VALOR UNIT QUANTIDADE TOTAL",
            "cod krona descricao valor unit quantidade total",
        ):
            with self.subTest(cabecalho=cabecalho):
                resultado = self.extrair(pdf_em_memoria(cabecalho + "\n" + LINHA_VALIDA))
                assert_frame_equal(resultado, esperado, check_exact=True)

    def test_quantidade_repetida_na_mesma_pagina_e_entre_paginas(self):
        linhas = [
            "0647 LUVA ESGOTO PRIM. - DN 100 2,226 1.000 R$ 2.226,00",
            "1231 ELETRODUTO CORRUGADO 25 MT 0,879 500 R$ 439,50",
            "0023 TUBO PVC SOLDÁVEL - 6M - DN 20 11,485 24 R$ 275,64",
        ]
        resultado = self.extrair(pdf_em_memoria(
            CABECALHO_MODELO + "\n" + linhas[0] + "\n" + CABECALHO_MODELO.lower(),
            CABECALHO_MODELO.replace("DESCRIÇÃO", "DESCRICAO") + "\n" + linhas[1],
            CABECALHO_MODELO.lower() + "\n" + linhas[2],
        ))
        self.assertEqual(len(resultado), 3)
        self.assertEqual(resultado["codigo_krona"].tolist(), ["647", "1231", "23"])
        self.assertEqual(resultado["pagina"].tolist(), [1, 2, 3])
        for registro, (_, descricao, unitario, quantidade, total) in zip(
                resultado.to_dict("records"), ITENS_MODELO):
            self.assertEqual(registro["descricao_krona"], descricao)
            for coluna, valor in (("valor_unitario_oc", unitario),
                                  ("quantidade_final", quantidade),
                                  ("total_documento", total)):
                self.assertIsInstance(registro[coluna], Decimal)
                self.assertEqual(registro[coluna], Decimal(valor))

    def test_quantidade_preserva_precos_decimais_e_total_divergente(self):
        resultado = self.extrair(pdf_em_memoria(
            CABECALHO_MODELO + "\n"
            "0647 LUVA DN 100 2,226 1.000,50 R$ 2.225,99\n"
            "1231 ELETRODUTO 25 MT 0,879 0,5 R$ 0,43\n"
            "0023 TUBO 6M DN 20 11,485 24 R$ 275,63",
        ))
        self.assertEqual(resultado["codigo_krona"].tolist(), ["647", "1231", "23"])
        for registro, (unitario, quantidade, total) in zip(
                resultado.to_dict("records"),
                (("2.226", "1000.50", "2225.99"),
                 ("0.879", "0.5", "0.43"), ("11.485", "24", "275.63"))):
            self.assertEqual(registro["valor_unitario_oc"], Decimal(unitario))
            self.assertEqual(registro["quantidade_final"], Decimal(quantidade))
            self.assertEqual(registro["total_documento"], Decimal(total))
            self.assertNotEqual(
                registro["total_documento"],
                (Decimal(unitario) * Decimal(quantidade)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                ),
            )

    def test_qnd_continua_igual_e_pode_alternar_com_quantidade(self):
        primeira = "0647 LUVA DN 100 2,226 1.000 R$ 2.225,99"
        segunda = "0023 TUBO DN 20 11,485 24 R$ 275,63"
        esperado = self.extrair(pdf_em_memoria(
            CABECALHO + "\n" + primeira,
            CABECALHO.upper() + "\n" + segunda,
        ))
        for cabecalhos in (
            (CABECALHO, CABECALHO_MODELO),
            (CABECALHO_MODELO, CABECALHO),
        ):
            with self.subTest(cabecalhos=cabecalhos):
                resultado = self.extrair(pdf_em_memoria(
                    cabecalhos[0] + "\n" + primeira,
                    cabecalhos[1] + "\n" + segunda,
                ))
                assert_frame_equal(resultado, esperado, check_exact=True)

    def test_comparacao_quantidade_equivale_a_qnd_sem_recalcular_documento(self):
        linha = "1231 ELETRODUTO CORRUGADO 25 MT 0,879 500 R$ 439,49"
        itens = [orcamento("1231", 1.0, quantidade=500)]
        esperado = comparador.comparar_documento_precificado(
            pdf_em_memoria(CABECALHO + "\n" + linha), itens,
        )
        resultado = comparador.comparar_documento_precificado(
            pdf_em_memoria(CABECALHO_MODELO + "\n" + linha), itens,
        )
        assert_frame_equal(resultado, esperado, check_exact=True)
        registro = resultado.iloc[0]
        for coluna, valor in (
            ("PRECO_OC", "0.879"), ("QUANTIDADE", "500"),
            ("TOTAL_DOCUMENTO", "439.49"), ("TOTAL_CALCULADO", "439.50"),
            ("DIFERENCA_TOTAL", "-0.01"),
        ):
            self.assertEqual(decimal_resultado(registro[coluna]), Decimal(valor))


class TestModeloPDFDocumentoPrecificado(unittest.TestCase):
    def modelo(self):
        caminho = os.path.join(BASE, "web", "modelos", "modelo_documento_precificado.pdf")
        self.assertTrue(os.path.isfile(caminho), "Modelo PDF fixo ainda ausente: " + caminho)
        with open(caminho, "rb") as arquivo:
            return arquivo.read()

    def test_pdf_valido_com_cabecalho_exato_quantidade_sem_qnd(self):
        dados = self.modelo()
        self.assertTrue(dados.startswith(b"%PDF-"))
        with fitz.open(stream=dados, filetype="pdf") as documento:
            self.assertFalse(documento.is_encrypted)
            self.assertGreater(len(documento), 0)
            texto = " ".join(" ".join(p.get_text() for p in documento).split())
        self.assertIn(CABECALHO_MODELO, texto)
        self.assertNotRegex(texto.lower(), r"\bqnd\b")

    def test_leitor_do_pdf_fixo_devolve_exatamente_os_tres_itens(self):
        from extrator_documento_precificado import extrair_documento_precificado
        resultado = extrair_documento_precificado(self.modelo())
        self.assertEqual(list(resultado.columns), COLUNAS_EXTRACAO)
        self.assertEqual(len(resultado), 3)
        self.assertEqual(resultado["codigo_krona"].tolist(), ["647", "1231", "23"])
        for registro, (codigo, descricao, unitario, quantidade, total) in zip(
                resultado.to_dict("records"), ITENS_MODELO):
            with self.subTest(codigo=codigo):
                self.assertIsInstance(registro["codigo_krona"], str)
                self.assertEqual(registro["descricao_krona"], descricao)
                self.assertIsInstance(registro["pagina"], int)
                self.assertGreaterEqual(registro["pagina"], 1)
                for coluna, valor in (("valor_unitario_oc", unitario),
                                      ("quantidade_final", quantidade),
                                      ("total_documento", total)):
                    self.assertIsInstance(registro[coluna], Decimal)
                    self.assertEqual(registro[coluna], Decimal(valor))


if __name__ == "__main__":
    unittest.main(verbosity=2)
