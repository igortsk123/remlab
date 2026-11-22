#!/usr/bin/env python3
"""ЗАЛИВКА НЕВИДИМОГО (T-20261120-164; план paint-photo-fill-01, шаги 4–5): текстура, где видимое с камеры фото осталось как есть, а невидимое залито ТОЙ ЖЕ ЧАСТЬЮ — программой, без нейросети и без платного.
Бесплатно, на процессоре, numpy + scipy + trimesh (+ PIL). Вход — GLB (форма, развёртка, текстура), маска «тексель известен» по каждой геометрии (видим с камеры фото, не вскользь, покрашен),
маски частей (по граням; нет частей — одна часть). Выход — новая текстура + отчёт-счётчики; форма и развёртка не меняются.

ПРАВИЛО (владелец, TG 101: «цвет и манера видимого бока — образец для всех невидимых граней»), порядок по каждому невидимому тексель-у:
  1. ЗЕРКАЛО. Если предмет симметричен (плоскость X или Z через центр габарита: большая доля точек поверхности имеет «двойника» с той же нормалью), тексель берёт цвет ЗЕРКАЛЬНОГО известного тексела
     ТОЙ ЖЕ части (диваны, кресла: второй подлокотник и бок). Только если зеркальная точка найдена в пределах `mirror_eps` и нормаль совпала.
  2. ГЕОДЕЗИЧЕСКАЯ ЗАЛИВКА. От известных текселей по ПОВЕРХНОСТИ (граф рёбер меша, дейкстра): цвет ближайшего известного места той же части, с затуханием `exp(−расстояние / geo_len)` к среднему цвету
     части (Lab). Путь идёт только по рёбрам граней ЭТОЙ части и ЭТОГО островка развёртки — вершины у швов развёртки не общие, граница части в граф не входит, поэтому цвет не «перетекает» через границу части
     и островка. Нет известного места в своём островке и части — среднее Lab части (нет и его — среднее по всем частям предмета: счётчик `fallback_global`).
  3. ФАКТУРА. К цвету добавляется бесшовный образец ВЫСОКОЙ частоты (остаток Lab над размытием) с «чистого» известного участка той же части (блок из текселей только этой части и одного островка, без швов,
     по типичной контрастности, не крайней). Копируется только статистика/текстура-остаток, не картинка: образец без среднего, размножен двумя разными по сдвигу и повороту плитками, амплитуда
     подогнана к разбросу известного остатка части (гейн в пределах `gain_min..gain_max`). Нет чистого блока — заливка гладкая (счётчик `no_patch`).
  Края: поле известного не меняется ни на единицу (кроме желоба вне островков — он дублирует ближайший цвет островка на `gutter` пикселей, чтобы билинейная выборка у шва не брала фон).

ПРОВЕРКА ПОКРЫТИЯ (шаг 5): после заливки `unpainted_after` — доля текселей островков с мерой `tex_coverage.UNPAINTED_SG` (ровный чёрный ≤3, магента) среди ВСЕХ текселей карты; должна быть 0.
Известное = видимое с камеры фото И не вскользь И покрашено: чёрные/магентовые тексели заливаются, даже если камера их видела (там краска не легла).
Все числа — `FILL` вверху файла. ID товаров в код не попадают.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import tex_coverage as TC  # noqa: E402

FILL = {
    'photo_azimuths': (0.0, 45.0),   # камеры «фото»: азимут от лица предмета (0 = в лоб, +X вправо), градусы; подменяется камерой T-112 через `known` напрямую
    'photo_res': 1024,               # буфер глубины вида, пикселей
    'photo_ortho': 1.8,              # сторона ортографического кадра (наибольшая сторона габарита = 1; диагональ куба 1,73)
    'cos_min': 0.35,                 # ниже — «вскользь» (как COS_GRAZE меры охвата): тексель не образец
    'erode_known': 3,                # отступ известного от границы известного/неизвестного и края островка, пикселей карты (у края — стыки, низкая уверенность)
    'min_known': 200,                # меньше известных текселей у части — статистика части берётся по всему предмету
    'smooth_iter': 4,                # проходов сглаживания цвета вершин по графу части (низкие частоты; шумный цвет мелких граней)
    'hp_px': 5.0,                    # сигма размытия для остатка (высокие частоты — фактура)
    'feather_len': 0.04,             # длина растушёвки зеркального к видимому у стыка «фото → достройка», доли размера предмета (≈ несколько см для предмета в метр)
    'dL_max': 15.0,                  # потолок поправки яркости достроенного к видимому, L*
    'ao': 0.0,                       # сила затенения углублений по форме (0 — выключено)
    'step_de': 8.0,                  # скачок цвета между соседними гранями одной части, ΔE00, считается «ступенью»
    'cross_islands': True,           # геодезическая заливка идёт по поверхности через шов развёртки (шов — разрез, не граница материала); False — шов преграда (только внутри островка)
    'geo_len': 0.12,                 # длина затухания геодезической заливки, доли размера предмета
    'mirror_min_score': 0.80,        # доля точек поверхности с «двойником» через плоскость, с которой предмет считается симметричным
    'mirror_eps': 0.012,             # допуск «двойника» по расстоянию, доли размера предмета
    'mirror_cos': 0.7,               # нормаль двойника (после отражения): |cos| не меньше
    'patch': 64,                     # сторона блока образца фактуры, пикселей карты
    'patch_known_min': 0.98,         # доля известных текселей в блоке, чтобы он годился (блок 64 и 32)
    'patch_known_min2': 0.90,        # то же для запасного блока 16 (известное дробное — большой блок не нашёлся)
    'gain_min': 0.5, 'gain_max': 2.0,
    'diffuse_iter': 150,             # проходов диффузии цвета по поверхности части: границы между «зонами ближайшего источника» размываются (без «лоскутов»)
    'far_de': 8.0,                   # мера пятен: тексель «далёк» от цвета своей части, если ΔE00 > far_de
    'quilt_block': 16, 'quilt_known_min': 0.75, 'quilt_n': 4,   # запасной лоскут фактуры: сборка quilt_n×quilt_n из мелких блоков, где известного ≥ quilt_known_min
    'tone': 'mode',                  # тон части: mode — самый частый цвет (фон, узор поверх), без затенённых; median — как раньше
    'tone_shadow_q': 0.15,           # тон: тексели темнее этого квантиля L части (затенённые складки, щели) в моду не входят
    'tone_bin': (4.0, 3.0, 3.0),     # тон: размер ячейки Lab (L, a, b) для моды; мода = медиана точек в ячейке и её соседях
    'patch_mode': 'quilt',           # фактура: quilt — сборка из мелких блоков (вся статистика частей, узор не теряется); block — один «типичный» блок 64/32/16 (как было)
    'quilt_pixels': 16,              # размер мелкого блока квилта, пикселей карты
    'quilt_known': 0.9,              # доля известного в блоке квилта
    'quilt_cells': 6,                # квилт = cells×cells блоков (не меньше `quilt_side` пикселей стороны)
    'quilt_side': 96,                # минимальная сторона плитки квилта, пикселей
    'quilt_overlap': 0.25,           # перекрытие блоков Efros–Freeman, доля блока (1/6–1/4)
    'quilt_block_min': 16, 'quilt_block_max': 48,   # блок — от периода узора (автокорреляция известного), в этих пределах
    'quilt_pool': 600,               # блоков-кандидатов на часть (шаг полблока, только чистые по части и известные)
    'quilt_fill_px': 4,              # блок квилта: дыры известного не дальше стольких пикселей от известного (закрываются ближайшим известным остатком)
    'quilt_pool_min': 24,            # меньше блоков в пуле — порог доли известного снижается (0,9 → 0,7 → 0,5)
    'quilt_tries': 40,              # случайных кандидатов на каждое место квилта
    'quilt_gain': (0.75, 1.33),      # выравнивание разброса блока к типичному: границы множителя (узорная часть; прочие — 0,6–1,6)
    'tone_dominance': 0.4,           # мода тона берётся, только если ячейка моды (с соседями) — не менее этой доли точек части; иначе медиана (ворс, полосы)
    'draft_when': 'a_fails',         # trellis с откатом: Б считается только если А не прошёл все мерки (a_fails); always — считать оба всегда
    'pattern_dark_ref': 40.0,        # на тёмной ткани (тон L ниже) шум хромы фото раздувается: σ хромы части умножается на min(1, L тона / pattern_dark_ref) до сравнения с pattern_chroma (диван L≈15 σ 1,6 — ровный, а не «узорный»; настоящий узор на тёмном — σ в разы выше). 0 — не нормировать
    'pattern_chroma': 1.5,           # часть, у которой МЕЛКИЙ разброс хромы (σ остатка от размытия pattern_blur_px, sqrt(σa²+σb²)) больше — «узорная»: остаток берётся от тона части (цветы/прожилки целиком), иначе — от размытия
    'pattern_blur_px': 12.0,         # размытие для отделения мелкого узора от крупных зон цвета (две большие зоны — не узор)
    'pattern_render': True,          # узорная часть: блоки квилта — из НЕПРЕРЫВНОГО кадра видимой стороны (az `pr_az`), а не из дырявой развёртки; мало блоков — прежний путь
    'pr_az': 0.0, 'pr_el': 0.0, 'pr_from_camera': True, 'pr_res': 1024, 'pr_ortho': 1.25, 'pr_cos_min': 0.5,   # кадр образца: азимут (0 = в лоб), сторона, охват, косинус к камере (вскользь — не образец)
    'pr_block_frac': 0.35,           # блок из кадра не меньше этой доли стороны видимого участка части (√ числа пикселей): мелкий период ткани не режет крупный узор
    'pr_clip_l': 2.5, 'pr_clip_l_min': 8.0,   # срез светлого в образце узора: k·σ(MAD) остатка яркости, не меньше pr_clip_l_min (L*)
    'pr_block_max': 320,             # блок квилта из кадра: до этой стороны В ПИКСЕЛЯХ КАДРА (кадр непрерывный — ветка и цветок целиком), потом пересчёт в масштаб карты
    'src_dev_pattern': 8.0,          # узорная часть: цвет-источник геодезической заливки не дальше этого ΔE (Lab) от тона части — розовый цветок у края не растекается по стойке
    'pm_spot_chroma': 10.0,          # мерка узора: «пятно» — хрома остатка от тона части больше этого
    'draft_blur_px': 6.0,            # trellis: размытие черновика внутри части до переноса статистики (штрих и муар черновика не переносятся)
    'draft_fallback': True,          # trellis: считать и А; взять Б, только если мерки не хуже (число непрошедших, затем ΔE00 перёд↔зад)
    'gutter': 8,                     # пикселей желоба вокруг островков
    'sample': 20000,                 # точек для оценки симметрии
    'source': 'stat',                # источник «невидимого»: stat — цвет части + лоскут фактуры; trellis — цвет черновика TRELLIS.2 со сдвигом тона (нужен draft); trellis_relief — цвет как stat, фактура = рельеф яркости черновика с ограничением силы (нужен draft; пороги — rules trellis_relief)
    'draft_scale_min': 0.3, 'draft_scale_max': 3.0,   # потолок растяжения разброса черновика к разбросу фото части (по каналам Lab)
    'draft_texture': False,          # trellis: класть поверх ещё и лоскут фактуры (детали черновика и так сохраняются)
    'draft_cos': 0.2,                # trellis: нормаль точки черновика к нормали текселя — не меньше (иначе перёд/зад тонкой вещи путаются)
    'draft_max_dist': 0.03,          # trellis: дальше от поверхности черновика (доли размера предмета) — черновика в тексele нет
    'relief_draft_cos': 0.5,         # trellis_relief: перенос строже (Codex 21.11): нормаль точки черновика к нормали текселя — не меньше этого (берётся больший из draft_cos и этого)
    'relief_draft_max_dist': 0.015,  # trellis_relief: ближе к поверхности черновика (берётся меньший из draft_max_dist и этого)
    'relief_draft_thin_cos': -0.2,   # trellis_relief: если рядом (в пределах расстояния) есть точка черновика с нормалью против нормали текселя (cos < этого) — тонкая вещь, перёд/зад путаются → тексель без черновика (None — выкл.)
    'part_role': None,               # {часть: роль этапа 3} (run_stage берёт из 03-parts/parts.json; нет — правила по ролям не действуют)
    'pattern_side_cos': 0.2,         # узорная часть: узор кладётся только на тексели, обращённые к фото (cos нормали с направлением камеры pr_az ≥ порога); обратная сторона/сиденье/низ — тон ткани без цветов (дефект Sakura 21.11: цветы спинки на заду и сиденье)
    'smooth_roles': ['legs', 'frame', 'handles'],   # роли без плитки фактуры на недостроенном: тон части без блоков («ёлочка» стыков на дереве, Sakura 21.11)
    'tone_share_roles': ['legs', 'frame', 'handles'],   # роли, у которых тон един на все части одной роли (один материал — один тон: задние ножки темнее передних из-за теней)
    'tone_only_use': True,           # run_stage: читать `tone_only.png` из папки этапа 6 (нет файла — прежнее поведение)
    'relief_calib_donor': False,     # Ш6 вариант 2: часть без своего фото берёт калибровку рельефа TRELLIS (σ/p95 чистой ткани) у донора тона той же роли; по умолчанию выкл. (без него рельеф у таких частей = stat)
    'borrow_texture': False,         # Ш6 вариант 1: часть без чистых блоков (нет квилта/блока) берёт микрофактуру у части ТОЙ ЖЕ материальной зоны (роль и тон близки, не узорная); по умолчанию выкл.
    'borrow_luma_only': True,        # заимствованный лоскут даёт только яркость (a/b — нет): цвет остаётся тоном части
    'borrow_rescale': True,          # заимствованный лоскут читается в масштабе поверхности: шаг текселя части ÷ шаг текселя донора
    'borrow_max_de': 6.0,            # …тон (Lab, евклид) донорской части ближе этого
    'nail_twins': True,              # мелкие тёмные компактные пятна (шляпки гвоздей) невидимой стороны: цвет — как у видимых двойников этой части с фото, форма — нативная (ряд гвоздей сзади не стирается тоном ткани)
    'nail_dark_drop': 25.0,          # пятно темнее тона части на столько L
    'nail_min_tone_L': 60.0,         # части темнее этого тона (тёмная ткань) — правило молчит: тёмное там не выделяется
    'nail_min_px': 6, 'nail_max_px': 400, 'nail_min_fill': 0.4, 'nail_max_aspect': 3.5,   # размер пятна, плотность в рамке, вытянутость (линии шва/трещины — не гвозди)
    'nail_max_de': 12.0, 'nail_max_dchroma': 8.0, 'nail_max_shift': 6.0,   # принимаем пятно, если средний Lab ближе к двойникам (красное/чёрное — не гвоздь); сдвиг к двойникам — мягкий
    'nail_neighbor_px': 80, 'nail_min_neighbours': 1,   # пятно «в ряду»: рядом (≤ px развёртки) есть видимый двойник или другое принятое пятно; одиночка (красноватая точка) — не гвоздь
    'nail_min_twins': 5,             # видимых двойников (пятен с тем же отбором) не меньше — иначе тёмное считается тенью/швом и правило молчит
    'tone_known_min_share': 0.02,    # часть с ролью этапа 3, у которой известного < этой доли её текселей: её тон — по случайным кусочкам (накладка подлокотника: известны торцы-дерево, тон вышел «песочным»); берёт тон соседней части ТОЙ ЖЕ роли с наибольшей общей границей
    'tone_compat_min_known': 1500, 'tone_compat_de': 25.0,   # донор той же роли: если у части известного ≥ порога — её видимый тон не должен отличаться от донора больше ΔE (иначе донор отвергнут)
    'catalog_tone': None, 'skip_global_tone': True,          # каталожный тон роли {роль: Lab}; часть с ролью без своего тона и без донора/каталога НЕ красится (не тон всего товара)
    'quilt_jump_max': 0.5,           # неузорная часть: скачок на швах плитки (jump_L) выше — плитка не кладётся, тон части (швы заметны)
    'part_class': None,              # trellis_relief: {часть: роль/семья из этапа 3} (run_stage --part-roles); нет — ворота только по однородности известного
}
BLACK_MAX = TC.UNPAINTED_SG['black_max']
VIEW_CLASSES = getattr(TC, 'VIEW_CLASSES', ('низ', 'верх', 'зад', 'перёд', 'бока', 'прочее'))   # как в сторожe T-152 (tex_coverage.view_class, ветка tex-guard-152); после слияния — только TC


def view_class(nout):
    """(n,3) наружные нормали (Y вверх, перёд +Z) → индексы в VIEW_CLASSES. Та же раскладка, что `tex_coverage.view_class` (ветка tex-guard-152, 8be604ff)."""
    if hasattr(TC, 'view_class'):
        return TC.view_class(nout)
    k = np.full(len(nout), 5, np.int8)
    k[np.abs(nout[:, 0]) > 0.5] = 4
    k[nout[:, 2] > 0.5] = 3
    k[nout[:, 2] < -0.5] = 2
    k[nout[:, 1] > 0.5] = 1
    k[nout[:, 1] < -0.5] = 0
    return k


# ---------------------------------------------------------------- цвет -----------------------------------------
def rgb2lab(rgb):
    return TC.rgb2lab(rgb)


def lab2rgb(lab):
    """Lab (N,3), D65 → sRGB uint8 (N,3); обратное к `rgb2lab`."""
    lab = np.asarray(lab, np.float64)
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200
    d = 6 / 29

    def inv(f):
        return np.where(f > d, f ** 3, 3 * d * d * (f - 4 / 29))
    xyz = np.stack([inv(fx), inv(fy), inv(fz)], 1) * np.array([0.95047, 1.0, 1.08883])
    M = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ M.T, 0.0, 1.0)
    c = np.where(c > 0.0031308, 1.055 * np.power(c, 1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(np.round(c * 255.0), 0, 255).astype(np.uint8)


def unpainted_mask(rgb):
    """Мера «не закрашено» сторожа покрытия (StableGen): ровный чёрный или магента — одна и та же, что в `tex_coverage.analyze(rig=…)`."""
    u = TC.UNPAINTED_SG
    rgb = np.asarray(rgb)
    return (rgb.max(axis=-1) <= u['black_max']) | ((rgb[..., 0] >= u['r_min']) & (rgb[..., 1] <= u['g_max']) & (rgb[..., 2] >= u['b_min']))


# ---------------------------------------------------------------- видимость с камеры фото ----------------------
def photo_views(azimuths=None, elevation: float = 0.0) -> list:
    """Камеры фото как виды (на_камеру, вправо, вверх) в кадре GLB (лицом +Z, Y вверх): азимут 0 — в лоб, 90 — справа (+X), 180 — сзади; elevation — угол над горизонтом (−90 — снизу, на дно)."""
    az = FILL['photo_azimuths'] if azimuths is None else azimuths
    out = []
    for a in az:
        r = np.radians(a)
        e = np.radians(elevation)
        c = np.array([np.sin(r) * np.cos(e), np.sin(e), np.cos(r) * np.cos(e)])
        right = np.cross([0.0, 1.0, 0.0], c) if abs(c[1]) < 0.999 else np.array([1.0, 0.0, 0.0])
        right /= np.linalg.norm(right)
        out.append((c, right, np.cross(c, right)))
    return out


def frame_of(geoms: list):
    """Центр и наибольшая сторона габарита всех геометрий вместе → точки куба P (как у меры охвата без поворота)."""
    V = np.concatenate([np.asarray(g['V'], np.float64) for g in geoms])
    lo, hi = V.min(axis=0), V.max(axis=0)
    ctr, size = (lo + hi) / 2.0, float(max((hi - lo).max(), 1e-9))
    return ctr, size


def _weld(key):
    """Номера склеенных вершин: строки `key` (N,k) с одинаковым значением — одна вершина."""
    _u, inv = np.unique(np.asarray(key), axis=0, return_inverse=True)
    return np.asarray(inv).reshape(-1)


def _islands(F, uvw):
    """Номер островка развёртки у каждой грани: грани, связанные общими вершинами, склеенными по UV (в GLB вершины не слиты: на каждый угол грани своя вершина)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    nf = len(F)
    rows = np.repeat(np.arange(nf), 3)
    cols = nf + np.asarray(uvw)[np.asarray(F)].reshape(-1)
    n = nf + int(np.max(uvw)) + 1
    _n, lab = connected_components(coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n)), directed=False)
    return lab[:nf]


class Tex:
    """Растр развёртки одной геометрии: у каждого занятого тексела — грань, точка и нормаль в 3D, часть, островок."""

    def __init__(self, g, P, T: int, part_of_face=None, cross_islands: bool = True):
        self.T = T
        F = np.asarray(g['F'], np.int64)
        UV = np.asarray(g['UV'], np.float64)
        xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
        ids, _ = TC.raster(xy, F, T)
        self.ids = ids
        ti = np.nonzero(ids >= 0)[0]
        self.ti = ti
        f = ids[ti].astype(np.int64)
        self.f = f
        a_, b_, c_ = F[f, 0], F[f, 1], F[f, 2]
        px, py = (ti % T) + 0.5, (ti // T) + 0.5
        A, B, C = xy[a_], xy[b_], xy[c_]
        ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
        wa = ((B[:, 0] - px) * (C[:, 1] - py) - (B[:, 1] - py) * (C[:, 0] - px)) / ar
        wb = ((C[:, 0] - px) * (A[:, 1] - py) - (C[:, 1] - py) * (A[:, 0] - px)) / ar
        self.bary = np.stack([wa, wb, 1.0 - wa - wb], 1)
        self.F = F
        self.UV = UV
        self.P = P
        self.Q = self.bary[:, :1] * P[a_] + self.bary[:, 1:2] * P[b_] + self.bary[:, 2:3] * P[c_]
        n3 = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        self.fnorm = n3 / np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
        self.N = self.fnorm[f]
        self.part_f = np.zeros(len(F), np.int32) if part_of_face is None else np.asarray(part_of_face, np.int32)
        self.part = self.part_f[f]
        uvw = _weld(np.round(UV * 1e5).astype(np.int64))
        self.island_f = _islands(F, uvw)
        # вершины склеены по 3D-позиции (шов развёртки — разрез, не разрыв поверхности): граф геодезической заливки; cross_islands=False — ещё и по UV (шов — преграда)
        key = np.round(P * 1e6).astype(np.int64)
        if not cross_islands:
            key = np.hstack([key, uvw[:, None]])
        self.W = _weld(key)
        self.FW = self.W[F]
        self.PW = np.zeros((int(self.W.max()) + 1, 3))
        self.PW[self.W] = P
        self.island = self.island_f[f]


# ---------------------------------------------------------------- известное: видимость с камер фото ------------
def known_from_photo(geoms: list, azimuths=None, res: int | None = None, cos_min: float | None = None, parts=None) -> list:
    """Маски «тексель виден с камер фото» по каждой геометрии (T×T bool): глубина вида — первая грань вдоль луча, угол к камере лучше `cos_min`, тексель покрашен (не чёрный/магента).
    Это ТОЛЬКО видимость; отступ от границы — в `fill`. Камеру T-112 подставляют готовой маской вместо этой функции."""
    res = int(res or FILL['photo_res'])
    cos_min = FILL['cos_min'] if cos_min is None else cos_min
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    Fall = np.concatenate([np.asarray(g['F'], np.int64) + offs[i] for i, g in enumerate(geoms)])
    cams = []
    ortho = FILL['photo_ortho']
    for v in photo_views(azimuths):
        x, y, d = TC.project(P, v, ortho)
        cams.append((v, TC.raster(np.stack([x * res, y * res], 1), Fall, res, d)[1]))
    out = []
    for gi, g in enumerate(geoms):
        T = _grid(g)
        tx = Tex(g, P[offs[gi]:offs[gi + 1]], T, None if parts is None else parts[gi])
        seen = np.zeros(len(tx.ti), bool)
        for v, zb in cams:
            x, y, d = TC.project(tx.Q, v, ortho)
            cs = np.abs(tx.N @ v[0])
            ix = np.clip(np.floor(x * res).astype(np.int64), 0, res - 1)
            iy = np.clip(np.floor(y * res).astype(np.int64), 0, res - 1)
            eps = TC.DEPTH_EPS + (ortho / res) * np.sqrt(np.maximum(1.0 - cs * cs, 0.0)) / np.maximum(cs, TC.COS_SEEN)
            seen |= (zb[iy * res + ix] <= d + eps) & (cs > cos_min)
        m = np.zeros(T * T, bool)
        m[tx.ti] = seen
        out.append(m.reshape(T, T))
    return out


def _grid(g, cap: int = 2048) -> int:
    H, W = np.asarray(g['tex']).shape[:2]
    if H != W:
        raise ValueError('текстура не квадратная: заливка работает по квадратной карте')
    return int(min(H, cap)) if H <= cap else int(H)


# ---------------------------------------------------------------- вспомогательные --------------------------------
def _blur_norm(img, known, sigma: float):
    """Размытие известного с нормировкой по весу (неизвестное не вносит чёрного): img (T,T,3) float, known (T,T) bool → (T,T,3), вес (T,T)."""
    from scipy.ndimage import gaussian_filter
    w = known.astype(np.float64)
    num = np.stack([gaussian_filter(img[..., k] * w, sigma, mode='nearest') for k in range(3)], -1)
    den = gaussian_filter(w, sigma, mode='nearest')
    return num / np.maximum(den, 1e-9)[..., None], den


def part_pattern(txs: list, labs: list, kn: list, part_ids: list, c: dict, tone_l: dict) -> tuple:
    """Узорность частей — ОДНА истина для 07 и для мерки Б (Ш6, 21.11): хроматический разброс высоких частот известных текселей (a/b), с поправкой на тёмный тон.
    tone_l {часть: L тона}. → ({часть: pat_std}, {часть: pat_eff}); часть узорная ⇔ pat_eff > c['pattern_chroma']."""
    lowb = [_blur_norm(labs[gi], kn[gi], c['pattern_blur_px'])[0] for gi in range(len(txs))]
    pat_std, pat_eff = {}, {}
    for p in part_ids:
        Hp = np.concatenate([(labs[gi] - lowb[gi]).reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
        pat_std[p] = float(np.hypot(Hp[:, 1].std(), Hp[:, 2].std())) if len(Hp) else 0.0
        pat_eff[p] = pat_std[p] * (min(1.0, max(float(tone_l.get(p, 0.0)), 0.0) / float(c['pattern_dark_ref'])) if float(c['pattern_dark_ref']) > 0 else 1.0)
    return pat_std, pat_eff


def tone_of(L, c) -> np.ndarray:
    """Тон части по Lab-точкам L (n,3): мода — самый частый цвет (фон; узор кладётся поверх остатком), без затенённых (L ниже квантиля `tone_shadow_q`). tone='median' — медиана."""
    if len(L) == 0:
        return np.array([50.0, 0.0, 0.0])
    if c['tone'] == 'median':
        return np.median(L, axis=0)
    if len(L) > 400000:
        L = L[np.random.RandomState(3).choice(len(L), 400000, replace=False)]
    M = L
    if c['tone_shadow_q'] > 0:
        keep = L[:, 0] >= np.quantile(L[:, 0], c['tone_shadow_q'])
        if keep.sum() >= max(50, 0.2 * len(L)):
            M = L[keep]
    q = np.floor(M / np.asarray(c['tone_bin'], np.float64)).astype(np.int64) + 512
    key = (q[:, 0] * 1024 + q[:, 1]) * 1024 + q[:, 2]
    u, cnt = np.unique(key, return_counts=True)
    b = int(u[int(np.argmax(cnt))])
    bq = np.array([b // (1024 * 1024), (b // 1024) % 1024, b % 1024])
    near = (np.abs(q - bq) <= 1).all(axis=1)
    if float(near.mean()) < c['tone_dominance']:             # единого фона нет (ворс, полосы, пёстрая ткань): мода случайна и тянет тон в сторону — берём медиану, как до моды
        return np.median(L, axis=0)
    return np.median(M[near], axis=0)


def _mincut_v(err: np.ndarray) -> np.ndarray:
    """Путь минимальной ошибки сверху вниз по зоне перекрытия err (H,W) → маска (H,W): True справа от пути (берём новый блок), слева — прежний."""
    H, W = err.shape
    E = err.astype(np.float64).copy()
    for i in range(1, H):
        up = E[i - 1]
        E[i] += np.minimum(np.minimum(np.r_[np.inf, up[:-1]], up), np.r_[up[1:], np.inf])
    path = np.zeros(H, np.int64)
    path[-1] = int(np.argmin(E[-1]))
    for i in range(H - 2, -1, -1):
        j = int(path[i + 1])
        lo, hi = max(0, j - 1), min(W, j + 2)
        path[i] = lo + int(np.argmin(E[i, lo:hi]))
    return np.arange(W)[None, :] >= path[:, None]


def quilt_image(pool: np.ndarray, cells: int, overlap: int, rng, tries: int = 40) -> np.ndarray:
    """Image quilting (Efros–Freeman) из блоков pool (N,B,B,3): блоки с перекрытием `overlap` пикселей, на каждом месте — лучший по ошибке перекрытия из `tries` случайных (из близких к лучшему — случайный), шов — путь минимальной ошибки.
    → (S,S,3), S = cells·(B−overlap)+overlap."""
    N, B = pool.shape[0], pool.shape[1]
    o = int(max(1, min(overlap, B // 2)))
    step = B - o
    S = cells * step + o
    out = np.zeros((S, S, 3))
    for i in range(cells):
        for j in range(cells):
            y, x = i * step, j * step
            idx = rng.choice(N, size=min(tries, N), replace=N < tries)
            cand = pool[idx]
            err = np.zeros(len(idx))
            if j > 0:
                err += ((cand[:, :, :o] - out[y:y + B, x:x + o][None]) ** 2).sum(axis=(1, 2, 3))
            if i > 0:
                err += ((cand[:, :o, :] - out[y:y + o, x:x + B][None]) ** 2).sum(axis=(1, 2, 3))
            if i > 0 or j > 0:
                good = np.nonzero(err <= err.min() * 1.1 + 1e-9)[0]
                k = int(good[rng.randint(len(good))])
            else:
                k = 0
            blk = cand[k]
            new = np.ones((B, B), bool)
            if j > 0:
                new[:, :o] &= _mincut_v(((out[y:y + B, x:x + o] - blk[:, :o]) ** 2).sum(axis=2))
            if i > 0:
                new[:o, :] &= _mincut_v(((out[y:y + o, x:x + B] - blk[:o, :]) ** 2).sum(axis=2).T).T
            cur = out[y:y + B, x:x + B]
            out[y:y + B, x:x + B] = np.where(new[..., None], blk, cur)
    return out


def wrap_soften(img: np.ndarray, sigma: float = 2.0, reach: int = 4) -> np.ndarray:
    """Плитка повторяется с периодом S: шов краёв (левый↔правый, верх↔низ) сглаживается — сдвиг на пол-периода, размытие узкой полосы по кресту, обратный сдвиг."""
    from scipy.ndimage import gaussian_filter
    S = img.shape[0]
    h = S // 2
    R = np.roll(img, (h, h), (0, 1))
    bl = np.stack([gaussian_filter(R[..., k], sigma, mode='nearest') for k in range(R.shape[2])], -1)
    d = np.minimum(np.abs(np.arange(S) - h)[:, None], np.abs(np.arange(S) - h)[None, :]).astype(np.float64)
    w = np.exp(-0.5 * (d / max(reach / 2.0, 1e-6)) ** 2)[..., None]
    return np.roll(R * (1.0 - w) + bl * w, (-h, -h), (0, 1))


def quilt_jump(patch: np.ndarray, step: int) -> float:
    """Межблочный скачок: средний |ΔL| между средними яркостями соседних клеток квилта (шахматка по яркости ↔ большое значение)."""
    S = patch.shape[0]
    n = max(1, S // max(step, 1))
    L = patch[:n * step, :n * step, 0].reshape(n, step, n, step).mean(axis=(1, 3))
    if n < 2:
        return 0.0
    return float(0.5 * (np.abs(np.diff(L, axis=0)).mean() + np.abs(np.diff(L, axis=1)).mean()))


def pattern_period(resL: np.ndarray, ok: np.ndarray, lo: int, hi: int) -> int:
    """Размер блока квилта по периоду узора: длина автокорреляции остатка яркости на известной части (первый лаг, где корреляция < 1/e, по осям), блок ≈ 3 длины, в [lo,hi], кратно 4."""
    from scipy.fft import rfft2, irfft2, next_fast_len
    T = resL.shape[0]
    s = next_fast_len(T + 2 * hi)
    m = ok.astype(np.float32)
    x = (resL.astype(np.float32) - float((resL * ok).sum() / max(float(m.sum()), 1.0))) * m
    Fx, Fm = rfft2(x, (s, s)), rfft2(m, (s, s))
    ac = irfft2(Fx * np.conj(Fx), (s, s))
    nm = np.maximum(irfft2(Fm * np.conj(Fm), (s, s)), 1.0)
    r = ac / nm
    if r[0, 0] <= 1e-9:
        return lo
    r = r / r[0, 0]
    lag = []
    for prof in (r[0, 1:hi + 1], r[1:hi + 1, 0]):
        below = np.nonzero(prof < 0.37)[0]
        lag.append(int(below[0]) + 1 if len(below) else hi)
    ell = float(min(lag))                                  # полосы вдоль одной оси: берём короткий период
    return int(np.clip(int(round(3.0 * ell / 4.0)) * 4, lo, hi))


def winding_by_known(normals: np.ndarray, known: np.ndarray, az_deg: float, el_deg: float = 0.0) -> float:
    """Знак обмотки граней по известному: известные тексели (взяты с фото) по определению обращены к камере, значит среднее (нормаль по обмотке · на камеру) у них > 0; < 0 — обмотка перевёрнутая → -1.
    Не по объёму сетки (у открытых сеток он врёт). Известного нет — +1."""
    kn = np.asarray(known, bool)
    if not kn.any():
        return 1.0
    return -1.0 if float(np.mean(np.asarray(normals)[kn] @ photo_views([az_deg], el_deg)[0][0])) < 0 else 1.0


def pr_camera_from_extra(extra: dict | None, cfg: dict | None) -> tuple:
    """Камера образца узора (`pr_az`, `pr_el`) — ПОДОБРАННАЯ камера этапа 4 из `06-visible/check.json` (`extra.camera`: az, el), а не 0°/0°: у товара, снятого под углом, «сторона фото» иначе не та (T-164, Codex 21.11).
    Явно заданный `pr_az` в cfg или `pr_from_camera=false` — как есть. → (cfg, заметка для report.pr_camera)."""
    cfg = dict(cfg or {})
    if 'pr_az' in cfg or not dict(FILL, **cfg).get('pr_from_camera', True):
        return cfg, {'source': 'cfg/по умолчанию', 'az': cfg.get('pr_az', FILL['pr_az']), 'el': cfg.get('pr_el', FILL['pr_el'])}
    cam = (extra or {}).get('camera')
    if not isinstance(cam, dict) or not isinstance(cam.get('az'), (int, float)):
        cfg['pattern_side_cos'] = None                           # камеры нет — «стороны фото» не знаем: правило узора по стороне молчит (не az 0); кадр образца — как раньше (az 0)
        return cfg, {'source': 'нет камеры в check этапа 6 — правило по стороне фото молчит', 'az': FILL['pr_az'], 'el': FILL['pr_el'], 'side_rule': False}
    az = ((float(cam['az']) + 180.0) % 360.0) - 180.0
    el = float(cam['el']) if isinstance(cam.get('el'), (int, float)) else 0.0
    cfg['pr_az'], cfg['pr_el'] = az, el
    return cfg, {'source': 'этап 4 (камера в check этапа 6)', 'az': round(az, 2), 'el': round(el, 2)}


def view_samples(geoms: list, azimuth: float, res: int, ortho: float, elevation: float = 0.0) -> dict:
    """Растр вида (как `render_ortho`): по занятым пикселям кадра — геометрия, UV точки и косинус нормали с камерой. → {'hit' (индексы пикселей), 'g', 'u', 'v', 'cos', 'res', 'ppu' (пикселей на единицу кадра)}."""
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    F = np.concatenate([np.asarray(g['F'], np.int64) + offs[i] for i, g in enumerate(geoms)])
    fg = np.concatenate([np.full(len(g['F']), i) for i, g in enumerate(geoms)])
    UV = np.concatenate([np.asarray(g['UV'], np.float64) for g in geoms])
    v = photo_views([azimuth], elevation)[0]
    x, y, d = TC.project(P, v, ortho)
    xy = np.stack([x * res, y * res], 1)
    ids, _zb = TC.raster(xy, F, res, d)
    hit = np.nonzero(ids >= 0)[0]
    f = ids[hit].astype(np.int64)
    px, py = (hit % res) + 0.5, (hit // res) + 0.5
    A, B, C = xy[F[f, 0]], xy[F[f, 1]], xy[F[f, 2]]
    ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    ar = np.where(np.abs(ar) < 1e-12, 1e-12, ar)
    wa = ((B[:, 0] - px) * (C[:, 1] - py) - (B[:, 1] - py) * (C[:, 0] - px)) / ar
    wb = ((C[:, 0] - px) * (A[:, 1] - py) - (C[:, 1] - py) * (A[:, 0] - px)) / ar
    uv = wa[:, None] * UV[F[f, 0]] + wb[:, None] * UV[F[f, 1]] + (1.0 - wa - wb)[:, None] * UV[F[f, 2]]
    n3 = np.cross(P[F[f, 1]] - P[F[f, 0]], P[F[f, 2]] - P[F[f, 0]])
    n3 /= np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    return {'hit': hit, 'g': fg[f], 'u': uv[:, 0], 'v': uv[:, 1], 'cos': np.abs(n3 @ v[0]), 'res': res, 'ppu': res / ortho}


def sample_view(S: dict, arrs: list, fill_value=0):
    """Значения карт `arrs` (по геометриям, (T,T[,C])) в пикселях кадра `view_samples` (ближайший тексель); вне предмета — fill_value. → (res,res[,C])."""
    a0 = np.asarray(arrs[0])
    out = np.full((S['res'] * S['res'],) + a0.shape[2:], fill_value, a0.dtype)
    for gi, a in enumerate(arrs):
        s = S['g'] == gi
        if not s.any():
            continue
        a = np.asarray(a)
        H, W = a.shape[:2]
        tx_ = np.clip(np.floor(S['u'][s] * W).astype(np.int64), 0, W - 1)
        ty_ = np.clip(np.floor((1.0 - S['v'][s]) * H).astype(np.int64), 0, H - 1)
        out[S['hit'][s]] = a[ty_, tx_]
    return out.reshape((S['res'], S['res']) + a0.shape[2:])


def texel_scale(geoms: list, parts: list | None, p: int, ppu: float) -> float:
    """Во сколько раз плотность карты (текселей на единицу кадра) у части `p` больше плотности кадра `view_samples` (пикселей на единицу): медиана sqrt(площадь в UV·T² / площадь в 3D) по граням части."""
    ctr, size = frame_of(geoms)
    r = []
    for gi, g in enumerate(geoms):
        V = (np.asarray(g['V'], np.float64) - ctr) / size
        F = np.asarray(g['F'], np.int64)
        UV = np.asarray(g['UV'], np.float64)
        tex = np.asarray(g['tex'])
        a3 = 0.5 * np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
        e1, e2 = UV[F[:, 1]] - UV[F[:, 0]], UV[F[:, 2]] - UV[F[:, 0]]
        auv = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) * tex.shape[0] * tex.shape[1]
        sel = (a3 > 1e-12) & (auv > 1e-9)
        if parts is not None:
            sel &= np.asarray(parts[gi]) == p
        r.append(np.sqrt(auv[sel] / a3[sel]))
    r = np.concatenate(r) if r else np.zeros(0)
    return float(np.median(r) / ppu) if len(r) else 1.0


def reject_outlier_blocks(pool: list, k: float, floor: float, quantile: float):
    """Отбраковка блоков-кандидатов с чужеродным пятном: мера блока — квантиль `quantile` модуля остатка Lab от медианы блока; блок с мерой > k·max(медиана мер пула, floor) отбрасывается
    (тёмная дыра, белый фон на краю фото, шов — у нормального блока такой контраст редок). Пороги — rules/paint-fill.json. → (оставшиеся блоки, сколько отброшено)."""
    P = np.stack(pool).astype(np.float64)
    r = P - np.median(P.reshape(len(P), -1, 3), axis=1)[:, None, None, :]
    mag = np.quantile(np.linalg.norm(r, axis=3).reshape(len(P), -1), quantile, axis=1)
    keep = mag <= k * max(float(np.median(mag)), floor)
    return [b for b, kp in zip(pool, keep) if kp], int((~keep).sum())


def dark_floor(tone_l: float, black_abs: float, black_rel: float) -> float:
    """Порог «абсолютно чёрного» L*: не выше `black_abs` и не выше доли `black_rel` тона части — на тёмной ткани (тон L≈15) порог 20 резал ВЕСЬ пул блоков и всё зеркало (T-164, диван 114082).
    Один источник для quilt_extreme и mirror_extreme (правила — rules/paint-fill.json)."""
    return min(float(black_abs), float(black_rel) * max(float(tone_l), 0.0))


def reject_extreme_blocks(pool: list, tone_l: float, dl_hi: float, black_abs: float, share: float):
    """Узорная часть, блоки — остаток Lab от тона: «плохой» пиксель — светлее тона больше чем на `dl_hi` (L*) или абсолютно чёрный (L* тона + остаток < `black_abs` — вызывающий передаёт уже `dark_floor`, т.е. порог относительно тона). Блок, где плохих пикселей больше доли `share`, отбрасывается.
    Пороги — rules/paint-fill.json (quilt_extreme). → (оставшиеся блоки, сколько отброшено)."""
    P = np.stack(pool).astype(np.float64)
    L = P[..., 0]
    bad = ((L > dl_hi) | (L + tone_l < black_abs)).reshape(len(P), -1).mean(axis=1)
    keep = bad <= share
    return [b for b, kp in zip(pool, keep) if kp], int((~keep).sum())


def render_pool(resq: np.ndarray, okr: np.ndarray, c: dict, scale: float):
    """Блоки узора из НЕПРЕРЫВНОГО кадра видимой стороны: `resq` (res,res,3) — остаток цвета от тона части, `okr` — пиксели «известное, эта часть, лицом к камере». Блок — по периоду узора, дыры ≤ `quilt_fill_px`
    закрываются ближайшим известным; блоки пересчитываются в масштаб карты (`scale` = текселей на пиксель кадра). → (сторона блока в текселях, [блоки]) | None, если блоков мало."""
    from scipy.ndimage import distance_transform_edt, zoom
    if int(okr.sum()) < 200:
        return None
    Bq = pattern_period(resq[..., 0], okr, int(c['quilt_block_min']), int(c['pr_block_max']))
    Bf = int(round(c['pr_block_frac'] * float(np.sqrt(okr.sum())) / 4.0)) * 4        # мелкая ткань (рогожка) даёт короткий период; крупный узор (ветки, цветы) — доля стороны видимого участка части
    Bq = int(min(max(Bq, Bf), int(c['pr_block_max']), okr.shape[0] // 2))
    dist_, (iy_, ix_) = distance_transform_edt(~okr, return_indices=True)
    fill_ = resq[iy_, ix_]
    I_ok = np.pad(okr.astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    I_nr = np.pad((dist_ <= c['quilt_fill_px']).astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    R = okr.shape[0]
    if R < Bq:
        return None
    s = max(Bq // 2, 1)
    ys = np.arange(0, R - Bq + 1, s)
    Y, X = np.meshgrid(ys, ys, indexing='ij')

    def bsum(I):
        return I[Y + Bq, X + Bq] - I[Y, X + Bq] - I[Y + Bq, X] + I[Y, X]
    pool = []
    for thr in (c['quilt_known'], 0.7, 0.5):
        good = (bsum(I_ok) >= thr * Bq * Bq) & (bsum(I_nr) >= Bq * Bq - 0.5)
        pool = [fill_[Y[by, bx]:Y[by, bx] + Bq, X[by, bx]:X[by, bx] + Bq] for by, bx in zip(*np.nonzero(good))]
        if len(pool) >= int(c['quilt_pool_min']):
            break
    if len(pool) < 4:
        return None
    Bt = max(8, int(round(Bq * scale)))
    if Bt != Bq:
        z = Bt / Bq
        pool = [zoom(b, (z, z, 1), order=1)[:Bt, :Bt] for b in pool]
    return Bt, pool


def symmetry(txs: list, known_flat: list, size_eps: float, sample: int, cos_min: float) -> dict:
    """Оценка симметрии: доля точек поверхности, у которых через плоскость X (или Z) через центр есть «двойник» (ближе `size_eps`, нормаль после отражения совпала). → {axis, score, planes}."""
    from scipy.spatial import cKDTree
    Q = np.concatenate([t.Q for t in txs])
    N = np.concatenate([t.N for t in txs])
    rng = np.random.RandomState(11)
    sel = rng.choice(len(Q), min(sample, len(Q)), replace=False) if len(Q) else np.zeros(0, int)
    tree = cKDTree(Q)
    best = {'axis': None, 'score': 0.0, 'planes': {}}
    for axis in (0, 2):
        R = np.ones(3)
        R[axis] = -1
        d, j = tree.query(Q[sel] * R, k=1, distance_upper_bound=size_eps)
        okj = np.isfinite(d)
        cs = np.abs((N[sel] * R * N[np.where(okj, j, 0)]).sum(axis=1))
        score = float((okj & (cs > cos_min)).mean()) if len(sel) else 0.0
        best['planes'][int(axis)] = round(score, 3)
        if score > best['score']:
            best['axis'], best['score'] = axis, score
    best['score'] = round(best['score'], 3)
    return best


def _gaussian_tile(patch, rng, keep_mean: bool = False):
    """Бесшовная плитка из блока остатка (B,B,3): смесь блока и его сдвига на пол-блока с весами, сохраняющими разброс (sin·sin и √(1−w²)) → периодична по обеим осям."""
    B = patch.shape[0]
    x = np.arange(B)
    w1 = (np.sin(np.pi * x / B)[:, None] * np.sin(np.pi * x / B)[None, :])[..., None]
    w2 = np.sqrt(np.maximum(1.0 - w1 * w1, 0.0))
    m = patch.mean(axis=(0, 1), keepdims=True)
    p = patch - m
    t = w1 * p + w2 * np.roll(p, (B // 2, B // 2), axis=(0, 1))
    return t + m if keep_mean else t


def concavity(tx, smooth: int = 2):
    """Вогнутость по склеенным вершинам: (среднее соседей − вершина)·нормаль / средняя длина ребра, сглажено; >0 — впадина (нормали наружу, грани против часовой). → (nW,) float."""
    from scipy.sparse import coo_matrix
    FW, PW = tx.FW, tx.PW
    nW = len(PW)
    nrm = np.zeros((nW, 3))
    for i in range(3):
        for k in range(3):
            nrm[:, k] += np.bincount(FW[:, i], weights=tx.fnorm[:, k], minlength=nW)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-12)[:, None]
    e = np.unique(np.sort(np.concatenate([FW[:, [0, 1]], FW[:, [1, 2]], FW[:, [2, 0]]]), axis=1), axis=0)
    e = e[e[:, 0] != e[:, 1]]
    A = coo_matrix((np.ones(2 * len(e)), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(nW, nW)).tocsr()
    deg = np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1.0)
    lap = (A @ PW) / deg[:, None] - PW
    el = float(np.linalg.norm(PW[e[:, 0]] - PW[e[:, 1]], axis=1).mean()) if len(e) else 1.0
    cv = (lap * nrm).sum(axis=1) / max(el, 1e-9)
    for _ in range(smooth):
        cv = (A @ cv + cv) / (deg + 1.0)
    return cv


def step_stats(tx, rgb, thr: float, skip=None) -> dict:
    """«Ступени» внутри части: резкий скачок цвета (ΔE00 > thr) между соседними гранями ОДНОЙ части вдоль поверхности (соседство — по склеенным вершинам). → доля граней со ступенью, доля пар,
    то же среди «достроенных» граней (больше половины их текселей неизвестны — передаётся в tx.unk_face)."""
    F, UV = tx.F, np.asarray(tx.UV)
    T = tx.T
    cu = UV[F].mean(axis=1)
    px = np.clip(np.floor(cu[:, 0] * T).astype(np.int64), 0, T - 1)
    py = np.clip(np.floor((1.0 - cu[:, 1]) * T).astype(np.int64), 0, T - 1)
    lab = rgb2lab(np.asarray(rgb)[py, px][:, :3])
    nf = len(F)
    ew = np.concatenate([tx.FW[:, [0, 1]], tx.FW[:, [1, 2]], tx.FW[:, [2, 0]]])
    ew = np.sort(ew, axis=1)
    fi = np.concatenate([np.arange(nf)] * 3)
    ok = ew[:, 0] != ew[:, 1]
    ew, fi = ew[ok], fi[ok]
    key = ew[:, 0].astype(np.int64) * (int(tx.FW.max()) + 1) + ew[:, 1]
    o = np.argsort(key, kind='stable')
    key, fi = key[o], fi[o]
    same = key[1:] == key[:-1]
    a, b = fi[:-1][same], fi[1:][same]
    keep = (a != b) & (tx.part_f[a] == tx.part_f[b])
    if skip is not None:                                                 # шляпки гвоздей (nail_twins): настоящая деталь, а не шов — грани с ними в ступенях не считаются
        sk = np.asarray(skip, bool)[py, px]
        keep &= ~(sk[a] | sk[b])
    a, b = a[keep], b[keep]
    if len(a) == 0:
        return {'pairs': 0, 'faces_step_pct': 0.0, 'pairs_step_pct': 0.0, 'filled_faces_step_pct': None}
    de = TC.de2000_v(lab[a], lab[b])
    st = de > thr
    faces = np.zeros(nf, bool)
    faces[a[st]] = True
    faces[b[st]] = True
    inpair = np.zeros(nf, bool)
    inpair[a] = True
    inpair[b] = True
    uf = getattr(tx, 'unk_face', None)
    fl = None
    if uf is not None and (inpair & uf).any():
        fl = round(100.0 * float((faces & uf).sum()) / float((inpair & uf).sum()), 2)
    return {'pairs': int(len(a)), 'faces_step_pct': round(100.0 * float(faces.sum()) / max(int(inpair.sum()), 1), 2),
            'pairs_step_pct': round(100.0 * float(st.mean()), 2), 'filled_faces_step_pct': fl}


def _mad_sigma(v: np.ndarray) -> float:
    """Робастный σ (1,4826·MAD): крошка и клочья черновика σ не раздувают."""
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if len(v) else 0.0


def texel_spacing(tx) -> np.ndarray:
    """Поверхностный шаг текселя в долях размера предмета (диагональ рамки): sqrt(площадь грани в 3D / площадь грани в текселях карты) / размер — на каждый тексел; поправка плотности UV."""
    P = tx.P
    size = max(float(np.linalg.norm(P.max(axis=0) - P.min(axis=0))), 1e-12)
    F = tx.F
    A3 = 0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)
    xy = tx.UV * tx.T
    Au = 0.5 * np.abs((xy[F[:, 1], 0] - xy[F[:, 0], 0]) * (xy[F[:, 2], 1] - xy[F[:, 0], 1]) - (xy[F[:, 1], 1] - xy[F[:, 0], 1]) * (xy[F[:, 2], 0] - xy[F[:, 0], 0]))
    return np.sqrt(A3[tx.f] / np.maximum(Au[tx.f], 1e-12)) / size


def _band(lab_l: np.ndarray, mask: np.ndarray, s_lo: float, s_hi: float) -> tuple:
    """Полосовой фильтр (DoG) яркости по маске: размытие(σ_lo) − размытие(σ_hi), оба с нормировкой по весу; → (полоса (T,T), вес при σ_hi (T,T))."""
    img = np.repeat(lab_l[..., None], 3, axis=2)
    b1 = _blur_norm(img, mask, s_lo)[0][..., 0]
    b2, w2 = _blur_norm(img, mask, s_hi)
    return b1 - b2[..., 0], w2


def draft_relief(txs: list, draft: dict, labs: list, kn: list, part_ids: list, pat_parts: set, c: dict, R: dict, calib: dict | None = None) -> tuple:
    """Вариант C-gated (T-164, Codex+директор 21.11): цвет — как stat, фактура невидимого — рельеф яркости черновика TRELLIS (DoG-полоса в МАСШТАБЕ ПОВЕРХНОСТИ, без цвета и пятен), только там, где это безопасно.
    Ворота по части: узорная (pat_parts) → stat; класс материала части (`c['part_class']`: {часть: семья}) вне `allowed_families` (дерево, металл, стекло…) → без рельефа; класса нет → только «однотонная» (σ низкочастотной L известного ≤ homog_max_std).
    Полоса: σ_lo/σ_hi = band_lo/band_hi (доли размера предмета) ÷ шаг текселя части (texel_spacing, поправка плотности UV). Амплитуда: gain = min(gain_max, σ_фото / σ_черновика) — оба σ робастные (MAD), фото — только уверенно известное
    (вес ≥ far_w при σ_hi, вдали от границы; затенённые тексели ниже квантиля tone_shadow_q не входят); потолок |рельеф| ≤ p95_cap·p95|полоса фото| (абсолют, не только gain). Маска «тут ждём фактуру»: локальная энергия черновика / σ_черновика ≤ 1 (гладкое остаётся гладким).
    Выброс (|полоса| > clip_k·σ, или большое пятно: размытое L (patch_frac) отличается от медианы части > patch_dl) и тексели без черновика — не берутся; доля выбросов > part_max_share — часть без рельефа. Тексели с `ok` черновика сужаются на ok_erode_px (границы/силуэт).
    → ([(значение L (T·T,), годно (T·T,)) по геометриям], отчёт по частям с причиной «ворот»). Стык (затухание от границы фото) и «гладкая заливка» вместо плитки — в fill()."""
    from scipy.ndimage import binary_dilation, binary_erosion, gaussian_filter
    spacing = [texel_spacing(tx) for tx in txs]
    cls = c.get('part_class') or {}
    out = [(np.zeros(tx.T * tx.T), np.zeros(tx.T * tx.T, bool)) for tx in txs]
    rp = {}
    dok = []
    for gi in range(len(txs)):
        ok_ = draft['ok'][gi]
        dok.append(binary_erosion(ok_, iterations=int(R['ok_erode_px'])) if R['ok_erode_px'] > 0 else ok_)
    for p in part_ids:
        if p in pat_parts:
            rp[p] = {'fallback': 'узорная часть — stat (узор из фото)'}
            continue
        fam = cls.get(p, cls.get(str(p)))
        if fam is not None and fam not in R['allowed_families']:
            rp[p] = {'fallback': f'класс {fam!r} вне допустимых {R["allowed_families"]} — stat', 'family': fam}
            continue
        sp = float(np.median(np.concatenate([spacing[gi][tx.part == p] for gi, tx in enumerate(txs)] or [np.zeros(0)]))) if any((tx.part == p).any() for tx in txs) else 0.0
        if sp <= 0:
            continue
        s_lo = float(np.clip(R['band_lo'] / sp, R['sigma_lo_min'], R['sigma_lo_max']))
        s_hi = float(np.clip(R['band_hi'] / sp, 2.0 * s_lo, R['sigma_hi_max']))
        selk = [kn[gi].reshape(-1)[tx.ti] & (tx.part == p) for gi, tx in enumerate(txs)]
        Lk = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[selk[gi]], 0] for gi, tx in enumerate(txs)])
        s_lo_k, s_hi_k, calib_q = s_lo, s_hi, None
        if len(Lk) < c['min_known'] and calib and p in calib and calib[p] not in pat_parts:
            # Ш6 вариант 2 для части БЕЗ своего фото: «чистую ткань» (σ и p95 полосы) берём у части-донора тона той же роли (этап 3), полосу фото считаем в масштабе ДОНОРА (его шаг текселя),
            # полосу черновика — в масштабе этой части: сравниваются одинаковые физические размеры; своего фото нет → «ворота однотонности» смотрят на донора
            calib_q = int(calib[p])
            selk = [kn[gi].reshape(-1)[tx.ti] & (tx.part == calib_q) for gi, tx in enumerate(txs)]
            Lk = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[selk[gi]], 0] for gi, tx in enumerate(txs)])
            spq = float(np.median(np.concatenate([spacing[gi][tx.part == calib_q] for gi, tx in enumerate(txs)] or [np.zeros(0)]))) if any((tx.part == calib_q).any() for tx in txs) else 0.0
            if spq > 0:
                s_lo_k = float(np.clip(R['band_lo'] / spq, R['sigma_lo_min'], R['sigma_lo_max']))
                s_hi_k = float(np.clip(R['band_hi'] / spq, 2.0 * s_lo_k, R['sigma_hi_max']))
        if len(Lk) < c['min_known']:
            rp[p] = {'fallback': f'мало известного ({len(Lk)} текселей) — stat'}
            continue
        shade = float(np.quantile(Lk, c['tone_shadow_q'])) if c['tone_shadow_q'] > 0 else -1e9
        pb, dbd, dlow = [], [], []
        for gi, tx in enumerate(txs):
            T = tx.T
            Lm = labs[gi][..., 0]
            m_vis = kn[gi] & (Lm >= shade)
            band, w2 = _band(Lm, m_vis, s_lo_k, s_hi_k)
            pb.append(band.reshape(-1)[tx.ti[selk[gi] & (w2.reshape(-1)[tx.ti] >= R['far_w']) & (Lm.reshape(-1)[tx.ti] >= shade)]])
            dl = draft['lab'][gi][..., 0]
            band_d, wd = _band(dl, dok[gi], s_lo, s_hi)
            band_d = np.where(dok[gi], band_d, 0.0)
            loc = np.sqrt(gaussian_filter(band_d ** 2, s_hi, mode='nearest'))
            lowL = _blur_norm(np.repeat(dl[..., None], 3, axis=2), dok[gi], max(R['patch_frac'] / sp, 3.0 * s_hi))[0][..., 0]
            hp = np.where(dok[gi], dl - _blur_norm(np.repeat(dl[..., None], 3, axis=2), dok[gi], 1.0)[0][..., 0], 0.0)      # пиксельная высокая частота — для поиска крошки (в полосе она размазана на σ_hi)
            dbd.append((band_d, loc, lowL, wd, hp))
        PB = np.concatenate(pb)
        if len(PB) < c['min_known']:
            rp[p] = {'fallback': f'мало уверенного фото в полосе ({len(PB)}) — stat', 'spacing': round(sp, 5)}
            continue
        sv, p95 = _mad_sigma(PB), float(np.quantile(np.abs(PB), 0.95))
        selD = [dok[gi].reshape(-1)[tx.ti] & (tx.part == p) & (dbd[gi][3].reshape(-1)[tx.ti] >= R['far_w']) for gi, tx in enumerate(txs)]
        DD = np.concatenate([dbd[gi][0].reshape(-1)[tx.ti[selD[gi]]] for gi, tx in enumerate(txs)])
        if len(DD) < c['min_known']:
            rp[p] = {'fallback': f'мало черновика в части ({len(DD)}) — stat', 'spacing': round(sp, 5)}
            continue
        sd = _mad_sigma(DD)
        homog = float(np.concatenate([_blur_norm(np.repeat(labs[gi][..., 0][..., None], 3, axis=2), kn[gi], s_hi_k)[0][..., 0].reshape(-1)[tx.ti[selk[gi]]] for gi, tx in enumerate(txs)]).std())
        info = {'family': fam, 'spacing': round(sp, 5), 'sigma_lo_px': round(s_lo, 2), 'sigma_hi_px': round(s_hi, 2), 'sigma_photo': round(sv, 3), 'sigma_draft': round(sd, 3), 'p95_photo': round(p95, 3), 'homog_std': round(homog, 2), 'calib_donor': calib_q, 'fallback': None}
        if fam is None and homog > R['homog_max_std']:
            info['fallback'] = f'класса нет, часть неоднотонная (σ низких частот {homog:.1f} > {R["homog_max_std"]}) — stat'
            rp[p] = info
            continue
        med = float(np.median(np.concatenate([dbd[gi][2].reshape(-1)[tx.ti[selD[gi]]] for gi, tx in enumerate(txs)])))
        sdh = _mad_sigma(np.concatenate([dbd[gi][4].reshape(-1)[tx.ti[selD[gi]]] for gi, tx in enumerate(txs)]))
        lim = R['clip_k'] * max(sdh, 0.3)
        cand, bad_n, tot_n = [], 0, 0
        for gi, tx in enumerate(txs):
            T = tx.T
            band_d, loc, lowL, wd, hp = dbd[gi]
            outl = (np.abs(hp) > lim) | (np.abs(lowL - med) > R['patch_dl'])
            selA = dok[gi].reshape(-1)[tx.ti] & (tx.part == p)                    # применяем на всём, где есть черновик (края островка тоже: полоса там считается по нормировке веса); σ оценивали по дальним
            om = np.zeros(T * T, bool)
            om[tx.ti[selA & outl.reshape(-1)[tx.ti]]] = True
            if R['dilate_px'] > 0:
                om = binary_dilation(om.reshape(T, T), iterations=int(R['dilate_px'])).reshape(-1)
            ti = tx.ti[selA]
            bad_n += int(om[ti].sum())
            tot_n += len(ti)
            cand.append((ti, om))
        share = bad_n / max(tot_n, 1)
        nh_ = nl_ = 0
        for gi, tx in enumerate(txs):                            # разбор выбросов по причинам (в отчёт): крошка (пиксельная ВЧ) / большое пятно (низкочастотное L)
            _b, _l, lowL_, _w, hp_ = dbd[gi]
            sA = dok[gi].reshape(-1)[tx.ti] & (tx.part == p)
            nh_ += int((np.abs(hp_.reshape(-1)[tx.ti[sA]]) > lim).sum())
            nl_ += int((np.abs(lowL_.reshape(-1)[tx.ti[sA]] - med) > R['patch_dl']).sum())
        info.update(outlier_pct=round(100.0 * share, 2), draft_texels=tot_n)
        info.update(crumb_pct=round(100.0 * nh_ / max(tot_n, 1), 2), blob_pct=round(100.0 * nl_ / max(tot_n, 1), 2), lim=round(lim, 3))
        if share > R['part_max_share']:
            info['fallback'] = 'выбросов %.1f %% > %.0f %% — часть без рельефа (stat/гладко)' % (100.0 * share, 100.0 * R['part_max_share'])
            rp[p] = info
            continue
        gain = float(min(R['gain_max'], sv / max(sd, 1e-6)))
        cap = R['p95_cap'] * max(p95, 1e-6)
        info['gain'] = round(gain, 3)
        n_use = 0
        for gi, (ti, om) in enumerate(cand):
            band_d, loc, lowL, wd, hp = dbd[gi]
            good = ~om[ti]
            w_det = np.clip(loc.reshape(-1)[ti] / max(sd, 1e-6), 0.0, 1.0)
            val, okm = out[gi]
            val[ti[good]] = np.clip(gain * band_d.reshape(-1)[ti[good]] * w_det[good], -cap, cap)
            okm[ti[good]] = True
            n_use += int(good.sum())
        info['usable_texels'] = n_use
        rp[p] = info
    return out, rp


# ---------------------------------------------------------------- заливка ---------------------------------------
def fill(geoms: list, known: list, parts: list | None = None, cfg: dict | None = None, mirror: bool = True, draft: dict | None = None, tone_only: list | None = None) -> dict:
    """geoms — `tex_coverage.load_geoms`; known — по геометрии (T×T bool), parts — по геометрии номера частей ГРАНЕЙ (None — одна часть).
    draft — черновик TRELLIS на ту же форму/развёртку (`draft_texels`): {'lab': [(T,T,3) Lab], 'ok': [(T,T) bool]}; нужен при cfg['source']=='trellis': невидимое берёт цвет черновика,
    сдвинутый переносом статистики Lab (медиана/разброс части: черновик → видимое фото), детали черновика сохраняются; стыки — та же растушёвка. 'stat' (по умолчанию) — цвет части + лоскут фактуры.
    tone_only — (Ш6, р.8) по геометриям T×T bool: тексели с ТОНОВЫМ полем этапа 6 (цвет есть в visible.glb, фото-правды нет; в `known` НЕ входят). Цвет такого тексела остаётся как есть (тон-поле, среднее сохраняется),
    а фактура/заём кладутся поверх как на неизвестный (остаток без среднего); в статистику частей, пул блоков и доноры они не входят. Нет — поведение прежнее.
    → {'tex': [uint8 (T,T,3) по геометриям], 'report': {...}}. Форма и развёртка не меняются."""
    from scipy.ndimage import binary_erosion, distance_transform_edt
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    c = dict(FILL, **(cfg or {}))
    if c['source'] not in ('stat', 'trellis', 'trellis_relief'):
        raise ValueError(f"source {c['source']!r}: ждём stat | trellis | trellis_relief")
    if c['source'] in ('trellis', 'trellis_relief') and draft is None:
        raise ValueError(f"source={c['source']} требует draft (draft_texels)")
    t0 = time.time()
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    Pall = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    txs, labs, kn, tex_in, kn_keep = [], [], [], [], []
    for gi, g in enumerate(geoms):
        T = _grid(g)
        tx = Tex(g, Pall[offs[gi]:offs[gi + 1]], T, None if parts is None else parts[gi], c['cross_islands'])
        rgb = np.asarray(g['tex'])[..., :3]
        if rgb.shape[0] != T:
            raise ValueError('текстура больше сетки карты (cap) — загрузите с её размером')
        k = np.asarray(known[gi], bool).copy()
        if tone_only is not None and gi < len(tone_only):
            k &= ~np.asarray(tone_only[gi], bool)              # тон-только — не фото-правда: в известные не входит (фактура и статистика — не отсюда)
        k0 = k & ~unpainted_mask(rgb)                      # известное этапа 6 и покрашенное — НЕ перезаписывается никогда (правило «заливка не меняет известное»)
        if c['erode_known'] > 0:
            k = binary_erosion(k, iterations=int(c['erode_known']))
        k &= ~unpainted_mask(rgb)
        txs.append(tx)
        kn.append(k)
        kn_keep.append(k0)
        tex_in.append(rgb)
        labs.append(rgb2lab(rgb.reshape(-1, 3)).reshape(T, T, 3))
    rep = {'geoms': [], 'parts': {}, 'mirror': None, 'fallback_global': 0, 'no_patch': 0, 'time_s': {}}
    # --- статистика частей (Lab среднее и разброс), по известным
    part_ids = sorted({int(p) for t in txs for p in np.unique(t.part)})
    stat, glob_l = {}, []
    for gi, tx in enumerate(txs):
        glob_l.append(labs[gi].reshape(-1, 3)[kn[gi].reshape(-1)])
    glob_l = np.concatenate(glob_l) if glob_l else np.zeros((0, 3))
    g_mean = tone_of(glob_l, c)
    g_std = glob_l.std(axis=0) if len(glob_l) else np.zeros(3)
    for p in part_ids:
        L = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
        if len(L) >= c['min_known']:
            stat[p] = (tone_of(L, c), L.std(axis=0), len(L), False)
        else:
            stat[p] = (g_mean, g_std, len(L), True)
            rep['fallback_global'] += 1
    pat_std, pat_eff = part_pattern(txs, labs, kn, part_ids, c, {p: float(stat[p][0][0]) for p in part_ids})              # одна функция на 07 и на мерку Б (мишень wholepart не узорная)
    for p in part_ids:
        L = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
        rep['parts'][p] = {'known_texels': int(len(L)), 'pattern': bool(pat_eff[p] > c['pattern_chroma']), 'pattern_chroma_std': round(float(pat_std[p]), 2), 'pattern_chroma_eff': round(float(pat_eff[p]), 2), 'mean_lab': [round(float(x), 2) for x in stat[p][0]], 'std_lab': [round(float(x), 2) for x in stat[p][1]], 'stats_from_global': stat[p][3]}
    rep['tone_shared'] = {}
    roles_ = c.get('part_role') or {}
    for role in c.get('tone_share_roles') or []:                     # один материал — один тон: части одной роли (ножки…) красятся общим тоном (по свету, без теней)
        mem = [p for p in part_ids if roles_.get(p, roles_.get(str(p))) == role]
        if len(mem) < 2:
            continue
        Lp = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & np.isin(tx.part, mem)]] for gi, tx in enumerate(txs)])
        if len(Lp) < c['min_known']:
            continue
        tone = tone_of(Lp, c)
        for p in mem:
            stat[p] = (tone, stat[p][1], stat[p][2], False)
        rep['tone_shared'][role] = {'parts': [int(p) for p in mem], 'tone': [round(float(x), 2) for x in tone], 'known': int(len(Lp))}
    rep['tone_from_neighbour'], rep['tone_source'], skip_parts = {}, {}, set()
    if c.get('part_role'):                                       # иерархия источника тона части: своя → донор той же роли (совместимый тон) → каталог → не красить
        tot_ = {p: int(sum(int((tx.part == p).sum()) for tx in txs)) for p in part_ids}
        kc_ = {p: int(stat[p][2]) for p in part_ids}
        fg_ = {p: bool(stat[p][3]) for p in part_ids}
        info_ = choose_tone_sources(part_ids, c['part_role'], kc_, tot_, fg_, {p: stat[p][0] for p in part_ids}, part_borders(txs), c)
        for p in part_ids:
            i_ = info_[p]
            rep['tone_source'][int(p)] = dict(i_, known=kc_[p], texels=tot_[p])
            if i_['source'] == 'donor':
                q = i_['donor']
                stat[p] = (stat[q][0], stat[q][1], stat[p][2], False)
                rep['tone_from_neighbour'][int(p)] = {'donor': int(q), 'known': kc_[p], 'texels': tot_[p], 'tone': [round(float(x), 2) for x in stat[q][0]]}
            elif i_['source'] == 'catalog':
                role = c['part_role'].get(p, c['part_role'].get(str(p)))
                stat[p] = (np.asarray(c['catalog_tone'][role], float), stat[p][1], stat[p][2], False)
            elif i_['source'] == 'skip':
                skip_parts.add(p)
    rep['tone_skipped_parts'] = sorted(int(p) for p in skip_parts)
    dshift = None
    if c['source'] == 'trellis':                     # перенос статистики Lab: черновик части → видимое фото той же части (медиана и разброс по каналам)
        dshift = []
        rep['draft'] = {'parts': {}, 'ok_pct': 0.0}
        n_ok = n_all_t = 0
        dm = {}
        dlab = [draft['lab'][gi] for gi in range(len(txs))]
        plow = [None] * len(txs)
        if c['draft_blur_px'] > 0:                   # черновик и фото — в низких частотах: штрих/муар черновика не переносится, разброс сравнивается по тем же частотам
            dlab = [_blur_norm(draft['lab'][gi], draft['ok'][gi], c['draft_blur_px'])[0] for gi in range(len(txs))]
            plow = [_blur_norm(labs[gi], kn[gi], c['draft_blur_px'])[0] for gi in range(len(txs))]
        for p in part_ids:
            D = np.concatenate([dlab[gi].reshape(-1, 3)[tx.ti[draft['ok'][gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
            if len(D) >= c['min_known']:
                dmed, dstd = tone_of(D, c), D.std(axis=0)
                if plow[0] is not None:
                    K_ = np.concatenate([plow[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]] for gi, tx in enumerate(txs)])
                    ref_std = K_.std(axis=0) if len(K_) >= c['min_known'] else stat[p][1]
                else:
                    ref_std = stat[p][1]
                scale = np.clip(ref_std / np.maximum(dstd, 1e-3), c['draft_scale_min'], c['draft_scale_max'])
                dm[p] = (dmed, scale)
                rep['draft']['parts'][p] = {'texels': int(len(D)), 'draft_median_lab': [round(float(x), 2) for x in dmed], 'draft_std_lab': [round(float(x), 2) for x in dstd], 'scale': [round(float(x), 2) for x in scale]}
            else:
                rep['draft']['parts'][p] = {'texels': int(len(D)), 'no_draft': True}
        for gi, tx in enumerate(txs):
            T = tx.T
            sh = np.zeros((T * T, 3))
            okf = np.zeros(T * T, bool)
            dl = dlab[gi].reshape(-1, 3)
            for p in part_ids:
                if p not in dm:
                    continue
                idx = tx.ti[(tx.part == p) & draft['ok'][gi].reshape(-1)[tx.ti]]
                sh[idx] = (dl[idx] - dm[p][0]) * dm[p][1] + stat[p][0]
                okf[idx] = True
            n_ok += int(okf[tx.ti].sum())
            n_all_t += len(tx.ti)
            dshift.append((sh, okf))
        rep['draft']['ok_pct'] = round(100.0 * n_ok / max(n_all_t, 1), 2)
    rep['time_s']['prepare'] = round(time.time() - t0, 2)
    # --- шаг 1: зеркало
    out_lab = [lb.copy() for lb in labs]
    done = [k.copy() for k in kn]                  # известное или уже залитое зеркалом/геодезией (источник дальнейших шагов)
    mirrored = [np.zeros_like(k) for k in kn]
    sym = symmetry(txs, kn, c['mirror_eps'], c['sample'], c['mirror_cos']) if mirror else {'axis': None, 'score': 0.0, 'planes': {}}
    rep['mirror'] = {'axis': sym['axis'], 'score': sym['score'], 'planes': sym['planes'], 'applied': False, 'texels': 0}
    if mirror and sym['axis'] is not None and sym['score'] >= c['mirror_min_score']:
        R = np.ones(3)
        R[sym['axis']] = -1
        rep['mirror']['applied'] = True
        for p in part_ids:
            srcQ, srcN, srcL = [], [], []
            for gi, tx in enumerate(txs):
                kk = kn[gi].reshape(-1)[tx.ti] & (tx.part == p)
                srcQ.append(tx.Q[kk])
                srcN.append(tx.N[kk])
                srcL.append(labs[gi].reshape(-1, 3)[tx.ti[kk]])
            srcQ, srcN, srcL = np.concatenate(srcQ), np.concatenate(srcN), np.concatenate(srcL)
            if len(srcQ) == 0:
                continue
            tree = cKDTree(srcQ)
            for gi, tx in enumerate(txs):
                unk = (~done[gi].reshape(-1)[tx.ti]) & (tx.part == p)
                if not unk.any():
                    continue
                d, j = tree.query(tx.Q[unk] * R, k=1, distance_upper_bound=c['mirror_eps'] * 1.5)
                okj = np.isfinite(d)
                jj = np.where(okj, j, 0)
                cs = np.abs((tx.N[unk] * R * srcN[jj]).sum(axis=1))
                use = okj & (cs > c['mirror_cos'])
                me = RULES['mirror_extreme']
                lim_dark = max(dark_floor(float(stat[p][0][0]), me['black_abs'], me['black_rel']), float(np.quantile(srcL[:, 0], me['rel_quantile'])) - float(me['rel_margin']))      # темнее абсолютно чёрного ИЛИ темнее почти всего известного этой части на запас
                black = use & (srcL[jj, 0] < lim_dark)                  # двойник — чёрный/слишком тёмный тексель (тень, дыра, край фото): не копируется, этот тексель красит геодезия
                rep['mirror']['dropped_black'] = rep['mirror'].get('dropped_black', 0) + int(black.sum())
                use &= ~black
                idx = tx.ti[np.nonzero(unk)[0][use]]
                flat = out_lab[gi].reshape(-1, 3)
                flat[idx] = srcL[jj[use]]
                done[gi].reshape(-1)[idx] = True
                mirrored[gi].reshape(-1)[idx] = True
                rep['mirror']['texels'] += int(use.sum())
    rep['time_s']['mirror'] = round(time.time() - t0, 2)
    _md = rep['mirror'].get('dropped_black', 0)
    rep['mirror']['dropped_pct'] = round(100.0 * _md / max(_md + rep['mirror']['texels'], 1), 1)
    # --- шаг 2: геодезическая заливка (низкие частоты) по поверхности ТОЙ ЖЕ части; зеркальное достраивается растушёвкой от известного
    lam_all, unk_all = [], []
    for gi, g in enumerate(geoms):
        tx = txs[gi]
        nvw = len(tx.PW)
        kflat = kn[gi].reshape(-1)[tx.ti]
        mflat = mirrored[gi].reshape(-1)[tx.ti]
        unk = ~kflat
        lab_flat = out_lab[gi].reshape(-1, 3)
        lam_t = np.zeros(len(tx.ti))
        for p in sorted({int(x) for x in np.unique(tx.part_f)}):
            Fp = tx.FW[tx.part_f == p]
            tsel = unk & (tx.part == p)
            if len(Fp) == 0 or not tsel.any():
                continue
            e = np.unique(np.sort(np.concatenate([Fp[:, [0, 1]], Fp[:, [1, 2]], Fp[:, [2, 0]]]), axis=1), axis=0)
            e = e[e[:, 0] != e[:, 1]]
            ln = np.linalg.norm(tx.PW[e[:, 0]] - tx.PW[e[:, 1]], axis=1) + 1e-9
            gr = coo_matrix((np.concatenate([ln, ln]), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(nvw, nvw)).tocsr()
            used = np.zeros(nvw, bool)
            used[Fp.reshape(-1)] = True
            Wn = gr.copy()
            Wn.data = np.ones_like(Wn.data)

            def field(src_tex):
                """Источник — тексели `src_tex` (bool по занятым) этой части → расстояние по поверхности до ближайшего источника и его (сглаженный по графу) цвет, по склеенным вершинам."""
                vw = np.zeros(nvw)
                vc = np.zeros((nvw, 3))
                sm = src_tex & (tx.part == p)
                fk, bk, lk = tx.f[sm], tx.bary[sm], lab_flat[tx.ti[sm]]
                for i in range(3):
                    vi = tx.FW[fk, i]
                    vw += np.bincount(vi, weights=bk[:, i], minlength=nvw)
                    for ch in range(3):
                        vc[:, ch] += np.bincount(vi, weights=bk[:, i] * lk[:, ch], minlength=nvw)
                vknown = vw > 1e-6
                wk = vknown.astype(np.float64)
                vcol = np.where(vknown[:, None], vc / np.maximum(vw, 1e-12)[:, None], 0.0)
                for _ in range(int(c['smooth_iter'])):
                    num = Wn @ (vcol * wk[:, None]) + vcol * wk[:, None]
                    den = Wn @ wk + wk
                    vcol = np.where((den > 0)[:, None], num / np.maximum(den, 1e-12)[:, None], 0.0)
                if rep['parts'][p]['pattern'] and c['src_dev_pattern'] > 0:      # узорная: цвет-источник не дальше `src_dev_pattern` от тона части (цветок у края не растекается по соседней детали)
                    dv = vcol - stat[p][0]
                    nv = np.linalg.norm(dv, axis=1, keepdims=True)
                    has = np.any(vcol != 0.0, axis=1, keepdims=True)
                    vcol = np.where(has, stat[p][0] + dv * np.minimum(1.0, c['src_dev_pattern'] / np.maximum(nv, 1e-9)), 0.0)
                src = np.nonzero(vknown & used)[0]
                dist = np.full(nvw, np.inf)
                col = np.zeros((nvw, 3))
                if len(src):
                    d, _pred, srcs = dijkstra(gr, directed=False, indices=src, min_only=True, return_predecessors=True)
                    reach = np.isfinite(d) & used & (srcs >= 0)
                    dist[reach] = d[reach]
                    col[reach] = vcol[srcs[reach]]
                    if c['diffuse_iter'] > 0:                  # неизвестные вершины — среднее соседей (известные зафиксированы): плавный переход вместо «зон источников»
                        deg = np.asarray(Wn.sum(axis=1)).ravel()
                        free = reach & ~vknown
                        cur = col.copy()
                        cur[vknown & used] = vcol[vknown & used]
                        for _ in range(int(c['diffuse_iter'])):
                            nxt = (Wn @ cur) / np.maximum(deg, 1.0)[:, None]
                            cur[free] = nxt[free]
                        col[free] = cur[free]
                return dist, col

            def at_texels(dist, col, length, sel):
                """Вес стороны источника exp(−d/length) и её цвет на текселях `sel` (барицентрическая интерполяция весов и цвет·вес)."""
                lv = np.where(np.isfinite(dist), np.exp(-np.where(np.isfinite(dist), dist, 0.0) / length), 0.0)
                ff, wv = tx.f[sel], tx.bary[sel]
                av = lv[tx.FW[ff]]
                at = (wv * av).sum(axis=1)
                ct = (wv[..., None] * (av[..., None] * col[tx.FW[ff]])).sum(axis=1)
                return at, ct / np.maximum(at, 1e-9)[:, None]

            msel_t = tsel & mflat                        # зеркальные: растушёвка к известному у стыка «фото → достройка»
            gsel_t = tsel & ~mflat                       # прочие: затухание от известного и зеркального к цвету части
            if gsel_t.any():
                dist_a, col_a = field(kflat | mflat)
                flat_idx = tx.ti[gsel_t]
                if dshift is not None:                   # черновик со сдвигом тона вместо цвета части; нет черновика в тексele — цвет части
                    at, gc = at_texels(dist_a, col_a, c['feather_len'], gsel_t)
                    sh, okf = dshift[gi]
                    base = np.where(okf[flat_idx][:, None], sh[flat_idx], stat[p][0])
                else:
                    at, gc = at_texels(dist_a, col_a, c['geo_len'], gsel_t)
                    base = stat[p][0]
                lab_flat[flat_idx] = at[:, None] * gc + (1.0 - at[:, None]) * base
                lam_t[gsel_t] = at
            if msel_t.any():
                dist_k, col_k = field(kflat)
                at, gc = at_texels(dist_k, col_k, c['feather_len'], msel_t)
                flat_idx = tx.ti[msel_t]
                lab_flat[flat_idx] = at[:, None] * gc + (1.0 - at[:, None]) * lab_flat[flat_idx]
                lam_t[msel_t] = at
        lam_all.append(lam_t)
        unk_all.append(unk)
        rep['geoms'].append({'texels': int(len(tx.ti)), 'known': int(kflat.sum()), 'mirrored': int(mflat.sum()),
                             'geodesic': int((unk & ~mflat & (lam_t >= 0.5)).sum()), 'part_mean': int((unk & ~mflat & (lam_t < 0.5)).sum())})
    rep['time_s']['geodesic'] = round(time.time() - t0, 2)
    # --- выравнивание яркости достроенного к видимому той же части (медиана L; поправка гаснет к стыку, зеркальное не трогаем)
    rep['brightness'] = {}
    for p in (part_ids if dshift is None else []):
        vals = [out_lab[gi].reshape(-1, 3)[tx.ti[unk_all[gi] & ~mirrored[gi].reshape(-1)[tx.ti] & (tx.part == p) & (lam_all[gi] < 0.2)]][:, 0] for gi, tx in enumerate(txs)]
        vals = np.concatenate(vals)
        if len(vals) < 50:
            continue
        shift = float(np.clip(stat[p][0][0] - np.median(vals), -c['dL_max'], c['dL_max']))
        rep['brightness'][p] = {'dL_before': round(float(np.median(vals) - stat[p][0][0]), 2), 'applied': 0.0}
        if abs(shift) < 0.5:
            continue
        for gi, tx in enumerate(txs):
            sel = unk_all[gi] & ~mirrored[gi].reshape(-1)[tx.ti] & (tx.part == p)
            out_lab[gi].reshape(-1, 3)[tx.ti[sel], 0] += shift * (1.0 - lam_all[gi][sel])
        rep['brightness'][p]['applied'] = round(shift, 2)
    # --- лёгкое затенение углублений по форме (AO-подобно, опция `ao` > 0): L *= 1 − ao·вогнутость
    if c['ao'] > 0:
        for gi, tx in enumerate(txs):
            cv = concavity(tx)
            ff, wv = tx.f, tx.bary
            ct = (wv * cv[tx.FW[ff]]).sum(axis=1)
            sel = unk_all[gi]
            out_lab[gi].reshape(-1, 3)[tx.ti[sel], 0] *= 1.0 - c['ao'] * np.clip(ct[sel], 0.0, 1.0)
        rep['ao'] = c['ao']
    # --- шаг 3: фактура (остаток высоких частот известного участка той же части), только на залитое не зеркалом
    rng = np.random.RandomState(5)
    patches, patch_gain = {}, {}
    blk = {}                                                  # по геометрии: остаток, номер части и островка (пиксель карты)
    for gi, tx in enumerate(txs):
        T = tx.T
        pm = np.zeros((T, T), np.int32) - 1
        pm.reshape(-1)[tx.ti] = tx.part
        im = np.zeros((T, T), np.int64) - 1
        im.reshape(-1)[tx.ti] = tx.island
        blur, _ = _blur_norm(labs[gi], kn[gi], c['hp_px'])
        blk[gi] = (labs[gi] - blur, pm, im)
    pat_parts = {p for p in part_ids if rep['parts'][p]['pattern']}
    raw_mean = {}
    shade_lo = {}
    for p in pat_parts:
        Lv = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)], 0] for gi, tx in enumerate(txs)])
        shade_lo[p] = float(np.quantile(Lv, c['tone_shadow_q'])) if len(Lv) and c['tone_shadow_q'] > 0 else -1e9
    if c['patch_mode'] == 'quilt' and (dshift is None or c['draft_texture']):
        qrng = np.random.RandomState(7)
        pr_S = pr_lab = pr_kn = pr_pm = None
        for p in part_ids:
            resg, okg = [], []
            for gi, tx in enumerate(txs):
                res_, pm, _im = blk[gi]
                if p in pat_parts:                               # узорная: остаток от тона части; затенённые тексели (складки) в узор не входят — нулевое отклонение
                    resq = (labs[gi] - stat[p][0]) * (labs[gi][..., 0] >= shade_lo[p])[..., None]
                else:
                    resq = res_
                resg.append(resq * kn[gi][..., None])
                okg.append(kn[gi] & (pm == p))
            cnt = [int(o.sum()) for o in okg]
            if sum(cnt) < 200:
                continue
            rp = None
            if p in pat_parts and c["pattern_render"]:                  # узорная: блоки — из непрерывного кадра видимой стороны (az фото), не из дырявой развёртки
                if pr_S is None:
                    pr_S = view_samples(geoms, c["pr_az"], int(c["pr_res"]), c["pr_ortho"], c["pr_el"])
                    pr_lab = sample_view(pr_S, labs)
                    pr_kn = sample_view(pr_S, kn)
                    pr_pm = sample_view(pr_S, [blk[gi][1] for gi in range(len(txs))], -1)
                cosimg = np.zeros(pr_S["res"] * pr_S["res"])
                cosimg[pr_S["hit"]] = pr_S["cos"]
                okr = pr_kn & (pr_pm == p) & (cosimg.reshape(pr_S["res"], pr_S["res"]) >= c["pr_cos_min"])
                resr = (pr_lab - stat[p][0]) * (pr_lab[..., 0] >= shade_lo[p])[..., None]
                if c["pr_clip_l"] > 0 and okr.any():                      # блики и белая кайма рамы (светлее тона) в образец узора не входят: плюс по яркости срезается; тёмное (ветки) остаётся
                    rl = resr[..., 0][okr]
                    lim = max(c["pr_clip_l"] * 1.4826 * float(np.median(np.abs(rl - np.median(rl)))), c["pr_clip_l_min"])
                    resr[..., 0] = np.minimum(resr[..., 0], lim)
                sc = texel_scale(geoms, parts, p, pr_S["ppu"])
                rp = render_pool(resr * okr[..., None], okr, c, sc)
                rep.setdefault("pattern_src", {})[int(p)] = ({"render": True, "pixels": int(okr.sum()), "scale": round(sc, 3), "block": rp[0], "pool": len(rp[1])} if rp is not None else {"render": False, "pixels": int(okr.sum()), "scale": round(sc, 3)})
            if rp is not None:
                Bq, pool = rp
                oq = max(2, int(round(Bq * c["quilt_overlap"])))
            else:
                gbest = int(np.argmax(cnt))                           # период узора — по геометрии, где у части больше всего известного
                Bq = pattern_period(resg[gbest][..., 0], okg[gbest], int(c['quilt_block_min']), int(c['quilt_block_max']))
                oq = max(2, int(round(Bq * c['quilt_overlap'])))
                pool = []
                ints = {}
                for gi, tx in enumerate(txs):                          # дыры известного (грани мельче пикселя фото) закрываются ближайшим известным остатком той же части; блок годен, если дыры не дальше `quilt_fill_px`
                    if tx.T < Bq or cnt[gi] < Bq * Bq:
                        continue
                    dist_, (iy_, ix_) = distance_transform_edt(~okg[gi], return_indices=True)
                    near_ = dist_ <= c['quilt_fill_px']
                    ints[gi] = (resg[gi][iy_, ix_], [np.pad(a.astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0))) for a in (okg[gi], blk[gi][1] == p, near_)])
                for thr in (c['quilt_known'], 0.7, 0.5):               # известного мало — порог доли известного в блоке снижается, пока в пуле не наберётся `quilt_pool_min`
                    pool = []
                    for gi, (fill_, (I_ok, I_pm, I_nr)) in ints.items():
                        T = txs[gi].T
                        s = max(Bq // 2, 1)
                        ys = np.arange(0, T - Bq + 1, s)
                        Y, X = np.meshgrid(ys, ys, indexing='ij')

                        def bsum(I):
                            return I[Y + Bq, X + Bq] - I[Y, X + Bq] - I[Y + Bq, X] + I[Y, X]
                        good = (bsum(I_pm) >= Bq * Bq - 0.5) & (bsum(I_ok) >= thr * Bq * Bq) & (bsum(I_nr) >= Bq * Bq - 0.5)
                        for by, bx in zip(*np.nonzero(good)):
                            pool.append(fill_[Y[by, bx]:Y[by, bx] + Bq, X[by, bx]:X[by, bx] + Bq])
                    if len(pool) >= int(c['quilt_pool_min']):
                        break
            if len(pool) < 4:
                continue
            qo = RULES['quilt_outlier']
            if p not in pat_parts and qo['k'] > 0 and len(pool) >= int(qo['min_pool']):       # неузорная часть: блок с чужеродным тёмным/светлым пятном (тень, шов, фон на краю фото) в образец не идёт
                n0 = len(pool)
                pool, nrej = reject_outlier_blocks(pool, qo['k'], qo['floor'], qo['quantile'])
                rep.setdefault('quilt_rejected', {})[int(p)] = nrej
                rep.setdefault('quilt_rejected_share', {})[int(p)] = round(nrej / max(n0, 1), 3)
                if len(pool) < 4:
                    continue
            qe = RULES['quilt_extreme']
            if p in pat_parts and qe['share'] > 0:                  # узорная часть (остаток от тона): блок с чёрным (тень, дыра) или сильно светлее тона (белый фон края фото) в образец не идёт; цветы и ветви — не такие
                n0 = len(pool)
                pool, nrej = reject_extreme_blocks(pool, float(stat[p][0][0]), qe['dL_hi'], dark_floor(float(stat[p][0][0]), qe['black_abs'], qe['black_rel']), qe['share'])
                rep.setdefault('quilt_rejected', {})[int(p)] = nrej
                rep.setdefault('quilt_rejected_share', {})[int(p)] = round(nrej / max(n0, 1), 3)
                if len(pool) < 4:
                    continue
            if len(pool) > int(c['quilt_pool']):
                pool = [pool[i] for i in qrng.choice(len(pool), int(c['quilt_pool']), replace=False)]
            P = np.stack(pool).astype(np.float64)
            # выравнивание блока к тону части: среднее (узорная — медиана: цветы не сдвигают фон) → 0; разброс → к типичному
            off = np.median(P.reshape(len(P), -1, 3), axis=1) if p in pat_parts else P.reshape(len(P), -1, 3).mean(axis=1)
            P = P - off[:, None, None, :]
            sd = P.reshape(len(P), -1).std(axis=1)
            glo, ghi = c['quilt_gain'] if p in pat_parts else (0.6, 1.6)
            P = P * np.clip(float(np.median(sd)) / np.maximum(sd, 1e-6), glo, ghi)[:, None, None, None]
            nq = int(max(c['quilt_cells'], np.ceil((c['quilt_side'] - oq) / (Bq - oq))))
            q = wrap_soften(quilt_image(P, nq, oq, qrng, int(c['quilt_tries'])))
            patches[p] = q
            patch_gain[p] = 1.0
            rep['quilt'] = rep.get('quilt', 0) + 1
            rep.setdefault('quilt_info', {})[int(p)] = {'block': Bq, 'overlap': oq, 'cells': nq, 'pool': len(pool), 'jump_L': round(quilt_jump(q, Bq - oq), 3)}
            if p in pat_parts:
                raw_mean[p] = q.mean(axis=(0, 1))                 # узорная: плитка без вычитания среднего и без смешения (фон = тон, цветы поверх)
    for p in (part_ids if (dshift is None or c['draft_texture']) else []):
        if p in patches:
            continue
        for B, thr in ((int(c['patch']), c['patch_known_min']), (int(c['patch']) // 2, c['patch_known_min']), (int(c['patch']) // 4, c['patch_known_min2'])):
            cands = []
            for gi, tx in enumerate(txs):
                T = tx.T
                res_, pm, im = blk[gi]
                n = T // B
                if n < 1:
                    continue
                m = n * B

                def tiles(a):
                    ex = a.shape[2:]
                    return a[:m, :m].reshape(n, B, n, B, *ex).transpose(0, 2, 1, 3, *range(4, 4 + len(ex))).reshape(n, n, B * B, *ex)
                kf = tiles(kn[gi]).mean(axis=2)
                pb, ib = tiles(pm), tiles(im)
                okb = (kf >= thr) & (pb.min(axis=2) == p) & (pb.max(axis=2) == p) & (ib.min(axis=2) == ib.max(axis=2))
                rb = tiles(res_)
                for by, bx in zip(*np.nonzero(okb)):
                    blkr = rb[by, bx].reshape(B, B, 3)
                    cands.append((float(blkr.std()), blkr.copy()))
            if cands:
                ss = np.array([x[0] for x in cands])
                med = float(np.median(ss))
                pick = cands[int(np.argmin(np.abs(ss - med)))]
                patches[p] = pick[1]
                patch_gain[p] = med / max(pick[0], 1e-6)       # типичный блок по контрастности; амплитуда подгоняется к медиане разброса известного
                break
        else:
            Bq, nq = int(c['quilt_block']), int(c['quilt_n'])
            cands = []
            for gi, tx in enumerate(txs):
                T = tx.T
                res_, pm, im = blk[gi]
                n = T // Bq
                if n < 1:
                    continue
                m = n * Bq
                res0 = res_ * kn[gi][..., None]                 # неизвестные пиксели в остаток не входят

                def tilesq(a):
                    ex = a.shape[2:]
                    return a[:m, :m].reshape(n, Bq, n, Bq, *ex).transpose(0, 2, 1, 3, *range(4, 4 + len(ex))).reshape(n, n, Bq * Bq, *ex)
                kf = tilesq(kn[gi]).mean(axis=2)
                pb = tilesq(pm)
                okb = (kf >= c['quilt_known_min']) & (pb.min(axis=2) == p) & (pb.max(axis=2) == p)
                rb = tilesq(res0)
                for by, bx in zip(*np.nonzero(okb)):
                    blkr = rb[by, bx].reshape(Bq, Bq, 3)
                    cands.append((float(blkr.std()), blkr.copy()))
            if len(cands) >= 2:
                ss = np.array([x[0] for x in cands])
                med = float(np.median(ss))
                near = np.argsort(np.abs(ss - med))[:max(2, min(len(cands), 32))]
                pick = rng.choice(near, size=nq * nq, replace=True)
                rows = [np.concatenate([cands[int(pick[r * nq + q])][1] for q in range(nq)], axis=1) for r in range(nq)]
                patches[p] = np.concatenate(rows, axis=0)
                patch_gain[p] = med / max(float(patches[p].std()), 1e-6)
                rep['quilt'] = rep.get('quilt', 0) + 1
            else:
                rep['no_patch'] += 1
    borrow_ratio = {}
    if c.get('borrow_texture'):
        tones_ = {int(q): np.asarray(stat[q][0], float) for q in part_ids if not stat[q][3]}
        need_ = [q for q in part_ids if q not in patches]
        bd = borrow_donors(need_, [q for q in part_ids if q in rep.get('quilt_info', {})], tones_, {int(q): roles_.get(q, roles_.get(str(q))) for q in part_ids}, set(skip_parts) | set(pat_parts), float(c['borrow_max_de']), part_borders(txs))
        for q, d_ in bd.items():
            patches[q] = patches[d_]
            patch_gain[q] = patch_gain.get(d_, 1.0)
        rep['borrowed'] = {int(q): int(d_) for q, d_ in bd.items()}
        if bd:
            sp_all = [texel_spacing(tx) for tx in txs]

            def _msp(pp):
                v = np.concatenate([sp_all[gi][tx.part == pp] for gi, tx in enumerate(txs)] or [np.zeros(0)])
                return float(np.median(v)) if len(v) else 0.0
            borrow_ratio = {int(q): (float(np.clip(_msp(q) / _msp(d_), 0.25, 4.0)) if _msp(q) > 0 and _msp(d_) > 0 else 1.0) for q, d_ in bd.items()}
            bb_ = part_borders(txs)
            rep['borrowed_info'] = {int(q): {'donor': int(d_), 'adjacent': bool(bb_.get((min(q, d_), max(q, d_)), 0) > 0), 'ratio': round(borrow_ratio[int(q)], 3)} for q, d_ in bd.items()}
        else:
            borrow_ratio = {}
    rep['texture_src'] = {int(p): ('borrow' if p in rep.get('borrowed', {}) else 'quilt' if p in rep.get('quilt_info', {}) else ('patch' if p in patches else 'none')) for p in part_ids}      # чем даётся фактура на каждой части: квилт из чистых блоков / один блок / ничем (гладко, счётчик no_patch)
    relief = None
    if c['source'] == 'trellis_relief':
        calib_ = {int(p_): int(v_['donor']) for p_, v_ in rep.get('tone_from_neighbour', {}).items()} if c.get('relief_calib_donor') else None
        relief, rep['relief'] = draft_relief(txs, draft, labs, kn, part_ids, set(raw_mean) | set(pat_parts), c, RULES['trellis_relief'], calib=calib_)
        Rr = RULES['trellis_relief']
        spac = [texel_spacing(tx) for tx in txs]
        fade = []
        for gi, tx in enumerate(txs):                            # затухание рельефа от границы фото в ФИЗИЧЕСКОМ расстоянии (шаг текселя × расстояние в карте), известные тексели не трогаем
            dpx = distance_transform_edt(~kn[gi])
            fade.append(np.clip(dpx.reshape(-1)[tx.ti] * spac[gi] / max(Rr['fade_len'], 1e-9), 0.0, 1.0))
        smooth_parts = {p for p in part_ids if p not in raw_mean and p not in pat_parts and rep.get('quilt_rejected_share', {}).get(p, 0.0) > Rr['smooth_pool_rejected']}
        rep['relief_smooth_parts'] = sorted(int(p) for p in smooth_parts)
    for gi, tx in enumerate(txs):
        T = tx.T
        unk_flat = (~kn[gi].reshape(-1)[tx.ti]) & (~mirrored[gi].reshape(-1)[tx.ti])
        if not unk_flat.any():
            continue
        px, py = tx.ti[unk_flat] % T, tx.ti[unk_flat] // T
        add = np.zeros((len(px), 3))
        side_ok = pattern_side_ok(tx.N[unk_flat] * winding_by_known(tx.N, kn[gi].reshape(-1)[tx.ti], c['pr_az'], c['pr_el']), c['pr_az'], c['pattern_side_cos'], c['pr_el'])             # тексель обращён к фото
        roles_ = c.get('part_role') or {}
        for p in part_ids:
            if p not in patches:
                continue
            sel = tx.part[unk_flat] == p
            if not sel.any():
                continue
            Bp = patches[p].shape[0]
            tile = patches[p] if p in raw_mean else _gaussian_tile(patches[p], rng)
            ox1, oy1 = rng.randint(0, Bp, 2)
            ox2, oy2 = rng.randint(0, Bp, 2)
            t2 = np.rot90(tile)
            qx_, qy_ = px[sel], py[sel]
            if p in borrow_ratio and c.get('borrow_rescale', True):                                  # лоскут донора — в масштабе поверхности (физический размер зерна тот же)
                qx_, qy_ = (qx_ * borrow_ratio[p]).astype(np.int64), (qy_ * borrow_ratio[p]).astype(np.int64)
            r1 = tile[(qy_ + oy1) % Bp, (qx_ + ox1) % Bp]
            r2 = t2[(qy_ * 3 // 2 + oy2) % Bp, (qx_ * 3 // 2 + ox2) % Bp]
            gain = float(np.clip(patch_gain[p], c['gain_min'], c['gain_max']))
            add[sel] = gain * (r1 + r2) / np.sqrt(2.0) if p not in raw_mean else r1                  # узорная: узор из фото целиком (отклонение от тона), без смешения двух сдвигов
            if p in borrow_ratio and c.get('borrow_luma_only', True):
                add[sel, 1:] = 0.0                                                                    # заём: только яркость
            if p in raw_mean:                                                                         # узор только на стороне фото: зад, сиденье, низ — тон без цветов
                add[sel & ~side_ok] = 0.0
            smooth_p = smooth_part_rule(roles_.get(p, roles_.get(str(p))), rep.get('quilt_info', {}).get(p, {}).get('jump_L'), p in raw_mean, c)
            if smooth_p:                                                                              # дерево/каркас и плитка с заметными швами — гладко, без «ёлочки»
                add[sel] = 0.0
                rep.setdefault('quilt_smooth_parts', [])
                if int(p) not in rep['quilt_smooth_parts']:
                    rep['quilt_smooth_parts'].append(int(p))
        if relief is not None:                                   # вариант C: на залитом (не зеркалом) — яркость рельефа черновика (только L), затухающая от границы фото; плохой черновик + отбракованный пул лоскута → ГЛАДКО (тон части), не плитка
            rv, rok = relief[gi]
            tl = tx.ti[unk_flat]
            for p in smooth_parts:
                add[tx.part[unk_flat] == p] = 0.0
            m_ = rok[tl]
            w_ = fade[gi][unk_flat]
            add[m_, 0] = rv[tl][m_] * w_[m_]
            add[m_, 1:] = 0.0
            rep.setdefault('relief_texels', 0)
            rep['relief_texels'] += int(m_.sum())
        if tone_only is not None and gi < len(tone_only):
            ts_ = np.asarray(tone_only[gi], bool).reshape(-1)[tx.ti][unk_flat] & ~unpainted_mask(tex_in[gi].reshape(-1, 3)[tx.ti[unk_flat]])
            if ts_.any():                                                       # цвет тон-только тексела — его собственный (поле этапа 6), не геодезическая заливка; остаток (без среднего) — поверх
                ob_ = out_lab[gi].reshape(-1, 3)
                ti_ = tx.ti[unk_flat][ts_]
                ob_[ti_] = labs[gi].reshape(-1, 3)[ti_]
                rep.setdefault('tone_only_texels', 0)
                rep['tone_only_texels'] += int(ts_.sum())
        out_lab[gi].reshape(-1, 3)[tx.ti[unk_flat]] += add
    rep['time_s']['texture'] = round(time.time() - t0, 2)
    # --- итог: RGB, желоб, проверка покрытия
    outs = []
    nail_masks = {}
    for gi, tx in enumerate(txs):
        T = tx.T
        rgb = tex_in[gi].copy()
        if c.get('nail_twins'):                                         # шляпки гвоздей: нативные тёмные пятна невидимой стороны в цвете видимых двойников (после всей заливки, до RGB)
            pm_ = np.full(T * T, -1, np.int64)
            pm_[tx.ti] = tx.part
            cand_ = np.zeros(T * T, bool)
            cand_[tx.ti] = ~kn[gi].reshape(-1)[tx.ti] & ~mirrored[gi].reshape(-1)[tx.ti] & ~unpainted_mask(tex_in[gi].reshape(-1, 3)[tx.ti])
            nt_ = nail_twins(labs[gi], kn[gi], cand_.reshape(T, T), pm_.reshape(T, T), {p: float(stat[p][0][0]) for p in part_ids if p not in skip_parts and not stat[p][3]}, c)
            rep['geoms'][gi]['nail_twins'] = nt_['report']
            if nt_['mask'].any():
                nail_masks[gi] = nt_['mask']
            if nt_['mask'].any():
                fl_ = out_lab[gi].reshape(-1, 3)
                mk_ = nt_['mask'].reshape(-1)[tx.ti]
                fl_[tx.ti[mk_]] = nt_['lab'].reshape(-1, 3)[tx.ti[mk_]]
        new = lab2rgb(out_lab[gi].reshape(-1, 3)[tx.ti])
        new = np.where((new.max(axis=1) <= BLACK_MAX)[:, None], np.maximum(new, BLACK_MAX + 1), new)    # тёмное — не «чёрное непокрашенное»: сторож охвата считает ≤ порога дырой
        keepk = kn_keep[gi].reshape(-1)[tx.ti]
        if skip_parts:                                                  # часть с ролью без тона (не тон всего товара) не красится: остаётся как на входе, пометка в отчёте
            keepk = keepk | (np.isin(tx.part, sorted(skip_parts)) & ~mirrored[gi].reshape(-1)[tx.ti])
        rgb.reshape(-1, 3)[tx.ti[~keepk]] = new[~keepk]
        occ = np.zeros((T, T), bool)
        occ.reshape(-1)[tx.ti] = True
        if c['gutter'] > 0:
            dist, (iy, ix) = distance_transform_edt(~occ, return_indices=True)
            g_ = (~occ) & (dist <= c['gutter'])
            rgb[g_] = rgb[iy[g_], ix[g_]]
        outs.append(rgb)
        bad_before = int((unpainted_mask(tex_in[gi].reshape(-1, 3)[tx.ti])).sum())
        bad_after = int((unpainted_mask(rgb.reshape(-1, 3)[tx.ti])).sum())
        rep['geoms'][gi].update({'unpainted_before': bad_before, 'unpainted_after': bad_after})
        vc = view_class(tx.N * np.where((tx.Q * tx.N).sum(axis=1) >= 0.0, 1.0, -1.0)[:, None])     # вид по наружной нормали (наружу — по знаку (точка − центр)·нормаль)
        ub, ua = unpainted_mask(tex_in[gi].reshape(-1, 3)[tx.ti]), unpainted_mask(rgb.reshape(-1, 3)[tx.ti])
        rep['geoms'][gi]['by_view'] = [[int((vc == i).sum()), int((vc == i)[ub].sum()), int((vc == i)[ua].sum())] for i in range(len(VIEW_CLASSES))]
        nfc = np.bincount(tx.f, minlength=len(tx.F)).astype(np.float64)
        tx.unk_face = (np.bincount(tx.f, weights=(~kn[gi].reshape(-1)[tx.ti]).astype(np.float64), minlength=len(tx.F)) > 0.5 * np.maximum(nfc, 1.0)) & (nfc > 0)
        nm_ = nail_masks.get(gi)
        if nm_ is not None:
            from scipy.ndimage import binary_dilation
            nm_ = binary_dilation(nm_, iterations=1)
        rep['geoms'][gi]['steps'] = {'before': step_stats(tx, tex_in[gi], c['step_de']), 'after': step_stats(tx, rgb, c['step_de'], nm_)}
        if nm_ is not None:
            rep['geoms'][gi]['steps']['after_with_nails'] = step_stats(tx, rgb, c['step_de'])
    far = {'known': [], 'filled': []}
    rs = np.random.RandomState(11)
    for gi, tx in enumerate(txs):
        lab_o = rgb2lab(outs[gi].reshape(-1, 3)[tx.ti])
        kk = kn[gi].reshape(-1)[tx.ti]
        for p in part_ids:
            sel = tx.part == p
            for nm, m in (('known', sel & kk), ('filled', sel & ~kk)):
                idx = np.nonzero(m)[0]
                if len(idx) > 100000:
                    idx = rs.choice(idx, 100000, replace=False)
                if len(idx):
                    far[nm].append((TC.de2000_v(lab_o[idx], np.broadcast_to(stat[p][0], (len(idx), 3)).copy()) > c['far_de']))
    fk = float(np.concatenate(far['known']).mean()) * 100.0 if far['known'] else 0.0
    ff = float(np.concatenate(far['filled']).mean()) * 100.0 if far['filled'] else 0.0
    rep['far_pct'] = {'known': round(fk, 2), 'filled': round(ff, 2), 'excess': round(ff - fk, 2)}
    n_all = sum(r['texels'] for r in rep['geoms'])
    rep['texels'] = n_all
    bv = np.sum([r['by_view'] for r in rep['geoms']], axis=0)
    rep['unpainted_by_view'] = {nm: {'texels_pct': round(100.0 * int(bv[i, 0]) / max(n_all, 1), 2), 'before_of_all_pct': round(100.0 * int(bv[i, 1]) / max(n_all, 1), 3),
                                     'after_of_all_pct': round(100.0 * int(bv[i, 2]) / max(n_all, 1), 3)} for i, nm in enumerate(VIEW_CLASSES)}
    rep['known_pct'] = round(100.0 * sum(r['known'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['mirrored_pct'] = round(100.0 * sum(r['mirrored'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['geodesic_pct'] = round(100.0 * sum(r['geodesic'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['part_mean_pct'] = round(100.0 * sum(r['part_mean'] for r in rep['geoms']) / max(n_all, 1), 2)
    rep['unpainted_before_pct'] = round(100.0 * sum(r['unpainted_before'] for r in rep['geoms']) / max(n_all, 1), 3)
    rep['unpainted_after_pct'] = round(100.0 * sum(r['unpainted_after'] for r in rep['geoms']) / max(n_all, 1), 3)
    rep['steps'] = {}
    for k in ('before', 'after'):
        ss = [r['steps'][k] for r in rep['geoms']]
        n = max(sum(x['pairs'] for x in ss), 1)
        rep['steps'][k] = {'faces_step_pct': round(sum(x['faces_step_pct'] * x['pairs'] for x in ss) / n, 2),
                           'pairs_step_pct': round(sum(x['pairs_step_pct'] * x['pairs'] for x in ss) / n, 2),
                           'filled_faces_step_pct': (round(sum((x['filled_faces_step_pct'] or 0.0) * x['pairs'] for x in ss) / n, 2) if any(x['filled_faces_step_pct'] is not None for x in ss) else None)}
    rep['time_s']['all'] = round(time.time() - t0, 2)
    return {'tex': outs, 'report': rep}


# ---------------------------------------------------------------- черновик TRELLIS на нашу форму --------------------
def draft_texels(geoms: list, draft_geoms: list, cfg: dict | None = None) -> dict:
    """Цвет черновика (`tex_coverage.load_geoms` родного GLB TRELLIS.2 или его копии на упрощённую форму) в текселях НАШЕЙ развёртки: ближайшая точка поверхности черновика
    (по 3D-позиции в кадре нашего предмета; нормаль не против нашей) → её Lab. Черновик в другой системе координат не подгоняется: кадр сверяется отчётом (`frame_gap`), расхождение — `ok` ложно.
    → {'lab': [(T,T,3)], 'ok': [(T,T) bool], 'report': {...}}."""
    from scipy.spatial import cKDTree
    c = dict(FILL, **(cfg or {}))
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    Pall = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    doffs = np.cumsum([0] + [len(g['V']) for g in draft_geoms])
    Dall = (np.concatenate([np.asarray(g['V'], np.float64) for g in draft_geoms]) - ctr) / size
    srcQ, srcN, srcL = [], [], []
    for gi, g in enumerate(draft_geoms):
        tx = Tex(g, Dall[doffs[gi]:doffs[gi + 1]], _grid(g), None, True)
        rgb = np.asarray(g['tex'])[..., :3]
        srcQ.append(tx.Q)
        srcN.append(tx.N)
        srcL.append(rgb2lab(rgb.reshape(-1, 3)[tx.ti]))
    srcQ, srcN, srcL = np.concatenate(srcQ), np.concatenate(srcN), np.concatenate(srcL)
    tree = cKDTree(srcQ)
    labs, oks, d_all, n_ok, n_tot = [], [], [], 0, 0
    for gi, g in enumerate(geoms):
        T = _grid(g)
        tx = Tex(g, Pall[offs[gi]:offs[gi + 1]], T, None, True)
        K = 4
        rl = c['source'] == 'trellis_relief'
        max_d = min(c['draft_max_dist'], c['relief_draft_max_dist']) if rl else c['draft_max_dist']
        cos_min = max(c['draft_cos'], c['relief_draft_cos']) if rl else c['draft_cos']
        d, j = tree.query(tx.Q, k=K, distance_upper_bound=max_d)
        jj = np.where(np.isfinite(d), j, 0)
        cs = (srcN[jj] * tx.N[:, None, :]).sum(axis=2)
        good = np.isfinite(d) & (cs > cos_min)
        if rl and c['relief_draft_thin_cos'] is not None:
            good &= ~(np.isfinite(d) & (cs < c['relief_draft_thin_cos'])).any(axis=1)[:, None]      # тонкая вещь: рядом поверхность с противоположной нормалью
        first = good.argmax(axis=1)
        has = good.any(axis=1)
        pick = jj[np.arange(len(jj)), first]
        lab = np.zeros((T * T, 3))
        ok = np.zeros(T * T, bool)
        lab[tx.ti[has]] = srcL[pick[has]]
        ok[tx.ti[has]] = True
        n_ok += int(has.sum())
        n_tot += len(tx.ti)
        labs.append(lab.reshape(T, T, 3))
        oks.append(ok.reshape(T, T))
        d_all.append(np.where(np.isfinite(d[:, 0]), d[:, 0], np.nan))
    dd = np.concatenate(d_all)
    A, B = (Pall.min(axis=0), Pall.max(axis=0)), (Dall.min(axis=0), Dall.max(axis=0))
    gap = float(np.abs(np.concatenate([A[0] - B[0], A[1] - B[1]])).max())
    return {'lab': labs, 'ok': oks, 'report': {'ok_pct': round(100.0 * n_ok / max(n_tot, 1), 2),
                                               'nearest_median': None if np.isnan(dd).all() else round(float(np.nanmedian(dd)), 4), 'frame_gap': round(gap, 3)}}


# ---------------------------------------------------------------- кадры «до | после» -------------------------------
def render_ortho(geoms: list, texs: list, azimuth: float = 180.0, res: int = 1024, ortho: float = 1.25, elevation: float = 0.0):
    """Ортографический кадр предмета с заданного азимута (0 — в лоб, 180 — сзади) с текстурами `texs` (по геометриям): цвет текстуры × освещение лоб-светом. Для проб, не для продукта."""
    ctr, size = frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    F = np.concatenate([np.asarray(g['F'], np.int64) + offs[i] for i, g in enumerate(geoms)])
    fg = np.concatenate([np.full(len(g['F']), i) for i, g in enumerate(geoms)])
    UV = np.concatenate([np.asarray(g['UV'], np.float64) for g in geoms])
    v = photo_views([azimuth], elevation)[0]
    x, y, d = TC.project(P, v, ortho)
    xy = np.stack([x * res, y * res], 1)
    ids, _zb = TC.raster(xy, F, res, d)
    hit = np.nonzero(ids >= 0)[0]
    f = ids[hit].astype(np.int64)
    px, py = (hit % res) + 0.5, (hit // res) + 0.5
    A, B, C = xy[F[f, 0]], xy[F[f, 1]], xy[F[f, 2]]
    ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    wa = ((B[:, 0] - px) * (C[:, 1] - py) - (B[:, 1] - py) * (C[:, 0] - px)) / ar
    wb = ((C[:, 0] - px) * (A[:, 1] - py) - (C[:, 1] - py) * (A[:, 0] - px)) / ar
    uv = wa[:, None] * UV[F[f, 0]] + wb[:, None] * UV[F[f, 1]] + (1.0 - wa - wb)[:, None] * UV[F[f, 2]]
    n3 = np.cross(P[F[f, 1]] - P[F[f, 0]], P[F[f, 2]] - P[F[f, 0]])
    n3 /= np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    col = np.zeros((len(hit), 3))
    for gi in range(len(geoms)):
        s = fg[f] == gi
        if not s.any():
            continue
        tex = np.asarray(texs[gi])
        H, W = tex.shape[:2]
        tx_ = np.clip(np.floor(uv[s, 0] * W).astype(np.int64), 0, W - 1)
        ty_ = np.clip(np.floor((1.0 - uv[s, 1]) * H).astype(np.int64), 0, H - 1)
        col[s] = tex[ty_, tx_][:, :3]
    img = np.full((res * res, 3), 245.0)
    img[hit] = col * (0.40 + 0.60 * np.abs(n3 @ v[0]))[:, None]
    return img.reshape(res, res, 3).astype(np.uint8)


# ---------------------------------------------------------------- этап 07 пути покраски: выход, проверка, кадр ----
STAGE = '07-fill'
RULES_PATH = os.environ.get('FILL_RULES') or os.path.join(HERE, '..', '..', 'rules', 'paint-fill.json')


def load_rules(path: str | None = None) -> dict:
    """Правила этапа 07 — `tools/scout/rules/paint-fill.json` (пороги check.json, ΔE «известное изменилось»); нет ключа — KeyError."""
    import json
    with open(path or RULES_PATH, encoding='utf-8') as f:
        r = json.load(f)
    for k in ('thresholds', 'known_change_de', 'quilt_outlier', 'quilt_extreme', 'mirror_extreme', 'stage6_gate'):
        if k not in r:
            raise KeyError(f'rules/paint-fill.json: нет ключа {k!r}')
    if 'trellis_relief' not in r:
        raise KeyError("rules/paint-fill.json: нет ключа 'trellis_relief'")
    for k in ('gain_max', 'clip_k', 'patch_frac', 'patch_dl', 'dilate_px', 'part_max_share', 'band_lo', 'band_hi', 'sigma_lo_min', 'sigma_lo_max', 'sigma_hi_max', 'far_w', 'p95_cap',
              'ok_erode_px', 'allowed_families', 'homog_max_std', 'fade_len', 'smooth_pool_rejected'):
        if k not in r['trellis_relief']:
            raise KeyError(f'rules/paint-fill.json: trellis_relief.{k} не задан')
    for k in ('quilt_extreme', 'mirror_extreme'):
        if 'black_rel' not in r[k]:
            raise KeyError(f'rules/paint-fill.json: {k}.black_rel не задан')
    for k in ('pool_rejected_pct', 'empty_pct', 'dE00_front_back', 'filled_faces_step_pct', 'far_excess_pct', 'known_changed_share_pct', 'time_s'):
        if k not in r['thresholds']:
            raise KeyError(f'rules/paint-fill.json: threshold {k!r} не задан')
    return r


RULES = load_rules()
THRESHOLDS = {k: (v[0], float(v[1])) for k, v in RULES['thresholds'].items()}   # пороги этапа (check.json) из rules/paint-fill.json: ΔE00 перёд↔зад (худшая часть с известным ≥ 1 %), ступени, пятна, «известное не изменено» (0), время


def merge_orphan_parts(mesh, part: np.ndarray):
    """Запасное деление по геометрии: часть-«сирота» (доля ПЛОЩАДИ < `refine.orphan_max_area_share` из parts-sam-rules.json) вливается в соседа с самой длинной границей — общее правило этапа 3 (`parts_refine.merge_orphans`, T-169), не дубль.
    У сироты нет текселей с фото, она красилась бы тоном целого (светлый клин у верха ножки). Нет модулей этапа 3 или порога — части как были. → (части с плотными номерами, строка для note: '' | '; сирот влито N')."""
    try:
        sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'assets'))
        import parts_refine as PR
        import parts_vote as PV
        thr = PV.load_rules().get('refine', {}).get('orphan_max_area_share')
    except Exception:  # noqa: BLE001 — нет parts_refine/parts_vote/правил (ветка этапа 3 не влита): прежний путь
        return part, '; сирот не ищем (нет parts_refine)'
    if not thr:
        return part, ''
    V = np.asarray(mesh.vertices, np.float64)
    F = np.asarray(mesh.faces)
    new, trace = PR.merge_orphans(np.asarray(part, np.int32), PV.weld_adjacency(V, F), PR._face_areas(V, F), thr)
    if not trace:
        return part, ''
    _, dense = np.unique(new, return_inverse=True)
    return dense.reshape(-1).astype(np.int32), f'; сирот влито {len(trace)}'


def parts_from_geometry(geoms: list):
    """Части граней по геометрии `tools/assets/material_parts.py`: 0 обивка/корпус, 1 ножки, 2 нейтральное (тонкое, полоса у ножек); нет уверенного деления — одна часть. → (список по геометриям | None, строка о способе)."""
    try:
        sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'assets'))
        import material_parts as MP
        rules = MP.load_rules()
    except Exception as e:  # noqa: BLE001 — частей нет, заливка идёт одной частью
        return None, f'частей нет ({type(e).__name__})'
    out, note = [], []
    for g in geoms:
        nf = len(g['F'])
        try:
            rec = MP.judge(MP.analyze(g['mesh'], rules), rules, None)
            if rec.get('status') == 'split' and rec.get('apply', rec.get('confidence', 0) >= rules['confidence']['apply']):
                leg = MP.legs_face_mask(g['mesh'], rec)
                neu = MP.neutral_face_mask(g['mesh'], rec) & ~leg
                p = np.zeros(nf, np.int32)
                p[leg] = 1
                p[neu] = 2
                p, onote = merge_orphan_parts(g['mesh'], p)
                out.append(p)
                note.append(f"split ножки {int(leg.sum())} нейтр. {int(neu.sum())} из {nf}{onote}")
                continue
            note.append(f"{rec.get('status')} → одна часть")
        except Exception as e:  # noqa: BLE001
            note.append(f'сбой частей {type(e).__name__}')
        out.append(np.zeros(nf, np.int32))
    return out, '; '.join(note)


def parts_from_npz(path: str, geoms: list):
    """Части граней этапа 3 пути покраски (`03-parts/parts.npz`, T-169): `part` int16 — ОДИН массив на все грани GLB в порядке геометрий; режется по числу граней каждой геометрии.
    −1 («нет части») получает отдельный номер. Число граней не совпало → ValueError (части другого меша — заливать нельзя). → (список по геометриям, строка о способе)."""
    z = np.load(path)
    part = np.asarray(z['part']).astype(np.int32)
    n = sum(len(g['F']) for g in geoms)
    if len(part) != n:
        raise ValueError(f'parts.npz: граней {len(part)}, а в GLB {n} — части другого меша')
    if (part < 0).any():
        part = np.where(part < 0, int(part.max()) + 1, part)
    out, o = [], 0
    for g in geoms:
        out.append(part[o:o + len(g['F'])])
        o += len(g['F'])
    return out, f'parts.npz: {int(part.max()) + 1} частей'


def roles_from_parts_json(path: str) -> dict:
    """Роли частей этапа 3 (`03-parts/parts.json`, поле `parts[].role`; правила — rules/part-roles.json): {номер части: роль} для частей с ОПРЕДЕЛЁННОЙ ролью.
    `unknown` (недоверие, нет правила…) в словарь не входит — у такой части класса нет, C решает по однородности известного. Нет файла/поля — {}."""
    import json
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    return {int(p['id']): str(p['role']) for p in d.get('parts', []) if p.get('role') and p['role'] != 'unknown' and 'id' in p}


def part_borders(txs: list) -> dict:
    """Общая граница частей: {(a, b) a<b: число рёбер} по граням, где соседние грани (общее ребро по сваренным вершинам) принадлежат разным частям."""
    out = {}
    for tx in txs:
        F, pf = np.asarray(tx.FW), np.asarray(tx.part_f)
        if len(F) == 0:
            continue
        e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
        fi = np.tile(np.arange(len(F)), 3)
        e.sort(axis=1)
        key = e[:, 0].astype(np.int64) * (int(F.max()) + 1) + e[:, 1]
        order = np.argsort(key, kind='stable')
        ks, fs = key[order], fi[order]
        same = ks[1:] == ks[:-1]
        a, b = pf[fs[:-1][same]], pf[fs[1:][same]]
        diff = a != b
        for x, y in zip(a[diff], b[diff]):
            k = (int(min(x, y)), int(max(x, y)))
            out[k] = out.get(k, 0) + 1
    return out


def _compact_blobs(mask, c: dict):
    """Связные (8) пятна маски в развёртке, прошедшие отбор «гвоздь»: размер, плотность в рамке, вытянутость. → (маска принятых, метки, число пятен)."""
    from scipy import ndimage as ndi
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    keep = np.zeros(n + 1, bool)
    if n:
        sz = ndi.sum(mask, lab, range(1, n + 1))
        for i, sl in enumerate(ndi.find_objects(lab), start=1):
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            keep[i] = (c['nail_min_px'] <= sz[i - 1] <= c['nail_max_px'] and sz[i - 1] / float(h * w) >= c['nail_min_fill'] and max(h, w) / float(min(h, w)) <= c['nail_max_aspect'])
    acc = keep[lab]
    return acc, np.where(acc, lab, 0), int(keep.sum())


def borrow_donors(need: list, quilted: list, tones: dict, roles: dict, bad: set, max_de: float, borders: dict | None = None) -> dict:
    """Ш6 вариант 1: {часть без своей фактуры → часть-донор того же материала}. need — части без блока/квилта; quilted — части с квилтом (есть чему делиться);
    tones {часть: Lab} (нет ключа — тон не свой, не берём); roles {часть: роль}; bad — части, которым/у которых брать нельзя (узорные, skip). Донор: та же роль, тон ближе max_de, самый близкий по тону."""
    out = {}
    for p in need:
        if p in bad or p not in tones:
            continue
        best = None
        for q in quilted:
            if q == p or q in bad or q not in tones or roles.get(q) != roles.get(p):
                continue
            d = float(np.linalg.norm(np.asarray(tones[p], float) - np.asarray(tones[q], float)))
            adj = 0 if borders and borders.get((min(p, q), max(p, q)), 0) > 0 else 1              # Ш6 п.2: часть с общей границей — материал почти наверняка тот же — идёт первой
            if d <= max_de and (best is None or (adj, d) < best[0]):
                best = ((adj, d), q)
        if best is not None:
            out[p] = best[1]
    return out


def nail_twins(lab_in, known, cand, partmap, tone_L: dict, c: dict) -> dict:
    """Шляпки гвоздей невидимой стороны (T-164, Sakura HD): у невидимых текселей нативный (TRELLIS) цвет в развёртке сохраняет мелкие тёмные пятна — ряд гвоздей, а заливка тоном ткани его стирает,
    и сзади гвоздей нет, спереди есть. Пятно-кандидат принимается, если тёмнее тона СВОЕЙ части на `nail_dark_drop` L, компактно и мелко (линии шва — нет), у части (или у товара) есть
    ≥ `nail_min_twins` видимых двойников с тем же отбором, И средний цвет пятна близок к двойникам (ΔE ≤ `nail_max_de` и цветность не выше двойников + `nail_max_dchroma`: красные пятна, чёрные дыры — не гвозди). Принятое пятно красится своим нативным
    Lab со сдвигом к медиане двойников (сдвиг ≤ `nail_max_shift` по каналу). → {'mask': (T,T) bool, 'lab': (T,T,3), 'report': {...}}."""
    from scipy import ndimage as ndi
    T = lab_in.shape[0]
    L0 = lab_in[..., 0]
    tl = np.full((T, T), np.nan)
    for p, v in tone_L.items():
        tl[partmap == p] = v
    dark = (L0 < tl - c['nail_dark_drop']) & (tl >= c['nail_min_tone_L'])
    _km, klab, n_kn = _compact_blobs(known & dark, c)
    _cm, clab, n_cd = _compact_blobs(cand & dark, c)
    rep = {'twins_blobs': n_kn, 'candidate_blobs': n_cd, 'parts': {}, 'texels': 0, 'applied': False}
    out = {'mask': np.zeros((T, T), bool), 'lab': lab_in, 'report': rep}
    if n_kn < c['nail_min_twins'] or n_cd == 0:
        rep['skip'] = 'нет видимых двойников' if n_kn < c['nail_min_twins'] else 'нет кандидатов'
        return out

    def stats(lab_map):                                              # по пятну: среднее Lab и часть
        idx = np.unique(lab_map[lab_map > 0])
        mean = np.stack([ndi.mean(lab_in[..., k], lab_map, idx) for k in range(3)], 1)
        prt = np.asarray(ndi.maximum(partmap, lab_map, idx), int)
        return idx, mean, prt
    ki, km, kp = stats(klab)
    ci, cm, cp = stats(clab)
    pooled = np.median(km, axis=0)
    mask = np.zeros((T, T), bool)
    new = lab_in.copy()
    parts_ = sorted({int(x) for x in cp})
    refs, okc = {}, np.zeros(len(ci), bool)
    for p in parts_:                                                 # проход 1: цвет близок к двойникам и не «краснее» их (красные крапины нативного цвета — не гвозди)
        tw = km[kp == p]
        refs[p] = np.median(tw, axis=0) if len(tw) >= c['nail_min_twins'] else pooled
        sel = cp == p
        okc[sel] = (np.linalg.norm(cm[sel] - refs[p], axis=1) <= c['nail_max_de']) & (np.hypot(cm[sel][:, 1], cm[sel][:, 2]) <= np.hypot(refs[p][1], refs[p][2]) + c['nail_max_dchroma'])
    # проход 2: «в ряду» — у пятна есть сосед (видимый двойник или другое принятое пятно) в радиусе `nail_neighbor_px` развёртки; одиночка — не гвоздь
    from scipy.spatial import cKDTree
    cc_ = np.array(ndi.center_of_mass(np.ones_like(clab), clab, ci)) if len(ci) else np.zeros((0, 2))
    kc_ = np.array(ndi.center_of_mass(np.ones_like(klab), klab, ki)) if len(ki) else np.zeros((0, 2))
    pts = np.concatenate([kc_, cc_[okc]]) if len(kc_) + int(okc.sum()) else np.zeros((0, 2))
    tree = cKDTree(pts) if len(pts) else None
    lonely = np.zeros(len(ci), bool)
    for i in np.nonzero(okc)[0]:
        lonely[i] = len(tree.query_ball_point(cc_[i], c['nail_neighbor_px'])) - 1 < c['nail_min_neighbours']      # -1: сам себя
    rep['lonely_dropped'] = int((okc & lonely).sum())
    okc &= ~lonely
    for p in parts_:
        tw = km[kp == p]
        ref = refs[p]
        sel = cp == p
        okb = okc[sel]
        pr = {'candidates': int(sel.sum()), 'accepted': int(okb.sum()), 'twins_blobs': int(len(tw)), 'ref_lab': [round(float(x), 1) for x in ref], 'ref': 'part' if len(tw) >= c['nail_min_twins'] else 'pooled'}
        rep['parts'][p] = pr
        if not okb.any():
            continue
        ids = ci[sel][okb]
        mp = np.isin(clab, ids)
        shift = np.clip(ref - np.median(cm[sel][okb], axis=0), -c['nail_max_shift'], c['nail_max_shift'])
        cand_new = lab_in + shift
        mp &= np.hypot(cand_new[..., 1], cand_new[..., 2]) <= np.hypot(ref[1], ref[2]) + c['nail_max_dchroma']      # и по тексельно: красные точки внутри принятого пятна не красим
        new[mp] = cand_new[mp]
        mask |= mp
        pr['shift'] = [round(float(x), 1) for x in shift]
        pr['texels'] = int(mp.sum())
    out['mask'], out['lab'] = mask, new
    rep['texels'], rep['applied'] = int(mask.sum()), bool(mask.any())
    return out


def choose_tone_sources(part_ids, roles: dict, known_cnt: dict, total: dict, from_global: dict, tones: dict, borders: dict, c: dict) -> dict:
    """Иерархия источника тона части (Codex 21.11, T-164): своя часть → та же роль И совместимый видимый тон (ΔE к известным текселям части, если их достаточно) → каталожный тон роли (`catalog_tone`) → НЕ красить.
    Тон ВСЕГО товара (`stats_from_global`) через границу материала не берётся: часть с ролью и без своего тона (известного < min_known) — `skip` (пометка в отчёте), а не global. Частям без роли (нет этапа 3 — материал неизвестен) прежнее поведение (`global_legacy`).
    → {p: {'source': own|own_weak|donor|catalog|skip|global_legacy, 'donor', 'de', 'rejected': [(q, ΔE)]}}."""
    mk, ms = int(c['min_known']), float(c.get('tone_known_min_share') or 0.0)
    role_of = lambda p: roles.get(p, roles.get(str(p)))  # noqa: E731
    reliable = {p: (not from_global[p]) and known_cnt[p] >= max(mk, ms * total[p]) for p in part_ids}
    out = {}
    for p in part_ids:
        role = role_of(p)
        if role is None or not roles:
            out[p] = {'source': 'global_legacy' if from_global[p] else 'own'}
            continue
        if reliable[p]:
            out[p] = {'source': 'own'}
            continue
        cands = sorted(((n, (b if a == p else a)) for (a, b), n in borders.items() if p in (a, b) and role_of(b if a == p else a) == role), reverse=True)
        picked, rej = None, []
        for n, q in cands:
            if not reliable[q]:
                continue
            de = None
            if not from_global[p] and known_cnt[p] >= int(c.get('tone_compat_min_known', 1500)):          # свой видимый тон достаточно надёжен, чтобы проверить совместимость
                de = float(TC.de2000_v(np.asarray(tones[p], float)[None], np.asarray(tones[q], float)[None])[0])
                if de > float(c.get('tone_compat_de', 25.0)):
                    rej.append((int(q), round(de, 1)))
                    continue
            picked = (q, de)
            break
        if picked is not None:
            out[p] = {'source': 'donor', 'donor': int(picked[0]), 'de': None if picked[1] is None else round(picked[1], 1), 'rejected': rej}
        elif (c.get('catalog_tone') or {}).get(role) is not None:
            out[p] = {'source': 'catalog', 'rejected': rej}
        elif from_global[p] and c.get('skip_global_tone', True):
            out[p] = {'source': 'skip', 'rejected': rej}
        else:
            out[p] = {'source': 'own_weak' if not from_global[p] else 'global_legacy', 'rejected': rej}
    return out


def pattern_side_ok(normals: np.ndarray, az_deg: float, cos_min: float | None, el_deg: float = 0.0) -> np.ndarray:
    """Правило узора (T-164, Sakura 21.11): узор кладётся только на тексели, обращённые к фото — cos(нормаль, направление на камеру az) ≥ cos_min (кадр GLB: лицом +Z, az 0 — в лоб).
    Зад, сиденье, низ — тон ткани без цветов. cos_min=None — правило выключено (все True)."""
    n = len(normals)
    if cos_min is None:
        return np.ones(n, bool)
    return (np.asarray(normals) @ photo_views([az_deg], el_deg)[0][0]) >= cos_min        # направление на камеру фото — с наклоном (el)


def smooth_part_rule(role, jump_l, pattern: bool, c: dict) -> bool:
    """Правило «без плитки» (дерево, «ёлочка» на швах): роль части (этап 3) в `smooth_roles`, либо неузорная часть со скачком L на швах плитки jump_L > `quilt_jump_max`."""
    if role in (c.get('smooth_roles') or []):
        return True
    return (not pattern) and jump_l is not None and jump_l > c['quilt_jump_max']


def resolve_part_class(cfg: dict | None, parts_npz: str | None, parts_from_stage3: bool) -> tuple:
    """Классы частей для C (`part_class`): заданы в cfg — они; иначе при source=trellis_relief и частях ИЗ этапа 3 — роли из `parts.json` рядом с parts.npz (один источник — этап 3), иначе None. → (cfg с part_class, строка о способе)."""
    c = dict(cfg or {})
    if c.get('source') != 'trellis_relief':
        return c, None
    if c.get('part_class') is not None:
        return c, 'part_class: заданы в cfg'
    if parts_from_stage3 and parts_npz:
        roles = roles_from_parts_json(os.path.join(os.path.dirname(parts_npz), 'parts.json'))
        if roles:
            c['part_class'] = roles
            return c, f'part_class: роли этапа 3 (parts.json), частей с ролью {len(roles)}'
    return c, 'part_class: нет — ворота C только по однородности известного'


def part_deltas(geoms: list, parts, kfront: list, kback: list, tex_before: list, tex_after: list) -> dict:
    """ΔE00 перёд↔зад внутри одной части: средние Lab текселей, видимых спереди (kfront) и сзади (kback), до и после заливки. → {часть: {'before', 'after'}}."""
    res = {}
    ids = sorted({int(p) for pp in (parts or [np.zeros(len(g['F']), np.int32) for g in geoms]) for p in np.unique(pp)})
    txs = [Tex(g, np.asarray(g['V'], np.float64), _grid(g), None if parts is None else parts[gi]) for gi, g in enumerate(geoms)]
    for p in ids:
        sets = {'before': ([], []), 'after': ([], [])}
        for gi, tx in enumerate(txs):
            sel = tx.part == p
            for nm, tex in (('before', tex_before[gi]), ('after', tex_after[gi])):
                flat = np.asarray(tex).reshape(-1, 3)
                for k, kk in ((0, kfront[gi]), (1, kback[gi])):
                    m = kk.reshape(-1)[tx.ti] & sel
                    m &= ~unpainted_mask(flat[tx.ti])
                    if m.any():
                        sets[nm][k].append(rgb2lab(flat[tx.ti[m]]))
        r = {}
        for nm, (fr, bk) in sets.items():
            if fr and bk:
                a, b = np.concatenate(fr).mean(axis=0, keepdims=True), np.concatenate(bk).mean(axis=0, keepdims=True)
                r[nm] = round(float(TC.de2000_v(a, b)[0]), 2)
            else:
                r[nm] = None
        res[p] = r
    return res


def _part_map(g, T: int, part_f) -> np.ndarray:
    """Карта частей развёртки (T,T): номер части грани в тексele, −1 вне развёртки."""
    UV = np.asarray(g['UV'], np.float64)
    ids, _ = TC.raster(np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1), np.asarray(g['F'], np.int64), T)
    ids = np.asarray(ids).reshape(-1)
    pm = np.full(T * T, -1, np.int32)
    m = ids >= 0
    pm[m] = np.asarray(part_f, np.int32)[ids[m]]
    return pm.reshape(T, T)


def _pattern_hists(lab: np.ndarray, mask: np.ndarray, tone: np.ndarray, spot_chroma: float) -> dict | None:
    """Статистика узора по кадру: гистограмма ориентаций градиента яркости (12 направлений по модулю π, вес — модуль), доля «пятен» (хрома остатка от тона > порога) и гистограмма размеров связных пятен (степени двойки)."""
    from scipy.ndimage import binary_erosion, gaussian_filter, label
    m = binary_erosion(mask, iterations=3)
    if int(m.sum()) < 500:
        return None
    L = gaussian_filter(np.where(mask, lab[..., 0], np.median(lab[..., 0][mask])), 1.0)
    gy, gx = np.gradient(L)
    mag = np.hypot(gx, gy)[m]
    th = np.mod(np.arctan2(gy, gx)[m], np.pi)
    oh = np.bincount(np.minimum((th / np.pi * 12).astype(int), 11), weights=mag, minlength=12)
    oh = oh / max(oh.sum(), 1e-12)
    chroma = np.hypot(lab[..., 1] - tone[1], lab[..., 2] - tone[2])
    B = (chroma > spot_chroma) & m
    lbl, n = label(B)
    sizes = np.bincount(lbl.ravel())[1:] if n else np.zeros(0)
    sh = np.bincount(np.minimum(np.log2(np.maximum(sizes, 1)).astype(int), 9), minlength=10).astype(np.float64)
    sh = sh / max(sh.sum(), 1.0)
    return {'orient': oh, 'spot_sizes': sh, 'spot_area': float(B.sum()) / float(m.sum()), 'n_spots': int(n), 'px': int(m.sum())}


def pattern_metrics(geoms: list, parts, known: list, tex_after: list, rep: dict, c: dict) -> dict:
    """Мерка узора (ТОЛЬКО отчёт, не отказ): внутри каждой узорной части — расстояние статистик узора перёд (известное, вид az `pr_az`) ↔ зад (достроенное, az+180):
    orient = ½·L1 между гистограммами ориентаций градиента; spot_sizes = ½·L1 между гистограммами размеров пятен; dist = среднее двух; spot_area_front/back — доля пятен. → {часть: {...}}."""
    out = {}
    pats = [int(p) for p, v in rep['parts'].items() if v['pattern']]
    if not pats:
        return out
    Ts = [np.asarray(t).shape[0] for t in tex_after]
    pms = [_part_map(g, Ts[gi], np.zeros(len(g['F']), np.int32) if parts is None else parts[gi]) for gi, g in enumerate(geoms)]
    labs_ = [rgb2lab(np.asarray(t)[..., :3].reshape(-1, 3)).reshape(Ts[gi], Ts[gi], 3) for gi, t in enumerate(tex_after)]
    views = {}
    for nm, az in (('front', c['pr_az']), ('back', c['pr_az'] + 180.0)):
        S = view_samples(geoms, az, int(c['pr_res']), c['pr_ortho'], c['pr_el'])
        cs = np.zeros(S['res'] * S['res'])
        cs[S['hit']] = S['cos']
        views[nm] = (sample_view(S, labs_), sample_view(S, pms, -1), sample_view(S, [np.asarray(k, bool) for k in known]), cs.reshape(S['res'], S['res']) >= c['pr_cos_min'])
    for p in pats:
        tone = np.asarray(rep['parts'][p]['mean_lab'])
        hs = {}
        for nm, (lab, pm, kn_, cosok) in views.items():
            mk = (pm == p) & cosok & (kn_ if nm == 'front' else ~kn_)
            hs[nm] = _pattern_hists(lab, mk, tone, c['pm_spot_chroma']) if mk.any() else None
        if hs['front'] is None or hs['back'] is None:
            out[p] = {'dist': None, 'note': 'мало пикселей перёд/зад'}
            continue
        o = 0.5 * float(np.abs(hs['front']['orient'] - hs['back']['orient']).sum())
        z = 0.5 * float(np.abs(hs['front']['spot_sizes'] - hs['back']['spot_sizes']).sum())
        out[p] = {'dist': round((o + z) / 2.0, 3), 'orient': round(o, 3), 'spot_sizes': round(z, 3), 'spot_area_front': round(hs['front']['spot_area'], 4), 'spot_area_back': round(hs['back']['spot_area'], 4),
                  'n_spots_front': hs['front']['n_spots'], 'n_spots_back': hs['back']['n_spots'], 'px_front': hs['front']['px'], 'px_back': hs['back']['px']}
    return out


def write_glb(geoms: list, texs: list, dst: str) -> None:
    """Та же форма и развёртка, текстура — заполненная (выход этапа для следующих)."""
    import trimesh
    from PIL import Image
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    sc = trimesh.Scene()
    for g, t in zip(geoms, texs):
        mesh = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
        mesh.visual = TextureVisuals(uv=np.asarray(g['UV']), material=PBRMaterial(baseColorTexture=Image.fromarray(np.asarray(t)), metallicFactor=0.0, roughnessFactor=1.0))
        sc.add_geometry(mesh, geom_name=str(g.get('name') or 'mesh'))
    sc.export(dst)


def known_changed_share(known: list, before: list, after: list, de_min: float) -> dict:
    """Доля известных этапу 6 (и покрашенных) текселей, цвет которых после заливки изменился больше de_min (ΔE00) — по правилу заливка их не трогает, ожидаем 0. → {'share_pct', 'known', 'changed'}."""
    tot, chg = 0, 0
    for k, b, a in zip(known, before, after):
        kk = np.asarray(k, bool) & ~unpainted_mask(b.reshape(-1, 3)).reshape(b.shape[:2])
        tot += int(kk.sum())
        diff = kk & np.any(np.asarray(a)[..., :3] != np.asarray(b)[..., :3], axis=2)
        if diff.any():
            la, lb = rgb2lab(np.asarray(a)[..., :3][diff]), rgb2lab(np.asarray(b)[..., :3][diff])
            chg += int((TC.de2000_v(la, lb) > de_min).sum())
    return {'share_pct': round(100.0 * chg / max(tot, 1), 4), 'known': tot, 'changed': chg}


def stage6_gate(prev_dir: str):
    """Можно ли заливать: по `check.json` и выходу этапа 6 (`06-visible`). Отказ: нет check.json, камера этапа 4 не прошла (`extra.camera_failed` / `camera_gate`='failed'), этап пометил отказ (`extra.refused`), нет `visible.glb`.
    Мягкий провал этапа 6 (passed=false по меркам, но выход есть — например `needs_qwen`) не отказ: заливка идёт, провал записывается в check.json (`stage6`). → (отказ, причина, {'passed', 'reason', 'soft_fail'})."""
    import paint_stage as PS
    hard = RULES['stage6_gate']['hard']                          # жёсткие причины отказа — в rules/paint-fill.json (stage6_gate.hard), всё прочее мягкое
    c = PS.read_check(prev_dir)
    if c is None:
        return (True, 'нет check.json этапа 6', {'passed': None}) if hard['need_check_json'] else (False, '', {'passed': None, 'soft_fail': True})
    ex = c.get('extra') or {}
    info = {'passed': bool(c.get('passed')), 'reason': str(c.get('reason') or '')[:300]}
    if any(ex.get(k) for k in hard['extra_true']) or any(ex.get(k) == v for k, v in hard['extra_equals'].items()):
        return True, info['reason'] or 'отказ этапа 6', info
    for fn in hard['required_files']:
        if not os.path.exists(os.path.join(prev_dir, fn)):
            return True, f'нет {fn} этапа 6', info
    info['soft_fail'] = not info['passed']
    return False, '', info


def run_stage(run: str, sku: str, glb: str, known: list | None = None, parts=None, cfg: dict | None = None, thresholds: dict | None = None, mirror: bool = True, draft_glb: str | None = None, out_name: str | None = None, parts_npz: str | None = None, prev_dir: str | None = None) -> dict:
    """Этап 07 «докрасить невидимое»: GLB (текстура = фото на видимом) → `<run>/<sku>/07-fill/` {filled.glb, report.json, frame.png (az180 до | после), check.json}.
    `known` — маска «видно с камеры фото» по геометриям (нет — из `known_from_photo`: az0/az45); `parts` — части граней (нет — `parts_from_geometry`). Не прошёл (check.json passed=false) — товар дальше не идёт.
    → {'check', 'report', 'geoms', 'tex_before', 'tex_after', 'known', 'parts', 'dir'} (для проб и кадров)."""
    import json
    from PIL import Image
    import paint_stage as PS
    t0 = time.time()
    d = PS.stage_dir(run, sku, out_name or STAGE)
    th = dict(THRESHOLDS, **(thresholds or {}))
    s6 = None
    if prev_dir:                                                  # выход этапа 6 (`06-visible`): отказ камеры/нет выхода — этап 7 сам отказывает, не заливает
        refuse, why, s6 = stage6_gate(prev_dir)
        if refuse:
            chk = PS.write_check(d, out_name or STAGE, sku, False, None, 'этап 6 отказал: ' + why, seconds=time.time() - t0, outputs=[], refused=True, stage6=s6)
            return {'check': chk, 'refused': True, 'report': None, 'dir': d}
    geoms = TC.load_geoms(glb)
    tex_before = [np.asarray(g['tex']).copy() for g in geoms]
    _chk6 = PS.read_check(prev_dir) if prev_dir else None
    cfg, cam_note = pr_camera_from_extra((_chk6 or {}).get('extra'), cfg)               # камера образца узора — из этапа 4
    if known is None:
        known = known_from_photo(geoms)
    parts_note = 'заданы'
    from_stage3 = parts is None and bool(parts_npz)
    if parts is None and parts_npz:
        parts, parts_note = parts_from_npz(parts_npz, geoms)
    if parts is None:
        parts, parts_note = parts_from_geometry(geoms)
    cfg, pc_note = resolve_part_class(cfg, parts_npz, from_stage3)
    if from_stage3 and (cfg or {}).get('part_role') is None:                    # роли этапа 3 — для правил по ролям (общий тон, гладкое дерево)
        _roles = roles_from_parts_json(os.path.join(os.path.dirname(parts_npz), 'parts.json'))
        if _roles:
            cfg = dict(cfg or {}, part_role=_roles)          # C: классы частей — из этапа 3 сами (CFG_C больше не нужен)
    draft = None
    if (cfg or {}).get('source') in ('trellis', 'trellis_relief'):
        draft = draft_texels(geoms, TC.load_geoms(draft_glb), cfg)
    kback = known_from_photo(geoms, azimuths=(180.0,))
    _to = load_tone_only_png(prev_dir) if (prev_dir and (cfg or {}).get('tone_only_use', True)) else None      # тон-слой этапа 6 (р.8): цвет оставить, фактуру положить поверх

    def one(cfg_, draft_):
        r_ = fill(geoms, known, parts, cfg_, mirror, draft_, tone_only=_to)
        rp, tx_ = r_['report'], r_['tex']
        de_ = part_deltas(geoms, parts, known, kback, tex_before, tx_)
        kt = max(sum(v['known_texels'] for v in rp['parts'].values()), 1)
        bg = [p for p, v in rp['parts'].items() if v['known_texels'] >= 0.01 * kt]
        da = {int(p): v['after'] for p, v in de_.items() if v['after'] is not None}
        dw = max([da[p] for p in bg if p in da] or [None]) if any(p in da for p in bg) else None
        vals = {'empty_pct': rp['unpainted_after_pct'], 'dE00_front_back': dw, 'filled_faces_step_pct': rp['steps']['after']['filled_faces_step_pct'], 'far_excess_pct': rp['far_pct']['excess']}
        nfail = sum(0 if PS.judge(vals[k], th[k][0], th[k][1]) else 1 for k in vals)
        return {'rep': rp, 'tex': tx_, 'de': de_, 'big': bg, 'de_worst': dw, 'vals': vals, 'nfail': nfail, 'key': (nfail, dw if dw is not None else 99.0, vals['far_excess_pct'] if vals['far_excess_pct'] is not None else 99.0)}
    tried = {}
    if draft is not None and (cfg or {}).get('source') == 'trellis' and dict(FILL, **(cfg or {}))['draft_fallback']:      # Б и А: Б берётся, только если мерки не хуже (число непрошедших, затем ΔE перёд↔зад, затем пятна)
        cA = one(dict(cfg or {}, source='stat'), None)
        tried = {'stat': {'nfail': cA['nfail'], **cA['vals']}}
        if cA['nfail'] == 0 and dict(FILL, **(cfg or {}))['draft_when'] == 'a_fails':    # А прошёл все мерки — Б не считаем (экономия времени этапа)
            pick, used = cA, 'stat'
        else:
            cB = one(cfg, draft)
            tried['trellis'] = {'nfail': cB['nfail'], **cB['vals']}
            pick, used = (cB, 'trellis') if cB['key'] <= cA['key'] else (cA, 'stat')
    else:
        pick, used = one(cfg, draft), ((cfg or {}).get('source') or 'stat')
    rep, tex_after, de, big, de_worst = pick['rep'], pick['tex'], pick['de'], pick['big'], pick['de_worst']
    kchg = known_changed_share(known, tex_before, tex_after, RULES['known_change_de'])
    rep['known_changed'] = kchg
    try:                                                          # мерка узора — только отчёт (порог по трудным — позже), сбой её не роняет этап
        rep['pattern_metric'] = pattern_metrics(geoms, parts, known, tex_after, rep, dict(FILL, **(cfg or {})))
    except Exception as e:  # noqa: BLE001
        rep['pattern_metric'] = {'error': f'{type(e).__name__}: {e}'}
    rep['source_used'], rep['source_tried'] = used, tried
    rep['pr_camera'] = cam_note
    write_glb(geoms, tex_after, os.path.join(d, 'filled.glb'))
    a = render_ortho(geoms, tex_before, 180.0)
    b = render_ortho(geoms, tex_after, 180.0)
    Image.fromarray(np.concatenate([a, np.full((a.shape[0], 12, 3), 255, np.uint8), b], axis=1)).save(os.path.join(d, PS.FRAME))
    secs = time.time() - t0
    metrics = {
        'empty_pct': {'value': rep['unpainted_after_pct'], 'threshold': th['empty_pct'][1], 'op': th['empty_pct'][0]},
        'dE00_front_back': {'value': de_worst, 'threshold': th['dE00_front_back'][1], 'op': th['dE00_front_back'][0]},
        'filled_faces_step_pct': {'value': rep['steps']['after']['filled_faces_step_pct'], 'threshold': th['filled_faces_step_pct'][1], 'op': th['filled_faces_step_pct'][0]},
        'far_excess_pct': {'value': rep['far_pct']['excess'], 'threshold': th['far_excess_pct'][1], 'op': th['far_excess_pct'][0]},
        'known_changed_share_pct': {'value': kchg['share_pct'], 'threshold': th['known_changed_share_pct'][1], 'op': th['known_changed_share_pct'][0]},
        'pool_rejected_pct': {'value': round(100.0 * max(rep.get('quilt_rejected_share', {}).values(), default=0.0), 1), 'threshold': th['pool_rejected_pct'][1], 'op': th['pool_rejected_pct'][0]},     # мягкий провал: больше половины пула блоков отбраковано правилом — образец беден, запасной режим (плитка) вместо квилта
        'time_s': {'value': round(secs, 1), 'threshold': th['time_s'][1], 'op': th['time_s'][0]},
    }
    for m in metrics.values():
        m['ok'] = PS.judge(m['value'], m['op'], m['threshold'])
    if draft is not None:
        rep['draft_transfer'] = draft['report']
    report = {'report': rep, 'deltaE_by_part': de, 'big_parts': big, 'parts_note': parts_note, 'part_class_note': pc_note, 'empty_before_pct': rep['unpainted_before_pct']}
    with open(os.path.join(d, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    check = PS.write_check(d, out_name or STAGE, sku, None, dict(metrics['empty_pct'], name='empty_pct'), '', metrics={k: v for k, v in metrics.items() if k != 'empty_pct'}, seconds=secs,
                           outputs=['filled.glb', 'report.json'], frame=PS.FRAME, known_pct=rep['known_pct'], mirrored_pct=rep['mirrored_pct'], empty_before_pct=rep['unpainted_before_pct'], empty_by_view=rep['unpainted_by_view'], steps=rep['steps'], parts=parts_note, source_used=used, source_tried=tried, pattern_metric=rep['pattern_metric'], pattern_src=rep.get('pattern_src'), stage6=s6, quilt_rejected=rep.get('quilt_rejected'))
    return {'check': check, 'report': rep, 'geoms': geoms, 'tex_before': tex_before, 'tex_after': tex_after, 'known': known, 'parts': parts, 'dir': d, 'deltaE': de, 'kback': kback}


def load_tone_only_png(visible: str) -> list | None:
    """Маски «тон-только» этапа 6 (р.8): `tone_only.png`, `tone_only1.png`, … (белое = цвет есть, фото-правды нет). Нет файла — None (прежнее поведение)."""
    from PIL import Image
    out = []
    for i in range(64):
        fp = os.path.join(visible, "tone_only.png" if i == 0 else f"tone_only{i}.png")
        if not os.path.exists(fp):
            break
        out.append(np.asarray(Image.open(fp).convert("L")) > 127)
    return out or None


def load_known_png(visible: str) -> list:
    """Маски «известно» этапа 6: `known.png`, `known1.png`, … (по геометриям, белое = известно)."""
    from PIL import Image
    kn = []
    for i in range(64):
        fp = os.path.join(visible, "known.png" if i == 0 else f"known{i}.png")
        if not os.path.exists(fp):
            break
        kn.append(np.asarray(Image.open(fp).convert("L")) > 127)
    return kn


def main(argv: list | None = None) -> int:
    """CLI этапа 07 в формате paint_stage (обвязка сквозного прогона 01→09):
      python3 tools/scout/salad/trellis/tex_fill.py run_stage <run> <sku> [--visible <папка 06-visible>] [--parts-npz <parts.npz> | --no-parts-npz] [--cfg <json>] [--no-mirror]
    Вход по умолчанию: выход этапа 6 `<run>/<sku>/06-visible/{visible.glb, known*.png, check.json}` и части этапа 3 `<run>/<sku>/03-parts/parts.npz` (нет файла — части по геометрии).
    Выход: `<run>/<sku>/07-fill/{filled.glb, report.json, frame.png, check.json}`. Этап 6 отказал (камера не прошла, нет выхода) — check.json passed=false, refused=true, заливки нет.
    Код выхода: 0 — этап отработал (прошёл или не прошёл — см. check.json), 2 — сбой запуска (нет входа, исключение)."""
    import argparse
    import json
    import paint_stage as PS
    ap = argparse.ArgumentParser(prog="tex_fill.py run_stage")
    ap.add_argument("cmd", choices=["run_stage"])
    ap.add_argument("run")
    ap.add_argument("sku")
    ap.add_argument("--visible", default=None)
    ap.add_argument("--parts-npz", default=None)
    ap.add_argument("--no-parts-npz", action="store_true")
    ap.add_argument("--cfg", default=None)
    ap.add_argument("--no-mirror", action="store_true")
    a = ap.parse_args(argv)
    base = os.path.join(a.run, PS.safe_name(a.sku))
    visible = a.visible or os.path.join(base, "06-visible")
    if a.no_parts_npz and a.parts_npz:
        ap.error("--parts-npz и --no-parts-npz вместе нельзя")
    default_npz = os.path.join(base, "03-parts", "parts.npz")
    parts_npz = None if a.no_parts_npz else (a.parts_npz or (default_npz if os.path.exists(default_npz) else None))      # --no-parts-npz: этап 3 отказал — parts.npz не брать, части по геометрии (+ сироты)
    cfg = dict({"erode_known": 0}, **(json.loads(a.cfg) if a.cfg else {}))      # вход этапа 6: маска «взято с фото» уже честная
    try:
        r = run_stage(a.run, a.sku, os.path.join(visible, "visible.glb"), known=load_known_png(visible) or None, cfg=cfg, mirror=not a.no_mirror, parts_npz=parts_npz, prev_dir=visible)
    except Exception as e:                                                       # noqa: BLE001 — сбой запуска: в check.json, не молча
        d = PS.stage_dir(a.run, a.sku, STAGE)
        PS.write_check(d, STAGE, a.sku, False, None, f"сбой этапа 7: {type(e).__name__}: {e}"[:300], outputs=[])
        print(f"сбой: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    c = r["check"]
    print(f"07-fill {a.sku}: passed={c['passed']} {c['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
