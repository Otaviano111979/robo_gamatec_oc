# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import os
import unicodedata
from typing import Dict, Optional, Any, List


def _normalizar_codigo(valor: Any) -> str:
    """
    Normaliza códigos para comparação segura.
    Mantém apenas dígitos e remove espaços.
    Ex:
        " 1101047 " -> "1101047"
        1101047 -> "1101047"
    """
    if valor is None:
        return ""

    texto = str(valor).strip()
    if not texto:
        return ""

    apenas_digitos = "".join(ch for ch in texto if ch.isdigit())
    return apenas_digitos


def _remover_acentos(texto: str) -> str:
    if texto is None:
        return ""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(ch) != "Mn"
    )


def _normalizar_nome_coluna(nome: str) -> str:
    """
    Normaliza nome de coluna para facilitar mapeamento.
    """
    if nome is None:
        return ""

    nome = str(nome).strip().lower()
    nome = _remover_acentos(nome)
    nome = nome.replace(" ", "_")
    nome = nome.replace("-", "_")
    nome = nome.replace(".", "_")
    nome = nome.replace("/", "_")
    nome = nome.replace("\\", "_")

    while "__" in nome:
        nome = nome.replace("__", "_")

    return nome.strip("_")


def _detectar_delimitador(linha: str) -> str:
    """
    Detecta delimitador provável do CSV/TXT.
    """
    candidatos = [";", ",", "\t", "|"]
    contagens = {d: linha.count(d) for d in candidatos}
    delimitador = max(contagens, key=contagens.get)
    return delimitador if contagens[delimitador] > 0 else ","


def _mapear_colunas(fieldnames: List[str]) -> Dict[str, str]:
    """
    Tenta localizar as colunas esperadas no arquivo.
    Esperadas:
      - codigo_mrv
      - codigo_krona
    """
    mapa_normalizado = {
        _normalizar_nome_coluna(c): c
        for c in fieldnames
        if c and str(c).strip()
    }

    candidatos_mrv = [
        "codigo_mrv",
        "cod_mrv",
        "codigomrv",
        "codigo_cliente",
        "codigo_oc",
        "codigo_interno_oc",
        "codigo_interno",
        "cod_cliente",
        "cod_item_cliente",
        "item_cliente",
        "codigo_do_cliente",
        "codigo_mrv_oc",
    ]

    candidatos_krona = [
        "codigo_krona",
        "cod_krona",
        "codigokrona",
        "codigo_produto",
        "codigo_produto_krona",
        "codigo_item",
        "cod_produto",
        "produto_krona",
        "cod_krona_item",
        "codigo_krona_sap",
        "codigo_sap",
        "codigo",
    ]

    coluna_mrv = None
    coluna_krona = None

    for c in candidatos_mrv:
        if c in mapa_normalizado:
            coluna_mrv = mapa_normalizado[c]
            break

    for c in candidatos_krona:
        if c in mapa_normalizado:
            coluna_krona = mapa_normalizado[c]
            break

    if not coluna_mrv or not coluna_krona:
        colunas_originais = list(fieldnames)
        colunas_normalizadas = list(mapa_normalizado.keys())
        raise ValueError(
            "Não foi possível localizar as colunas obrigatórias da base MRV.\n"
            f"Colunas originais: {colunas_originais}\n"
            f"Colunas normalizadas: {colunas_normalizadas}"
        )

    return {
        "codigo_mrv": coluna_mrv,
        "codigo_krona": coluna_krona,
    }


def carregar_base_mrv(caminho_arquivo: str) -> Dict[str, Dict[str, Any]]:
    """
    Carrega base MRV (CSV/TXT delimitado) e retorna índice por codigo_mrv.

    Retorno:
    {
        "1101047": {
            "codigo_mrv": "1101047",
            "codigo_krona": "123456",
            "linha_original": {...}
        },
        ...
    }
    """
    if not os.path.exists(caminho_arquivo):
        raise FileNotFoundError(f"Base MRV não encontrada: {caminho_arquivo}")

    with open(caminho_arquivo, "r", encoding="utf-8-sig", newline="") as f:
        primeira_linha = f.readline()
        if not primeira_linha:
            raise ValueError("Arquivo da base MRV está vazio.")

        delimitador = _detectar_delimitador(primeira_linha)
        print(f"[BASE MRV] Delimitador detectado: {repr(delimitador)}")

        f.seek(0)
        reader = csv.DictReader(f, delimiter=delimitador)

        if not reader.fieldnames:
            raise ValueError("Não foi possível ler o cabeçalho da base MRV.")

        print(f"[BASE MRV] Cabeçalho original: {reader.fieldnames}")

        mapeamento = _mapear_colunas(reader.fieldnames)

        print(f"[BASE MRV] Coluna MRV mapeada: {mapeamento['codigo_mrv']}")
        print(f"[BASE MRV] Coluna Krona mapeada: {mapeamento['codigo_krona']}")

        indice: Dict[str, Dict[str, Any]] = {}
        duplicados = 0
        linhas_lidas = 0
        linhas_validas = 0

        for row in reader:
            linhas_lidas += 1

            codigo_mrv = _normalizar_codigo(row.get(mapeamento["codigo_mrv"]))
            codigo_krona = _normalizar_codigo(row.get(mapeamento["codigo_krona"]))

            if not codigo_mrv:
                continue

            registro = {
                "codigo_mrv": codigo_mrv,
                "codigo_krona": codigo_krona,
                "linha_original": row,
            }

            if codigo_mrv in indice:
                duplicados += 1

            indice[codigo_mrv] = registro
            linhas_validas += 1

    print("\n[BASE MRV]")
    print(f"Arquivo: {caminho_arquivo}")
    print(f"Linhas lidas: {linhas_lidas}")
    print(f"Linhas válidas indexadas: {linhas_validas}")
    print(f"Códigos únicos indexados: {len(indice)}")
    print(f"Duplicados sobrescritos: {duplicados}")

    return indice


def buscar_codigo_mrv(
    indice_mrv: Dict[str, Dict[str, Any]],
    codigo_mrv: Any
) -> Optional[Dict[str, Any]]:
    """
    Busca um código MRV já normalizado a partir do índice.
    """
    chave = _normalizar_codigo(codigo_mrv)
    if not chave:
        return None
    return indice_mrv.get(chave)


if __name__ == "__main__":
    caminho = r"C:\robo_gamatec_oc\dados\base_mrv.csv"

    print("\n[TESTE BASE MRV]")
    print(f"Caminho esperado: {caminho}")
    print(f"Arquivo existe? {os.path.exists(caminho)}")

    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8-sig", newline="") as f:
            primeira_linha = f.readline()
            segunda_linha = f.readline()

        print(f"Primeira linha bruta: {repr(primeira_linha)}")
        print(f"Segunda linha bruta: {repr(segunda_linha)}")

        indice = carregar_base_mrv(caminho)

        exemplos = ["1101047", "0000000", " 1101047 "]
        for codigo in exemplos:
            resultado = buscar_codigo_mrv(indice, codigo)
            print(f"\nConsulta código MRV: {codigo}")
            print(resultado)
    else:
        print("ERRO: arquivo não encontrado no caminho informado.")