"""Оценка скорости Cycles по Blender Open Data (снимок opendata.blender.org, JSONL): медиана samples/min по устройству и версии Blender.
  python3 od_scores.py <opendata.jsonl> <подстрока CPU> <подстрока GPU> [мин. версия, по умолчанию 4.4]
Берём записи, где единственное вычислительное устройство — ровно искомое (CPU — тип CPU; GPU — OptiX/CUDA/HIP без CPU рядом), и сцены
классических бенчмарков (monster, junkshop, classroom); баллы — сумма samples_per_minute по трём сценам не нужна, смотрим по сценам."""
import json
import re
import statistics
import sys
from collections import defaultdict

path, cpu_q, gpu_q = sys.argv[1], sys.argv[2].lower(), sys.argv[3].lower()
minv = tuple(int(x) for x in (sys.argv[4] if len(sys.argv) > 4 else '4.4').split('.'))
res = defaultdict(list)
seen = 0
with open(path, encoding='utf-8') as f:
    for line in f:
        if cpu_q not in line.lower() and gpu_q not in line.lower():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        for r in rec.get('data', []):
            try:
                ver = r['blender_version']['version']
                vt = tuple(int(x) for x in re.findall(r'\d+', ver)[:2])
                if vt < minv:
                    continue
                devs = r['device_info']['compute_devices']
                names = [d['name'].lower() for d in devs]
                runtime = r['device_info'].get('device_type') or ''
                sc = r['scene']['label']
                spm = r['stats']['samples_per_minute']
            except (KeyError, TypeError, ValueError):
                continue
            if len(devs) != 1:
                continue
            nm = names[0]
            if cpu_q in nm and devs[0]['type'] == 'CPU':
                res[('CPU ' + devs[0]['name'], ver.rsplit('.', 1)[0], sc)].append(spm)
            elif gpu_q in nm and devs[0]['type'] != 'CPU':
                res[(devs[0]['type'] + ' ' + devs[0]['name'], ver.rsplit('.', 1)[0], sc)].append(spm)
            seen += 1
print('записей', seen)
for k in sorted(res):
    v = res[k]
    print(f'{k[0]:50s} blender {k[1]:5s} {k[2]:12s} n={len(v):4d}  медиана {statistics.median(v):8.1f}  samples/min')
