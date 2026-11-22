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
  legs_match    · ножки: компоненты нижней полосы маски фото ↔ формы парой по центрам, макс. смещение центра / шаг между соседними ножками фото (силуэт IoU этого не видит; нормировка на ширину предмета не разводила) · «Пропали ножки», «ножки не там» (р.3, T-191/1)
  relief_graze  · мелкий рельеф кадра 0° при боковом свете ВНУТРИ маски формы (альфа, без фона и тени)  · «Дыры, рваный фасад»
  back_relief   · то же на кадре 180°: у корпусной мебели с плоской спиной (`flat_back_roles`) сильный рельеф сзади — каркас/копия фасада · «Открытая сломанная спина», «фасад сзади»
  vlm_<вид>     · оценщик по картинке (vlm_judge.py, T-184/9): «да» в обоих прогонах VLM по виду брака из паспорта (`vlm_<вид>_check` — «да» хотя бы в одном: на глаз директору), виды и роли — в rules `vlm_judge` · «Дыры, рваный фасад», «грани», «фасад без щелей», «перекос корпуса», «зад=копия», «выдуманная деталь»
  body_skew     · перекос корпуса по 3D: завал и трапеция стенок корпуса (спереди и сбоку), градусы; только корпусные роли · «перекос корпуса»
  back_dup_mask · рельеф 0° и 180° внутри маски совпадает (прямо/зеркально), только для ролей с плоской спиной · «фасад продублирован на задней стенке»
Режим: `block` в rules — проверки, чей флаг даёт статус `shape_reject` (в списке только то, у чего 0 ложных на годных формах); остальные — `observe`.
Статус формы: shape_reject (сработала block-проверка) · camera_or_mask_uncertain (только провал контура из этапа 04: поза/маска/перёд-зад — не доказательство брака формы) · needs_review (прочие флаги) · pass.
Запуск: python3 form_checks.py --glbs DIR --glb-name '{sku}-hd.glb' --photos DIR --frames DIR --skus a,b | --skus-file F --out DIR [--eye eye.json --table table.md]
"""
from __future__ import annotations

import argparse
import json
import math
import os
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


# ---------- ножки: внутренняя деталь, которой не видно по IoU (логика р.router-3, T-191/1) ----------
def leg_centers(m: np.ndarray, y0: int, y1: int, min_area: int) -> list[tuple[float, float]]:
    from scipy import ndimage
    reg = np.zeros_like(m)
    reg[y0:y1] = m[y0:y1]
    lab, n = ndimage.label(reg, structure=np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        if int((lab == i).sum()) >= min_area:
            cy, cx = ndimage.center_of_mass(lab == i)
            out.append((cx, cy))
    return out


def legs_match(S: np.ndarray, pa: np.ndarray, R: dict) -> dict:
    """S — маска формы с позы 04, pa — маска фото в тех же пикселях. Ножки = компоненты нижней полосы `leg_match_band` высоты предмета. Число ножек разное (скрыты/слиты) — значение не считается."""
    from scipy.optimize import linear_sum_assignment
    ys, xs = np.nonzero(pa)
    if not len(ys):
        return check('legs_match', None, R['legs_match'], False, 'маска фото пуста')
    y0, y1 = ys.min(), ys.max() + 1
    ya = y1 - int((y1 - y0) * R['leg_match_band'])
    cp, cs = leg_centers(pa, ya, y1, R['leg_match_area']), leg_centers(S, ya, y1, R['leg_match_area'])
    if len(cp) < 2:
        return check('legs_match', None, R['legs_match'], False, f'ножки фото не раздельны ({len(cp)}) — не применима')
    if len(cp) != len(cs):
        return check('legs_match', None, R['legs_match'], False, f'ножек фото/формы {len(cp)}/{len(cs)} — разное число (скрыты или слиты), значение не считается')
    D = np.array([[math.hypot(a[0] - b[0], a[1] - b[1]) for b in cs] for a in cp])
    r, c = linear_sum_assignment(D)
    pitch = float(np.min(np.diff(sorted(a[0] for a in cp))))                      # шаг между ближайшими ножками фото, px
    mx = float(D[r, c].max()) / max(pitch, 1.0)
    return check('legs_match', mx, R['legs_match'], mx > R['legs_match'], f'ножек {len(cp)}, макс. смещение центра {float(D[r, c].max()):.1f} px при шаге между ножками {pitch:.0f} px (среднее смещение {float(D[r, c].mean()):.1f})')


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


# ---------- задняя стенка по кадрам ----------
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


def edge_slopes(u: np.ndarray, y: np.ndarray, ylo: float, yhi: float, nb: int = 14) -> tuple[float, float] | None:
    """Левая/правая кромка u(y): перцентили по полосам высоты → линейная подгонка → углы от вертикали, градусы (знак +, если верх смещён вправо)."""
    edges = np.linspace(ylo, yhi, nb + 1)
    ys, lo, hi = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        s = (y >= a) & (y < b)
        if s.sum() < 200:
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
def run_sku(sku: str, glb: str | None, photo: str | None, frames: str | None, rules: dict, pose_roots: list[str] | None = None, alpha_dir: str | None = None, role: str = '', vlm_cache: str | None = None, chat=None) -> dict:
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
            rec['checks'] += pose_checks(sku, pose_roots or [])
            rec['checks'] += legs_checks(sku, photo, pose_roots or [], R)
            if photo and os.path.isfile(photo):
                pm = photo_mask(photo)
                fs, az = best_front(surface_points(m, int(R['sil_points'])), pm, R)
                rec['checks'] += sil_checks(fs, pm, R, az)
            else:
                rec['checks'].append(check('sil_extra~', None, R['sil_extra'], False, 'нет маски фото — приближённые силуэтные проверки пропущены'))
    if frames:
        rec['checks'] += back_dup(frames, R)
    if alpha_dir:
        rec['checks'] += mask_checks(alpha_dir, role, R)
    if vlm_cache and frames and rules.get('vlm_judge'):
        import vlm_judge as VJ
        rec['checks'] += VJ.judge(sku, glb, photo, frames, role, rules['vlm_judge'], vlm_cache, chat)
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
    ap.add_argument('--vlm-cache', default='', help='папка кэша оценщика по картинке (включает vlm_judge: платные вызовы шлюза, ответы кэшируются по хешу GLB/фото и версии вопроса)')
    ap.add_argument('--rules', default=RULES)
    a = ap.parse_args()
    rules = load_rules(a.rules)
    skus = [s for s in a.skus.split(',') if s]
    if a.skus_file:
        skus += [ln.split()[0] for ln in open(a.skus_file, encoding='utf-8') if ln.strip()]
    os.makedirs(a.out, exist_ok=True)
    roles = json.load(open(a.roles, encoding='utf-8')) if a.roles else {}
    recs = []
    for s in skus:
        rec = run_sku(s, os.path.join(a.glbs, a.glb_name.format(sku=s)), os.path.join(a.photos, a.photo_name.format(sku=s)), os.path.join(a.frames, s) if a.frames else None, rules, [x for x in a.pose_roots.split(',') if x],
                      os.path.join(a.alpha_root, s) if a.alpha_root else None, roles.get(s, ''), a.vlm_cache or None)
        os.makedirs(os.path.join(a.out, s), exist_ok=True)
        json.dump(rec, open(os.path.join(a.out, s, 'form_checks.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        recs.append(rec)
        print(f"{s} {rec['status']} {rec['flags']}", flush=True)
    json.dump(recs, open(os.path.join(a.out, 'all.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if a.table:
        eye = json.load(open(a.eye, encoding='utf-8')) if a.eye else {}
        open(a.table, 'w', encoding='utf-8').write(table(recs, eye, ['open_edges', 'detached', 'sil_iou', 'sil_extra', 'sil_miss', 'legs', 'sil_extra~', 'sil_miss~', 'holes', 'relief', 'back_dup', 'legs_match', 'relief_graze', 'back_relief', 'back_dup_mask']) + '\n\n' + summary(recs, eye) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
