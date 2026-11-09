#!/usr/bin/env python3
"""ПРОБА АГЕНТА: ДАННЫЕ СТРАНИЦЫ /demo ПОД ЗАГРУЖЕННЫЙ ПЛАН (план agent-trial-08-demo-as-template, задача А; T-20261109-21).

Итог пробы открывается ТЕМ ЖЕ `index.html`, что и `/demo`, поэтому у каждого задания свой `demo-data.json` по контракту
`flat215_demo.py:build`: `room`, `rooms_geo`, `apartment_rooms`, `variants`, `feeds` (и `v.cams`, `rules`). Вход:
`contracts/trial.ts:floorplanResult` и, когда мебель готова, сцена `trial_demo.py` (`~/scout-scenes/trial/<id>/scene.json`).

  без сцены — по варианту на комнату типа «гостиная»: `items: []`, валидные id/room_id/стиль, размеры и `pending: true` —
  «мебель подбирается» (Codex 09.11: пустой список сам по себе не значит «готовая пустая комната»);
  со сценой — варианты сцены на гостиной сцены; прочие гостиные честно без мебели (`trial_demo` обставляет одну).

Комната — прямоугольное ядро как `trial_room.adapt`, проёмы — по стенам. Отличие от `adapt` одно: геометрия НЕ отказывает
из-за мебели (нет окна, диван не влезает, нет входа, масштаб не проверен) — это причины отказа `trial_demo`, а пустая
комната и в них честно показывается («сбой гостиной — 3D остаётся»). Неоднозначные данные — отказ, не угадывание:
`opening_ambiguous`, `contour_distorted`, `no_core`, `opening_cut_by_core`. Радиаторов в контракте нет — `radiators: []`,
не выдумываем. Этажи — `storey` у комнаты, только если подпись панели его подтверждает; `floor`/`floorsTotal` (этаж дома)
не трогаем. Папки и версии — на проде (`lib/trial/repo-bundle.ts`): здесь только сборка JSON.

  ~/venvs/scout/bin/python trial_bundle.py <job_id> <floorplanResult.json> [--scene scene.json] [--out demo-data.json]
Код выхода: 0 — собрано, 2 — честный отказ (причина JSON-строкой в stdout).
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import trial_room as TR  # noqa: E402  (кладёт солвер в sys.path)

LIVING = 'living'
# как `flat215_demo.STYLE_IDS` и `STYLE_IDS` страницы (сверка — тестом): страница узнаёт стиль по этому ключу
STYLE_IDS = {'сканди': 'scandi', 'современный': 'modern', 'минимализм': 'minimal', 'лофт': 'loft', 'неоклассика': 'neoclassic',
             'джапанди': 'japandi'}
PENDING_STYLE = 'сканди'                 # стиль пустой комнаты: валидный, сменится с приходом вариантов
# причины ядра, которые решают судьбу МЕБЕЛИ, а не геометрии (см. шапку)
FURNITURE_ONLY_REASONS = {'living_core_small', 'no_entry'}
TITLES = {'living': ('Гостиная', 'Living room'), 'bedroom': ('Спальня', 'Bedroom'), 'kitchen': ('Кухня', 'Kitchen'),
          'bathroom': ('Санузел', 'Bathroom'), 'hall': ('Прихожая', 'Hall'), 'other': ('Помещение', 'Room')}
SCENE_FURNITURE = {'ok': 'ready', 'partial': 'partial', 'refused': 'failed', 'failed': 'failed'}
SCENE_READY = ('ok', 'partial')
OUTCOME_TEXT = {'living_core_small': 'Комната слишком мала для набора мебели гостиной.',
                'no_entry': 'На плане не нашлось входа в комнату, поэтому мебель расставить нельзя.',
                'one_living_furnished': 'Мебель подбираем только для самой большой гостиной.',
                'room_kind_not_furnished': 'Для комнат такого типа мебель пока не подбираем.',
                'opening_ambiguous': 'Не удалось надёжно определить окна и двери этой комнаты.',
                'contour_distorted': 'Не удалось надёжно построить эту комнату по плану.',
                'no_core': 'Не удалось надёжно построить эту комнату по плану.',
                'opening_cut_by_core': 'Не удалось надёжно построить эту комнату по плану.'}
OUTCOME_DEFAULT = 'Не удалось подобрать мебель для этой комнаты.'


class BundleRefused(Exception):
    """Честный отказ собрать данные: страницу без вариантов открыть нельзя (`load()` упадёт), выдумывать комнату — тоже."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(f'{code}: {detail}')
        self.code, self.detail = code, detail


def default_ctx() -> dict:
    """Что берётся у живого демо: числа правил страницы и модель товара. Импорт `flat215_demo` тяжёлый — только здесь."""
    import flat215_demo as FD
    return {'rules': {**FD._rules(), 'soft_roles': FD.soft_roles()}, 'msid_of': FD._msid, 'slot_band': FD._slot_band}


# ───────────────────────── этажи ─────────────────────────

_STOREY_WORDS = (
    (r'\b(basement|cellar|цокол\w*|подвал\w*)\b', -1), (r'\bground\b', 0), (r'\b(first|1st)\s+(floor|level|storey)\b', 1),
    (r'\b(second|2nd)\s+(floor|level|storey)\b', 2), (r'\b(third|3rd)\s+(floor|level|storey)\b', 3),
    (r'\b(fourth|4th)\s+(floor|level|storey)\b', 4), (r'\bпервый\s+этаж\b', 1), (r'\bвторой\s+этаж\b', 2), (r'\bтретий\s+этаж\b', 3),
)
_STOREY_NUM = (r'\b(?:floor|level|storey)\s*(\d{1,2})\b', r'\b(\d{1,2})(?:-?(?:й|ой))?\s+этаж\b', r'\bэтаж\s*(\d{1,2})\b')


def storey_of(title: str | None) -> int | None:
    """Этаж по подписи панели; нет слова об этаже или подпись называет два разных (`Ground and First Floor`) — неизвестно."""
    s = re.sub(r'lower[\s-]*ground', 'basement', str(title or '').lower())
    found = {v for pat, v in _STOREY_WORDS if re.search(pat, s)}
    found |= {int(m) for pat in _STOREY_NUM for m in re.findall(pat, s)}
    return found.pop() if len(found) == 1 else None


def storeys(panels: list) -> tuple[dict, list]:
    """Индекс панели → этаж. Этаж считается подтверждённым, только если подписаны ВСЕ панели и разными этажами."""
    vals = [storey_of(p.get('title')) for p in panels]
    if any(v is None for v in vals) or len(set(vals)) != len(vals):
        return {}, ['storey_unconfirmed'] if len(panels) > 1 else []
    return dict(enumerate(vals)), []


# ───────────────────────── геометрия комнаты ─────────────────────────

def _num(v: float) -> float | int:
    r = round(float(v), 1)
    return int(r) if r == int(r) else r


def _openings_for_page(ops: list) -> list:
    """Проёмы ядра → формат `room.openings` страницы: служебное (`_…`) снято; проход без полотна (`door` без дуги) — `opening`,
    как `trial_demo.core_room(render=True)`: дверь в проходе рисовать нечем."""
    out = []
    for o in ops:
        o = {k: v for k, v in o.items() if not k.startswith('_')}
        if o.get('kind') == 'door' and not o.get('swing_cm'):
            o = {k: v for k, v in o.items() if k != 'swing_cm'}
            o['kind'] = 'opening'
        out.append(o)
    return out


def core_geometry(panel: dict, room: dict, cfg: dict) -> dict:
    """Ядро комнаты и проёмы по её стенам (шаги `trial_room.adapt` без мебельных отказов) → w, d, openings. Отказ — `Refusal`."""
    from planner.geometry import largest_free_rectangles
    ours, amb = TR._openings_of(panel, room, cfg)
    if amb:
        raise TR.Refusal('opening_ambiguous', '; '.join(f"{o['kind']} {o['widthCm']:.0f} см в {o['_d']:.0f} см от стены" for o in amb))
    fr = TR.ortho_frame(room['contour'], cfg)
    ops = [TR._place_opening(fr['poly'], o, fr['T'], cfg) for o in ours]
    rects = [g.bounds for g in largest_free_rectangles(fr['poly'], min_side_cm=cfg['core_min_side_cm'], limit=24)]
    if not rects:
        raise TR.Refusal('no_core')
    cands = [TR.core_candidate(fr['poly'], r, ops, TR.need_group(), cfg) for r in rects[:int(cfg['core_candidates'])]]
    blocking = [[r for r in c['reasons'] if r.split(':')[0] not in FURNITURE_ONLY_REASONS] for c in cands]
    ok = [c for c, b in zip(cands, blocking) if not b]
    ok.sort(key=lambda c: (not c['light_on_core'], -c['area_m2']))
    if not ok:
        why = [r.split(':')[0] for b in blocking for r in b]
        code = 'opening_cut_by_core' if 'opening_cut_by_core' in why else 'no_core'
        raise TR.Refusal(code, '; '.join(f"ядро {c['w']:.0f}×{c['d']:.0f}: {', '.join(b)}" for c, b in zip(cands, blocking)))
    best = ok[0]
    return {'w': _num(best['w']), 'd': _num(best['d']), 'openings': _openings_for_page(TR.solver_openings(best, cfg))}


# ───────────────────────── варианты ─────────────────────────

def _title(room: dict, geo: dict) -> str:
    area = room.get('areaM2') or geo['w'] * geo['d'] / 1e4
    label = (room.get('name') or '').strip() or TITLES.get(room['kind'], TITLES['other'])[1]
    return f'{label} {area:.1f} m²'


def _url(u: str | None) -> str | None:
    return ('https:' + u) if isinstance(u, str) and u.startswith('//') else u


def _base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role)


def _empty_variant(room_id: str, geo: dict, state: str, problem: dict | None = None) -> dict:
    out = {'id': f'trial-{room_id}', 'title': PENDING_STYLE.capitalize(), 'style': PENDING_STYLE, 'style_id': STYLE_IDS[PENDING_STYLE],
           'room_id': room_id, 'items': [], 'decor': [], 'dims_unknown': [], 'missing_item': [], 'fill': [], 'fill_pct': None,
           'cams': [], 'pending': state == 'pending', 'furniture_state': state, 'room_size': {'w': geo['w'], 'd': geo['d']}}
    if problem:
        out['furniture_problem'] = problem
    return out


def _outcome(state: str, code: str | None = None) -> dict:
    """Исход мебели по комнате для страницы: готово / подбирается / отказ с текстом для покупателя."""
    return {'furniture_state': state, 'furniture_code': code, 'furniture_text': OUTCOME_TEXT.get(code, OUTCOME_DEFAULT) if state == 'refused' else None}


def _item(row: dict, place: dict | None, msid_of) -> dict:
    """Строка сцены `trial_demo` → предмет варианта (как объект `items` в `flat215_demo.build`)."""
    p = place or {}
    h = row.get('h') if row.get('h') is not None else p.get('h')
    sku = {'name': row.get('name'), 'price': row.get('price'), 'img': _url(row.get('img')), 'url': row.get('url'), 'sid': row.get('sid'),
           'msid': msid_of(row.get('sid')) if row.get('sid') else None, 'w': row.get('w'), 'd': row.get('d'), 'h': h}
    return {'role': row['role'], 'x': row['x'], 'y': row['y'], 'rot': int(row.get('rot') or 0), 'w': row.get('w'), 'd': row.get('d'), 'h': h,
            'dims_src': 'каталог', 'sku': sku, 'corner': bool(row.get('corner')), 'corner_left': bool(p.get('corner_left')),
            'section': p.get('section')}


def _scene_variant(sv: dict, room_id: str, geo: dict, msid_of) -> dict:
    style = sv.get('style') or PENDING_STYLE
    failed = bool(sv.get('failed'))
    state = 'failed' if failed else ('ready' if sv.get('post_ok') and not sv.get('hard') else 'partial')
    place = {p['role']: p for p in sv.get('placements_core') or []}
    out = {'id': f"set{sv['set_index']}", 'title': style.capitalize(), 'style': style, 'style_id': STYLE_IDS.get(style, ''),
           'room_id': room_id, 'items': [_item(r, place.get(r['role']), msid_of) for r in sv.get('items') or []], 'decor': [],
           'dims_unknown': [], 'missing_item': [{'role': r} for r in sv.get('absent_roles') or []], 'fill': [], 'fill_pct': None,
           'cams': [], 'pending': False, 'furniture_state': state, 'room_size': {'w': geo['w'], 'd': geo['d']}}
    if state != 'ready':
        out['furniture_problem'] = {'codes': sorted({p.get('code') for p in sv.get('problems') or []} | set(sv.get('hard') or []))}
    return out


def _feeds(variants: list) -> dict:
    """Ленты замен — только товары самой сцены задания (других для этого плана не считалось), `диван` → строки как в живом `feeds`."""
    out: dict = {}
    seen: dict = {}
    for v in variants:
        for it in v['items']:
            sku, base = it['sku'], _base_role(it['role'])
            key = (base, sku.get('sid') or sku.get('name'))
            if key in seen:
                seen[key]['styles'].append(v['style'])
                continue
            row = {**sku, 'style': v['style'], 'styles': [v['style']], 'src': 'set', 'corner': it['corner']}
            seen[key] = row
            out.setdefault(base, []).append(row)
    for lst in out.values():
        lst.sort(key=lambda p: p.get('price') or 0)
    return out


# ───────────────────────── сборка ─────────────────────────

def _check_input(job_id: str, result: dict, scene: dict | None) -> None:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', job_id or ''):
        raise BundleRefused('bad_job_id', str(job_id))
    if result.get('version') != 1 or result.get('units') != 'cm' or not result.get('panels'):
        raise BundleRefused('bad_result', 'нужен floorplanResult v1 в сантиметрах')
    if scene is None:
        return
    if scene.get('trial_id') != job_id:
        raise BundleRefused('scene_mismatch', f"сцена другого задания: {scene.get('trial_id')}")
    if scene.get('status') not in SCENE_FURNITURE:
        raise BundleRefused('scene_mismatch', f"неизвестный статус сцены: {scene.get('status')}")
    if scene['status'] in SCENE_READY and not (scene.get('core') and scene.get('room') and scene.get('variants')):
        raise BundleRefused('scene_mismatch', 'сцена без ядра, комнаты или вариантов')


def _living_rooms(result: dict, cfg: dict) -> tuple[list, list]:
    """Комнаты типа «гостиная»: первая — та же, что выбирает `trial_room.pick_living` (её обставляет сцена), дальше по площади."""
    try:
        panel, main, flags = TR.pick_living(result, cfg)
    except TR.Refusal as e:
        raise BundleRefused(e.code, e.detail) from e
    from shapely.geometry import Polygon
    rest = [(p, r) for p in result['panels'] for r in p['rooms'] if r.get('kind') == LIVING and r is not main]
    rest.sort(key=lambda pr: -Polygon(pr[1]['contour']).area)
    return [(panel, main)] + rest, flags


def build(job_id: str, result: dict, scene: dict | None = None, ctx: dict | None = None) -> dict:
    """floorplanResult (+ сцена) → `demo-data.json`. Нечего показать — `BundleRefused`."""
    _check_input(job_id, result, scene)
    ctx = ctx or default_ctx()
    cfg = TR.rules()
    panels = result['panels']
    panel_of = {id(r): i for i, p in enumerate(panels) for r in p['rooms']}
    livings, flags = _living_rooms(result, cfg)
    main = livings[0][1]
    if scene is not None and scene.get('room') and (scene['room'].get('id') != main['id'] or
                                                     scene['room'].get('panel') != panels[panel_of[id(main)]]['id']):
        raise BundleRefused('scene_mismatch', f"сцена про комнату {scene['room'].get('id')}, а гостиная плана — {main['id']}")
    furnished = scene is not None and scene['status'] in SCENE_READY
    geos, refused = {}, []
    for panel, room in livings:
        try:
            if room is main and furnished:
                first = next(v for v in sorted(scene['variants'], key=lambda v: bool(v.get('failed'))))
                ops = scene['geometries'][first['geometry']]['openings_core'] or scene['openings_core']
                geos[id(room)] = {'w': _num(scene['core']['w']), 'd': _num(scene['core']['d']), 'openings': _openings_for_page(ops)}
            else:
                geos[id(room)] = core_geometry(panel, room, cfg)
        except TR.Refusal as e:
            refused.append({'room': room, 'code': e.code, 'detail': e.detail})
    if not geos:
        raise BundleRefused(refused[0]['code'], refused[0]['detail'])
    # id: первая собранная гостиная — `living` (страница и `HOME.room` опираются на него); уникальны и через панели
    ids: dict = {}
    n_living = 0
    for _, room in livings:
        if id(room) in geos:
            n_living += 1
            ids[id(room)] = LIVING if n_living == 1 else f'{LIVING}-{n_living}'
    for _, room in livings:
        if id(room) not in geos:
            n_living += 1
            ids[id(room)] = f'{LIVING}-{n_living}'
    counters: dict = {}
    for p in panels:
        for r in p['rooms']:
            if id(r) not in ids:
                counters[r['kind']] = counters.get(r['kind'], 0) + 1
                ids[id(r)] = f"{r['kind']}-{counters[r['kind']]}"
    storey_map, storey_flags = storeys(panels)
    rooms_geo, apartment_rooms, variants = {}, [], []
    outcomes = {ids[id(x['room'])]: _outcome('refused', x['code']) for x in refused}
    for panel, room in livings:
        if id(room) not in geos:
            continue
        rid, geo = ids[id(room)], geos[id(room)]
        full = {'w': geo['w'], 'd': geo['d'], 'title': _title(room, geo), 'openings': geo['openings'], 'radiators': []}
        st = storey_map.get(panel_of[id(room)])
        if st is not None:
            full['storey'] = st
        rooms_geo[rid] = full
        if room is main and furnished:
            ready = [_scene_variant(sv, rid, geo, ctx['msid_of']) for sv in scene['variants']]
            variants += sorted(ready, key=lambda v: v['furniture_state'] == 'failed')
            shown = any(v['items'] and v['furniture_state'] != 'failed' for v in ready)
            outcomes[rid] = _outcome('ready') if shown else _outcome('refused', 'furniture_failed')
        elif room is main and scene is not None:
            why = scene.get('refusal') or {'code': (scene.get('problems') or [{}])[0].get('code') or scene['status']}
            variants.append(_empty_variant(rid, geo, 'failed', why))
            outcomes[rid] = _outcome('refused', why.get('code'))
        elif scene is not None:                              # `trial_demo` обставляет одну гостиную: эта уже не дождётся мебели
            variants.append(_empty_variant(rid, geo, 'none', {'code': 'one_living_furnished'}))
            outcomes[rid] = _outcome('refused', 'one_living_furnished')
        else:
            variants.append(_empty_variant(rid, geo, 'pending'))
            outcomes[rid] = _outcome('pending')
    with_variant = {v['room_id'] for v in variants}
    order = [r for _, r in livings] + [r for p in panels for r in p['rooms'] if r.get('kind') != LIVING and r is not main]
    for i, r in enumerate(order, 1):
        entry = {'id': ids[id(r)], 'kind': r['kind'], 'ordinal': i, 'titleRu': TITLES.get(r['kind'], TITLES['other'])[0],
                 'titleEn': (r.get('name') or '').strip() or TITLES.get(r['kind'], TITLES['other'])[1],
                 'areaM2': r.get('areaM2') or None, 'contentState': 'ready' if ids[id(r)] in with_variant else 'soon',
                 **(outcomes.get(ids[id(r)]) or _outcome('refused', 'room_kind_not_furnished'))}
        st = storey_map.get(panel_of[id(r)])
        if st is not None:
            entry['storey'] = st
        apartment_rooms.append(entry)
    rules = dict(ctx['rules'])
    if ctx.get('slot_band') and LIVING in rooms_geo:
        rules['slot_band_cm'] = ctx['slot_band'](rooms_geo[LIVING])
    feeds = _feeds(variants) if furnished else {}
    trial = {'job_id': job_id, 'scale': result['scale']['status'], 'furniture': SCENE_FURNITURE[scene['status']] if scene else 'pending',
             'flags': sorted(set(result.get('flags') or []) | set(flags) | set(storey_flags) | set((scene or {}).get('flags') or [])),
             'refused_rooms': [{'room_id': ids[id(x['room'])], 'code': x['code'], 'detail': x['detail']} for x in refused],
             'panels': [{'id': p['id'], 'title': p['title'],
                         **({'storey': storey_map[i]} if i in storey_map else {}),
                         'rooms': [{'id': ids[id(r)], 'src_id': r['id'], 'name': r.get('name'), 'kind': r['kind'], 'areaM2': r.get('areaM2'),
                                    'bbox': r.get('bbox'), 'contour': r.get('contour'), 'flags': r.get('flags') or []} for r in p['rooms']],
                         'openings': p.get('openings') or [], 'walls': p.get('walls') or []} for i, p in enumerate(panels)]}
    room = rooms_geo.get(LIVING) or next(iter(rooms_geo.values()))
    return {'room': room, 'rooms_geo': rooms_geo, 'apartment_id': '', 'plan': {}, 'apartment_rooms': apartment_rooms,
            'rooms_enabled': sorted(with_variant), 'variants': variants, 'sets': [], 'sofa_feed': feeds.get('диван', []), 'feeds': feeds,
            'rules': rules, 'incomplete_styles': [], 'trial': trial}


def write_atomic(path: str, data: dict) -> None:
    """Подменой: читатель (и сбой на полпути) не видит половину файла."""
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def _arg(args: list, name: str) -> str | None:
    if name not in args:
        return None
    i = args.index(name)
    val = args[i + 1]
    del args[i:i + 2]
    return val


def main() -> int:
    args = sys.argv[1:]
    scene_path, out = _arg(args, '--scene'), _arg(args, '--out')
    if len(args) != 2:
        print(__doc__)
        return 0
    job_id, result_path = args
    result = json.load(open(result_path, encoding='utf-8'))
    scene = json.load(open(scene_path, encoding='utf-8')) if scene_path else None
    try:
        data = build(job_id, result, scene)
    except BundleRefused as e:
        print(json.dumps({'refusal': e.code, 'detail': e.detail}, ensure_ascii=False))
        return 2
    if out:
        write_atomic(out, data)
        print(json.dumps({'ok': True, 'rooms': list(data['rooms_geo']), 'variants': len(data['variants'])}, ensure_ascii=False))
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, separators=(',', ':'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
