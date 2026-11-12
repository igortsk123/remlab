"""P2 свода №12: beam по планировочным гипотезам — инварианты.

- greedy-результат всегда гипотеза №0 (среди кандидатов);
- выбранный план лексикографически не хуже greedy по plan_key;
- детерминизм: два запуска — одинаковый выбор и ключ;
- enumerate_k: первый вариант == single-результат place_template;
- конфиг beam с пруфом.
"""
import json
import os

RULES = os.path.join(os.path.dirname(__file__), '..', 'rules')


def _scene():
    from planner.models import Item, Room
    room = Room(width_cm=520, depth_cm=430, openings=[])
    items = [Item(role='диван', w_cm=220, d_cm=95, h_cm=85),
             Item(role='кресло', w_cm=80, d_cm=85, h_cm=80),
             Item(role='столик', w_cm=110, d_cm=60, h_cm=45),
             Item(role='ковёр', w_cm=240, d_cm=170, h_cm=1),   # 17.08: без допусков (сдвиг столика снят) канон sofa_armchair требует ковёр под всю группу
             Item(role='тв-тумба', w_cm=160, d_cm=45, h_cm=50),
             Item(role='стол обеденный', w_cm=120, d_cm=75, h_cm=75),
             Item(role='стул', w_cm=45, d_cm=50, h_cm=90),
             Item(role='стул 2', w_cm=45, d_cm=50, h_cm=90),
             Item(role='стеллаж', w_cm=80, d_cm=35, h_cm=180)]
    return room, items


def test_beam_config_has_proof():
    z = json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))
    b = z['beam']
    assert b['enabled'] is True
    assert 1 <= int(b['ladder_steps']) <= 6 and 1 <= int(b['blocks_per_step']) <= 8
    assert 'greedy' in b['_why'].lower() or 'гипотез' in b['_why']


def test_enumerate_first_equals_single():
    from planner.template import place_template
    from planner.zones import usable_polygon
    room, items = _scene()
    one = place_template(room, 'sofa_armchair', items, usable_polygon(room))
    many = place_template(room, 'sofa_armchair', items, usable_polygon(room), enumerate_k=4)
    assert one and many and len(many) >= 1
    k = lambda ps: [(p.role, round(p.x), round(p.y), int(p.rot) % 360) for p in ps]
    assert k(many[0]) == k(one), 'первый вариант перечисления обязан совпадать с single'


def test_greedy_is_hypothesis_zero_and_not_worse():
    from planner.zones import solve_zoned, solve_zoned_beam
    room, items = _scene()
    outs_b, gid_b = solve_zoned_beam(room, items)
    outs_g, gid_g = solve_zoned(room, items)
    assert outs_b and outs_b[0].placements
    bm = outs_b[0].meta.get('beam')
    assert bm and bm['hypotheses'][0]['name'] == 'greedy'
    assert bm['hypotheses'][0]['gid'] == gid_g
    assert tuple(bm['chosen_key']) <= tuple(bm['greedy_key'])


def test_beam_deterministic():
    from planner.zones import solve_zoned_beam
    room, items = _scene()
    a, ga = solve_zoned_beam(room, items)
    b, gb = solve_zoned_beam(room, items)
    assert ga == gb
    ka = a[0].meta['beam']['chosen_key']; kb = b[0].meta['beam']['chosen_key']
    assert ka == kb and a[0].meta['beam']['chosen'] == b[0].meta['beam']['chosen']
    pa = [(p.role, round(p.x), round(p.y)) for p in a[0].placements]
    pb = [(p.role, round(p.x), round(p.y)) for p in b[0].placements]
    assert pa == pb


def test_plan_key_prefers_canonical_over_tolerated_table():
    """Codex 17.08 (владелец №31 set16-base): при равных верхних ярусах канон (столик по центру,
    номинальный зазор) выигрывает у допуска (+table_axis_shifted / +gap32|48) даже при чуть лучшем
    мягком терме — template_degradation стоит выше lexo-термов в v1 и v2."""
    from planner.zones import template_degradation
    from planner.models import Item, Placement

    def _p(role, var, tpl='seating'):
        p = Placement(role=role, x=0, y=0, rot=0, item=Item(role=role, w_cm=100, d_cm=60, h_cm=45))
        p.tpl_id = tpl; p.tpl_variant = var
        return p
    assert template_degradation([_p('столик', 'default')]) == (0, 0)
    assert template_degradation([_p('столик', 'default+gap36')]) == (1, 1)
    assert template_degradation([_p('столик', 'default+table_axis_shifted')]) == (2, 1)
    assert template_degradation([_p('столик', 'default+gap48'), _p('диван', 'default+gap48')]) == (2, 2)
    assert template_degradation([_p('кресло', 'quiet_chat+table_axis_shifted', tpl='quiet')]) == (0, 0)  # только seating
    import inspect
    from planner import zones as Z
    src_v1 = inspect.getsource(Z.plan_key); src_v2 = inspect.getsource(Z.plan_key_v2)
    for src in (src_v1, src_v2):
        assert 'template_degradation(ps)' in src and 'lk[1:]' in src
        assert src.index('template_degradation(ps)') < src.index('lk[1:]'), 'деградация — до мягких термов'


def test_light_missing_tier_prefers_light_over_dining():
    """T-20261112-98: носитель света (торшер или комод под лампу, zones.json light_carriers) в банке есть, а в плане нет —
    ярус light_missing=1; план со светом выигрывает у плана со столовой (стол — preferred, хранение в have не считалось),
    но не у плана с лучшим маршрутом. Носителя в банке нет — ярус нейтрален (0 у всех)."""
    from types import SimpleNamespace
    from planner import zones as Z
    from planner.models import Item, Placement

    def _lay(*roles):
        return SimpleNamespace(placements=[Placement(role=r, x=0, y=0, item=Item(role=r, w_cm=90, d_cm=45, h_cm=80))
                                           for r in roles])
    lamp = ['лампа', 'ковёр']
    assert Z.light_carrier_roles(lamp) == {'торшер', 'комод'}
    bank = [Item(role=r, w_cm=90, d_cm=45, h_cm=80) for r in ('диван', 'комод', 'стол обеденный')]
    assert Z.light_missing(_lay('диван', 'стол обеденный'), bank, lamp) == 1
    assert Z.light_missing(_lay('диван', 'комод'), bank, lamp) == 0
    assert Z.light_missing(_lay('диван', 'торшер 2'), bank, lamp) == 0           # базовая роль
    assert Z.light_missing(_lay('диван'), bank[:1] + bank[2:], lamp) == 0        # в банке нечем светить — нейтрально
    assert Z.light_missing(_lay('диван'), None, lamp) == 0                       # старые вызовы без items
    import inspect
    src = inspect.getsource(Z.plan_key)
    ret = src[src.index('return (hard'):]
    assert ret.index('main_route_tier') < ret.index('light_missing') < ret.index('-covered_pref'), \
        'свет — после маршрута, до богатства состава'
    # все гипотезы beam — с банком и декором набора
    assert inspect.getsource(Z._solve_zoned_beam_inner).count("items=items, decor_roles=kw.get('decor_roles'))))") == 3


def test_dresser_is_light_only_with_lamp():
    """T-20261112-98/2 (условие Codex ②): комод — носитель света только под лампу (zones.json light_carriers.requires_decor).
    В наборе нет лампы (или декор не передан) — комод не свет, ступень не срабатывает; торшер — свет всегда."""
    from types import SimpleNamespace
    from planner import zones as Z
    from planner.models import Item, Placement

    def _lay(*roles):
        return SimpleNamespace(placements=[Placement(role=r, x=0, y=0, item=Item(role=r, w_cm=90, d_cm=45, h_cm=80))
                                           for r in roles])
    req = (Z.zone_rules()['zone_priority']['light_carriers'].get('requires_decor') or {})
    assert req.get('комод') == ['лампа'], 'правило «комод + лампа» — в данных'
    assert Z.light_carrier_roles(['ковёр', 'ваза']) == {'торшер'}
    assert Z.light_carrier_roles(None) == {'торшер'}
    bank = [Item(role=r, w_cm=90, d_cm=45, h_cm=80) for r in ('диван', 'комод', 'стол обеденный')]
    for decor in (None, [], ['ковёр', 'ваза', 'шторы']):
        assert Z.light_missing(_lay('диван', 'стол обеденный'), bank, decor) == 0, decor    # ступень не срабатывает
        assert Z.light_missing(_lay('диван', 'комод'), bank, decor) == 0, decor
    assert Z.light_missing(_lay('диван', 'стол обеденный'), bank, ['лампа']) == 1
    bank_t = bank + [Item(role='торшер', w_cm=40, d_cm=40, h_cm=160)]
    assert Z.light_missing(_lay('диван', 'стол обеденный'), bank_t, None) == 1           # торшер лампы не требует


def _key_scene():
    """Два готовых плана одной комнаты 600×500 без проёмов: одинаковая посадка и медиа; у одного — комод у стены, у другого —
    обеденный стол со стульями. Целые ключи `plan_key` (T-98/2, Codex: сравнение ключей целиком, а не одного яруса)."""
    from planner.models import Item, Layout, Placement, Room
    room = Room(width_cm=600, depth_cm=500, openings=[])

    def P(role, x, y, w, d, h, rot=0):
        return Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))
    seat = [P('диван', 200, 450, 220, 95, 85), P('столик', 200, 340, 100, 55, 45), P('тв-тумба', 200, 25, 160, 45, 50)]
    light = Layout(room=room, placements=seat + [P('комод', 560, 250, 45, 100, 85, rot=90)])
    dining = Layout(room=room, placements=seat + [P('стол обеденный', 480, 250, 120, 80, 75),
                                                  P('стул', 480, 175, 45, 50, 90), P('стул 2', 480, 325, 45, 50, 90)])
    bank = [Item(role=r, w_cm=90, d_cm=45, h_cm=80)
            for r in ('диван', 'столик', 'тв-тумба', 'комод', 'стол обеденный', 'стул', 'стул 2')]
    return room, light, dining, bank


def test_plan_key_full_compare_light_vs_dining():
    """T-98/2 ③: сравнение двух ключей ЦЕЛИКОМ. Стол preferred + лампа в наборе → план с комодом лучше плана со столом;
    стол required (кухня-гостиная) → план со столом лучше (missing_req выше света); без лампы → свет не в счёт, выигрывает стол;
    маршрут хуже у плана со светом → выигрывает стол (проход выше света)."""
    from planner import zones as Z
    room, light, dining, bank = _key_scene()
    lamp = ['лампа', 'ковёр']
    pref = Z.scenario_needs(dining_need='preferred')
    req = Z.scenario_needs(dining_need='required')
    assert Z.main_route_tier(room, light) == Z.main_route_tier(room, dining), 'предпосылка: маршрут одинаков'
    kl, kd = Z.plan_key(room, light, pref, items=bank, decor_roles=lamp), Z.plan_key(room, dining, pref, items=bank, decor_roles=lamp)
    assert kl[0] == kd[0] == 0 and kl[1] == kd[1] == 0
    assert kl < kd, (kl, kd)                                                     # свет вытесняет столовую (preferred)
    assert Z.plan_key(room, dining, req, items=bank, decor_roles=lamp) < \
        Z.plan_key(room, light, req, items=bank, decor_roles=lamp)              # кухня-гостиная: стол остаётся
    assert Z.plan_key(room, dining, pref, items=bank, decor_roles=['ковёр']) < \
        Z.plan_key(room, light, pref, items=bank, decor_roles=['ковёр'])        # комод без лампы — не свет
    _orig = Z.main_route_tier
    try:                                                                         # маршрут выше света
        Z.main_route_tier = lambda r, lay: 1 if lay is light else 0
        assert Z.plan_key(room, dining, pref, items=bank, decor_roles=lamp) < \
            Z.plan_key(room, light, pref, items=bank, decor_roles=lamp)
    finally:
        Z.main_route_tier = _orig


def test_kitchen_living_room_kind_needs_dining_required():
    """T-98/2 ①: кухня-гостиная → dining_need=required — одно правило (zones.json scenario_needs.by_room_kind) для всех
    вызовов (тур/«Этажи»/новая загрузка — `trial_demo.run_solver`, /demo — `flat215_demo.solve_layouts`, оба через env
    SCENE_ROOM_KIND/SCENE_ROOM_TITLE → `tools/scout/solver_run.py` → `room_kind_needs`)."""
    from planner import zones as Z
    assert Z.room_kind_of('kitchen_living') == 'kitchen_living'
    assert Z.room_kind_of('living', 'Kitchen-living room') == 'kitchen_living'          # разбор плана: kind=living, имя
    assert Z.room_kind_of(None, 'Кухня-гостиная 24 м²') == 'kitchen_living'
    assert Z.room_kind_of('living', 'Гостиная 14.4 м²') == 'living'
    assert Z.room_kind_of(None, None) == 'living'
    assert Z.room_kind_needs('living', 'Kitchen-living room') == {'dining_need': 'required'}
    assert Z.room_kind_needs('living', 'Living room') == {}
    assert Z.scenario_needs(**Z.room_kind_needs(None, 'Кухня-гостиная'))['dining'] == 'required'


def test_living_dining_titles_need_table():
    """T-20261112-98/3 (владелец «Да», TG 1207): гостиная-столовая — стол обязателен, как в кухне-гостиной; просто гостиная — нет.
    «Dining room» / «Столовая» отдельно — тоже да (то же слово; комнату взяли под гостиную — стол по смыслу обязателен)."""
    from planner import zones as Z
    yes = ['Living/Dining room', 'Living / Dining Room', 'Living-dining room', 'Гостиная-столовая', 'Гостиная-столовая 22 м²',
           'Столовая', 'Dining room', 'Kitchen/Living/Dining', 'Kitchen-living room']
    no = ['Living room', 'Living', 'Lounge', 'Reception Room', 'Sitting room', 'Гостиная', 'Гостиная 14.4 м²', 'Зал', '']
    assert [t for t in yes if Z.room_kind_of('living', t) != 'kitchen_living'] == []
    assert [t for t in no if Z.room_kind_of('living', t) != 'living'] == []
    assert Z.room_kind_needs('living', 'Living/Dining room') == {'dining_need': 'required'}
    assert Z.room_kind_needs('living', 'Lounge') == {}


def test_kitchen_living_keeps_table_with_light_carrier_in_bank():
    """T-98/2 ①: кухня-гостиная с носителем света (комод + лампа) в банке — решатель целиком (beam) оставляет стол."""
    from planner import zones as Z
    from planner.models import Item, Room
    room = Room(width_cm=440, depth_cm=340, openings=[])
    items = [Item(role='диван', w_cm=200, d_cm=90, h_cm=85),
             Item(role='столик', w_cm=90, d_cm=50, h_cm=45),
             Item(role='тв-тумба', w_cm=150, d_cm=40, h_cm=50),
             Item(role='комод', w_cm=100, d_cm=45, h_cm=85),
             Item(role='стол обеденный', w_cm=110, d_cm=70, h_cm=75),
             Item(role='стул', w_cm=45, d_cm=50, h_cm=90),
             Item(role='стул 2', w_cm=45, d_cm=50, h_cm=90)]
    need = Z.room_kind_needs('living', 'Kitchen-living room')
    outs, _ = Z.solve_zoned_beam(room, items, top_k=1, decor_roles=['лампа'], **need)
    roles = {p.role.split(' ')[0] for p in outs[0].placements}
    assert 'стол' in roles, roles
