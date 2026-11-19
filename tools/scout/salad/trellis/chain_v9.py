#!/usr/bin/env python3
"""T-20261119-88 (план `mesh-photo-projection-01`): ЦЕПОЧКА «ВАРИАНТ 9» на готовой краске MV-Adapter, бесплатно, на процессоре, форма и развёртка не меняются.

  1. краска MV-Adapter на 12 камер (mv12) — вход цепочки, не пересчитывается (GLB из `T-20261119-81/c2-mv12/`);
  2. пиксели фото на видимую сторону (`photo_front.py`: вес по углу, растушёвка по поверхности, гейт «рельеф ≠ фото → не класть»); карта сразу пишется в итоговый размер (`--out-size`, 4096);
  3. оттенок a*b* (`ab_tint.py`, T-20261119-87);
  4. заливка дыр по поверхности меша (`tex_fill.py` из ветки trial/tex-fill, вызывается как есть отдельным процессом — у неё свой `tex_coverage`);
  5. итог — карта 4096 (копия результата шага 4 под именем `<ключ>-v9-4096.glb`, проверка размера и формы).

На КАЖДОМ шаге: свой GLB и json в папке шага, кадр вида 0° (`view0.png`), мерки (hf 1 %, σL, ΔE00 нч, `pattern_grad_ncc`, регистрация фиксированная), проверка формы относительно входа (вершины/грани/UV, 1e-6).
Любой отказ шага или формы — цепочка стоит, в `chain.json` причина (дальше не идём на «битом» входе).

  chain_v9.py --glb <mv12.glb> --stages <A0 stages/> --photo <фото .rgba.png> --out-dir <папка> --key <ключ> [--yaw N] [--size 4096]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))

FORM_TOL = 1e-6


def form_guard(a: str, b: str, tol: float = FORM_TOL) -> dict:
    """Форма и развёртка двух GLB совпадают: вершины, грани, UV (trimesh без слияния вершин), число геометрий. Размер карты не сравниваем."""
    import trimesh

    def load(p):
        sc = trimesh.load(p, force='scene', process=False)
        out = []
        for name in sorted(sc.geometry):
            g = sc.geometry[name]
            out.append((np.asarray(g.vertices, np.float64), np.asarray(g.faces, np.int64), np.asarray(g.visual.uv, np.float64)))
        return out
    ga, gb = load(a), load(b)
    if len(ga) != len(gb):
        return {'ok': False, 'why': f'число геометрий {len(ga)} → {len(gb)}'}
    dv = df = du = 0.0
    for (va, fa, ua), (vb, fb, ub) in zip(ga, gb):
        if va.shape != vb.shape or fa.shape != fb.shape or ua.shape != ub.shape:
            return {'ok': False, 'why': f'формы массивов {va.shape}/{fa.shape}/{ua.shape} → {vb.shape}/{fb.shape}/{ub.shape}'}
        dv, df, du = max(dv, float(np.abs(va - vb).max())), max(df, float(np.abs(fa - fb).max())), max(du, float(np.abs(ua - ub).max()))
    return {'ok': dv <= tol and df == 0 and du <= tol, 'max_diff_vertices': dv, 'max_diff_faces': df, 'max_diff_uv': du}


def run_chain(steps: list, first_glb: str, out_dir: str, measure, guard=form_guard) -> dict:
    """Цепочка шагов. `steps` — список `(имя, функция(glb_in, папка_шага) → glb_out)`; для каждого: запуск → проверка формы относительно входа цепочки → мерки (`measure(glb, папка_шага, имя)`) →
    выход идёт следующему. Первый шаг (`first_glb`) измеряется как «шаг 1». Сбой шага/формы → `ok: False`, `failed_step`, дальше не идём. Итог пишется в `chain.json`."""
    os.makedirs(out_dir, exist_ok=True)
    res = {'input': first_glb, 'steps': [], 'ok': True, 'failed_step': None}
    cur = first_glb
    t0 = time.time()

    def record(name, glb, d, extra):
        rec = {'name': name, 'glb': glb, 'dir': d, **extra}
        if glb != first_glb:
            rec['form_guard'] = guard(first_glb, glb)
            if not rec['form_guard']['ok']:
                rec['error'] = 'форма/развёртка изменились'
                return rec
        rec['metrics'] = measure(glb, d, name)
        return rec

    d1 = os.path.join(out_dir, 's1-mv12')
    os.makedirs(d1, exist_ok=True)
    rec = record('s1-mv12', first_glb, d1, {'t_s': 0.0})
    res['steps'].append(rec)
    for name, fn in steps:
        d = os.path.join(out_dir, name)
        os.makedirs(d, exist_ok=True)
        t1 = time.time()
        try:
            out = fn(cur, d)
            rec = record(name, out, d, {'t_s': round(time.time() - t1, 1)})
        except Exception as e:  # noqa: BLE001 — шаг упал: цепочка стоит, причина в json
            rec = {'name': name, 'dir': d, 'error': f'{type(e).__name__}: {e}', 't_s': round(time.time() - t1, 1)}
        res['steps'].append(rec)
        if rec.get('error'):
            res['ok'] = False
            res['failed_step'] = name
            break
        cur = rec['glb']
    res['final'] = cur if res['ok'] else None
    res['time_s'] = round(time.time() - t0, 1)
    json.dump(res, open(os.path.join(out_dir, 'chain.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


class Measurer:
    """Мерки по кадру вида 0 для любой карты любого размера (регистрация и маска — А0, форма/UV те же)."""

    def __init__(self, stages: str, photo_path: str):
        import cv2
        from PIL import Image
        import a1_tone as A
        import stage_loss as SL
        self.A, self.SL, self.Image = A, SL, Image
        sl = json.load(open(os.path.join(os.path.dirname(stages.rstrip('/')), 'stage_loss.json'), encoding='utf-8'))
        P = np.array(sl['registration']['P'], np.float64).reshape(3, 3)
        rd = os.path.join(stages, 'render_view0')
        S = np.asarray(Image.open(os.path.join(rd, 'mask.png')).convert('L')) > 127
        aoi = np.asarray(Image.open(os.path.join(rd, 'aoi_cos16.png'))).astype(np.float32) / 65535.0
        self.uvd = np.load(os.path.join(rd, 'uv.npz'))
        photo = SL.read_rgba(photo_path)
        fh, fw = S.shape
        A_fr = SL.warp_inv((photo[..., 3] > 127).astype(np.float32), P, (fw, fh)) > 0.5
        self.cm, self.width = SL.common_mask(S, A_fr, aoi)
        self.ph = np.clip(SL.warp_inv(photo[..., :3], P, (fw, fh), cv2.INTER_LINEAR), 0, 255).astype(np.uint8)

    def __call__(self, glb: str, d: str, name: str) -> dict:
        import ab_tint as T
        j, b = self.A.read_glb(glb)
        tex = T.read_texture(j, b)
        img = self.A.render_view0(tex, self.uvd)
        self.Image.fromarray(img).save(os.path.join(d, 'view0.png'))
        m = self.SL.stage_metrics(img, self.ph, self.cm, self.width, ncc=True)
        out = {'tex_size': list(tex.shape[:2]), 'hf_1%': m['hf']['1%']['ratio'], 'sigmaL': m['sigmaL']['ratio'], 'dE00_lf': m['dE00_lf_median'],
               'ncc': (m.get('ncc') or {}).get('median'), 'ncc_p10': (m.get('ncc') or {}).get('p10')}
        json.dump(out, open(os.path.join(d, 'metrics.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        return out


def _sub(cmd: list, log: str, env: dict | None = None, cwd: str | None = None) -> None:
    with open(log, 'w', encoding='utf-8') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f'{os.path.basename(cmd[1])} rc={r.returncode}, см. {log}')


def make_steps(a) -> list:
    py = sys.executable

    def s2(glb, d):
        _sub([py, os.path.join(HERE, 'photo_front.py'), '--glb', glb, '--stages', a.stages, '--photo', a.photo, '--out-dir', d, '--stem', a.key, '--out-size', str(a.size)], os.path.join(d, 'step.log'))
        return os.path.join(d, f'{a.key}-photo.glb')

    def s3(glb, d):
        _sub([py, os.path.join(HERE, 'ab_tint.py'), '--glb', glb, '--stages', a.stages, '--photo', a.photo, '--out-dir', d, '--stem', a.key], os.path.join(d, 'step.log'))
        return os.path.join(d, f'{a.key}-ab.glb')

    def s4(glb, d):
        src = os.path.join(d, f'{a.key}.glb')
        shutil.copyfile(glb, src)                                           # tex_fill называет выход по имени входа: <ключ>-fill.glb
        env = dict(os.environ, PYTHONPATH=HERE + os.pathsep + os.environ.get('PYTHONPATH', ''))
        _sub([py, os.path.join(a.fill_dir, 'tex_fill.py'), src, '--out', d, '--yaw', str(a.yaw), '--grid', str(a.size)], os.path.join(d, 'step.log'), env=env, cwd=a.fill_dir)
        os.remove(src)
        return os.path.join(d, f'{a.key}-fill.glb')

    def s5(glb, d):
        dst = os.path.join(d, f'{a.key}-v9-{a.size}.glb')
        shutil.copyfile(glb, dst)
        import ab_tint as T
        import a1_tone as A
        j, b = A.read_glb(dst)
        n = T.read_texture(j, b).shape[0]
        if n != a.size:
            raise ValueError(f'итог: карта {n}, ожидалась {a.size}')
        return dst
    return [('s2-photo', s2), ('s3-ab', s3), ('s4-fill', s4), ('s5-final', s5)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb', required=True)
    ap.add_argument('--stages', required=True)
    ap.add_argument('--photo', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--yaw', default='auto', help='поворот формы для tex_fill (из stages/manifest.json: yaw_deg)')
    ap.add_argument('--size', type=int, default=4096)
    ap.add_argument('--fill-dir', default=os.path.expanduser('~/remlab-logs/t88-v9/tool'), help='папка с tex_fill.py и его tex_coverage.py (ветка trial/tex-fill)')
    a = ap.parse_args()
    if a.yaw == 'auto':
        m = json.load(open(os.path.join(a.stages, 'manifest.json'), encoding='utf-8'))
        a.yaw = m.get('yaw_deg', 0.0)
    res = run_chain(make_steps(a), a.glb, a.out_dir, Measurer(a.stages, a.photo))
    for s in res['steps']:
        mt = s.get('metrics') or {}
        print(f"{s['name']:9s} {s.get('error') or 'ok':10s} карта {mt.get('tex_size')} hf1%={mt.get('hf_1%')} σL={mt.get('sigmaL')} ΔE00нч={mt.get('dE00_lf')} ncc={mt.get('ncc')} форма={(s.get('form_guard') or {}).get('ok')} {s.get('t_s')} с")
    print('итог:', res['final'] or f"ОТКАЗ на {res['failed_step']}")
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
