from typing import List, Dict, Any

from extracao_oc.pdf_reader import extrair_linhas_pdf, extrair_linhas_pdf_uau, extrair_linhas_pdf_brasal
from extracao_oc.normalizador_oc import normalizar_linhas
from extracao_oc.segmentador_documento import classificar_linhas_documento, detectar_formato_documento
from extracao_oc.agrupador_itens import agrupar_blocos_itens
from extracao_oc.estruturador_item import estruturar_blocos_em_itens
from extracao_oc.validacao_extracao_oc import validar_itens_extraidos
from extracao_oc.debug_extracao import gerar_relatorio_extracao
from extracao_oc.extrator_sienge import extrair_oc_sienge, detectar_formato_sienge
import re as _re


# ================================================================
# DETECTOR E EXTRATOR — BRASAL / CLOSER / ARTESANO
# ================================================================

def _detectar_formato_brasal(caminho_pdf: str) -> bool:
    """
    Detecta se o PDF e do formato Brasal/Closer ou Brasal/Artesano.

    Suporta dois layouts:
    - Closer (antigo): tem 'KRONA/KRONA' no texto
    - Artesano/Marista (novo): tem 'PROCESSO Nº' + 'ORDEM DE COMPRA' + 'BRASAL'
    """
    try:
        import pdfplumber
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = pdf.pages[0].extract_text() or ""
            t = texto.upper()

            # formato Closer (antigo)
            if (
                "KRONA/KRONA" in t
                and "CÓDIGO" in t
                and "QUANTIDADE" in t
                and "UNIDADE" in t
            ):
                return True

            # formato Artesano/Marista (novo)
            if (
                "PROCESSO" in t
                and "ORDEM DE COMPRA" in t
                and "BRASAL" in t
                and "DADOS DO FORNECEDOR" in t
            ):
                return True

            return False
    except Exception:
        return False


def _extrair_itens_brasal(caminho_pdf: str) -> List[Dict[str, Any]]:
    """
    Extração direta para o formato Brasal/Closer.
    O codigo Krona ja esta na OC — faz match direto sem passar pelo matcher.
    """
    import pdfplumber

    def limpar(v):
        if v is None: return ""
        return _re.sub(r'[\n\r]+', ' ', str(v)).strip()

    def limpar_codigo(v):
        return _re.sub(r'[.\s]', '', str(v).strip())

    def br_float(v):
        t = str(v or "").strip().replace(".", "").replace(",", ".")
        try: return float(t)
        except: return None

    def e_item(row):
        if not row or len(row) < 4: return False
        cod  = limpar_codigo(limpar(row[0]))
        un   = limpar(row[2]).upper()
        desc = limpar(row[3])
        if not cod.isdigit(): return False
        if un not in ('M','MT','UN','UND','RL','BR','KG','CX','PC','L','LT'): return False
        if not desc or desc.upper() in ('KRONA/KRONA','DESCRIÇÃO DO PRODUTO',''): return False
        return True

    def limpar_desc(raw):
        d = _re.sub(r'KRONA/KRONA', '', raw, flags=_re.IGNORECASE)
        d = _re.sub(r'\b\d{1,2}\.\d{3}\b', '', d)
        d = _re.sub(r'[\n\r]+', ' ', d).strip()
        return _re.sub(r'\s+', ' ', d).strip()

    itens = []
    idx   = 1

    with pdfplumber.open(caminho_pdf) as pdf:
        for numero_pagina, pagina in enumerate(pdf.pages, start=1):
            for tabela in pagina.extract_tables():
                for row in tabela:
                    if not e_item(row): continue

                    ncols        = len(row)
                    codigo_raw   = limpar_codigo(limpar(row[0]))
                    unidade      = limpar(row[2]).upper()
                    qtd_raw      = limpar(row[1])
                    descricao    = limpar_desc(limpar(row[3]))

                    if ncols >= 12:
                        preco_raw = limpar(row[6])
                        total_raw = limpar(row[11])
                    else:
                        preco_raw = limpar(row[4]) if ncols > 4 else ""
                        total_raw = limpar(row[8]) if ncols > 8 else ""

                    quantidade  = br_float(qtd_raw)
                    valor_unit  = br_float(preco_raw)
                    valor_total = br_float(total_raw)

                    itens.append({
                        "idx_item":               idx,
                        "codigo_interno_oc":       codigo_raw,
                        "descricao_original":      descricao,
                        "descricao_reconstruida":  descricao,
                        "quantidade":              quantidade,
                        "unidade_original":        unidade,
                        "unidade_normalizada":     unidade,
                        "valor_unitario":          valor_unit,
                        "valor_total":             valor_total,
                        "pagina":                  numero_pagina,
                        "linhas_origem":           [idx],
                        "score_extracao":          0.98,
                        "status_extracao":         "ok",
                        "observacoes":             ["formato_brasal"],
                    })
                    idx += 1

    return itens


# ================================================================
# DETECTOR E EXTRATOR — PAVINI SEROA ENGENHARIA
# Formato próprio — tabela N. | Item | Qtd. | Unit.(R$) | ...
# ================================================================

def _detectar_formato_pavini(caminho_pdf: str) -> bool:
    """
    Detecta OCs da Pavini Seroa Engenharia.
    Marcadores: 'DADOS DA ORDEM DE COMPRA' + 'RESPONSAVEL PELA COMPRA'
    ou 'PAVINI' + 'OBRA/CENTRO DE CUSTO'.
    """
    try:
        import pdfplumber
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = (pdf.pages[0].extract_text() or "").upper()

        if (
            "DADOS DA ORDEM DE COMPRA" in texto
            and "RESPONSAVEL PELA COMPRA" in texto
        ):
            return True

        if (
            "PAVINI" in texto
            and "OBRA/CENTRO DE CUSTO" in texto
        ):
            return True

        return False
    except Exception:
        return False


def _extrair_itens_pavini(caminho_pdf: str) -> List[Dict[str, Any]]:
    """
    Extração de itens para OCs Pavini.
    Tabela: N. | Item | Qtd.\\nUND | Unit.(R$) | Subtotal | Desc. | Total
    A quantidade e a unidade estão na mesma célula separadas por \\n.
    """
    import pdfplumber

    def limpar(v):
        if v is None: return ""
        return _re.sub(r'[\n\r]+', ' ', str(v)).strip()

    def br_float(v):
        t = str(v or "").strip().replace(".", "").replace(",", ".")
        try: return float(t)
        except: return None

    def e_item_pavini(row):
        """Linha válida: primeira célula é número sequencial (1, 2, 3...)."""
        if not row or len(row) < 3: return False
        n = limpar(row[0]).strip()
        if not n.isdigit(): return False
        desc = limpar(row[1])
        if not desc or desc.upper() in ("N.", "ITEM", ""): return False
        return True

    itens = []
    idx   = 1

    with pdfplumber.open(caminho_pdf) as pdf:
        for numero_pagina, pagina in enumerate(pdf.pages, start=1):
            tabelas = pagina.extract_tables() or []
            for tabela in tabelas:
                if not tabela: continue

                # verifica se é a tabela de itens (tem coluna "Item" ou "N.")
                header = [limpar(c).upper() for c in (tabela[0] or [])]
                if "ITEM" not in header and "N." not in header:
                    continue

                for row in tabela[1:]:
                    if not e_item_pavini(row): continue

                    descricao = limpar(row[1])
                    # remove quebras de linha internas da descrição
                    descricao = _re.sub(r'\s+', ' ', descricao).strip()

                    # qtd e unidade estão na mesma célula: "168,00\nUND"
                    qtd_cell  = str(row[2] or "").strip()
                    partes    = qtd_cell.split("\n")
                    qtd_raw   = partes[0].strip() if partes else ""
                    unidade   = partes[1].strip().upper() if len(partes) > 1 else "UND"
                    # normaliza unidade
                    if unidade == "M":
                        unidade = "M"
                    elif unidade not in ("M","MT","UN","UND","RL","BR","KG","CX","PC","L","LT"):
                        unidade = "UND"

                    preco_raw = limpar(row[3]) if len(row) > 3 else ""
                    total_raw = limpar(row[6]) if len(row) > 6 else ""

                    quantidade  = br_float(qtd_raw)
                    valor_unit  = br_float(preco_raw)
                    valor_total = br_float(total_raw)

                    if not descricao or quantidade is None:
                        continue

                    itens.append({
                        "idx_item":               str(idx).zfill(5),
                        "codigo_interno_oc":       "",    # Pavini nao tem codigo Krona na OC
                        "descricao_original":      descricao,
                        "descricao_reconstruida":  descricao,
                        "quantidade":              quantidade,
                        "unidade_original":        unidade,
                        "unidade_normalizada":     unidade,
                        "valor_unitario":          valor_unit,
                        "valor_total":             valor_total,
                        "pagina":                  numero_pagina,
                        "linhas_origem":           [idx],
                        "score_extracao":          0.97,
                        "status_extracao":         "ok",
                        "observacoes":             ["formato_pavini"],
                    })
                    idx += 1

    return itens


# ================================================================
# FUNÇÃO PRINCIPAL
# ================================================================

def extrair_itens_oc(caminho_pdf: str, caminho_debug: str | None = None) -> List[Dict[str, Any]]:

    # ── PRIORIDADE 1: SIENGE/STARIAN ─────────────────────────
    if detectar_formato_sienge(caminho_pdf):
        resultado = extrair_oc_sienge(caminho_pdf)
        if resultado["ok"] and resultado["itens"]:
            itens_normalizados = []
            for i, item in enumerate(resultado["itens"], 1):
                itens_normalizados.append({
                    "idx_item":               str(i).zfill(5),
                    "codigo_interno_oc":       item["codigo_cliente"],
                    "descricao_original":      item["descricao"],
                    "descricao_reconstruida":  item["descricao"],
                    "quantidade":              item["quantidade"],
                    "unidade_original":        item["unidade"],
                    "unidade_normalizada":     item["unidade"],
                    "preco_unitario":          item["preco_unitario"],
                    "preco_total":             item["preco_total"],
                    "data_entrega":            item["data_entrega"],
                    "status_extracao":         "extraido",
                    "observacoes":             ["formato_sienge"],
                })
            if caminho_debug:
                try:
                    with open(caminho_debug, "w", encoding="utf-8") as f:
                        f.write(f"FORMATO: SIENGE/STARIAN\n")
                        f.write(f"Pedido: {resultado['numero_oc']}\n")
                        f.write(f"Cliente: {resultado['cliente']}\n")
                        f.write(f"Total de itens: {len(itens_normalizados)}\n\n")
                        for item in itens_normalizados:
                            f.write(f"[{item['status_extracao']}] {item['idx_item']} | {item['descricao_reconstruida']}\n")
                            f.write(f"  codigo={item['codigo_interno_oc']} | qtd={item['quantidade']} {item['unidade_normalizada']}\n")
                except Exception:
                    pass
            return itens_normalizados

    # ── PRIORIDADE 2: BRASAL / CLOSER / ARTESANO ─────────────
    if _detectar_formato_brasal(caminho_pdf):
        itens = _extrair_itens_brasal(caminho_pdf)
        if itens:
            if caminho_debug:
                try:
                    with open(caminho_debug, "w", encoding="utf-8") as f:
                        f.write("FORMATO: BRASAL/CLOSER\n")
                        f.write(f"Total de itens: {len(itens)}\n\n")
                        for item in itens:
                            f.write(f"[{item['status_extracao']}] {item['idx_item']} | {item['descricao_reconstruida']}\n")
                            f.write(f"  codigo_interno={item['codigo_interno_oc']} | qtd={item['quantidade']} {item['unidade_normalizada']}\n")
                except Exception:
                    pass
            return itens

    # ── PRIORIDADE 3: PAVINI SEROA ENGENHARIA ────────────────
    if _detectar_formato_pavini(caminho_pdf):
        itens = _extrair_itens_pavini(caminho_pdf)
        if itens:
            if caminho_debug:
                try:
                    with open(caminho_debug, "w", encoding="utf-8") as f:
                        f.write("FORMATO: PAVINI SEROA ENGENHARIA\n")
                        f.write(f"Total de itens: {len(itens)}\n\n")
                        for item in itens:
                            f.write(f"[{item['status_extracao']}] {item['idx_item']} | {item['descricao_reconstruida']}\n")
                            f.write(f"  qtd={item['quantidade']} {item['unidade_normalizada']} | unit=R${item['valor_unitario']}\n")
                except Exception:
                    pass
            return itens

    # ── PRIORIDADE 4: UAU / MRV / KRONA (fluxo original) ────
    linhas_probe = extrair_linhas_pdf(caminho_pdf)
    linhas_probe = normalizar_linhas(linhas_probe)
    formato      = detectar_formato_documento(linhas_probe)

    if formato == "UAU":
        linhas = extrair_linhas_pdf_uau(caminho_pdf)
    else:
        linhas = linhas_probe

    linhas = normalizar_linhas(linhas) if formato == "UAU" else linhas
    linhas = classificar_linhas_documento(linhas)

    blocos = agrupar_blocos_itens(linhas)
    itens  = estruturar_blocos_em_itens(blocos)
    itens  = validar_itens_extraidos(itens)

    if caminho_debug:
        gerar_relatorio_extracao(itens, caminho_debug)

    resultado = []
    for item in itens:
        resultado.append({
            "idx_item":               item.idx_item,
            "codigo_interno_oc":       item.codigo_interno_oc,
            "descricao_original":      item.descricao_original,
            "descricao_reconstruida":  item.descricao_reconstruida,
            "quantidade":              item.quantidade,
            "unidade_original":        item.unidade_original,
            "unidade_normalizada":     item.unidade_normalizada,
            "valor_unitario":          item.valor_unitario,
            "valor_total":             item.valor_total,
            "pagina":                  item.pagina,
            "linhas_origem":           item.linhas_origem,
            "score_extracao":          item.score_extracao,
            "status_extracao":         item.status_extracao,
            "observacoes":             item.observacoes,
        })

    # fallback generico — clientes nao cadastrados
    if not resultado:
        try:
            from extracao_oc.extrator_generico import detectar_generico, extrair_itens_generico
            if detectar_generico(caminho_pdf):
                itens = extrair_itens_generico(caminho_pdf)
                if itens:
                    return itens, "GENERICO"
        except Exception as e:
            print(f"[EXTRATOR] Erro no extrator generico: {e}")

    return resultado
