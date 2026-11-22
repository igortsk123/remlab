#!/usr/bin/env python3
"""СВЕРКА «у нас локально / на Salad» для этапов 06/07 (T-189/1): те же товары, тот же код → выход должен совпасть. Только чтение, бесплатно.
  python compare_stage.py --local <папка> --salad <папка> --skus a,b,c [--tol 0.005] [--md таблица.md]
Папка = `<папка>/<товар>/06-visible/…` и `07-fill/…`. Сравнивается:
  06: known.png и frame.png — средняя |разница| пикселей (доли 0…1 по всем каналам; разный размер — отказ), check.json — `passed` и главная мера (IoU) ±tol;
  07: текстура filled.glb и frame.png — то же; report.json — числовые счётчики верхнего уровня (должны совпасть; расхождения списком).
Выход: таблица (markdown), код 0 — всё в допуске, 1 — есть расхождения, 2 — нет файлов для сверки."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import numpy as np
from PIL import Image

PNG06 = ('known.png', 'frame.png')
PNG07 = ('frame.png',)


def png_diff(a: str, b: str) -> tuple[float | None, str]:
    """Средняя |разница| двух картинок (0…1, RGBA→RGB поверх белого). (None, причина) — нет файла или другой размер."""
    if not os.path.isfile(a) or not os.path.isfile(b):
        return None, 'нет файла'
    x, y = Image.open(a), Image.open(b)
    return arr_diff(x, y)


def flat(img: Image.Image) -> np.ndarray:
    img = img.convert('RGBA')
    bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
    return np.asarray(Image.alpha_composite(bg, img).convert('RGB'), dtype=np.float32) / 255.0


def arr_diff(x: Image.Image, y: Image.Image) -> tuple[float | None, str]:
    if x.size != y.size:
        return None, f'размер {x.size} ≠ {y.size}'
    return float(np.abs(flat(x) - flat(y)).mean()), ''


def glb_texture(path: str) -> Image.Image | None:
    """Базовая текстура GLB (первая найденная у материалов сцены)."""
    import trimesh
    s = trimesh.load(path, force='scene')
    for g in s.geometry.values():
        m = getattr(getattr(g, 'visual', None), 'material', None)
        t = getattr(m, 'baseColorTexture', None) or getattr(m, 'image', None)
        if t is not None:
            return t
    return None


def glb_diff(a: str, b: str) -> tuple[float | None, str]:
    if not os.path.isfile(a) or not os.path.isfile(b):
        return None, 'нет файла'
    ta, tb = glb_texture(a), glb_texture(b)
    if ta is None or tb is None:
        return None, 'в GLB нет текстуры'
    return arr_diff(ta, tb)


def scalars(d: dict, prefix: str = '') -> dict[str, float]:
    out = {}
    for k, v in d.items():
        if isinstance(v, bool):
            out[prefix + k] = float(v)
        elif isinstance(v, (int, float)):
            out[prefix + k] = float(v)
        elif isinstance(v, dict):
            out.update(scalars(v, f'{prefix}{k}.'))
    return out


def json_diffs(a: str, b: str, skip=('seconds', 'time', 'elapsed', 'wall', 'sec')) -> list[str]:
    """Расхождения числовых полей двух json (поля со временем счёта не сравниваем)."""
    if not os.path.isfile(a) or not os.path.isfile(b):
        return ['нет файла']
    x, y = scalars(json.load(open(a, encoding='utf-8'))), scalars(json.load(open(b, encoding='utf-8')))
    out = []
    for k in sorted(set(x) | set(y)):
        if any(s in k.lower() for s in skip):
            continue
        if k not in x or k not in y:
            out.append(f'{k}: есть только {"у нас" if k in x else "на Salad"}')
        elif abs(x[k] - y[k]) > 1e-6 + 1e-6 * abs(x[k]):
            out.append(f'{k}: {x[k]:g} ≠ {y[k]:g}')
    return out


def main_metric(p: str):
    try:
        m = json.load(open(p, encoding='utf-8')).get('metric') or {}
        return m.get('value')
    except (OSError, ValueError):
        return None


def compare(local: str, salad: str, skus: list[str], tol: float) -> tuple[list[dict], bool]:
    rows, allok = [], True
    for sku in skus:
        for stage, dn, pngs in (('06', '06-visible', PNG06), ('07', '07-fill', PNG07)):
            L, S = os.path.join(local, sku, dn), os.path.join(salad, sku, dn)
            for f in pngs:
                v, why = png_diff(os.path.join(L, f), os.path.join(S, f))
                rows.append({'sku': sku, 'stage': stage, 'what': f, 'value': v, 'why': why, 'ok': v is not None and v <= tol})
            glb = 'filled.glb' if stage == '07' else None
            if glb:
                v, why = glb_diff(os.path.join(L, glb), os.path.join(S, glb))
                rows.append({'sku': sku, 'stage': stage, 'what': 'текстура ' + glb, 'value': v, 'why': why, 'ok': v is not None and v <= tol})
            cl, cs = os.path.join(L, 'check.json'), os.path.join(S, 'check.json')
            try:
                pl, ps = json.load(open(cl, encoding='utf-8')).get('passed'), json.load(open(cs, encoding='utf-8')).get('passed')
            except (OSError, ValueError):
                pl = ps = 'нет файла'
            ml, ms = main_metric(cl), main_metric(cs)
            md = abs(ml - ms) if isinstance(ml, (int, float)) and isinstance(ms, (int, float)) else None
            rows.append({'sku': sku, 'stage': stage, 'what': 'check.passed / главная мера', 'value': md, 'why': f'passed {pl} / {ps}; мера {ml} / {ms}',
                         'ok': pl == ps and pl != 'нет файла' and (md is None or md <= tol)})
            if stage == '07':
                diffs = json_diffs(os.path.join(L, 'report.json'), os.path.join(S, 'report.json'))
                rows.append({'sku': sku, 'stage': stage, 'what': 'report.json счётчики', 'value': float(len(diffs)), 'why': '; '.join(diffs[:6]), 'ok': not diffs})
    for r in rows:
        allok &= r['ok']
    return rows, allok


def table(rows: list[dict], tol: float) -> str:
    out = [f'| товар | этап | что | разница (допуск {tol}) | в допуске | пояснение |', '|---|---|---|---|---|---|']
    for r in rows:
        v = '—' if r['value'] is None else f"{r['value']:.5f}"
        out.append(f"| {r['sku']} | {r['stage']} | {r['what']} | {v} | {'да' if r['ok'] else '**НЕТ**'} | {r['why']} |")
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--local', required=True)
    ap.add_argument('--salad', required=True)
    ap.add_argument('--skus', required=True)
    ap.add_argument('--tol', type=float, default=0.005)
    ap.add_argument('--md', default='')
    a = ap.parse_args()
    skus = [s for s in a.skus.split(',') if s]
    rows, allok = compare(a.local, a.salad, skus, a.tol)
    if not any(r['value'] is not None or r['ok'] for r in rows):
        print('нет файлов для сверки', file=sys.stderr)
        return 2
    t = table(rows, a.tol)
    print(t)
    if a.md:
        open(a.md, 'w', encoding='utf-8').write(t + '\n')
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
