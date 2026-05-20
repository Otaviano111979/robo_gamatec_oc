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

                # --- NOVA LÓGICA DE EXTRAÇÃO ROBUSTA ---
                parts = line.split()
                if len(parts) < 4:
                    continue

                # 1. Extrair Código (4 dígitos iniciais)
                first = parts[0]
                codigo = ""
                if len(first) >= 4 and first[:4].isdigit():
                    codigo = _norm_codigo(first[:4])
                    if len(first) > 4:
                        parts[0] = first[4:] # Remove código grudado na descrição
                    else:
                        parts.pop(0)
                else:
                    continue

                # 2. Identificar números no final (de trás para frente)
                # Vamos pegar todos os números possíveis até encontrar um texto
                nums = []
                num_parts = []
                for p in reversed(parts):
                    val = _parse_num_br(p)
                    if val is not None:
                        nums.insert(0, val)
                        num_parts.insert(0, p)
                    else:
                        break
                
                if len(nums) < 3:
                    continue

                # 3. Mapear Colunas de forma robusta (Triplet Q * P = T)
                # O objetivo é encontrar a quantidade e o preço unitário.
                qtde_val = None
                preco_val = None
                
                def is_approx(v1, v2, tol=0.05):
                    if v1 is None or v2 is None: return False
                    return abs(v1 - v2) < tol

                # Tenta encontrar o melhor triplet (Q, P, T) tal que Q*P ≈ T
                # No padrão de 8 colunas: Q=nums[1], P=nums[2], T=nums[3]
                # No padrão de 4 colunas: Q=nums[1], P=nums[2], T=nums[3] (se nums[0] for Emb)
                # No padrão de 3 colunas: Q=nums[0], P=nums[1], T=nums[2]
                
                found = False
                for i in range(len(nums) - 2):
                    q, p, t = nums[i], nums[i+1], nums[i+2]
                    if q > 0 and p > 0 and is_approx(q * p, t):
                        qtde_val, preco_val = q, p
                        found = True
                        break
                
                # Fallback se não achou triplet perfeito:
                if not found:
                    if len(nums) == 3:
                        qtde_val, preco_val = nums[0], nums[1]
                    elif len(nums) >= 4:
                        # Se tiver 4 ou mais, o Unitário costuma ser o 3º se houver Emb, ou o 2º.
                        # Na dúvida, pegamos o penúltimo ou antepenúltimo?
                        # No caso de 8 colunas, o unitário desejado é o nums[2].
                        # Se len(nums) >= 4, nums[1] costuma ser Qtde e nums[2] Unitário.
                        qtde_val, preco_val = nums[1], nums[2]

                # 4. Descrição é o que sobrou no meio
                # A descrição termina onde começam os números que usamos
                # Mas para simplificar, removemos todos os 'num_parts' do final
                desc_limit = len(parts) - len(nums)
                descricao = " ".join(parts[:desc_limit]).strip()

                if preco_val is not None and qtde_val is not None and preco_val > 0:
                    itens.append({
                        'codigo':          codigo,
                        'descricao':       descricao,
                        'qtde':            qtde_val,
                        'preco_orcamento': preco_val,
                    })

                # --- FIM DA LÓGICA ROBUSTA ---
                continue

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
