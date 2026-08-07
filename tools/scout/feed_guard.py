#!/usr/bin/env python3
"""Предохранитель фидов ДО загрузки в БД (T0 мастер-плана truth-first, урок 203).

Два класса тихих сбоев, которые load3 не ловит:
  1) исторически непустой фид вдруг отдаёт 0 офферов — скачивание «успешно» (файл валиден),
     load3 просто не видит его товаров, и никто не алертится (так молчал 10-й фид);
  2) фид протух: файл лежит, но `yml_catalog date` старше SLA — товары едут в сеты
     с ценами/наличием недельной давности.

Пишет tools/scout/feed-freshness.json:
  {hash: {offers, prev_offers, yml_date, age_hours, state: fresh|degraded|stale|empty}}
Алертит через alert.sh; выход всегда 0 (guard не должен ронять конвейер — только кричать).
Запуск: refresh_daily.sh шаг feed_guard, либо руками: python feed_guard.py
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'feed-freshness.json')
FRESH_H = 30      # yml_catalog date моложе 30 ч — fresh (фид регенерится ~ежесуточно)
DEGRADED_H = 54   # 30–54 ч — degraded (одна пропущенная регенерация); старше — stale


def _alert(msg: str) -> None:
    subprocess.run(['bash', os.path.join(HERE, 'alert.sh'), msg], timeout=60)


def scan() -> dict:
    prev = {}
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE))
        except json.JSONDecodeError:
            pass
    now = time.time()
    out = {}
    for zp in sorted(glob.glob(os.path.join(HERE, 'feeds2', '*.xml.zip'))):
        h = os.path.basename(zp).split('.')[0]
        offers, yml_date = 0, None
        try:
            with zipfile.ZipFile(zp) as z:
                for name in z.namelist():
                    with z.open(name) as f:
                        head = f.read(4096).decode('utf-8', 'ignore')
                        m = re.search(r'yml_catalog date="([^"]+)"', head)
                        if m:
                            yml_date = m.group(1)
                    with z.open(name) as f:
                        # потоковый счёт без разбора дерева; маркер «<offer » (с пробелом),
                        # иначе тег-обёртка <offers> считается оффером; на стыке чанков
                        # вычитаем счёт хвоста, чтобы не задвоить маркер
                        mark = b'<offer '
                        buf = b''
                        while chunk := f.read(1 << 20):
                            offers += (buf + chunk).count(mark) - buf.count(mark)
                            buf = chunk[-len(mark):]
        except (zipfile.BadZipFile, OSError) as e:
            out[h] = {'offers': 0, 'error': str(e)[:120], 'state': 'broken'}
            _alert(f'remlab: фид {h[:12]} не читается ({e}) — работаем на прежних данных БД')
            continue
        age_h = None
        if yml_date:
            try:
                age_h = round((now - time.mktime(time.strptime(yml_date, '%Y-%m-%d %H:%M'))) / 3600, 1)
            except ValueError:
                pass
        if age_h is None:
            age_h = round((now - os.path.getmtime(zp)) / 3600, 1)
        state = ('fresh' if age_h <= FRESH_H else 'degraded' if age_h <= DEGRADED_H else 'stale')
        prev_offers = (prev.get(h) or {}).get('offers', 0)
        if offers == 0:
            state = 'empty'
            # алертим только исторически непустой: вечно пустой фид — известная особенность,
            # о нём алерт один раз при переходе непустой→пустой
            if prev_offers > 100:
                _alert(f'remlab: фид {h[:12]} отдал 0 офферов (было {prev_offers}) — '
                       f'скачался «успешно», но каталог пуст')
        elif state == 'stale':
            _alert(f'remlab: фид {h[:12]} протух — yml_date {yml_date} ({age_h:.0f} ч), '
                   f'товары едут на старых ценах/наличии')
        out[h] = {'offers': offers, 'prev_offers': prev_offers,
                  'yml_date': yml_date, 'age_hours': age_h, 'state': state}
    json.dump(out, open(STATE, 'w'), ensure_ascii=False, indent=1)
    return out


if __name__ == '__main__':
    res = scan()
    for h, r in res.items():
        print(f"{h[:12]}: {r.get('offers', 0):>6} офферов, {r.get('age_hours', '?')} ч, {r['state']}")
    n_bad = sum(1 for r in res.values() if r['state'] in ('empty', 'stale', 'broken'))
    print(f"итого фидов {len(res)}, проблемных {n_bad}")
    sys.exit(0)
