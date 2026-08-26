#!/usr/bin/env python3
"""ССЫЛКИ НА ТОВАР — ФОРМА И ЖИВОСТЬ (26.08, владелец: «чтоб всегда были актуальные ссылки»).

Реферальная ссылка — это наш заработок, и она ломается тихо: 26 августа выяснилось, что
партнёрка отдаёт `.../путь/&erid=XXX` без «?», и nonton на такую ссылку отвечал 404, а
divan.ru — 502. Поэтому проверяем две вещи:

1. ФОРМА — дёшево и по ВСЕМУ каталогу: схема http(s), первый параметр через «?», метка `erid`
   не потеряна, ссылка ведёт в магазин, а не на редирект партнёрки.
2. ЖИВОСТЬ — выборочно и по кругу: магазины отвечают капчей на массовые заходы, поэтому
   ежедневно берём N самых давно проверенных ссылок. 404/410 — мёртвая; 403/429/капча —
   «не знаю» (не наказываем товар за антибот).

  linkcheck.py --shape             # проверка формы по всему каталогу (секунды)
  linkcheck.py --probe --limit 400 # выборочная проверка живости, по кругу
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'link-alive.json')
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


def _probe(url: str) -> str:
    """→ 'ok' | 'dead' | 'unknown' (антибот/сеть — не приговор товару)."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html'})
        with urllib.request.urlopen(req, timeout=20) as f:
            body = f.read(2048).decode('utf-8', 'replace').lower()
            if 'showcaptcha' in f.geturl() or 'captcha' in body:
                return 'unknown'
            return 'ok' if 200 <= f.status < 400 else 'unknown'
    except urllib.error.HTTPError as e:
        return 'dead' if e.code in (404, 410) else 'unknown'
    except Exception:
        return 'unknown'


def probe(limit: int = 400, workers: int = 8) -> None:
    mem = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    rows = _rows("select coalesce(direct_url,'') from products where in_stock and direct_url is not null")
    rows.sort(key=lambda u: mem.get(u, {}).get('ts', 0))          # по кругу: давние — первыми
    todo = rows[:limit]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for u, st in zip(todo, ex.map(_probe, todo)):
            prev = mem.get(u) or {}
            fails = int(prev.get('fails') or 0) + 1 if st == 'dead' else 0
            mem[u] = {'state': st, 'ts': int(time.time()), 'fails': fails}
    json.dump(mem, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    dead = [u for u in todo if mem[u]['state'] == 'dead']
    unk = sum(1 for u in todo if mem[u]['state'] == 'unknown')
    print(f'живость ссылок: проверено {len(todo)} (всего в базе {len(rows)}), '
          f'мёртвых {len(dead)}, не определилось {unk}')
    for u in dead[:5]:
        print('  мертва:', u[:100])
    # ДВА РАЗА ПОДРЯД 404 — ТОВАРА НЕТ (26.08). Один раз мог быть выкат магазина; на втором
    # снимаем с продажи, и товар уходит из пула подбора и из банка через контракт слота.
    confirmed = [u for u in dead if int(mem[u].get('fails') or 0) >= 2]
    if confirmed:
        vals = ','.join("'" + u.replace("'", "''") + "'" for u in confirmed)
        subprocess.run(PSQL + [f"update products set in_stock=false where direct_url in ({vals})"],
                       capture_output=True, text=True)
        print(f'снято с продажи по подтверждённому 404: {len(confirmed)}')
    # системная поломка (а не единичный товар) — повод для тревоги
    if todo and len(dead) * 100 / len(todo) > 20:
        os.system(f'bash {os.path.join(HERE, "alert.sh")} '
                  f'"remlab: {len(dead)}/{len(todo)} ссылок на товар отдают 404 — проверить формирование ссылок"')


if __name__ == '__main__':
    if '--probe' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 400
        probe(lim)
    elif '--shape' in sys.argv:
        sys.exit(1 if shape() else 0)
    else:
        print(__doc__)
