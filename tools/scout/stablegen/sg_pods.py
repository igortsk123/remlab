"""Список подов RunPod учётки (только чтение): id, имя, статус, цена/час. Ключ — из банка (sg_runpod.load_key), на экран не выводится.
  python3 sg_pods.py [id_пода]   → «подов N» и строки по каждому; с id — ещё поля пода (статус, машина, образ, время работы, ошибка), без переменных окружения"""
import sys

import sg_runpod

SHOW = ('desiredStatus', 'lastStatusChange', 'imageName', 'costPerHr', 'cost', 'adjustedCostPerHr', 'machineId', 'gpu', 'vcpuCount', 'memoryInGb', 'containerDiskInGb',
        'uptimeSeconds', 'runtime', 'consumerUserId', 'publicIp', 'portMappings', 'ports', 'lastStartedAt', 'machine', 'cloud', 'createdAt', 'interruptible', 'image')

api = sg_runpod.Api(sg_runpod.load_key())
res = api.call('GET', '/v2/pods')
pods = res[1] if isinstance(res, tuple) else res
pods = pods if isinstance(pods, list) else (pods or {}).get('pods', [])
print(f'подов {len(pods)}')
for p in pods:
    print(p.get('id'), p.get('name'), p.get('desiredStatus'), p.get('costPerHr'))
if len(sys.argv) > 1:
    c, r = api.call('GET', f'/v2/pods/{sys.argv[1]}')
    print('прямо', sys.argv[1], c)
    for k in SHOW:
        if k in r:
            print(' ', k, '=', str(r[k])[:300])
