#!/usr/bin/env python3
"""ЖИВЫЕ ГРУППЫ SALAD И ИХ ДЕРЖАТЕЛИ (T-20261124-42/1, урок 929). Только чтение: один GET списка контейнеров, ничего не создаёт и не гасит. $0.

Строка на живую группу: `trial-x · живых 1 · держатель pid 1234 / T-… · жив · молчит 3 мин`; итог `ЖИВО машин всего (оценка): N · из них проба … · ❗ без держателя: K`.
❗ — группа с МЁРТВЫМ держателем, без записи в реестре или с истёкшей тёплой меткой. «чужая машина» (запись с другого host) проверить нельзя — не ❗, но видно.
Код выхода: 1 при K>0 (обход замечает), 0 иначе, 2 — список не получен.

    set -a; . ~/scout-scenes/salad.env; set +a; python3 tools/ops/salad_live.py        # ключ — из окружения, не печатается
    python3 tools/ops/salad_live.py --groups-file список.json --registry папка          # без сети (тесты/разбор)
Реестр пишут `kit_driver.create_and_start` и `batch_show.ensure_group_started` (`tools/scout/salad/holder_registry.py`).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scout', 'salad'))
import holder_registry as HR  # noqa: E402

URL = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'
UA = 'remlab-mesh/1.0'


def fetch_groups(key: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(URL, headers={'Salad-Api-Key': key, 'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def live_groups(listing: dict) -> list[dict]:
    """Живые/поднимающиеся группы — та же логика, что в salad_live.sh: статус не stopped/failed или есть allocating/creating/running."""
    rows = []
    for x in listing.get('items') or []:
        cs = x.get('current_state') or {}
        st = cs.get('status')
        ic = cs.get('instance_status_counts') or {}
        run = sum(int(ic.get(k) or 0) for k in ('allocating_count', 'creating_count', 'running_count'))
        if st not in ('stopped', 'failed') or run:
            live = max(run, 1 if st in ('running', 'deploying', 'pending') else 0)
            rows.append({'name': x.get('name'), 'status': st, 'replicas': x.get('replicas'), 'running': ic.get('running_count'), 'live': live})
    return rows


def verdict(rec: dict | None, now: float, host: str | None = None, alive_fn=None) -> tuple[str, str]:
    """(вид, текст). Виды: ok | warm | foreign | dead | norec | warm_expired. ❗ — dead, norec, warm_expired."""
    if not rec:
        return 'norec', 'НЕТ ЗАПИСИ (держатель неизвестен)'
    who = f'держатель pid {rec.get("pid")} / {rec.get("task") or "?"}'
    quiet = max(0, int((now - float(rec.get('heartbeat_at') or rec.get('started_at') or now)) // 60))
    wu = rec.get('warm_until')
    if wu is not None:
        left = int((float(wu) - now) // 60)
        if float(wu) > now:
            return 'warm', f'{who} · тёплая нода, осталось {left} мин (гасит sweep)'
        return 'warm_expired', f'{who} · тёплая метка ИСТЕКЛА {-left} мин назад'
    st = HR.holder_state(rec, host, alive_fn)
    if st == 'alive':
        return 'ok', f'{who} · жив · молчит {quiet} мин'
    if st == 'foreign':
        return 'foreign', f'{who} · чужая машина ({rec.get("host")}), не проверить · молчит {quiet} мин'
    return 'dead', f'{who} · МЁРТВ · молчит {quiet} мин'


def report(rows: list[dict], registry: dict[str, dict], now: float, host: str | None = None, alive_fn=None) -> tuple[list[str], int]:
    lines, bad = [], 0
    for r in rows:
        kind, text = verdict(registry.get(r['name']), now, host, alive_fn)
        flag = '❗ ' if kind in ('dead', 'norec', 'warm_expired') else '   '
        bad += flag.startswith('❗')
        lines.append(f'{flag}{str(r["name"]):<32} · живых {r["live"]} ({r["status"]}) · {text}')
    live_names = {r['name'] for r in rows}
    stale = sorted(g for g in registry if g not in live_names)
    if stale:
        lines.append(f'   записи без живой группы (после стопа не через драйвер, мусор, в итог не входят): {", ".join(stale)}')
    total = sum(r['live'] for r in rows)
    trial = sum(r['live'] for r in rows if str(r['name']).startswith('trial-'))
    lines.append(f'ЖИВО машин всего (оценка): {total} · из них проба (trial-*): {trial} · ❗ без держателя: {bad}')
    return lines, bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--groups-file', default='', help='список групп из файла вместо GET (без сети)')
    ap.add_argument('--registry', default='', help='папка реестра (по умолчанию $SALAD_HOLDERS_DIR или ~/.local/state/remlab/salad-holders)')
    a = ap.parse_args(argv)
    try:
        if a.groups_file:
            with open(a.groups_file, encoding='utf-8') as f:
                listing = json.load(f)
        else:
            key = os.environ.get('SALAD_API_KEY')
            if not key:
                print('нет SALAD_API_KEY: сперва `set -a; . ~/scout-scenes/salad.env; set +a`', file=sys.stderr)
                return 2
            listing = fetch_groups(key)
    except Exception as e:  # noqa: BLE001 — текст ошибки без заголовков запроса (ключ там)
        print(f'список групп не получен: {type(e).__name__}', file=sys.stderr)
        return 2
    lines, bad = report(live_groups(listing), HR.read_all(a.registry or None), time.time(), socket.gethostname())
    print('\n'.join(lines))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
