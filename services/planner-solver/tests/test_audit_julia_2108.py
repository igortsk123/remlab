"""Аудит Юли 21.08 (план canons-audit-julia): контракты движка, введённые разбором.

№13 — armchair_pair предпочитает паспортный приставной; №27/31 — свет за плечом, не за
спинкой; №28 — в эркере торшер уходит к устью, а не выбрасывается; №41 — простенок между
окон имеет НАСТОЯЩУЮ реализацию (прод-дыра: _window_candidates центрирует по окну);
№46 — консоль короче 2/3 дивана помечается деградацией (+short)."""
from planner.models import Item, Opening, Placement, Room
from planner import template as T
from planner.zones import usable_polygon


def _door(wall='west', off=40):
    return Opening(kind='door', wall=wall, offset_cm=off, width_cm=90, swing_cm=90)


def test_armchair_pair_prefers_side_table():
    by = {'кресло': Item(role='кресло', w_cm=80, d_cm=82, h_cm=80),
          'кресло 2': Item(role='кресло 2', w_cm=80, d_cm=82, h_cm=80),
          'столик': Item(role='столик', w_cm=110, d_cm=60, h_cm=45),
          'приставной': Item(role='приставной', w_cm=45, d_cm=45, h_cm=55),
          'ковёр': Item(role='ковёр', w_cm=290, d_cm=200, h_cm=1)}
    b = T.build_block('armchair_pair', by, variant='default')
    assert b is not None
    roles = [it.role for it, *_ in b.rel]
    assert 'приставной' in roles and 'столик' not in roles


def test_reading_lamp_beside_not_behind():
    """Угловой уголок: торшер за плечом (сбоку), а не на оси спинки кресла."""
    room = Room(width_cm=440, depth_cm=420, openings=[_door()])
    items = [Item(role='кресло', w_cm=80, d_cm=82, h_cm=80),
             Item(role='торшер', w_cm=35, d_cm=35, h_cm=165),
             Item(role='приставной', w_cm=45, d_cm=45, h_cm=55)]
    ps = T.place_reading(room, items, usable_polygon(room))
    assert ps is not None
    arm = next(p for p in ps if p.role == 'кресло')
    lamp = next(p for p in ps if p.role == 'торшер')
    import math
    r = math.radians(arm.rot)
    dx, dy = lamp.x - arm.x, lamp.y - arm.y
    lateral = abs(math.cos(r) * dx - math.sin(r) * dy)     # поперёк оси взгляда
    assert lateral > 30.0, f'торшер на оси спинки (lateral={lateral:.0f})'


def test_bay_full_kit_keeps_lamp():
    """№28: полный комплект чтения в эркере больше не худеет до кресла — свет к устью."""
    room = Room(width_cm=440, depth_cm=420,
                openings=[_door(), Opening(kind='window', wall='north', offset_cm=140,
                                           width_cm=160, sill_cm=80)],
                contour=[[0, 0], [440, 0], [440, 300], [320, 300], [320, 420],
                         [120, 420], [120, 300], [0, 300]])
    items = [Item(role='кресло', w_cm=80, d_cm=82, h_cm=80),
             Item(role='торшер', w_cm=35, d_cm=35, h_cm=165),
             Item(role='приставной', w_cm=45, d_cm=45, h_cm=55)]
    ps = T.place_reading(room, items, usable_polygon(room))
    assert ps is not None
    assert any(p.role == 'торшер' for p in ps), 'торшер выброшен каскадом'


def test_between_windows_candidates_center_on_pier():
    room = Room(width_cm=560, depth_cm=430, openings=[
        _door(off=300),
        Opening(kind='window', wall='north', offset_cm=60, width_cm=120, sill_cm=80),
        Opening(kind='window', wall='north', offset_cm=380, width_cm=120, sill_cm=80)])
    stand = Item(role='тв-тумба', w_cm=150, d_cm=40, h_cm=50)
    cands = T._between_windows_candidates(room, stand, usable_polygon(room))
    assert cands, 'простенок 200 см не дал кандидата'
    # простенок 180..380 → ось 280
    assert any(abs(c.placement.x - 280) < 1.0 for c in cands)
    assert all(c.topology == 'between_windows' for c in cands)


def test_console_short_is_tagged_degraded():
    room = Room(width_cm=560, depth_cm=430, openings=[_door(off=300)])
    sofa = Placement(role='диван', x=310, y=240, rot=180,
                     item=Item(role='диван', w_cm=220, d_cm=95, h_cm=85))
    free = usable_polygon(room).difference(
        __import__('planner.geometry', fromlist=['footprint']).footprint(sofa))
    # раунд 2 (владелец 21.08): корпус с ящиками БЕЗ caps.sofa_console_capable — не консоль
    it_dresser = Item(role='комод', w_cm=150, d_cm=35, h_cm=75)
    assert T.place_console_behind_sofa(room, [it_dresser], free, fixed=[sofa]) is None
    assert T.CONSOLE_DIAG.get('reject') == 'no_console_capable_sku'
    # настоящий стол-консоль (caps) работает; короче 2/3 — явная деградация +short
    for w, short in ((150, False), (120, True)):
        it = Item(role='комод', w_cm=w, d_cm=35, h_cm=75,
                  caps={'sofa_console_capable': True})
        ps = T.place_console_behind_sofa(room, [it], free, fixed=[sofa])
        assert ps, f'консоль {w} не встала: {T.CONSOLE_DIAG}'
        v = ps[0].tpl_variant
        assert v.endswith('+short') == short, f'w={w}: variant={v}'


def test_rug_zone_eligibility_and_guard():
    """Аудит владельца 21.08 («ковёр 80×50 — такого канона нет»): недомерок выкидывается
    из сборки ДО блока (клей зоны — столик), а сторож RUG_ZONE_UNDERSIZED ловит обходные пути."""
    from planner.validate import Severity, validate
    sofa = Item(role='диван', w_cm=220, d_cm=95, h_cm=85)
    ok_rug, why = T._rug_zone_eligible(Item(role='ковёр', w_cm=290, d_cm=200, h_cm=1), sofa)
    assert ok_rug, why
    for w, d in ((80, 50), (180, 120), (120, 120)):
        bad, why = T._rug_zone_eligible(Item(role='ковёр', w_cm=w, d_cm=d, h_cm=1), sofa)
        assert not bad, f'{w}x{d} прошёл как зонный'
    # build_block: недомерок уходит в ничто, блок собирается со столиком-клеем
    by = {'диван': sofa, 'столик': Item(role='столик', w_cm=110, d_cm=60, h_cm=45),
          'ковёр': Item(role='ковёр', w_cm=80, d_cm=50, h_cm=1)}
    b = T.build_block('sofa_solo', by, variant='default')
    assert b is not None
    assert all(it.role != 'ковёр' for it, *_ in b.rel), 'накидка 80×50 вошла в блок'
    assert 'rug_ineligible' in T.RUG_DIAG
    # сторож: ковёр-недомерок прямо в зоне (обходной путь) — HARD
    room = Room(width_cm=560, depth_cm=430,
                openings=[Opening(kind='door', wall='west', offset_cm=300,
                                  width_cm=90, swing_cm=90)])
    sp = Placement(role='диван', x=280, y=60, rot=0, item=sofa)
    rp = Placement(role='ковёр', x=280, y=200, rot=0,
                   item=Item(role='ковёр', w_cm=180, d_cm=120, h_cm=1))
    codes = {v.code for v in validate(room, [sp, rp]).violations
             if v.severity is Severity.HARD}
    assert 'RUG_ZONE_UNDERSIZED' in codes
    # соразмерный ковёр — чист
    rp2 = Placement(role='ковёр', x=280, y=200, rot=0,
                    item=Item(role='ковёр', w_cm=290, d_cm=200, h_cm=1))
    codes2 = {v.code for v in validate(room, [sp, rp2]).violations
              if v.severity is Severity.HARD}
    assert 'RUG_ZONE_UNDERSIZED' not in codes2


def test_dresser_out_of_sofa_view():
    """Правило владельца 21.08: комод — только вне конуса взгляда дивана (±60°, >5% — HARD);
    исключение — компаньон медиа-инсталляции; фильтр кандидатов не даёт видимых позиций."""
    from planner.validate import Severity, validate
    room = Room(width_cm=560, depth_cm=430,
                openings=[Opening(kind='door', wall='west', offset_cm=300,
                                  width_cm=90, swing_cm=90)])
    sofa = Placement(role='диван', x=280, y=60, rot=0,
                     item=Item(role='диван', w_cm=220, d_cm=95, h_cm=85))
    dresser_front = Placement(role='комод', x=280, y=410, rot=180,
                              item=Item(role='комод', w_cm=120, d_cm=40, h_cm=80))
    codes = {v.code for v in validate(room, [sofa, dresser_front]).violations
             if v.severity is Severity.HARD}
    assert 'DRESSER_IN_SOFA_VIEW' in codes, 'комод прямо перед диваном не пойман'
    # комод ЗА спиной дивана — легален
    dresser_back = Placement(role='комод', x=100, y=20, rot=0,
                             item=Item(role='комод', w_cm=120, d_cm=40, h_cm=80))
    codes2 = {v.code for v in validate(room, [sofa, dresser_back]).violations
              if v.severity is Severity.HARD}
    assert 'DRESSER_IN_SOFA_VIEW' not in codes2
    # медиа-исключение СНЯТО (владелец 21.08): комод у ТВ нелегален даже как компаньон
    dresser_media = Placement(role='комод', x=430, y=410, rot=180,
                              item=Item(role='комод', w_cm=120, d_cm=40, h_cm=80))
    dresser_media.tpl_id = 'media'
    dresser_media.tpl_variant = 'installation'
    codes3 = {v.code for v in validate(room, [sofa, dresser_media]).violations
              if v.severity is Severity.HARD}
    assert 'DRESSER_IN_SOFA_VIEW' in codes3
    # а витрина-компаньон («дисплей») — легальна: правило только про комод
    vitr = Placement(role='витрина', x=430, y=410, rot=180,
                     item=Item(role='витрина', w_cm=80, d_cm=40, h_cm=190))
    vitr.tpl_id = 'media'; vitr.tpl_variant = 'installation'
    codes3b = {v.code for v in validate(room, [sofa, vitr]).violations
               if v.severity is Severity.HARD}
    assert 'DRESSER_IN_SOFA_VIEW' not in codes3b
    # place_storage: с диваном в fixed комод не получает видимых позиций (уходит в сторону/зад)
    from planner.zones import usable_polygon
    from planner.geometry import footprint as _fp
    free = usable_polygon(room).difference(_fp(sofa))
    ps = T.place_storage(room, [Item(role='комод', w_cm=120, d_cm=40, h_cm=80)],
                         free, fixed=[sofa])
    if ps:
        codes4 = {v.code for v in validate(room, [sofa] + list(ps)).violations
                  if v.severity is Severity.HARD}
        assert 'DRESSER_IN_SOFA_VIEW' not in codes4, 'фильтр кандидатов пропустил видимую позицию'
