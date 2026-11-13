#!/usr/bin/env python3
"""ОДИН AI-КАДР ГОСТИНОЙ ДЛЯ ПРОБЫ АГЕНТА (MASTER-agent-trial T7, T-20261109-13): кадр рендера 3D + состав сцены → одно
фото «как в объявлении» с плашкой `AI-generated visualisation — not a photograph` НА САМОЙ картинке.

ЧТО ПЕРЕИСПОЛЬЗУЕМ, А НЕ КОПИРУЕМ. Боевой путь «Сделать реалистичнее» (`draft_render.render(quality='realistic')`):
лист эталонов `draft_render._identity`, список товаров `improve_mode.product_list` (промпт v4), третий лист мягкого и декора
`improve_mode.third_sheet`, ворота «без листа товаров не платим» `improve_mode.paid_gate`, промпт `improve_mode.prompt_for`, вызов
шлюза `draft_render.gpt_edit`, исход одной меткой `draft_render.photo_outcome`. Отличие одно: у пробы ОДИН вид, а боевой промпт
написан под лист из двух видов с маджента-полосой — `single_view_prompt` меняет только фразы про два вида и полосу и ОТКАЗЫВАЕТ
(до оплаты), если после замены в тексте осталось хоть что-то про второй вид (промпт поменяли — тест и прогон это увидят).

КОНТРАКТ СО СТАДИЕЙ МЕБЕЛИ ПРОБЫ (T-12, `trial_demo.py`; T-13/2) — переделки там НЕ нужно, стадия читает то, что T-12 уже пишет:
  ~/scout-scenes/trial/<trial_id>/scene.json   (`trial_demo.build`) — поля, которые читаем:
    trial_id; status ∈ {ok, partial} (иначе отказ `trial_not_ready`, тур без фото);
    core.w, core.d — ядро гостиной, см (рендер и камера — в координатах ядра, как `trial_demo.frame_entry`);
    openings_core[] — {kind: window|door|balcony|opening, wall: south|north|west|east, offset_cm, width_cm, sill_cm?, height_cm?,
                       swing_cm?, hinge?} (`planner.models.Opening`; дверь без swing_cm → проём без полотна);
    variants[] — {style, post_ok, hard[], set_id, placements_core[] {role, x, y, rot, w, d, h, elev, corner, corner_left, section},
                  items[] {role, name, sid, img}} — товар места по роли; `img` — https:// или //…; меш — `flat215_demo._msid(sid)`.
  Камеру стадия мебели НЕ ставит и кадр НЕ рисует: ракурс героя (`pick_hero_camera`) и широкий кадр (`OVERSCAN`) — эта стадия.
  Выход — `~/scout-scenes/trial/<trial_id>/hero/` (hero.jpg, hero.json, sources/); запуск после мебели:
    python tools/scout/trial_hero.py --scene ~/scout-scenes/trial/<id> --out ~/scout-scenes/trial/<id>/hero --go [--style сканди]
  Стиль не задан — первый вариант без проблем. Бюджет 60 с: рендер ~23 с + модель ~18 с (замер 09.11); не уложились — отказ.

ВХОД — папка сцены (демо или своя):
  frame.jpg | frame.png   кадр рендера гостиной с мебелью (любая пропорция; режется по центру под размер запроса, 3:2)
  scene.json              {"room": {...}, "items": [{role, name, img, w, d, h, x, y, rot, ...}], "decor": [...], "style": "сканди",
                           "floor": {...}?, "walls": {...}?} — формат запроса страницы к сервису кадров (`draft_render.scene_from_request`);
                          `img` — https:// или file:// (относительный путь берётся от папки сцены)
ВЫХОД — папка `--out`:
  hero.jpg                фото с плашкой (только при успехе; без плашки картинку не сохраняем)
  sources/4-model-wide.jpg  ответ модели до обрезки широкого кадра (тоже с плашкой; для разбора отъезда)
  hero.json               {ok, model, quality, size, prompt_version, prompt_sha, timing{prep, model, post, total}, cost_usd,
                           cost_source, error, error_code, dry_run, ...}
  sources/                что ушло (или ушло бы) в модель: 1-frame.png, 2-ident.jpg, 3-extra.jpg, prompt.txt

  python tools/scout/trial_hero.py --scene DIR --out DIR            # СУХОЙ прогон: всё собрать, в модель не слать (бесплатно)
  python tools/scout/trial_hero.py --scene DIR --out DIR --go       # один платный кадр
  … --render [--cam hero|hero:N|scene]  # кадра в папке нет — нарисовать сервером одной камерой (полные меши; тяжёлое →
                                     # heavy-slot); hero — ракурс героя (по умолчанию), hero:1 — второй по счёту, scene — первая
                                     # камера сцены; кадр шире на OVERSCAN
  … --style лофт                     # сцена пробы T-12: какой вариант
  python tools/scout/trial_hero.py --prepare-demo demo-data.json --variant set1 --sheet лист.jpg --view 0 --scene DIR \\
         [--img-base ~/scout-scenes/flat215-demo]                   # папка сцены из демо (flat215): состав варианта + вид листа
Ключи: --budget 60 (с на весь шаг; кончился — отказ, тур отдаётся без фото), --size 1536x1024, --quality medium, --model ….
Код выхода: 0 — готово (или сухой прогон собран), 3 — отказ (hero.json с ошибкой, фото нет), 2 — неверный вход.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
# промпт и модель — как у рисующего процесса DEV (`tools/scout/systemd/remlab-render.service`): v4 читается при импорте improve_mode
os.environ.setdefault('IMPROVE_PROMPT', 'v4')

from PIL import Image, ImageDraw  # noqa: E402

BADGE_TEXT = 'AI-generated visualisation — not a photograph'
MODEL = os.environ.get('TRIAL_HERO_MODEL') or os.environ.get('REALISTIC_MODEL') or 'openai/gpt-image-2.5-sunburst'
QUALITY = os.environ.get('TRIAL_HERO_QUALITY', 'medium')
SIZE = os.environ.get('TRIAL_HERO_SIZE', '1536x1024')
BUDGET_S = float(os.environ.get('TRIAL_HERO_BUDGET_S', '60'))
SINGLE_TAG = 'single1'          # версия замены «два вида → один»; часть prompt_version в ответе

# ОДИН ВИД ВМЕСТО ЛИСТА: (было, стало). Блоки декора/мягкого/штор условные — замены, которых нет в тексте, пропускаются;
# что осталось про второй вид — ловит `_TWO_VIEW_LEFT` и отказывает до оплаты.
SINGLE_SUBS = [
    ('* IMAGE 1: one sheet containing TWO rendered views of the SAME furnished room, stacked vertically and separated by a magenta band.',
     '* IMAGE 1: one rendered view of the furnished room from a single camera.'),
    ('TASK: turn IMAGE 1 into two photorealistic views of a renovated room.',
     'TASK: turn IMAGE 1 into one photorealistic view of a renovated room.'),
    ('* the two-view layout or magenta separator;\n', ''),
    ('Keep the magenta band in exactly the same position, height and colour, with nothing drawn over it.\n\n', ''),
    (' Place each item ONCE and show it in both views if that surface is visible in both.', ' Place each item ONCE.'),
    ('show it in both views wherever that place is visible.', 'show it wherever that place is visible.'),
    ('hang them correctly and identically in both views', 'hang them correctly'),
    ('hung correctly and identical in both views.', 'hung correctly.'),
    ('The two views show the SAME room. Use exactly the same wall colour, floor material and direction, trim, door finish, window '
     'design and light temperature in both views.\n\n', ''),
    (' and must appear consistently in both views.', '.'),
    ('It is the same physical fixture in both views: the same design, materials, colour, scale, ceiling attachment point and '
     'switched-off state, shown only where naturally visible from each existing camera.',
     'It is switched off and shown only where naturally visible from the existing camera.'),
    # П1.50 — куски задания по составу набора (rules/photo-set-roles.json)
    (', keep them identical in both views and add no other', ' and add no other'),
    ('show them identically in both views wherever their place is visible.', 'show them wherever their place is visible.'),
    ('It is the same physical fixture in both views, shown only where naturally visible from each existing camera.',
     'It is shown only where naturally visible from the existing camera.'),
    ('Return ONE image with exactly the dimensions and proportions of IMAGE 1 and the same two-view layout.',
     'Return ONE image with exactly the dimensions and proportions of IMAGE 1.'),
]
_TWO_VIEW_LEFT = re.compile(r'magenta|both views|two views|two-view|each existing camera|view 1|view 2|stacked|separator|'
                            r'side by side', re.I)


class HeroError(RuntimeError):
    """Отказ шага с меткой (`code`) для json и очереди пробы: тур отдаётся без фото."""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code


def single_view_prompt(prompt: str) -> str:
    """Боевой промпт листа → промпт одного вида. Осталось упоминание второго вида/полосы — HeroError до оплаты."""
    for old, new in SINGLE_SUBS:
        prompt = prompt.replace(old, new)
    left = sorted({m.group(0).lower() for m in _TWO_VIEW_LEFT.finditer(prompt)})
    if left:
        raise HeroError('prompt_two_view', 'в промпте одного вида осталось про два вида: ' + ', '.join(left))
    return prompt


def fit_frame(img: Image.Image, size: str) -> Image.Image:
    """Кадр → ровно размер запроса: обрезка по центру до пропорции, затем масштаб (пропорция входа = пропорция ответа)."""
    tw, th = (int(x) for x in size.split('x'))
    img = img.convert('RGB')
    if abs(img.width / img.height - tw / th) > 0.002:
        if img.width / img.height > tw / th:
            cw = round(img.height * tw / th)
            x0 = (img.width - cw) // 2
            img = img.crop((x0, 0, x0 + cw, img.height))
        else:
            ch = round(img.width * th / tw)
            y0 = (img.height - ch) // 2
            img = img.crop((0, y0, img.width, y0 + ch))
    return img.resize((tw, th), Image.LANCZOS) if img.size != (tw, th) else img


BADGE_EM = float(os.environ.get('TRIAL_HERO_BADGE_EM', '0.022'))   # кегль плашки — доля высоты кадра (ведущий 09.11, T-13/2)
BADGE_ALPHA = 140                                                   # подложка ~55 % чёрного: полупрозрачная, текст белый


def badge(img: Image.Image, text: str = BADGE_TEXT) -> Image.Image:
    """Плашка на картинке — компактная «пилюля» внизу слева, как на лендинге (ведущий 09.11, T-13/2: прежняя занимала ~85 %
    ширины и закрывала диван). Кегль = 2,2 % высоты кадра → на 1536×1024 пилюля ≈ 40 % ширины; не влезла (узкий кадр) — кегль
    уменьшается до 90 % ширины. Подложка полупрозрачная тёмная, радиус — половина высоты."""
    import draft_render as DR
    img = img.convert('RGB')
    W, H = img.size
    fs = max(10, round(H * BADGE_EM))
    probe = ImageDraw.Draw(img)
    font = DR._font(fs)
    while fs > 8 and probe.textlength(text, font=font) > W * 0.90:
        fs -= 1
        font = DR._font(fs)
    tw = probe.textlength(text, font=font)
    padx, pady, m = round(fs * 0.75), round(fs * 0.42), round(min(W, H) * 0.022)
    box = (m, H - m - fs - 2 * pady, m + round(tw) + 2 * padx, H - m)
    over = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    d.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=(0, 0, 0, BADGE_ALPHA))
    d.text((box[0] + padx, (box[1] + box[3]) / 2), text, font=font, fill=(255, 255, 255, 255), anchor='lm')
    return Image.alpha_composite(img.convert('RGBA'), over).convert('RGB')


# ───────────────────────── кадр шире и обрезка назад (защита от «расширения кадра») ─────────────────────────
# Модель иногда чуть отъезжает (лофт 09.11: у правого края дорисованы ТВ и тумба — настоящие товары, но вне кадра 3D). Рендерим
# кадр на OVERSCAN шире (угол по тангенсу, сдвиг объектива пересчитан — исходный вид = ровно центр), отдаём модели широкий, ответ
# режем по центру назад. Отъезд модели тогда заполняется НАСТОЯЩИМ поясом рендера, а пояс уходит в обрезку.
OVERSCAN = float(os.environ.get('TRIAL_HERO_OVERSCAN', '1.08'))


def overscan_camera(fov_deg: float, shift_y: float, k: float) -> tuple[float, float]:
    """(угол, сдвиг) широкой камеры: tg(угол'/2) = k·tg(угол/2); сдвиг — доля высоты кадра, а кадр в k раз выше → сдвиг/k
    (`planner/scene.py`: v = H/2 − f·…/z + shift_y·H, f = (W/2)/tg(угол/2))."""
    import math
    return math.degrees(2 * math.atan(k * math.tan(math.radians(fov_deg) / 2))), shift_y / k


def crop_overscan(img: Image.Image, k: float, size: str | None = None) -> Image.Image:
    """Центр широкого кадра = исходный вид; `size` — вернуть в размер запроса (иначе — честные пиксели обрезки)."""
    if not k or k <= 1.0001:
        return img if not size else fit_frame(img, size)
    W, H = img.size
    cw, ch = round(W / k), round(H / k)
    x0, y0 = (W - cw) // 2, (H - ch) // 2
    out = img.crop((x0, y0, x0 + cw, y0 + ch))
    if size:
        tw, th = (int(x) for x in size.split('x'))
        out = out.resize((tw, th), Image.LANCZOS)
    return out


# ───────────────────────── ракурс «героя» ─────────────────────────
HERO_FOV = 72.0          # потолок владельца 01.09 (≈24 мм): шире — растяжение по краям
HERO_POSE = 3            # поза v3 (глаз 150, взгляд вниз 8°, сдвиг объектива) — `draft_render.photo_pose_heights`
HERO_INSET = 20.0        # глаз — в 20 см от стен (фотограф стоит у стены; 35 см не давали ни одного кадра у set6 flat215)
HERO_MIN_SOFA_CM = 185.0  # ближе — ножки дивана уходят под кадр: поза v3 видит пол с ≈ 1,9 м (низ кадра 38° вниз, глаз 150)
HERO_MAX_SIDE = 75.0     # диван виден спереди: угол между его «лицом» и камерой ≤ 75° (68° у set10 flat215 — лучший кадр 09.11)
_SKIP_VIS = ('ковёр', 'тв')


def _rbase(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role or '').split(' ')[0] if role else ''


def _view_dir(rot: float) -> tuple[float, float]:
    """Направление взгляда камеры запроса на плане (`draft_render.cams_from_request`: цель = x + 400·sin, y − 400·cos)."""
    import math
    a = math.radians(rot)
    return math.sin(a), -math.cos(a)


def _ang(eye, d, p) -> float:
    """Угол (°) между осью взгляда `d` и направлением на точку плана `p`; позади камеры — > 90."""
    import math
    vx, vy = p[0] - eye[0], p[1] - eye[1]
    n = math.hypot(vx, vy) or 1e-9
    return math.degrees(math.acos(max(-1.0, min(1.0, (vx * d[0] + vy * d[1]) / n))))


def _ray_to_wall(eye, d, W: float, D: float) -> float:
    ts = []
    for c, dc, lim in ((eye[0], d[0], W), (eye[1], d[1], D)):
        if dc > 1e-9:
            ts.append((lim - c) / dc)
        elif dc < -1e-9:
            ts.append(-c / dc)
    return min(ts) if ts else 0.0


def _wall_point(o, W: float, D: float, t: float) -> tuple[float, float]:
    """Точка проёма на стене: `offset_cm` — от начала стены (запад→восток / юг→север), юг — y=0 (`planner/models.py:Opening`)."""
    s = o.offset_cm + t * o.width_cm
    return {'south': (s, 0.0), 'north': (s, D), 'west': (0.0, s), 'east': (W, s)}[str(getattr(o.wall, 'value', o.wall))]


def pick_hero_camera(room, placements, fov: float = HERO_FOV, rank: int = 0) -> dict | None:
    """РАКУРС ГЕРОЯ ПО ГЕОМЕТРИИ СЦЕНЫ, БЕЗ ПЛАТНОГО (ведущий 09.11, T-13/2: «афиша» C1 flat215 смотрит из-за дивана — слабый
    кадр). Перебор: глаз — сетка ~20 см по периметру в `HERO_INSET` (20 см) от стен, поворот — каждые 3°.
    Жёстко: диван ЦЕЛИКОМ в кадре по горизонтали, камера спереди дивана (не со спины и не сбоку > `HERO_MAX_SIDE` = 75°), ближняя
    точка дивана ≥ `HERO_MIN_SOFA_CM` (185 см — иначе низ кадра режет ножки), глаз не внутри мебели (+20 см). Счёт: окно в кадре
    (доля ширины проёма × косинус угла к окну — окно «вскользь» почти не считается) ×2, доля предметов целиком в кадре, глубина
    взгляда до стены («не в стену»), вид на диван в три четверти (20–70°), угол комнаты, диван ближе к центру кадра; минус —
    высокий предмет между глазом и диваном, предметы, обрезанные краем кадра, и особенно обрезанные ближе 1,5 м от глаза
    (передний план «куском»). Окна в кадре нет ни у одного кандидата — лучший без окна (`why.window` = 0). Дивана нет — кресло;
    нет и его — None (решает автоподбор `draft_render.demo_cams`). `rank` — N-я по счёту точка глаза (лучший поворот на
    каждую; «другой ракурс» без нового расчёта), в ответе `alternatives` — четыре лучших. Ответ — камера в формате запроса (`cams`), её ставит
    `draft_render.cams_from_request` — то же единственное место решения ракурса, что у черновика и платного улучшения."""
    import math
    from planner.geometry import facing_vector, footprint
    W, D = float(room.width_cm), float(room.depth_cm)
    seat = next((p for p in placements if _rbase(p.role) == 'диван' and p.item), None) \
        or next((p for p in placements if _rbase(p.role) == 'кресло' and p.item), None)
    if seat is None:
        return None
    polys = {id(p): footprint(p) for p in placements if p.item}
    sofa = polys[id(seat)]
    sofa_pts = list(sofa.exterior.coords)[:-1]
    sc = (sofa.centroid.x, sofa.centroid.y)
    fv = facing_vector(seat.rot)
    wins = [o for o in room.openings if str(getattr(o.kind, 'value', o.kind)) in ('window', 'balcony')]
    win_pts = [[_wall_point(o, W, D, t) for t in (0.1, 0.3, 0.5, 0.7, 0.9)] for o in wins]
    _N_IN = {'south': (0.0, 1.0), 'north': (0.0, -1.0), 'west': (1.0, 0.0), 'east': (-1.0, 0.0)}
    win_n = [_N_IN[str(getattr(o.wall, 'value', o.wall))] for o in wins]
    vis = [p for p in placements if p.item and _rbase(p.role) not in _SKIP_VIS]
    blockers = [polys[id(p)].buffer(20) for p in vis]
    tall = [polys[id(p)] for p in vis if p is not seat and (p.item.h_cm or 0) >= 110 and min(p.item.w_cm, p.item.d_cm) >= 30]
    from shapely.geometry import LineString, Point
    half = fov / 2
    eyes = []
    nx, ny = max(4, round((W - 2 * HERO_INSET) / 20)), max(4, round((D - 2 * HERO_INSET) / 20))   # шаг ≈ 20 см вдоль стен
    for e in ([(HERO_INSET + i / nx * (W - 2 * HERO_INSET), y) for i in range(nx + 1) for y in (HERO_INSET, D - HERO_INSET)]
              + [(x, HERO_INSET + j / ny * (D - 2 * HERO_INSET)) for j in range(ny + 1) for x in (HERO_INSET, W - HERO_INSET)]):
        e = (round(e[0], 1), round(e[1], 1))
        if e not in eyes:
            eyes.append(e)
    corners = {(round(x, 1), round(y, 1)) for x in (HERO_INSET, W - HERO_INSET) for y in (HERO_INSET, D - HERO_INSET)}
    best = []
    for eye in eyes:
        pt = Point(eye)
        if any(b.contains(pt) for b in blockers):
            continue
        vx, vy = eye[0] - sc[0], eye[1] - sc[1]
        dist = math.hypot(vx, vy) or 1e-9
        front = (vx * fv[0] + vy * fv[1]) / dist
        near = min(math.hypot(eye[0] - x, eye[1] - y) for x, y in sofa_pts)
        if front < math.cos(math.radians(HERO_MAX_SIDE)) or near < HERO_MIN_SOFA_CM:
            continue
        occl = any(LineString([eye, sc]).intersects(tp) for tp in tall)
        side = math.degrees(math.acos(max(-1.0, min(1.0, front))))
        tq = 1.0 if 20 <= side <= 70 else 0.5 if side < 20 else 0.0
        # окно «лицом»: доля проёма в кадре × косинус угла, под которым его видно (с ребра — почти ноль; set6 09.11)
        face = []
        for ws, (nxw, nyw) in zip(win_pts, win_n):
            cx, cy = ws[2]
            dd = math.hypot(eye[0] - cx, eye[1] - cy) or 1e-9
            face.append(max(0.0, ((eye[0] - cx) * nxw + (eye[1] - cy) * nyw) / dd))
        pts_of = {id(p): list(polys[id(p)].exterior.coords)[:-1] for p in vis}
        close = {id(p) for p in vis if p is not seat and min(math.hypot(eye[0] - x, eye[1] - y) for x, y in pts_of[id(p)]) < 150}
        for rot in range(0, 360, 3):
            d = _view_dir(rot)
            if any(_ang(eye, d, q) > half - 2 for q in sofa_pts):
                continue
            wv = [sum(1 for q in ws if _ang(eye, d, q) <= half - 1) / len(ws) for ws in win_pts]
            win = max((w * f for w, f in zip(wv, face)), default=0.0)
            inside = {id(p): [_ang(eye, d, q) <= half for q in pts_of[id(p)]] for p in vis}
            full = sum(1 for v in inside.values() if all(v))
            cut = sum(1 for v in inside.values() if any(v) and not all(v))          # обрезан краем кадра
            near_cut = sum(1 for k, v in inside.items() if k in close and any(v))   # ближе 1,5 м — срежет низ кадра
            depth = _ray_to_wall(eye, d, W, D)
            score = (2.0 * win + 1.0 * full / max(1, len(vis)) + 0.8 * min(1.0, depth / (0.8 * max(W, D))) + 0.6 * tq
                     + 0.4 * (eye in corners) + 0.3 * (1 - _ang(eye, d, sc) / half) - 1.5 * occl - 0.25 * cut - 0.6 * near_cut)
            best.append((round(score, 4), win > 0.15, eye, rot, {'window': round(win, 2), 'full_items': f'{full}/{len(vis)}',
                                                                  'cut': cut, 'near': near_cut, 'depth_cm': round(depth),
                                                                  'sofa_side_deg': round(side), 'corner': eye in corners,
                                                                  'occluded': occl, 'sofa_cm': round(near)}))
    if not best:
        return None
    pool = [b for b in best if b[1]] or best
    by_eye = {}
    for b in sorted(pool, key=lambda b: (-b[0], b[3])):     # лучший поворот на каждую точку глаза
        by_eye.setdefault(b[2], b)
    ranked = list(by_eye.values())
    score, _, eye, rot, why = ranked[min(max(0, rank), len(ranked) - 1)]
    return {'name': 'hero', 'x': eye[0], 'y': eye[1], 'rot': float(rot), 'fov': fov, 'pose': HERO_POSE, 'score': score, 'why': why,
            'rank': min(max(0, rank), len(ranked) - 1),
            'alternatives': [{'x': b[2][0], 'y': b[2][1], 'rot': float(b[3]), 'score': b[0]} for b in ranked[:4]]}


def edge_risk(room, placements, cam_xy, rot: float, fov: float = HERO_FOV, k: float = OVERSCAN) -> list:
    """КРУПНОЕ У КРАЯ КАДРА — ДО ОПЛАТЫ, БЕСПЛАТНО. Предметы (≥ 60 см или выше 1 м), чей след вне итогового кадра, но в
    пределах 15° за краем: их модель и «дотягивает» в кадр при отъезде (лофт 09.11: ТВ и тумба). Пояс OVERSCAN их уже несёт
    настоящими — список в json для разбора, не отказ. Пиксельной проверки после модели нет: стены, шторы и картины модель
    меняет законно, дешёвое сравнение краёв с рендером ловит их чаще, чем лишнюю мебель (вывод — в отчёте T-13/2)."""
    from planner.geometry import footprint
    half, d, out = fov / 2, _view_dir(rot), []
    import math
    for p in placements:
        if not p.item or _rbase(p.role) in ('ковёр',) or (max(p.item.w_cm, p.item.d_cm) < 60 and (p.item.h_cm or 0) < 100):
            continue
        angs = [_ang(cam_xy, d, q) for q in list(footprint(p).exterior.coords)[:-1]]
        lo = min(angs)
        if lo > half and lo <= half + 15:
            c = footprint(p).centroid
            vx, vy = c.x - cam_xy[0], c.y - cam_xy[1]
            side = 'right' if vx * -d[1] + vy * d[0] > 0 else 'left'      # право кадра на плане — (−dy, dx), `planner/scene.py`
            out.append({'role': p.role, 'side': side, 'beyond_deg': round(lo - half, 1),
                        'in_overscan': lo <= math.degrees(math.atan(k * math.tan(math.radians(half))))})
    return out


def _abs_img(url, base: str):
    if not url or str(url).startswith(('http://', 'https://', 'file://', '//')):
        return url
    return 'file://' + os.path.abspath(os.path.join(base, str(url)))


def render_frame(payload: dict, size: str = SIZE, cam_mode: str = 'hero', k: float = OVERSCAN) -> tuple[Image.Image, dict]:
    """КАДР РИСУЕМ САМИ ОДНОЙ КАМЕРОЙ. Тот же рендер полных мешей, что у боевого `improve_mode.build` (`draft_render.scene3d_frame`),
    но одна камера и сразу в размер запроса. Камера: `cam_mode='hero'` — `pick_hero_camera` (не нашлась — первая из `cams` сцены /
    автоподбор), `'scene'` — первая из `cams` сцены (у демо — «афиша» C1). Кадр шире в `k` раз (`overscan_camera`): исходный вид —
    его центр. Меш — по `msid`/`sid`, экземпляр комплекта — меш базовой роли."""
    os.environ.setdefault('SCENE3D_QUALITY', 'full')
    import draft_render as DR
    from planner.scene import Camera
    DR.S3_LITE[0] = False                                 # в платный запрос — только полная геометрия (как improve_mode.build)
    room, placements, photos = DR.scene_from_request(payload)
    hero = None
    if cam_mode.startswith('hero'):                       # 'hero' | 'hero:1' — N-й ракурс героя
        hero = pick_hero_camera(room, placements, rank=int(cam_mode.split(':')[1]) if ':' in cam_mode else 0)
    c = DR.cams_from_request(room, placements, {'cams': [hero]} if hero else payload)[0]
    tw, th = (int(x) for x in size.split('x'))
    fov, shift = overscan_camera(c.fov_deg, getattr(c, 'shift_y', 0.0) or 0.0, k)
    cam = Camera(name=c.name, eye=c.eye, target=c.target, fov_deg=fov, width=tw, height=th, shift_y=shift)
    rot = hero['rot'] if hero else _rot_of(c.eye, c.target)
    risk = edge_risk(room, placements, (c.eye[0], c.eye[2]), rot, c.fov_deg, k)
    sid = {it['role']: (it.get('msid') or it.get('sid')) for it in payload.get('items') or [] if it.get('role')}
    for role in list(sid):
        base = re.sub(r'\s+\d+$', '', role)
        if not sid[role] and base != role and sid.get(base):
            sid[role] = sid[base]
    for d in DR.decor_split(payload)[0]:
        sk = d.get('sku') or {}
        if d.get('role') and (sk.get('msid') or sk.get('sid')):
            sid[d['role']] = sk.get('msid') or sk.get('sid')
    img, diag = DR.scene3d_frame(room, placements, cam, sid, photos)
    return img, {'camera': c.name, 'hero': hero, 'eye': [round(v, 1) for v in c.eye], 'fov': c.fov_deg, 'overscan': k,
                 'edge_risk': risk, 'clay': sorted(set(r for r in (diag.get('clay') or []) if r != 'тв'))}


def _rot_of(eye, target) -> float:
    """Поворот камеры запроса по глазу и цели (обратное к `_view_dir`)."""
    import math
    return math.degrees(math.atan2(target[0] - eye[0], -(target[2] - eye[2]))) % 360


def _msid(sid):
    """Какой меш грузит сцена — ОДНО правило с демо (`flat215_demo._msid`, привязка `room_bindings`); нет модуля — sid как есть."""
    if not sid:
        return None
    try:
        import flat215_demo as FD
        return FD._msid(sid)
    except Exception:  # noqa: BLE001 — без привязки предмет станет clay-формой, а не уронит шаг
        return sid


def is_trial_scene(d) -> bool:
    return isinstance(d, dict) and bool(d.get('trial_id')) and isinstance(d.get('core'), dict) and isinstance(d.get('variants'), list)


def payload_from_trial(sc: dict, style: str | None = None) -> dict:
    """СЦЕНА ПРОБЫ (T-12, `trial_demo.build` → `~/scout-scenes/trial/<id>/scene.json`) → запрос как у страницы
    (`draft_render.scene_from_request`). Координаты — ядра (`core.w × core.d`, `openings_core`, `placements_core`) — в них же
    рендер T-12 (`trial_demo.frame_entry`). Дверь без зоны открывания (стык с проходом) — проём без полотна, как у T-12. Товар
    места — из `items` варианта по роли (экземпляр «стул 2» — по базовой роли); меш — `_msid(sid)`. Стиль: заданный; нет — первый
    вариант без проблем (`post_ok` и пустой `hard`), иначе первый."""
    if sc.get('status') not in ('ok', 'partial'):
        raise HeroError('trial_not_ready', f'сцена пробы {sc.get("trial_id")}: статус {sc.get("status")!r}')
    vs = sc.get('variants') or []
    if style:
        v = next((x for x in vs if x.get('style') == style), None)
        if v is None:
            raise HeroError('bad_input', f'в сцене пробы нет стиля {style!r} (есть: {[x.get("style") for x in vs]})')
    else:
        v = next((x for x in vs if x.get('post_ok') and not x.get('hard')), vs[0] if vs else None)
    if v is None:
        raise HeroError('bad_input', 'в сцене пробы нет вариантов')
    if not isinstance(sc.get('openings_core'), list):
        # окна и двери ядра — часть контракта: без них кадр без окон и не совпадает с туром (сцены T-12 15:08 — null)
        raise HeroError('trial_no_openings', f'сцена пробы {sc.get("trial_id")}: openings_core не задан')
    if not v.get('placements_core'):
        raise HeroError('trial_empty_variant', f'сцена пробы {sc.get("trial_id")}: у стиля {v.get("style")!r} нет расстановки')
    sku = {it.get('role'): it for it in v.get('items') or [] if it.get('role')}
    items = []
    for q in v.get('placements_core') or []:
        if not q.get('w') or not q.get('role'):
            continue
        s = sku.get(q['role']) or sku.get(re.sub(r'\s+\d+$', '', q['role'])) or {}
        it = {k: q.get(k) for k in ('role', 'x', 'y', 'rot', 'w', 'd', 'h', 'elev', 'corner', 'corner_left', 'section')}
        it.update(name=s.get('name'), img=s.get('img'), sid=s.get('sid'), msid=_msid(s.get('sid')))
        items.append({k: x for k, x in it.items() if x is not None})
    ops = []
    for o in sc.get('openings_core') or []:
        o = {k: x for k, x in o.items() if not str(k).startswith('_')}
        if o.get('kind') == 'door' and not o.get('swing_cm'):
            o['kind'] = 'opening'
        ops.append(o)
    core = sc['core']
    return {'room': {'w': core['w'], 'd': core['d'], 'openings': ops, 'radiators': []}, 'items': items, 'decor': [],
            'style': v.get('style') or '', 'variant': v.get('set_id'), 'source': f'trial:{sc.get("trial_id")}:{v.get("style")}'}


def load_scene(scene_dir: str, render: bool = False, style: str | None = None,
               cam_mode: str = 'hero', size: str = SIZE) -> tuple[dict, Image.Image]:
    """Папка сцены → (запрос как у страницы, кадр). Пути картинок товаров — абсолютные. Кадра нет и `render` — рисуем сами.
    Сцена пробы T-12 (`is_trial_scene`) — всегда рисуем сами: ракурс героя и широкий кадр — часть этой стадии."""
    sj = os.path.join(scene_dir, 'scene.json')
    if not os.path.exists(sj):
        raise HeroError('bad_input', f'в {scene_dir} нет scene.json')
    try:
        payload = json.load(open(sj, encoding='utf-8'))
    except ValueError as e:
        raise HeroError('bad_input', f'scene.json не читается: {e}') from None
    if is_trial_scene(payload):
        payload, render = payload_from_trial(payload, style), True
        fp = None
    else:
        fp = next((os.path.join(scene_dir, n) for n in ('frame.jpg', 'frame.png') if os.path.exists(os.path.join(scene_dir, n))), None)
    if fp is None and not render:
        raise HeroError('bad_input', f'в {scene_dir} нужны scene.json и frame.jpg|png')
    if not isinstance(payload, dict) or not payload.get('room') or not payload.get('items'):
        raise HeroError('bad_input', 'scene.json без room/items')
    for it in payload['items']:
        it['img'] = _abs_img(it.get('img'), scene_dir)
    for d in payload.get('decor') or []:
        sk = d.get('sku') or {}
        if sk.get('img'):
            sk['img'] = _abs_img(sk['img'], scene_dir)
    if fp is None:
        img, info = render_frame(payload, size, cam_mode=cam_mode)
        payload['_rendered'] = info
        return payload, img
    return payload, Image.open(fp).convert('RGB')


def items_from_variant(v: dict, img_base: str) -> list:
    """Предметы варианта демо (`sku` вложен) → плоский формат запроса (как `improve_mode.variant_payload`): экземпляр комплекта
    («стул 2» без своего товара) наследует товар базовой роли."""
    items = []
    for it in v.get('items') or []:
        sku = it.get('sku') or {}
        items.append({'role': it['role'], 'x': it['x'], 'y': it['y'], 'rot': it.get('rot'), 'w': it.get('w'), 'd': it.get('d'),
                      'h': it.get('h'), 'elev': it.get('elev'), 'hung': sku.get('hung') if it.get('hung') is None else it.get('hung'),
                      'corner': it.get('corner'), 'section': it.get('section'), 'sid': sku.get('sid'), 'msid': sku.get('msid'),
                      'name': sku.get('name'), 'img': _abs_img(sku.get('img'), img_base)})
    by_role = {it['role']: it for it in items if it.get('name')}
    for it in items:
        if not it.get('name'):
            src = by_role.get(re.sub(r'\s+\d+$', '', it['role']))
            if src:
                for k in ('sid', 'msid', 'name', 'img'):
                    it[k] = src.get(k)
    return [{k: v for k, v in it.items() if v is not None} for it in items]


def prepare_demo(demo_json: str, variant: str, sheet: str, view: int, scene_dir: str, img_base: str | None = None) -> str:
    """Папка сцены из демо: состав варианта `variant` из `demo-data.json` + вид №`view` листа двух видов (кадры исходника
    «Сделать реалистичнее» `~/scout-scenes/src/improve-*/1-ОТПРАВЛЯЕМ-лист-двух-видов.jpg`). Живые файлы только читаются;
    `img_base` — папка, от которой считаются `img/…` товаров (живое демо), по умолчанию — папка `demo-data.json`."""
    d = json.load(open(demo_json, encoding='utf-8'))
    v = next((x for x in d.get('variants') or [] if x.get('id') == variant or x.get('title') == variant), None)
    if v is None:
        raise HeroError('bad_input', f'нет варианта {variant!r}')
    base = os.path.abspath(img_base) if img_base else os.path.dirname(os.path.abspath(demo_json))
    decor = []
    for x in v.get('decor') or []:
        x = json.loads(json.dumps(x))
        if (x.get('sku') or {}).get('img'):
            x['sku']['img'] = _abs_img(x['sku']['img'], base)
        decor.append(x)
    payload = {'room': d['room'], 'items': items_from_variant(v, base), 'decor': decor, 'style': v.get('style') or '',
               'variant': v.get('id'), 'source': f'demo:{d.get("apartment_id") or "?"}:{v.get("id")}',
               'cams': [{k: c[k] for k in ('name', 'x', 'y', 'rot', 'fov', 'pose') if k in c} for c in (v.get('cams') or [])]}
    os.makedirs(scene_dir, exist_ok=True)
    json.dump(payload, open(os.path.join(scene_dir, 'scene.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if not sheet:
        return scene_dir                                  # без листа — только scene.json (кадр нарисует --render)
    im = Image.open(sheet).convert('RGB')
    import numpy as np
    a = np.asarray(im).astype(int)
    rows = ((a[..., 0] > 170) & (a[..., 2] > 170) & (a[..., 1] < 110)).mean(axis=1) > 0.5
    idx = np.where(rows)[0]
    if len(idx) >= 8:
        views = [im.crop((0, 0, im.width, int(idx[0]))), im.crop((0, int(idx[-1]) + 1, im.width, im.height))]
    else:
        views = [im]
    views[min(view, len(views) - 1)].save(os.path.join(scene_dir, 'frame.jpg'), quality=93)
    return scene_dir


def build(payload: dict, frame: Image.Image, size: str = SIZE) -> dict:
    """Всё, что уходит в модель: кадр под размер, лист эталонов, третий лист (декор вне сцены и мягкое), промпт одного вида."""
    import draft_render as DR
    import improve_mode as IM
    items = payload.get('items') or []
    # СОСТАВ (П1.50): кадр — сцена сервера, нарисован настольный декор `decor_split[0]` — карточками на лист эталонов
    plan = IM.decor_plan(payload, DR.decor_split(payload)[0])
    C = IM.compose(payload, items, plan)
    photos = {it['role']: DR.photo(it.get('img')) for it in items + C['extra'] if it.get('img') and it.get('role')}
    for it in items:                                     # «стул 2» — фото базовой роли
        base = re.sub(r'\s+\d+$', '', it.get('role') or '')
        if photos.get(it.get('role')) is None and photos.get(base) is not None:
            photos[it['role']] = photos[base]
    ident = None
    try:
        sheet_items = items + C['extra']
        ident = DR._identity([{'role': it['role'], 'n': i + 1} for i, it in enumerate(sheet_items) if it.get('name')], photos,
                             {it['role']: it for it in sheet_items if it.get('role')})
    except Exception as e:  # noqa: BLE001 — отказ решают ворота ниже
        print(f'  лист эталонов не собрался: {str(e)[:80]}')
    decor, soft = C['decor'], C['soft']
    extra = None
    if decor or soft:
        try:
            extra = IM.third_sheet(decor, soft, C['n3'])
        except Exception as e:  # noqa: BLE001
            print(f'  третий лист не собрался: {str(e)[:80]}')
    if extra is None:
        decor, soft = [], []
        C['groups'] = IM.set_groups(payload, items, plan['kept'], [], C['n3'])
    prods = None
    if IM.PROMPT_V4:
        try:
            prods = IM.product_list(items, photos)
        except Exception as e:  # noqa: BLE001
            print(f'  список товаров не собрался: {str(e)[:80]}')
    fl, wl = payload.get('floor') or {}, payload.get('walls') or {}
    base_prompt = IM.prompt_for(payload.get('style') or '', decor, fl.get('title') or fl.get('id') or None,
                                wl.get('title') or wl.get('id') or None, None, prods, IM.soft_list(soft, C['n3'] + len(decor), items),
                                room=IM.room_kind(payload), groups=C['groups'], kept=C['kept'], n3=C['n3'])
    prompt = single_view_prompt(base_prompt)
    named = [it for it in items if it.get('name')]
    return {'frame': fit_frame(frame, size), 'ident': ident, 'dsheet': extra, 'prompt': prompt, 'size': size,
            'prods_failed': IM.PROMPT_V4 and not prods, 'prompt_version': f'{IM.PROMPT_VERSION}-{SINGLE_TAG}',
            'prompt_sha': IM.prompt_sha(prompt), 'n_items': len(named),
            'n_photos': sum(1 for it in named if photos.get(it['role']) is not None), 'n_extra': len(decor) + len(soft)}


MIN_PHOTO_SHARE = 0.75


def photo_gate(built: dict) -> None:
    """БЕЗ ФОТО ТОВАРОВ НЕ ПЛАТИМ. `paid_gate` проверяет, что лист эталонов собран, но лист из карточек «фото нет» он пропускает
    (найдено сухим прогоном 09.11: путь к `img/` не тот — 0 фото из 9, лист собран). Модель тогда рисует товары по названию —
    «не тот» набор за деньги. Порог — 3/4 позиций с фото."""
    n, k = built.get('n_items') or 0, built.get('n_photos') or 0
    if n == 0 or k < MIN_PHOTO_SHARE * n:
        raise HeroError('no_product_photos', f'фото товаров {k} из {n} — платный вызов не делаю')


def _save_sources(out: str, built: dict) -> None:
    src = os.path.join(out, 'sources')
    os.makedirs(src, exist_ok=True)
    built['frame'].save(os.path.join(src, '1-frame.png'))
    if built.get('ident') is not None:
        built['ident'].save(os.path.join(src, '2-ident.jpg'), quality=88)
    if built.get('dsheet') is not None:
        built['dsheet'].save(os.path.join(src, '3-extra.jpg'), quality=88)
    open(os.path.join(src, 'prompt.txt'), 'w', encoding='utf-8').write(built['prompt'])


def _write_json(out: str, res: dict) -> None:
    p = os.path.join(out, 'hero.json')
    tmp = p + '.tmp'
    json.dump(res, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def run(scene_dir: str, out: str, go: bool = False, budget_s: float = BUDGET_S, size: str = SIZE, quality: str = QUALITY,
        model: str = MODEL, render: bool = False, style: str | None = None, cam_mode: str = 'hero') -> dict:
    """Шаг пробы целиком. Никогда не бросает: итог — словарь (он же hero.json); `ok` False — тур отдаётся без фото."""
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    res = {'ok': False, 'dry_run': not go, 'model': model, 'quality': quality, 'size': size, 'badge': BADGE_TEXT,
           'budget_s': budget_s, 'timing': {}, 'cost_usd': None, 'cost_source': None, 'error': None, 'error_code': None,
           'scene': os.path.abspath(scene_dir), 'image': None}
    try:
        import draft_render as DR
        import improve_mode as IM
        payload, frame = load_scene(scene_dir, render=render, style=style, cam_mode=cam_mode, size=size)
        k = 1.0
        if payload.get('_rendered'):
            res['timing']['render'] = round(time.time() - t0, 2)
            res['rendered'] = payload.pop('_rendered')
            k = float(res['rendered'].get('overscan') or 1.0)
        res['overscan'] = k
        built = build(payload, frame, size)
        res.update(prompt_version=built['prompt_version'], prompt_sha=built['prompt_sha'], n_items=built['n_items'],
                   n_extra=built['n_extra'], style=payload.get('style') or '', source=payload.get('source'))
        _save_sources(out, built)
        try:
            IM.paid_gate(built)                               # без листа товаров не платим (room-photos-07 п.3)
        except DR.NoProductSheet as e:
            raise HeroError('no_product_sheet', str(e)) from None
        photo_gate(built)
        res['n_photos'] = built['n_photos']
        res['timing']['prep'] = round(time.time() - t0, 2)
        imgs = [built['frame'], built['ident']] + ([built['dsheet']] if built.get('dsheet') is not None and 'IMAGE 3' in built['prompt']
                                                   else [])
        if not go:
            # сухой прогон: плашка на ВХОДНОМ кадре — проверить читаемость бесплатно; в модель ничего не ушло
            badge(crop_overscan(built['frame'], k, size)).save(os.path.join(out, 'dry-badge.jpg'), quality=90)
            res.update(ok=True, images_sent=len(imgs), note='сухой прогон: в модель НЕ отправлено')
            return res
        left = budget_s - (time.time() - t0) - 3.0           # 3 с — на плашку и запись
        if left < 10:
            raise HeroError('budget', f'на модель осталось {left:.0f} с — не зову')
        bal0 = DR.gw_credits(max_age_s=0)
        DR._GW_TIMEOUT = max(5, int(left))                   # потолок ожидания шлюза = остаток бюджета шага
        t_m = time.time()
        try:
            img = DR.gpt_edit(imgs, built['prompt'], size=size, quality=quality, model=model)
        except BaseException as e:                           # SystemExit шлюза, таймаут, нет денег — одной меткой
            raise HeroError(DR.photo_outcome(e), str(e)[:300]) from None
        res['timing']['model'] = round(time.time() - t_m, 1)
        t_p = time.time()
        img = fit_frame(img, size) if abs(img.width / img.height - built['frame'].width / built['frame'].height) > 0.01 else img
        if k > 1.0001:
            # ответ модели до обрезки — для разбора отъезда; тоже с плашкой: ни одна AI-картинка без неё не ложится на диск
            badge(img).save(os.path.join(out, 'sources', '4-model-wide.jpg'), quality=85)
            img = crop_overscan(img, k, size)
        badge(img).save(os.path.join(out, 'hero.jpg'), quality=90)
        res['timing']['post'] = round(time.time() - t_p, 2)
        res.update(ok=True, image=os.path.join(out, 'hero.jpg'), out_px=list(img.size))
        time.sleep(2)                                         # баланс шлюза обновляется не мгновенно
        bal1 = DR.gw_credits(max_age_s=0)
        if bal0 is not None and bal1 is not None and bal0 >= bal1:
            res.update(cost_usd=round(bal0 - bal1, 4), cost_source='balance_delta (общий счёт шлюза: параллельные задания DEV '
                                                                    'попадают в разницу)')
        return res
    except HeroError as e:
        res.update(error=str(e), error_code=e.code)
        return res
    except Exception as e:  # noqa: BLE001 — шаг пробы не роняет конвейер: причина — в json
        res.update(error=f'{type(e).__name__}: {str(e)[:300]}', error_code='other')
        return res
    finally:
        res['timing']['total'] = round(time.time() - t0, 2)
        _write_json(out, res)


def _arg(name: str, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main() -> int:
    if '--prepare-demo' in sys.argv:
        try:
            d = prepare_demo(_arg('--prepare-demo'), _arg('--variant', 'set1'), _arg('--sheet'), int(_arg('--view', '0')),
                             _arg('--scene'), _arg('--img-base'))
        except HeroError as e:
            print(f'ошибка: {e}')
            return 2
        print(f'папка сцены: {d}')
        return 0
    scene, out = _arg('--scene'), _arg('--out')
    if not scene or not out:
        print(__doc__)
        return 2
    r = run(scene, out, go='--go' in sys.argv, budget_s=float(_arg('--budget', BUDGET_S)), size=_arg('--size', SIZE),
            quality=_arg('--quality', QUALITY), model=_arg('--model', MODEL), render='--render' in sys.argv,
            style=_arg('--style'), cam_mode=_arg('--cam', 'hero'))
    print(json.dumps({k: r[k] for k in ('ok', 'dry_run', 'model', 'size', 'timing', 'cost_usd', 'error_code', 'error', 'image')
                      if k in r}, ensure_ascii=False))
    return 0 if r['ok'] else 3


if __name__ == '__main__':
    sys.exit(main())
