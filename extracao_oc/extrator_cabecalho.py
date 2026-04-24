# -*- coding: utf-8 -*-
"""
extracao_oc/extrator_cabecalho.py

Extrai dados estruturados do cabeçalho e rodapé de PDFs de OC e Cotação.
Suporta os formatos: SIENGE/STARIAN, UAU, MRV, BRASAL/CLOSER, KRONA direto.

Retorna um dict padronizado com:
  - empresa     : nome, cnpj, ie, endereco, telefone, email
  - obra        : nome, codigo, endereco_entrega
  - documento   : numero, data, tipo, total, cond_pagamento
  - contatos    : lista de {nome, cargo, email, telefone}
  - confianca   : 0.0 a 1.0 — score de confiança da extração
  - revisao     : True se confiança abaixo do threshold
  - formato     : formato detectado do PDF
"""

import re
import pdfplumber
from typing import Optional


# threshold abaixo do qual o registro é marcado para revisão manual
CONFIANCA_MINIMA = 0.60


# ============================================================
# UTILITÁRIOS
# ============================================================

def _limpar(texto) -> str:
    if not texto:
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip()


def _normalizar_cnpj(texto: str) -> str:
    """Remove formatação e mantém apenas dígitos. Ex: '55.461.477/0001-66' → '55461477000166'"""
    return re.sub(r"\D", "", str(texto or ""))


def _normalizar_telefone(texto: str) -> str:
    """Remove formatação. Ex: '(61)99999-9999' → '61999999999'"""
    return re.sub(r"\D", "", str(texto or ""))


def _extrair_cidade_estado_cep(endereco: str):
    """
    Tenta extrair cidade, estado e CEP de uma string de endereço.
    Ex: 'VALPARAÍSO DE GOIÁS - GO\n72870-136'
    """
    cidade = estado = cep = ""

    # CEP: XXXXX-XXX ou XXXXXXXX
    m_cep = re.search(r"\b(\d{5}-?\d{3})\b", endereco)
    if m_cep:
        cep = re.sub(r"\D", "", m_cep.group(1))

    # Estado: UF de 2 letras precedida de " - " ou " / "
    m_uf = re.search(r"[-/\s]([A-Z]{2})\b", endereco.upper())
    if m_uf:
        estado = m_uf.group(1)

    # Cidade: texto antes da UF
    if estado:
        partes = re.split(r"[-/]" + estado, endereco.upper())
        if partes:
            trecho = partes[0].strip().strip("-").strip()
            # pega a última linha (normalmente é a cidade)
            linhas = [l.strip() for l in trecho.splitlines() if l.strip()]
            if linhas:
                cidade = linhas[-1].title()

    return cidade, estado, cep


def _resultado_vazio(formato: str, motivo: str) -> dict:
    return {
        "empresa":   {},
        "obra":      {},
        "documento": {},
        "contatos":  [],
        "confianca": 0.0,
        "revisao":   True,
        "formato":   formato,
        "motivo_falha": motivo,
    }


# ============================================================
# EXTRATOR SIENGE / STARIAN
# Estrutura de tabelas bem definida — alta confiança
# ============================================================

def _extrair_sienge(caminho_pdf: str) -> dict:
    empresa   = {}
    obra      = {}
    documento = {}
    contatos  = []
    campos_ok = 0
    campos_total = 8  # nome, cnpj, email, tel, endereco, numero_doc, data, obra

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            todas_tabelas = []
            for page in pdf.pages:
                todas_tabelas.extend(page.extract_tables() or [])

        # monta índice label→valor das tabelas
        idx = {}
        for tabela in todas_tabelas:
            for row in (tabela or []):
                if not row or len(row) < 2:
                    continue
                chave = _limpar(row[0]).lower()
                valor = _limpar(row[1])
                if chave and valor:
                    idx[chave] = valor
                # linha com 4 colunas: chave1, val1, chave2, val2
                if len(row) >= 4 and row[2] and row[3]:
                    chave2 = _limpar(row[2]).lower()
                    valor2 = _limpar(row[3])
                    if chave2 and valor2:
                        idx[chave2] = valor2

        # ── documento ──
        num = idx.get("pedido") or idx.get("cotação") or idx.get("numero") or ""
        data = idx.get("data do pedido") or idx.get("data de envio") or idx.get("data") or ""
        tipo = "COTACAO" if ("cotação" in idx or "cotacao" in idx) else "OC"
        total_str = (
            idx.get("total do pedido") or
            idx.get("total dos insumos") or
            idx.get("total da cotação") or ""
        )
        try:
            total = float(re.sub(r"[^\d,]", "", total_str).replace(",", ".")) if total_str else None
        except Exception:
            total = None

        documento = {
            "numero":           _limpar(num),
            "data":             _limpar(data),
            "tipo":             tipo,
            "total_valor":      total,
            "cond_pagamento":   _limpar(idx.get("cond. pagamento", "")),
            "sistema_origem":   "SIENGE",
        }
        if num:   campos_ok += 1
        if data:  campos_ok += 1

        # ── empresa (faturamento) ──
        nome_emp  = idx.get("nome", "")
        end_emp   = idx.get("endereço", "")
        cnpj_raw  = idx.get("cnpj", "") or idx.get("cnpj/cpf", "")
        ie_raw    = idx.get("ie", "")
        tel_raw   = idx.get("telefone", "")
        email_raw = idx.get("e-mail", "") or idx.get("email", "")

        cidade, estado, cep = _extrair_cidade_estado_cep(end_emp)

        empresa = {
            "nome":      _limpar(nome_emp),
            "cnpj":      _normalizar_cnpj(cnpj_raw),
            "ie":        _limpar(ie_raw),
            "endereco":  _limpar(end_emp.splitlines()[0] if end_emp else ""),
            "cidade":    cidade,
            "estado":    estado,
            "cep":       cep,
            "telefone":  _normalizar_telefone(tel_raw),
            "email":     _limpar(email_raw).lower(),
        }
        if nome_emp:   campos_ok += 1
        if cnpj_raw:   campos_ok += 1
        if email_raw:  campos_ok += 1
        if tel_raw:    campos_ok += 1
        if end_emp:    campos_ok += 1

        # ── obra ──
        obra_raw = idx.get("obra", "")
        entrega  = idx.get("local entrega", "") or idx.get("local de entrega", "")

        cod_obra = nome_obra = ""
        if obra_raw:
            m = re.match(r"^(\d+)\s*[-–]\s*(.+)$", obra_raw)
            if m:
                cod_obra  = m.group(1).strip()
                nome_obra = m.group(2).strip()
            else:
                nome_obra = obra_raw

        cidade_obra, estado_obra, cep_obra = _extrair_cidade_estado_cep(entrega)

        obra = {
            "codigo":           cod_obra,
            "nome":             nome_obra,
            "endereco_entrega": _limpar(entrega),
            "cidade":           cidade_obra,
            "estado":           estado_obra,
            "cep":              cep_obra,
        }
        if obra_raw: campos_ok += 1

        # ── contato a partir do email ──
        if email_raw:
            cargo = "financeiro" if "financeiro" in email_raw.lower() else "compras"
            contatos.append({
                "nome":     "",
                "cargo":    cargo,
                "email":    _limpar(email_raw).lower(),
                "telefone": _normalizar_telefone(tel_raw),
                "origem":   "cabecalho_pdf_sienge",
            })

        # contato do campo "contato" se existir
        contato_nome = idx.get("contato", "")
        if contato_nome and contato_nome.lower() not in ("hugo", ""):
            contatos.append({
                "nome":     _limpar(contato_nome),
                "cargo":    "contato",
                "email":    "",
                "telefone": "",
                "origem":   "cabecalho_pdf_sienge",
            })

    except Exception as e:
        return _resultado_vazio("SIENGE", f"erro_extracao: {e}")

    confianca = round(campos_ok / campos_total, 2)

    return {
        "empresa":   empresa,
        "obra":      obra,
        "documento": documento,
        "contatos":  contatos,
        "confianca": confianca,
        "revisao":   confianca < CONFIANCA_MINIMA,
        "formato":   "SIENGE",
    }


# ============================================================
# EXTRATOR UAU / GPL / CITY
# Estrutura via extract_text — tabelas menos previsíveis
# ============================================================

def _extrair_uau(caminho_pdf: str) -> dict:
    empresa   = {}
    obra      = {}
    documento = {}
    contatos  = []
    campos_ok = 0
    campos_total = 7

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = ""
            for page in pdf.pages:
                texto += (page.extract_text() or "") + "\n"

        linhas = texto.splitlines()

        def buscar(padroes, texto_busca=texto):
            for p in padroes:
                m = re.search(p, texto_busca, re.IGNORECASE)
                if m:
                    return _limpar(m.group(1))
            return ""

        # número da OC / cotação
        num = buscar([
            r"O\.C\.\s*[:\-]?\s*(\d+)",
            r"COT\.\s*[:\-]?\s*(\d+)",
            r"ORDEM DE COMPRA[:\s]+(\d+)",
            r"PEDIDO[:\s]+(\d+)",
        ])
        data = buscar([
            r"DATA[:\s]+(\d{2}/\d{2}/\d{4})",
            r"(\d{2}/\d{2}/\d{4})",
        ])
        tipo = "COTACAO" if re.search(r"COTAC|COT\.", texto, re.IGNORECASE) else "OC"

        documento = {
            "numero": num, "data": data, "tipo": tipo,
            "total_valor": None, "cond_pagamento": "",
            "sistema_origem": "UAU",
        }
        if num:  campos_ok += 1
        if data: campos_ok += 1

        # empresa — busca por padrões de cabeçalho UAU
        nome_emp  = buscar([r"(?:EMPRESA|CLIENTE|RAZÃO SOCIAL)[:\s]+([A-Z][^\n]{5,80})"])
        cnpj_raw  = buscar([r"CNPJ[:\s/]*([\d]{2}\.[\d]{3}\.[\d]{3}/[\d]{4}-[\d]{2})"])
        tel_raw   = buscar([r"(?:FONE|TEL|TELEFONE)[:\s]*([\(\d][^\n]{6,20})"])
        email_raw = buscar([r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})"])
        end_raw   = buscar([r"(?:ENDEREÇO|ENDERECO)[:\s]+([^\n]{10,120})"])

        cidade, estado, cep = _extrair_cidade_estado_cep(end_raw)

        empresa = {
            "nome": nome_emp, "cnpj": _normalizar_cnpj(cnpj_raw),
            "ie": "", "endereco": end_raw, "cidade": cidade,
            "estado": estado, "cep": cep,
            "telefone": _normalizar_telefone(tel_raw),
            "email": email_raw.lower(),
        }
        if nome_emp:   campos_ok += 1
        if cnpj_raw:   campos_ok += 1
        if email_raw:  campos_ok += 1
        if end_raw:    campos_ok += 1

        # obra
        obra_raw = buscar([
            r"OBRA[:\s]+([^\n]{5,100})",
            r"EMPREENDIMENTO[:\s]+([^\n]{5,100})",
        ])
        entrega = buscar([r"(?:LOCAL|ENTREGA)[:\s]+([^\n]{10,150})"])
        cod_obra = nome_obra = ""
        if obra_raw:
            m = re.match(r"^(\d+)\s*[-–]\s*(.+)$", obra_raw)
            if m:
                cod_obra = m.group(1).strip()
                nome_obra = m.group(2).strip()
            else:
                nome_obra = obra_raw

        cidade_obra, estado_obra, cep_obra = _extrair_cidade_estado_cep(entrega)
        obra = {
            "codigo": cod_obra, "nome": nome_obra,
            "endereco_entrega": entrega,
            "cidade": cidade_obra, "estado": estado_obra, "cep": cep_obra,
        }
        if obra_raw: campos_ok += 1

        if email_raw:
            contatos.append({
                "nome": "", "cargo": "contato",
                "email": email_raw.lower(),
                "telefone": _normalizar_telefone(tel_raw),
                "origem": "cabecalho_pdf_uau",
            })

    except Exception as e:
        return _resultado_vazio("UAU", f"erro_extracao: {e}")

    confianca = round(campos_ok / campos_total, 2)
    return {
        "empresa": empresa, "obra": obra, "documento": documento,
        "contatos": contatos,
        "confianca": confianca,
        "revisao": confianca < CONFIANCA_MINIMA,
        "formato": "UAU",
    }


# ============================================================
# EXTRATOR MRV
# Estrutura tabelada — colunas bem definidas
# ============================================================

def _extrair_mrv(caminho_pdf: str) -> dict:
    empresa   = {}
    obra      = {}
    documento = {}
    contatos  = []
    campos_ok = 0
    campos_total = 6

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = ""
            for page in pdf.pages:
                texto += (page.extract_text() or "") + "\n"

        def buscar(padroes):
            for p in padroes:
                m = re.search(p, texto, re.IGNORECASE)
                if m:
                    return _limpar(m.group(1))
            return ""

        num  = buscar([r"PEDIDO[:\s#]+(\d+)", r"N[ºo°]\s*(\d+)"])
        data = buscar([r"DATA[:\s]+(\d{2}/\d{2}/\d{4})"])
        nome = buscar([r"(?:OBRA|EMPREENDIMENTO)[:\s]+([A-Z][^\n]{4,80})"])
        cnpj = buscar([r"CNPJ[:\s]*([\d]{2}\.[\d]{3}\.[\d]{3}/[\d]{4}-[\d]{2})"])
        end  = buscar([r"(?:ENDEREÇO|ENDERECO)[:\s]+([^\n]{10,120})"])

        documento = {
            "numero": num, "data": data, "tipo": "OC",
            "total_valor": None, "cond_pagamento": "30 dias",
            "sistema_origem": "MRV",
        }
        if num:  campos_ok += 1
        if data: campos_ok += 1

        cidade, estado, cep = _extrair_cidade_estado_cep(end)
        empresa = {
            "nome": nome, "cnpj": _normalizar_cnpj(cnpj),
            "ie": "", "endereco": end, "cidade": cidade,
            "estado": estado, "cep": cep,
            "telefone": "", "email": "",
        }
        if nome: campos_ok += 1
        if cnpj: campos_ok += 1
        if end:  campos_ok += 1

        obra_raw = buscar([r"OBRA[:\s]+([^\n]{5,100})"])
        if obra_raw:
            campos_ok += 1
        cidade_obra, estado_obra, cep_obra = _extrair_cidade_estado_cep(end)
        obra = {
            "codigo": "", "nome": obra_raw,
            "endereco_entrega": end,
            "cidade": cidade_obra, "estado": estado_obra, "cep": cep_obra,
        }

    except Exception as e:
        return _resultado_vazio("MRV", f"erro_extracao: {e}")

    confianca = round(campos_ok / campos_total, 2)
    return {
        "empresa": empresa, "obra": obra, "documento": documento,
        "contatos": contatos,
        "confianca": confianca,
        "revisao": confianca < CONFIANCA_MINIMA,
        "formato": "MRV",
    }


# ============================================================
# EXTRATOR BRASAL / CLOSER
# ============================================================

def _extrair_bloco_brasal(texto: str, marcador_inicio: str, marcador_fim: str = None) -> str:
    """Extrai bloco de texto entre dois marcadores no PDF BRASAL."""
    pattern = marcador_inicio + r"(.*?)" + (marcador_fim or "$")
    m = re.search(pattern, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _buscar_campo_brasal(bloco: str, rotulos: list) -> str:
    """
    Busca valor após rótulo no formato BRASAL.
    Ex: 'Razão Social : INC 41 BRASAL...'
    """
    for rotulo in rotulos:
        p = rotulo + r"\s*:?\s*([^\n:]{3,120})"
        m = re.search(p, bloco, re.IGNORECASE)
        if m:
            val = _limpar(m.group(1))
            # remove lixo que vem após próximo rótulo na mesma linha
            val = re.split(r"\s{2,}[A-Za-zÀ-ú]", val)[0].strip()
            # remove sufixo "Bairro" que cola no endereço
            val = re.sub(r"\s*Bairro\s*$", "", val, flags=re.IGNORECASE).strip()
            if val:
                return val
    return ""


def _extrair_brasal(caminho_pdf: str) -> dict:
    """
    Extrator para OCs BRASAL/CLOSER (sistema Artesano/Marista).
    Estrutura: blocos de texto por seção (DADOS DO FORNECEDOR,
    DADOS PARA FATURAMENTO, DADOS PARA ENTREGA).
    O CLIENTE é a empresa em DADOS PARA FATURAMENTO (Brasal/INC XX).
    """
    empresa   = {}
    obra      = {}
    documento = {}
    contatos  = []
    campos_ok = 0
    campos_total = 8  # num, data, nome, cnpj, end, email, cond, obra

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # ── DOCUMENTO ────────────────────────────────────────────
        m_num  = re.search(r"OC\s*N[oº°][:.]?\s*(\d+)", texto, re.IGNORECASE)
        m_proc = re.search(r"Processo\s*N[oº°][:.]?\s*(\d+)", texto, re.IGNORECASE)
        m_data = re.search(r"Emiss[aã]o[:.]?\s*(\d{2}/\d{2}/\d{4})", texto, re.IGNORECASE)
        m_cond = re.search(r"Cond\.\s*Pagt[oa][:.]?\s*([\d]+\s*dias?)", texto, re.IGNORECASE)
        m_total= re.search(r"Total\s*Pedido\s*[\n\r]\s*([\d.,]+)", texto, re.IGNORECASE)
        m_obra = re.search(r"Centro\s*de\s*Custo[:.]?\s*([^\n]{3,80})", texto, re.IGNORECASE)
        m_inc  = re.search(
            r"(\d{4,6})\s*[-–]\s*(INC\s*\d+\s*[A-Z][^\n]{5,80}?)(?:\s+OC\s*N|\s*$)",
            texto, re.IGNORECASE | re.MULTILINE
        )

        num_doc  = m_num.group(1)  if m_num  else (m_proc.group(1) if m_proc else "")
        data_doc = m_data.group(1) if m_data else ""
        cond_pgt = m_cond.group(1) if m_cond else ""
        total_val= None
        if m_total:
            try:
                total_val = float(m_total.group(1).replace(".", "").replace(",", "."))
            except Exception:
                pass

        # obra: combina centro de custo + linha INC
        cod_obra  = m_inc.group(1).strip()  if m_inc  else ""
        nome_obra = m_inc.group(2).strip()  if m_inc  else (
            m_obra.group(1).strip() if m_obra else ""
        )
        # limpa lixo do final do nome da obra
        nome_obra = re.sub(r"\s+OC\s*N.*$", "", nome_obra, flags=re.IGNORECASE).strip()

        documento = {
            "numero":          num_doc,
            "data":            data_doc,
            "tipo":            "OC",
            "total_valor":     total_val,
            "cond_pagamento":  cond_pgt,
            "sistema_origem":  "BRASAL",
        }
        if num_doc:  campos_ok += 1
        if data_doc: campos_ok += 1

        # ── EMPRESA — bloco DADOS PARA FATURAMENTO (= cliente Brasal) ──
        bloco_fat = _extrair_bloco_brasal(
            texto,
            r"DADOS PARA FATURAMENTO",
            r"DADOS PARA COBRAN"
        )

        nome_emp  = _buscar_campo_brasal(bloco_fat, [r"Raz[aã]o\s+Social"])
        end_emp   = _buscar_campo_brasal(bloco_fat, [r"Endere[cç]o"])
        cnpj_raw  = _buscar_campo_brasal(bloco_fat, [r"CNPJ"])
        ie_raw    = _buscar_campo_brasal(bloco_fat, [r"I\.E\."])
        municipio = _buscar_campo_brasal(bloco_fat, [r"Munic[ií]pio"])
        bairro    = _buscar_campo_brasal(bloco_fat, [r"Bairro"])
        m_cep     = re.search(r"CEP\s*[:.]?\s*([\d]{2}\.?[\d]{3}-[\d]{3})", bloco_fat)
        m_email   = re.search(r"E-?Mail\s*:\s*([^\s\n]+@[^\s\n]+)", bloco_fat, re.IGNORECASE)

        # normaliza CNPJ — remove sufixo "I.E." que pode colar
        cnpj_raw = re.sub(r"\s*I\.?E\..*$", "", cnpj_raw, flags=re.IGNORECASE).strip()

        # normaliza município — remove sufixo "CEP" que pode colar
        municipio = re.sub(r"\s*CEP.*$", "", municipio, flags=re.IGNORECASE).strip()

        cep_emp = re.sub(r"\D", "", m_cep.group(1)) if m_cep else ""
        cidade_emp, estado_emp, _ = _extrair_cidade_estado_cep(municipio)

        email_emp = m_email.group(1).lower().strip() if m_email else ""

        empresa = {
            "nome":     nome_emp,
            "cnpj":     _normalizar_cnpj(cnpj_raw),
            "ie":       ie_raw if ie_raw.upper() != "ISENTO" else "ISENTO",
            "endereco": end_emp,
            "bairro":   bairro,
            "cidade":   cidade_emp or _limpar(municipio.split("-")[0]),
            "estado":   estado_emp,
            "cep":      cep_emp,
            "telefone": "",
            "email":    email_emp,
        }
        if nome_emp:   campos_ok += 1
        if cnpj_raw:   campos_ok += 1
        if end_emp:    campos_ok += 1
        if email_emp:  campos_ok += 1

        # ── OBRA ─────────────────────────────────────────────────
        obra = {
            "codigo":           cod_obra,
            "nome":             nome_obra,
            "endereco_entrega": _buscar_campo_brasal(
                _extrair_bloco_brasal(texto, r"DADOS PARA ENTREGA", r"AUTORIZAMOS"),
                [r"Endere[cç]o"]
            ),
            "cidade":  cidade_emp,
            "estado":  estado_emp,
            "cep":     cep_emp,
        }
        if nome_obra: campos_ok += 1

        # ── CONTATOS ─────────────────────────────────────────────
        # 1. email do faturamento (cobrança Brasal)
        if email_emp:
            contatos.append({
                "nome":     "",
                "cargo":    "cobranca",
                "email":    email_emp,
                "telefone": "",
                "origem":   "cabecalho_pdf_brasal_faturamento",
            })

        # 2. email do responsável no rodapé (ex: Carlos Muller Araujo da Silva)
        m_resp_email = re.search(r"E-mail:\s*([^\s\n]+@[^\s\n]+)", texto, re.IGNORECASE)
        # busca linha isolada com 3+ palavras em Title Case — exclui headers
        m_resp_nome = None
        for _m in re.finditer(r"\n([A-Z][a-z]+(?: (?:de|da|do|e|[A-Z][a-z]+)){2,5})\s*\n", texto):
            _ln = _m.group(1)
            if ":" not in _ln and not _ln.isupper():
                m_resp_nome = _m
                break
        if m_resp_email:
            contatos.append({
                "nome":     _limpar(m_resp_nome.group(1)) if m_resp_nome else "",
                "cargo":    "responsavel_compras",
                "email":    m_resp_email.group(1).lower().strip(),
                "telefone": "",
                "origem":   "rodape_pdf_brasal",
            })

        # 3. email do fornecedor/representante (UNE)
        bloco_forn = _extrair_bloco_brasal(texto, r"DADOS DO FORNECEDOR", r"DADOS PARA FATURAMENTO")
        m_forn_email = re.search(r"E-?Mail\s*:\s*([^\s\n]+@[^\s\n]+)", bloco_forn, re.IGNORECASE)
        m_forn_tel   = re.search(
            r"(?:Celular|Comercial)\s*:\s*([\(\d][^\-\n]{5,20})", bloco_forn, re.IGNORECASE
        )
        if m_forn_email:
            contatos.append({
                "nome":     "",
                "cargo":    "representante",
                "email":    m_forn_email.group(1).lower().strip(),
                "telefone": _normalizar_telefone(m_forn_tel.group(1)) if m_forn_tel else "",
                "origem":   "cabecalho_pdf_brasal_fornecedor",
            })

        if cond_pgt: campos_ok += 1

    except Exception as e:
        return _resultado_vazio("BRASAL", f"erro_extracao: {e}")

    confianca = round(campos_ok / campos_total, 2)
    return {
        "empresa":   empresa,
        "obra":      obra,
        "documento": documento,
        "contatos":  contatos,
        "confianca": confianca,
        "revisao":   confianca < CONFIANCA_MINIMA,
        "formato":   "BRASAL",
    }


# ============================================================
# DISPATCHER — detecta formato e chama o extrator certo
# ============================================================

def detectar_formato_pdf(caminho_pdf: str) -> str:
    """Detecta o formato do PDF para escolher o extrator correto."""
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = (pdf.pages[0].extract_text() or "").lower()

        if "sienge" in texto or "starian" in texto:
            return "SIENGE"
        if "uau! software" in texto or "gerou o.c." in texto:
            return "UAU"
        if "krona/krona" in texto or "processo nº" in texto:
            return "BRASAL"
        if "ncm" in texto and ("item nº" in texto or "item no" in texto):
            return "MRV"
        return "DESCONHECIDO"
    except Exception:
        return "DESCONHECIDO"


def extrair_cabecalho(caminho_pdf: str, formato: Optional[str] = None) -> dict:
    """
    Ponto de entrada principal.
    Detecta o formato automaticamente (ou usa o fornecido) e extrai
    todos os dados estruturados do cabeçalho/rodapé do PDF.

    Retorna dict com: empresa, obra, documento, contatos,
                      confianca, revisao, formato
    """
    fmt = formato or detectar_formato_pdf(caminho_pdf)

    extratores = {
        "SIENGE": _extrair_sienge,
        "UAU":    _extrair_uau,
        "MRV":    _extrair_mrv,
        "BRASAL": _extrair_brasal,
    }

    extrator = extratores.get(fmt, _extrair_uau)  # UAU como fallback genérico
    resultado = extrator(caminho_pdf)
    resultado["formato"] = fmt

    return resultado