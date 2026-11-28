"""Загрузка паспорта листа: новый режим читателя (vlm2/<id>/labels5.json: area_text, dims с направлением) предпочтительнее старого (vlm/<id>/labels4).
load(sid) → (список помещений [{name,type,pt,area_m2,area_text,dims_m,unsure}], источник 'labels5'|'labels4'|None, список всех размерных чисел или None)
dims_m комнаты из labels5 — только если у неё ровно два числа, одно 'h' и одно 'v' (иначе None: длины без привязки в Д×Ш не берём).
printed_for_plan(sid, plan, k, fit) → ({id комнаты плана: напечатанная площадь м² (сумма, если в контуре несколько помещений паспорта)}, статус паспорта) — цифры ВОРОТ из паспорта, не из ответа нейросети."""
import json
import os
import re

V = '/home/pakar/remlab-logs/etazhi-walls/voronka/versii/20261126-2234'
R = '/home/pakar/remlab-logs/etazhi-walls'
OUT_WORDS = ('балкон', 'лодж', 'balcon', 'loggia', 'terrace', 'terras')


def load(sid):
    p5 = f'{V}/vlm2/{sid}/labels5.json'
    if os.path.exists(p5):
        j = json.load(open(p5, encoding='utf-8'))
        rooms = []
        pb = f'{V}/vlm2/{sid}/labels5b.json'                  # второй проход читателя (только помеченные/мелкие цифры): расхождение с первым или «?» → цифра спорная
        b2 = json.load(open(pb, encoding='utf-8')) if os.path.exists(pb) else {}
        for i, r in enumerate(j.get('rooms', [])):
            ds = [d for d in j.get('dims', []) if d.get('room') == i and d.get('value_m')]
            hs = [d['value_m'] for d in ds if d.get('dir') == 'h']
            vs = [d['value_m'] for d in ds if d.get('dir') == 'v']
            dims = [hs[0], vs[0]] if len(ds) == 2 and len(hs) == 1 and len(vs) == 1 else None
            rooms.append({'name': r.get('name'), 'type': r.get('type'), 'pt': r.get('pt'), 'area_m2': r.get('area_m2'), 'area_text': r.get('area_text'),
                          'dims_m': dims, 'unsure': r.get('unsure')})
            q = b2.get(str(i))
            if q and (('?' in str(q['text_pass2'])) or (q.get('value_m2_pass2') is not None and r.get('area_m2') is not None and abs(q['value_m2_pass2'] - r['area_m2']) > 1e-9)):
                rooms[-1]['b_conflict'] = f'второй проход читателя: «{q["text_pass2"]}» против первого «{q["text_pass1"]}»'
        return rooms, 'labels5', j.get('dims', [])
    p4 = f'{V}/vlm/{sid}/labels4/raw-T-labels4.txt'
    if os.path.exists(p4):
        m = re.search(r'\{.*\}', open(p4, encoding='utf-8').read(), re.S)
        if m:
            return json.loads(m.group(0)).get('rooms', []), 'labels4', None
    return [], None, None


def _balc(p):
    return p.get('type') == 'balcony' or any(w in str(p.get('name') or '').lower() for w in OUT_WORDS)


def _listing(sid):
    """T-171: листы набора 1000 лежат в ru-plans-1000, стенда — в ru-plans (в снимке был только второй путь)."""
    for d in ('ru-plans-1000', 'ru-plans'):
        p = f'{R}/{d}/{sid}/listing.json'
        if os.path.exists(p):
            return p
    return f'{R}/ru-plans/{sid}/listing.json'


def sheet_status(sid, pas):
    """Правило трёх сумм (Fable 9): True — сверен; None — сумму сверить нельзя; False — не свидетель."""
    try:
        tot = float(str(json.load(open(_listing(sid), encoding='utf-8')).get('square_total')).replace(',', '.'))
    except Exception:  # noqa: BLE001
        return False
    if not pas:
        return False
    if any(not p.get('area_m2') and not _balc(p) for p in pas):
        return None

    def sums(items):
        nb = sum(p['area_m2'] for p in items if p.get('area_m2') and not _balc(p))
        pr = sum(p['area_m2'] for p in items if p.get('area_m2'))
        fu = nb + sum((p['dims_m'][0] * p['dims_m'][1] if p.get('dims_m') else p['area_m2']) for p in items if p.get('area_m2') and _balc(p))
        return (nb, pr, fu)
    if min(abs(x / tot - 1) for x in sums(pas)) <= 0.03:
        return True
    for i in range(len(pas)):
        if pas[i].get('area_m2') and min(abs(x / tot - 1) for x in sums(pas[:i] + pas[i + 1:])) <= 0.015:
            return True
    return False


def _px(x, y, s_, tx, ty, flip, fit):
    import math
    rot = fit.get('rot_deg') or 0.0
    if rot:
        cx, cy = fit.get('rot_center_cm') or [0.0, 0.0]
        a = math.radians(rot)
        dx, dy = x - cx, y - cy
        x, y = cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)
    return (s_ * x + tx, (-s_ * y + ty) if flip else (s_ * y + ty))


def printed_for_plan(sid, plan, k, fit):
    from shapely.geometry import Point, Polygon
    pas, src, _ = load(sid)
    st = sheet_status(sid, pas)
    if st is False:
        return {}, 'паспорт не свидетель (пуст или не сверен)'
    s_, (tx, ty) = fit['scale_px_per_unit_cm'], fit['shift_px']
    W, H = fit['sheet_px']
    flip = bool(fit.get('flipy'))
    polys = []
    for lv in plan['levels']:
        for r in lv.get('rooms', []):
            nm = str(r.get('name') or '').lower()
            if r.get('use') in ('balcony', 'outdoor') or r.get('ceiling') is False or any(w in nm for w in OUT_WORDS):
                continue
            pts = [_px(x * k, y * k, s_, tx, ty, flip, fit) for x, y in r['polygon']]
            g = Polygon(pts)
            polys.append((r.get('id', ''), g if g.is_valid else g.buffer(0)))
    out = {}
    for p in pas:
        if not p.get('area_m2') or _balc(p) or not p.get('pt'):
            continue
        pt = Point(p['pt'][0] * W / 1000.0, p['pt'][1] * H / 1000.0)
        hit = [rid for rid, g in polys if g.buffer(2).contains(pt)]
        if len(hit) == 1:
            out[hit[0]] = out.get(hit[0], 0.0) + float(p['area_m2'])
    return out, ('сверен' if st else 'сумму сверить нельзя (комнаты по цифрам)')
