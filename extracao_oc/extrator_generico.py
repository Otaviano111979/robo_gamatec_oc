# -*- coding: utf-8 -*-
"""
extracao_oc/extrator_generico.py

Extrator deterministico para OCs de clientes nao cadastrados (sem IA).

Estrategias em ordem:
  1. TEMPLATE  — formato ja aprendido para este cliente (dados/formatos_clientes.json)
  2. TABELA_CABECALHO      — tabela com palavras de cabecalho reconheciveis
  3. TABELA_CONTEUDO       — tabela sem cabecalho; colunas classificadas por conteudo
                             (unidades, numeros, texto longo)
  4. TEXTO                 — linhas de texto puro com regex de item/descricao/unidade/qtd

Todo cliente desconhecido que extrai com sucesso aprende um template deterministico:
o proximo PDF com a mesma assinatura usa a estrategia vencedora direto.
"""

import os
import re
import json

import pdfplumber

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO_FORMATOS_CLIENTES = os.path.join(BASE_DIR, "dados", "formatos_clientes.json")

UNIDADES = {
    "UN", "UND", "UNID", "PC", "PCS", "PÇ", "PÇS", "PCE",
    "M", "MT", "MTS", "MTR", "METRO", "M2", "M²", "M3", "M³", "KG", "TON",
    "CX", "CAIXA", "RL", "ROLO", "BR", "BRAÇO", "LT", "L", "GL", "GALAO",
    "FD", "FDO", "FARD", "JG", "JGO", "JD", "JARRA", "PAR", "PR",
    "BCT", "SAC", "SC", "TUBO", "BAR",
}

PALAVRAS_CABECALHO = {"item", "codigo", "cod", "descricao", "descr", "produto",
                      "material", "insumo", "un", "unid", "um", "qtde", "qtd",
                      "quantidade", "quant", "preco", "preço", "valor", "unit"}

_RE_NUM = re.compile(r"^\s*\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?\s*$|^\s*\d+(?:\.\d+)?\s*$")


# ============================================================
# API publica
# ============================================================

def detectar_generico(caminho_pdf: str) -> bool:
    return True


def extrair_itens_generico(caminho_pdf: str) -> list:
    """Contrato antigo: retorna apenas a lista de itens."""
    itens, _meta = extrair_itens_generico_com_meta(caminho_pdf)
    return itens


def extrair_itens_generico_com_meta(caminho_pdf: str):
    """Retorna (itens, meta). meta = {"estrategia": str, "itens": int}."""
    assinatura = _assinatura_pdf(caminho_pdf)

    # 1. template aprendido
    template = _buscar_template(assinatura)
    if template:
        estrategia = template.get("estrategia", "")
        itens = _executar_estrategia(caminho_pdf, estrategia)
        if itens:
            _touch_template(template["chave"], len(itens))
            return itens, {"estrategia": estrategia, "itens": len(itens), "template": True}

    # 2..4 estrategias live
    melhor_itens, melhor_meta = [], {"estrategia": "NENHUMA", "itens": 0}
    for estrategia in ("TABELA_CABECALHO", "TABELA_CONTEUDO", "TEXTO"):
        try:
            itens = _executar_estrategia(caminho_pdf, estrategia)
        except Exception as e:
            print(f"[EXTRATOR GENERICO] {estrategia} falhou: {e}")
            continue
        if len(itens) > len(melhor_itens):
            melhor_itens, melhor_meta = itens, {"estrategia": estrategia, "itens": len(itens)}
        if len(itens) >= 3:
            break

    if melhor_itens and assinatura:
        _aprender_template(assinatura, melhor_meta["estrategia"], len(melhor_itens))
    return melhor_itens, melhor_meta


def _executar_estrategia(caminho_pdf: str, estrategia: str) -> list:
    if estrategia == "TABELA_CABECALHO":
        return _estrategia_tabela_cabecalho(caminho_pdf)
    if estrategia == "TABELA_CONTEUDO":
        return _estrategia_tabela_conteudo(caminho_pdf)
    if estrategia == "TEXTO":
        return _estrategia_texto(caminho_pdf)
    return []


# ============================================================
# Estrategia 2 — tabela com cabecalho reconhecivel
# ============================================================

def _estrategia_tabela_cabecalho(caminho_pdf: str) -> list:
    itens = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            for tabela in pagina.extract_tables() or []:
                if not tabela:
                    continue
                idx_cab = _detectar_cabecalho(tabela)
                if idx_cab is None:
                    continue
                for linha in tabela[idx_cab + 1:]:
                    item = _parsear_linha(linha, tabela[idx_cab])
                    if item:
                        itens.append(item)
    return itens


def _detectar_cabecalho(tabela: list):
    for i, linha in enumerate(tabela[:5]):
        if not linha:
            continue
        celulas = [str(c or "").lower().strip() for c in linha]
        if sum(1 for c in celulas if any(p in c for p in PALAVRAS_CABECALHO)) >= 3:
            return i
    return None


def _parsear_linha(linha: list, cabecalho: list):
    if not linha or all(c is None or str(c).strip() == "" for c in linha):
        return None
    mapa = {}
    for i, col in enumerate(cabecalho or []):
        col_lower = str(col or "").lower().strip()
        if i >= len(linha):
            continue
        val = str(linha[i] or "").strip()
        if any(p in col_lower for p in ["descr", "descri", "produto", "material", "insumo"]):
            mapa["descricao"] = val.replace("\n", " ").replace("\r", " ").strip()
        elif any(p in col_lower for p in ["qtde", "qtd", "quant"]):
            mapa["quantidade"] = _num(val)
        elif any(p in col_lower for p in ["un", "unid", "um"]):
            val_limpo = val.replace(",", "").replace(".", "").strip()
            if not (val_limpo.isdigit() or val_limpo == ""):
                mapa["unidade"] = val
        elif any(p in col_lower for p in ["cod"]):
            mapa["codigo_cliente"] = val
        elif "item" in col_lower:
            mapa["num_item"] = val
        elif any(p in col_lower for p in ["preco", "preço", "valor", "unit"]):
            mapa["preco_unitario"] = _num(val)
    if not _descricao_valida(mapa.get("descricao", "")):
        return None
    if not mapa.get("quantidade") or mapa["quantidade"] <= 0:
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


# ============================================================
# Estrategia 3 — tabela SEM cabecalho: colunas por conteudo
# ============================================================

def _estrategia_tabela_conteudo(caminho_pdf: str) -> list:
    itens = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            for tabela in pagina.extract_tables() or []:
                itens_tabela = _parsear_tabela_por_conteudo(tabela)
                itens.extend(itens_tabela)
    return itens


def _eh_unidade(texto: str) -> bool:
    t = re.sub(r"[.\s:\n]", "", str(texto or "")).upper()
    return t in UNIDADES if t else False


def _celula_num(texto: str) -> bool:
    v = str(texto or "").replace("\n", " ").strip()
    return bool(_RE_NUM.match(v)) and any(ch.isdigit() for ch in v)


def _parsear_tabela_por_conteudo(tabela):
    if not tabela or len(tabela) < 3:
        return []
    linhas = [r for r in tabela if r and any(str(c or "").strip() for c in r)]
    ncol = max(len(r) for r in linhas)
    if ncol < 3:
        return []

    col_unidade, col_qtd, col_desc, col_cod, col_preco = None, None, None, None, None
    melhor_un_frac = 0.0
    for j in range(ncol):
        vals = [str(linha[j] or "").strip() for linha in linhas if j < len(linha)]
        nao_vazias = [v for v in vals if v]
        if not nao_vazias:
            continue
        frac_un = sum(1 for v in nao_vazias if _eh_unidade(v)) / len(nao_vazias)
        if frac_un > melhor_un_frac:
            melhor_un_frac, col_unidade = frac_un, j

    if col_unidade is None or melhor_un_frac < 0.4:
        return []

    # quantidade: coluna numerica adjacente a unidade (preferindo esquerda), senao a numerica mais proxima
    numerica = []
    for j in range(ncol):
        vals = [str(linha[j] or "").strip() for linha in linhas
                if j < len(linha) and str(linha[j] or "").strip()]
        if vals and sum(1 for v in vals if _celula_num(v)) / len(vals) >= 0.6:
            numerica.append(j)
    adjacentes = [j for j in numerica if abs(j - col_unidade) == 1]
    if adjacentes:
        col_qtd = adjacentes[0]
    elif numerica:
        col_qtd = numerica[0]
    else:
        return []

    # descricao: coluna com texto longo e letras, excluidas unidade/qtd
    melhor_len, col_desc = 0, None
    for j in range(ncol):
        if j in (col_unidade, col_qtd):
            continue
        vals = [re.sub(r"\s+", " ", str(linha[j] or "")).strip() for linha in linhas
                if j < len(linha) and str(linha[j] or "").strip()]
        longas = [v for v in vals if len(v) >= 8 and sum(c.isalpha() for c in v) >= 5]
        if longas:
            medio = sum(len(v) for v in longas) / len(longas)
            if medio > melhor_len:
                melhor_len, col_desc = medio, j
    if col_desc is None:
        return []

    # codigo: coluna a esquerda da descricao com valores curtos alfanumericos
    for j in range(col_desc):
        if j in (col_unidade, col_qtd):
            continue
        vals = [str(linha[j] or "").strip() for linha in linhas
                if j < len(linha) and str(linha[j] or "").strip()]
        curtos = [v for v in vals if 1 < len(v) <= 12 and not _eh_unidade(v)]
        if vals and len(curtos) / len(vals) >= 0.6:
            col_cod = j
            break

    # preco: coluna numerica a direita da unidade que nao seja qtd/desc/cod
    for j in numerica:
        if j not in (col_qtd, col_desc, col_cod) and j > col_unidade:
            col_preco = j
            break

    itens = []
    for linha in linhas:
        def cell(j):
            if j is None or j >= len(linha):
                return ""
            return re.sub(r"\s+", " ", str(linha[j] or "")).strip()

        # pula linhas de cabecalho (>=2 celulas sao palavras de cabecalho)
        palavras_linha = [str(c or "").strip().lower() for c in linha]
        n_header = sum(1 for v in palavras_linha
                       if v and any(p == v.rstrip('.').strip() for p in PALAVRAS_CABECALHO))
        if n_header >= 2:
            continue

        descricao = cell(col_desc)
        if not _descricao_valida(descricao):
            continue
        quantidade = _num(cell(col_qtd))
        if not quantidade or quantidade <= 0:
            continue
        unidade = cell(col_unidade)
        item = {
            "num_item":       "",
            "codigo_cliente": cell(col_cod),
            "descricao_oc":   descricao,
            "unidade":        unidade if _eh_unidade(unidade) else "PC",
            "quantidade":     quantidade,
            "preco_unitario": _num(cell(col_preco)) if col_preco is not None else None,
            "observacoes":    ["CLIENTE_NOVO", "EXTRATOR_GENERICO_CONTEUDO"],
        }
        itens.append(item)
    return itens


# ============================================================
# Estrategia 4 — texto puro, variantes de regex deterministico
# ============================================================

_UN = r"UNID|UND|UN|PÇS|PÇ|PCS|PC|PCE|MTS|MT|M²|M³|M2|M3|KG|CX|RL|BR|LT|GL|FD|JG|PAR"
_RE_TEXTO_1 = re.compile(
    rf"^\s*(\d{{1,3}})\s+(\S{{2,15}})\s+(.+?\d.+?)\s+({_UN})[\s.]*+(\d[\d.,]*)", re.IGNORECASE)
_RE_TEXTO_2 = re.compile(
    rf"^\s*(\d{{1,4}})[.\-\)]\s+(.+?)\s+({_UN})[\s.]*+(\d[\d.,]*)", re.IGNORECASE)
_RE_TEXTO_3 = re.compile(
    rf"^\s*(.+?[a-zA-ZÀ-ÿ]{{8,}}?)\s+(\d[\d.,]*)\s+({_UN})\b", re.IGNORECASE)


def _estrategia_texto(caminho_pdf: str) -> list:
    itens = []
    vistos = set()
    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text() or ""
            for linha in texto.split("\n"):
                linha = linha.strip()
                if len(linha) < 12:
                    continue
                item = None
                m = _RE_TEXTO_1.match(linha)
                if m:
                    item = {"num_item": m.group(1), "codigo_cliente": m.group(2),
                            "descricao_oc": _limpa(m.group(3)), "unidade": m.group(4).upper(),
                            "quantidade": _num(m.group(5))}
                else:
                    m = _RE_TEXTO_2.match(linha)
                    if m:
                        item = {"num_item": m.group(1), "codigo_cliente": "",
                                "descricao_oc": _limpa(m.group(2)), "unidade": m.group(3).upper(),
                                "quantidade": _num(m.group(4))}
                    else:
                        m = _RE_TEXTO_3.match(linha)
                        if m and not re.match(r"^\s*(total|sub\s*total)", m.group(1), re.IGNORECASE):
                            item = {"num_item": "", "codigo_cliente": "",
                                    "descricao_oc": _limpa(m.group(1)), "unidade": m.group(3).upper(),
                                    "quantidade": _num(m.group(2))}
                if item and _descricao_valida(item["descricao_oc"]) \
                        and item.get("quantidade") and item["quantidade"] > 0:
                    chave = (item["descricao_oc"][:40].upper(), item["quantidade"])
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    item["preco_unitario"] = None
                    item["observacoes"] = ["CLIENTE_NOVO", "EXTRATOR_GENERICO_TEXTO"]
                    itens.append(item)
    return itens


def _limpa(v: str) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _descricao_valida(desc: str) -> bool:
    if not desc or len(desc) < 5:
        return False
    if sum(c.isalpha() for c in desc) < 3:
        return False
    up = desc.upper()
    if any(p in up for p in ("TOTAL", "SUBTOTAL", "DESCONTO", "FRETE", "VALOR", "OBS:", "PAGINA")):
        return False
    return True


def _num(texto):
    if not texto:
        return None
    limpo = re.sub(r"[^\d,.]", "", str(texto))
    if not limpo:
        return None
    try:
        return float(limpo.replace(".", "").replace(",", "."))
    except Exception:
        try:
            return float(limpo.replace(",", "."))
        except Exception:
            return None


# ============================================================
# Templates determinísticos por cliente (fase 3)
# ============================================================

def _carregar_formatos() -> dict:
    if os.path.exists(CAMINHO_FORMATOS_CLIENTES):
        try:
            with open(CAMINHO_FORMATOS_CLIENTES, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _salvar_formatos(formatos: dict) -> None:
    os.makedirs(os.path.dirname(CAMINHO_FORMATOS_CLIENTES), exist_ok=True)
    with open(CAMINHO_FORMATOS_CLIENTES, "w", encoding="utf-8") as f:
        json.dump(formatos, f, ensure_ascii=False, indent=2)


def _assinatura_pdf(caminho_pdf: str) -> str:
    """Assinatura estavel do formato: texto da 1a pagina sem numeros."""
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = pdf.pages[0].extract_text() or ""
        normal = re.sub(r"\d+", "#", texto.upper())
        normal = re.sub(r"[^A-Z# ]+", " ", normal)
        normal = re.sub(r"\s+", " ", normal).strip()
        return normal[:400]
    except Exception:
        return ""


def _tokens(assinatura: str) -> set:
    return {t for t in assinatura.split() if len(t) >= 4}


def _buscar_template(assinatura: str):
    if not assinatura:
        return None
    alvos = _tokens(assinatura)
    if not alvos:
        return None
    melhor, melhor_frac, melhor_chave = None, 0.0, None
    for chave, tpl in _carregar_formatos().items():
        guardados = _tokens(tpl.get("assinatura", ""))
        if not guardados:
            continue
        frac = len(alvos & guardados) / len(guardados)
        if frac > melhor_frac:
            melhor, melhor_frac = tpl, frac
            melhor_chave = chave
    if melhor and melhor_frac >= 0.7:
        melhor = dict(melhor)
        melhor["chave"] = melhor_chave
        return melhor
    return None


def _aprender_template(assinatura: str, estrategia: str, itens: int) -> None:
    formatos = _carregar_formatos()
    chave = assinatura[:80]
    entrada = formatos.get(chave, {})
    entrada.update({
        "assinatura": assinatura,
        "estrategia": estrategia,
        "vezes_usado": entrada.get("vezes_usado", 0) + 1,
        "ultimo_itens": itens,
    })
    formatos[chave] = entrada
    _salvar_formatos(formatos)


def _touch_template(chave: str, itens: int) -> None:
    formatos = _carregar_formatos()
    if chave in formatos:
        formatos[chave]["vezes_usado"] = formatos[chave].get("vezes_usado", 0) + 1
        formatos[chave]["ultimo_itens"] = itens
        _salvar_formatos(formatos)
