# -*- coding: utf-8 -*-
"""
extrator_orcamento_gamatec.py — Extrai itens do PDF de orçamento Gamatec/Krona

Formato esperado (linha de item):
  CODIGO  DESCRICAO...  EMB  QTDE  UNITARIO  TOTAL  IPI  ICMS  RET  UNIT.IMP  TOT.IMP

Exemplo:
  0029 TUBO PVC SOLDAVEL - 6M - 75MM 1 4 201,698 806,79 0,00 0,00 201,698 806,79
"""

import re
import pdfplumber


# Padrão: 4 dígitos + descrição + emb(int) + qtde(num) + unitário(num,num) + ...
_LINHA_ITEM = re.compile(
    r'^(\d{4})\s+(.+?)\s+(\d+)\s+([\d.]+)\s+([\d.,]+)\s+([\d.,]+)'
)

# Linhas a ignorar
_IGNORAR = re.compile(
    r'^(Página|Relatório|Produto|Peso:|Cubagem:|Total|Valor|Desc\.|CNPJ|Rua|Joinville'
    r'|www\.|Representante|Cliente|CNPJ/CPF|Endereço|Cidade|CEP|Fone|Condição|Imagem'
    r'|\(47\)|Nº Orç|Emissão|I\.E\.)',
    re.IGNORECASE
)


def _parse_num(s: str) -> float:
    """Converte '1.234,56' ou '1234.56' para float."""
    s = str(s).strip()
    # formato brasileiro: ponto = milhar, vírgula = decimal
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0


def extrair_orcamento_gamatec(pdf_bytes: bytes) -> dict:
    """
    Recebe bytes do PDF e retorna dict com:
    {
        'numero_orcamento': 'K77661',
        'cliente': 'MAZZUTTI EMPREENDIMENTOS LTDA',
        'emissao': '29/04/2026',
        'itens': [
            {
                'codigo': '0029',
                'descricao': 'TUBO PVC SOLDAVEL - 6M - 75MM',
                'qtde': 4.0,
                'preco_orcamento': 201.698,
            },
            ...
        ],
        'total_itens': 131,
    }
    """
    import io

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

                # Cabeçalho — extrair metadados
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

                # Ignorar linhas de cabeçalho/rodapé
                if _IGNORAR.match(line):
                    continue

                # Tentar extrair item
                m = _LINHA_ITEM.match(line)
                if not m:
                    continue

                codigo    = m.group(1).strip()
                descricao = m.group(2).strip()
                qtde      = _parse_num(m.group(4))
                unitario  = _parse_num(m.group(5))

                # Sanity check — unitário deve ser > 0
                if unitario <= 0:
                    continue

                itens.append({
                    'codigo':          codigo,
                    'descricao':       descricao,
                    'qtde':            qtde,
                    'preco_orcamento': unitario,
                })

    return {
        'numero_orcamento': numero_orcamento,
        'cliente':          cliente,
        'emissao':          emissao,
        'itens':            itens,
        'total_itens':      len(itens),
    }


def extrair_orcamento_gamatec_arquivo(caminho: str) -> dict:
    """Conveniência: recebe caminho do arquivo."""
    with open(caminho, 'rb') as f:
        return extrair_orcamento_gamatec(f.read())


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Uso: python extrator_orcamento_gamatec.py arquivo.pdf")
        sys.exit(1)
    resultado = extrair_orcamento_gamatec_arquivo(sys.argv[1])
    print(f"Orçamento: {resultado['numero_orcamento']}")
    print(f"Cliente:   {resultado['cliente']}")
    print(f"Emissão:   {resultado['emissao']}")
    print(f"Itens:     {resultado['total_itens']}")
    for it in resultado['itens'][:5]:
        print(f"  {it['codigo']} | {it['descricao'][:40]} | qtde={it['qtde']} | R${it['preco_orcamento']}")
