# -*- coding: utf-8 -*-
"""
testes/baseline_oc.py

Gera planilhas de referencia (baseline de regressao) para um conjunto de OCs,
sem mover ficheiros nem gravar no CRM. Uso:

    python testes/baseline_oc.py antes
    python testes/baseline_oc.py depois
    python testes/baseline_oc.py comparar antes depois
"""
import sys
import os
import glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pandas as pd

from processar_oc_individual_pasta_ajustado import (
    extrair_individual,
    gerar_planilha_enxuta_individual,
    montar_saida_oc,
)
from app import etapa_matching, etapa_unidade

SAMPLES = [
    "processados_oc/Ped._MRV4509562009.pdf",
    "processados_oc/Ped._MRV4509650024_SENSIA_CITY_GALLERIA.pdf",
    "processados_oc/180-_KRONA_-_PALAZZO.pdf",
    "processados_oc/OC_002076_-_KRONA_-_PAVINI.pdf",
    "processados_oc/PedidoCompra4364490044191835194.pdf",
    "processados_oc/EMAIL_Pedido_908843.pdf",
    "processados_oc/Pedido_904365.pdf",
    "processados_oc/200.pdf",
    "processados_oc/ActiveReports_Document-20260529-144838_1.pdf",
    "processados_oc/Bling_-_Pedido_de_Compra_KRONA.pdf",
]


def rodar(rotulo: str) -> str:
    outdir = os.path.join(BASE, "testes", f"baseline_{rotulo}")
    os.makedirs(outdir, exist_ok=True)

    for rel in SAMPLES:
        caminho = os.path.join(BASE, rel)
        nome = os.path.splitext(os.path.basename(rel))[0]
        if not os.path.exists(caminho):
            print(f"[SKIP] {nome}: nao encontrado")
            continue
        print(f"\n===== {nome} =====")
        linhas = []
        try:
            debug = os.path.join(outdir, f"{nome}_debug.txt")
            df = extrair_individual(caminho, debug)
            linhas.append(f"itens_extraidos={len(df)}")
            if "status_extracao" in df.columns:
                linhas.append("status=" + str(df["status_extracao"].value_counts().to_dict()))
            if "observacoes" in df.columns:
                obs = " ".join(str(o) for o in df["observacoes"].astype(str).tolist()[:3])
                linhas.append(f"observacoes_amostra={obs[:160]}")
            validos = df[df["status_extracao"] != "falhou"] if "status_extracao" in df.columns else df
            if validos.empty:
                linhas.append("ERRO=todos_itens_falharam")
            else:
                dm = etapa_matching(validos.copy())
                dfinal = etapa_unidade(dm)
                if "tipo_match" in dfinal.columns:
                    linhas.append("matches=" + str(dfinal["tipo_match"].value_counts().to_dict()))
                csv = os.path.join(outdir, f"{nome}_planilha.csv")
                xlsx = os.path.join(outdir, f"{nome}_planilha.xlsx")
                gerar_planilha_enxuta_individual(dfinal, csv, xlsx)
                # resumo estavel (sem timestamps) para dif
                pd.DataFrame([{"linha": l for l in linhas}], index=[0]).to_csv(
                    os.path.join(outdir, f"{nome}_resumo.csv"), index=False, encoding="utf-8")
                # tambem copia o resultado processado para dif detalhado
                dfinal.to_csv(os.path.join(outdir, f"{nome}_processado.csv"),
                              index=False, sep=";", encoding="utf-8-sig")
        except Exception as e:
            linhas.append(f"ERRO={type(e).__name__}: {e}")
            pd.DataFrame([{"linha": l for l in linhas}], index=[0]).to_csv(
                os.path.join(outdir, f"{nome}_resumo.csv"), index=False, encoding="utf-8")
        for l in linhas:
            print("  " + l)
    print(f"\nBaseline gravado em: {outdir}")
    return outdir


def comparar(rotulo_a: str, rotulo_b: str) -> None:
    dir_a = os.path.join(BASE, "testes", f"baseline_{rotulo_a}")
    dir_b = os.path.join(BASE, "testes", f"baseline_{rotulo_b}")
    regressoes = 0
    for rel in SAMPLES:
        nome = os.path.splitext(os.path.basename(rel))[0]
        a = os.path.join(dir_a, f"{nome}_planilha.csv")
        b = os.path.join(dir_b, f"{nome}_planilha.csv")
        if not (os.path.exists(a) and os.path.exists(b)):
            print(f"[{nome}] presente apenas em um dos lados — verificar")
            continue
        da = pd.read_csv(a, sep=";", encoding="utf-8-sig").fillna("")
        db = pd.read_csv(b, sep=";", encoding="utf-8-sig").fillna("")
        if da.equals(db):
            print(f"[{nome}] IGUAL ({len(da)} itens)")
        else:
            regressoes += 1
            print(f"[{nome}] DIFERENTE — antes:{len(da)} depois:{len(db)}")
    print(f"\n{regressoes} OC(s) com diferenca.")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "comparar":
        comparar(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2:
        rodar(sys.argv[1])
    else:
        print(__doc__)
