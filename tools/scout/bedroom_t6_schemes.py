"""Спальня Т6 «было | стало» в виде листа-образца (T-20261112-62, план bedroom-groups-01).

Те же пары, что в листах Т6 (`.t38-sheet.py`, T-20261112-38/2): демо-спальни 1 и 2 по стилям (банк `sets-bedroom.json`, пара,
тир «комфорт») — БЫЛО = раскладка банка, СТАЛО = движок групп (`planner.bedroom.solve_bedroom(engine='groups')`) на тех же
предметах; спальни UK-туров — БЫЛО = поштучный движок (`engine='items'`), СТАЛО = движок групп. Координаты — из результатов
движка (центр + поворот → след `planner.geometry.footprint`), своей геометрией не пересчитываем.

Рисование и проверки — `bedroom_schemes.py` импортом: масштаб и сетка 50 см, размер у предмета, зоны с числом см (бок 75 /
изножье 60, 90 перед шкафом, 76 перед комодом, 76 у двери и дуга), дорожки от двери к кровати/окну/столу, красная штриховка
нарушения и строка причины. Нормы — `services/planner-solver/rules/occupancy.json`. Отдельной строкой — что говорит проверка
движка (`planner.bedroom_checks.validate_bedroom`): обе проверки на листе, расхождение видно.

Запуск (без сети и БД): python tools/scout/bedroom_t6_schemes.py <папка-вывода> [банк.json] [папка UK scenes]
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'services' / 'planner-solver'))
sys.path.insert(0, str(HERE))
import bedroom_schemes as bs  # noqa: E402

BANK = Path('/home/pakar/igor/remlab/tools/scout/sets-bedroom.json')     # не в git — основная копия (как в Т6)
UK_SCENES = Path('/home/pakar/remlab-logs/t13-1111/1943-r3/bed/scenes')   # сцены UK-туров, на которых строился Т6
UK_PICK = [('new-4y0opqHwp1gkKYnIDgm1Kw', 0), ('new-4y0opqHwp1gkKYnIDgm1Kw', 2), ('new-FjiOaFNsLKJoAZJSHSFz8w', 1),
           ('new-aOv8kTVEKMgu2H6iD6UIJg', 0)]
FURN = ('кровать', 'тумба', 'шкаф', 'комод', 'стол', 'стул', 'туалетный')
KIND = (('кровать', 'bed'), ('тумба', 'ns'), ('шкаф', 'wardrobe'), ('комод', 'dresser'), ('туалетный', 'desk'),
        ('стол', 'desk'), ('стул', 'chair'))
GROUP = {'bed': 'sleep', 'ns': 'sleep', 'wardrobe': 'wardrobe', 'dresser': 'dresser', 'desk': 'work', 'chair': 'work'}
BACK = {0: 'south', 90: 'west', 180: 'north', 270: 'east'}   # facing_vector(rot) = (sin, cos): 0 — лицом на север
PURPOSE = {'couple': 'couple', 'guest': 'guest', 'single': 'single', 'single_narrow': 'single_narrow'}
STYLE_ORDER = ['сканди', 'современный', 'минимализм', 'лофт', 'джапанди']


# ---------------------------------------------------------------- перевод результата движка в предметы схемы
def kind_of(role):
    r = role.lower()
    for k, v in KIND:
        if r.startswith(k):
            return v
    return None


def back_wall(rot):
    """Стена за спиной предмета по повороту движка (лицо — facing_vector)."""
    return BACK[int(round((rot % 360) / 90)) % 4 * 90]


def to_item(room, role, sku, rect, rot, variant=None):
    """Предмет схемы из следа движка: стена — за спиной, off — вдоль стены от её начала (как `bs.band`), g — зазор до
    стены. Зоны строятся от фактической грани (g + глубина), а не от стены."""
    kind = kind_of(role)
    wall = back_wall(rot)
    W, D = room['W'], room['D']
    off = rect[0] if wall in ('south', 'north') else rect[1]
    g = {'south': rect[1], 'north': D - rect[3], 'west': rect[0], 'east': W - rect[2]}[wall]
    w, d = sku['w'], sku['d']
    it = {'role': role, 'kind': kind, 'sku': sku, 'wall': wall, 'off': off, 'group': GROUP[kind], 'rect': tuple(rect),
          'zones': [], 'gap_wall': g}
    front = {'wardrobe': ('WARDROBE_FRONT', bs.WARD), 'dresser': ('DRESSER_FRONT', bs.DRESS), 'desk': ('DESK_CHAIR', bs.DESKZ)}
    if kind in front:
        code, depth = front[kind]
        it['zones'].append({'code': code, 'rect': bs.band(room, wall, off, w, g + d, g + d + depth), 'label': f'{depth:.0f}',
                            'kind': kind, 'wall': wall})
    if kind == 'bed':
        it['variant'] = variant or 'pair'
        it['side_zone'] = {'lo': bs.band(room, wall, off - bs.SIDE, bs.SIDE, g, g + d),
                           'hi': bs.band(room, wall, off + w, bs.SIDE, g, g + d)}
        it['foot_zone'] = bs.band(room, wall, off, w, g + d, g + d + bs.FOOT)
        it['gap'] = {'lo': off, 'hi': bs.wall_len(room, wall) - off - w}
    return it


def scheme_room(rid, title, model, notes=()):
    """Комната схемы из модели движка (`planner.models.Room`): те же стены — юг y=0, север y=D (`geometry._wall_strip`)."""
    ops = [o.model_dump() for o in model.openings]
    rads = [{'wall': r.wall, 'offset_cm': r.offset_cm, 'width_cm': r.width_cm, 'depth_cm': r.depth_cm} for r in model.radiators]
    room = bs._room(rid, title, 'движок', model.width_cm, model.depth_cm, ops, rads, list(notes))
    room['_geo'] = {'doors': [bs.door_geo(room, d) for d in room['doors']],
                    'rads': [bs.band(room, r['wall'], r['off'], r['width'], 0, r['depth']) for r in room['rads']],
                    'wins': [bs.band(room, w['wall'], w['off'], w['width'], 0, 1) for w in room['wins']]}
    return room


def items_from(room, placements, names, variant=None):
    from planner.geometry import footprint
    out = []
    for p in placements:
        if kind_of(p.role) is None or p.item is None:
            continue
        it = p.item
        sku = {'w': float(it.w_cm), 'd': float(it.d_cm), 'h': float(it.h_cm or 0), 'name': names.get(p.role) or p.role}
        out.append(to_item(room, p.role, sku, footprint(p).bounds, p.rot, variant))
    return out


def evaluate(room, items, purpose):
    """Проверки схемы (нормы occupancy.json) + дорожки от двери; результат в формате `bs.render`."""
    geo = room['_geo']
    vs = bs.evaluate(room, geo, items, purpose, {})
    rv, paths = bs.check_routes(room, geo, items, purpose, want_paths=True)
    vs += rv
    return {'items': items, 'vs': vs, 'ok': not any(v['hard'] for v in vs), 'purpose': purpose}, paths


def engine_verdict(model, lay, strict=True):
    """Что говорит проверка движка (жёсткие коды) — для строки под схемой."""
    from planner.bedroom_checks import validate_bedroom
    from planner.models import Severity
    if not lay.placements:
        return []
    return [v.message or v.code for v in validate_bedroom(model, lay.placements, strict=strict).violations
            if v.severity is Severity.HARD]


def match(before, after):
    """Пары «было → стало» по виду предмета: одинаковые (две тумбы) — по ближайшему месту, а не по имени роли
    (движок может поменять «тумба» и «тумба 2» местами — это не сдвиг на 2 м)."""
    cand = sorted((abs(y['rect'][0] - x['rect'][0]) + abs(y['rect'][1] - x['rect'][1]), i, k)
                  for i, x in enumerate(before) for k, y in enumerate(after) if y['kind'] == x['kind'])
    got, used = {}, set()
    for _dist, i, k in cand:          # сначала самые близкие пары
        if i not in got and k not in used:
            got[i] = k
            used.add(k)
    pairs = [(x, after[got[i]] if i in got else None) for i, x in enumerate(before)]
    return pairs, [y for k, y in enumerate(after) if k not in used]


def moved(before, after):
    """Что поменялось между БЫЛО и СТАЛО: к другой стене / сдвиг вдоль стены, убранные и новые предметы."""
    out = []
    pairs, extra = match(before, after)
    for x, y in pairs:
        name = bs.ITEM_RU[x['kind']].lower()
        if y is None:
            out.append(f'{name} — убран')
        elif x['wall'] != y['wall']:
            out.append(f"{name}: к {bs.WALL_RU[y['wall']]} стене")
        else:
            dx = (y['rect'][0] - x['rect'][0], y['rect'][1] - x['rect'][1])
            if max(abs(dx[0]), abs(dx[1])) >= 1:
                ax = dx[0] if abs(dx[0]) >= abs(dx[1]) else dx[1]
                out.append(f"{name}: {'+' if ax > 0 else '−'}{abs(ax):.0f} см вдоль стены")
    out += [f"{bs.ITEM_RU[y['kind']].lower()} — добавлен" for y in extra]
    return list(dict.fromkeys(out))


def composition(items):
    k = [i['kind'] for i in items]
    p = ['кровать' if 'bed' in k else 'без кровати']
    n = k.count('ns')
    if n:
        p.append(f'{n} тумбы' if n > 1 else 'тумба')
    for kk, ru in (('wardrobe', 'шкаф'), ('dresser', 'комод'), ('desk', 'стол'), ('chair', 'стул')):
        if kk in k:
            p.append(ru)
    return ' + '.join(p)


# ---------------------------------------------------------------- пары «было | стало»
def sku_name(s, role):
    """Имя товара роли из набора банка (`items` — словарь роль→товар или список товаров с полем role)."""
    its = s.get('items') or {}
    x = its.get(role) if isinstance(its, dict) else next((i for i in its if isinstance(i, dict) and i.get('role') == role), None)
    if isinstance(x, dict):
        return x.get('name') or (x.get('sku') or {}).get('name')
    return x if isinstance(x, str) else None


def demo_pairs(bank_path):
    import compose_bedroom as CB
    from planner.bedroom import solve_bedroom
    from planner.models import Item, Placement
    from types import SimpleNamespace as NS
    bank = json.load(open(bank_path, encoding='utf-8'))
    bank = bank.get('sets', bank) if isinstance(bank, dict) else bank
    out = []
    for s in bank:
        if s['purpose'] != 'couple' or s.get('tier') != 'комфорт':
            continue
        lay = s['layout']
        model = CB._room_model(lay['_room'], s['purpose'])
        roles = [r for r in lay if not r.startswith('_') and r.split(' ')[0] in FURN]
        items = [Item(role=r, w_cm=lay[r]['w'], d_cm=lay[r]['d'], h_cm=lay[r]['h'], side_back=lay[r].get('side_back')) for r in roles]
        before = NS(placements=[Placement(role=r, x=lay[r]['x'], y=lay[r]['z'], rot=lay[r]['rot'], item=it)
                                for r, it in zip(roles, items)], meta={'engine': 'items'})
        after = solve_bedroom(model, items, 'couple', engine='groups')
        names = {r: sku_name(s, r) for r in roles}
        n = 1 if s['room_id'] == 'bedroom-1' else 2
        title = f"Демо спальня {n} · {s['style']} · {model.width_cm:.0f}×{model.depth_cm:.0f}"
        out.append({'id': f"{s['room_id']}-{s['style']}", 'group': f'demo-{n}', 'title': title, 'model': model,
                    'purpose': 'couple', 'before': before, 'after': after, 'names': names,
                    'before_src': 'раскладка банка', 'style': s['style']})
    out.sort(key=lambda p: (p['group'], STYLE_ORDER.index(p['style']) if p['style'] in STYLE_ORDER else 99))
    return out


def uk_name(sku):
    """В сценах UK у товара родовое имя («Кровать») — на схеме вместо него ширина спального места."""
    n = sku.get('name')
    if n == 'Кровать' and sku.get('sleep_w'):
        return f"спальное {sku['sleep_w']}"
    return n


def uk_pairs(scenes_dir):
    from planner.bedroom import solve_bedroom
    from planner.models import Item, Opening, Room
    out = []
    for sc, i in UK_PICK:
        d = json.load(open(Path(scenes_dir) / sc / 'bedrooms.json', encoding='utf-8'))
        rooms = d if isinstance(d, list) else d.get('rooms')
        r = rooms[i]
        v = r['variants'][0]
        purpose = v['purpose']
        ops = [Opening(**{k: x for k, x in o.items() if k in ('kind', 'wall', 'offset_cm', 'width_cm', 'swing_cm', 'hinge', 'sill_cm', 'height_cm')})
               for o in (v.get('openings_core') or r['openings_core'])]
        model = Room(width_cm=r['core']['w'], depth_cm=r['core']['d'], openings=ops, room_type='bedroom', purpose=purpose)
        its = [it for it in v['items'] if it['role'].split(' ')[0] in FURN]
        items = [Item(role=it['role'], w_cm=it['w'], d_cm=it['d'], h_cm=it['h']) for it in its]
        names = {it['role']: uk_name(it.get('sku') or {}) for it in its}
        before = solve_bedroom(model, items, purpose, engine='items')
        after = solve_bedroom(model, items, purpose, engine='groups')
        rid = f"uk-{sc[4:12]}-{i}-{int(model.width_cm)}x{int(model.depth_cm)}-{purpose}"
        title = f"UK {r.get('name') or 'Bedroom'} · {model.width_cm:.0f}×{model.depth_cm:.0f}"
        out.append({'id': rid, 'group': 'uk', 'title': title, 'model': model, 'purpose': purpose, 'before': before,
                    'after': after, 'names': names, 'before_src': 'поштучный движок',
                    'notes': ['радиаторов в сцене нет (как в Т6)']})
    return out


def build_panels(pair):
    """Две панели схемы на пару: БЫЛО и СТАЛО — с проверками, дорожками, строкой движка и списком изменений."""
    room = scheme_room(pair['id'], pair['title'], pair['model'], pair.get('notes', ()))
    purpose = PURPOSE.get(pair['purpose'], 'couple')
    meta = pair['after'].meta or {}
    variant = meta.get('sleep_variant')
    ib = items_from(room, pair['before'].placements, pair['names'], variant)
    ia = items_from(room, pair['after'].placements, pair['names'], variant)
    rb, pb = evaluate(room, ib, purpose)
    ra, pa = evaluate(room, ia, purpose)
    comp = meta.get('composition') or {}
    out = []
    for kind, res, paths, lay in (('БЫЛО', rb, pb, pair['before']), ('СТАЛО', ra, pa, pair['after'])):
        res['tpl'] = bs.classify(room, res)
        if kind == 'СТАЛО':   # шифр шаблона и уровень — из паспорта движка (meta.composition)
            cipher = f"{comp.get('template') or meta.get('template') or '—'} · ур. {comp.get('level') or '—'}"
            src = f"движок групп; раскладка группы сна {meta.get('template') or '—'}, вариант {variant or '—'}"
            if comp.get('degraded_from'):
                src += f"; упрощено с уровня {', '.join(comp['degraded_from'])}"
        else:
            cipher = 'без шаблона'
            src = pair['before_src']
        eng = engine_verdict(pair['model'], lay, strict=True)
        out.append({'room': room, 'res': res, 'paths': paths, 'kind': kind, 'cipher': cipher, 'src': src,
                    'engine_hard': eng, 'lost': [], 'moved': moved(ib, ia) if kind == 'СТАЛО' else []})
    lost = [bs.ITEM_RU[x['kind']].lower() for x, y in match(ib, ia)[0] if y is None]
    if lost:
        why = [w for w in (meta.get('sleep_why'), f"уровень {comp['level']}" if comp.get('degraded_from') else None) if w]
        out[1]['lost'] = lost
        out[1]['lost_why'] = ', '.join(why)
    return out


# ---------------------------------------------------------------- листы
SMALL = 20.0   # нарушение «на N см» пишем, когда залезание маленькое — видно, что это почти впритык, а не грубо


def reasons(res):
    """Жёсткие причины как `bs.hard_reasons`, но с глубиной залезания: «нет 90 перед шкафом — на 1 см»."""
    depth = {}
    for v in res['vs']:
        if v['hard']:
            t = bs.CODE_RU.get(v['code'], v['code'])
            dd = [min(r[2] - r[0], r[3] - r[1]) for r in v['regions']]
            depth[t] = max(depth.get(t) or 0, max(dd)) if dd else depth.get(t)
    return [t + (f' — на {d:.0f} см' if d is not None and d <= SMALL else '') for t, d in depth.items()]


def wrap(text, f, maxw, indent='   '):
    d = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    out, cur = [], ''
    for wd in text.split(' '):
        t = (cur + ' ' + wd) if cur else wd
        if cur and d.textlength(t, font=f) > maxw:
            out.append(cur)
            cur = indent + wd
        else:
            cur = t
    out.append(cur)
    return out


def foot_lines(pn, maxw):
    res = pn['res']
    f = bs.font(15)
    L = []
    if res['ok']:
        L.append('✓ влезает')
    else:
        L += ['✗ ' + t for t in reasons(res)]     # все, не прячем
    if pn['engine_hard']:
        L.append('✗ проверка движка: ' + '; '.join(dict.fromkeys(pn['engine_hard']))[:200])
    else:
        L.append('проверка движка: жёстких нарушений нет')
    L.append(pn['src'])
    mv = [m for m in pn['moved'] if not m.endswith('— убран')]   # убранное — отдельной красной строкой ниже
    if mv:
        L.append('изменилось: ' + '; '.join(mv))
    elif pn['kind'] == 'СТАЛО':
        L.append('изменилось: ничего — та же расстановка')
    if pn['lost']:
        L.append('✗ движок не поставил: ' + ', '.join(pn['lost']) + (f" ({pn['lost_why']})" if pn.get('lost_why') else ''))
    for n in pn['room']['notes']:
        L.append('условно: ' + n)
    return [x for ln in L for x in wrap(ln, f, maxw)]


def render_panel(pn, colw):
    room, res = pn['room'], pn['res']
    s = min((colw - 100) / room['W'], 520 / room['D'])
    title = f"{pn['kind']} · {room['title']} — {pn['cipher']}"
    f = bs.font(20, True)
    d = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    rt = room['title']
    for cut in (lambda t: t.rsplit(' · ', 1)[0],           # не влезло — без размеров (они на чертеже)
                lambda t: t.replace('Демо спальня', 'Спальня').replace('UK ', '')):
        if d.textlength(title, font=f) <= colw - 24:
            break
        rt = cut(rt)
        title = f"{pn['kind']} · {rt} — {pn['cipher']}"
    sub = f"{bs.PURPOSE_RU.get(res['purpose'], res['purpose'])} · схема {res['tpl']}: {composition(res['items'])}"
    return bs.render(room, res, s, compact=True, title=title, subtitle=sub[:84], foot_lines=foot_lines(pn, colw - 30),
                     paths=pn['paths'])


LEGEND = ('зелёное — проход 75 у боков и 60 у изножья · синее — 90 перед шкафом · фиолетовое — 76 перед комодом · '
          'жёлтое — дверь 76 и дуга · пунктир — путь 75 от двери: зелёный к кровати, синий к окну, оранжевый к столу · '
          'оранжевое у стены — радиатор · красная штриховка — нарушение · схема P1…P10 — тип по образцу Т0')


def make_sheets(out, pairs_panels, name, head, per=4, colw=640):
    files = []
    for si in range(0, len(pairs_panels), per):
        chunk = pairs_panels[si:si + per]
        rows = [[render_panel(pn, colw) for pn in pp] for pp in chunk]
        lf = bs.font(14)
        leg = wrap(LEGEND, lf, colw * 2 - 10, indent='')
        top = 50 + len(leg) * 20 + 10
        H = sum(max(im.height for im in r) + 16 for r in rows) + top
        sheet = Image.new('RGB', (colw * 2 + 30, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        n = si // per + 1
        tot = (len(pairs_panels) + per - 1) // per
        d.text((14, 12), f'{head} · БЫЛО | СТАЛО (масштаб, сетка 50 см)' + (f' · лист {n}/{tot}' if tot > 1 else ''),
               font=bs.font(24, True), fill=(0, 0, 0))
        for k, ln in enumerate(leg):
            d.text((14, 46 + 20 * k), ln, font=lf, fill=(70, 70, 70))
        y = top
        for r in rows:
            x = 10
            for im in r:
                sheet.paste(im, (x, y))
                d.rectangle([x, y, x + im.width - 1, y + im.height - 1], outline=(200, 200, 200))
                x += colw + 10
            y += max(im.height for im in r) + 16
        fn = out / f'{name}-{n}.png'
        sheet.save(fn)
        files.append(fn)
        print('sheet', fn, flush=True)
    return files


def main(out, bank=BANK, scenes=UK_SCENES):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pairs = demo_pairs(bank) + uk_pairs(scenes)
    allp, notes = {}, []
    for p in pairs:
        pp = build_panels(p)
        allp.setdefault(p['group'], []).append(pp)
        b, a = pp
        notes.append({'id': p['id'], 'before_ok': b['res']['ok'], 'after_ok': a['res']['ok'],
                      'before_hard': bs.hard_reasons(b['res']), 'after_hard': bs.hard_reasons(a['res']),
                      'engine_before': b['engine_hard'], 'engine_after': a['engine_hard'], 'cipher_after': a['cipher'],
                      'moved': a['moved'], 'lost': a['lost']})
        print(p['id'], '| было', 'ok' if b['res']['ok'] else bs.hard_reasons(b['res']), '| стало',
              'ok' if a['res']['ok'] else bs.hard_reasons(a['res']), '| движок стало', a['engine_hard'], flush=True)
    heads = {'demo-1': 'Демо спальня 1 (597×293) по стилям', 'demo-2': 'Демо спальня 2 (450×293) по стилям',
             'uk': 'Спальни UK-туров'}
    for g, pp in allp.items():
        make_sheets(out, pp, f'sheet-{g}', heads.get(g, g))
    json.dump(notes, open(out / 'notes.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    a = sys.argv[1:]
    main(a[0], *(Path(x) for x in a[1:3]))
