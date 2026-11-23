#!/usr/bin/env python3
"""check.json этапов 01-trellis и 02-prep для «лесенки форм» TRELLIS.2 (T-20261123-45; те же правила, что у этих этапов в обычном пути, — sg_color_transfer.stage01 / stage02_form).

ЗАЧЕМ. Лесенка (`trellis_trial.py --ladder`) отдаёт готовую форму `<товар>-<ступень>.glb` и больше ничего: ни `01-trellis/`, ни `02-prep/`. Этап 9 по правилу «этап без своего check.json = не пройден»
(T-20261123-44) показывал у таких товаров «нет данных» — не потому, что форма плохая, а потому что проверки никто не записал. Здесь они пишутся рядом с формой, тем же кодом, что в обычном пути:
  01-trellis — baseColor в GLB есть (главная, порог 1), доля альфа<128 (справочная);
  02-prep    — доля граней с текселем ≥ порога этапа, граней ≤ порога; мерки «против родной» не считаются (родной в лесенке нет; в check.json `compared_to_native=false`).
Этап 05-delight лесенка НЕ выполняет (убрать свет — отдельный шаг над фото, не над формой): его check.json лесенка не пишет и не выдумывает — в 09 это «нет данных», пока 05 не запущен на этих фото.

Папка прогона: `<out>/ladder-run/<ступень>/<товар>/NN-этап/check.json` (по ступени — чтобы несколько ступеней одного товара не затирали друг друга).
  python ladder_checks.py recompute --glbs <папка с <товар>-<ступень>.glb> --step hd --run <куда> [--sku …]   # пересчёт по готовым файлам, без GPU и без платного
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'stablegen'))
RUN_DIR = 'ladder-run'
NOT_RUN = '05-delight'


def run_dir(out: str, step: str) -> str:
    return os.path.join(out, RUN_DIR, step)


def _failed(run: str, sku: str, stage: str, e: Exception) -> dict:
    import paint_stage as ps
    return ps.write_check(ps.stage_dir(run, sku, stage), stage, sku, False, reason=f'проверка этапа упала: {type(e).__name__}: {str(e)[:120]}', compared_to_native=False)


def write_checks(run: str, sku: str, glb: str) -> dict:
    """Записать check.json этапов 01 и 02 формы `glb` в `<run>/<sku>/`. Любая ошибка этапа — его check.json с passed=false и причиной (молча не пропускаем). → {'01': {...}, '02': {...}}."""
    import sg_color_transfer as T
    out = {}
    for st, fn in (('01-trellis', lambda: T.stage01(run, sku, glb)), ('02-prep', lambda: T.stage02_form(run, sku, glb))):
        t0 = time.time()
        try:
            c = fn()
        except Exception as e:  # noqa: BLE001
            c = _failed(run, sku, st, e)
        out[st[:2]] = {'passed': c['passed'], 'reason': c['reason'], 'seconds': round(time.time() - t0, 1)}
    return out


def write_for_job(out: str, sku: str, step: str, glb: str) -> dict:
    """Вызов из `trellis_trial.py` после скачивания GLB ступени."""
    run = run_dir(out, step)
    return {'run': run, **write_checks(run, sku.replace(':', '_'), glb), 'not_run': f'{NOT_RUN}: лесенка его не выполняет, check.json нет'}


def recompute(glbs: str, step: str, run: str, skus: list | None = None) -> list:
    """Пересчёт по готовым `<glbs>/<товар>-<ступень>.glb` (без `.raw.`/`.clean`-вариантов); → [(sku, {'01':…, '02':…})]."""
    rows = []
    for p in sorted(glob.glob(os.path.join(glbs, f'*-{step}.glb'))):
        sku = os.path.basename(p)[:-len(f'-{step}.glb')]
        if skus and sku not in skus:
            continue
        rows.append((sku, write_checks(run_dir_for(run, step), sku, p)))
    return rows


def run_dir_for(run: str, step: str) -> str:
    return os.path.join(run, step)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('recompute')
    r.add_argument('--glbs', required=True)
    r.add_argument('--step', default='hd')
    r.add_argument('--run', required=True)
    r.add_argument('--sku', action='append', default=[])
    a = ap.parse_args()
    rows = recompute(os.path.expanduser(a.glbs), a.step, os.path.expanduser(a.run), a.sku or None)
    bad = 0
    for sku, c in rows:
        flag = '' if c['01']['passed'] and c['02']['passed'] else '  ← ЕСТЬ НЕПРОШЕДШИЕ'
        bad += bool(flag)
        print(f"{sku}  01 {'ок' if c['01']['passed'] else 'НЕТ: ' + c['01']['reason']}  02 {'ок' if c['02']['passed'] else 'НЕТ: ' + c['02']['reason']}{flag}")
    print(f'итого: товаров {len(rows)}, с непрошедшим этапом {bad}')
    return 0 if rows else 1


if __name__ == '__main__':
    sys.exit(main())
