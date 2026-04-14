# -*- coding: utf-8 -*-
"""
orquestrador_agente_gamatec.py

AJUSTE INCREMENTAL DO ORQUESTRADOR DO AGENTE GAMATEC
- sem reestruturacao radical
- sem voltar fases
- consumindo a nova percepcao
- consumindo a nova decisao do agente
- fluxo: perceber -> decidir -> agir -> validar
- aplicacao real de desconto via UI plugada

OBS:
- este ajuste assume que voce ja calibrou a coordenada do campo % Desc da primeira linha
- a linha alvo eh calculada por indice_linha + passo_linha
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

try:
    import pyautogui
except Exception:
    pyautogui = None

from percepcao_gamatec import PercepcaoGamatec, carregar_calibracao
from agente_gamatec import AgenteGamatec, DecisaoAgente
from config import BASE_DIR


# =========================
# DATA CLASSES
# =========================

@dataclass
class ResultadoOrquestracao:
    sucesso: bool
    status: str
    motivo: str
    item_indice: Optional[int] = None
    codigo_planejado: Optional[str] = None
    codigo_tela_lido: Optional[str] = None
    codigo_tela_normalizado: Optional[str] = None
    desconto_aplicado: Optional[float] = None
    preco_alvo: Optional[float] = None
    preco_final_lido: Optional[str] = None
    tentativas: int = 0
    scrolls: int = 0
    releituras: int = 0
    detalhes: Optional[Dict[str, Any]] = None


# =========================
# ESTADO LOCAL DO CICLO
# =========================

class EstadoExecucaoLocal:
    def __init__(self) -> None:
        self.item_atual_idx: int = 0
        self.scrolls_realizados: int = 0
        self.releituras_realizadas: int = 0
        self.ciclos_realizados: int = 0
        self.historico: List[Dict[str, Any]] = []

    def registrar(self, evento: str, dados: Optional[Dict[str, Any]] = None) -> None:
        self.historico.append({
            "ts": time.time(),
            "evento": evento,
            "dados": dados or {}
        })


# =========================
# ORQUESTRADOR
# =========================

class OrquestradorAgenteGamatec:
    def __init__(
        self,
        calibracao: Dict[str, Any],
        debug: bool = True,
        pasta_debug: str = None,
        quantidade_linhas_visiveis: int = 12,
        max_scrolls_por_item: int = 20,
        max_releituras_por_item: int = 5,
        pausa_curta: float = 0.15,
        pausa_media: float = 0.35,
        pausa_longa: float = 0.60,
    ):
        self.debug = debug
        self.pasta_debug = pasta_debug if pasta_debug is not None else os.path.join(BASE_DIR, "saida")
        os.makedirs(self.pasta_debug, exist_ok=True)

        self.quantidade_linhas_visiveis = quantidade_linhas_visiveis
        self.max_scrolls_por_item = max_scrolls_por_item
        self.max_releituras_por_item = max_releituras_por_item
        self.pausa_curta = pausa_curta
        self.pausa_media = pausa_media
        self.pausa_longa = pausa_longa

        self.percepcao = PercepcaoGamatec(
            calibracao=calibracao,
            debug=debug,
            salvar_crops_debug=True
        )

        self.agente = AgenteGamatec(
            tolerancia_preco=0.02,
            exigir_preco_final=True,
            exigir_ult_preco=False,
            debug=debug,
            pasta_debug=pasta_debug
        )

        self.estado = EstadoExecucaoLocal()
        self.cal = dict(calibracao)

        # scroll
        self.x_area_scroll = int(self.cal.get("x_area_scroll", self.percepcao.x_codigo))
        self.y_area_scroll = int(self.cal.get("y_area_scroll", self.percepcao.y_codigo_linha2))
        self.scroll_click_antes = bool(self.cal.get("scroll_click_antes", False))
        self.scroll_quantidade = int(self.cal.get("scroll_quantidade", -650))

        # campo % desc
        self.x_desc_campo = int(self.cal.get("x_desc_campo", self.cal.get("x_percentual_desc", 0)))
        self.y_desc_campo_linha1 = int(self.cal.get("y_desc_campo_linha1", self.cal.get("y_percentual_desc_linha1", 0)))

        # foco auxiliar
        self.x_codigo_click = int(self.cal.get("x_codigo_click", self.percepcao.x_codigo + 15))
        self.x_desc_click = int(self.cal.get("x_desc_click", self.percepcao.x_desc + 20))

        # formato desconto
        self.separador_decimal_desconto = str(self.cal.get("separador_decimal_desconto", ",")).strip() or ","
        self.casas_decimais_desconto = int(self.cal.get("casas_decimais_desconto", 2))
        self.usar_ctrl_a_para_limpar = bool(self.cal.get("usar_ctrl_a_para_limpar", True))
        self.confirmar_com_enter = bool(self.cal.get("confirmar_com_enter", True))
        self.duplo_clique_campo_desc = bool(self.cal.get("duplo_clique_campo_desc", True))

        # tentativas leves
        self.max_tentativas_aplicar_desconto = int(self.cal.get("max_tentativas_aplicar_desconto", 2))

        if pyautogui is not None:
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.02

    # =========================
    # DEBUG / LOG
    # =========================

    def _salvar_json(self, nome_arquivo: str, payload: Any) -> str:
        caminho = os.path.join(self.pasta_debug, nome_arquivo)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return caminho

    def _log(self, msg: str, dados: Optional[Dict[str, Any]] = None) -> None:
        self.estado.registrar(msg, dados)
        if self.debug:
            print(msg)
            if dados:
                try:
                    print(json.dumps(dados, ensure_ascii=False, indent=2))
                except Exception:
                    print(dados)

    # =========================
    # HELPERS UI
    # =========================

    def _formatar_desconto_para_digitacao(self, desconto: float) -> str:
        txt = f"{float(desconto):.{self.casas_decimais_desconto}f}"
        if self.separador_decimal_desconto == ",":
            txt = txt.replace(".", ",")
        else:
            txt = txt.replace(",", ".")
        return txt

    def _calcular_y_linha_desc(self, indice_linha: int) -> int:
        """
        indice_linha eh 1-based vindo da percepcao/agente
        """
        deslocamento = max(0, indice_linha - 1) * self.percepcao.passo_linha
        return int(self.y_desc_campo_linha1 + deslocamento)

    def _clicar_em(self, x: int, y: int, duplo: bool = False) -> None:
        if pyautogui is None:
            return

        pyautogui.moveTo(x, y, duration=0.05)
        if duplo:
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.click(x, y)

    def _limpar_campo(self) -> None:
        if pyautogui is None:
            return

        if self.usar_ctrl_a_para_limpar:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(self.pausa_curta / 2)

        pyautogui.press("backspace")
        time.sleep(self.pausa_curta / 2)

        # limpeza extra leve
        pyautogui.press("delete")
        time.sleep(self.pausa_curta / 2)

    def _digitar_texto(self, texto: str) -> None:
        if pyautogui is None:
            return
        pyautogui.write(texto, interval=0.03)

    def _confirmar_digitacao(self) -> None:
        if pyautogui is None:
            return
        if self.confirmar_com_enter:
            pyautogui.press("enter")
            time.sleep(self.pausa_media)

    # =========================
    # LEITURA DA TELA
    # =========================

    def perceber_grade_visivel(self) -> List[Any]:
        self._log("[ORQUESTRADOR] Percebendo grade visivel...")
        linhas = self.percepcao.ler_grade(
            quantidade_linhas=self.quantidade_linhas_visiveis,
            auto_ancorar_primeira_linha=True
        )
        self.percepcao.salvar_json_debug(linhas, "orquestrador_leitura_grade.json")
        return linhas

    def reler_grade_visivel(self) -> List[Any]:
        self.estado.releituras_realizadas += 1
        time.sleep(self.pausa_curta)
        self._log("[ORQUESTRADOR] Releitura da grade visivel...", {
            "releituras": self.estado.releituras_realizadas
        })
        return self.perceber_grade_visivel()

    # =========================
    # EXECUCAO DE ACOES NA UI
    # =========================

    def executar_scroll_proxima_pagina(self) -> None:
        self.estado.scrolls_realizados += 1

        self._log("[ORQUESTRADOR] Executando scroll...", {
            "scrolls": self.estado.scrolls_realizados
        })

        if pyautogui is None:
            time.sleep(self.pausa_media)
            return

        try:
            if self.scroll_click_antes:
                pyautogui.click(self.x_area_scroll, self.y_area_scroll)
                time.sleep(self.pausa_curta)

            pyautogui.moveTo(self.x_area_scroll, self.y_area_scroll, duration=0.05)
            pyautogui.scroll(self.scroll_quantidade)
            time.sleep(self.pausa_media)
        except Exception as e:
            self._log("[ORQUESTRADOR] Falha ao executar scroll", {"erro": str(e)})
            time.sleep(self.pausa_media)

    def aplicar_desconto_na_linha(self, decisao: DecisaoAgente) -> bool:
        """
        Aplicacao real via UI no campo % Desc da linha alvo.
        """
        self._log("[ORQUESTRADOR] Solicitação de aplicação de desconto", {
            "indice_linha": decisao.indice_linha,
            "codigo_tela_lido": decisao.codigo_tela_lido,
            "codigo_tela_normalizado": decisao.codigo_tela_normalizado,
            "codigo_planejado": decisao.codigo_planejado,
            "desconto_alvo": decisao.desconto_alvo,
            "preco_alvo": decisao.preco_alvo,
        })

        if pyautogui is None:
            self._log("[ORQUESTRADOR] pyautogui indisponível")
            return False

        if decisao.indice_linha is None:
            self._log("[ORQUESTRADOR] indice_linha ausente para aplicar desconto")
            return False

        if decisao.desconto_alvo is None:
            self._log("[ORQUESTRADOR] desconto_alvo ausente")
            return False

        if self.x_desc_campo <= 0 or self.y_desc_campo_linha1 <= 0:
            self._log("[ORQUESTRADOR] coordenadas do campo % Desc nao calibradas", {
                "x_desc_campo": self.x_desc_campo,
                "y_desc_campo_linha1": self.y_desc_campo_linha1
            })
            return False

        desconto_txt = self._formatar_desconto_para_digitacao(decisao.desconto_alvo)
        y_alvo = self._calcular_y_linha_desc(decisao.indice_linha)

        self._log("[ORQUESTRADOR] Aplicando desconto na UI", {
            "x_desc_campo": self.x_desc_campo,
            "y_alvo": y_alvo,
            "desconto_txt": desconto_txt,
            "passo_linha": self.percepcao.passo_linha
        })

        for tentativa in range(1, self.max_tentativas_aplicar_desconto + 1):
            try:
                # 1. foco inicial leve na linha
                self._clicar_em(self.x_codigo_click, y_alvo, duplo=False)
                time.sleep(self.pausa_curta)

                # 2. clicar no campo % Desc
                self._clicar_em(self.x_desc_campo, y_alvo, duplo=self.duplo_clique_campo_desc)
                time.sleep(self.pausa_curta)

                # 3. reforco de foco
                self._clicar_em(self.x_desc_campo, y_alvo, duplo=False)
                time.sleep(self.pausa_curta)

                # 4. limpar campo
                self._limpar_campo()

                # 5. digitar desconto
                self._digitar_texto(desconto_txt)
                time.sleep(self.pausa_curta)

                # 6. confirmar
                self._confirmar_digitacao()

                self._log("[ORQUESTRADOR] Desconto digitado com sucesso", {
                    "tentativa": tentativa,
                    "indice_linha": decisao.indice_linha,
                    "desconto_txt": desconto_txt
                })
                return True

            except Exception as e:
                self._log("[ORQUESTRADOR] Falha na aplicacao do desconto", {
                    "tentativa": tentativa,
                    "erro": str(e)
                })
                time.sleep(self.pausa_media)

        return False

    # =========================
    # TRATAMENTO DAS DECISOES
    # =========================

    def tratar_decisao(
        self,
        decisao: DecisaoAgente,
        item_planejado: Any,
    ) -> ResultadoOrquestracao:
        self._log("[ORQUESTRADOR] Decisão recebida", asdict(decisao))

        if decisao.acao == "RELER_CODIGO":
            return ResultadoOrquestracao(
                sucesso=False,
                status="RELER",
                motivo=decisao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=decisao.codigo_planejado,
                codigo_tela_lido=decisao.codigo_tela_lido,
                codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                preco_alvo=decisao.preco_alvo,
                preco_final_lido=decisao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(decisao)
            )

        if decisao.acao == "RELER_PRECO_FINAL":
            return ResultadoOrquestracao(
                sucesso=False,
                status="RELER",
                motivo=decisao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=decisao.codigo_planejado,
                codigo_tela_lido=decisao.codigo_tela_lido,
                codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                preco_alvo=decisao.preco_alvo,
                preco_final_lido=decisao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(decisao)
            )

        if decisao.acao == "RELER_ULT_PRECO":
            return ResultadoOrquestracao(
                sucesso=False,
                status="RELER",
                motivo=decisao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=decisao.codigo_planejado,
                codigo_tela_lido=decisao.codigo_tela_lido,
                codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                preco_alvo=decisao.preco_alvo,
                preco_final_lido=decisao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(decisao)
            )

        if decisao.acao == "ITEM_OK_VALIDAR_E_SEGUIR":
            return ResultadoOrquestracao(
                sucesso=True,
                status="ITEM_OK",
                motivo=decisao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=decisao.codigo_planejado,
                codigo_tela_lido=decisao.codigo_tela_lido,
                codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                desconto_aplicado=decisao.desconto_alvo,
                preco_alvo=decisao.preco_alvo,
                preco_final_lido=decisao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(decisao)
            )

        if decisao.acao == "APLICAR_DESCONTO":
            ok = self.aplicar_desconto_na_linha(decisao)

            if not ok:
                return ResultadoOrquestracao(
                    sucesso=False,
                    status="FALHA_APLICACAO",
                    motivo="falha_ao_aplicar_desconto",
                    item_indice=self.estado.item_atual_idx,
                    codigo_planejado=decisao.codigo_planejado,
                    codigo_tela_lido=decisao.codigo_tela_lido,
                    codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                    desconto_aplicado=decisao.desconto_alvo,
                    preco_alvo=decisao.preco_alvo,
                    preco_final_lido=decisao.final_tela,
                    tentativas=self.estado.ciclos_realizados,
                    scrolls=self.estado.scrolls_realizados,
                    releituras=self.estado.releituras_realizadas,
                    detalhes=asdict(decisao)
                )

            time.sleep(self.pausa_longa)
            linhas_repercebidas = self.reler_grade_visivel()

            linha_mesmo_indice = None
            for linha in linhas_repercebidas:
                if getattr(linha, "indice_linha", None) == decisao.indice_linha:
                    linha_mesmo_indice = linha
                    break

            if linha_mesmo_indice is None:
                return ResultadoOrquestracao(
                    sucesso=False,
                    status="REVALIDAR",
                    motivo="linha_pos_desconto_nao_reencontrada_na_releitura",
                    item_indice=self.estado.item_atual_idx,
                    codigo_planejado=decisao.codigo_planejado,
                    codigo_tela_lido=decisao.codigo_tela_lido,
                    codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                    desconto_aplicado=decisao.desconto_alvo,
                    preco_alvo=decisao.preco_alvo,
                    preco_final_lido=None,
                    tentativas=self.estado.ciclos_realizados,
                    scrolls=self.estado.scrolls_realizados,
                    releituras=self.estado.releituras_realizadas,
                    detalhes=asdict(decisao)
                )

            validacao = self.agente.validar_resultado_pos_desconto(
                linha_repercebida=linha_mesmo_indice,
                item_planejado=item_planejado
            )

            self._log("[ORQUESTRADOR] Validação pós-desconto", asdict(validacao))

            return ResultadoOrquestracao(
                sucesso=(validacao.acao == "SUCESSO_VALIDADO"),
                status=validacao.acao,
                motivo=validacao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=validacao.codigo_planejado,
                codigo_tela_lido=validacao.codigo_tela_lido,
                codigo_tela_normalizado=validacao.codigo_tela_normalizado,
                desconto_aplicado=validacao.desconto_alvo,
                preco_alvo=validacao.preco_alvo,
                preco_final_lido=validacao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(validacao)
            )

        if decisao.acao == "SCROLL_PROXIMA_PAGINA":
            return ResultadoOrquestracao(
                sucesso=False,
                status="SCROLL",
                motivo=decisao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=decisao.codigo_planejado,
                codigo_tela_lido=decisao.codigo_tela_lido,
                codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                desconto_aplicado=decisao.desconto_alvo,
                preco_alvo=decisao.preco_alvo,
                preco_final_lido=decisao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(decisao)
            )

        if decisao.acao == "VALIDAR_MANUALMENTE":
            return ResultadoOrquestracao(
                sucesso=False,
                status="VALIDAR_MANUALMENTE",
                motivo=decisao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=decisao.codigo_planejado,
                codigo_tela_lido=decisao.codigo_tela_lido,
                codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                desconto_aplicado=decisao.desconto_alvo,
                preco_alvo=decisao.preco_alvo,
                preco_final_lido=decisao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(decisao)
            )

        if decisao.acao == "REAPLICAR_OU_VALIDAR":
            return ResultadoOrquestracao(
                sucesso=False,
                status="REAPLICAR_OU_VALIDAR",
                motivo=decisao.motivo,
                item_indice=self.estado.item_atual_idx,
                codigo_planejado=decisao.codigo_planejado,
                codigo_tela_lido=decisao.codigo_tela_lido,
                codigo_tela_normalizado=decisao.codigo_tela_normalizado,
                desconto_aplicado=decisao.desconto_alvo,
                preco_alvo=decisao.preco_alvo,
                preco_final_lido=decisao.final_tela,
                tentativas=self.estado.ciclos_realizados,
                scrolls=self.estado.scrolls_realizados,
                releituras=self.estado.releituras_realizadas,
                detalhes=asdict(decisao)
            )

        return ResultadoOrquestracao(
            sucesso=False,
            status="ACAO_NAO_TRATADA",
            motivo=f"acao_nao_tratada:{decisao.acao}",
            item_indice=self.estado.item_atual_idx,
            codigo_planejado=decisao.codigo_planejado,
            codigo_tela_lido=decisao.codigo_tela_lido,
            codigo_tela_normalizado=decisao.codigo_tela_normalizado,
            desconto_aplicado=decisao.desconto_alvo,
            preco_alvo=decisao.preco_alvo,
            preco_final_lido=decisao.final_tela,
            tentativas=self.estado.ciclos_realizados,
            scrolls=self.estado.scrolls_realizados,
            releituras=self.estado.releituras_realizadas,
            detalhes=asdict(decisao)
        )

    # =========================
    # CICLO POR ITEM
    # =========================

    def processar_item_planejado(
        self,
        item_planejado: Any,
        item_idx: int = 0
    ) -> ResultadoOrquestracao:
        self.estado.item_atual_idx = item_idx
        self.estado.scrolls_realizados = 0
        self.estado.releituras_realizadas = 0
        self.estado.ciclos_realizados = 0

        self._log("[ORQUESTRADOR] Iniciando processamento do item", {
            "item_idx": item_idx,
            "item_planejado": item_planejado
        })

        while True:
            self.estado.ciclos_realizados += 1

            if self.estado.scrolls_realizados > self.max_scrolls_por_item:
                resultado = ResultadoOrquestracao(
                    sucesso=False,
                    status="LIMITE_SCROLL",
                    motivo="limite_de_scrolls_excedido",
                    item_indice=item_idx,
                    codigo_planejado=self.agente._codigo_planejado_normalizado(item_planejado),
                    tentativas=self.estado.ciclos_realizados,
                    scrolls=self.estado.scrolls_realizados,
                    releituras=self.estado.releituras_realizadas,
                    detalhes={"item_planejado": item_planejado}
                )
                self._persistir_resultado(item_idx, resultado)
                return resultado

            if self.estado.releituras_realizadas > self.max_releituras_por_item:
                resultado = ResultadoOrquestracao(
                    sucesso=False,
                    status="LIMITE_RELEITURA",
                    motivo="limite_de_releituras_excedido",
                    item_indice=item_idx,
                    codigo_planejado=self.agente._codigo_planejado_normalizado(item_planejado),
                    tentativas=self.estado.ciclos_realizados,
                    scrolls=self.estado.scrolls_realizados,
                    releituras=self.estado.releituras_realizadas,
                    detalhes={"item_planejado": item_planejado}
                )
                self._persistir_resultado(item_idx, resultado)
                return resultado

            linhas_visiveis = self.perceber_grade_visivel()
            decisao = self.agente.decidir_em_grade_visivel(linhas_visiveis, item_planejado)
            resultado = self.tratar_decisao(decisao, item_planejado)

            self._persistir_decisao(item_idx, decisao)
            self._persistir_resultado(item_idx, resultado)

            if resultado.status == "RELER":
                self.reler_grade_visivel()
                continue

            if resultado.status == "SCROLL":
                self.executar_scroll_proxima_pagina()
                continue

            return resultado

    # =========================
    # LOTE DE ITENS
    # =========================

    def processar_lote(self, itens_planejados: List[Any]) -> List[ResultadoOrquestracao]:
        resultados: List[ResultadoOrquestracao] = []

        for idx, item in enumerate(itens_planejados, start=1):
            resultado = self.processar_item_planejado(item, item_idx=idx)
            resultados.append(resultado)

            self._log("[ORQUESTRADOR] Resultado do item", asdict(resultado))

        self._salvar_json("resultado_lote_orquestrador.json", [asdict(r) for r in resultados])
        self._salvar_json("historico_orquestrador.json", self.estado.historico)

        return resultados

    # =========================
    # PERSISTENCIA DEBUG
    # =========================

    def _persistir_decisao(self, item_idx: int, decisao: DecisaoAgente) -> None:
        nome = f"decisao_item_{item_idx:03d}.json"
        self._salvar_json(nome, asdict(decisao))

    def _persistir_resultado(self, item_idx: int, resultado: ResultadoOrquestracao) -> None:
        nome = f"resultado_item_{item_idx:03d}.json"
        self._salvar_json(nome, asdict(resultado))


# =========================
# TESTE LOCAL
# =========================

if __name__ == "__main__":
    caminho_calibracao = os.path.join(BASE_DIR, "saida", "calibracao_gamatec.json")

    if not os.path.exists(caminho_calibracao):
        raise FileNotFoundError(f"Calibracao nao encontrada: {caminho_calibracao}")

    calibracao = carregar_calibracao(caminho_calibracao)

    orquestrador = OrquestradorAgenteGamatec(
        calibracao=calibracao,
        debug=True,
        pasta_debug=os.path.join(BASE_DIR, "saida"),
        quantidade_linhas_visiveis=12,
        max_scrolls_por_item=20,
        max_releituras_por_item=5,
        pausa_curta=0.15,
        pausa_media=0.35,
        pausa_longa=0.60,
    )

    itens_planejados = [
        {
            "codigo_krona": "340",
            "descricao_krona": "ITEM TESTE 1",
            "preco_alvo": 12.50,
            "desconto_calculado": 10.00
        },
        {
            "codigo_krona": "929",
            "descricao_krona": "ITEM TESTE 2",
            "preco_alvo": 44.30,
            "desconto_calculado": 8.50
        }
    ]

    resultados = orquestrador.processar_lote(itens_planejados)

    print("\n[RESULTADOS FINAIS]")
    for r in resultados:
        print("-" * 100)
        print(json.dumps(asdict(r), ensure_ascii=False, indent=2))