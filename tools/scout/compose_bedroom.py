#!/usr/bin/env python3
"""СБОРЩИК НАБОРОВ СПАЛЬНИ (план onb-06 Т3–Т5, вариант Б; ADR-0330 п.3) — наборы по 5 стилям × назначению × тиру с
раскладкой нашего солвера спальни на реальной геометрии комнаты квартиры 215. Пишет ОТДЕЛЬНЫЙ банк
`sets-bedroom.next.json` (`bank_paths.room_bank_output`): живой `sets3.json` и гостиную не трогает.

ПОРЯДОК (одна ячейка `room_id|purpose|band|style|tier`):
  1. кандидаты слота — товар с Ш×Г×В (без размеров в набор не ставим), в полосе 0,8–1,1 идеала слота по сторонам `band`
     (ADR-0322, допуск — zones.json), кровать — с честным габаритом (`footprint_ok`) и спальным местом в вилке назначения;
     в стиле — балл ≥ `in_style_min` (rules/demo-swap.json); цена — в квантилях тира роли;
  2. порядок — СНАЧАЛА с мешом (готов → сгенерирован → нет; решение ведущего 05.11: «3D собирается сразу»), потом балл
     стиля + палитра (0,5 × `compose_common.palette_score`), ничья — цена → SKU;
  3. разнообразие: между стилями одной комнаты и назначения — ≤ 1 общая крупная модель (семейство), связка
     «кровать + шкаф» не повторяется нигде; повтор кровати внутри стиля — штраф;
  4. раскладка — `planner.bedroom.solve_bedroom`; кровать не встала или не встало ни одно хранение — следующий кандидат;
     ковёр — под нижние 2/3 кровати, не под дугу двери; лампы — на тумбах; шторы — по числу окон;
  5. запись = формат `sets3` + `room_id`, `room_type`, `purpose`, `slots` (идеал и полоса — по ним очередь мешей T-35),
     `layout` (x, z, rot, w, d, h, sid — как `v3set{n}-layout.json`), `mesh_need`.
Пустые назначения (кабинет, детская) — в отчёте рядом с причиной (`<банк>.report.json`), в банк не идут.

  ~/venvs/scout/bin/python compose_bedroom.py --rooms bedroom-1 [--sheet DIR]   # канарейка
  ~/venvs/scout/bin/python compose_bedroom.py --rooms bedroom-1,bedroom-2 --sheet DIR
  ~/venvs/scout/bin/python compose_bedroom.py --nightly        # ночь: только комнаты с enabled=true (сейчас — ни одной)
  python3 compose_bedroom.py --selftest                        # чистые функции, без базы и сети
Env: `ROOM_SETS_OUTPUT` — путь банка (живой — отказ); `BEDROOM_STYLE_SCORES` — файл стиля спальни (по умолчанию
`style-scores-bedroom.json` рядом; в worktree его нет — указать путь основной копии).
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
FLAT = os.path.join(HERE, 'flat215-bedrooms.json')
# ПРОФИЛЬ КОМНАТЫ (room-pipeline-01 Б-2, T-20261105-40): правила состава, допуск полосы, порог стиля, крупное, веса стиля и
# жёсткий минимум шкафа — из `rules/profiles/bedroom.json` (ссылки на bedroom-composition.json, zones.json, demo-swap.json)
import room_profile as _RP  # noqa: E402
PROFILE = _RP.load('bedroom')
MAJOR = _RP.major(PROFILE)          # крупное: кровать, шкаф, комод, тумба (полоса Ш×Г×В, вес стиля)
FLOOR = MAJOR                       # то, что ставит солвер и чему нужен меш под слот
ROLE_W = dict(PROFILE['style']['role_weights'])   # вес в стиле набора (styles.json — шкаф/комод)
WARDROBE_MIN_W = _RP.hard(PROFILE, 'шкаф', 'min_w')   # уже — не шкаф, а пенал (ведущий 05.11: «ни один шкаф ≥ 80 см не встаёт»)


def rules() -> dict:
    """Правила состава наборов (профиль → composer.rules); новая копия на вызов, как прежний load_json(RULES)."""
    return _RP.load('bedroom')['composer']['rules']


def tolerance() -> tuple:
    return tuple(PROFILE['tolerance'] or (0.8, 1.1))
MESH_RANK = {'ready': 0, 'generated': 1, None: 2}


def load_json(p: str) -> dict:
    return json.load(open(p, encoding='utf-8'))


# ---------------------------------------------------------------- чистые функции (селфтест)
# общие со сборщиком прихожей (`compose_hall.py`, T-20261105-48) — в `compose_common`, тела без изменений; имена остаются
# и здесь (их берут `asset_coverage.buckets_slots` и селфтест)
from compose_common import band_of, dominated, num, palette, side, tier_range  # noqa: E402,F401


def gate(it: dict, slot: dict, band: dict) -> str | None:
    """None — товар годен в слот по размерам; иначе причина. Без Ш×Г×В — не ставим (дополнение ведущего 05.11).
    Декор без полосы (шторы, плед — мягкое, ADR-0323) размеров не требует."""
    need = ('w', 'd', 'h') if slot.get('role') in MAJOR else (slot.get('need_dims') or ())
    if need and not all(num(it.get(k)) for k in need):
        return 'нет Ш×Г×В' if len(need) == 3 else 'нет Ш×Г'
    if slot.get('role') == 'кровать':
        if not it.get('footprint_ok'):
            return 'габарит не сверен'
        sw, (a, b) = num(it.get('sleep_w')), slot['sleep_w']
        if sw is None or not (a <= sw <= b):
            return f'спальное место {sw} вне {a}–{b}'
    for k, (lo, hi) in band.items():
        v = side(it, k)
        if v is None:
            return f'нет размера {k}'
        if not (lo <= v <= hi):
            return f'{k}={v:g} вне полосы {lo:g}–{hi:g}'
    return None


def rank_key(it: dict) -> tuple:
    """Порядок кандидатов (полный ключ, без зависимости от порядка пула):
    1) модель ещё не стоит в этом стиле (тиры одного стиля — разные вещи; «Монблан» в трёх наборах из четырёх — канарейка 05.11);
    2) меш: готов → сгенерирован → нет → брак меша (приоритет ведущего 05.11 — 3D собирается сразу; «брак не брать» —
       бракованный идёт последним: только если другого в полосе и стиле нет);
    2б) декор: подходящий по названию (`prefer`: ночник, прикроватная, абажур — ведущий 05.11) — при прочих равных первым;
    3) модель ещё не стоит в других стилях комнаты (жёсткий предел ≤ 1 общей — `diversity_ok`, здесь — «лучше ноль»);
    4) балл (стиль + палитра), 5) цена, 6) SKU."""
    return (bool(it.get('seen_style')), 3 if it.get('mesh_defect') else MESH_RANK.get(it.get('mesh'), 2),
            it.get('preferred') is False, bool(it.get('seen_all')),
            -round(it.get('score', 0.0), 4), it.get('price') or 0, int(it['mid']), str(it['eid']))


def diversity_ok(fam: str, role: str, cur: dict, built: list, style: str) -> bool:
    """Жёсткое разнообразие. cur — {роль: семейство} набора в сборке; built — [(стиль, {роль: семейство})] уже собранных
    наборов той же комнаты и назначения. Между РАЗНЫМИ стилями — ≤ 1 общая крупная модель; связка «кровать + шкаф» —
    ни с одним набором."""
    if role not in MAJOR:
        return True
    mine = dict(cur, **{role: fam})
    for st, other in built:
        if st != style and len(set(mine.values()) & set(other.values())) > 1:
            return False
        if ('кровать' in mine and 'шкаф' in mine and mine['кровать'] == other.get('кровать')
                and mine['шкаф'] == other.get('шкаф')):
            return False
    return True


def set_fit(items: dict, style: str) -> float:
    """Стиль набора — средневзвешенный балл крупного (веса ROLE_W)."""
    num_, den = 0.0, 0.0
    for r, it in items.items():
        w = ROLE_W.get(r)
        if w and it.get('style_score') is not None:
            num_ += w * it['style_score']
            den += w
    return round(num_ / den, 1) if den else 0.0


def local_to_world(px: float, py: float, rot: float, lx: float, ly: float) -> tuple:
    """Точка в осях предмета (x — ширина, y — к изножью) → комната; поворот как `planner.bedroom._nightstand_spots`."""
    a = math.radians(-rot)
    return (round(px + lx * math.cos(a) - ly * math.sin(a), 1), round(py + lx * math.sin(a) + ly * math.cos(a), 1))


def set_id(room_id: str, purpose: str, band: str, style: str, tier: str) -> str:
    """id набора — от ЯЧЕЙКИ `room_id|purpose|band|style|tier`, без состава (room-bank-01 этап В, T-20261106-70): замена
    предмета — то же set_id, новое поколение ячейки. До этапа В id считался и от SKU — замена давала «новый набор»."""
    import room_identity as RI
    return RI.set_id_of('bedroom', (room_id, purpose, band, style, tier))


def cell_band(spec: dict) -> str:
    """Полоса ячейки спальни — площадь комнаты по геометрии, м² до десятых (`'10.6'`)."""
    return f"{round(spec['w'] * spec['d'] / 10000, 1):g}"


def cells(R: dict) -> list:
    """ОЖИДАЕМАЯ МАТРИЦА ячеек из правил профиля — в порядке сборки (`compose`): комнаты → непустые назначения → стили → тиры;
    полоса — площадь комнаты. Её обязан дать полный кандидат банка (`room_identity.check`)."""
    out = []
    for room_id, rc in R['rooms'].items():
        band = cell_band(room_spec(room_id, rc['variant']))
        for purpose in rc['purposes']:
            if R['purposes'][purpose].get('empty'):
                continue
            out += [(room_id, purpose, band, style, tier) for style in R['styles'] for tier in R['tiers']]
    return out


# ---------------------------------------------------------------- данные
def _room_model(spec: dict, purpose: str):
    sys.path.insert(0, SOLVER)
    from planner.models import Opening, Radiator, Room
    return Room(width_cm=spec['w'], depth_cm=spec['d'], contour=spec.get('contour'),
                openings=[Opening(**{k: v for k, v in o.items() if not k.startswith('_')}) for o in spec.get('openings', [])],
                radiators=[Radiator(**{k: v for k, v in r.items() if not k.startswith('_')}) for r in spec.get('radiators', [])],
                room_type='bedroom', purpose=purpose)


def room_spec(room_id: str, variant: str) -> dict:
    for r in load_json(FLAT)['rooms']:
        if r['id'] == room_id and r['variant'] == variant:
            return r
    raise SystemExit(f'{FLAT}: нет {room_id}/{variant}')


def load_items(rules: dict) -> tuple:
    """(мебель, декор) спальни из адаптера каталога (`catalog_items.items('bedroom')`, room-pipeline-01 Б-1). Мебель —
    room_catalog (показ, включённые роли, без детского в общих ролях), стиль — по семейству из `style-scores-bedroom.json`;
    декор — каталог гостиной (в наличии, фото живо, цена, есть `product_style_scores`). Признаки ламп по описанию товара
    (`lamp_task_desc` / `lamp_bed_desc` правил) — флагами из БД, сам текст не тянем. Поля словарей и их порядок — прежние
    (`load_catalog`/`load_decor` до T-20261105-39): банк до/после перевода побайтно равен; NULL текста — '' как раньше."""
    import catalog_items as CI
    return to_dicts(CI.items('bedroom', desc_flags={'task': rules.get('lamp_task_desc'), 'bed': rules.get('lamp_bed_desc')}))


def to_dicts(got: list) -> tuple:
    """CatalogItem спальни → (мебель, декор) — словари сборщика (их же берёт аудит покрытия `asset_coverage.py`).
    Признаков описания нет (адаптер без desc_flags) — False."""
    cat, decor = [], []
    for c in got:
        for role in c.roles:
            base = dict(role=role, mid=c.mid, eid=c.eid, name=c.name or '', shop=c.shop or '', price=int(c.price),
                        w=num(c.dims['w']), d=num(c.dims['d']), h=num(c.dims['h']))
            if c.origin == 'room_catalog':
                cat.append(dict(base, sleep_w=num(c.dims['sleep_w']), footprint_ok=c.dims['footprint_ok'] is True,
                                img=c.photo['best'] or '', url=c.url or '', fam=c.family, styles=c.style))
            else:
                decor.append(dict(base, img=c.photo['url'] or '', url=c.url or '', desc_task=c.flags.get('task', False),
                                  desc_bed=c.flags.get('bed', False), styles=c.style, fam=f"{c.shop or ''}|{c.name or ''}"))
    return cat, decor


# ---------------------------------------------------------------- сборка
class Composer:
    def __init__(self, cat: list, decor: list, ready: set, gen: set, rules: dict, tol: tuple, thr: float,
                 rejected: set = frozenset()):
        self.R, self.tol, self.thr = rules, tol, thr
        md = (rules.get('mesh_defect') or {}).get('names')
        defect = re.compile(md, re.I) if md else None
        for it in cat + decor:
            sku = f"{it['mid']}:{it['eid']}"
            it['sid'] = sku
            it['mesh'] = 'ready' if sku in ready else ('generated' if sku in gen else None)
            if it['mesh'] and (sku in rejected or (defect and defect.search(it.get('name') or ''))):
                it['mesh'], it['mesh_defect'] = None, True     # брак меша — как будто меша нет: в «нужен меш»
        self.cat, self.decor = cat, decor
        self.need_mesh: dict = {}
        self.shortage: dict = {}
        self.purpose = ''

    def pool(self, slot: dict, style: str, tier: str, source: list, extra=None) -> tuple:
        """(кандидаты слота в стиле и тире, полоса, тир ослаблен ли). Тир — квантили цены роли по всем годным в полосе
        (как гостиная); в стиле нет ни одного товара этой цены — квантили внутри стиля (`tier_relaxed` в записи:
        «премиум лофта» дешевле премиума современного, но тройка тиров в стиле есть). extra — доп. фильтр слота."""
        band = band_of(slot, self.tol)
        fit = [it for it in source if it['role'] == slot['role'] and gate(it, slot, band) is None
               and (extra is None or extra(it))]
        lo, hi = tier_range([it['price'] for it in fit], self.R['tiers'][tier])
        styled = [it for it in fit if it.get('styles') and (it['styles'].get(style) or 0) >= self.thr]
        k = (slot['role'], style, self.purpose)    # у назначений разный идеал слота — считаем раздельно
        self.shortage[k] = (len(styled), sum(1 for it in styled if it['mesh']))
        out = [it for it in styled if lo <= it['price'] <= hi]
        if out or not styled:
            return out, band, False
        lo, hi = tier_range([it['price'] for it in styled], self.R['tiers'][tier])
        return [it for it in styled if lo <= it['price'] <= hi], band, True

    def score(self, it: dict, style: str, ctx: dict) -> tuple:
        import compose_common as CC
        s = float(it['styles'][style])
        why = [f'стиль {s:g}']
        if it.get('cls'):
            pal = CC.palette_score(it['cls'], it.get('cls2'), CC.STYLE_PAIR[style], ctx.get('temp', 'mid'), it.get('rgb'))
            s += 0.5 * pal
            why.append(f'палитра{0.5 * pal:+.1f}')
        if it['mesh']:
            why.append('меш ' + ('готов' if it['mesh'] == 'ready' else 'сгенерирован'))
        return round(s, 3), '; '.join(why)

    def ranked(self, cands: list, style: str, ctx: dict) -> list:
        out = []
        for it in cands:
            sc, why = self.score(it, style, ctx)
            out.append(dict(it, score=sc, why=why, style_score=float(it['styles'][style]),
                            seen_style=it['fam'] in ctx.get('used_style', ()), seen_all=it['fam'] in ctx.get('used_all', ())))
        return sorted(out, key=rank_key)

    def build(self, room_id: str, purpose: str, style: str, tier: str, spec: dict, built: list, used: dict) -> dict:
        from planner.bedroom import solve_bedroom
        from planner.models import Item
        cfg = self.R['purposes'][purpose]
        self.purpose = purpose
        room = _room_model(spec, purpose.split(':')[0])
        slots, lists, bands, relaxed = {}, {}, {}, []
        for sl in cfg['slots']:
            cands, band, rx = self.pool(sl, style, tier, self.cat)
            if rx:
                relaxed.append(sl['role'])
            palette(cands)
            slots[sl['role']] = sl
            bands[sl['role']] = band
            lists[sl['role']] = cands
        if not lists['кровать']:
            return {'empty': 'NO_BED_IN_STYLE_TIER'}
        banned: set = set()
        ctx = {'temp': 'mid', 'used_style': used['style'], 'used_all': used['all']}
        for attempt in range(self.R['tries']['кровать'] + self.R['tries']['storage']):
            chosen, cur = {}, {}
            for role in [sl['role'] for sl in cfg['slots']]:
                rk = self.ranked([c for c in lists[role] if c['sid'] not in banned], style, ctx)
                pick = next((c for c in rk if diversity_ok(c['fam'], role, cur, built, style)), None)
                if pick is None:
                    continue
                chosen[role] = dict(pick, qty=slots[role].get('qty', 1))
                cur[role] = pick['fam']
                if role == 'кровать':
                    import compose_common as CC
                    ctx = dict(ctx, temp=CC.temperature(pick.get('rgb')))
            if 'кровать' not in chosen:
                return {'empty': 'NO_BED_DIVERSE'}
            items = []
            for role, it in chosen.items():
                for n in range(it['qty']):
                    items.append(Item(role=role if n == 0 else f'{role} {n + 1}', w_cm=it['w'], d_cm=it['d'], h_cm=it['h'],
                                      name=it['name'], item_id=it['sid']))
            lay = solve_bedroom(room, items, purpose.split(':')[0])
            placed = {p.role for p in lay.placements}
            if os.environ.get('BEDROOM_DEBUG'):
                print(f'    попытка {attempt + 1}: ' + ', '.join(f'{r} {c["sid"]} {c["w"]:g}×{c["d"]:g}' for r, c in chosen.items())
                      + f' → встали {sorted(placed)}; {lay.meta.get("reason")}; ' + ','.join(v.code for v in lay.violations),
                      flush=True)
            if 'кровать' not in placed:
                banned |= dominated(chosen['кровать'], lists['кровать'])
                continue
            storage = [r for r in chosen if slots[r].get('storage')]
            if storage and not any(r in placed for r in storage):
                for r in storage:
                    banned |= dominated(chosen[r], lists[r])
                continue
            wardrobe = None
            if 'шкаф' in slots and 'шкаф' not in placed:
                wardrobe = self.narrow_wardrobe(room, purpose, style, tier, slots['шкаф'], chosen, lay, built, ctx)
                if wardrobe.get('layout') is not None:
                    chosen['шкаф'], lay = wardrobe['item'], wardrobe['layout']
                    placed = {p.role for p in lay.placements}
                    lists['шкаф'], bands['шкаф'] = wardrobe['cands'], wardrobe['band']
                    slots['шкаф'] = wardrobe['slot']
                    relaxed = [r for r in relaxed if r != 'шкаф'] + (['шкаф'] if wardrobe['relaxed'] else [])
            for r in list(chosen):          # опциональное без места — не в наборе (и не в цене)
                if r not in placed:
                    chosen.pop(r)
            if 'тумба прикроватная' in chosen:
                chosen['тумба прикроватная']['qty'] = sum(1 for p in lay.placements if p.role.startswith('тумба прикроватная'))
            return {'chosen': chosen, 'layout': lay, 'room': room, 'lists': lists, 'bands': bands, 'slots': slots,
                    'attempts': attempt + 1, 'ctx': ctx, 'banned': sorted(banned),
                    'relaxed': [r for r in relaxed if r in chosen], 'wardrobe': wardrobe}
        return {'empty': 'NO_FIT_AFTER_TRIES', 'banned': sorted(banned)}

    def free_wall(self, room, base: list, slot: dict, purpose: str) -> tuple | None:
        """Шире какого шкафа эта комната при уже стоящих кровати и тумбах не примет → (Ш, Г) или None. Пробный шкаф
        идеальной глубины (и −20 %) сужаем шагом 5 см до 80 (меньше — не шкаф), пока солвер не поставит его, не сняв
        ни кровать, ни тумбу: шкаф важнее комода, но тумбы у кровати пары — норма (ведущий 05.11, T-31/2)."""
        from planner.bedroom import solve_bedroom
        from planner.models import Item
        need = {i.role for i in base}
        top = int(band_of(slot, self.tol)['w'][1] // 5 * 5)
        ih = slot['ideal']['h']
        for d in (slot['ideal']['d'], round(slot['ideal']['d'] * self.tol[0])):
            for w in range(top, WARDROBE_MIN_W - 1, -5):
                lay = solve_bedroom(room, base + [Item(role='шкаф', w_cm=w, d_cm=d, h_cm=ih)], purpose)
                pl = {p.role for p in lay.placements}
                if 'шкаф' in pl and need <= pl:
                    return w, d
        return None

    def narrow_wardrobe(self, room, purpose: str, style: str, tier: str, slot: dict, chosen: dict, lay, built: list,
                        ctx: dict) -> dict:
        """Шкаф с общим идеалом не встал (спальня 2, 13,2 м²: 13 из 15 пар без шкафа — канарейка 05.11). Идеал слота —
        от свободной стены ЭТОЙ комнаты, полоса 0,8–1,1 от него; кандидаты в стиле и тире (как обычно), не уже 80 см.
        Верх полосы — не шире стены и не глубже пробы. Ставим по порядку ранжирования; не встал — отсекаем и всё не меньше. Ни один ≥ 80 — {'layout': None, 'why'}:
        в наборе остаётся комод, пометка «без места: шкаф» честная."""
        from planner.bedroom import solve_bedroom
        from planner.models import Item
        p_ = purpose.split(':')[0]
        keep = [p for p in lay.placements if p.role.split(' ')[0] in ('кровать', 'тумба')]
        base = [Item(role=p.role, w_cm=p.item.w_cm, d_cm=p.item.d_cm, h_cm=p.item.h_cm, name=p.item.name,
                     item_id=p.item.item_id) for p in keep]
        fw = self.free_wall(room, base, slot, p_)
        if fw is None:
            return {'layout': None, 'why': f'свободной стены под шкаф ≥ {WARDROBE_MIN_W} см нет'}
        w, d = fw
        nslot = dict(slot, ideal=dict(slot['ideal'], w=w, d=d), free_wall_cm=w)
        k = ('шкаф', style, purpose)
        saved = self.shortage.get(k)              # нехватка в отчёте — по общему идеалу слота, не по узкому
        # верх полосы — сама стена: шире свободного места не встанет (лофт·комфорт 05.11: стена 130, полоса до 143,
        # все 4 кандидата 137 — ячейка пустела)
        cands, band, rx = self.pool(nslot, style, tier, self.cat,
                                    lambda it: WARDROBE_MIN_W <= (num(it.get('w')) or 0) <= w and (num(it.get('d')) or 0) <= d)
        band = dict(band, w=[band['w'][0], min(band['w'][1], w)], d=[band['d'][0], min(band['d'][1], d)])
        if saved is not None:
            self.shortage[k] = saved
        palette(cands)
        need = {p.role for p in keep}
        cur = {r: c['fam'] for r, c in chosen.items() if r != 'шкаф'}
        banned: set = set()
        tried = 0
        if os.environ.get('BEDROOM_DEBUG'):
            print(f'    узкий шкаф: стена {w}×{d}, полоса {band}, кандидаты '
                  + ', '.join(f'{c["sid"][-6:]} {c["w"]:g}×{c["d"]:g} {c["fam"][:30]} div={diversity_ok(c["fam"], "шкаф", cur, built, style)}'
                              for c in cands), flush=True)
        while tried < self.R['tries']['storage']:
            rk = self.ranked([c for c in cands if c['sid'] not in banned], style, ctx)
            pick = next((c for c in rk if diversity_ok(c['fam'], 'шкаф', cur, built, style)), None)
            if pick is None:
                break
            tried += 1
            items = base + [Item(role='шкаф', w_cm=pick['w'], d_cm=pick['d'], h_cm=pick['h'], name=pick['name'],
                                 item_id=pick['sid'])]
            if 'комод' in chosen:
                c = chosen['комод']
                items.append(Item(role='комод', w_cm=c['w'], d_cm=c['d'], h_cm=c['h'], name=c['name'], item_id=c['sid']))
            nl = solve_bedroom(room, items, p_)
            pl = {p.role for p in nl.placements}
            if os.environ.get('BEDROOM_DEBUG'):
                print(f'    узкий шкаф (стена {w}): {pick["sid"]} {pick["w"]:g}×{pick["d"]:g} → встали {sorted(pl)}', flush=True)
            if 'шкаф' in pl and need <= pl:
                return {'layout': nl, 'item': dict(pick, qty=1), 'cands': cands, 'band': band, 'slot': nslot,
                        'relaxed': rx, 'free_wall_cm': w, 'tried': tried}
            banned |= dominated(pick, cands)
        return {'layout': None, 'why': f'свободная стена {w} см, шкафов в стиле и полосе {len(cands)}, '
                                       f'не встал ни один из {tried}'}

    def decor_pick(self, purpose: str, style: str, tier: str, ctx: dict, lay, room, chosen: dict) -> tuple:
        cfg = self.R['purposes'][purpose].get('decor', {})
        self.purpose = purpose
        picks, alts, gaps, lay_extra, slots, relaxed = {}, {}, [], {}, {}, []
        windows = [o for o in room.openings if o.kind == 'window']
        for role, dc in cfg.items():
            if role.startswith('_'):
                continue
            sl = dict(dc, role=role, need_dims=(('w', 'd') if role == 'ковёр' else ('w', 'd', 'h')) if dc.get('band') else None)
            sl.setdefault('ideal', {})
            src = [it for it in self.decor if it['role'] == role]
            cands, band, rx = self.pool(sl, style, tier, self.decor, _decor_filter(dc, windows, self.R, src))
            if not cands:
                gaps.append(dc.get('gap') or (f'{role}: нет в стиле' + (' по размеру окна' if dc.get('min_w') == 'window' else '')))
                continue
            if dc.get('prefer'):
                pref = re.compile(dc['prefer'], re.I)
                for c in cands:
                    c['preferred'] = bool(pref.search(c.get('name') or '')) or bool(c.get('desc_bed'))
            if rx:
                relaxed.append(role)
            palette(cands)
            rk = self.ranked(cands, style, ctx)
            qty = 1
            if dc.get('qty_from') == 'windows':
                qty = max(1, len(windows))
            elif dc.get('qty_from'):
                qty = (chosen.get(dc['qty_from']) or {}).get('qty', 0)
                if not qty:
                    gaps.append(f'{role}: нет опоры ({dc["qty_from"]})')
                    continue
            pick = rk[0]
            if role == 'ковёр':
                place = rug_place(lay, room, pick)
                if place is None:
                    pick = next((c for c in rk[1:] if rug_place(lay, room, c)), None)
                    if pick is None:
                        gaps.append('ковёр: не лёг ни один (дверь/стены)')
                        continue
                    place = rug_place(lay, room, pick)
                lay_extra['ковёр'] = dict(place, sid=pick['sid'])
            picks[role] = dict(pick, qty=qty)
            alts[role] = [_alt(c) for c in rk if c['sid'] != pick['sid']][:self.R['alternates']]
            slots[role] = {'ideal': dc.get('ideal', {}), 'band': band, 'tolerance': list(self.tol), 'qty': qty,
                           'mesh': role in ('лампа',)}
        # лампы — на тумбах, плед — на кровати, шторы — на окнах (не пол: солвер их не ставит)
        stands = [p for p in lay.placements if p.role.startswith('тумба прикроватная')]
        if 'лампа' in picks:
            for n, p in enumerate(stands):
                lay_extra['лампа' if n == 0 else f'лампа {n + 1}'] = {
                    'x': p.x, 'z': p.y, 'rot': int(p.rot), 'w': picks['лампа']['w'], 'd': picks['лампа']['d'],
                    'h': picks['лампа']['h'], 'elev': p.item.h_cm, 'on': p.role, 'sid': picks['лампа']['sid']}
        if 'плед' in picks:
            lay_extra['плед'] = {'on': 'кровать', 'sid': picks['плед']['sid']}
        if 'шторы' in picks:
            lay_extra['шторы'] = {'windows': [{'wall': o.wall, 'offset_cm': o.offset_cm, 'width_cm': o.width_cm}
                                              for o in windows], 'sid': picks['шторы']['sid']}
        return picks, alts, gaps, lay_extra, slots, relaxed


MODEL_CODE = re.compile(r'\b([A-Z]{1,3}\d{4,6}[A-Z]{0,3})')


def model_code(name: str) -> str | None:
    """Артикул модели без цвета: «Arte Lamp A5126Lt-1Bk» → A5126LT (цвета одной модели — одна вещь)."""
    m = MODEL_CODE.search((name or '').upper())
    return m.group(1) if m else None


def _decor_filter(dc: dict, windows: list, rules: dict | None = None, source: list = ()):
    """Доп. фильтр декора из правил: `deny` — по названию (рулонные шторы не закрывают окно 2,4 м; `@ключ` — регэксп из
    корня правил), `deny_model` — и братья по артикулу отсеянного, `min_w: window` — ширина не меньше самого широкого
    окна комнаты (полотно 300 на окно 240; 55 см — нет)."""
    pat = dc.get('deny')
    if pat and pat.startswith('@'):
        pat = (rules or {}).get(pat[1:])
    deny = re.compile(pat, re.I) if pat else None
    task = (lambda it: bool(deny and deny.search(it.get('name') or '')) or bool(it.get('desc_task'))) \
        if dc.get('deny_model') else (lambda it: False)
    codes = ({model_code(it.get('name')) for it in source if task(it)} | set((rules or {}).get('lamp_task_models') or ())) - {None} \
        if dc.get('deny_model') else set()
    wmin = max((o.width_cm for o in windows), default=0) if dc.get('min_w') == 'window' else 0

    def ok(it):
        if deny and deny.search(it.get('name') or ''):
            return False
        if dc.get('deny_model') and (it.get('desc_task') or model_code(it.get('name')) in codes):
            return False   # рабочая по описанию, по фото (lamp_task_models) или брат по артикулу рабочей
        return not wmin or (num(it.get('w')) or 0) >= wmin
    return ok if (deny or wmin) else None


def rug_place(lay, room, rug: dict) -> dict | None:
    """Ковёр поперёк кровати под её нижние 2/3; внутри комнаты и не под дугой двери (иначе дверь цепляет). None — не лёг."""
    sys.path.insert(0, SOLVER)
    from shapely.geometry import Polygon
    from planner.geometry import room_polygon, swing_polygon
    bed = next((p for p in lay.placements if p.role == 'кровать'), None)
    if bed is None or not (rug.get('w') and rug.get('d')):
        return None
    L, S = max(rug['w'], rug['d']), min(rug['w'], rug['d'])
    poly = room_polygon(room)
    swings = [swing_polygon(room, o) for o in room.openings if o.kind == 'door']
    bd = bed.item.d_cm
    for k in range(0, 8):
        cy = -bd / 2 + bd / 3 + S / 2 - 10 * k
        pts = [local_to_world(bed.x, bed.y, bed.rot, sx * L / 2, cy + sy * S / 2) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        g = Polygon(pts)
        if g.difference(poly).area > 1.0 or any(not s.is_empty and g.intersects(s.buffer(-1.0)) for s in swings):
            continue
        x, z = local_to_world(bed.x, bed.y, bed.rot, 0, cy)
        return {'x': x, 'z': z, 'rot': int(bed.rot), 'w': L, 'd': S, 'h': rug.get('h') or 1}
    return None


def _alt(c: dict) -> dict:
    return dict({k: c.get(k) for k in ('mid', 'eid', 'sid', 'name', 'price', 'score', 'w', 'd', 'h', 'img', 'url', 'mesh',
                                       'style_score')}, has_mesh=bool(c.get('mesh')), mesh_defect=bool(c.get('mesh_defect')))


def _item(c: dict) -> dict:
    keep = ('mid', 'eid', 'sid', 'name', 'price', 'w', 'd', 'h', 'shop', 'img', 'url', 'qty', 'why', 'score', 'style_score',
            'mesh', 'cls', 'cls2', 'rgb', 'sleep_w', 'fam')
    # «меш есть/нет» на позицию (ведущий 05.11): по нему Работник 2 строит 3D, нет — список заказа мешей T-35
    return dict({k: c.get(k) for k in keep if k in c}, has_mesh=bool(c.get('mesh')), mesh_defect=bool(c.get('mesh_defect')))


def record(C: Composer, room_id: str, spec: dict, purpose: str, style: str, tier: str, res: dict, dec: tuple) -> dict:
    import compose_common as CC
    chosen, lay = res["chosen"], res["layout"]
    picks, alts_d, gaps, lay_extra, dslots, relaxed_d = dec
    items = {r: _item(c) for r, c in chosen.items()}
    items.update({r: _item(c) for r, c in picks.items()})
    alts = {r: [_alt(c) for c in C.ranked([x for x in res['lists'][r] if x['sid'] != chosen[r]['sid']], style, res['ctx'])
                ][:C.R['alternates']] for r in chosen}
    alts.update(alts_d)
    slots = {r: dict({'ideal': res['slots'][r]['ideal'], 'band': res['bands'][r], 'tolerance': list(C.tol),
                      'qty': chosen[r]['qty'], 'mesh': True},
                     **({'free_wall_cm': res['slots'][r]['free_wall_cm']} if 'free_wall_cm' in res['slots'][r] else {}))
             for r in chosen}
    slots.update(dslots)
    layout = {p.role: {'x': p.x, 'z': p.y, 'rot': int(p.rot), 'w': p.item.w_cm, 'd': p.item.d_cm, 'h': p.item.h_cm,
                       'sid': p.item.item_id} for p in lay.placements}
    layout.update(lay_extra)
    layout['_room'] = {'variant': spec['variant'], 'w': spec['w'], 'd': spec['d'],
                       'openings': [{k: v for k, v in o.items() if not k.startswith('_')} for o in spec.get('openings', [])],
                       'radiators': [{k: v for k, v in r.items() if not k.startswith('_')} for r in spec.get('radiators', [])]}
    layout['_meta'] = {'solver': lay.meta.get('solver'), 'template': lay.meta.get('template'), 'reason': lay.meta.get('reason'),
                       'soft': sorted({v.code for v in lay.violations}), 'skipped_optional': lay.skipped_optional,
                       'floor_used_pct': lay.floor_used_pct, 'attempts': res['attempts']}
    wd = res.get('wardrobe')
    if wd:      # шкаф не встал с общим идеалом: узкий по свободной стене или честное «без места»
        layout['_meta']['wardrobe'] = ({'narrow': True, 'free_wall_cm': wd['free_wall_cm'], 'tried': wd['tried']}
                                       if wd.get('layout') is not None else {'narrow': False, 'why': wd['why']})
    m2 = round(spec['w'] * spec['d'] / 10000, 1)
    rec = {'room_id': room_id, 'room_type': 'bedroom', 'purpose': purpose, 'band': cell_band(spec), 'm2': m2, 'tier': tier,
           'style': style, 'style_fit': set_fit(items, style), 'pair': list(CC.STYLE_PAIR[style]), 'gaps': gaps,
           'total': sum((it.get('price') or 0) * (it.get('qty') or 1) for it in items.values()),
           'items': items, 'alternates': alts, 'slots': slots, 'layout': layout,
           'tier_relaxed': sorted(res.get('relaxed', []) + relaxed_d),
           'mesh_need': sorted(it['sid'] for r, it in items.items() if r in FLOOR + ('лампа',) and not it.get('mesh'))}
    rec['cell'] = '|'.join([room_id, purpose, rec['band'], style, tier])
    rec['set_id'] = set_id(room_id, purpose, rec['band'], style, tier)
    if getattr(C, 'prov', None):     # происхождение (этап В): профиль, версия, content_sha, плагин, дайджест правил и кода
        rec['provenance'] = dict(C.prov)
    return rec


def compose(rooms: list, C: Composer) -> tuple:
    bank, report = [], {'cells': [], 'shortage': {}}
    for room_id in rooms:
        rc = C.R['rooms'][room_id]
        spec = room_spec(room_id, rc['variant'])
        for purpose in rc['purposes']:
            pc = C.R['purposes'][purpose]
            if pc.get('empty'):
                report['cells'].append({'room_id': room_id, 'purpose': purpose, 'empty': pc['empty'], 'why': pc.get('_why')})
                continue
            built: list = []
            used_all: set = set()
            for style in C.R['styles']:
                used = {'style': set(), 'all': used_all}
                for tier in C.R['tiers']:
                    res = C.build(room_id, purpose, style, tier, spec, built, used)
                    cell = {'room_id': room_id, 'purpose': purpose, 'style': style, 'tier': tier}
                    if 'empty' in res:
                        report['cells'].append(dict(cell, empty=res['empty']))
                        print(f'  {room_id} {purpose} {style} {tier}: ПУСТО — {res["empty"]}', flush=True)
                        continue
                    ctx = dict(res['ctx'], used_style=used['style'], used_all=used_all)
                    dec = C.decor_pick(purpose, style, tier, ctx, res['layout'], res['room'], res['chosen'])
                    rec = record(C, room_id, spec, purpose, style, tier, res, dec)
                    bank.append(rec)
                    built.append((style, {r: res['chosen'][r]['fam'] for r in res['chosen'] if r in MAJOR}))
                    fams = {c['fam'] for c in list(res['chosen'].values()) + list(dec[0].values())}
                    used['style'] |= fams
                    used_all |= fams
                    report['cells'].append(dict(cell, set_id=rec['set_id'], total=rec['total'], fit=rec['style_fit'],
                                                mesh_need=len(rec['mesh_need']), gaps=rec['gaps'],
                                                skipped=rec['layout']['_meta']['skipped_optional'],
                                                wardrobe=rec['layout']['_meta'].get('wardrobe')))
                    print(f"  {room_id} {purpose} {style} {tier}: {rec['set_id']} {rec['total']:,} ₽ фит {rec['style_fit']} "
                          f"меш нужен {len(rec['mesh_need'])} пробелы {rec['gaps']} без места {rec['layout']['_meta']['skipped_optional']}",
                          flush=True)
    wd = [c for c in report['cells'] if c.get('wardrobe')]
    report['wardrobe'] = {'narrow': sum(1 for c in wd if c['wardrobe'].get('narrow')),
                          'no_room': [dict(cell=f"{c['room_id']}|{c['purpose']}|{c['style']}|{c['tier']}", why=c['wardrobe']['why'])
                                      for c in wd if not c['wardrobe'].get('narrow')]}
    report['shortage'] = {f'{r} × {s} · {p}': {'кандидатов': n, 'с мешом': m}
                          for (r, s, p), (n, m) in sorted(C.shortage.items())}
    return bank, report


SPARE_MIN = 3                  # запас замен у роли набора (onb-06): меньше — у мебели нарушение, у декора предупреждение
SPARE_MODES = ('hard', 'warn')


def spare_short(s: dict) -> list[tuple[str, int, bool]]:
    """Роли набора с запасом замен меньше `SPARE_MIN` → [(роль, сколько замен, мебель ли)] в порядке предметов."""
    alts = s.get('alternates') or {}
    return [(r, len(alts.get(r, [])), r in MAJOR) for r in s['items'] if len(alts.get(r, [])) < SPARE_MIN]


def check_bank(bank: list, R: dict, tol: tuple, spare: str = 'hard') -> list:
    """Критерии плана onb-06 по готовому банку → список нарушений (пусто — чисто). Раскладку перепроверяет `validate`
    (диспетчер по room_type): жёстких 0. `spare` — нехватка запаса замен у мебели: 'hard' — нарушение (ночная замена,
    этап Г), 'warn' — предупреждение `~` (поколение 0: набор полный, не хватает лишь запаса — `room_bootstrap`, T-70/2)."""
    if spare not in SPARE_MODES:
        raise ValueError(f'spare={spare!r}? можно {", ".join(SPARE_MODES)}')
    sys.path.insert(0, SOLVER)
    from planner.models import Item, Placement, Severity
    from planner.validate import validate
    bad = []
    by_group: dict = {}
    for s in bank:
        sid = s.get('set_id')
        for k in ('room_id', 'room_type', 'purpose', 'style', 'tier', 'layout', 'slots', 'cell'):
            if not s.get(k):
                bad.append(f'{sid}: нет {k}')
        it = s['items']
        if 'кровать' not in it or not any(r in it for r in ('шкаф', 'комод')):
            bad.append(f'{sid}: ядро неполное (кровать + шкаф/комод)')
        slot_cfg = {sl['role']: sl for sl in R['purposes'][s['purpose']]['slots']}
        short = {r: (n, major) for r, n, major in spare_short(s)}
        for r, x in it.items():
            if r in MAJOR:      # полоса — из записи: у узкого шкафа она от свободной стены комнаты, не общая
                sc = dict(slot_cfg[r], ideal=s['slots'][r]['ideal'])
                g = gate(dict(x, role=r, footprint_ok=True), sc, s['slots'][r]['band'])
                if g:
                    bad.append(f'{sid}: {r} {x["sid"]} — {g}')
            if r in short:      # декор тоньше мебели — предупреждение (`~`), не нарушение
                n, major = short[r]
                bad.append(('' if major and spare == 'hard' else '~ ') + f'{sid}: {r} — альтернатив {n} < {SPARE_MIN}')
        if s['purpose'] == 'couple' and (it.get('тумба прикроватная') or {}).get('qty') != 2:
            bad.append(f'{sid}: пара без двух тумб')
        lay = s['layout']
        rm = lay['_room']
        room = _room_model(rm, s['purpose'])
        pls = [Placement(role=r, x=p['x'], y=p['z'], rot=p['rot'], item=Item(role=r, w_cm=p['w'], d_cm=p['d'], h_cm=p['h']))
               for r, p in lay.items() if not r.startswith('_') and r.split(' ')[0] in ('кровать', 'тумба', 'шкаф', 'комод')]
        hard = [v.code for v in validate(room, pls).violations if v.severity is Severity.HARD]
        if hard:
            bad.append(f'{sid}: жёсткие нарушения раскладки {hard}')
        by_group.setdefault((s['room_id'], s['purpose']), []).append(s)
    fam = lambda x: x.get('fam') or x['sid']   # noqa: E731
    for g, sets in by_group.items():
        pairs = {}
        for i, a in enumerate(sets):
            ma = {fam(a['items'][r]) for r in MAJOR if r in a['items']}
            pr = (fam(a['items']['кровать']), fam(a['items']['шкаф'])) if 'шкаф' in a['items'] else None
            if pr and pr in pairs:
                bad.append(f'{a["set_id"]}: связка кровать+шкаф повторяет {pairs[pr]}')
            if pr:
                pairs[pr] = a['set_id']
            for b in sets[i + 1:]:
                if a['style'] != b['style']:
                    mb = {fam(b['items'][r]) for r in MAJOR if r in b['items']}
                    if len(ma & mb) > 1:
                        bad.append(f'{a["set_id"]}↔{b["set_id"]}: общих крупных {len(ma & mb)} > 1')
    return bad


def _check_text(bank: list, problems: list) -> str:
    hard = [p for p in problems if not p.startswith('~')]
    warn = [p[2:] for p in problems if p.startswith('~')]
    return (f'ПРОВЕРКА банка: наборов {len(bank)}, нарушений {len(hard)}, предупреждений по декору {len(warn)}'
            + ''.join(f'\n  ✗ {p}' for p in hard) + ''.join(f'\n  ~ {p}' for p in warn))


def main(argv: list) -> int:
    sys.path.insert(0, SOLVER)
    sys.path.insert(0, HERE)
    import bank_paths as BP
    R = rules()
    tol = tolerance()
    thr = float(PROFILE['style']['in_style_min'])
    rooms = argv[argv.index('--rooms') + 1].split(',') if '--rooms' in argv else list(R['rooms'])
    if '--nightly' in argv:     # флаг ADR-0330 п.5: ночь собирает только включённые комнаты
        on = {r['id'] for r in load_json(FLAT)['rooms'] if r.get('enabled')}
        rooms = [r for r in rooms if r in on]
        if not rooms:
            print('compose_bedroom: ни одна спальня не включена (enabled=false) — ночной шаг пропущен')
            return 0
    out = BP.room_bank_output(os.environ, 'bedroom')
    print(f'Каталог спальни, декор, меши... порог стиля {thr}, полоса {tol}', flush=True)
    import catalog_items as CI
    cat, decor = load_items(R)
    ready, gen, rejected = CI.mesh_state()
    C = Composer(cat, decor, ready, gen, R, tol, thr, rejected)
    import room_identity as RI
    C.prov = RI.provenance('bedroom')
    print(f'мебели {len(cat)}, декора {len(decor)}, мешей готово {len(ready)} / сгенерировано {len(gen)}', flush=True)
    bank, report = compose(rooms, C)
    json.dump(bank, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    rp = os.path.splitext(out)[0] + '.report.json'
    need: dict = {}
    for s in bank:
        for r, it in s['items'].items():
            if it['sid'] in s['mesh_need']:
                need.setdefault(it['sid'], {'role': r, 'name': it['name'], 'sets': 0, 'w': it['w'], 'd': it['d'], 'h': it['h']})
                need[it['sid']]['sets'] += 1
    report['mesh_need'] = sorted(need.items(), key=lambda kv: (-kv[1]['sets'], kv[0]))
    json.dump(report, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'БАНК: {out} — наборов {len(bank)}; отчёт {rp}; нужен меш: {len(need)} товаров', flush=True)
    problems = check_bank(bank, R, tol)
    print(_check_text(bank, problems), flush=True)
    ident = RI.check(bank, cells(R), C.prov)    # матрица профиля и id (этап В): кандидат с отказом банк не примет
    print(f'ИДЕНТИЧНОСТЬ кандидата: ячеек {len(bank)} из {len(cells(R))}, отказов {len(ident)}'
          + ''.join(f'\n  ✗ {x}' for x in ident), flush=True)
    if '--sheet' in argv:
        import bedroom_sheet
        print('лист:', bedroom_sheet.write(bank, report, argv[argv.index('--sheet') + 1]))
    return 0


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    R = rules()
    tol = (0.8, 1.1)
    bed = R['purposes']['couple']['slots'][0]
    b = band_of(bed, tol)
    ok('полоса кровати пары: 140–192,5 по ширине, 172–236,5 по глубине', b == {'w': [140.0, 192.5], 'd': [172.0, 236.5]})
    good = {'role': 'кровать', 'w': 176, 'd': 214, 'h': 100, 'footprint_ok': True, 'sleep_w': 160}
    ok('кровать 160 в полосе — годна', gate(good, bed, b) is None)
    _R = rules()
    _lamps = [{'name': n} for n in ('Офисная настольная лампа Arte Lamp EDWARD A5126LT-1WH', 'Светильник настольный Arte Lamp A5126Lt-1Bk',
                                     'Светильник настольный Xiaomi Yeelight J1 YLTD10YL', 'Светильник настольный Gauss Qplus GT6011 белый диммируемый',
                                     'Светильник настольный Gauss Qplus GTL502 8W 500lm 3500-5500K 170-265V',
                                     'Декоративная настольная лампа Arte Lamp PADOVA A2404LT-1AM', 'Светильник Glasar с абажуром 36х30х59 см',
                                     'Лампа настольная Citilux CL306831 Джейн')] + [
        {'name': 'Светильник настольный Arte Lamp A5122LT-1BK', 'desc_task': True}, {'name': 'Настольная лампа Arte Lamp Cord A1210LT-1BK'}]
    _f = _decor_filter(_R['purposes']['couple']['decor']['лампа'], [], _R, _lamps)
    ok('лампы: рабочие (офисная, её брат по артикулу A5126LT, Yeelight, диммируемая LED, люмены, «рабочая» по описанию, '
       'прищепка Cord по фото) — нет; декоративные — да',
       [_f(x) for x in _lamps] == [False, False, False, False, False, True, True, True, False, False])
    ok('артикул без цвета: A5126Lt-1Bk → A5126LT; цоколь E27 — не артикул',
       model_code('Arte Lamp A5126Lt-1Bk') == 'A5126LT' and model_code('Лампа 1хE27 60 Вт') is None)
    sys.path.insert(0, SOLVER)
    from planner.models import Item as _It
    _C = Composer([], [], set(), set(), _R, (0.8, 1.1), 6.6)
    _room2 = _room_model(room_spec('bedroom-2', 'drawing-180'), 'couple')
    _base = [_It(role='кровать', w_cm=175, d_cm=213, h_cm=110), _It(role='тумба прикроватная', w_cm=45, d_cm=40, h_cm=55),
             _It(role='тумба прикроватная 2', w_cm=45, d_cm=40, h_cm=55)]
    _shk = next(x for x in _R['purposes']['couple']['slots'] if x['role'] == 'шкаф')
    ok('спальня 2 (450×293), кровать 175×213 + 2 тумбы: свободная стена под шкаф 110 см (общий идеал 150 не встаёт)',
       _C.free_wall(_room2, _base, _shk, 'couple') == (110, 60))
    _cat = [{'mid': 1, 'eid': 'a', 'name': 'Кровать divan.ru Стелла 160'}, {'mid': 1, 'eid': 'b', 'name': 'Кровать Рио 160'},
            {'mid': 1, 'eid': 'c', 'name': 'Тумба Норд'}, {'mid': 1, 'eid': 'd', 'name': 'Комод Лайт'}]
    Composer(_cat, [], {'1:b'}, {'1:a', '1:c', '1:d'}, {'mesh_defect': {'names': 'Стелла'}}, (0.8, 1.1), 6.6, {'1:d'})
    ok('брак меша (имя из правил, owner_reject) — меша нет и в «нужен меш»; годный — есть',
       [(c['mesh'], bool(c.get('mesh_defect'))) for c in _cat]
       == [(None, True), ('ready', False), ('generated', False), (None, True)])
    _c = [{'sid': 'a', 'w': 180, 'd': 230}, {'sid': 'b', 'w': 175, 'd': 213}, {'sid': 'c', 'w': 190, 'd': 225}]
    ok('не встала 180×225 — отсекаем и всё не меньше (180×230, 190×225), меньшую 175×213 — нет',
       dominated({'sid': 'x', 'w': 180, 'd': 225}, _c) == {'x', 'a', 'c'})
    ok('без высоты — не ставим (нет Ш×Г×В)', gate(dict(good, h=None), bed, b) == 'нет Ш×Г×В')
    ok('спальное 140 — не пара', 'спальное' in (gate(dict(good, sleep_w=140), bed, b) or ''))
    ok('габарит не сверен — нельзя', gate(dict(good, footprint_ok=False), bed, b) == 'габарит не сверен')
    ok('ширина 200 (+14 %) — вне полосы', 'вне полосы' in (gate(dict(good, w=200), bed, b) or ''))
    rug = {'role': 'ковёр', 'ideal': {'long': 300}, 'band': ['long']}
    ok('ковёр меряется длинной стороной', gate({'role': 'ковёр', 'w': 200, 'd': 300}, rug, band_of(rug, tol)) is None
       and gate({'role': 'ковёр', 'w': 160, 'd': 230}, rug, band_of(rug, tol)) is not None)
    ok('шторы без полосы — размеры не нужны', gate({'role': 'шторы'}, {'role': 'шторы'}, {}) is None)
    ok('тир: квантили цены', tier_range(list(range(100)), (0.05, 0.45)) == (5, 45))
    a = {'mid': 1, 'eid': 'a', 'score': 5.0, 'price': 10, 'mesh': None}
    m = {'mid': 2, 'eid': 'b', 'score': 3.0, 'price': 20, 'mesh': 'generated'}
    r_ = {'mid': 3, 'eid': 'c', 'score': 1.0, 'price': 30, 'mesh': 'ready'}
    ok('порядок: готовый меш → сгенерированный → без меша, потом балл', sorted([a, m, r_], key=rank_key) == [r_, m, a])
    ok('ничья балла — цена, потом SKU', sorted([dict(a, mid=9, price=5), a], key=rank_key)[0]['mid'] == 9)
    ok('уже стоит в этом стиле — после всех, даже с готовым мешом', sorted([dict(r_, seen_style=True), a], key=rank_key)[0] is a)
    ok('стоит в другом стиле — меш важнее', sorted([dict(r_, seen_all=True), a], key=rank_key)[0]['mid'] == 3
       and sorted([dict(a, seen_all=True), dict(a, mid=8)], key=rank_key)[0]['mid'] == 8)
    from types import SimpleNamespace as NS
    f = _decor_filter({'min_w': 'window', 'deny': 'рулон'}, [NS(width_cm=210), NS(width_cm=240)])
    ok('шторы: не уже окна 240 и не рулонные', f({'name': 'Тюль', 'w': 300}) and not f({'name': 'Тюль', 'w': 200})
       and not f({'name': 'Рулонная штора', 'w': 300}) and _decor_filter({}, []) is None)
    built = [('сканди', {'кровать': 'B1', 'шкаф': 'W1', 'комод': 'K1'})]
    ok('другой стиль: одна общая модель — можно', diversity_ok('B1', 'кровать', {}, built, 'лофт'))
    ok('другой стиль: вторая общая — нельзя', not diversity_ok('W1', 'шкаф', {'кровать': 'B1'}, built, 'лофт'))
    ok('связка кровать+шкаф не повторяется и в том же стиле', not diversity_ok('W1', 'шкаф', {'кровать': 'B1'}, built, 'сканди'))
    ok('тот же стиль, другой шкаф — можно', diversity_ok('W2', 'шкаф', {'кровать': 'B1'}, built, 'сканди'))
    ok('декор разнообразием не ограничен', diversity_ok('W1', 'лампа', {'кровать': 'B1', 'шкаф': 'W1'}, built, 'лофт'))
    ok('стиль набора — средневзвешенный крупного', set_fit({'кровать': {'style_score': 8}, 'шкаф': {'style_score': 6},
                                                            'лампа': {'style_score': 1}}, 'x') == round((8 + 0.85 * 6) / 1.85, 1))
    ok('оси предмета → комната: rot 0 — изножье к +y', local_to_world(100, 100, 0, 0, 50) == (100, 150))
    ok('rot 180 — изножье к −y', local_to_world(100, 100, 180, 0, 50) == (100, 50))
    ok('rot 90 — изножье к +x (как тумбы солвера)', local_to_world(100, 100, 90, 0, 50) == (150, 100))
    ok('id набора — от ячейки, не от состава (этап В)', set_id('r', 'p', '10.6', 's', 't') == set_id('r', 'p', '10.6', 's', 't')
       != set_id('r', 'p', '10.6', 's', 'u') and set_id('r', 'p', '10.6', 's', 't').startswith('bed-'))
    ok('матрица профиля: 60 ячеек (спальня 1 — пара, спальня 2 — пара, один, гость; × 5 стилей × 3 тира)',
       len(cells(R)) == 60 and cells(R)[0][:3] == ('bedroom-1', 'couple', cell_band(room_spec('bedroom-1', R['rooms']['bedroom-1']['variant']))))
    ok('пустые назначения объявлены с причиной', all(R['purposes'][p].get('empty') for p in
                                                     ('office', 'child:0-3', 'child:3-7', 'child:7-12', 'child:teen')))
    ok('спальня 2 — все назначения словаря ADR-0330', set(R['rooms']['bedroom-2']['purposes']) ==
       {'couple', 'single', 'guest', 'office', 'child:0-3', 'child:3-7', 'child:7-12', 'child:teen'})
    # ковёр под кроватью — на геометрии спальни 1 (солвер, без базы)
    sys.path.insert(0, SOLVER)
    from planner.bedroom import solve_bedroom
    from planner.models import Item
    spec = room_spec('bedroom-1', R['rooms']['bedroom-1']['variant'])
    room = _room_model(spec, 'couple')
    lay = solve_bedroom(room, [Item(role='кровать', w_cm=176, d_cm=214, h_cm=100)])
    pl = rug_place(lay, room, {'w': 300, 'd': 200})
    ok('ковёр 200×300 лёг под кровать спальни 1', pl is not None and pl['w'] == 300 and pl['rot'] == int(lay.placements[0].rot))
    ok('ковёр шире комнаты не лёг', rug_place(lay, room, {'w': 700, 'd': 200}) is None)
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
