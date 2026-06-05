# -*- coding: utf-8 -*-
"""
extracao_oc/extrator_generico.py

Extrator generico para OCs de clientes nao cadastrados.
Fallback de ultimo recurso quando extratores dedicados falham.
"""

import re
import pdfplumber


def detectar_generico(caminho_pdf: str) -> bool:
    return True


def extrair_itens_generico(caminho_pdf: str) -> list:
    itens = []
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for pagina in pdf.pages:
                tabelas = pagina.extract_tables()
                for tabela in tabelas:
                    if not tabela:
                        continue
                    idx_cab = _detectar_cabecalho(tabela)
                    if idx_cab is None:
                        continue
                    for linha in tabela[idx_cab + 1:]:
                        item = _parsear_linha(linha, tabela[idx_cab])
                        if item:
                            itens.append(item)
                if not itens:
                    texto = pagina.extract_text() or ""
                    itens.extend(_extrair_de_texto(texto))
    except Exception as e:
        print(f"[EXTRATOR GENERICO] Erro: {e}")
    return itens


def _detectar_cabecalho(tabela: list):
    palavras = {"item","codigo","descricao","descr","un","unid","qtde","qtd","quantidade","preco","valor","cod"}
    for i, linha in enumerate(tabela[:5]):
        if not linha:
            continue
        celulas = [str(c or "").lower().strip() for c in linha]
        if sum(1 for c in celulas if any(p in c for p in palavras)) >= 3:
            return i
    return None


def _parsear_linha(linha: list, cabecalho: list) -> dict:
    if not linha or all(c is None or str(c).strip() == "" for c in linha):
        return None
    mapa = {}
    for i, col in enumerate(cabecalho or []):
        col_lower = str(col or "").lower().strip()
        if i >= len(linha):
            continue
        val = str(linha[i] or "").strip()
        if any(p in col_lower for p in ["descr", "desc"]):
            mapa["descricao"] = val.replace("\n", " ").replace("\r", " ").strip()
        elif any(p in col_lower for p in ["qtde", "qtd", "quant"]):
            mapa["quantidade"] = _num(val)
        elif any(p in col_lower for p in ["un", "unid"]):
            # valida: unidade nao pode ser numerica (ex: "1,7360" e preco, nao unidade)
            val_limpo = val.replace(",", "").replace(".", "").strip()
            if val_limpo.isdigit() or (val_limpo.replace(" ", "") == ""):
                pass  # ignora valor numerico na coluna de unidade
            else:
                mapa["unidade"] = val
        elif any(p in col_lower for p in ["cod", "codigo"]):
            mapa["codigo_cliente"] = val
        elif "item" in col_lower:
            mapa["num_item"] = val
        elif any(p in col_lower for p in ["preco", "valor", "unit"]):
            mapa["preco_unitario"] = _num(val)
    if not mapa.get("descricao") or len(mapa["descricao"]) < 5:
        return None
    desc_up = mapa["descricao"].upper()
    if any(p in desc_up for p in ["TOTAL","SUBTOTAL","DESCONTO","FRETE","ITEM"]):
        return None
    return {
        "num_item":       mapa.get("num_item", ""),
        "codigo_cliente": mapa.get("codigo_cliente", ""),
        "descricao_oc":   mapa["descricao"],
        "unidade":        mapa.get("unidade", "PC"),
        "quantidade":     mapa.get("quantidade"),
        "preco_unitario": mapa.get("preco_unitario"),
        "observacoes":    ["CLIENTE_NOVO", "EXTRATOR_GENERICO"],
    }


def _extrair_de_texto(texto: str) -> list:
    itens = []
    for linha in texto.split("\n"):
        linha = linha.strip()
        if len(linha) < 10:
            continue
        m = re.match(
            r"^\s*(\d{1,3})\s+(\w+)\s+(.{10,}?)\s+(PC|UN|UND|UNID|BR|KG|MT|M2?|CX|RL|PCT|GL|LT|FD)\s+([\d.,]+)",
            linha, re.IGNORECASE
        )
        if m:
            itens.append({
                "num_item":       m.group(1),
                "codigo_cliente": m.group(2),
                "descricao_oc":   m.group(3).strip(),
                "unidade":        m.group(4).upper(),
                "quantidade":     _num(m.group(5)),
                "observacoes":    ["CLIENTE_NOVO", "EXTRATOR_GENERICO_TEXTO"],
            })
    return itens


def _num(texto: str):
    if not texto:
        return None
    limpo = re.sub(r"[^\d,.]", "", texto).replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except Exception:
        return None
