# -*- coding: utf-8 -*-
"""
agente_gamatec.py

AJUSTE INCREMENTAL DA CAMADA DE DECISAO DO AGENTE GAMATEC
- sem reestruturar o projeto
- sem voltar fases
- consumindo codigo normalizado vindo da percepcao
- mantendo codigo lido para debug/auditoria
- preparando a etapa seguinte de aplicar desconto e validar preco final

Premissa:
    A percepcao retorna objetos LinhaPercebida com:
        linha.codigo.valor               -> codigo lido da tela
        linha.codigo.valor_normalizado   -> codigo normalizado para comparacao
        linha.descricao.valor
        linha.ult_preco.valor
        linha.final.valor
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


# =========================
# DATACLASSES DE DECISAO
# =========================

@dataclass
class DecisaoAgente:
    acao: str
    motivo: str
    indice_linha: Optional[int] = None
    codigo_tela_lido: Optional[str] = None
    codigo_tela_normalizado: Optional[str] = None
    codigo_planejado: Optional[str] = None
    descricao_tela: Optional[str] = None
    ult_preco_tela: Optional[str] = None
    final_tela: Optional[str] = None
    desconto_alvo: Optional[float] = None
    preco_alvo: Optional[float] = None
    confianca: float = 0.0
    detalhes: Optional[Dict[str, Any]] = None


# =========================
# FUNCOES AUXILIARES
# =========================

def limpar_texto(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalizar_codigo_para_comparacao(codigo: Any) -> Optional[str]:
    if codigo is None:
        return None

    s = re.sub(r"\D", "", str(codigo))
    if not s:
        return None

    s = s.lstrip("0")
    if s == "":
        s = "0"
    return s


def parse_float_seguro(valor: Any) -> Optional[float]:
    if valor is None:
        return None

    s = str(valor).strip()
    if not s:
        return None

    s = s.replace("R$", "").replace("r$", "").replace(" ", "")
    s = s.replace("..", ".").replace(",,", ",")
    s = re.sub(r"[^0-9,.\-]", "", s)

    if not s:
        return None

    if "," in s:
        if s.count(",") > 1:
            partes = s.split(",")
            s = "".join(partes[:-1]) + "," + partes[-1]
        if "." in s:
            s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        if s.count(".") > 1:
            partes = s.split(".")
            s = "".join(partes[:-1]) + "." + partes[-1]

    try:
        return float(s)
    except Exception:
        return None


def float_para_str(v: Optional[float]) -> Optional[str]:
    if v is None:
        return None
    return f"{v:.2f}"


def obter_attr(obj: Any, nome: str, padrao: Any = None) -> Any:
    if obj is None:
        return padrao

    if isinstance(obj, dict):
        return obj.get(nome, padrao)

    return getattr(obj, nome, padrao)


# =========================
# AGENTE
# =========================

class AgenteGamatec:
    """
    Ajuste incremental do agente:
    - consome linha percebida
    - compara com item planejado
    - decide se pode agir, reler, rolar ou validar

    Estrutura esperada de item_planejado:
        {
            "codigo_krona": "340" ou "0340",
            "descricao_krona": "...",
            "preco_alvo": 12.34,
            "desconto_calculado": 8.50
        }

    Ou objeto equivalente com esses atributos.
    """

    def __init__(
        self,
        tolerancia_preco: float = 0.02,
        exigir_preco_final: bool = True,
        exigir_ult_preco: bool = False,
        debug: bool = True,
        pasta_debug: str = r"C:\robo_gamatec_oc\saida"
    ):
        self.tolerancia_preco = tolerancia_preco
        self.exigir_preco_final = exigir_preco_final
        self.exigir_ult_preco = exigir_ult_preco
        self.debug = debug
        self.pasta_debug = pasta_debug
        os.makedirs(self.pasta_debug, exist_ok=True)

    # =========================
    # NORMALIZACAO DE ENTRADA
    # =========================

    def _codigo_planejado_normalizado(self, item_planejado: Any) -> Optional[str]:
        codigo = obter_attr(item_planejado, "codigo_krona")
        if codigo is None:
            codigo = obter_attr(item_planejado, "codigo")
        return normalizar_codigo_para_comparacao(codigo)

    def _descricao_planejada(self, item_planejado: Any) -> Optional[str]:
        desc = obter_attr(item_planejado, "descricao_krona")
        if desc is None:
            desc = obter_attr(item_planejado, "descricao")
        return limpar_texto(desc) or None

    def _preco_alvo(self, item_planejado: Any) -> Optional[float]:
        preco = obter_attr(item_planejado, "preco_alvo")
        if preco is None:
            preco = obter_attr(item_planejado, "valor_unitario")
        return parse_float_seguro(preco)

    def _desconto_alvo(self, item_planejado: Any) -> Optional[float]:
        desconto = obter_attr(item_planejado, "desconto_calculado")
        if desconto is None:
            desconto = obter_attr(item_planejado, "percentual_desconto")
        return parse_float_seguro(desconto)

    # =========================
    # EXTRACAO DA LINHA PERCEBIDA
    # =========================

    def _extrair_dados_linha(self, linha: Any) -> Dict[str, Any]:
        codigo = obter_attr(linha, "codigo")
        descricao = obter_attr(linha, "descricao")
        ult_preco = obter_attr(linha, "ult_preco")
        final = obter_attr(linha, "final")

        dados = {
            "indice_linha": obter_attr(linha, "indice_linha"),
            "codigo_tela_lido": obter_attr(codigo, "valor"),
            "codigo_tela_normalizado": (
                obter_attr(codigo, "valor_normalizado")
                or normalizar_codigo_para_comparacao(obter_attr(codigo, "valor"))
            ),
            "codigo_valido": bool(obter_attr(codigo, "valido", False)),
            "descricao_tela": obter_attr(descricao, "valor"),
            "descricao_valida": bool(obter_attr(descricao, "valido", False)),
            "ult_preco_tela": obter_attr(ult_preco, "valor"),
            "ult_preco_valido": bool(obter_attr(ult_preco, "valido", False)),
            "final_tela": obter_attr(final, "valor"),
            "final_valido": bool(obter_attr(final, "valido", False)),
            "confianca_codigo": float(obter_attr(codigo, "confianca", 0.0) or 0.0),
            "confianca_descricao": float(obter_attr(descricao, "confianca", 0.0) or 0.0),
            "confianca_ult_preco": float(obter_attr(ult_preco, "confianca", 0.0) or 0.0),
            "confianca_final": float(obter_attr(final, "confianca", 0.0) or 0.0),
        }

        dados["ult_preco_float"] = parse_float_seguro(dados["ult_preco_tela"])
        dados["final_float"] = parse_float_seguro(dados["final_tela"])

        return dados

    # =========================
    # VALIDACAO DA PERCEPCAO
    # =========================

    def _validar_percepcao_minima(self, dados_linha: Dict[str, Any]) -> Optional[DecisaoAgente]:
        if not dados_linha["codigo_valido"] or not dados_linha["codigo_tela_normalizado"]:
            return DecisaoAgente(
                acao="RELER_CODIGO",
                motivo="codigo_tela_invalido_ou_ausente",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                confianca=dados_linha["confianca_codigo"],
                detalhes=dados_linha
            )

        if self.exigir_preco_final and dados_linha["final_float"] is None:
            return DecisaoAgente(
                acao="RELER_PRECO_FINAL",
                motivo="preco_final_invalido_ou_ausente",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                confianca=dados_linha["confianca_final"],
                detalhes=dados_linha
            )

        if self.exigir_ult_preco and dados_linha["ult_preco_float"] is None:
            return DecisaoAgente(
                acao="RELER_ULT_PRECO",
                motivo="ult_preco_invalido_ou_ausente",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                confianca=dados_linha["confianca_ult_preco"],
                detalhes=dados_linha
            )

        return None

    # =========================
    # COMPARACAO COM O PLANEJADO
    # =========================

    def _comparar_item_planejado(self, dados_linha: Dict[str, Any], item_planejado: Any) -> Tuple[bool, Dict[str, Any]]:
        codigo_tela = dados_linha["codigo_tela_normalizado"]
        codigo_planejado = self._codigo_planejado_normalizado(item_planejado)

        detalhes = {
            "codigo_tela_lido": dados_linha["codigo_tela_lido"],
            "codigo_tela_normalizado": codigo_tela,
            "codigo_planejado_normalizado": codigo_planejado,
            "descricao_tela": dados_linha["descricao_tela"],
            "descricao_planejada": self._descricao_planejada(item_planejado),
            "preco_final_tela": dados_linha["final_float"],
            "preco_alvo": self._preco_alvo(item_planejado),
            "desconto_alvo": self._desconto_alvo(item_planejado),
        }

        if not codigo_tela or not codigo_planejado:
            return False, detalhes

        return codigo_tela == codigo_planejado, detalhes

    # =========================
    # DECISAO PRINCIPAL POR LINHA
    # =========================

    def decidir_proxima_acao_para_linha(self, linha: Any, item_planejado: Any) -> DecisaoAgente:
        dados_linha = self._extrair_dados_linha(linha)

        # 1. validar leitura minima
        decisao_percepcao = self._validar_percepcao_minima(dados_linha)
        if decisao_percepcao is not None:
            return decisao_percepcao

        # 2. comparar codigo da tela x codigo planejado usando normalizado
        bateu_codigo, detalhes_comp = self._comparar_item_planejado(dados_linha, item_planejado)

        codigo_planejado = detalhes_comp["codigo_planejado_normalizado"]
        preco_alvo = detalhes_comp["preco_alvo"]
        desconto_alvo = detalhes_comp["desconto_alvo"]

        if not bateu_codigo:
            return DecisaoAgente(
                acao="AVANCAR_PROXIMA_LINHA",
                motivo="codigo_tela_diferente_do_planejado",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=dados_linha["confianca_codigo"],
                detalhes=detalhes_comp
            )

        # 3. codigo bateu: agora decidir agir/validar
        final_tela = dados_linha["final_float"]

        if preco_alvo is None:
            return DecisaoAgente(
                acao="VALIDAR_MANUALMENTE",
                motivo="item_planejado_sem_preco_alvo",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=90.0,
                detalhes=detalhes_comp
            )

        if final_tela is None:
            return DecisaoAgente(
                acao="RELER_PRECO_FINAL",
                motivo="codigo_bateu_mas_final_nao_foi_lido",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=dados_linha["confianca_final"],
                detalhes=detalhes_comp
            )

        # 4. validar se ja esta no alvo
        diferenca = final_tela - preco_alvo

        if final_tela <= (preco_alvo + self.tolerancia_preco):
            return DecisaoAgente(
                acao="ITEM_OK_VALIDAR_E_SEGUIR",
                motivo="codigo_bateu_e_preco_final_ja_esta_no_alvo_ou_abaixo",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=float_para_str(final_tela),
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=95.0,
                detalhes={
                    **detalhes_comp,
                    "diferenca_final_menos_alvo": round(diferenca, 4)
                }
            )

        # 5. precisa aplicar desconto
        if desconto_alvo is None:
            return DecisaoAgente(
                acao="CALCULAR_DESCONTO_OU_VALIDAR",
                motivo="codigo_bateu_mas_nao_ha_desconto_alvo_disponivel",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=float_para_str(final_tela),
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=92.0,
                detalhes={
                    **detalhes_comp,
                    "diferenca_final_menos_alvo": round(diferenca, 4)
                }
            )

        return DecisaoAgente(
            acao="APLICAR_DESCONTO",
            motivo="codigo_bateu_e_preco_final_esta_acima_do_alvo",
            indice_linha=dados_linha["indice_linha"],
            codigo_tela_lido=dados_linha["codigo_tela_lido"],
            codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
            codigo_planejado=codigo_planejado,
            descricao_tela=dados_linha["descricao_tela"],
            ult_preco_tela=dados_linha["ult_preco_tela"],
            final_tela=float_para_str(final_tela),
            preco_alvo=preco_alvo,
            desconto_alvo=desconto_alvo,
            confianca=98.0,
            detalhes={
                **detalhes_comp,
                "diferenca_final_menos_alvo": round(diferenca, 4)
            }
        )

    # =========================
    # BUSCA DO ITEM CERTO NAS LINHAS VISIVEIS
    # =========================

    def decidir_em_grade_visivel(self, linhas_visiveis: List[Any], item_planejado: Any) -> DecisaoAgente:
        """
        Percorre as linhas atualmente visiveis e decide:
        - qual linha corresponde ao item planejado
        - se deve agir, reler, seguir ou rolar
        """
        melhor_releitura: Optional[DecisaoAgente] = None

        for linha in linhas_visiveis:
            decisao = self.decidir_proxima_acao_para_linha(linha, item_planejado)

            if decisao.acao in ("APLICAR_DESCONTO", "ITEM_OK_VALIDAR_E_SEGUIR"):
                return decisao

            if decisao.acao in ("RELER_CODIGO", "RELER_PRECO_FINAL", "RELER_ULT_PRECO"):
                if melhor_releitura is None or decisao.confianca > melhor_releitura.confianca:
                    melhor_releitura = decisao

        if melhor_releitura is not None:
            return melhor_releitura

        return DecisaoAgente(
            acao="SCROLL_PROXIMA_PAGINA",
            motivo="item_planejado_nao_encontrado_nas_linhas_visiveis",
            codigo_planejado=self._codigo_planejado_normalizado(item_planejado),
            preco_alvo=self._preco_alvo(item_planejado),
            desconto_alvo=self._desconto_alvo(item_planejado),
            confianca=80.0,
            detalhes={
                "codigo_planejado_normalizado": self._codigo_planejado_normalizado(item_planejado),
                "descricao_planejada": self._descricao_planejada(item_planejado),
            }
        )

    # =========================
    # VALIDACAO POS-ACAO
    # =========================

    def validar_resultado_pos_desconto(self, linha_repercebida: Any, item_planejado: Any) -> DecisaoAgente:
        """
        Rele a linha depois da aplicacao do desconto e valida o preco final.
        """
        dados_linha = self._extrair_dados_linha(linha_repercebida)
        preco_alvo = self._preco_alvo(item_planejado)
        desconto_alvo = self._desconto_alvo(item_planejado)
        codigo_planejado = self._codigo_planejado_normalizado(item_planejado)

        decisao_percepcao = self._validar_percepcao_minima(dados_linha)
        if decisao_percepcao is not None:
            decisao_percepcao.motivo = f"pos_desconto_{decisao_percepcao.motivo}"
            decisao_percepcao.codigo_planejado = codigo_planejado
            decisao_percepcao.preco_alvo = preco_alvo
            decisao_percepcao.desconto_alvo = desconto_alvo
            return decisao_percepcao

        if dados_linha["codigo_tela_normalizado"] != codigo_planejado:
            return DecisaoAgente(
                acao="VALIDAR_MANUALMENTE",
                motivo="pos_desconto_codigo_na_tela_nao_confere",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=70.0,
                detalhes=dados_linha
            )

        final_tela = dados_linha["final_float"]
        if final_tela is None or preco_alvo is None:
            return DecisaoAgente(
                acao="RELER_PRECO_FINAL",
                motivo="pos_desconto_sem_preco_final_ou_preco_alvo",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=dados_linha["final_tela"],
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=70.0,
                detalhes=dados_linha
            )

        diferenca = final_tela - preco_alvo

        if final_tela <= (preco_alvo + self.tolerancia_preco):
            return DecisaoAgente(
                acao="SUCESSO_VALIDADO",
                motivo="pos_desconto_preco_final_validado",
                indice_linha=dados_linha["indice_linha"],
                codigo_tela_lido=dados_linha["codigo_tela_lido"],
                codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
                codigo_planejado=codigo_planejado,
                descricao_tela=dados_linha["descricao_tela"],
                ult_preco_tela=dados_linha["ult_preco_tela"],
                final_tela=float_para_str(final_tela),
                preco_alvo=preco_alvo,
                desconto_alvo=desconto_alvo,
                confianca=99.0,
                detalhes={
                    **dados_linha,
                    "diferenca_final_menos_alvo": round(diferenca, 4)
                }
            )

        return DecisaoAgente(
            acao="REAPLICAR_OU_VALIDAR",
            motivo="pos_desconto_preco_final_ainda_acima_do_alvo",
            indice_linha=dados_linha["indice_linha"],
            codigo_tela_lido=dados_linha["codigo_tela_lido"],
            codigo_tela_normalizado=dados_linha["codigo_tela_normalizado"],
            codigo_planejado=codigo_planejado,
            descricao_tela=dados_linha["descricao_tela"],
            ult_preco_tela=dados_linha["ult_preco_tela"],
            final_tela=float_para_str(final_tela),
            preco_alvo=preco_alvo,
            desconto_alvo=desconto_alvo,
            confianca=85.0,
            detalhes={
                **dados_linha,
                "diferenca_final_menos_alvo": round(diferenca, 4)
            }
        )

    # =========================
    # DEBUG
    # =========================

    def salvar_decisao_json(self, decisao: DecisaoAgente, nome_arquivo: str = "decisao_agente_gamatec.json") -> str:
        caminho = os.path.join(self.pasta_debug, nome_arquivo)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(asdict(decisao), f, ensure_ascii=False, indent=2)
        return caminho


# =========================
# TESTE LOCAL
# =========================

if __name__ == "__main__":
    class CampoFake:
        def __init__(self, valor, valor_normalizado=None, valido=True, confianca=95.0):
            self.valor = valor
            self.valor_normalizado = valor_normalizado
            self.valido = valido
            self.confianca = confianca

    class LinhaFake:
        def __init__(self):
            self.indice_linha = 3
            self.codigo = CampoFake("0340", "340", True, 98.0)
            self.descricao = CampoFake("ADAPTADOR PVC SOLD", "ADAPTADOR PVC SOLD", True, 80.0)
            self.ult_preco = CampoFake("15,90", "15.90", True, 88.0)
            self.final = CampoFake("14,20", "14.20", True, 90.0)

    item_planejado = {
        "codigo_krona": "340",
        "descricao_krona": "ADAPTADOR PVC SOLDAVEL",
        "preco_alvo": 12.50,
        "desconto_calculado": 10.00
    }

    agente = AgenteGamatec(
        tolerancia_preco=0.02,
        exigir_preco_final=True,
        exigir_ult_preco=False,
        debug=True
    )

    linha = LinhaFake()

    decisao = agente.decidir_proxima_acao_para_linha(linha, item_planejado)
    print("\n[DECISAO PRINCIPAL]")
    print(json.dumps(asdict(decisao), ensure_ascii=False, indent=2))

    caminho = agente.salvar_decisao_json(decisao, "teste_decisao_agente.json")
    print(f"\nJSON salvo em: {caminho}")

    decisao_pos = agente.validar_resultado_pos_desconto(linha, item_planejado)
    print("\n[VALIDACAO POS-DESCONTO]")
    print(json.dumps(asdict(decisao_pos), ensure_ascii=False, indent=2))