import re
import unicodedata
from typing import List

from extracao_oc.modelos import LinhaDocumento


def limpar_espacos(texto: str) -> str:
    texto = texto.replace("\t", " ")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def remover_controles(texto: str) -> str:
    return "".join(
        ch for ch in texto
        if unicodedata.category(ch)[0] != "C" or ch in "\n\t"
    )


def normalizar_texto_linha(texto: str) -> str:
    texto = remover_controles(texto)
    texto = limpar_espacos(texto)
    return texto


def normalizar_linhas(linhas: List[LinhaDocumento]) -> List[LinhaDocumento]:
    for linha in linhas:
        linha.texto_normalizado = normalizar_texto_linha(linha.texto_original)

    return linhas