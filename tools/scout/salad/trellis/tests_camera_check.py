#!/usr/bin/env python3
"""Тесты `camera_check.py` (T-20261121-112/3): гейт этапа 04-camera — passed = IoU И miss («фото не закрыто формой») И extra («форма вне фото»), всего кадра и нижней полосы;
02-prep plate_found без среза → камера unreliable. Синтетика: «комод» (форма-трапеция без ножек, IoU держится ≥0,85), «хорошая» форма, «диван с плитой». Нужны numpy, PIL, cv2.

  python3 tools/scout/salad/trellis/tests_camera_check.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import numpy as np  # noqa: E402
import camera_check as CC  # noqa: E402
import paint_stage as PS  # noqa: E402

bad = 0


def check(name: str, ok: bool, extra: str = '') -> None:
    global bad
    if not ok:
        bad += 1
    print(('ok   ' if ok else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))


H = W = 200
RULES = CC.load_rules()


def rect(y0, y1, x0, x1) -> np.ndarray:
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = True
    return m


def dresser_photo() -> np.ndarray:
    """Корпус 40..130 + четыре тонкие ножки 130..170."""
    m = rect(40, 130, 30, 170)
    for x in (34, 70, 120, 160):
        m |= rect(130, 170, x, x + 6)
    return m


# 0. правила целы
for k in ('iou_min', 'strip_frac', 'miss_max', 'extra_max', 'miss_bottom_max', 'extra_bottom_max', 'edge_ref'):
    check(f'rules: {k} — число > 0', isinstance(RULES.get(k), (int, float)) and RULES[k] > 0)

# 1. форма == фото: все доли 0
A = dresser_photo()
sh = CC.silhouette_shares(A, A, RULES['strip_frac'])
check('идеальная форма: miss=extra=0, внизу тоже', sh['miss'] == 0 and sh['extra'] == 0 and sh['miss_bottom'] == 0 and sh['extra_bottom'] == 0, str(sh))
ok, why = CC.verdict(1.0, sh, 0.9, RULES)
check('идеальная форма: passed', ok, why)

# 2. «комод»: форма без ножек + плита слева-снизу, IoU по кадру остаётся высоким, нижняя полоса — нет
S_body = rect(40, 130, 30, 170)
iou_body = float((S_body & A).sum()) / float((S_body | A).sum())
sh = CC.silhouette_shares(S_body, A, RULES['strip_frac'])
ok, why = CC.verdict(max(iou_body, 0.86), sh, 0.2, RULES)
check('комод без ножек: IoU ≥ порога, но miss внизу → passed=false', iou_body > 0.6 and not ok and sh['miss_bottom'] > RULES['miss_bottom_max'], f"iou={iou_body:.3f} {why}")

# 3. форма сильно шире фото (плита): extra растёт
S_plate = A | rect(130, 175, 5, 195)
sh = CC.silhouette_shares(S_plate, A, RULES['strip_frac'])
ok, why = CC.verdict(0.9, sh, 0.5, RULES)
check('плита шире фото: extra внизу высокий → passed=false', not ok and sh['extra_bottom'] > RULES['extra_bottom_max'], why)

# 4. форма чуть смещена (пара пикселей) — проходит
S_shift = np.roll(A, 1, axis=1)
sh = CC.silhouette_shares(S_shift, A, RULES['strip_frac'])
ok, why = CC.verdict(0.95, sh, 0.5, RULES)
check('сдвиг на 1 пиксель: passed', ok, why)

# 5. пустые маски не прячут беду
sh = CC.silhouette_shares(np.zeros((H, W), bool), A, RULES['strip_frac'])
check('формы нет, фото есть: miss=1, внизу miss=1', sh['miss'] == 1.0 and sh['miss_bottom'] == 1.0)
sh = CC.silhouette_shares(np.zeros((H, W), bool), np.zeros((H, W), bool), RULES['strip_frac'])
check('обе пусто: нули, strip_rows=None', sh['miss'] == 0 and sh['strip_rows'] is None)

# 6. нижняя полоса — 15 % высоты объединения от низа: фото строки 40..169 (h=130) → 20 строк
sh = CC.silhouette_shares(A, A, 0.15)
check('полоса: 20 строк от низа (150..169)', sh['strip_rows'] == [150, 169], str(sh['strip_rows']))

# 7. plate_found без среза → unreliable; со срезом — нет; нет 02-prep — не флажим
with tempfile.TemporaryDirectory() as root:
    for sku, plate, cut in (('a', True, False), ('b', True, True), ('c', False, False)):
        d = PS.stage_dir(root, sku, '02-prep')
        PS.write_check(d, '02-prep', sku, passed=True, metrics={'plate_found': {'value': plate}}, outputs=['cut.glb'] if cut else [], report={'written': cut})
    check('plate_found=true, среза нет → unreliable', CC.prep_plate_unreliable(root, 'a')[0])
    check('plate_found=true, срез есть → ок', not CC.prep_plate_unreliable(root, 'b')[0])
    check('plate_found=false → ок', not CC.prep_plate_unreliable(root, 'c')[0])
    check('нет 02-prep → не флажим', CC.prep_plate_unreliable(root, 'zz') == (False, ''))
    ok, why = CC.verdict(0.99, CC.silhouette_shares(A, A, 0.15), 0.9, RULES, CC.prep_plate_unreliable(root, 'a')[1])
    check('unreliable ломает passed даже при идеальной форме', not ok and 'plate_found' in why, why)

# 8. сквозной прогон main() на синтетической папке прогона: check.json + кадр
def e2e(sku: str, S: np.ndarray, Aph: np.ndarray, root: str, prep_plate: bool | None = None) -> dict:
    from PIL import Image
    run = os.path.join(root, sku)
    os.makedirs(os.path.join(run, 'stages', 'render_view0'))
    Image.fromarray((S * 255).astype(np.uint8)).save(os.path.join(run, 'stages', 'render_view0', 'mask.png'))
    iou = float((S & Aph).sum()) / float((S | Aph).sum())
    json.dump({'registration': {'iou': iou, 'P': np.eye(3).tolist(), 'method': 'identity'}}, open(os.path.join(run, 'stage_loss.json'), 'w'))
    json.dump({'picked': {'edge': {'agree': 0.9}}, 'camera': {'az': 0, 'el': 10, 'd': 3, 'f': 2}, 'yaw': 0, 'textured': False}, open(os.path.join(run, 'pose.json'), 'w'))
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[Aph] = (200, 120, 60, 255)
    photo = os.path.join(root, sku + '.rgba.png')
    Image.fromarray(rgba, 'RGBA').save(photo)
    if prep_plate is not None:
        PS.write_check(PS.stage_dir(root, sku, '02-prep'), '02-prep', sku, passed=True, metrics={'plate_found': {'value': prep_plate}}, outputs=[], report={'written': False})
    old = sys.argv
    sys.argv = ['camera_check.py', '--run', run, '--photo', photo, '--yaw', '0']
    try:
        CC.main()
    finally:
        sys.argv = old
    return json.load(open(os.path.join(root, sku, '04-camera', 'check.json'), encoding='utf-8'))


with tempfile.TemporaryDirectory() as root:
    good = e2e('good', np.roll(A, 1, axis=1), A, root)
    check('e2e хорошая: passed, метрики miss/extra/низ в check.json', good['passed'] and {'miss', 'extra', 'miss_bottom', 'extra_bottom'} <= set(good['metrics']), good['reason'])
    bad_c = e2e('komod', S_body, A, root)
    check('e2e комод без ножек: passed=false, причина про низ', not bad_c['passed'] and 'внизу' in bad_c['reason'], bad_c['reason'])
    unrel = e2e('plate', np.roll(A, 1, axis=1), A, root, prep_plate=True)
    check('e2e plate_found без среза: passed=false, unreliable=true', not unrel['passed'] and unrel['extra']['unreliable'] is True and 'plate_found' in unrel['extra']['unreliable_reason'], unrel['reason'])
    check('e2e: кадр frame.png записан', os.path.exists(os.path.join(root, 'good', '04-camera', 'frame.png')))

# 9. пометка «низ: маска фото грубая»: бледные тонкие ножки на белом фоне — да; тёмные ножки / толстый низ — нет
rgb_pale = np.full((H, W, 3), 255, np.uint8)
rgb_pale[A] = (222, 214, 200)                                           # бледное на белом: контраст ≈ 0,1
sr = CC.silhouette_shares(A, A, 0.15)['strip_rows']
q = CC.bottom_mask_quality(rgb_pale, A, sr)
check('маска грубая: тонкие бледные ножки → thin<0,3, contrast<0,25', q['thin_share'] < RULES['coarse_thin_max'] and q['contrast'] < RULES['coarse_contrast_max'], str(q))
rgb_dark = np.full((H, W, 3), 255, np.uint8)
rgb_dark[A] = (40, 30, 25)
q = CC.bottom_mask_quality(rgb_dark, A, sr)
check('маска не грубая: тёмные ножки → контраст высокий', q['contrast'] > RULES['coarse_contrast_max'], str(q))
q = CC.bottom_mask_quality(rgb_dark, A, None)
check('нет полосы → None', q['thin_share'] is None)

# 9б. bottom_shape_mismatch: корпус лёг, ножки формы другие, маска не грубая → причина; грубая маска или плохой корпус → нет
def chair_photo() -> np.ndarray:
    m = rect(40, 130, 30, 170)
    for x in (36, 160):                                                  # на фото две толстые боковые ножки
        m |= rect(130, 170, x, x + 14)
    return m


Ach = chair_photo()
S_legs4 = rect(40, 130, 30, 170)
for x in (36, 80, 112, 160):                                             # у формы четыре ножки, две из них там, где на фото пусто
    S_legs4 |= rect(130, 175, x, x + 14)
sh = CC.silhouette_shares(S_legs4, Ach, RULES['strip_frac'])
check('iou_top считается (корпус совпал, верх ≥ 0,9)', sh['iou_top'] is not None and sh['iou_top'] > 0.9, str(sh['iou_top']))
check('кресло: extra внизу выше порога', sh['extra_bottom'] > RULES['extra_bottom_max'], str(sh['extra_bottom']))
check('bottom_shape_mismatch: корпус лёг, ножки не те, маска не грубая → да', CC.bottom_shape_mismatch(sh, False, RULES))
check('bottom_shape_mismatch: маска грубая → нет', not CC.bottom_shape_mismatch(sh, True, RULES))
check('bottom_shape_mismatch: идеальные ножки → нет', not CC.bottom_shape_mismatch(CC.silhouette_shares(Ach, Ach, RULES['strip_frac']), False, RULES))
S_bad_top = np.roll(S_legs4, 40, axis=1)                                 # корпус сдвинут — поза плохая, это не про ножки
sh2 = CC.silhouette_shares(S_bad_top, Ach, RULES['strip_frac'])
check('bottom_shape_mismatch: корпус не лёг (IoU верха < порога) → нет', not CC.bottom_shape_mismatch(sh2, False, RULES), str(sh2['iou_top']))
with tempfile.TemporaryDirectory() as root:
    chair = e2e('chair', S_legs4, Ach, root)
    check('e2e кресло: passed=false, bottom_shape_mismatch=true, причина названа', not chair['passed'] and chair['extra']['bottom_shape_mismatch'] is True and 'bottom_shape_mismatch' in chair['reason'], chair['reason'][:120])
    check('e2e: в check.json есть iou_top и bottom_mask', chair['extra']['iou_top'] is not None and 'bottom_mask' in chair['extra'])

# 10. мультистарт pose_fit: стол с четырьмя ножками, камера на 40°/15°; от стартов MS_AZ × MS_EL находит позу с IoU ≥ 0,9, и оценка лучшего старта выше худшего
import pose_fit as PF  # noqa: E402
rng = np.random.default_rng(1)


def table_cloud() -> np.ndarray:
    top = np.c_[rng.uniform(-.5, .5, 5000), np.full(5000, .5) + rng.uniform(0, .04, 5000), rng.uniform(-.35, .35, 5000)]
    legs = [np.c_[np.full(800, x) + rng.uniform(-.02, .02, 800), rng.uniform(-.5, .5, 800), np.full(800, z) + rng.uniform(-.02, .02, 800)] for x, z in ((-.42, -.28), (.42, -.28), (-.42, .28), (.42, .28))]
    return np.vstack([top] + legs)


Pt = table_cloud()
cam_true = {'az': 40.0, 'el': 15.0, 'd': 4.0, 'f': 3.0, 'cx': 0.5, 'cy': 0.5}
Mt = PF.splat_mask(Pt, cam_true, 128)
pick, allr = PF.multistart_fit(Pt, Mt, 128, topk=2, log=lambda *_: None)
check('мультистарт: все старты записаны с числами', len(allr) == len(PF.MS_AZ) * len(PF.MS_EL) and all({'iou', 'miss', 'extra', 'score', 'start_az', 'cam'} <= set(r) for r in allr))
check('мультистарт: лучший IoU ≥ 0,85 (поза с точностью до симметрии стола)', pick[0]['iou'] >= 0.85, f"{pick[0]['iou']}")
check('мультистарт: оценки отсортированы, лучший ≥ худшего', allr[0]['score'] >= allr[-1]['score'] and pick[0]['score'] == allr[0]['score'])
sc_bad = PF.pose_score(PF.splat_mask(Pt, {**cam_true, 'az': 40 + 90}, 128), Mt)
sc_ok = PF.pose_score(Mt, Mt)
check('оценка позы: точная > повёрнутая на 90°', sc_ok['score'] > sc_bad['score'], f"{sc_ok['score']} vs {sc_bad['score']}")

print('all ok' if not bad else f'FAILED: {bad}')
sys.exit(1 if bad else 0)
