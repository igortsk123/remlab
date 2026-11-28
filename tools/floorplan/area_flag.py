"""Флажок «проверь площадь» (T-171/флажок-площади; Fable ❓9, ❓25/❓26, директор 28.11; rab-7). Выключатель FP_AREA_FLAG, по умолчанию ВЫКЛ.

Что делает. По плану Этажей (plan.v1) и напечатанным на листе площадям комнат (подпись, привязанная к ОДНОЙ комнате) считает «чистую» площадь комнаты —
контур на осях стен минус полтолщины каждой стены на её ребре — и сравнивает с подписью. Комната, у которой |чистая − подпись| / подпись ≥ BOUNDARY, получает строку
справки листа: «проверь площадь: комната X расходится с подписью на N % (толщина своя|условная)».

Толщина (РОВНО проверенный прибор, Fable ❓25): у стены своя толщина из ответа, где она есть. Где её нет: на листе, где у наружных стен своей нет ни у одной («нет ни у одной»), — условные
COND_EXT_M / COND_INT_M (0,35 / 0,06); на остальных листах — типовые TYP_EXT_M / TYP_INT_M (0,40 / 0,15), как у прибора отчётов (`t171-ploshchad/pribor.py`). Метка «толщина: условная» — если
хоть одна стена комнаты считана условной/типовой; «своя» — все стены комнаты со своей толщиной.
  _why: 0,35/0,06 — значения, при которых верхушка подтверждена слепым зрителем 28.11 (второй зритель rab-4: 75 % против 10 % у контроля); это НЕ оценка толщины стен.
  Граница BOUNDARY = 0,222 — |расхождение| 20-й по рангу из 20 «худших» комнат этой же выборки (заморожено в ZADANIE до кода), НЕ пересчитывать и не подгонять.

Что НЕ делает.
  • Флажок — не звонок и не приговор: функции только ЧИТАЮТ план и возвращают строки; исход листа, план, площади и показ они не меняют (тест на глубокое сравнение).
  • Звонком он станет только после приёмки на резерве 74 днём (слепой подтверждает ≥ 70 %) — решение директора, не этот код.
  • Балкон/лоджия (по имени/use/ceiling) исключены из флажка СОВСЕМ — не метятся и не «оправдываются» (как П7). Коэффициенты ×1/×0,5/×0,3 ОТМЕНЕНЫ (Fable ❓26);
    «лоджия не та по форме» — слепая зона флажка, по лоджиям — круг 5б.
  • Лист-схема (чертёж не в масштабе: наложение «легло» ∧ доля на линии ≥ SCHEME_ON_LINE ∧ ≥ SCHEME_OUT_MIN комнат вне SCHEME_T) — флажков нет, отдельная строка. Признак считается
    на типовых толщинах (0,40/0,15), как при отборе слепой выборки.
  • Нет данных (неизвестные единицы, нет подписи) — комната пропущена с причиной в `skipped`, не угадывается.

Два места кода — одно содержание: тот же счёт чистой площади живёт в `~/remlab-logs/t171-ploshchad/pribor.py` (прибор отчётов); их равенство на сохранённых прогонах проверяет
`~/remlab-logs/t171-ploshchad/flag/prognat.py`. Менять счёт — в обоих местах. Врезка в сторож листа (`ustroystvo/storozh.py`, вне репозитория) — под `area_flag.enabled` в `storozh_rules.json`.

    import area_flag as AF
    AF.sheet_lines(plan, printed, overlay=...)   # [] пока FP_AREA_FLAG не включён
    AF.evaluate(plan, printed, ...)              # то же всегда, без выключателя: {'scheme', 'flags', 'skipped', 'mode', 'lines'}
"""
from __future__ import annotations

import math
import os

from shapely.geometry import Polygon
from shapely.ops import unary_union

ENV = 'FP_AREA_FLAG'
BOUNDARY = 0.222                 # |чистая − подпись| / подпись; заморожено 28.11 (ZADANIE t171-ploshchad), не подгонять и не пересчитывать
TYP_EXT_M, TYP_INT_M = 0.40, 0.15     # типовые толщины РФ: нет своей толщины у стены, лист «со своей хотя бы у части наружных»
COND_EXT_M, COND_INT_M = 0.35, 0.06   # условные: лист, где своей толщины нет ни у одной наружной (см. _why в шапке)
TOL_AXIS_M = 0.05                # стена «лежит на ребре»: оба конца ближе 5 см к прямой ребра
MIN_OVERLAP_M = 0.01
SCHEME_ON_LINE, SCHEME_OUT_MIN, SCHEME_T = 0.80, 2, 0.215    # признак «чертёж не в масштабе» (лист целиком)
SCHEME_ABS_M2 = 0.3              # допуск комнаты вне порога: max(SCHEME_T · подпись, 0,3 м²) — как в годности прибора
UNIT_TO_M = {'m': 1.0, 'cm': 0.01, 'mm': 0.001}
OUT_WORDS = ('балкон', 'лоджи', 'террас', 'веранд', 'balcon', 'terrace', 'loggia', 'patio', 'deck', 'veranda')
NO_OWN, SOME_OWN, ALL_OWN, NO_EXT = 'нет ни у одной', 'у части', 'все наружные со своей', 'нет наружных'


def enabled(env=None) -> bool:
    """Выключатель: по умолчанию ВЫКЛ; включают только значения 1/true/on/yes."""
    v = (os.environ if env is None else env).get(ENV, '')
    return str(v).strip().lower() in ('1', 'true', 'on', 'yes')


def is_outdoor(room: dict) -> bool:
    nm = str(room.get('name') or '').lower()
    return room.get('use') in ('balcony', 'outdoor') or room.get('ceiling') is False or any(w in nm for w in OUT_WORDS)


def _own(w) -> float:
    try:
        t = float(w.get('thickness'))
    except (TypeError, ValueError):
        return 0.0
    return t if t > 0 else 0.0


def thickness_group(plan: dict) -> str:
    """Группа листа по толщине наружных стен ответа: NO_EXT / ALL_OWN / SOME_OWN / NO_OWN (как у прибора отчётов)."""
    ext = [w for lv in plan.get('levels') or [] for w in lv.get('walls') or [] if w.get('kind') == 'exterior']
    if not ext:
        return NO_EXT
    n = sum(1 for w in ext if _own(w) > 0)
    return ALL_OWN if n == len(ext) else (NO_OWN if n == 0 else SOME_OWN)


def values_for(plan: dict, mode: str = 'auto') -> tuple:
    """(наружная, внутренняя, условная?) для стен без своей толщины. mode: 'auto' — по группе листа; 'typical' — всегда 0,40/0,15 (признак «схема»)."""
    if mode == 'auto' and thickness_group(plan) == NO_OWN:
        return COND_EXT_M, COND_INT_M, True
    return TYP_EXT_M, TYP_INT_M, False


def _unit(plan: dict) -> float:
    u = plan.get('units')
    if u not in UNIT_TO_M:
        raise ValueError('единицы плана неизвестны: %r' % (u,))
    return UNIT_TO_M[u]


def _strip(p, q, n, h):
    return Polygon([p, q, (q[0] + n[0] * h, q[1] + n[1] * h), (p[0] + n[0] * h, p[1] + n[1] * h)])


def _net(poly_pts, walls, k, typ_ext, typ_int):
    """→ (чистая площадь, м²; все стены комнаты со своей толщиной?). Контур на осях минус ОБЪЕДИНЕНИЕ полос в полтолщины каждой стены на её ребре, со стороны комнаты."""
    pts = [(x * k, y * k) for x, y in poly_pts]
    g = Polygon(pts)
    valid = g.is_valid
    if not valid:
        g = g.buffer(0)
    ccw = Polygon(pts).exterior.is_ccw if valid else True
    strips, all_own = [], True
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-6:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = (-uy, ux) if ccw else (uy, -ux)          # внутрь комнаты
        for w in walls:
            p, q = (w['from'][0] * k, w['from'][1] * k), (w['to'][0] * k, w['to'][1] * k)
            dp = abs((p[0] - a[0]) * (-uy) + (p[1] - a[1]) * ux)
            dq = abs((q[0] - a[0]) * (-uy) + (q[1] - a[1]) * ux)
            if dp > TOL_AXIS_M or dq > TOL_AXIS_M:
                continue
            s1, s2 = sorted(((p[0] - a[0]) * ux + (p[1] - a[1]) * uy, (q[0] - a[0]) * ux + (q[1] - a[1]) * uy))
            s1, s2 = max(0.0, s1), min(L, s2)
            if s2 - s1 >= MIN_OVERLAP_M:
                t = _own(w) * k
                if t <= 0:
                    all_own = False
                    t = typ_ext if w.get('kind') == 'exterior' else typ_int
                strips.append(_strip((a[0] + ux * s1, a[1] + uy * s1), (a[0] + ux * s2, a[1] + uy * s2), (nx, ny), t / 2.0))
    return (g.difference(unary_union(strips)).area if strips else g.area), all_own


def net_detail(plan: dict, mode: str = 'auto') -> dict:
    """{id комнаты: {'area': чистая м², 'own': все стены комнаты со своей толщиной}} по комнатам плана (контур ≥ 3 точек). План не меняется. Неизвестные единицы — ValueError."""
    k = _unit(plan)
    te, ti, _cond = values_for(plan, mode)
    out = {}
    for lv in plan.get('levels') or []:
        walls = [w for w in lv.get('walls') or [] if w.get('from') and w.get('to')]
        for r in lv.get('rooms') or []:
            poly = r.get('polygon') or []
            if len(poly) >= 3:
                a, own = _net(poly, walls, k, te, ti)
                out[r.get('id', '')] = {'area': a, 'own': own}
    return out


def net_areas(plan: dict, mode: str = 'auto') -> dict:
    """{id комнаты: чистая площадь, м²} (сверка с прибором отчётов)."""
    return {rid: v['area'] for rid, v in net_detail(plan, mode).items()}


def _rooms(plan: dict) -> dict:
    return {r.get('id', ''): r for lv in plan.get('levels') or [] for r in lv.get('rooms') or []}


def _dev(clean: float, printed: float) -> float:
    return (clean - printed) / printed


def is_scheme(plan: dict, printed: dict, overlay: dict | None) -> bool:
    """Лист-схема, чертёж не в масштабе: наложение «легло» ∧ доля на линии ≥ SCHEME_ON_LINE ∧ ≥ SCHEME_OUT_MIN комнат (не балкон) вне max(SCHEME_T, 0,3 м²) — на типовых 0,40/0,15.
    Нет данных наложения (overlay None) — не схема: класс не назначается без наложения."""
    ov = overlay or {}
    if ov.get('overlay_status') != 'легло' or (ov.get('на_линии') or 0) < SCHEME_ON_LINE:
        return False
    net = net_areas(plan, 'typical')
    rooms = _rooms(plan)
    nout = 0
    for rid, pr in printed.items():
        if rid in net and pr and not is_outdoor(rooms.get(rid, {})) and abs(net[rid] - pr) > max(SCHEME_T * pr, SCHEME_ABS_M2):
            nout += 1
    return nout >= SCHEME_OUT_MIN


def evaluate(plan: dict, printed: dict, *, overlay: dict | None = None, boundary: float = BOUNDARY) -> dict:
    """Без выключателя, только чтение. printed — {id комнаты: подпись, м²} (одна комната), overlay — {'overlay_status', 'на_линии'}.
    → {'scheme': bool, 'mode': группа листа по толщине, 'flags': [{id, name, printed_m2, clean_m2, dev, thickness}], 'skipped': [(id, причина)], 'lines': [str]};
    на листе-схеме flags пуст (отдельная строка). Балкон/лоджия — вне флажка (ни метки, ни «оправдания»)."""
    mode = thickness_group(plan)
    try:
        det = net_detail(plan)
    except ValueError as ex:
        return {'scheme': False, 'mode': mode, 'flags': [], 'skipped': [('*', str(ex))], 'lines': []}
    rooms = _rooms(plan)
    scheme = is_scheme(plan, printed or {}, overlay)
    flags, skipped = [], []
    for rid, pr in sorted((printed or {}).items()):
        if rid not in det:
            skipped.append((rid, 'нет контура комнаты'))
            continue
        if not pr or pr <= 0:
            skipped.append((rid, 'нет подписи'))
            continue
        if is_outdoor(rooms.get(rid, {})):
            continue
        d = _dev(det[rid]['area'], pr)
        if abs(d) >= boundary:
            flags.append({'id': rid, 'name': rooms.get(rid, {}).get('name') or rid, 'printed_m2': pr, 'clean_m2': det[rid]['area'], 'dev': d,
                          'thickness': 'своя' if det[rid]['own'] else 'условная'})
    flags.sort(key=lambda x: (-abs(x['dev']), x['id']))
    if scheme:
        flags = []
    lines = []
    if scheme:
        lines.append('чертёж не сходится со своими подписями')
    for f in flags:
        lines.append('проверь площадь: комната %s расходится с подписью на %d %% (толщина %s)' % (f['name'], round(100 * abs(f['dev'])), f['thickness']))
    return {'scheme': scheme, 'mode': mode, 'flags': flags, 'skipped': skipped, 'lines': lines}


def sheet_lines(plan: dict, printed: dict, **kw) -> list:
    """Строки справки листа. Выключатель FP_AREA_FLAG выкл (по умолчанию) — пусто, ничего не считается; на исход листа не влияет в обоих случаях."""
    if not enabled():
        return []
    return evaluate(plan, printed, **kw)['lines']
