#!/usr/bin/env python3
"""Шаг «поле вокруг островов» (дилатация, вариант А, шаг 7; T-20261126-97/1 фаза 3). Правила — rules/tex-owner.json, секция dilate; расчёт — tex_owner.dilate_gutter. ВЫКЛЮЧЕНО по умолчанию (dilate.uv_gutter_px=0): ничего не пишет, код 0.

ЗАЧЕМ. Тексели вокруг острова UV, которых не касается ни одна грань, остаются цветом заполнителя 06/зерна; при линейной выборке видеокарта подмешивает их на границе острова — получается крап. Здесь непокрытые тексели не дальше
uv_gutter_px от покрытых берут цвет ближайшего покрытого (покрытые не меняются). Порядок: 06 → Ш4а → tex_owner_stage → зерно (part_grain_stage) → ЭТОТ ШАГ → 07 (дилатация — после зерна, чтобы поле копировало и узор).

Читает `<run>/<sku>/06-visible/visible.glb`; исходник сохраняет как `visible.pre-gutter.glb` (повторный запуск идёт от него); пишет visible.glb (та же геометрия, новая текстура) и след `tex_gutter.json` (числа + сторож
«непокрытые в полосе с |ΔL| > порога = 0»). Нет текстуры/UV или причина воздержаться — след с причиной, код 0.

  python tools/scout/tex_gutter_stage.py --run RUN --sku SKU [--rules ФАЙЛ.json] [--out-dir 06-visible] [--force-px N]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]

import tex_owner_stage as OS  # noqa: E402

OUT = 'tex_gutter.json'
PRE = 'visible.pre-gutter.glb'
VERSION = 1


class Abstain(Exception):
    """Воздержание: причина идёт в след, остальные шаги идут как раньше."""


def process(rules: dict, px: int, d: str, rep: dict) -> None:
    import tex_owner as TO
    t0 = time.time()
    pre = os.path.join(d, PRE)
    vis = os.path.join(d, 'visible.glb')
    src = pre if os.path.exists(pre) else vis
    if not os.path.exists(src):
        raise Abstain('нет visible.glb этапа 6')
    js, binb = TO.read_glb(src)
    tex = TO.tex_of(js, binb, 0)
    if tex.shape[0] != tex.shape[1]:
        raise Abstain('текстура %s не квадратная (шаг считает квадрат)' % (tex.shape[:2],))
    P, UV, F = TO.read_geom(src)
    ids = TO.owner_ids(UV, F, tex.shape[0], rules)
    dl_max = float(rules['dilate']['guard_dl_max'])
    rep['до'] = TO.guard_gutter(tex, ids, px, dl_max)
    new, n = TO.dilate_gutter(tex, ids, px)
    rep['перекрашено_текселей'] = n
    rep['непокрытых_всего'] = int((ids < 0).sum())
    rep['после'] = TO.guard_gutter(new, ids, px, dl_max)                  # сторож по итоговой текстуре
    if not os.path.exists(pre):
        shutil.copy2(vis, pre)                                              # исходник один раз; повторный запуск идёт от него
    TO.write_glb_with_tex(src, new, vis)
    rep['seconds'] = round(time.time() - t0, 1)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', required=True)
    ap.add_argument('--sku', required=True)
    ap.add_argument('--rules', default='')
    ap.add_argument('--out-dir', default='', help='папка 06-visible для пробы вместо <run>/<sku>/06-visible')
    ap.add_argument('--force-px', type=int, default=0, help='взять ширину поля N вместо rules.dilate.uv_gutter_px (замер/проба)')
    a = ap.parse_args(argv)
    rules = OS.load_rules(a.rules or OS.RULES_PATH)
    px = a.force_px or int(rules['dilate']['uv_gutter_px'])
    if px <= 0:
        print('tex_gutter: выключено (dilate.uv_gutter_px=0) — ничего не меняю')
        return 0
    d = a.out_dir or os.path.join(a.run, a.sku, OS.STAGE_DIR)
    os.makedirs(d, exist_ok=True)
    rep = {'version': VERSION, 'rule': 'R-TEX-GUTTER', 'sku': a.sku, 'uv_gutter_px': px, 'abstain': None}
    try:
        process(rules, px, d, rep)
    except Abstain as e:
        rep['abstain'] = str(e)
    except Exception as e:  # noqa: BLE001 — шаг не роняет конвейер: остальные шаги идут как раньше, причина в след
        rep['abstain'] = 'сбой: %s: %s' % (type(e).__name__, e)
        traceback.print_exc()
    with open(os.path.join(d, OUT), 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=float)
    print('tex_gutter:', 'поле %d px, перекрашено %d текселей' % (px, rep.get('перекрашено_текселей', 0)) if not rep['abstain'] else 'воздержался — ' + rep['abstain'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
