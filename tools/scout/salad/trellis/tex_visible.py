#!/usr/bin/env python3
"""ЭТАП 6 «ФОТО НА ВИДИМОЕ» (T-20261120-168; план paint-photo-fill-01, § «Этапы», «Проверка на каждом этапе»). Бесплатно, на процессоре (numpy + scipy + trimesh + cv2 + PIL).

Что делает: берёт форму (GLB с развёрткой; текстуры нет — серая заготовка), вырезку фото и КАМЕРУ ФОТО ОТ ЭТАПА 4 (р.2, `pose_fit.py`, T-112: перспективная; в папке прогона лежат
`stages/render_view0/{ids,uv,aoi_cos16,mask}`, `stages/manifest.json`, `stage_loss.json` с матрицей фото→кадр) и каждому тексель-у, который эта камера видит (первая грань вдоль луча, угол
к камере лучше `COS_MIN`, внутри силуэта фото с отступом от края), присваивает цвет фото в точке его проекции. Прямой перенос, без нейросети: цвет и узор видимого бока — настоящие, не нарисованные.
Своей камеры здесь нет (решение директора 20.11): камера — вход этапа. Невидимое не трогается (серая заготовка) — его закрывает этап 7 (`tex_fill.py`, р.3).
Выход этапа — `<run>/<sku>/06-visible/`: `visible.glb`, `known.png` (маска «тексель взят с фото»), `check.json` (через `paint_stage.write_check`), `frame.png` (фото | кадр с камеры фото | ±40°).

Qwen-правка — ТОЛЬКО если прямой перенос не лёг: гейт не прошёл → `check.json`: passed=false, `extra.needs_qwen=true`, причина по меркам (запасной путь — отдельным шагом, после камеры).
Гейт (все пороги — `GATE`; ПРОВИЗОРНЫЕ до замера на 12 трудных, в план — только после замера):
  silhouette_iou   — совпадение силуэта фото и формы в кадре камеры (`iou_frame` этапа 4; план: ≥ 0,85, иначе камере не верим → дальше не идёт);
  known_share      — доля занятых текселей, взятых с фото (честный охват; ниже порога — нечего переносить);
  edge_corr / lab_dE — перенос не потерян при записи: края и медиана Lab «фото ↔ кадр по новой текстуре» (по частям — часть = геометрия GLB, пока нет масок р.1).
Справочно (без порога): `edge_agree` этапа 4 — совпадение внутренних кромок формы и фото.
ID товаров в код не попадают.

  python tex_visible.py <shape.glb> <photo.rgba.png> <pose_run> <run_dir> <sku>      # pose_run — папка `fit_pose` этапа 4 (stage_loss.json + stages/)
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.dirname(HERE)
SCOUT = os.path.dirname(SALAD)
sys.path[:0] = [HERE, SALAD, SCOUT]

import tex_coverage as TC  # noqa: E402
import paint_stage as PS  # noqa: E402
import crease_mask as CM  # noqa: E402     # мерки полос у изломов и карта уверенности текселя (T-194/1, T-194/2); текстуру не меняет

def _rules() -> dict:
    try:
        return json.load(open(os.path.join(SCOUT, 'rules', 'tex-visible.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


R = _rules()
COS_MIN = float(R.get('cos_min', 0.40))          # cos угла к лучу: 66° и больше — вскользь, не берём (rules/tex-visible.json)
DEPTH_JUMP = float(R.get('depth_jump_px', 12.0))  # разрыв глубины между соседними пикселями кадра больше стольких px_len — край складки/щели: полоса вокруг не берётся
MM_GAP = float(R.get('multi_material_gap_L', 25.0))      # бимодальный L* внутри части → мерка перёд↔бок N/A
MM_SHARE = float(R.get('multi_material_min_share', 0.20))
EDGE_BG_PX = float(os.environ.get('EDGE_BG_PX', R.get('edge_bg_reject_px', 8.0)))   # 0 — правило выкл.
EDGE_BG_MEASURE = float(R.get('edge_bg_measure_px', 6.0))
EDGE_BG_DL = float(R.get('edge_bg_dL', 6.0))
EDGE_BG_WHITE_L = float(R.get('edge_bg_white_L', 90.0))   # медиана ядра светлее — ткань белая, мерка и правило каймы слепы (N/A)
FRAYED_PX = int(R.get('frayed_px', 3))           # рваность: известный пиксель в этих px от неизвестного внутри силуэта
EDGE_BG_MAX = float(R.get('edge_bg_share_max', 0.05))
DEPTH_MED = int(R.get('depth_median_px', 7))   # медиана карты глубины перед поиском разрыва: на рёбрах треугольников в ней пятна-выбросы
DEPTH_BAND = int(R.get('depth_band_px', 2))      # ширина этой полосы, пикселей кадра
COS_FULL = float(R.get('cos_full', 0.60))         # полный вес с этого косинуса; между COS_MIN и COS_FULL — плавная передача заготовке
EDGE_FRAC = 4.0 / 480   # отступ от силуэта фото внутрь, доли стороны кадра: вес растёт от 0 до 1 (там фон и ореол)
GUTTER = 6              # желоб вокруг островков, пикселей текстуры (билинейная выборка у шва не берёт серый фон)
EDGE_ERODE = float(R.get('edge_erode_px', 2.0))        # жёсткая эрозия маски фото: пиксели ближе к краю силуэта не берутся совсем (там белый фон и ореол; директор 21.11)
W_TAKE = 0.25           # вес меньше — тексель не берём (остаётся прежним), вес выше — цвет фото целиком, без подмеса светлой заготовки (иначе светлые полосы на вскользь видимых краях)
HOLE_R = 2.5            # дыры между взятыми текселями (пикселей кадра реже текселей) закрываются ближайшим взятым не дальше этого, текселей
DEPTH_PX = 3.0          # допуск «тексель не заслонён»: расхождение глубины точки и буфера глубины камеры не больше стольких пикселей предмета (у косых граней — шире)
GREY = 128
REG_FIT = bool(R.get('reg_fit', True))                  # подгонка сдвига регистрации по силуэту (T-197/2)
REG_MAX_PX = float(R.get('reg_max_shift_px', 3.0))      # дальше этого сдвиг не ищем и не берём (больше — другая беда: форма/камера, не подпиксель)
REG_SIGMA = float(R.get('reg_sigma_px', 1.0))           # размытие маски и альфы перед сравнением: гладкая цель → подпиксельный минимум
REG_MIN_GAIN = float(R.get('reg_min_gain', 0.10))       # сдвиг принят, если невязка силуэта упала не менее чем на эту долю (на боевых силуэт искажён формой: слабые подгонки шумны)
PHOTO_INTERP = str(R.get('photo_interp', 'lanczos'))   # перевод фото в кадр: lanczos (T-197: линейная теряла ~⅓ мелкого контраста при растяжке фото ×2) | cubic | linear
SAMPLE_ORDER = int(R.get('sample_order', 3))             # выборка цвета в тексель из кадра: порядок сплайна (3 — бикубика; 1 — билинейная, теряла 15–40 % мелкого контраста; T-197)
FRONT_COS = 0.80       # мерка света «перёд↔бок»: перёд — cos ≥ этого, бок — от cos_min до SIDE_COS
SIDE_COS = 0.65
GATE = {                # (порог, op) — провизорно, см. шапку
    'silhouette_iou': (0.85, '>='),
    'known_share': (0.15, '>='),
    'edge_corr': (0.90, '>='),
    'lab_dE': (3.0, '<='),
    'edge_bg_share': (EDGE_BG_MAX, '<='),      # светлая кайма/ореол вырезки среди взятых у края (нет достаточно краевых пикселей — мерки нет, это не отказ)
}


# ── вход ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def load_shape(path: str) -> list:
    """GLB → геометрии {'V','F','UV','tex'}: как `tex_coverage.load_geoms`, но без текстуры берётся серая заготовка 2048² (форма из sg_prep_shape её не несёт)."""
    import trimesh
    sc = trimesh.load(path, force='scene', process=False)
    out = []
    for name, g in sc.geometry.items():
        try:
            g.apply_transform(sc.graph.get(name)[0])
        except Exception:  # noqa: BLE001
            pass
        vis = getattr(g, 'visual', None)
        uv = getattr(vis, 'uv', None)
        if uv is None:
            raise ValueError(f'{os.path.basename(path)}: у геометрии «{name}» нет развёртки')
        mat = getattr(vis, 'material', None)
        im = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
        if im is not None and min(im.size) < 64:                 # заглушка 1–2 пикселя, которую trimesh подставляет форме без текстуры, — это не текстура
            im = None
        tex = np.asarray(im.convert('RGB'), np.uint8) if im is not None else np.full((2048, 2048, 3), GREY, np.uint8)
        if tex.shape[0] != tex.shape[1]:
            tex = np.asarray(Image.fromarray(tex).resize((max(tex.shape[:2]),) * 2, Image.BILINEAR))
        out.append({'name': name, 'V': np.asarray(g.vertices, np.float64), 'F': np.asarray(g.faces, np.int64), 'UV': np.asarray(uv, np.float64), 'tex': tex, 'has_tex': im is not None})
    if not out:
        raise ValueError(f'{os.path.basename(path)}: в файле нет геометрии')
    return out


def load_stage(pose_run: str) -> dict:
    """Камера этапа 4 из папки прогона `pose_fit.fit_pose`: растр вида (id грани, UV, cos, маска), матрица фото→кадр, числа камеры. Нет `ids.npz` — прогон старше коммита eabaff04, камеру надо пересчитать."""
    rd = os.path.join(pose_run, 'stages', 'render_view0')
    need = [os.path.join(rd, f) for f in ('ids.npz', 'uv.npz', 'depth.npz', 'aoi_cos16.png', 'mask.png')] + [os.path.join(pose_run, 'stage_loss.json')]
    miss = [os.path.basename(p) for p in need if not os.path.exists(p)]
    if miss:
        raise FileNotFoundError(f'{pose_run}: нет {", ".join(miss)} — камеру этапа 4 надо (пере)считать pose_fit.fit_pose')
    sl = json.load(open(os.path.join(pose_run, 'stage_loss.json'), encoding='utf-8'))
    ids = np.load(os.path.join(rd, 'ids.npz'))['ids']
    uv = np.load(os.path.join(rd, 'uv.npz'))['uv']
    dz = np.load(os.path.join(rd, 'depth.npz'))
    depth, px_len = dz['depth'], float(dz['px_len'])
    cos = np.asarray(Image.open(os.path.join(rd, 'aoi_cos16.png')), np.float32) / 65535.0
    mask = np.asarray(Image.open(os.path.join(rd, 'mask.png'))) > 127
    px = ids.shape[0]
    P = np.array(sl['registration']['P'], np.float64).reshape(3, 3)
    return {'ids': ids, 'uv': uv, 'depth': depth, 'px_len': px_len, 'cos': cos, 'mask': mask, 'px': px, 'P': P, 'camera': sl.get('camera'), 'iou_frame': sl['registration'].get('iou'), 'pose_run': pose_run}


def photo_to_frame(photo_rgba: np.ndarray, P: np.ndarray, px: int) -> tuple[np.ndarray, np.ndarray]:
    """Фото в кадр камеры по обратной карте P (кадр → пиксель фото; как `stage_loss.warp_inv`). Соглашение пикселя — как у `pose_fit.canvas_P`: P угловая (кадр i → фото s·i + x0, без поправки 0,5·(s−1) на центры пикселей); камера этапа 4 подогнана под неё по силуэту, так что фото и растр согласованы. Менять P на «центровую» нельзя без пересчёта камер (T-197/3: при масштабе s≠1 разница = (1−s)/(2s) px кадра, ≈0,5 px при s=0,5). Цвет — с учётом альфы (без ореола фона). Возвращает (rgb uint8 px×px×3, маска фото в кадре)."""
    import cv2
    a = photo_rgba[..., 3:4].astype(np.float32) / 255.0
    src = np.concatenate([photo_rgba[..., :3].astype(np.float32) * a, a], axis=2)
    fl = {'lanczos': cv2.INTER_LANCZOS4, 'cubic': cv2.INTER_CUBIC, 'linear': cv2.INTER_LINEAR}[PHOTO_INTERP] | cv2.WARP_INVERSE_MAP
    w = cv2.warpAffine(src, np.asarray(P, np.float64)[:2], (px, px), flags=fl, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    al = w[..., 3]
    rgb = np.where(al[..., None] > 1e-3, w[..., :3] / np.maximum(al[..., None], 1e-3), 0.0)
    return np.clip(rgb + 0.5, 0, 255).astype(np.uint8), al > 0.5


def _shift_P(P: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Матрица кадр → фото для случая, когда содержимое фото в кадре сдвинуто на (dx, dy) пикселей кадра."""
    T = np.array([[1.0, 0.0, -dx], [0.0, 1.0, -dy], [0.0, 0.0, 1.0]])
    return np.asarray(P, np.float64) @ T


def fit_registration(photo_rgba: np.ndarray, P: np.ndarray, mask: np.ndarray, max_shift: float = None, sigma: float = None) -> dict:
    """Подпиксельный сдвиг регистрации по силуэту (T-197/2): минимум невязки между альфой фото в кадре и маской растра камеры, обе размыты σ.
    Поиск от грубого к тонкому (шаг 1 → 0,25 → 0,0625 px) в пределах max_shift. Только сдвиг: масштаб/поворот и форма не трогаются.
    Возвращает {'dx','dy','cost0','cost','gain','P'}: (dx,dy) — поправка, на которую надо сдвинуть фото в кадре, P — матрица кадр → фото с поправкой; gain — доля, на которую упала невязка (0 — сдвиг не нужен)."""
    import cv2
    max_shift = REG_MAX_PX if max_shift is None else max_shift
    sigma = REG_SIGMA if sigma is None else sigma
    px = mask.shape[0]
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return {'dx': 0.0, 'dy': 0.0, 'cost0': 0.0, 'cost': 0.0, 'gain': 0.0, 'P': np.asarray(P, np.float64)}
    pad = int(max_shift + 4 * sigma + 4)
    y0, y1, x0, x1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, px), max(xs.min() - pad, 0), min(xs.max() + pad + 1, px)
    m = cv2.GaussianBlur(mask[y0:y1, x0:x1].astype(np.float32), (0, 0), sigma)
    al = photo_rgba[..., 3].astype(np.float32) / 255.0
    crop = np.array([[1.0, 0.0, x0], [0.0, 1.0, y0], [0.0, 0.0, 1.0]])             # координаты окна → кадр

    def cost(dx: float, dy: float) -> float:
        M = _shift_P(P, dx, dy) @ crop
        w = cv2.warpAffine(al, M[:2], (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return float(((cv2.GaussianBlur(w, (0, 0), sigma) - m) ** 2).sum())

    c0 = cost(0.0, 0.0)
    best = (c0, 0.0, 0.0)
    for step, span in ((1.0, max_shift), (0.25, 1.0), (0.0625, 0.25)):
        cx, cy = best[1], best[2]
        n = int(round(span / step))
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                dx, dy = cx + i * step, cy + j * step
                if abs(dx) > max_shift or abs(dy) > max_shift or (i == 0 and j == 0 and step != 1.0):
                    continue
                c = cost(dx, dy)
                if c < best[0]:
                    best = (c, dx, dy)
    gain = (c0 - best[0]) / max(c0, 10.0)                           # 10 — пол невязки (px²): у почти идеальной регистрации доля не раздувается
    return {'dx': best[1], 'dy': best[2], 'cost0': c0, 'cost': best[0], 'gain': gain, 'P': _shift_P(P, best[1], best[2])}


# ── перенос ────────────────────────────────────────────────────────────────────────────────────────────────────────

def face_maps(st: dict, nF: int, off: int = 0) -> dict:
    """Для каждой видимой грани — линейная карта «координата развёртки → пиксель кадра» (x, y) и глубина Z, подогнанные по пикселям растра камеры этой грани (метод наименьших квадратов, центрированно).
    Так тексель (любой плотности — текстура может быть гуще кадра) находит СВОЮ точку на фото; растр id/UV/глубины — то, что отдаёт этап 4. Грани с < 3 пикселей или вырожденные — `ok=False`."""
    ids, uv, depth, mask = st['ids'], st['uv'], st['depth'], st['mask']
    ys, xs = np.nonzero(mask & (ids >= off) & (ids < off + nF))
    f = (ids[ys, xs] - off).astype(np.int64)
    u, v = uv[ys, xs, 0].astype(np.float64), uv[ys, xs, 1].astype(np.float64)
    X, Y, Z = xs + 0.5, ys + 0.5, depth[ys, xs].astype(np.float64)
    cnt = np.bincount(f, minlength=nF).astype(np.float64)
    c1 = np.maximum(cnt, 1.0)
    mu, mv = np.bincount(f, u, nF) / c1, np.bincount(f, v, nF) / c1
    mx, my, mz = np.bincount(f, X, nF) / c1, np.bincount(f, Y, nF) / c1, np.bincount(f, Z, nF) / c1
    du, dv = u - mu[f], v - mv[f]
    Suu, Suv, Svv = np.bincount(f, du * du, nF), np.bincount(f, du * dv, nF), np.bincount(f, dv * dv, nF)
    det = Suu * Svv - Suv * Suv
    ok = (cnt >= 3) & (det > 1e-3 * np.maximum(Suu * Svv, 1e-30)) & (Suu * Svv > 0)
    d1 = np.where(ok, det, 1.0)
    out = {'ok': ok, 'mu': mu, 'mv': mv, 'mx': mx, 'my': my, 'mz': mz, 'cos': np.bincount(f, st['cos'][ys, xs].astype(np.float64), nF) / c1, 'cnt': cnt}
    for name, val in (('x', X - mx[f]), ('y', Y - my[f]), ('z', Z - mz[f])):
        sa, sb = np.bincount(f, du * val, nF), np.bincount(f, dv * val, nF)
        out['a' + name] = (sa * Svv - sb * Suv) / d1
        out['b' + name] = (sb * Suu - sa * Suv) / d1
    return out


def _de(lab: np.ndarray, ref: np.ndarray) -> np.ndarray:
    import recolor_lp as LP
    flat = lab.reshape(-1, 3)
    return LP.de2000(flat, np.broadcast_to(np.asarray(ref, np.float64), flat.shape)).reshape(lab.shape[:-1])


def bg_like(lab: np.ndarray, med: np.ndarray) -> np.ndarray:
    """Цвет «как фон вырезки»: ближе к белому, чем к цвету ткани (медиана ядра), и светлее ткани на EDGE_BG_DL L*."""
    white = _lab(np.full((1, 1, 3), 255, np.uint8))[0, 0]
    return (_de(lab, white) < _de(lab, med)) & (lab[..., 0] > med[0] + EDGE_BG_DL)


def core_median(st: dict, prgb: np.ndarray, pmask: np.ndarray) -> np.ndarray:
    """Цвет ткани по фото: медиана Lab пикселей прямо к камере (cos >= 0.8), глубже 12 px от края фото и силуэта растра."""
    from scipy.ndimage import distance_transform_edt
    core = st['mask'] & pmask & (st['cos'] >= 0.8) & (distance_transform_edt(pmask) > 12) & (distance_transform_edt(st['mask']) > 12)
    if core.sum() < 100:
        core = st['mask'] & pmask & (st['cos'] >= TV_FALLBACK_COS)
    return np.median(_lab(prgb)[core], axis=0)


TV_FALLBACK_COS = 0.5


def edge_bg_fringe(st: dict, prgb: np.ndarray, pmask: np.ndarray) -> np.ndarray:
    """Пиксели кадра у края альфы фото (<= EDGE_BG_PX), чей цвет — фон вырезки, а не ткань: в перенос не идут (общее правило, не по товару)."""
    if EDGE_BG_PX <= 0:
        return np.zeros(pmask.shape, bool)
    from scipy.ndimage import distance_transform_edt
    med = core_median(st, prgb, pmask)
    if med[0] > EDGE_BG_WHITE_L:
        return np.zeros(pmask.shape, bool)
    return bg_like(_lab(prgb), med) & (distance_transform_edt(pmask) <= EDGE_BG_PX) & pmask


def known_px(geoms: list, st: dict, tr: dict) -> np.ndarray:
    """Маска кадра: пиксели силуэта растра, чей тексель взят из фото (known)."""
    ids, uv, mask = st['ids'], st['uv'], st['mask']
    offs = np.cumsum([0] + [len(g['F']) for g in geoms])
    gid = np.full(ids.shape, -1, np.int32)
    gid[ids >= 0] = np.searchsorted(offs, ids[ids >= 0], side='right') - 1
    kn = np.zeros(mask.shape, bool)
    for gi, k in enumerate(tr['known']):
        T = k.shape[0]
        ys, xs = np.nonzero((gid == gi) & mask)
        tx = np.clip(np.floor(uv[ys, xs, 0] * T).astype(np.int64), 0, T - 1)
        ty = np.clip(np.floor(uv[ys, xs, 1] * T).astype(np.int64), 0, T - 1)
        kn[ys, xs] = k[ty, tx]
    return kn


def frayed_share(kn: np.ndarray, mask: np.ndarray, px: int = FRAYED_PX) -> dict:
    """Рваность края известного: доля взятых пикселей кадра, у которых в пределах px пикселей внутри силуэта есть неизвестный (щели, рваная кромка, брызги разрыва глубины).
    Не порог, а мерка для сравнения форм/камер (Sakura: v3 0,237 → v4 0,113); < 200 взятых — мерки нет."""
    from scipy.ndimage import binary_dilation
    n = int(kn.sum())
    if n < 200:
        return {}
    unk = mask & ~kn
    fr = kn & binary_dilation(unk, iterations=px)
    return {'frayed_share': round(float(fr.sum() / n), 4), 'frayed_px': int(fr.sum()), 'frayed_known_px': n}


def edge_bg_share(geoms: list, st: dict, prgb: np.ndarray, pmask: np.ndarray, tr: dict, after: np.ndarray) -> dict:
    """Автопроверка: доля «светлых как фон» среди ВЗЯТЫХ пикселей кадра у края (<= EDGE_BG_MEASURE px от края альфы фото или силуэта растра)."""
    from scipy.ndimage import distance_transform_edt
    mask = st['mask']
    kn = known_px(geoms, st, tr)
    near = (np.minimum(distance_transform_edt(pmask), distance_transform_edt(mask)) <= EDGE_BG_MEASURE) & kn
    med = core_median(st, prgb, pmask)
    if med[0] > EDGE_BG_WHITE_L:
        return {'edge_bg_share': None, 'edge_known_px': int(near.sum()), 'edge_bg_px': 0, 'edge_bg_na': f'N/A: белая ткань (медиана ядра L* {med[0]:.1f} > {EDGE_BG_WHITE_L:g}), мерка слепа'}
    bg = bg_like(_lab(after), med) & near
    n = int(near.sum())
    return {'edge_bg_share': None if n < 200 else round(float(bg.sum() / n), 4), 'edge_known_px': n, 'edge_bg_px': int(bg.sum())}


def depth_band(st: dict) -> np.ndarray:
    """Маска кадра: пиксели у разрыва глубины (край складки, щель между подушками, торец за выступом) шире DEPTH_BAND px — фото там берёт тень щели, а не поверхность."""
    from scipy.ndimage import binary_dilation, median_filter
    d0 = st['depth'].astype(np.float64)
    ok = (d0 > 0) & st['mask']
    d = median_filter(np.where(d0 > 0, d0, float(np.median(d0[ok])) if ok.any() else 0.0), size=max(DEPTH_MED, 1)) if DEPTH_MED > 1 else d0
    lim = max(float(st.get('px_len') or 0.0), 1e-6) * DEPTH_JUMP
    jump = np.zeros(d.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        a, b = d[: d.shape[0] - dy, : d.shape[1] - dx], d[dy:, dx:]
        both = ok[: d.shape[0] - dy, : d.shape[1] - dx] & ok[dy:, dx:]
        j = both & (np.abs(a - b) > lim)
        jump[: d.shape[0] - dy, : d.shape[1] - dx] |= j
        jump[dy:, dx:] |= j
    if DEPTH_BAND <= 0:
        return jump
    return binary_dilation(jump, iterations=DEPTH_BAND)


def transfer(geoms: list, st: dict, prgb: np.ndarray, pmask: np.ndarray, cos_min: float = COS_MIN) -> dict:
    """Новые текстуры + маски «известно» по геометриям. Каждый занятый тексель идёт на фото СВОЕЙ точкой (карта грани, `face_maps`), берётся, если: его грань видна с углом лучше `cos_min`,
    глубина точки совпадает с буфером глубины камеры (не заслонена), точка внутри силуэта фото с отступом от края. Цвет — билинейно с фото; невидимое остаётся прежним."""
    from scipy.ndimage import distance_transform_edt, map_coordinates
    ids, depth = st['ids'], st['depth']
    px = st['px']
    offs = np.cumsum([0] + [len(g['F']) for g in geoms])
    if ids.max() >= offs[-1]:
        raise ValueError(f'растр камеры ссылается на грань {int(ids.max())}, в форме граней {int(offs[-1])} — форма не та, что у камеры')
    dist_edge = distance_transform_edt(pmask)
    nogo = depth_band(st)
    n_nogo = int((nogo & st['mask']).sum())
    fringe = edge_bg_fringe(st, prgb, pmask)
    nogo = nogo | fringe
    crr = CM.load_rules()
    crs = CM.crease_shadow(prgb, pmask, st, geoms, crr)                         # полоса изломов в кадре — для мерки и уверенности (текстуру не трогает)
    cf = CM.frame_confidence(prgb, pmask, st, crs, crr)                    # уверенность пикселя: у излома и блика ниже (шаг сведения швов)
    edge_px = max(EDGE_FRAC * px, 1.0)
    z_eps = max(float(st.get('px_len') or 0.0), 1e-6) * DEPTH_PX
    texs, knowns, confs, stats = [], [], [], []
    for gi, g in enumerate(geoms):
        T = int(g['tex'].shape[0])
        F, UV = g['F'], g['UV']
        fm = face_maps(st, len(F), int(offs[gi]))
        xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
        fid, _ = TC.raster(xy, F, T)
        fid = fid.reshape(T, T)
        occ = fid >= 0
        ty, tx = np.nonzero(occ)
        f = fid[ty, tx].astype(np.int64)
        ut, vt = (tx + 0.5) / T, (ty + 0.5) / T
        du, dv = ut - fm['mu'][f], vt - fm['mv'][f]
        x = fm['mx'][f] + fm['ax'][f] * du + fm['bx'][f] * dv
        y = fm['my'][f] + fm['ay'][f] * du + fm['by'][f] * dv
        z = fm['mz'][f] + fm['az'][f] * du + fm['bz'][f] * dv
        inside = fm['ok'][f] & (x >= 0.5) & (x <= px - 0.5) & (y >= 0.5) & (y <= px - 0.5)
        xi, yi = np.clip(np.floor(x).astype(np.int64), 0, px - 1), np.clip(np.floor(y).astype(np.int64), 0, px - 1)
        front = np.abs(z - depth[yi, xi]) <= z_eps * np.maximum(1.0, 1.0 / np.maximum(fm['cos'][f], 0.2))       # у косых граней глубина меняется быстрее по пикселю — допуск растёт
        cs = fm['cos'][f]
        w_ang = np.clip((cs - cos_min) / max(COS_FULL - cos_min, 1e-6), 0.0, 1.0)
        w_edge = np.clip((map_coordinates(dist_edge.astype(np.float32), [y - 0.5, x - 0.5], order=1, mode='nearest') - EDGE_ERODE) / edge_px, 0.0, 1.0)
        w = np.where(inside & front & (depth[yi, xi] > 0) & pmask[yi, xi] & ~nogo[yi, xi], w_ang * w_edge, 0.0)
        use = w >= W_TAKE
        col = np.clip(np.stack([map_coordinates(prgb[..., c].astype(np.float32), [y[use] - 0.5, x[use] - 0.5], order=SAMPLE_ORDER, mode='nearest') for c in range(3)], 1), 0.0, 255.0)   # бикубика выходит за 0..255 у резких границ
        tex = g['tex'].astype(np.float64).copy()
        sel = (ty[use], tx[use])
        tex[sel] = col
        wmap = np.zeros((T, T), np.float64)
        wmap[ty, tx] = w
        known = wmap >= W_TAKE
        cmap = np.zeros((T, T), np.float32)                              # уверенность известных текселей 0…1: угол обзора × край силуэта × (излом, блик)
        cmap[ty, tx] = (w * cf[yi, xi]).astype(np.float32)
        cmap[~known] = 0.0
        n_face = int(known.sum())
        ys, xs = np.nonzero(st['mask'] & (ids >= offs[gi]) & (ids < offs[gi + 1]))             # проход 2: пиксели растра камеры — каждый на тексель СВОЕЙ развёртки (грани мельче пикселя карту грани не строят)
        wp = np.clip((st['cos'][ys, xs] - cos_min) / max(COS_FULL - cos_min, 1e-6), 0.0, 1.0) * np.clip((dist_edge[ys, xs] - EDGE_ERODE) / edge_px, 0.0, 1.0) * pmask[ys, xs] * (~nogo[ys, xs])
        keep = wp >= W_TAKE
        ys, xs, wp = ys[keep], xs[keep], wp[keep]
        tpx = np.clip(np.floor(st['uv'][ys, xs, 0] * T).astype(np.int64), 0, T - 1)
        tpy = np.clip(np.floor(st['uv'][ys, xs, 1] * T).astype(np.int64), 0, T - 1)
        flat = tpy * T + tpx
        sw = np.bincount(flat, wp, T * T).reshape(T, T)
        cnt2 = np.bincount(flat, None, T * T).reshape(T, T)
        scf = np.bincount(flat, wp * cf[ys, xs], T * T).reshape(T, T)
        scol = np.stack([np.bincount(flat, wp * prgb[ys, xs, c].astype(np.float64), T * T).reshape(T, T) for c in range(3)], 2)
        take = occ & ~known & (sw >= W_TAKE)
        tex[take] = scol[take] / sw[take][:, None]
        cmap[take] = (scf[take] / np.maximum(cnt2[take], 1)).astype(np.float32)
        known = known | take
        n_splat = int(take.sum())
        hd, (hy, hx) = distance_transform_edt(~known, return_distances=True, return_indices=True)       # дыры между пикселями: ближайший взятый тексель не дальше HOLE_R
        fill = occ & ~known & (hd <= HOLE_R)
        tex[fill] = tex[hy[fill], hx[fill]]
        cmap[fill] = cmap[hy[fill], hx[fill]] * float(crr['conf_fill'])     # дыра — цвет соседа, уверенность вдвое ниже
        known = known | fill
        n_fill = int(fill.sum())
        gd, (iy, ix) = distance_transform_edt(~occ, return_distances=True, return_indices=True)     # желоб: ближайший занятый тексель на GUTTER пикселей наружу
        ring = (~occ) & (gd <= GUTTER)
        tex[ring] = tex[iy[ring], ix[ring]]
        texs.append(np.clip(tex + 0.5, 0, 255).astype(np.uint8))
        knowns.append(known)
        confs.append(np.where(known, cmap, 0.0).astype(np.float32))
        stats.append({'name': g['name'], 'T': T, 'occupied': int(occ.sum()), 'known': int(known.sum()), 'faces_ok': int(fm['ok'].sum()), 'faces_seen': int((fm['cnt'] > 0).sum()), 'texels_taken': int(use.sum()), 'known_facemap': n_face, 'known_splat': n_splat, 'known_filled': n_fill})
    return {'tex': texs, 'known': knowns, 'conf': confs, 'stats': stats, 'depth_band_share': round(n_nogo / max(int(st['mask'].sum()), 1), 4), 'edge_bg_fringe_px': int((fringe & st['mask']).sum()), 'crease': crs}


def write_glb(geoms: list, texs: list, dst: str) -> None:
    """Те же форма и развёртка, текстура baseColor — новая (геометрии пишутся как есть, без слияния вершин)."""
    import trimesh
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    sc = trimesh.Scene()
    for g, t in zip(geoms, texs):
        m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
        m.visual = TextureVisuals(uv=g['UV'], material=PBRMaterial(baseColorTexture=Image.fromarray(t), metallicFactor=0.0, roughnessFactor=0.9))
        sc.add_geometry(m, node_name=g['name'], geom_name=g['name'])
    sc.export(dst)


# ── мерки ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _lab(rgb8: np.ndarray) -> np.ndarray:
    import recolor_lp as LP
    return LP.lab_f(rgb8)      # lab_f сам принимает sRGB 0–255 (прежний s2l перед ним сводил Lab к нулю: lab_dE и front_side были пустыми числами)


def _sobel(L: np.ndarray) -> np.ndarray:
    from scipy.ndimage import gaussian_filter, sobel
    b = gaussian_filter(L.astype(np.float32), 1.5)
    return np.hypot(sobel(b, axis=1), sobel(b, axis=0))


def frame_from_tex(st: dict, geoms: list, texs: list) -> np.ndarray:
    """Кадр камеры, как его даст НОВАЯ текстура: цвет по UV растра камеры (проверка, что запись текстуры и развёртка держат перенос)."""
    ids, uv, mask = st['ids'], st['uv'], st['mask']
    offs = np.cumsum([0] + [len(g['F']) for g in geoms])
    out = np.full(ids.shape + (3,), 255, np.uint8)
    gid = np.full(ids.shape, -1, np.int32)
    gid[ids >= 0] = np.searchsorted(offs, ids[ids >= 0], side='right') - 1
    for gi, t in enumerate(texs):
        T = t.shape[0]
        ys, xs = np.nonzero((gid == gi) & mask)
        tx_ = np.clip(np.floor(uv[ys, xs, 0] * T).astype(np.int64), 0, T - 1)
        ty_ = np.clip(np.floor(uv[ys, xs, 1] * T).astype(np.int64), 0, T - 1)
        out[ys, xs] = t[ty_, tx_]
    return out


def hatch(tex: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Только для показа: непросмотренные тексели — нейтральная серая штриховка (цвет заготовки не путать с цветом товара)."""
    out = tex.copy()
    ty, tx = np.mgrid[0: tex.shape[0], 0: tex.shape[1]]
    pat = np.where(((tx + ty) // 6) % 2 == 0, 205, 170).astype(np.uint8)
    miss = ~known
    out[miss] = pat[miss][:, None]
    return out


def multi_material(L: np.ndarray) -> bool:
    """L* пикселей части бимодален: два заметных пика (каждый >= MM_SHARE/2 части в бине 5 L*), пики отстоят >= MM_GAP, между ними провал глубже половины меньшего пика.
    Скошенное распределение одной ткани с хвостом (узор, тени) под это не попадает; признак по пикселям части, не по товару."""
    if L.size < 600:
        return False
    h = np.histogram(L, bins=20, range=(0.0, 100.0))[0] / float(L.size)
    pk = [i for i in range(20) if h[i] >= MM_SHARE / 2 and h[i] >= (h[i - 1] if i else 0) and h[i] >= (h[i + 1] if i < 19 else 0)]
    for i in pk:
        for j in pk:
            if j > i and (j - i) * 5.0 >= MM_GAP and h[i + 1:j].min() < 0.5 * min(h[i], h[j]):
                return True
    return False


def metrics(geoms, st, prgb, pmask, tr, after: np.ndarray, cos_min: float) -> dict:
    from scipy.ndimage import binary_erosion
    import recolor_lp as LP
    occ = sum(s['occupied'] for s in tr['stats'])
    kn = sum(s['known'] for s in tr['stats'])
    iou = st.get('iou_frame')
    A, S = pmask, st['mask']
    if iou is None:
        iou = float((A & S).sum() / max((A | S).sum(), 1))
    out = {'silhouette_iou': round(float(iou), 4), 'known_share': round(kn / max(occ, 1), 4)}
    both = binary_erosion(S, iterations=3) & binary_erosion(A, iterations=3) & (st['cos'] >= cos_min)
    out['both_px'] = int(both.sum())
    if both.sum() > 200:
        Lp, La = _lab(prgb), _lab(after)
        ep, ea = _sobel(Lp[..., 0]), _sobel(La[..., 0])
        out['edge_corr'] = round(float(np.corrcoef(ep[both], ea[both])[0, 1]), 4)
        out['lab_dE'] = round(float(np.median(LP.de2000(Lp[both], La[both]))), 3)
        offs = np.cumsum([0] + [len(g['F']) for g in geoms])
        gid = np.zeros(st['ids'].shape, np.int16)
        gid[st['ids'] >= 0] = np.searchsorted(offs, st['ids'][st['ids'] >= 0], side='right') - 1
        per = {}
        for gi, g in enumerate(geoms):
            mk = both & (gid == gi)
            if mk.sum() > 100:
                per[g['name']] = round(float(np.median(LP.de2000(Lp[mk], La[mk]))), 3)
        out['lab_dE_by_part'] = per
        # независимая мерка света: одна ткань, перёд против бока — медианы Lab фото на пикселях «перёд» (cos ≥ FRONT_COS) и «бок» (cos между COS_MIN и SIDE_COS) внутри части, без полосы разрыва глубины
        free = both & ~depth_band(st)
        fs = {}
        for gi, g in enumerate(geoms):
            mk = free & (gid == gi)
            fr, sd = mk & (st['cos'] >= FRONT_COS), mk & (st['cos'] >= cos_min) & (st['cos'] < SIDE_COS)
            if fr.sum() > 300 and sd.sum() > 300:
                mf, ms = np.median(Lp[fr], axis=0), np.median(Lp[sd], axis=0)
                if multi_material(Lp[mk][:, 0]):
                    fs[g['name']] = {'dE': None, 'n_a': 'N/A: часть из разных материалов (бимодальный L* внутри части)', 'dE_raw': round(float(LP.de2000(mf[None], ms[None])[0]), 3), 'n_front': int(fr.sum()), 'n_side': int(sd.sum())}
                    continue
                fs[g['name']] = {'dE': round(float(LP.de2000(mf[None], ms[None])[0]), 3), 'dL': round(float(mf[0] - ms[0]), 2), 'n_front': int(fr.sum()), 'n_side': int(sd.sum())}
        out['front_side'] = fs
    out.update(frayed_share(known_px(geoms, st, tr), st['mask']))               # только мерка (порога нет): сравнение форм v3/v4 и камер
    eb = edge_bg_share(geoms, st, prgb, pmask, tr, after)
    out.update({k: v for k, v in eb.items() if v is not None})                   # None (мало краевых или белая ткань) — мерки нет; gate её тогда не требует
    return out


def gate(m: dict, thin_pass: bool = False) -> tuple[dict, list]:
    """Мерки с порогами (формат paint_stage) и список причин отказа. Нет измерения — не «ок». thin_pass — тонкий предмет, камера легла по контуру: IoU площади не мерка."""
    mm, why = {}, []
    for k, (thr, op) in GATE.items():
        if k == 'edge_bg_share' and k not in m:
            continue
        mm[k] = {'value': m.get(k), 'threshold': thr, 'op': op}
        if k == 'silhouette_iou' and thin_pass and k in m:
            mm[k]['thin_not_a_measure'] = True
            continue
        if k not in m or not PS.judge(m[k], op, thr):
            why.append(f'{k} {m.get(k, "нет измерения")} (нужно {op} {thr})')
    return mm, why


# ── кадр ───────────────────────────────────────────────────────────────────────────────────────────────────────────

SIDE_DEG = 40.0


def side_view_angles(cam: dict | None, side_deg: float = SIDE_DEG) -> dict:
    """Ракурсы «слева/справа» для листа этапа: от азимута НАЙДЕННОЙ камеры фото (az_cam ∓ side_deg), на той же высоте (el камеры) — а не от осей формы
    (владелец TG 1586: камера Босса az 170,6° — ±40° от оси формы показывали спину, всё серое). Угол камеры `pose_fit`: 0 — спереди, + — камера вправо от предмета; `mesh_render.render`
    поворачивает ПРЕДМЕТ, поэтому yaw = −az (знак проверен по силуэтам на 3 формах: IoU 0,87–0,97 при yaw=−az, pitch=+el). Нет камеры — как раньше (az 0, подъём 10°).
    → {az_cam, el_cam, left: {az, yaw}, right: {az, yaw}, pitch}."""
    az = float((cam or {}).get('az', 0.0))
    az = (az + 180.0) % 360.0 - 180.0                                   # (−180, 180]
    el = float((cam or {}).get('el', 10.0))
    return {'az_cam': round(az, 2), 'el_cam': round(el, 2), 'pitch': round(el, 2),
            'left': {'az': round(az - side_deg, 2), 'yaw': round(-(az - side_deg), 2)}, 'right': {'az': round(az + side_deg, 2), 'yaw': round(-(az + side_deg), 2)}}


def frame(path: str, prgb: np.ndarray, pmask: np.ndarray, after: np.ndarray, dst_glb: str, size: int = 480, view_glb: str = None, cam: dict | None = None) -> dict:
    """«фото | кадр с камеры фото по новой текстуре | слева 40° | справа 40°» отдельным листом; боковые — рендер без света записанного GLB (файл читается, развёртка на месте); ракурсы — от азимута камеры фото (`side_view_angles`). → словарь углов."""
    import recolor_lp as LP
    px = prgb.shape[0]
    sv = side_view_angles(cam)
    panels = [np.where(pmask[..., None], prgb, 255).astype(np.uint8), after]
    panels = [np.asarray(Image.fromarray(p).resize((size * 2, size * 2), Image.LANCZOS)) for p in panels]
    for yaw in (sv['left']['yaw'], sv['right']['yaw']):
        im = np.asarray(LP.render_unlit(view_glb or dst_glb, yaw, sv['pitch'], size * 2))
        panels.append(np.where((im[..., 3] > 8)[..., None], im[..., :3], 255).astype(np.uint8))
    Image.fromarray(np.concatenate(panels, axis=1)).save(path)
    return sv


# ── этап ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def run(glb: str, photo: str, pose_run: str, run_dir: str, sku: str, cos_min: float = COS_MIN, body_only: bool = False) -> dict:
    """Этап 6 для одного товара. Любая ошибка (форма не читается, нет файлов камеры, не та форма) — НЕ роняет пакет: пишет check.json passed=false с причиной (fail-closed, T-168)."""
    t0 = time.time()
    try:
        return _run(glb, photo, pose_run, run_dir, sku, cos_min, body_only)
    except Exception as e:  # noqa: BLE001 — причина уходит в check.json и в ответ, пакет идёт дальше
        d = PS.stage_dir(run_dir, sku, '06-visible')
        why = f'{type(e).__name__}: {e}'[:400]
        PS.write_check(d, '06-visible', sku, passed=False, metric={'name': 'silhouette_iou', 'value': 0.0, 'threshold': GATE['silhouette_iou'][0], 'op': '>='},
                       reason=f'этап 6 не выполнен: {why}', seconds=round(time.time() - t0, 1), needs_qwen=False, stage_error=why, pose_run=pose_run)
        return {'sku': sku, 'passed': False, 'reason': 'error', 'why': [why], 'dir': d}


def thin_ok(pose_run: str) -> bool:
    """Камера 04 прошла гейт по контуру тонкого предмета (extra.thin_rescue и thin.passed): IoU площади для такого — не мерка (rules/camera-check.json), этап 6 его не требует."""
    try:
        ch = json.load(open(os.path.join(pose_run, '04-camera', 'check.json'), encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return False
    ex = ch.get('extra') or {}
    th = ex.get('thin') or {}
    return bool(ch.get('passed') is True and ex.get('thin_rescue') and th.get('eligible') and th.get('passed'))


def camera_gate(pose_run: str) -> tuple:
    """Гейт предыдущего этапа: `<pose_run>/04-camera/check.json`. (True|False|None, причина словами). None — файла нет (прогон камеры старше гейта): этап идёт, но в check.json пишется camera_gate=absent."""
    p = os.path.join(pose_run, '04-camera', 'check.json')
    if not os.path.exists(p):
        return None, 'у камеры нет check.json'
    try:
        ch = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError) as e:
        return False, f'check.json камеры не читается ({e})'
    if ch.get('passed') is True:
        return True, ''
    mt = ch.get('metric') or {}
    bad = [f"{k} {v.get('value')} (нужно {v.get('op')} {v.get('threshold')})" for k, v in (ch.get('metrics') or {}).items() if isinstance(v, dict) and v.get('ok') is False]
    if mt and mt.get('ok') is False:
        bad.insert(0, f"{mt.get('name')} {mt.get('value')} (нужно {mt.get('op')} {mt.get('threshold')})")
    return False, 'камера этапа 4 не прошла свой гейт: ' + ('; '.join(bad) or str(ch.get('reason') or 'passed=false'))


def legs_cut(pose_run: str):
    """Ножки формы не совпали с фото (T-191/3: 04 check.json extra.legs_block (= legs_mismatch при включённом rules legs_match.block_photo, по умолчанию выкл); сверка — legs_check.legs_report): {'row': первая строка ножек в пикселях кадра камеры, 'frame_px', 'boxes': рамки ножек формы,
    прошедших сверку (фото на них переносим; пол сдвинут — пусто), 'why'}. Нет флага / нет файла → None. Камеру НЕ бракует: 04 passed остаётся как есть."""
    try:
        ch = json.load(open(os.path.join(pose_run, '04-camera', 'check.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return None
    ex = ch.get('extra') or {}
    if not ex.get('legs_block') or ex.get('legs_cut_row') is None:
        return None
    lm = ex.get('legs_match') or {}
    try:
        fpx = int(json.load(open(os.path.join(pose_run, 'stage_loss.json'), encoding='utf-8')).get('frame_px') or 0)
    except (OSError, ValueError):
        fpx = 0
    boxes = [] if lm.get('floor_ok') is False else [list(map(int, b)) for b in (ex.get('legs_trusted_boxes') or [])]
    return {'row': int(ex['legs_cut_row']), 'frame_px': fpx, 'boxes': boxes, 'why': str(lm.get('why') or '')}


def leg_block_mask(shape: tuple, row: int, boxes: list, scale: float = 1.0, margin: int = 3):
    """Маска кадра «фото не переносим»: строки ≥ row, кроме рамок ножек, прошедших сверку (с запасом margin px). row/boxes — в пикселях кадра камеры, scale — к кадру этапа."""
    blk = np.zeros(shape, bool)
    r = max(1, min(shape[0], int(round(row * scale)) - 4))                 # запас 4 px над ножками, как у body_cut
    blk[r:] = True
    for x0, y0, x1, y1 in boxes:
        blk[max(int(y0 * scale) - margin, r):int(round(y1 * scale)) + margin + 1, max(int(x0 * scale) - margin, 0):int(round(x1 * scale)) + margin + 1] = False
    return blk, r


def body_cut(pose_run: str):
    """«Корпус годен» (р.2): камера не прошла гейт ТОЛЬКО из-за нижней полосы (ножки формы не совпадают с фото), верх лёг (iou_top ≥ порога). Возвращает {'row': первая строка нижней полосы в пикселях кадра камеры, 'frame_px'} или None."""
    p = os.path.join(pose_run, '04-camera', 'check.json')
    try:
        ch = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return None
    ex = ch.get('extra') or {}
    rows = ex.get('strip_rows')
    if not (ex.get('bottom_shape_mismatch') and rows and len(rows) == 2):
        return None
    if float(ex.get('iou_top') or 0.0) < float(ex.get('bottom_top_iou_min') or 0.85):
        return None
    bad = [k for k, v in (ch.get('metrics') or {}).items() if isinstance(v, dict) and v.get('ok') is False]
    if any(not k.endswith('_bottom') for k in bad):                  # провал не только внизу — корпусу тоже не верим
        return None
    try:
        sl = json.load(open(os.path.join(pose_run, 'stage_loss.json'), encoding='utf-8'))
        fpx = int(sl.get('frame_px') or 0)
    except (OSError, ValueError):
        fpx = 0
    return {'row': int(rows[0]), 'frame_px': fpx, 'iou_top': float(ex.get('iou_top') or 0.0)}


def _run(glb: str, photo: str, pose_run: str, run_dir: str, sku: str, cos_min: float = COS_MIN, body_only: bool = False) -> dict:
    t0 = time.time()
    d = PS.stage_dir(run_dir, sku, '06-visible')
    cg, cg_why = camera_gate(pose_run)
    bc = body_cut(pose_run) if (cg is False and body_only) else None
    lc = legs_cut(pose_run) if (body_only and bc is None) else None      # ножки не совпали (T-191/3): фото на них не переносим, кроме прошедших сверку; камера при этом прошла
    if cg is False and bc is None:                                   # вход не прошёл прежний гейт — этап его не берёт
        PS.write_check(d, '06-visible', sku, passed=False, reason=cg_why + ' — этап 6 вход не берёт, перенос не делался', seconds=round(time.time() - t0, 1),
                       needs_qwen=False, camera_failed=True, camera_gate='failed', pose_run=pose_run)
        return {'sku': sku, 'passed': False, 'reason': 'camera_gate', 'why': [cg_why]}
    geoms = load_shape(glb)
    st = load_stage(pose_run)
    P = np.asarray(Image.open(photo).convert('RGBA'))
    prgb, pmask = photo_to_frame(P, st['P'], st['px'])
    cut_row = None
    blk = None
    if bc is not None:                                               # переносим только выше нижней полосы; ножки — этапу 8
        cut_row = int(round(bc['row'] * st['px'] / bc['frame_px'])) if bc['frame_px'] else int(bc['row'])
        cut_row = max(1, min(st['px'], cut_row - 4))                 # запас 4 px над полосой
        blk = np.zeros(st['mask'].shape, bool); blk[cut_row:] = True
    elif lc is not None:                                             # ножки: ниже границы корпуса — кроме рамок ножек, прошедших сверку
        blk, cut_row = leg_block_mask(st['mask'].shape, lc['row'], lc['boxes'], (st['px'] / lc['frame_px']) if lc['frame_px'] else 1.0)
    if blk is not None:
        st['ids'] = st['ids'].copy(); st['ids'][blk] = -1
        st['cos'] = st['cos'].copy(); st['cos'][blk] = 0.0
        st['mask'] = st['mask'].copy(); st['mask'][blk] = False
        pmask = pmask.copy(); pmask[blk] = False
        prgb = prgb.copy(); prgb[blk] = 0
    iou_here = float((pmask & st['mask']).sum() / max((pmask | st['mask']).sum(), 1))
    if st.get('iou_frame') is not None and cut_row is None and abs(iou_here - st['iou_frame']) > 0.02:
        raise ValueError(f'фото не то или матрица не та: IoU силуэта здесь {iou_here:.3f}, в прогоне камеры {st["iou_frame"]:.3f}')
    st['iou_frame'] = iou_here
    thin_pass = thin_ok(pose_run)                                     # тонкий предмет: камера легла по контуру, IoU площади не мерка (06 и 04 не расходятся)
    if iou_here < GATE['silhouette_iou'][0] and not thin_pass:        # камере не верим: перенос не делаем (fail-closed)
        PS.write_check(d, '06-visible', sku, passed=False, metric={'name': 'silhouette_iou', 'value': round(iou_here, 4), 'threshold': GATE['silhouette_iou'][0], 'op': '>='},
                       reason=f'камера фото не легла по силуэту (IoU {iou_here:.3f}) — перенос не делался', seconds=round(time.time() - t0, 1), needs_qwen=False, camera_failed=True,
                       camera=st['camera'], pose_run=pose_run)
        return {'sku': sku, 'passed': False, 'reason': 'camera', 'iou': iou_here}
    reg = {'applied': False, 'dx': 0.0, 'dy': 0.0, 'gain': 0.0}
    if REG_FIT:                                                      # подпиксельная подгонка регистрации по силуэту (T-197/2); гейт и сверка IoU выше — по матрице камеры, не по подгонке
        fr_ = fit_registration(P, st['P'], st['mask'])
        reg.update(dx=round(fr_['dx'], 3), dy=round(fr_['dy'], 3), gain=round(fr_['gain'], 4))
        if fr_['gain'] >= REG_MIN_GAIN and (fr_['dx'] or fr_['dy']):
            st['P'] = fr_['P']
            prgb, pmask = photo_to_frame(P, st['P'], st['px'])
            if blk is not None:
                pmask = pmask.copy(); pmask[blk] = False
                prgb = prgb.copy(); prgb[blk] = 0
            reg['applied'] = True
    tr = transfer(geoms, st, prgb, pmask, cos_min)
    dst = os.path.join(d, 'visible.glb')
    write_glb(geoms, tr['tex'], dst)
    for i, k in enumerate(tr['known']):
        Image.fromarray((k * 255).astype(np.uint8)).save(os.path.join(d, 'known.png' if i == 0 else f'known{i}.png'))
        Image.fromarray(np.clip(tr['conf'][i] * 255.0 + 0.5, 0, 255).astype(np.uint8)).save(os.path.join(d, 'conf.png' if i == 0 else f'conf{i}.png'))     # уверенность текселя 0…255 (T-194/1)
    after = frame_from_tex(st, geoms, tr['tex'])
    cs = tr['crease']
    kvalid = known_px(geoms, st, tr)
    cn = np.concatenate([c[k] for c, k in zip(tr['conf'], tr['known'])]) if tr['known'] else np.zeros(0)
    zone, zcut = CM.body_zone(st['mask'], cut_row=cut_row)                  # корпус: выше нижней кромки (T-194/4); ножки — отдельной меркой
    crease_info = {'body_cut_row': zcut, 'confidence_mean': round(float(cn.mean()), 4) if cn.size else None, 'confidence_low_share': round(float((cn < 0.5).mean()), 4) if cn.size else None, **cs['stats'],
                   'dark_streak': CM.dark_streak_share(after, cs['band'], cs['groove'], kvalid, st['mask'], zone=zone), 'dark_streak_new': CM.dark_streak_new(after, prgb, pmask, cs['band'], cs['groove'], kvalid, st['mask'], zone=zone),
                   'dark_streak_legs': CM.dark_streak_new(after, prgb, pmask, cs['band'], cs['groove'], kvalid, st['mask'], zone=~zone),
                   'slit_contrast': CM.slit_contrast_ratio(prgb, after, cs, st['mask'], kvalid)}
    m = metrics(geoms, st, prgb, pmask, tr, after, cos_min)
    view = os.path.join(d, '_view.glb')                                 # для показа: непросмотренное — штриховка; в visible.glb заготовка не тронута (этап 7 заливает её)
    write_glb(geoms, [hatch(t, k) for t, k in zip(tr['tex'], tr['known'])], view)
    after_vis = frame_from_tex(st, geoms, [hatch(t, k) for t, k in zip(tr['tex'], tr['known'])])
    side_views = frame(os.path.join(d, 'frame.png'), prgb, pmask, after_vis, dst, view_glb=view, cam=st['camera'])
    os.remove(view)
    mm, why = gate(m, thin_pass)
    main = mm.pop('silhouette_iou')
    ok = not why
    PS.write_check(d, '06-visible', sku, passed=ok, metric={'name': 'silhouette_iou', **{k: main[k] for k in ('value', 'threshold', 'op')}}, metrics=mm,
                   reason='' if ok else '; '.join(why), seconds=round(time.time() - t0, 1), outputs=['visible.glb', 'known.png', 'conf.png', 'frame.png'], frame='frame.png',
                   needs_qwen=(not ok), cos_min=cos_min, camera=st['camera'], side_views=side_views, pose_run=pose_run, crease_shadow=crease_info, stats=tr['stats'], depth_band_share=tr['depth_band_share'], body_only=(cut_row is not None), registration_fit=reg, cut_row=cut_row, legs_block=(None if lc is None else {'why': lc['why'], 'trusted_legs': len(lc['boxes']), 'row': cut_row}), legs_left_to_stage8=(cut_row is not None), extra_metrics={k: v for k, v in m.items() if k not in GATE})
    return {'sku': sku, 'passed': ok, 'metrics': m, 'why': why, 'dir': d}


def resheet_sides(stage_d: str, pose_run: str, size: int = 480) -> dict:
    """Пересобрать у готового `06-visible/frame.png` только плитки «слева/справа» по текущему правилу (`side_view_angles`: от азимута камеры фото) — перенос заново не считается (visible.glb, known*.png на месте).
    Плитки 1–2 берутся из старого листа как есть. Штриховка непросмотренного — как в `_run`. → словарь углов (пишется и в check.json: side_views)."""
    glb = os.path.join(stage_d, 'visible.glb')
    geoms = load_shape(glb)
    texs, hat = [], []
    for i, g in enumerate(geoms):
        k = np.asarray(Image.open(os.path.join(stage_d, 'known.png' if i == 0 else f'known{i}.png')).convert('L')) > 127
        texs.append(g['tex']); hat.append(hatch(g['tex'], k))
    view = os.path.join(stage_d, '_view.glb')
    write_glb(geoms, hat, view)
    try:
        cam = load_stage(pose_run)['camera']
        old = np.asarray(Image.open(os.path.join(stage_d, 'frame.png')).convert('RGB'))
        w4 = old.shape[1] // 4
        sv = side_view_angles(cam)
        import recolor_lp as LP
        panels = [old[:, :w4], old[:, w4: 2 * w4]]
        for yaw in (sv['left']['yaw'], sv['right']['yaw']):
            im = np.asarray(LP.render_unlit(view, yaw, sv['pitch'], w4))
            panels.append(np.where((im[..., 3] > 8)[..., None], im[..., :3], 255).astype(np.uint8))
        Image.fromarray(np.concatenate(panels, axis=1)).save(os.path.join(stage_d, 'frame.png'))
    finally:
        os.remove(view)
    cp = os.path.join(stage_d, 'check.json')
    ch = json.load(open(cp, encoding='utf-8'))
    ch['side_views'] = sv
    json.dump(ch, open(cp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return sv


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('glb')
    ap.add_argument('photo', help='RGBA-вырезка товара (то же фото, по которому посчитана камера)')
    ap.add_argument('pose_run', help='папка прогона pose_fit.fit_pose (stage_loss.json, stages/render_view0/)')
    ap.add_argument('run_dir')
    ap.add_argument('--body-only', action='store_true', help='камера красная только внизу (bottom_shape_mismatch): перенос выше нижней полосы, ножки — этапу 8')
    ap.add_argument('sku')
    a = ap.parse_args()
    r = run(a.glb, a.photo, a.pose_run, a.run_dir, a.sku, body_only=a.body_only)
    print(json.dumps(r, ensure_ascii=False, default=str)[:2000])
    return 0 if r['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
