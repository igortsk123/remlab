#!/usr/bin/env python3
"""Потолок денег у РУЧНОГО старта волны (план mesh-18 этап 4, T-20261027-02).

ЗАЧЕМ. Потолок волны держал только автозапуск: `wave_guard` пишет волну с `usd_cap` в разрешение владельца
(`wave-lease.json`), и `money_guard.budget_breach` гасит пул по ней. Ручной `mesh_wave_start.sh --launch` такой записи
не делал — проба 27.10 (T-20261027-01) шла без потолка, его держал рабочий глазами, а суд цены сторожа ждёт 8 ч.
Писать ручную волну в `wave-lease.json` нельзя: это разрешение владельца на АВТОволны, его срок и сумму продлевает
только человек. Поэтому ручная волна — в СВОЁМ файле той же формы (`{"waves": [...]}`): сторож денег судит её тем же
`budget_breach`, а `wave_guard` этот файл не читает и по истёкшему разрешению по-прежнему не стартует.

Жизнь записи: `mesh_wave_start.sh --launch --rub-cap N` открывает волну ДО запуска конвейера (сторож видит потолок с
первой минуты) → потолок выбран — сторож гасит пул и пишет стоп-файл `kind: budget, source: manual` → конвейер выходит
(`batch_show.run_batch`) → `finale()` закрывает запись (факт денег) и снимает СВОЙ стоп-файл потолка.

    ~/venvs/scout/bin/python salad/wave_cap.py --open 174 [снимок]   # открыть ручную волну с потолком 174 ₽
    ~/venvs/scout/bin/python salad/wave_cap.py --close 'причина'     # закрыть последнюю открытую
    ~/venvs/scout/bin/python salad/wave_cap.py --show
"""
from __future__ import annotations

import json
import os
import sys
import time

PATH = os.environ.get('MESH_WAVE_MANUAL') or os.path.expanduser('~/scout-scenes/wave-manual.json')
KEEP = 20          # история ручных волн — последние N записей


def read() -> dict | None:
    """Файл ручных волн; нет или битый — None (битый не отменяет остальные правила сторожа)."""
    try:
        d = json.load(open(PATH, encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _write(d: dict) -> None:
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def open_wave(rub_cap: float, usd_rub: float, usd_mark: float, snapshot: str = '', now: float | None = None) -> dict:
    """Новая ручная волна: потолок в ₽ → `usd_cap` по курсу правил (книга сторожа считает в $), отметка книги на
    старте `usd_mark`. Прежняя открытая (конвейер упал без `finale`) закрывается как брошенная."""
    if rub_cap <= 0 or usd_rub <= 0:
        raise ValueError(f'потолок {rub_cap} ₽ при курсе {usd_rub} — нечем ограничить волну')
    now = now or time.time()
    d = read() or {}
    waves = d.get('waves') or []
    if waves and not waves[-1].get('closed'):
        waves[-1].update({'closed': now, 'why': 'брошена: открыта новая ручная волна'})
    w = {'at': time.strftime('%Y-%m-%d', time.gmtime(now)), 'started': now, 'rub_cap': round(rub_cap, 2),
         'usd_cap': round(rub_cap / usd_rub, 4), 'usd_mark': round(usd_mark, 4), 'snapshot': snapshot}
    d['waves'] = (waves + [w])[-KEEP:]
    _write(d)
    return w


def close(why: str, paid_usd: float, usd_rub: float, now: float | None = None) -> dict | None:
    """Закрыть последнюю открытую ручную волну: факт денег по книге сторожа. Открытой нет — None."""
    d = read() or {}
    waves = d.get('waves') or []
    if not waves or waves[-1].get('closed'):
        return None
    w = waves[-1]
    spent = max(paid_usd - float(w.get('usd_mark', 0)), 0.0)
    w.update({'closed': now or time.time(), 'why': why, 'spent_usd': round(spent, 4),
              'spent_rub': round(spent * usd_rub, 1)})
    _write(d)
    return w


def clear_budget_halt(halt_path: str) -> bool:
    """Снять стоп-файл, если его поставил потолок РУЧНОЙ волны (своё отработал, как у `wave_guard.close_wave`).
    Чужой (тишина, приёмник, потолок разрешения владельца) не трогаем."""
    try:
        h = json.load(open(halt_path, encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if h.get('kind') == 'budget' and h.get('source') == 'manual':
        os.remove(halt_path)
        return True
    return False


def main() -> int:
    a = sys.argv[1:]
    if '--show' in a:
        print(json.dumps(read(), ensure_ascii=False, indent=1))
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import money_guard as MG  # noqa: PLC0415 — книга расходов сторожа (один источник)
    import salad_groups as SG  # noqa: PLC0415 — курс из правил
    if '--open' in a:
        rub = float(a[a.index('--open') + 1])
        snap = a[a.index('--open') + 2] if len(a) > a.index('--open') + 2 else ''
        w = open_wave(rub, SG.usd_rub(), MG.paid_usd(MG.load()), snap)
        print(f'ручная волна: потолок {w["rub_cap"]} ₽ (${w["usd_cap"]}), отметка книги ${w["usd_mark"]} → {PATH}')
        return 0
    if '--close' in a:
        w = close(a[a.index('--close') + 1], MG.paid_usd(MG.load()), SG.usd_rub())
        print('ручная волна закрыта: ' + json.dumps(w, ensure_ascii=False) if w else 'открытой ручной волны нет')
        return 0
    print(__doc__)
    return 64


if __name__ == '__main__':
    sys.exit(main())
