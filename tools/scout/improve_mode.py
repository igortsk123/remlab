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
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

from PIL import Image  # noqa: E402

DEMO_URL = 'https://remont-lab.online/test/buildup/demo-data.json'
IMG_BASE = 'https://remont-lab.online/test/buildup/'
SIZE = os.environ.get('IMPROVE_SIZE', '2048x3072')     # замер: принимается шлюзом
PROMPT_VERSION = 'improve-v1'

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


def prompt_for(style: str | None, decor: list | None = None) -> str:
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
        '* the two-view layout or magenta separator.',
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
        'Renovate only exposed walls, ceiling, floor, skirting, trim and other fixed architectural '
        'elements according to the STYLE GUIDE below.',
        '',
        'You ARE ALLOWED and expected to:',
        '',
        '* PAINT OR FINISH THE WALLS in colours and materials that suit the style — plain paint, '
        'plaster, brick or a single accent wall are all acceptable when the STYLE GUIDE calls for '
        'them. White walls are not the default; choose what the style needs.',
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
    sid_by_role = {it['role']: it.get('sid') for it in payload.get('items', []) if it.get('role')}
    for role, sid in list(sid_by_role.items()):
        if sid:
            continue
        base = _re.sub(r'\s+\d+$', '', role)
        if base != role and sid_by_role.get(base):
            sid_by_role[role] = sid_by_role[base]
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
    decor = payload.get('decor') or []
    dsheet = None
    if decor:
        try:
            an = [{'role': x['role'], 'n': i + 1} for i, x in enumerate(decor)]
            ph = {x['role']: DR.photo((x.get('sku') or {}).get('img')) for x in decor}
            dsheet = DR._identity(an, ph, {x['role']: x.get('sku') or {} for x in decor})
        except Exception as e:  # noqa: BLE001
            print(f'  лист декора не собрался: {str(e)[:70]}')
    prompt = prompt_for(style, decor)
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
