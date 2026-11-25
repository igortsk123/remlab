#!/usr/bin/env python3
"""Автопроверки ФОРМЫ TRELLIS.2 (Ш0) — режим OBSERVE (T-184/3, директор 22.11, P-064 п.4): меряют по GLB, кадрам и маске фото то, что не требует глаза, и пишут вердикт РЯДОМ (`form_checks.json`).
Ничего не бракуют и не останавливают конвейер: `observe: true` в `tools/scout/rules/form-checks.json`. Таблица брака — `plans/mesh-type-rules-01.md` § «Приёмка формы TRELLIS.2».
Пороги — СТАРТОВЫЕ, в rules, в коде нет ни порогов, ни ID товаров; калибруются по таблице «авто ↔ глаз» (`--table`).

Проверки (имя → что ловит, строка таблицы брака):
  glb_sane      · не читается / нулевой размер (низ формы — только в отчёт: у форм центр в нуле) · «Не читается, нулевой размер»
  open_edges    · доля открытых рёбер (грань без пары) — дыры и разрывы поверхности · «Дыры, рваный фасад или верх»
  detached      · доля площади крупных частей, парящих вне габарита главного куска · «крупный оторванный кусок»
  sil_iou/extra/miss/legs · контур кадра против маски фото и нижняя полоса (ножки) — из этапа 04 камеры (--pose-roots), пороги оттуда же · «Наплыв … меняет контур», «Пропали ножки»
  sil_extra~/sil_miss~/legs~ · то же приближённо (ортогональный силуэт GLB при лучшем азимуте), когда позы нет; только значения (approx_flag: false)
  holes         · грубые лишние сквозные просветы в силуэте против фото (приближение)  · «Дыры, рваный фасад»
  relief        · много мелкого рельефа на кадре 0° — рваный, «изъеденный» фасад   · «Дыры, рваный фасад»
  back_dup      · кадр 0° и кадр 180° (прямо или зеркально) совпадают по рельефу    · «фасад продублирован на задней стенке» (ловит только точную копию)
  legs_match    · ножки: компоненты нижней полосы маски фото ↔ формы парой по центрам, ошибка ножки ÷ её толщина, пол, число ножек (T-191/3: legs_check.py, пороги — camera-check.json legs_match; силуэт IoU этого не видит) · «Пропали ножки», «ножки не там»
  relief_graze  · мелкий рельеф кадра 0° при боковом свете ВНУТРИ маски формы (альфа, без фона и тени)  · «Дыры, рваный фасад»
  back_relief   · то же на кадре 180°: у корпусной мебели с плоской спиной (`flat_back_roles`) сильный рельеф сзади — каркас/копия фасада · «Открытая сломанная спина», «фасад сзади»
  vlm_<вид>     · оценщик по картинке (vlm_judge.py, T-184/9): «да» в обоих прогонах VLM по виду брака из паспорта (`vlm_<вид>_check` — «да» хотя бы в одном: на глаз директору), виды и роли — в rules `vlm_judge` · «Дыры, рваный фасад», «грани», «фасад без щелей», «перекос корпуса», «зад=копия», «выдуманная деталь»
  body_skew     · перекос корпуса по 3D: завал и трапеция стенок корпуса (спереди и сбоку), градусы; только корпусные роли · «перекос корпуса»
  back_dup_mask · рельеф 0° и 180° внутри маски совпадает (прямо/зеркально), только для ролей с плоской спиной · «фасад продублирован на задней стенке»
  dims_depth    · глубина формы ÷ глубина карточки при масштабе по высоте (T-20261124-11; паспорт #130/#132/#145): значение — отклонение меньшей горизонтальной оси, +0,25 = форма толще каталога на 25 %. Только ЭТАЛОННЫЕ размеры карточки (ось, выведенная программой — `NOT_REFERENCE_RX` из dimless.py, — не берётся: иначе мерка сверяла бы форму с её же приором) · «форма-ящик толще каталога», «тонкие ленты/стержни»
  dims_axes     · наибольшее по модулю отклонение габарита формы от карточки по осям (ширина, глубина, высота) · то же
  (обе мерки в observe: `dims_flag: false` — флага нет, значение и `would_flag` («сработало бы при пороге») пишутся; сколько сработало бы — для калибровки порогов `dims_*` в rules)
  thin_width    · толщина тонких частей (ленты, стержни, ножки-прутья) формы ÷ фото по силуэтам, оба к высоте `thin_h`; габарит верный (dims молчит), а лента тоньше/толще фото (T-20261124-17; #145) · «ленты/стержни»
  thin_len      · длина тонких частей формы ÷ фото (пропали/появились лишние стержни; в 3/4 часть скрыта — допуск шире). Обе — observe: `thin_flag: false`, пишется `would_flag`
Режим: `block` в rules — проверки, чей флаг даёт статус `shape_reject` (в списке только то, у чего 0 ложных на годных формах); остальные — `observe`.
Статус формы: shape_reject (сработала block-проверка) · camera_or_mask_uncertain (только провал контура из этапа 04: поза/маска/перёд-зад — не доказательство брака формы) · needs_review (прочие флаги) · pass.
Запуск: python3 form_checks.py --glbs DIR --glb-name '{sku}-hd.glb' --photos DIR --frames DIR --skus a,b | --skus-file F --out DIR [--eye eye.json --table table.md]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'form-checks.json'))
SIL_N = 256                                                    # сторона нормированной сетки сравнения силуэтов


def load_rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


def load_mesh(path: str):
    """GLB → один trimesh с применёнными преобразованиями сцены; None если не читается."""
    import trimesh
    try:
        sc = trimesh.load(path, force='scene')
        m = sc.to_geometry() if hasattr(sc, 'to_geometry') else sc.dump(concatenate=True)
    except Exception as exc:                                   # noqa: BLE001 — причина уходит в отчёт проверки glb_sane
        return None, f'{type(exc).__name__}: {exc}'
    if m is None or not len(getattr(m, 'faces', [])):
        return None, 'нет граней'
    m = m.copy()
    m.merge_vertices(merge_tex=True, merge_norm=True)                  # GLB режет вершины по UV/нормалям: без склейки по положению каждый треугольник — «отдельный кусок»
    return m, ''


def check(name: str, value, thr, flag: bool, note: str = '') -> dict:
    return {'name': name, 'value': None if value is None else round(float(value), 4), 'thr': thr, 'flag': bool(flag), 'note': note}


# ---------- геометрия ----------
def glb_sane(m, why: str, R: dict) -> dict:
    if m is None:
        return check('glb_sane', None, None, True, f'не читается: {why}')
    ext = np.asarray(m.extents, float)
    if not np.all(np.isfinite(ext)) or ext.min() <= R['min_extent']:
        return check('glb_sane', float(ext.min()), R['min_extent'], True, f'нулевой размер {np.round(ext, 4).tolist()}')
    off = float(m.bounds[0][1]) / float(ext[1])               # низ формы относительно высоты; у форм TRELLIS центр в нуле (−0,5) — только в отчёт, не флаг
    return check('glb_sane', float(ext.min()), R['min_extent'], False, f'низ формы {off:+.3f} высоты, габарит {np.round(ext, 3).tolist()}')


def open_edges(m, R: dict) -> dict:
    e = m.edges_sorted
    if not len(e):
        return check('open_edges', None, R['open_edge_share'], False, 'нет рёбер')
    _u, cnt = np.unique(e, axis=0, return_counts=True)
    share = float((cnt == 1).sum()) / len(cnt)
    return check('open_edges', share, R['open_edge_share'], share > R['open_edge_share'], f'рёбер {len(cnt)}, открытых {int((cnt == 1).sum())}')


def detached(m, R: dict) -> dict:
    """«Крупный оторванный кусок»: часть, не связанная с главным куском И не касающаяся его по габариту (с запасом `detached_gap` диагонали). Ножки/панели из отдельных кусков, упирающиеся в корпус, — норма."""
    import trimesh
    comps = trimesh.graph.connected_components(m.face_adjacency, nodes=np.arange(len(m.faces)), min_len=1)
    area = m.area_faces
    tot = float(area.sum())
    order = sorted(range(len(comps)), key=lambda i: -float(area[comps[i]].sum()))
    main = m.vertices[np.unique(m.faces[comps[order[0]]])]
    gap = R['detached_gap'] * float(np.linalg.norm(m.extents))
    lo, hi = main.min(0) - gap, main.max(0) + gap
    far, tot_far = 0, 0.0
    for i in order[1:]:
        share = float(area[comps[i]].sum()) / tot
        if share < R['detached_piece_min']:
            continue
        v = m.vertices[np.unique(m.faces[comps[i]])]
        if np.any(v.max(0) < lo) or np.any(v.min(0) > hi):
            far += 1
            tot_far += share
    return check('detached', tot_far, R['detached_share'], tot_far > R['detached_share'], f'кусков {len(comps)}, крупных парящих (вне габарита главного) {far}, главный {float(area[comps[order[0]]].sum()) / tot:.3f} площади')


# ---------- силуэты ----------
def surface_points(m, n: int, seed: int = 0) -> np.ndarray:
    import trimesh
    return np.asarray(trimesh.sample.sample_surface(m, n, seed=seed)[0], float)


def sil_at(pts: np.ndarray, az_deg: float, grid: int = 384) -> np.ndarray:
    """Ортогональный силуэт облака точек поверхности при повороте вокруг вертикали (Y вверх; az 0 — смотрим с +Z, как камера az000 после импорта glTF в Blender). Дыры от разрежения закрываются на 2 шага."""
    from scipy import ndimage
    a = math.radians(az_deg)
    x = pts[:, 0] * math.cos(a) + pts[:, 2] * math.sin(a)
    y = pts[:, 1]
    k = (grid - 5) / max(float(x.max() - x.min()), float(y.max() - y.min()), 1e-9)
    ix, iy = ((x - x.min()) * k + 2).astype(int), ((y.max() - y) * k + 2).astype(int)
    img = np.zeros((int(iy.max()) + 3, int(ix.max()) + 3), bool)
    img[iy, ix] = True
    return crop(ndimage.binary_closing(img, structure=np.ones((3, 3), bool), iterations=2))


def best_front(pts: np.ndarray, photo: np.ndarray, R: dict) -> tuple[np.ndarray, float]:
    """Азимут формы, при котором силуэт лучше всего совпадает с маской фото (фото снято не строго спереди: у форм разный поворот, см. pose az). → (силуэт, азимут)."""
    pn = norm(photo)
    best = (-1.0, 0.0, None)
    for az in range(0, 360, int(R['az_step'])):
        s = sil_at(pts, az)
        a = norm(s)
        iou = float((a & pn).sum()) / max(float((a | pn).sum()), 1.0)
        if iou > best[0]:
            best = (iou, float(az), s)
    return best[2], best[1]


def photo_mask(path: str, alpha_min: int = 127) -> np.ndarray:
    a = np.asarray(Image.open(path).convert('RGBA'))[:, :, 3]
    return crop(a > alpha_min)


def crop(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(ys) else mask


def norm(mask: np.ndarray, n: int = SIL_N) -> np.ndarray:
    """Силуэт, обрезанный по bbox, → сетка n×n (отношение сторон нормируется; его расхождение меряет отдельно aspect)."""
    return np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((n, n), Image.BILINEAR)) > 127


def fill_holes(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage
    return ndimage.binary_fill_holes(mask)


def sil_checks(front: np.ndarray, photo: np.ndarray, R: dict, az: float = 0.0) -> list[dict]:
    """ПРИБЛИЖЕНИЕ без позы камеры: ортогональный силуэт формы при лучшем азимуте против маски фото (фото снято в 3/4 с перспективой — тонкие ножки и контур считаются грубо).
    Пороги `sil_*` флагают только грубое; точная сверка — `pose_checks` (этап 04 камеры) там, где он есть. `approx_flag: false` — только значения."""
    fl = bool(R.get('approx_flag', False))
    a, b = norm(front), norm(photo)
    union = float((a | b).sum())
    iou = float((a & b).sum()) / union if union else 0.0
    extra = float((a & ~b).sum()) / max(float(b.sum()), 1.0)
    miss = float((~a & b).sum()) / max(float(b.sum()), 1.0)
    ar = math.log((front.shape[1] / front.shape[0]) / (photo.shape[1] / photo.shape[0]))
    ctx = f'IoU {iou:.3f} при азимуте {az:.0f}° (приближение, ортогонально), пропорции формы/фото {math.exp(ar):.2f}'
    out = [check('sil_extra~', extra, R['sil_extra'], fl and extra > R['sil_extra'], ctx), check('sil_miss~', miss, R['sil_miss'], fl and miss > R['sil_miss'], ctx)]
    ha = float((fill_holes(a) & ~a).sum()) / max(float(a.sum()), 1.0)                # сквозные просветы внутри силуэта
    hb = float((fill_holes(b) & ~b).sum()) / max(float(b.sum()), 1.0)
    out.append(check('holes', ha - hb, R['holes_extra'], ha - hb > R['holes_extra'], f'просветов у формы {ha:.3f}, у фото {hb:.3f} (грубые сквозные дыры; приближение)'))
    ra, rb = runs(a, R), runs(b, R)
    out.append(check('legs~', ra - rb, 0, fl and ra < rb, f'опор в нижней полосе: форма {ra}, фото {rb} (приближение)'))
    return out


def pose_checks(sku: str, roots: list[str]) -> list[dict]:
    """Точная сверка контура с маской фото — результат этапа 04 камеры (`04-camera/check.json`): IoU силуэта, пропавшее/лишнее, то же в нижней полосе (ножки). Пороги — из самого check.json
    (единый источник этапа 04). Нет прогона — пусто."""
    import glob
    for r in roots:
        for pth in [os.path.join(r, sku, '04-camera', 'check.json')] + sorted(glob.glob(os.path.join(r, 'g*', sku, '04-camera', 'check.json'))):
            if os.path.isfile(pth):
                c = json.load(open(pth, encoding='utf-8'))
                mt = c['metrics']
                src = f'этап 04 камеры ({os.path.relpath(pth, r).split(os.sep)[0] if os.sep in os.path.relpath(pth, r) else "прогон"})'

                def one(name, v, thr, op):
                    bad = (v < thr) if op == '>=' else (v > thr)
                    return check(name, v, thr, bad, f'{src}: {op} {thr}')
                return [one('sil_iou', c['metric']['value'], c['metric']['threshold'], c['metric']['op']),
                        one('sil_extra', mt['extra']['value'], mt['extra']['threshold'], mt['extra']['op']),
                        one('sil_miss', mt['miss']['value'], mt['miss']['threshold'], mt['miss']['op']),
                        one('legs', mt['miss_bottom']['value'], mt['miss_bottom']['threshold'], mt['miss_bottom']['op'])]
    return []


def runs(mask: np.ndarray, R: dict) -> int:
    """Число отдельных опор в нижней полосе силуэта: столбцы, где в полосе есть форма, склеиваем в отрезки; короче `leg_min_w` долей ширины — шум."""
    h = mask.shape[0]
    band = mask[int(h * (1 - R['leg_band'])):]
    col = band.mean(axis=0) > R['leg_fill']
    n, i = 0, 0
    while i < len(col):
        if col[i]:
            j = i
            while j < len(col) and col[j]:
                j += 1
            if (j - i) / len(col) >= R['leg_min_w']:
                n += 1
            i = j
        else:
            i += 1
    return n


# ---------- ножки: внутренняя деталь, которой не видно по IoU (T-191/1; мерка и пороги — T-191/3: salad/trellis/legs_check.py, rules/camera-check.json блок legs_match) ----------
def legs_match(S: np.ndarray, pa: np.ndarray, R: dict) -> dict:
    """S — маска формы с позы 04, pa — маска фото в тех же пикселях. Значение — худшая ошибка ножки ÷ её толщина (`legs_check.legs_report`), порог — `err_over_w_max`; флаг — провал сверки (число ножек, пол или хоть одна ножка).
    Меньше двух раздельных ножек на фото — значение не считается. `R` не используется: единственный источник порогов — camera-check.json (общий с этапами 04 и 06)."""
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', 'trellis')))
    import legs_check as LC                                       # noqa: PLC0415
    rules = LC.load_rules()
    rep = LC.legs_report(S, pa, rules)
    thr = rules['err_over_w_max']
    if not rep['applicable']:
        return check('legs_match', None, thr, False, rep['why'] or 'не применима')
    note = f"ножек фото/формы {rep['n_photo']}/{rep['n_mesh']}, худшая ошибка/толщина {rep['err_over_w_max']}, пол {rep['floor_dy_pct']:+.1f} % высоты" + (f" — {rep['why']}" if rep['mismatch'] else '')
    return check('legs_match', rep['err_over_w_max'], thr, bool(rep['mismatch']), note)


def legs_checks(sku: str, photo: str | None, roots: list[str], R: dict) -> list[dict]:
    """Маски с позы этапа 04 (stage_loss.json + stages/render_view0/mask.png) и фото в одних пикселях; нет прогона 04 или фото — пусто."""
    import glob
    run = next((os.path.dirname(p) for r in roots for p in [os.path.join(r, sku, 'stage_loss.json')] + sorted(glob.glob(os.path.join(r, 'g*', sku, 'stage_loss.json')))
                if os.path.isfile(p) and os.path.isfile(os.path.join(os.path.dirname(p), 'stages', 'render_view0', 'mask.png'))), None)
    if not run or not photo or not os.path.isfile(photo):
        return []
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', 'trellis')))
    import stage_loss as SL                                       # noqa: PLC0415 — тянет cv2, нужен только здесь
    import cv2
    reg = json.load(open(os.path.join(run, 'stage_loss.json'), encoding='utf-8'))['registration']
    S = np.asarray(Image.open(os.path.join(run, 'stages', 'render_view0', 'mask.png')).convert('L')) > 127
    h, w = S.shape
    ph = SL.read_rgba(photo)
    pa = SL.warp_inv((ph[..., 3] > 127).astype(np.uint8) * 255, np.array(reg['P'], np.float64).reshape(3, 3), (w, h), interp=cv2.INTER_NEAREST) > 127
    return [legs_match(S, pa, R)]


# ---------- тонкие ленты и стержни: габарит верный, толщина нет (T-20261124-17; паспорт #145) ----------
def thin_parts(mask: np.ndarray, R: dict) -> dict:
    """Тонкие части силуэта (ленты, стержни, спицы, ножки-прутья, тонкие рамы и кромки): то, что пропадает при раскрытии маски кругом радиуса `thin_r` × высоты силуэта (раскрытие = объединение кругов, целиком
    влезающих в маску; через два EDT, без структурного элемента). Масштаб — высота силуэта = `thin_h` пикселей, отношение сторон сохраняется. Берутся связные куски остатка длиной ≥ `thin_comp_min` × высоты
    (мелкая «крошка» у краёв толстых частей — не лента). У куска: толщина = 4 × среднее (EDT − ½) по его пикселям (для полосы шириной n пикселей это n — без дрожания на чётных/нечётных n, как у «2·EDT−1» по хребту),
    длина = площадь ÷ толщина, центр — доли ширины и высоты.
    → {len: суммарная длина ÷ высота, w: медиана толщин кусков ÷ высота (None, если кусков нет), n: число кусков, share: доля площади силуэта, comps: [{cx, cy, len, w}]}."""
    from scipy import ndimage
    h0, w0 = mask.shape
    H = int(R['thin_h'])
    s = H / max(h0, 1)
    img = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((max(int(round(w0 * s)), 1), H), Image.BILINEAR)) > 127
    img = np.pad(img, 2)                                                       # рамка из фона: край кадра — тоже край силуэта
    edt = ndimage.distance_transform_edt(img)
    r = max(float(R['thin_r']) * H, 1.0)
    core = edt > r
    thin = img & ~(ndimage.distance_transform_edt(~core) <= r) if core.any() else img.copy()
    lab, n = ndimage.label(thin, structure=np.ones((3, 3), bool))
    comps, area = [], 0
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        m = lab[sl] == i
        a = int(m.sum())
        wpx = 4.0 * float((edt[sl][m] - 0.5).mean())
        if wpx <= 0 or a / wpx < float(R['thin_comp_min']) * H:
            continue
        ys, xs = np.nonzero(m)
        comps.append({'cx': (float(xs.mean()) + sl[1].start) / img.shape[1], 'cy': (float(ys.mean()) + sl[0].start) / H, 'len': a / wpx / H, 'w': wpx / H})
        area += a
    if not comps:
        return {'len': 0.0, 'w': None, 'n': 0, 'share': 0.0, 'comps': []}
    return {'len': sum(c['len'] for c in comps), 'w': float(np.median([c['w'] for c in comps])), 'n': len(comps), 'share': area / max(float(img.sum()), 1.0), 'comps': comps}


def thin_pairs(a: dict, b: dict, R: dict) -> list[tuple]:
    """Пары «тонкая часть формы ↔ тонкая часть фото»: жадно по расстоянию между центрами (доли ширины и высоты) ≤ `thin_pair_dist`, длины в пределах ×`thin_pair_len` друг от друга (ножка — с ножкой, кромка — с кромкой).
    Ближайшие пары первыми, каждая часть — в одной паре. → [(часть формы, часть фото, расстояние)]."""
    cand = sorted(((math.hypot(p['cx'] - q['cx'], p['cy'] - q['cy']), i, j) for i, p in enumerate(a['comps']) for j, q in enumerate(b['comps'])
                   if max(p['len'], q['len']) <= float(R['thin_pair_len']) * max(min(p['len'], q['len']), 1e-9)), key=lambda t: t[0])
    used_a, used_b, out = set(), set(), []
    for d, i, j in cand:
        if d > float(R['thin_pair_dist']):
            break
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        out.append((a['comps'][i], b['comps'][j], d))
    return out


def thin_checks(front: np.ndarray, photo: np.ndarray, R: dict, az: float = 0.0) -> list[dict]:
    """Мерка по силуэту фото для тонких частей (паспорт #145: габарит формы совпал с карточкой — `dims_*` молчит, — но лента/стержень тоньше или толще, чем на фото).
    thin_width: толщина тонких частей формы ÷ фото ПО ПАРАМ (`thin_pairs`: ножка с ножкой, кромка с кромкой), значение — медиана отношений пар; нужно ≥ `thin_min_pairs` пар. Нет тонких частей у фото —
    мерка неприменима; у фото есть, у формы нет (или пар не набралось) — значение None, причина в note (длину ловит thin_len). Сработало бы при ≤ `thin_w_lo` или ≥ `thin_w_hi`.
    thin_len: суммарная длина тонких частей формы ÷ фото (пропали/появились лишние стержни; фото в 3/4 прячет часть — допуск шире). OBSERVE: `thin_flag: false` → флага нет, `would_flag` пишется.
    Силуэт формы — ортогональный при лучшем азимуте (приближение, как `sil_checks`): перспектива фото и поворот чуть меняют толщину, допуск порога это учитывает."""
    on = bool(R.get('thin_flag', False))
    a, b = thin_parts(front, R), thin_parts(photo, R)
    ctx = (f"азимут {az:.0f}° (приближение, ортогонально); тонких кусков форма/фото {a['n']}/{b['n']}, длина {a['len']:.2f}/{b['len']:.2f} высоты, "
           f"толщина (медиана) {('%.3f' % a['w']) if a['w'] else '—'}/{('%.3f' % b['w']) if b['w'] else '—'} высоты")
    thr_w = [R['thin_w_lo'], R['thin_w_hi']]
    thr_l = [R['thin_len_lo'], R['thin_len_hi']]
    if b['w'] is None or b['len'] < R['thin_min_len']:
        why = ctx + ' — у фото тонких частей нет: мерка неприменима'
        return [dict(check('thin_width', None, thr_w, False, why), would_flag=False, pairs=0), dict(check('thin_len', None, thr_l, False, why), would_flag=False)]
    lr = a['len'] / b['len']
    would_l = lr <= R['thin_len_lo'] or lr >= R['thin_len_hi']
    out_l = dict(check('thin_len', round(lr, 3), thr_l, would_l and on, ctx), would_flag=bool(would_l))
    if a['w'] is None or a['len'] < R['thin_min_len']:
        return [dict(check('thin_width', None, thr_w, False, ctx + ' — у формы тонких частей нет (на фото есть): пропали или слиты'), would_flag=False, pairs=0), out_l]
    pr = thin_pairs(a, b, R)
    if len(pr) < int(R['thin_min_pairs']):
        return [dict(check('thin_width', None, thr_w, False, ctx + f' — пар «часть формы ↔ часть фото» {len(pr)} < {int(R["thin_min_pairs"])}: сравнить толщину не с чем'), would_flag=False, pairs=len(pr)), out_l]
    ratios = [p['w'] / q['w'] for p, q, _ in pr]
    wr = float(np.median(ratios))
    would_w = wr <= R['thin_w_lo'] or wr >= R['thin_w_hi']
    note = ctx + f"; пар {len(pr)}, отношения толщин {', '.join('%.2f' % x for x in sorted(ratios))}"
    return [dict(check('thin_width', round(wr, 3), thr_w, would_w and on, note), would_flag=bool(would_w), pairs=len(pr)), out_l]


# ---------- задняя стенка по кадрам ----------
def stitch_depth(m, role: str, card: dict | None, R: dict) -> list[dict]:
    """Мерка «глубокие борозды стёжки на сиденье мягкой обивки» (T-20261124-57, П1.160, паспорт: T-156/1 р.6; код — `relief_checks.py`). Значение — p95 глубины борозд по зоне сиденья, см;
    сработало бы при p95 > `stitch_p95_cm` ИЛИ доле площади глубже 0,5 см > `stitch_share05_max`. Только мягкие типы (`stitch_roles` — по префиксу роли каталога); высота — `card['h']` (см).
    OBSERVE: `stitch_flag: false` → `flag` всегда false, `would_flag` — сработало бы; форму не меняет."""
    thr = [R['stitch_p95_cm'], R['stitch_share05_max']]

    def na(note):
        return [dict(check('stitch_p95', None, thr, False, note), would_flag=False)]
    if not any((role or '').startswith(x) for x in R['stitch_roles']):
        return na('тип без мягкой обивки сиденья — мерка не применима')
    h = (card or {}).get('h')
    if not h or not float(h) > 0:
        return na('нет высоты карточки — глубина в см не считается')
    if HERE not in sys.path:
        sys.path.append(HERE)
    import relief_checks as RC
    s = RC.seat_groove_stats(m, float(h), R)
    if s['status'] != 'ok':
        return na(s.get('why') or 'зона сиденья не найдена')
    would = s['p95'] > R['stitch_p95_cm'] or s['share05'] > R['stitch_share05_max']
    note = f"p95 {s['p95']} см, доля глубже 0,5 см {s['share05'] * 100:.1f} %, max {s['max']} см, зона {s['n']} вершин"
    return [dict(check('stitch_p95', s['p95'], thr, would and bool(R['stitch_flag']), note), would_flag=bool(would), share05=s['share05'])]


def back_dup(frames_dir: str, R: dict) -> list[dict]:
    """Кадр 0° и зеркальный кадр 180° (вид с другой стороны, тот же свет относительно камеры): продублированный фасад даёт почти одинаковый рельеф. Корреляция высокочастотной части
    в центральном окне; считается только если рельеф есть на обоих кадрах (энергия ≥ порога) — гладкая плита не даёт ложной «похожести»."""
    f0 = next((f for f in sorted(os.listdir(frames_dir)) if '_az000_clay.png' in f), None) if os.path.isdir(frames_dir) else None
    f1 = next((f for f in sorted(os.listdir(frames_dir)) if '_az180_clay.png' in f), None) if os.path.isdir(frames_dir) else None
    if not f0 or not f1:
        return [check('back_dup', None, R['back_dup_corr'], False, 'нет кадров 0°/180°')]
    from scipy import ndimage

    def hp(p):
        g = np.asarray(Image.open(os.path.join(frames_dir, p)).convert('L'), float)
        h, w = g.shape
        g = g[int(h * R['bd_win'][1]):int(h * R['bd_win'][3]), int(w * R['bd_win'][0]):int(w * R['bd_win'][2])]
        return g - ndimage.gaussian_filter(g, R['bd_sigma'])
    a, b0 = hp(f0), hp(f1)
    b = b0
    relief = check('relief', float(a.std()), R['relief_energy'], float(a.std()) > R['relief_energy'], f'энергия мелкого рельефа кадра 0° {float(a.std()):.2f} (гладкая плита ≈2, рваный фрезерованный фасад ≫)')
    ea, eb = float(a.std()), float(b.std())
    if min(ea, eb) < R['bd_energy']:
        return [relief, check('back_dup', 0.0, R['back_dup_corr'], False, f'рельефа мало (энергия {ea:.2f}/{eb:.2f} < {R["bd_energy"]}) — проверка не применима')]
    w = min(a.shape[1], b.shape[1])
    cd = float(np.corrcoef(a[:, :w].ravel(), b0[:, :w].ravel())[0, 1])               # зеркальная по глубине копия фасада сзади: с обеих сторон читается одинаково (без отражения)
    cm = float(np.corrcoef(a[:, :w].ravel(), b0[:, ::-1][:, :w].ravel())[0, 1])      # копия, повёрнутая вокруг вертикали: на кадре 180° отражена по горизонтали
    c = max(cd, cm)
    return [relief, check('back_dup', c, R['back_dup_corr'], bool(R.get('back_dup_flag', True)) and c > R['back_dup_corr'], f'корреляция рельефа 0°↔180°: прямая {cd:.3f}, зеркальная {cm:.3f}; энергия {ea:.2f}/{eb:.2f}')]


# ---------- по маске формы (альфа-кадры T-184/5) ----------
def hp_in_mask(frame: str, alpha: str, R: dict):
    """Высокочастотная часть кадра ВНУТРИ маски формы (альфа, сжатая на `mask_erode` долей стороны — край и тень не мешают). → (карта, маска) или (None, None)."""
    from scipy import ndimage
    if not (os.path.isfile(frame) and os.path.isfile(alpha)):
        return None, None
    g = np.asarray(Image.open(frame).convert('L'), float)
    a = np.asarray(Image.open(alpha).convert('RGBA'))[:, :, 3] > R['alpha_min']
    if a.shape != g.shape or a.sum() < 100:
        return None, None
    k = max(2, int(R['mask_erode'] * min(a.shape)))
    inner = ndimage.binary_erosion(a, iterations=k)
    if inner.sum() < 100:
        return None, None
    return g - ndimage.gaussian_filter(g, R['bd_sigma']), inner


def energy(hp, inner) -> float:
    return float(hp[inner].std())


def edge_slopes(u: np.ndarray, y: np.ndarray, ylo: float, yhi: float, nb: int = 14, min_share: float = 0.5) -> tuple[float, float] | None:
    """Левая/правая кромка u(y): перцентили по полосам высоты → линейная подгонка → углы от вертикали, градусы (знак +, если верх смещён вправо)."""
    edges = np.linspace(ylo, yhi, nb + 1)
    ys, lo, hi = [], [], []
    cnt = [int(((y >= a) & (y < b)).sum()) for a, b in zip(edges[:-1], edges[1:])]
    med = float(np.median([c for c in cnt if c > 0])) if any(cnt) else 0.0
    for (a, b), c in zip(zip(edges[:-1], edges[1:]), cnt):
        s = (y >= a) & (y < b)
        if c < 200 or c < min_share * med:                             # полосы с редкими точками — ножки/опоры/проём, не корпус: в подгонку не берём
            continue
        ys.append((a + b) / 2)
        lo.append(np.percentile(u[s], 0.3))
        hi.append(np.percentile(u[s], 99.7))
    if len(ys) < 4:
        return None
    return (math.degrees(math.atan(np.polyfit(ys, lo, 1)[0])), math.degrees(math.atan(np.polyfit(ys, hi, 1)[0])))


def body_skew(m, role: str, R: dict) -> list[dict]:
    """Перекос корпуса по 3D (T-184/9, слово владельца TG 1702–1703), НЕ по кадру: наши кадры — перспектива (lens 50), вертикали на них сходятся даже у идеальной коробки.
    Только корпусные роли (`flat_back_roles`). Облако точек поверхности (Y вверх): корпус = выше 12 % высоты (без ножек); спереди (x,y) и сбоку (z,y): завал = среднее углов левой/правой кромки, трапеция = их разность (стенки не параллельны), градусы. Значение = максимум по четырём."""
    r = (role or '').lower()
    if not any(x in r for x in R['flat_back_roles']):
        return []
    P = surface_points(m, int(R['body_skew_points']), seed=1)
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    h = float(y.max() - y.min())
    ylo, yhi = float(y.min()) + R['body_skew_leg_cut'] * h, float(y.max()) - 0.02 * h
    vals, note = [], []
    for nm, u in (('спереди', x), ('сбоку', z)):
        sl = edge_slopes(u, y, ylo, yhi)
        if sl is None:
            continue
        vals += [abs((sl[0] + sl[1]) / 2), abs(sl[1] - sl[0])]
        note.append(f'{nm}: завал {(sl[0] + sl[1]) / 2:+.2f}°, трапеция {sl[1] - sl[0]:+.2f}°')
    if not vals:
        return [check('body_skew', None, R['body_skew_deg'], False, 'мало точек корпуса')]
    return [check('body_skew', max(vals), R['body_skew_deg'], max(vals) > R['body_skew_deg'], '; '.join(note))]


def reference_rx():
    """Единый источник «что НЕ эталон размера карточки» — `dimless.NOT_REFERENCE_RX` (tools/scout/dimless.py; тот же список у приора глубины и калибровки меша): выведенная программой ось не годится эталоном для формы."""
    sc = os.path.normpath(os.path.join(HERE, '..', '..'))
    if sc not in sys.path:
        sys.path.append(sc)                                                  # append, не insert: чужие модули рядом не должны перекрыть свои
    import dimless
    return re.compile(dimless.NOT_REFERENCE_RX)


def card_axes(card: dict | None, R: dict) -> tuple[tuple | None, str]:
    """Эталонные габариты карточки, см: ((высота, большая горизонтальная, меньшая горизонтальная), '') либо (None, причина). `card` = {'w','d','h','len','dia': число|None, 'src': {ось: источник из dims_evidence}}.
    Ось, чей источник — не эталон (`reference_rx`), считается отсутствующей. Горизонтали: ширина+глубина (или длина вместо глубины), иначе диаметр дважды."""
    if not card:
        return None, 'нет карточки с размерами'
    rx = reference_rx()
    src = card.get('src') or {}

    def val(k):
        v = card.get(k)
        if v is None or not float(v) > 0:
            return None
        return None if rx.search(src.get(k) or '') else float(v)
    h, w, d, ln, dia = (val(k) for k in ('h', 'w', 'd', 'len', 'dia'))
    if not h:
        return None, 'нет эталонной высоты карточки'
    if w and (d or ln):
        a, b = sorted((w, d or ln), reverse=True)
        basis = 'wd' if d else 'wl'
    elif dia:
        if not R.get('dims_dia_axes'):
            return None, ('карточка по диаметру: габарит следа формы с дугой, плафоном или основанием не сравним с диаметром (замер: торшеры +130 % по ширине при верной высоте) — мерка не считается; '
                          'у круглого стола/кашпо диаметр = след — включается `dims_dia_axes`')
        a = b = dia
        basis = 'dia'
    else:
        return None, 'нет двух эталонных горизонтальных размеров карточки'
    return (h, a, b, basis), ''


def form_axes(m, R: dict) -> tuple[float, float, float]:
    """Габарит формы в её единицах: (большая горизонталь, меньшая горизонталь, высота). Горизонтали — стороны МИНИМАЛЬНОГО по площади прямоугольника вокруг следа на полу (перебор углов `dims_rot_step`; у квадрата и повёрнутой формы
    нет произвола оси, как у PCA); перцентили `dims_pct` с обоих краёв отсекают единичные выбросы. Y — вертикаль."""
    P = surface_points(m, int(R['dims_points']), seed=2)
    xz = P[:, [0, 2]]
    p = float(R['dims_pct'])
    step = float(R['dims_rot_step'])

    def rect(deg: float) -> tuple:
        t = math.radians(deg)
        u = xz[:, 0] * math.cos(t) + xz[:, 1] * math.sin(t)
        v = -xz[:, 0] * math.sin(t) + xz[:, 1] * math.cos(t)
        eu = float(np.percentile(u, 100 - p) - np.percentile(u, p))
        ev = float(np.percentile(v, 100 - p) - np.percentile(v, p))
        return (eu * ev, eu, ev, deg)
    best = min((rect(d) for d in np.arange(0.0, 90.0, step)), key=lambda x: x[0])
    best = min([best] + [rect(best[3] + k * step / 8.0) for k in range(-7, 8)], key=lambda x: x[0])        # уточнение угла вокруг найденного минимума: шаг сетки давал +3…4 п.п. к глубине у повёрнутой формы
    ext = sorted((best[1], best[2]), reverse=True)
    h = float(np.percentile(P[:, 1], 100 - p) - np.percentile(P[:, 1], p))
    return ext[0], ext[1], h


def dims_vs_card(m, card: dict | None, R: dict) -> list[dict]:
    """Мерка «габарит формы ÷ габарит карточки по трём осям» (T-20261124-11, паспорт #130/#132/#145). Масштаб формы — по высоте (`dims_anchor: h`, как в замерах паспорта: +21,5/+19,7/+26,5 % у распашных шкафов) либо по медиане трёх отношений
    (`median` — когда высота карточки сомнительна). Отклонение оси = (ось_формы / масштаб) / ось_карточки − 1.
    dims_depth — меньшая горизонтальная (глубина): сработало бы при ≥ +`dims_depth_over` (толще каталога) или ≤ −`dims_depth_under` (тоньше — ленты/стержни); dims_axes — наибольшее |отклонение| по осям > `dims_axis_dev`.
    OBSERVE: `dims_flag: false` → `flag` всегда false, `would_flag` — сработало бы; значение пишется всегда, когда есть эталонная карточка. Нет эталона — значения нет, причина в note."""
    thr_d, thr_a = [-R['dims_depth_under'], R['dims_depth_over']], R['dims_axis_dev']

    def empty(note):
        return [dict(check('dims_depth', None, thr_d, False, note), would_flag=False), dict(check('dims_axes', None, thr_a, False, note), would_flag=False)]
    ax, why = card_axes(card, R)
    if ax is None:
        return empty(why)
    ch, ca, cb, basis = ax
    fa, fb, fh = form_axes(m, R)
    if min(fa, fb, fh) <= R['min_extent']:
        return empty('форма без габарита по одной из осей — мерка не считается')
    r = [fa / ca, fb / cb, fh / ch]
    s = float(np.median(r)) if R['dims_anchor'] == 'median' else fh / ch
    dev = [x / s - 1.0 for x in r]
    note = (f"форма (масштаб по {'медиане осей' if R['dims_anchor'] == 'median' else 'высоте'}) / карточка, см: ширина {fa / s:.0f}/{ca:g} ({dev[0]:+.0%}), "
            f"глубина {fb / s:.0f}/{cb:g} ({dev[1]:+.0%}), высота {fh / s:.0f}/{ch:g} ({dev[2]:+.0%})")
    would_d = dev[1] >= R['dims_depth_over'] or dev[1] <= -R['dims_depth_under']
    top = max(abs(x) for x in dev)
    would_a = top > R['dims_axis_dev']
    on = bool(R['dims_flag'])
    return [dict(check('dims_depth', dev[1], thr_d, would_d and on, note), would_flag=bool(would_d), basis=basis),
            dict(check('dims_axes', top, thr_a, would_a and on, note), would_flag=bool(would_a), basis=basis)]


CARD_SQL = ("select json_build_object('k', shop_mid||'_'||external_id, 'w', w_cm, 'd', d_cm, 'h', h_cm, 'len', len_cm, 'dia', dia_cm, "
            "'src', json_build_object('w', dims_evidence->'w'->>'source', 'd', dims_evidence->'d'->>'source', 'h', dims_evidence->'h'->>'source', "
            "'len', dims_evidence->'len'->>'source', 'dia', dims_evidence->'dia'->>'source')) from products where shop_mid||'_'||external_id in ({ids})")


def cards_from_db(skus: list[str], runner=None) -> dict:
    """{товар (магазин_товар): карточка} из боевой базы (только чтение: размеры и источник каждой оси из dims_evidence) для `run_sku(card=…)`. Нет базы/сбой → {} (мерка тогда просто не считается, форма не страдает).
    `runner(sql) -> текст` подменяется в тестах; по умолчанию docker exec psql (имя базы — env REMLAB_DEVDB_NAME, как у dimless/mesh_bind)."""
    ids = sorted({s.replace(':', '_') for s in skus if re.fullmatch(r'\d+[_:]\d+', s)})
    if not ids:
        return {}
    sql = CARD_SQL.format(ids=','.join("'" + i + "'" for i in ids))
    try:
        if runner:
            raw = runner(sql)
        else:
            import subprocess
            raw = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'), '-At'],
                                 input=sql, capture_output=True, text=True, timeout=60).stdout
    except Exception as exc:  # noqa: BLE001 — база недоступна: мерка по карточке пропускается, остальное идёт
        print(f'cards_from_db: нет базы ({type(exc).__name__}) — dims_depth/dims_axes не считаются', file=sys.stderr)
        return {}
    out = {}
    for ln in raw.splitlines():
        if ln.startswith('{'):
            j = json.loads(ln)
            out[j.pop('k')] = j
    return out


def mask_checks(sku_dir: str, role: str, R: dict) -> list[dict]:
    """Проверки по кадрам с альфой (`<sku>/alpha/NN_<вид>_clay_graze.png` рядом с обычным кадром). Нет кадров — пусто."""
    ad = os.path.join(sku_dir, 'alpha')
    if not os.path.isdir(ad):
        return []

    def pick(az):
        return next((f for f in sorted(os.listdir(sku_dir)) if f'_{az}_clay_graze.png' in f), None)
    f0, f1 = pick('az000'), pick('az180')
    if not f0 or not f1:
        return [check('relief_graze', None, R['relief_graze'], False, 'нет кадров 0°/180° при боковом свете')]
    a, ma = hp_in_mask(os.path.join(sku_dir, f0), os.path.join(ad, f0), R)
    b, mb = hp_in_mask(os.path.join(sku_dir, f1), os.path.join(ad, f1), R)
    if a is None or b is None:
        return [check('relief_graze', None, R['relief_graze'], False, 'маска формы пуста или кадр другого размера')]
    ea, eb = energy(a, ma), energy(b, mb)
    out = [check('relief_graze', ea, R['relief_graze'], ea > R['relief_graze'], f'энергия рельефа 0° внутри маски {ea:.2f} (боковой свет)')]
    flat = any((role or '').lower().startswith(x) for x in R['flat_back_roles'])
    out.append(check('back_relief', eb, R['back_relief'], flat and eb > R['back_relief'],
                     f'энергия рельефа 180° внутри маски {eb:.2f}; роль «{role or "?"}» {"с плоской спиной" if flat else "— проверка не применима"}'))
    c = None
    if flat and min(ea, eb) >= R['bd_energy']:
        both = ma & ma[:, ::-1] & mb
        if both.sum() > 100:
            c = max(float(np.corrcoef(a[both], b[both])[0, 1]), float(np.corrcoef(a[both], b[:, ::-1][both])[0, 1]))
    out.append(check('back_dup_mask', c, R['back_dup_mask'], c is not None and c > R['back_dup_mask'],
                     'нет рельефа или роль без плоской спины — не применима' if c is None else f'корреляция рельефа 0°↔180° внутри маски {c:.3f}'))
    return out


def status_of(checks: list[dict], block: list[str]) -> str:
    flagged = [c['name'] for c in checks if c['flag']]
    if any(n in block for n in flagged):
        return 'shape_reject'
    pose = {'sil_iou', 'sil_extra', 'sil_miss', 'legs'}
    if flagged and set(flagged) <= pose:
        return 'camera_or_mask_uncertain'
    return 'needs_review' if flagged else 'pass'


def summary(recs: list[dict], eye: dict) -> str:
    """Проверка × поймала брак × ложных на годных: по этой таблице выбирают, что можно ставить в block (только 0 ложных)."""
    names = sorted({c['name'] for r in recs for c in r['checks']})
    bad = [r for r in recs if eye.get(r['sku'], {}).get('verdict') == 'брак']
    good = [r for r in recs if eye.get(r['sku'], {}).get('verdict') == 'годна']
    lines = [f'| проверка | поймала брак (из {len(bad)}) | ложных на годных (из {len(good)}) |', '|---|---|---|']
    for n in names:
        fl = lambda rs: sum(1 for r in rs for c in r['checks'] if c['name'] == n and c['flag'])
        lines.append(f'| {n} | {fl(bad)} | {fl(good)} |')
    return '\n'.join(lines)


# ---------- один товар ----------
def run_sku(sku: str, glb: str | None, photo: str | None, frames: str | None, rules: dict, pose_roots: list[str] | None = None, alpha_dir: str | None = None, role: str = '', vlm_cache: str | None = None, chat=None, vlm_kw: dict | None = None, card: dict | None = None) -> dict:
    """`card` — размеры карточки (см. `card_axes`); None — мерка по карточке не считается вовсе, {} — карточки нет: в записи `dims_*` со значением None и причиной."""
    R = rules['thresholds']
    block = rules.get('block', [])
    rec: dict = {'sku': sku, 'observe': not block, 'block': block, 'checks': []}
    if not glb or not os.path.isfile(glb):
        rec['checks'].append(check('glb_sane', None, None, True, 'GLB не найден'))
    else:
        m, why = load_mesh(glb)
        rec['checks'].append(glb_sane(m, why, R))
        if m is not None:
            rec['checks'] += [open_edges(m, R), detached(m, R)]
            rec['checks'] += body_skew(m, role, R)
            rec['checks'] += stitch_depth(m, role, card, R)
            if card is not None:
                rec['checks'] += dims_vs_card(m, card, R)
            rec['checks'] += pose_checks(sku, pose_roots or [])
            rec['checks'] += legs_checks(sku, photo, pose_roots or [], R)
            if photo and os.path.isfile(photo):
                pm = photo_mask(photo)
                fs, az = best_front(surface_points(m, int(R['sil_points'])), pm, R)
                rec['checks'] += sil_checks(fs, pm, R, az)
                rec['checks'] += thin_checks(sil_at(surface_points(m, int(R['thin_points']), seed=3), az, int(R['thin_grid'])), pm, R, az)
            else:
                rec['checks'].append(check('sil_extra~', None, R['sil_extra'], False, 'нет маски фото — приближённые силуэтные проверки пропущены'))
                rec['checks'].append(dict(check('thin_width', None, [R['thin_w_lo'], R['thin_w_hi']], False, 'нет маски фото — мерка тонких частей пропущена'), would_flag=False))
    if frames:
        rec['checks'] += back_dup(frames, R)
    if alpha_dir:
        rec['checks'] += mask_checks(alpha_dir, role, R)
    if vlm_cache and frames and rules.get('vlm_judge'):
        import vlm_judge as VJ
        rec['checks'] += VJ.judge(sku, glb, photo, frames, role, rules['vlm_judge'], vlm_cache, chat, **(vlm_kw or {}))
    flags = [c['name'] for c in rec['checks'] if c['flag']]
    rec['auto'] = 'flag' if flags else 'ok'
    rec['status'] = status_of(rec['checks'], block)
    rec['flags'] = flags
    return rec


def table(recs: list[dict], eye: dict, names: list[str]) -> str:
    lines = ['| форма | глаз | авто | ' + ' | '.join(names) + ' | флаги |', '|---|---|---|' + '---|' * len(names) + '---|']
    agree = 0
    for r in recs:
        by = {c['name']: c for c in r['checks']}
        e = eye.get(r['sku'], {})
        ev = e.get('verdict', '—')
        ok_auto = 'ok' if r['auto'] == 'ok' else 'флаг'
        if ev != '—' and ((ev == 'годна' and r['auto'] == 'ok') or (ev == 'брак' and r['auto'] == 'flag')):
            agree += 1
        cells = []
        for n in names:
            c = by.get(n)
            cells.append('—' if not c or c['value'] is None else f"{'⚠ ' if c['flag'] else ''}{c['value']}")
        lines.append(f"| {r['sku']} | {ev}{' · ' + e['note'] if e.get('note') else ''} | {ok_auto} | " + ' | '.join(cells) + f" | {', '.join(r['flags']) or '—'} |")
    judged = sum(1 for r in recs if eye.get(r['sku'], {}).get('verdict') in ('годна', 'брак'))
    lines.append(f'\nсовпало с глазом: {agree} из {judged}')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glbs', required=True)
    ap.add_argument('--glb-name', default='{sku}-hd.glb')
    ap.add_argument('--photos', required=True, help='папка <sku>.hd.rgba.png (маска — альфа)')
    ap.add_argument('--photo-name', default='{sku}.hd.rgba.png')
    ap.add_argument('--frames', default='', help='папка <sku>/NN_az000_clay.png … (для back_dup)')
    ap.add_argument('--skus', default='')
    ap.add_argument('--skus-file', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--eye', default='', help='JSON {sku: {verdict: годна|брак, note}} — вердикт глазом для таблицы')
    ap.add_argument('--table', default='')
    ap.add_argument('--pose-roots', default='', help='папки прогонов этапа 04 камеры (<root>/<sku>/04-camera/check.json или <root>/g*/<sku>/…) через запятую — точная сверка контура с фото')
    ap.add_argument('--alpha-root', default='', help='папка <sku>/NN_…_clay_graze.png + <sku>/alpha/ (кадры формы с альфой, T-184/5)')
    ap.add_argument('--roles', default='', help='JSON {sku: роль каталога} — для проверок спины (flat_back_roles)')
    ap.add_argument('--cards', default='', help='JSON {sku: {w,d,h,len,dia,src}} (см) — мерка форма÷карточка; `db` — взять из базы (cards_from_db); пусто — мерка не считается')
    ap.add_argument('--vlm-cache', default='', help='папка кэша оценщика по картинке (включает vlm_judge: платные вызовы шлюза, ответы кэшируются по хешу GLB/фото и версии вопроса)')
    ap.add_argument('--rules', default=RULES)
    a = ap.parse_args()
    rules = load_rules(a.rules)
    skus = [s for s in a.skus.split(',') if s]
    if a.skus_file:
        skus += [ln.split()[0] for ln in open(a.skus_file, encoding='utf-8') if ln.strip()]
    os.makedirs(a.out, exist_ok=True)
    roles = json.load(open(a.roles, encoding='utf-8')) if a.roles else {}
    cards = cards_from_db(skus) if a.cards == 'db' else (json.load(open(a.cards, encoding='utf-8')) if a.cards else None)
    recs = []
    for s in skus:
        rec = run_sku(s, os.path.join(a.glbs, a.glb_name.format(sku=s)), os.path.join(a.photos, a.photo_name.format(sku=s)), os.path.join(a.frames, s) if a.frames else None, rules, [x for x in a.pose_roots.split(',') if x],
                      os.path.join(a.alpha_root, s) if a.alpha_root else None, roles.get(s, ''), a.vlm_cache or None, card=None if cards is None else cards.get(s.replace(':', '_'), {}))
        os.makedirs(os.path.join(a.out, s), exist_ok=True)
        json.dump(rec, open(os.path.join(a.out, s, 'form_checks.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        recs.append(rec)
        print(f"{s} {rec['status']} {rec['flags']}", flush=True)
    json.dump(recs, open(os.path.join(a.out, 'all.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if a.table:
        eye = json.load(open(a.eye, encoding='utf-8')) if a.eye else {}
        open(a.table, 'w', encoding='utf-8').write(table(recs, eye, ['open_edges', 'detached', 'sil_iou', 'sil_extra', 'sil_miss', 'legs', 'sil_extra~', 'sil_miss~', 'holes', 'relief', 'back_dup', 'legs_match', 'relief_graze', 'back_relief', 'back_dup_mask', 'dims_depth', 'dims_axes']) + '\n\n' + summary(recs, eye) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
