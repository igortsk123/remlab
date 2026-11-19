#!/usr/bin/env python3
"""ЖИВЫЕ ЦЕНЫ КЛАССОВ GPU SALAD (T-20261118-91/2, только чтение): GET /organizations/<орг>/gpu-classes — цена за час по приоритетам.
Печатает только имя, id и цены (без ключей). Запуск (pakardev): ~/venvs/scout/bin/python live_prices.py [часть-имени …]"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import migrate_groups as MG  # noqa: E402


def main() -> int:
    MG.env_from_file()
    m = re.match(r'(.*?/organizations/[^/]+)', MG.API)
    if not m:
        print('не разобрала адрес API')
        return 2
    url = m.group(1) + '/gpu-classes'
    req = urllib.request.Request(url, headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0'})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    want = [w.lower() for w in sys.argv[1:]]
    for c in d.get('items', []):
        nm = c.get('name', '')
        if want and not any(w in nm.lower() for w in want):
            continue
        print(c.get('id'), nm, json.dumps(c.get('prices'), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
