"""Список подов RunPod учётки (только чтение): id, имя, статус, цена/час. Ключ — из банка (sg_runpod.load_key), на экран не выводится.
  python3 sg_pods.py [id_пода]   → «подов N» и строки по каждому; с id — ещё прямой запрос этого пода"""
import json
import sys

import sg_runpod

api = sg_runpod.Api(sg_runpod.load_key())
res = api.call('GET', '/v2/pods')
print('ответ /pods:', type(res).__name__, str(res)[:300].replace('\n', ' '))
pods = res[1] if isinstance(res, tuple) else res
pods = pods if isinstance(pods, list) else (pods or {}).get('pods', [])
print(f'подов {len(pods)}')
for p in pods:
    print(p.get('id'), p.get('name'), p.get('desiredStatus'), p.get('costPerHr'))
if len(sys.argv) > 1:
    r = api.call('GET', f'/v2/pods/{sys.argv[1]}')
    print('прямо', sys.argv[1], str(r)[:300].replace('\n', ' '))
