# -*- coding: utf-8 -*-
"""Test validation script for enriched semantic matching"""
import os
import sys

os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

try:
    from motor_semantico import obter_motor
    import pandas as pd
    
    print("[*] Carregando motor semântico...")
    motor = obter_motor()
    
    print("[*] Carregando base Krona...")
    base = pd.read_csv(
        r"C:\robo_gamatec_oc\saida\base_krona_final.csv",
        sep=";",
        encoding="utf-8-sig"
    )
    print(f"[*] Base carregada: {len(base)} produtos")
    
    print("[*] Reindexando com enriquecimento...")
    motor.indexar(base, forcar_reindexar=True)
    print("[OK] Indexação completa")
    
    # TEST 1
    print("\n" + "="*70)
    print("[TEST 1] PORTA GRELHA PVC BRANCO 100X100MM")
    print("="*70)
    r1 = motor.match("PORTA GRELHA PVC BRANCO 100X100MM")
    print(f"Código Krona: {r1.get('codigo_krona')}")
    print(f"Descrição: {r1.get('descricao_krona')}")
    print(f"Score: {r1.get('score_total')}")
    print(f"Tipo Match: {r1.get('tipo_match')}")
    print(f"Match Encontrado: {r1.get('match_encontrado')}")
    
    # TEST 2
    print("\n" + "="*70)
    print("[TEST 2] ELETRODUTO PVC RIGIDO 3/4 X 3000MM")
    print("="*70)
    r2 = motor.match("ELETRODUTO PVC RIGIDO 3/4 X 3000MM")
    print(f"Código Krona: {r2.get('codigo_krona')}")
    print(f"Descrição: {r2.get('descricao_krona')}")
    print(f"Score: {r2.get('score_total')}")
    print(f"Tipo Match: {r2.get('tipo_match')}")
    print(f"Match Encontrado: {r2.get('match_encontrado')}")
    
    # TEST 3
    print("\n" + "="*70)
    print("[TEST 3] TE REDUCAO PVC SOLDAVEL 25X20MM")
    print("="*70)
    r3 = motor.match("TE REDUCAO PVC SOLDAVEL 25X20MM")
    print(f"Código Krona: {r3.get('codigo_krona')}")
    print(f"Descrição: {r3.get('descricao_krona')}")
    print(f"Score: {r3.get('score_total')}")
    print(f"Tipo Match: {r3.get('tipo_match')}")
    print(f"Match Encontrado: {r3.get('match_encontrado')}")
    
    print("\n" + "="*70)
    print("[CONCLUSÃO] Validação concluída com sucesso")
    print("="*70)
    
except Exception as e:
    import traceback
    print(f"\n[ERRO] {e}")
    traceback.print_exc()
    sys.exit(1)
