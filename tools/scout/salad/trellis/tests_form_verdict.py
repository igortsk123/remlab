#!/usr/bin/env python3
"""T-20261125-78/2: ярлык формы этапа 04 (form_verdict.py) — «форма / скругление / ложная_кромка / ок», только отчёт; флаг выкл = блока нет.
Синтетика: ящик 0,88 × 1,0 × 0,26 с камеры az 20° (видна боковина), кадр нормалей из pose_fit.render_persp; цель стыка (кромка фото) задаётся по сценарию.
Нужны numpy, PIL, cv2. Без тяжёлого:  python3 tools/scout/salad/trellis/tests_form_verdict.py"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_form_verdict')
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import camera_check as CC  # noqa: E402
import form_verdict as FV  # noqa: E402
import junction as J  # noqa: E402
import pose_fit as PF  # noqa: E402

LO, HI = np.array([-0.44, -0.5, -0.13]), np.array([0.44, 0.5, 0.13])
CAM = {'az': 20.0, 'el': 3.0, 'd': 3.0, 'f': 2.4, 'cx': 0.5, 'cy': 0.5}
CV = {'x0': 0.0, 'y0': 0.0, 'side': 800.0}
NPX = 256
BOX = J.box_geometry(LO, HI)
POSE = {'camera': CAM, 'form_box': {'lo': LO.tolist(), 'hi': HI.tolist()}}
bad = 0


def check(name: str, ok: bool, extra: str = '') -> None:
    global bad
    if not ok:
        bad += 1
    print(('ok   ' if ok else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))


def box_geo() -> dict:
    """Ящик: 12 плоских треугольников, нормаль вершины = нормаль грани."""
    V, N = [], []
    for k in range(3):
        a, b = [i for i in range(3) if i != k]
        for sgn, val in ((-1, LO[k]), (1, HI[k])):
            q = []
            for ua, ub in ((0, 0), (1, 0), (1, 1), (0, 1)):
                p = np.zeros(3)
                p[k], p[a], p[b] = val, (LO, HI)[ua][a], (LO, HI)[ub][b]
                q.append(p)
            for tri in ((0, 1, 2), (0, 2, 3)):
                for i in tri:
                    V.append(q[i])
                    n = np.zeros(3)
                    n[k] = sgn
                    N.append(n)
    V = np.array(V)
    return {'V': V, 'F': np.arange(len(V)).reshape(-1, 3), 'UV': np.zeros((len(V), 2)), 'N': np.array(N)}


def write_run(root: str) -> str:
    r = PF.render_persp(box_geo(), CAM, NPX)
    rgb = ((r['normal'] * 0.5 + 0.5).clip(0, 1) * 255 * r['mask'][..., None]).round().astype(np.uint8)          # как pose_fit.write_stages
    d = os.path.join(root, 'stages', 'render_view0')
    os.makedirs(d, exist_ok=True)
    Image.fromarray(rgb).save(os.path.join(d, 'normal_cam.png'))
    return root


def fe_for(fl, fr, side, w_photo, scenario, sidew):
    """front_edge-словарь для сценария: цель стыка на стороне боковины сдвинута, другая сторона — на углу формы."""
    tgt = {'l': fl, 'r': fr}
    kind = {'l': 'кромка', 'r': 'кромка'}
    form = {'l': fl, 'r': fr}
    sgn = 1.0 if side == 'r' else -1.0
    if scenario == 'форма':                                         # у фото бока нет: цель — внешний край боковины формы, боковина целиком ложится на фасад фото
        tgt[side] = form[side] + sgn * sidew
    elif scenario == 'ложная_кромка':                               # то же, но цель взята по контуру (кромку бока мерка не нашла)
        tgt[side] = form[side] + sgn * sidew
        kind[side] = 'контур'
    elif scenario == 'скругление':                                  # цель внутрь от угла формы: фасад формы заходит на скруглённый угол, боковина на своём месте
        tgt[side] = form[side] - sgn * 0.04 * w_photo
    dx = {s: round(form[s] - tgt[s], 1) for s in 'lr'}
    return {'measured': True, 'dx_px': dx, 'kind': kind, 'target_px': tgt, 'form_px': form, 'gap_px': round(max(abs(dx['l']), abs(dx['r'])), 1), 'width_px': round(w_photo, 1), 'has_edge': True}


def test_classify_labels():
    kinds_ok = {'l': 'кромка', 'r': 'кромка'}
    sw0 = {'l': 0.0, 'r': 0.0}
    c = FV.classify(23.2, 68.8, kinds_ok, sw0)
    check('classify: форма', c['label'] == 'форма' and not c['uncertain'], c['why'])
    c = FV.classify(3.5, 0.0, kinds_ok, sw0)
    check('classify: скругление', c['label'] == 'скругление', c['why'])
    c = FV.classify(9.4, 98.7, {'l': 'контур', 'r': 'кромка'}, {'l': 61.0, 'r': 4.0})
    check('classify: ложная_кромка важнее «формы» (числа недостоверны)', c['label'] == 'ложная_кромка', c['why'])
    c = FV.classify(0.8, 0.0, kinds_ok, sw0)
    check('classify: ок (стык в норме)', c['label'] == 'ок' and not c['uncertain'])
    c = FV.classify(5.0, 20.0, kinds_ok, sw0)
    check('classify: серая зона (бок между порогами) — ок, uncertain', c['label'] == 'ок' and c['uncertain'], c['why'])
    c = FV.classify(5.0, None, kinds_ok, sw0)
    check('classify: боковины нет, стык велик — ок, uncertain', c['label'] == 'ок' and c['uncertain'])
    c = FV.classify(0.1, 0.0, {'l': 'контур', 'r': 'контур'}, {'l': 2.0, 'r': 0.0})
    check('classify: контур без видимой боковины (<8 px) — не ложная кромка', c['label'] == 'ок', c['why'])
    c = FV.classify(3.0, 0.0, kinds_ok, sw0, {'gap_pct_min': 5.0})
    check('classify: порог — из правил, не из кода (gap_pct_min 5 → ок)', c['label'] == 'ок')


def test_synthetic_box_all_labels():
    with tempfile.TemporaryDirectory() as root:
        run = write_run(root)
        fl, fr = J.front_corners(PF, BOX, CAM, CV)[0]
        wide = {'form_px': {'l': fl, 'r': fr}, 'target_px': {'l': -1e9, 'r': 1e9}}
        rgb = np.asarray(Image.open(os.path.join(run, 'stages', 'render_view0', 'normal_cam.png')).convert('RGB'))
        st0 = FV.side_stats(rgb, BOX, CAM, CV, wide)
        side = 'l' if st0['side_w_px']['l'] > st0['side_w_px']['r'] else 'r'
        sidew = st0['side_w_px'][side]
        check('ящик: боковина видна с одной стороны, ширина > 20 px, вся на «фасаде» при открытой цели', sidew > 20 and st0['side_w_px']['l' if side == 'r' else 'r'] < 3 and st0['side_from_front'] == 100.0,
              str(st0))
        w_photo = (fr - fl) + sidew
        got = {}
        for sc in ('ок', 'форма', 'скругление', 'ложная_кромка'):
            fe = fe_for(fl, fr, side, w_photo, sc, sidew)
            v = FV.from_run(run, POSE, fe, CV, J)
            got[sc] = v
            check(f'ящик, сценарий «{sc}»: ярлык {sc}', v['measured'] and v['label'] == sc, f"{v.get('label')} gap {v.get('gap_pct')} % бок из фасада {v.get('side_from_front')} % {v.get('why')}")
        check('ящик «ок»: стык 0, бок на своём месте (бок из фасада ≈ 0)', got['ок']['gap_pct'] == 0.0 and got['ок']['side_from_front'] < 5.0, str(got['ок']))
        check('ящик «форма»: бок из фасада ≈ 100 %, edge_kind = кромка', got['форма']['side_from_front'] > 95.0 and got['форма']['edge_kind'][side] == 'кромка')
        check('ящик «скругление»: бок из фасада ≈ 0, фасад на боку фото > 0', got['скругление']['side_from_front'] < 5.0 and got['скругление']['front_on_side'] > 0.0, str(got['скругление']))
        check('ящик «ложная_кромка»: edge_kind = контур на стороне боковины', got['ложная_кромка']['edge_kind'][side] == 'контур')
        check('блок самодостаточен: пороги и ширина боковины записаны', set(got['форма']['thresholds']) == set(FV.DEFAULTS) - {'enabled'} and got['форма']['side_w_px'][side] > 20)


def test_not_measured_is_not_ok():
    with tempfile.TemporaryDirectory() as root:
        run = write_run(root)
        v = FV.from_run(run, POSE, {'measured': False, 'reason': 'форма не коробчатая'}, CV, J)
        check('стык не измерен → label None (не «ок»), причина названа', v['measured'] is False and v['label'] is None and 'не коробчатая' in v['reason'], str(v))
        fl, fr = J.front_corners(PF, BOX, CAM, CV)[0]
        fe = fe_for(fl, fr, 'r', 700.0, 'ок', 40.0)
        v = FV.from_run(os.path.join(root, 'нет-такой-папки'), POSE, fe, CV, J)
        check('нет normal_cam.png → label None, причина', v['label'] is None and 'normal_cam' in v['reason'], str(v))
        v = FV.from_run(run, {'camera': CAM}, fe, CV, J)
        check('нет form_box → label None, причина', v['label'] is None and 'form_box' in v['reason'], str(v))


def test_flag_off_is_main():
    """Флаг ВЫКЛ (по умолчанию и без ключа) — form_verdict_extra пуст: в check.json блока нет, файл как у main; ВКЛ — блок с ярлыком."""
    with tempfile.TemporaryDirectory() as root:
        run = write_run(root)
        fl, fr = J.front_corners(PF, BOX, CAM, CV)[0]
        fe = fe_for(fl, fr, 'r', 700.0, 'ок', 40.0)
        check('нет ключа form_verdict в правилах → {}', CC.form_verdict_extra(run, POSE, {}, CV, fe) == {})
        check('enabled=false → {}', CC.form_verdict_extra(run, POSE, {'form_verdict': {'enabled': False}}, CV, fe) == {})
        on = CC.form_verdict_extra(run, POSE, {'form_verdict': {'enabled': True}}, CV, fe)
        check('enabled=true → блок form_verdict с ярлыком', set(on) == {'form_verdict'} and on['form_verdict']['label'] == 'ок', str(on)[:160])
    r = CC.load_rules()
    fvr = r.get('form_verdict') or {}
    check('camera-check.json: form_verdict.enabled = false по умолчанию', fvr.get('enabled') is False)
    check('camera-check.json: набор порогов = DEFAULTS модуля (пороги живут в json)', set(fvr) == set(FV.DEFAULTS) and all(fvr[k] == v for k, v in FV.DEFAULTS.items()), str(fvr))
    src = open(os.path.join(HERE, 'form_verdict.py'), encoding='utf-8').read() + open(os.path.join(HERE, 'camera_check.py'), encoding='utf-8').read()
    import re
    check('в коде нет номеров товаров (длинных ID)', not re.search(r'\b\d{15,}\b', src))
    json.dumps(r)


if __name__ == '__main__':
    for n, f in sorted(globals().items()):
        if n.startswith('test_') and callable(f):
            f()
    print('итог:', 'OK' if not bad else f'{bad} провал(ов)')
    raise SystemExit(1 if bad else 0)
