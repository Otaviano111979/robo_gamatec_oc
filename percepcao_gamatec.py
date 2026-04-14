# -*- coding: utf-8 -*-
"""
percepcao_gamatec.py

AJUSTE INCREMENTAL DA CAMADA DE PERCEPCAO DO GAMATEC
- sem reestruturar o projeto
- foco total em leitura robusta da grade
- evita header/interface
- corrige desalinhamento fino de ROI
- estabiliza leitura de preco
- preserva codigo lido e codigo normalizado para comparacao
- reduz custo de OCR na operacao real

Dependencias esperadas:
    pip install pyautogui pillow pytesseract opencv-python numpy
"""

from __future__ import annotations

import os
import re
import json
import time
from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple, Dict, Any

import pyautogui
import pytesseract

from PIL import Image, ImageOps, ImageEnhance, ImageFilter

try:
    import cv2  # noqa: F401
    TEM_CV2 = True
except Exception:
    TEM_CV2 = False


TESSERACT_CMD_PADRAO = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_CMD_PADRAO):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD_PADRAO

DEBUG_DIR = r"C:\robo_gamatec_oc\saida\debug_percepcao"
os.makedirs(DEBUG_DIR, exist_ok=True)

pyautogui.FAILSAFE = True


@dataclass
class CampoLido:
    valor: Optional[str]
    confianca: float
    x: int
    y: int
    w: int
    h: int
    bruto: str = ""
    valido: bool = False
    tentativas: int = 0
    valor_normalizado: Optional[str] = None


@dataclass
class LinhaPercebida:
    indice_linha: int
    y_base: int
    codigo: CampoLido
    descricao: CampoLido
    ult_preco: CampoLido
    final: CampoLido

    def tem_dados(self) -> bool:
        return any([
            self.codigo.valor,
            self.descricao.valor,
            self.ult_preco.valor,
            self.final.valor
        ])

    def codigo_valido(self) -> bool:
        return self.codigo is not None and self.codigo.valido

    def to_dict(self) -> Dict[str, Any]:
        return {
            "indice_linha": self.indice_linha,
            "y_base": self.y_base,
            "codigo": asdict(self.codigo),
            "descricao": asdict(self.descricao),
            "ult_preco": asdict(self.ult_preco),
            "final": asdict(self.final),
        }


def garantir_int(v: Any, padrao: int = 0) -> int:
    try:
        return int(round(float(v)))
    except Exception:
        return padrao


def clamp(v: int, vmin: int, vmax: int) -> int:
    return max(vmin, min(vmax, v))


def salvar_debug_imagem(img: Image.Image, nome: str) -> str:
    caminho = os.path.join(DEBUG_DIR, nome)
    img.save(caminho)
    return caminho


def limpar_texto(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parece_header_ou_interface(texto: str) -> bool:
    t = limpar_texto(texto).lower()

    if not t:
        return False

    palavras_proibidas = [
        "código", "codigo", "últ.", "ult.", "último", "ultimo",
        "final", "mix", "itens", "item", "qtde", "quantidade",
        "interface", "pedido", "cliente", "desconto", "% desc",
        "gamatec", "produto", "valor", "preço", "preco"
    ]

    for p in palavras_proibidas:
        if p in t:
            return True

    return False


def extrair_digitos_codigo(texto: str) -> Optional[str]:
    if not texto:
        return None

    bruto = texto.upper().strip()

    substituicoes = {
        "O": "0",
        "D": "0",
        "Q": "0",
        "I": "1",
        "L": "1",
        "|": "1",
        "Z": "2",
        "S": "5",
        "B": "8",
        "G": "6",
    }

    corr = []
    for ch in bruto:
        corr.append(substituicoes.get(ch, ch))
    bruto = "".join(corr)

    digitos = re.sub(r"\D", "", bruto)

    if not digitos:
        return None

    if len(digitos) > 6:
        encontrados = re.findall(r"\d{3,6}", digitos)
        if encontrados:
            digitos = encontrados[0]
        else:
            digitos = digitos[:6]

    if len(digitos) < 3:
        return None

    return digitos


def normalizar_codigo_para_comparacao(codigo: Optional[str]) -> Optional[str]:
    if not codigo:
        return None

    digitos = re.sub(r"\D", "", str(codigo))
    if not digitos:
        return None

    normalizado = digitos.lstrip("0")
    if normalizado == "":
        normalizado = "0"

    return normalizado


def _normalizar_texto_preco(texto: str) -> str:
    s = (texto or "").upper().strip()
    s = s.replace(" ", "")
    s = s.replace("R$", "")

    substituicoes = {
        "O": "0",
        "D": "0",
        "Q": "0",
        "I": "1",
        "L": "1",
        "|": "1",
        "S": "5",
        "B": "8",
    }
    s = "".join(substituicoes.get(ch, ch) for ch in s)
    s = s.replace("..", ".").replace(",,", ",")
    s = re.sub(r"[^0-9,\.\-]", "", s)
    return s


def parse_preco_brasil(texto: str) -> Optional[float]:
    if not texto:
        return None

    s = _normalizar_texto_preco(texto)
    if not s:
        return None

    candidatos = []

    # 1) prioriza formato monetario clássico com 2 casas
    candidatos.extend(re.findall(r"\d{1,3}(?:\.\d{3})*,\d{2}", s))
    candidatos.extend(re.findall(r"\d+,\d{2}", s))
    candidatos.extend(re.findall(r"\d+\.\d{2}", s))

    # 2) fallback: pega maior bloco numérico plausível
    if not candidatos:
        blocos = re.findall(r"[\d\.,]+", s)
        blocos = [b for b in blocos if re.search(r"\d", b)]
        blocos.sort(key=len, reverse=True)
        candidatos.extend(blocos)

    for candidato in candidatos:
        c = candidato

        if "," in c:
            if c.count(",") > 1:
                partes = c.split(",")
                c = "".join(partes[:-1]) + "," + partes[-1]

            if "." in c:
                c = c.replace(".", "")
            c = c.replace(",", ".")
        else:
            if c.count(".") > 1:
                partes = c.split(".")
                c = "".join(partes[:-1]) + "." + partes[-1]
            elif "." not in c and re.fullmatch(r"\d{3,}", c):
                c = c[:-2] + "." + c[-2:]

        c = re.sub(r"[^0-9.\-]", "", c)
        if c.count(".") > 1:
            partes = c.split(".")
            c = "".join(partes[:-1]) + "." + partes[-1]

        try:
            valor = float(c)
            if 0 <= valor <= 999999.99:
                return valor
        except Exception:
            continue

    return None


def preco_para_str(valor: Optional[float]) -> Optional[str]:
    if valor is None:
        return None
    return f"{valor:.2f}"


class PercepcaoGamatec:
    def __init__(
        self,
        calibracao: Dict[str, Any],
        debug: bool = True,
        salvar_crops_debug: bool = False
    ):
        self.cal = dict(calibracao)
        self.debug = debug
        self.salvar_crops_debug = salvar_crops_debug

        self.x_codigo = garantir_int(self.cal.get("x_codigo"))
        self.y_codigo_linha1 = garantir_int(self.cal.get("y_codigo_linha1"))
        self.y_codigo_linha2 = garantir_int(self.cal.get("y_codigo_linha2"))

        self.x_desc = garantir_int(self.cal.get("x_desc"))
        self.x_ult_preco = garantir_int(self.cal.get("x_ult_preco"))
        self.x_final = garantir_int(self.cal.get("x_final"))

        self.w_codigo = garantir_int(self.cal.get("w_codigo", 95))
        self.h_codigo = garantir_int(self.cal.get("h_codigo", 30))

        self.w_desc = garantir_int(self.cal.get("w_desc", 340))
        self.h_desc = garantir_int(self.cal.get("h_desc", 30))

        self.w_ult_preco = garantir_int(self.cal.get("w_ult_preco", 170))
        self.h_ult_preco = garantir_int(self.cal.get("h_ult_preco", 30))

        self.w_final = garantir_int(self.cal.get("w_final", 170))
        self.h_final = garantir_int(self.cal.get("h_final", 30))

        self.offset_y_codigo = garantir_int(self.cal.get("offset_y_codigo", 0))
        self.offset_y_desc = garantir_int(self.cal.get("offset_y_desc", 0))
        self.offset_y_ult = garantir_int(self.cal.get("offset_y_ult", 0))
        self.offset_y_final = garantir_int(self.cal.get("offset_y_final", 0))

        self.passo_linha = max(1, self.y_codigo_linha2 - self.y_codigo_linha1)

        self.screen_w, self.screen_h = pyautogui.size()

        # MODO RÁPIDO OPERACIONAL
        self.max_varredura_linhas = garantir_int(self.cal.get("max_varredura_linhas", 3))

        self.raio_x_codigo = garantir_int(self.cal.get("raio_x_codigo", 2))
        self.raio_y_codigo = garantir_int(self.cal.get("raio_y_codigo", 2))
        self.passo_busca_codigo = garantir_int(self.cal.get("passo_busca_codigo", 2))

        self.raio_x_desc = garantir_int(self.cal.get("raio_x_desc", 2))
        self.raio_y_desc = garantir_int(self.cal.get("raio_y_desc", 2))
        self.passo_busca_desc = garantir_int(self.cal.get("passo_busca_desc", 2))

        self.raio_x_preco = garantir_int(self.cal.get("raio_x_preco", 2))
        self.raio_y_preco = garantir_int(self.cal.get("raio_y_preco", 2))
        self.passo_busca_preco = garantir_int(self.cal.get("passo_busca_preco", 2))

        self.max_variantes_codigo = garantir_int(self.cal.get("max_variantes_codigo", 2))
        self.max_variantes_desc = garantir_int(self.cal.get("max_variantes_desc", 1))
        self.max_variantes_preco = garantir_int(self.cal.get("max_variantes_preco", 2))

        self.log_ocr = bool(self.cal.get("log_ocr", False))

        # AJUSTE INCREMENTAL DE CROP PARA EVITAR HEADER/BORDAS/VAZAMENTO ENTRE COLUNAS
        self.crop_left_codigo = garantir_int(self.cal.get("crop_left_codigo", 2))
        self.crop_top_codigo = garantir_int(self.cal.get("crop_top_codigo", 3))
        self.crop_right_codigo = garantir_int(self.cal.get("crop_right_codigo", 4))
        self.crop_bottom_codigo = garantir_int(self.cal.get("crop_bottom_codigo", 3))

        self.crop_left_desc = garantir_int(self.cal.get("crop_left_desc", 4))
        self.crop_top_desc = garantir_int(self.cal.get("crop_top_desc", 3))
        self.crop_right_desc = garantir_int(self.cal.get("crop_right_desc", 8))
        self.crop_bottom_desc = garantir_int(self.cal.get("crop_bottom_desc", 3))

        self.crop_left_preco = garantir_int(self.cal.get("crop_left_preco", 8))
        self.crop_top_preco = garantir_int(self.cal.get("crop_top_preco", 3))
        self.crop_right_preco = garantir_int(self.cal.get("crop_right_preco", 12))
        self.crop_bottom_preco = garantir_int(self.cal.get("crop_bottom_preco", 3))

        self.exigir_descricao_min_chars = garantir_int(self.cal.get("exigir_descricao_min_chars", 4))
        self.ancorar_com_descricao = bool(self.cal.get("ancorar_com_descricao", True))
        self.ancorar_com_preco = bool(self.cal.get("ancorar_com_preco", True))

    def _log(self, msg: str) -> None:
        if self.debug:
            print(msg, flush=True)

    def capturar_regiao(self, x: int, y: int, w: int, h: int) -> Image.Image:
        x = clamp(x, 0, self.screen_w - 1)
        y = clamp(y, 0, self.screen_h - 1)
        w = max(5, min(w, self.screen_w - x))
        h = max(5, min(h, self.screen_h - y))
        return pyautogui.screenshot(region=(x, y, w, h))

    def _crop_util(
        self,
        img: Image.Image,
        left: int = 0,
        top: int = 0,
        right: int = 0,
        bottom: int = 0
    ) -> Image.Image:
        w, h = img.size
        x1 = clamp(left, 0, max(0, w - 2))
        y1 = clamp(top, 0, max(0, h - 2))
        x2 = clamp(w - right, x1 + 1, w)
        y2 = clamp(h - bottom, y1 + 1, h)
        return img.crop((x1, y1, x2, y2))

    def _preprocess_codigo(self, img: Image.Image) -> List[Image.Image]:
        variantes = []

        base = self._crop_util(
            img,
            left=self.crop_left_codigo,
            top=self.crop_top_codigo,
            right=self.crop_right_codigo,
            bottom=self.crop_bottom_codigo,
        )
        base = base.convert("L")
        base = ImageOps.autocontrast(base)
        base = base.resize((base.width * 3, base.height * 3), Image.Resampling.LANCZOS)
        base = base.filter(ImageFilter.SHARPEN)
        variantes.append(base)

        bw = base.point(lambda p: 255 if p > 170 else 0)
        variantes.append(bw)

        bw2 = base.point(lambda p: 255 if p > 145 else 0)
        variantes.append(bw2)

        return variantes[:self.max_variantes_codigo]

    def _preprocess_numero(self, img: Image.Image) -> List[Image.Image]:
        variantes = []

        base = self._crop_util(
            img,
            left=self.crop_left_preco,
            top=self.crop_top_preco,
            right=self.crop_right_preco,
            bottom=self.crop_bottom_preco,
        )
        base = base.convert("L")
        base = ImageOps.autocontrast(base)
        base = base.resize((base.width * 3, base.height * 3), Image.Resampling.LANCZOS)

        enhancer = ImageEnhance.Contrast(base)
        base = enhancer.enhance(2.2)
        base = base.filter(ImageFilter.SHARPEN)
        variantes.append(base)

        bw = base.point(lambda p: 255 if p > 180 else 0)
        variantes.append(bw)

        bw2 = base.point(lambda p: 255 if p > 150 else 0)
        variantes.append(bw2)

        return variantes[:self.max_variantes_preco]

    def _preprocess_texto(self, img: Image.Image) -> List[Image.Image]:
        variantes = []

        base = self._crop_util(
            img,
            left=self.crop_left_desc,
            top=self.crop_top_desc,
            right=self.crop_right_desc,
            bottom=self.crop_bottom_desc,
        )
        base = base.convert("L")
        base = ImageOps.autocontrast(base)
        base = base.resize((base.width * 2, base.height * 2), Image.Resampling.LANCZOS)

        enhancer = ImageEnhance.Contrast(base)
        base = enhancer.enhance(1.8)
        variantes.append(base)

        bw = base.point(lambda p: 255 if p > 170 else 0)
        variantes.append(bw)

        return variantes[:self.max_variantes_desc]

    def _ocr_texto(self, img: Image.Image, config: str) -> Tuple[str, float]:
        try:
            data = pytesseract.image_to_data(
                img,
                config=config,
                output_type=pytesseract.Output.DICT
            )

            textos = []
            confs = []

            n = len(data["text"])
            for i in range(n):
                txt = (data["text"][i] or "").strip()
                conf = data["conf"][i]
                try:
                    conf = float(conf)
                except Exception:
                    conf = -1

                if txt:
                    textos.append(txt)
                    if conf >= 0:
                        confs.append(conf)

            texto_final = limpar_texto(" ".join(textos))
            confianca = (sum(confs) / len(confs)) if confs else 0.0

            if self.log_ocr:
                self._log(f"[OCR] txt='{texto_final}' conf={confianca:.2f}")

            return texto_final, confianca
        except Exception:
            try:
                txt = pytesseract.image_to_string(img, config=config)
                txt = limpar_texto(txt)
                if self.log_ocr:
                    self._log(f"[OCR fallback] txt='{txt}'")
                return txt, 0.0
            except Exception:
                return "", 0.0

    def _gerar_offsets_busca(self, raio_x: int, raio_y: int, passo: int = 2) -> List[Tuple[int, int]]:
        if raio_x <= 0 and raio_y <= 0:
            return [(0, 0)]

        pontos = [(0, 0)]

        for dy in range(-raio_y, raio_y + 1, passo):
            for dx in range(-raio_x, raio_x + 1, passo):
                if dx == 0 and dy == 0:
                    continue
                pontos.append((dx, dy))

        pontos.sort(key=lambda p: abs(p[0]) + abs(p[1]))
        return pontos

    def _avaliar_codigo(self, txt: str, conf: float) -> Tuple[Optional[str], Optional[str], float]:
        if not txt:
            return None, None, 0.0

        if parece_header_ou_interface(txt):
            return None, None, 0.0

        cod_lido = extrair_digitos_codigo(txt)
        if not cod_lido:
            return None, None, 0.0

        cod_normalizado = normalizar_codigo_para_comparacao(cod_lido)

        score = conf
        if re.fullmatch(r"\d{3,6}", cod_lido):
            score += 30
        if len(cod_lido) in (3, 4):
            score += 10
        if cod_normalizado:
            score += 10
        if txt.strip().isdigit():
            score += 10

        return cod_lido, cod_normalizado, score

    def _avaliar_preco(self, txt: str, conf: float) -> Tuple[Optional[float], float]:
        if not txt:
            return None, 0.0

        if parece_header_ou_interface(txt):
            return None, 0.0

        valor = parse_preco_brasil(txt)
        if valor is None:
            return None, 0.0

        score = conf
        if valor > 0:
            score += 20
        if 0.01 <= valor <= 999999.99:
            score += 10
        if re.search(r"[\.,]\d{2}", _normalizar_texto_preco(txt)):
            score += 10

        return valor, score

    def _avaliar_descricao(self, txt: str, conf: float) -> Tuple[Optional[str], float]:
        txt = limpar_texto(txt)
        if not txt:
            return None, 0.0

        if parece_header_ou_interface(txt):
            return None, 0.0

        if len(txt) < self.exigir_descricao_min_chars:
            return None, 0.0

        if re.fullmatch(r"[\d\W_]+", txt):
            return None, 0.0

        score = conf + min(len(txt), 40)
        return txt, score

    def ler_codigo(self, x: int, y: int, nome_debug: str = "") -> CampoLido:
        melhor = CampoLido(
            valor=None,
            confianca=0.0,
            x=x,
            y=y,
            w=self.w_codigo,
            h=self.h_codigo,
            bruto="",
            valido=False,
            tentativas=0,
            valor_normalizado=None
        )

        offsets = self._gerar_offsets_busca(
            self.raio_x_codigo,
            self.raio_y_codigo,
            self.passo_busca_codigo
        )

        for idx, (dx, dy) in enumerate(offsets, start=1):
            img = self.capturar_regiao(x + dx, y + dy, self.w_codigo, self.h_codigo)

            if self.salvar_crops_debug and nome_debug and idx <= 2:
                salvar_debug_imagem(img, f"{nome_debug}_codigo_raw_{idx}.png")

            variantes = self._preprocess_codigo(img)
            for j, var in enumerate(variantes, start=1):
                txt, conf = self._ocr_texto(
                    var,
                    r'--oem 3 --psm 7 -c tessedit_char_whitelist="0123456789ODILZSBGQ|"'
                )
                cod_lido, cod_normalizado, score = self._avaliar_codigo(txt, conf)

                melhor.tentativas += 1

                if cod_lido and score > melhor.confianca:
                    melhor = CampoLido(
                        valor=cod_lido,
                        confianca=score,
                        x=x + dx,
                        y=y + dy,
                        w=self.w_codigo,
                        h=self.h_codigo,
                        bruto=txt,
                        valido=True,
                        tentativas=melhor.tentativas,
                        valor_normalizado=cod_normalizado
                    )

                    if conf >= 70 and abs(dx) <= 2 and abs(dy) <= 2:
                        return melhor

        return melhor

    def ler_preco(self, x: int, y: int, w: int, h: int, nome_debug: str = "") -> CampoLido:
        melhor = CampoLido(
            valor=None,
            confianca=0.0,
            x=x,
            y=y,
            w=w,
            h=h,
            bruto="",
            valido=False,
            tentativas=0,
            valor_normalizado=None
        )

        offsets = self._gerar_offsets_busca(
            self.raio_x_preco,
            self.raio_y_preco,
            self.passo_busca_preco
        )

        for idx, (dx, dy) in enumerate(offsets, start=1):
            img = self.capturar_regiao(x + dx, y + dy, w, h)

            if self.salvar_crops_debug and nome_debug and idx <= 2:
                salvar_debug_imagem(img, f"{nome_debug}_preco_raw_{idx}.png")

            variantes = self._preprocess_numero(img)
            for j, var in enumerate(variantes, start=1):
                txt, conf = self._ocr_texto(
                    var,
                    r'--oem 3 --psm 7 -c tessedit_char_whitelist="0123456789,.R$ODQILSB|"'
                )
                valor, score = self._avaliar_preco(txt, conf)

                melhor.tentativas += 1

                if valor is not None and score > melhor.confianca:
                    melhor = CampoLido(
                        valor=preco_para_str(valor),
                        confianca=score,
                        x=x + dx,
                        y=y + dy,
                        w=w,
                        h=h,
                        bruto=txt,
                        valido=True,
                        tentativas=melhor.tentativas,
                        valor_normalizado=preco_para_str(valor)
                    )

                    if conf >= 65 and abs(dx) <= 2 and abs(dy) <= 2:
                        return melhor

        return melhor

    def ler_descricao(self, x: int, y: int, nome_debug: str = "") -> CampoLido:
        melhor = CampoLido(
            valor=None,
            confianca=0.0,
            x=x,
            y=y,
            w=self.w_desc,
            h=self.h_desc,
            bruto="",
            valido=False,
            tentativas=0,
            valor_normalizado=None
        )

        offsets = self._gerar_offsets_busca(
            self.raio_x_desc,
            self.raio_y_desc,
            self.passo_busca_desc
        )

        for idx, (dx, dy) in enumerate(offsets, start=1):
            img = self.capturar_regiao(x + dx, y + dy, self.w_desc, self.h_desc)

            if self.salvar_crops_debug and nome_debug and idx <= 1:
                salvar_debug_imagem(img, f"{nome_debug}_desc_raw_{idx}.png")

            variantes = self._preprocess_texto(img)
            for j, var in enumerate(variantes, start=1):
                txt, conf = self._ocr_texto(
                    var,
                    r'--oem 3 --psm 7'
                )
                desc, score = self._avaliar_descricao(txt, conf)

                melhor.tentativas += 1

                if desc and score > melhor.confianca:
                    melhor = CampoLido(
                        valor=desc,
                        confianca=score,
                        x=x + dx,
                        y=y + dy,
                        w=self.w_desc,
                        h=self.h_desc,
                        bruto=txt,
                        valido=True,
                        tentativas=melhor.tentativas,
                        valor_normalizado=desc
                    )

                    if conf >= 55 and abs(dx) <= 2 and abs(dy) <= 2:
                        return melhor

        return melhor

    def _score_ancoragem_linha(self, y_teste: int, indice_debug: int = 0) -> float:
        score = 0.0

        campo_codigo = self.ler_codigo(
            self.x_codigo,
            y_teste + self.offset_y_codigo,
            nome_debug=f"scan_linha_{indice_debug}_codigo" if indice_debug else ""
        )
        if not (campo_codigo.valido and campo_codigo.valor):
            return 0.0

        score += campo_codigo.confianca + 30

        if self.ancorar_com_descricao:
            campo_desc = self.ler_descricao(
                self.x_desc,
                y_teste + self.offset_y_desc,
                nome_debug=f"scan_linha_{indice_debug}_desc" if indice_debug else ""
            )
            if campo_desc.valido and campo_desc.valor:
                score += min(35.0, campo_desc.confianca * 0.35 + 12.0)

        if self.ancorar_com_preco:
            campo_preco = self.ler_preco(
                self.x_ult_preco,
                y_teste + self.offset_y_ult,
                self.w_ult_preco,
                self.h_ult_preco,
                nome_debug=f"scan_linha_{indice_debug}_ult" if indice_debug else ""
            )
            if campo_preco.valido and campo_preco.valor:
                score += min(30.0, campo_preco.confianca * 0.30 + 10.0)

        return score

    def encontrar_primeira_linha_valida(
        self,
        max_varredura_linhas: Optional[int] = None
    ) -> Optional[int]:
        if max_varredura_linhas is None:
            max_varredura_linhas = self.max_varredura_linhas

        y_base_inicial = self.y_codigo_linha1

        self._log(f"[PERCEPCAO] Procurando primeira linha válida em até {max_varredura_linhas} linhas...")

        candidatos = []
        for i in range(max_varredura_linhas):
            y_teste = y_base_inicial + (i * self.passo_linha)
            self._log(f"[PERCEPCAO] Testando linha-base {i + 1} em y={y_teste}")

            score = self._score_ancoragem_linha(y_teste, indice_debug=i + 1)
            if score > 0:
                candidatos.append((score, y_teste))

        if not candidatos:
            self._log("[PERCEPCAO] Nenhuma primeira linha válida encontrada, usando y calibrado.")
            return None

        candidatos.sort(reverse=True, key=lambda t: t[0])
        y_escolhido = candidatos[0][1]
        self._log(f"[PERCEPCAO] Primeira linha válida escolhida em y={y_escolhido}")
        return y_escolhido

    def ler_linha(self, indice_linha: int, y_base: int) -> LinhaPercebida:
        self._log(f"[PERCEPCAO] Lendo linha {indice_linha} em y_base={y_base}")

        nome_base = f"linha_{indice_linha:03d}"

        y_codigo = y_base + self.offset_y_codigo
        y_desc = y_base + self.offset_y_desc
        y_ult = y_base + self.offset_y_ult
        y_final = y_base + self.offset_y_final

        codigo = self.ler_codigo(self.x_codigo, y_codigo, nome_debug=nome_base)
        descricao = self.ler_descricao(self.x_desc, y_desc, nome_debug=nome_base)
        ult_preco = self.ler_preco(
            self.x_ult_preco, y_ult, self.w_ult_preco, self.h_ult_preco,
            nome_debug=nome_base + "_ult"
        )
        final = self.ler_preco(
            self.x_final, y_final, self.w_final, self.h_final,
            nome_debug=nome_base + "_final"
        )

        return LinhaPercebida(
            indice_linha=indice_linha,
            y_base=y_base,
            codigo=codigo,
            descricao=descricao,
            ult_preco=ult_preco,
            final=final
        )

    def _linha_parece_interface(self, linha: LinhaPercebida) -> bool:
        textos = [
            linha.codigo.bruto if linha.codigo else "",
            linha.descricao.bruto if linha.descricao else "",
            linha.ult_preco.bruto if linha.ult_preco else "",
            linha.final.bruto if linha.final else "",
        ]

        hits_header = sum(1 for t in textos if t and parece_header_ou_interface(t))
        campos_validos = sum(
            1 for c in [linha.codigo, linha.descricao, linha.ult_preco, linha.final]
            if c and c.valido and c.valor
        )

        if hits_header >= 2:
            return True
        if hits_header >= 1 and campos_validos <= 1:
            return True
        return False

    def ler_grade(
        self,
        quantidade_linhas: int = 15,
        auto_ancorar_primeira_linha: bool = True
    ) -> List[LinhaPercebida]:
        t0 = time.time()
        self._log(f"[PERCEPCAO] Iniciando leitura da grade com {quantidade_linhas} linhas...")

        if auto_ancorar_primeira_linha:
            y_inicio = self.encontrar_primeira_linha_valida()
            if y_inicio is None:
                y_inicio = self.y_codigo_linha1
        else:
            y_inicio = self.y_codigo_linha1

        linhas = []

        for i in range(quantidade_linhas):
            y_base = y_inicio + (i * self.passo_linha)
            linha = self.ler_linha(i + 1, y_base)

            if self._linha_parece_interface(linha):
                self._log(f"[PERCEPCAO] Linha {i + 1} descartada por parecer header/interface.")
                continue

            linhas.append(linha)

        self._log(f"[PERCEPCAO] Leitura da grade concluída em {time.time() - t0:.2f}s")
        return linhas

    def salvar_json_debug(self, linhas: List[LinhaPercebida], nome: str = "leitura_grade.json") -> str:
        caminho = os.path.join(DEBUG_DIR, nome)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump([ln.to_dict() for ln in linhas], f, ensure_ascii=False, indent=2)
        return caminho


def carregar_calibracao(caminho_json: str) -> Dict[str, Any]:
    with open(caminho_json, "r", encoding="utf-8") as f:
        return json.load(f)
