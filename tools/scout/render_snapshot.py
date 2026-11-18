#!/usr/bin/env python3
"""КОНТРАКТ СНИМКА РАССТАНОВКИ ДЛЯ РЕНДЕРА (T-20261117-19/1, план `photo-render-first-01`, шаг 1).

Страница шлёт СВОЮ расстановку (какой вариант витрины, какие предметы где стоят, две позы камер) — сервер не верит ничему,
кроме номеров: комнату, размеры, товары и их ассеты берёт из данных витрины (демо — `demo-data.json`; тур — данные задания,
их передаёт приложение с внутренним ключом) и строит из них ту же сцену, что движок /demo (`demo_scene_dump.mjs`,
`lib/viewer3d/scene-export.ts`). Декор (шторы, картины, люстра, подушки, растения, радиаторы) страница не присылает вовсе:
в 3D он берётся из данных варианта (`liveDecor()` страницы), сервер берёт оттуда же.

Запрос (версия `SNAPSHOT_VERSION`):
  {"v": 1,
   "variant_id": "<id варианта данных>",                      обязательно
   "room_id": "<комната>", "room": {"w": см, "d": см},       необязательно: сверка («снято в другой комнате» → 409 stale)
   "items": [{"role", "sid" | ("msid", "name"), "x", "y", "rot", "corner"?, "corner_left"?, "section"?}, …]   нет — предметы варианта как есть
   "cams":  [{"name": "C1"|"C2", "x", "y", "rot", "fov", "pose"?, "pshift"?}, …]            нет — позы варианта}

Товар: /demo шлёт `sid`; тур — `msid` + `name` (у заглушки без модели `msid` нет — тогда одно `name`) (в публичных данных тура `sid` нет, `trial_bundle.NEVER_KEYS`): карточка ищется
ТОЛЬКО в данных этого тура по паре (`msid`, `name`; нет `msid` — по имени); нет пары или у пары разные карточки (цвет, размеры, цена, тон) → `bad_item`, без угадывания.
Что проверяется: предметов ≤ MAX_ITEMS; товар есть в данных (индекс товаров по всем местам данных) и у товара есть размеры;
роль — из ролей данных; место — внутри комнаты (допуск 5 см); камеры — ровно C1 и C2, внутри комнаты, углы и обзор в разумных
пределах. Размеры предмета — из данных (тот же предмет варианта — его размеры, иначе — размеры товара), не от страницы.
Числа округляются (0,1 см / 0,1°), потом хеш: одна расстановка → один `scene_hash`.

Самопроверка без Blender: `python tools/scout/render_snapshot.py --selftest`.
"""
import copy
import hashlib
import json
import math
import re
import sys

SNAPSHOT_VERSION = 1
MAX_ITEMS = 40
SLACK_CM = 5.0               # предмет может касаться стены в пределах округления
CAM_SLACK_CM = 100.0         # камера у самой стены или в проёме
SID_RE = re.compile(r'^[0-9A-Za-z_.:\-]{1,80}$')
ID_RE = re.compile(r'^[0-9A-Za-z_.:\-]{1,80}$')
CAM_NAMES = ('C1', 'C2')


class SnapshotError(Exception):
    """Отказ по существу: `status` для HTTP, `code` — для страницы, текст — пара RU/EN (сервер ничего не угадывает)."""

    def __init__(self, status: int, code: str, ru: str, en: str):
        super().__init__(ru)
        self.status, self.code, self.ru, self.en = status, code, ru, en

    def body(self) -> dict:
        return {'error': self.ru, 'error_en': self.en, 'code': self.code}


def _num(v, lo: float, hi: float, what: str, nd: int = 1) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SnapshotError(422, 'bad_snapshot', f'Расстановка не принята: «{what}» не число.',
                            f'The layout was not accepted: "{what}" is not a number.')
    if math.isnan(x) or math.isinf(x) or x < lo or x > hi:
        raise SnapshotError(422, 'bad_snapshot', f'Расстановка не принята: «{what}» вне допустимых значений.',
                            f'The layout was not accepted: "{what}" is out of range.')
    return round(x, nd)


def sku_index(data: dict) -> dict:
    """sid → карточка товара по ВСЕМ местам данных (варианты, декор, наборы, ленты, каталог спален): страница может поставить
    любой товар, который сама получила из этих же данных. Первое вхождение побеждает (одинаковый sid — один товар)."""
    idx: dict = {}

    def walk(o):
        if isinstance(o, dict):
            if 'sid' in o and 'name' in o and o.get('sid') is not None:
                idx.setdefault(str(o['sid']), o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return idx


# поля карточки, по которым две карточки с одной парой (msid, name) считаются РАЗНЫМИ товарами (цвет семейства, размеры, цена, тон)
_CARD_DIFF_KEYS = ('colour', 'colour_en', 'w', 'd', 'h', 'dia', 'price', 'tint', 'swatch', 'hex', 'url')
_AMBIGUOUS = object()


def msid_index(data: dict) -> dict:
    """(msid, name) → карточка — только карточки БЕЗ `sid` (товары тура). Пара с двумя разными карточками — `_AMBIGUOUS` (отказ, не угадывание).
    Первое вхождение побеждает, если остальные не отличаются по `_CARD_DIFF_KEYS`."""
    idx: dict = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get('sid') is None and isinstance(o.get('name'), str) and ('msid' in o):
                k = (str(o['msid'] or ''), o['name'])          # заглушка без модели (ковёр, обеденный стол) — `msid` null: ключ только имя
                cur = idx.get(k)
                if cur is None:
                    idx[k] = o
                elif cur is not _AMBIGUOUS and any(cur.get(f) != o.get(f) for f in _CARD_DIFF_KEYS):
                    idx[k] = _AMBIGUOUS
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return idx


def pkey(sku: dict) -> tuple:
    """Ключ товара: `sid`, если он есть (/demo), иначе (`msid`, `name`) (тур)."""
    sku = sku or {}
    return ('sid', str(sku['sid'])) if sku.get('sid') is not None else ('msid', str(sku.get('msid') or ''), sku.get('name'))   # msid null → ''


def room_of(data: dict, variant: dict) -> dict:
    rid = variant.get('room_id') or 'living'
    return (data.get('rooms_geo') or {}).get(rid) or data.get('room') or {}


def _find_variant(data: dict, vid) -> dict:
    if not isinstance(vid, str) or not ID_RE.match(vid):
        raise SnapshotError(422, 'bad_snapshot', 'Расстановка не принята: нет номера варианта.',
                            'The layout was not accepted: the variant id is missing.')
    for v in data.get('variants') or []:
        if v.get('id') == vid:
            return v
    raise SnapshotError(404, 'unknown_variant', 'Такого варианта в данных нет. Обновите страницу.',
                        'This variant is not in the data. Reload the page.')


def _dims_of(sku: dict) -> tuple:
    w = sku.get('w') or sku.get('dia')
    d = sku.get('d') or sku.get('dia')
    h = sku.get('h')
    return w, d, h


def _item(raw, base_items: list, roles: set, skus: dict, room: dict, msids: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise SnapshotError(422, 'bad_snapshot', 'Расстановка не принята: предмет записан неверно.',
                            'The layout was not accepted: an item is malformed.')
    role = raw.get('role')
    if not isinstance(role, str) or not (1 <= len(role) <= 40) or role not in roles:
        raise SnapshotError(422, 'bad_item', 'Расстановка не принята: неизвестный вид предмета.',
                            'The layout was not accepted: unknown item type.')
    sid = str(raw.get('sid') or '')
    if sid:
        if not SID_RE.match(sid) or sid not in skus:
            raise SnapshotError(422, 'bad_item', 'Расстановка не принята: товара нет в данных. Обновите страницу.',
                                'The layout was not accepted: the product is not in the data. Reload the page.')
        sku = skus[sid]
    else:
        # тур: товар по паре (msid, name) только из данных этого тура; пары нет или она двусмысленна — отказ с причиной
        msid, nm = str(raw.get('msid') or ''), raw.get('name')
        sku = (msids or {}).get((msid, nm)) if (not msid or SID_RE.match(msid)) and isinstance(nm, str) and 1 <= len(nm) <= 300 else None
        if sku is _AMBIGUOUS:
            raise SnapshotError(422, 'bad_item', 'Расстановка не принята: товар в данных неоднозначен (одна пара — разные карточки).',
                                'The layout was not accepted: the product is ambiguous in the data (one pair, different cards).')
        if sku is None:
            raise SnapshotError(422, 'bad_item', 'Расстановка не принята: товара нет в данных. Обновите страницу.',
                                'The layout was not accepted: the product is not in the data. Reload the page.')
    x = _num(raw.get('x'), -SLACK_CM, float(room.get('w') or 0) + SLACK_CM, 'x')
    y = _num(raw.get('y'), -SLACK_CM, float(room.get('d') or 0) + SLACK_CM, 'y')
    rot = _num(raw.get('rot', 0), -720, 720, 'rot')
    # тот же предмет варианта (роль и товар совпали) — его размеры (`dims_src` каталога/расчёта); иначе — размеры товара
    same = next((b for b in base_items if b.get('role') == role and pkey(b.get('sku')) == pkey(sku)), None)
    if same is not None:
        w, d, h = same.get('w'), same.get('d'), same.get('h')
        extra = {k: same[k] for k in ('dims_src', 'd_catalog', 'strategy') if k in same}
    else:
        w, d, h = _dims_of(sku)
        extra = {'dims_src': 'каталог'}
    # ширина и глубина обязательны; высоты у плоских предметов (ковёр) нет — как в данных витрины, движок масштабирует по плану
    if not (w and d):
        raise SnapshotError(422, 'no_dims', 'Для этого товара нет размеров — снять его честно нельзя.',
                            'This product has no dimensions, so it cannot be rendered faithfully.')
    w, d = _num(w, 1, 1000, 'w'), _num(d, 1, 1000, 'd')
    h = _num(h, 1, 1000, 'h') if h else None
    sec = raw.get('section', same.get('section') if same else None)
    return {'role': role, 'x': x, 'y': y, 'rot': rot, 'w': w, 'd': d, 'h': h, **extra, 'sku': copy.deepcopy(sku),
            'corner': bool(raw.get('corner', same.get('corner') if same else False)),
            'corner_left': bool(raw.get('corner_left', same.get('corner_left') if same else False)),
            'section': sec if (sec is None or isinstance(sec, (int, str))) else None}


def _cam(raw, room: dict) -> dict:
    if not isinstance(raw, dict) or raw.get('name') not in CAM_NAMES:
        raise SnapshotError(422, 'bad_cams', 'Расстановка не принята: нужны два ракурса C1 и C2.',
                            'The layout was not accepted: two views, C1 and C2, are required.')
    out = {'name': raw['name'],
           'x': _num(raw.get('x'), -CAM_SLACK_CM, float(room.get('w') or 0) + CAM_SLACK_CM, 'cam.x'),
           'y': _num(raw.get('y'), -CAM_SLACK_CM, float(room.get('d') or 0) + CAM_SLACK_CM, 'cam.y'),
           'rot': _num(raw.get('rot', 0), -720, 720, 'cam.rot'),
           'fov': _num(raw.get('fov', 90), 20, 140, 'cam.fov')}
    if raw.get('pose') is not None:
        out['pose'] = int(_num(raw['pose'], 0, 99, 'cam.pose', 0))
    if raw.get('pshift') is not None:
        out['pshift'] = _num(raw['pshift'], -1, 1, 'cam.pshift', 3)
    return out


def _tour_name(sku) -> dict:
    """В хеш — имя и ключ карточки только у товара без `sid` (тур): хеш заказов /demo остаётся прежним."""
    sku = sku or {}
    if sku.get('sid') is not None:
        return {}
    k = {'name': sku.get('name')}
    k.update({f: sku[f] for f in ('colour', 'tint') if f in sku})
    return k


def canonicalize(data: dict, req: dict, source: str = 'demo') -> dict:
    """Запрос страницы + данные → снимок: {'v', 'source', 'scene_hash', 'key', 'variant' (всё для сборки сцены), 'brief' (что в хеше)}.
    Отказ — `SnapshotError`. Данные не меняются."""
    if not isinstance(req, dict) or req.get('v') != SNAPSHOT_VERSION:
        raise SnapshotError(422, 'bad_version', 'Страница устарела. Обновите её и повторите.',
                            'The page is out of date. Reload it and try again.')
    base = _find_variant(data, req.get('variant_id'))
    room = room_of(data, base)
    if not (room.get('w') and room.get('d')):
        raise SnapshotError(409, 'not_ready', 'Данные комнаты неполные.', 'The room data is incomplete.')
    if req.get('room_id') is not None and req['room_id'] != (base.get('room_id') or 'living'):
        raise SnapshotError(409, 'stale', 'Кадры сняты в другой комнате. Откройте эту комнату заново.',
                            'The views were taken in another room. Open this room again.')
    rr = req.get('room')
    if isinstance(rr, dict):
        for k in ('w', 'd'):
            if rr.get(k) is not None and abs(float(rr[k]) - float(room[k])) > 1:
                raise SnapshotError(409, 'stale', 'Размеры комнаты изменились. Обновите страницу.',
                                    'The room size has changed. Reload the page.')
    skus = sku_index(data)
    msids = msid_index(data)
    roles = {str(i.get('role')) for v in data.get('variants') or [] for i in (v.get('items') or []) if i.get('role')}
    raw_items = req.get('items')
    base_items = base.get('items') or []
    if raw_items is None:
        raw_items = [{'role': i['role'], 'x': i['x'], 'y': i['y'], 'rot': i.get('rot') or 0,
                      **({'sid': i['sku']['sid']} if (i.get('sku') or {}).get('sid') is not None
                         else {'msid': (i.get('sku') or {}).get('msid') or None, 'name': (i.get('sku') or {}).get('name')})}
                     for i in base_items]
    if not isinstance(raw_items, list) or not (1 <= len(raw_items) <= MAX_ITEMS):
        raise SnapshotError(422, 'bad_snapshot', 'Расстановка не принята: число предметов вне допустимого.',
                            'The layout was not accepted: the number of items is out of range.')
    items = [_item(r, base_items, roles, skus, room, msids) for r in raw_items]
    raw_cams = req.get('cams')
    if raw_cams is None:
        raw_cams = [c for c in base.get('cams') or [] if c.get('name') in CAM_NAMES]
    if not isinstance(raw_cams, list) or len(raw_cams) != 2:
        raise SnapshotError(422, 'bad_cams', 'Расстановка не принята: нужны два ракурса C1 и C2.',
                            'The layout was not accepted: two views, C1 and C2, are required.')
    cams = sorted((_cam(c, room) for c in raw_cams), key=lambda c: c['name'])
    if [c['name'] for c in cams] != list(CAM_NAMES):
        raise SnapshotError(422, 'bad_cams', 'Расстановка не принята: нужны два ракурса C1 и C2.',
                            'The layout was not accepted: two views, C1 and C2, are required.')
    decor = copy.deepcopy(base.get('decor') or [])
    # состав хеша: всё, что меняет картинку; данные декора — по составу (товар и места), сборка данных — отдельным полем
    brief = {'v': SNAPSHOT_VERSION, 'source': source, 'apartment': data.get('apartment_id') or '', 'build': data.get('build') or '',
             'variant': base.get('id'), 'room': {'w': room.get('w'), 'd': room.get('d')}, 'style': base.get('style') or '',
             'items': sorted(({'role': i['role'], 'sid': i['sku'].get('sid'), 'msid': i['sku'].get('msid'), **_tour_name(i['sku']), 'x': i['x'], 'y': i['y'],
                               'rot': i['rot'], 'w': i['w'], 'd': i['d'], 'h': i['h'], 'corner': i['corner'], 'corner_left': i['corner_left'],
                               'section': i['section']} for i in items), key=lambda r: (r['role'], str(r['sid']), r['x'], r['y'], r['rot'])),
             'decor': sorted(({'role': d.get('role'), 'sid': (d.get('sku') or {}).get('sid'), **_tour_name(d.get('sku')), 'strategy': d.get('strategy'),
                               'place': d.get('place'), 'look': d.get('look')} for d in decor),
                             key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False)),
             'cams': cams}
    scene_hash = hashlib.sha256(json.dumps(brief, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    variant = {k: copy.deepcopy(v) for k, v in base.items() if k not in ('items', 'decor', 'cams')}
    variant.update(items=items, decor=decor, cams=cams)
    sr = (data.get('rules') or {}).get('soft_roles')
    return {'v': SNAPSHOT_VERSION, 'source': source, 'scene_hash': scene_hash, 'variant': variant, 'room': dict(room), 'brief': brief,
            'rules': {'soft_roles': sr} if isinstance(sr, list) else {}}


def synthetic_data(data: dict, snap: dict) -> dict:
    """Данные в формате витрины с ОДНИМ вариантом (расстановка снимка): их читают `export_scene.py` и `demo_scene_dump.mjs`
    (оба ждут `variants[idx]`, `rooms_geo`, `room`, `rules`); индекс варианта — 0."""
    rid = snap['variant'].get('room_id') or 'living'
    return {'room': data.get('room'), 'rooms_geo': {rid: snap['room']}, 'apartment_id': data.get('apartment_id'),
            'rules': snap.get('rules') or {}, 'build': data.get('build'), 'variants': [snap['variant']]}


def legacy_items(snap: dict) -> list:
    """Предметы снимка в формате заказа фото нейросети (`draft`/`improve_mode`): тот же список, что собирает страница в `payload()`."""
    out = []
    for it in snap['variant']['items']:
        sk = it.get('sku') or {}
        out.append({'role': it['role'], 'x': it['x'], 'y': it['y'], 'rot': it.get('rot') or 0, 'w': it['w'], 'd': it['d'], 'h': it['h'],
                    'corner': it['corner'], 'corner_left': it['corner_left'], 'section': it.get('section'),
                    'sid': sk.get('sid'), 'msid': sk.get('msid') or sk.get('sid'), 'name': sk.get('name'), 'hung': sk.get('hung'),
                    'pack': sk.get('pack'), 'img': sk.get('img'), 'swatch': sk.get('swatch')})
    return out


DEMO_HASH_PINNED = '038fc80d7f6903e51506fd2f9b608ececd96520a2898a16f372eaa8fc7ae9f68'   # scene_hash снимка по умолчанию v1 из самопроверки — снят до T-20261117-20/3


def _selftest() -> int:
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + name)
        bad += 0 if c else 1

    def sk(sid, w=100, d=50, h=80, **kw):
        return {'sid': sid, 'msid': sid, 'name': 'Товар ' + sid, 'w': w, 'd': d, 'h': h, 'img': 'img/' + sid + '.jpg', **kw}
    sofa, sofa2, lamp = sk('s1', 200, 90, 85), sk('s2', 180, 80, 80), sk('l1', 30, 30, 150)
    cams = [{'name': 'C1', 'x': 50, 'y': 40, 'rot': 105, 'fov': 90, 'pose': 3, 'pshift': -0.04},
            {'name': 'C2', 'x': 400, 'y': 280, 'rot': -69, 'fov': 90}]
    data = {'apartment_id': 'a1', 'build': 'b1', 'room': {'w': 439, 'd': 325, 'title': 'Гостиная'}, 'rules': {}, 'rooms_geo': {},
            'variants': [{'id': 'v1', 'room_id': 'living', 'style': 'сканди', 'cams': cams,
                          'items': [{'role': 'диван', 'x': 220, 'y': 270, 'rot': 180, 'w': 200, 'd': 90, 'h': 85, 'sku': sofa,
                                     'corner': False, 'corner_left': False, 'section': None},
                                    {'role': 'торшер', 'x': 30, 'y': 30, 'rot': 0, 'w': 30, 'd': 30, 'h': 150, 'sku': lamp,
                                     'corner': False, 'corner_left': False, 'section': None}],
                          'decor': [{'role': 'шторы', 'strategy': 'textile_abstract', 'sku': sk('c1'),
                                     'place': {'x': 0, 'y': 145, 'kind': 'curtain'}, 'look': {'hex': '#aabbcc', 'of': 'c1'}}]},
                         {'id': 'v2', 'room_id': 'living', 'style': 'лофт', 'cams': cams, 'items': [
                             {'role': 'диван', 'x': 100, 'y': 100, 'rot': 0, 'w': 180, 'd': 80, 'h': 80, 'sku': sofa2,
                              'corner': False, 'corner_left': False, 'section': None}], 'decor': []}]}

    s = canonicalize(data, {'v': 1, 'variant_id': 'v1'})
    ok(len(s['scene_hash']) == 64 and len(s['variant']['items']) == 2 and len(s['variant']['cams']) == 2, 'снимок по умолчанию — предметы и позы варианта')
    ok(s['variant']['decor'] == data['variants'][0]['decor'], 'декор — из данных варианта')
    # тот же состав, другой порядок и «шум» округления — тот же хеш
    r1 = {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'торшер', 'sid': 'l1', 'x': 30.04, 'y': 30, 'rot': 0},
                                                {'role': 'диван', 'sid': 's1', 'x': 220, 'y': 270, 'rot': 180}]}
    ok(canonicalize(data, r1)['scene_hash'] == s['scene_hash'], 'порядок предметов и округление до 0,1 см хеш не меняют')
    r2 = {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'торшер', 'sid': 'l1', 'x': 31, 'y': 30, 'rot': 0},
                                                {'role': 'диван', 'sid': 's1', 'x': 220, 'y': 270, 'rot': 180}]}
    ok(canonicalize(data, r2)['scene_hash'] != s['scene_hash'], 'сдвиг предмета на 1 см — другой хеш')
    # замена товара: размеры — из товара, не от страницы
    r3 = {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'sid': 's2', 'x': 220, 'y': 270, 'rot': 180, 'w': 999}]}
    c3 = canonicalize(data, r3)
    ok(c3['variant']['items'][0]['w'] == 180 and c3['variant']['items'][0]['sku']['sid'] == 's2', 'размеры замены — из данных (страница их не присылает)')
    # отказы
    def fails(req, code, status=None):
        try:
            canonicalize(data, req)
        except SnapshotError as e:
            return e.code == code and (status is None or e.status == status) and bool(e.ru) and bool(e.en)
        return False
    ok(fails({'v': 2, 'variant_id': 'v1'}, 'bad_version'), 'чужая версия контракта — отказ')
    ok(fails({'v': 1, 'variant_id': 'v-none'}, 'unknown_variant', 404), 'неизвестный вариант — 404')
    ok(fails({'v': 1, 'variant_id': 'v1', 'room_id': 'bedroom-1'}, 'stale', 409), 'другая комната — stale')
    ok(fails({'v': 1, 'variant_id': 'v1', 'room': {'w': 600, 'd': 325}}, 'stale', 409), 'другие размеры комнаты — stale')
    ok(fails({'v': 1, 'variant_id': 'кириллица'}, 'bad_snapshot'), 'номер варианта не по шаблону — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'sid': 'нет-такого', 'x': 1, 'y': 1}]}, 'bad_item'), 'товара нет в данных — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'ракета', 'sid': 's1', 'x': 1, 'y': 1}]}, 'bad_item'), 'неизвестная роль — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'sid': 's1', 'x': 900, 'y': 1}]}, 'bad_snapshot'), 'предмет вне комнаты — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'sid': 's1', 'x': 'a', 'y': 1}]}, 'bad_snapshot'), 'не число — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'sid': 's1', 'x': 1, 'y': 1}] * 41}, 'bad_snapshot'), 'больше MAX_ITEMS — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'items': []}, 'bad_snapshot'), 'пустая расстановка — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'cams': [cams[0]]}, 'bad_cams'), 'один ракурс — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'cams': [cams[0], dict(cams[0])]}, 'bad_cams'), 'C1 дважды — отказ')
    ok(fails({'v': 1, 'variant_id': 'v1', 'cams': [cams[0], dict(cams[1], fov=500)]}, 'bad_snapshot'), 'обзор вне пределов — отказ')
    data2 = copy.deepcopy(data)
    data2['variants'][0]['items'][0]['sku']['w'] = None
    data2['variants'][0]['items'][0]['w'] = None
    try:
        canonicalize(data2, {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'sid': 's1', 'x': 1, 'y': 1}]})
        ok(False, 'товар без ширины — отказ no_dims')
    except SnapshotError as e:
        ok(e.code == 'no_dims' and e.status == 422, 'товар без ширины — отказ no_dims')
    # новая сборка данных → другой хеш (кэш не отдаёт кадр старых данных)
    d3 = copy.deepcopy(data); d3['build'] = 'b2'
    ok(canonicalize(d3, {'v': 1, 'variant_id': 'v1'})['scene_hash'] != s['scene_hash'], 'новая сборка данных — другой хеш')
    syn = synthetic_data(data, s)
    ok(len(syn['variants']) == 1 and syn['rooms_geo']['living']['w'] == 439, 'данные из одного варианта для выгрузчиков')
    d4 = copy.deepcopy(data)
    d4['variants'][0]['items'][0].update(h=None, role='диван')
    d4['variants'][0]['items'][0]['sku']['h'] = None
    ok(canonicalize(d4, {'v': 1, 'variant_id': 'v1'})['variant']['items'][0]['h'] is None, 'плоский предмет без высоты (ковёр) принимается как есть')
    li = legacy_items(s)
    ok(li[0]['sid'] == 's1' and li[0]['msid'] == 's1' and li[0]['img'] == 'img/s1.jpg', 'предметы в формате заказа нейросети')
    # ТУР (T-20261117-20/3): карточки без sid, ключ — пара (msid, name); /demo-хеш от этого не меняется
    def tk(msid, name, w=100, d=50, h=80, **kw):
        return {'msid': msid, 'name': name, 'w': w, 'd': d, 'h': h, 'price': 100, **kw}
    t1, t1b, t2, t3 = tk('m1', 'Диван А', 200, 90, 85, colour='серый'), tk('m1', 'Диван Б', 180, 80, 80, colour='беж'), tk('m2', 'Лампа', 30, 30, 150), tk('m3', 'Шторы')
    tdata = copy.deepcopy(data)
    tdata['variants'][0]['items'][0]['sku'], tdata['variants'][0]['items'][1]['sku'] = t1, t2
    tdata['variants'][0]['decor'] = [{'role': 'шторы', 'strategy': 'textile_abstract', 'sku': t3, 'place': {'x': 0, 'y': 145, 'kind': 'curtain'}, 'look': {'hex': '#aabbcc'}}]
    tdata['variants'][1]['items'][0]['sku'] = t1b          # тот же msid, другое имя и размеры — цвет семейства
    ts = canonicalize(tdata, {'v': 1, 'variant_id': 'v1'})
    treq = {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'торшер', 'msid': 'm2', 'name': 'Лампа', 'x': 30, 'y': 30, 'rot': 0},
                                                  {'role': 'диван', 'msid': 'm1', 'name': 'Диван А', 'x': 220, 'y': 270, 'rot': 180}]}
    tc = canonicalize(tdata, treq)
    ok(tc['scene_hash'] == ts['scene_hash'] and len(tc['variant']['items']) == 2, 'тур: заказ по (msid, name) = предметы варианта, тот же хеш')
    ok(tc['variant']['items'][1]['w'] == 200 and 'sid' not in tc['variant']['items'][1]['sku'], 'тур: размеры из карточки данных, sid в снимок не попадает')
    tr = {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'msid': 'm1', 'name': 'Диван Б', 'x': 220, 'y': 270, 'rot': 180}]}
    tcb = canonicalize(tdata, tr)
    ok(tcb['variant']['items'][0]['w'] == 180 and tcb['scene_hash'] != ts['scene_hash'], 'тур: замена на другую карточку того же msid — свои размеры и другой хеш')

    def tfails(req, d=tdata):
        try:
            canonicalize(d, req)
        except SnapshotError as e:
            return e.code == 'bad_item' and e.status == 422 and bool(e.ru) and bool(e.en)
        return False
    ok(tfails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'msid': 'm1', 'name': 'Нет такого', 'x': 1, 'y': 1}]}), 'тур: пары нет — bad_item')
    ok(tfails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'msid': 'm1', 'x': 1, 'y': 1}]}), 'тур: нет имени — bad_item')
    ok(tfails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'x': 1, 'y': 1}]}), 'тур: ни sid, ни msid — bad_item')
    amb = copy.deepcopy(tdata)
    amb['variants'][1]['items'][0]['sku'] = tk('m1', 'Диван А', 150, 70, 70, colour='красный')
    ok(tfails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'msid': 'm1', 'name': 'Диван А', 'x': 1, 'y': 1}]}, amb), 'тур: пара с двумя разными карточками — bad_item, не угадывание')
    same = copy.deepcopy(tdata)
    same['variants'][1]['items'][0]['sku'] = copy.deepcopy(t1)
    ok(canonicalize(same, treq)['scene_hash'] == ts['scene_hash'], 'тур: одна и та же карточка в двух местах — не двусмысленность')
    tcol = copy.deepcopy(tdata); tcol['variants'][0]['decor'][0]['sku'] = tk('m3', 'Шторы', colour='синий')
    ok(canonicalize(tcol, {'v': 1, 'variant_id': 'v1'})['scene_hash'] != ts['scene_hash'], 'тур: другой товар декора — другой хеш')
    cp = copy.deepcopy(tdata); cp['variants'][0]['items'][1]['sku'] = {'msid': None, 'name': 'Ковёр Мирна', 'w': 200, 'd': 300, 'h': 1}
    cpr = canonicalize(cp, {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'торшер', 'name': 'Ковёр Мирна', 'x': 30, 'y': 30, 'rot': 0}]})
    ok(cpr['variant']['items'][0]['sku']['name'] == 'Ковёр Мирна', 'тур: заглушка без модели (msid null) — ключ одно имя')
    ok(tfails({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'торшер', 'name': 'Ковёр Мирна', 'x': 30, 'y': 30, 'rot': 0}]}), 'тур: имя заглушки без msid, когда в данных такого нет — bad_item')
    # /demo-хеш прежний (значение снято на коде до этой правки): sid-карточки хешируются как раньше
    ok(s['scene_hash'] == DEMO_HASH_PINNED, 'хеш /demo-заказа не изменился: ' + s['scene_hash'][:12])
    print('итог:', 'чисто' if not bad else f'{bad} провал(ов)')
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())


if __name__ == '__main__' and '--canon' in sys.argv:
    # `render_snapshot.py --canon <данные.json> <заказ.json>` → {"ok": true, "scene_hash", "items"} | {"ok": false, "code", "status"} — для тестов на настоящих данных тура
    _d = json.load(open(sys.argv[sys.argv.index('--canon') + 1], encoding='utf-8'))
    _r = json.load(open(sys.argv[sys.argv.index('--canon') + 2], encoding='utf-8'))
    try:
        _s = canonicalize(_d, _r, 'trial')
        print(json.dumps({'ok': True, 'scene_hash': _s['scene_hash'], 'items': len(_s['variant']['items'])}))
    except SnapshotError as _e:
        print(json.dumps({'ok': False, 'code': _e.code, 'status': _e.status}))
