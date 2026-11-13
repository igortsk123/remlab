#!/usr/bin/env python3
"""КАТАЛОГ ШАБЛОНОВ СПАЛЬНИ НА РЕАЛЬНЫХ КОМНАТАХ — листы в масштабе для показа владельцу (T-20261112-120, план
`.memory_bank/plans/bedroom-templates-catalog-01.md`; паспорт ТЕНЬЮ `services/planner-solver/rules/room-templates/bedroom-catalog.json`,
исследование `.memory_bank/_intake/codex/2026-11-12-bedroom-templates-answer.md`).

Эскиз, НЕ солвер (движок спальни этот паспорт пока не читает): для каждой комнаты и назначения берёт ВСЕ шаблоны каталога, чьи
`purpose` и `when` подходят, и перебирает их так, как движок будет после «ок» (Codex §4): шаблон → уровень A…(богатый → минимальный)
→ лестница кровати (`bed_width_ladder`) → стены × сдвиги; проходы сперва по цели, потом в допуске compact (`planner/passage_norms.py`).
Победитель среди шаблонов — по ключу «без нарушений и с обязательными группами → по цели раньше compact → уровень → полнота хранения
(фронт / target) → кровать → специфичность (порог площади) → priority → мягкий счёт» (Codex 13.11 п.3,
`_intake/codex/2026-11-13-t120-bedroom-catalog-answer.md`); ни один не встал — NO_ROOM_TEMPLATE_FITS и кандидат в новый шаблон.
head_wall (`off_corner` + `bed_side_gaps_open`): изголовье на глухом участке, оба боковых зазора открыты; twin_apart — две кровати
в разных углах у разных стен; игровая зона — гипотеза `play_zone` (150 → 120, мягко); зеркало и пуф ставятся; условные габариты —
`bedroom_catalog.conditional_cm` в правилах. Итог «встало X из Y» по полному паспорту — в начале matrix.md.
Геометрия, проверки и рисунок — `bedroom_schemes.py` импортом (масштаб, сетка 50 см, зоны проходов, дуга двери, путь от двери,
красная штриховка нарушения); поверх — места зависимых по паспорту: шторы, общий свет, лампы/бра, ковёр, плед, картина, декор.
Товары — реальные рамы банка `sets-bedroom.json`; ролей, которых в банке нет (кроватка, стол, туалетный столик, стеллаж, диван-кровать,
кресло, банкетка), — пунктиром «условно».

  python bedroom_catalog_schemes.py OUT_DIR [SCENES_DIR] [--jobs N] [--rooms id1,id2]
    SCENES_DIR — папка сцен туров (`<trial>/bedrooms.json` с коробкой `core`), без неё — только демо и UK-комнаты.
    → OUT_DIR/sheet-N.png, OUT_DIR/<панель>.png, matrix.md, results.json

Только чтение банка и правил; солвер не вызывается.
"""
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'services' / 'planner-solver'))
sys.path.insert(0, str(HERE))
import bedroom_schemes as bs  # noqa: E402
from planner import passage_norms as PN  # noqa: E402
from planner import room_templates as RT  # noqa: E402

CAT = RT.load('bedroom-catalog')
BC = RT._distances()['bedroom_catalog']
EPS = bs.EPS
PURPOSES = ['couple', 'single', 'single_narrow', 'guest', 'office', 'twin', 'child:0-3', 'child:3-7', 'child:7-12', 'child:teen']
PURPOSE_RU = {'couple': 'пара', 'single': 'один взрослый', 'single_narrow': 'UK single (узкая)', 'guest': 'гостевая',
              'office': 'кабинет-гостевая', 'twin': 'двое (две кровати)', 'child:0-3': 'детская 0–3', 'child:3-7': 'детская 3–7',
              'child:7-12': 'детская 7–12', 'child:teen': 'подросток'}
WORK_PURPOSES = {'office', 'child:7-12', 'child:teen'}
BED_SKU = {180: 'bed_couple_wide', 160: 'bed_couple', 140: 'bed_guest', 120: 'bed_single', 90: 'bed_narrow'}
COND_RU = {'cot': 'Кроватка 60×120', 'child80': 'Детская 80×160', 'dressing': 'Туалетный столик', 'pouf': 'Пуф', 'shelf': 'Стеллаж',
           'sofabed': 'Диван-кровать', 'armchair': 'Кресло', 'bench': 'Банкетка', 'mirror': 'Зеркало в рост'}
# роли, которых в банке спальни нет — условные размеры из правил (`bedroom_catalog.conditional_cm`), пунктир на листе
COND2 = {k: {'name': f"{COND_RU.get(k, k)} — НЕТ В БАНКЕ (условно {v['w']}×{v['d']})", 'w': float(v['w']), 'd': float(v['d']), 'h': float(v['h'])}
         for k, v in BC['conditional_cm'].items() if not k.startswith('_')}
SOFABED_OPEN = float(RT.rule_value('distances_cm.bedroom_catalog.sofabed_open'))   # раскладка дивана-кровати вперёд (условно)
PLAY = BC['play_zone']                                                                # игровая зона — гипотеза, мягко
GAP_OPEN = float(RT.rule_value('distances_cm.bedroom_catalog.head_wall_side_gap_min'))
WALKIN_NOTE = 'хранение в нише (шкаф-купе/гардеробная — по глубине ниши)'
MODE_RU = {'target': 'цель', 'compact': 'compact'}
# новые виды предметов — цвета и подписи рисунка `bedroom_schemes.render`
bs.ITEM_COL.update({'shelf': (176, 190, 197), 'dressing': (248, 187, 208), 'sofabed': (197, 225, 165), 'armchair': (255, 205, 210),
                    'bench': (215, 204, 200), 'walkin': (120, 144, 156), 'pouf': (240, 98, 146), 'mirror': (129, 212, 250)})
bs.ITEM_RU.update({'shelf': 'Стеллаж', 'dressing': 'Туал. столик', 'sofabed': 'Диван-кровать', 'armchair': 'Кресло',
                   'bench': 'Банкетка', 'walkin': 'Ниша-хранение', 'pouf': 'Пуф', 'mirror': 'Зеркало'})
bs.ITEM_SHORT.update({'shelf': 'Сл', 'dressing': 'ТС', 'sofabed': 'ДК', 'armchair': 'Кр', 'bench': 'Б', 'walkin': 'Н', 'pouf': 'П',
                      'mirror': 'З'})
bs.ZONE_COL.update({'SHELF_FRONT': (142, 36, 170, 40), 'SOFABED_OPEN': (124, 179, 66, 50), 'BENCH_FRONT': (67, 160, 71, 45),
                    'DRESSING_SEAT': (236, 64, 122, 50), 'MIRROR_FRONT': (3, 155, 229, 35)})


# ---------------------------------------------------------------- нормы проходов по режиму (как движок: target | compact)
def set_norm(mode):
    with PN.using(mode):
        bs.SIDE, bs.FOOT = PN.clearance('bed_side_couple'), PN.clearance('bed_foot_route')
        bs.WARD = PN.clearance('wardrobe_hinged_front')
        bs.DRESS = max(PN.clearance('dresser_front'), PN.drawer_reach_unknown())
        bs.ROUTE = PN.clearance('route_door_window')
    bs.CODE_RU.update({'BED_SIDE_PASSAGE': f'нет прохода {bs.SIDE:.0f} у бока кровати', 'BED_FOOT_PASSAGE': f'нет {bs.FOOT:.0f} у изножья',
                       'WARDROBE_FRONT': f'нет {bs.WARD:.0f} перед шкафом', 'DRESSER_FRONT': f'нет {bs.DRESS:.0f} перед комодом',
                       'ROUTE_BED': f'нет пути {bs.ROUTE:.0f} от двери к кровати', 'ROUTE_WINDOW': f'нет пути {bs.ROUTE:.0f} от двери к окну',
                       'ROUTE_DESK': f'нет пути {bs.ROUTE:.0f} от двери к столу'})


bs.CODE_RU.update({'ANCHOR_STORAGE': 'хранение не там, где велит шаблон', 'DESK_NOT_AT_WINDOW': 'стол дальше 100 см от окна',
                   'BED_HEAD_WINDOW': 'изголовье под окном', 'COT_UNSAFE': 'кроватка у радиатора/окна',
                   'PLAY_ZONE': 'нет свободной игровой зоны (гипотеза)', 'SHELF_FRONT': 'нет места перед стеллажом',
                   'HEAD_NOT_SOLID': 'изголовье не на глухом участке (окно/проём/ниша)',
                   'BED_SIDE_GAP_BLOCKED': 'боковой зазор кровати закрыт (head_wall: оба бока открыты)',
                   'TWIN_APART_CLASH': 'кровати врозь мешают друг другу', 'MIRROR_FRONT': 'нет места перед зеркалом',
                   'SOFABED_OPEN': 'диван-кровать не разложить', 'BENCH_FRONT': 'нет прохода за банкеткой',
                   'DRESSING_SEAT': 'нет места под пуф у столика', 'BED_FOOT_IN_SWING': 'изножье в дуге двери',
                   'NO_BED_SKU': 'в банке нет кровати этой ширины'})


# ---------------------------------------------------------------- комнаты
REAL_BASE = ('demo597', 'demo450', 'uk377', 'uk396', 'uk244')


def tour_rooms(scenes):
    out = []
    for f in sorted(Path(scenes).glob('*/bedrooms.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        tag = d.get('trial_id', f.parent.name)[:4]
        for r in d.get('rooms', []):
            core = r.get('core')
            if not core:
                continue
            W, D = float(core['w']), float(core['d'])
            ops = [o for o in r.get('openings_core') or [] if o.get('kind') in ('door', 'window')]
            for o in ops:
                o.setdefault('hinge', 'left')
            room = bs._room(f"{tag}-{r['room_id']}", f"Тур {tag} · {r['room_id']} · {W:.0f}×{D:.0f}", f'{f} {r["room_id"]}', W, D, ops, [],
                            ['коробка расстановки тура (core); радиаторов на плане нет'])
            room['niches'], room['nonsolid'] = [], []
            for res in core.get('residues') or []:
                for wall, a, b in res.get('junctions') or []:
                    room['nonsolid'].append({'wall': wall, 'a': float(a), 'b': float(b), 'kind': res['kind']})   # стык — не глухая стена
                    if res['kind'] == 'recess' and res.get('depth_cm', 0) >= 50 and b - a >= 100:
                        room['niches'].append({'wall': wall, 'a': float(a), 'b': float(b), 'depth': float(res['depth_cm'])})
                    elif res['kind'] in ('passage', 'tail'):
                        room['notes'].append(f"открытая сторона ({res['kind']}) {wall} {a:.0f}–{b:.0f} — проход, мебель не ставим")
            room['listing_m2'] = r.get('area_m2')
            out.append(room)
    return out


def load_all(scenes=None):
    rooms = [r for r in bs.load_rooms() if r['id'] in REAL_BASE]
    for r in rooms:
        r['niches'], r['nonsolid'] = [], []
    if scenes:
        rooms += tour_rooms(scenes)
    for room in rooms:
        room['_geo'] = {'doors': [bs.door_geo(room, d) for d in room['doors']],
                        'rads': [bs.band(room, r['wall'], r['off'], r['width'], 0, r['depth']) for r in room['rads']],
                        'wins': [bs.band(room, w['wall'], w['off'], w['width'], 0, 1) for w in room['wins']]}
    return rooms


def facts_of(room, purpose):
    W, D = room['W'], room['D']
    return {'area_m2': round(W * D / 1e4, 2), 'aspect': round(max(W, D) / min(W, D), 2), 'has_window': bool(room['wins']),
            'has_niche': bool(room.get('niches')), 'external_storage': False, 'accessible': False,
            'work_needed': purpose in WORK_PURPOSES}


# ---------------------------------------------------------------- паспорт → план уровня
def _slots(group, variant):
    return CAT['groups'][group]['variants'][variant].get('slots') or []


def ladder_of(slot):
    ref = slot.get('rule_ref') or ''
    return list(RT.rule_value(ref)) if ref.startswith('distances_cm.bedroom_catalog.bed_width_ladder') else []


def plan_of(tpl, lv):
    """Уровень паспорта → что ставить: сон (вид, тумбы, лестница кровати), хранение, стол, столик, кресло/банкетка, игровая зона."""
    use = lv['use']
    p = {'sleep': None, 'storage': [], 'work': 'work' in use, 'dressing': 'dressing' in use, 'seat': use.get('seat'),
         'play': 'play' in use, 'use': use}
    if use.get('sleep'):
        sl = _slots('sleep', use['sleep'])
        bed = next(s for s in sl if s['id'] == 'bed')
        ns = next((s.get('count', 1) for s in sl if s['id'] == 'ns'), 0)
        kind = {'кроватка': 'cot', 'диван-кровать': 'sofabed'}.get(bed['role'], 'twin' if bed.get('count', 1) == 2 else 'bed')
        p['sleep'] = {'kind': kind, 'ns': ns, 'ladder': ladder_of(bed) or [None], 'variant': use['sleep']}
    if use.get('storage'):
        for s in _slots('storage', use['storage']):
            p['storage'] += [s['id']] * s.get('count', 1)
    return p


def anchors(tpl):
    return tpl.get('anchors') or {}


def rel_kinds(tpl):
    return {r['kind'] for r in tpl.get('relations') or []}


# ---------------------------------------------------------------- кандидаты
def cond_sku(k):
    return dict(COND2[k], sid=None, cond=True)


def bed_sku(skus, width, kind):
    if kind == 'cot':
        return cond_sku('cot')
    if width == 80:
        return cond_sku('child80')
    k = BED_SKU.get(width)
    return skus[k] if k else None


def head_solid(room, b):
    """Изголовье — глухой участок: на стене изголовья под шириной кровати нет окна, двери, стыка-проёма или ниши."""
    a0, a1 = b['off'], b['off'] + b['sku']['w']
    spans = [(o['off'], o['off'] + o['width']) for o in room['wins'] + room['doors'] if o['wall'] == b['wall']]
    spans += [(n['a'], n['b']) for n in room.get('nonsolid') or [] if n['wall'] == b['wall']]
    return not any(s0 < a1 - EPS and s1 > a0 + EPS for s0, s1 in spans)


def side_gaps_open(room, items, b):
    """head_wall (Codex 13.11 п.1): оба боковых зазора открыты — полоса GAP_OPEN вдоль всего ложа внутри комнаты, не занята
    ничем, кроме своей тумбы. Рабочий проход (bed_side_passage) с одного бока проверяет `bed_side_checks`."""
    out = []
    L = b['sku']['d']
    for sd in ('lo', 'hi'):
        off = b['off'] - GAP_OPEN if sd == 'lo' else b['off'] + b['sku']['w']
        z = bs.band(room, b['wall'], off, GAP_OPEN, 0, L)
        if not bs.inside(z, room):
            out.append(bs.V('BED_SIDE_GAP_BLOCKED', f'бок кровати ({sd}) — щель у стены, не зазор {GAP_OPEN:.0f}', [bs.clip(z, room)]))
            continue
        for o in items:
            if o is b or (o['kind'] == 'ns' and o['group'] == b['group']):
                continue
            h = bs.inter(z, o['rect'])
            if h:
                out.append(bs.V('BED_SIDE_GAP_BLOCKED', f'бок кровати закрыт «{o["role"]}»', [h]))
        for rr in room['_geo']['rads']:
            h = bs.inter(z, rr)
            if h:
                out.append(bs.V('BED_SIDE_GAP_BLOCKED', 'бок кровати закрыт радиатором', [h]))
    return out


def bed_ok_anchor(room, b, tpl, facts):
    a = anchors(tpl).get('sleep') or {}
    q = set(a.get('qualifiers') or [])
    W, D = room['W'], room['D']
    L = bs.wall_len(room, b['wall'])
    if 'long' in q and L < max(W, D) - EPS:
        return False
    if 'axis' in q and facts['aspect'] >= RT.rule_value('distances_cm.bedroom_elongated_aspect_min') and L > min(W, D) + EPS:
        return False
    if a.get('type') == 'corner' and min(b['gap'].values()) > bs.WALL_GAP:
        return False
    if 'off_corner' in q and min(b['gap'].values()) <= bs.WALL_GAP:      # head_wall: не в углу — оба бока не у стены
        return False
    if ('solid' in q or a.get('relation') == 'solid_wall') and not head_solid(room, b):
        return False
    if 'away_from_window' in q and any(bs.rdist(b['rect'], ws) < bs.RAD_SOFT - EPS for ws in room['_geo']['wins']):
        return False
    for pr in tpl.get('predicates') or []:
        if pr['kind'] == 'clear_width' and pr.get('of') == 'bed_axis':
            axis = D if b['wall'] in ('south', 'north') else W
            if axis < RT.rule_value(pr['rule_ref']) - EPS:
                return False
    return True


def gen_twin(room, sk, two_ns):
    """Две кровати параллельно у одной стены: проход между ними (тумба общая — в проходе у изголовья), вторая тумба — снаружи."""
    out = []
    B, ns = sk['bed']['w'], sk.get('ns')
    g = max(bs.SIDE, (ns['w'] + 2 * bs.NS_GAP) if ns else 0)
    for wall in bs.WALLS:
        L = bs.wall_len(room, wall)
        need = 2 * B + g + ((ns['w'] + bs.NS_GAP) if two_ns else 0)
        for off in bs.wall_offsets(room, wall, need, step=5):
            b1 = bs.sleep_group(room, sk, 'corner', wall, off)[0]
            b2 = bs.sleep_group(room, sk, 'corner', wall, off + B + g)[0]
            b2['role'] = 'кровать 2'
            its = [b1, b2]
            if ns:
                its.append(bs.item(room, 'тумба', 'ns', ns, wall, off + B + (g - ns['w']) / 2, 'sleep'))
                if two_ns:
                    its.append(bs.item(room, 'тумба 2', 'ns', ns, wall, off + 2 * B + g + bs.NS_GAP, 'sleep'))
            if off + need <= L + EPS:
                out.append(its)
    return out


def gen_twin_apart(room, sk, with_ns):
    """br.twin_apart (Codex 13.11 п.2): две кровати в РАЗНЫХ углах, изголовьями к разным стенам (напротив или под углом),
    длинный бок — к стене, тумба (если есть) — с открытого бока; наложения и «кровать в изножье/проходе другой» отсекаем тут."""
    ns = sk.get('ns') if with_ns else None
    B = sk['bed']['w']
    singles = []
    for wall in bs.WALLS:
        L = bs.wall_len(room, wall)
        for off, side in ((0.0, 'hi'), (L - B, 'lo')):
            if off < -EPS:
                continue
            if ns and (off + B + bs.NS_GAP + ns['w'] > L + EPS if side == 'hi' else off - bs.NS_GAP - ns['w'] < -EPS):
                continue
            g = bs.sleep_group(room, dict(sk, ns=ns) if ns else {'bed': sk['bed']}, 'corner', wall, off, side if ns else None)
            singles.append(g)
    free = []      # «со смещением»: вторая кровать — изголовьем к другой стене не в углу (шаг 20), тумба с любого бока
    for wall in bs.WALLS:
        L = bs.wall_len(room, wall)
        for off in bs.wall_offsets(room, wall, B, step=20):
            if min(off, L - off - B) <= bs.WALL_GAP:
                continue
            for side in (('lo', 'hi') if ns else (None,)):
                if ns and (off + B + bs.NS_GAP + ns['w'] > L + EPS if side == 'hi' else off - bs.NS_GAP - ns['w'] < -EPS):
                    continue
                free.append(bs.sleep_group(room, dict(sk, ns=ns) if ns else {'bed': sk['bed']}, 'one_side' if ns else 'solo', wall, off, side))
    pairs = [(singles[i], singles[j]) for i in range(len(singles)) for j in range(i + 1, len(singles))]
    pairs += [(g1, g2) for g1 in singles for g2 in free]
    out = []
    for g1, g2 in pairs:
        if g1[0]['wall'] == g2[0]['wall']:
            continue
        clash = any(bs.inter(x['rect'], y['rect']) for x in g1 for y in g2)
        for bb, other in ((g1[0], g2), (g2[0], g1)):     # кровать не в изножье и не в боковом проходе другой
            zones = [bb['foot_zone']] + [bb['side_zone'][s] for s in ('lo', 'hi') if bb['gap'][s] > bs.WALL_GAP]
            clash = clash or any(bs.inter(z, o['rect']) for z in zones for o in other)
        if clash:
            continue
        c2 = [dict(it, twin=2, role='кровать 2' if it['kind'] == 'bed' else 'тумба 2') for it in g2]
        out.append([dict(it, twin=1) for it in g1] + c2)
    return out


def wall_item(room, kind, sku, wall, off, zone=None):
    grp = {'walkin': 'wardrobe'}.get(kind, kind)
    return bs.item(room, bs.ITEM_RU[kind].lower(), kind, sku, wall, off, grp, zone)


def gen_wall(room, kind, skus_list, zone_of):
    out = []
    for k, sku in enumerate(skus_list):
        for wall in bs.WALLS:
            for off in bs.wall_offsets(room, wall, sku['w']):
                it = wall_item(room, kind, sku, wall, off, zone_of(sku))
                it['size_pen'] = 8 * k
                out.append([it])
    return out


def gen_sleep(room, tpl, facts, skus, sp, width, mode):
    sk = {}
    if sp['kind'] == 'sofabed':
        return gen_wall(room, 'sofabed', [cond_sku('sofabed')], lambda s: ('SOFABED_OPEN', SOFABED_OPEN, 'разлож.'))
    bed = bed_sku(skus, width, sp['kind'])
    if bed is None:
        return None
    sk['bed'] = bed
    if sp['ns']:
        sk['ns'] = skus['ns_compact' if mode == 'compact' else 'ns']
    if sp['kind'] == 'twin' and sp['variant'].startswith('twin_apart'):
        return gen_twin_apart(room, sk, sp['ns'] >= 2)
    if sp['kind'] == 'twin':
        return gen_twin(room, sk, sp['ns'] >= 2)
    corner = (anchors(tpl).get('sleep') or {}).get('type') == 'corner'
    var = 'pair' if sp['ns'] >= 2 else ('corner' if corner else ('one_side' if sp['ns'] else 'solo'))
    cands = bs.gen_sleep(room, sk, var)
    return [c for c in cands if bed_ok_anchor(room, c[0], tpl, facts)]


def gen_storage(room, sid, skus):
    ward = [skus['ward_l'], skus['ward_m'], skus['ward_s']]
    if sid == 'wardrobe':
        return [[dict(it, kind='wardrobe')] for c in bs.gen_wall_items(room, 'wardrobe', ward) for it in c]
    if sid == 'dresser':
        return bs.gen_wall_items(room, 'dresser', [skus['dresser']])
    if sid == 'shelf':
        return gen_wall(room, 'shelf', [cond_sku('shelf')], lambda s: ('SHELF_FRONT', bs.DRESS, f'{bs.DRESS:.0f}'))
    if sid == 'walkin':
        out = []
        for n in room.get('niches') or []:
            sku = {'name': f"Ниша {n['b'] - n['a']:.0f}×{n['depth']:.0f} — {WALKIN_NOTE}", 'w': n['b'] - n['a'], 'd': 1.0, 'h': 220.0,
                   'sid': None, 'cond': True}
            out.append([wall_item(room, 'walkin', sku, n['wall'], n['a'], ('WARDROBE_FRONT', bs.WARD, f'{bs.WARD:.0f}'))])
        return out
    return []


def gen_wardrobe_run(room, skus):
    """Шкафы в ряд вдоль одной стены (fitted wall): два корпуса вплотную."""
    out = []
    for a, b in (('ward_l', 'ward_m'), ('ward_l', 'ward_s'), ('ward_m', 'ward_s'), ('ward_s', 'ward_s')):
        s1, s2 = skus[a], skus[b]
        for wall in bs.WALLS:
            for off in bs.wall_offsets(room, wall, s1['w'] + s2['w']):
                i1 = bs.storage_item(room, 'wardrobe', s1, wall, off)
                i2 = bs.storage_item(room, 'wardrobe', s2, wall, off + s1['w'])
                i2['role'] = 'шкаф 2'
                out.append([i1, i2])
    return out


def gen_dressing(room):
    """Туалетный столик + пуф (паспорт dressing.table_seat): пуф — в зоне посадки перед столиком, той же группы."""
    s, pf = cond_sku('dressing'), cond_sku('pouf')
    out = []
    for c in gen_wall(room, 'dressing', [s], lambda _s: ('DRESSING_SEAT', bs.DESKZ, f'{bs.DESKZ:.0f}')):
        t = c[0]
        off = t['off'] + (s['w'] - pf['w']) / 2
        p = {'role': 'пуф', 'kind': 'pouf', 'sku': pf, 'wall': t['wall'], 'off': off, 'group': t['group'], 'zones': [],
             'rect': bs.band(room, t['wall'], off, pf['w'], s['d'] + 5, s['d'] + 5 + pf['d'])}
        out.append([t, p])
    return out


def bench_for(room, items):
    b = next((i for i in items if i['kind'] == 'bed'), None)
    if b is None:
        return []
    s = cond_sku('bench')
    L = b['sku']['d']
    off = b['off'] + (b['sku']['w'] - s['w']) / 2
    it = {'role': 'банкетка', 'kind': 'bench', 'sku': s, 'wall': b['wall'], 'off': off, 'group': 'sleep',
          'rect': bs.band(room, b['wall'], off, s['w'], L, L + s['d']),
          'zones': [{'code': 'BENCH_FRONT', 'rect': bs.band(room, b['wall'], off, s['w'], L + s['d'], L + s['d'] + bs.FOOT),
                     'label': f'{bs.FOOT:.0f}', 'kind': 'bench', 'wall': b['wall']}]}
    return [[it]]


# ---------------------------------------------------------------- проверки сверх `bedroom_schemes.evaluate`
def play_square(room, geo, items, size):
    """Свободный квадрат size×size (сетка 5 см): вне предметов, их фронтов, проходов у кровати, полосы и дуги двери."""
    st = 5.0
    nx, ny = int(room['W'] // st), int(room['D'] // st)
    occ = np.zeros((ny, nx), dtype=np.int32)

    def mark(r):
        x0, y0 = max(int(r[0] // st), 0), max(int(r[1] // st), 0)
        x1, y1 = min(int(math.ceil(r[2] / st)), nx), min(int(math.ceil(r[3] / st)), ny)
        if x1 > x0 and y1 > y0:
            occ[y0:y1, x0:x1] = 1
    for it in items:
        mark(it['rect'])
        for z in it['zones']:
            mark(z['rect'])
        if it['kind'] == 'bed':
            mark(it['foot_zone'])
            for sd, zz in it['side_zone'].items():
                if it.get('side_state', {}).get(sd) != 'wall':
                    mark(zz)
    for g in geo['doors']:
        mark(g['strip'])
        mark(g['qbox'])
    k = int(size // st)
    if k > nx or k > ny:
        return None
    c = np.pad(occ, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    free = np.argwhere(s == 0)
    if not len(free):
        return None
    cy, cx = (ny - k) / 2, (nx - k) / 2      # ближе к середине комнаты
    y, x = min(free, key=lambda p: (p[0] - cy) ** 2 + (p[1] - cx) ** 2)
    return (x * st, y * st, x * st + size, y * st + size)


def play_check(room, items):
    """Игровая зона — ГИПОТЕЗА (Codex 13.11 п.4), не hard: 150×150 цель → 120×120 compact (мягкий штраф) → нет (штраф больше)."""
    for key, pen in (('target', 0), ('compact', 40)):
        size = float(PLAY[key][0])
        sq = play_square(room, room['_geo'], items, size)
        if sq:
            return (sq, key), ([] if not pen else [bs.V('PLAY_ZONE_COMPACT', f'игровая зона только {size:.0f}×{size:.0f} (compact)', hard=False, pen=pen)])
    return (None, None), [bs.V('PLAY_ZONE', f"нет свободной игровой зоны даже {PLAY['compact'][0]}×{PLAY['compact'][1]} (гипотеза, мягко)", hard=False, pen=200)]


class Ctx:
    def __init__(self, room, tpl, purpose, plan):
        self.room, self.tpl, self.purpose, self.plan = room, tpl, purpose, plan
        sides2 = any(p['kind'] == 'side_access' and p.get('sides') == 2 for p in tpl.get('predicates') or [])
        self.rels = rel_kinds(tpl)
        self.head_gaps = 'bed_side_gaps_open' in self.rels
        # узкая «боком к стене» — мягкий штраф эскиза; у head_wall бок к стене запрещён контрактом, штраф не нужен
        self.bs_purpose = 'couple' if sides2 else ('single_narrow' if purpose == 'single_narrow' and not self.head_gaps else 'single')
        self.mirror = bool(plan['use'].get('mirror'))
        self.store_rel = (anchors(tpl).get('storage') or {}).get('relation')
        self.work_window = (anchors(tpl).get('work') or {}).get('type') == 'window'
        self.cot = bool(plan['sleep']) and plan['sleep']['kind'] == 'cot'


def evaluate2(ctx, items, cache):
    room, geo = ctx.room, ctx.room['_geo']
    beds = [i for i in items if i['kind'] == 'bed']
    vs = bs.evaluate(room, geo, items, ctx.bs_purpose, cache)
    for b2 in beds[1:]:                       # две кровати: у второй — свой рабочий бок
        vs += bs.bed_side_checks(room, geo, [b2] + [i for i in items if i is not b2], 'single')
    out = []
    for v in vs:
        if v['code'] == 'BED_HEAD_WINDOW' and 'bed_head_not_under_window' in ctx.rels:
            v = dict(v, hard=True, pen=0)
        if v['code'] == 'BED_NEAR_RADIATOR' and ctx.cot:
            v = dict(v, code='COT_UNSAFE', hard=True, pen=0, text='кроватка ближе 50 см к радиатору')
        out.append(v)
    b = beds[0] if beds else None
    W, D = room['W'], room['D']
    if ctx.head_gaps:
        for bb in beds:
            out += side_gaps_open(room, items, bb)
    if ctx.mirror and not any(i['kind'] == 'mirror' for i in items):
        out.append(bs.V('MIRROR_NONE', 'зеркало по уровню не встало', hard=False, pen=30))
    for it in items:
        if it['kind'] in ('wardrobe', 'walkin') and b is not None and ctx.store_rel:
            bad = ((ctx.store_rel == 'opposite_sleep_foot' and it['wall'] != bs.OPPOSITE[b['wall']])
                   or (ctx.store_rel == 'beside_sleep_not_foot' and it['wall'] == bs.OPPOSITE[b['wall']])
                   or (ctx.store_rel == 'short_wall' and bs.wall_len(room, it['wall']) > min(W, D) + EPS))
            if bad:
                out.append(bs.V('ANCHOR_STORAGE', f'шкаф не по шаблону ({ctx.store_rel})', [it['rect']]))
        if it['kind'] == 'desk' and ctx.work_window:
            dmin = min([bs.rdist(it['rect'], ws) for ws in geo['wins']] or [999])
            if dmin > bs.DESK_WIN + EPS:
                out.append(bs.V('DESK_NOT_AT_WINDOW', f'стол в {dmin:.0f} см от окна (шаблон — у окна ≤ {bs.DESK_WIN:.0f})', [it['rect']]))
        if it['kind'] == 'dressing':
            dmin = min([bs.rdist(it['rect'], ws) for ws in geo['wins']] or [400])
            out.append(bs.V('DRESSING_FAR', '', hard=False, pen=0.2 * dmin))
        if ctx.cot and it['kind'] == 'bed':
            for ws in geo['wins']:
                if bs.rdist(it['rect'], ws) < bs.RAD_SOFT - EPS:
                    out.append(bs.V('COT_UNSAFE', 'кроватка у окна (шнуры, сквозняк)', [it['rect']]))
        if it['kind'] == 'sofabed':     # разложенный — спальное место: не в дуге и не в полосе двери, не на других предметах
            for z in it['zones']:
                for g in geo['doors']:
                    h = bs.swing_hit(z['rect'], g) or bs.inter(z['rect'], g['strip'])
                    if h:
                        out.append(bs.V('SOFABED_OPEN', 'разложенный диван-кровать в дуге/проходе двери', [h]))
                for o in items:
                    if o is not it and bs.inter(z['rect'], o['rect']):
                        out.append(bs.V('SOFABED_OPEN', f'разложенный диван-кровать упирается в «{o["role"]}»', [bs.inter(z['rect'], o['rect'])]))
    return out


def routes(ctx, items):
    beds = [i for i in items if i['kind'] == 'bed']
    rv, paths = [], []
    order = [beds[0]] + [i for i in items if i is not beds[0]] if beds else items
    v, p = bs.check_routes(ctx.room, ctx.room['_geo'], order, ctx.bs_purpose, want_paths=True)
    rv += v
    paths += p
    for b2 in beds[1:]:
        bs.bed_side_checks(ctx.room, ctx.room['_geo'], [b2] + [i for i in items if i is not b2], 'single')
        v, p = bs.check_routes(ctx.room, ctx.room['_geo'], [b2] + [i for i in items if i is not b2], 'single', want_paths=True)
        rv += [x for x in v if x['code'] == 'ROUTE_BED' or not x['code'].startswith('ROUTE_WINDOW')]
        paths += [x for x in p if x[0].startswith('bed')]
    if beds:      # side_state первой кровати — заново (проверка второй его не трогает, но для рисунка — явно)
        bs.bed_side_checks(ctx.room, ctx.room['_geo'], order, ctx.bs_purpose)
    return rv, paths


def search2(ctx, stages, beam=30):
    """Как `bedroom_schemes.search`: луч по стадиям, путь от двери — уже на частичном составе. stages: [(имя, кандидаты | f(items))]."""
    cache = {}
    states = [([], (0, 0.0))]
    for name, cands in stages:
        nxt = {}
        for items, _ in states:
            cs = cands(items) if callable(cands) else cands
            for c in cs:
                its = items + [dict(x) for x in c]
                sc = bs.score(evaluate2(ctx, its, cache))
                k = bs.sig(its)
                if k not in nxt or sc < nxt[k][1]:
                    nxt[k] = (its, sc)
        ranked = sorted(nxt.values(), key=lambda t: t[1])
        if name in ('sleep', 'desk'):
            per, keep = {}, []
            for its, sc in ranked:
                key = tuple(i['wall'] for i in its if i['kind'] in ('bed', 'desk', 'sofabed'))
                if per.get(key, 0) < beam // 4 + 2:
                    per[key] = per.get(key, 0) + 1
                    keep.append((its, sc))
            ranked = keep
        good, bad, checks = [], [], 0
        for its, sc in ranked:
            if len(good) >= beam or checks >= 90:
                break
            if sc[0] == 0:
                checks += 1
                rv, _ = routes(ctx, its)
                if rv:
                    bad.append((its, (sc[0] + len(rv), sc[1])))
                    continue
            good.append((its, sc))
        states = (good + sorted(bad, key=lambda t: t[1]))[:beam] if good else ranked[:beam]
        if not states:
            return None
    best = None
    for items, sc in states:
        vs = evaluate2(ctx, items, cache)
        if sc[0] == 0:
            rv, _ = routes(ctx, items)
            vs = vs + rv
        if ctx.plan['play']:
            vs = vs + play_check(ctx.room, items)[1]
        sc2 = bs.score(vs)
        if best is None or sc2 < best[1]:
            best = (items, sc2, vs)
        if sc2[0] == 0:
            break
    items, sc, vs = best
    if sc[0] > 0:
        rv, _ = routes(ctx, items)
        vs = vs + [v for v in rv if v['code'] not in {x['code'] for x in vs}]
        sc = bs.score(vs)
    return {'items': items, 'score': sc, 'vs': vs, 'ok': sc[0] == 0}


def stages_for(ctx, skus, width, mode, facts):
    p, room = ctx.plan, ctx.room
    st = []
    if p['work']:
        sk = {'desk': skus['desk'], 'chair': skus['chair']}
        st.append(('desk', bs.gen_desk(room, sk)))
    if p['sleep']:
        c = gen_sleep(room, ctx.tpl, facts, skus, p['sleep'], width, mode)
        if c is None:
            return None
        st.append(('sleep', c))
    sto = list(p['storage'])
    if sto.count('wardrobe') == 2:
        st.append(('wardrobe', gen_wardrobe_run(room, skus)))
        sto = [s for s in sto if s != 'wardrobe']
    for sid in sto:
        st.append((sid, gen_storage(room, sid, skus)))
    if p['dressing']:
        st.append(('dressing', gen_dressing(room)))
    if p['seat'] == 'armchair':
        st.append(('armchair', gen_wall(room, 'armchair', [cond_sku('armchair')], lambda s: None)))
    if p['seat'] == 'bench':
        st.append(('bench', lambda items: bench_for(room, items)))
    if any(not c for _n, c in st if not callable(c)):
        return []
    if ctx.mirror:      # зеркало по желанию (required: false): пустой вариант разрешён, но со штрафом MIRROR_NONE
        st.append(('mirror', gen_wall(room, 'mirror', [cond_sku('mirror')], lambda s: ('MIRROR_FRONT', bs.DRESS, f'{bs.DRESS:.0f}')) + [[]]))
    return st


def storage_fill(tpl, purpose, items):
    """Полнота хранения: фронт шкафов / target по назначению (`wardrobe_front_cm`); комод и стеллаж — отдельной строкой."""
    key = {'couple': 'couple', 'twin': 'twin', 'guest': 'guest'}.get(purpose, 'child' if purpose.startswith('child') else 'single')
    wf = BC['wardrobe_front_cm'][key]
    front = sum(i['sku']['w'] for i in items if i['kind'] in ('wardrobe', 'walkin'))
    return front, wf


def run_template(room, tpl, purpose, skus):
    """Шаблон: уровни × кровать — сперва по цели, потом compact (у доступной — без compact); исключение sleep_before_mode —
    по цели вышло тумб меньше `want` → тот же перебор в compact на уровнях с тумбами (как `planner/bedroom.py:_sleep_first`)."""
    facts = facts_of(room, purpose)
    levels = RT.levels_for(tpl, facts)
    tries = []
    modes = ('target',) if tpl['id'] == 'br.accessible_principal' else ('target', 'compact')
    found = None
    for mode in modes:
        set_norm(mode)
        for li, lid in enumerate(levels):
            lv = next(x for x in tpl['levels'] if x['id'] == lid)
            plan = plan_of(tpl, lv)
            ctx = Ctx(room, tpl, purpose, plan)
            for bi, width in enumerate(plan['sleep']['ladder'] if plan['sleep'] else [None]):
                stg = stages_for(ctx, skus, width, mode, facts)
                if stg is None:
                    tries.append({'level': lid, 'bed': width, 'mode': mode, 'ok': False, 'why': ['в банке нет кровати этой ширины']})
                    continue
                res = search2(ctx, stg) if stg else None
                if res is None:
                    tries.append({'level': lid, 'bed': width, 'mode': mode, 'ok': False, 'why': ['нет места ни для одного предмета уровня']})
                    continue
                why = bs.hard_reasons(res)
                tries.append({'level': lid, 'bed': width, 'mode': mode, 'ok': res['ok'], 'why': why})
                if res['ok']:
                    found = dict(res, level=lid, li=li, bed=width, bi=bi, mode=mode, plan=plan, ctx=ctx)
                    break
            if found:
                break
        if found:
            break
    sbm = tpl.get('sleep_before_mode') or {}
    if found and found['mode'] == 'target' and purpose in (sbm.get('purpose') or []):
        want = {'pair': 2, 'one_side': 1}.get((sbm.get('want') or {}).get(purpose), 0)
        have = found['plan']['sleep']['ns'] if found['plan']['sleep'] else 0
        if have < want:
            set_norm('compact')
            for li, lid in enumerate(levels[:found['li']]):
                lv = next(x for x in tpl['levels'] if x['id'] == lid)
                plan = plan_of(tpl, lv)
                if not plan['sleep'] or plan['sleep']['ns'] < want or len(plan['storage']) < len(found['plan']['storage']):
                    continue
                ctx = Ctx(room, tpl, purpose, plan)
                for bi, width in enumerate(plan['sleep']['ladder']):
                    stg = stages_for(ctx, skus, width, 'compact', facts)
                    res = search2(ctx, stg) if stg else None
                    if res and res['ok']:
                        tries.append({'level': lid, 'bed': width, 'mode': 'compact', 'ok': True, 'why': ['тумбы важнее режима прохода (sleep_before_mode)']})
                        found = dict(res, level=lid, li=li, bed=width, bi=bi, mode='compact', plan=plan, ctx=ctx, sbm=True)
                        break
                if found.get('sbm'):
                    break
    if found:
        set_norm(found['mode'])
        _rv, found['paths'] = routes(found['ctx'], found['items'])
        found['fill'] = storage_fill(tpl, purpose, found['items'])
        if found['plan']['play']:
            found['play_sq'], found['play_mode'] = play_check(room, found['items'])[0]
        found['places'] = places_count(found)
    return found, tries


def places_count(f):
    """Полнота по паспорту: мест-товаров уровня (роль × count) и сколько из них стоит на эскизе. Зависимые (свет, шторы, ковёр…)
    рисуются схемой по носителям и решателем `planner/dependents.py` здесь не проверяются — считаем только места на полу/стене."""
    use = f['plan']['use']
    want = 0
    for g, v in use.items():
        if g in ('light', 'textile', 'art', 'decor'):
            continue
        for s in CAT['groups'][g]['variants'][v].get('slots') or []:
            want += s.get('count', 1)
    have = len(f['items']) + (1 if f.get('play_sq') else 0)
    return min(have, want), want


def specificity(tpl):
    return max([RT.rule_value(w['rule_ref']) for w in tpl.get('when') or [] if w['kind'] == 'area_min'] or [0])


def fill_ratio(f):
    front, wf = f['fill']
    return min(front / wf['target'], 1.0) if wf.get('target') else 0.0


def win_key(tpl, f):
    """Codex 13.11 п.3: без нарушений (уже) → цель раньше compact → уровень → полнота хранения front/target → ширина кровати
    (ступень лестницы) → специфичность (порог площади) → priority → мягкий счёт."""
    miss = 1 if f['plan']['play'] and f.get('play_mode') is None else 0     # обязательная группа без места (игровая — мягко, но ниже)
    return (miss, 0 if f['mode'] == 'target' else 1, f['li'], -round(fill_ratio(f), 3), f['bi'], -specificity(tpl), tpl['priority'], f['score'][1])


def why_not(tpl, facts):
    for w in tpl.get('when') or []:
        if not RT.when_ok([w], facts):
            if w['kind'] == 'area_min':
                return f"площадь {facts['area_m2']:.1f} < {RT.rule_value(w['rule_ref'])} м²"
            if w['kind'] == 'aspect_min':
                return f"не вытянута ({facts['aspect']:.2f} < {RT.rule_value(w['rule_ref'])})"
            return {'has_niche': 'нет ниши', 'work_needed': 'стол не просили', 'accessible': 'профиль доступности не задан',
                    'external_storage': 'внешнего хранения нет'}.get(w['kind'], w['kind'])
    return ''


def run_room(args):
    room, skus = args
    out = {}
    for purpose in PURPOSES:
        facts = facts_of(room, purpose)
        cells = []
        for tpl in sorted((t for t in CAT['templates'] if purpose in t['purpose']), key=lambda t: t['priority']):
            if not RT.when_ok(tpl.get('when'), facts):
                cells.append({'tpl': tpl['id'], 'applies': False, 'why': why_not(tpl, facts)})
                continue
            f, tries = run_template(room, tpl, purpose, skus)
            cells.append({'tpl': tpl['id'], 'applies': True, 'found': f, 'tries': tries})
        ok = [c for c in cells if c.get('found')]
        ok.sort(key=lambda c: win_key(next(t for t in CAT['templates'] if t['id'] == c['tpl']), c['found']))
        out[purpose] = {'facts': facts, 'cells': cells, 'ranking': [c['tpl'] for c in ok]}
        print(room['id'], purpose, ok[0]['tpl'] if ok else ('NO_ROOM_TEMPLATE_FITS' if any(c['applies'] for c in cells) else 'нет шаблонов по площади'), flush=True)
    return room['id'], out


# ---------------------------------------------------------------- рисунок: места зависимых по паспорту
def finish_overlay(room, f, tpl):
    use = f['plan']['use']
    items = f['items']

    def draw(cv, d):
        col_l, col_c, col_r, col_a = (255, 179, 0), (123, 31, 162), (121, 85, 72), (55, 71, 79)
        if use.get('textile'):
            for w in room['wins']:
                a = bs.wall_point(room, w['wall'], w['off'] - 15, 7)
                b = bs.wall_point(room, w['wall'], w['off'] + w['width'] + 15, 7)
                d.line([cv.P(*a), cv.P(*b)], fill=col_c, width=3)
        beds = [i for i in items if i['kind'] in ('bed', 'sofabed')]
        if use.get('textile') in ('bed', 'nursery'):
            ov = RT.rule_value('distances_cm.bed_rug_overhang')[0]
            for b in beds:
                L = b['sku']['d'] + (SOFABED_OPEN if b['kind'] == 'sofabed' else 0)   # из правил: bedroom_catalog.sofabed_open
                r = bs.clip(bs.band(room, b['wall'], b['off'] - ov, b['sku']['w'] + 2 * ov, L * 0.35, L + ov), room)
                if r:
                    x0, y0, x1, y1 = cv.R(r)
                    for k in range(int(x0), int(x1), 12):
                        d.line([(k, y0), (min(k + 6, x1), y0)], fill=col_r, width=2)
                        d.line([(k, y1), (min(k + 6, x1), y1)], fill=col_r, width=2)
                    for k in range(int(y0), int(y1), 12):
                        d.line([(x0, k), (x0, min(k + 6, y1))], fill=col_r, width=2)
                        d.line([(x1, k), (x1, min(k + 6, y1))], fill=col_r, width=2)
                if use.get('textile') == 'bed' and b['kind'] == 'bed':
                    t = bs.band(room, b['wall'], b['off'] + 6, b['sku']['w'] - 12, b['sku']['d'] - 38, b['sku']['d'] - 8)
                    d.rectangle(cv.R(t), outline=(141, 110, 99), width=2)
        light = use.get('light') or ''
        if light:
            zone = [i['rect'] for i in items if i['kind'] in ('bed', 'sofabed', 'ns')] or [i['rect'] for i in items if i['kind'] == 'desk']
            if zone:
                cx = (min(r[0] for r in zone) + max(r[2] for r in zone)) / 2
                cy = (min(r[1] for r in zone) + max(r[3] for r in zone)) / 2
            else:
                cx, cy = room['W'] / 2, room['D'] / 2
            x, y = cv.P(cx, cy)
            rr = 9
            d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=col_l, width=3)
            d.line([(x - rr, y), (x + rr, y)], fill=col_l, width=2)
            d.line([(x, y - rr), (x, y + rr)], fill=col_l, width=2)
            for i in items:
                if (i['kind'] == 'ns' and 'bedside' in light) or (i['kind'] == 'desk' and 'desk' in light) or \
                        (i['kind'] == 'dresser' and light == 'nursery'):
                    q = cv.R(i['rect'])
                    cx2, cy2 = (q[0] + q[2]) / 2, (q[1] + q[3]) / 2
                    d.ellipse([cx2 - 6, cy2 - 6, cx2 + 6, cy2 + 6], fill=col_l, outline=(120, 80, 0))
            if 'headboard' in light:
                for b in [i for i in items if i['kind'] == 'bed']:
                    for sd, o in (('lo', b['off'] - 8), ('hi', b['off'] + b['sku']['w'] + 8)):
                        if b['gap'][sd] > bs.WALL_GAP:
                            x, y = cv.P(*bs.wall_point(room, b['wall'], o, 4))
                            d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=col_l, outline=(120, 80, 0))
        art = use.get('art')
        car = [i for i in items if i['kind'] == 'bed'][:1] if art == 'over_bed' else \
            [i for i in items if i['kind'] in ('dresser', 'desk')][:1] if art == 'over_side' else []
        for c in car:
            w = c['sku']['w'] * 0.667
            a = bs.wall_point(room, c['wall'], c['off'] + (c['sku']['w'] - w) / 2, 2)
            b = bs.wall_point(room, c['wall'], c['off'] + (c['sku']['w'] + w) / 2, 2)
            d.line([cv.P(*a), cv.P(*b)], fill=col_a, width=6)
        dec = use.get('decor')
        for i in items:
            if (dec == 'on_dresser' and i['kind'] == 'dresser') or (dec == 'on_ns' and i['kind'] == 'ns' and i['role'] == 'тумба'):
                q = cv.R(i['rect'])
                x, y = q[2] - 10, q[1] + 10
                d.polygon([(x, y - 6), (x + 6, y + 5), (x - 6, y + 5)], fill=(0, 137, 123))
        sq = f.get('play_sq')
        if sq:
            x0, y0, x1, y1 = cv.R(sq)
            for k in range(int(x0), int(x1), 10):
                d.line([(k, y0), (min(k + 5, x1), y0)], fill=(46, 125, 50), width=3)
                d.line([(k, y1), (min(k + 5, x1), y1)], fill=(46, 125, 50), width=3)
            for k in range(int(y0), int(y1), 10):
                d.line([(x0, k), (x0, min(k + 5, y1))], fill=(46, 125, 50), width=3)
                d.line([(x1, k), (x1, min(k + 5, y1))], fill=(46, 125, 50), width=3)
            bs.text_c(d, ((x0 + x1) / 2, (y0 + y1) / 2), f"игровая\n{sq[2] - sq[0]:.0f}×{sq[3] - sq[1]:.0f}", bs.font(12, True), (46, 125, 50))
    return draw


def tpl_by(tid):
    return next(t for t in CAT['templates'] if t['id'] == tid)


def label_ru(tpl):
    return tpl.get('label', tpl['id']).split(' / ')[0]


def panel(room, purpose, cell, rank, compact, s):
    tpl = tpl_by(cell['tpl'])
    f = cell['found']
    set_norm(f['mode'])
    bed = f'{f["bed"]}' if f['bed'] else ''
    title = f"{room['title'].replace('Демо · ', 'Демо ')} — {tpl['id'].replace('br.', '')} · {f['level']}"
    sub = f"{PURPOSE_RU[purpose]}: {label_ru(tpl)}"
    front, wf = f['fill']
    lv = next(x for x in tpl['levels'] if x['id'] == f['level'])
    comp = ' + '.join(CAT['groups'][g]['variants'][v].get('label', v).split(' / ')[0] for g, v in lv['use'].items()
                      if g not in ('light', 'textile', 'art', 'decor'))
    fl = [f"Уровень {f['level']}: {comp}"[:120]]
    if bed:
        fl.append(f"кровать {bed} (лестница {'→'.join(str(x) for x in f['plan']['sleep']['ladder'])}) · проходы: {MODE_RU[f['mode']]}"
                  + (' (тумбы важнее режима)' if f.get('sbm') else ''))
    else:
        fl.append(f"проходы: {MODE_RU[f['mode']]}")
    if front:
        fl.append(f"хранение: шкаф {front:.0f} см (норма {wf['min']}–{wf['target']})" + (' — неполное' if front < wf['min'] else ''))
    elif f['plan']['storage']:
        fl.append(f"хранение: без шкафа — {', '.join(bs.ITEM_RU.get(s, s).lower() for s in f['plan']['storage'])} (норма шкафа {wf['min']}–{wf['target']})")
    have, want = f['places']
    extra = []
    if f['plan']['play']:
        extra.append({'target': f"игровая {PLAY['target'][0]}×{PLAY['target'][1]}", 'compact': f"игровая только {PLAY['compact'][0]}×{PLAY['compact'][1]}",
                      None: 'игровой зоны нет'}[f.get('play_mode')] + ' (гипотеза)')
    if f['ctx'].mirror and not any(i['kind'] == 'mirror' for i in f['items']):
        extra.append('зеркало не встало')
    fl.append(f"по паспорту: мест {have} из {want}" + (' · ' + ', '.join(extra) if extra else '')
              + ' · ✓ проходы, дверь, путь к кровати и окну')
    if rank:
        fl.append('Другие шаблоны: ' + '; '.join(rank)[:110])
    res = {'items': f['items'], 'vs': f['vs']}
    return bs.render(room, res, s, compact=compact, title=title, subtitle=sub[:80], foot_lines=fl, paths=f['paths'],
                     extra=finish_overlay(room, f, tpl))


def fmt_found(f):
    return f"{f['level']}·{f['bed'] or '—'}·{MODE_RU[f['mode']]}"


def main(out, scenes=None, jobs=1, only=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    err = RT.check(CAT)
    if err:
        raise SystemExit('паспорт каталога с ошибками схемы: ' + '; '.join(err[:5]))
    skus, nsets = bs.load_skus()
    rooms = [r for r in load_all(scenes) if not only or r['id'] in only]
    if jobs > 1:
        with Pool(jobs) as pool:
            got = dict(pool.map(run_room, [(r, skus) for r in rooms], chunksize=1))
    else:
        got = dict(map(run_room, [(r, skus) for r in rooms]))
    # панели: по комнате — победитель главного назначения; потом — каждый шаблон каталога хотя бы раз (первая комната, где он встал)
    panels, drawn = [], set()
    for room in rooms:
        a = room['W'] * room['D'] / 1e4
        main_p = 'couple' if a >= BC['area_min_m2']['couple'] else ('single_narrow' if room['id'].startswith('uk') else 'single')
        r = got[room['id']][main_p]
        if r['ranking']:
            panels.append((room, main_p, r['ranking'][0]))
            drawn.add(r['ranking'][0])
    for tpl in sorted(CAT['templates'], key=lambda t: t['id']):
        if tpl['id'] in drawn:
            continue
        for room in rooms:
            hit = next(((p, c) for p in PURPOSES for c in got[room['id']][p]['cells'] if c['tpl'] == tpl['id'] and c.get('found')), None)
            if hit:
                panels.append((room, hit[0], tpl['id']))
                drawn.add(tpl['id'])
                break
    imgs = []
    for room, purpose, tid in panels:
        r = got[room['id']][purpose]
        cell = next(c for c in r['cells'] if c['tpl'] == tid)
        others = [f"{t.replace('br.', '')} {fmt_found(next(c for c in r['cells'] if c['tpl'] == t)['found'])}" for t in r['ranking'] if t != tid][:3]
        win = r['ranking'][0] == tid
        img = panel(room, purpose, cell, (['победил'] if win else ['не первый: ' + r['ranking'][0].replace('br.', '')]) + others, False, 2.0)
        fn = out / f"{room['id']}-{purpose.replace(':', '')}-{tid.replace('br.', '')}.png"
        img.save(fn)
        s = min(540 / room['W'], 480 / room['D'])
        imgs.append(panel(room, purpose, cell, (['победил'] if win else ['не первый: ' + r['ranking'][0].replace('br.', '')]) + others, True, s))
    sheets = make_sheets(out, imgs)
    write_matrix(out, rooms, got, skus, nsets, panels, sheets)
    dump = {}
    for rid, per in got.items():
        dump[rid] = {p: {'facts': v['facts'], 'ranking': v['ranking'],
                         'cells': [{'tpl': c['tpl'], 'applies': c['applies'], 'why': c.get('why'),
                                    'found': None if not c.get('found') else {k: c['found'][k] for k in ('level', 'bed', 'mode')},
                                    'tries': c.get('tries')} for c in v['cells']]} for p, v in per.items()}
    (out / 'results.json').write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding='utf-8')
    print(totals(rooms, got)[0], flush=True)
    print('done', out, len(panels), 'панелей', sheets)


LEGEND = ('зелёное — проход у кровати и изножья · синее — перед шкафом · фиолетовое — перед комодом/стеллажом · жёлтое — дверь · '
          'красная штриховка — нарушение · пунктир — нет в банке (условно)')
LEGEND2 = ('места по паспорту: фиолетовая линия — шторы · жёлтый круг с крестом — общий свет · жёлтая точка — лампа/бра · '
           'коричневый пунктир — ковёр · рамка у изножья — плед · тёмная черта у стены — картина · бирюзовый треугольник — декор')


def make_sheets(out, imgs, per=8):
    colw = 660
    names = []
    for si in range(0, len(imgs), per):
        chunk = imgs[si:si + per]
        rows = [chunk[i:i + 2] for i in range(0, len(chunk), 2)]
        H = sum(max(im.height for im in r) + 16 for r in rows) + 96
        sheet = Image.new('RGB', (colw * 2 + 30, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        n = si // per + 1
        d.text((14, 10), f'Спальня строго по шаблонам: каталог {len(CAT['templates'])} шаблонов на реальных комнатах (масштаб, сетка 50 см) · лист {n}',
               font=bs.font(22, True), fill=(0, 0, 0))
        d.text((14, 42), LEGEND, font=bs.font(12), fill=(70, 70, 70))
        d.text((14, 62), LEGEND2, font=bs.font(12), fill=(70, 70, 70))
        y = 90
        for r in rows:
            x = 10
            for im in r:
                if im.width > colw:
                    im = im.resize((colw, int(im.height * colw / im.width)))
                sheet.paste(im, (x, y))
                d.rectangle([x, y, x + im.width - 1, y + im.height - 1], outline=(200, 200, 200))
                x += colw + 10
            y += max(min(im.height, int(im.height * colw / max(im.width, 1))) for im in r) + 16
        fn = out / f'sheet-{n}.png'
        sheet.save(fn)
        names.append(fn.name)
    return names


def totals(rooms, got):
    """Честный счёт по ПОЛНОМУ паспорту: пары «комната × назначение», где шаблоны назначения применимы; встало — есть победитель
    без жёстких нарушений; места — у победителей, сколько мест-товаров уровня стоит (зеркало по желанию тоже в счёте)."""
    app = [(r, p) for r in rooms for p in PURPOSES if any(c['applies'] for c in got[r['id']][p]['cells'])]
    fit = [(r, p) for r, p in app if got[r['id']][p]['ranking']]
    have = want = full = 0
    soft = {'зеркало не встало': 0, 'игровая только compact': 0, 'игровой зоны нет': 0}
    for r, p in fit:
        c = next(c for c in got[r['id']][p]['cells'] if c['tpl'] == got[r['id']][p]['ranking'][0])
        h, w = c['found']['places']
        have, want, full = have + h, want + w, full + (h == w)
        if c['found']['ctx'].mirror and not any(i['kind'] == 'mirror' for i in c['found']['items']):
            soft['зеркало не встало'] += 1
        pm = c['found'].get('play_mode', 'target') if c['found']['plan']['play'] else 'target'
        if pm != 'target':
            soft['игровая только compact' if pm == 'compact' else 'игровой зоны нет'] += 1
    return [f'**Итог по полному паспорту: встало {len(fit)} из {len(app)}** (комната × назначение, где шаблоны применимы); '
            f'у победителей мест-товаров {have} из {want}, весь состав уровня — {full} из {len(fit)}; '
            + ', '.join(f'{k}: {v}' for k, v in soft.items()) + '. Зависимые (свет, шторы, ковёр, картина, декор) — схемой по носителям, '
            'решатель `planner/dependents.py` на эскизе не запускался.', '']


def write_matrix(out, rooms, got, skus, nsets, panels, sheets):
    L = ['# Спальня строго по шаблонам — каталог ' + str(len(CAT['templates'])) + ' шаблонов на реальных комнатах (T-20261112-120, эскиз — не солвер)', '',
         'Паспорт тенью: `services/planner-solver/rules/room-templates/bedroom-catalog.json` (движок пока читает `bedroom.json`). '
         f'Товары — рамы банка `sets-bedroom.json` ({nsets} наборов); кроватки, стола, туалетного столика, стеллажа, дивана-кровати, кресла, '
         'банкетки в банке нет — условные размеры. Ячейка: `уровень·кровать·проходы` (цель | compact), `✗` — шаблон подходит, но не встал '
         '(причина первого уровня), `—` — шаблон не рассматривается (почему). Победитель — **жирным**: без нарушений → по цели раньше compact → '
         'уровень → полнота хранения (фронт шкафа / target) → кровать → специфичность (порог площади) → priority (Codex 13.11 п.3).', '']
    L += totals(rooms, got)
    for room in rooms:
        a = room['W'] * room['D'] / 1e4
        lm = f" (в объявлении {room['listing_m2']} м²)" if room.get('listing_m2') else ''
        L.append(f"## {room['title']} — {a:.1f} м²{lm}, вытянутость {max(room['W'], room['D']) / min(room['W'], room['D']):.2f}"
                 + (f", ниша {', '.join(f'{n['b'] - n['a']:.0f}×{n['depth']:.0f}' for n in room['niches'])}" if room.get('niches') else ''))
        L.append('')
        L.append('| назначение | итог | шаблоны |')
        L.append('|---|---|---|')
        for p in PURPOSES:
            r = got[room['id']][p]
            parts = []
            for c in r['cells']:
                t = c['tpl'].replace('br.', '')
                if not c['applies']:
                    parts.append(f'{t} — {c["why"]}')
                elif c.get('found'):
                    s = f"{t} {fmt_found(c['found'])}"
                    parts.append(f'**{s}**' if r['ranking'] and r['ranking'][0] == c['tpl'] else s)
                else:
                    first = (c['tries'] or [{}])[0]
                    parts.append(f"{t} ✗ {', '.join((first.get('why') or ['—'])[:2])}")
            if r['ranking']:
                top = r['ranking'][0].replace('br.', '')
            elif any(c['applies'] for c in r['cells']):
                top = '**NO_ROOM_TEMPLATE_FITS** → кандидат в новый шаблон'
            else:
                top = '— комната не для этого назначения (порог площади/условия)'
            L.append(f"| {PURPOSE_RU[p]} | {top} | {'<br>'.join(parts)} |")
        L.append('')
    nofit = [(room, p) for room in rooms for p in PURPOSES if not got[room['id']][p]['ranking']
             and any(c['applies'] for c in got[room['id']][p]['cells'])]
    L.append('## Кандидаты в новый шаблон (шаблоны назначения есть, но ни один не встал)')
    L.append('')
    for room, p in nofit:
        r = got[room['id']][p]
        why = sorted({w for c in r['cells'] if c['applies'] for t in c['tries'][:1] for w in t['why'][:2]})
        L.append(f"- {room['id']} · {PURPOSE_RU[p]}: {room['W']:.0f}×{room['D']:.0f}, двери {len(room['doors'])}, окна {len(room['wins'])} — "
                 f"{'; '.join(why)[:200]}")
    if not nofit:
        L.append('- нет')
    L.append('')
    L.append('## Панели листов')
    L.append('')
    for room, p, tid in panels:
        L.append(f"- {room['id']} · {PURPOSE_RU[p]} · {tid}")
    L.append('')
    L.append('Листы: ' + ', '.join(sheets))
    (out / 'matrix.md').write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(2)
    jobs = int(a[a.index('--jobs') + 1]) if '--jobs' in a else 1
    only = a[a.index('--rooms') + 1].split(',') if '--rooms' in a else None
    pos = [x for i, x in enumerate(a) if not x.startswith('--') and (i == 0 or not a[i - 1].startswith('--'))]
    main(pos[0], pos[1] if len(pos) > 1 else None, jobs, only)
