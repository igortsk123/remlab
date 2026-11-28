"""T-98/6 (замена по Fable otvet-2 § 3): пересчёт моделей на листах «разбор» РФ под вопросы
  число комнат против объявления · подпись площади ровно в одной комнате · «спасла» · 5 проверок устройства дверей · колонки для воронки р.5.
Вход (только чтение): nc-models/ru/out (CC5K-base, R2S-CC5K), voronka/run/<id>/result.json (правила, р.5), voronka/vlm/<id>/labels4 (подписи с точками, р.5), ru-plans/index.csv.
Выход: ru/eval-ru.json, ru/table-ru.md, ru/voronka-kolonki.csv (для р.5), ru/kadry/<id>.png.
Меры и пороги записаны ДО счёта в ru/ozhidanie-ru.md. Вариант по умолчанию (выбран до счёта): R2S «crop», CC5K-base «s1024»; «лучший из входов» — отдельно и помечен как оптимистичный (число из объявления участвует в выборе).
  ru_eval.py [--no-kadry]"""
import csv
import json
import math
import os
import re
import sys
from collections import deque

import cv2
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, os.path.expanduser('~/remlab-logs/etazhi-walls/nc-models'))
import nc_eval as NE  # noqa: E402  (walls_assembly, poly_of)

W = os.path.expanduser('~/remlab-logs/etazhi-walls')
N = W + '/nc-models'
OUT = N + '/ru/out'
VK = W + '/voronka'
MIN_FRAC = 0.002          # комната модели — не меньше 0,2 % листа
LIVING_M2 = 8.0           # CC5K-base: подписей классов нет → «жилая» = ≥ 8 м² (масштаб по объявлению, условно)
DEF_VAR = {'r2s': 'crop', 'base': 's1024'}
ALL_VARS = {'r2s': ['full', 'crop', 'pad'], 'base': ['s512', 's1024', 's1536']}
SRC = ['rules', 'r2s', 'base']


# ---------------------------------------------------------------- загрузка источников
def vid_cat(raw):
    t = (raw or '').lower()
    if any(k in t for k in ('бти', 'фото', 'скан', 'рукопис', 'от руки', 'бумаг', 'paint')):
        return 'фото/скан/от руки'
    if 'застройщик' in t:
        return 'лист застройщика'
    if any(k in t for k in ('схем', 'планировщик', 'чертёж', 'чертеж')):
        return 'схема/чертёж'
    return 'прочее'


def jload(p):
    try:
        return json.load(open(p))
    except Exception:
        return None


def mk_room(pts, living=False, name=''):
    poly = NE.poly_of(pts) if len(pts) >= 3 else None
    return None if poly is None else {'poly': poly, 'living': living, 'name': name}


def door_len(poly_pts):
    a = np.asarray(poly_pts, np.float32)
    if len(a) < 2:
        return None, None
    (cx, cy), (w, h), ang = cv2.minAreaRect(a.reshape(-1, 1, 2))
    return float(max(w, h)), (cx, cy)


def load_rules(i):
    """Правила (р.5, result.json): комнаты и двери в пикселях листа, ppm из pxPerCm. None — нет результата."""
    d = jload('%s/run/%s/result.json' % (VK, i))
    if not d:
        return None
    rooms, doors, windows, ppm = [], [], [], None
    for pn in d.get('panels', []):
        sh = pn.get('sheet') or {}
        k = sh.get('pxPerCm') or 0
        if not k:
            continue
        ppm = k * 100.0
        x0, y0 = sh.get('x0', 0), sh.get('y0', 0)
        for r in pn.get('rooms', []):
            pts = [[x0 + p[0] * k, y0 + p[1] * k] for p in r.get('contour', [])]
            rm = mk_room(pts, r.get('kind') in ('living', 'bedroom'), r.get('name', ''))
            if rm:
                rm['kind'] = r.get('kind')
                rooms.append(rm)
        for o in pn.get('openings', []):
            c = (x0 + o['c'][0] * k, y0 + o['c'][1] * k)
            if o.get('kind') == 'door':
                doors.append({'c': c, 'w': o['widthCm'] / 100.0, 'ext_flag': bool(o.get('exterior'))})
            elif o.get('kind') == 'window' and o.get('exterior'):
                windows.append({'c': c, 'w': o['widthCm'] / 100.0})
    src_wh = (d.get('source', {}).get('imageW'), d.get('source', {}).get('imageH'))
    return {'rooms': rooms, 'doors': doors, 'windows': windows, 'ppm': ppm, 'scale': 'правила', 'src_wh': src_wh}


def r2s_load(js):
    Wd, Hd = js['sheet']
    rooms, doors = [], []
    for p in js['polys']:
        if p['cat'] in (9, 10, 0):
            if p['cat'] == 10 and len(p['poly']) >= 2:
                doors.append(p['poly'])
            continue
        rm = mk_room(p['poly'], p['cat'] in (2, 3), p.get('label', ''))
        if rm and rm['poly'].area >= MIN_FRAC * Wd * Hd:
            rooms.append(rm)
    return rooms, doors


def base_load(js):
    Wd, Hd = js['sheet']
    rooms = []
    for r in NE.walls_assembly(js, 1.0):
        if r['poly'].area >= MIN_FRAC * Wd * Hd:
            rooms.append({'poly': r['poly'], 'living': False, 'name': 'free'})
    doors = [p['poly'] for p in js['polys'] if p.get('kind') == 'door' and len(p['poly']) >= 2]
    return rooms, doors


def finish_model(rooms, door_polys, total, kind):
    """Масштаб «по площади объявления» (НЕ независимый), ширина дверей, «жилая» для CC5K-base."""
    if not rooms:
        return {'rooms': [], 'doors': [], 'ppm': None, 'scale': 'нет комнат'}
    s_px = unary_union([r['poly'] for r in rooms]).area
    ppm = math.sqrt(s_px / total) if total else None
    doors = []
    for dp in door_polys:
        wpx, c = door_len(dp)
        if wpx:
            doors.append({'c': c, 'w': wpx / ppm if ppm else None})
    if kind == 'base' and ppm:
        for r in rooms:
            r['living'] = r['poly'].area / ppm / ppm >= LIVING_M2
    return {'rooms': rooms, 'doors': doors, 'ppm': ppm, 'scale': 'по объявлению (не независимый)'}


# ---------------------------------------------------------------- метрики
def count_cmp(src, expected):
    if src is None:
        return None
    n = sum(1 for r in src['rooms'] if r['living'])
    return {'n_all': len(src['rooms']), 'living': n, 'cmp': 'равно' if n == expected else ('меньше' if n < expected else 'больше')}


# T-20261127-ЦП · рамка подписей (rab-8; Fable reshenie-ekzamen-ramka.md): `pt` читателя (labels4/labels5) — сетка 0–1000 по каждой оси листа, а не пиксели. Пересчёт — ЗДЕСЬ, в месте чтения
# (нужны ширина и высота листа), и только при включённом выключателе (storozh_rules.json: labels_frame.enabled; по умолчанию выкл — подписи отдаются как раньше, байт в байт).
GRID = 1000.0
GRID_TOL = 0.5            # допуск округления у края сетки: pt до 1000,5 — ещё сетка
FRAMES = ('grid1000', 'px')
SHEET_PATH = None         # хук: sid → путь картинки листа, ПО КОТОРОЙ считалось наложение/подгонка (storozh ставит <E.A>/input/<sid>__d.jpg; у наложения fit.json sheet_px = её [W, H])
LAST_REFUSAL = {}         # лист → причина отказа рамки (не молчим: stderr + поле guard.json «рамка_отказ»)
_SIZES = {}


def sheet_wh(i):
    """(W, H) картинки листа: сперва та, по которой считалось наложение (SHEET_PATH), иначе plan.* из SB_PLANS_DIR; None — не нашли."""
    cands = [SHEET_PATH(i)] if SHEET_PATH else []
    pdir = os.environ.get('SB_PLANS_DIR') or W + '/ru-plans'
    try:
        cands += [os.path.join(pdir, i, f) for f in sorted(os.listdir(os.path.join(pdir, i))) if f.startswith('plan.')]
    except OSError:
        pass
    for p in cands:
        if p in _SIZES:
            return _SIZES[p]
        if os.path.exists(p):
            im = cv2.imread(p)
            if im is not None:
                _SIZES[p] = (int(im.shape[1]), int(im.shape[0]))
                return _SIZES[p]
    return None


def _declared_frame(d):
    """Признак рамки В САМИХ подписях: поле `frame` (grid1000 | px) в корне labels. Нет поля — None (решает выключатель)."""
    f = d.get('frame') if isinstance(d, dict) else None
    return None if f is None else str(f)


def _labels_of(d, frame=None, wh=None, sid=None):
    """[(x, y, площадь)] из подписей. frame=None — как раньше (без пересчёта). frame='grid1000' — x·W/1000, y·H/1000 по размеру листа wh=(W, H); поле `frame` в самих подписях главнее
    (px — не пересчитывать). Не сетка (pt вне 0…1000), неизвестное поле frame или нет размера листа — ОТКАЗ: возвращает None и пишет причину в LAST_REFUSAL[sid]."""
    out = []
    for r in d.get('rooms', []):
        if r.get('area_m2') is not None and r.get('pt'):
            out.append((float(r['pt'][0]), float(r['pt'][1]), float(r['area_m2'])))
    if frame is None:
        return out
    decl = _declared_frame(d)
    fr = decl or frame
    if fr not in FRAMES:
        why = 'рамка подписей «%s» неизвестна (ждём grid1000 или px)' % fr
    elif fr == 'px':
        return out
    elif not out:
        return out
    else:
        mx = max(max(x, y) for (x, y, _a) in out)
        mn = min(min(x, y) for (x, y, _a) in out)
        if mx > GRID + GRID_TOL or mn < 0:
            why = 'подписи не в сетке 0–1000: pt от %g до %g — рамку не знаю, не пересчитываю' % (mn, mx)
        elif not wh:
            why = 'нет размера листа (картинка листа не найдена) — сетку в пиксели не перевести'
        else:
            return [(x * wh[0] / GRID, y * wh[1] / GRID, a) for (x, y, a) in out]
    LAST_REFUSAL[sid] = why
    sys.stderr.write('РАМКА ПОДПИСЕЙ — отказ (%s): %s\n' % (sid, why))
    return None


def parse_labels(i, src=None, frame=None):
    """Подписи листа → [(x, y, площадь м²)] или None. T-98/17: источник — `src` или переменная окружения LABELS_SRC:
      'labels4' (по умолчанию, как было: vlm/<id>/labels4/raw-T-labels4.txt — результат байт в байт прежний),
      'labels5' (vlm2/<id>/labels5.json читателя reader_v2: те же поля rooms[].pt / area_m2),
      'auto'    (формат определяется по файлу: есть labels4 — он, иначе labels5).
    T-20261127-ЦП: frame='grid1000' (или переменная окружения LABELS_FRAME) — подписи из сетки 0–1000 в пиксели листа (см. _labels_of); не задано — как раньше."""
    src = src or os.environ.get('LABELS_SRC') or 'labels4'
    frame = frame or os.environ.get('LABELS_FRAME') or None
    wh = None
    if frame:
        LAST_REFUSAL.pop(i, None)
        wh = sheet_wh(i)
    p5 = '%s/vlm2/%s/labels5.json' % (VK, i)
    p = '%s/vlm/%s/labels4/raw-T-labels4.txt' % (VK, i)
    if src == 'labels5' or (src == 'auto' and not os.path.exists(p)):
        if not os.path.exists(p5):
            return None
        try:
            return _labels_of(json.load(open(p5, encoding='utf-8')), frame, wh, i)
        except Exception:
            return None
    if not os.path.exists(p):
        return None
    t = open(p).read()
    m = re.search(r'```json\s*(\{.*?\})\s*```', t, re.S)
    try:
        d = json.loads(m.group(1) if m else t)
    except Exception:
        return None
    return _labels_of(d, frame, wh, i)


def label_check(src, labels, scale_xy):
    if src is None or labels is None:
        return None
    if len(labels) < 3:
        return {'status': 'не проверяемо: подписей < 3', 'labels': len(labels)}
    cnt = [0] * len(src['rooms'])
    one = 0
    for (x, y, a) in labels:
        pt = Point(x * scale_xy[0], y * scale_xy[1])
        hit = [k for k, r in enumerate(src['rooms']) if r['poly'].buffer(2).contains(pt)]
        if len(hit) == 1:
            one += 1
        for k in hit:
            cnt[k] += 1
    merged = sum(1 for c in cnt if c >= 2)
    ok = (one == len(labels)) and merged == 0
    return {'status': 'проходит' if ok else 'не проходит', 'labels': len(labels), 'in_one': one, 'merged_rooms': merged}


def door_checks(src):
    if src is None:
        return None
    ppm = src['ppm']
    rooms, doors = src['rooms'], src['doors']
    if not ppm or not rooms or not doors:
        return {'doors': len(doors), 'no_doors_or_rooms': True}
    r_in = 0.5 * ppm
    buf = [r['poly'].buffer(0.1 * ppm) for r in rooms]
    hull = unary_union([r['poly'] for r in rooms]).buffer(0.25 * ppm)
    hull_f = Polygon(hull.exterior) if hull.geom_type == 'Polygon' else hull
    adj = {k: set() for k in range(len(rooms))}
    street = set()
    off_wall = off_w = 0
    touched = set()
    exterior = 0
    ext_centers = []
    for d in doors:
        cx, cy = d['c']
        inside, outside = set(), False
        for a in range(16):
            px, py = cx + r_in * math.cos(a * math.pi / 8), cy + r_in * math.sin(a * math.pi / 8)
            pt = Point(px, py)
            h = [k for k in range(len(rooms)) if buf[k].contains(pt)]
            if h:
                inside.update(h)
            elif not hull_f.contains(pt):
                outside = True
        touched |= inside
        ks = sorted(inside)
        if outside and len(ks) >= 1:
            exterior += 1
            ext_centers.append((cx, cy))
            street.update(ks)
        elif len(ks) < 2:
            off_wall += 1
        for x in ks:
            for y in ks:
                if x != y:
                    adj[x].add(y)
        if d['w'] is not None and not (0.6 <= d['w'] <= 1.0):
            off_w += 1
    dups = 0
    for a in range(len(doors)):
        for b in range(a + 1, len(doors)):
            if math.hypot(doors[a]['c'][0] - doors[b]['c'][0], doors[a]['c'][1] - doors[b]['c'][1]) < 0.4 * ppm:
                dups += 1
    start = set(street) if street else {max(range(len(rooms)), key=lambda k: rooms[k]['poly'].area)}
    seen, dq = set(start), deque(start)
    while dq:
        x = dq.popleft()
        for y in adj[x]:
            if y not in seen:
                seen.add(y)
                dq.append(y)
    big = [k for k in range(len(rooms)) if rooms[k]['poly'].area / ppm / ppm >= 2.0]
    no_entry = sum(1 for k in big if k not in touched)
    reach = (sum(1 for k in big if k in seen) / len(big)) if big else None
    ws = [d['w'] for d in doors if d['w'] is not None]
    return {'ext_centers': ext_centers, 'doors': len(doors), 'rooms_ge2m2': len(big), 'no_entry_rooms': no_entry, 'exterior_doors': exterior, 'reach_frac': None if reach is None else round(reach, 2),
            'off_wall': off_wall, 'off_width': off_w, 'dups': dups, 'median_w': round(float(np.median(ws)), 2) if ws else None,
            'clean': bool(no_entry == 0 and exterior == 1 and (reach or 0) >= 0.999 and off_wall == 0 and off_w == 0 and dups == 0)}


# ---------------------------------------------------------------- кадры
def draw(img, src, title):
    over = img.copy()
    rng = np.random.RandomState(5)
    for r in src['rooms']:
        pts = np.array(r['poly'].exterior.coords, np.int32)
        cv2.fillPoly(over, [pts], tuple(int(v) for v in rng.randint(60, 230, 3)))
    out = cv2.addWeighted(over, 0.45, img, 0.55, 0)
    for r in src['rooms']:
        cv2.polylines(out, [np.array(r['poly'].exterior.coords, np.int32)], True, (0, 0, 0), 1)
        c = r['poly'].centroid
        txt = 'Ж' if r['living'] else ''
        if src['ppm']:
            txt += '%.0f' % (r['poly'].area / src['ppm'] ** 2)
        cv2.putText(out, txt, (int(c.x) - 10, int(c.y)), cv2.FONT_HERSHEY_SIMPLEX, max(0.4, img.shape[1] / 1800), (0, 0, 170), 1, cv2.LINE_AA)
    for d in src['doors']:
        cx, cy = d['c']
        cv2.circle(out, (int(cx), int(cy)), max(4, img.shape[1] // 120), (0, 0, 230), -1)
    bar = np.full((34, out.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, title, (6, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return np.vstack([bar, out])


def read_sheet(path):
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        a = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (img[:, :, :3].astype(np.float32) * a + 255.0 * (1 - a)).astype(np.uint8)
    return img


# ---------------------------------------------------------------- главное
def main():
    kadry = '--no-kadry' not in sys.argv
    jobs = json.load(open(N + '/ru/jobs-ru-all.json'))
    idx = {r['city'] + '-' + r['id']: r for r in csv.DictReader(open(W + '/ru-plans/index.csv'))}
    vt = {x[0]: x for x in csv.reader(open(W + '/ru-plans/vid-tip.csv'), delimiter=';') if len(x) > 3}
    fun = {r['id']: r for r in csv.DictReader(open(VK + '/funnel.csv'))} if os.path.exists(VK + '/funnel.csv') else {}
    os.makedirs(N + '/ru/kadry', exist_ok=True)
    res = []
    for j in jobs:
        i = j['id']
        row = idx[i]
        total = float(row['square_total'])
        nroom = int(row['rooms'])
        exp = max(nroom, 1)
        rec = {'id': i, 'vid': vid_cat(vt[i][1] if i in vt else ''), 'listing_rooms': nroom, 'expected_living': exp, 'total': total, 'src': {}}
        variants = {}
        for kind, folder in (('r2s', 'cc5k'), ('base', 'cc5kbase')):
            for v in ALL_VARS[kind]:
                js = jload('%s/%s/%s.%s.json' % (OUT, folder, i, v))
                if not js or js.get('error'):
                    continue
                rooms, dp = (r2s_load if kind == 'r2s' else base_load)(js)
                variants[(kind, v)] = (finish_model(rooms, dp, total, kind), js['sheet'])
        srcs = {'rules': load_rules(i)}
        sheet_wh = None
        for kind in ('r2s', 'base'):
            s = variants.get((kind, DEF_VAR[kind]))
            srcs[kind] = s[0] if s else None
            if s:
                sheet_wh = s[1]
        best = {}
        for kind in ('r2s', 'base'):
            cands = [(abs(sum(1 for r in v[0]['rooms'] if r['living']) - exp), k[1]) for k, v in variants.items() if k[0] == kind]
            best[kind] = min(cands)[1] if cands else None
        lab = parse_labels(i)
        sc = (1.0, 1.0)
        rl = srcs['rules']
        for s in SRC:
            sr = srcs[s]
            cc = count_cmp(sr, exp)
            rec['src'][s] = {'count': cc, 'labels': label_check(sr, lab, (1.0, 1.0)) if sr else None, 'doors': door_checks(sr), 'ppm': None if not sr or not sr['ppm'] else round(sr['ppm'], 1)}
        ent = {'rules_ext_flag': None, 'rules_ext_geom': None, 'r2s_ext': None, 'base_ext': None, 'rules_window_at_model_door': None}
        if rl and rl['rooms']:
            ent['rules_ext_flag'] = sum(1 for d in rl['doors'] if d.get('ext_flag'))
            dc = rec['src']['rules']['doors']
            ent['rules_ext_geom'] = None if not dc or dc.get('no_doors_or_rooms') else dc['exterior_doors']
        for kk in ('r2s', 'base'):
            dc = rec['src'][kk]['doors']
            ent[kk + '_ext'] = None if not dc or dc.get('no_doors_or_rooms') else dc['exterior_doors']
        # «правила назвали окном то, что модель считает наружной дверью»
        if rl and rl['rooms']:
            tol = 0.6 * rl['ppm']
            near = 0
            tot_m = 0
            for kk in ('r2s', 'base'):
                dc = rec['src'][kk]['doors']
                for (x, y) in (dc or {}).get('ext_centers', []):
                    tot_m += 1
                    near += any(math.hypot(x - w['c'][0], y - w['c'][1]) <= tol for w in rl['windows'])
            ent['rules_window_at_model_door'] = [near, tot_m]
        rec['entrance'] = ent
        rec['labels_n'] = None if lab is None else len(lab)
        rec['sheet_wh'] = sheet_wh
        rec['rules_src_wh'] = rl['src_wh'] if rl else None
        rec['best_variant'] = best
        rec['best_count'] = {}
        for kind in ('r2s', 'base'):
            if best[kind]:
                rec['best_count'][kind] = count_cmp(variants[(kind, best[kind])][0], exp)
        rec['rules_funnel_died'] = fun.get(i, {}).get('умер_на')
        rec['rules_funnel_living'] = fun.get(i, {}).get('жилых_наших')
        res.append(rec)
        if kadry and sheet_wh and srcs['r2s'] and srcs['base']:
            img = read_sheet(j['image'])
            panels = []
            for s, nm in (('rules', 'правила'), ('r2s', 'R2S-CC5K'), ('base', 'CC5K-base')):
                if srcs[s] and srcs[s]['rooms']:
                    c = rec['src'][s]['count']
                    t = '%s %s | объявл.: комнат %d, %.1f м2 | жилых %d (%s) | дверей %d' % (i, nm, nroom, total, c['living'], c['cmp'], len(srcs[s]['doors']))
                    panels.append(draw(img, srcs[s], t[:140]))
            if panels:
                hh = 700
                panels = [cv2.resize(p, (int(p.shape[1] * hh / p.shape[0]), hh)) for p in panels]
                cv2.imwrite('%s/ru/kadry/%s.png' % (N, i), np.hstack(panels))
    json.dump(res, open(N + '/ru/eval-ru.json', 'w'), ensure_ascii=False, indent=1)
    tables(res)
    voronka_cols(res)


def pc(a, b):
    return '%d из %d (%.0f %%)' % (a, b, 100.0 * a / b) if b else '0 из 0'


def tables(res):
    rr = [r for r in res if r['src']['rules'] and r['src']['rules']['count'] and r['src']['rules']['count']['n_all'] >= 0 and r['src']['rules']['count'] is not None]
    L = ['# T-98/6 · модели на листах «разбор» РФ (НЕКОММЕРЧЕСКИЕ ВЕСА, выходы — не разметка)', '',
         'Листов «разбор»: %d. Правила (р.5, voronka/run) есть на %d листах — колонки «правила» и «спасла» считаются только на них. Масштаб моделей — «по площади объявления» (не независимый).' % (len(res), len(rr)),
         'Вариант по умолчанию: R2S «crop», CC5K-base «s1024»; «лучший вход» — оптимистично (выбор по числу из объявления).', '']
    L += ['## 1. Число жилых комнат против объявления', '', '| группа | листов | R2S совпало | R2S меньше | R2S больше | base совпало | base меньше | base больше | оба совпали | R2S лучший вход (оптим.) | base лучший вход (оптим.) |', '|---|---|---|---|---|---|---|---|---|---|---|']
    groups = {}
    for r in res:
        groups.setdefault(r['vid'], []).append(r)
    groups['ВСЕ'] = res
    for g, rs in sorted(groups.items(), key=lambda kv: (kv[0] == 'ВСЕ', kv[0])):
        n = len(rs)

        def c(kind, key):
            return sum(1 for r in rs if r['src'][kind]['count'] and r['src'][kind]['count']['cmp'] == key)
        both = sum(1 for r in rs if all(r['src'][k]['count'] and r['src'][k]['count']['cmp'] == 'равно' for k in ('r2s', 'base')))

        def bc(k):
            return sum(1 for r in rs if r['best_count'].get(k) and r['best_count'][k]['cmp'] == 'равно')
        L.append('| %s | %d | %s | %d | %d | %s | %d | %d | %d | %d | %d |' % (g, n, pc(c('r2s', 'равно'), n), c('r2s', 'меньше'), c('r2s', 'больше'), pc(c('base', 'равно'), n), c('base', 'меньше'), c('base', 'больше'), both, bc('r2s'), bc('base')))
    L += ['', 'Правила (там, где результат есть): %s' % pc(sum(1 for r in rr if r['src']['rules']['count']['cmp'] == 'равно'), len(rr)), '']
    L += ['## 2. Подпись площади ровно в одной комнате (и ни в одной комнате двух подписей)', '', '| источник | проверяемых листов (подписей ≥3) | проходит | не проходит | из них со слитой комнатой (2 подписи) |', '|---|---|---|---|---|']
    for s in SRC:
        ok = [r for r in res if r['src'][s]['labels'] and r['src'][s]['labels']['status'] in ('проходит', 'не проходит')]
        L.append('| %s | %d | %s | %d | %d |' % (s, len(ok), pc(sum(1 for r in ok if r['src'][s]['labels']['status'] == 'проходит'), len(ok)), sum(1 for r in ok if r['src'][s]['labels']['status'] != 'проходит'), sum(1 for r in ok if r['src'][s]['labels']['merged_rooms'] > 0)))
    L.append('')
    L += ['## 3. «Спасла» / «навредила» (только листы с результатом правил)', '', '| модель | листов с правилами | правила ошиблись | модель права там («спасла») | правила правы | модель тоже права | модель ошиблась там («навредила») | вывод по порогу |', '|---|---|---|---|---|---|---|---|']
    for k, nm in (('r2s', 'R2S-CC5K'), ('base', 'CC5K-base')):
        rw = [r for r in rr if r['src']['rules']['count']['cmp'] != 'равно']
        rg = [r for r in rr if r['src']['rules']['count']['cmp'] == 'равно']
        sav = sum(1 for r in rw if r['src'][k]['count'] and r['src'][k]['count']['cmp'] == 'равно')
        agr = sum(1 for r in rg if r['src'][k]['count'] and r['src'][k]['count']['cmp'] == 'равно')
        verdict = 'мало данных (<10 листов «правила ошиблись»)' if len(rw) < 10 else ('счётчик полезен' if (sav / len(rw) >= 0.3 and len(rg) and agr / len(rg) >= 0.7) else 'не счётчик')
        L.append('| %s | %d | %d | %d | %d | %d | %d | %s |' % (nm, len(rr), len(rw), sav, len(rg), agr, len(rg) - agr, verdict))
    L.append('')
    L += ['## 4. Двери — пять проверок устройства', '', 'Лист «чистый» = нет комнат без входа, ровно одна входная, все комнаты достижимы, нет дверей не на стене, нет дверей вне 0,6–1,0 м, нет дублей. Масштаб моделей — по объявлению.', '',
          '| источник | листов с дверями | чистых | комнат без входа (сумма) | листов, где входных ≠ 1 | листов с недостижимыми | дверей не на стене | дверей вне 0,6–1,0 м | всего дверей | дублей | медиана ширины по листам |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for s in SRC:
        ds = [r['src'][s]['doors'] for r in res if r['src'][s]['doors'] and not r['src'][s]['doors'].get('no_doors_or_rooms')]
        alld = sum(d['doors'] for d in ds)
        meds = [d['median_w'] for d in ds if d['median_w'] is not None]
        L.append('| %s | %d | %s | %d | %d | %d | %d | %d | %d | %d | %s |' % (
            s, len(ds), pc(sum(1 for d in ds if d['clean']), len(ds)), sum(d['no_entry_rooms'] for d in ds), sum(1 for d in ds if d['exterior_doors'] != 1),
            sum(1 for d in ds if (d['reach_frac'] or 0) < 0.999), sum(d['off_wall'] for d in ds), sum(d['off_width'] for d in ds), alld, sum(d['dups'] for d in ds),
            '%.2f' % float(np.median(meds)) if meds else '—'))
    L += ['', '## 5. Наружные / входные двери (правка Fable 13:3x — единственный вопрос про двери)', '',
          'Наружная дверь = дверь на стене, за которой с одной стороны комната, с другой — улица (геометрия, 16 точек вокруг двери). Для правил отдельно — их собственный признак `exterior` у двери. «Нужна» = у квартиры есть вход, то есть ≥ 1 наружная дверь.', '',
          '| источник | листов с результатом | ≥ 1 наружная найдена | 0 наружных | ровно 1 | > 1 |', '|---|---|---|---|---|---|']
    ent = [r['entrance'] for r in res]

    def row5(name, key, only_with_rules=False):
        vals = [e[key] for r, e in zip(res, ent) if e[key] is not None and (not only_with_rules or e['rules_ext_flag'] is not None)]
        return '| %s | %d | %s | %d | %d | %d |' % (name, len(vals), pc(sum(1 for v in vals if v >= 1), len(vals)), sum(1 for v in vals if v == 0), sum(1 for v in vals if v == 1), sum(1 for v in vals if v > 1))
    L += [row5('правила (свой признак exterior)', 'rules_ext_flag'), row5('правила (по геометрии)', 'rules_ext_geom'),
          row5('R2S-CC5K (по геометрии, те же листы, что у правил)', 'r2s_ext', True), row5('CC5K-base (по геометрии, те же листы)', 'base_ext', True), '']
    both = [(r['id'], e) for r, e in zip(res, ent) if e['rules_ext_flag'] is not None]
    lost = [(i, e) for i, e in both if e['rules_ext_flag'] == 0 and ((e['r2s_ext'] or 0) >= 1 or (e['base_ext'] or 0) >= 1)]
    w = [e['rules_window_at_model_door'] for i, e in both if e['rules_window_at_model_door']]
    L.append('Листов, где правила не нашли ни одной наружной, а модель нашла: %d из %d (с результатом правил). Из наружных дверей моделей на этих листах правила приняли за окно (окно в пределах 0,6 м): %d из %d (по всем листам с правилами).' % (len(lost), len(both), sum(a for a, b in w), sum(b for a, b in w)))
    L += ['', '## По листам', '', '| id | вид | объявл. комнат / м² | подписей | правила: жилых / итог | R2S: жилых / итог / подпись | base: жилых / итог / подпись | двери: правила / R2S / base (чистый?) |', '|---|---|---|---|---|---|---|---|']

    def cell(r, s):
        c = r['src'][s]['count']
        return 'нет' if not c else str(c['living'])

    def itg(r, s):
        c = r['src'][s]['count']
        return '—' if not c else {'равно': '=', 'меньше': '<', 'больше': '>'}[c['cmp']]

    def lab(r, s):
        x = r['src'][s]['labels']
        return '—' if not x else {'проходит': 'ок', 'не проходит': 'нет'}.get(x['status'], 'не пров.')

    def dr(r, s):
        d = r['src'][s]['doors']
        if not d:
            return '—'
        if d.get('no_doors_or_rooms'):
            return '0 дв.'
        return '%d (%s)' % (d['doors'], 'да' if d['clean'] else 'нет')
    for r in res:
        L.append('| %s | %s | %d / %.1f | %s | %s / %s | %s / %s / %s | %s / %s / %s | %s / %s / %s |' % (
            r['id'], r['vid'], r['listing_rooms'], r['total'], '—' if r['labels_n'] is None else r['labels_n'],
            cell(r, 'rules'), itg(r, 'rules'), cell(r, 'r2s'), itg(r, 'r2s'), lab(r, 'r2s'), cell(r, 'base'), itg(r, 'base'), lab(r, 'base'), dr(r, 'rules'), dr(r, 'r2s'), dr(r, 'base')))
    open(N + '/ru/table-ru.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L[:48]))


def voronka_cols(res):
    """Для р.5: выжила ли модель на шаге 3 (≥2 замкнутых комнат) и шаге 4 (число жилых = объявлению); рядом — где умерли правила."""
    with open(N + '/ru/voronka-kolonki.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['id', 'правила_умер_на', 'R2S_шаг3_комнат>=2', 'R2S_шаг4_число=объявл', 'CC5K-base_шаг3_комнат>=2', 'CC5K-base_шаг4_число=объявл', 'R2S_комнат_всего', 'base_комнат_всего', 'примечание'])
        for r in res:
            def s3(k):
                c = r['src'][k]['count']
                return '' if not c else ('да' if c['n_all'] >= 2 else 'нет')

            def s4(k):
                c = r['src'][k]['count']
                return '' if not c else ('да' if c['cmp'] == 'равно' else 'нет')

            def na(k):
                return '' if not r['src'][k]['count'] else r['src'][k]['count']['n_all']
            w.writerow([r['id'], r['rules_funnel_died'] or '', s3('r2s'), s4('r2s'), s3('base'), s4('base'), na('r2s'), na('base'), 'вариант по умолчанию; масштаб по объявлению; «жилая» у base = ≥8 м² условно'])


if __name__ == '__main__':
    main()
