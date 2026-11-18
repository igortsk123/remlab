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
   "items": [{"role", "sid" | "pid" | "ref", "x", "y", "rot", "corner"?, "corner_left"?, "section"?}, …]   нет — предметы варианта как есть
      (`sid` — ключ товара данных витрины; `pid` — публичный ключ товара тура `p1:…`, у публичных данных тура `sid` нет, T-20261118-03/9;
      `ref` — номер предмета в `variant.items` для ПЛОСКОГО предмета без меша (`strategy: procedural_plane`: ковёр, картина, зеркало) — его данные берутся из варианта)
   "cams":  [{"name": "C1"|"C2", "x", "y", "rot", "fov", "pose"?, "pshift"?}, …]            нет — позы варианта}

Что проверяется: предметов ≤ MAX_ITEMS; `sid` (или `pid`) есть в данных (индекс товаров по всем местам данных) и у товара есть размеры;
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

import asset_strategy as AS
import scene_inputs as SI

SNAPSHOT_VERSION = 1
MAX_ITEMS = 40
SLACK_CM = 5.0               # предмет может касаться стены в пределах округления
CAM_SLACK_CM = 100.0         # камера у самой стены или в проёме
SID_RE = re.compile(r'^[0-9A-Za-z_.:\-]{1,80}$')
ID_RE = re.compile(r'^[0-9A-Za-z_.:\-]{1,80}$')
PID_RE = re.compile(r'^p1:[0-9a-f]{24}$')     # публичный ключ товара тура (`trial_bundle.pid_of`); в `sid`/`msid` он не попадает никогда
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


def pid_index(data: dict) -> dict:
    """pid → карточка товара по ВСЕМ местам данных (то же, что `sku_index`, но по публичному ключу тура). Карточки с одним `pid`, но разным
    товаром (название или плитка фото) — неоднозначно: ключ в индексе помечается `None`, заказ с ним отказывается (`bad_item`), а не берёт первую."""
    idx: dict = {}

    def walk(o):
        if isinstance(o, dict):
            p = o.get('pid')
            if isinstance(p, str) and PID_RE.match(p) and isinstance(o.get('name'), str):
                if p not in idx:
                    idx[p] = o
                elif idx[p] is not None and idx[p].get('name') != o.get('name'):
                    idx[p] = None
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return idx


def flat_base_card(base_items: list, ref, role: str):
    """РЕШЕНИЕ БЕЗ КАРТОЧКИ (T-20261118-03/9, директор): процедурный плоский предмет (`strategy: procedural_plane` — ковёр, картина, зеркало; меша у него нет)
    рисуется по ДАННЫМ САМОГО ПРЕДМЕТА варианта (`sku`: фото, размеры, цвет) — ключ товара для кадра не нужен. `ref` — номер предмета в `variant.items`;
    роль должна совпасть, а плоский ли предмет — решает КАНОН ролей (`asset_strategy.strategy(role)`, как в `draft_render`), а не поле `strategy` данных
    (у части перенесённых предметов тура его нет). Иначе None (заказ откажется `bad_item`). Данные берём из варианта на сервере, не от страницы."""
    if not isinstance(ref, int) or isinstance(ref, bool) or not (0 <= ref < len(base_items)):
        return None
    b = base_items[ref]
    if not isinstance(b, dict) or b.get('role') != role or AS.strategy(role) != 'procedural_plane' or not isinstance(b.get('sku'), dict):
        return None
    return b['sku']


def _key_of(item: dict, n: int) -> dict:
    """Как назвать предмет варианта в заказе «как есть»: `sid` витрины, иначе `pid` тура, иначе (плоский предмет без ключа) — номер `ref`."""
    sku = item.get('sku') or {}
    if sku.get('sid'):
        return {'sid': sku['sid']}
    if sku.get('pid'):
        return {'pid': sku['pid']}
    return {'ref': n} if AS.strategy(item.get('role')) == 'procedural_plane' else {}


def product_key(sku: dict):
    """Ключ товара карточки для сравнения «тот же предмет»: `sid` (витрина), иначе `pid` (тур); нет ни того ни другого — None (не равен никому)."""
    sku = sku or {}
    return ('sid', str(sku['sid'])) if sku.get('sid') not in (None, '') else (('pid', sku['pid']) if sku.get('pid') else None)


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


def _rules_of_build(build) -> str:
    """Метка сборки данных `<git>.<правила>` (`build_stamp.py`) → в хеш только `<правила>` (решение директора 18.11): коммит кода сам по себе кадры не меняет —
    правка решателя меняет снимок (расстановку), а она уже в хеше; git-часть сдвигала бы ключ всех комнат на каждый коммит (и перерисовку за деньги).
    Метка без точки (тест, чужой формат) — как есть. Само поле `build` в данных и у других потребителей не меняется."""
    b = str(build or '')
    return b.rsplit('.', 1)[1] if '.' in b else b


def _pid_in_hash(sku: dict) -> dict:
    """Личность товара в хеше — только там, где у карточки нет `sid` (тур): два разных ковра одного размера и плитки не должны делить кадр.
    У /demo (`sid` есть) и у карточек без `pid` ключа нет вовсе — их хеши и готовые кадры не меняются (тест `_selftest`)."""
    return {'pid': sku['pid']} if not sku.get('sid') and sku.get('pid') else {}


def _sku_inputs(sku: dict, mesh: bool) -> dict:
    """Что в товаре меняет кадр, но не было в хеше: подкраска, образец ткани, фото-текстура (ковёр, картина — файл в `img/`) и, у предмета
    мебели, файл меша (`msid` или `sid`: перегенерация меша — новые кадры только тех комнат, где он стоит). Пустое не пишем — ключ тех, у кого
    этих полей нет, зависит только от них самих."""
    out: dict = {}
    for k in ('tint', 'swatch', 'img'):
        if sku.get(k) not in (None, '', []):
            out[k] = sku[k]
    if sku.get('img'):
        sha = SI.img_sha(sku['img'])
        if sha:
            out['img_sha'] = sha
    if mesh:
        sha = SI.mesh_sha(sku.get('msid') or sku.get('sid'))
        if sha:
            out['mesh_sha'] = sha
    return out


def _item(raw, base_items: list, roles: set, skus: dict, room: dict, pids: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise SnapshotError(422, 'bad_snapshot', 'Расстановка не принята: предмет записан неверно.',
                            'The layout was not accepted: an item is malformed.')
    role = raw.get('role')
    if not isinstance(role, str) or not (1 <= len(role) <= 40) or role not in roles:
        raise SnapshotError(422, 'bad_item', 'Расстановка не принята: неизвестный вид предмета.',
                            'The layout was not accepted: unknown item type.')
    sid, pid, ref = str(raw.get('sid') or ''), raw.get('pid'), raw.get('ref')
    if ref is not None:                          # плоский предмет без меша (ковёр, картина, зеркало): данные — предмета варианта, карточку не ищем
        card = flat_base_card(base_items, ref, role) if not sid and pid is None else None
    elif sid:                                      # ключ витрины (демо; так же — тур со `sid` в данных)
        card = skus.get(sid) if SID_RE.match(sid) else None
        if card is not None and pid is not None and card.get('pid') not in (None, pid):
            card = None                          # оба ключа названы и указывают на разные товары — не угадываем
    else:                                        # публичный ключ тура: карточку берём из ДАННЫХ, не от страницы; неоднозначный ключ — отказ
        card = (pids or {}).get(pid) if isinstance(pid, str) and PID_RE.match(pid) else None
        if card is not None:                     # предмет этой комнаты с тем же ключом — его карточка (фото и цвет те же, что на странице)
            card = next((b['sku'] for b in base_items if isinstance(b.get('sku'), dict) and b['sku'].get('pid') == pid), card)
    if card is None:
        raise SnapshotError(422, 'bad_item', 'Расстановка не принята: товара нет в данных. Обновите страницу.',
                            'The layout was not accepted: the product is not in the data. Reload the page.')
    sku = card
    x = _num(raw.get('x'), -SLACK_CM, float(room.get('w') or 0) + SLACK_CM, 'x')
    y = _num(raw.get('y'), -SLACK_CM, float(room.get('d') or 0) + SLACK_CM, 'y')
    rot = _num(raw.get('rot', 0), -720, 720, 'rot')
    # тот же предмет варианта (роль и товар совпали) — его размеры (`dims_src` каталога/расчёта); иначе — размеры товара
    key = product_key(sku)
    if ref is not None:
        same = base_items[ref]
    else:
            same = next((b for b in base_items if key is not None and b.get('role') == role and product_key(b.get('sku')) == key), None)
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
    skus, pids = sku_index(data), pid_index(data)
    roles = {str(i.get('role')) for v in data.get('variants') or [] for i in (v.get('items') or []) if i.get('role')}
    raw_items = req.get('items')
    base_items = base.get('items') or []
    if raw_items is None:
        raw_items = [{'role': i['role'], **_key_of(i, n), 'x': i['x'], 'y': i['y'], 'rot': i.get('rot') or 0} for n, i in enumerate(base_items)]
    if not isinstance(raw_items, list) or not (1 <= len(raw_items) <= MAX_ITEMS):
        raise SnapshotError(422, 'bad_snapshot', 'Расстановка не принята: число предметов вне допустимого.',
                            'The layout was not accepted: the number of items is out of range.')
    items = [_item(r, base_items, roles, skus, room, pids) for r in raw_items]
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
    brief = {'v': SNAPSHOT_VERSION, 'source': source, 'apartment': data.get('apartment_id') or '', 'build': _rules_of_build(data.get('build')),
             'variant': base.get('id'), 'room': {'w': room.get('w'), 'd': room.get('d')}, 'style': base.get('style') or '',
             'items': sorted(({'role': i['role'], 'sid': i['sku'].get('sid'), 'msid': i['sku'].get('msid'), 'x': i['x'], 'y': i['y'],
                               'rot': i['rot'], 'w': i['w'], 'd': i['d'], 'h': i['h'], 'corner': i['corner'], 'corner_left': i['corner_left'],
                               'section': i['section'], **_pid_in_hash(i['sku']), **_sku_inputs(i['sku'], mesh=True)} for i in items),
                            key=lambda r: (r['role'], str(r['sid']), str(r.get('pid')), r['x'], r['y'], r['rot'])),
             'decor': sorted(({'role': d.get('role'), 'sid': (d.get('sku') or {}).get('sid'), 'strategy': d.get('strategy'),
                               'place': d.get('place'), 'look': d.get('look'), **_pid_in_hash(d.get('sku') or {}), **_sku_inputs(d.get('sku') or {}, mesh=False)} for d in decor),
                             key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False)),
             'cams': cams, 'env': SI.env_sha()}
    scene_hash = hashlib.sha256(json.dumps(brief, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    variant = {k: copy.deepcopy(v) for k, v in base.items() if k not in ('items', 'decor', 'cams')}
    variant.update(items=items, decor=decor, cams=cams)
    sr = (data.get('rules') or {}).get('soft_roles')
    rules = {'soft_roles': sr} if isinstance(sr, list) else {}
    # КЛЮЧ ПО КОМНАТЕ (T-20261118-04/16/1): вход рендера v2 — отпечаток сцены этой комнаты без метки выкладки и правил экрана (`render_input.py`).
    # Включён `RENDER_KEY_V2` — `scene_hash` и есть этот отпечаток (его видят задания, кэш подготовки, meta); выключен — прежний `scene_hash`, v2 лежит рядом (`scene_digest`).
    import render_input as RI
    fi = RI.build(room, variant, cams, rules)
    return {'v': SNAPSHOT_VERSION, 'source': source, 'scene_hash': fi['digest'] if RI.v2_on() else scene_hash, 'legacy_hash': scene_hash, 'scene_digest': fi['digest'],
            'frame_inputs': {k: fi[k] for k in ('schema', 'scene', 'assets', 'missing')}, 'variant': variant, 'room': dict(room), 'brief': brief, 'rules': rules}


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
    # ВХОДЫ-ФАЙЛЫ И МЕТКА СБОРКИ (T-20261118-09/1): диски — во временных папках, чтобы тест не зависел от машины
    import os as _os
    import tempfile as _tf
    tmp = _tf.mkdtemp(prefix='snap-inputs-')
    for k, sub in (('SCENE_INPUTS_PUBLIC', 'public'), ('SCENE3D_CACHE', 'mcache'), ('SCENE_INPUTS_GALLERY', 'gallery'), ('SCENE_INPUTS_INDEX', 'idx/i.json'), ('DEMO_LOCAL_DIR', 'demo')):
        _os.environ[k] = _os.path.join(tmp, sub)
    for sub in ('public/flat3d/env', 'public/scene/views', 'mcache', 'demo/img'):
        _os.makedirs(_os.path.join(tmp, sub), exist_ok=True)
    SI._ENV_MEMO.clear()
    SI.ENV_TTL_S = 0
    h = lambda dd: canonicalize(dd, {'v': 1, 'variant_id': 'v1'})['scene_hash']  # noqa: E731
    h0 = h(data)
    dg = copy.deepcopy(data); dg['build'] = 'abc1234567.' + str(data.get('build') or 'x').rsplit('.', 1)[-1]
    dg2 = copy.deepcopy(data); dg2['build'] = 'fff9999999.' + str(data.get('build') or 'x').rsplit('.', 1)[-1]
    ok(h(dg) == h(dg2), 'метка сборки: смена git-части хеш не меняет (коммит кадры не сбрасывает)')
    dr = copy.deepcopy(data); dr['build'] = 'abc1234567.otherrules'
    ok(h(dr) != h(dg), 'метка сборки: смена правил — другой хеш')
    dt = copy.deepcopy(data); dt['variants'][0]['items'][0]['sku']['tint'] = [1.2, 1.0, 0.8]
    ok(h(dt) != h0, 'подкраска товара (tint) — другой хеш')
    dw = copy.deepcopy(data); dw['variants'][0]['items'][0]['sku']['swatch'] = '#aabbcc'
    ok(h(dw) != h0, 'образец ткани (swatch) — другой хеш')
    sid0 = data['variants'][0]['items'][0]['sku']['sid']
    open(_os.path.join(tmp, 'mcache', sid0 + '.glb'), 'wb').write(b'a' * 2000)
    hm1 = h(data)
    ok(hm1 != h0, 'меш товара появился на диске — хеш с ним')
    open(_os.path.join(tmp, 'mcache', sid0 + '.glb'), 'wb').write(b'b' * 2100)
    ok(h(data) != hm1, 'меш перегенерирован (тот же sid, другой файл) — другой хеш')
    open(_os.path.join(tmp, 'mcache', sid0 + '.glb'), 'wb').write(b'a' * 2000)
    ok(h(data) == hm1, 'тот же файл меша — тот же хеш')
    _os.remove(_os.path.join(tmp, 'mcache', sid0 + '.glb'))
    ok(h(data) == hm1, 'кэш мешей вытеснил файл — хеш из индекса прежний (комнату не перерисовываем)')
    he1 = h(data)
    open(_os.path.join(tmp, 'public/flat3d/env/outside.webp'), 'wb').write(b'x' * 50)
    ok(h(data) != he1, 'картинка окружения заменена — другой хеш')
    he2 = h(data)
    open(_os.path.join(tmp, 'public/scene/views/yard.webp'), 'wb').write(b'y' * 60)
    ok(h(data) != he2, 'вид из окна заменён — другой хеш')
    di = copy.deepcopy(data); di['variants'][0]['items'][0]['sku']['img'] = 'img/rug.jpg'
    hi1 = h(di)
    open(_os.path.join(tmp, 'demo/img/rug.jpg'), 'wb').write(b'1' * 70)
    hi2 = h(di)
    ok(hi2 != hi1, 'фото-текстура товара появилась на диске — другой хеш')
    open(_os.path.join(tmp, 'demo/img/rug.jpg'), 'wb').write(b'2' * 70)
    ok(h(di) != hi2, 'фото-текстура товара заменена — другой хеш')
    syn = synthetic_data(data, s)
    ok(len(syn['variants']) == 1 and syn['rooms_geo']['living']['w'] == 439, 'данные из одного варианта для выгрузчиков')
    d4 = copy.deepcopy(data)
    d4['variants'][0]['items'][0].update(h=None, role='диван')
    d4['variants'][0]['items'][0]['sku']['h'] = None
    ok(canonicalize(d4, {'v': 1, 'variant_id': 'v1'})['variant']['items'][0]['h'] is None, 'плоский предмет без высоты (ковёр) принимается как есть')
    li = legacy_items(s)
    ok(li[0]['sid'] == 's1' and li[0]['msid'] == 's1' and li[0]['img'] == 'img/s1.jpg', 'предметы в формате заказа нейросети')
    # ——— публичные данные тура (T-20261118-03/9): у карточек нет `sid`, есть `pid` (и `msid` или null у ковра)
    pa, pb, pc = 'p1:' + 'a' * 24, 'p1:' + 'b' * 24, 'p1:' + 'c' * 24

    def tsk(pid, name, **kw):
        return {'pid': pid, 'name': name, 'w': 100, 'd': 50, 'h': 80, **kw}
    tour = {'apartment_id': 't1', 'build': 'b1', 'room': {'w': 439, 'd': 325}, 'rules': {}, 'rooms_geo': {},
            'variants': [{'id': 'tv1', 'room_id': 'living', 'style': 'сканди', 'cams': cams, 'decor': [], 'items': [
                {'role': 'диван', 'x': 220, 'y': 270, 'rot': 180, 'w': 200, 'd': 90, 'h': 85, 'sku': tsk(pa, 'Диван', msid='m1', w=200, d=90, h=85)},
                {'role': 'ковёр', 'x': 220, 'y': 160, 'rot': 0, 'w': 230, 'd': 160, 'h': 1,
                 'sku': tsk(pb, 'Ковёр Б', msid=None, img='img/bbbbbbbbbbbbbbbb.jpg', w=230, d=160, h=1)}]}],
            'feeds': {'ковёр': [tsk(pc, 'Ковёр В', msid=None, img='img/cccccccccccccccc.jpg', w=230, d=160, h=1)]}}

    def tbad(req, dat=tour):
        try:
            canonicalize(dat, req)
        except SnapshotError as e:
            return e.code
        return None
    ts = canonicalize(tour, {'v': 1, 'variant_id': 'tv1'})
    ok(len(ts['variant']['items']) == 2 and ts['variant']['items'][1]['sku']['pid'] == pb and ts['variant']['items'][1]['w'] == 230,
       'тур: снимок варианта без `sid` принимается (ковёр без msid), размеры — предмета варианта')
    swap = {'v': 1, 'variant_id': 'tv1', 'items': [{'role': 'ковёр', 'pid': pc, 'x': 220, 'y': 160, 'rot': 0},
                                                   {'role': 'диван', 'pid': pa, 'x': 220, 'y': 270, 'rot': 180}]}
    tw = canonicalize(tour, swap)
    ok(tw['variant']['items'][0]['sku']['name'] == 'Ковёр В' and tw['scene_hash'] != ts['scene_hash'], 'тур: замена ковра товаром ленты по `pid` — карточка из данных, другой хеш')
    same_geo = copy.deepcopy(tour)
    same_geo['variants'][0]['items'][1]['sku'].update(pid=pc, name='Ковёр В', img='img/bbbbbbbbbbbbbbbb.jpg')
    same_geo['feeds'] = {}
    ok(canonicalize(same_geo, {'v': 1, 'variant_id': 'tv1'})['scene_hash'] != ts['scene_hash'], 'тур: другой товар при том же размере и фото — другой хеш (личность `pid` в хеше)')
    ok(all(tbad({**swap, 'items': [{'role': 'ковёр', 'pid': x, 'x': 220, 'y': 160, 'rot': 0}]}) == 'bad_item'
           for x in ('p1:' + 'd' * 24, 'p1:XYZ', pa.upper(), pa + '0', '1_2', 5)), 'тур: неизвестный или кривой `pid` — bad_item')
    ok(tbad({**swap, 'items': [{'role': 'ковёр', 'sid': pb, 'x': 220, 'y': 160, 'rot': 0}]}) == 'bad_item', '`pid` в поле `sid` товаром не считается — bad_item')
    amb = copy.deepcopy(tour)
    amb['feeds']['ковёр'][0].update(pid=pb)                                           # один ключ — два разных товара: не первая карточка, а отказ
    ok(tbad({**swap, 'items': [{'role': 'ковёр', 'pid': pb, 'x': 220, 'y': 160, 'rot': 0}]}, amb) == 'bad_item', 'тур: один `pid` у двух разных товаров — bad_item, не первая карточка')
    # /demo и готовые кадры: `pid` рядом с `sid` в хеш НЕ идёт; карточка без `pid` — прежний хеш
    dp = copy.deepcopy(data)
    for v in dp['variants']:
        for it in v['items']:
            it['sku']['pid'] = pa
    ok(canonicalize(dp, {'v': 1, 'variant_id': 'v1'})['scene_hash'] == canonicalize(data, {'v': 1, 'variant_id': 'v1'})['scene_hash'], 'демо: `pid` рядом с `sid` хеш не меняет (готовые кадры целы)')
    both = {'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'sid': 's1', 'pid': pb, 'x': 220, 'y': 270, 'rot': 180}]}
    ok(tbad(both, dp) == 'bad_item', 'и `sid`, и `pid` названы, а карточка с другим `pid` — bad_item')
    # ——— тот же товар с другой плиткой фото в ленте — не коллизия; карточка комнаты — предмета варианта
    ph = copy.deepcopy(tour)
    own_name = tour['variants'][0]['items'][0]['sku']['name']
    ph['feeds']['ковёр'][0].update(pid=pa, name=own_name, img='img/9999999999999999.jpg')
    ph_snap = canonicalize(ph, {'v': 1, 'variant_id': 'tv1', 'items': [{'role': 'диван', 'pid': pa, 'x': 220, 'y': 270, 'rot': 180}]})
    ok(ph_snap['variant']['items'][0]['sku'].get('img') != 'img/9999999999999999.jpg' and ph_snap['variant']['items'][0]['sku'].get('img') == tour['variants'][0]['items'][0]['sku'].get('img'), 'тот же товар, другая плитка в ленте: не отказ, берётся карточка предмета комнаты')
    # ——— плоский предмет без меша и без ключа (ковёр вне витрины): данные — из варианта, карточку не ищем (директор, T-20261118-03/9)
    flat = copy.deepcopy(tour)
    rug = flat['variants'][0]['items'][1]
    rug.pop('strategy', None)                     # поля `strategy` в данных нет — решает канон ролей
    del rug['sku']['pid']
    fs = canonicalize(flat, {'v': 1, 'variant_id': 'tv1'})
    ok(fs['variant']['items'][1]['sku']['img'] == 'img/bbbbbbbbbbbbbbbb.jpg' and fs['variant']['items'][1]['w'] == 230 and 'pid' not in fs['variant']['items'][1]['sku'],
       'плоский ковёр без ключа: снимок «как есть» по данным предмета варианта')
    own = {'v': 1, 'variant_id': 'tv1', 'items': [{'role': 'ковёр', 'ref': 1, 'x': 200, 'y': 160, 'rot': 0},
                                                  {'role': 'диван', 'pid': pa, 'x': 220, 'y': 270, 'rot': 180}]}
    ok(canonicalize(flat, own)['variant']['items'][0]['sku']['img'] == 'img/bbbbbbbbbbbbbbbb.jpg', 'ковёр по `ref`: его же данные; двигать можно, размеры — предмета варианта')
    moved = canonicalize(flat, {**own, 'items': [{**own['items'][0], 'x': 210}, own['items'][1]]})
    ok(moved['scene_hash'] != canonicalize(flat, own)['scene_hash'] and moved['variant']['items'][0]['w'] == 230, 'сдвиг ковра — другой хеш, размеры те же')
    flat2 = copy.deepcopy(flat)
    flat2['variants'][0]['items'][1]['sku']['img'] = 'img/cccccccccccccccc.jpg'
    ok(canonicalize(flat2, own)['scene_hash'] != canonicalize(flat, own)['scene_hash'], 'другая картинка ковра — другой хеш (фото в хеше)')
    bad_ref = [{'role': 'ковёр', 'ref': 0}, {'role': 'диван', 'ref': 1}, {'role': 'ковёр', 'ref': 5}, {'role': 'ковёр', 'ref': -1}, {'role': 'ковёр', 'ref': True},
               {'role': 'ковёр', 'ref': '1'}, {'role': 'ковёр', 'ref': 1, 'pid': pb}, {'role': 'ковёр', 'ref': 1, 'sid': 's1'}]
    ok(all(tbad({'v': 1, 'variant_id': 'tv1', 'items': [{**x, 'x': 200, 'y': 160, 'rot': 0}]}, flat) == 'bad_item' for x in bad_ref),
       '`ref` на предмет другой роли, не плоский, вне списка, не число или вместе с ключом — bad_item')
    ok(tbad({'v': 1, 'variant_id': 'tv1'}, tour) is None and tbad({'v': 1, 'variant_id': 'v1', 'items': [{'role': 'диван', 'ref': 0, 'x': 1, 'y': 1, 'rot': 0}]}, data) == 'bad_item',
       'мебель по `ref` не берётся (только плоские); у /demo `ref` не работает, их хеши не затронуты')
    print('итог:', 'чисто' if not bad else f'{bad} провал(ов)')
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
