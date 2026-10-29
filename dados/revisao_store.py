# -*- coding: utf-8 -*-
"""
Sistema de armazenamento para revisão humana de itens com score baixo.
Utiliza SQLite para persistência de itens pendentes e suas resoluções.
"""

import sqlite3
import json
import math
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "revisoes.db")


def _texto(valor) -> str:
    """Normaliza valores do pandas (NaN/None) para texto vazio."""
    if valor is None:
        return ""
    texto = str(valor).strip()
    return "" if texto.lower() in {"nan", "none", "nat"} else texto


def _score(valor) -> float:
    try:
        numero = float(valor)
        return 0.0 if math.isnan(numero) else numero
    except (TypeError, ValueError):
        return 0.0


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
            justificativa_ia TEXT,
            sugestao_composicao TEXT
        )
    """)
    # migração: adiciona colunas IA em bases existentes sem elas
    colunas_existentes = {row[1] for row in c.execute("PRAGMA table_info(itens_revisao)")}
    if "confianca_ia" not in colunas_existentes:
        c.execute("ALTER TABLE itens_revisao ADD COLUMN confianca_ia TEXT")
    if "justificativa_ia" not in colunas_existentes:
        c.execute("ALTER TABLE itens_revisao ADD COLUMN justificativa_ia TEXT")
    if "alerta_equivalencia" not in colunas_existentes:
        c.execute("ALTER TABLE itens_revisao ADD COLUMN alerta_equivalencia TEXT")
    if "sugestao_composicao" not in colunas_existentes:
        c.execute("ALTER TABLE itens_revisao ADD COLUMN sugestao_composicao TEXT")
    conn.commit()
    conn.close()


def salvar_item_revisao(arquivo, num_item, descricao_oc,
                        codigo_sugerido, descricao_sugerida,
                        score, tipo_match,
                        confianca_ia=None, justificativa_ia=None,
                        alerta_equivalencia=None, sugestao_composicao=None):
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
        alerta_equivalencia: mensagem de alerta de regra de negócio (ex: equivalência
            de adesivo MRV) ou None. Se o item já estiver pendente na fila (por outro
            motivo, ex: score baixo), o alerta é adicionado à linha existente via UPDATE
            em vez de ser descartado pela deduplicação.
        sugestao_composicao: composição sugerida ou None.

    Returns:
        ID da linha (existente ou recém-criada).
    """
    arquivo = _texto(arquivo)
    num_item = _texto(num_item)
    descricao_oc = _texto(descricao_oc)
    codigo_sugerido = _texto(codigo_sugerido)
    descricao_sugerida = _texto(descricao_sugerida)
    tipo_match = _texto(tipo_match)
    confianca_ia = _texto(confianca_ia) or None
    justificativa_ia = _texto(justificativa_ia) or None
    alerta_equivalencia = _texto(alerta_equivalencia) or None
    sugestao_composicao = _texto(sugestao_composicao) or None
    score = _score(score)

    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # evita duplicatas do mesmo arquivo+item com status pendente
    c.execute("""
        SELECT id FROM itens_revisao
        WHERE arquivo=? AND descricao_oc=? AND status='pendente'
    """, (arquivo, descricao_oc))

    existente = c.fetchone()

    if existente:
        # item já pendente — atualiza a sugestão técnica (pode ter mudado desde o
        # último processamento) e anexa alerta/composição novos
        campos = [
            "num_item=?",
            "codigo_krona_sugerido=?",
            "descricao_krona_sugerida=?",
            "score_total=?",
            "tipo_match=?",
            "confianca_ia=?",
            "justificativa_ia=?",
        ]
        valores = [
            num_item,
            codigo_sugerido,
            descricao_sugerida,
            score,
            tipo_match,
            confianca_ia,
            justificativa_ia,
        ]
        if alerta_equivalencia:
            campos.append("alerta_equivalencia=?")
            valores.append(alerta_equivalencia)
        if sugestao_composicao:
            campos.append("sugestao_composicao=?")
            valores.append(sugestao_composicao)
        valores.append(existente[0])
        c.execute(
            f"UPDATE itens_revisao SET {', '.join(campos)} WHERE id=?",
            valores,
        )
        conn.commit()
        conn.close()
        return existente[0]

    c.execute("""
        INSERT INTO itens_revisao
        (arquivo, num_item, descricao_oc, codigo_krona_sugerido,
         descricao_krona_sugerida, score_total, tipo_match,
         confianca_ia, justificativa_ia, alerta_equivalencia,
         sugestao_composicao)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (arquivo, num_item, descricao_oc, codigo_sugerido,
          descricao_sugerida, score, tipo_match,
          confianca_ia, justificativa_ia,
          alerta_equivalencia, sugestao_composicao))

    novo_id = c.lastrowid
    conn.commit()
    conn.close()
    return novo_id


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


def limpar_resolvidos(dias: int = 180):
    """Remove itens resolvidos com mais de `dias` dias (limpeza)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        DELETE FROM itens_revisao
        WHERE status='resolvido' 
        AND datetime(resolvido_em) < datetime('now', ?)
    """, (f"-{int(dias)} days",))
    conn.commit()
    conn.close()


def remover_pendentes_obsoletos(arquivo, ids_mantidos):
    """
    Remove pendentes de um arquivo que já não são gerados pelo processamento
    atual (itens que passaram a ter match automático ou que deixaram de existir).

    Só deve ser chamada no fim de um processamento bem-sucedido, com os IDs
    efetivamente gravados nessa execução.

    Args:
        arquivo: nome do arquivo OC
        ids_mantidos: IDs de linhas que continuam válidas

    Returns:
        Número de linhas removidas.
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ids = sorted({int(i) for i in ids_mantidos if i is not None})
    if ids:
        placeholders = ",".join("?" * len(ids))
        c.execute(
            f"""
            DELETE FROM itens_revisao
            WHERE arquivo=? AND status='pendente' AND id NOT IN ({placeholders})
            """,
            (_texto(arquivo), *ids),
        )
    else:
        c.execute(
            "DELETE FROM itens_revisao WHERE arquivo=? AND status='pendente'",
            (_texto(arquivo),),
        )
    removidos = c.rowcount
    conn.commit()
    conn.close()
    return removidos


def _horas_texto(horas):
    """Formata uma duração em horas para leitura rápida."""
    if horas is None:
        return None
    if horas < 1:
        return f"{max(1, round(horas * 60))} min"
    if horas < 48:
        return f"{round(horas)} h"
    return f"{horas / 24:.1f} d".replace(".", ",")


def metricas_revisao():
    """
    Resumo da fila de revisão: pendentes, histórico, tempo até resolução
    e as OCs que mais precisaram de correção humana.
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        pendentes = conn.execute(
            "SELECT COUNT(*) FROM itens_revisao WHERE status='pendente'").fetchone()[0]
        idade_mais_antigo = conn.execute(
            "SELECT julianday('now') - julianday(MIN(criado_em)) "
            "FROM itens_revisao WHERE status='pendente'").fetchone()[0]

        por_status = {linha["status"]: linha["total"] for linha in conn.execute(
            "SELECT status, COUNT(*) AS total FROM itens_revisao GROUP BY status")}
        resolvidos = por_status.get("resolvido", 0)
        descartados = por_status.get("descartado", 0)

        resolvidos_30 = conn.execute(
            "SELECT COUNT(*) FROM itens_revisao WHERE status='resolvido' "
            "AND datetime(resolvido_em) >= datetime('now', '-30 days')").fetchone()[0]

        duracoes = sorted(
            linha[0] for linha in conn.execute(
                "SELECT (julianday(resolvido_em) - julianday(criado_em)) * 24 "
                "FROM itens_revisao WHERE status='resolvido' "
                "AND resolvido_em IS NOT NULL AND criado_em IS NOT NULL")
            if linha[0] is not None)
        media = sum(duracoes) / len(duracoes) if duracoes else None
        mediana = None
        if duracoes:
            meio = len(duracoes) // 2
            mediana = (duracoes[meio] if len(duracoes) % 2
                       else (duracoes[meio - 1] + duracoes[meio]) / 2)

        top_ocs = [dict(linha) for linha in conn.execute("""
            SELECT arquivo,
                   SUM(status='resolvido')  AS correcoes,
                   SUM(status='descartado') AS descartados,
                   SUM(status='pendente')   AS pendentes
            FROM itens_revisao
            GROUP BY arquivo
            HAVING SUM(status='resolvido') > 0
            ORDER BY correcoes DESC, pendentes DESC, arquivo
            LIMIT 5
        """)]
        ocs_com_correcao = conn.execute(
            "SELECT COUNT(DISTINCT arquivo) FROM itens_revisao "
            "WHERE status='resolvido'").fetchone()[0]
    finally:
        conn.close()

    decididos = resolvidos + descartados
    return {
        "pendentes": pendentes,
        "pendente_mais_antigo_dias": round(idade_mais_antigo) if idade_mais_antigo is not None else None,
        "resolvidos": resolvidos,
        "descartados": descartados,
        "resolvidos_30_dias": resolvidos_30,
        "taxa_correcao": round(resolvidos * 100 / decididos) if decididos else None,
        "tempo_medio": _horas_texto(media),
        "tempo_mediano": _horas_texto(mediana),
        "amostra_tempo": len(duracoes),
        "top_ocs": top_ocs,
        "ocs_com_correcao": ocs_com_correcao,
    }


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
