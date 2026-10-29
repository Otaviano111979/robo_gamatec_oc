"""Ilha da sidebar: tempo de Goiânia, mercado e notícias do setor.

Fontes públicas e sem chave. Cada secção falha sozinha: em caso de erro usa o
último resultado bom e marca a secção como desatualizada.
"""

import json
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

FUSO = timezone(timedelta(hours=-3))
TEMPO_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=-16.6869&longitude=-49.2648"
    "&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min"
    "&timezone=America%2FSao_Paulo&forecast_days=4"
)
CAMBIO_URL = "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL"
BOLSA_URL = "https://api.hgbrasil.com/finance?format=json"
NOTICIAS = (
    ("CBIC", "https://cbic.org.br/feed/"),
    ("Cimento Itambé", "https://www.cimentoitambe.com.br/feed/"),
    ("google", "https://news.google.com/rss/search?q=materiais+de+constru%C3%A7%C3%A3o"
               "&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
)
CACHE_TTL = 600
CACHE_TTL_FALHA = 60
TIMEOUT = 4
NAVEGADOR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

CONDICOES = {
    0: ("Céu limpo", "sol"),
    1: ("Predominantemente limpo", "sol-nublado"),
    2: ("Parcialmente nublado", "sol-nublado"),
    3: ("Nublado", "nublado"),
    45: ("Nevoeiro", "nevoeiro"),
    48: ("Nevoeiro com geada", "nevoeiro"),
    51: ("Garoa fraca", "chuva"),
    53: ("Garoa", "chuva"),
    55: ("Garoa forte", "chuva"),
    56: ("Garoa gelada", "chuva"),
    57: ("Garoa gelada forte", "chuva"),
    61: ("Chuva fraca", "chuva"),
    63: ("Chuva", "chuva"),
    65: ("Chuva forte", "chuva"),
    66: ("Chuva gelada", "chuva"),
    67: ("Chuva gelada forte", "chuva"),
    71: ("Neve fraca", "neve"),
    73: ("Neve", "neve"),
    75: ("Neve forte", "neve"),
    77: ("Granizo fino", "neve"),
    80: ("Pancadas fracas", "chuva"),
    81: ("Pancadas de chuva", "chuva"),
    82: ("Pancadas fortes", "chuva"),
    85: ("Pancadas de neve", "neve"),
    86: ("Pancadas de neve fortes", "neve"),
    95: ("Trovoada", "trovoada"),
    96: ("Trovoada com granizo", "trovoada"),
    99: ("Trovoada com granizo forte", "trovoada"),
}
DIAS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")

_lock = threading.Lock()
_cache = {"dados": None, "quando": 0.0, "ttl": CACHE_TTL}
_ultimos = {}


def _abrir(url):
    pedido = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR})
    with urllib.request.urlopen(pedido, timeout=TIMEOUT) as resposta:
        return resposta.read()


def _obter_json(url):
    return json.loads(_abrir(url).decode("utf-8"))


def _obter_texto(url):
    return _abrir(url)


def _condicao(codigo):
    return CONDICOES.get(int(codigo), ("Tempo variável", "nublado"))


def _tempo():
    dados = _obter_json(TEMPO_URL)
    agora = dados["current"]
    descricao, icone = _condicao(agora["weather_code"])
    diario = dados["daily"]
    hoje = datetime.now(FUSO).date()
    dias = []
    for indice, data in enumerate(diario["time"]):
        dia = datetime.strptime(data, "%Y-%m-%d").date()
        rotulo, icone_dia = _condicao(diario["weather_code"][indice])
        if dia == hoje:
            nome = "Hoje"
        elif dia == hoje + timedelta(days=1):
            nome = "Amanhã"
        else:
            nome = DIAS[dia.weekday()]
        dias.append({
            "data": data,
            "rotulo": nome,
            "max": round(diario["temperature_2m_max"][indice]),
            "min": round(diario["temperature_2m_min"][indice]),
            "descricao": rotulo,
            "icone": icone_dia,
        })
    return {
        "cidade": "Goiânia",
        "agora": {
            "temp": round(agora["temperature_2m"]),
            "sensacao": round(agora["apparent_temperature"]),
            "umidade": round(agora["relative_humidity_2m"]),
            "vento": round(agora["wind_speed_10m"]),
            "descricao": descricao,
            "icone": icone,
        },
        "dias": dias,
    }


def _numero(valor):
    if isinstance(valor, str):
        valor = valor.replace(".", "").replace(",", ".") if valor.count(",") else valor
    return float(valor)


def _mercado():
    cambio = _obter_json(CAMBIO_URL)
    itens = []
    for moeda, nome in (("USDBRL", "Dólar"), ("EURBRL", "Euro")):
        cotacao = cambio.get(moeda)
        if not cotacao:
            continue
        itens.append({
            "nome": nome,
            "valor": _numero(cotacao["bid"]),
            "variacao": _numero(cotacao["pctChange"]),
            "casas": 2,
        })
    try:
        bolsa = _obter_json(BOLSA_URL)["results"]["stocks"]["IBOVESPA"]
        itens.append({
            "nome": "IBOV",
            "valor": _numero(bolsa["points"]),
            "variacao": _numero(bolsa["variation"]),
            "casas": 0,
        })
    except (KeyError, TypeError, ValueError):
        pass
    return itens


def _data_publicacao(texto):
    if not texto:
        return None
    try:
        return parsedate_to_datetime(texto).astimezone(FUSO)
    except (TypeError, ValueError):
        return None


def _noticias():
    itens = []
    for fonte, url in NOTICIAS:
        try:
            raiz = ET.fromstring(_obter_texto(url))
        except ET.ParseError:
            continue
        for noticia in raiz.findall(".//item"):
            titulo = (noticia.findtext("title") or "").strip()
            link = (noticia.findtext("link") or "").strip()
            if not titulo or not link.startswith(("http://", "https://")):
                continue
            publicada = _data_publicacao(noticia.findtext("pubDate"))
            nome = fonte
            if fonte == "google" and " - " in titulo:
                titulo, nome = titulo.rsplit(" - ", 1)
                nome = nome.strip()
            itens.append({
                "titulo": titulo,
                "fonte": nome,
                "url": link,
                "publicada": publicada.isoformat(timespec="minutes") if publicada else None,
            })
            break
    itens.sort(key=lambda item: item["publicada"] or "", reverse=True)
    return itens[:3]


def _secao(nome, funcao):
    try:
        dados = funcao()
        if not dados:
            raise ValueError("sem dados")
        _ultimos[nome] = dados
        return dados, False
    except Exception:
        return _ultimos.get(nome), True


def coletar(forcar=False):
    with _lock:
        if not forcar and _cache["dados"] and time.time() - _cache["quando"] < _cache["ttl"]:
            return dict(_cache["dados"], cache=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        tarefas = {
            nome: executor.submit(_secao, nome, funcao)
            for nome, funcao in (("tempo", _tempo), ("mercado", _mercado), ("noticias", _noticias))
        }
        resultado = {nome: tarefa.result() for nome, tarefa in tarefas.items()}
    tempo, tempo_velho = resultado["tempo"]
    mercado, mercado_velho = resultado["mercado"]
    noticias, noticias_velho = resultado["noticias"]
    dados = {
        "ok": bool(tempo or mercado or noticias),
        "atualizado": datetime.now(FUSO).isoformat(timespec="seconds"),
        "tempo": dict(tempo, desatualizado=tempo_velho) if tempo else None,
        "mercado": list(mercado or []),
        "mercado_desatualizado": mercado_velho,
        "noticias": list(noticias or []),
        "noticias_desatualizado": noticias_velho,
        "desatualizado": bool(tempo_velho or mercado_velho or noticias_velho),
        "cache": False,
    }
    with _lock:
        _cache["dados"] = dados
        _cache["quando"] = time.time()
        _cache["ttl"] = CACHE_TTL_FALHA if dados["desatualizado"] else CACHE_TTL
    return dict(dados)


def limpar_cache():
    with _lock:
        _cache.update({"dados": None, "quando": 0.0, "ttl": CACHE_TTL})
        _ultimos.clear()
