from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set
from datetime import datetime


@dataclass
class LeituraLinha:
    pagina: int
    linha: int
    codigo_lido: str = ""
    descricao_lida: str = ""
    ult_preco_lido: Optional[float] = None
    final_lido: Optional[float] = None
    origem_match: str = ""
    score_confianca: float = 0.0
    item_esperado: str = ""
    item_resolvido: str = ""
    status: str = ""
    observacao: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class EventoAgente:
    tipo: str
    mensagem: str
    pagina: int = 0
    linha: int = 0
    detalhes: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class EstadoExecucao:
    sessao_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    iniciado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    pagina_atual: int = 1
    linha_atual: int = 0
    assinatura_primeira_linha: str = ""
    assinatura_primeira_linha_anterior: str = ""
    scroll_funcionou_ultima_tentativa: bool = False
    paginas_sem_novos_itens: int = 0
    falhas_consecutivas: int = 0

    total_itens_planejados: int = 0
    total_itens_processados: int = 0
    total_itens_pulados: int = 0
    total_itens_revisao: int = 0

    codigos_planejados: Set[str] = field(default_factory=set)
    codigos_processados: Set[str] = field(default_factory=set)
    codigos_pulados: Set[str] = field(default_factory=set)
    codigos_repetidos: Set[str] = field(default_factory=set)
    codigos_nao_encontrados: Set[str] = field(default_factory=set)

    codigo_esperado_atual: str = ""
    codigo_lido_atual: str = ""
    descricao_lida_atual: str = ""
    ult_preco_atual: Optional[float] = None
    final_atual: Optional[float] = None
    origem_match_atual: str = ""
    score_confianca_atual: float = 0.0
    status_atual: str = ""
    observacao_atual: str = ""

    leituras: List[LeituraLinha] = field(default_factory=list)
    eventos: List[EventoAgente] = field(default_factory=list)

    def definir_planejamento(self, codigos_planejados: List[str]) -> None:
        limpos = {str(c).strip() for c in codigos_planejados if str(c).strip()}
        self.codigos_planejados = limpos
        self.total_itens_planejados = len(limpos)

    def atualizar_contexto_linha(
        self,
        pagina: int,
        linha: int,
        codigo_lido: str = "",
        descricao_lida: str = "",
        ult_preco_lido: Optional[float] = None,
        final_lido: Optional[float] = None,
        origem_match: str = "",
        score_confianca: float = 0.0,
        item_esperado: str = "",
        item_resolvido: str = "",
        status: str = "",
        observacao: str = "",
    ) -> None:
        self.pagina_atual = pagina
        self.linha_atual = linha
        self.codigo_lido_atual = str(codigo_lido or "").strip()
        self.descricao_lida_atual = str(descricao_lida or "").strip()
        self.ult_preco_atual = ult_preco_lido
        self.final_atual = final_lido
        self.origem_match_atual = str(origem_match or "").strip()
        self.score_confianca_atual = float(score_confianca or 0.0)
        self.codigo_esperado_atual = str(item_esperado or "").strip()
        self.status_atual = str(status or "").strip()
        self.observacao_atual = str(observacao or "").strip()

        leitura = LeituraLinha(
            pagina=pagina,
            linha=linha,
            codigo_lido=self.codigo_lido_atual,
            descricao_lida=self.descricao_lida_atual,
            ult_preco_lido=ult_preco_lido,
            final_lido=final_lido,
            origem_match=self.origem_match_atual,
            score_confianca=self.score_confianca_atual,
            item_esperado=self.codigo_esperado_atual,
            item_resolvido=str(item_resolvido or "").strip(),
            status=self.status_atual,
            observacao=self.observacao_atual,
        )
        self.leituras.append(leitura)

    def registrar_evento(
        self,
        tipo: str,
        mensagem: str,
        pagina: Optional[int] = None,
        linha: Optional[int] = None,
        detalhes: Optional[Dict[str, Any]] = None,
    ) -> None:
        evento = EventoAgente(
            tipo=str(tipo or "").strip(),
            mensagem=str(mensagem or "").strip(),
            pagina=self.pagina_atual if pagina is None else pagina,
            linha=self.linha_atual if linha is None else linha,
            detalhes=detalhes or {},
        )
        self.eventos.append(evento)

    def registrar_item_processado(self, codigo: str) -> None:
        codigo = str(codigo or "").strip()
        if not codigo:
            return
        self.codigos_processados.add(codigo)
        self.total_itens_processados = len(self.codigos_processados)

    def registrar_item_pulado(self, codigo: str, motivo: str = "") -> None:
        codigo = str(codigo or "").strip()
        if codigo:
            self.codigos_pulados.add(codigo)
            self.total_itens_pulados = len(self.codigos_pulados)

        self.registrar_evento(
            tipo="ITEM_PULADO",
            mensagem=f"Item pulado: {codigo}" if codigo else "Item pulado",
            detalhes={"codigo": codigo, "motivo": motivo},
        )

    def registrar_item_repetido(self, codigo: str) -> None:
        codigo = str(codigo or "").strip()
        if not codigo:
            return
        self.codigos_repetidos.add(codigo)
        self.registrar_evento(
            tipo="ITEM_REPETIDO",
            mensagem=f"Item repetido detectado: {codigo}",
            detalhes={"codigo": codigo},
        )

    def registrar_item_nao_encontrado(self, codigo: str = "", descricao: str = "") -> None:
        codigo = str(codigo or "").strip()
        descricao = str(descricao or "").strip()

        if codigo:
            self.codigos_nao_encontrados.add(codigo)

        self.registrar_evento(
            tipo="ITEM_NAO_ENCONTRADO",
            mensagem="Item não encontrado na grade",
            detalhes={"codigo": codigo, "descricao": descricao},
        )

    def atualizar_assinatura_primeira_linha(self, assinatura: str) -> None:
        self.assinatura_primeira_linha_anterior = self.assinatura_primeira_linha
        self.assinatura_primeira_linha = str(assinatura or "").strip()

    def registrar_scroll(self, funcionou: bool, assinatura_antes: str = "", assinatura_depois: str = "") -> None:
        self.scroll_funcionou_ultima_tentativa = bool(funcionou)

        if funcionou:
            self.paginas_sem_novos_itens = 0
            self.registrar_evento(
                tipo="SCROLL_OK",
                mensagem="Scroll executado com mudança de grade",
                detalhes={
                    "assinatura_antes": assinatura_antes,
                    "assinatura_depois": assinatura_depois,
                },
            )
        else:
            self.registrar_evento(
                tipo="SCROLL_FALHOU",
                mensagem="Scroll executado sem mudança de grade",
                detalhes={
                    "assinatura_antes": assinatura_antes,
                    "assinatura_depois": assinatura_depois,
                },
            )

    def incrementar_falha_consecutiva(self, motivo: str = "") -> None:
        self.falhas_consecutivas += 1
        self.registrar_evento(
            tipo="FALHA_CONSECUTIVA",
            mensagem=f"Falha consecutiva #{self.falhas_consecutivas}",
            detalhes={"motivo": motivo},
        )

    def zerar_falhas_consecutivas(self) -> None:
        self.falhas_consecutivas = 0

    def incrementar_pagina(self) -> None:
        self.pagina_atual += 1
        self.linha_atual = 0

    def resumo(self) -> Dict[str, Any]:
        faltantes = sorted(self.codigos_planejados - self.codigos_processados - self.codigos_pulados)

        return {
            "sessao_id": self.sessao_id,
            "iniciado_em": self.iniciado_em,
            "pagina_atual": self.pagina_atual,
            "linha_atual": self.linha_atual,
            "total_itens_planejados": self.total_itens_planejados,
            "total_itens_processados": self.total_itens_processados,
            "total_itens_pulados": self.total_itens_pulados,
            "total_itens_revisao": self.total_itens_revisao,
            "falhas_consecutivas": self.falhas_consecutivas,
            "scroll_funcionou_ultima_tentativa": self.scroll_funcionou_ultima_tentativa,
            "codigos_processados": sorted(self.codigos_processados),
            "codigos_pulados": sorted(self.codigos_pulados),
            "codigos_repetidos": sorted(self.codigos_repetidos),
            "codigos_nao_encontrados": sorted(self.codigos_nao_encontrados),
            "codigos_faltantes": faltantes,
            "total_eventos": len(self.eventos),
            "total_leituras": len(self.leituras),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "estado": self.resumo(),
            "leituras": [asdict(l) for l in self.leituras],
            "eventos": [asdict(e) for e in self.eventos],
        }