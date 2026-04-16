from typing import List, Dict, Any

from extracao_oc.pdf_reader import extrair_linhas_pdf, extrair_linhas_pdf_uau, extrair_linhas_pdf_brasal
from extracao_oc.normalizador_oc import normalizar_linhas
from extracao_oc.segmentador_documento import classificar_linhas_documento, detectar_formato_documento
from extracao_oc.agrupador_itens import agrupar_blocos_itens
from extracao_oc.estruturador_item import estruturar_blocos_em_itens
from extracao_oc.validacao_extracao_oc import validar_itens_extraidos
from extracao_oc.debug_extracao import gerar_relatorio_extracao
import re as _re


def _detectar_formato_brasal(caminho_pdf: str) -> bool:
    """Detecta se o PDF e do formato Brasal/Closer verificando o texto bruto."""
    try:
        import pdfplumber
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = pdf.pages[0].extract_text() or ""
            texto_upper = texto.upper()
            return (
                "KRONA/KRONA" in texto_upper
                and "CÓDIGO" in texto_upper
                and "QUANTIDADE" in texto_upper
                and "UNIDADE" in texto_upper
            )
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
        cod = limpar_codigo(limpar(row[0]))
        un  = limpar(row[2]).upper()
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
    idx = 1

    with pdfplumber.open(caminho_pdf) as pdf:
        for numero_pagina, pagina in enumerate(pdf.pages, start=1):
            for tabela in pagina.extract_tables():
                for row in tabela:
                    if not e_item(row): continue

                    ncols = len(row)
                    codigo_raw   = limpar_codigo(limpar(row[0]))  # codigo interno Brasal
                    unidade      = limpar(row[2]).upper()
                    qtd_raw      = limpar(row[1])
                    descricao    = limpar_desc(limpar(row[3]))

                    if ncols >= 12:
                        preco_raw = limpar(row[6])
                        total_raw = limpar(row[11])
                    else:
                        preco_raw = limpar(row[4]) if ncols > 4 else ""
                        total_raw = limpar(row[8]) if ncols > 8 else ""

                    quantidade   = br_float(qtd_raw)
                    valor_unit   = br_float(preco_raw)
                    valor_total  = br_float(total_raw)

                    itens.append({
                        "idx_item":             idx,
                        "codigo_interno_oc":    codigo_raw,  # codigo interno Brasal — nao e codigo Krona
                        "descricao_original":   descricao,
                        "descricao_reconstruida": descricao,
                        "quantidade":           quantidade,
                        "unidade_original":     unidade,
                        "unidade_normalizada":  unidade,
                        "valor_unitario":       valor_unit,
                        "valor_total":          valor_total,
                        "pagina":               numero_pagina,
                        "linhas_origem":        [idx],
                        "score_extracao":       0.98,
                        "status_extracao":      "ok",
                        "observacoes":          ["formato_brasal"],
                    })
                    idx += 1

    return itens


def extrair_itens_oc(caminho_pdf: str, caminho_debug: str | None = None) -> List[Dict[str, Any]]:
    # detecta formato Brasal/Closer antes de tudo
    if _detectar_formato_brasal(caminho_pdf):
        itens = _extrair_itens_brasal(caminho_pdf)
        if itens:
            if caminho_debug:
                try:
                    # debug simplificado para formato Brasal
                    with open(caminho_debug, "w", encoding="utf-8") as f:
                        f.write("FORMATO: BRASAL/CLOSER\n")
                        f.write(f"Total de itens: {len(itens)}\n\n")
                        for item in itens:
                            f.write(f"[{item['status_extracao']}] {item['idx_item']} | {item['descricao_reconstruida']}\n")
                            f.write(f"  codigo_interno={item['codigo_interno_oc']} | qtd={item['quantidade']} {item['unidade_normalizada']}\n")
                except Exception:
                    pass
            return itens

    # pre-leitura para detectar o formato sem usar o extrator definitivo ainda
    linhas_probe = extrair_linhas_pdf(caminho_pdf)
    linhas_probe = normalizar_linhas(linhas_probe)
    formato = detectar_formato_documento(linhas_probe)

    # UAU usa extract_tables() para preservar a estrutura de colunas
    # MRV e Krona continuam usando o extrator de texto original
    if formato == "UAU":
        linhas = extrair_linhas_pdf_uau(caminho_pdf)
    else:
        linhas = linhas_probe

    linhas = normalizar_linhas(linhas) if formato == "UAU" else linhas
    linhas = classificar_linhas_documento(linhas)

    blocos = agrupar_blocos_itens(linhas)
    itens = estruturar_blocos_em_itens(blocos)
    itens = validar_itens_extraidos(itens)

    if caminho_debug:
        gerar_relatorio_extracao(itens, caminho_debug)

    resultado = []
    for item in itens:
        resultado.append({
            "idx_item": item.idx_item,
            "codigo_interno_oc": item.codigo_interno_oc,
            "descricao_original": item.descricao_original,
            "descricao_reconstruida": item.descricao_reconstruida,
            "quantidade": item.quantidade,
            "unidade_original": item.unidade_original,
            "unidade_normalizada": item.unidade_normalizada,
            "valor_unitario": item.valor_unitario,
            "valor_total": item.valor_total,
            "pagina": item.pagina,
            "linhas_origem": item.linhas_origem,
            "score_extracao": item.score_extracao,
            "status_extracao": item.status_extracao,
            "observacoes": item.observacoes,
        })

    return resultado