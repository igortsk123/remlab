"""Q9 свода №13: МОДЕЛЬ ВОЗМОЖНОСТЕЙ (opportunity) и приоры практики — ТЕНЬ (Codex 18.08).

Возможность — место, где практика даёт узнаваемый набор исходов: `window` (у окна),
`seating_center` (центр посадочной группы), `free_corner` (свободный угол), `primary_wall`
(главная стена напротив дивана). Для готового плана определяем ВЫБРАННЫЙ исход и сравниваем
его ранг с приорами практики (`tools/scout/rules/practice_priors.json`).

Контракт (важно): приоры — НЕ веса и НЕ вероятности. Это ordinal tie-break между равноценными
и достижимыми исходами; «пусто» (`free_intentional`) — полноценный исход, а не отсутствие
решения. В production приоры включаются только после слепых пар; здесь — измерение и артефакт.
"""
from __future__ import annotations

import json
import math
import os

from .geometry import base_role, footprint, opening_polygon, room_polygon
from .models import Placement, Room

_PRIORS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', '..', '..', 'tools', 'scout', 'rules', 'practice_priors.json')
def _oz(name: str, default: float) -> float:
    """Пороги зон возможностей — из правил (Q12-1, ADR-0112): раньше числа были зашиты в коде
    без провенанса, и «ситуация» опиралась на невидимые константы."""
    try:
        from .zones import zone_rules as _zr
        v = ((_zr().get('opportunity_zones') or {}).get(name) or {}).get('v')
        return float(default if v is None else v)
    except Exception:
        return float(default)


WINDOW_ZONE_DEPTH_CM = _oz('window_band_depth_cm', 90.0)   # полоса «у окна»
CORNER_BOX_CM = _oz('corner_box_cm', 130.0)                # квадрат угла комнаты
CENTER_REACH_CM = _oz('center_reach_cm', 120.0)            # «центр группы» перед фронтом дивана
PRIMARY_WALL_DEPTH_CM = _oz('primary_wall_depth_cm', 70.0)

# ЯКОРЬ СХЕМЫ → ИСХОД возможности (Q12-1): исход обязан определяться по ТОМУ, ЧТО ПОСТАВИЛА зона
# (tpl_id/tpl_variant), а не по первой роли, попавшей в полосу. Иначе скамья у окна
# классифицировалась как edge_nook просто потому, что банкетка встречается в его ролях.
ANCHOR_OUTCOME = {
    ('reading', 'window_anchor'): 'armchair_or_pair',
    ('reading', 'bay_anchor'): 'armchair_or_pair',
    ('bay_armchair', ''): 'armchair_or_pair',
    ('window_seat', 'bench_under_window'): 'window_seat_bench',
    ('window_seat', 'bay_bench'): 'window_seat_bench',
    ('seating', ''): 'sofa_at_window',
    ('storage', 'corner_tower'): 'storage_tower',
    ('reading', 'corner_vignette'): 'reading_corner',
    ('decor', ''): 'plant',
}


def _anchor_outcome(kind: str, ps_in_zone: list) -> str | None:
    """Исход по якорю поставленной схемы (приоритетнее ролевого)."""
    ranks = _rank_map(kind)
    for p in ps_in_zone:
        tid = (getattr(p, 'tpl_id', '') or '')
        tv = (getattr(p, 'tpl_variant', '') or '').split('+')[0]
        for key in ((tid, tv), (tid, '')):
            oid = ANCHOR_OUTCOME.get(key)
            if oid and oid in ranks:
                return oid
    return None


def priors() -> dict:
    try:
        return json.load(open(os.path.abspath(_PRIORS_PATH), encoding='utf-8'))
    except Exception:
        return {'opportunities': {}, 'item_presence_pct': {}}


def _rank_map(kind: str) -> dict:
    """id исхода → ранг (0 = самый частый в практике)."""
    outs = ((priors().get('opportunities') or {}).get(kind) or {}).get('outcomes') or []
    return {o['id']: i for i, o in enumerate(outs)}


def _role_outcome(kind: str, roles: set[str]) -> str | None:
    """Первый исход паспорта приоров, чьи роли встретились в зоне (порядок = порядок практики)."""
    outs = ((priors().get('opportunities') or {}).get(kind) or {}).get('outcomes') or []
    for o in outs:
        if o.get('roles') and roles & set(o['roles']):
            return o['id']
    return None


def _band(room: Room, op) -> object:
    """Полоса перед окном глубиной WINDOW_ZONE_DEPTH_CM внутрь комнаты."""
    g = opening_polygon(room, op)
    x0, y0, x1, y1 = g.bounds
    d = WINDOW_ZONE_DEPTH_CM
    if op.wall == 'south':
        box = (x0, 0, x1, d)
    elif op.wall == 'north':
        box = (x0, room.depth_cm - d, x1, room.depth_cm)
    elif op.wall == 'west':
        box = (0, y0, d, y1)
    else:
        box = (room.width_cm - d, y0, room.width_cm, y1)
    from shapely.geometry import box as _b
    return _b(*box).intersection(room_polygon(room))


REQUIRED_ROLES = ('диван', 'тв-тумба', 'стенка', 'стол обеденный')   # обязательные/preferred зоны
# какие роли банка делают исход инвентарно возможным (Q10-0: «нечего ставить» ≠ «решили не ставить»)
OUTCOME_INVENTORY = {
    'armchair_or_pair': ('кресло',), 'window_seat_bench': ('банкетка',),
    'low_console_storage': ('комод', 'тв-тумба', 'стеллаж'), 'plants_decor': ('кашпо', 'растение'),
    'table_work_or_dining': ('стол обеденный',), 'sofa_or_loveseat': ('диван',),
    'reading_armchair': ('кресло',), 'plant': ('кашпо', 'растение'), 'floor_lamp': ('торшер',),
    'side_table_console': ('приставной', 'столик', 'комод'), 'shelving': ('стеллаж',),
    'coffee_table': ('столик',), 'ottoman_table': ('пуф',),
}


def _blocked_zone(room: Room, box) -> bool:
    """Место занято конструкцией/маршрутом: дуга двери, радиатор (Q10-0, Codex: счётчик
    свободных углов был завышен — считал углы, где физически ничего не поставить)."""
    from .geometry import radiator_polygon, swing_polygon
    for op in room.openings:
        if op.kind in ('door', 'balcony'):
            try:
                if swing_polygon(room, op).intersection(box).area > 0.25 * box.area:
                    return True
            except Exception:
                pass
    for rad in (room.radiators or []):
        try:
            if radiator_polygon(room, rad).intersects(box):
                return True
        except Exception:
            pass
    return False


def certify(room: Room, ps: list[Placement], bank_roles: set | None = None,
            attempts: dict | None = None) -> list[dict]:
    """Q10-0 (Codex 19.08): ЧЕСТНЫЙ сертификат возможности. Пустота больше не считается
    «намеренной» по умолчанию: различаем `occupied_by_required_zone` (окно занято обязательной
    зоной), `forced_empty_inventory` (в банке нечего ставить), `not_attempted` (оконного/углового
    placer'а ещё нет — Q10b/Q10e), `free_intentional` (валидный вариант БЫЛ и проиграл пустоте).
    `bank_roles` — роли банка сцены; без них состояние инвентаря = unknown."""
    out = []
    for opp in opportunities(room, ps):
        rec = dict(opp)
        rec['applicable'] = True
        sel = opp['selected_outcome']
        if sel != 'free_intentional' and sel != 'accent_wall_free':
            rec['state'] = 'selected'
            rec['selected_by'] = 'zone_placement'
            # исход занят обязательной зоной — это НЕ «выбор практики»
            if set(opp.get('roles_present') or []) & set(REQUIRED_ROLES):
                rec['state'] = 'occupied_by_required_zone'
        else:
            elig = None
            if bank_roles is not None:
                prio = ((priors().get('opportunities') or {}).get(opp['kind']) or {}).get('outcomes') or []
                elig = sorted({o['id'] for o in prio
                               if set(OUTCOME_INVENTORY.get(o['id'], ())) & set(bank_roles)})
            rec['inventory_eligible'] = elig
            # Q10-0: диагноз реальной попытки (placer сообщает, пробовал ли и почему не смог)
            att = (attempts or {}).get(opp['kind'])
            if att:
                rec['attempt'] = att
                if att.get('placed'):
                    rec['state'] = 'selected'          # поставили, но исход не распознан по ролям
                elif att.get('reject') in ('no_armchair', 'no_reading_kit'):
                    rec['state'] = 'forced_empty_inventory'
                elif att.get('reject') in ('no_valid_position', 'no_candidates'):
                    rec['state'] = 'forced_empty_geometry'
                else:
                    rec['state'] = 'not_attempted'
            elif elig is not None and not elig:
                rec['state'] = 'forced_empty_inventory'
            else:
                # placer'а для этой возможности ещё нет (угол — Q10e): честно «не пробовали»
                rec['state'] = 'not_attempted'
            rec['selected_outcome'] = 'empty'
        out.append(rec)
    return out


def opportunities(room: Room, ps: list[Placement]) -> list[dict]:
    """Список возможностей плана с выбранным исходом и доказательством (роли в зоне)."""
    out: list[dict] = []
    items = [p for p in ps if base_role(p.role) != 'ковёр']
    # --- окна
    for op in sorted((o for o in room.openings if o.kind == 'window'),
                     key=lambda o: (o.wall, o.offset_cm, o.width_cm)):
        zone = _band(room, op)
        inzone = [p for p in items if footprint(p).intersects(zone)]
        roles = {base_role(p.role) for p in inzone}
        # Q12-1: исход — сперва по ЯКОРЮ поставленной схемы, роли только как запасной путь
        oid = _anchor_outcome('window', inzone) or _role_outcome('window', roles) or 'free_intentional'
        _rad = any(r.wall == op.wall and
                   r.offset_cm < op.offset_cm + op.width_cm and
                   op.offset_cm < r.offset_cm + r.width_cm for r in (room.radiators or []))
        out.append({  # ID — из канонической сигнатуры проёма, не из порядка массива (Q12-1):
                      # при перестановке openings объяснение обязано остаться тем же
                    'opportunity_id': f'window:{op.wall}:{int(op.offset_cm)}:{int(op.width_cm)}',
                    'kind': 'window', 'anchor_type': 'window',
                    'anchor_ref': f'{op.wall}@{int(op.offset_cm)}+{int(op.width_cm)}',
                    'qualifiers': sorted(([ 'radiator_under' ] if _rad else [])
                                         + (['low_sill'] if (getattr(op, 'sill_cm', 0) or 0) < 60 else [])),
                    'selected_outcome': oid, 'roles_present': sorted(roles),
                    # чем предмет привязан к окну: зона+форма (истина) или просто попал в полосу
                    'anchored_zones': sorted({f"{getattr(p, 'tpl_id', '') or '-'}"
                                              f"/{getattr(p, 'tpl_variant', '') or '-'}" for p in inzone})})
    # --- центр посадочной группы
    sofa = next((p for p in items if base_role(p.role) == 'диван'), None)
    if sofa is not None and sofa.item is not None:
        r = math.radians(sofa.rot)
        cx = sofa.x + math.sin(r) * (sofa.item.d_cm / 2 + CENTER_REACH_CM / 2)
        cy = sofa.y + math.cos(r) * (sofa.item.d_cm / 2 + CENTER_REACH_CM / 2)
        from shapely.geometry import Point
        zone = Point(cx, cy).buffer(CENTER_REACH_CM / 2)
        roles = {base_role(p.role) for p in items if p is not sofa and footprint(p).intersects(zone)}
        oid = _role_outcome('seating_center', roles) or 'free_intentional'
        out.append({'opportunity_id': 'seating_center', 'kind': 'seating_center',
                    'anchor_type': 'object', 'anchor_ref': 'диван', 'qualifiers': [],
                    'selected_outcome': oid, 'roles_present': sorted(roles)})
        # --- главная стена (та, к которой обращён фронт дивана)
        fx, fy = math.sin(r), math.cos(r)
        wall = ('north' if fy > 0 else 'south') if abs(fy) > abs(fx) else ('east' if fx > 0 else 'west')
        from shapely.geometry import box as _b
        depth = PRIMARY_WALL_DEPTH_CM
        strip = {'north': _b(0, room.depth_cm - depth, room.width_cm, room.depth_cm),
                 'south': _b(0, 0, room.width_cm, depth),
                 'east': _b(room.width_cm - depth, 0, room.width_cm, room.depth_cm),
                 'west': _b(0, 0, depth, room.depth_cm)}[wall]
        roles = {base_role(p.role) for p in items if footprint(p).intersects(strip)}
        oid = _role_outcome('primary_wall', roles) or 'accent_wall_free'
        out.append({'opportunity_id': f'primary_wall:{wall}', 'kind': 'primary_wall',
                    'anchor_type': 'wall_segment', 'anchor_ref': wall, 'qualifiers': [],
                    'selected_outcome': oid, 'roles_present': sorted(roles)})
    # --- свободные углы
    from shapely.geometry import box as _b
    corners = {'sw': _b(0, 0, CORNER_BOX_CM, CORNER_BOX_CM),
               'se': _b(room.width_cm - CORNER_BOX_CM, 0, room.width_cm, CORNER_BOX_CM),
               'nw': _b(0, room.depth_cm - CORNER_BOX_CM, CORNER_BOX_CM, room.depth_cm),
               'ne': _b(room.width_cm - CORNER_BOX_CM, room.depth_cm - CORNER_BOX_CM,
                        room.width_cm, room.depth_cm)}
    for name, box in corners.items():
        box = box.intersection(room_polygon(room))
        if box.is_empty or box.area < 0.4 * CORNER_BOX_CM ** 2:
            continue                      # угла как места нет (контур/эркер)
        if _blocked_zone(room, box):
            continue                      # дуга двери/радиатор — «свободного угла» здесь нет
        roles = {base_role(p.role) for p in items if footprint(p).intersection(box).area > 400}
        if {'диван', 'стенка', 'стол обеденный'} & roles:
            continue                      # угол занят главной зоной — это не «свободный угол»
        _inbox = [p for p in items if footprint(p).intersection(box).area > 400]
        oid = _anchor_outcome('free_corner', _inbox) or _role_outcome('free_corner', roles) \
            or 'free_intentional'
        out.append({'opportunity_id': f'corner:{name}', 'kind': 'free_corner',
                    'anchor_type': 'corner', 'anchor_ref': name, 'qualifiers': [],
                    'selected_outcome': oid, 'roles_present': sorted(roles)})
    return out


def prior_ranks(room: Room, ps: list[Placement]) -> dict:
    """{opportunity_id: (kind, selected_outcome, rank)} — ранг исхода в приорах практики.
    Ранг = ПОРЯДОК распространённости (0 — самый частый), не вероятность и не доля."""
    out = {}
    for opp in opportunities(room, ps):
        rank = _rank_map(opp['kind']).get(opp['selected_outcome'])
        if rank is None:
            continue
        out[opp['opportunity_id']] = (opp['kind'], opp['selected_outcome'], rank)
    return out


def prior_prefers(room: Room, a: list[Placement], b: list[Placement]) -> int:
    """ЛОКАЛЬНОЕ сравнение по приорам (Q12-2, ADR-0112). Возвращает -1 (лучше a), +1 (лучше b)
    или 0 (приор не высказывается).

    Приор высказывается ТОЛЬКО когда планы различаются исходом РОВНО ОДНОЙ И ТОЙ ЖЕ возможности.
    Прежний `practice_prior_key` складывал ранги по всем возможностям — это скрытые веса
    (плохой исход у окна «компенсировался» углом, а комната с четырьмя углами меняла масштаб
    цели); суммировать ранги запрещено (`anti-patterns.md`)."""
    ra, rb = prior_ranks(room, a), prior_ranks(room, b)
    diff = [k for k in (set(ra) & set(rb)) if ra[k][1] != rb[k][1]]
    if len(diff) != 1:
        return 0                      # различий нет или их несколько — приор молчит
    k = diff[0]
    if ra[k][2] == rb[k][2]:
        return 0
    return -1 if ra[k][2] < rb[k][2] else 1


def practice_prior_key(room: Room, ps: list[Placement]) -> tuple:
    """СНЯТО (Q12-2): сумма рангов была скрытой аддитивной системой весов. Оставлено только как
    диагностика формы «сколько возможностей распознано», без влияния на выбор."""
    ranks = prior_ranks(room, ps)
    return (0, -len(ranks))
