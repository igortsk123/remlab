#!/usr/bin/env python3
"""СБОРЩИК НАБОРОВ ПРИХОЖЕЙ (T-20261105-48, room-pipeline-01; по образцу `compose_bedroom.py`) — набор «стиль → какие товары»
с раскладкой солвера прихожей (`planner.hall.solve_hall`) на геометрии прихожей квартиры 215 (`flat215-hall.json`). Пишет
ОТДЕЛЬНЫЙ банк-кандидат `sets-hall.next.json` (`bank_paths.room_bank_output`): живого банка прихожей нет и сборщик его не создаёт.

Всё про комнату — из профиля `rules/profiles/hall.json`: роли и крупное (major — полоса Ш×Г×В), веса стиля, порог «в стиле»
(`in_style_min`), допуск полосы (zones.json, 0,8–1,1 идеала), правила состава `composer.rules` = `rules/hall-composition.json`
(6 стилей, ступень цены, слоты с идеалом, порядок хранения, роли без оценки стиля). Каталог — адаптер
`catalog_items.items('hall', with_assets=True)`: стиль — `product_style_scores` своих товаров, меш — привязка `offer_asset_binding`.

ПОРЯДОК (ячейка `hall|hall|<м²>|<стиль>|<ступень>`):
  1. кандидаты слота — с Ш×Г×В и правдоподобными размерами (`footprint_ok`), крупное — в полосе идеала слота; в стиле — балл
     ≥ `in_style_min`; у ролей `style_unknown` (обувница, модуль, вешалка, консоль — оценок почти нет) при пустом стиле —
     товары БЕЗ оценки, по палитре стиля, с пометкой `style_unknown`; цена — в квантилях ступени роли;
  2. порядок — СНАЧАЛА с мешом (готов → есть, но заблокирован/сгенерирован → нет → брак), потом балл (стиль + 0,5 × палитра),
     ничья — цена → SKU (`rank_key`);
  3. разнообразие: между стилями — ≤ 1 общая крупная модель (семейство);
  4. хранение — первое из `storage` (шкаф-купе → модуль → напольная вешалка), которое солвер поставит; остальное — по одному
     на роль; не встало — следующий кандидат роли (меньший), не нашлось — роль уходит из набора (`skipped`);
  5. запись — как у спальни: `items`, `alternates`, `slots` (идеал и полоса), `layout` (x, z, rot, w, d, h, sid, elev), `mesh_need`
     (товары без меша — спрос на генерацию), `mesh_blocked` (меш есть, но не годен), `style_unknown`.

  ~/venvs/scout/bin/python compose_hall.py [--variant drawing-180] [--sheet DIR]   # банк-кандидат + отчёт (+ лист сверху)
  ~/venvs/scout/bin/python compose_hall.py --check sets-hall.next.json            # критерии по готовому банку
  ~/venvs/scout/bin/python compose_hall.py --selftest                              # чистые функции и солвер, без базы и сети
Env: `ROOM_SETS_OUTPUT` — путь банка (живой — отказ).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
FLAT = os.path.join(HERE, 'flat215-hall.json')
sys.path.insert(0, HERE)
import room_profile as _RP  # noqa: E402
from compose_common import band_of, dominated, num, palette, slot_sizes, tier_range  # noqa: E402,F401

ROOM = 'hall'
PROFILE = _RP.load(ROOM)
MAJOR = _RP.major(PROFILE)                         # шкаф-купе, прихожая, обувница, банкетка, консоль — полоса Ш×Г×В
ROLE_W = dict(PROFILE['style']['role_weights'])
# меш: готов → есть, но не годен (blocked) / сгенерирован без привязки → нет; брак — последним (как спальня: «брак не брать»)
MESH_RANK = {'ready': 0, 'blocked': 1, 'generated': 1, None: 2}
WALL_RU = {'south': 'юг', 'north': 'север', 'east': 'восток', 'west': 'запад'}


def entrance_note(spec: dict) -> str:
    """Вход комнаты — ФАКТ из данных экземпляра (`is_entrance` у проёма, T-20261106-72; flat215 — юг, владелец 06.11, TG 153) с
    источником из `_why` проёма. Флага нет — так и говорим (солвер угадает вход эвристикой и напишет WARN), а не молчим."""
    ent = [o for o in spec.get('openings', []) if o.get('is_entrance')]
    if not ent:
        return 'вход не помечен (нет is_entrance) — солвер угадывает эвристикой, WARN'
    o = ent[0]
    return (f"вход — {WALL_RU.get(o['wall'], o['wall'])}, дверь {o['width_cm']:g} см с отступа {o['offset_cm']:g}"
            + (f" ({o['_why']})" if o.get('_why') else ''))


def rules() -> dict:
    """Правила состава (профиль → composer.rules); новая копия на вызов."""
    return _RP.load(ROOM)['composer']['rules']


def tolerance() -> tuple:
    return tuple(PROFILE['tolerance'] or (0.8, 1.1))


def load_json(p: str) -> dict:
    return json.load(open(p, encoding='utf-8'))


# ---------------------------------------------------------------- чистые функции (селфтест)
def gate(it: dict, slot: dict, band: dict) -> str | None:
    """None — товар годен в слот по размерам; иначе причина. Крупному (major) и слотам с `need_dims` нужны Ш×Г×В и
    правдоподобный габарит (`footprint_ok` — `hall_catalog.dims_of`: `dims_sane` роли); крупное — ещё и в полосе."""
    need = ('w', 'd', 'h') if slot.get('role') in MAJOR else tuple(slot.get('need_dims') or ())
    if need and not all(num(it.get(k)) for k in need):
        return 'нет Ш×Г×В'
    if need and it.get('footprint_ok') is False:
        return 'размеры неправдоподобны'
    for k, (lo, hi) in band.items():
        v = num(it.get(k))
        if v is None:
            return f'нет размера {k}'
        if not (lo <= v <= hi):
            return f'{k}={v:g} вне полосы {lo:g}–{hi:g}'
    return None


def fit_size(it: dict, slot: dict, tol: tuple) -> tuple:
    """Типоразмер слота, в который товар годен (T-20261106-90): (слот типоразмера с `size`, его полоса) — первый по порядку
    правил (основной первым); ни в один — (None, причина по основному). Слот без полосы — один «основной» без полосы."""
    why = None
    for sz in slot_sizes(slot):
        band = band_of(sz, tol) if sz.get('band') else {}
        g = gate(it, sz, band)
        if g is None:
            return sz, band
        why = why or g
    return None, why


def size_slot(slot: dict, size_id: str | None, tol: tuple) -> tuple:
    """(слот типоразмера, полоса) по id типоразмера товара; нет такого id — основной."""
    szs = slot_sizes(slot)
    sz = next((x for x in szs if x['size'] == size_id), szs[0])
    return sz, (band_of(sz, tol) if sz.get('band') else {})


def floor_hanger(it: dict, R: dict) -> bool:
    """Напольная вешалка (стойка, рейл) — может быть хранением: высота ≥ floor_hanger_min_h и глубина ≥ floor_hanger_min_d;
    ниже или тоньше — настенная (крючки, планка)."""
    return (num(it.get('h')) or 0) >= R.get('floor_hanger_min_h', 140) and (num(it.get('d')) or 0) >= R.get('floor_hanger_min_d', 30)


def mesh_of(asset: dict) -> str | None:
    """Меш товара из `CatalogItem.asset` (with_assets): привязка ready → ready; blocked — меш есть, но не годен (ориентация,
    паспорт); привязки нет, а ревизия есть — generated; иначе None (меша нет — спрос на генерацию)."""
    st = (asset or {}).get('mesh_status')
    if st == 'ready':
        return 'ready'
    if st == 'blocked':
        return 'blocked'
    if (asset or {}).get('revision') in ('ready', 'generated'):
        return 'generated'
    return None


def rank_key(it: dict) -> tuple:
    """Порядок кандидатов: 1) модель ещё не стоит в этом стиле; 2) меш (готов → есть, не годен → нет → брак);
    3) в скольких наборах других стилей модель уже стоит (меньше — раньше: в каталоге 2 семьи шкафов-купе в стиле — пусть
    чередуются); 4) товар с оценкой стиля раньше товара без неё; 5) балл; 6) цена; 7) SKU."""
    return (bool(it.get('seen_style')), 3 if it.get('mesh_defect') else MESH_RANK.get(it.get('mesh'), 2),
            int(it.get('seen_all') or 0), bool(it.get('style_unknown')), -round(it.get('score', 0.0), 4), it.get('price') or 0,
            int(it['mid']), str(it['eid']))


def diversity_ok(fam: str, role: str, cur: dict, built: list, style: str) -> bool:
    """Между РАЗНЫМИ стилями — ≤ 1 общая крупная модель (семейство). cur — {роль: семейство} набора в сборке; built —
    [(стиль, {роль: семейство})] уже собранных наборов."""
    if role not in MAJOR:
        return True
    mine = dict(cur, **{role: fam})
    return all(st == style or len(set(mine.values()) & set(other.values())) <= 1 for st, other in built)


def set_fit(items: dict, style: str) -> float:
    """Стиль набора — средневзвешенный балл товаров с оценкой (веса ROLE_W профиля); без оценки — не в счёт."""
    num_, den = 0.0, 0.0
    for r, it in items.items():
        w = ROLE_W.get(r)
        if w and it.get('style_score') is not None:
            num_ += w * it['style_score']
            den += w
    return round(num_ / den, 1) if den else 0.0


def set_id(room_id: str, band: str, style: str, tier: str) -> str:
    """id набора — от ЯЧЕЙКИ `room_id|hall|band|style|tier`, без состава (как спальня этапа В, T-20261106-89 шаг 2): замена
    предмета — то же set_id, новое поколение ячейки. Живого банка прихожей не было — старые id (от состава) никто не хранит."""
    import room_identity as RI
    return RI.set_id_of(ROOM, (room_id, ROOM, band, style, tier))


def cell_band(spec: dict) -> str:
    """Полоса ячейки — площадь прихожей по геометрии, м² до десятых (как `record`: `'8.4'`)."""
    return f"{round(spec['w'] * spec['d'] / 10000, 1):g}"


def cells(R: dict, spec: dict | None = None) -> list:
    """ОЖИДАЕМАЯ МАТРИЦА ячеек прихожей из правил профиля в порядке сборки (`compose`): стили → ступени; комната и полоса — из
    геометрии варианта (по умолчанию — `rooms.hall.variant` правил). Её обязан дать полный кандидат (`room_identity.check`)."""
    spec = spec or room_spec(ROOM, R['rooms'][ROOM].get('variant'))
    band = cell_band(spec)
    return [(spec['id'], ROOM, band, style, tier) for style in R['styles'] for tier in R['tiers']]


# ---------------------------------------------------------------- данные
def _room_model(spec: dict):
    sys.path.insert(0, SOLVER)
    from planner.models import Opening, Radiator, Room
    return Room(width_cm=spec['w'], depth_cm=spec['d'], contour=spec.get('contour'),
                openings=[Opening(**{k: v for k, v in o.items() if not k.startswith('_')}) for o in spec.get('openings', [])],
                radiators=[Radiator(**{k: v for k, v in r.items() if not k.startswith('_')}) for r in spec.get('radiators', [])],
                room_type='hall')


def room_spec(room_id: str, variant: str | None) -> dict:
    """Комната из `flat215-hall.json` (рабочие `rooms`, не `archived_rooms`); variant None — ПЕРВЫЙ вариант этой комнаты в файле."""
    for r in load_json(FLAT)['rooms']:
        if r['id'] == room_id and (variant is None or r['variant'] == variant):
            return r
    raise SystemExit(f'{FLAT}: нет {room_id}/{variant}')


def to_dicts(got: list) -> tuple:
    """CatalogItem прихожей → (мебель, декор) — словари сборщика, как `compose_bedroom.to_dicts` (их же берёт аудит покрытия
    `asset_coverage.py`); декора у прихожей нет. Меш — `mesh_of`."""
    out = []
    for c in got:
        for role in c.roles:
            out.append(dict(role=role, mid=c.mid, eid=c.eid, name=c.name or '', shop=c.shop or '', price=int(c.price),
                            w=num(c.dims['w']), d=num(c.dims['d']), h=num(c.dims['h']),
                            footprint_ok=c.dims['footprint_ok'] is True, img=c.photo['best'] or '', url=c.url or '',
                            fam=c.family, styles=c.style, mesh=mesh_of(c.asset), mesh_defect=bool(c.asset.get('defect'))))
    return out, []


def load_items() -> list:
    import catalog_items as CI
    return to_dicts(CI.items(ROOM, with_assets=True))[0]


# ---------------------------------------------------------------- сборка
class Composer:
    def __init__(self, cat: list, rules: dict, tol: tuple, thr: float):
        self.R, self.tol, self.thr = rules, tol, thr
        md = (rules.get('mesh_defect') or {}).get('names')
        defect = re.compile(md, re.I) if md else None
        for it in cat:
            it['sid'] = f"{it['mid']}:{it['eid']}"
            if it.get('mesh') and (it.get('mesh_defect') or (defect and defect.search(it.get('name') or ''))):
                it['mesh'], it['mesh_defect'] = None, True     # брак меша — как будто меша нет: в «нужен меш»
        self.cat = cat
        self.unknown_roles = set((rules.get('style_unknown') or {}).get('roles') or ())
        self.shortage: dict = {}

    def pool(self, slot: dict, style: str, tier: str, extra=None, tag: str = '') -> tuple:
        """(кандидаты, полоса, ступень ослаблена, без оценки стиля). Ступень — квантили цены роли по всем годным в полосе;
        в стиле нет ни одного товара этой цены — квантили внутри стиля. В стиле пусто, а роль в `style_unknown` — товары
        без оценки (их палитру отбирает `ranked`). extra — доп. отбор ДО квантилей (напольная вешалка-хранение: её цена
        меряется среди напольных, а не среди дешёвых крючков); tag — подпись строки нехватки. Годен по размеру — в полосе
        ЛЮБОГО типоразмера слота (`fit_size`, T-20261106-90); id типоразмера пишется в товар (`size`) — запись набора берёт
        полосу именно его. Возвращаемая полоса — основного типоразмера."""
        band = band_of(slot, self.tol) if slot.get('band') else {}
        fit = []
        for it in self.cat:
            if it['role'] != slot['role'] or (extra is not None and not extra(it)):
                continue
            sz, _ = fit_size(it, slot, self.tol)
            if sz is not None:
                it['size'] = sz['size']
                fit.append(it)
        q = self.R['tiers'][tier]
        lo, hi = tier_range([it['price'] for it in fit], q)
        styled = [it for it in fit if _RP.in_style(it.get('styles'), style, self.thr)]
        unknown = False
        if not styled and slot['role'] in self.unknown_roles:
            styled, unknown = [it for it in fit if not it.get('styles')], True
        k = (slot['role'] + tag, style)
        fams = lambda L: len({it.get('fam') or it.get('sid') or (it.get('mid'), it.get('eid')) for it in L})  # noqa: E731
        self.shortage[k] = {'годных по размеру': len(fit), 'в стиле': 0 if unknown else len(styled),
                            'без оценки стиля': len(styled) if unknown else 0,
                            'с готовым мешом': sum(1 for it in styled if it.get('mesh') == 'ready'),
                            # второй счёт — модели (семейства): владелец ещё решает, что считать товаром (T-90)
                            'семейств по размеру': fams(fit), 'семейств в стиле': 0 if unknown else fams(styled),
                            'семейств без оценки': fams(styled) if unknown else 0,
                            'по типоразмерам': {sz: sum(1 for it in fit if it.get('size') == sz)
                                                for sz in [x['size'] for x in slot_sizes(slot)]}}
        out = [it for it in styled if lo <= it['price'] <= hi]
        if out or not styled:
            return out, band, False, unknown
        lo, hi = tier_range([it['price'] for it in styled], q)
        return [it for it in styled if lo <= it['price'] <= hi], band, True, unknown

    def score(self, it: dict, style: str, ctx: dict) -> tuple:
        import compose_common as CC
        sc = (it.get('styles') or {}).get(style)
        s = float(sc) if sc is not None else 0.0
        why = [f'стиль {s:g}' if sc is not None else 'стиль без оценки']
        pal = None
        if it.get('cls'):
            pal = CC.palette_score(it['cls'], it.get('cls2'), CC.STYLE_PAIR[style], ctx.get('temp', 'mid'), it.get('rgb'))
            s += 0.5 * pal
            why.append(f'палитра{0.5 * pal:+.1f}')
        if it.get('mesh'):
            why.append({'ready': 'меш готов', 'blocked': 'меш не годен', 'generated': 'меш сгенерирован'}[it['mesh']])
        return round(s, 3), '; '.join(why), pal

    def ranked(self, cands: list, style: str, ctx: dict, unknown: bool = False) -> list:
        """Кандидаты по `rank_key`. Без оценки стиля (`unknown`) — только с палитрой стиля ≥ `style_unknown.palette_min`."""
        pmin = float((self.R.get('style_unknown') or {}).get('palette_min', 0.0))
        out = []
        for it in cands:
            sc, why, pal = self.score(it, style, ctx)
            if unknown and pal is not None and pal < pmin:
                continue
            ss = (it.get('styles') or {}).get(style)
            out.append(dict(it, score=sc, why=why, style_score=float(ss) if ss is not None else None,
                            style_unknown=unknown, seen_style=it['fam'] in ctx.get('used_style', ()),
                            seen_all=(ctx.get('used_all') or {}).get(it['fam'], 0)))
        return sorted(out, key=rank_key)

    def build(self, style: str, tier: str, spec: dict, built: list, used: dict) -> dict:
        sys.path.insert(0, SOLVER)
        import compose_common as CC
        from planner.hall import solve_hall
        from planner.models import Item
        cfg = self.R['purposes'][ROOM]
        room = _room_model(spec)
        slots, lists, bands, relaxed, unknown = {}, {}, {}, [], set()
        for sl in cfg['slots']:
            cands, band, rx, unk = self.pool(sl, style, tier)
            palette(cands)
            slots[sl['role']], lists[sl['role']], bands[sl['role']] = sl, cands, band
            if rx:
                relaxed.append(sl['role'])
            if unk:
                unknown.add(sl['role'])
        storage = list(cfg['storage'])
        # вешалка-хранение — свой список: только напольные, ступень цены — среди напольных (T-48/2: 38-тысячная стойка
        # Verda джапанди выпадала из «комфорта», посчитанного по крючкам за 1,6 тыс., и ячейка оставалась без хранения)
        st_lists, st_rx, st_unk = {}, {}, {}
        for r in storage:
            if r == 'вешалка':
                st_lists[r], _, st_rx[r], st_unk[r] = self.pool(slots[r], style, tier, lambda it: floor_hanger(it, self.R),
                                                                ' (хранение)')
                palette(st_lists[r])
            else:
                st_lists[r], st_rx[r], st_unk[r] = lists[r], r in relaxed, r in unknown
        banned: set = set()
        ctx = {'temp': 'mid', 'used_style': used['style'], 'used_all': used['all']}
        best, st_tries = None, 0
        for attempt in range(self.R['tries']['set']):
            chosen, cur = {}, {}
            st_role = None
            for r in storage:            # хранение: первое по порядку, у которого есть годный кандидат
                src = [c for c in st_lists[r] if c['sid'] not in banned]
                pick = next((c for c in self.ranked(src, style, ctx, st_unk[r])
                             if diversity_ok(c['fam'], r, cur, built, style)), None)
                if pick is not None:
                    chosen[r], cur[r], st_role = pick, pick['fam'], r
                    ctx = dict(ctx, temp=CC.temperature(pick.get('rgb')))
                    break
            if st_role is None:
                return best or {'empty': 'NO_STORAGE_IN_STYLE', 'banned': sorted(banned)}
            for sl in cfg['slots']:
                r = sl['role']
                if r in chosen or (r in storage and r != 'вешалка'):   # одно хранение-шкаф; вешалка — дополнением
                    continue
                pick = next((c for c in self.ranked([c for c in lists[r] if c['sid'] not in banned], style, ctx, r in unknown)
                             if diversity_ok(c['fam'], r, cur, built, style)), None)
                if pick is not None:
                    chosen[r], cur[r] = pick, pick['fam']
            items = [Item(role=r, w_cm=c['w'], d_cm=c['d'], h_cm=c['h'], name=c['name'], item_id=c['sid'])
                     for r, c in chosen.items()]
            lay = solve_hall(room, items)
            placed = {p.role for p in lay.placements}
            if os.environ.get('HALL_DEBUG'):
                print(f'    попытка {attempt + 1}: ' + ', '.join(f'{r} {c["sid"]} {c["w"]:g}×{c["d"]:g}' for r, c in chosen.items())
                      + f' → встали {sorted(placed)}; {lay.meta.get("reason")}', flush=True)
            if st_role not in placed:     # хранение не встало — отсекаем его и всё не меньше, следующее хранение
                st_tries += 1
                banned |= dominated(chosen[st_role], st_lists[st_role])
                if st_tries >= self.R['tries']['storage']:
                    return best or {'empty': 'STORAGE_NO_FIT', 'banned': sorted(banned)}
                continue
            skipped = [r for r in chosen if r not in placed]
            kept = {r: c for r, c in chosen.items() if r in placed}
            rx_now = (set(relaxed) - {st_role}) | ({st_role} if st_rx[st_role] else set())
            unk_now = (unknown - {st_role}) | ({st_role} if st_unk[st_role] else set())
            res = {'chosen': kept, 'layout': lay, 'room': room, 'lists': dict(lists, **{st_role: st_lists[st_role]}),
                   'bands': bands, 'slots': slots, 'attempts': attempt + 1, 'ctx': ctx, 'storage': st_role,
                   'skipped': skipped, 'relaxed': sorted(r for r in rx_now if r in kept),
                   'unknown': sorted(r for r in unk_now if r in kept)}
            if best is None or len(kept) > len(best['chosen']):
                best = res
            if not skipped:
                return best
            for r in skipped:             # не встало опциональное — следующий кандидат роли (меньше этого)
                banned |= dominated(chosen[r], lists[r])
        return best or {'empty': 'NO_FIT_AFTER_TRIES', 'banned': sorted(banned)}


def _alt(c: dict) -> dict:
    return dict({k: c.get(k) for k in ('mid', 'eid', 'sid', 'name', 'price', 'score', 'w', 'd', 'h', 'img', 'url', 'mesh',
                                       'style_score', 'size')}, has_mesh=c.get('mesh') == 'ready', mesh_defect=bool(c.get('mesh_defect')),
                style_unknown=bool(c.get('style_unknown')))


def _item(c: dict) -> dict:
    keep = ('mid', 'eid', 'sid', 'name', 'price', 'w', 'd', 'h', 'shop', 'img', 'url', 'qty', 'why', 'score', 'style_score',
            'mesh', 'cls', 'cls2', 'rgb', 'fam', 'size')
    # «меш есть/нет» на позицию: has_mesh — готовый (его ставит 3D демо); нет — спрос на генерацию (mesh_need)
    return dict({k: c.get(k) for k in keep if k in c}, qty=1, has_mesh=c.get('mesh') == 'ready',
                mesh_defect=bool(c.get('mesh_defect')), style_unknown=bool(c.get('style_unknown')))


def record(C: Composer, spec: dict, style: str, tier: str, res: dict) -> dict:
    import compose_common as CC
    chosen, lay = res['chosen'], res['layout']
    items = {r: _item(c) for r, c in chosen.items()}
    alts = {r: [_alt(c) for c in C.ranked([x for x in res['lists'][r] if x['sid'] != chosen[r]['sid']
                                           and (r != res['storage'] or r != 'вешалка' or floor_hanger(x, C.R))],
                                          style, res['ctx'], r in res['unknown'])][:C.R['alternates']] for r in chosen}
    sizes = {r: size_slot(res['slots'][r], chosen[r].get('size'), C.tol) for r in chosen}   # типоразмер выбранного товара
    slots = {r: {'ideal': sizes[r][0].get('ideal', {}), 'band': sizes[r][1], 'size': sizes[r][0]['size'],
                 'tolerance': list(C.tol), 'qty': 1, 'mesh': True, 'storage': r == res['storage']} for r in chosen}
    layout = {p.role: {'x': p.x, 'z': p.y, 'rot': int(p.rot), 'w': p.item.w_cm, 'd': p.item.d_cm, 'h': p.item.h_cm,
                       'elev': p.elev_cm, 'sid': p.item.item_id} for p in lay.placements}
    # контур Г-образного варианта (l-doors) — в комнату записи: витрина и перепроверка (`_room_model`) берут её, не чертёж (hall-demo-01 этап 3)
    layout['_room'] = {'id': spec['id'], 'variant': spec['variant'], 'w': spec['w'], 'd': spec['d'],
                       **({'contour': spec['contour']} if spec.get('contour') else {}),
                       'openings': [{k: v for k, v in o.items() if not k.startswith('_')} for o in spec.get('openings', [])],
                       'radiators': [{k: v for k, v in r.items() if not k.startswith('_')} for r in spec.get('radiators', [])],
                       'entrance_note': entrance_note(spec)}
    layout['_meta'] = {'solver': lay.meta.get('solver'), 'template': lay.meta.get('template'), 'reason': lay.meta.get('reason'),
                       'soft': sorted({v.code for v in lay.violations}), 'skipped_optional': sorted(res['skipped']),
                       'floor_used_pct': lay.floor_used_pct, 'attempts': res['attempts']}
    m2 = round(spec['w'] * spec['d'] / 10000, 1)
    rec = {'room_id': spec['id'], 'room_type': ROOM, 'purpose': ROOM, 'band': cell_band(spec), 'm2': m2, 'tier': tier, 'style': style,
           'style_fit': set_fit(items, style), 'pair': list(CC.STYLE_PAIR[style]), 'storage': res['storage'],
           'gaps': [f'{r}: не встал ни один кандидат' for r in sorted(res['skipped'])],
           'total': sum((it.get('price') or 0) for it in items.values()),
           'items': items, 'alternates': alts, 'slots': slots, 'layout': layout,
           'tier_relaxed': sorted(res['relaxed']), 'style_unknown': res['unknown'],
           'mesh_need': sorted(it['sid'] for it in items.values() if not it.get('mesh')),
           'mesh_blocked': sorted(it['sid'] for it in items.values() if it.get('mesh') in ('blocked', 'generated'))}
    rec['cell'] = '|'.join([spec['id'], ROOM, rec['band'], style, tier])
    rec['set_id'] = set_id(spec['id'], rec['band'], style, tier)
    if getattr(C, 'prov', None):     # происхождение (как спальня этапа В): профиль, версия, content_sha, плагин, дайджест правил и кода
        rec['provenance'] = dict(C.prov)
    return rec


def compose(spec: dict, C: Composer) -> tuple:
    bank, report = [], {'cells': [], 'shortage': {}}
    built: list = []
    used_all: dict = {}            # семейство → в скольких наборах уже стоит
    for style in C.R['styles']:
        used = {'style': set(), 'all': used_all}
        for tier in C.R['tiers']:
            res = C.build(style, tier, spec, built, used)
            cell = {'style': style, 'tier': tier}
            if 'empty' in res:
                report['cells'].append(dict(cell, empty=res['empty']))
                print(f'  {style} {tier}: ПУСТО — {res["empty"]}', flush=True)
                continue
            rec = record(C, spec, style, tier, res)
            bank.append(rec)
            built.append((style, {r: c['fam'] for r, c in res['chosen'].items() if r in MAJOR}))
            fams = {c['fam'] for c in res['chosen'].values()}
            used['style'] |= fams
            for f in fams:
                used_all[f] = used_all.get(f, 0) + 1
            report['cells'].append(dict(cell, set_id=rec['set_id'], total=rec['total'], fit=rec['style_fit'],
                                        storage=rec['storage'], roles=sorted(rec['items']), mesh_need=len(rec['mesh_need']),
                                        mesh_blocked=len(rec['mesh_blocked']), style_unknown=rec['style_unknown'],
                                        skipped=rec['layout']['_meta']['skipped_optional']))
            print(f"  {style} {tier}: {rec['set_id']} {rec['total']:,} ₽ фит {rec['style_fit']} хранение {rec['storage']} "
                  f"предметов {len(rec['items'])} без меша {len(rec['mesh_need'])} без оценки стиля {rec['style_unknown']} "
                  f"не встали {rec['layout']['_meta']['skipped_optional']}", flush=True)
    report['shortage'] = {f'{r} × {s}': v for (r, s), v in sorted(C.shortage.items())}
    report['by_role'] = by_role(bank)
    return bank, report


def by_role(bank: list) -> dict:
    """По ролям: в скольких наборах, сколько из них с готовым мешом / меш не годен / без меша (спрос на генерацию) / без
    оценки стиля (спрос на оценку)."""
    out: dict = {}
    for s in bank:
        for r, it in s['items'].items():
            o = out.setdefault(r, {'в наборах': 0, 'меш готов': 0, 'меш не годен': 0, 'без меша': 0, 'без оценки стиля': 0,
                                   'товаров': set()})
            o['в наборах'] += 1
            o['товаров'].add(it['sid'])
            o['меш готов' if it.get('mesh') == 'ready' else 'меш не годен' if it.get('mesh') else 'без меша'] += 1
            o['без оценки стиля'] += bool(it.get('style_unknown'))
    return {r: dict(o, товаров=len(o['товаров'])) for r, o in sorted(out.items())}


def check_bank(bank: list, R: dict, tol: tuple) -> list:
    """Критерии по готовому банку → нарушения (пусто — чисто; «~» — предупреждение). Раскладку перепроверяет `validate`
    (диспетчер по room_type → validate_hall): жёстких 0."""
    sys.path.insert(0, SOLVER)
    from planner.models import Item, Placement, Severity
    from planner.validate import validate
    bad = []
    slot_cfg = {sl['role']: sl for sl in R['purposes'][ROOM]['slots']}
    storage_any = set(R['purposes'][ROOM]['storage'])
    for s in bank:
        sid = s.get('set_id')
        for k in ('room_id', 'room_type', 'purpose', 'style', 'tier', 'layout', 'slots', 'cell', 'storage'):
            if not s.get(k):
                bad.append(f'{sid}: нет {k}')
        it = s['items']
        if not storage_any & set(it):
            bad.append(f'{sid}: нет хранения верхней одежды ({sorted(storage_any)})')
        for r, x in it.items():
            # полоса записи — обязана быть полосой одного из типоразмеров слота правил (T-90): иначе запись «расширила» слот
            allowed = [band_of(sz, tol) for sz in slot_sizes(slot_cfg[r])] if slot_cfg[r].get('band') else [{}]
            if s['slots'][r]['band'] not in allowed:
                bad.append(f'{sid}: {r} — полоса {s["slots"][r]["band"]} не из типоразмеров слота')
            g = gate(dict(x, role=r, footprint_ok=True), dict(slot_cfg[r], ideal=s['slots'][r]['ideal']), s['slots'][r]['band'])
            if g:
                bad.append(f'{sid}: {r} {x["sid"]} — {g}')
            if r not in s['layout']:
                bad.append(f'{sid}: {r} в наборе, но не в раскладке')
            n = len(s['alternates'].get(r, []))
            if n < 3:
                bad.append(f'~ {sid}: {r} — альтернатив {n} < 3 (каталог тонкий: замена в демо беднее)')
        lay = s['layout']
        room = _room_model(lay['_room'])
        pls = [Placement(role=r, x=p['x'], y=p['z'], rot=p['rot'], elev_cm=p.get('elev') or 0,
                         item=Item(role=r, w_cm=p['w'], d_cm=p['d'], h_cm=p['h']))
               for r, p in lay.items() if not r.startswith('_')]
        hard = [v.code for v in validate(room, pls).violations if v.severity is Severity.HARD]
        if hard:
            bad.append(f'{sid}: жёсткие нарушения раскладки {hard}')
    fam = lambda x: x.get('fam') or x['sid']   # noqa: E731
    for i, a in enumerate(bank):
        ma = {fam(a['items'][r]) for r in MAJOR if r in a['items']}
        for b in bank[i + 1:]:
            if a['style'] != b['style']:
                mb = {fam(b['items'][r]) for r in MAJOR if r in b['items']}
                if len(ma & mb) > 1:
                    bad.append(f'{a["set_id"]}↔{b["set_id"]}: общих крупных {len(ma & mb)} > 1')
    return bad


def _check_text(bank: list, problems: list) -> str:
    hard = [p for p in problems if not p.startswith('~')]
    warn = [p[2:] for p in problems if p.startswith('~')]
    return (f'ПРОВЕРКА банка: наборов {len(bank)}, нарушений {len(hard)}, предупреждений {len(warn)}'
            + ''.join(f'\n  ✗ {p}' for p in hard) + ''.join(f'\n  ~ {p}' for p in warn))


# ---------------------------------------------------------------- лист: раскладка сверху + состав по стилям
def sheet(bank: list, out_dir: str) -> str:
    """PNG на набор (план сверху — `hall_exam.draw`, под ним состав: фото, роль, товар, цена, меш) и общий лист `_hall.png`."""
    from PIL import Image, ImageDraw, ImageFont
    import compose_common as CC
    import hall_exam as HE
    from planner.models import Item, Layout, Placement
    os.makedirs(out_dir, exist_ok=True)
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    f11, f12 = ImageFont.truetype(font, 11), ImageFont.truetype(font, 12)
    paths = []
    for s in bank:
        lay = s['layout']
        room = _room_model(lay['_room'])
        pls = [Placement(role=r, x=p['x'], y=p['z'], rot=p['rot'], elev_cm=p.get('elev') or 0,
                         item=Item(role=r, w_cm=p['w'], d_cm=p['d'], h_cm=p['h']))
               for r, p in lay.items() if not r.startswith('_')]
        L = Layout(room=room, placements=pls)
        meta = lay['_meta']
        res = {'id': f"{s['style']} · {s['total']:,} ₽".replace(',', ' '), 'area_m2': s['m2'], 'expect': 'solve', 'pass': True,
               'hard': [], 'soft': meta['soft'], 'skipped_optional': meta['skipped_optional'], 'reason': meta['reason']}
        top = os.path.join(out_dir, f"{s['set_id']}-plan.png")
        HE.draw(room, L, res, top)
        plan = Image.open(top).convert('RGB')
        order = [sl['role'] for sl in rules()['purposes'][ROOM]['slots']]
        rows = sorted(s['items'].items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order))
        rh, W = 66, plan.width
        img = Image.new('RGB', (W, plan.height + 40 + rh * len(rows)), (255, 255, 255))
        img.paste(plan, (0, 0))
        g = ImageDraw.Draw(img)
        y0 = plan.height + 4
        g.text((12, y0), f"фит стиля {s['style_fit']}; без меша {len(s['mesh_need'])} из {len(rows)}; "
                         f"без оценки стиля: {', '.join(s['style_unknown']) or '—'}", fill=(40, 40, 40), font=f12)
        for n, (r, it) in enumerate(rows):
            y = y0 + 26 + n * rh
            p = CC.get_thumb(it['img'], it['mid'], it['eid']) if it.get('img') else None
            if p:
                th = Image.open(p).convert('RGB')
                th.thumbnail((80, 60))
                img.paste(th, (12, y))
            mark = {'ready': 'меш готов', 'blocked': 'меш не годен', 'generated': 'меш не годен'}.get(it.get('mesh'), 'БЕЗ МЕША')
            st = f"стиль {it['style_score']:g}" if it.get('style_score') is not None else 'без оценки стиля'
            g.text((100, y + 2), f"{r} · {it['w']:g}×{it['d']:g}×{it['h']:g} · {it['price']:,} ₽".replace(',', ' '),
                   fill=(0, 0, 0), font=f12)
            g.text((100, y + 20), (it.get('name') or '')[:58], fill=(60, 60, 60), font=f11)
            g.text((100, y + 38), f'{st} · {mark}', fill=(170, 40, 40) if not it.get('mesh') else (40, 120, 60), font=f11)
        path = os.path.join(out_dir, f"{s['set_id']}.png")
        img.save(path)
        paths.append(path)
    out = os.path.join(out_dir, '_hall.png')
    if paths:
        HE.sheet(paths, out, cols=len(paths))
    return out


def main(argv: list) -> int:
    sys.path.insert(0, SOLVER)
    import bank_paths as BP
    R = rules()
    tol = tolerance()
    thr = float(PROFILE['style']['in_style_min'])
    rc = R['rooms'][ROOM]
    variant = argv[argv.index('--variant') + 1] if '--variant' in argv else rc.get('variant')
    spec = room_spec(ROOM, variant)
    out = BP.room_bank_output(os.environ, ROOM)
    print(f'Прихожая {spec["id"]}/{spec["variant"]} {spec["w"]}×{spec["d"]}; {entrance_note(spec)}', flush=True)
    print(f'Каталог прихожей, стиль, меши... порог стиля {thr}, полоса {tol}', flush=True)
    cat = load_items()
    C = Composer(cat, R, tol, thr)
    by: dict = {}
    for it in cat:
        b = by.setdefault(it['role'], [0, 0, 0])
        b[0] += 1
        b[1] += bool(it.get('styles'))
        b[2] += it.get('mesh') == 'ready'
    print('товаров: ' + ', '.join(f'{r} {n} (оценка стиля {s}, меш готов {m})' for r, (n, s, m) in sorted(by.items())), flush=True)
    import room_identity as RI
    C.prov = RI.provenance(ROOM)
    bank, report = compose(spec, C)
    report['room'] = {'id': spec['id'], 'variant': spec['variant'], 'title': spec.get('title'), 'entrance_note': entrance_note(spec)}
    need: dict = {}
    for s in bank:
        for r, it in s['items'].items():
            if it['sid'] in s['mesh_need']:
                need.setdefault(it['sid'], {'role': r, 'name': it['name'], 'sets': 0, 'w': it['w'], 'd': it['d'], 'h': it['h']})
                need[it['sid']]['sets'] += 1
    report['mesh_need'] = sorted(need.items(), key=lambda kv: (-kv[1]['sets'], kv[0]))
    # проверка ДО записи (T-20261106-89, шаг 1): жёсткое нарушение — прежний кандидат цел, отказ рядом, код 1
    import room_candidate as RC
    problems = check_bank(bank, R, tol)
    print('по ролям: ' + json.dumps(report['by_role'], ensure_ascii=False), flush=True)
    print(_check_text(bank, problems), flush=True)
    want = cells(R, spec)
    ident = RI.check(bank, want, C.prov, ROOM)
    print(f'ИДЕНТИЧНОСТЬ кандидата: ячеек {len(bank)} из {len(want)}, отказов {len(ident)}'
          + ''.join(f'\n  ✗ {x}' for x in ident), flush=True)
    hard, warn = RC.split(problems, ident)
    rc = RC.commit('compose_hall', out, bank, report, hard, warn)
    if rc == 0:
        print(f'БАНК: {out} — наборов {len(bank)}; отчёт {RC.report_path(out)}; нужен меш: {len(need)} товаров', flush=True)
    if '--sheet' in argv:
        print('лист:', sheet(bank, argv[argv.index('--sheet') + 1]))
    return rc


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    R = rules()
    tol = (0.8, 1.1)
    S = {sl['role']: sl for sl in R['purposes'][ROOM]['slots']}
    ok('профиль: сборщик hall, роли слотов = роли профиля, 6 стилей (неоклассика последней — T-89)',
       PROFILE['composer']['plugin'] == 'hall' and set(S) == set(PROFILE['roles']) and len(R['styles']) == 6
       and R['styles'][-1] == 'неоклассика')
    ok('хранение — из storage_any солвера (без «шкафа» — его нет в каталоге)',
       set(R['purposes'][ROOM]['storage']) <= set(load_json(os.path.join(SOLVER, 'rules', 'hall.json'))['composition']['storage_any']))
    b = band_of(S['шкаф-купе'], tol)
    ok('полоса шкафа-купе: −20…+10 % от 180×60×240', b == {'w': [144.0, 198.0], 'd': [48.0, 66.0], 'h': [192.0, 264.0]})
    wr = {'w': 180, 'd': 60, 'h': 240, 'footprint_ok': True}
    ok('шкаф 180×60×240 — годен; 200 — вне полосы; без высоты — нет; неправдоподобный — нет',
       gate(wr, S['шкаф-купе'], b) is None and 'вне полосы' in gate(dict(wr, w=200), S['шкаф-купе'], b)
       and gate(dict(wr, h=None), S['шкаф-купе'], b) == 'нет Ш×Г×В'
       and gate(dict(wr, footprint_ok=False), S['шкаф-купе'], b) == 'размеры неправдоподобны')
    ok('обувница: высота свободна (44 и 107 — обе), ширина в полосе 48–66',
       gate({'w': 60, 'd': 35, 'h': 44}, S['обувница'], band_of(S['обувница'], tol)) is None
       and gate({'w': 60, 'd': 35, 'h': 107}, S['обувница'], band_of(S['обувница'], tol)) is None
       and gate({'w': 80, 'd': 35, 'h': 107}, S['обувница'], band_of(S['обувница'], tol)) is not None)
    ok('зеркало и вешалка — без полосы, но с Ш×Г×В', band_of(S['зеркало'], tol) == {} and
       gate({'w': 50, 'd': 3, 'h': 150}, S['зеркало'], {}) is None and gate({'w': 50, 'h': 150}, S['зеркало'], {}) == 'нет Ш×Г×В')
    ok('напольная вешалка (60×45×175) — хранение; настенная (46×17×92) — нет',
       floor_hanger({'w': 60, 'd': 45, 'h': 175}, R) and not floor_hanger({'w': 46, 'd': 17, 'h': 92}, R))
    ok('меш: привязка ready → ready, blocked → blocked, ревизия без привязки → generated, ничего → None',
       [mesh_of(a) for a in ({'mesh_status': 'ready'}, {'mesh_status': 'blocked'}, {'mesh_status': 'none', 'revision': 'generated'},
                             {'mesh_status': 'none', 'revision': None}, {})] == ['ready', 'blocked', 'generated', None, None])
    a = {'mid': 1, 'eid': 'a', 'score': 5.0, 'price': 10, 'mesh': None}
    m = {'mid': 2, 'eid': 'b', 'score': 3.0, 'price': 20, 'mesh': 'blocked'}
    r_ = {'mid': 3, 'eid': 'c', 'score': 1.0, 'price': 30, 'mesh': 'ready'}
    ok('порядок: готовый меш → не годен → нет, потом балл', sorted([a, m, r_], key=rank_key) == [r_, m, a])
    ok('модель реже стоит в других стилях — раньше (счёт, не флаг)',
       sorted([dict(a, seen_all=2), dict(a, mid=7, seen_all=1, score=1.0)], key=rank_key)[0]['mid'] == 7)
    ok('брак меша — последним', sorted([dict(r_, mesh_defect=True), a], key=rank_key)[0] is a)
    ok('с оценкой стиля — раньше товара без оценки при равном меше', sorted([dict(a, style_unknown=True, score=9), dict(a, mid=5)],
                                                                         key=rank_key)[0]['mid'] == 5)
    built = [('сканди', {'шкаф-купе': 'W1', 'обувница': 'S1', 'банкетка': 'B1'})]
    ok('другой стиль: одна общая крупная — можно, вторая — нельзя; зеркало не в счёт',
       diversity_ok('W1', 'шкаф-купе', {}, built, 'лофт') and not diversity_ok('S1', 'обувница', {'шкаф-купе': 'W1'}, built, 'лофт')
       and diversity_ok('M1', 'зеркало', {'шкаф-купе': 'W1', 'обувница': 'S1'}, built, 'лофт'))
    ok('стиль набора: товары без оценки не в счёт', set_fit({'шкаф-купе': {'style_score': 8}, 'обувница': {'style_score': None},
                                                             'зеркало': {'style_score': 6}}, 'x') == round((8 + 0.3 * 6) / 1.3, 1))
    # пул: в стиле пусто, роль в style_unknown — товары без оценки; вне списка — пусто
    cat = [dict(role='обувница', mid=1, eid=str(i), name='Обувница', price=1000 + i, w=60, d=35, h=100, footprint_ok=True,
                img='', fam=f'f{i}', styles=None, mesh=None) for i in range(10)]
    cat += [dict(role='банкетка', mid=2, eid='x', name='Банкетка', price=5000, w=110, d=45, h=46, footprint_ok=True, img='',
                 fam='b', styles={'сканди': 5.0}, mesh=None)]
    C = Composer(cat, R, tol, 6.6)
    sh, _b, _rx, unk = C.pool(S['обувница'], 'сканди', 'комфорт')
    bn, _b2, _rx2, unk2 = C.pool(S['банкетка'], 'сканди', 'комфорт')
    ok('обувница без оценок — идёт без оценки стиля (style_unknown); банкетка 5,0 < 6,6 — не в стиле и не подменяется',
       unk and len(sh) >= 1 and not bn and not unk2)
    ok('ступень «комфорт» — квантили 0,2–0,85 цены роли: из 10 цен 1000…1009 — 1002…1008',
       sorted(x['price'] for x in sh) == list(range(1002, 1009)))
    # вешалка-хранение: ступень цены — среди напольных; дорогая стойка в стиле не теряется за дешёвыми крючками
    hang = [dict(role='вешалка', mid=3, eid=f'k{i}', name='Вешалка настенная', price=1500 + i, w=50, d=10, h=20,
                 footprint_ok=True, img='', fam=f'k{i}', styles={'джапанди': 7.0}, mesh=None) for i in range(10)]
    hang += [dict(role='вешалка', mid=3, eid='v', name='Вешалка напольная', price=38000, w=50, d=44, h=144, footprint_ok=True,
                  img='', fam='v', styles={'джапанди': 7.4}, mesh=None)]
    C2 = Composer(hang, R, tol, 6.6)
    allh = C2.pool(S['вешалка'], 'джапанди', 'комфорт')[0]
    floor = C2.pool(S['вешалка'], 'джапанди', 'комфорт', lambda it: floor_hanger(it, R), ' (хранение)')[0]
    ok('вешалка-хранение: в общей ступени стойки за 38 тыс. нет, среди напольных — есть; нехватка — своей строкой',
       'v' not in {x['eid'] for x in allh} and [x['eid'] for x in floor] == ['v']
       and ('вешалка (хранение)', 'джапанди') in C2.shortage)
    # солвер на геометрии flat215 (первый вариант файла) — набор встаёт, повтор — та же раскладка
    spec = room_spec(ROOM, R['rooms'][ROOM].get('variant'))
    ok('вариант по умолчанию — первый в файле (drawing-180)', spec['variant'] == load_json(FLAT)['rooms'][0]['variant'] == 'drawing-180')
    sys.path.insert(0, SOLVER)
    from planner.hall import solve_hall
    from planner.models import Item
    room = _room_model(spec)
    kit = [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in
           (('шкаф-купе', 180, 60, 240), ('обувница', 60, 35, 100), ('банкетка', 110, 45, 46), ('зеркало', 60, 3, 80))]
    lay = solve_hall(room, kit)
    sig = lambda L: [(p.role, p.x, p.y, p.rot) for p in L.placements]  # noqa: E731
    ok('солвер прихожей ставит шкаф-купе 180 на flat215 и повтор детерминирован',
       'шкаф-купе' in {p.role for p in lay.placements} and sig(lay) == sig(solve_hall(room, kit)))
    ok('id набора — от ячейки, не от состава (T-89 шаг 2): та же ячейка — тот же id, другая ступень — другой; префикс hall-',
       set_id('hall', '8.4', 'сканди', 'комфорт') == set_id('hall', '8.4', 'сканди', 'комфорт')
       != set_id('hall', '8.4', 'сканди', 'эконом') and set_id('hall', '8.4', 'сканди', 'комфорт').startswith('hall-'))
    # ---- типоразмеры слота (T-20261106-90): допуск внутри каждого; суд — по типоразмеру товара
    szs = {r: [x['size'] for x in slot_sizes(S[r])] for r in ('шкаф-купе', 'обувница', 'банкетка', 'консоль')}
    ok('типоразмеры из правил: основной первым; шкаф-купе 2, обувница 5, банкетка 6, консоль 3',
       szs['обувница'][0] == '60x35' and [len(v) for v in szs.values()] == [2, 5, 6, 3])
    sz, bd = fit_size({'w': 90, 'd': 38, 'h': 50, 'footprint_ok': True}, S['обувница'], tol)
    ok('обувница 90×38 — вне основной полосы, годна в 90x35; полоса — −20…+10 % от 90×35',
       gate({'w': 90, 'd': 38, 'h': 50}, S['обувница'], band_of(S['обувница'], tol)) is not None
       and sz['size'] == '90x35' and bd == {'w': [72.0, 99.0], 'd': [28.0, 38.5]})
    ok('шкаф-купе 180×40×210 (неглубокий) — годен в 180x45 по Ш×Г×В; 100×60 — ни в один (причина по основному)',
       fit_size({'w': 180, 'd': 40, 'h': 210, 'footprint_ok': True}, S['шкаф-купе'], tol)[0]['size'] == '180x45'
       and fit_size({'w': 100, 'd': 60, 'h': 210, 'footprint_ok': True}, S['шкаф-купе'], tol)[0] is None
       and 'вне полосы' in fit_size({'w': 100, 'd': 60, 'h': 210, 'footprint_ok': True}, S['шкаф-купе'], tol)[1])
    ok('честность размеров не ослаблена: без глубины и с неправдоподобным габаритом — ни в один типоразмер',
       fit_size({'w': 90, 'h': 50}, S['обувница'], tol)[0] is None
       and fit_size({'w': 90, 'd': 35, 'h': 50, 'footprint_ok': False}, S['обувница'], tol)[0] is None)
    C3 = Composer([dict(role='консоль', mid=4, eid=e, name='Консоль', price=9000, w=w, d=d, h=80, footprint_ok=True, img='',
                        fam=f'c{e}', styles={'лофт': 7.0}, mesh=None) for e, w, d in (('a', 90, 35), ('b', 120, 30), ('c', 150, 30))],
                  R, tol, 6.6)
    C3.pool(S['консоль'], 'лофт', 'комфорт')
    sh3 = C3.shortage[('консоль', 'лофт')]
    ok('пул: 90×35 и 120×30 годны (основной и 120x30), 150×30 — нет; счёт по типоразмерам и семействам в отчёте',
       sh3['годных по размеру'] == 2 and sh3['семейств по размеру'] == 2 and sh3['по типоразмерам']['120x30'] == 1
       and sh3['по типоразмерам']['90x35'] == 1)

    def one_set(role, x, size_id):
        """Минимальный набор для суда: шкаф-купе основной + предмет роли в типоразмере size_id (раскладка — солвер)."""
        wr_ = dict(mid=9, eid='w', sid='9:w', w=180, d=60, h=240)
        chosen_ = {'шкаф-купе': wr_, role: x}
        lay_ = solve_hall(room, [Item(role=r, w_cm=c['w'], d_cm=c['d'], h_cm=c['h'], item_id=c['sid']) for r, c in chosen_.items()])
        sl_ = {r: dict(zip(('ideal', 'band'), (lambda z: (z[0]['ideal'], z[1]))(size_slot(S[r], sz_, tol))), size=sz_)
               for r, sz_ in (('шкаф-купе', '180x60'), (role, size_id))}
        layout_ = {p.role: {'x': p.x, 'z': p.y, 'rot': int(p.rot), 'w': p.item.w_cm, 'd': p.item.d_cm, 'h': p.item.h_cm,
                            'elev': p.elev_cm, 'sid': p.item.item_id} for p in lay_.placements}
        layout_['_room'] = {'id': spec['id'], 'variant': spec['variant'], 'w': spec['w'], 'd': spec['d'],
                            'openings': [{k: v for k, v in o.items() if not k.startswith('_')} for o in spec.get('openings', [])],
                            'radiators': []}
        return [{'set_id': 'hall-t', 'room_id': 'hall', 'room_type': ROOM, 'purpose': ROOM, 'style': 'лофт', 'tier': 'комфорт',
                 'cell': 'c', 'storage': 'шкаф-купе', 'items': chosen_, 'slots': sl_, 'layout': layout_,
                 'alternates': {r: [{}] * 3 for r in chosen_}}]
    cons = dict(mid=4, eid='b', sid='4:b', w=120, d=30, h=80)
    good = one_set('консоль', cons, '120x30')
    ok('суд: набор с консолью второго типоразмера (120×30) — без нарушений', check_bank(good, R, tol) == [])
    wide = one_set('консоль', dict(cons, w=150), '120x30')
    ok('суд: консоль 150×30 — вне всех полос → отказ', any('вне полосы' in p for p in check_bank(wide, R, tol)))
    forged = one_set('консоль', dict(cons, w=150), '120x30')
    forged[0]['slots']['консоль']['band'] = {'w': [100, 160], 'd': [24, 33]}
    ok('суд: полоса записи не из типоразмеров (подделана под товар) → отказ',
       any('не из типоразмеров' in p for p in check_bank(forged, R, tol)))
    want = cells(R, spec)
    ok(f'матрица прихожей: стили × ступени ({len(R["styles"])} × {len(R["tiers"])}), комната и полоса — из геометрии',
       len(want) == len(R['styles']) * len(R['tiers']) == len(set(want))
       and want[0] == (spec['id'], ROOM, cell_band(spec), R['styles'][0], next(iter(R['tiers']))))
    print(f'FAILS {bad}')
    return bad


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if _selftest() else 0)
    if '--check' in sys.argv:
        _b = load_json(sys.argv[sys.argv.index('--check') + 1])
        _p = check_bank(_b, rules(), tolerance())
        print(_check_text(_b, _p))
        sys.exit(1 if [x for x in _p if not x.startswith('~')] else 0)
    sys.exit(main(sys.argv[1:]))
