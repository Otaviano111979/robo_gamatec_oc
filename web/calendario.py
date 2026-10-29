"""Calendário da sidebar: feriados, datas importantes e efemérides do dia.

Fontes públicas e sem chave. Tudo o que é lido fica em cache no disco, por isso
depois da primeira leitura o calendário continua a funcionar mesmo sem rede.
Cada fonte falha sozinha: o que não se conseguir atualizar mantém-se em falta
sem derrubar o resto.
"""

import json
import os
import threading
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

UF = "GO"
MUNICIPIO_IBGE = "5208707"  # Goiânia
TIMEOUT = 8
NAVEGADOR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

NACIONAIS_URL = "https://brasilapi.com.br/api/feriados/v1/{ano}"
_DATASET = ("https://raw.githubusercontent.com/joaopbini/feriados-brasil/master/dados/"
            "feriados/{tipo}/json/{ano}.json")
COMEMORATIVAS_URL = ("https://raw.githubusercontent.com/joaopbini/feriados-brasil/master/"
                     "dados/comemorativas/json/{ano}.json")
EFEMERIDES_URL = ("https://api.wikimedia.org/feed/v1/wikipedia/pt/onthisday/events/"
                  "{mes:02d}/{dia:02d}")

ROTULOS = {"nacional": "Nacional", "estadual": "Goiás", "municipal": "Goiânia"}
_PRIORIDADE = {"nacional": 0, "estadual": 1, "municipal": 2}
EFEMERIDES_POR_DIA = 3
EFEMERIDES_MAX_CARACTERES = 150

# cache em memoria; o ficheiro e a copia persistente (por ano e por dia)
CACHE_FILE = None
_lock = threading.Lock()
_memoria = None


def _caminho_cache():
    if CACHE_FILE:
        return CACHE_FILE
    try:
        from config import BASE_DIR
    except Exception:
        BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(BASE_DIR, "dados", "cache_calendario.json")


def _ler_cache():
    global _memoria
    with _lock:
        if _memoria is not None:
            return _memoria
    dados = {}
    try:
        with open(_caminho_cache(), encoding="utf-8") as ficheiro:
            lidos = json.load(ficheiro)
        if isinstance(lidos, dict):
            dados = lidos
    except (OSError, ValueError):
        dados = {}
    with _lock:
        if _memoria is None:
            _memoria = dados
        return _memoria


def _gravar_cache():
    caminho = _caminho_cache()
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        temporario = caminho + ".tmp"
        with open(temporario, "w", encoding="utf-8") as ficheiro:
            json.dump(_memoria, ficheiro, ensure_ascii=False)
        os.replace(temporario, caminho)
    except (OSError, TypeError, ValueError):
        pass


def _obter(chave, carregar):
    """Devolve (valor, falhou). Só guarda leituras bem-sucedidas."""
    cache = _ler_cache()
    with _lock:
        if chave in cache:
            return cache[chave], False
    try:
        valor = carregar()
    except Exception:
        return None, True
    cache[chave] = valor
    with _lock:
        _gravar_cache()
    return valor, False


def _obter_json(url):
    pedido = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR})
    with urllib.request.urlopen(pedido, timeout=TIMEOUT) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def _iso(texto):
    if not isinstance(texto, str):
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto.strip(), formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _item(dia, nome, tipo):
    nome = (nome or "").strip()
    if not dia or not nome:
        return None
    return {"data": dia, "nome": nome, "tipo": tipo}


def _nacionais(ano):
    itens = (_item(_iso(bruto.get("date")), bruto.get("name"), "nacional")
             for bruto in _obter_json(NACIONAIS_URL.format(ano=ano)))
    return [item for item in itens if item]


def _estaduais(ano):
    itens = (_item(_iso(bruto.get("data")), bruto.get("nome"), "estadual")
             for bruto in _obter_json(_DATASET.format(tipo="estadual", ano=ano))
             if bruto.get("uf") == UF)
    return [item for item in itens if item]


def _municipais(ano):
    itens = (_item(_iso(bruto.get("data")), bruto.get("nome"), "municipal")
             for bruto in _obter_json(_DATASET.format(tipo="municipal", ano=ano))
             if str(bruto.get("codigo_ibge")) == MUNICIPIO_IBGE)
    return [item for item in itens if item]


def _comemorativas(ano):
    itens = (_item(_iso(bruto.get("data")), bruto.get("nome"), "comemorativa")
             for bruto in _obter_json(COMEMORATIVAS_URL.format(ano=ano)))
    return [item for item in itens if item]


def _normalizar(texto):
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _com_rotulo(itens):
    """Junta as listas sem repetir o mesmo dia por nacional/estadual/municipal."""
    ordenados = sorted(itens, key=lambda item: _PRIORIDADE.get(item["tipo"], 9))
    vistos = set()
    saida = []
    for item in ordenados:
        chave = _normalizar(item["nome"])
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(dict(item, rotulo=ROTULOS.get(item["tipo"], "")))
    return saida


def _feriados(ano):
    fontes = {
        "nacional": lambda: _nacionais(ano),
        "estadual": lambda: _estaduais(ano),
        "municipal": lambda: _municipais(ano),
    }
    with ThreadPoolExecutor(max_workers=3) as executor:
        tarefas = {
            tipo: executor.submit(_obter, f"feriados-{tipo}-{ano}", carregar)
            for tipo, carregar in fontes.items()
        }
        resultado = {tipo: tarefa.result() for tipo, tarefa in tarefas.items()}

    itens = []
    falhou = False
    for tipo, (lista, falta) in resultado.items():
        falhou = falhou or falta
        itens.extend(lista or [])
    return _com_rotulo(itens), falhou


def _datas_importantes(ano):
    lista, falta = _obter(f"comemorativas-{ano}", lambda: _comemorativas(ano))
    return _com_rotulo(lista or []), falta


def _wikimedia(dia):
    dados = _obter_json(EFEMERIDES_URL.format(mes=dia.month, dia=dia.day))
    itens = []
    for bruto in (dados.get("events") or [])[:EFEMERIDES_POR_DIA]:
        texto = (bruto.get("text") or "").strip()
        if not texto:
            continue
        if len(texto) > EFEMERIDES_MAX_CARACTERES:
            texto = texto[:EFEMERIDES_MAX_CARACTERES - 3].rstrip() + "…"
        itens.append({"ano": bruto.get("year"), "texto": texto})
    return itens


def _efemerides(dia):
    chave = f"efemerides-{dia.month:02d}-{dia.day:02d}"
    return _obter(chave, lambda: _wikimedia(dia))


def _por_dia(itens, prefixo):
    mapa = {}
    for item in itens:
        if not item["data"].startswith(prefixo):
            continue
        mapa.setdefault(item["data"], []).append(
            {"nome": item["nome"], "rotulo": item["rotulo"]})
    return mapa


def mes(ano, numero_mes):
    """Feriados e datas importantes do mês, agrupados por dia (YYYY-MM-DD)."""
    prefixo = f"{ano:04d}-{numero_mes:02d}"
    feriados, falta_feriado = _feriados(ano)
    comemorativas, falta_comemorativa = _datas_importantes(ano)
    return {
        "ok": True,
        "ano": ano,
        "mes": numero_mes,
        "feriados": _por_dia(feriados, prefixo),
        "comemorativas": _por_dia(comemorativas, prefixo),
        "completo": not (falta_feriado or falta_comemorativa),
    }


def dia(iso_data):
    """Tudo o que se sabe sobre um dia: feriados, datas importantes e efemérides."""
    data = datetime.strptime(iso_data, "%Y-%m-%d").date()
    feriados, falta_feriado = _feriados(data.year)
    comemorativas, falta_comemorativa = _datas_importantes(data.year)
    efemerides, falta_efemerides = _efemerides(data)

    def do_dia(itens):
        return [{"nome": item["nome"], "rotulo": item["rotulo"]}
                for item in itens if item["data"] == iso_data]

    return {
        "ok": True,
        "data": iso_data,
        "feriados": do_dia(feriados),
        "comemorativas": do_dia(comemorativas),
        "efemerides": efemerides or [],
        "completo": not (falta_feriado or falta_comemorativa or falta_efemerides),
    }


def limpar_cache():
    global _memoria
    with _lock:
        _memoria = None
