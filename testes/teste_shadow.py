import logging
logging.basicConfig(level=logging.DEBUG)

import pandas as pd
from matcher import carregar_base_krona
import os, time, json, threading

base = carregar_base_krona()

item = {
    'descricao_oc': 'TUBO PVC SOLDAVEL 25MM 6M',
    'descricao_normalizada': 'TUBO PVC SOLDAVEL 25MM 6M',
    'observacoes': []
}
resultado_fake = {
    'tipo_match': 'MATCH_DESCRICAO_REVISAR',
    'codigo_krona': 24,
    'score_total': 0.75
}

# roda a funcao interna diretamente, sem thread
from shadow_mode import _rodar_shadow
print('Rodando _rodar_shadow diretamente...')
_rodar_shadow(item, resultado_fake, base)
print('Concluido.')

shadow = r'C:\robo_gamatec_oc\saida\shadow_mode.jsonl'
errors = r'C:\robo_gamatec_oc\saida\shadow_errors.log'
print('shadow existe:', os.path.exists(shadow))
print('errors existe:', os.path.exists(errors))
if os.path.exists(errors):
    print(open(errors, encoding='utf-8').read())
if os.path.exists(shadow):
    print(open(shadow, encoding='utf-8').read())