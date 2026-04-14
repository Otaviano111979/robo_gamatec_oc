from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LinhaDocumento:
    pagina: int
    numero_linha: int
    texto_original: str
    texto_normalizado: str = ""
    classe: str = "DESCONHECIDA"
    score: float = 0.0
    motivos: List[str] = field(default_factory=list)


@dataclass
class BlocoItem:
    pagina_inicial: int
    linhas: List[LinhaDocumento] = field(default_factory=list)
    score_bloco: float = 0.0
    observacoes: List[str] = field(default_factory=list)


@dataclass
class ItemExtraido:
    idx_item: Optional[int] = None
    codigo_interno_oc: Optional[str] = None

    descricao_original: str = ""
    descricao_reconstruida: str = ""

    quantidade: Optional[float] = None
    unidade_original: Optional[str] = None
    unidade_normalizada: Optional[str] = None

    valor_unitario: Optional[float] = None
    valor_total: Optional[float] = None

    pagina: Optional[int] = None
    linhas_origem: List[int] = field(default_factory=list)

    score_extracao: float = 0.0
    status_extracao: str = "falhou"
    observacoes: List[str] = field(default_factory=list)