#!/usr/bin/env python3
"""РЕЖИМ «УЛУЧШИТЬ ФОТО»: сборка запроса на ремонт поверх НАШЕГО кадра с мебелью.

Владелец 01.09: «наш прежний ГПТ-запрос, только исходник — наша модель с расставленными мешами;
ремонт делать под нужный стиль, стиль передаётся; мебель двигать нельзя; отдаём склеенные 2
ракурса, получаем склеенный результат и режем на 2 вида».

ЧТО СЮДА НЕ ВОШЛО И ПОЧЕМУ.
- **Маски нет.** Замер 01.09 (`improve_probe.py`): полностью непрозрачная маска («менять нечего»)
  не остановила модель. Но кадр при этом вышел ПРАВИЛЬНЫЙ — ремонт сделан, мебель на месте.
  Значит маска не нужна: она ничего не гарантирует и только усложняет запрос. Владелец: «зачем
  маска, на фото же было ок, мы отправляем в GPT фото».
- **Два вызова вместо листа — отвергнуто.** Разошлись бы цвет стен, пол и свет: два вида одной
  комнаты выглядели бы как две квартиры. Лист даёт одинаковую отделку по построению.

РАЗРЕШЕНИЕ. Замер показал, что шлюз принимает лист до 2048×3072. Прежние 1024×1536 давали после
резки ~720 px на вид при исходнике 1344×896 — мы отдавали хороший кадр и забирали худший.

Ничего не отправляет. Собирает лист и промпт, выкладывает страницу исходников и печатает ссылку.

  improve_mode.py --variant "Вариант 4"          # собрать исходник по живому демо
  improve_mode.py --variant "Вариант 4" --style лофт
"""
import io
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from PIL import Image  # noqa: E402

DEMO_URL = 'https://remont-lab.online/demo/demo-data.json'
IMG_BASE = 'https://remont-lab.online/demo/'
SIZE = os.environ.get('IMPROVE_SIZE', '2048x3072')     # замер: принимается шлюзом
# improve-v2 (demo-11, бенч 17.10, ADR-0302): блок PHOTOGRAPHIC LOOK и правило каталожной формы. Версия — часть ключа
# готового ответа и исходника (`draft_render._improve_cache`, `from_sources`): ответ v1 не отдаётся на запрос v2
PROMPT_VERSION = 'improve-v2'


def prompt_sha(prompt: str) -> str:
    """Отпечаток текста промпта — в ответ и реестр рядом с версией (видно, каким текстом снято фото)."""
    import hashlib
    return hashlib.sha1(prompt.encode('utf-8')).hexdigest()[:12]


# ФОТОГРАФИЧЕСКИЙ ВИД (бенч 17.10: 3/3 живее, `tools/ops/bench-realistic4.py:PHOTO`). Объектив — как у IMAGE 1 (Codex 17.10:
# «24 mm» спорил с правилом «не менять перспективу» и произвольным углом камеры)
PHOTO_LOOK = ('PHOTOGRAPHIC LOOK — MANDATORY. The result must read as a real interior photograph for a property listing, not as '
              'a 3D render: match IMAGE 1 lens and perspective exactly (a wide-angle property-listing look only where it is '
              'consistent with IMAGE 1); physically plausible global illumination with soft bounced light, accurate contact '
              'shadows under every object, subtle ambient occlusion in corners, real fabric weave on upholstery and curtains, '
              'visible wood grain on the floor and table, faint micro-imperfections on painted walls, slight natural vignetting '
              'and gentle sensor grain, true-to-life white balance. No plastic-looking surfaces, no perfectly uniform walls, no '
              'CGI gloss, no oversaturation.')
# КАТАЛОЖНАЯ ФОРМА (владелец 17.10: «подлокотники есть — оставляем, нет — дорисовывать нельзя»; бенч 3/3 без выдумок)
SHAPE_RULE = ('* the catalogue shape of every product: keep armrests, cushions and other parts exactly as the product has them; '
              'never invent detachable cushions, throws or armrests that the catalogue product does not have;')

# СТИЛИ И ПОЛИТИКА ДЕКОРА — ИЗ КАНОНА (`styles.json`), НЕ ИЗ КОДА. Владелец 01.09: «название
# стиля должно из базы браться»; «что добавлять — GPT решает, можно дать примеры, но всё должно
# в базе храниться, что именно можно, что нельзя»; «стили у нас разные, и от этого набор можно
# менять». В `styles.json` у каждого стиля уже лежит ГОТОВОЕ описание ремонта (поле `prompt`) —
# им и пользуемся: мой прежний словарь «неоклассика = панели и ёлочка» был выдумкой поверх
# существующего канона.
_STYLES = None


def styles_db() -> dict:
    global _STYLES
    if _STYLES is None:
        _STYLES = json.load(open(os.path.join(HERE, 'styles.json'), encoding='utf-8'))
    return _STYLES


def style_block(style: str | None) -> tuple[str, str, dict]:
    """→ (имя стиля, STYLE GUIDE из канона, политика декора).

    Берём `render_guide`, а НЕ соседнее поле `prompt`: то писалось для генерации сцены с нуля и
    требует шторы, люстру и розетку под неё — светильники и текстиль, добавлять которые в этом
    режиме запрещено.
    """
    db = styles_db()
    st = (style or '').strip().lower()
    rec = (db.get('styles') or {}).get(st) or {}
    return (st if rec else ''), (rec.get('render_guide') or ''), (db.get('_decor_policy') or {})


def prompt_for(style: str | None, decor: list | None = None, floor: str | None = None, walls: str | None = None) -> str:
    """Промпт режима ремонта. СТРУКТУРА ВЛАДЕЛЬЦА (01.09): статические правила отдельно,
    STYLE GUIDE — единственный переменный блок, и он СОВЕТУЮЩИЙ, а не список обязательного.

    Владелец переписал мою версию и поправил четыре фактические ошибки, которые я бы отправил
    в модель: телевизор СТОИТ на тумбе (во втором ракурсе виден с торца), а не висит; торшер —
    это реальный товар из каталога, а не служебная заглушка; симметрия неоклассики относится
    только к раскладке молдингов, иначе модель переставит мебель ради неё; свет должен быть
    одним решением (тёплый дневной), а не «дневной и одновременно вечерний».
    """
    st, guide, pol = style_block(style)
    deny = list((pol.get('deny_always') or [])) + list((pol.get('deny_now') or {}).keys())
    allow = list((pol.get('allow_now') or {}).keys())
    return '\n'.join([
        'You are given TWO images:',
        '',
        '* IMAGE 1: one sheet containing TWO rendered views of the SAME furnished room, stacked '
        'vertically and separated by a magenta band.',
        '* IMAGE 2: catalogue references for all real products already placed in the room.',
    ] + ([
        '* IMAGE 3: decor items that are part of this set but are NOT yet in the render. They are '
        'bought goods and MUST appear in the result.',
    ] if decor else []) + [
        '',
        'TASK: turn IMAGE 1 into two photorealistic views of a renovated room. Preserve the room, '
        'cameras and furniture; change only finishes, product materials and service placeholders.',
        '',
        'STATIC HARD RULES',
        '',
        'IMAGE 1 controls all geometry. Do not change:',
        '',
        '* camera, crop, perspective or proportions;',
        '* room geometry, wall corners, ceiling, door or window openings;',
        '* the position, silhouette, size, rotation, orientation, count or design of any '
        'furniture, lamp or rug;',
        '* the furniture arrangement or object visibility;',
        '* the two-view layout or magenta separator;',
        SHAPE_RULE,
    ] + ([
        # ПОЛ ЗАСТРОЙЩИКА (demo-06): выбран покупателем и уже нарисован на IMAGE 1 — модель его не перекрашивает
        f'* the FLOOR: it is the developer option «{floor}» chosen by the buyer and already shown in '
        'IMAGE 1 — keep its pattern, plank direction and tone exactly, only add realistic sheen and shadows.',
    ] if floor else []) + ([
        # СТЕНЫ ЗАСТРОЙЩИКА (demo-07): выбраны покупателем и уже на IMAGE 1, включая акцентную стену — модель их не меняет
        f'* the WALLS: they are the developer option «{walls}» chosen by the buyer and already shown in IMAGE 1, including '
        'an accent wall if there is one — keep their colour and finish exactly.',
    ] if walls else []) + [
        '',
        'Keep the magenta band in exactly the same position, height and colour, with nothing '
        'drawn over it.',
        '',
        'IMAGE 2 controls only the COLOUR, MATERIAL and SURFACE APPEARANCE of real products. '
        'Correct inaccurate upholstery, shades, finishes and surface patterns to match the '
        'references, but never reconstruct, replace, move, resize, mirror or duplicate a product. '
        'Ignore catalogue backgrounds, text, logos and watermarks.',
        '',
        'A grey schematic object standing on the floor beside the furniture may be an existing '
        'catalogue product whose 3D model is not ready (for example a FLOOR LAMP). It is not a '
        'placeholder to redesign: keep its position and silhouette and correct only its materials '
        'from IMAGE 2.',
        '',
    ] + ([
        'DECOR FROM IMAGE 3 — MUST BE PLACED:',
        '',
        'Every item on IMAGE 3 has to appear in the room, standing ON an existing horizontal '
        'surface: the TV console, the coffee table or the dining table. Choose the surface that '
        'suits it, keep it small and natural in scale, and do not let it hide, touch or move any '
        'existing product. Place each item ONCE and show it in both views if that surface is '
        'visible in both. Nothing else may be added.',
        '',
    ] if decor else []) + [
        'SERVICE PLACEHOLDERS',
        '',
        'Turn these schematic elements into realistic objects while preserving their exact outer '
        'size, position and perspective:',
        '',
        '* The large grey rectangular plane at the TV console is a TELEVISION; seen edge-on from '
        'the side it is the same television. Render one modern flat TV with a thin bezel and a '
        'switched-off dark screen. Our code decides the mounting from the real console height, so '
        'keep it EXACTLY as rendered: if it stands on the console, do not wall-mount it; if it '
        'hangs on the wall, do not place it on the console. Same height and gap as in IMAGE 1.',
        '* A BLUE wall rectangle is a WINDOW. Render a typical white PVC window with frame, glass, '
        'sashes and windowsill. Keep the exact opening.',
        '* A BROWN rectangle is a DOOR. Render a real door leaf with frame, trim and handle, '
        'finished to suit the renovation.',
        '* Keep the rug flat on the floor with its exact existing size, position, pattern and '
        'colour. Never add a second rug or place textile on a wall.',
        '* Every planter or vase must hold a live plant sized to it.',
        '',
        'RENOVATION',
        '',
        'Renovate only exposed ' + ('' if walls else 'walls, ') + 'ceiling, ' + ('' if floor else 'floor, ') + 'skirting, trim and other fixed architectural '
        'elements according to the STYLE GUIDE below.',
        '',
        'You ARE ALLOWED and expected to:',
        '',
    ] + ([] if walls else [
        '* PAINT OR FINISH THE WALLS in colours and materials that suit the style — plain paint, '
        'plaster, brick or a single accent wall are all acceptable when the STYLE GUIDE calls for '
        'them. White walls are not the default; choose what the style needs.',
    ]) + [
        '* DRESS THE WINDOW WITH CURTAINS or blinds that suit the style, hung correctly and '
        'identical in both views. They must not cover furniture or change the window opening.',
        '',
        'The two views show the SAME room. Use exactly the same wall colour, floor material and '
        'direction, trim, door finish, window design and light temperature in both views.',
        '',
        'Add realistic materials, ambient light, soft shadows and contact shadows beneath existing '
        'objects. Preserve the original object positions and occlusions. Keep vertical lines '
        'vertical and wall-to-floor junctions correct.',
        '',
        PHOTO_LOOK,
        '',
        'STYLE GUIDE — VARIABLE AND ADVISORY, NOT A CHECKLIST',
        '',
        'This is the only section that changes between projects. Use it to guide colours, '
        'finishes, atmosphere and optional light decor. Select only elements that fit the visible '
        'room and omit anything unnecessary. It never overrides the STATIC HARD RULES or FORBIDDEN '
        'list.',
        '',
        guide or 'Choose finishes that suit the room and look ordinary, affordable and tasteful.',
        '',
        'Optional decor may be added sparingly, but it must not cover, touch or move existing '
        'objects and must appear consistently in both views. It must not read as new furniture.',
        '',
        'FORBIDDEN',
        '',
        'Never add, remove or replace:',
        '',
    ] + [f'* {x};' for x in deny] + [
        '',
        'Do not add text, labels, logos or watermarks. Do not change the camera, architecture or '
        'furniture arrangement.',
    ] + ([
        '',
        'Explicitly ALLOWED despite the caution above: ' + ', '.join(allow) + '.',
    ] if allow else []) + [
        '',
        'OUTPUT',
        '',
        'Return ONE image with exactly the dimensions and proportions of IMAGE 1 and the same '
        'two-view layout.',
    ])


def variant_payload(title: str) -> tuple[dict, str]:
    """Живое демо как источник: берём тот же вариант, что видит партнёр."""
    d = json.loads(urllib.request.urlopen(DEMO_URL, timeout=60).read().decode())
    v = next((x for x in d['variants'] if x.get('title') == title), None)
    if v is None:
        raise SystemExit(f'нет варианта {title!r}; есть: '
                         + ', '.join(x.get('title', '?') for x in d['variants']))
    items = []
    for it in v['items']:
        sku = it.get('sku') or {}
        img = sku.get('img')
        items.append({'role': it['role'], 'x': it['x'], 'y': it['y'], 'rot': it.get('rot'),
                      'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
                      'corner': it.get('corner'), 'section': it.get('section'),
                      'sid': sku.get('sid'), 'name': sku.get('name'),
                      'img': (img if (img or '').startswith('http') else
                              (IMG_BASE + img if img else None))})
    # ЭКЗЕМПЛЯР КОМПЛЕКТА НАСЛЕДУЕТ ТОВАР БАЗОВОЙ РОЛИ — ОДИН РАЗ, В ОДНОМ МЕСТЕ (владелец
    # 01.09, третье напоминание: «хотя бы в демо всё размечу сам, чтоб автоматом подтягивалось
    # 2 стула, если их 2»). Слот «стул 2» создаёт раскладка, а товар в банке лежит один — под
    # «стул», потому что продаётся комплектом. Раньше такой слот ехал пустым, и его теряли ВСЕ
    # потребители сразу: меша нет → серая заглушка в кадре, названия нет → нет карточки в листе
    # эталонов. Достраиваем здесь, до всего остального.
    import re as _re
    by_role = {it['role']: it for it in items if it.get('name')}
    for it in items:
        if it.get('name'):
            continue
        base = _re.sub(r'\s+\d+$', '', it['role'])
        src = by_role.get(base)
        if src:
            for k in ('sid', 'name', 'img'):
                it[k] = src.get(k)
    return {'room': d['room'], 'items': items, 'decor': v.get('decor') or []}, (v.get('style') or '')


_IDENT_CACHE: dict = {}


# ——— КАДРЫ ИЗ БРАУЗЕРНОЙ СЦЕНЫ (план demo-10, Codex 17.10) ———————————————————————————————————————————————
# Страница снимает оба вида из своей 3D-сцены (`DemoScene.capture`), грузит их на прод (`/render/frame`, имя = sha256 содержимого)
# и шлёт в задании только имена. Здесь лист собирается из этих кадров — без серверного рендера (было 27 с «нашей части»).
import hashlib as _hl
import threading as _th

_SF_LOCKS: dict = {}
_SF_GUARD = _th.Lock()


def frame_path(fid: str) -> str:
    """Где лежит загруженный кадр на проде (раздаётся как /test/share/frames-in/<id>.jpg)."""
    import draft_render as DR
    return os.path.join(os.path.dirname(DR.FRAMES_DIR), 'frames-in', f'{fid}.jpg')


def load_frame(fid: str) -> Image.Image:
    """Кадр по имени: с диска (прод, запасной путь) или с прода по ссылке (DEV); содержимое сверяется с именем."""
    import draft_render as DR
    if not (isinstance(fid, str) and len(fid) == 64 and all(c in '0123456789abcdef' for c in fid)):
        raise ValueError('неверное имя кадра')
    p = frame_path(fid)
    if os.path.exists(p):
        raw = open(p, 'rb').read()
    else:
        url = (DR.PUBLIC_BASE or 'https://remont-lab.online') + '/test/share/frames-in/' + fid + '.jpg'
        raw = urllib.request.urlopen(url, timeout=30).read()
    if _hl.sha256(raw).hexdigest() != fid:
        raise ValueError('кадр не совпал со своим именем')
    return Image.open(io.BytesIO(raw)).convert('RGB')


def sheet_from_views(views: list) -> Image.Image:
    """Два вида → лист под запрашиваемый размер (`SIZE`): каждый вид ровно `(SIZE_w) × ((SIZE_h − BAND_PX) / 2)` — пропорция
    листа обязана совпасть с запросом (Codex: проверка пропорций отвергает иное). Кадр другой пропорции обрезается по центру."""
    import draft_render as DR
    rw, rh = (int(x) for x in SIZE.split('x'))
    per = (rh - DR.BAND_PX) // 2
    out = []
    for v in views:
        tw, th = rw, per
        if abs(v.width / v.height - tw / th) > 0.002:
            if v.width / v.height > tw / th:
                cw = round(v.height * tw / th); x0 = (v.width - cw) // 2; v = v.crop((x0, 0, x0 + cw, v.height))
            else:
                ch = round(v.width * th / tw); y0 = (v.height - ch) // 2; v = v.crop((0, y0, v.width, y0 + ch))
        out.append(v.resize((tw, th), Image.LANCZOS) if v.size != (tw, th) else v)
    sheet = Image.new('RGB', (rw, per * len(out) + DR.BAND_PX * (len(out) - 1)), DR.BAND_RGB)
    y = 0
    for v in out:
        sheet.paste(v, (0, y)); y += v.height + DR.BAND_PX
    return sheet


def frames_key(payload: dict, model: str, quality: str) -> str:
    """СЕРВЕРНЫЙ КЛЮЧ ОТВЕТА (Codex 17.10, п.3): не `stateId` (он без камер) — кадры по содержимому в порядке C1/C2, стиль,
    отделка, набор эталонов, декор, версия промпта, модель и качество. Тот же ключ — тот же ответ, повтор не платит."""
    views = sorted(payload.get('views') or [], key=lambda x: str(x.get('camera')))
    items = sorted((it.get('role'), it.get('name'), it.get('img')) for it in payload.get('items', []) if it.get('name'))
    decor = [((d.get('sku') or {}).get('name')) for d in (payload.get('decor') or [])]
    key = json.dumps([[(v.get('camera'), v.get('id')) for v in views], payload.get('style') or '',
                      (payload.get('floor') or {}).get('id'), (payload.get('walls') or {}).get('id'),
                      ((payload.get('walls') or {}).get('accent') or {}).get('side'), items, decor,
                      PROMPT_VERSION, model, quality], ensure_ascii=False, sort_keys=True)
    return _hl.sha256(key.encode('utf-8')).hexdigest()[:32]


def single_flight(key: str):
    """Один ключ — одна оплата: второй одинаковый запрос ждёт первый (затем берёт его ответ из кэша)."""
    with _SF_GUARD:
        lk = _SF_LOCKS.setdefault(key, _th.Lock())
    return lk


def build_from_views(payload: dict, style: str | None, stamp: str | None = None) -> dict:
    """Лист из кадров браузера + эталоны + промпт; исходники публикуются В ФОНЕ (не на горячем пути, Codex п.5)."""
    import draft_render as DR
    vs = sorted(payload.get('views') or [], key=lambda x: str(x.get('camera')))
    if len(vs) < 2:
        raise ValueError('нужны оба вида')
    sheet = sheet_from_views([load_frame(v.get('id')) for v in vs[:2]])
    items = payload.get('items', [])
    ident = None
    try:
        _ikey = tuple(sorted((it.get('role'), it.get('name'), it.get('img')) for it in items if it.get('name')))
        ident = _IDENT_CACHE.get(_ikey)
        if ident is None:
            anchors_all = [{'role': it['role'], 'n': i + 1} for i, it in enumerate(items) if it.get('name')]
            photos = {it['role']: DR.photo(it.get('img')) for it in items if it.get('img') and it.get('role')}
            ident = DR._identity(anchors_all, photos, {it['role']: it for it in items if it.get('role')})
            if len(_IDENT_CACHE) > 12:
                _IDENT_CACHE.clear()
            _IDENT_CACHE[_ikey] = ident
    except Exception as e:  # noqa: BLE001 — без эталонов запрос всё равно осмыслен
        print(f'  лист эталонов не собрался: {str(e)[:80]}')
    decor = DR.decor_split(payload)[1]
    dsheet = None
    if decor:
        try:
            an = [{'role': x['role'], 'n': i + 1} for i, x in enumerate(decor)]
            ph = {x['role']: DR.photo((x.get('sku') or {}).get('img')) for x in decor}
            dsheet = DR._identity(an, ph, {x['role']: x.get('sku') or {} for x in decor})
        except Exception as e:  # noqa: BLE001
            print(f'  лист декора не собрался: {str(e)[:70]}')
    fl, wl = payload.get('floor') or {}, payload.get('walls') or {}
    prompt = prompt_for(style, decor, fl.get('title') or fl.get('id') or None, wl.get('title') or wl.get('id') or None)
    stamp = f'improve-{stamp}' if stamp else f'improve-{time.strftime("%H%M%S")}'
    clay = [str(x) for x in (payload.get('clay') or []) if x][:20]
    meta = {'режим': 'улучшить фото — кадры из браузерной сцены (demo-10)', 'стиль': style or '—',
            'кадры': ', '.join(f"{v.get('camera')} {str(v.get('id'))[:12]}" for v in vs[:2]), 'размер запроса': SIZE,
            'лист на входе': f'{sheet.width}×{sheet.height}', 'версия промпта': PROMPT_VERSION,
            'серые заглушки в кадре': ', '.join(clay) or 'нет'}
    imgs = {'1-ОТПРАВЛЯЕМ-лист-двух-видов': sheet, '2-ОТПРАВЛЯЕМ-эталоны-товаров': ident, '3-ОТПРАВЛЯЕМ-декор-разместить': dsheet}
    _th.Thread(target=lambda: DR._publish_sources(stamp, imgs, prompt, [], meta), daemon=True).start()
    url = (DR.PUBLIC_BASE + DR.SRC_URL + '/' + stamp + '/') if DR.PUBLIC_BASE else os.path.join(DR.SRC_DIR, stamp)
    return {'src_url': url, 'sheet': sheet, 'ident': ident, 'prompt': prompt, 'clay': clay, 'cams': [v.get('camera') for v in vs[:2]]}


def build(payload: dict, style: str | None, stamp: str | None = None) -> dict:
    # ПОЛНОЕ КАЧЕСТВО ОБЯЗАТЕЛЬНО. В быстром режиме растеризатор отсекает «задние» грани по
    # нормали, а у мешей Hunyuan нормали местами перевёрнуты — и в спинке дивана пробиваются
    # дыры (владелец видел это на первом же листе 01.09; та же грабля отмечена в коде 31.08).
    # Лист уходит в платную генерацию: отдавать модели дырявую мебель нельзя, она её «починит»
    # по-своему, то есть перерисует.
    os.environ.setdefault('SCENE3D_QUALITY', 'full')
    import draft_render as DR
    # ПЛАТНЫЙ РЕЖИМ — ТОЛЬКО ПОЛНЫЕ МЕШИ (план draft-render-speed, 02.09). Эскиз рисуется
    # лёгкими копиями и мог оставить флаг включённым в этом же процессе; в модель обязана уйти
    # полная геометрия — за неё заплачено, и упрощение там экономит секунды ценой качества.
    DR.S3_LITE[0] = False
    room, placements, photos = DR.scene_from_request(payload)
    # РАКУРС — ТОТ ЖЕ, ЧТО НА ЧЕРНОВИКЕ (владелец 01.09: «развернул камеры как хочу, на
    # черновике вижу верно, а при генерации ГПТ уходят другие виды»). Здесь стоял прямой
    # вызов автоподбора `demo_cams` — он не знал ни про перетаскивание, ни про поворот,
    # и платная генерация уходила с чужих точек. Решение о ракурсе теперь одно на всех.
    cams = DR.cams_from_request(room, placements, payload)[:2]
    # РАЗРЕШЕНИЕ ЛИСТА (владелец 01.09 «разрешение больше»). Камеры демо считают кадр 1344×896 —
    # для платной генерации это мало: модель получила бы вход хуже собственного выхода.
    # Пересобираем ТЕ ЖЕ камеры под большую ширину: точка, цель и угол не меняются, растёт
    # только плотность пикселей.
    from planner.scene import Camera as _Cam
    # ЛИСТ СОБИРАЕМ РОВНО ПОД ЗАПРАШИВАЕМЫЙ РАЗМЕР (владелец 01.09: «минимализм, что за хрень на
    # втором виде»). Мы отправляли лист 2048×2824, а просили вернуть 2048×3072 — модель тянула
    # картинку по высоте почти на 9 %, и после резки второй вид приезжал искажённым и смещённым.
    # Пропорция запроса и пропорция входа обязаны совпадать: считаем высоту вида из `SIZE`.
    rw, rh_total = (int(x) for x in SIZE.split('x'))
    per = (rh_total - DR.BAND_PX) // 2
    cams = [_Cam(name=c.name, eye=c.eye, target=c.target, fov_deg=c.fov_deg,
                 width=rw, height=per) for c in cams]
    # ВСЕ ПРЕДМЕТЫ, А НЕ ТОЛЬКО ТЕ, У КОГО СВОЯ КАРТОЧКА (владелец 01.09 «и все предметы»).
    # Пронумерованный экземпляр («стул 2») своего товара в банке не имеет и приезжал без `sid`,
    # то есть рисовался серой заглушкой рядом с честным первым стулом. Берём меш базовой роли —
    # это тот же товар, комплект из двух штук.
    import re as _re
    # меш ищем по артикулу МОДЕЛИ (`msid`, ADR-0196): у цветового варианта своего файла нет
    sid_by_role = {it['role']: (it.get('msid') or it.get('sid'))
                   for it in payload.get('items', []) if it.get('role')}
    for role, sid in list(sid_by_role.items()):
        if sid:
            continue
        base = _re.sub(r'\s+\d+$', '', role)
        if base != role and sid_by_role.get(base):
            sid_by_role[role] = sid_by_role[base]
    # ДЕКОР, КОТОРЫЙ МЫ ПОСТАВИЛИ САМИ, ТОЖЕ ИЩЕТ СВОЮ МОДЕЛЬ (08.09). Черновик добавляет вазу в
    # карту мешей, а платный режим строил её только по `items` — и на дорогой картинке ваза
    # оказалась бы серой коробкой (находка советника).
    for _d in DR.decor_split(payload)[0]:
        _sk = _d.get('sku') or {}
        if _d.get('role') and (_sk.get('msid') or _sk.get('sid')):
            sid_by_role[_d['role']] = _sk.get('msid') or _sk.get('sid')
    views, clay = [], []
    for cam in cams:
        img, diag = DR.scene3d_frame(room, placements, cam, sid_by_role, photos)
        views.append(img)
        # «тв» — наша служебная панель, её отсутствие меша нормой считать нельзя, но и блокировать
        # кнопку из-за неё незачем: она всегда рисуется коробкой
        clay += [r for r in (diag.get('clay') or []) if r != 'тв']
    w = views[0].width
    total_h = sum(v.height for v in views) + DR.BAND_PX * (len(views) - 1)
    sheet = Image.new('RGB', (w, total_h), DR.BAND_RGB)
    y = 0
    for v in views:
        sheet.paste(v, (0, y))
        y += v.height + DR.BAND_PX
    # ЛИСТ ЭТАЛОНОВ (владелец 01.09): «бывает, на модели неверный цвет и текстура — пусть GPT
    # смотрит на коллаж из предметов дополнительно». Фото каждого товара с подписью роли; по
    # нему модель правит ЦВЕТ И МАТЕРИАЛ, не трогая форму и место.
    # ЛИСТ ЭТАЛОНОВ КЭШИРУЕМ ПО СОСТАВУ ТОВАРОВ (план paid-path-speed): он одинаков для всех
    # кадров одного набора и не зависит ни от ракурса, ни от расстановки. Пересобирать его на
    # каждый запрос — собирать один и тот же коллаж заново.
    ident = None
    try:
        anchors_all = [{'role': it['role'], 'n': i + 1}
                       for i, it in enumerate(payload.get('items', [])) if it.get('name')]
        skus = {it['role']: it for it in payload.get('items', []) if it.get('role')}
        _ikey = tuple(sorted((it.get('role'), it.get('name'), it.get('img'))
                             for it in payload.get('items', []) if it.get('name')))
        ident = _IDENT_CACHE.get(_ikey)
        if ident is None:
            ident = DR._identity(anchors_all, photos, skus)
            if len(_IDENT_CACHE) > 12:
                _IDENT_CACHE.clear()
            _IDENT_CACHE[_ikey] = ident
    except Exception as e:  # noqa: BLE001 — без эталонов запрос всё равно осмыслен
        print(f'  лист эталонов не собрался: {str(e)[:80]}')
    # ТРЕТИЙ ЛИСТ — ДЕКОР НА МЕБЕЛЬ (владелец 01.09). Вазы куплены и лежат в комплекте, но на
    # плане их нет: они стоят на тумбе или столе, а не на полу. Отдаём отдельным изображением с
    # прямым указанием, что это НАДО разместить, — иначе оплаченный товар в кадр не попадёт.
    # ПРОСИМ ДОРИСОВАТЬ ТОЛЬКО ТО, ЧЕГО В СЦЕНЕ НЕТ (08.09). Вазы теперь стоят на столешнице
    # физически (`draft_render._decor_places`); если продолжать отдавать их третьим листом с
    # просьбой «размести», модель нарисует ВТОРУЮ такую же вазу рядом с нашей.
    decor = DR.decor_split(payload)[1]
    dsheet = None
    if decor:
        try:
            an = [{'role': x['role'], 'n': i + 1} for i, x in enumerate(decor)]
            ph = {x['role']: DR.photo((x.get('sku') or {}).get('img')) for x in decor}
            dsheet = DR._identity(an, ph, {x['role']: x.get('sku') or {} for x in decor})
        except Exception as e:  # noqa: BLE001
            print(f'  лист декора не собрался: {str(e)[:70]}')
    _ft = (((getattr(room, 'finish', None) or {}).get('floor') or {}).get('tex'))
    _wo = (((getattr(room, 'finish', None) or {}).get('wall') or {}).get('opt'))
    prompt = prompt_for(style, decor, (_ft.get('title') or _ft.get('id')) if _ft else None, (_wo.get('title') or _wo.get('id')) if _wo else None)
    # Метку может задать вызывающий: черновик заранее сообщает странице адрес исходника,
    # и папка обязана совпасть с этим адресом (иначе «Улучшить фото» не найдёт готовый лист).
    stamp = f'improve-{stamp}' if stamp else f'improve-{time.strftime("%H%M%S")}'
    out_w, out_h = (int(x) for x in SIZE.split('x'))
    per_view_h = (out_h - DR.BAND_PX) // 2
    url = DR._publish_sources(
        stamp, {'1-ОТПРАВЛЯЕМ-лист-двух-видов': sheet,
                '2-ОТПРАВЛЯЕМ-эталоны-товаров': ident,
                '3-ОТПРАВЛЯЕМ-декор-разместить': dsheet}, prompt, [],
        {'режим': 'улучшить фото — только ремонт',
         'стиль': style or '—',
         'ОТПРАВЛЕНО В МОДЕЛЬ': 'НЕТ, это сборка исходника',
         # КАЧЕСТВО ВХОДА ФИКСИРУЕМ В САМОЙ ПАПКЕ (план paid-path-speed): платный режим
         # переиспользует лист ТОЛЬКО если он собран полными мешами. Иначе ускорение
         # черновика молча протечёт в платный результат, как это уже случилось 02.09.
         'качество': 'full' if not DR.S3_LITE[0] else 'lite',
         'размер запроса': SIZE,
         'лист на входе': f'{sheet.width}×{sheet.height}',
         'на вид после резки': f'~{out_w}×{per_view_h} (было ~1024×721)',
         'версия промпта': PROMPT_VERSION,
         'камеры': ', '.join(f'{c.name} fov {c.fov_deg:.0f}°' for c in cams),
         'серые заглушки в кадре': ', '.join(sorted(set(clay))) or 'нет',
         'маска': 'не используется — замер показал, что она не соблюдается'})
    return {'src_url': url, 'sheet': sheet, 'ident': ident, 'prompt': prompt,
            'clay': sorted(set(clay)), 'cams': [c.name for c in cams]}


def main() -> int:
    title = sys.argv[sys.argv.index('--variant') + 1] if '--variant' in sys.argv else 'Вариант 4'
    payload, style = variant_payload(title)
    if '--style' in sys.argv:
        style = sys.argv[sys.argv.index('--style') + 1]
    print(f'{title}: предметов {len(payload["items"])}, стиль «{style or "—"}»')
    r = build(payload, style)
    print(f'  лист: {r["sheet"].width}×{r["sheet"].height}, камеры {", ".join(r["cams"])}')
    if r['clay']:
        print(f'  ВНИМАНИЕ, серые заглушки в кадре: {", ".join(r["clay"])} — '
              'у этих товаров нет меша, модель их не исправит')
    print(f'\nИСХОДНИК ЗАПРОСА: {r["src_url"]}')
    print('в модель НИЧЕГО не отправлено')
    return 0


if __name__ == '__main__':
    sys.exit(main())


def publish_from_views(views: list, payload: dict, stamp: str) -> str:
    """Собрать исходник запроса ИЗ УЖЕ ОТРИСОВАННЫХ кадров черновика.

    Владелец 01.09: «когда жму — собирается сцена; эта сцена должна быть в черновике на отправку,
    с ракурсов с полосой объединяй; она же должна быть исходником запроса». Смысл в том, чтобы
    показанное и отправляемое были ОДНИМ изображением: раньше страница исходников собиралась
    отдельным прогоном, и разойтись с показанным кадром могла на чём угодно — камере, версии
    кода, свежести меша.
    """
    import draft_render as DR
    if len(views) < 2:
        raise ValueError('нужны два ракурса')
    style = (payload or {}).get('style') or ''
    w = min(v.width for v in views)
    parts = [v if v.width == w else v.resize((w, int(round(w * v.height / v.width))))
             for v in views]
    total_h = sum(v.height for v in parts) + DR.BAND_PX * (len(parts) - 1)
    sheet = Image.new('RGB', (w, total_h), DR.BAND_RGB)
    y = 0
    for v in parts:
        sheet.paste(v, (0, y))
        y += v.height + DR.BAND_PX
    ident = None
    try:
        items = payload.get('items') or []
        anchors_all = [{'role': it['role'], 'n': i + 1}
                       for i, it in enumerate(items) if it.get('name')]
        photos = {it['role']: DR.photo(it.get('img')) for it in items if it.get('img')}
        ident = DR._identity(anchors_all, photos, {it['role']: it for it in items if it.get('role')})
    except Exception as e:  # noqa: BLE001 — без эталонов запрос всё равно осмыслен
        print(f'  лист эталонов не собрался: {str(e)[:80]}')
    out_w, out_h = (int(x) for x in SIZE.split('x'))
    return DR._publish_sources(
        f'improve-{stamp}',
        {'1-ОТПРАВЛЯЕМ-лист-двух-видов': sheet, '2-ОТПРАВЛЯЕМ-эталоны-товаров': ident},
        prompt_for(style), [],
        {'режим': 'улучшить фото — только ремонт',
         'стиль': style or '—',
         'ОТПРАВЛЕНО В МОДЕЛЬ': 'НЕТ, это сборка исходника по показанному кадру',
         'размер запроса': SIZE,
         'лист на входе': f'{sheet.width}×{sheet.height}',
         'на вид после резки': f'~{out_w}×{(out_h - DR.BAND_PX) // 2}',
         'версия промпта': PROMPT_VERSION})


def from_sources(src_id: str | None):
    """Взять УЖЕ СОБРАННЫЙ лист и промпт по id страницы исходников.

    Кнопка «улучшить фото» нажимается на кадре, для которого исходник уже выложен: пересобирать
    его — минута лишнего ожидания и риск отправить не то, что человек видел (за это время могли
    смениться меш, ориентация или код). Читаем с диска то же самое изображение.
    """
    import draft_render as DR
    if not src_id:
        return None
    d = os.path.join(DR.SRC_DIR, str(src_id))
    sheet_p = os.path.join(d, '1-ОТПРАВЛЯЕМ-лист-двух-видов.jpg')
    prompt_p = os.path.join(d, 'prompt.txt')
    if not (os.path.exists(sheet_p) and os.path.exists(prompt_p)):
        return None
    # ИСХОДНИК ДРУГОЙ ВЕРСИИ ПРОМПТА НЕ ПЕРЕИСПОЛЬЗУЕМ (demo-09/11, Codex 17.10): `prompt.txt` v1 ушёл бы в модель с листом
    # нового запроса — пересобираем с текущим промптом
    try:
        _mv = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
        if isinstance(_mv, dict) and _mv.get('версия промпта') != PROMPT_VERSION:
            print(f'улучшение: исходник {src_id} — промпт {_mv.get("версия промпта")}, нужен {PROMPT_VERSION} — пересобираю', flush=True)
            return None
    except Exception:  # noqa: BLE001 — без легенды версия неизвестна: пересобираем
        return None
    # ЛИСТ ИЗ ЛЁГКИХ МЕШЕЙ НЕ ПЕРЕИСПОЛЬЗУЕМ (план paid-path-speed, 02.09). Черновик рисуется
    # упрощённой геометрией ради скорости; отправлять её в платную генерацию — платить за
    # огрублённый вход. Нет пометки «full» — считаем лист негодным и пересобираем.
    try:
        _mt = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
        _q = _mt.get('качество') if isinstance(_mt, dict) else None
        if _q and _q != 'full':
            print(f'улучшение: исходник {src_id} собран в режиме «{_q}» — пересобираю полным',
                  flush=True)
            return None
    except Exception:  # noqa: BLE001 — нет легенды: старая папка, доверяем как раньше
        pass
    sh = Image.open(sheet_p).convert('RGB')
    _w, _h = (int(x) for x in SIZE.split('x'))
    if abs(sh.width / max(sh.height, 1) - _w / _h) > 0.01:
        # Пропорция листа обязана совпадать с запрашиваемой: иначе модель растянет вход и
        # после резки второй вид уедет (дефект 01.09, замер 02.09: 1344×1886 против 2048×3072).
        print(f'улучшение: исходник {src_id} пропорции {sh.width}×{sh.height} — пересобираю',
              flush=True)
        return None
    ident_p = os.path.join(d, '2-ОТПРАВЛЯЕМ-эталоны-товаров.jpg')
    return {'sheet': sh,
            'ident': Image.open(ident_p).convert('RGB') if os.path.exists(ident_p) else None,
            'prompt': open(prompt_p, encoding='utf-8').read(),
            'src_url': (DR.PUBLIC_BASE + DR.SRC_URL + '/' + str(src_id) + '/')
                       if DR.PUBLIC_BASE else d,
            'clay': []}
