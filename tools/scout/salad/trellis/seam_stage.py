#!/usr/bin/env python3
"""ШАГ «СВЕДЕНИЕ ШВА ФОТО | ЗАЛИВКА» после этапа 07 (T-196/1, П1.136; владелец TG 1652/1687/1723/1768): граница = известное фото ↔ всё залитое (зеркало, донор, заливка — без различия).
Вход: готовый 07 (`<папка 07>/filled.glb` — известные тексели там 1:1 фото) и 06 (`<папка 06>/known*.png`, по возможности `conf*.png` доверия, `visible.glb` не нужен).
Что делает (код — `tex_seam.py`, общий проход — `tex_fill.seam_pass`): ① доверие к фото-текселю → вес ② граница по мм, не по текселям (feather: размытая маска, фото вытягивается в заливку на ≤ 2·feather_mm)
③ тон заливки у границы по материальной зоне (поле не пересекает излом панели > crease_deg) ④ контраст фактуры ⑤ мерка: пары через шов (ΔE00 медиана/p95, отношение контраста) и шероховатость границы («ступеньки», мм) до/после.
Середина фото (вес 1) не меняется ни на единицу — проверяется `known_changed` в отчёте.
Запуск (на pakardev, python -I из venv scout, под heavy-slot — расчёт на процессоре):
  python seam_stage.py <run> <sku> --fill <папка 07-fill> --visible <папка 06-visible> [--cfg '{"seam":{...}}']
Выход: `<run>/<sku>/07-seam/{seam.glb, report.json, frame.png, check.json}`; код выхода 0 — отработал (passed см. check.json), 2 — сбой запуска (в check.json). Правила — `rules/paint-fill.json` → `seam`."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402
import paint_stage as PS  # noqa: E402

STAGE = '07-seam'


def run_seam(run: str, sku: str, fill_dir: str, visible: str, cfg: dict | None = None) -> dict:
    from PIL import Image
    t0 = time.time()
    d = PS.stage_dir(run, sku, STAGE)
    glb = os.path.join(fill_dir, 'filled.glb')
    geoms = TC.load_geoms(glb)
    known = TF.load_known_png(visible)
    if not known:
        raise ValueError(f'нет known.png в {visible}')
    conf = TF.load_conf_png(visible)
    seam_c = dict(TF.RULES.get('seam') or {}, **((cfg or {}).get('seam') or {}))
    seam_c['enabled'] = True
    gutter = int((cfg or {}).get('gutter', TF.FILL['gutter']))
    parts, parts_note = TF.parts_from_geometry(geoms)
    ctr, size = TF.frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    Pall = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    txs, labs, kn_keep, tex_in = [], [], [], []
    for gi, g in enumerate(geoms):
        T = TF._grid(g)
        tx = TF.Tex(g, Pall[offs[gi]:offs[gi + 1]], T, None if parts is None else parts[gi], True)
        rgb = np.asarray(g['tex'])[..., :3]
        k0 = np.asarray(known[gi], bool) & ~TF.unpainted_mask(rgb)
        txs.append(tx)
        tex_in.append(rgb)
        kn_keep.append(k0)
        labs.append(TF.rgb2lab(rgb.reshape(-1, 3)).reshape(T, T, 3))
    out_lab = [x.copy() for x in labs]
    keep0 = [k.copy() for k in kn_keep]
    srep = TF.seam_pass(txs, out_lab, labs, kn_keep, conf, seam_c, gutter)
    outs, changed = [], 0
    for gi, tx in enumerate(txs):
        T = tx.T
        rgb = tex_in[gi].copy()
        ol, lb = out_lab[gi].reshape(-1, 3)[tx.ti], labs[gi].reshape(-1, 3)[tx.ti]
        ch = np.abs(ol - lb).max(axis=1) > 1e-6                         # только тексели, которые шов реально поменял (остальные — байт в байт как на входе, без круга Lab↔RGB)
        new = TF.lab2rgb(ol)
        new = np.where((new.max(axis=1) <= TF.BLACK_MAX)[:, None], np.maximum(new, TF.BLACK_MAX + 1), new)
        rgb.reshape(-1, 3)[tx.ti[ch]] = new[ch]
        changed += int(ch.sum())
        if gutter > 0:
            from scipy.ndimage import distance_transform_edt
            occ = np.zeros((T, T), bool)
            occ.reshape(-1)[tx.ti] = True
            dist, (iy, ix) = distance_transform_edt(~occ, return_indices=True)
            g_ = (~occ) & (dist <= gutter)
            rgb[g_] = rgb[iy[g_], ix[g_]]
        outs.append(rgb)
    # середина фото 1:1: известное, оставшееся в keep, не должно отличаться от входа
    mid_bad = 0
    mid_all = 0
    for gi, tx in enumerate(txs):
        m = kn_keep[gi].reshape(-1)[tx.ti]
        mid_all += int(m.sum())
        mid_bad += int((outs[gi].reshape(-1, 3)[tx.ti[m]] != tex_in[gi].reshape(-1, 3)[tx.ti[m]]).sum())
    TF.write_glb(geoms, outs, os.path.join(d, 'seam.glb'))
    a = TF.render_ortho(geoms, tex_in, 180.0)
    b = TF.render_ortho(geoms, outs, 180.0)
    Image.fromarray(np.concatenate([a, np.full((a.shape[0], 12, 3), 255, np.uint8), b], axis=1)).save(os.path.join(d, PS.FRAME))
    g0 = srep['geoms']
    def _agg(key, field):
        v = [x[key][field] for x in g0 if x.get(key) and x[key].get(field) is not None]
        return round(float(max(v)), 3) if v else None
    def _rough(key, field):
        v = [x[key][field] for x in g0 if x.get(key)]
        return round(float(max(v)), 3) if v else None
    secs = time.time() - t0
    rb = _rough_max([x['rough_before'] for x in g0], 'rough_rms_mm')
    ra = _rough_max([x['rough_after'] for x in g0], 'rough_rms_mm')
    p95b, p95a = _agg('before', 'dE00_p95'), _agg('after', 'dE00_p95')
    medb, meda = _agg('before', 'dE00_median'), _agg('after', 'dE00_median')
    stb, sta = _agg('before', 'step_ratio'), _agg('after', 'step_ratio')
    def _dev(key):                                   # худшее отклонение texture_ratio от 1 по геометриям
        v = [abs(x[key]['texture_ratio'] - 1.0) for x in g0 if x.get(key) and x[key].get('texture_ratio') is not None]
        return round(float(max(v)), 3) if v else None
    txb, txa = _dev('before'), _dev('after')
    metrics = {
        'seam_dE00_p95': {'value': p95a, 'threshold': p95b, 'op': '<=', 'note': 'после ≤ до'},
        'boundary_rough_rms_mm': {'value': ra, 'threshold': rb, 'op': '<=', 'note': 'после ≤ до'},
        'seam_step_ratio': {'value': sta, 'threshold': (None if stb is None else max(stb, 1.5)), 'op': '<=', 'note': 'скачок яркости поперёк шва / такой же внутри фото (цель ≈ 1); после ≤ max(до; 1,5)'},
        'seam_texture_dev': {'value': txa, 'threshold': (None if txb is None else max(txb, 0.3)), 'op': '<=', 'note': '|σ мелкого рельефа заливка/фото в полосе шва − 1| (цель ≈ 0); после ≤ max(до; 0,3)'},
        'photo_middle_changed_texels': {'value': mid_bad, 'threshold': 0, 'op': '<='},
        'time_s': {'value': round(secs, 1), 'threshold': 120.0, 'op': '<='},
    }
    for m in metrics.values():
        m['ok'] = None if m['value'] is None or m['threshold'] is None else PS.judge(m['value'], m['op'], m['threshold'])
    srep['summary'] = {'dE00_median': [medb, meda], 'dE00_p95': [p95b, p95a], 'rough_rms_mm': [rb, ra], 'step_ratio': [stb, sta], 'texture_dev': [txb, txa], 'changed_texels': changed, 'photo_middle_texels': mid_all, 'photo_middle_changed': mid_bad,
                       'parts_note': parts_note}
    with open(os.path.join(d, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump({'seam': srep}, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    check = PS.write_check(d, STAGE, sku, None, None, '', metrics=metrics, seconds=secs, outputs=['seam.glb', 'report.json'], frame=PS.FRAME, summary=srep['summary'])
    return {'check': check, 'report': srep, 'dir': d}


def _rough_max(lst: list, field: str):
    v = [x[field] for x in lst if x]
    return round(float(max(v)), 3) if v else None


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog='seam_stage.py')
    ap.add_argument('run')
    ap.add_argument('sku')
    ap.add_argument('--fill', required=True, help='папка 07-fill (filled.glb)')
    ap.add_argument('--visible', required=True, help='папка 06-visible (known*.png, conf*.png)')
    ap.add_argument('--cfg', default=None)
    a = ap.parse_args(argv)
    try:
        r = run_seam(a.run, a.sku, a.fill, a.visible, json.loads(a.cfg) if a.cfg else None)
    except Exception as e:                                                       # noqa: BLE001 — сбой запуска: в check.json, не молча
        d = PS.stage_dir(a.run, a.sku, STAGE)
        PS.write_check(d, STAGE, a.sku, False, None, f'сбой шага шва: {type(e).__name__}: {e}'[:300], outputs=[])
        print(f'сбой: {type(e).__name__}: {e}', file=sys.stderr)
        return 2
    c = r['check']
    print(f'07-seam {a.sku}: passed={c["passed"]} {c["reason"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
