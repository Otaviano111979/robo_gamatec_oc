# -*- coding: utf-8 -*-
"""
Sistema de armazenamento para revisão humana de itens com score baixo.
Utiliza SQLite para persistência de itens pendentes e suas resoluções.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "revisoes.db")


def init_db():
    """Inicializa a tabela de revisões e aplica migrações necessárias."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS itens_revisao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arquivo TEXT NOT NULL,
            num_item TEXT,
            descricao_oc TEXT NOT NULL,
            codigo_krona_sugerido TEXT,
            descricao_krona_sugerida TEXT,
            score_total REAL,
            tipo_match TEXT,
            status TEXT DEFAULT 'pendente',
            codigo_krona_correto TEXT,
            descricao_krona_correta TEXT,
            corrigido_por TEXT,
            criado_em TEXT DEFAULT (datetime('now')),
            resolvido_em TEXT,
            confianca_ia TEXT,
            justificativa_ia TEXT
        )
    """)
    # migração: adiciona colunas IA em bases existentes sem elas
    colunas_existentes = {row[1] for row in c.execute("PRAGMA table_info(itens_revisao)")}
    if "confianca_ia" not in colunas_existentes:
        c.execute("ALTER TABLE itens_revisao ADD COLUMN confianca_ia TEXT")
    if "justificativa_ia" not in colunas_existentes:
        c.execute("ALTER TABLE itens_revisao ADD COLUMN justificativa_ia TEXT")
    conn.commit()
    conn.close()


def salvar_item_revisao(arquivo, num_item, descricao_oc,
                        codigo_sugerido, descricao_sugerida,
                        score, tipo_match,
                        confianca_ia=None, justificativa_ia=None):
    """
    Salva um item para revisão, evitando duplicatas.

    Args:
        arquivo: nome do arquivo OC
        num_item: número do item
        descricao_oc: descrição extraída da OC
        codigo_sugerido: código Krona sugerido
        descricao_sugerida: descrição Krona sugerida
        score: score total do match
        tipo_match: tipo de match (EXATO, SEMANTICO, SEM_MATCH, MATCH_IA, etc)
        confianca_ia: nível de confiança da IA ("alta", "media", "baixa") ou None
        justificativa_ia: justificativa textual retornada pela IA ou None
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # evita duplicatas do mesmo arquivo+item com status pendente
    c.execute("""
        SELECT id FROM itens_revisao
        WHERE arquivo=? AND descricao_oc=? AND status='pendente'
    """, (arquivo, descricao_oc))

    if c.fetchone():
        conn.close()
        return

    c.execute("""
        INSERT INTO itens_revisao
        (arquivo, num_item, descricao_oc, codigo_krona_sugerido,
         descricao_krona_sugerida, score_total, tipo_match,
         confianca_ia, justificativa_ia)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (arquivo, num_item, descricao_oc, codigo_sugerido,
          descricao_sugerida, score, tipo_match,
          confianca_ia or None, justificativa_ia or None))

    conn.commit()
    conn.close()


def listar_pendentes(limite=None):
    """
    Lista todos os itens pendentes de revisão.
    
    Args:
        limite: número máximo de itens a retornar (None = sem limite)
        
    Returns:
        Lista de dicionários com os itens pendentes
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if limite:
        c.execute("""
            SELECT * FROM itens_revisao
            WHERE status='pendente'
            ORDER BY criado_em DESC
            LIMIT ?
        """, (limite,))
    else:
        c.execute("""
            SELECT * FROM itens_revisao
            WHERE status='pendente'
            ORDER BY criado_em DESC
        """)
    
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def contar_pendentes():
    """Retorna a quantidade de itens pendentes."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM itens_revisao WHERE status='pendente'")
    count = c.fetchone()[0]
    conn.close()
    return count


def obter_item_revisao(item_id):
    """Obtém um item específico de revisão."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM itens_revisao WHERE id=?
    """, (item_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def resolver_item(item_id, codigo_correto, descricao_correta, usuario):
    """
    Marca um item como resolvido com a correção do usuário.
    
    Args:
        item_id: ID do item na tabela
        codigo_correto: código Krona correto selecionado
        descricao_correta: descrição Krona correta
        usuario: usuário que fez a correção
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE itens_revisao
        SET status='resolvido',
            codigo_krona_correto=?,
            descricao_krona_correta=?,
            corrigido_por=?,
            resolvido_em=datetime('now')
        WHERE id=?
    """, (codigo_correto, descricao_correta, usuario, item_id))
    conn.commit()
    conn.close()


def descartar_item(item_id, usuario):
    """Descarta item da fila de revisão sem gerar correção."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE itens_revisao
        SET status='descartado',
            corrigido_por=?,
            resolvido_em=datetime('now')
        WHERE id=?
    """, (usuario, item_id))
    conn.commit()
    conn.close()


def salvar_correcao_aprendizado(descricao_oc, codigo_krona, descricao_krona):
    """
    Salva correção em JSON para que o motor aprenda dessa resolução.
    
    Args:
        descricao_oc: descrição original da OC
        codigo_krona: código Krona correto
        descricao_krona: descrição Krona correta
    """
    path = os.path.join(os.path.dirname(__file__), "correcoes_aprendidas.json")
    correcoes = []
    
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                correcoes = json.load(f)
        except Exception:
            correcoes = []
    
    # atualiza se já existe, senão adiciona nova
    for c in correcoes:
        if c.get('descricao_oc', '').lower() == descricao_oc.lower():
            c['codigo_krona'] = codigo_krona
            c['descricao_krona'] = descricao_krona
            c['data_atualizacao'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(correcoes, f, ensure_ascii=False, indent=2)
            return
    
    # nova correção
    correcoes.append({
        'descricao_oc': descricao_oc,
        'codigo_krona': codigo_krona,
        'descricao_krona': descricao_krona,
        'data': datetime.now().strftime('%Y-%m-%d')
    })
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(correcoes, f, ensure_ascii=False, indent=2)


def listar_resolvidos_por_arquivo(arquivo: str):
    """Retorna todos os itens resolvidos para um arquivo específico."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM itens_revisao
        WHERE arquivo=? AND status='resolvido'
        ORDER BY resolvido_em DESC
    """, (arquivo,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def limpar_resolvidos():
    """Remove itens resolvidos mais antigos de 30 dias (limpeza)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        DELETE FROM itens_revisao
        WHERE status='resolvido' 
        AND datetime(resolvido_em) < datetime('now', '-30 days')
    """)
    conn.commit()
    conn.close()


def listar_resolvidos(limite=50):
    """
    Retorna os últimos itens resolvidos com detalhes.
    
    Args:
        limite: número máximo de itens a retornar (padrão 50)
        
    Returns:
        Lista de dicionários com os itens resolvidos
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM itens_revisao
        WHERE status IN ('resolvido', 'descartado')
        ORDER BY resolvido_em DESC
        LIMIT ?
    """, (limite,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
