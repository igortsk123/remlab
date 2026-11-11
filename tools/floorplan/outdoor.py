"""Балкон / лоджия / терраса — комната результата (T-20261111-20, владелец TG 1525: балкон на планировке «Этажей»).

Маска стен (`bench.build_mask`) берёт только толстые тёмные стены, а уличные помещения застройщики рисуют ТОНКИМИ линиями снаружи
наружной стены (Этажи: трапеция над спальней 2, «2.70 (0.80)»). VLM подпись видит (`labels4` тип `balcony`), но комнаты модели под
ней нет (`label_report.room is None`) — балкон пропадал. Здесь, ПОСЛЕ разбора и масштаба (bench/fpcore не трогаются, масштаб квартиры
тот же — уличная доля из него вычтена `pipeline.outdoor_share`), область достраивается по листу:

  дом     — полы комнат и полосы стен модели панели (метры → пиксели листа), с запасом;
  чернила — всё темнее INK_THR (тонкие линии контура, мебель, текст), расширенное на 1 px (сшить сглаживание);
  наружа  — свободное, связанное с краем листа; ЗАМКНУТОЕ = не наружа и не дом; балкон — его кусок у точки подписи.

Строится только при напечатанной площади. Кандидаты — все замкнутые куски в радиусе SEED_M от точки подписи; годен кусок, что не
касается края листа, примыкает к дому общей границей ≥ CONTACT_M и по площади (упрощённого контура) против подписи в
[AREA_MIN; AREA_MAX]; из годных — ближайший к подписи по площади. Нет годного — балкона нет, как раньше, флаг результата
`outdoor_not_built`. Комната: вид `other`, флаги `outdoor` + `outdoor_outline`, площадь для показа — подпись (полная, не
приведённая), контур — `areaContourM2`. Не обставляется (`trial_bundle`: вид `other`), в сверку масштаба по подписям
(`pipeline.scale_by_labels`) не входит. (Второе мнение Codex 11.11: кандидаты с выбором лучшего, обязательная площадь, длина
общей границы; окно целиком в дверь не превращать.)

Выход на балкон (`exits`): дверь/проход у балкона уже есть — ничего. Иначе наружное окно у балкона не уже BLOCK_MIN с видимой дугой
у одного конца (чернила внутри комнаты) — балконный блок: окно + дверь DOOR_W у этого конца, флаг балкона `outdoor_exit_block`.
Не доказано — проёмы как были, флаг `outdoor_exit_unresolved`."""
from __future__ import annotations

import math

import cv2
import numpy as np

INK_THR = 200            # чернила линий: темнее 200 (заливка пола балкона 230–245, линия контура ~100)
AREA_MIN, AREA_MAX = 0.6, 1.6   # площадь контура против подписи: иначе контур не замкнут / не тот
CONTACT_M = 0.8          # примыкает к дому общей границей не короче 0,8 м (не одним пикселем: размерные рамки, ограды сада)
SEED_M = 1.0             # точка подписи может стоять на цифре или кресле: куски ищутся в радиусе 1 м, берётся лучший
EXIT_M = 0.35            # проём у балкона: центр не дальше 0,35 м от контура балкона (полстены + запас)
BLOCK_MIN_CM = 120.0     # балконный блок (окно + дверь) — только из окна не уже 1,2 м и только при видимой дуге двери
DOOR_W_CM = 75.0         # ширина двери балконного блока
ARC_RATIO = 1.5          # перевес чернил дуги у одного конца проёма, чтобы поставить дверь туда
APPROX_M = 0.04          # упрощение контура (4 см)
SPUR_M = 0.12            # хвосты чернил тоньше 12 см, прилипшие к области снаружи, срезаются (открытие)


def is_outdoor(g: dict | None, name: str = '') -> bool:
    """Уличное помещение: тип VLM `balcony` или название из уличных (`listing.OPEN_AIR`: балкон, лоджия, терраса, патио, …)."""
    import listing
    if (g or {}).get('vtype') == 'balcony':
        return True
    s = f"{name or ''} {(g or {}).get('name0') or ''}".lower()
    return any(r in s for r in listing.OPEN_AIR)


def _to_px(pts_m, ppm: float, k: float, X0: int, Y0: int) -> np.ndarray:
    return np.array([[p[0] / k * ppm + X0, p[1] / k * ppm + Y0] for p in pts_m], np.float32)


def house_mask(model: dict, shape, ppm: float, k: float, X0: int, Y0: int) -> np.ndarray:
    """Полы комнат и полосы стен модели (метры панели × k) → маска листа."""
    m = np.zeros(shape[:2], np.uint8)
    polys = [f['outer'] for f in model.get('floors') or []]
    polys += [p['outer'] for b in model.get('bands') or [] for p in b.get('polys') or []]
    for poly in polys:
        if len(poly) >= 3:
            cv2.fillPoly(m, [np.round(_to_px(poly, ppm, k, X0, Y0)).astype(np.int32)], 1)
    return m > 0


def _outside(free: np.ndarray) -> np.ndarray:
    """Свободное, связанное с краем листа (4-связность)."""
    _, lab = cv2.connectedComponents(free.astype(np.uint8), connectivity=4)
    e = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist()) - {0}
    return np.isin(lab, list(e)) if e else np.zeros(free.shape, bool)


class Sheet:
    """Лист и дом панели для поиска уличных областей: чернила, дом с запасом, «наружа» и замкнутые куски (считаются один раз)."""

    def __init__(self, gray: np.ndarray, house: np.ndarray, ppm: float, t_px: float):
        self.gray, self.house, self.ppm = gray, house, ppm
        self.ink = cv2.dilate((gray < INK_THR).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        self.pad = max(2, int(round(t_px / 2)))
        self.hd = cv2.dilate(house.astype(np.uint8), np.ones((2 * self.pad + 1,) * 2, np.uint8)) > 0
        closed = ~_outside(~self.ink & ~self.hd) & ~self.hd
        self.n, self.lab = cv2.connectedComponents(closed.astype(np.uint8), connectivity=8)
        self.out0 = _outside(~self.ink & ~house)          # наружа без запаса у дома: полоса запаса вдоль стены — не балкон
        self.ring = cv2.dilate(self.hd.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

    def candidates(self, pt) -> list:
        """Замкнутые куски в радиусе SEED_M от точки подписи (точка может стоять на цифре, кресле) → [(расстояние px, id)]."""
        H, W = self.gray.shape[:2]
        x, y, r = int(round(pt[0])), int(round(pt[1])), int(SEED_M * self.ppm)
        y0, y1, x0, x1 = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
        if y0 >= y1 or x0 >= x1:
            return []
        sub = self.lab[y0:y1, x0:x1]
        yy, xx = np.nonzero(sub)
        best: dict = {}
        for cid, d in zip(sub[yy, xx].tolist(), np.hypot(yy + y0 - y, xx + x0 - x).tolist()):
            if d <= r and d < best.get(cid, math.inf):
                best[cid] = d
        return sorted((d, c) for c, d in best.items())

    def body(self, cid: int) -> np.ndarray | None:
        """Кусок → тело области: дыры (текст, мебель) заполнены, тонкие хвосты чернил снаружи (выносные, подоконник) срезаны
        открытием SPUR_M, полоса запаса у дома возвращена (до наружной грани стены, не вдоль неё)."""
        comp = self.lab == cid
        cs = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
        filled = np.zeros(comp.shape, np.uint8)
        cv2.drawContours(filled, cs, -1, 1, -1)
        s = max(3, int(round(SPUR_M * self.ppm)) | 1)
        body = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (s, s)))
        n3, lab3, st3, _ = cv2.connectedComponentsWithStats(body, connectivity=8)
        if n3 < 2:
            return None
        comp = lab3 == 1 + int(np.argmax(st3[1:, cv2.CC_STAT_AREA]))
        grow = cv2.dilate(comp.astype(np.uint8), np.ones((2 * self.pad + 3,) * 2, np.uint8)) > 0
        return comp | (grow & self.hd & ~self.house & ~self.out0)

    def contact_m(self, comp: np.ndarray) -> float:
        """Длина общей границы с домом, м: пиксели области в узком кольце вокруг дома с запасом (≈ длина × ширина кольца)."""
        return float((comp & self.ring & ~self.hd).sum()) / 2.0 / self.ppm


def _touches(a: np.ndarray, b: np.ndarray) -> bool:
    return bool(a[0].any() or a[-1].any() or a[:, 0].any() or a[:, -1].any()) if b is None else bool((a & b).any())


def contour_m(comp: np.ndarray, ppm: float, k: float, X0: int, Y0: int) -> list | None:
    cs = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, max(1.0, APPROX_M * ppm), True).reshape(-1, 2)
    if len(c) < 3:
        return None
    return [[(float(x) - X0) / ppm * k, (float(y) - Y0) / ppm * k] for x, y in c]


def build(P: dict, model: dict, G_by: dict, gray: np.ndarray, t_px: float, k: float = 1.0) -> tuple[list, list]:
    """Уличные помещения панели, которых нет в модели → ([{'name', 'g', 'contour_m', 'area_m2'}], флаги результата)."""
    X0, Y0 = int(P['bbox_px'][0]), int(P['bbox_px'][1])
    ppm = float(P.get('ppm') or 0)
    if ppm <= 0 or gray is None:
        return [], []
    lost = [q for q in P.get('label_report') or [] if q.get('room') is None and is_outdoor(G_by.get(q['name']), q['name'])]
    if not lost:
        return [], []
    S = Sheet(gray, house_mask(model, gray.shape, ppm, k, X0, Y0), ppm, t_px)
    out, flags, taken = [], [], np.zeros(gray.shape[:2], bool)
    for q in lost:
        g = G_by.get(q['name']) or {}
        want = printed_area(g)
        if not want:                                  # без напечатанной площади не строим: сад/двор за домом не отличить от балкона
            flags.append('outdoor_not_built')
            continue
        pick = None
        for d, cid in S.candidates((q['pt'][0] + X0, q['pt'][1] + Y0)):
            comp = S.body(cid)
            if comp is None or _touches(comp, None) or (comp & taken).any():
                continue
            ring = contour_m(comp, ppm, k, X0, Y0)
            if not ring:
                continue
            got = _shoelace(ring)
            if not (AREA_MIN <= got / float(want) <= AREA_MAX) or S.contact_m(comp) * k < CONTACT_M:
                continue
            score = (abs(math.log(got / float(want))), d)  # ближе к подписи по площади, затем по расстоянию до точки
            if pick is None or score < pick[0]:
                pick = (score, comp, ring, got)
        if pick is None:
            flags.append('outdoor_not_built')
            continue
        taken |= pick[1]
        out.append({'name': q['name'], 'g': g, 'contour_m': pick[2], 'area_m2': pick[3]})
    return out, flags


def printed_area(g: dict) -> float | None:
    """Площадь с листа: подпись «2.7 m²», иначе произведение напечатанных размеров «1.34 x 2.62 m» (терраса Giraffe360)."""
    a = g.get('area_m2')
    if a:
        return float(a)
    d = g.get('dims_m') or []
    if len(d) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in d):
        return round(float(d[0]) * float(d[1]), 2)
    return None


def _shoelace(r) -> float:
    return abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) / 2


def _ink_near(gray: np.ndarray, room_poly_px: np.ndarray, c, r_px: float) -> int:
    """Чернила в круге r у точки c внутри комнаты (дуга двери рисуется в комнате у петли)."""
    m = np.zeros(gray.shape[:2], np.uint8)
    cv2.circle(m, (int(round(c[0])), int(round(c[1]))), max(2, int(round(r_px))), 1, -1)
    rm = np.zeros(gray.shape[:2], np.uint8)
    cv2.fillPoly(rm, [np.round(room_poly_px).astype(np.int32)], 1)
    return int(((gray < INK_THR) & (m > 0) & (rm > 0)).sum())


def _seg_dist(c, ring) -> float:
    best = math.inf
    for i in range(len(ring)):
        (ax, ay), (bx, by) = ring[i - 1], ring[i]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        tt = 0.0 if L2 == 0 else max(0.0, min(1.0, ((c[0] - ax) * dx + (c[1] - ay) * dy) / L2))
        best = min(best, math.hypot(c[0] - ax - tt * dx, c[1] - ay - tt * dy))
    return best


def exits(openings: list, rooms: list, balcony: dict, gray: np.ndarray | None, ppm_cm: float, X0: int, Y0: int) -> tuple[list, str | None]:
    """Проёмы результата панели (см) → (проёмы, исход): None — выход уже есть (дверь/проход у балкона); `block` — окно у балкона
    поделено на окно + дверь (балконный блок: окно ≥ BLOCK_MIN_CM и дуга двери видна у одного конца); `unresolved` — выход
    не доказан, проёмы как были (окно целиком в дверь не превращаем: у комнаты пропал бы свет, а наружная дверь до 1,5 м — это
    «вход в квартиру» для расстановки, `trial_room._light`/`is_entrance`). `ppm_cm` — пикселей листа на сантиметр результата."""
    ring = balcony['contour']
    near = [i for i, o in enumerate(openings) if _seg_dist(o['c'], ring) <= EXIT_M * 100]
    if any(openings[i]['kind'] in ('door', 'opening') for i in near):
        return openings, None
    near = [i for i in near if openings[i]['kind'] == 'window' and openings[i].get('exterior')]
    if not near or gray is None:
        return openings, 'unresolved'
    i = max(near, key=lambda j: openings[j]['widthCm'])
    o = openings[i]
    out = list(openings)
    if o['widthCm'] < BLOCK_MIN_CM:
        return openings, 'unresolved'
    # балконный блок: ось проёма — вдоль ближайшего ребра балкона
    best, axis = math.inf, (1.0, 0.0)
    for j in range(len(ring)):
        (ax, ay), (bx, by) = ring[j - 1], ring[j]
        L = math.hypot(bx - ax, by - ay)
        if L <= 0:
            continue
        d = _seg_dist(o['c'], [ring[j - 1], ring[j]])
        if d < best:
            best, axis = d, ((bx - ax) / L, (by - ay) / L)
    half = o['widthCm'] / 2
    ends = [(o['c'][0] - axis[0] * half, o['c'][1] - axis[1] * half), (o['c'][0] + axis[0] * half, o['c'][1] + axis[1] * half)]
    host = min(rooms, key=lambda r: _seg_dist(o['c'], r['contour']), default=None)
    if host is None:
        return openings, 'unresolved'
    poly = np.array([[x * ppm_cm + X0, y * ppm_cm + Y0] for x, y in host['contour']], np.float32)
    ink = [_ink_near(gray, poly, (e[0] * ppm_cm + X0, e[1] * ppm_cm + Y0), DOOR_W_CM * ppm_cm) for e in ends]
    # дуга: у одного конца чернил не меньше длины полотна и в ARC_RATIO раз больше, чем у другого (мебель у окна — у обоих)
    if max(ink) < DOOR_W_CM * ppm_cm or max(ink) < ARC_RATIO * max(1, min(ink)):
        return openings, 'unresolved'
    side = int(np.argmax(ink))
    sgn = -1 if side == 0 else 1
    dc = (o['c'][0] + sgn * axis[0] * (half - DOOR_W_CM / 2), o['c'][1] + sgn * axis[1] * (half - DOOR_W_CM / 2))
    wc = (o['c'][0] - sgn * axis[0] * DOOR_W_CM / 2, o['c'][1] - sgn * axis[1] * DOOR_W_CM / 2)
    out[i] = dict(o, kind='window', c=[round(wc[0], 1), round(wc[1], 1)], widthCm=round(o['widthCm'] - DOOR_W_CM, 1))
    # дверь — в КОНЕЦ списка: номера прежних проёмов (`s<idx>` правок агента, `room_edits`/`reparse`) не сдвигаются
    out.append(dict(o, kind='door', c=[round(dc[0], 1), round(dc[1], 1)], widthCm=DOOR_W_CM))
    return out, 'block'
