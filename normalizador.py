import re
import unicodedata


SIGLAS_EQUIVALENTES = {
    r"\bSR\b": "SERIE REFORCADA",
    r"\bESG\b": "ESGOTO",
    r"\bROSC\b": "ROSCAVEL",
    r"\bSOLD\b": "SOLDAVEL",
    r"\bSEC\b": "SECUNDARIO",
    r"\bPRIM\b": "PRIMARIO",
}


PADROES_CATEGORIA = [
    ("TUBO", [
        r"\bTUBO\b",
    ]),
    ("JOELHO", [
        r"\bJOELHO\b",
        r"\bCURVA 90\b",
        r"\bCURVA 45\b",
        r"\bCURVA\b",
    ]),
    ("TE", [
        r"\bTE\b",
        r"\bT[EÊ]\b",
    ]),
    ("LUVA", [
        r"\bLUVA\b",
    ]),
    ("CAP", [
        r"\bCAP\b",
        r"\bCAPA\b",
    ]),
    ("ADAPTADOR", [
        r"\bADAPTADOR\b",
    ]),
    ("BUCHA", [
        r"\bBUCHA\b",
    ]),
    ("REGISTRO", [
        r"\bREGISTRO\b",
    ]),
    ("VALVULA", [
        r"\bVALVULA\b",
        r"\bV[ÁA]LVULA\b",
    ]),
    ("FLANGE", [
        r"\bFLANGE\b",
    ]),
    ("UNIAO", [
        r"\bUNIAO\b",
        r"\bUNI[AÃ]O\b",
    ]),
    ("TAMPA", [
        r"\bTAMPA\b",
    ]),
    ("PASTA LUBRIFICANTE", [
        r"\bPASTA LUBRIFICANTE\b",
        r"\bLUBRIFICANTE\b",
    ]),
    ("ADESIVO", [
        r"\bADESIVO\b",
        r"\bCOLA\b",
    ]),
    ("REDUCAO", [
        r"\bREDUCAO\b",
        r"\bREDU[CÇ][AÃ]O\b",
    ]),
]


def remover_acentos(texto: str) -> str:
    if texto is None:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )


def limpar_espacos(texto: str) -> str:
    texto = re.sub(r"[;/|]+", " ", texto)
    texto = re.sub(r"[-]+", " - ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def expandir_siglas(descricao: str) -> str:
    texto = str(descricao or "")
    texto = remover_acentos(texto).upper()

    for padrao, substituicao in SIGLAS_EQUIVALENTES.items():
        texto = re.sub(padrao, substituicao, texto)

    texto = limpar_espacos(texto)
    return texto


def normalizar_descricao(descricao: str) -> str:
    texto = expandir_siglas(descricao)

    # remove caracteres estranhos, mantendo letras, números, espaço, ponto, vírgula e hífen
    texto = re.sub(r"[^A-Z0-9.,\-\s]", " ", texto)

    # padronizações úteis
    texto = texto.replace(" MM", "MM")
    texto = texto.replace(" M ", " M ")
    texto = texto.replace(" DN ", " DN ")

    texto = limpar_espacos(texto)
    return texto


def detectar_categoria(descricao_normalizada: str):
    texto = str(descricao_normalizada or "")

    for categoria, padroes in PADROES_CATEGORIA:
        for padrao in padroes:
            if re.search(padrao, texto):
                return categoria

    return None


def detectar_eh_tubo(descricao_normalizada: str) -> bool:
    texto = str(descricao_normalizada or "")
    return bool(re.search(r"\bTUBO\b", texto))


def detectar_diametro_mm(descricao_normalizada: str):
    texto = str(descricao_normalizada or "")

    padroes = [
        r"\bDN\s*(\d{1,3}(?:[.,]\d+)?)\b",
        r"\b(\d{1,3}(?:[.,]\d+)?)\s*MM\b",
        r"\b(\d{1,3}(?:[.,]\d+)?)MM\b",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto)
        if m:
            valor = m.group(1).replace(",", ".")
            try:
                return float(valor)
            except ValueError:
                pass

    return None


def detectar_comprimento_m(descricao_normalizada: str):
    texto = str(descricao_normalizada or "")

    padroes = [
        r"\b(\d{1,2}(?:[.,]\d+)?)\s*M\b",
        r"\b(\d{1,2}(?:[.,]\d+)?)M\b",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto)
        if m:
            valor = m.group(1).replace(",", ".")
            try:
                comprimento = float(valor)
                if 0.3 <= comprimento <= 12:
                    return comprimento
            except ValueError:
                pass

    return None


def enriquecer_descricao(descricao: str):
    descricao_original = str(descricao or "").strip()
    descricao_normalizada = normalizar_descricao(descricao_original)

    categoria_detectada = detectar_categoria(descricao_normalizada)
    eh_tubo = detectar_eh_tubo(descricao_normalizada)
    diametro_mm = detectar_diametro_mm(descricao_normalizada)
    comprimento_detectado_m = detectar_comprimento_m(descricao_normalizada)

    return {
        "descricao_normalizada": descricao_normalizada,
        "categoria_detectada": categoria_detectada,
        "eh_tubo": eh_tubo,
        "diametro_mm": diametro_mm,
        "comprimento_detectado_m": comprimento_detectado_m,
    }


if __name__ == "__main__":
    exemplos = [
        "TUBO PVC SOLDAVEL - 6M - 20MM",
        "TUBO PVC ESG SR - 6M - DN 75",
        "Tubo PVC Esgoto Serie Reforçada 75 MM",
        "PASTA LUBRIFICANTE 160G",
        "TE SOLDAVEL 25MM",
        "LUVA ROSC 3/4",
        "TUBO ULTRATERM 3M - 22MM",
    ]

    for item in exemplos:
        print("=" * 80)
        print("ENTRADA:", item)
        print("SAIDA:", enriquecer_descricao(item))