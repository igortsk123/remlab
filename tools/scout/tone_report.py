#!/usr/bin/env python3
"""Отчёт о тоне по шагам покраски (T-99/7, 26.11, просьба директора): L/C/h текстуры после каждого цветового шага — 06 перенос, Ш4а, owner, зерно, gutter, 07 fill, шов, 08.
ТОЛЬКО ОТЧЁТ: порогов нет, ничего не режет и не блокирует, код выхода всегда 0 (сбой измерения — строка в отчёте, не падение этапа). Порог/обрезка — отдельным решением после ответа Fable.

Что меряем. Текстура GLB шага; охват = тексели, которые покрывают грани в UV (растр граней, `thin_plate._raster`) — то есть ВСЯ развёртка модели, не только верх (маски «верха» у шагов
разные, общей нет; «верх» по маскам — отдельная мерка позже). L — светлота Lab 0..100 (среднее), C — хроматичность sqrt(a²+b²) (СРЕДНЕЕ по текселям), h — угол средних a,b в градусах.
Эталон «фото» — те же L/C/h по непрозрачным пикселям вырезки фото (весь предмет на фото: со светом и тенями — ориентир шкалы насыщенности, не тексель-в-тексель); «генератор» —
та же мерка по форме TRELLIS (`--generator`, нужен, чтобы видеть, что прибавил каждый шаг).

Что пишет:
  • `<run>/<sku>/tone_report.json` — шаги, L/C/h, ΔC к прошлому шагу, C к фото и к генератору;
  • `extra.tone` в `check.json` этапов 06-visible, 07-fill, 07-seam, 08-material (через paint_stage.write_check; остальное содержимое check.json не меняется);
  • таблицу в stdout (строка в отчёт прогона).
Запуск: tone_report.py run --run RUN --sku SKU [--photo ФОТО.rgba.png] [--generator ФОРМА.glb]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'salad', 'trellis')]
import paint_stage as PS  # noqa: E402

SCOPE = 'uv_coverage'            # охват = все тексели граней в UV
# (метка, подпапка этапа, файл) — снимки внутри 06 пишут сами шаги: pre-X = состояние ДО шага X
STEPS = [('06 перенос фото', '06-visible', 'visible.pre-partmaterial.glb'),
         ('Ш4а', '06-visible', 'visible.pre-owner.glb'),
         ('owner', '06-visible', 'visible.pre-grain.glb'),
         ('зерно', '06-visible', 'visible.pre-gutter.glb'),
         ('gutter', '06-visible', 'visible.glb'),
         ('07 fill', '07-fill', 'filled.glb'),
         ('шов', '07-seam', 'seam.glb'),
         ('08 материал', '08-material', 'material.glb')]
ATTACH = {'gutter': '06-visible', '07 fill': '07-fill', 'шов': '07-seam', '08 материал': '08-material'}    # check.json, куда кладём extra.tone (итог этапа)


def _lab_stats(rgb: np.ndarray, mask: np.ndarray | None = None) -> dict:
    import cv2
    lab = cv2.cvtColor(np.ascontiguousarray(rgb[..., :3].astype(np.uint8)), cv2.COLOR_RGB2LAB).astype(np.float64)
    sel = np.ones(lab.shape[:2], bool) if mask is None else mask
    if not sel.any():
        return {'L': None, 'C': None, 'h': None, 'n': 0}
    a, b, L = lab[..., 1][sel] - 128, lab[..., 2][sel] - 128, lab[..., 0][sel] * 100 / 255
    return {'L': round(float(L.mean()), 2), 'C': round(float(np.hypot(a, b).mean()), 2), 'h': round(float(np.degrees(np.arctan2(b.mean(), a.mean()))), 1), 'n': int(sel.sum())}


def glb_tone(glb: str) -> dict:
    """L/C/h текстуры GLB по охвату граней в UV."""
    import thin_plate as TPL
    import tex_visible as TV
    g = TV.load_shape(glb)[0]
    F = np.asarray(g['F'])
    uv = np.asarray(g['UV'] if 'UV' in g else g['uv'], np.float64)
    tex = np.asarray(g['tex'])[..., :3].astype(np.uint8)
    cov = TPL._raster(uv, F, np.ones(len(F), bool), tex.shape[0])
    return _lab_stats(tex, cov)


def photo_tone(photo: str) -> dict:
    """L/C/h по непрозрачным пикселям вырезки (alpha > 127; нет альфы — не-белые)."""
    from PIL import Image
    im = np.asarray(Image.open(photo).convert('RGBA'))
    return _lab_stats(im[..., :3], im[..., 3] > 127)


def attach(stage_dir: str, tone: dict) -> bool:
    """Кладёт `extra.tone` в check.json этапа, остальное содержимое — как было. Нет check.json — False."""
    doc = PS.read_check(stage_dir)
    if not doc:
        return False
    extra = dict(doc.get('extra') or {})
    extra['tone'] = tone
    PS.write_check(stage_dir, doc['stage'], doc['sku'], passed=doc['passed'], metric=doc.get('metric'), metrics=doc.get('metrics'), reason=doc.get('reason') or '',
                   seconds=doc.get('seconds'), outputs=doc.get('outputs'), frame=doc.get('frame'), **extra)
    return True


def build(run: str, sku: str, photo: str | None = None, generator: str | None = None) -> dict:
    sd = os.path.join(run, PS.safe_name(sku))
    rep = {'scope': SCOPE, 'sku': sku, 'photo': None, 'generator': None, 'steps': []}
    if photo and os.path.exists(photo):
        try:
            rep['photo'] = photo_tone(photo)
        except Exception as e:  # noqa: BLE001 — отчёт не роняет этап
            rep['photo'] = {'error': f'{type(e).__name__}: {e}'[:160]}
    if generator and os.path.exists(generator):
        try:
            rep['generator'] = glb_tone(generator)
        except Exception as e:  # noqa: BLE001
            rep['generator'] = {'error': f'{type(e).__name__}: {e}'[:160]}
    prev = (rep['generator'] or {}).get('C')
    for name, sub, fn in STEPS:
        p = os.path.join(sd, sub, fn)
        row = {'step': name, 'file': f'{sub}/{fn}'}
        if not os.path.exists(p):
            row['note'] = 'нет файла'
            rep['steps'].append(row)
            continue
        try:
            row.update(glb_tone(p))
        except Exception as e:  # noqa: BLE001
            row['note'] = f'сбой измерения: {type(e).__name__}: {e}'[:160]
            rep['steps'].append(row)
            continue
        if prev is not None and row.get('C') is not None:
            row['dC'] = round(row['C'] - prev, 2)
        if row.get('C') is not None:
            prev = row['C']
            if (rep['photo'] or {}).get('C'):
                row['C_to_photo'] = round(row['C'] / rep['photo']['C'], 2)
            if (rep['generator'] or {}).get('C'):
                row['C_to_generator'] = round(row['C'] / rep['generator']['C'], 2)
        rep['steps'].append(row)
    return rep


def table(rep: dict) -> str:
    out = [f"тон по шагам · {rep['sku']} · охват: {rep['scope']} (вся развёртка; отчёт, порогов нет)", 'шаг                  L      C      h°     ΔC   C/фото  C/ген.']
    for key, name in (('generator', 'генератор'), ('photo', 'фото (вырезка)')):
        t = rep.get(key)
        if t and t.get('C') is not None:
            out.append(f"{name:18s} {t['L']:6.1f} {t['C']:6.1f} {t['h']:6.1f}")
    for r in rep['steps']:
        if r.get('C') is None:
            out.append(f"{r['step']:18s} — {r.get('note', 'нет данных')}")
        else:
            out.append(f"{r['step']:18s} {r['L']:6.1f} {r['C']:6.1f} {r['h']:6.1f} {r.get('dC', 0):+6.1f} {r.get('C_to_photo', 0):7.2f} {r.get('C_to_generator', 0):7.2f}")
    return '\n'.join(out)


def run_report(run: str, sku: str, photo: str | None, generator: str | None) -> dict:
    rep = build(run, sku, photo, generator)
    sd = os.path.join(run, PS.safe_name(sku))
    out_dir = os.path.join(sd, '08-material') if os.path.isdir(os.path.join(sd, '08-material')) else sd       # отчёт лежит у итогового этапа (объявлен в outputs правил), нет папки — рядом с товаром
    with open(os.path.join(out_dir, 'tone_report.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    by = {r['step']: r for r in rep['steps'] if r.get('C') is not None}
    for step, sub in ATTACH.items():
        if step in by:
            r = by[step]
            tone = {'scope': SCOPE, 'step': step, **{k: r[k] for k in ('L', 'C', 'h', 'dC', 'C_to_photo', 'C_to_generator') if k in r}, 'photo': rep['photo'], 'generator': rep['generator'], 'report_only': True}
            attach(os.path.join(sd, sub), tone)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['run'])
    ap.add_argument('--run', required=True)
    ap.add_argument('--sku', required=True)
    ap.add_argument('--photo', default='')
    ap.add_argument('--generator', default='')
    a = ap.parse_args()
    try:
        rep = run_report(a.run, a.sku, a.photo or None, a.generator or None)
        print(table(rep))
    except Exception as e:  # noqa: BLE001 — отчёт-проверка не роняет этап (код выхода всегда 0)
        print(f'tone_report: сбой отчёта: {type(e).__name__}: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
