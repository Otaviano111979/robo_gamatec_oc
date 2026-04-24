# -*- coding: utf-8 -*-
"""
dados/crm_loader.py

Banco de dados CRM — empresas, obras, contatos e documentos.
Usa SQLAlchemy Core para independência de banco:
  - Hoje:   SQLite  → arquivo dados/crm.db
  - Futuro: PostgreSQL → muda só DATABASE_URL no config.py

Estratégia de upsert:
  - Empresa identificada pelo CNPJ (único).
    Se não tem CNPJ, usa nome normalizado como fallback.
  - Obra identificada por (empresa_id + nome).
  - Contato identificado por (empresa_id + email).
  - Documento identificado por (numero + sistema_origem).
  - Campos mais completos sobrescrevem campos vazios (nunca apaga dado).
  - Confiança abaixo de CONFIANCA_MINIMA → revisao=True no registro.
"""

import os
import re
import time
import json
from typing import Optional, Dict, Any

# SQLAlchemy — usa apenas Core (sem ORM) para manter código simples
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    Integer, Text, Float, Boolean, String,
    select, insert, update, and_, text
)
from sqlalchemy.exc import IntegrityError

from config import BASE_DIR

# ============================================================
# CONFIGURAÇÃO
# ============================================================

# Para migrar para PostgreSQL no futuro, basta alterar esta linha no config.py:
# DATABASE_URL = "postgresql://usuario:senha@host:5432/vortex_crm"
DATABASE_URL = os.environ.get(
    "VORTEX_DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR, 'dados', 'crm.db')}"
)

_engine   = None
_metadata = MetaData()

# ============================================================
# DEFINIÇÃO DAS TABELAS
# ============================================================

t_empresas = Table("empresas", _metadata,
    Column("id",             Integer, primary_key=True, autoincrement=True),
    Column("nome",           Text,    nullable=False),
    Column("cnpj",           String(14), unique=True, nullable=True),
    Column("ie",             Text,    default=""),
    Column("endereco",       Text,    default=""),
    Column("cidade",         Text,    default=""),
    Column("estado",         String(2), default=""),
    Column("cep",            String(8), default=""),
    Column("telefone",       Text,    default=""),
    Column("email",          Text,    default=""),
    Column("site",           Text,    default=""),
    Column("sistema_oc",     Text,    default=""),   # SIENGE | UAU | MRV | BRASAL
    Column("revisao",        Boolean, default=False),
    Column("confianca",      Float,   default=0.0),
    Column("criado_em",      Text,    default=""),
    Column("atualizado_em",  Text,    default=""),
)

t_obras = Table("obras", _metadata,
    Column("id",             Integer, primary_key=True, autoincrement=True),
    Column("empresa_id",     Integer, nullable=False),
    Column("codigo",         Text,    default=""),
    Column("nome",           Text,    nullable=False),
    Column("endereco_entrega", Text,  default=""),
    Column("cidade",         Text,    default=""),
    Column("estado",         String(2), default=""),
    Column("cep",            String(8), default=""),
    Column("criado_em",      Text,    default=""),
)

t_contatos = Table("contatos", _metadata,
    Column("id",             Integer, primary_key=True, autoincrement=True),
    Column("empresa_id",     Integer, nullable=False),
    Column("nome",           Text,    default=""),
    Column("cargo",          Text,    default=""),
    Column("email",          Text,    default=""),
    Column("telefone",       Text,    default=""),
    Column("origem",         Text,    default=""),  # cabecalho_pdf | email | manual
    Column("criado_em",      Text,    default=""),
)

t_documentos = Table("documentos", _metadata,
    Column("id",             Integer, primary_key=True, autoincrement=True),
    Column("empresa_id",     Integer, nullable=True),
    Column("obra_id",        Integer, nullable=True),
    Column("tipo",           Text,    default="OC"),     # OC | COTACAO
    Column("numero",         Text,    default=""),
    Column("data_documento", Text,    default=""),
    Column("arquivo_pdf",    Text,    default=""),
    Column("total_valor",    Float,   nullable=True),
    Column("total_itens",    Integer, nullable=True),
    Column("itens_com_match", Integer, nullable=True),
    Column("sistema_origem", Text,    default=""),
    Column("email_origem",   Text,    default=""),
    Column("processado_em",  Text,    default=""),
    Column("status",         Text,    default="processado"),  # processado | erro | revisao
    Column("dados_raw",      Text,    default=""),  # JSON do extrator_cabecalho para auditoria
)


# ============================================================
# INICIALIZAÇÃO
# ============================================================

def get_engine():
    global _engine
    if _engine is None:
        os.makedirs(os.path.join(BASE_DIR, "dados"), exist_ok=True)
        _engine = create_engine(DATABASE_URL, echo=False, future=True)
    return _engine


def inicializar_banco():
    """Cria as tabelas se não existirem. Seguro para chamar múltiplas vezes."""
    engine = get_engine()
    _metadata.create_all(engine)
    print(f"[CRM] Banco inicializado: {DATABASE_URL}")


# ============================================================
# UTILITÁRIOS INTERNOS
# ============================================================

def _agora() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _normalizar_nome(nome: str) -> str:
    """Normaliza nome para comparação. Remove sufixos jurídicos e espaços."""
    sufixos = [
        r"\bLTDA\.?\b", r"\bS\.A\.?\b", r"\bSA\b", r"\bEIRELI\b",
        r"\bSPE\b", r"\bME\b", r"\bEPP\b", r"\bS\/A\b",
    ]
    n = str(nome or "").upper().strip()
    for s in sufixos:
        n = re.sub(s, "", n, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", n).strip()


def _mesclar(existente: dict, novo: dict) -> dict:
    """
    Mescla dois dicts: campos vazios do existente recebem valor do novo.
    Nunca apaga dado já preenchido.
    """
    resultado = dict(existente)
    for k, v in novo.items():
        if not resultado.get(k) and v:
            resultado[k] = v
    return resultado


def _limpar(texto) -> str:
    if not texto:
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip()


# ============================================================
# EMPRESAS
# ============================================================

def buscar_empresa(cnpj: str = "", nome: str = "") -> Optional[Dict]:
    """Busca empresa por CNPJ (preferencial) ou nome normalizado."""
    engine = get_engine()
    with engine.connect() as conn:
        # 1. por CNPJ
        if cnpj and len(cnpj) >= 8:
            cnpj_norm = re.sub(r"\D", "", cnpj)
            stmt = select(t_empresas).where(
                t_empresas.c.cnpj.like(f"{cnpj_norm[:8]}%")
            )
            row = conn.execute(stmt).mappings().first()
            if row:
                return dict(row)

        # 2. por nome normalizado (fallback)
        if nome:
            nome_norm = _normalizar_nome(nome)
            stmt = select(t_empresas)
            rows = conn.execute(stmt).mappings().all()
            for row in rows:
                if _normalizar_nome(row["nome"]) == nome_norm:
                    return dict(row)

    return None


def salvar_empresa(dados: dict, confianca: float = 1.0, revisao: bool = False) -> int:
    """
    Upsert de empresa.
    Retorna o ID da empresa (nova ou existente).
    """
    engine   = get_engine()
    cnpj     = re.sub(r"\D", "", dados.get("cnpj", ""))
    nome     = _limpar(dados.get("nome", ""))
    agora    = _agora()

    if not nome:
        return -1

    existente = buscar_empresa(cnpj=cnpj, nome=nome)

    novo = {
        "nome":          nome,
        "cnpj":          cnpj or None,
        "ie":            _limpar(dados.get("ie", "")),
        "endereco":      _limpar(dados.get("endereco", "")),
        "cidade":        _limpar(dados.get("cidade", "")),
        "estado":        _limpar(dados.get("estado", "")),
        "cep":           re.sub(r"\D", "", dados.get("cep", "")),
        "telefone":      re.sub(r"\D", "", dados.get("telefone", "")),
        "email":         _limpar(dados.get("email", "")).lower(),
        "sistema_oc":    _limpar(dados.get("sistema_oc", "")),
        "confianca":     confianca,
        "revisao":       revisao,
        "atualizado_em": agora,
    }

    with engine.begin() as conn:
        if existente:
            # mescla: não apaga dados existentes
            atualizado = _mesclar(existente, novo)
            atualizado["atualizado_em"] = agora
            # atualiza confiança se melhorou
            if confianca > existente.get("confianca", 0):
                atualizado["confianca"] = confianca
                atualizado["revisao"]   = revisao
            conn.execute(
                update(t_empresas)
                .where(t_empresas.c.id == existente["id"])
                .values({k: atualizado[k] for k in novo if k in atualizado})
            )
            return existente["id"]
        else:
            novo["criado_em"] = agora
            result = conn.execute(insert(t_empresas).values(**novo))
            return result.inserted_primary_key[0]


# ============================================================
# OBRAS
# ============================================================

def buscar_obra(empresa_id: int, nome: str = "", codigo: str = "") -> Optional[Dict]:
    engine = get_engine()
    with engine.connect() as conn:
        if codigo:
            stmt = select(t_obras).where(
                and_(t_obras.c.empresa_id == empresa_id,
                     t_obras.c.codigo == codigo)
            )
            row = conn.execute(stmt).mappings().first()
            if row:
                return dict(row)

        if nome:
            nome_norm = _normalizar_nome(nome)
            stmt = select(t_obras).where(t_obras.c.empresa_id == empresa_id)
            rows = conn.execute(stmt).mappings().all()
            for row in rows:
                if _normalizar_nome(row["nome"]) == nome_norm:
                    return dict(row)
    return None


def salvar_obra(empresa_id: int, dados: dict) -> int:
    """Upsert de obra. Retorna ID."""
    engine   = get_engine()
    nome     = _limpar(dados.get("nome", ""))
    codigo   = _limpar(dados.get("codigo", ""))
    agora    = _agora()

    if not nome and not codigo:
        return -1

    existente = buscar_obra(empresa_id, nome=nome, codigo=codigo)

    novo = {
        "empresa_id":        empresa_id,
        "codigo":            codigo,
        "nome":              nome,
        "endereco_entrega":  _limpar(dados.get("endereco_entrega", "")),
        "cidade":            _limpar(dados.get("cidade", "")),
        "estado":            _limpar(dados.get("estado", "")),
        "cep":               re.sub(r"\D", "", dados.get("cep", "")),
    }

    with engine.begin() as conn:
        if existente:
            atualizado = _mesclar(existente, novo)
            conn.execute(
                update(t_obras)
                .where(t_obras.c.id == existente["id"])
                .values({k: atualizado[k] for k in novo if k in atualizado})
            )
            return existente["id"]
        else:
            novo["criado_em"] = agora
            result = conn.execute(insert(t_obras).values(**novo))
            return result.inserted_primary_key[0]


# ============================================================
# CONTATOS
# ============================================================

def salvar_contato(empresa_id: int, dados: dict) -> int:
    """Upsert de contato por email. Retorna ID."""
    engine = get_engine()
    email  = _limpar(dados.get("email", "")).lower()
    nome   = _limpar(dados.get("nome", ""))
    agora  = _agora()

    if not email and not nome:
        return -1

    with engine.connect() as conn:
        # busca por email (se tiver)
        if email:
            stmt = select(t_contatos).where(
                and_(t_contatos.c.empresa_id == empresa_id,
                     t_contatos.c.email == email)
            )
            existente = conn.execute(stmt).mappings().first()
            if existente:
                existente = dict(existente)
                novo = {
                    "nome":     nome or existente["nome"],
                    "cargo":    _limpar(dados.get("cargo", "")) or existente["cargo"],
                    "telefone": re.sub(r"\D", "", dados.get("telefone", "")) or existente["telefone"],
                    "origem":   _limpar(dados.get("origem", "")) or existente["origem"],
                }
                with engine.begin() as conn2:
                    conn2.execute(
                        update(t_contatos)
                        .where(t_contatos.c.id == existente["id"])
                        .values(**novo)
                    )
                return existente["id"]

    novo = {
        "empresa_id": empresa_id,
        "nome":       nome,
        "cargo":      _limpar(dados.get("cargo", "")),
        "email":      email,
        "telefone":   re.sub(r"\D", "", dados.get("telefone", "")),
        "origem":     _limpar(dados.get("origem", "")),
        "criado_em":  agora,
    }
    with engine.begin() as conn:
        result = conn.execute(insert(t_contatos).values(**novo))
        return result.inserted_primary_key[0]


# ============================================================
# DOCUMENTOS
# ============================================================

def salvar_documento(
    empresa_id:     Optional[int],
    obra_id:        Optional[int],
    dados_doc:      dict,
    arquivo_pdf:    str = "",
    total_itens:    int = 0,
    itens_com_match: int = 0,
    email_origem:   str = "",
    status:         str = "processado",
    dados_raw:      dict = None,
) -> int:
    """Registra documento processado. Retorna ID."""
    engine = get_engine()
    agora  = _agora()

    numero  = _limpar(dados_doc.get("numero", ""))
    sistema = _limpar(dados_doc.get("sistema_origem", ""))

    # evita duplicatas do mesmo documento
    with engine.connect() as conn:
        if numero and sistema:
            stmt = select(t_documentos).where(
                and_(t_documentos.c.numero == numero,
                     t_documentos.c.sistema_origem == sistema)
            )
            existente = conn.execute(stmt).mappings().first()
            if existente:
                # atualiza status e match se reprocessado
                with engine.begin() as conn2:
                    conn2.execute(
                        update(t_documentos)
                        .where(t_documentos.c.id == existente["id"])
                        .values(
                            status=status,
                            total_itens=total_itens,
                            itens_com_match=itens_com_match,
                            processado_em=agora,
                        )
                    )
                return existente["id"]

    novo = {
        "empresa_id":      empresa_id,
        "obra_id":         obra_id,
        "tipo":            _limpar(dados_doc.get("tipo", "OC")),
        "numero":          numero,
        "data_documento":  _limpar(dados_doc.get("data", "")),
        "arquivo_pdf":     arquivo_pdf,
        "total_valor":     dados_doc.get("total_valor"),
        "total_itens":     total_itens,
        "itens_com_match": itens_com_match,
        "sistema_origem":  sistema,
        "email_origem":    email_origem,
        "processado_em":   agora,
        "status":          status,
        "dados_raw":       json.dumps(dados_raw or {}, ensure_ascii=False),
    }
    with engine.begin() as conn:
        result = conn.execute(insert(t_documentos).values(**novo))
        return result.inserted_primary_key[0]


# ============================================================
# FUNÇÃO PRINCIPAL — chamada pelo processador de OC
# ============================================================

def registrar_documento_completo(
    resultado_cabecalho: dict,
    arquivo_pdf:         str,
    total_itens:         int = 0,
    itens_com_match:     int = 0,
    email_origem:        str = "",
) -> dict:
    """
    Ponto de entrada principal.
    Recebe o dict do extrator_cabecalho e salva tudo no banco.

    Retorna: { empresa_id, obra_id, documento_id, revisao, confianca }
    """
    inicializar_banco()

    empresa_dados  = resultado_cabecalho.get("empresa", {})
    obra_dados     = resultado_cabecalho.get("obra", {})
    doc_dados      = resultado_cabecalho.get("documento", {})
    contatos_lista = resultado_cabecalho.get("contatos", [])
    confianca      = resultado_cabecalho.get("confianca", 0.0)
    revisao        = resultado_cabecalho.get("revisao", True)
    formato        = resultado_cabecalho.get("formato", "")

    # adiciona sistema_oc à empresa
    empresa_dados["sistema_oc"] = formato

    # salva empresa
    empresa_id = -1
    if empresa_dados.get("nome") or empresa_dados.get("cnpj"):
        empresa_id = salvar_empresa(empresa_dados, confianca=confianca, revisao=revisao)
        print(f"[CRM] Empresa salva/atualizada — id={empresa_id} "
              f"nome='{empresa_dados.get('nome', '')}' "
              f"confianca={confianca:.2f} revisao={revisao}")

    # salva obra
    obra_id = -1
    if empresa_id > 0 and (obra_dados.get("nome") or obra_dados.get("codigo")):
        obra_id = salvar_obra(empresa_id, obra_dados)
        print(f"[CRM] Obra salva/atualizada — id={obra_id} "
              f"nome='{obra_dados.get('nome', '')}'")

    # salva contatos
    for contato in contatos_lista:
        if empresa_id > 0 and (contato.get("email") or contato.get("nome")):
            cid = salvar_contato(empresa_id, contato)
            print(f"[CRM] Contato salvo — id={cid} email='{contato.get('email', '')}'")

    # define status do documento
    status = "revisao" if revisao else "processado"

    # salva documento
    doc_id = salvar_documento(
        empresa_id      = empresa_id if empresa_id > 0 else None,
        obra_id         = obra_id if obra_id > 0 else None,
        dados_doc       = doc_dados,
        arquivo_pdf     = arquivo_pdf,
        total_itens     = total_itens,
        itens_com_match = itens_com_match,
        email_origem    = email_origem,
        status          = status,
        dados_raw       = resultado_cabecalho,
    )
    print(f"[CRM] Documento registrado — id={doc_id} "
          f"numero='{doc_dados.get('numero', '')}' status={status}")

    return {
        "empresa_id":  empresa_id,
        "obra_id":     obra_id,
        "documento_id": doc_id,
        "revisao":     revisao,
        "confianca":   confianca,
    }


# ============================================================
# UTILITÁRIOS DE CONSULTA (para o CRM futuro)
# ============================================================

def listar_empresas(revisao: bool = None) -> list:
    """Lista empresas. Se revisao=True, retorna apenas as marcadas para revisão."""
    engine = get_engine()
    with engine.connect() as conn:
        stmt = select(t_empresas)
        if revisao is not None:
            stmt = stmt.where(t_empresas.c.revisao == revisao)
        stmt = stmt.order_by(t_empresas.c.nome)
        return [dict(r) for r in conn.execute(stmt).mappings().all()]


def listar_documentos_empresa(empresa_id: int) -> list:
    engine = get_engine()
    with engine.connect() as conn:
        stmt = (
            select(t_documentos)
            .where(t_documentos.c.empresa_id == empresa_id)
            .order_by(t_documentos.c.processado_em.desc())
        )
        return [dict(r) for r in conn.execute(stmt).mappings().all()]


def listar_pendentes_revisao() -> list:
    """Retorna documentos marcados para revisão manual."""
    engine = get_engine()
    with engine.connect() as conn:
        stmt = (
            select(t_documentos)
            .where(t_documentos.c.status == "revisao")
            .order_by(t_documentos.c.processado_em.desc())
        )
        return [dict(r) for r in conn.execute(stmt).mappings().all()]


def stats_crm() -> dict:
    """Estatísticas gerais do banco para o painel."""
    engine = get_engine()
    with engine.connect() as conn:
        return {
            "total_empresas":  conn.execute(text("SELECT COUNT(*) FROM empresas")).scalar(),
            "total_obras":     conn.execute(text("SELECT COUNT(*) FROM obras")).scalar(),
            "total_contatos":  conn.execute(text("SELECT COUNT(*) FROM contatos")).scalar(),
            "total_documentos": conn.execute(text("SELECT COUNT(*) FROM documentos")).scalar(),
            "pendentes_revisao": conn.execute(
                text("SELECT COUNT(*) FROM documentos WHERE status='revisao'")
            ).scalar(),
        }