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
from datetime import datetime, timedelta, timezone
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
NOT_TODAY_H = 20  # свежий, но старше 20 ч — «фид не сегодняшний» (после крона 10:40 UTC свежий < 2 ч)
# Гдеслон штампует `yml_catalog date` по МОСКВЕ (03.09: 12:35 при скачивании в 09:40 UTC).
# Раньше строка читалась как локальное время DEV-машины (UTC) → возраст занижен на 3 ч,
# сразу после скачивания он был ОТРИЦАТЕЛЬНЫМ (-2.9 ч в feed-freshness.json).
FEED_TZ = timezone(timedelta(hours=3))
TAIL = 64         # хвост, переносимый между чанками: атрибут merchant_id="99272" не должен рваться


def age_hours(yml_date: str | None, now: float) -> float | None:
    """Возраст фида в часах по штампу Гдеслона (МСК). None — штампа нет или он нечитаем."""
    if not yml_date:
        return None
    try:
        ts = datetime.strptime(yml_date, '%Y-%m-%d %H:%M').replace(tzinfo=FEED_TZ).timestamp()
    except ValueError:
        return None
    return round((now - ts) / 3600, 1)


def state_for(age_h: float, offers: int) -> str:
    if offers == 0:
        return 'empty'
    return 'fresh' if age_h <= FRESH_H else 'degraded' if age_h <= DEGRADED_H else 'stale'


def scan_stream(f, chunk_size: int = 1 << 20) -> tuple[int, set[int]]:
    """Потоково: число офферов и mid магазинов. Маркер «<offer » (с пробелом), иначе обёртка
    <offers> считается оффером; на стыке чанков вычитаем счёт хвоста. mid — из атрибута
    merchant_id (есть у каждого оффера всех 9 выгрузок); хвост TAIL байт переносится в следующий
    чанк, иначе «merchant_id="99|272"» на стыке давал фантомный mid 99 (03.09)."""
    mark = b'<offer '
    offers, mids, buf, tail = 0, set(), b'', b''
    while chunk := f.read(chunk_size):
        offers += (buf + chunk).count(mark) - buf.count(mark)
        if len(mids) < 8:
            for m in re.finditer(rb'merchant_id="(\d+)"', tail + chunk):
                mids.add(int(m.group(1)))
        buf = chunk[-len(mark):]
        tail = (tail + chunk)[-TAIL:]   # копим хвост, а не берём от одного чанка: чанк может быть короче атрибута
    return offers, mids


def _alert(msg: str) -> None:
    subprocess.run(['bash', os.path.join(HERE, 'alert.sh'), msg], timeout=60)


# реестр «фид → mid магазина» (для broken-фидов, где mids из архива не прочитать):
# 777e580d = 116933 nonton.ru (сломан с 11.08); остальные фиды читают mids потоково
FEED_OWNER = {'777e580d462f92086d4875cf39500375e2a113f6': [116933]}


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
                        n, m_ids = scan_stream(f)
                        offers += n
                        mids: set[int] = m_ids
        except (zipfile.BadZipFile, OSError) as e:
            # mids прежней исправной записи сохраняем: иначе compose2/candidates не узнают, ЧЕЙ
            # источник сломан (777e580d = 116933 nonton.ru, Codex 16.08), и карантин не сработает
            _prev_m = (prev.get(h) or {}).get('mids') or []
            # 17.08: у broken-фида известен ХОЗЯИН (реестр FEED_OWNER) — держим его в
            # mids_quarantine_pending, пока владелец не решил карантин: compose2/heal обязаны
            # fail-closed не брать эти SKU в НОВЫЕ pod-комплекты (общий пул не трогаем)
            _pend = sorted(set((prev.get(h) or {}).get('mids_quarantine_pending') or []) | set(FEED_OWNER.get(h, [])) - set(_prev_m))
            out[h] = {'offers': 0, 'error': str(e)[:120], 'state': 'broken', 'mids': _prev_m,
                      'mids_quarantine_pending': _pend,
                      'broken_since': (prev.get(h) or {}).get('broken_since') or datetime.now().strftime('%Y-%m-%d')}
            _alert(f'remlab: фид {h[:12]} не читается ({e}) — работаем на прежних данных БД')
            continue
        age_h = age_hours(yml_date, now)
        if age_h is None:
            age_h = round((now - os.path.getmtime(zp)) / 3600, 1)
        state = state_for(age_h, offers)
        prev_offers = (prev.get(h) or {}).get('offers', 0)
        if state == 'fresh' and age_h > NOT_TODAY_H:
            # не тревога, а WARN в лог шага: Гдеслон опоздал со сборкой, мы взяли вчерашний файл
            # (маркер `WARN:` читает step() в refresh_daily.sh и кладёт в дайджест)
            print(f'WARN: фид {h[:12]} не сегодняшний — yml_date {yml_date} ({age_h:.0f} ч)', flush=True)
        if offers == 0:
            # W5 (аудит 10.08): алертим ЛЮБОЙ переход в empty (в т.ч. первый раз увиденный
            # пустой фид) — раньше «вечно пустой» e2fccbea жил незамеченным месяцами.
            prev_state = (prev.get(h) or {}).get('state')
            if prev_state != 'empty':
                _alert(f'remlab: фид {h[:12]} отдал 0 офферов'
                       f'{f" (было {prev_offers})" if prev_offers else " (пустой)"} — '
                       f'скачался «успешно», но каталог пуст')
        elif state == 'stale':
            _alert(f'remlab: фид {h[:12]} протух — yml_date {yml_date} ({age_h:.0f} ч), '
                   f'товары едут на старых ценах/наличии')
        out[h] = {'offers': offers, 'prev_offers': prev_offers, 'mids': sorted(mids),
                  'yml_date': yml_date, 'age_hours': age_h, 'state': state}
    json.dump(out, open(STATE, 'w'), ensure_ascii=False, indent=1)
    return out


def selftest() -> int:
    import io
    bad = 0

    def check(name, got, want):
        nonlocal bad
        if got != want:
            bad += 1
            print(f'  FAIL {name}: {got!r} != {want!r}')

    # (1) стык чанков: merchant_id рвётся между чанками — фантомного mid быть не должно
    body = b'<offers>' + b'<offer merchant_id="99272" id="1"><name>x</name></offer>' * 3
    for size in (8, 13, 17, 1 << 20):
        n, mids = scan_stream(io.BytesIO(body), chunk_size=size)
        check(f'offers@{size}', n, 3)
        check(f'mids@{size}', mids, {99272})
    # (2) возраст: штамп по МСК; DEV в UTC. 12:35 МСК при now=09:41 UTC → 0.1 ч, не -2.9
    now = datetime(2026, 9, 3, 9, 41, tzinfo=timezone.utc).timestamp()
    check('age_msk', age_hours('2026-09-03 12:35', now), 0.1)
    check('age_yesterday', age_hours('2026-09-02 12:35', now), 24.1)
    check('age_none', age_hours(None, now), None)
    check('age_bad', age_hours('вчера', now), None)
    # (3) состояния
    check('fresh', state_for(2.0, 100), 'fresh')
    check('degraded', state_for(40.0, 100), 'degraded')
    check('stale', state_for(60.0, 100), 'stale')
    check('empty', state_for(2.0, 0), 'empty')
    # (4) порог «не сегодняшний» лежит между свежим (<2 ч) и деградированным (30 ч)
    check('not_today_bounds', 2 < NOT_TODAY_H < FRESH_H, True)
    print('feed_guard selftest:', 'FAIL' if bad else 'ok')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    res = scan()
    for h, r in res.items():
        print(f"{h[:12]}: {r.get('offers', 0):>6} офферов, {r.get('age_hours', '?')} ч, {r['state']}")
    n_bad = sum(1 for r in res.values() if r['state'] in ('empty', 'stale', 'broken'))
    print(f"итого фидов {len(res)}, проблемных {n_bad}")
    sys.exit(0)
