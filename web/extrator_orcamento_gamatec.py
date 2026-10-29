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

_CABECALHO = re.compile(
    r'^Produto\s+(?P<emb>Emb\.?\s+)?Qtde\s+Unit[aá]rio\s+Total'
    r'(?P<impostos>\s+IPI\s+ICMS\s+Ret\.?\s+Unit\.Imp\.?\s+Tot\.c/Imp\.?)?$',
    re.IGNORECASE,
)
_INTEIRO_BR = r'(?:\d{1,3}(?:\.\d{3})+|\d+)'
_NUMERO_BR = rf'{_INTEIRO_BR}(?:,\d+)?'
_VALOR_BR = rf'{_INTEIRO_BR},\d{{2,3}}'
_COLUNAS = {
    8: ('emb', 'qtde', 'preco', 'total', 'ipi', 'icms', 'preco_impostos', 'total_impostos'),
    4: ('emb', 'qtde', 'preco', 'total'),
    3: ('qtde', 'preco', 'total'),
}
_LINHAS_ITEM = {
    quantidade: re.compile(
        r'(?P<descricao>.+?)\s+' + r'\s+'.join(
            rf'(?P<{coluna}>{_NUMERO_BR if coluna in ("emb", "qtde") else _VALOR_BR})'
            for coluna in colunas
        )
    )
    for quantidade, colunas in _COLUNAS.items()
}

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
    '1.508' (sem vírgula, mas com ponto de milhar) → 1508.0
    """
    s = str(s).strip()
    if not s:
        return None
    
    # Se não tiver dígitos nem for algo como "0,00", não é número
    if not any(c.isdigit() for c in s):
        return None

    # Se tem ponto e vírgula: 1.340,06
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    # Se tem apenas vírgula: 0,652
    elif ',' in s:
        s = s.replace(',', '.')
    # Se tem apenas ponto: pode ser decimal (1.508) ou milhar (1.508)
    # No contexto da Krona/Gamatec, quantidades como 1.508 são 1508 unidades.
    # Preços sempre vêm com vírgula: 0,652.
    # Então, se tem apenas ponto, removemos o ponto.
    elif '.' in s:
        # Se o ponto separa 3 dígitos finais, é milhar (ex: 1.508)
        # Se fosse decimal, teria vírgula no padrão brasileiro deste PDF.
        s = s.replace('.', '')
        
    try:
        v = float(s)
        return v
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
    layout = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pagina, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue

                cabecalho = _CABECALHO.fullmatch(line)
                if cabecalho:
                    if cabecalho['impostos'] and not cabecalho['emb']:
                        raise ValueError('Cabeçalho do orçamento não suportado.')
                    layout = 8 if cabecalho['impostos'] else 4 if cabecalho['emb'] else 3
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

                inicio = re.match(r'^(\d{4})(?!\d)\s*(.+)$', line)
                if not inicio:
                    continue

                codigo = _norm_codigo(inicio[1])
                conteudo = inicio[2]
                formatos = (layout,) if layout is not None else (8, 4, 3)
                item = None
                for formato in formatos:
                    item = _LINHAS_ITEM[formato].fullmatch(conteudo)
                    if item:
                        layout = formato
                        break
                if item is None:
                    raise ValueError(
                        f'Colunas inválidas no item {codigo}, página {pagina} do orçamento.'
                    )

                qtde_val = _parse_num_br(item['qtde'])
                preco_val = _parse_num_br(item['preco'])
                if preco_val > 0:
                    itens.append({
                        'codigo': codigo,
                        'descricao': item['descricao'],
                        'qtde': qtde_val,
                        'preco_orcamento': preco_val,
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
