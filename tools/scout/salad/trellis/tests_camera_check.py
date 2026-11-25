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
def e2e(sku: str, S: np.ndarray, Aph: np.ndarray, root: str, prep_plate: bool | None = None, edge: dict | None = None) -> dict:
    from PIL import Image
    run = os.path.join(root, sku)
    os.makedirs(os.path.join(run, 'stages', 'render_view0'))
    Image.fromarray((S * 255).astype(np.uint8)).save(os.path.join(run, 'stages', 'render_view0', 'mask.png'))
    iou = float((S & Aph).sum()) / float((S | Aph).sum())
    json.dump({'registration': {'iou': iou, 'P': np.eye(3).tolist(), 'method': 'identity'}}, open(os.path.join(run, 'stage_loss.json'), 'w'))
    json.dump({'picked': {'edge': edge or {'agree': 0.9}}, 'camera': {'az': 0, 'el': 10, 'd': 3, 'f': 2}, 'yaw': 0, 'textured': False}, open(os.path.join(run, 'pose.json'), 'w'))
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
    ne = e2e('noedges', np.roll(A, 1, axis=1), A, root, edge={'agree': -1.0, 'iou_frame': 0.9, 'width_px': 0.0, 'no_edges': True})
    check('e2e «нет кромок» (agree −1,0 + no_edges): edge_agree.value = null, не число; passed не страдает; не «ниже порога»',
          ne['passed'] and ne['metrics']['edge_agree']['value'] is None and ne['metrics']['edge_agree'].get('no_edges') is True and ne['extra']['edge_below_ref'] is False and ne['extra']['no_edges'] is True and 'кромок для сравнения нет' in ne["extra"]["note"], str(ne["metrics"]["edge_agree"]) + " " + ne["extra"]["note"])
    check('e2e с кромками: edge_agree — число, no_edges=false', good['metrics']['edge_agree']['value'] == 0.9 and good['extra']['no_edges'] is False)
check('verdict: edge=None → пометка про отсутствие кромок, ok', CC.verdict(0.95, {'miss': 0, 'extra': 0, 'miss_bottom': 0, 'extra_bottom': 0}, None, RULES)[0] is True)

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

# 9в. shape_mismatch: лучшие старты сходятся в узком коридоре и IoU низкий → форма, а не поза
def ms_of(ious) -> dict:
    return {'ran': True, 'starts': [{'iou': i, 'score': i - 0.2, 'cam': {}} for i in ious]}


ok_, info = CC.shape_mismatch(0.71, ms_of([0.70, 0.705, 0.71, 0.69, 0.70, 0.55, 0.30]), RULES)
check('shape_mismatch: 5 лучших в коридоре, IoU 0,71 < 0,85 → да', ok_ and info['iou_spread'] <= RULES['shape_corridor_eps'], str(info))
ok_, info = CC.shape_mismatch(0.71, ms_of([0.71, 0.65, 0.60, 0.55, 0.50, 0.40]), RULES)
check('shape_mismatch: старты разбросаны (не нашли позу) → нет', not ok_, str(info))
ok_, info = CC.shape_mismatch(0.90, ms_of([0.90, 0.90, 0.89, 0.90, 0.90]), RULES)
check('shape_mismatch: коридор есть, но IoU ≥ порога → нет', not ok_)
check('shape_mismatch: мультистарта не было → нет', CC.shape_mismatch(0.5, None, RULES) == (False, {}) and CC.shape_mismatch(0.5, {'ran': False, 'starts': []}, RULES) == (False, {}))
check('shape_mismatch: стартов меньше shape_top_k → нет', not CC.shape_mismatch(0.5, ms_of([0.5, 0.5]), RULES)[0])
for k in ('shape_top_k', 'shape_corridor_eps', 'bottom_top_iou_min'):
    check(f'rules: {k} — число > 0', isinstance(RULES.get(k), (int, float)) and RULES[k] > 0)

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

# --- триггер мультистарта (22.11): auto — по IoU ИЛИ по провалу низа лучшего кандидата ---
check('ms_trigger: off → None, on → on', PF.ms_trigger('off', {'iou': 0.5}) is None and PF.ms_trigger('on', {'iou': 0.99}) == 'on')
check('ms_trigger: auto, IoU < 0,9 → iou', PF.ms_trigger('auto', {'iou': 0.85, 'miss_bottom': 0.0, 'extra_bottom': 0.0}, RULES) == 'iou')
check('ms_trigger: auto, IoU 0,956, низ 0,81/0,70 (кресло 44846) → bottom', PF.ms_trigger('auto', {'iou': 0.956, 'miss_bottom': 0.808, 'extra_bottom': 0.703}, RULES) == 'bottom')
check('ms_trigger: auto, только extra низа выше порога → bottom', PF.ms_trigger('auto', {'iou': 0.95, 'miss_bottom': 0.1, 'extra_bottom': RULES['extra_bottom_max'] + 0.01}, RULES) == 'bottom')
check('ms_trigger: auto, IoU ≥ 0,9 и низ проходит → None (не гоняем лишний раз)', PF.ms_trigger('auto', {'iou': 0.95, 'miss_bottom': 0.2, 'extra_bottom': 0.3}, RULES) is None)
check('ms_trigger: ровно на пороге низа — не триггер (строго «>», как гейт)', PF.ms_trigger('auto', {'iou': 0.95, 'miss_bottom': RULES['miss_bottom_max'], 'extra_bottom': RULES['extra_bottom_max']}, RULES) is None)

# --- принятие позы мультистарта по низу (22.11, директор): низ проходит И кромки не хуже допуска, иначе остаётся прежняя ---
TOL = RULES['ms_bottom_accept']['edge_agree_tol']
check('ms_accept: допуск кромок — из rules, не из кода', 0 < TOL < 0.2)
ok_, _w = PF.ms_accept({'miss_bottom': 0.171, 'extra_bottom': 0.079}, {'miss_bottom': 0.808, 'extra_bottom': 0.703}, 0.4469, 0.46, RULES)
check('ms_accept: кресло 44846 (низ 0,17/0,08 проходит, кромки 0,46 → 0,447) → новая', ok_ is True, _w)
_a, _b, _c = {'iou': 0.95, 'score': 0.90}, {'iou': 0.94, 'score': 0.85}, {'iou': 0.70, 'score': 0.40}
_pool, _ev = PF.pool_and_evalset([_a, _b, _c], _a, None)
check('pool_and_evalset: без мультистарта (trig=None) не падает, пул по IoU, расчёт = пул', _pool == [_a, _b] and _ev == [_a, _b] and _ev is not _pool, str(_pool))
_m = {'iou': 0.60, 'score': 0.99}
for _trig in ('iou', 'on'):
    _pool, _ev = PF.pool_and_evalset([_m, _a, _b, _c], _a, _trig)
    check(f'pool_and_evalset: trig={_trig} — пул по score, std0 лишней не добавляется', _pool == [_m] and _ev == [_m], str(_pool))
_pool, _ev = PF.pool_and_evalset([_m, _a, _b], _a, 'bottom')
check('pool_and_evalset: trig=bottom, std0 вне пула → считается дополнительно, в пул не входит', _pool == [_m] and _ev == [_m, _a], str(_ev))
_pool, _ev = PF.pool_and_evalset([_a, _m], _a, 'bottom')
check('pool_and_evalset: trig=bottom, std0 уже в пуле → без дубля', _ev == _pool and _ev.count(_a) == 1, str(_ev))
ok_, _w = PF.ms_accept({'miss_bottom': 0.249, 'extra_bottom': 0.253}, {'miss_bottom': 0.411, 'extra_bottom': 0.468}, 0.7342, 0.7514, RULES)
check('ms_accept: комод 3635 (низ 0,25/0,25 проходит, кромки 0,75 → 0,73) → новая', ok_ is True, _w)
ok_, _w = PF.ms_accept({'miss_bottom': 0.481, 'extra_bottom': 0.23}, {'miss_bottom': 0.65, 'extra_bottom': 0.023}, 0.4746, 0.7489, RULES)
check('ms_accept: ТВ-тумба 7736 (низ не прошёл И кромки 0,75 → 0,47) → остаётся старая', ok_ is False, _w)
ok_, _w = PF.ms_accept({'miss_bottom': 0.481, 'extra_bottom': 0.23}, {'miss_bottom': 0.65, 'extra_bottom': 0.023}, 0.80, 0.70, RULES)
check('ms_accept: низ не прошёл, даже если кромки лучше → старая (берём только при низе, который проходит)', ok_ is False and 'низ' in _w, _w)
ok_, _w = PF.ms_accept({'miss_bottom': 0.1, 'extra_bottom': 0.1}, {'miss_bottom': 0.8, 'extra_bottom': 0.7}, 0.70 - TOL - 0.01, 0.70, RULES)
check('ms_accept: низ проходит, но кромки хуже допуска → старая', ok_ is False and 'кромки' in _w, _w)
ok_, _w = PF.ms_accept({'miss_bottom': 0.1, 'extra_bottom': 0.1}, {'miss_bottom': 0.8, 'extra_bottom': 0.7}, 0.70 - TOL + 0.005, 0.70, RULES)
check('ms_accept: кромки хуже, но в допуске → новая', ok_ is True, _w)
ok_, _w = PF.ms_accept({'miss_bottom': 0.1, 'extra_bottom': 0.1}, {'miss_bottom': 0.8, 'extra_bottom': 0.7}, None, 0.7, RULES)
check('ms_accept: кромок нет (None) — сравнивать нечем, решает низ → новая', ok_ is True, _w)

# --- уточнение по кромкам не должно ронять силуэт (стул 12914: 0,86 → 0,72 из-за заглушки «кромок нет») ---
check('edge_term: «кромок нет» → нейтрально 0 (не штраф)', PF.edge_term({'agree': -1.0, 'no_edges': True}) == 0.0)
check('edge_term: обычные кромки как есть', PF.edge_term({'agree': 0.4, 'no_edges': False}) == 0.4 and PF.edge_term({'agree': 0.2}) == 0.2)
check('refine_ok: падение 0,03 — принимаем', PF.refine_ok(0.90, 0.87))
check('refine_ok: падение 0,14 (12914) — отклоняем', not PF.refine_ok(0.8578, 0.7178))
check('refine_ok: рост — принимаем', PF.refine_ok(0.85, 0.86))
# --- camera_refine_v2 (T-20261124-44): флаг в rules/pose-rank.json; выключен — поведение как в main, включён — вес/кадр/порог из правила ---
import inspect  # noqa: E402
import pose_rank as PR_  # noqa: E402
_v2 = PR_.rules().get('camera_refine_v2') or {}
check('camera_refine_v2: в правилах есть, по умолчанию ВЫКЛ', _v2.get('enabled') is False and 'w_iou' in _v2 and 'n' in _v2 and 'tri_drop' in _v2, str(_v2))
check('флаг выкл = старое поведение: refine_v2_rules() → None, W_IOU=2 и порог 0,05 по вершинам в коде как в main', PF.refine_v2_rules() is None and PF.W_IOU == 2.0 and PF.REFINE_IOU_DROP == 0.05)
check('флаг выкл: refine_by_edges по умолчанию берёт W_IOU модуля (w_iou=None)', inspect.signature(PF.refine_by_edges).parameters['w_iou'].default is None)
_rules0 = PR_.rules
PR_.rules = lambda path=None: {**_rules0(), 'camera_refine_v2': {**_v2, 'enabled': True}}
try:
    _on = PF.refine_v2_rules()
finally:
    PR_.rules = _rules0
check('флаг вкл: refine_v2_rules() отдаёт w_iou=12, n=512, tri_drop=0,01 из правила', _on is not None and _on['w_iou'] == 12.0 and _on['n'] == 512 and _on['tri_drop'] == 0.01, str(_on))
check('флаг вкл: refine_ok_tri — падение IoU треугольников 0,009 принимаем, 0,0375 (13994…) отклоняем, рост принимаем', PF.refine_ok_tri(0.9579, 0.9489, 0.01) and not PF.refine_ok_tri(0.9591, 0.9216, 0.01) and PF.refine_ok_tri(0.90, 0.91, 0.01))
ms_r = {'ran': True, 'starts': [{'score': 0.76 - i * 0.01, 'iou': 0.50, 'iou_sil': 0.85 - i * 0.005} for i in range(5)]}
check('shape_mismatch: коридор по IoU ДО уточнения (iou_sil), а не после', CC.shape_mismatch(0.80, ms_r, RULES)[1]['iou_spread'] <= 0.03, str(CC.shape_mismatch(0.80, ms_r, RULES)[1]))

# --- surf_pick (T-173): из двух поз (боевая, surf) — с большим IoU по треугольникам; ничья ≤ SURF_TIE и пустые значения → боевая; по умолчанию выкл. ---
import inspect  # noqa: E402


def pk(tri):
    return {'edge': {'iou_frame': tri}}


r_321 = PF.choose_pose(pk(0.9632), pk(0.9106))      # серый комод на ножках: surf уводит позу на фронт и роняет форму
check('choose_pose: surf хуже боевой (комод, −0,053) → боевая', r_321['chosen'] == 'base' and r_321['gap'] == -0.0526, str(r_321))
r_tab = PF.choose_pose(pk(0.8099), pk(0.8582))      # столик: боевая с длинной ножкой, surf совпал
check('choose_pose: surf лучше боевой (столик, +0,048) → surf', r_tab['chosen'] == 'surf' and r_tab['gap'] == 0.0483, str(r_tab))
check('choose_pose: ничья в пределах SURF_TIE → боевая', PF.choose_pose(pk(0.900), pk(0.904))['chosen'] == 'base' and PF.choose_pose(pk(0.900), pk(0.9051))['chosen'] == 'surf')
check('choose_pose: нет iou_frame у любой позы → боевая', PF.choose_pose({'edge': {}}, pk(0.9))['chosen'] == 'base' and PF.choose_pose(pk(0.9), {})['chosen'] == 'base' and PF.choose_pose({}, {})['gap'] is None)
check('fit_pose: surf_pick по умолчанию выключен', inspect.signature(PF.fit_pose).parameters['surf_pick'].default is False)
cube_V = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)], float)
cube_F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
cube = {'V': cube_V, 'F': cube_F}
S_pts = PF._surf_points(cube, n_pts=20000)
cam_c = {'az': 30.0, 'el': 15.0, 'd': 4.0, 'f': 3.0, 'cx': 0.5, 'cy': 0.5}
check('surf_points: вершины на месте + заданное число точек граней', len(S_pts) == len(cube_V) + 20000 and np.allclose(S_pts[:len(cube_V)], cube_V))
check('surf_points: точки внутри габарита формы', bool((np.abs(S_pts) <= 0.5 + 1e-9).all()))
m_v, m_s = PF.splat_mask(cube_V, cam_c, 128), PF.splat_mask(S_pts, cam_c, 128)
check('surf_points: маска по поверхности заполнена, по вершинам дырявая (плоские грани)', m_s.sum() > 10 * m_v.sum(), f'{int(m_s.sum())} vs {int(m_v.sum())} px')
check('surf_points: воспроизводимо (seed)', np.array_equal(PF._surf_points(cube, 500), PF._surf_points(cube, 500)))


# 10. тонкий предмет (T-188/2): площадная мерка проваливается на 1–2 px сдвига палки, мерка по контуру — нет
check('rules: thin — числа из файла', all(isinstance(RULES['thin'].get(k), (int, float)) and RULES['thin'][k] > 0 for k in ('half_frac', 'share_min', 'tau_frac', 'precision_min', 'recall_min')) and RULES['thin']['enabled'] is True)


def lamp() -> np.ndarray:
    m = rect(20, 180, 100, 103)                                          # стойка 3 px
    m |= rect(20, 23, 100, 150)                                          # рука
    m |= rect(176, 180, 80, 124)                                         # плита
    return m


A_l = lamp()
tm0 = CC.thin_metrics(A_l, A_l, RULES)
check('thin: торшер — тонкий (доля ≥ порога), форма == фото: precision=recall=1, passed', tm0['eligible'] and tm0['passed'] and tm0['precision'] == 1.0 and tm0['recall'] == 1.0, str(tm0))
S_l = np.roll(A_l, 1, axis=1)
iou_l = float((S_l & A_l).sum()) / float((S_l | A_l).sum())
tm1 = CC.thin_metrics(S_l, A_l, RULES)
check('thin: сдвиг на 1 px — IoU площади ниже порога, контур годен', iou_l < RULES['iou_min'] and tm1['passed'], f'iou {iou_l:.3f} {tm1}')
tm2 = CC.thin_metrics(np.roll(A_l, 12, axis=1), A_l, RULES)
check('thin: сдвиг на 12 px (≫ допуска) — контур провален', tm2['eligible'] and not tm2['passed'], str(tm2))
box = rect(40, 160, 40, 160)
tm3 = CC.thin_metrics(np.roll(box, 25, axis=1), box, RULES)
check('thin: компактный предмет — не тонкий (eligible=false), путь не включается', not tm3['eligible'], str(tm3))
tm4 = CC.thin_metrics(np.zeros_like(A_l), A_l, RULES)
check('thin: пустая форма — не годен, без исключения', not tm4['passed'] and not tm4['eligible'])
with tempfile.TemporaryDirectory() as root:
    r1 = e2e('lamp1', S_l, A_l, root)
    check('e2e торшер сдвиг 1 px: passed=true по контуру, thin_rescue, причина названа', r1['passed'] and r1['extra']['thin_rescue'] is True and r1['extra']['thin']['eligible'] and not r1['extra']['shape_mismatch'] and 'по контуру' in r1["extra"]["note"], r1["extra"]["note"])
    r2 = e2e('lamp2', np.roll(A_l, 12, axis=1), A_l, root)
    check('e2e торшер сдвиг 12 px: провал, не спасён', not r2['passed'] and r2['extra']['thin_rescue'] is False, r2['reason'])
    r3 = e2e('box', np.roll(box, 25, axis=1), box, root)
    check('e2e компактный с плохим IoU: провал, не спасён', not r3['passed'] and r3['extra']['thin_rescue'] is False and r3['extra']['thin']['eligible'] is False)
    r4 = e2e('lamp3', S_l, A_l, root, prep_plate=True)
    check('e2e торшер, но 02-prep plate_found без среза (unreliable): провал остаётся', not r4['passed'] and r4['extra']['thin_rescue'] is False and r4['extra']['unreliable'] is True, r4['reason'])
    r5 = e2e('good2', np.roll(A, 1, axis=1), A, root)
    check('e2e годная по площади: путь не нужен, thin_rescue=false (спасение не отнимает и не подменяет)', r5['passed'] and r5['extra']['thin_rescue'] is False)
    ea5 = r5['extra'].get('edge_angle') or {}
    check('e2e: extra.edge_angle записана (T-18), passed 04 не зависит от неё (enforce=false)', 'measured' in ea5 and ea5.get('enforce') in (False, None) and r5['passed'], str(ea5)[:200])
    vc5 = r5['extra'].get('vertical_convergence') or {}
    check('e2e: extra.vertical_convergence записана (T-18 шаг 3): измерена или «не измерено» с причиной; passed 04 не зависит', 'measured' in vc5 and (vc5['measured'] or vc5.get('reason')) and r5['passed'], str(vc5)[:200])
    rules_off = json.loads(json.dumps(RULES))
    rules_off['thin']['enabled'] = False
    _lr = CC.load_rules
    CC.load_rules = lambda path=CC.RULES_PATH: rules_off
    try:
        r6 = e2e('lamp4', S_l, A_l, root)
    finally:
        CC.load_rules = _lr
    check('e2e enabled=false в правилах: торшер снова брак (путь выключается правилом)', not r6['passed'] and r6['extra']['thin_rescue'] is False and r6['extra']['thin'] is None, r6['reason'])

print('all ok' if not bad else f'FAILED: {bad}')
sys.exit(1 if bad else 0)
