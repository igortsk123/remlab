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
  known_visible_share — доля пикселей силуэта растра с z-буфером (то, что камера видит истинно), чей тексель взят с фото (T-215: ниже порога — нечего переносить);
                   прежняя `known_share` (доля занятых ТЕКСЕЛЕЙ всей развёртки, включая зад и невидимое) остаётся справочной мерой без порога — зад в знаменателе делал порог ложным;
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
import vertex_normals as VNM  # noqa: E402      # нормали вершин для NORMAL в GLB (T-20261124-10/4)
import paint_stage as PS  # noqa: E402
import front_axis as FA  # noqa: E402       # общий свидетель «перёда» (T-21/2): доли известного по сторонам; нет модуля — ошибка импорта, не молчание
import back_panel_stage as BPS  # noqa: E402    # зад корпусной после переноса (T-43/❓2): тип по паспорту, камера и фото-сторона из этого же выхода
import crease_mask as CM  # noqa: E402     # мерки полос у изломов и карта уверенности текселя (T-194/1, T-194/2); текстуру не меняет
import shadow_leak as SLK  # noqa: E402     # R-SHADOW-LEAK (T-20261124-15): тень щели в известном — мерка всегда для мягкого, лечение по rules/tex-visible.json shadow_leak.enabled
import mesh_type_passports as MTP  # noqa: E402   # роль → семья типа (мягкое/корпусное/…) для допуска правила

def _rules() -> dict:
    try:
        return json.load(open(os.path.join(SCOUT, 'rules', 'tex-visible.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return {}


R = _rules()
SLK_ON = bool(int(os.environ['SHADOW_LEAK'])) if 'SHADOW_LEAK' in os.environ else None       # env 1/0 — проба «включено/выключено» поверх rules; нет — из rules/tex-visible.json shadow_leak.enabled
COS_MIN = float(R.get('cos_min', 0.40))          # cos угла к лучу: 66° и больше — вскользь, не берём (rules/tex-visible.json)
DEPTH_JUMP = float(R.get('depth_jump_px', 12.0))  # разрыв глубины между соседними пикселями кадра больше стольких px_len — край складки/щели: полоса вокруг не берётся
MM_GAP = float(R.get('multi_material_gap_L', 25.0))      # бимодальный L* внутри части → мерка перёд↔бок N/A
MM_SHARE = float(R.get('multi_material_min_share', 0.20))
EDGE_BG_PX = float(os.environ.get('EDGE_BG_PX', R.get('edge_bg_reject_px', 8.0)))   # 0 — правило выкл.
EDGE_BG_MEASURE = float(R.get('edge_bg_measure_px', 6.0))
EDGE_BG_DL = float(R.get('edge_bg_dL', 6.0))
EDGE_BG_LOCAL = os.environ.get('EDGE_BG_LOCAL', str(R.get('edge_bg_local', False))).lower() in ('1', 'true', 'yes')   # T-20261124-10/2: опора каймы — цвет БЛИЖАЙШЕГО ядра, а не одна медиана на товар
EDGE_BG_INWARD = os.environ.get('EDGE_BG_INWARD', str(R.get('edge_bg_inward', False))).lower() in ('1', 'true', 'yes')   # T-85 хвост (вариант В): опора каймы — цвет товара на INWARD_LO..INWARD_HI px вглубь от края фото (кайма вырезки тоньше, чем рама/ножка/кант), не медиана и не роль
EDGE_BG_REACH = float(R.get('edge_bg_reject_px', 8.0))   # T-85/В: под флагом inward мерка смотрит только на пиксели ≤ этого от края фото (кайма вырезки по определению у края; светлая деталь глубже — не кайма)
INWARD_LO, INWARD_HI = float(R.get('edge_bg_inward_lo_px', 8.0)), float(R.get('edge_bg_inward_hi_px', 14.0))
EDGE_BG_REF_SIGMA = float(R.get('edge_bg_ref_sigma_px', 6.0))     # сглаживание опорного цвета ядра (px кадра)
EDGE_BG_WHITE_L = float(R.get('edge_bg_white_L', 90.0))   # медиана ядра светлее — ткань белая, мерка и правило каймы слепы (N/A)
FRAYED_PX = int(R.get('frayed_px', 3))           # рваность: известный пиксель в этих px от неизвестного внутри силуэта
DEPTH_MED = int(R.get('depth_median_px', 7))   # медиана карты глубины перед поиском разрыва: на рёбрах треугольников в ней пятна-выбросы
DEPTH_BAND = int(R.get('depth_band_px', 2))      # ширина этой полосы, пикселей кадра
COS_FULL = float(R.get('cos_full', 0.60))         # полный вес с этого косинуса; между COS_MIN и COS_FULL — плавная передача заготовке
EDGE_FRAC = 4.0 / 480   # отступ от силуэта фото внутрь, доли стороны кадра: вес растёт от 0 до 1 (там фон и ореол)
GUTTER = 6              # желоб вокруг островков, пикселей текстуры (билинейная выборка у шва не берёт серый фон)
EDGE_ERODE = float(R.get('edge_erode_px', 2.0))        # жёсткая эрозия маски фото: пиксели ближе к краю силуэта не берутся совсем (там белый фон и ореол; директор 21.11)
W_TAKE = 0.25           # вес меньше — тексель не берём (остаётся прежним), вес выше — цвет фото целиком, без подмеса светлой заготовки (иначе светлые полосы на вскользь видимых краях)
HOLE_R = 2.5            # дыры между взятыми текселями (пикселей кадра реже текселей) закрываются ближайшим взятым не дальше этого, текселей
DEPTH_PX = 3.0          # допуск «тексель не заслонён»: расхождение глубины точки и буфера глубины камеры не больше стольких пикселей предмета (у косых граней — шире)
TONE_ON = bool(int(os.environ['TEX_VISIBLE_TONE'])) if 'TEX_VISIBLE_TONE' in os.environ else bool(R.get('tone_oblique', True))   # Ш3б: тон с острого угла (rules/tex-visible.json, _tone_doc); env 0 — контрольный прогон «без тона»
TONE_COS_MIN = float(R.get('tone_cos_min', 0.08))           # острее — луч почти вдоль поверхности, наблюдение ничего не стоит
TONE_WL = float(R.get('tone_wl', 0.3))                      # доверие наблюдению: светлота слабо (косой свет, тень) …
TONE_WC = float(R.get('tone_wc', 0.8))                      # … цветность сильно (это доверие ВДАЛИ от наблюдавшихся граней)
TONE_NEAR_FRAC = float(R.get('tone_near_frac', 0.05))       # у самой наблюдавшейся грани доверие 1,0 (фото — истина на этих пикселях), к этой доле габарита по поверхности спадает до tone_wl / tone_wc
TONE_SMOOTH_ITERS = int(R.get('tone_smooth_iters', 12))    # сглаживание поля Δ по поверхности (шагов графа граней)
TONE_REF_ITERS = int(R.get('tone_ref_iters', 12))           # сглаживание опорного цвета (известное рядом) по поверхности
TONE_DIST_W = float(R.get('tone_dist_weight', 0.15))        # цена шага по поверхности: доля расстояния между центрами граней …
TONE_SRC_COS = float(os.environ['TONE_SRC_COS']) if 'TONE_SRC_COS' in os.environ else float(R.get('tone_src_cos_min', 0.7))   # грань красится тоном, только если cos(её нормаль, нормаль наблюдавшейся грани-источника) не ниже порога (~45°); 0 = выкл.
TONE_CREASE_W = float(R.get('tone_crease_weight', 0.25))    # … плюс доля габарита × (1 − cos угла между нормалями соседних граней): излом дорог, плоскость почти бесплатна
TONE_REACH_FRAC = float(R.get('tone_reach_frac', 0.3))     # тон растекается от наблюдавшейся грани не дальше доли габарита формы (по поверхности)
TONE_SKIP_DROPPED = bool(int(os.environ['TEX_VISIBLE_TONE_DROP'])) if 'TEX_VISIBLE_TONE_DROP' in os.environ else bool(R.get('tone_skip_dropped', True))   # грань, наблюдавшаяся, но отброшенная по ΔE (другой материал/блик), соседским тоном не красится
TONE_MAX_DE = float(R.get('tone_max_de', 20.0))             # ΔE00(наблюдение, опора) больше — другой материал или блик: не красим
TONE_PLANE_REF = bool(int(os.environ['TEX_VISIBLE_TONE_PLANE_REF'])) if 'TEX_VISIBLE_TONE_PLANE_REF' in os.environ else bool(R.get('tone_plane_ref', False))   # T-20261124-27: опора тона — местное поле наблюдений САМОЙ плоскости, не ближайшая известная грань (кромка); выкл. = как было
TONE_PLANE_ANGLE = float(R.get('tone_plane_angle_deg', 8.0))        # грань — в плоскости, если её нормаль ≤ этого угла от нормали-якоря плоскости (не цепочкой от соседа)
TONE_PLANE_MIN_FACES = int(R.get('tone_plane_min_faces', 20))         # меньше граней с одной нормалью — не плоскость (шум сетки)
TONE_PLANE_MIN_OBS = int(R.get('tone_plane_min_obs_px', 200))       # меньше наблюдений в плоскости — опора по-старому (ближайшее известное)
TONE_PLANE_UNIMODAL = float(R.get('tone_plane_unimodal_share', 0.8))   # плоскость «одногорбая», если ≥ этой доли наблюдённых граней в TONE_MAX_DE от её медианы; иначе (ёлочка/мрамор/два цвета) отсев по ΔE не делаем
TONE_GLARE = bool(int(os.environ['TEX_VISIBLE_TONE_GLARE'])) if 'TEX_VISIBLE_TONE_GLARE' in os.environ else bool(R.get('tone_glare', False))   # T-20261124-27: БЛИК глянца (светлое, почти без цвета на плоскости цветного корпуса) красится прежней опорой (Δ 0), а не запекается в текстуру; действует только вместе с tone_plane_ref
TONE_GLARE_MIN_DL = float(R.get('tone_glare_min_dL', 8.0))              # (а) грань светлее прежней опоры не меньше чем на столько L
TONE_GLARE_C_RATIO = float(R.get('tone_glare_c_ratio', 0.25))           # (а) цветность грани C ≤ этой доли C опоры (перед/бок/кромка согласны)
TONE_GLARE_MIN_REF_C = float(R.get('tone_glare_min_ref_c', 30.0))       # (а) блик ищем только на цветном корпусе: C опоры ≥ этого (белое/серое не блик)
TONE_GLARE_CORR_MAX = float(R.get('tone_glare_corr_max', -0.3))         # (б) в плоскости L растёт — C падает: взвешенная корреляция(L, C) по наблюдённым граням ≤ этого
TONE_GLARE_MIN_FACES = int(R.get('tone_glare_min_faces_corr', 6))       # (б) считается при ≥ стольких наблюдённых гранях плоскости; меньше — голос не подан
TONE_OWN_N0 = float(os.environ['TEX_VISIBLE_TONE_OWN_N0']) if 'TEX_VISIBLE_TONE_OWN_N0' in os.environ else float(R.get('tone_own_n0', 0.0))   # T-20261124-27 (шум Киннера): вес собственного наблюдения грани a = n/(n+N0), n — её пиксели; остальное — сглаженное Δ соседей; 0 = как было (a = 1); действует при tone_plane_ref
TONE_PLANE_ITERS = int(R.get('tone_plane_iters', 12))               # сглаживание поля наблюдений плоскости (шагов графа граней внутри плоскости)
TONE_MIN_OBS = int(R.get('tone_min_obs_px', 30))            # меньше наблюдений в геометрии — тона нет
ISL = R.get('island_edge') or {}                              # T-20261124-05: тон у границы острова, тонкая щель целиком, верх по моде (rules/tex-visible.json § island_edge)
ISL_ON = bool(int(os.environ['TEX_VISIBLE_ISLAND'])) if 'TEX_VISIBLE_ISLAND' in os.environ else bool(ISL.get('enabled', False))   # env 1/0 — проба / контроль
ISL_TONE, ISL_LINE, ISL_TOP, ISL_JUMP = (ISL.get(k) or {} for k in ('edge_tone', 'line_close', 'top_mode', 'jump'))
ZBUF_ON = bool(int(os.environ['TEX_VISIBLE_ZBUF'])) if 'TEX_VISIBLE_ZBUF' in os.environ else bool(R.get('z_buffer', True))   # z-буфер видимости (T-201); env 0 — контрольный прогон «как было»
ZBUF_TOL = float(os.environ.get('TEX_VISIBLE_ZBUF_TOL', R.get('z_buffer_tol_px', 3.0)))                 # грань растра этапа 4 дальше ближайшей в пикселе больше чем на столько px предмета — растр ошибся (рисует без z-буфера), в пикселе видна ближайшая
ZBUF_GEOM_TOL = float(R.get('z_buffer_geom_tol_px', 2.0))          # страховка «форма та же, что у камеры»: на пикселях, где растр и z-буфер назвали одну грань, глубины расходятся не больше (медиана, px предмета)
ZBUF_MIN_COVER = float(R.get('z_buffer_min_cover', 0.5))           # … и z-буфер покрывает не меньше этой доли силуэта растра
ZDEPTH_ALL = bool(int(os.environ['TEX_VISIBLE_ZDEPTH_ALL'])) if 'TEX_VISIBLE_ZDEPTH_ALL' in os.environ else bool(R.get('z_buffer_depth_all', False))   # T-20261124-27 (Крит): глубина этапа 4 (depth.npz) на косых гранях — мусор; там, где z-буфер покрыл пиксель, глубина берётся из него (rules/tex-visible.json § _zdepth_doc); env 1/0 — проба / контроль
DEPTH_TILT = bool(int(os.environ['TEX_VISIBLE_DEPTH_TILT'])) if 'TEX_VISIBLE_DEPTH_TILT' in os.environ else bool(R.get('depth_band_tilt', False))   # порог разрыва глубины растёт на ожидаемый шаг плоскости px_len·tgθ (при cos < ~0,09 плоскость сама «разрыв»); отдельный флаг от zbuffer_depth_all
BACK_ON = bool(int(os.environ['TEX_VISIBLE_BACK'])) if 'TEX_VISIBLE_BACK' in os.environ else bool(R.get('back_cull', True))
ZBUF_BACK = bool(int(os.environ['TEX_VISIBLE_ZBUF_BACK'])) if 'TEX_VISIBLE_ZBUF_BACK' in os.environ else bool(R.get('z_buffer_replace_back', True))   # ничья по глубине: грань спиной к камере уступает ближайшей (знаковая нормаль — вторичный признак при z-буфере)
PRUNE_ON = bool(int(os.environ['TEX_VISIBLE_PRUNE'])) if 'TEX_VISIBLE_PRUNE' in os.environ else bool(R.get('back_prune_panels', True))
BACK_WINDING_MIN =float(R.get('back_winding_min', 0.95))           # знаковую нормаль грани берём, только если обход граней сетки согласован (доля парных рёбер с противоположными направлениями) и объём положителен
BACK_CREASE_DEG = float(R.get('back_panel_crease_deg', 15.0))       # панель = связная по рёбрам группа граней с изломом между соседями не больше этого
BACK_MIN_SHARE = float(R.get('back_panel_min_known_share', 0.05))   # на крупной панели с долей известного с фото меньше этой известное снимается (страховка; 07 красит панель тоном своей зоны)
BACK_MIN_OCC = float(R.get('back_panel_min_occ_share', 0.01))       # «крупная» панель: не меньше этой доли занятых текселей геометрии (мелкие панели рельефа/обивки не трогаем)
PROV = {'direct': 1, 'splat': 2, 'hole': 3, 'synth': 4}     # провенанс known (карта prov.png), 0 — не известно
GREY = 128
REG_FIT = bool(int(os.environ['TEX_VISIBLE_REG'])) if 'TEX_VISIBLE_REG' in os.environ else bool(R.get('reg_fit', True))   # env 0 — контрольный прогон без подгонки; умолчание — из rules               # подгонка сдвига регистрации по силуэту (T-197/2)
REG_MAX_PX = float(R.get('reg_max_shift_px', 3.0))      # дальше этого сдвиг не ищем и не берём (больше — другая беда: форма/камера, не подпиксель)
REG_SIGMA = float(R.get('reg_sigma_px', 1.0))           # размытие маски и альфы перед сравнением: гладкая цель → подпиксельный минимум
REG_MIN_GAIN = float(R.get('reg_min_gain', 0.10))       # сдвиг принят, если невязка силуэта упала не менее чем на эту долю (на боевых силуэт искажён формой: слабые подгонки шумны)
PHOTO_INTERP = str(R.get('photo_interp', 'lanczos'))   # перевод фото в кадр: lanczos (T-197: линейная теряла ~⅓ мелкого контраста при растяжке фото ×2) | cubic | linear
SAMPLE_ORDER = int(R.get('sample_order', 3))             # выборка цвета в тексель из кадра: порядок сплайна (3 — бикубика; 1 — билинейная, теряла 15–40 % мелкого контраста; T-197)
FRONT_COS = 0.80       # мерка света «перёд↔бок»: перёд — cos ≥ этого, бок — от cos_min до SIDE_COS
SIDE_COS = 0.65
def _gate(r: dict) -> dict:
    """Пороги гейта — только из rules/tex-visible.json `gate` (T-20261123-19/1: числа не в коде). Нет раздела или мерки — ошибка: нет порога ≠ «прошло»."""
    g = r.get('gate')
    need = ('silhouette_iou', 'known_visible_share', 'edge_corr', 'lab_dE', 'edge_bg_share')
    if not isinstance(g, dict) or any(k not in g for k in need):
        raise RuntimeError(f"rules/tex-visible.json: нет раздела gate с порогами {need}")
    return {k: (float(g[k][0]), str(g[k][1])) for k in need}


GATE = _gate(R)         # (порог, op) — провизорно, см. шапку


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
        out.append({'name': name, 'V': np.asarray(g.vertices, np.float64), 'F': np.asarray(g.faces, np.int64), 'UV': np.asarray(uv, np.float64), 'tex': tex, 'has_tex': im is not None, 'VN': VNM.file_normals(g)})
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
    """Цвет «как фон вырезки»: ближе к белому, чем к цвету ткани (опора), и светлее ткани на EDGE_BG_DL L*. Опора med — один цвет (3,) или по пикселю (H,W,3: local_reference)."""
    white = _lab(np.full((1, 1, 3), 255, np.uint8))[0, 0]
    med = np.asarray(med)
    if med.ndim == 1:
        return (_de(lab, white) < _de(lab, med)) & (lab[..., 0] > med[0] + EDGE_BG_DL)
    flat, mflat = lab.reshape(-1, 3), med.reshape(-1, 3)
    import recolor_lp as LP
    d_ref = LP.de2000(flat, np.asarray(mflat, np.float64)).reshape(lab.shape[:-1])
    return (_de(lab, white) < d_ref) & (lab[..., 0] > med[..., 0] + EDGE_BG_DL)


def core_median(st: dict, prgb: np.ndarray, pmask: np.ndarray) -> np.ndarray:
    """Цвет ткани по фото: медиана Lab пикселей прямо к камере (cos >= 0.8), глубже 12 px от края фото и силуэта растра."""
    from scipy.ndimage import distance_transform_edt
    core = st['mask'] & pmask & (st['cos'] >= 0.8) & (distance_transform_edt(pmask) > 12) & (distance_transform_edt(st['mask']) > 12)
    if core.sum() < 100:
        core = st['mask'] & pmask & (st['cos'] >= TV_FALLBACK_COS)
    return np.median(_lab(prgb)[core], axis=0)


TV_FALLBACK_COS = 0.5


_INWARD_REP: dict = {}


def inward_reference(st: dict, prgb: np.ndarray, pmask: np.ndarray) -> np.ndarray:
    """Lab-опора по пикселю (H,W,3): сглаженный цвет БЛИЖАЙШЕГО пикселя «кольца вглубь» — товара на lo..lo+span px от края альфы фото (внутри силуэта растра), span = INWARD_HI − INWARD_LO.
    Светлая кайма вырезки (1–3 px) сравнивается с тканью сразу под ней; светлое дерево рамы/кромки шире каймы — с самим собой. ТОНКИЕ ЧАСТИ (ножка, рейка) и чужие стороны: кольцо
    принимается, только если ОТРЕЗОК от пикселя до пикселя кольца целиком лежит внутри маски фото (линия видимости: через белый зазор, фон или другую сторону кольцо не берётся) и не дальше
    2×INWARD_HI px; нет — следующая ступень глубины lo → 5 → 3 px (кольцо ложится внутри ЭТОЙ части); нет и ступени — запасной путь: медиана ядра товара (core_median). Что и сколько ушло
    в запасной путь и почему — `_INWARD_REP` → check.json `edge_bg_inward`."""
    from scipy.ndimage import distance_transform_edt, gaussian_filter, maximum_filter
    dp = distance_transform_edt(pmask)
    loc = maximum_filter(dp, size=int(2 * INWARD_HI) + 1)               # локальная полуширина части (только отчёт и быстрый отсев: решает линия видимости)
    lab = _lab(prgb).astype(np.float32)
    sg = max(EDGE_BG_REF_SIGMA, 0.5)
    span = INWARD_HI - INWARD_LO
    ref = np.broadcast_to(core_median(st, prgb, pmask), prgb.shape).astype(np.float32).copy()
    todo = st['mask'] & pmask
    rep = {'tiers': [], 'fallback_px': 0, 'fallback_why': {}}
    ts = np.linspace(0.0, 1.0, 17)[1:]
    for lo in (INWARD_LO, 5.0, 3.0):
        ring = st['mask'] & pmask & (dp > lo) & (dp <= lo + span)
        use = todo & (loc >= lo + 1.0)                                  # хоть 1 px кольца внутри окна этой части
        if not use.any():
            continue
        if ring.sum() < 100:
            rep['tiers'].append({'lo': lo, 'px': int(use.sum()), 'ring_px': int(ring.sum()), 'why': 'кольца нет (< 100 px)'})
            continue
        w = ring.astype(np.float32)
        ws = gaussian_filter(w, sg)[..., None]
        sm = np.stack([gaussian_filter(lab[..., c] * w, sg) for c in range(3)], -1) / np.maximum(ws, 1e-6)
        dist, (iy, ix) = distance_transform_edt(~ring, return_indices=True)
        yy, xx = np.nonzero(use & (dist <= 2 * INWARD_HI))
        ok_los = np.ones(len(yy), bool)
        if len(yy):
            qy, qx = iy[yy, xx], ix[yy, xx]
            for t in ts:                                                # отрезок пиксель → кольцо целиком внутри маски фото
                sy = np.rint(yy + (qy - yy) * t).astype(np.int64)
                sx = np.rint(xx + (qx - xx) * t).astype(np.int64)
                ok_los &= pmask[sy, sx]
        sel = np.zeros(pmask.shape, bool)
        sel[yy[ok_los], xx[ok_los]] = True
        ref[sel] = sm[iy, ix][sel]
        rep['tiers'].append({'lo': lo, 'px': int(use.sum()), 'ring_px': int(ring.sum()), 'ref_px': int(sel.sum()), 'no_sight_px': int(len(yy) - ok_los.sum()), 'far_px': int((use & ~sel).sum() - (len(yy) - ok_los.sum()))})
        todo = todo & ~sel
    rep['fallback_px'] = int(todo.sum())
    if rep['fallback_px']:
        thin = int((todo & (loc < INWARD_LO / 2)).sum())
        if thin:
            rep['fallback_why']['часть тоньше 8 px (кольца внутри нет)'] = thin
        if rep['fallback_px'] - thin:
            rep['fallback_why']['кольцо вне линии видимости внутри маски или дальше 2×hi'] = rep['fallback_px'] - thin
    _INWARD_REP.clear()
    _INWARD_REP.update(rep)
    return ref


def fringe_reference(st: dict, prgb: np.ndarray, pmask: np.ndarray) -> np.ndarray:
    """Опорный цвет «ткани» для каймы/мерки края (T-20261124-10/2): флаг edge_bg_local ВЫКЛ — одна медиана ядра на весь товар (core_median, как раньше); ВКЛ — local_reference по пикселю.
    Одна медиана на товар из двух материалов (синяя обивка + светлое дерево) принимала дерево за «фон вырезки» (Марти-2: 4416 из 4416 пикселей на ножках, edge_bg_share 0,258)."""
    if EDGE_BG_INWARD:
        return inward_reference(st, prgb, pmask)
    return local_reference(st, prgb, pmask) if EDGE_BG_LOCAL else core_median(st, prgb, pmask)


def local_reference(st: dict, prgb: np.ndarray, pmask: np.ndarray) -> np.ndarray:
    """Lab-опора по пикселю (H,W,3): сглаженный (σ = edge_bg_ref_sigma_px) цвет БЛИЖАЙШЕГО пикселя ядра — ядро то же, что у core_median (cos >= 0.8, глубже 12 px от краёв фото и силуэта).
    Дерево у ножки сравнивается с деревом ядра ножки, обивка — с обивкой: материал не размазывается в одну медиану. Ядра нет (< 100 px) — запасное, как у core_median; совсем нет — одна медиана."""
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    dp, dm = distance_transform_edt(pmask), distance_transform_edt(st['mask'])
    core = st['mask'] & pmask & (st['cos'] >= 0.8) & (dp > 12) & (dm > 12)
    if core.sum() < 100:
        core = st['mask'] & pmask & (st['cos'] >= TV_FALLBACK_COS)
    if not core.any():
        return np.broadcast_to(core_median(st, prgb, pmask), prgb.shape).astype(np.float32)
    lab = _lab(prgb).astype(np.float32)
    w = core.astype(np.float32)
    sg = max(EDGE_BG_REF_SIGMA, 0.5)
    ws = gaussian_filter(w, sg)[..., None]
    sm = np.stack([gaussian_filter(lab[..., c] * w, sg) for c in range(3)], -1) / np.maximum(ws, 1e-6)
    _, (iy, ix) = distance_transform_edt(~core, return_indices=True)
    return sm[iy, ix].astype(np.float32)


def edge_bg_fringe(st: dict, prgb: np.ndarray, pmask: np.ndarray) -> np.ndarray:
    """Пиксели кадра у края альфы фото (<= EDGE_BG_PX), чей цвет — фон вырезки, а не ткань: в перенос не идут (общее правило, не по товару)."""
    if EDGE_BG_PX <= 0:
        return np.zeros(pmask.shape, bool)
    from scipy.ndimage import distance_transform_edt
    med = core_median(st, prgb, pmask)
    if med[0] > EDGE_BG_WHITE_L:                       # белая ткань (по всему товару): «светлее фона» — сама ткань
        return np.zeros(pmask.shape, bool)
    return bg_like(_lab(prgb), fringe_reference(st, prgb, pmask) if (EDGE_BG_LOCAL or EDGE_BG_INWARD) else med) & (distance_transform_edt(pmask) <= EDGE_BG_PX) & pmask


def known_px(geoms: list, st: dict, tr: dict) -> np.ndarray:
    """Маска кадра: пиксели силуэта растра, чей тексель взят из фото (known)."""
    ids, uv, mask = st['ids'], st['uv'], st['mask']
    offs = np.cumsum([0] + [len(g['F']) for g in geoms])
    gid = np.full(ids.shape, -1, np.int32)
    gid[ids >= 0] = np.searchsorted(offs, ids[ids >= 0], side='right') - 1
    kn = np.zeros(mask.shape, bool)
    for gi, k in enumerate(tr.get('known_photo', tr['known'])):         # только с фото: тон с острого угла (synth) в мерки края/каймы/рваности не входит
        T = k.shape[0]
        ys, xs = np.nonzero((gid == gi) & mask)
        tx = np.clip(np.floor(uv[ys, xs, 0] * T).astype(np.int64), 0, T - 1)
        ty = np.clip(np.floor(uv[ys, xs, 1] * T).astype(np.int64), 0, T - 1)
        kn[ys, xs] = k[ty, tx]
    return kn


def visible_known_share(geoms: list, st: dict, tr: dict) -> tuple[float, int]:
    """T-215: мерка гейта «есть ли что переносить» — доля пикселей силуэта растра (после `zbuffer_fix` это истинно видимое: ближайшая грань в каждом пикселе), чей тексель взят с фото
    (`known_photo`, тон synth не входит). Знаменатель — пиксели силуэта, а не занятые тексели всей развёртки: у прежней `known_share` зад и невидимое сидели в знаменателе, а ложное фото
    зада в числителе (до T-201), поэтому её порог 0,15 не значил «видимое покрыто». → (доля, число пикселей силуэта)."""
    vis = int(st['mask'].sum())
    return round(int(known_px(geoms, st, tr).sum()) / max(vis, 1), 4), vis


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


def edge_bg_reach(pmask: np.ndarray) -> np.ndarray:
    """Маска кадра: пиксели фото не дальше EDGE_BG_REACH px от края его альфы (область мерки под флагом edge_bg_inward; директор 25.11: кайма живёт у края, светлая деталь на 10–15 px — не кайма)."""
    from scipy.ndimage import distance_transform_edt
    return distance_transform_edt(pmask) <= EDGE_BG_REACH


def edge_bg_share(geoms: list, st: dict, prgb: np.ndarray, pmask: np.ndarray, tr: dict, after: np.ndarray) -> dict:
    """Автопроверка: доля «светлых как фон» среди ВЗЯТЫХ пикселей кадра у края (<= EDGE_BG_MEASURE px от края альфы фото или силуэта растра)."""
    from scipy.ndimage import distance_transform_edt
    mask = st['mask']
    kn = known_px(geoms, st, tr)
    near = (np.minimum(distance_transform_edt(pmask), distance_transform_edt(mask)) <= EDGE_BG_MEASURE) & kn
    if EDGE_BG_INWARD:
        near = near & edge_bg_reach(pmask)
    med = core_median(st, prgb, pmask)
    if med[0] > EDGE_BG_WHITE_L:
        return {'edge_bg_share': None, 'edge_known_px': int(near.sum()), 'edge_bg_px': 0, 'edge_bg_na': f'N/A: белая ткань (медиана ядра L* {med[0]:.1f} > {EDGE_BG_WHITE_L:g}), мерка слепа'}
    bg = bg_like(_lab(after), fringe_reference(st, prgb, pmask) if (EDGE_BG_LOCAL or EDGE_BG_INWARD) else med) & near
    n = int(near.sum())
    if os.environ.get('EDGE_BG_DEBUG'):                                  # отладка (только по env): что мерка видит у края — для разбора слепоты опоры
        _rf = fringe_reference(st, prgb, pmask) if (EDGE_BG_LOCAL or EDGE_BG_INWARD) else med
        np.savez_compressed(os.environ['EDGE_BG_DEBUG'], near=near, bg=bg, bg_med=bg_like(_lab(after), med) & near, lab=_lab(after).astype(np.float16), ref=np.broadcast_to(np.asarray(_rf), prgb.shape).astype(np.float16), pmask=pmask, mask=mask)
    ref_kind = 'inward' if EDGE_BG_INWARD else ('local' if EDGE_BG_LOCAL else 'median')
    out = {}
    if EDGE_BG_INWARD and _INWARD_REP:
        out['edge_bg_inward'] = dict(_INWARD_REP)
    out.update({'edge_bg_share': None if n < 200 else round(float(bg.sum() / n), 4), 'edge_known_px': n, 'edge_bg_px': int(bg.sum()), 'edge_bg_ref': ref_kind})
    return out


def depth_band(st: dict) -> np.ndarray:
    """Маска кадра: пиксели у разрыва глубины (край складки, щель между подушками, торец за выступом) шире DEPTH_BAND px — фото там берёт тень щели, а не поверхность."""
    from scipy.ndimage import binary_dilation, median_filter
    d0 = st['depth'].astype(np.float64)
    ok = (d0 > 0) & st['mask']
    d = median_filter(np.where(d0 > 0, d0, float(np.median(d0[ok])) if ok.any() else 0.0), size=max(DEPTH_MED, 1)) if DEPTH_MED > 1 else d0
    pl = max(float(st.get('px_len') or 0.0), 1e-6)
    lim = pl * DEPTH_JUMP
    jump = np.zeros(d.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        a, b = d[: d.shape[0] - dy, : d.shape[1] - dx], d[dy:, dx:]
        both = ok[: d.shape[0] - dy, : d.shape[1] - dx] & ok[dy:, dx:]
        lm = lim
        if DEPTH_TILT:                                                    # плоскость под углом θ к лучу даёт шаг глубины px_len·tgθ на пиксель — это не разрыв
            c = np.maximum(np.minimum(st['cos'][: d.shape[0] - dy, : d.shape[1] - dx], st['cos'][dy:, dx:]), 0.05).astype(np.float64)
            lm = lim + pl * np.sqrt(1.0 - c * c) / c
        j = both & (np.abs(a - b) > lm)
        jump[: d.shape[0] - dy, : d.shape[1] - dx] |= j
        jump[dy:, dx:] |= j
    if DEPTH_BAND <= 0:
        return jump
    return binary_dilation(jump, iterations=DEPTH_BAND)


def _face_graph(V: np.ndarray, F: np.ndarray):
    """Смежность граней по общему ребру (вершины склеены по положению — развёртка рвёт их по швам, форма цела). → (A: взвешенная расстоянием центров, B: бинарная, центры)."""
    from scipy.sparse import coo_matrix
    nF = len(F)
    ext = max(float(np.ptp(V, axis=0).max()), 1e-9)
    q = np.round(V / (ext * 1e-6)).astype(np.int64)
    _, vid = np.unique(q, axis=0, return_inverse=True)
    vid = vid.ravel()
    Fv = vid[F]
    e = np.concatenate([Fv[:, [0, 1]], Fv[:, [1, 2]], Fv[:, [2, 0]]])
    fi = np.tile(np.arange(nF), 3)
    e.sort(1)
    key = e[:, 0] * (int(vid.max()) + 1) + e[:, 1]
    o = np.argsort(key, kind='stable')
    ks, fs = key[o], fi[o]
    same = ks[1:] == ks[:-1]
    a, b = fs[:-1][same], fs[1:][same]
    ok = a != b
    a, b = a[ok], b[ok]
    cen = V[F].mean(1)
    nrm = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    cth = np.clip((nrm[a] * nrm[b]).sum(1), -1.0, 1.0)
    w = TONE_DIST_W * np.linalg.norm(cen[a] - cen[b], axis=1) + TONE_CREASE_W * ext * (1.0 - cth) + 1e-9      # плоскость почти бесплатна (большие грани столешницы), излом дорог
    r, c = np.r_[a, b], np.r_[b, a]
    A = coo_matrix((np.r_[w, w], (r, c)), shape=(nF, nF)).tocsr()
    B = coo_matrix((np.ones(len(r)), (r, c)), shape=(nF, nF)).tocsr()
    B.data[:] = 1.0
    return A, B, cen, ext


def tone_same_side(V: np.ndarray, F: np.ndarray, src: np.ndarray, min_cos: float) -> np.ndarray:
    """Грань «той же стороны», что её источник тона: cos(нормаль грани, нормаль источника) >= min_cos (src < 0 — не достигнута → False). min_cos <= 0 — без запрета.
    Рёберный запрет обходится скошенной сеткой (угол размазан по цепочке мелких граней), поэтому сравниваем с ИСТОЧНИКОМ, а не с соседом: тон фасада не уходит на зад/верх/бок."""
    ok = src >= 0
    if min_cos <= 0:
        return ok
    nrm = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    cs = (nrm * nrm[np.clip(src, 0, None)]).sum(1)
    return ok & (cs >= min_cos)


def _gsmooth(B, num: np.ndarray, den: np.ndarray, iters: int) -> tuple[np.ndarray, np.ndarray]:
    """Нормированное сглаживание по графу граней: число и вес растекаются по соседям, значение = num/den (где den > 0)."""
    for _ in range(max(int(iters), 0)):
        num = num + B @ num
        den = den + B @ den
        s = float(den.max())
        if s > 1e100:
            num, den = num / s, den / s
    return num, den


def _tone_unknown(pop: tuple, known: np.ndarray, take: np.ndarray | None) -> float | None:
    """МЕРКА (T-20261124-27, п.5): доля пикселей косой части (cos в диапазоне тона), чей тексель остался НЕИЗВЕСТНЫМ: не взят с фото и не окрашен тоном Ш3б. Ловит и «отброшено по ΔE», и «нет опоры» одним числом; None — пикселей нет."""
    py, px = pop
    if len(py) == 0:
        return None
    unk = ~known[py, px]
    if take is not None:
        unk &= ~take[py, px]
    return round(float(unk.mean()), 4)


def tone_planes(V: np.ndarray, F: np.ndarray, B, angle_deg: float, min_faces: int = 20) -> tuple[np.ndarray, object]:
    """Плоскости формы по НОРМАЛИ-ЯКОРЮ (без дрейфа цепочкой: скруглённый край с шагом нормали < угла склеил бы верх и фасад в одну «плоскость» со средней нормалью по диагонали — все грани вне неё, 12 032 из 12 467 у комода-лака).
    Жадно: самое людное направление нормалей среди нераспределённых граней (ячейка 0,1) → якорь = их средняя нормаль; грани с нормалью ≤ angle_deg от якоря, связные по рёбрам графа граней, — плоскость (метка ≥ 0); повтор, пока людное направление ≥ min_faces граней.
    Остальные — -1 (изгиб, мелочь). → (метка плоскости на грань, граф B только по рёбрам внутри плоскости — сглаживание не переходит через излом)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    nF = len(F)
    nrm = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    ca = float(np.cos(np.radians(angle_deg)))
    lab = np.full(nF, -1, np.int64)
    rest = np.ones(nF, bool)
    q = np.round(nrm * 10.0).astype(np.int64)
    key = (q[:, 0] + 20) * 1681 + (q[:, 1] + 20) * 41 + (q[:, 2] + 20)
    Bc = B.tocoo()
    nxt = 0
    for _ in range(64):
        if not rest.any():
            break
        ks, cnt = np.unique(key[rest], return_counts=True)
        if int(cnt.max()) < int(min_faces):
            break
        anchor = nrm[rest & (key == ks[int(cnt.argmax())])].mean(0)
        anchor /= max(float(np.linalg.norm(anchor)), 1e-12)
        sel = rest & ((nrm @ anchor) >= ca)
        e = sel[Bc.row] & sel[Bc.col]
        Bs = coo_matrix((np.ones(int(e.sum())), (Bc.row[e], Bc.col[e])), shape=(nF, nF)).tocsr()
        _n, cl = connected_components(Bs, directed=False)
        idx = np.nonzero(sel)[0]
        for c in np.unique(cl[idx]):
            m = idx[cl[idx] == c]
            if len(m) >= 1:
                lab[m] = nxt
                nxt += 1
        rest &= ~sel
    e = (lab[Bc.row] >= 0) & (lab[Bc.row] == lab[Bc.col])
    Bp = coo_matrix((np.ones(int(e.sum())), (Bc.row[e], Bc.col[e])), shape=(nF, nF)).tocsr()
    return lab, Bp


def _glare_faces(lo: np.ndarray, w: np.ndarray, ref: np.ndarray, card: dict | None = None) -> tuple[np.ndarray, dict | None]:
    """БЛИК глянца на плоскости (T-20261124-27, комод-лак: светлый верх у красного корпуса запекался в текстуру с любого угла).
    Грань — кандидат (а): светлее прежней опоры на ≥ TONE_GLARE_MIN_DL, опора цветная (C ≥ TONE_GLARE_MIN_REF_C), а её собственная цветность C ≤ TONE_GLARE_C_RATIO·C опоры.
    Принимается, если подан голос (б): по плоскости L растёт — C падает (корреляция ≤ TONE_GLARE_CORR_MAX при ≥ TONE_GLARE_MIN_FACES граней) ИЛИ (в) карточка товара «лак/глянец/эмаль» (card['gloss']);
    против — card['other_material'] (стекло/камень/другой цвет). Карточки в Ш3б нет (приходит на этапе 07), поэтому по умолчанию работают (а)+(б). → (маска блика на гранях, сведения по плоскости | None)."""
    C = np.hypot(lo[:, 1], lo[:, 2])
    Cr = np.hypot(ref[:, 1], ref[:, 2])
    cand = (lo[:, 0] - ref[:, 0] >= TONE_GLARE_MIN_DL) & (Cr >= TONE_GLARE_MIN_REF_C) & (C <= TONE_GLARE_C_RATIO * Cr)
    if not cand.any():
        return cand, None
    corr = None
    if len(lo) >= TONE_GLARE_MIN_FACES:
        ww = np.maximum(w, 1e-9)
        mL, mC = np.average(lo[:, 0], weights=ww), np.average(C, weights=ww)
        cv = np.average((lo[:, 0] - mL) * (C - mC), weights=ww)
        sL, sC = np.sqrt(np.average((lo[:, 0] - mL) ** 2, weights=ww)), np.sqrt(np.average((C - mC) ** 2, weights=ww))
        if sL > 1e-6 and sC > 1e-6:
            corr = float(cv / (sL * sC))
    card = card or {}
    vote_b = corr is not None and corr <= TONE_GLARE_CORR_MAX
    vote_c = bool(card.get('gloss'))
    against = bool(card.get('other_material'))
    ok = (vote_b or vote_c) and not against
    info = {'faces_cand': int(cand.sum()), 'faces_obs': int(len(lo)), 'med_L': round(float(np.median(lo[cand, 0])), 1), 'med_C': round(float(np.median(C[cand])), 1),
            'ref_L': round(float(np.median(ref[cand, 0])), 1), 'ref_C': round(float(np.median(Cr[cand])), 1), 'corr_L_C': None if corr is None else round(corr, 2),
            'vote_b': bool(vote_b), 'vote_card': vote_c, 'against': against, 'glare': bool(ok)}
    return (cand if ok else np.zeros(len(lo), bool)), info


def tone_plane_ref(lo_f: np.ndarray, no: np.ndarray, ref: np.ndarray, V: np.ndarray, F: np.ndarray, B, de2000, card: dict | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Опора тона от САМОЙ плоскости (T-20261124-27, Крит: опора с кромки L 56 при верхе L 76 → отброшено 47 % верха).
    Для плоскости с ≥ TONE_PLANE_MIN_OBS наблюдений: опора грани = местное сглаженное поле наблюдений плоскости (вес — число пикселей; выбросы по ΔE > TONE_MAX_DE от поля вынимаются и поле считается заново);
    цвет грани по-прежнему её собственное наблюдение (тон по медиане НЕ красим — сотрёт ёлочку/мрамор). Плоскость не одногорбая (< TONE_PLANE_UNIMODAL граней в TONE_MAX_DE от медианы) — отсев не делаем:
    опора наблюдённой грани = её наблюдение (ΔE 0, Δ 0). Мало наблюдений — опора прежняя.
    БЛИК (TONE_GLARE, `_glare_faces`): грани-блики плоскости из поля и отсева выводятся, опора у них ПРЕЖНЯЯ (цвет корпуса), в маске glare — красить опорой (Δ 0), не выкидывать и не запекать; у плоскости, где блик ≥ половины веса, так же и ненаблюдённые грани.
    → (ref', force_keep: маска граней без отсева, glare: маска граней-бликов, info)."""
    nF = len(F)
    lab, Bp = tone_planes(V, F, B, TONE_PLANE_ANGLE, TONE_PLANE_MIN_FACES)
    ref2 = ref.copy()
    keep_all = np.zeros(nF, bool)
    glare = np.zeros(nF, bool)
    obs = no > 0
    info = {'tone_planes': 0, 'tone_planes_used': 0, 'tone_planes_multimodal': 0, 'tone_plane_faces_obs': 0}
    if TONE_GLARE:
        info.update(tone_glare_planes=0, tone_glare_faces=0, tone_glare_info=[])
    ob = obs & (lab >= 0)                                                         # грани вне плоскостей (lab = -1) в счёт наблюдений плоскости не идут
    npx = np.bincount(lab[ob], weights=no[ob], minlength=int(lab.max()) + 1) if ob.any() else np.zeros(1)
    for pl in np.nonzero(npx >= TONE_PLANE_MIN_OBS)[0]:
        mem = lab == pl
        of = np.nonzero(mem & obs)[0]
        if len(of) == 0:
            continue
        info['tone_planes'] += 1
        if TONE_GLARE:
            gf, gi = _glare_faces(lo_f[of], no[of], ref[of], card)
            if gi is not None and len(info['tone_glare_info']) < 12:
                info['tone_glare_info'].append(dict(gi, plane=int(pl)))
            if gf.any():
                if float(no[of][gf].sum()) >= 0.5 * float(no[of].sum()):
                    glare[mem & ~obs] = True                                          # блик у большинства плоскости: ненаблюдённые грани тоже красим опорой
                glare[of[gf]] = True
                info['tone_glare_planes'] += 1
                info['tone_glare_faces'] += int(gf.sum())
                of = of[~gf]
                if len(of) == 0:
                    continue                                                          # вся плоскость — блик: опора прежняя
        med = np.median(lo_f[of], axis=0)
        d_med = de2000(lo_f[of], np.repeat(med[None], len(of), 0))
        if float((d_med <= TONE_MAX_DE).mean()) < TONE_PLANE_UNIMODAL:
            keep_all[of] = True
            ref2[of] = lo_f[of]                                                       # ёлочка/мрамор/два цвета: грань — своё наблюдение, отсева нет
            info['tone_planes_multimodal'] += 1
            info['tone_plane_faces_obs'] += int(len(of))
            continue
        w = np.where(mem & obs & ~glare, no, 0.0)
        rn, rd = _gsmooth(Bp, lo_f * w[:, None], w, TONE_PLANE_ITERS)
        fld = rn / np.maximum(rd, 1e-12)[:, None]
        d1 = de2000(lo_f[of], fld[of])
        w2 = w.copy()
        w2[of[d1 > TONE_MAX_DE]] = 0.0                                                # выбросы (другой материал, блик) из поля вынуть и пересчитать
        if float(w2.sum()) > 0:
            rn, rd = _gsmooth(Bp, lo_f * w2[:, None], w2, TONE_PLANE_ITERS)
            fld = rn / np.maximum(rd, 1e-12)[:, None]
        has = mem & (rd > 0) & ~glare
        ref2[has] = fld[has]
        info['tone_planes_used'] += 1
        info['tone_plane_faces_obs'] += int(len(of))
    return ref2, keep_all, glare, info


def tone_oblique(tex: np.ndarray, occ: np.ndarray, known: np.ndarray, fid: np.ndarray, st: dict, prgb: np.ndarray, pmask: np.ndarray, nogo: np.ndarray, edge_ok: np.ndarray,
                 lo: int, hi: int, cos_max: float, g: dict) -> dict:
    """Ш3б: тон с острого угла плавным полем по ПОВЕРХНОСТИ части (граф граней, не по текселям — развёртка TRELLIS рвёт поверхность на мелкие острова, соседи по текселям чужие).
    Наблюдение — пиксель растра геометрии (грань ВИДНА камере), cos в [TONE_COS_MIN, cos_max), в силуэте фото, не у разрыва глубины/каймы фона/края фото (маска +1 px), тексель ещё не известен.
    По граням: опора = цвет ближайших по поверхности известных граней (с фото), сглаженный; Δ = наблюдение − опора; грань с ΔE00(наблюдение, опора) > TONE_MAX_DE (другой материал, блик) отбрасывается;
    Δ растекается по поверхности (цена шага — TONE_DIST_W·расстояние + TONE_CREASE_W·габарит·(1−cos излома): по плоскости далеко, через острый излом — нет) не дальше TONE_REACH_FRAC габарита от наблюдавшейся грани и сглаживается; цвет неизвестных текселей грани = опора + (WL·ΔL, WC·Δa, WC·Δb).
    Возвращает {'take': маска T×T, 'rgb': uint8 T×T×3, 'info': {…}}."""
    import recolor_lp as LP
    from scipy.ndimage import binary_dilation
    from scipy.sparse.csgraph import dijkstra
    T = occ.shape[0]
    F, V = g['F'], g['V']
    nF = len(F)
    ids, cs = st['ids'], st['cos']
    info = {'tone_obs_px': 0, 'tone_faces_obs': 0, 'tone_faces_kept': 0, 'tone_dropped_de': 0, 'tone_faces_painted': 0, 'tone_painted': 0}
    zero = {'take': np.zeros((T, T), bool), 'rgb': np.zeros((T, T, 3), np.uint8), 'info': info}
    if int(known.sum()) < 200:
        info['tone_skip'] = 'мало известного (опоры нет)'
        return zero
    bad = binary_dilation(nogo, iterations=1)
    ys, xs = np.nonzero(st['mask'] & (ids >= lo) & (ids < hi) & pmask & ~bad & edge_ok & (cs >= TONE_COS_MIN) & (cs < cos_max))
    tpx = np.clip(np.floor(st['uv'][ys, xs, 0] * T).astype(np.int64), 0, T - 1)
    tpy = np.clip(np.floor(st['uv'][ys, xs, 1] * T).astype(np.int64), 0, T - 1)
    sel = occ[tpy, tpx] & ~known[tpy, tpx]
    pop = (tpy[occ[tpy, tpx]], tpx[occ[tpy, tpx]])                                                      # МЕРКА: пиксели косой части (cos в диапазоне тона, в силуэте, не у разрыва/каймы) на текселях формы
    info['tone_unknown_share'] = _tone_unknown(pop, known, None)
    ys, xs = ys[sel], xs[sel]
    info['tone_obs_px'] = int(len(ys))
    if len(ys) < TONE_MIN_OBS:
        info['tone_skip'] = f'мало наблюдений ({len(ys)} < {TONE_MIN_OBS})'
        return zero
    A, B, cen, ext = _face_graph(V, F)
    fo = (ids[ys, xs] - lo).astype(np.int64)
    labp = LP.lab_f(prgb[ys, xs][None])[0].astype(np.float64)
    no = np.bincount(fo, minlength=nF).astype(np.float64)
    lo_f = np.stack([np.bincount(fo, labp[:, c], nF) for c in range(3)], 1) / np.maximum(no, 1.0)[:, None]
    obs_faces = np.nonzero(no > 0)[0]
    info['tone_faces_obs'] = int(len(obs_faces))
    kf = fid[known]
    nk = np.bincount(kf, minlength=nF).astype(np.float64)
    lab_t = LP.lab_f(np.clip(tex[known], 0, 255).astype(np.float32)[None])[0].astype(np.float64)
    lk_f = np.stack([np.bincount(kf, lab_t[:, c], nF) for c in range(3)], 1) / np.maximum(nk, 1.0)[:, None]
    known_faces = np.nonzero(nk >= 3)[0]
    if len(known_faces) == 0:
        info['tone_skip'] = 'нет граней с известным цветом'
        return zero
    glob = np.median(lab_t[:: max(1, len(lab_t) // 20000)], axis=0)
    _d, _p, srck = dijkstra(A, directed=False, indices=known_faces, min_only=True, return_predecessors=True)
    ref0 = np.where((srck >= 0)[:, None], lk_f[np.clip(srck, 0, None)], glob[None, :])
    rn, rd = _gsmooth(B, ref0, np.ones(nF), TONE_REF_ITERS)
    ref = rn / rd[:, None]
    keep_all = np.zeros(nF, bool)
    glare = np.zeros(nF, bool)
    if TONE_PLANE_REF:
        ref, keep_all, glare, pinfo = tone_plane_ref(lo_f, no, ref, np.asarray(V, np.float64), np.asarray(F), B, LP.de2000, g.get('gloss_card'))
        info.update(pinfo)
    de = LP.de2000(lo_f[obs_faces], ref[obs_faces])
    ok = ((de <= TONE_MAX_DE) | keep_all[obs_faces]) & ~glare[obs_faces]
    kept = obs_faces[ok]
    n_glare_obs = int(glare[obs_faces].sum())
    info['tone_dropped_de'] = int(len(obs_faces) - len(kept) - n_glare_obs)
    info['tone_drop_share'] = round(info['tone_dropped_de'] / max(len(obs_faces), 1), 4)
    if TONE_GLARE and TONE_PLANE_REF:
        info['tone_glare_share'] = round(n_glare_obs / max(len(obs_faces), 1), 4)                       # доля наблюдённых граней-бликов (красим опорой, Δ 0)
    info['tone_faces_kept'] = int(len(kept))
    if len(kept) == 0 and n_glare_obs == 0:
        info['tone_skip'] = f'все наблюдения дальше {TONE_MAX_DE:g} ΔE00 от опоры'
        return zero
    if len(kept):
        dist, _p2, src = dijkstra(A, directed=False, indices=kept, min_only=True, return_predecessors=True, limit=TONE_REACH_FRAC * ext)
        reached = tone_same_side(V, F, src, TONE_SRC_COS)                                                # другая сторона формы (зад/верх/бок) — другая поверхность: тон фасада на неё не переносим
    else:                                                                                                  # только блики: Δ ни у кого нет, красим опорой
        dist, src, reached = np.full(nF, np.inf), np.full(nF, -1, np.int64), np.zeros(nF, bool)
    delta0 = np.zeros((nF, 3))
    delta0[reached] = (lo_f - ref)[src[reached]]
    dn, dd = _gsmooth(B, delta0 * reached[:, None], reached.astype(np.float64), TONE_SMOOTH_ITERS)
    painted = reached & (dd > 0)
    if TONE_SKIP_DROPPED:
        dropped = np.setdiff1d(obs_faces, kept)
        painted[dropped] = False
    painted |= glare                                                                                       # блик: красим опорой (Δ 0), не выкидываем (иначе крапа) и не запекаем
    delta = dn / np.maximum(dd, 1e-12)[:, None]
    near = np.clip(1.0 - dist / max(TONE_NEAR_FRAC * ext, 1e-9), 0.0, 1.0)[:, None]                  # 1 на наблюдавшейся грани → 0 дальше tone_near_frac·габарит
    wgt = near + (1.0 - near) * np.array([TONE_WL, TONE_WC, TONE_WC])[None, :]
    own = np.zeros(nF, bool)
    own[kept] = True                                                                                     # у самой наблюдавшейся грани — её собственное наблюдение (сглаженное Δ соседей светлее/темнее фото на этих пикселях)
    if TONE_PLANE_REF and TONE_OWN_N0 > 0:                                                              # грань с малым числом пикселей — шумное среднее: тянем к сглаженному Δ соседей
        a_own = (no / (no + TONE_OWN_N0))[:, None]
        delta = np.where(own[:, None], a_own * (lo_f - ref) + (1.0 - a_own) * delta, delta)
    else:
        delta = np.where(own[:, None], lo_f - ref, delta)
    delta[glare] = 0.0
    if ISL_ON and (ISL_TOP.get('enabled', True)):                                                      # верх по моде: Δ граней верха → к их медиане (гасим полосы блика), низкочастотный тон остаётся
        delta, top_info = top_mode(delta, painted, V, F, ISL_TOP)
        info.update(top_info)
        delta[glare] = 0.0
    lab_new = ref + delta * wgt
    frgb = LP.l2s8(LP.lab_to_lin(lab_new.astype(np.float32)[None]))[0]
    fcl = np.clip(fid, 0, nF - 1)
    take = occ & ~known & painted[fcl]
    rgb = frgb[fcl]
    info['tone_faces_painted'] = int(painted.sum())
    info['tone_painted'] = int(take.sum())
    info['tone_unknown_share'] = _tone_unknown(pop, known, take)
    info['tone_mean_abs_delta'] = [round(float(np.abs(delta[painted][:, c]).mean()), 2) for c in range(3)]
    return {'take': take, 'rgb': rgb, 'info': info}


def _lab_img(tex: np.ndarray) -> np.ndarray:
    """T×T×3 (0…255) → Lab T×T×3 float32 (та же Lab, что в тоне Ш3б)."""
    import recolor_lp as LP
    T = tex.shape[0]
    return LP.lab_f(np.clip(tex, 0, 255).astype(np.float32).reshape(1, -1, 3))[0].reshape(T, T, 3).astype(np.float32)


def _lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Lab (N,3) → sRGB 0…255 float (N,3)."""
    import recolor_lp as LP
    return LP.l2s8(LP.lab_to_lin(np.asarray(lab, np.float32)[None]))[0].astype(np.float64)


def island_jump(tex: np.ndarray, occ: np.ndarray, known_photo: np.ndarray, known_all: np.ndarray, cfg: dict | None = None) -> dict:
    """МЕРКА «скачок тона на границе острова» (справочная): медианы Lab взятых с фото текселей и не взятых (родной цвет) в `ring_px` по обе стороны границы взятого.
    Скачок большой — граница фото-острова видна ступенькой (рваный контур, пятна у кромки). Нет границы/мало текселей — `None` (не 0)."""
    from scipy.ndimage import distance_transform_edt
    cfg = cfg if cfg is not None else ISL_JUMP
    ring, min_px = float(cfg.get('ring_px', 3)), int(cfg.get('min_px', 30))
    out = {'dL': None, 'da': None, 'db': None, 'dE': None, 'n_in': 0, 'n_out': 0, 'bad': None}
    if int(known_photo.sum()) < min_px:
        return out
    d_in = distance_transform_edt(known_photo)
    d_out = distance_transform_edt(~known_photo)
    inn = known_photo & (d_in <= ring)
    outer = occ & ~known_all & (d_out <= ring)
    out['n_in'], out['n_out'] = int(inn.sum()), int(outer.sum())
    if out['n_in'] < min_px or out['n_out'] < min_px:
        return out
    lab = _lab_img(tex)
    dv = np.median(lab[inn], axis=0) - np.median(lab[outer], axis=0)
    out.update(dL=round(float(dv[0]), 2), da=round(float(dv[1]), 2), db=round(float(dv[2]), 2), dE=round(float(np.hypot(dv[1], dv[2])), 2))
    out['bad'] = bool(abs(dv[0]) > float(cfg.get('dL', 4.0)) or np.hypot(dv[1], dv[2]) > float(cfg.get('dAB', 6.0)))
    return out


def island_tone(tex: np.ndarray, native: np.ndarray, occ: np.ndarray, known_photo: np.ndarray, known_all: np.ndarray, cfg: dict | None = None) -> tuple[np.ndarray, dict]:
    """ТОН У ГРАНИЦЫ ОСТРОВА: не взятые тексели в полосе `band_px` от взятых с фото получают плавный сдвиг Lab (поле Δ = фото − родной цвет, гаусс `sigma_px`, вес 1 у границы → 0 на band_px).
    Меняется только низкочастотный тон; рисунок родного цвета и известные тексели не трогаются; тексель остаётся неизвестным. Возвращает (новая текстура, сводка)."""
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    cfg = cfg if cfg is not None else ISL_TONE
    band, sig = float(cfg.get('band_px', 6.0)), float(cfg.get('sigma_px', 4.0))
    info = {'edge_tone_texels': 0}
    if int(known_photo.sum()) < int(cfg.get('min_known_px', 200)):
        info['edge_tone_skip'] = 'мало известного'
        return tex, info
    lab_t, lab_n = _lab_img(tex), _lab_img(native)
    m = known_photo.astype(np.float32)
    d = np.where(known_photo[..., None], lab_t - lab_n, 0.0).astype(np.float32)
    den = gaussian_filter(m, sig)
    num = np.stack([gaussian_filter(d[..., c], sig) for c in range(3)], 2)
    dsm = num / np.maximum(den, 1e-3)[..., None]
    dsm[..., 0] = np.clip(dsm[..., 0], -float(cfg.get('max_shift_L', 15.0)), float(cfg.get('max_shift_L', 15.0)))
    dsm[..., 1:] = np.clip(dsm[..., 1:], -float(cfg.get('max_shift_ab', 20.0)), float(cfg.get('max_shift_ab', 20.0)))
    dist = distance_transform_edt(~known_photo)
    target = occ & ~known_all & (dist <= band) & (den >= float(cfg.get('min_cover', 0.02)))
    if not target.any():
        return tex, info
    w = np.clip(1.0 - dist / max(band, 1e-6), 0.0, 1.0)[target][:, None]
    new = tex.copy()
    new[target] = _lab_to_rgb(lab_n[target] + w * dsm[target])
    info['edge_tone_texels'] = int(target.sum())
    info['edge_tone_mean_abs_shift'] = [round(float(np.abs(w * dsm[target]).mean(axis=0)[c]), 2) for c in range(3)]   # w (N,1) × (N,3); (N,1)×(N,) давало матрицу N×N — на 30 тыс. текселей 6,7 ГБ
    return new, info


def line_gaps(tex: np.ndarray, occ: np.ndarray, known: np.ndarray, cfg: dict | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """ТОНКАЯ ЩЕЛЬ ЦЕЛИКОМ: тёмная тонкая линия на взятом с фото (L темнее местного фона на `dark_dL`, ширина ≤ `max_width_px`) с разрывами ≤ `max_gap_px` вдоль линии (замыкание вдоль осей развёртки; диагональные щели не склеиваем).
    Разрыв закрывается цветом ближайшего тёмного текселя. Заполненное шире `max_width_px` (две параллельные щели) отбрасывается; непрерывная линия не меняется.
    Возвращает (тексели для закрытия, цвет RGB T×T×3 float, сводка с долей «рваных» = закрытые / (тёмные тонкие + закрытые))."""
    from scipy.ndimage import binary_closing, binary_opening, distance_transform_edt, gaussian_filter
    cfg = cfg if cfg is not None else ISL_LINE
    w, gap, sig = int(cfg.get('max_width_px', 2)), int(cfg.get('max_gap_px', 5)), float(cfg.get('bg_sigma_px', 8.0))
    info = {'line_thin_px': 0, 'line_gap_px': 0, 'line_ragged_share': None}
    none = np.zeros(occ.shape, bool)
    if int(known.sum()) < 200:
        return none, tex, info
    L = _lab_img(tex)[..., 0]
    m = known.astype(np.float32)
    ref = gaussian_filter(np.where(known, L, 0.0).astype(np.float32), sig) / np.maximum(gaussian_filter(m, sig), 1e-3)
    dark = known & (L < ref - float(cfg.get('dark_dL', 12.0)))
    thin = dark & ~binary_opening(dark, structure=np.ones((w + 1, w + 1), bool))
    info['line_thin_px'] = int(thin.sum())
    if not thin.any():
        return none, tex, info
    info['line_thin_share'] = round(float(thin.sum()) / max(int(known.sum()), 1), 4)
    if info['line_thin_share'] > float(cfg.get('max_thin_share', 0.05)):                 # тёмных тонких линий много — это рисунок ткани/узор, а не щели: не трогаем (проба: узор 12008 превращался в сетку)
        info['line_skip'] = 'рисунок: тонких тёмных линий %.1f %% взятого' % (100 * info['line_thin_share'])
        return none, tex, info
    k = gap + 1
    ses = [np.ones((1, k), bool), np.ones((k, 1), bool)]                       # только вдоль осей развёртки: диагональное замыкание рисует клинья на стыках щелей (проба на комоде)
    closed = np.zeros(occ.shape, bool)
    for se in ses:
        closed |= binary_closing(thin, structure=se)
    gaps = closed & ~thin & occ
    gaps &= ~binary_opening(gaps, structure=np.ones((w + 1, w + 1), bool))          # заполнение шире линии — это промежуток между двумя щелями, не разрыв
    info['line_gap_px'] = int(gaps.sum())
    info['line_ragged_share'] = round(float(gaps.sum()) / max(int(thin.sum() + gaps.sum()), 1), 4)
    if not gaps.any():
        return none, tex, info
    _d, (iy, ix) = distance_transform_edt(~thin, return_distances=True, return_indices=True)
    col = tex.copy()
    col[gaps] = tex[iy[gaps], ix[gaps]]
    return gaps, col, info


def top_mode(delta: np.ndarray, painted: np.ndarray, V: np.ndarray, F: np.ndarray, cfg: dict | None = None) -> tuple[np.ndarray, dict]:
    """ВЕРХ ПО МОДЕ: у окрашенных тоном Ш3б граней верха (|нормаль·вверх| ≥ `top_ny`; вверх — ось y GLB) поле Δ тянется к медиане Δ верха с весом `k`. Гасит полосы блика между гранями,
    низкочастотный тон (медиана) остаётся. Граней мало (< `min_faces`) — не трогаем."""
    cfg = cfg if cfg is not None else ISL_TOP
    V, F = np.asarray(V, np.float64), np.asarray(F, np.int64)
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    ny = np.abs(n[:, 1]) / np.maximum(np.linalg.norm(n, axis=1), 1e-12)
    top = painted & (ny >= float(cfg.get('top_ny', 0.7)))
    info = {'top_faces': int(top.sum())}
    if info['top_faces'] < int(cfg.get('min_faces', 20)):
        info['top_skip'] = 'граней верха мало'
        return delta, info
    k = float(cfg.get('k', 0.7))
    med = np.median(delta[top], axis=0)
    out = delta.copy()
    out[top] = (1.0 - k) * delta[top] + k * med
    info['top_delta_std'] = [[round(float(delta[top][:, c].std()), 2) for c in range(3)], [round(float(out[top][:, c].std()), 2) for c in range(3)]]
    return out, info


def cube_frame(geoms: list, st: dict):
    """Форма в кадре камеры этапа 4: вершины куба (`worker_trellis.to_cube` с yaw из manifest этапа 4) и центр перспективной камеры (None — ортографическая, смотрит на сторону +Z куба).
    → ({'P', 'cam', 'C'} | None, пометка). Общее для z-буфера и правила «спиной к камере»."""
    cam = st.get('camera')
    if not cam:
        return None, 'нет камеры'
    if len(geoms) != 1:
        return None, 'несколько геометрий'
    import mv_geometry as MG                                            # to_cube вынесена из worker_trellis сюда (тот же код); worker_trellis в образ этапов не входит. Импорты — вне try: нет файла в образе = отказ этапа, не тихий пропуск
    import pose_fit as PF
    try:
        yaw = 0.0
        mp = os.path.join(st.get('pose_run') or '', 'stages', 'manifest.json')
        if os.path.exists(mp):
            yaw = float(json.load(open(mp, encoding='utf-8')).get('yaw_deg') or 0.0)
        P, _c, _s, _R = MG.to_cube(geoms[0]['V'], yaw)
        if 'az' in cam:
            C = PF.cam_basis(cam['az'], cam['el'], cam['d'])[0]
        else:
            C = None
    except Exception as e:  # noqa: BLE001 — правила страховочные, этап не роняют
        return None, f'пропуск: {type(e).__name__}: {str(e)[:80]}'
    return {'P': P, 'cam': cam, 'C': C}, ''


def zbuffer_fix(geoms: list, st: dict) -> tuple[dict, dict]:
    """Z-буфер видимости (T-201). Кадр этапа 4 (`pose_fit.render_persp`) рисует грани «дальние первыми» по СРЕДНЕЙ глубине грани, без z-буфера: у тонкой двойной стенки (фасад TRELLIS: передний и задний слой рядом)
    и у больших косых граней на пикселе остаётся не ближайшая грань — ложная «видимая» грань проходит и cos, и допуск глубины (глубина берётся из неё же) и получает фото чужой стороны.
    Здесь форма заново растрируется с настоящим z-буфером (`tex_coverage.raster`, глубина 1/Z — линейна по экрану, значит перспективно верна); в пикселе, где грань растра этапа 4 дальше ближайшей больше чем на
    `z_buffer_tol_px` пикселей предмета, подставляется ближайшая (UV, cos, глубина — `pose_fit.pixel_attrs`, та же арифметика, что в кадре этапа 4). Остальное — как есть: допуск не даёт менять растр
    из-за разных правил закраски краёв у cv2 и у нашего растеризатора. Нет перспективной камеры / форма не совпала с растром — растр остаётся, причина в пометке. → (st, {zbuf…})."""
    if not ZBUF_ON:
        return st, {'zbuf': 'выключено'}
    fr, note = cube_frame(geoms, st)
    if fr is None:
        return st, {'zbuf': note}
    if fr['C'] is None:
        return st, {'zbuf': 'пропуск: камера не перспективная'}
    import pose_fit as PF
    P, cam, n = fr['P'], fr['cam'], int(st['px'])
    F = np.asarray(geoms[0]['F'], np.int64)
    x, y, Z = PF.project(P, cam)
    ids_z, zb = TC.raster(np.stack([x * n, y * n], 1), F, n, 1.0 / np.maximum(Z, 1e-6))        # БОЛЬШЕ = БЛИЖЕ: 1/Z
    ids_z = ids_z.reshape(n, n)
    zn = np.where(np.isfinite(zb), 1.0 / np.maximum(zb, 1e-12), 0.0).reshape(n, n)
    ids, depth, mask = st['ids'], st['depth'], st['mask']
    both = mask & (ids >= 0) & (ids_z >= 0)
    cover = float(both.sum() / max(int(mask.sum()), 1))
    px_len = max(float(st.get('px_len') or 0.0), 1e-9)
    same = both & (ids == ids_z)
    med = float(np.median(np.abs(depth[same] - zn[same])) / px_len) if same.any() else float('inf')
    if cover < ZBUF_MIN_COVER or med > ZBUF_GEOM_TOL:
        return st, {'zbuf': f'пропуск: форма не совпала с растром камеры (покрытие {cover:.2f}, расхождение глубины {med:.1f} px)'}
    dm = depth_mismatch(st, zn, both, ids_z, px_len)                                 # мерка В (T-20261124-27): честна ли глубина этапа 4 на видимых гранях; пишется всегда, флаг не нужен
    wrong = both & (ids != ids_z) & ((depth - zn) > ZBUF_TOL * px_len)
    n_back = 0
    if ZBUF_BACK:                                                                    # ничья по глубине (двойная стенка толщиной < допуска): грань спиной к камере (знаковая нормаль) видимой поверхностью замкнутой формы быть не может — берём ближайшую
        back, _bn = back_face_mask(geoms, st)
        if back is not None:
            tie = both & (ids != ids_z) & back[np.clip(ids, 0, len(back) - 1)] & ~back[np.clip(ids_z, 0, len(back) - 1)] & ~wrong
            n_back = int(tie.sum())
            wrong = wrong | tie
    info = {'zbuf': 'вкл', 'zbuf_px_fixed': int(wrong.sum()), 'zbuf_px_back_tie': n_back, 'zbuf_faces_replaced': int(np.unique(ids[wrong]).size), 'zbuf_share': round(float(wrong.sum() / max(int(mask.sum()), 1)), 4), 'depth_mismatch': dm}
    zall = ZDEPTH_ALL and bool(((zn > 0) & both).any())
    if not wrong.any() and not zall:
        return st, info
    out = dict(st)
    out['ids'], out['uv'], out['cos'], out['depth'] = ids.copy(), st['uv'].copy(), st['cos'].copy(), depth.copy()
    if wrong.any():
        ys, xs = np.nonzero(wrong)
        pa = PF.pixel_attrs(P, F, np.asarray(geoms[0]['UV'], np.float64), None, cam, n, ids_z[ys, xs], ys, xs)
        out['ids'][ys, xs] = ids_z[ys, xs]
        out['uv'][ys, xs, 0] = pa['u']
        out['uv'][ys, xs, 1] = 1.0 - pa['v']
        out['cos'][ys, xs] = pa['cos']
        out['depth'][ys, xs] = pa['zpix']
    if zall:                                                                         # флаг zbuffer_depth_all: глубина — из z-буфера везде, где он покрыл пиксель растра (id/UV/cos не трогаем); пиксели вне покрытия z-буфера остаются как есть
        sel = both & (zn > 0) & ~wrong
        out['depth'][sel] = zn[sel].astype(out['depth'].dtype)
        info['zbuf_depth_all_px'] = int(sel.sum())
    return out, info


def depth_mismatch(st: dict, zn: np.ndarray, both: np.ndarray, ids_z: np.ndarray, px_len: float) -> dict:
    """Мерка В (T-20261124-27, Крит): расхождение глубины этапа 4 (`depth.npz`, растр без z-буфера: на косых гранях плоскость экстраполируется за грань) и z-буфера на видимых пикселях растра, по корзинам cos
    (<0,2 / 0,2–0,4 / ≥0,4): доля пикселей с |Δ| > DEPTH_JUMP·px_len (столько `depth_band` считает разрывом), медиана |Δ|/px_len, доля пикселей, где id этапа 4 совпал с z-буфером. Здоровый растр — доля ≈ 0;
    у Крита на верхе медиана ≈ 1100 px_len, depth_band метил 99,9 % верха. Флаг мерки: `suspect` — доля > 0,2 в корзине cos<0,4 при ≥ 500 пикселей (гипотеза-порог до замера на круге 29)."""
    sel = both & (zn > 0)
    out = {}
    if not sel.any():
        return {'N/A': 'нет покрытия z-буфера'}
    dz = np.abs(st['depth'].astype(np.float64) - zn) / px_len
    same = st['ids'] == ids_z
    suspect = False
    for name, lo, hi in (('cos<0.2', 0.0, 0.2), ('cos0.2-0.4', 0.2, 0.4), ('cos>=0.4', 0.4, 9.0)):
        m = sel & (st['cos'] >= lo) & (st['cos'] < hi)
        k = int(m.sum())
        if k == 0:
            continue
        sh = float((dz[m] > DEPTH_JUMP).mean())
        out[name] = {'px': k, 'share_jump': round(sh, 4), 'median_px_len': round(float(np.median(dz[m])), 2), 'id_match': round(float(same[m].mean()), 4)}
        if hi <= 0.4 and k >= 500 and sh > 0.2:
            suspect = True
    out['suspect'] = suspect
    return out


def back_face_mask(geoms: list, st: dict):
    """T-201: ВТОРИЧНЫЙ признак поверх z-буфера (`zbuffer_fix`): основное — ближайшая грань в пикселе; знаковая нормаль решает ничью по глубине и снимает остатки (замкнутая форма — грань спиной видимой быть не может).
    Грани «спиной к камере» по ЗНАКОВОЙ нормали (порядок обхода) — этап 4 рисует кадр без z-буфера (дальние первыми по средней глубине граней) и берёт cos = |n·v|, поэтому у тонкой двойной стенки
    (фасад TRELLIS: передний и задний слой почти рядом) задняя грань может оказаться «видимой» и пройти и порог cos, и допуск глубины (её глубина — из неё же). → (bool на грань по всем геометриям | None, пометка)."""
    if not BACK_ON:
        return None, 'выключено'
    fr, note = cube_frame(geoms, st)
    if fr is None:
        return None, note
    P, C = fr['P'], fr['C']
    F = np.asarray(geoms[0]['F'], np.int64)
    nF = len(F)
    q = np.round(P / 1e-6).astype(np.int64)
    _, vid = np.unique(q, axis=0, return_inverse=True)
    Fv = vid.ravel()[F]
    e = np.concatenate([Fv[:, [0, 1]], Fv[:, [1, 2]], Fv[:, [2, 0]]])
    key = np.minimum(e[:, 0], e[:, 1]) * (int(vid.max()) + 1) + np.maximum(e[:, 0], e[:, 1])
    fl = (e[:, 0] < e[:, 1])
    o = np.argsort(key, kind='stable')
    ks, fl = key[o], fl[o]
    same = ks[1:] == ks[:-1]
    cons = float((fl[1:] != fl[:-1])[same].mean()) if same.any() else 0.0
    vol = float(np.einsum('ij,ij->i', P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum())
    if cons < BACK_WINDING_MIN or vol <= 0:
        return None, f'пропуск: обход граней не согласован ({cons:.3f}) или объём ≤ 0'
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    vv = (np.array([0.0, 0.0, 1.0])[None, :] if C is None else C[None, :] - P[F].mean(1))
    return ((fn * vv).sum(1) < 0.0), f'согласованность обхода {cons:.3f}'


def prune_panels(g: dict, fid: np.ndarray, occ: np.ndarray, known: np.ndarray, tex: np.ndarray, tex0: np.ndarray, prov: np.ndarray) -> int:
    """Страховка: панель (связная группа граней с изломом ≤ BACK_CREASE_DEG), крупная (≥ BACK_MIN_OCC занятых текселей геометрии), где с фото известно < BACK_MIN_SHARE, — известное на ней снимается
    (цвет заготовки, прежний этап 7 красит её тоном своей зоны). → число снятых текселей."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    F, V = g['F'], g['V']
    nF = len(F)
    _A, B, _cen, _ext = _face_graph(V, F)
    r, c = B.nonzero()
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    ok = np.abs((n[r] * n[c]).sum(1)) >= np.cos(np.radians(BACK_CREASE_DEG))
    G = coo_matrix((np.ones(int(ok.sum())), (r[ok], c[ok])), shape=(nF, nF)).tocsr()
    _k, lab = connected_components(G, directed=False)
    oc = np.bincount(fid[occ], minlength=nF).astype(np.float64)
    kc = np.bincount(fid[known & occ], minlength=nF).astype(np.float64)
    po, pk = np.bincount(lab, oc), np.bincount(lab, kc)
    bad = (po >= BACK_MIN_OCC * max(float(oc.sum()), 1.0)) & (pk > 0) & (pk < BACK_MIN_SHARE * np.maximum(po, 1.0))
    clear = known & occ & bad[lab[np.clip(fid, 0, None)]]
    tex[clear] = tex0[clear]
    known[clear] = False
    prov[clear] = 0
    return int(clear.sum())


def transfer(geoms: list, st: dict, prgb: np.ndarray, pmask: np.ndarray, cos_min: float = COS_MIN, tone: bool | None = None) -> dict:
    """Новые текстуры + маски «известно» по геометриям. Каждый занятый тексель идёт на фото СВОЕЙ точкой (карта грани, `face_maps`), берётся, если: его грань видна с углом лучше `cos_min`,
    глубина точки совпадает с буфером глубины камеры (не заслонена), точка внутри силуэта фото с отступом от края. Цвет — билинейно с фото; невидимое остаётся прежним.
    `tone` (None — из rules/tex-visible.json): Ш3б, тон с острого угла (`tone_oblique`) на неизвестных текселях, которые камера видит под углом ниже порога фактуры; known включает их (прочие этапы
    не перекрашивают), `known_photo` — только с фото (гейт и мерки), `prov` — карта провенанса (PROV: 1 direct, 2 splat, 3 hole, 4 synth)."""
    from scipy.ndimage import distance_transform_edt, map_coordinates
    use_tone = TONE_ON if tone is None else bool(tone)
    back, back_note = back_face_mask(geoms, st)
    back_info = {'back_cull': back_note}
    if back is not None and back.any():                                                              # грани спиной к камере из растра убираем (как нижняя полоса body_only): с них ничего не берётся
        hit = (st['ids'] >= 0) & (st['ids'] < len(back)) & back[np.clip(st['ids'], 0, len(back) - 1)]
        back_info.update({'back_faces_visible': int(np.unique(st['ids'][hit]).size), 'back_px_removed': int(hit.sum())})
        st = dict(st)
        st['ids'] = np.where(hit, -1, st['ids'])
        st['mask'] = st['mask'] & ~hit
        st['cos'] = np.where(hit, 0.0, st['cos'])
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
    texs, knowns, confs, stats, known_photos, provs = [], [], [], [], [], []
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
        prov = np.where(known, PROV['direct'], 0).astype(np.uint8)
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
        prov[take] = PROV['splat']
        n_splat = int(take.sum())
        hd, (hy, hx) = distance_transform_edt(~known, return_distances=True, return_indices=True)       # дыры между пикселями: ближайший взятый тексель не дальше HOLE_R
        fill = occ & ~known & (hd <= HOLE_R)
        tex[fill] = tex[hy[fill], hx[fill]]
        cmap[fill] = cmap[hy[fill], hx[fill]] * float(crr['conf_fill'])     # дыра — цвет соседа, уверенность вдвое ниже
        known = known | fill
        prov[fill] = PROV['hole']
        n_fill = int(fill.sum())
        isl_info = {}
        lg, lcol, li = line_gaps(tex, occ, known, ISL_LINE)                                            # тонкая щель: разрывы вдоль линии (мерка — всегда; закрываем при island_edge.enabled)
        isl_info.update(li)
        if ISL_ON and ISL_LINE.get('enabled', True) and lg.any():
            tex[lg] = lcol[lg]
            new_k = lg & ~known
            prov[new_k] = PROV['hole']
            cmap[new_k] = float(crr['conf_fill'])
            known = known | lg
            n_fill += int(new_k.sum())
            isl_info['line_ragged_share_after'] = line_gaps(tex, occ, known, ISL_LINE)[2]['line_ragged_share']       # мерка после закрытия (то, что осталось рваным)
        n_pruned = prune_panels(g, fid, occ, known, tex, g['tex'].astype(np.float64), prov) if (BACK_ON and PRUNE_ON) else 0
        known_photo = known.copy()                                                                     # известное С ФОТО (без тона): по нему считаются гейт и мерки
        tone_info, n_synth = {}, 0
        if use_tone:                                                                                    # Ш3б: тон с острого угла на наблюдаемых камерой неизвестных текселях
            tn = tone_oblique(tex, occ, known, fid, st, prgb, pmask, nogo, (dist_edge - EDGE_ERODE) / edge_px >= W_TAKE, int(offs[gi]), int(offs[gi + 1]), cos_min + W_TAKE * (COS_FULL - cos_min), g)
            tex[tn['take']] = tn['rgb'][tn['take']]
            known = known | tn['take']
            prov[tn['take']] = PROV['synth']
            tone_info, n_synth = tn['info'], int(tn['take'].sum())
        if ISL_ON and ISL_TONE.get('enabled', True):                                                    # тон у границы острова: не взятые рядом со взятыми — на плавный сдвиг к тону фото (остаются неизвестными)
            jb = island_jump(tex, occ, known_photo, known)                                              # скачок ДО: правило включается только там, где граница острова видна ступенькой (признак, не ID)
            isl_info['island_jump_before'] = jb
            if jb.get('bad'):
                tex, ti = island_tone(tex, g['tex'].astype(np.float64), occ, known_photo, known, ISL_TONE)
                isl_info.update(ti)
            else:
                isl_info['edge_tone_skip'] = 'скачка нет или не измерен' if jb.get('bad') is None else 'скачок в норме'
        isl_info['island_jump'] = island_jump(tex, occ, known_photo, known)
        gd, (iy, ix) = distance_transform_edt(~occ, return_distances=True, return_indices=True)     # желоб: ближайший занятый тексель на GUTTER пикселей наружу
        ring = (~occ) & (gd <= GUTTER)
        tex[ring] = tex[iy[ring], ix[ring]]
        texs.append(np.clip(tex + 0.5, 0, 255).astype(np.uint8))
        knowns.append(known)
        known_photos.append(known_photo)
        provs.append(prov)
        confs.append(np.where(known, cmap, 0.0).astype(np.float32))
        stats.append({'name': g['name'], 'T': T, 'occupied': int(occ.sum()), 'known': int(known_photo.sum()), 'known_synth': n_synth, **tone_info, **isl_info, **back_info, 'known_pruned_panels': n_pruned, 'faces_ok': int(fm['ok'].sum()), 'faces_seen': int((fm['cnt'] > 0).sum()), 'texels_taken': int(use.sum()), 'known_facemap': n_face, 'known_splat': n_splat, 'known_filled': n_fill})
    return {'tex': texs, 'known': knowns, 'known_photo': known_photos, 'prov': provs, 'conf': confs, 'stats': stats, 'depth_band_share': round(n_nogo / max(int(st['mask'].sum()), 1), 4), 'edge_bg_fringe_px': int((fringe & st['mask']).sum()), 'crease': crs}


def write_glb(geoms: list, texs: list, dst: str) -> None:
    """Те же форма и развёртка, текстура baseColor — новая (геометрии пишутся как есть, без слияния вершин)."""
    import trimesh
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    sc = trimesh.Scene()
    for g, t in zip(geoms, texs):
        m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], vertex_normals=VNM.geom_normals(g), process=False)      # NORMAL в файле (T-20261124-10/4): без него зритель шейдит гранями
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


HATCH_TINT = 225      # светлота подмешиваемого серого: непросмотренное — мягкая заливка цветом заготовки с лёгкой серой вуалью (не штриховка: на рёбрах мелких островов штриховка читалась как «трещины»)
HATCH_VEIL = 0.4


def hatch(tex: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Только для показа: непросмотренные тексели — цвет заготовки с лёгкой серой вуалью (подпись на листе — «не видно на фото»)."""
    out = tex.copy()
    miss = ~known
    out[miss] = np.clip((1.0 - HATCH_VEIL) * tex[miss].astype(np.float64) + HATCH_VEIL * HATCH_TINT, 0, 255).astype(tex.dtype)
    return out


def caption(im: np.ndarray, text: str) -> np.ndarray:
    """Подпись в левом нижнем углу плитки листа (шрифт с кириллицей; нет шрифта — стандартный)."""
    from PIL import ImageDraw, ImageFont
    pil = Image.fromarray(im)
    d = ImageDraw.Draw(pil)
    size = max(14, im.shape[0] // 40)
    font = None
    for fp in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/dejavu/DejaVuSans.ttf'):
        if os.path.exists(fp):
            font = ImageFont.truetype(fp, size)
            break
    if font is None:
        font = ImageFont.load_default()
    d.text((8, im.shape[0] - size - 10), text, fill=(90, 90, 90), font=font)
    return np.asarray(pil)


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
    out = {'silhouette_iou': round(float(iou), 4), 'known_share': round(kn / max(occ, 1), 4)}                  # kn — только с фото (stats['known'] без synth)
    out['known_visible_share'], out['visible_px'] = visible_known_share(geoms, st, tr)                           # мерка гейта (T-215): знаменатель — истинно видимое, не все тексели
    if any(s.get('known_synth') for s in tr['stats']):
        out['known_synth_share'] = round(sum(s.get('known_synth', 0) for s in tr['stats']) / max(occ, 1), 4)   # справочно: тон с острого угла (Ш3б), порога нет
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
    panels[1] = caption(panels[1], 'светлая вуаль — не видно на фото')
    for yaw in (sv['left']['yaw'], sv['right']['yaw']):
        im = np.asarray(LP.render_unlit(view_glb or dst_glb, yaw, sv['pitch'], size * 2))
        panels.append(caption(np.where((im[..., 3] > 8)[..., None], im[..., :3], 255).astype(np.uint8), 'светлая вуаль — не видно на фото'))
    Image.fromarray(np.concatenate(panels, axis=1)).save(path)
    return sv


# ── этап ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def role_family(role: str | None) -> str | None:
    """Роль каталога → семья паспорта типа (None — роли нет/тип неизвестен: правила по семье воздерживаются)."""
    if not role:
        return None
    try:
        return (MTP.get(role) or {}).get('family')
    except Exception:  # noqa: BLE001 — реестр не читается: без семьи правило не применяется
        return None


def save_leak_frame(path: str, maps: dict) -> None:
    """Кадр «до | после | карта утечки» вокруг найденных щелей (полный размер кадра камеры, отступ 60 px)."""
    lk = maps['leak']
    ys, xs = np.nonzero(lk)
    h, w = lk.shape
    y0, y1, x0, x1 = max(int(ys.min()) - 60, 0), min(int(ys.max()) + 60, h), max(int(xs.min()) - 60, 0), min(int(xs.max()) + 60, w)
    mp = maps['before'].copy()
    mp[lk] = (255, 40, 40)
    Image.fromarray(np.concatenate([maps['before'][y0:y1, x0:x1], maps['after'][y0:y1, x0:x1], mp[y0:y1, x0:x1]], 1)).save(path)


def run(glb: str, photo: str, pose_run: str, run_dir: str, sku: str, cos_min: float = COS_MIN, body_only: bool = False, role: str = '') -> dict:
    """Этап 6 для одного товара. Любая ошибка (форма не читается, нет файлов камеры, не та форма) — НЕ роняет пакет: пишет check.json passed=false с причиной (fail-closed, T-168)."""
    t0 = time.time()
    try:
        return _run(glb, photo, pose_run, run_dir, sku, cos_min, body_only, role)
    except Exception as e:  # noqa: BLE001 — причина уходит в check.json и в ответ, пакет идёт дальше
        d = PS.stage_dir(run_dir, sku, '06-visible')
        why = f'{type(e).__name__}: {e}'[:400]
        PS.write_check(d, '06-visible', sku, passed=False, metric={'name': 'silhouette_iou', 'value': 0.0, 'threshold': GATE['silhouette_iou'][0], 'op': '>='},
                       reason=f'этап 6 не выполнен: {why}', seconds=round(time.time() - t0, 1), needs_qwen=False, stage_error=why, pose_run=pose_run, photo_input=PS.photo_input(photo, pose_run))
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


# ── перёд/зад после переноса (T-20261123-43) ──────────────────────────────────────────────────────────────────────

def pose_edge_agree(pose_run: str) -> float | None:
    """Согласие кромок выбранной позы (pose.json: picked.edge.agree); нет файла/поля/кромки не измерены → None."""
    try:
        pj = json.load(open(os.path.join(pose_run, 'pose.json'), encoding='utf-8'))
        e = (pj.get('picked') or {}).get('edge') or {}
        return None if e.get('no_edges') or e.get('agree') is None else float(e['agree'])
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def edge_ref() -> float:
    """Порог «камере не верим» — один, rules/camera-check.json: edge_ref (копии нет)."""
    return float(json.load(open(os.path.join(SCOUT, 'rules', 'camera-check.json'), encoding='utf-8'))['edge_ref'])


def front_check(geoms: list, tr: dict, cam: dict | None, pose_run: str, shares_fn=None, flipped_fn=None, agree: float | None = None, ref: float | None = None) -> dict:
    """Вторая линия «перёд/зад» после переноса: доли известных текселей (known.png, как у листа) по сторонам (общая функция `front_axis.front_shares`, камера az этапа 4) и вердикт `front_flipped`.
    state: 'flipped' (зад известен больше перёда на margin И кромки позы < edge_ref — отказ 06), 'ok', 'n/a' (нет правил front_guard / камеры / данных / проверка выключена — не отказ). Пороги долей — sides-eval.json: front_guard."""
    out = {'state': 'n/a', 'why': ''}
    if not (R.get('front_check') or {}).get('enabled', True):
        out['why'] = 'выключено правилом front_check'
        return out
    if not cam or cam.get('az') is None:
        out['why'] = 'нет азимута камеры'
        return out
    try:
        sh_fn, fl_fn = shares_fn or FA.front_shares, flipped_fn or FA.front_flipped
        gi = int(np.argmax([int(np.asarray(k).sum()) for k in tr['known']]))      # как у листа (known.png этапа 6, front_guard): по части с наибольшим известным
        g = geoms[gi]
        shares = sh_fn(g['V'], g['F'], g['UV'], np.asarray(tr['known'][gi]), float(cam['az']))
        flipped = bool(fl_fn(shares))
    except (ImportError, KeyError, OSError, ValueError, TypeError) as e:       # нет модуля/блока front_guard — проверка неприменима
        out['why'] = f'нет свидетеля перёда: {type(e).__name__}: {str(e)[:120]}'
        return out
    agree = pose_edge_agree(pose_run) if agree is None else agree
    try:
        ref = edge_ref() if ref is None else ref
    except (OSError, KeyError, ValueError, TypeError) as e:                  # нет правил камеры в окружении этапа — порога «камере не верим» нет, проверка неприменима
        out.update({'why': f'нет порога edge_ref (rules/camera-check.json): {type(e).__name__}', 'shares': shares, 'front_flipped': flipped})
        return out
    out.update({'shares': shares, 'front_flipped': flipped, 'edge_agree': agree, 'edge_ref': ref})
    if flipped and agree is not None and agree < ref:
        out.update({'state': 'flipped', 'why': f"фото легло на сторону, противоположную перёду: известно у «зад» {shares.get('зад')} больше, чем у «перёд» {shares.get('перед')}, а согласие кромок камеры {agree:.2f} < {ref:g} — камере не верим (перёд/зад перепутаны)"})
    else:
        out.update({'state': 'ok', 'why': ('зад известен больше перёда, но кромки камеры в порядке — перёд не определён, не отказ' if flipped else '')})
    return out


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
    return {'row': int(rows[0]), 'frame_px': fpx, 'iou_top': float(ex.get('iou_top') or 0.0), 'bottom_shape_mismatch': True}


def _run(glb: str, photo: str, pose_run: str, run_dir: str, sku: str, cos_min: float = COS_MIN, body_only: bool = False, role: str = '') -> dict:
    t0 = time.time()
    d = PS.stage_dir(run_dir, sku, '06-visible')
    pin = PS.photo_input(photo, pose_run)                                 # какое фото подано (delight|raw|other): только запись в check.json (T-20261125-82)
    cg, cg_why = camera_gate(pose_run)
    bc = body_cut(pose_run) if (cg is False and body_only) else None
    lc = legs_cut(pose_run) if (body_only and bc is None) else None      # ножки не совпали (T-191/3): фото на них не переносим, кроме прошедших сверку; камера при этом прошла
    if cg is False and bc is None:                                   # вход не прошёл прежний гейт — этап его не берёт
        PS.write_check(d, '06-visible', sku, passed=False, reason=cg_why + ' — этап 6 вход не берёт, перенос не делался', seconds=round(time.time() - t0, 1),
                       needs_qwen=False, camera_failed=True, camera_gate='failed', pose_run=pose_run, photo_input=pin)
        return {'sku': sku, 'passed': False, 'reason': 'camera_gate', 'why': [cg_why]}
    geoms = load_shape(glb)
    st = load_stage(pose_run)
    st, zbuf_info = zbuffer_fix(geoms, st)                           # растр камеры с z-буфером: дальше и перенос, и мерки, и кадр берут его
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
                       camera=st['camera'], pose_run=pose_run, photo_input=pin)
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
    sl = SLK.run(prgb, pmask, st, geoms, role_family(role), None, SLK_ON)               # тень щели в известном (R-SHADOW-LEAK): выключено/чужая семья — prgb тот же объект, байты те же
    prgb = sl['prgb']
    sl['info']['outside_changed_px'] = sl.get('outside_changed_px')
    tr = transfer(geoms, st, prgb, pmask, cos_min)
    fchk = front_check(geoms, tr, st['camera'], pose_run)
    if fchk['state'] == 'flipped':                                   # фото на стороне, противоположной перёду, камере не верим: красить нечего (до 07)
        PS.write_check(d, '06-visible', sku, passed=False, reason='front_flipped: ' + fchk['why'], seconds=round(time.time() - t0, 1), needs_qwen=False, camera_failed=True,
                       camera_gate='front_flipped', camera=st['camera'], pose_run=pose_run, front_check=fchk, photo_input=pin)
        return {'sku': sku, 'passed': False, 'reason': 'front_flipped', 'why': [fchk['why']], 'front_check': fchk}
    dst = os.path.join(d, 'visible.glb')
    write_glb(geoms, tr['tex'], dst)
    for i, k in enumerate(tr['known']):
        Image.fromarray((k * 255).astype(np.uint8)).save(os.path.join(d, 'known.png' if i == 0 else f'known{i}.png'))
        Image.fromarray(np.clip(tr['conf'][i] * 255.0 + 0.5, 0, 255).astype(np.uint8)).save(os.path.join(d, 'conf.png' if i == 0 else f'conf{i}.png'))     # уверенность текселя 0…255 (T-194/1)
    for i, pv in enumerate(tr.get('prov', [])):                         # провенанс known: 0 нет, 1 direct, 2 splat, 3 hole, 4 synth (значения в PNG как есть)
        Image.fromarray(pv).save(os.path.join(d, 'prov.png' if i == 0 else f'prov{i}.png'))
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
    view = os.path.join(d, '_view.glb')                                 # для показа: непросмотренное — светлая вуаль + подпись; в visible.glb заготовка не тронута (этап 7 заливает её)
    write_glb(geoms, [hatch(t, k) for t, k in zip(tr['tex'], tr['known'])], view)
    after_vis = frame_from_tex(st, geoms, [hatch(t, k) for t, k in zip(tr['tex'], tr['known'])])
    side_views = frame(os.path.join(d, 'frame.png'), prgb, pmask, after_vis, dst, view_glb=view, cam=st['camera'])
    os.remove(view)
    leak_out = []
    if sl['maps'] is not None:
        save_leak_frame(os.path.join(d, 'shadow-leak.png'), sl['maps'])
        leak_out = ['shadow-leak.png']
    mm, why = gate(m, thin_pass)
    main = mm.pop('silhouette_iou')
    ok = not why
    PS.write_check(d, '06-visible', sku, passed=ok, metric={'name': 'silhouette_iou', **{k: main[k] for k in ('value', 'threshold', 'op')}}, metrics=mm,
                   reason='' if ok else '; '.join(why), seconds=round(time.time() - t0, 1), outputs=['visible.glb', 'known.png', 'conf.png', 'frame.png'] + leak_out, frame='frame.png',
                   needs_qwen=(not ok), cos_min=cos_min, camera=st['camera'], side_views=side_views, pose_run=pose_run, crease_shadow=crease_info, stats=tr['stats'], front_check=fchk, depth_band_share=tr['depth_band_share'], body_only=(cut_row is not None), form_defect=(None if bc is None else {'kind': 'bottom_shape_mismatch', 'about': 'ножки формы (этап 2) не совпали с фото (число/длина/наклон): камера годна только по корпусу, фото на ножки не переносилось', 'iou_top': round(bc['iou_top'], 4), 'row': cut_row}), registration_fit=reg, cut_row=cut_row, legs_block=(None if lc is None else {'why': lc['why'], 'trusted_legs': len(lc['boxes']), 'row': cut_row}), legs_left_to_stage8=(cut_row is not None), z_buffer=zbuf_info, shadow_leak=sl['info'], extra_metrics={k: v for k, v in m.items() if k not in GATE}, photo_input=pin)
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
            panels.append(caption(np.where((im[..., 3] > 8)[..., None], im[..., :3], 255).astype(np.uint8), 'светлая вуаль — не видно на фото'))
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
    ap.add_argument('--product-json', default='', help='product.json товара {sid,name,role,params} (путь во входе задания Salad): роль → допуск «зад корпусной» по паспорту типа (после 06, back_panel_stage); нет файла/роли — шаг не запускается')
    a = ap.parse_args()
    role = ''
    if a.product_json:
        try:
            role = (json.load(open(a.product_json, encoding='utf-8')) or {}).get('role') or ''
        except (OSError, ValueError):
            role = ''
    r = run(a.glb, a.photo, a.pose_run, a.run_dir, a.sku, body_only=a.body_only, role=role)
    if a.product_json:
        bp = BPS.run_stage(a.run_dir, a.sku, role, keep_original=False, pose_run=a.pose_run,      # согласие кромок — из pose.json прогона позы во входе (в папке товара на ноде его нет)
                           refusal='' if r.get('passed') else str(r.get('reason') or 'отказ без причины'))   # этап отказал — выход 06 не годится, зад не трогаем, но запись правила пишется
        r['back_panel'] = {'applied': bp['applied'], 'reason': bp['reason']}
    print(json.dumps(r, ensure_ascii=False, default=str)[:2000])
    return 0 if r['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
