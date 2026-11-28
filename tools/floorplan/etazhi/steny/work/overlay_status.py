#!/usr/bin/env python3
"""T-98/18 · Fable 17: статус наложения листа и столбцы «в тени» для run_sb100 (р.2). $0, без сети, ничего не правит.

  из кода:   from overlay_status import measure, status_of, column
             m = measure(plan_path, sheet_path, out_dir)          # запускает vetka_fit (CORRECT_V2=1 SOFT_INK=1 — как «до» в s0) + считает зону/слои
             r = column(m)                                         # {'overlay_status','на_линии','покрыто','покрыто_в_зоне','лишнее_м','пропущено_м','куски_соседа','пороги'}
  из строки: python -I overlay_status.py --plan plan.json --sheet лист.jpg --out папка [--cfg overlay_status_config.json]   → JSON в stdout, файлы vetka_fit в --out

Статусы: «легло» · «частично» · «не легло» · «не проверено» (чернил не найдено / привязка не сошлась). Звонки наложения — ТОЛЬКО с «легло»; «не проверено» браком не считается, но доля его пишется отдельно.
Пороги — overlay_status_config.json (с полем _why). Столбцы лишнее_м / пропущено_м / куски_соседа — ТОЛЬКО в тени (ничего не правят и не звонят).
  лишнее_м    — чуткий слой: длина стен ответа, под которыми нет НИ сильных, НИ слабых чернил (класс «выдуманная» после SOFT_INK), в метрах
  пропущено_м — строгий слой: чернила В ЗОНЕ квартиры (комнаты ответа +запас), не покрытые стенами, куски длиннее strict_min_cm и вытянутые, в метрах (приближённо: диагональ рамки куска)
  стена_без_комнаты — справка: стены без комнат вдоль; внешняя и >0,3 м от комнат → «пропущена комната?», остальное → «перегородка/выступ» (куски соседа на 10 кадрах глазом: 0 из 10 — правило «сосед» снято); только при «легло», не звонить
  вход        — 'как есть' | '4c' | 'как есть (4c не лучше)' | '4c недоступен' (бледный лист: если как есть не «легло», повтор с очисткой линий 4c из floorplan/input_step.py; ответ не меняет, только вход проверки наложения).
                «4c недоступен» не молчаливый: поле в столбце + overlay_status.counters(cols)['4c_недоступен'] в итог прогона. В снимке 4c берётся ТОЛЬКО из floorplan/ рядом (копия + FLOORPLAN-SHA.txt)
"""
import argparse
import collections
import csv
import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np

V = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, V)
CFG_PATH = os.path.join(V, 'overlay_status_config.json')
PY = os.environ.get('OVERLAY_PY', sys.executable)
UNIT = {'cm': 1.0, 'm': 100.0, 'mm': 0.1}


def load_cfg(path=None):
    return json.load(open(path or CFG_PATH, encoding='utf-8'))


def _run_fit(plan_path, sheet_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    env = dict(os.environ, CORRECT_V2='1', SOFT_INK='1', OMP_NUM_THREADS='1')
    env.pop('INK_PALE', None)
    env.pop('KEEP_FRAME', None)
    r = subprocess.run([PY, '-I', os.path.join(V, 'vetka_fit.py'), '--plan', plan_path, '--sheet', sheet_path, '--out', out_dir], env=env, capture_output=True, text=True, timeout=900)
    return r.returncode, r.stderr[-300:]


def _pale(sheet_path, cfg):
    import vetka_fit as vf
    return float(np.percentile(vf.load_gray(sheet_path), 0.5)) > cfg.get('pale_p05_min', 150)


COUNTERS = collections.Counter()   # «вход: …» за время работы процесса (для итога прогона); то же по готовым столбцам — counters(cols)


def floorplan_dir():
    """где лежит input_step.py (4c). Порядок: env REMLAB_FLOORPLAN (если задан — ТОЛЬКО он, без запасных путей) → папка floorplan/ рядом с этим файлом (в снимке — копия из репозитория,
    суббота берёт только её) → живой репозиторий (только вне снимка, т.е. если этот файл не лежит в versii/)."""
    e = os.environ.get('REMLAB_FLOORPLAN')
    if e:
        return e
    near = os.path.join(V, 'floorplan')
    if os.path.isdir(near):
        return near
    if os.sep + 'versii' + os.sep not in V + os.sep:
        return '/home/pakar/igor/remlab/tools/floorplan'
    return near


def _make_4c(sheet_path, out_png):
    """вход 4c: input_step.run только «lines» (FP_CLEAN_LINES). Нет папки/файла/модуля — ИСКЛЮЧЕНИЕ (молчаливого отката нет: measure пишет «вход: 4c недоступен»)"""
    d = floorplan_dir()
    if not os.path.exists(os.path.join(d, 'input_step.py')):
        raise FileNotFoundError(f'нет {d}/input_step.py')
    os.environ['FP_CLEAN_LINES'] = '0'
    if d not in sys.path:
        sys.path.insert(0, d)
    import input_step
    from PIL import Image
    r = input_step.run(Image.open(sheet_path).convert('RGB'), {'rect': False, 'bg': False, 'grid': False, 'lines': True, 'layers': False, 'cut': False})
    r['sheet'].save(out_png)
    return out_png


def measure(plan_path, sheet_path, out_dir, cfg=None):
    """бледный лист (0,5 %-перцентиль яркости > pale_p05_min) и как есть не «легло» → повтор с входом 4c; берём лучший по «на_линии»+«покрыто».
    Поле «вход»: 'как есть' | 'как есть (4c не лучше)' | '4c' | '4c недоступен' (+ вход_4c_ошибка). Каждое значение — в COUNTERS."""
    cfg = cfg or load_cfg()
    m = _measure_once(plan_path, sheet_path, out_dir, cfg)
    m['вход'] = 'как есть'
    if cfg.get('pale_4c', False) and status_of(m, cfg) != 'легло' and _pale(sheet_path, cfg):
        try:
            c4 = _make_4c(sheet_path, os.path.join(out_dir, 'sheet-4c.png'))
            m4 = _measure_once(plan_path, c4, out_dir + '-4c', cfg)
        except Exception as e:   # noqa: BLE001  (не молчим: статус остаётся по «как есть», но вход помечен и посчитан)
            m['вход'] = '4c недоступен'
            m['вход_4c_ошибка'] = f'{type(e).__name__}: {e}'[:200]
            m4 = None
        if m4 is not None:
            key = lambda x: (0, 0) if 'не_проверено' in x else (x['на_линии'], x['покрыто'])   # noqa: E731
            if key(m4) > key(m):
                m4['вход'] = '4c'
                m4['sheet_orig'] = sheet_path
                m = m4
            else:
                m['вход'] = 'как есть (4c не лучше)'
    COUNTERS['вход: ' + m['вход']] += 1
    return m


def counters(cols):
    """итог по списку столбцов column(...) для run_sb100: сколько каких статусов и входов, доля «не проверено», счётчик «4c недоступен» (его >0 — в итог прогона строкой)"""
    n = len(cols)
    st = collections.Counter(c['overlay_status'] for c in cols)
    vh = collections.Counter(c.get('вход', 'как есть') for c in cols)
    return {'пар': n, 'статусы': dict(st), 'входы': dict(vh), '4c_недоступен': vh.get('4c недоступен', 0), 'доля_не_проверено': round(st.get('не проверено', 0) / max(n, 1), 3)}


def _measure_once(plan_path, sheet_path, out_dir, cfg):
    rc, err = _run_fit(plan_path, sheet_path, out_dir)
    m = {'plan': plan_path, 'sheet': sheet_path, 'rc': rc}
    if rc != 0 or not os.path.exists(out_dir + '/ink.json'):
        m['не_проверено'] = 'сбой привязки: ' + err
        return m
    ik = json.load(open(out_dir + '/ink.json', encoding='utf-8'))
    fit = json.load(open(out_dir + '/fit.json', encoding='utf-8'))
    if ik.get('не_проверено'):
        m['не_проверено'] = ik.get('причина', 'чернил не найдено')
        return m
    rows = list(csv.DictReader(open(out_dir + '/walls.csv', encoding='utf-8')))
    s = float(fit['scale_px_per_unit_cm'])
    m.update({'на_линии': ik['доля_длины_стен_на_чернилах'], 'покрыто': ik['покрыто_стенами_доля'], 'пропущено_доля': ik['пропущено_доля'],
              'доля_точек_3px': fit['inliers_share_le_3px'], 'масштаб': s, 'стен': ik['стен'], 'выдуманных': ik['выдуманных'], 'слабых_линий': ik['слабых_линий'],
              'лишнее_м': round(sum(float(r['длина_px']) for r in rows if r['класс'] == 'выдуманная') / s / 100.0, 2)})
    m.update(_zone(plan_path, sheet_path, fit, s, cfg))
    return m


def _zone(plan_path, sheet_path, fit, s, cfg):
    import vetka_fit as vf
    plan = json.load(open(plan_path, encoding='utf-8'))
    g = vf.load_gray(sheet_path)
    H, W = g.shape
    ink = vf.ink_mask(g)
    tx, ty = fit['shift_px']
    rot, rc = fit.get('rot_deg') or 0.0, fit.get('rot_center_cm')

    def to_px(P):
        P = np.asarray(P, float)
        if rot and rc:
            P = vf.rot_about(P, rot, rc)
        return P * s + [tx, ty]
    k = UNIT.get(plan.get('units', 'cm'), 1.0)
    zone = np.zeros((H, W), np.uint8)
    cov = np.zeros((H, W), np.uint8)
    for lv in plan['levels']:
        for r in lv.get('rooms', []):
            pg = to_px([[x * k, y * k] for x, y in r['polygon']])
            cv2.fillPoly(zone, [np.round(pg).astype(np.int32)], 1)
        for w in lv.get('walls', []):
            th = float(w['thickness']) * k if w.get('thickness') else {'exterior': 30.0, 'partition': 8.0}.get(w.get('kind'), 12.0)
            pa, pb = to_px([[w['from'][0] * k, w['from'][1] * k], [w['to'][0] * k, w['to'][1] * k]])
            band = 0.5 * th * s + vf.TOL_MIN
            cv2.line(cov, tuple(np.round(pa).astype(int)), tuple(np.round(pb).astype(int)), 1, int(2 * band + 1))
    mg = int(round(cfg['zone_margin_cm'] * s))
    if mg > 0:
        zone = cv2.dilate(zone, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * mg + 1, 2 * mg + 1)))
    zone, cov = zone.astype(bool), cov.astype(bool)
    if not zone.any():                                    # у ответа нет комнат — зоны нет: «покрыто в зоне» = покрыто по листу, куски соседа не определены
        return {'нет_комнат': True, 'чернил_в_зоне_доля': None, 'покрыто_в_зоне': round(float((ink & cov).sum() / max(int(ink.sum()), 1)), 3), 'пропущено_м': None}
    iz = ink & zone
    out = {'чернил_в_зоне_доля': round(float(iz.sum() / max(int(ink.sum()), 1)), 3)}
    out['покрыто_в_зоне'] = round(float((iz & cov).sum() / max(int(iz.sum()), 1)), 3)
    miss = cv2.morphologyEx((iz & ~cov).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(miss, 8)
    tot = 0.0
    for i in range(1, n):
        w_, h_ = int(st[i, cv2.CC_STAT_WIDTH]), int(st[i, cv2.CC_STAT_HEIGHT])
        ln = math.hypot(w_, h_)
        area = int(st[i, cv2.CC_STAT_AREA])
        if ln >= cfg['strict_min_cm'] * s and area / max(ln, 1.0) <= cfg['strict_max_thick_cm'] * s:      # длинный и не «пятно» (подпись/мебель — короткие или плотные)
            tot += ln / s / 100.0
    out['пропущено_м'] = round(tot, 2)
    return out


def _no_room_walls(plan_path):
    """стены, не граничащие ни с одной комнатой ответа (oblomki_feat.features: доля контура комнаты вдоль стены ≥0,30)"""
    try:
        from oblomki_feat import features
        plan = json.load(open(plan_path, encoding='utf-8'))
        if not any(lv.get('rooms') for lv in plan['levels']):
            return None                                   # комнат нет — правило «стена без комнат» неприменимо (иначе все стены «соседи»)
        return [{'стена': f['id'], 'длина_м': f['L_m'], 'вид': f['kind'], 'до_комнаты_м': f['room_dist_m'], 'свободных_концов': f['free_ends']} for f in features(plan) if not f['rooms']]
    except Exception as e:   # noqa: BLE001  (нет shapely и т.п.: столбец пустой, статус не страдает)
        return None


def _no_room_hint(plan_path, cfg):
    """справка в тени (директор 26.11, глаз 10 кадров: соседей 0 из 10): стена без комнаты вдоль. Внешняя и дальше no_room_far_m от комнат → «пропущена комната?» (лоджия на чернилах, комнаты в ответе нет);
    остальные (короткие внутренние со свободными концами, стенки-выступы) → «перегородка/выступ»: справка, не звонить. None — у ответа нет комнат вообще."""
    ws = _no_room_walls(plan_path)
    if ws is None:
        return None
    far = cfg.get('no_room_far_m', 0.3)
    for w in ws:
        w['подсказка'] = 'пропущена комната?' if (w['вид'] == 'exterior' and w['до_комнаты_м'] > far) else 'перегородка/выступ'
    return ws


def status_of(m, cfg=None, zone=False):
    """zone=False — по порогам директора (на_линии ≥ on_line_min И покрыто ≥ covered_min); zone=True — то же, но «покрыто» считается внутри зоны квартиры"""
    cfg = cfg or load_cfg()
    if 'не_проверено' in m:
        return 'не проверено'
    a = m['на_линии']
    b = m['покрыто_в_зоне'] if zone else m['покрыто']
    if a >= (cfg['on_line_zone_min'] if zone else cfg['on_line_min']) and b >= (cfg['covered_zone_min'] if zone else cfg['covered_min']):
        return 'легло'
    if a >= cfg['part_on_line_min'] and b >= cfg['part_covered_min']:
        return 'частично'
    return 'не легло'


def column(m, cfg=None):
    """что отдаём run_sb100: статус + столбцы в тени. Куски соседа — только при «легло»."""
    cfg = cfg or load_cfg()
    st = status_of(m, cfg, zone=cfg.get('use_zone_for_status', False))
    by_zone = False
    if st in ('частично', 'не легло') and cfg.get('zone_rescue') and status_of(m, cfg, zone=True) == 'легло':     # соседи на листе занижают «покрыто» (9583744): ложимся по зоне квартиры, на_линии при этом ≥ on_line_zone_min
        st, by_zone = 'легло', True
    c = {'overlay_status': st, 'легло_по_зоне': by_zone, 'пороги': {k: cfg[k] for k in ('on_line_min', 'covered_min', 'on_line_zone_min', 'covered_zone_min')}}
    if st == 'не проверено':
        c.update({'причина': m.get('не_проверено'), 'вход': m.get('вход', 'как есть')})
        if m.get('вход_4c_ошибка'):
            c['вход_4c_ошибка'] = m['вход_4c_ошибка']
        return c
    c.update({'на_линии': m['на_линии'], 'покрыто': m['покрыто'], 'покрыто_в_зоне': m['покрыто_в_зоне'], 'доля_точек_3px': m['доля_точек_3px']})
    if st == 'легло':
        c.update({'лишнее_м': m['лишнее_м'], 'пропущено_м': m['пропущено_м'], 'стена_без_комнаты': _no_room_hint(m['plan'], cfg)})
    else:
        c.update({'лишнее_м': None, 'пропущено_м': None, 'стена_без_комнаты': None, 'примечание': 'столбцы только с «легло»'})
    c['вход'] = m.get('вход', 'как есть')
    if m.get('вход_4c_ошибка'):
        c['вход_4c_ошибка'] = m['вход_4c_ошибка']
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--sheet', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cfg')
    a = ap.parse_args()
    cfg = load_cfg(a.cfg)
    m = measure(a.plan, a.sheet, a.out, cfg)
    print(json.dumps(column(m, cfg), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
