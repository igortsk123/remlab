"""РАКУРСЫ ТУРА — ПАРАЛЛЕЛЬНО И С ЧАСТИЧНЫМ ИТОГОМ (T-20261111-23, владелец: «тур открывается долго»).

Почему: `tools/flat3d/demo-cams.mjs` одним процессом считал все варианты подряд и писал файл только в конце. Тур aOv8 «Этажи»
(17 вариантов в трёх комнатах) — 140 с при сроке 120: таймаут, и ни у одного варианта пары в данных нет. Страница тогда
перебирает точки в главном потоке при открытии (замер T-21: данные+разметка 7,1 с вместо 0,95 с, первое фото карточки 19 с
вместо 12,5 с на телефоне).

Как: куски (`demo-cams.mjs --units`: общая пара комнаты — один кусок, иначе по варианту) раздаются N процессам node по
очереди (`--only <id> --part <файл>`), каждый кусок пишет свой файл итога. Срок общий: к сроку недосчитанные процессы
снимаются, в данные идут пары готовых кусков, остальные варианты страница посчитает сама (как раньше без пар). Порядок —
порядок вариантов в данных: первая комната тура получает пары первой.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time

UNITS_TIMEOUT_S = 30.0       # `--units` читает данные и печатает куски — секунды


def node_cmd(root: str, path: str, *extra: str) -> list:
    """Команда node со своим PATH (`tools/ops/node-env.sh`); `exec` — снятие по сроку убивает сам node, а не только bash."""
    args = ' '.join(f'"{a}"' for a in extra)
    return ['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && exec node "{root}/tools/flat3d/demo-cams.mjs" "{path}" {args}']


def units_of(root: str, path: str, run=subprocess.run) -> list:
    """Куски подбора: список списков id вариантов. Сбой — исключение (вызывающий решает, что делать)."""
    r = run(node_cmd(root, path, '--units'), capture_output=True, text=True, timeout=UNITS_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f'--units rc={r.returncode}: {(r.stderr or r.stdout or "").strip()[-200:]}')
    got = json.loads((r.stdout or '').strip().splitlines()[-1])
    if not isinstance(got, list) or not all(isinstance(u, list) and u for u in got):
        raise ValueError(f'--units: не список кусков: {str(got)[:120]}')
    return [[str(x) for x in u] for u in got]


def run_units(units: list, jobs: int, deadline: float, cmd_of, tmp: str, poll: float = 0.1,
              popen=subprocess.Popen, clock=time.monotonic) -> tuple[dict, list, list]:
    """Раздать куски `jobs` процессам по очереди до срока `deadline` (по `clock`). `cmd_of(ids, part)` → команда куска.
    → (итоги готовых кусков: {id: {cams, cam_level, cam_cover}}, общая пара была (флаги кусков), строки сбоев кусков)."""
    queue = list(enumerate(units))
    running: list = []                 # (процесс, номер куска, файл итога)
    got: dict = {}
    shared: list = []
    errs: list = []

    def collect(p, i, part):
        if p.returncode != 0:
            tail = ''
            try:
                with open(part + '.log', encoding='utf-8', errors='replace') as f:
                    tail = f.read()
            except OSError:
                pass
            errs.append(f'кусок {",".join(units[i])}: rc={p.returncode} {tail.strip()[-160:]}')
            return
        try:
            with open(part, encoding='utf-8') as f:
                d = json.load(f)
            got.update({k: v for k, v in (d.get('vars') or {}).items() if isinstance(v, dict) and isinstance(v.get('cams'), list)})
            shared.append(bool(d.get('shared')))
        except (OSError, ValueError) as e:
            errs.append(f'кусок {",".join(units[i])}: итог не прочитан: {type(e).__name__}')

    while queue or running:
        while queue and len(running) < max(1, jobs) and clock() < deadline:
            i, ids = queue.pop(0)
            part = os.path.join(tmp, f'part-{i}.json')
            with open(part + '.log', 'wb') as log:   # вывод — в файл: труба без читателя встала бы на 64 КБ
                running.append((popen(cmd_of(ids, part), stdout=log, stderr=subprocess.STDOUT), i, part))
        if not running:
            break                        # срок вышел до запуска оставшихся
        for p, i, part in list(running):
            if p.poll() is not None:
                running.remove((p, i, part))
                collect(p, i, part)
        if running and clock() >= deadline:
            for p, i, part in running:  # снять недосчитанные: их варианты посчитает страница
                p.kill()
                p.wait()
            running = []
            break
        if running:
            time.sleep(poll)
    return got, shared, errs


def apply(path: str, got: dict, shared: list) -> tuple[int, int, list]:
    """Дописать пары в файл данных подменой. → (с парой, всего вариантов, id без пары)."""
    with open(path, encoding='utf-8') as f:
        D = json.load(f)
    vs = D.get('variants') or []
    for v in vs:
        r = got.get(str(v.get('id')))
        if r:
            v.update({k: r[k] for k in ('cams', 'cam_level', 'cam_cover') if k in r})
    D['cams_shared'] = any(shared)
    tmp = f'{path}.cams-par-{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(D, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)
    miss = [str(v.get('id')) for v in vs if str(v.get('id')) not in got]
    return len(vs) - len(miss), len(vs), miss


def cams(root: str, path: str, jobs: int, budget_s: float, units: list | None = None, cmd_of=None,
         clock=time.monotonic) -> str:
    """Пары ракурсов в файл данных, параллельно и к сроку → строка лога сборки. Не валит сборку: сбой списка кусков или ни
    одного готового куска — строка WARN, файл не тронут. Готово меньше вариантов — WARN:trial_cams с числом и списком."""
    t0 = clock()
    try:
        units = units if units is not None else units_of(root, path)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        return f'WARN:trial_cams: куски ракурсов не получены — ракурсы считает страница: {type(e).__name__}: {str(e)[:160]}'
    cmd_of = cmd_of or (lambda ids, part: node_cmd(root, path, '--only', ','.join(ids), '--part', part))
    jobs = max(1, min(jobs, len(units) or 1))
    with tempfile.TemporaryDirectory(prefix='cams-par-', dir=os.path.dirname(os.path.abspath(path))) as tmp:
        got, shared, errs = run_units(units, jobs, t0 + budget_s, cmd_of, tmp, clock=clock)
    took = clock() - t0
    total = sum(len(u) for u in units)
    if not got:
        return (f'WARN:trial_cams: ракурсы 0 из {total} вариантов (срок {budget_s:.0f} с, процессов {jobs}) — ракурсы считает '
                f'страница' + (f'; {errs[0]}' if errs else ''))
    n, nv, miss = apply(path, got, shared)
    head = f'ракурсы окна в данных: вариантов {n} из {nv} (за {took:.0f} с, процессов {jobs}, срок {budget_s:.0f} с)'
    if miss:
        return (f'WARN:trial_cams: {head} — без пары (посчитает страница): {", ".join(miss[:20])}'
                + (f'; сбои: {"; ".join(errs[:3])}' if errs else ''))
    return head
