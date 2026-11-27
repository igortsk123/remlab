#!/usr/bin/env python3
"""КОНТРОЛЬ ДНЯ ЭКЗАМЕНА (условие Fable 27.11 19:32): N случайных листов из набора распознать ЛОКАЛЬНО (замороженный words_on_sheet в venv ocr-trial) и сравнить с кэшем, заполненным на Salad.
Равны должны быть words, found, n_lines (conf — в таблице, допуск ±0,01 только для показа). Расхождение хоть на одном листе, лист без записи в кэше (или с записью под другой версией правил) — КОД 1 и
«КЭШ ВЫБРОСИТЬ, считать локально»: локальный OCR остаётся запасным. С `--discard` кэш при этом ПЕРЕИМЕНУЕТСЯ в `<кэш>.DISCARDED-<время>` (не удаляется; читатель увидит пустое место и посчитает сам).
Сломанная проверка (нет листов/venv, мало листов, OCR упал) — код 2 с причиной, НЕ «0 расхождений». Всё сошлось — код 0.
Случайность воспроизводима: выбор печатается вместе с `--seed` (по умолчанию — от времени, значение в выводе).

Запуск (после заполнения кэша на Salad, ПОСЛЕ вскрытия свежих листов):
  python control_words.py --cache <папка прогона>/words_flags.json --ids <100 id> --sheets-dirs <папка листов> [--n 5] [--seed 7] [--discard]
Локальный OCR: `--local-python` (по умолчанию ~/venvs/ocr-trial/bin/python) запускает `frozen/words_on_sheet.py` с WORDS_FLAGS_CACHE во временный файл — боевой кэш не пишется.
Выход: таблица в stdout (для шапки таблицы экзамена: `слова: кэш заполнен на Salad, образ <digest>, rapidocr 3.10.0 / onnxruntime 1.31.1, контроль N/N`)."""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ocr_words_run as RUN  # noqa: E402  (find_sheet, sheet_sha, rules_ver — те же, что у драйвера)

EXACT = ('words', 'found', 'n_lines')
CONF_TOL = 0.01
WORDS_PY = os.path.join(HERE, 'frozen', 'words_on_sheet.py')
LOCAL_PY = os.path.expanduser('~/venvs/ocr-trial/bin/python')


class ControlError(Exception):
    """Проверка не смогла отработать (код 2): нет данных/окружения. Это НЕ «кэш хороший»."""


def pick(ids: list[str], n: int, seed: int) -> list[str]:
    """n разных id случайно (воспроизводимо по seed); id меньше n — ошибка проверки."""
    uniq = sorted(set(ids))
    if len(uniq) < n:
        raise ControlError(f'для контроля нужно {n} листов, в списке {len(uniq)}')
    return sorted(random.Random(seed).sample(uniq, n))


def local_ocr(path: str, python: str = LOCAL_PY, script: str = WORDS_PY, timeout: int = 600) -> dict:
    """Локальный OCR листа замороженным words_on_sheet (подпроцесс, `-I`); кэш — во временный файл. → {'words','found','conf','n_lines'}."""
    if not os.path.exists(python):
        raise ControlError(f'нет локального venv для OCR: {python}')
    with tempfile.TemporaryDirectory() as t:
        env = {**os.environ, 'WORDS_FLAGS_CACHE': os.path.join(t, 'tmp_flags.json')}
        r = subprocess.run([python, '-I', script, path], capture_output=True, text=True, timeout=timeout, env=env)
    lines = r.stdout.strip().splitlines()
    if r.returncode != 0 or not lines:
        raise ControlError(f'локальный OCR упал на {path}: rc={r.returncode} {(r.stderr or r.stdout)[-300:]}')
    d = json.loads(lines[-1])
    if d.get('cache') is not False:      # контроль без настоящего OCR (ответ из кэша) — не контроль
        raise ControlError(f'локальный прогон не распознавал лист {path} (cache={d.get("cache")!r}) — контроль недействителен')
    return {k: d[k] for k in ('words', 'found', 'conf', 'n_lines')}


def check(cache: dict, ids: list[str], dirs: list[str], rules: str, ocr_fn=local_ocr) -> list[dict]:
    """По каждому id: файл листа → запись кэша (ключ sha файла, те же правила) → локальный OCR → сравнение. → строки {id, ok, why, cache, local}."""
    rows = []
    for sid in ids:
        p = RUN.find_sheet(sid, dirs)
        if p is None:
            raise ControlError(f'нет файла листа {sid} в {dirs}')
        e = cache.get(RUN.sheet_sha(p))
        loc = ocr_fn(p)
        if e is None or e.get('rules') != rules:
            rows.append({'id': sid, 'ok': False, 'why': 'нет в кэше' if e is None else f'правила кэша {e.get("rules")} ≠ {rules}', 'cache': e, 'local': loc})
            continue
        bad = [k for k in EXACT if e.get(k) != loc.get(k)]
        rows.append({'id': sid, 'ok': not bad, 'why': ','.join(bad), 'cache': e, 'local': loc,
                     'conf_diff': round(abs(float(e.get('conf', 0)) - float(loc.get('conf', 0))), 3)})
    return rows


def table(rows: list[dict], seed: int) -> str:
    out = [f'контроль {len(rows)} случайных листов (seed {seed}): локальный OCR vs кэш', '| лист | words | found | n_lines | conf | итог |', '|---|---|---|---|---|---|']
    for r in rows:
        e, loc = r.get('cache') or {}, r['local']
        out.append(f"| {r['id']} | {e.get('words')}→{loc['words']} | {e.get('found')}→{loc['found']} | {e.get('n_lines')}→{loc['n_lines']} | "
                   f"{e.get('conf')}→{loc['conf']} | {'✅' if r['ok'] else '❌ ' + r['why']} |")
    n_ok = sum(1 for r in rows if r['ok'])
    out.append(f'\nсовпало {n_ok} из {len(rows)}')
    return '\n'.join(out)


def discard(cache_path: str, now=time.time) -> str:
    """Кэш — в сторону (rename, не удаление): `<кэш>.DISCARDED-<ГГГГММДД-ЧЧММСС>`. → новый путь."""
    new = f'{cache_path}.DISCARDED-{time.strftime("%Y%m%d-%H%M%S", time.gmtime(now()))}'
    os.rename(cache_path, new)
    return new


def run(a, ocr_fn=local_ocr) -> int:
    try:
        with open(a.cache, encoding='utf-8') as f:
            cache = json.load(f)
        with open(a.ids, encoding='utf-8') as f:
            ids = [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
        seed = a.seed if a.seed is not None else int(time.time())
        chosen = pick(ids, a.n, seed)
        rows = check(cache, chosen, [d for d in a.sheets_dirs.split(',') if d], RUN.rules_ver(), ocr_fn)
    except (ControlError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'КОНТРОЛЬ НЕ ВЫПОЛНЕН (код 2): {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(table(rows, seed))
    if all(r['ok'] for r in rows):
        print(f'КОНТРОЛЬ ПРОЙДЕН: {len(rows)} из {len(rows)} — кэш Salad можно использовать')
        return 0
    bad = [r['id'] for r in rows if not r['ok']]
    print(f'КЭШ ВЫБРОСИТЬ, считать локально: расхождение на {bad}', file=sys.stderr)
    if a.discard:
        print(f'кэш отложен: {discard(a.cache)}', file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cache', required=True, help='words_flags.json, заполненный на Salad')
    ap.add_argument('--ids', required=True, help='файл со списком id листов дня (100 свежих)')
    ap.add_argument('--sheets-dirs', required=True, help='папки листов <папка>/<id>/plan.* через запятую')
    ap.add_argument('--n', type=int, default=5)
    ap.add_argument('--seed', type=int, default=None, help='зерно выбора (по умолчанию от времени; печатается)')
    ap.add_argument('--discard', action='store_true', help='при расхождении кэш переименовать в .DISCARDED-<время>')
    ap.add_argument('--local-python', default=LOCAL_PY)
    a = ap.parse_args()
    return run(a, ocr_fn=lambda p: local_ocr(p, python=a.local_python))


if __name__ == '__main__':
    sys.exit(main())
