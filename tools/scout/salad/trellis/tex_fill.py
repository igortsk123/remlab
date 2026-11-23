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
    'pattern_lattice_margin': 0.1,   # узорная часть: решётка допустима до эталона src (та же мерка по известному фото части) + этот запас, но не ниже quilt_lattice_max
    'pattern_min_blocks': 8.0,       # узорная часть с известным меньше стольких площадей блока: «рисунок не наблюдаем» → тон части + зерно, без квилта (решение директора 23.11)
    'pattern_big_mul': 1.5,          # ступень (в) для узорной: блок крупнее во столько раз, пул — из всей части (развёртка)
    'quilt_lattice_max': 0.3,        # мерка «решётка квилта»: избыточная автокорреляция детали L на лагах, кратных шагу блока (B−перекрытие), выше — пул слишком мал (блоки повторяются по сетке), квилт пересобирается
    'quilt_stride_div': 2,           # шаг выборки блоков пула = блок / quilt_stride_div (2 = полблока); при решётке удваивается, пока мерка не уйдёт или не достигнет quilt_stride_div_max
    'quilt_stride_div_max': 8,
    'patch_quilt_min_pool': 8,       # блок-образец (patch 64/32/16): один «типичный» блок плиткой даёт решётку с периодом B; при стольких и более годных блоках плитка собирается квилтом из ВСЕХ (если решётка меньше)
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
    'ref_zone_map': None,            # Ш8м: {face_zone, face_side, map, offs} из ref_zone.compare — карта зона×сторона×свойство; применяется ПОСЛЕ заливки, только при apply_to_fill=true (по умолчанию выкл.)
    'ref_verdict': None,             # Ш8 (ADR-0459): {часть: 'same'|'different'|'unknown'} — решение по образцу UltraTex (ref_zone.py); different → тон части без рисунка; нет — прежнее поведение
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
    'no_role_global': 'skip',                                # часть БЕЗ роли (нет этапа 3), у которой известного < min_known: 'skip' — не красить (тон ВСЕГО товара через границу материала не берётся, правило Ш6), 'legacy' — прежний тон всего товара
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


def quilt_lattice(patch: np.ndarray, step: int) -> dict:
    """Мерка «решётка квилта» (T-187/7, 23.11): повторяются ли одни и те же блоки по сетке шага `step` = B − перекрытие. Деталь яркости (L минус гауссов низкий пас σ6, плитка циклическая — она кладётся с обёрткой),
    циклическая автокорреляция r; на каждом лаге k·step по осям — ИЗБЫТОК r над средним двух соседних лагов (±step/2): волокно дерева коррелирует на любом лаге вдоль волокна (избыток ≈ 0), повтор блока — пик
    ровно на k·step. → {'excess': максимум избытка, 'r': r на этом лаге, 'lag': (ось, лаг)}; плитка меньше двух шагов — 0."""
    from scipy.ndimage import gaussian_filter
    S = patch.shape[0]
    step = int(step)
    if step < 2 or S < 2 * step + 2:
        return {'excess': 0.0, 'r': 0.0, 'lag': None}
    L = patch[..., 0].astype(np.float64)
    L = L - gaussian_filter(L, 6, mode='wrap')
    F = np.fft.rfft2(L)
    ac = np.fft.irfft2(F * np.conj(F), s=L.shape)
    if ac[0, 0] <= 1e-9:
        return {'excess': 0.0, 'r': 0.0, 'lag': None}
    ac = ac / ac[0, 0]
    d = max(2, step // 2)
    best = {'excess': -1.0, 'r': 0.0, 'lag': None}
    for ax in (0, 1):
        prof = ac[:, 0] if ax == 0 else ac[0, :]
        for k in range(1, (S // 2) // step + 1):
            lag = k * step
            if lag + d >= S:
                break
            ex = float(prof[lag] - 0.5 * (prof[lag - d] + prof[lag + d]))
            if ex > best['excess']:
                best = {'excess': ex, 'r': float(prof[lag]), 'lag': ('y' if ax == 0 else 'x', lag)}
    return best


def part_rng(base: int, part, gi: int = 0) -> np.random.RandomState:
    """Свой генератор на часть (и геометрию): результат части не зависит от того, сколько и каких частей рядом (T-187/6, 23.11)."""
    return np.random.RandomState((int(base) + 1000003 * (int(part) + 1) + 7919 * int(gi)) % (2 ** 31 - 1))


def known_lattice(res: np.ndarray, ok: np.ndarray, step: int):
    """Эталон src для узорной части (T-187/6, 23.11): та же мерка, что `quilt_lattice` (деталь L = L минус гаусс σ6; избыток автокорреляции на лагах k·step над средним соседних ±step/2), но по ВСЕМУ известному
    части с дырами: маскированная автокорреляция без обёртки (сумма произведений пар известных / число пар), нормирована на лаг 0. Это период самого рисунка фото, не квилта.
    `res` (n,n,3) остаток цвета, `ok` (n,n) bool «известное этой части», `step` — шаг лага в пикселях/текселях ЭТОГО массива. Мало известного (< 8 шагов²) или нет лага с ≥ 50 пар — None."""
    from scipy.ndimage import gaussian_filter
    ok = np.asarray(ok, bool)
    step = int(step)
    n = ok.shape[0]
    if step < 2 or n < 2 * step + 2 or int(ok.sum()) < 8 * step * step:
        return None
    m = ok.astype(np.float64)
    L = np.asarray(res)[..., 0].astype(np.float64)
    lo = gaussian_filter(L * m, 6) / np.maximum(gaussian_filter(m, 6), 1e-6)
    H = (L - lo) * m
    shp = (2 * n, 2 * n)
    FH, FM = np.fft.rfft2(H, s=shp), np.fft.rfft2(m, s=shp)
    num = np.fft.irfft2(FH * np.conj(FH), s=shp)
    den = np.fft.irfft2(FM * np.conj(FM), s=shp)
    ac = num / np.maximum(den, 1.0)
    if ac[0, 0] <= 1e-9:
        return None
    ac = ac / ac[0, 0]
    d = max(2, step // 2)
    best = None
    for ax in (0, 1):
        prof = ac[:, 0] if ax == 0 else ac[0, :]
        cnt = den[:, 0] if ax == 0 else den[0, :]
        for k in range(1, (n // 2) // step + 1):
            lag = k * step
            if lag + d >= n or min(cnt[lag - d], cnt[lag], cnt[lag + d]) < 50:
                break
            ex = float(prof[lag] - 0.5 * (prof[lag - d] + prof[lag + d]))
            best = ex if best is None or ex > best else best
    return best


def pattern_lattice_limit(src, lmax: float, margin: float) -> float:
    """Предел решётки узорной части: max(порог, src + запас); эталона нет (известного мало) — просто порог."""
    return float(lmax) if src is None else max(float(lmax), float(src) + float(margin))


def pattern_unobserved(known_px: float, block_area: float, min_blocks: float) -> bool:
    """«Рисунок не наблюдаем»: известного у узорной части меньше `min_blocks` площадей блока (в тех же единицах). Блока нет/0 — не судим (False)."""
    return block_area > 0 and float(known_px) < float(min_blocks) * float(block_area)


def lattice_end_action(is_pattern: bool, after: float, src, big_tried: bool, lmax: float, margin: float) -> str:
    """Что делать, когда лестница (пул гуще → отражения ×4) кончилась, а решётка выше порога: 'ok' (после ≤ порога), 'flat' (обычная часть → плоский тон),
    'pass' (узорная в пределах эталона — период рисунка), 'big' (узорная: ступень (в), ещё не пробовали), 'fail' (узорная: (в) была, не дошло — честный провал, рисунок не стираем)."""
    if after <= lmax:
        return 'ok'
    if not is_pattern:
        return 'flat'
    if after <= pattern_lattice_limit(src, lmax, margin):
        return 'pass'
    return 'fail' if big_tried else 'big'


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


def render_pool(resq: np.ndarray, okr: np.ndarray, c: dict, scale: float, stride_div: int | None = None):
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
    s = max(Bq // int(stride_div or c['quilt_stride_div']), 1)
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


def _pb_donors(part_ids: list, stat: dict, qunobs: set) -> dict:
    """Донор «чистой полосы фото» для «не наблюдаем»: часть с наибольшим известным (не сама)."""
    return {p: max((q for q in part_ids if q != p), key=lambda q: stat[q][2]) for p in qunobs if len(part_ids) > 1}


def draft_relief(txs: list, draft: dict, labs: list, kn: list, part_ids: list, pat_parts: set, c: dict, R: dict, calib: dict | None = None, no_homog: set | frozenset = frozenset(), pb_donor: dict | None = None) -> tuple:
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
        def _pb_of(selk_, Lk_, slo_, shi_):
            shade_ = float(np.quantile(Lk_, c['tone_shadow_q'])) if c['tone_shadow_q'] > 0 and len(Lk_) else -1e9
            out_ = []
            for gi_, tx_ in enumerate(txs):
                Lm_ = labs[gi_][..., 0]
                band_, w2_ = _band(Lm_, kn[gi_] & (Lm_ >= shade_), slo_, shi_)
                out_.append(band_.reshape(-1)[tx_.ti[selk_[gi_] & (w2_.reshape(-1)[tx_.ti] >= R['far_w']) & (Lm_.reshape(-1)[tx_.ti] >= shade_)]])
            return np.concatenate(out_) if out_ else np.zeros(0)
        PB = _pb_of(selk, Lk, s_lo_k, s_hi_k)
        pb_from = None
        if len(PB) < c['min_known'] and pb_donor and p in pb_donor:                      # «не наблюдаем» с мизерным известным: чистая полоса фото — у части с наибольшим известным (в её масштабе), как calib
            q_ = int(pb_donor[p])
            selq = [kn[gi].reshape(-1)[tx.ti] & (tx.part == q_) for gi, tx in enumerate(txs)]
            Lq = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[selq[gi]], 0] for gi, tx in enumerate(txs)])
            spq_ = float(np.median(np.concatenate([spacing[gi][tx.part == q_] for gi, tx in enumerate(txs)] or [np.zeros(0)]))) if any((tx.part == q_).any() for tx in txs) else 0.0
            if spq_ > 0 and len(Lq) >= c['min_known']:
                slo_q = float(np.clip(R['band_lo'] / spq_, R['sigma_lo_min'], R['sigma_lo_max']))
                shi_q = float(np.clip(R['band_hi'] / spq_, 2.0 * slo_q, R['sigma_hi_max']))
                PB_q = _pb_of(selq, Lq, slo_q, shi_q)
                if len(PB_q) >= c['min_known']:
                    PB, pb_from = PB_q, q_
        pb, dbd, dlow = [], [], []
        for gi, tx in enumerate(txs):
            T = tx.T
            dl = draft['lab'][gi][..., 0]
            band_d, wd = _band(dl, dok[gi], s_lo, s_hi)
            band_d = np.where(dok[gi], band_d, 0.0)
            loc = np.sqrt(gaussian_filter(band_d ** 2, s_hi, mode='nearest'))
            lowL = _blur_norm(np.repeat(dl[..., None], 3, axis=2), dok[gi], max(R['patch_frac'] / sp, 3.0 * s_hi))[0][..., 0]
            hp = np.where(dok[gi], dl - _blur_norm(np.repeat(dl[..., None], 3, axis=2), dok[gi], 1.0)[0][..., 0], 0.0)      # пиксельная высокая частота — для поиска крошки (в полосе она размазана на σ_hi)
            dbd.append((band_d, loc, lowL, wd, hp))
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
        info = {'family': fam, 'spacing': round(sp, 5), 'sigma_lo_px': round(s_lo, 2), 'sigma_hi_px': round(s_hi, 2), 'sigma_photo': round(sv, 3), 'sigma_draft': round(sd, 3), 'p95_photo': round(p95, 3), 'homog_std': round(homog, 2), 'calib_donor': calib_q if pb_from is None else pb_from, 'fallback': None}
        if fam is None and p not in no_homog and homog > R['homog_max_std']:
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
def seam_pass(txs: list, out_lab: list, labs: list, kn_keep: list, conf: list | None, seam_c: dict, gutter: int = 8, skip_fn=None) -> dict:
    """Сведение шва «фото | заливка» (T-196, П1.136) на готовых растрах: out_lab[gi] (T,T,3 Lab, результат заливки) ПРАВИТСЯ на месте, kn_keep[gi] — тексели, оставшиеся 1:1 фото, тоже на месте.
    labs[gi] — Lab фото (исходник), conf — доверие к фото-текселю (этап 6) или None, skip_fn(gi, tx) → bool (n,) зоны без перекраски. Граница = известное ↔ всё залитое (зеркало не при чём).
    → отчёт: {'enabled', 'size_mm', 'conf_source', 'geoms': [{…, 'before', 'after'}], 'time_s'}. Общий код этапа 07 (при seam.enabled) и отдельного шага `seam_stage.py`."""
    import tex_seam as TS
    t_s = time.time()
    size_mm = float(seam_c.get('size_mm') or seam_c['size_mm_default'])
    srep = {'enabled': True}
    srep.update({'size_mm': size_mm, 'geoms': [], 'conf_source': 'карта этапа 6' if conf is not None else 'запасное: от границы известного'})
    for gi, tx in enumerate(txs):
        ti = tx.ti
        ol = out_lab[gi].reshape(-1, 3)
        skip_ = skip_fn(gi, tx) if skip_fn else np.zeros(len(ti), bool)
        cf = None if conf is None or gi >= len(conf) or conf[gi] is None else np.asarray(conf[gi], np.float64).reshape(-1)[ti]
        k0f = kn_keep[gi].reshape(-1)[ti]
        before = ol[ti].copy()
        sb = TS.surface_dist(tx, ~(k0f & ~skip_), size_mm, seam_c['pair_mm'] + 1.0)
        so = TS.surface_dist(tx, k0f & ~skip_, size_mm, seam_c['pair_mm'] + 1.0)
        tmm = TS.texel_mm(tx, size_mm)

        def _metric(lab_n, solid, s_in_, s_out_):
            img = TS.atlas_with_gutter(tx, lab2rgb(lab_n), gutter if gutter > 0 else 8)
            return TS.seam_metric(tx, TS.panel_zone(tx, seam_c['crease_deg'], seam_c['normal_smooth_iters'], seam_c['min_panel_faces']), lab_n, TS.mip1_lab(tx, img, rgb2lab), solid, s_in_, s_out_, seam_c, size_mm, tmm, TC.de2000_v)
        m_before = _metric(before, k0f & ~skip_, sb, so)
        # варианты сведения (T-196/1): полный (тон + контраст) | без контраста | только граница (feather); берём тот, у кого шов по мерке лучше; ни один не лучше «как было» — оставляем «как было»
        # (мерка шва — ΔE00 p95 пар через границу; шов, который уже не виден, не трогаем: на 112923/114082 полный вариант портил шов, p95 6,7→8,2 и 3,0→5,5)
        variants = [('full', seam_c), ('soft', dict(seam_c, contrast_gmax=min(1.3, seam_c['contrast_gmax']), patch_strength=0.5 * seam_c.get('patch_strength', 1.0))),
                    ('no_patch', dict(seam_c, patch_texture=False)), ('no_contrast', dict(seam_c, patch_texture=False, contrast_gmin=1.0, contrast_gmax=1.0)),
                    ('feather_only', dict(seam_c, patch_texture=False, contrast_gmin=1.0, contrast_gmax=1.0, tone_max=[0.0, 0.0, 0.0])),
                    # только тон заливки у границы: фото не вытягивается в заливку (feather 0) и слабое фото не переводится в заливку (conf_min/full < 0) — для узких ободков, где вытяжка вредит (стул 114082_7733, ободок сиденья)
                    ('tone_only', dict(seam_c, feather_mm=0.0, conf_min=-1.0, conf_full=-0.5, patch_texture=False, contrast_gmin=1.0, contrast_gmax=1.0))]

        def _dev(mx):
            return None if mx.get('texture_ratio') is None else abs(mx['texture_ratio'] - 1.0)
        p95_b = m_before['dE00_p95'] if m_before['dE00_p95'] is not None else 0.0
        step_b, dev_b = m_before.get('step_ratio'), _dev(m_before)
        tried, best = {}, None
        for vname, vc in variants:
            rv = TS.blend_seam(tx, before, labs[gi].reshape(-1, 3)[ti], k0f, cf, skip_, vc, size_mm)
            mv = _metric(rv['lab'], rv['solid'], rv['s_in'], rv['s_out'])
            rb_, ra_ = rv['report']['rough_before'].get('rough_rms_mm'), rv['report']['rough_after'].get('rough_rms_mm')
            tried[vname] = {k_: mv.get(k_) for k_ in ('dE00_median', 'dE00_p95', 'bad_share_pct', 'contrast_ratio', 'texture_ratio', 'step_ratio', 'step_ratio_p95')}
            tried[vname]['rough_rms_mm'] = ra_
            # «не навреди» по ВСЕМ меркам (те же пороги, что в check.json шва): ΔE00 p95, ступенька, фактура, шероховатость границы; не прошёл хотя бы одну — вариант отпадает
            why = []
            p95_v = mv['dE00_p95'] if mv['dE00_p95'] is not None else 99.0
            if p95_v > p95_b * seam_c.get('accept_p95_ratio', 1.0) + seam_c.get('accept_p95_abs', 0.0):
                why.append('p95')
            if step_b is not None and mv.get('step_ratio') is not None and mv['step_ratio'] > max(step_b, seam_c.get('step_floor', 1.5)):
                why.append('step')
            if _dev(mv) is not None and dev_b is not None and _dev(mv) > max(dev_b, seam_c.get('texdev_floor', 0.3)):
                why.append('texture')
            if rb_ is not None and ra_ is not None and ra_ > rb_ * seam_c.get('rough_tol', 1.1):
                why.append('rough')
            tried[vname]['rejected'] = why
            if why:
                continue
            key = (round(p95_v * 4.0) / 4.0, abs((mv['contrast_ratio'] or 0.0) - 1.0))     # p95 с шагом 0,25 (шум не решает), при равенстве — ближе контраст фактуры к 1
            if best is None or key < best[0]:
                best = (key, vname, rv, mv)
        if best is not None:
            _, chosen, r_, m_after_pre = best
        else:                                                           # ни один вариант не прошёл «не навреди» — не трогаем
            chosen, r_, m_after_pre = 'unchanged', None, m_before
        if r_ is None:
            r_ = {'lab': before.copy(), 'keep': k0f.copy(), 'solid': k0f & ~skip_, 's_in': sb, 's_out': so, 'report': {'zones': None, 'demoted_texels': 0, 'solid_texels': int((k0f & ~skip_).sum()), 'rough_before': TS.boundary_rough(tx, k0f, np.ones(len(ti), bool), tmm, seam_c['rough_sigma_mm'])}}
            r_['report']['rough_after'] = r_['report']['rough_before']
        ol[ti] = r_['lab']
        kk = kn_keep[gi].reshape(-1).copy()
        kk[ti] = r_['keep']
        kn_keep[gi] = kk.reshape(kn_keep[gi].shape)
        m_after = m_after_pre
        srep['geoms'].append(dict(r_['report'], before=m_before, after=m_after, variant=chosen, variants=tried))
    srep['time_s'] = round(time.time() - t_s, 2)
    return srep


def fill(geoms: list, known: list, parts: list | None = None, cfg: dict | None = None, mirror: bool = True, draft: dict | None = None, tone_only: list | None = None, unobs_draft_fn=None, conf: list | None = None) -> dict:
    """geoms — `tex_coverage.load_geoms`; known — по геометрии (T×T bool), parts — по геометрии номера частей ГРАНЕЙ (None — одна часть).
    draft — черновик TRELLIS на ту же форму/развёртку (`draft_texels`): {'lab': [(T,T,3) Lab], 'ok': [(T,T) bool]}; нужен при cfg['source']=='trellis': невидимое берёт цвет черновика,
    сдвинутый переносом статистики Lab (медиана/разброс части: черновик → видимое фото), детали черновика сохраняются; стыки — та же растушёвка. 'stat' (по умолчанию) — цвет части + лоскут фактуры.
    tone_only — (Ш6, р.8) по геометриям T×T bool: тексели с ТОНОВЫМ полем этапа 6 (цвет есть в visible.glb, фото-правды нет; в `known` НЕ входят). Цвет такого тексела остаётся как есть (тон-поле, среднее сохраняется),
    а фактура/заём кладутся поверх как на неизвестный (остаток без среднего); в статистику частей, пул блоков и доноры они не входят. Нет — поведение прежнее.
    conf — (T-196) доверие к фото-текселю 0..1 по геометриям (T×T float; карта этапа 6 `conf.png`), нет — запасное от границы известного; нужен только сведению шва (`rules/paint-fill.json` → `seam`).
    → {'tex': [uint8 (T,T,3) по геометриям], 'report': {...}, 'keep': [bool (T,T): тексели, оставшиеся 1:1 фото]}. Форма и развёртка не меняются."""
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
    if c.get('part_role') or c.get('no_role_global', 'skip') == 'skip':   # иерархия источника тона части: своя → донор той же роли (совместимый тон) → каталог → не красить
        tot_ = {p: int(sum(int((tx.part == p).sum()) for tx in txs)) for p in part_ids}
        kc_ = {p: int(stat[p][2]) for p in part_ids}
        fg_ = {p: bool(stat[p][3]) for p in part_ids}
        info_ = choose_tone_sources(part_ids, c.get('part_role') or {}, kc_, tot_, fg_, {p: stat[p][0] for p in part_ids}, part_borders(txs), c)
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
    mirror_on = bool(mirror) and bool(RULES.get('mirror_enabled', False))           # зеркала в пути 07 нет (rules/paint-fill.json: mirror_enabled=false); тон невидимого — донор по UltraTex (ref_zone)
    sym = symmetry(txs, kn, c['mirror_eps'], c['sample'], c['mirror_cos']) if mirror_on else {'axis': None, 'score': 0.0, 'planes': {}}
    rep['mirror'] = {'axis': sym['axis'], 'score': sym['score'], 'planes': sym['planes'], 'applied': False, 'texels': 0}
    if mirror and not mirror_on:
        rep['mirror']['off'] = 'rules mirror_enabled=false'
    if mirror_on and sym['axis'] is not None and sym['score'] >= c['mirror_min_score']:
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
        tgt, tgt_from, gap = float(stat[p][0][0]), 'tone', None
        if c.get('brightness_target', RULES.get('brightness_target', 'tone')) == 'median' and not stat[p][3]:          # T-198/1: цель — медиана L известного части (как мерит check), мода — только для a,b; статистика «глобальная» — своей медианы нет
            Lk = np.concatenate([labs[gi].reshape(-1, 3)[tx.ti[kn[gi].reshape(-1)[tx.ti] & (tx.part == p)]][:, 0] for gi, tx in enumerate(txs)])
            if len(Lk) >= c['min_known']:
                med_k = float(np.median(Lk))
                gap = round(tgt - med_k, 2)
                if gap > float(c.get('brightness_gap', RULES.get('brightness_gap', 3.0))):
                    tgt, tgt_from = med_k, 'median'
        shift = float(np.clip(tgt - np.median(vals), -c['dL_max'], c['dL_max']))
        rep['brightness'][p] = {'dL_before': round(float(np.median(vals) - tgt), 2), 'applied': 0.0, 'target': round(tgt, 2), 'target_from': tgt_from, 'mode_minus_median': gap}
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
    qunobs = set()                                         # узорные «рисунок не наблюдаем»: ни квилта, ни образца-заплатки — тон части
    qflat = set()                                          # части, где решётка квилта/образца не ушла после всех пересборок: фактура гладко (тон части), в отчёте flat (T-187/7, 23.11)
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
        qrngs = {}                                           # свой генератор на часть (живёт между ступенями лестницы: пересборки различаются)
        pr_S = pr_lab = pr_kn = pr_pm = None
        qwork = [(p, int(c['quilt_stride_div']), 0) for p in part_ids]      # часть может вернуться в конец списка с более плотным пулом (мерка решётки квилта); список растёт на ходу
        qlat = {}
        qsrc, qbq, qbig = {}, {}, {}          # узорные: эталон src решётки, блок первой сборки, пробовалась ли ступень (в)
        for p, qdiv, qaug in qwork:
            qrng = qrngs.setdefault(int(p), part_rng(7, p))
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
            if p in pat_parts and c["pattern_render"] and int(p) not in qbig:                  # узорная: блоки — из непрерывного кадра видимой стороны (az фото), не из дырявой развёртки; ступень (в) — из развёртки всей части
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
                rp = render_pool(resr * okr[..., None], okr, c, sc, qdiv)
                rep.setdefault("pattern_src", {})[int(p)] = ({"render": True, "pixels": int(okr.sum()), "scale": round(sc, 3), "block": rp[0], "pool": len(rp[1])} if rp is not None else {"render": False, "pixels": int(okr.sum()), "scale": round(sc, 3)})
            if rp is not None:
                Bq, pool = rp
                oq = max(2, int(round(Bq * c["quilt_overlap"])))
            else:
                gbest = int(np.argmax(cnt))                           # период узора — по геометрии, где у части больше всего известного
                Bq = pattern_period(resg[gbest][..., 0], okg[gbest], int(c['quilt_block_min']), int(c['quilt_block_max']))
                if int(p) in qbig:                                     # ступень (в): блок крупнее первой сборки
                    Bq = int(min(max(Bq, int(round(qbq.get(int(p), Bq) * float(c['pattern_big_mul'])))), int(c['quilt_block_max'])))
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
                        s = max(Bq // qdiv, 1)
                        ys = np.arange(0, T - Bq + 1, s)
                        Y, X = np.meshgrid(ys, ys, indexing='ij')

                        def bsum(I):
                            return I[Y + Bq, X + Bq] - I[Y, X + Bq] - I[Y + Bq, X] + I[Y, X]
                        good = (bsum(I_pm) >= Bq * Bq - 0.5) & (bsum(I_ok) >= thr * Bq * Bq) & (bsum(I_nr) >= Bq * Bq - 0.5)
                        for by, bx in zip(*np.nonzero(good)):
                            pool.append(fill_[Y[by, bx]:Y[by, bx] + Bq, X[by, bx]:X[by, bx] + Bq])
                    if len(pool) >= int(c['quilt_pool_min']):
                        break
            if p in pat_parts:                                         # узорная с малым известным (< pattern_min_blocks площадей блока): рисунок не наблюдаем → тон + зерно, без квилта
                kpx_, barea_ = (int(okr.sum()), (Bq / max(sc, 1e-6)) ** 2) if rp is not None else (int(sum(cnt)), float(Bq * Bq))
                if pattern_unobserved(kpx_, barea_, c['pattern_min_blocks']):
                    rep.setdefault('pattern_unobserved', {})[int(p)] = {'known_px': kpx_, 'block_area': round(barea_, 1), 'blocks': round(kpx_ / max(barea_, 1.0), 2)}
                    qflat.add(int(p))
                    qunobs.add(int(p))
                    rep.setdefault('quilt_lattice', {})[int(p)] = {'before': 0.0, 'rebuilt': 0, 'after': 0.0, 'flat': True, 'unobserved': True}
                    continue
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
            if qaug:                                              # пул мал даже при самом густом шаге: ×4 отражениями (по x, по y, оба) — блоки для сетки есть, повтор по сетке реже
                P = np.concatenate([P, P[:, ::-1], P[:, :, ::-1], P[:, ::-1, ::-1]])
            nq = int(max(c['quilt_cells'], np.ceil((c['quilt_side'] - oq) / (Bq - oq))))
            q = wrap_soften(quilt_image(P, nq, oq, qrng, int(c['quilt_tries']) * max(1, qdiv // int(c['quilt_stride_div'])) * (2 if qaug else 1)))
            lat = quilt_lattice(q, Bq - oq)
            first = int(p) not in qlat
            if first or lat['excess'] < qlat[int(p)]:             # лучшая из сборок (первая, либо с меньшей решёткой)
                qlat[int(p)] = lat['excess']
                patches[p] = q
                patch_gain[p] = 1.0
                if first:
                    rep['quilt'] = rep.get('quilt', 0) + 1
                rep.setdefault('quilt_info', {})[int(p)] = {'block': Bq, 'overlap': oq, 'cells': nq, 'pool': len(pool), 'jump_L': round(quilt_jump(q, Bq - oq), 3), 'stride_div': qdiv, 'flip': qaug,
                                                           'lattice': round(lat['excess'], 3), 'lattice_r': round(lat['r'], 3), 'lattice_lag': lat['lag']}
                if p in pat_parts:
                    raw_mean[p] = q.mean(axis=(0, 1))             # узорная: плитка без вычитания среднего и без смешения (фон = тон, цветы поверх)
            if first:
                qbq[int(p)] = Bq
                rep.setdefault('quilt_lattice', {})[int(p)] = {'before': round(lat['excess'], 3), 'rebuilt': 0}
            else:
                rep['quilt_lattice'][int(p)]['rebuilt'] = qdiv
                rep['quilt_lattice'][int(p)]['flip'] = qaug
                rep['quilt_lattice'][int(p)]['after'] = round(qlat[int(p)], 3)
            if lat['excess'] > c['quilt_lattice_max']:            # решётка: блоки повторяются по сетке (пул мал) — лестница: пул гуще (шаг вдвое мельче) → отражения ×4 → гладко (узорная: эталон src, ступень (в), без «гладко»)
                if p in pat_parts and int(p) not in qsrc:                                   # эталон узора: та же мерка по известному фото части (шаг лага — в пикселях того массива)
                    if rp is not None:
                        qsrc[int(p)] = known_lattice(resr, okr, max(2, int(round((Bq - oq) / max(sc, 1e-6)))))
                    else:
                        qsrc[int(p)] = known_lattice(resg[gbest], okg[gbest], Bq - oq)
                src_ = qsrc.get(int(p))
                lim_ = pattern_lattice_limit(src_, c['quilt_lattice_max'], c['pattern_lattice_margin'])
                if p in pat_parts and qlat[int(p)] <= lim_:                                   # решётка узорной не выше эталона (период самого рисунка) — не брак
                    rep.setdefault('quilt_lattice_pattern', {})[int(p)] = {'src': None if src_ is None else round(src_, 3), 'after': round(qlat[int(p)], 3), 'limit': round(lim_, 3), 'verdict': 'pass', 'big': int(p) in qbig}
                elif qdiv * 2 <= int(c['quilt_stride_div_max']) and int(p) not in qbig:
                    qwork.append((p, qdiv * 2, qaug))
                elif not qaug and int(p) not in qbig:
                    qwork.append((p, qdiv, 1))
                else:
                    act_ = lattice_end_action(p in pat_parts, qlat[int(p)], src_, int(p) in qbig, c['quilt_lattice_max'], c['pattern_lattice_margin'])
                    if act_ == 'flat':                                                        # обычная часть: гладко (тон части + зерно UltraTex)
                        qflat.add(int(p))
                        rep['quilt_lattice'][int(p)].update({'after_best': round(qlat[int(p)], 3), 'after': 0.0, 'flat': True})
                    elif act_ == 'big':                                                       # узорная: ступень (в) — блок крупнее, пул из всей части, пул гуще и отражения
                        qbig[int(p)] = float(c['pattern_big_mul'])
                        qwork.append((p, int(c['quilt_stride_div_max']), 1))
                    elif act_ == 'fail':                                                      # (в) не дошла — честный провал, рисунок не стираем
                        rep.setdefault('quilt_lattice_pattern', {})[int(p)] = {'src': None if src_ is None else round(src_, 3), 'after': round(qlat[int(p)], 3), 'limit': round(lim_, 3), 'verdict': 'fail', 'big': True}
        for p_ in qbig:                                          # (в) запускалась, но терминальной записи нет (пул мал → пропуск): итог по лучшей сборке
            if p_ in qlat and p_ not in qunobs and p_ not in rep.get("quilt_lattice_pattern", {}):
                lim_ = pattern_lattice_limit(qsrc.get(p_), c['quilt_lattice_max'], c['pattern_lattice_margin'])
                rep.setdefault('quilt_lattice_pattern', {})[p_] = {'src': None if qsrc.get(p_) is None else round(qsrc[p_], 3), 'after': round(qlat[p_], 3), 'limit': round(lim_, 3), 'verdict': 'pass' if qlat[p_] <= lim_ else 'fail', 'big': True}
    for p in (part_ids if (dshift is None or c['draft_texture']) else []):
        if p in patches or int(p) in qunobs:
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
                lat0 = quilt_lattice(np.tile(pick[1], (3, 3, 1)), B)             # один блок плиткой — период B по построению: решётка (T-187/7, 23.11: дерево №20, блок 16, r 0,6 на лагах 16/32/64/96)
                info_ = {'block': B, 'cands': len(cands), 'single_lattice': round(lat0['excess'], 3), 'used': 'single', 'lattice': round(lat0['excess'], 3)}
                oq_ = max(2, int(round(B * c['quilt_overlap'])))
                if len(cands) >= 3 and B - oq_ >= 2:
                    prng = np.random.RandomState(11 + int(p))                    # свой генератор: общий rng (смещения плиток ниже) не сдвигается
                    Pq = np.stack([x[1] for x in cands]).astype(np.float64)
                    if len(Pq) > int(c['quilt_pool']):
                        Pq = Pq[prng.choice(len(Pq), int(c['quilt_pool']), replace=False)]
                    Pq = Pq - Pq.mean(axis=(1, 2), keepdims=True)
                    sdq = Pq.reshape(len(Pq), -1).std(axis=1)
                    Pq = Pq * np.clip(med / np.maximum(sdq, 1e-6), c['quilt_gain'][0], c['quilt_gain'][1])[:, None, None, None]
                    nq_ = int(max(c['quilt_cells'], np.ceil((c['quilt_side'] - oq_) / (B - oq_))))
                    best_ = None
                    for flip_ in ((0, 1) if len(cands) >= int(c['patch_quilt_min_pool']) else (1,)):          # лестница: пул как есть → отражения ×4 (у малого пула — сразу ×4)
                        Pf = np.concatenate([Pq, Pq[:, ::-1], Pq[:, :, ::-1], Pq[:, ::-1, ::-1]]) if flip_ else Pq
                        q_ = wrap_soften(quilt_image(Pf, nq_, oq_, prng, int(c['quilt_tries']) * (2 if flip_ else 1)))
                        l_ = quilt_lattice(q_, B - oq_)
                        if best_ is None or l_['excess'] < best_[1]['excess']:
                            best_ = (q_, l_, flip_)
                        if l_['excess'] <= c['quilt_lattice_max']:
                            break
                    q_, lat1, flip_ = best_
                    info_.update({'quilt_lattice': round(lat1['excess'], 3), 'quilt_tile': int(q_.shape[0]), 'flip': flip_})
                    if lat1['excess'] < lat0['excess']:
                        patches[p] = q_
                        patch_gain[p] = med / max(float(q_.std()), 1e-6)
                        info_['used'] = 'quilt'
                        info_['lattice'] = round(lat1['excess'], 3)
                if info_['lattice'] > c['quilt_lattice_max']:                     # решётка осталась — гладко (тон части), мерка по итогу 0
                    qflat.add(int(p))
                    info_.update({'used': 'flat', 'lattice_best': info_['lattice'], 'lattice': 0.0})
                rep.setdefault('patch_lattice', {})[int(p)] = info_
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
                pick = part_rng(5, p).choice(near, size=nq * nq, replace=True)
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
    unobs_only = c['source'] != 'trellis_relief' and bool(qunobs) and unobs_draft_fn is not None       # боевой путь (stat): рельеф UltraTex — только «рисунок не наблюдаем»
    if c['source'] == 'trellis_relief' or unobs_only:
        calib_ = {int(p_): int(v_['donor']) for p_, v_ in rep.get('tone_from_neighbour', {}).items()} if c.get('relief_calib_donor') else None
        if unobs_only:
            draft = unobs_draft_fn()
            relief, rep["relief"] = draft_relief(txs, draft, labs, kn, sorted(qunobs), set(), c, RULES["trellis_relief"], calib=calib_, no_homog=frozenset(qunobs), pb_donor=_pb_donors(part_ids, stat, qunobs))
        else:
            relief, rep["relief"] = draft_relief(txs, draft, labs, kn, part_ids, (set(raw_mean) | set(pat_parts)) - qunobs, c, RULES["trellis_relief"], calib=calib_, no_homog=frozenset(qunobs), pb_donor=_pb_donors(part_ids, stat, qunobs))          # «рисунок не наблюдаем» — как обычная часть: рельеф UltraTex (T-187/6, 23.11)
        Rr = RULES['trellis_relief']
        spac = [texel_spacing(tx) for tx in txs]
        fade = []
        for gi, tx in enumerate(txs):                            # затухание рельефа от границы фото в ФИЗИЧЕСКОМ расстоянии (шаг текселя × расстояние в карте), известные тексели не трогаем
            dpx = distance_transform_edt(~kn[gi])
            fade.append(np.clip(dpx.reshape(-1)[tx.ti] * spac[gi] / max(Rr['fade_len'], 1e-9), 0.0, 1.0))
        smooth_parts = set() if unobs_only else {p for p in part_ids if p not in raw_mean and p not in pat_parts and rep.get('quilt_rejected_share', {}).get(p, 0.0) > Rr['smooth_pool_rejected']}
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
            rng_p = part_rng(5, p, gi)
            tile = patches[p] if p in raw_mean else _gaussian_tile(patches[p], rng_p)
            ox1, oy1 = rng_p.randint(0, Bp, 2)
            ox2, oy2 = rng_p.randint(0, Bp, 2)
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
            rv_ = (c.get('ref_verdict') or {})
            smooth_p = smooth_part_rule(roles_.get(p, roles_.get(str(p))), rep.get('quilt_info', {}).get(p, {}).get('jump_L'), p in raw_mean, c, rv_.get(p, rv_.get(str(p))))
            if smooth_p or int(p) in qflat:                                                                              # дерево/каркас и плитка с заметными швами — гладко, без «ёлочки»
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
    # --- сведение шва «фото | заливка» (T-196, П1.136): доверие → тон зоны → контраст фактуры и переход на сомнительных краях фото; мерка шва до/после (на mip1)
    seam_c = dict(RULES.get('seam') or {}, **((cfg or {}).get('seam') or {}))
    rep['seam'] = {'enabled': bool(seam_c.get('enabled'))}
    if seam_c.get('enabled'):
        rep['seam'] = seam_pass(txs, out_lab, labs, kn_keep, conf, seam_c, c['gutter'],
                                lambda gi, tx: (np.isin(tx.part, sorted(skip_parts)) & ~mirrored[gi].reshape(-1)[tx.ti]) if skip_parts else np.zeros(len(tx.ti), bool))
        rep['time_s']['seam'] = rep['seam']['time_s']
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

    def finish(outs):
        """Мерки по ГОТОВОЙ текстуре (outs): непокрашенное, виды, ступени, далёкий цвет. fill() зовёт её сам; run_stage_once — ещё раз по итогу после всех хуков (р.7, 23.11)."""
        for gi, tx in enumerate(txs):
            T = tx.T
            rgb = outs[gi]
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
        return rep

    finish(outs)
    return {'tex': outs, 'report': rep, 'finish': finish, 'keep': kn_keep}


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
def side_azimuths(geoms: list, known: list, cands=(0.0, 90.0, 180.0, 270.0), res: int = 256) -> dict:
    """Стороны предмета по known (T-187/6, 23.11): фото-сторона — азимут, с которого видно больше всего известных (фото) текселей; зад — противоположный. Не по числу: формы лежат передом в разные стороны.
    → {'photo': az, 'back': az, 'shares': {az: доля известного в кадре}}; known нет/пуст — {'photo': 0, 'back': 180, 'shares': {}, 'fallback': True}."""
    try:
        kn = [np.where(np.asarray(k, bool)[..., None], np.array([255, 0, 0], np.uint8), np.array([0, 0, 255], np.uint8)).astype(np.uint8) for k in known]      # известное — красное, нет — синее (фон серый, не считается)
        sh = {}
        for az in cands:
            im = render_ortho(geoms, kn, az, res=res)
            red = int((im[..., 0].astype(int) - im[..., 2].astype(int) > 40).sum())
            blue = int((im[..., 2].astype(int) - im[..., 0].astype(int) > 40).sum())
            sh[az] = red / max(red + blue, 1)
        best = max(sh, key=lambda a: sh[a])
        if sh[best] <= 0.005:
            return {'photo': 0.0, 'back': 180.0, 'shares': sh, 'fallback': True}
        return {'photo': float(best), 'back': float((best + 180.0) % 360.0), 'shares': {str(int(k)): round(v, 4) for k, v in sh.items()}}
    except Exception as e:  # noqa: BLE001
        return {'photo': 0.0, 'back': 180.0, 'shares': {}, 'fallback': True, 'error': f'{type(e).__name__}: {e}'}


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
    for k in ('enabled', 'size_mm_default', 'conf_min', 'conf_full', 'edge_mm', 'probe_mm', 'cell_mm', 'reach_mm', 'tone_decay_mm', 'tone_max', 'min_cell', 'hi_sigma_mm', 'contrast_decay_mm',
              'contrast_gmin', 'contrast_gmax', 'contrast_floor', 'pair_mm', 'pair_cos', 'de_bad', 'poisson', 'crease_deg', 'normal_smooth_iters', 'min_panel_faces', 'feather_mm', 'feather_lo', 'feather_hi', 'rough_sigma_mm', 'accept_p95_ratio', 'accept_p95_abs', 'patch_texture', 'patch_reach_mm', 'patch_strength', 'patch_mm', 'patch_decay_mm', 'texture_band_mm', 'step_floor', 'texdev_floor', 'rough_tol', 'cpu_s_per_variant_geom', 'tone_zone_min_cells'):
        if k not in (r.get('seam') or {}):
            raise KeyError(f'rules/paint-fill.json: seam.{k} не задан')
    for k in ('gain_max', 'clip_k', 'patch_frac', 'patch_dl', 'dilate_px', 'part_max_share', 'band_lo', 'band_hi', 'sigma_lo_min', 'sigma_lo_max', 'sigma_hi_max', 'far_w', 'p95_cap',
              'ok_erode_px', 'allowed_families', 'homog_max_std', 'fade_len', 'smooth_pool_rejected'):
        if k not in r['trellis_relief']:
            raise KeyError(f'rules/paint-fill.json: trellis_relief.{k} не задан')
    for k in ('quilt_extreme', 'mirror_extreme'):
        if 'black_rel' not in r[k]:
            raise KeyError(f'rules/paint-fill.json: {k}.black_rel не задан')
    for k in ('pool_rejected_pct', 'empty_pct', 'dE00_front_back', 'dL_front_back', 'filled_faces_step_pct', 'far_excess_pct', 'known_changed_share_pct', 'cpu_s', 'front_on_back_corr', 'quilt_lattice_max'):
        if k not in r['thresholds']:
            raise KeyError(f'rules/paint-fill.json: threshold {k!r} не задан')
    return r


RULES = load_rules()
THRESHOLDS = {k: (v[0], float(v[1])) for k, v in RULES['thresholds'].items()}   # пороги этапа (check.json) из rules/paint-fill.json: ΔE00 перёд↔зад (худшая часть с известным ≥ 1 %), ступени, пятна, «известное не изменено» (0), время


def load_part_modules():
    """Модули частей граней из `tools/assets` (material_parts, parts_refine, parts_vote) и их правила. → (MP, PR, PV, правила material_parts, правила parts_vote).
    НЕ ГЛОТАЕТ ошибки загрузки (T-193/3, 22.11): нет модуля/файла правил (ImportError/OSError/ValueError) — исключение, этап падает. Раньше `except Exception` превращал это в «частей нет»,
    и на Salad (в срезе кода не было tools/assets) 07 тихо считался БЕЗ частей, расходясь с локальным (сверка T-193/2)."""
    assets = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'assets'))
    if assets not in sys.path:
        sys.path.insert(0, assets)
    import material_parts as MP
    import parts_refine as PR
    import parts_vote as PV

    def rules_of(mod) -> str:                                     # ROOT/data/flat3d/x.json; в срезе кода для Salad те же байты лежат как tools/assets/_data/flat3d/x.json (воркер распаковывает только tools/…, code_tar.packed_name)
        p = mod.RULES_PATH
        packed = os.path.join(assets, '_data', 'flat3d', os.path.basename(p))
        return p if os.path.isfile(p) or not os.path.isfile(packed) else packed
    return MP, PR, PV, MP.load_rules(rules_of(MP)), PV.load_rules(rules_of(PV))


def merge_orphan_parts(mesh, part: np.ndarray):
    """Запасное деление по геометрии: часть-«сирота» (доля ПЛОЩАДИ < `refine.orphan_max_area_share` из parts-sam-rules.json) вливается в соседа с самой длинной границей — общее правило этапа 3 (`parts_refine.merge_orphans`, T-169), не дубль.
    У сироты нет текселей с фото, она красилась бы тоном целого (светлый клин у верха ножки). Нет порога в правилах — части как были; нет МОДУЛЕЙ/правил — ошибка (`load_part_modules`). → (части с плотными номерами, строка для note: '' | '; сирот влито N')."""
    _, PR, PV, _, vote_rules = load_part_modules()
    thr = vote_rules.get('refine', {}).get('orphan_max_area_share')
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
    MP, _, _, rules, _ = load_part_modules()                      # нет модулей/правил — исключение (не «частей нет»), см. load_part_modules
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
        except ImportError:                                       # не хватает модуля внутри разбора — отказ этапа, не тихий откат (T-193/3)
            raise
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
            if from_global[p] and c.get('no_role_global', 'skip') == 'skip' and any(reliable.values()):       # материал неизвестен, своего тона нет: тон ВСЕГО товара — дыра Ш6; хоть одна часть с тоном есть — эту не красим
                out[p] = {'source': 'skip', 'why': 'нет роли и своего тона (известного < min_known) — тон всего товара не берём'}
            else:
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


def smooth_part_rule(role, jump_l, pattern: bool, c: dict, ref_verdict=None) -> bool:
    """Правило «без плитки» (дерево, «ёлочка» на швах): роль части (этап 3) в `smooth_roles`, либо неузорная часть со скачком L на швах плитки jump_L > `quilt_jump_max`."""
    if ref_verdict == 'different':                           # Ш8 (ADR-0459): образец UltraTex показал, что невидимая сторона зоны отличается по свойствам — только тон зоны с фото, рисунок не переносим
        return True
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
                F_, B_ = np.concatenate(fr), np.concatenate(bk)
                a, b = F_.mean(axis=0, keepdims=True), B_.mean(axis=0, keepdims=True)
                r[nm] = round(float(TC.de2000_v(a, b)[0]), 2)
                r['dL_' + nm] = round(float(np.median(B_[:, 0]) - np.median(F_[:, 0])), 2)       # медиана L* зад − перёд (светлее/темнее), единицы L*
            else:
                r[nm] = None
                r['dL_' + nm] = None
        res[p] = r
    return res


def lighter_than_photo_share(after_rgb: np.ndarray, photo_rgb: np.ndarray, mask: np.ndarray, dl: float | None = None, edge_px: int | None = None, grad_thr: float | None = None) -> dict:
    """Пятна «светлее фото» (T-187/1, разбор пятен 06): в кадре камеры 04 внутри силуэта, дальше `edge_px` от края и от перепадов яркости фото, доля пикселей, где итог светлее фото больше чем на `dl` L*.
    Пороги — rules/paint-fill.json `lighter_than_photo`; допустимая доля — thresholds.lighter_than_photo_pct. → {'share_pct', 'inner_px', 'spot_px'}."""
    import cv2
    r = RULES['lighter_than_photo']
    dl, edge_px, grad_thr = float(dl if dl is not None else r['dl']), int(edge_px if edge_px is not None else r['edge_px']), float(grad_thr if grad_thr is not None else r['grad_thr'])
    h_, w_ = np.asarray(photo_rgb).shape[:2]
    La = rgb2lab(np.asarray(after_rgb, np.uint8).reshape(-1, 3))[:, 0].reshape(h_, w_)
    Lp = rgb2lab(np.asarray(photo_rgb, np.uint8).reshape(-1, 3))[:, 0].reshape(h_, w_)
    m = np.asarray(mask, bool)
    dist = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
    gy, gx = np.gradient(cv2.GaussianBlur(Lp.astype(np.float32), (0, 0), 1.5))
    near_edge = cv2.dilate((np.hypot(gx, gy) > grad_thr).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    inner = m & (dist > edge_px) & ~near_edge
    spot = inner & ((La - Lp) > dl)
    return {'share_pct': round(100.0 * float(spot.sum()) / max(int(inner.sum()), 1), 3), 'inner_px': int(inner.sum()), 'spot_px': int(spot.sum())}


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


def front_axis_of_check(chk) -> tuple | None:
    """(ось 0|2, знак) «перёд» формы по азимуту камеры этапа 4 из check.json этапа 6 (`extra.camera.az`): камера смотрит вдоль −(sin az, cos az) в (x, z); перёд — ось с бо́льшей долей, знак — сторона камеры.
    Нет позы → None. Это ТОЛЬКО для автопроверки «перёд на заду» (сверка); источник оси «перёд» для сайта — модуль ориентации (orient_worker)."""
    cam = ((chk or {}).get('extra') or {}).get('camera') or {}
    if 'az' not in cam:
        return None
    a = np.radians(float(cam['az']))
    sx, cz = float(np.sin(a)), float(np.cos(a))
    return (0, 1 if sx >= 0 else -1) if abs(sx) > abs(cz) else (2, 1 if cz >= 0 else -1)


def _center_by_part(v: np.ndarray, lab: np.ndarray, min_n: int) -> np.ndarray:
    """Вычесть среднее по части (T-198/1): остаётся фактура ВНУТРИ части; части с парами < min_n — одной общей группой."""
    out, lab = np.asarray(v, np.float64).copy(), np.asarray(lab).copy()
    u, cnt = np.unique(lab, return_counts=True)
    if (cnt < min_n).any():
        lab[np.isin(lab, u[cnt < min_n])] = -1
    for p in np.unique(lab):
        m = lab == p
        out[m] -= out[m].mean()
    return out


def _lattice_value(rep: dict) -> float:
    """Максимум решётки квилта по ИТОГОВЫМ сборкам всех путей (T-187/6, 23.11): fill-квилт (after, если пересобирали, иначе before), patch, own_panel (после пересборки/фоллбэка плоским)."""
    vals = []
    qp = rep.get('quilt_lattice_pattern') or {}
    for p_, v in (rep.get('quilt_lattice') or {}).items():
        if (qp.get(p_) or qp.get(str(p_)) or {}).get('verdict') == 'pass':          # узорная: решётка в пределах эталона src (период рисунка) — не брак
            continue
        vals.append(float(v.get('after', v.get('before', 0.0))))
    for v in (rep.get('patch_lattice') or {}).values():
        if isinstance(v, dict) and v.get('lattice', v.get('quilt_lattice')) is not None:
            vals.append(float(v.get('lattice', v.get('quilt_lattice'))))      # `lattice` = решётка ИТОГОВОГО образца (одиночный/квилт/гладко = 0)
    vals.append(float((rep.get('own_panel') or {}).get('quilt_lattice_max', 0.0)))
    return round(max(vals), 3) if vals else 0.0


def front_on_back_corr(geoms: list, tex_list: list, front: tuple | None, eps_frac: float = 0.02, min_pairs: int = 200, min_std: float = 2.0, parts: list | None = None, min_part_pairs: int = 30) -> dict:
    """Автопроверка «перёд скопирован на зад» (T-187/6): пары граней ЗАДА и их зеркальных двойников на ПЕРЕДЕ (отражение через центр по оси «перёд»); корреляция яркости текстуры в центрах граней.
    Нормаль берётся без знака (обмотка мешей TRELLIS не согласована), сторона — по положению центра грани. Гладкие (σ < `min_std`) или мало пар — corr None (не измерено).
    `parts` (части граней по геометриям, как в 07) заданы — `corr` считается по ОСТАТКУ после вычитания среднего тона по ключу «пара частей» (часть зад-грани, часть её перёд-двойника), одинаково для обеих сторон: общий порядок
    ровных тонов частей, одинаковых спереди и сзади (подлокотники/сиденье), копией фактуры не считается (T-198/1: диван 16411, по частям PartLLM 0,688 при остатке 0,117), а копия остаётся видна и при разных частях зада и перёда
    (ключ по паре, не по стороне: иначе у зада в одной части идеальная копия давала 0,43); внутри пар гладко (σ остатка < min_std) — не измерено. `raw` — корреляция по яркости целиком.
    `imprint` — справочно: доля разброса яркости зад-граней внутри их части, объяснённая частью перёд-двойника (тон перёда лёг рисунком частей на заднюю часть; при гладком перёде corr None, а это брак) — в гейт не входит.
    → {'corr', 'raw', 'imprint', 'pairs', 'axis', 'mode': 'within_parts'|'raw'}."""
    from scipy.spatial import cKDTree
    if front is None:
        return {'corr': None, 'pairs': 0, 'axis': None, 'why': 'нет позы камеры'}
    axis, sign = front
    Lf, Lb, Pf, Pb = [], [], [], []
    for gi_, (g, tex) in enumerate(zip(geoms, tex_list)):
        V, F, UV = np.asarray(g['V'], np.float64), np.asarray(g['F'], np.int64), np.asarray(g['UV'], np.float64)
        tri = V[F]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1), 1e-30)[:, None]
        cen = tri.mean(1)
        ctr = 0.5 * (V.min(0) + V.max(0))
        half = max(0.5 * float(np.ptp(V[:, axis])), 1e-9)
        pos = (cen[:, axis] - ctr[axis]) * sign
        diag = float(np.linalg.norm(V.max(0) - V.min(0)))
        fr = (np.abs(n[:, axis]) > 0.7) & (pos > 0.6 * half)
        bk = (np.abs(n[:, axis]) > 0.7) & (pos < -0.6 * half)
        if not fr.any() or not bk.any():
            continue
        T = int(np.asarray(tex).shape[0])
        uvc = UV[F].mean(1)
        px = np.clip((uvc[:, 0] * T).astype(int), 0, T - 1)
        py = np.clip(((1.0 - uvc[:, 1]) * T).astype(int), 0, T - 1)
        lum = np.asarray(tex, np.float64)[py, px, :3].mean(1)
        bi, fi = np.flatnonzero(bk), np.flatnonzero(fr)
        refl = cen[bi].copy()
        refl[:, axis] = 2 * ctr[axis] - refl[:, axis]
        d, j = cKDTree(cen[fi]).query(refl, k=1, distance_upper_bound=eps_frac * diag)
        okp = np.isfinite(d)
        Lb.append(lum[bi][okp])
        Lf.append(lum[fi[j[okp]]])
        if parts is not None:
            pa_ = np.asarray(parts[gi_])
            Pb.append(pa_[bi][okp])
            Pf.append(pa_[fi[j[okp]]])
    if not Lb:
        return {'corr': None, 'pairs': 0, 'axis': axis, 'why': 'нет пар зад↔перёд'}
    lb, lf = np.concatenate(Lb), np.concatenate(Lf)
    if len(lb) < min_pairs or lb.std() < min_std or lf.std() < min_std:
        return {'corr': None, 'pairs': int(len(lb)), 'axis': axis, 'why': 'мало пар или гладко'}
    raw = round(float(np.corrcoef(lb, lf)[0, 1]), 3)
    if parts is None:
        return {'corr': raw, 'raw': raw, 'pairs': int(len(lb)), 'axis': axis, 'mode': 'raw'}
    pb_, pf_ = np.concatenate(Pb).astype(np.int64), np.concatenate(Pf).astype(np.int64)
    key = pb_ * (int(max(pb_.max(), pf_.max())) + 2) + pf_                              # пара (часть зада, часть перёда) — общая для обеих сторон
    rb, rf = _center_by_part(lb, key, min_part_pairs), _center_by_part(lf, key, min_part_pairs)
    rb_own = _center_by_part(lb, pb_, min_part_pairs)                                  # зад внутри своей части
    imprint = None
    if rb_own.std() >= min_std:
        imprint = round(float(1.0 - _center_by_part(rb_own, pf_, min_part_pairs).var() / max(rb_own.var(), 1e-12)), 3)
    if rb.std() < min_std or rf.std() < min_std:
        return {'corr': None, 'raw': raw, 'imprint': imprint, 'pairs': int(len(lb)), 'axis': axis, 'mode': 'within_parts', 'why': 'внутри пар частей гладко'}
    return {'corr': round(float(np.corrcoef(rb, rf)[0, 1]), 3), 'raw': raw, 'imprint': imprint, 'pairs': int(len(lb)), 'axis': axis, 'mode': 'within_parts'}


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


def pick_relief_draft(geoms: list, draft_glb: str | None, ut_glb: str | None, source: str | None = None) -> tuple:
    """Источник запасной микрофактуры (trellis_relief, Ш6; владелец 22.11 TG 1640: «с UltraTex, TRELLIS хуже»): правило `trellis_relief.texture_source` (rules/paint-fill.json, ultratex | trellis).
    ultratex — меш UltraTex на НАШЕЙ форме (тот же V, F, UV — `ref_zone.same_mesh`): берутся только яркостные полосы его текстуры, тон остаётся нашим, ворота Ш6 те же; TRELLIS — если UltraTex
    нет, меш другой или правило `trellis`. → (путь черновика | None, 'ultratex' | 'trellis' | None, причина)."""
    src = source or RULES['trellis_relief'].get('texture_source', 'ultratex')
    if src == 'ultratex':
        if not ut_glb or not os.path.isfile(ut_glb):
            return draft_glb, ('trellis' if draft_glb else None), 'UltraTex-меша нет'
        import ref_zone as RZ
        sm = RZ.same_mesh(geoms, TC.load_geoms(ut_glb))
        if sm['same']:
            return ut_glb, 'ultratex', 'тот же меш'
        return draft_glb, ('trellis' if draft_glb else None), 'UltraTex-меш другой: ' + str(sm.get('why'))
    return draft_glb, ('trellis' if draft_glb else None), 'правило texture_source=trellis'


def RZ_same_mesh(a: list, b: list) -> bool:
    import ref_zone as RZ
    return bool(RZ.same_mesh(a, b).get('same'))


def _shrink_layout(step: int, geoms: list, tex_after: list, known: list, ut_g: list | None) -> tuple:
    """Та же раскладка с каждым `step`-м тексельем (UV не меняются — те же места на модели): для пробных заливок ничьей (быстро), результат пробы — только число front_on_back.
    Не массивы текстур (тесты) или step ≤ 1 — без изменений."""
    def ok(a):
        return isinstance(a, np.ndarray) and a.ndim >= 2 and a.shape[0] >= 512 and a.shape[0] % step == 0
    if step <= 1 or not geoms or not all(ok(np.asarray(g['tex'])) if isinstance(g, dict) and 'tex' in g else False for g in geoms):
        return geoms, tex_after, known, ut_g
    sh = lambda a: np.ascontiguousarray(np.asarray(a)[::step, ::step])
    g2 = [dict(g, tex=sh(g['tex'])) for g in geoms]
    u2 = [dict(g, tex=sh(g['tex'])) for g in ut_g] if ut_g is not None else None
    return g2, [sh(t) for t in tex_after], [sh(k) for k in known], u2


def own_panel_tone_hook(geoms: list, tex_after: list, known: list, ut_g: list | None, parts, front: tuple | None = None, thr: float = 0.6) -> tuple:
    """Хук 07 (T-187/6): невидимые панели — донор по оттенку+фактуре UltraTex (тон и куски фото донора) или тон своей зоны + суть UltraTex; чужого квилта нет (ref_zone.own_panel_tone). Сбой не роняет этап."""
    import ref_zone as RZ
    try:
        t_al = time.time()
        ut_al, al = RZ.align_ut(geoms, tex_after, known, ut_g)                # UltraTex → поза фото; нет уверенности — UltraTex не используется (тон своей зоны)
        al['sec_align'] = round(time.time() - t_al, 1)
        out = rep = None
        if al.get('status') == 'tied':                                        # несколько поворотов почти равны: второй ступенью — тот, у кого front_on_back после заливки минимален и ≤ порога
            fb_by, best = {}, None
            mx = int(((RZ.R.get('align') or {}).get('max_ties')) or 2)      # на медленном ядре каждый кандидат = полная заливка: пробуем только лучшие по энергии (T-187/6, зависание >700 с)
            cand = sorted(al['ties'], key=lambda y: -float((al.get('corr') or {}).get(str(y), 0.0)))[:mx]
            al['ties_tried'] = cand
            t_tie = time.time()
            stp = int(((RZ.R.get('align') or {}).get('trial_step')) or 2)     # пробы — на уменьшенной раскладке (в stp² раз быстрее), полная заливка — только победителю
            g_t, ta_t, kn_t, ug_t = _shrink_layout(stp, geoms, tex_after, known, ut_g)
            al['trial_step'] = stp if g_t is not geoms else 1
            for y in cand:
                ut_y, _ = RZ.align_ut(g_t, ta_t, kn_t, ug_t, yaw=y)
                o_y, r_y = RZ.own_panel_tone(g_t, ta_t, kn_t, ut_y, parts)
                c_y = front_on_back_corr(g_t, o_y, front, parts=parts).get('corr')
                fb_by[str(y)] = c_y
                if c_y is not None and c_y <= thr and (best is None or c_y < best[0]):
                    best = (c_y, y, o_y, r_y)
            al['tie_front_on_back'] = fb_by
            al['sec_tie'] = round(time.time() - t_tie, 1)
            if best is not None:
                if g_t is not geoms:                                              # победитель — заново на полной раскладке
                    ut_w, _ = RZ.align_ut(geoms, tex_after, known, ut_g, yaw=best[1])
                    out, rep = RZ.own_panel_tone(geoms, tex_after, known, ut_w, parts)
                else:
                    out, rep = best[2], best[3]
                al.update({'status': 'aligned_by_front_on_back', 'yaw_deg': best[1], 'chosen_front_on_back': best[0]})
            else:
                al.update({'status': 'uncertain', 'yaw_deg': None, 'why': f'{al.get("why")}; front_on_back не ≤ {thr} ни у одного (или не измерен)'})
        if rep is None:
            out, rep = RZ.own_panel_tone(geoms, tex_after, known, ut_al, parts)
        rep['ut_align'] = al
        rep['sec_hook'] = round(time.time() - t_al, 1)
        return out, rep
    except Exception as e:  # noqa: BLE001
        return tex_after, {'error': f'{type(e).__name__}: {e}'}


def top_prior_hook(geoms: list, tex_after: list, known: list, parts, cfg: dict | None, draft_glb: str | None) -> tuple:
    """Хук 07 (T-187/7; канон paint-photo-fill-01 строка 7: «верх — Ш3в»): невидимые тексели ВЕРХА (нормаль вверх, верхний уровень; `top & ~known`) красятся тоном `top_prior`, если его уверенность ≥ порога
    (rules/top-prior.json → stage07.min_confidence), иначе верх остаётся как сделал 07 (донор / тон своей зоны). Идёт ПОСЛЕ own_panel_tone_hook и ДО front_on_back; known не меняется.
    cfg: `top_card` (карточка: класс материала верха, размеры), `top_photo` (фото: контраст узора). Узор — из rules `library_pat` (в репо и в срезе кода Salad). Сбой не роняет этап. → (текстуры, отчёт с `top_source`)."""
    import top_prior as TP                                        # ВНЕ try: нет модуля в срезе кода = отказ этапа, не тихое «как было» (Salad ≠ локально, T-193/4)
    c = cfg or {}
    if not c.get('top_card'):                                     # без карточки класс материала верха неизвестен: не молчаливый as_before, а причина в report.json (счётчик — в итоге пакета stage_trial)
        return tex_after, {'top_source': 'as_before', 'applied': False, 'top_skip': 'no_card', 'gate': 'нет карточки (--card-json): класс материала верха неизвестен'}
    try:
        rules = TP.load_rules()
        if not rules.get('stage07', {}).get('enabled', False):
            return tex_after, {'top_source': 'as_before', 'applied': False, 'top_skip': 'disabled', 'gate': 'stage07.enabled = false'}
        draft = draft_texels(geoms, TC.load_geoms(draft_glb), None) if draft_glb and os.path.isfile(draft_glb) else None
        return TP.stage07(geoms, tex_after, known, parts, c.get('part_role'), draft, c.get('top_card'), c.get('top_photo'), rules)
    except Exception as e:  # noqa: BLE001
        return tex_after, {'top_source': 'as_before', 'applied': False, 'error': f'{type(e).__name__}: {e}'}


def apply_ref_zone_map(geoms: list, tex_after: list, known: list, cfg: dict | None, force: bool = False) -> tuple:
    """Хук Ш8м (за флагом): `texture = different` для (зона, сторона) → невидимые тексели пары теряют фактуру, остаётся тон. Идёт ПОСЛЕ заливки, значит зеркало и trellis_relief
    обойти `different` не могут; фото-тексели (known) не меняются. Флаг выкл. (rules/ref-zone.json) или карты нет — текстуры как были. → (текстуры, {'applied', 'texels_detextured'})."""
    m = (cfg or {}).get('ref_zone_map')
    import ref_zone as RZ
    if not m or not (RZ.APPLY or force):
        return tex_after, {'applied': False, 'texels_detextured': 0, 'flag': bool(RZ.APPLY), 'map': bool(m)}
    out, rep = RZ.apply_to_fill(geoms, tex_after, known, np.asarray(m['face_zone']), np.asarray(m['face_side']), m['map'], m['offs'])
    return out, dict(rep, applied=True, flag=bool(RZ.APPLY))


def _front_back_vals(geoms: list, parts, known: list, kback: list, tex_before: list, tex_x: list, rp: dict) -> tuple:
    """ΔE/ΔL перёд↔зад по частям текстуры tex_x → (de по частям, крупные части bg, худшая ΔE00, худшая |ΔL|). Одна функция на выбор stat/trellis (до хуков) и на итоговую мерку (после хуков)."""
    de_ = part_deltas(geoms, parts, known, kback, tex_before, tex_x)
    kt = max(sum(v['known_texels'] for v in rp['parts'].values()), 1)
    bg = [p for p, v in rp['parts'].items() if v['known_texels'] >= 0.01 * kt]
    da = {int(p): v['after'] for p, v in de_.items() if v['after'] is not None}
    dls = [abs(de_[p]['dL_after']) for p in bg if p in de_ and de_[p].get('dL_after') is not None]
    dlw = max(dls) if dls else None
    dw = max([da[p] for p in bg if p in da] or [None]) if any(p in da for p in bg) else None
    return de_, bg, dw, dlw


def run_stage_once(run: str, sku: str, glb: str, known: list | None = None, parts=None, cfg: dict | None = None, thresholds: dict | None = None, mirror: bool = True, draft_glb: str | None = None, ut_glb: str | None = None, out_name: str | None = None, parts_npz: str | None = None, prev_dir: str | None = None) -> dict:
    """Этап 07 «докрасить невидимое»: GLB (текстура = фото на видимом) → `<run>/<sku>/07-fill/` {filled.glb, report.json, frame.png (az180 до | после), check.json}.
    `known` — маска «видно с камеры фото» по геометриям (нет — из `known_from_photo`: az0/az45); `parts` — части граней (нет — `parts_from_geometry`). Не прошёл (check.json passed=false) — товар дальше не идёт.
    → {'check', 'report', 'geoms', 'tex_before', 'tex_after', 'known', 'parts', 'dir'} (для проб и кадров)."""
    import json
    from PIL import Image
    import paint_stage as PS
    t0 = time.time()
    cpu0 = time.process_time()                                    # мерка времени — процессорные секунды (не зависят от того, сколько ядер дала нода Salad)
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
    relief_src = None
    if (cfg or {}).get('source') in ('trellis', 'trellis_relief'):
        if (cfg or {}).get('source') == 'trellis_relief':
            draft_glb, relief_src, _why = pick_relief_draft(geoms, draft_glb, ut_glb)
        draft = draft_texels(geoms, TC.load_geoms(draft_glb), cfg)
    kback = known_from_photo(geoms, azimuths=(180.0,))
    _to = load_tone_only_png(prev_dir) if (prev_dir and (cfg or {}).get('tone_only_use', True)) else None      # тон-слой этапа 6 (р.8): цвет оставить, фактуру положить поверх

    _cf = load_conf_png(prev_dir) if prev_dir else None                                  # доверие к фото-текселю (этап 6, р.3) — нет файла: запасное от границы известного

    _ut_early = None
    if ut_glb and os.path.isfile(ut_glb) and (cfg or {}).get('source', 'stat') == 'stat':
        _ug0 = TC.load_geoms(ut_glb)
        _ut_early = _ug0 if RZ_same_mesh(geoms, _ug0) else None
    _unobs_fn = (lambda: draft_texels(geoms, _ut_early, cfg)) if _ut_early is not None else None            # UltraTex — на нашей форме: яркостный рельеф для «рисунок не наблюдаем» (T-187/6, 23.11); считается только если такие части есть

    def one(cfg_, draft_):
        r_ = fill(geoms, known, parts, cfg_, mirror, draft_, tone_only=_to, unobs_draft_fn=_unobs_fn if (cfg_ or {}).get('source', 'stat') == 'stat' else None, conf=_cf)
        rp, tx_ = r_['report'], r_['tex']
        de_, bg, dw, dlw = _front_back_vals(geoms, parts, known, kback, tex_before, tx_, rp)
        vals = {'empty_pct': rp['unpainted_after_pct'], 'dE00_front_back': dw, 'dL_front_back': dlw, 'filled_faces_step_pct': rp['steps']['after']['filled_faces_step_pct'], 'far_excess_pct': rp['far_pct']['excess']}
        nfail = sum(0 if PS.judge(vals[k], th[k][0], th[k][1]) else 1 for k in vals)
        return {'finish': r_['finish'], 'keep': r_.get('keep'), 'rep': rp, 'tex': tx_, 'de': de_, 'big': bg, 'de_worst': dw, 'vals': vals, 'nfail': nfail, 'key': (nfail, dw if dw is not None else 99.0, vals['far_excess_pct'] if vals['far_excess_pct'] is not None else 99.0)}
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
    tex_after, rep['ref_zone_map'] = apply_ref_zone_map(geoms, tex_after, known, cfg)
    rep['relief_source'] = relief_src
    ut_g = None
    if ut_glb and os.path.isfile(ut_glb):
        _ug = TC.load_geoms(ut_glb)
        ut_g = _ug if RZ_same_mesh(geoms, _ug) else None
    tex_after, rep['own_panel'] = own_panel_tone_hook(geoms, tex_after, known, ut_g, parts, front_axis_of_check(_chk6), float(th['front_on_back_corr'][1]))
    import ref_zone as RZ
    try:                                                                  # части-близнецы (стул 7733, 23.11): тон из мизерного известного подтягивается к парной части с тем же цветом 06; сбой не роняет этап
        _, rep['sibling_tone'] = RZ.sibling_tone(geoms, tex_before, tex_after, known, parts)             # кандидаты (все пары)
        _cands = [(p['geom'], p['part']) for p in rep['sibling_tone'].get('pairs', [])]
        _acc, _log = [], []
        _cur = tex_after
        _, _, _dw0, _dl0 = _front_back_vals(geoms, parts, known, kback, tex_before, _cur, rep) if _cands else (None, None, None, None)
        for _c in _cands:                                              # страж ПО ПАРЕ: перёд↔зад не должен ухудшиться (локально 23.11: стул 7733, №20) — иначе эта пара откатывается
            _try, _r1 = RZ.sibling_tone(geoms, tex_before, _cur, known, parts, only={_c})
            _, _, _dw1, _dl1 = _front_back_vals(geoms, parts, known, kback, tex_before, _try, rep)
            _bad = (_dw1 is not None and _dw0 is not None and _dw1 > _dw0 + 1.0) or (_dl1 is not None and _dl0 is not None and _dl1 > _dl0 + 1.0)
            _log.append({'geom': _c[0], 'part': _c[1], 'dE00': [_dw0, _dw1], 'dL': [_dl0, _dl1], 'reverted': bool(_bad)})
            if not _bad:
                _cur, _dw0, _dl0 = _try, _dw1, _dl1
                _acc.append(_c)
        tex_sib = _cur
        rep['sibling_tone']['accepted'] = [list(c) for c in _acc]
        rep['sibling_tone']['guard'] = _log
        rep['sibling_tone']['texels_changed'] = int(sum(p['texels'] for p in rep['sibling_tone'].get('pairs', []) if (p['geom'], p['part']) in set(_acc)))
        _tp, _ps = RZ.panel_sibling_tone(geoms, tex_before, tex_sib, known, parts)
        if _ps.get('texels_changed'):
            _, _, _dwa, _dla = _front_back_vals(geoms, parts, known, kback, tex_before, tex_sib, rep)
            _, _, _dwb, _dlb = _front_back_vals(geoms, parts, known, kback, tex_before, _tp, rep)
            _pbad = (_dwb is not None and _dwa is not None and _dwb > _dwa + 1.0) or (_dlb is not None and _dla is not None and _dlb > _dla + 1.0)
            _ps['reverted'] = bool(_pbad)
            if not _pbad:
                tex_sib = _tp
        rep['sibling_tone']['panels_in_part'] = _ps
        tex_after = tex_sib
    except Exception as e:  # noqa: BLE001
        rep['sibling_tone'] = {'error': f'{type(e).__name__}: {e}'}
    try:                                                                  # подчасть по цвету 06 (Б, 23.11): мелкие невидимые панели со своим тоном; сбой не роняет этап
        tex_after, rep['sub_tone'] = RZ.sub_tone(geoms, tex_before, tex_after, known, parts)
    except Exception as e:  # noqa: BLE001
        rep['sub_tone'] = {'error': f'{type(e).__name__}: {e}'}
    tex_after, rep['top_prior'] = top_prior_hook(geoms, tex_after, known, parts, cfg, None if relief_src == 'ultratex' else draft_glb)
    rep['top_source'] = rep['top_prior'].get('top_source')
    rep['metrics_pre_hook'] = {k: pick['vals'].get(k) for k in ('empty_pct', 'dE00_front_back', 'dL_front_back', 'filled_faces_step_pct', 'far_excess_pct')}     # что было бы до хуков (для сравнения; на passed не влияет)
    pick['finish'](tex_after)                                          # мерки — по ИТОГОВОЙ текстуре (после ref_zone_map, own_panel, top_prior), не по текстуре до хуков
    de, big, de_worst, _dlw = _front_back_vals(geoms, parts, known, kback, tex_before, tex_after, rep)
    pick['vals'] = dict(pick['vals'], empty_pct=rep['unpainted_after_pct'], dE00_front_back=de_worst, dL_front_back=_dlw, filled_faces_step_pct=rep['steps']['after']['filled_faces_step_pct'], far_excess_pct=rep['far_pct']['excess'])
    rep['front_on_back'] = front_on_back_corr(geoms, tex_after, front_axis_of_check(_chk6), parts=parts)
    rep['front_on_back_raw'] = rep['front_on_back'].get('raw')                      # старая мера (по яркости целиком) — для сравнения (T-198/1)
    kchg = known_changed_share(pick.get('keep') or known, tex_before, tex_after, RULES['known_change_de'])
    rep['known_changed'] = kchg
    try:                                                          # мерка узора — только отчёт (порог по трудным — позже), сбой её не роняет этап
        rep['pattern_metric'] = pattern_metrics(geoms, parts, known, tex_after, rep, dict(FILL, **(cfg or {})))
    except Exception as e:  # noqa: BLE001
        rep['pattern_metric'] = {'error': f'{type(e).__name__}: {e}'}
    rep['source_used'], rep['source_tried'] = used, tried
    rep['pr_camera'] = cam_note
    write_glb(geoms, tex_after, os.path.join(d, 'filled.glb'))
    sides = side_azimuths(geoms, known)                        # зад — сторона без фото по known (не фиксированный 180: формы лежат передом в разные стороны)
    rep['frame_sides'] = sides
    for _az, _nm in ((sides['back'], PS.FRAME), (sides['photo'], 'frame-photo.png')):
        a = render_ortho(geoms, tex_before, _az)
        b = render_ortho(geoms, tex_after, _az)
        Image.fromarray(np.concatenate([a, np.full((a.shape[0], 12, 3), 255, np.uint8), b], axis=1)).save(os.path.join(d, _nm))
    secs = time.time() - t0
    cpu_s = time.process_time() - cpu0
    rep['wall_s'], rep['cpu_s'] = round(secs, 1), round(cpu_s, 1)           # wall_s — только отчёт (на passed не влияет)
    metrics = {
        'empty_pct': {'value': rep['unpainted_after_pct'], 'threshold': th['empty_pct'][1], 'op': th['empty_pct'][0]},
        'dE00_front_back': {'value': de_worst, 'threshold': th['dE00_front_back'][1], 'op': th['dE00_front_back'][0]},
        'dL_front_back': {'value': pick['vals']['dL_front_back'], 'threshold': th['dL_front_back'][1], 'op': th['dL_front_back'][0]},
        'filled_faces_step_pct': {'value': rep['steps']['after']['filled_faces_step_pct'], 'threshold': th['filled_faces_step_pct'][1], 'op': th['filled_faces_step_pct'][0]},
        'far_excess_pct': {'value': rep['far_pct']['excess'], 'threshold': th['far_excess_pct'][1], 'op': th['far_excess_pct'][0]},
        'known_changed_share_pct': {'value': kchg['share_pct'], 'threshold': th['known_changed_share_pct'][1], 'op': th['known_changed_share_pct'][0]},
        'pool_rejected_pct': {'value': round(100.0 * max(rep.get('quilt_rejected_share', {}).values(), default=0.0), 1), 'threshold': th['pool_rejected_pct'][1], 'op': th['pool_rejected_pct'][0]},     # мягкий провал: больше половины пула блоков отбраковано правилом — образец беден, запасной режим (плитка) вместо квилта
        'cpu_s': {'value': round(cpu_s, 1), 'threshold': th['cpu_s'][1], 'op': th['cpu_s'][0]},
        'quilt_lattice_max': {'value': _lattice_value(rep), 'threshold': th['quilt_lattice_max'][1], 'op': th['quilt_lattice_max'][0]},        # решётка плитки на каждой залитой зоне (T-187/6, 23.11): fill-квилт, patch, own_panel; провал — гуще/плоско
        'front_on_back_corr': {'value': rep['front_on_back']['corr'], 'threshold': th['front_on_back_corr'][1], 'op': th['front_on_back_corr'][0]},      # перёд на заду (T-187/6): не измерено (None) — не провал
    }
    for k_, m in metrics.items():
        m['ok'] = True if (k_ == 'front_on_back_corr' and m['value'] is None) else PS.judge(m['value'], m['op'], m['threshold'])
    if draft is not None:
        rep['draft_transfer'] = draft['report']
    report = {'report': rep, 'deltaE_by_part': de, 'big_parts': big, 'parts_note': parts_note, 'part_class_note': pc_note, 'empty_before_pct': rep['unpainted_before_pct']}
    with open(os.path.join(d, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    check = PS.write_check(d, out_name or STAGE, sku, None, dict(metrics['empty_pct'], name='empty_pct'), '', metrics={k: v for k, v in metrics.items() if k != 'empty_pct'}, seconds=secs,
                           outputs=['filled.glb', 'report.json'], frame=PS.FRAME, known_pct=rep['known_pct'], mirrored_pct=rep['mirrored_pct'], empty_before_pct=rep['unpainted_before_pct'], empty_by_view=rep['unpainted_by_view'], steps=rep['steps'], parts=parts_note, source_used=used, source_tried=tried, pattern_metric=rep['pattern_metric'], pattern_src=rep.get('pattern_src'), stage6=s6, quilt_rejected=rep.get('quilt_rejected'))
    return {'check': check, 'report': rep, 'geoms': geoms, 'tex_before': tex_before, 'tex_after': tex_after, 'known': known, 'parts': parts, 'dir': d, 'deltaE': de, 'kback': kback}


def _zones_stamp(d: str, used: str, why: str | None, tried: dict | None = None, total_s: float | None = None) -> None:
    """Дописать в report.json источник зон: zones_used (parts|panels), zones_reason, zones_parts_try (мерки прогона по частям, если откатились), zones_total_s."""
    import json
    fp = os.path.join(d, 'report.json')
    if not os.path.isfile(fp):
        return
    with open(fp, encoding='utf-8') as f:
        doc = json.load(f)
    doc.update({'zones_used': used, 'zones_reason': why})
    if tried is not None:
        doc['zones_parts_try'] = tried
    if total_s is not None:
        doc['zones_total_s'] = round(total_s, 1)
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def run_stage(*args, fallback: bool = True, **kw) -> dict:
    """Этап 07 с откатом зон (T-198/1): заливка по частям PartLLM (`parts_npz` задан), и если провалена мерка из rules/paint-fill.json `zones_fallback` (перёд на заду) — тот же этап
    сразу заливает заново по панелям (`parts_npz=None`) и оставляет этот вариант. Остальное — как `run_stage_once`. `fallback=False` — без отката (пробы). Источник зон — в report.json (`zones_used`).
    Отказ этапа 6, `parts`/`parts_npz` не заданы — без изменений (панели и так). Время этапа в check.json — последнего прогона; сумма — `zones_total_s`."""
    import shutil
    t0 = time.time()
    r = run_stage_once(*args, **kw)
    names = list(RULES.get('zones_fallback') or [])
    if r.get('refused') or not (kw.get('parts_npz') and kw.get('parts') is None):
        return r
    chk = r.get('check') or {}
    mets = chk.get('metrics') or {}
    bad = [k for k in names if (mets.get(k) or {}).get('ok') is False] if fallback else []
    if not bad:
        _zones_stamp(r['dir'], 'parts', None if fallback else 'без отката (fallback=False)')
        return r
    d = r['dir']
    tried = {k: {'value': (mets.get(k) or {}).get('value'), 'threshold': (mets.get(k) or {}).get('threshold'), 'ok': (mets.get(k) or {}).get('ok')} for k in names}
    tried['seconds'] = chk.get('seconds')
    for src, dst in (('check.json', 'check-parts.json'), ('frame.png', 'frame-parts.png')):
        if os.path.isfile(os.path.join(d, src)):
            shutil.copyfile(os.path.join(d, src), os.path.join(d, dst))
    r2 = run_stage_once(*args, **dict(kw, parts_npz=None))
    mets2 = ((r2.get('check') or {}).get('metrics')) or {}
    still = [k for k in bad if (mets2.get(k) or {}).get('ok') is False]
    why = ('по частям провал: ' + ', '.join(f"{k} {tried[k]['value']} против порога {tried[k]['threshold']}" for k in bad) + '; по панелям: ' + ', '.join(f"{k} {(mets2.get(k) or {}).get('value')}" for k in bad)
           + (' — и панели не проходят (оставлены панели как основа)' if still else ' — проходят'))
    _zones_stamp(r2['dir'], 'panels', why, tried, time.time() - t0)
    return r2


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


def load_conf_png(visible: str) -> list | None:
    """Доверие к фото-текселю этапа 6 (р.3, T-194/1): `conf.png`, `conf1.png`, … — uint8 = доверие×255, 0 где не известно. Нет файла — None (сведение шва берёт запасное)."""
    from PIL import Image
    out = []
    for i in range(64):
        fp = os.path.join(visible, "conf.png" if i == 0 else f"conf{i}.png")
        if not os.path.exists(fp):
            break
        out.append(np.asarray(Image.open(fp).convert("L"), np.float32) / 255.0)
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
    ap.add_argument("--ut-glb", default=None, help="UltraTex-меш на НАШЕЙ форме (тот же V, F): донор невидимых панелей по оттенку и фактуре; нет — тон своей зоны")
    ap.add_argument("--card-json", default=None, help="карточка товара: файл JSON или сам JSON ({role, name, <характеристики>}): класс материала верха для top_prior (нет — без слова карточки)")
    ap.add_argument("--photo", default=None, help="фото каталога (RGBA/белый фон): контраст узора верха; нет — запасной коэффициент")
    a = ap.parse_args(argv)
    base = os.path.join(a.run, PS.safe_name(a.sku))
    visible = a.visible or os.path.join(base, "06-visible")
    if a.no_parts_npz and a.parts_npz:
        ap.error("--parts-npz и --no-parts-npz вместе нельзя")
    default_npz = os.path.join(base, "03-parts", "parts.npz")
    zones_from = RULES.get("zones_from", "parts")                                  # rules/paint-fill.json: parts (части этапа 3, если есть) | panels (только панели формы) — T-198/1
    if zones_from not in ("parts", "panels"):
        ap.error(f"rules/paint-fill.json: zones_from={zones_from!r}, ожидалось parts или panels")
    parts_npz = None if (a.no_parts_npz or (zones_from == "panels" and not a.parts_npz)) else (a.parts_npz or (default_npz if os.path.exists(default_npz) else None))      # --no-parts-npz: этап 3 отказал — parts.npz не брать, части по геометрии (+ сироты); явный --parts-npz сильнее флага
    cfg = dict({"erode_known": 0}, **(json.loads(a.cfg) if a.cfg else {}))      # вход этапа 6: маска «взято с фото» уже честная
    if a.card_json:
        cfg["top_card"] = json.load(open(a.card_json, encoding="utf-8")) if os.path.isfile(a.card_json) else json.loads(a.card_json)      # путь к файлу (на Salad — @in/card.json) или сам JSON
    if a.photo:
        cfg["top_photo"] = a.photo
    try:
        r = run_stage(a.run, a.sku, os.path.join(visible, "visible.glb"), known=load_known_png(visible) or None, cfg=cfg, mirror=not a.no_mirror, ut_glb=a.ut_glb, parts_npz=parts_npz, prev_dir=visible)
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
