#!/usr/bin/env python3
"""Проба заливки невидимого (T-20261120-164) на готовых покрашенных прогонах Salad — без платного, на процессоре.
На каждый прогон: этап 07 (`tex_fill.run_stage`: GLB → маска «видно с камер фото» az0/az45 → части → заливка → `<выход>/<метка>/07-fill/{filled.glb, report.json, frame.png, check.json}`) и сверх этапа —
кадры «до | после» с az000 (перёд), az090, az180 (отдельные полные PNG + пара) и мера сторожа охвата с камерами прогона до/после.
  python3 tex_fill_probe.py [--visible-root <корень этапа 6: <root>/<sku>/06-visible> --source stat|trellis --draft-dir <папка родных GLB TRELLIS.2> --draft-fallback on|off --draft-texture on|off] <выход-папка> <папка-прогона> [<папка-прогона> …]
Источник «trellis» (вариант Б): черновик берётся как `<draft-dir>/<mid>_<eid>-1024-42-0.glb` по имени прогона (до «@»); нет файла — сбой этого товара, счётчик отказов в итоге.
Строка на прогон — `<выход>/results.jsonl`; таблица товар × этап — `python3 tools/scout/paint_stage.py table <выход>`."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'stablegen'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np  # noqa: E402
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402


def probe(rund: str, out: str, label: str, cfg: dict | None = None, draft_glb: str | None = None, visible: str | None = None) -> dict:
    """visible — папка `06-visible` этапа 6 (visible.glb + known.png[, known1.png…]): настоящий вход этапа 7; без неё — GLB прогона `rund` и маска «видно с камер» az0/az45."""
    import sg_cams
    import sg_guard
    from PIL import Image
    if visible:
        cfg = dict({'erode_known': 0}, **(cfg or {}))          # вход этапа 6: маска «взято с фото» уже честная (дыры ≤2,5 текселя закрыты); отступ в 3 пикселя съедал бы известное (грани мельче пикселя) и затирал бы кадр фото
        kn = []
        for i in range(64):
            fp = os.path.join(visible, 'known.png' if i == 0 else f'known{i}.png')
            if not os.path.exists(fp):
                break
            kn.append(np.asarray(Image.open(fp).convert('L')) > 127)
        r = TF.run_stage(out, label, os.path.join(visible, 'visible.glb'), known=kn, cfg=cfg, draft_glb=draft_glb)
    else:
        r = TF.run_stage(out, label, sg_guard.glb_of(rund), cfg=cfg, draft_glb=draft_glb)
    geoms, before, after, rep = r['geoms'], r['tex_before'], r['tex_after'], r['report']
    rec = {'run': label, 'passed': r['check']['passed'], 'reason': r['check']['reason'], 'metrics': r['check']['metrics'], 'seconds': r['check']['seconds'],
           'known_pct': rep['known_pct'], 'mirrored_pct': rep['mirrored_pct'], 'geodesic_pct': rep['geodesic_pct'], 'part_mean_pct': rep['part_mean_pct'],
           'unpainted_before_pct': rep['unpainted_before_pct'], 'unpainted_after_pct': rep['unpainted_after_pct'], 'fallback_global': rep['fallback_global'], 'no_patch': rep['no_patch'],
           'mirror': rep['mirror'], 'steps': rep['steps'], 'brightness': rep['brightness'], 'deltaE_by_part': r['deltaE'], 'parts_note': r['check']['extra'].get('parts'),
           'draft': rep.get('draft'), 'draft_transfer': rep.get('draft_transfer'), 'back_visible_pct': round(100.0 * float(np.mean([kk.mean() for kk in r['kback']])), 1)}
    try:                                                          # мера сторожа охвата с камерами прогона: до и после
        if visible:
            raise RuntimeError('вход — этап 6 (visible.glb): камер прогона нет, мера охвата не считается')
        V = np.concatenate([g['V'] for g in geoms])
        doc = sg_cams.rig_for_run(rund, ((V.min(axis=0) + V.max(axis=0)) / 2.0).tolist(), None, True)
        rig = sg_cams.rig_glb(doc)
        T = min(2048, max(max(g['tex'].shape[:2]) for g in geoms))
        for nm, tx in (('before', before), ('after', after)):
            gg = [dict(g, tex=t) for g, t in zip(geoms, tx)]
            rr = TC.analyze(gg, 0.0, T, 768, ext_n=TC.EXT_DIRS, rig=rig)
            rec['guard_' + nm] = {'outer_tex': rr['outer_tex'], 'tex': rr['tex']}
    except Exception as e:  # noqa: BLE001 — мера охвата не обязательна для кадров
        rec['guard_error'] = f'{type(e).__name__}: {e}'
    for az, el, nm in ((0.0, 0.0, 'az000-перёд'), (90.0, 0.0, 'az090-бок'), (180.0, 0.0, 'az180-зад'), (0.0, -90.0, 'низ')):     # перёд (как «фото»), бок, зад, дно (камера снизу)
        a, b = TF.render_ortho(geoms, before, az, elevation=el), TF.render_ortho(geoms, after, az, elevation=el)
        Image.fromarray(a).save(os.path.join(out, f'{label}-before-{nm}.png'))
        Image.fromarray(b).save(os.path.join(out, f'{label}-after-{nm}.png'))
        Image.fromarray(np.concatenate([a, np.full((a.shape[0], 12, 3), 255, np.uint8), b], axis=1)).save(os.path.join(out, f'{label}-pair-{nm}.png'))
    Image.fromarray(after[0]).save(os.path.join(out, f'{label}-after-atlas0.png'))
    return rec


def main() -> int:
    args = sys.argv[1:]
    cfg, draft_dir, visible_root, draft_pat = {}, None, None, '{base}-1024-42-0.glb'
    while args and args[0].startswith('--'):
        k, v = args[0], args[1]
        if k == '--source':
            cfg['source'] = v
        elif k == '--draft-dir':
            draft_dir = v
        elif k == '--draft-fallback':                 # on|off: этап считает и А, берёт Б только если мерки не хуже (по умолчанию on); off — Б «как есть» для сравнения
            cfg['draft_fallback'] = (v == 'on')
        elif k == '--draft-pattern':                 # имя черновика в --draft-dir, {base} — имя прогона/товара (по умолчанию родной TRELLIS.2: {base}-1024-42-0.glb; out30: {base}-n1024.glb)
            draft_pat = v
        elif k == '--visible-root':                   # корень выхода этапа 6 (`<root>/<sku>/06-visible/`): вместо папок прогонов — имена товаров (sku)
            visible_root = v
        elif k == '--draft-texture':                  # on|off: класть на черновик Б лоскут фактуры фото (квилт)
            cfg['draft_texture'] = (v == 'on')
        elif k == '--cfg':                            # JSON-добавка к FILL (варианты проб): '{"pattern_render": false, "pr_block_max": 64}'
            cfg.update(json.loads(v))
        else:
            print(__doc__)
            return 2
        args = args[2:]
    if len(args) < 2 or (cfg.get('source') == 'trellis' and not draft_dir):
        print(__doc__)
        return 2
    out, runs = args[0], args[1:]
    os.makedirs(out, exist_ok=True)
    bad = 0
    for rund in runs:
        base = os.path.basename(rund.rstrip('/'))
        label = (base[-12:] if visible_root else base.split('-q2509')[0].split('@')[0][-12:] + '_' + base.split('@')[-1][:12])
        try:
            dg = os.path.join(draft_dir, draft_pat.format(base=base.split('@')[0])) if draft_dir else None
            if dg and not os.path.exists(dg):
                raise FileNotFoundError(f'нет черновика {dg}')
            rec = probe(rund, out, label, cfg, dg, os.path.join(visible_root, base, '06-visible') if visible_root else None)
        except Exception as e:  # noqa: BLE001 — один сбой не рушит пакет, счётчик отказов в итоге
            rec = {'run': label, 'error': f'{type(e).__name__}: {e}'}
            bad += 1
        with open(os.path.join(out, 'results.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, 'item') else str(o)) + '\n')
        print(json.dumps({k: rec.get(k) for k in ('run', 'error', 'passed', 'reason', 'seconds')}, ensure_ascii=False), flush=True)
    print(f'проба: ошибок {bad} из {len(runs)}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
