#!/usr/bin/env python3
"""ПРОБА СТОРОЖА ПУСТЫХ ВИДОВ на Salad (T-20261118-04/13, ❹): опытная группа поднимается, N заданий перекраски по одному
(`shape_url` + `_dump`), группа гасится — в любом случае (finally) и по потолку времени.

  ~/venvs/scout/bin/python grey_probe.py <probe.json> --group mesh-q-greytop-canary --queue mesh-q-greytop \
      --run t0413 [--ceiling-min 55] [--no-start] [--only <sku-часть>]

`probe.json` — список {sku, role, dims{w,d,h,dia}, image_url, shape_url}. Потолок: «запущена, но не закрыта» дольше
`--ceiling-min` минут — группа гасится, оставшиеся задания снимаются (4060 Ti low ≈ $0,10/ч: 55 мин ≈ 8 ₽).
Итог по каждому заданию — `<out>/<sku>.result.json` (ответ воркера, в нём `view_guard`) и общая строка в `<out>/summary.json`.
Замок конвейера держим, пока идёт проба (иначе «мёртвая рука» сервера погасит группу через 30 мин).
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import queue_run as Q  # noqa: E402

POLL_S = 20
JOB_MAX_S = 20 * 60   # одно задание перекраски: ~2–5 мин; дольше 20 — что-то не так


def log(msg: str) -> None:
    print(f'{time.strftime("%H:%M:%S", time.gmtime())} UTC {msg}', flush=True)


def group_state(g: str) -> str | None:
    code, d = Q.req('GET', f'/containers/{g}')
    return (d.get('current_state') or {}).get('status') if code == 200 else None


def ready(g: str) -> int | None:
    return Q.ready_by_group([g]).get(g)


def stop(g: str, wait_s: int = 300) -> bool:
    code, _ = Q.req('POST', f'/containers/{g}/stop', None, 60)
    log(f'stop {g}: HTTP {code}')
    t0 = time.time()
    while time.time() - t0 < wait_s:
        st = group_state(g)
        if st in ('stopped', 'pending'):   # pending — состояние группы, ни разу не запускавшейся
            log(f'группа {g}: {st}, счёт не идёт')
            return True
        time.sleep(10)
    log(f'!! группа {g} за {wait_s} с не остановилась (сейчас {group_state(g)}) — проверь портал')
    return False


def build_job(e: dict, run: str) -> dict:
    return {'sku': e['sku'], 'role': e['role'], 'image_url': e['image_url'], 'dims_cm': e.get('dims') or {},
            'seed': int(e.get('seed') or 0), 'shape_url': e['shape_url'],
            'params': {'_dump': 1, '_run': run}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('probe')
    ap.add_argument('--group', required=True)
    ap.add_argument('--queue', required=True)
    ap.add_argument('--run', default='probe')
    ap.add_argument('--out', default=None)
    ap.add_argument('--ceiling-min', type=float, default=55)
    ap.add_argument('--no-start', action='store_true')
    ap.add_argument('--warm-until', default=None, help='HH:MM UTC: ждать прогрева машины не дольше этого времени (по умолчанию — потолок от старта)')
    ap.add_argument('--only', default=None)
    ap.add_argument('--keep', action='store_true', help='не гасить группу в конце (следующий прогон ждёт её тёплой)')
    a = ap.parse_args()
    entries = json.load(open(a.probe, encoding='utf-8'))
    if a.only:
        entries = [e for e in entries if a.only in e['sku']]
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.probe)), f'run-{a.run}')
    os.makedirs(out, exist_ok=True)
    log(f'замок конвейера: {Q.hold_lock()}')
    t_start = time.time()
    summary, rc = [], 1
    try:
        if not a.no_start:
            code, d = Q.req('POST', f'/containers/{a.group}/start', None, 60)
            log(f'start {a.group}: HTTP {code} {"" if code in (200, 202) else d}')
            if code not in (200, 202):
                return 1
        # ждём первую готовую машину (прогрев модели; закачка образа не тарифицируется)
        warm_deadline = t_start + a.ceiling_min * 60
        if a.warm_until:
            hh, mm = map(int, a.warm_until.split(':'))
            lt = time.gmtime()
            warm_deadline = calendar.timegm((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, 0))
        t_ready = None
        while time.time() < warm_deadline:
            r = ready(a.group)
            if r:
                log(f'готовых машин: {r} (через {time.time() - t_start:.0f} с)')
                t_ready = time.time()   # с этого момента тарифицируется: потолок денег считаем от него
                break
            time.sleep(30)
        else:
            log('!! машина не прогрелась до потолка')
            return 1
        for e in entries:
            if time.time() - t_ready > a.ceiling_min * 60:
                log('!! потолок времени — остаток заданий не кладу')
                break
            job = build_job(e, a.run)
            qid, why = Q.submit(a.queue, job, {'sku': job['sku'], 'seed': job['seed'], 'by': 'grey_probe'})
            if not qid:
                log(f'!! {e["sku"]} не положено: {why}')
                summary.append({'sku': e['sku'], 'status': 'not_submitted', 'why': why})
                continue
            log(f'{e["sku"]}: положено {qid}')
            t0, seen, res = time.time(), None, None
            while time.time() - t0 < JOB_MAX_S and time.time() - t_ready < a.ceiling_min * 60 + 300:
                code, d = Q.get(a.queue, qid)
                st = d.get('status') if code == 200 else f'HTTP {code}'
                if st != seen:
                    seen = st
                    log(f'  {e["sku"]}: {st} (+{time.time() - t0:.0f} с)')
                if st in ('succeeded', 'failed', 'cancelled') or code == 404:
                    res = Q.to_result(d, job) if code == 200 else {'status': 'gone'}
                    break
                time.sleep(POLL_S)
            if res is None:
                Q.cancel(a.queue, qid)
                res = {'status': 'timeout'}
            res['wall_s'] = round(time.time() - t0, 1)
            res['qid'] = qid
            fn = e['sku'].split(':')[-1]
            json.dump(res, open(os.path.join(out, f'{fn}.result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            vg = res.get('view_guard') or {}
            log(f'  итог {e["sku"]}: {res.get("status")} {res["wall_s"]} с; view_guard dropped={vg.get("dropped")} '
                f'bad={vg.get("bad")} errors={vg.get("errors")}')
            summary.append({'sku': e['sku'], 'status': res.get('status'), 'wall_s': res['wall_s'],
                            'job_id': res.get('job_id'), 'prefix': res.get('prefix'), 'view_guard': vg})
        rc = 0
    finally:
        keep = a.keep and rc == 0   # при любом сбое — гасим
        ok = True if keep else stop(a.group)
        if keep:
            log(f'!! группа {a.group} ОСТАВЛЕНА включённой (--keep): гасить — тому, кто ведёт следующий прогон')
        mins = (time.time() - t_start) / 60
        json.dump({'summary': summary, 'group_stopped': ok, 'minutes_group_on': round(mins, 1)},
                  open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        log(f'группа была включена {mins:.1f} мин ≈ {mins / 60 * 0.10:.3f} $ (4060 Ti low $0,10/ч)')
    return rc


if __name__ == '__main__':
    sys.exit(main())
