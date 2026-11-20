#!/usr/bin/env python3
"""Проба заливки невидимого (T-20261120-164) на готовых покрашенных прогонах Salad — без платного, на процессоре.
На каждый прогон: GLB → маска «видно с камер фото» (az0, az45; потом заменит камера T-112) → части (геометрия `material_parts`: ножки / обивка / нейтральное; нет — одна часть) → заливка →
кадры «до | после» сзади (az180, отдельные полные PNG + пара), метрики: «не закрашено» до/после (по самой заливке и по мере сторожа охвата с камерами прогона), ΔE00 перёд↔зад по частям, время заливки.
  python3 tex_fill_probe.py <выход-папка> <папка-прогона> [<папка-прогона> …]
Строка результата на прогон — `<выход>/results.jsonl`; кадры — `<выход>/<метка>-{before,after,pair}-az180.png`."""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'stablegen'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'assets'))
import numpy as np  # noqa: E402
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402


def parts_of(geoms: list):
    """Части граней по геометрии: 0 обивка/корпус, 1 ножки, 2 нейтральное (тонкое, полоса у ножек). Нет уверенного деления — одна часть. → (список по геометриям | None, строка о способе)."""
    try:
        import material_parts as MP
        rules = MP.load_rules()
    except Exception as e:  # noqa: BLE001 — частей нет, заливка идёт одной частью
        return None, f'частей нет ({type(e).__name__})'
    out, note = [], []
    for g in geoms:
        nf = len(g['F'])
        try:
            rec = MP.judge(MP.analyze(g['mesh'], rules), rules, None)
            if rec.get('status') == 'split' and rec.get('apply', rec.get('confidence', 0) >= rules['confidence']['apply']):
                leg = MP.legs_face_mask(g['mesh'], rec)
                neu = MP.neutral_face_mask(g['mesh'], rec) & ~leg
                p = np.zeros(nf, np.int32)
                p[leg] = 1
                p[neu] = 2
                out.append(p)
                note.append(f"split ножки {int(leg.sum())} нейтр. {int(neu.sum())} из {nf}")
                continue
            note.append(f"{rec.get('status')} → одна часть")
        except Exception as e:  # noqa: BLE001
            note.append(f'сбой частей {type(e).__name__}')
        out.append(np.zeros(nf, np.int32))
    return out, '; '.join(note)


def part_deltas(geoms, parts, kfront, kback, tex_before, tex_after) -> dict:
    """ΔE00 перёд↔зад внутри одной части: средние Lab текселей, видимых спереди (az0/45) и видимых сзади (az180), до и после заливки."""
    res = {}
    ids = sorted({int(p) for pp in (parts or [np.zeros(len(g['F']), np.int32) for g in geoms]) for p in np.unique(pp)})
    for p in ids:
        sets = {'before': ([], []), 'after': ([], [])}
        for gi, g in enumerate(geoms):
            T = TF._grid(g)
            tx = TF.Tex(g, np.asarray(g['V'], np.float64), T, None if parts is None else parts[gi])
            sel = tx.part == p
            for nm, tex in (('before', tex_before[gi]), ('after', tex_after[gi])):
                flat = tex.reshape(-1, 3)
                for k, kk in ((0, kfront[gi]), (1, kback[gi])):
                    m = kk.reshape(-1)[tx.ti] & sel
                    m &= ~TF.unpainted_mask(flat[tx.ti])
                    if m.any():
                        sets[nm][k].append(TF.rgb2lab(flat[tx.ti[m]]))
        r = {}
        for nm, (fr, bk) in sets.items():
            if fr and bk:
                a, b = np.concatenate(fr).mean(axis=0, keepdims=True), np.concatenate(bk).mean(axis=0, keepdims=True)
                r[nm] = round(float(TC.de2000_v(a, b)[0]), 2)
            else:
                r[nm] = None
        res[p] = r
    return res


def probe(rund: str, out: str, label: str) -> dict:
    import sg_cams
    import sg_guard
    from PIL import Image
    glb = sg_guard.glb_of(rund)
    geoms = TC.load_geoms(glb)
    rec = {'run': label, 'geoms': len(geoms), 'tex': [list(np.asarray(g['tex']).shape[:2]) for g in geoms]}
    tex_before = [np.asarray(g['tex']).copy() for g in geoms]
    t0 = time.time()
    known = TF.known_from_photo(geoms)
    parts, note = parts_of(geoms)
    rec['parts_note'] = note
    t1 = time.time()
    res = TF.fill(geoms, known, parts)
    t2 = time.time()
    rec['time_s'] = {'visibility_parts': round(t1 - t0, 1), 'fill': round(t2 - t1, 1), 'all': round(t2 - t0, 1)}
    rep = res['report']
    for k in ('texels', 'known_pct', 'mirrored_pct', 'geodesic_pct', 'part_mean_pct', 'unpainted_before_pct', 'unpainted_after_pct', 'fallback_global', 'no_patch'):
        rec[k] = rep[k]
    rec['mirror'] = rep['mirror']
    rec['steps'] = rep['steps']
    rec['brightness'] = rep['brightness']
    rec['fill_time_parts'] = rep['time_s']
    tex_after = res['tex']
    # перёд↔зад
    kback = TF.known_from_photo(geoms, azimuths=(180.0,))
    rec['deltaE_front_back'] = part_deltas(geoms, parts, known, kback, tex_before, tex_after)
    rec['back_visible_pct'] = round(100.0 * float(np.mean([kk.mean() for kk in kback])), 1)
    # мера сторожа охвата с камерами прогона: до и после
    try:
        V = np.concatenate([g['V'] for g in geoms])
        doc = sg_cams.rig_for_run(rund, ((V.min(axis=0) + V.max(axis=0)) / 2.0).tolist(), None, True)
        rig = sg_cams.rig_glb(doc)
        T = min(2048, max(max(g['tex'].shape[:2]) for g in geoms))
        for nm, tx in (('before', tex_before), ('after', tex_after)):
            gg = [dict(g, tex=t) for g, t in zip(geoms, tx)]
            r = TC.analyze(gg, 0.0, T, 768, ext_n=TC.EXT_DIRS, rig=rig)
            rec['guard_' + nm] = {'outer_tex': r['outer_tex'], 'tex': r['tex']}
    except Exception as e:  # noqa: BLE001 — мера охвата не обязательна для кадров
        rec['guard_error'] = f'{type(e).__name__}: {e}'
    # кадры «до | после» сзади, перёд для сверки
    for az in (0.0, 90.0, 180.0):
        nm = f'az{int(az):03d}'
        a = TF.render_ortho(geoms, tex_before, az)
        b = TF.render_ortho(geoms, tex_after, az)
        Image.fromarray(a).save(os.path.join(out, f'{label}-before-{nm}.png'))
        Image.fromarray(b).save(os.path.join(out, f'{label}-after-{nm}.png'))
        Image.fromarray(np.concatenate([a, np.full((a.shape[0], 12, 3), 255, np.uint8), b], axis=1)).save(os.path.join(out, f'{label}-pair-{nm}.png'))
    Image.fromarray(TF.unpainted_mask(tex_before[0]).astype(np.uint8) * 255).save(os.path.join(out, f'{label}-unpainted-before-atlas0.png'))
    Image.fromarray(tex_after[0]).save(os.path.join(out, f'{label}-after-atlas0.png'))
    return rec


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    bad = 0
    for rund in sys.argv[2:]:
        label = os.path.basename(rund.rstrip('/')).split('-q2509')[0].split('@')[0][-12:] + '_' + os.path.basename(rund.rstrip('/')).split('@')[-1][:12]
        try:
            rec = probe(rund, out, label)
        except Exception as e:  # noqa: BLE001 — один сбой не рушит пакет, счётчик отказов в итоге
            rec = {'run': label, 'error': f'{type(e).__name__}: {e}'}
            bad += 1
        with open(os.path.join(out, 'results.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(json.dumps({k: rec.get(k) for k in ('run', 'error', 'time_s', 'known_pct', 'unpainted_before_pct', 'unpainted_after_pct', 'fallback_global', 'no_patch')}, ensure_ascii=False), flush=True)
    print(f'проба: ошибок {bad} из {len(sys.argv) - 2}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
