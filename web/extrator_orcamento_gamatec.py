# -*- coding: utf-8 -*-
"""
extrator_orcamento_gamatec.py — Extrai itens do PDF de orçamento Gamatec/Krona

Suporta dois formatos de linha:
  COM espaço:  0029 TUBO PVC SOLDAVEL - 6M - 75MM 1 4 201,698 806,79 ...
  SEM espaço:  0331ADAPTADOR SOLD CURTO 25MM X 3/4 50 484 0,652 315,57 ...

Normalização:
  - Código: zeros à esquerda removidos (0331 → 331, igual ao CSV da OC)
  - Números: formato brasileiro (1.234,56 → 1234.56)
"""

import re
import io
import pdfplumber

# Padrão: 4 dígitos + (espaço opcional) + descrição + emb + qtde + unitário + total
_LINHA_ITEM = re.compile(
    r'^(\d{4})\s*([A-Z].+?)\s+(\d+)\s+([\d.]+)\s+([\d.,]+)\s+([\d.,]+)'
)

_IGNORAR = re.compile(
    r'^(Página|Relatório|Produto|Peso:|Cubagem:|Total|Valor|Desc\.|CNPJ|Rua|Joinville'
    r'|www\.|Representante|Cliente|CNPJ/CPF|Endereço|Cidade|CEP|Fone|Condição|Imagem'
    r'|\(47\)|Nº Orç|Emissão|I\.E\.)',
    re.IGNORECASE
)


def _parse_num_br(s: str) -> float | None:
    """Converte número brasileiro para float.
    '0,652' → 0.652
    '1.340,06' → 1340.06
    '18,180' → 18.18
    """
    s = str(s).strip()
    if not s:
        return None
    if ',' in s and '.' in s:
        # formato milhar: 1.340,06
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        # formato simples: 0,652
        s = s.replace(',', '.')
    try:
        v = float(s)
        return v if v > 0 else None
    except Exception:
        return None


def _norm_codigo(codigo: str) -> str:
    """Remove zeros à esquerda: '0331' → '331', '0029' → '29'"""
    try:
        return str(int(codigo))
    except Exception:
        return codigo.lstrip('0') or '0'


def extrair_orcamento_gamatec(pdf_bytes: bytes) -> dict:
    """
    Recebe bytes do PDF e retorna:
    {
        'numero_orcamento': 'K25138',
        'cliente': 'MRV PRIME INCORPORACOES CENTRO OESTE LTD',
        'emissao': '30/04/2026',
        'itens': [
            {
                'codigo': '331',         ← sem zeros à esquerda
                'descricao': 'ADAPTADOR SOLD CURTO 25MM X 3/4',
                'qtde': 484.0,
                'preco_orcamento': 0.652, ← float correto
            },
            ...
        ],
        'total_itens': 13,
    }
    """
    numero_orcamento = ""
    cliente = ""
    emissao = ""
    itens = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue

                # Metadados do cabeçalho
                if 'Nº Orçamento:' in line or 'Nº Orcamento:' in line:
                    m = re.search(r'Nº Or[çc]amento:\s*(\S+)', line)
                    if m:
                        numero_orcamento = m.group(1).strip()
                    m2 = re.search(r'Cliente:\s*\d+/\d+-(.+?)\s+Nº', line)
                    if m2:
                        cliente = m2.group(1).strip()

                if 'Emissão:' in line or 'Emissao:' in line:
                    m = re.search(r'Emiss[aã]o:\s*(\d{2}/\d{2}/\d{4})', line)
                    if m:
                        emissao = m.group(1)

                if _IGNORAR.match(line):
                    continue

                m = _LINHA_ITEM.match(line)
                if not m:
                    continue

                codigo  = _norm_codigo(m.group(1))
                descricao = m.group(2).strip()
                qtde    = _parse_num_br(m.group(4))
                preco   = _parse_num_br(m.group(5))

                if preco is None or preco <= 0:
                    continue

                itens.append({
                    'codigo':          codigo,
                    'descricao':       descricao,
                    'qtde':            qtde,
                    'preco_orcamento': preco,
                })

    return {
        'numero_orcamento': numero_orcamento,
        'cliente':          cliente,
        'emissao':          emissao,
        'itens':            itens,
        'total_itens':      len(itens),
    }


def extrair_orcamento_gamatec_arquivo(caminho: str) -> dict:
    with open(caminho, 'rb') as f:
        return extrair_orcamento_gamatec(f.read())


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python extrator_orcamento_gamatec.py arquivo.pdf")
        sys.exit(1)
    r = extrair_orcamento_gamatec_arquivo(sys.argv[1])
    print(f"Orçamento : {r['numero_orcamento']}")
    print(f"Cliente   : {r['cliente']}")
    print(f"Emissão   : {r['emissao']}")
    print(f"Itens     : {r['total_itens']}")
    print()
    for it in r['itens']:
        print(f"  {it['codigo']:>6} | R${it['preco_orcamento']:>10.3f} | qtde={it['qtde']:>8} | {it['descricao'][:40]}")
