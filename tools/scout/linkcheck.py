#!/usr/bin/env python3
"""ССЫЛКИ НА ТОВАР — ФОРМА И ЖИВОСТЬ (26.08, владелец: «чтоб всегда были актуальные ссылки»).

Реферальная ссылка — это наш заработок, и она ломается тихо: 26 августа выяснилось, что
партнёрка отдаёт `.../путь/&erid=XXX` без «?», и nonton на такую ссылку отвечал 404, а
divan.ru — 502. Поэтому проверяем две вещи:

1. ФОРМА — дёшево и по ВСЕМУ каталогу: схема http(s), первый параметр через «?», метка `erid`
   не потеряна, ссылка ведёт в магазин, а не на редирект партнёрки.
2. ЖИВОСТЬ — ПЕРЕЕХАЛА в `stock_check.py` (31.08). Здешняя проверка брала 400 ссылок в день
   по кругу в 20 000, писала вердикт прямо в `products.in_stock` (его стирал `load3` наутро)
   и выбирала только `where in_stock` — снятый товар не мог воскреснуть никогда. Наличие теперь
   считается по наблюдениям с подтверждением: `stock_check.py`, `stock_truth.py`.

  linkcheck.py --shape             # проверка формы по всему каталогу (секунды)
"""
import os
import subprocess
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-tAc']
BROKEN_SEP = re.compile(r'^[^?]*&')          # первый параметр без «?» — та самая поломка
AFFILIATE = re.compile(r'^https?://(xf|af|sf)\.gdeslon\.ru/', re.I)


def _rows(q: str) -> list:
    return [r for r in subprocess.run(PSQL + [q], capture_output=True, text=True).stdout.splitlines() if r]


def shape() -> int:
    rows = _rows("select shop||'~'||coalesce(direct_url,'')||'~'||coalesce(url,'') "
                 "from products where in_stock")
    bad = {'нет ссылки': 0, 'первый параметр без ?': 0, 'редирект партнёрки вместо магазина': 0,
           'потеряна метка erid': 0, 'не http(s)': 0}
    per_shop: dict = {}
    for r in rows:
        p = r.split('~')
        if len(p) < 3:
            continue
        shop, d, u = p[0], p[1], p[2]
        why = None
        if not d:
            why = 'нет ссылки'
        elif not d.startswith(('http://', 'https://')):
            why = 'не http(s)'
        elif AFFILIATE.match(d):
            why = 'редирект партнёрки вместо магазина'
        elif BROKEN_SEP.match(d):
            why = 'первый параметр без ?'
        elif 'erid' in u and 'erid' not in d:
            why = 'потеряна метка erid'
        if why:
            bad[why] += 1
            per_shop.setdefault(shop, {}).setdefault(why, 0)
            per_shop[shop][why] += 1
    total_bad = sum(bad.values())
    print(f'форма ссылок: проверено {len(rows)}, с дефектом {total_bad}')
    for k, v in bad.items():
        if v:
            print(f'  {k}: {v}')
    for shop, d in sorted(per_shop.items(), key=lambda x: -sum(x[1].values()))[:5]:
        print(f'  {shop}: ' + ', '.join(f'{k} {v}' for k, v in d.items()))
    return total_bad


if __name__ == '__main__':
    if '--shape' in sys.argv:
        sys.exit(1 if shape() else 0)
    else:
        print(__doc__)
