import os
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

from motor_semantico import obter_motor
import pandas as pd

try:
    print("[*] Iniciando motor...")
    motor = obter_motor()
    print("[*] Lendo base de dados...")
    base = pd.read_csv(r"C:\robo_gamatec_oc\saida\base_krona_final.csv", sep=";", encoding="utf-8-sig")
    print(f"[*] Indexando {len(base)} produtos Krona com enriquecimento...")
    motor.indexar(base, forcar_reindexar=True)
    print("[OK] Indexação concluída")
    
    # Teste 1: PORTA GRELHA
    print("\n[TEST 1] PORTA GRELHA PVC BRANCO 100X100MM")
    r1 = motor.match("PORTA GRELHA PVC BRANCO 100X100MM")
    print(f"  Código retornado: {r1.get('codigo_krona')} (esperado: 944)")
    print(f"  Descricao: {r1.get('descricao_krona')}")
    print(f"  Score: {r1.get('score_total')}")
    print(f"  Match encontrado: {r1.get('match_encontrado')}")
    
    # Teste 2: ELETRODUTO 3/4
    print("\n[TEST 2] ELETRODUTO PVC RIGIDO 3/4 X 3000MM")
    r2 = motor.match("ELETRODUTO PVC RIGIDO 3/4 X 3000MM")
    print(f"  Código retornado: {r2.get('codigo_krona')} (esperado: 1200)")
    print(f"  Descricao: {r2.get('descricao_krona')}")
    print(f"  Score: {r2.get('score_total')}")
    print(f"  Match encontrado: {r2.get('match_encontrado')}")
    
    # Teste 3: TE REDUCAO
    print("\n[TEST 3] TE REDUCAO PVC SOLDAVEL 25X20MM")
    r3 = motor.match("TE REDUCAO PVC SOLDAVEL 25X20MM")
    print(f"  Código retornado: {r3.get('codigo_krona')} (esperado: 463)")
    print(f"  Descricao: {r3.get('descricao_krona')}")
    print(f"  Score: {r3.get('score_total')}")
    print(f"  Match encontrado: {r3.get('match_encontrado')}")
    
    print("\n[CONCLUSÃO] Validação concluída com sucesso")
    
except Exception as e:
    import traceback
    print(f"[ERRO] {e}")
    traceback.print_exc()
