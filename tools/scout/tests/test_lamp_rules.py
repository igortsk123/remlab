"""Правила ламп спальни (T-20261117-13, владелец TG 1382, шаг 2 bedroom-life-01): нижняя граница полосы высоты — данными (`band_min`),
запас у соседнего стиля — когда своих ламп (с моделью, влезающих) нет; лампа соседа помечена `style_from`, своя — нет.
Без сети и моделей: товары синтетические, проверка модели подменена.
    ~/venvs/scout/bin/python -m pytest -q -p no:cacheprovider tools/scout/tests/test_lamp_rules.py"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import compose_common as CC  # noqa: E402
import dependent_decor as DD  # noqa: E402

RULES = os.path.join(HERE, '..', 'rules', 'bedroom-composition.json')
DRESSER = {'role': 'комод', 'x': 60.0, 'y': 120.0, 'rot': 90, 'w': 120.0, 'd': 45.0, 'h': 80.0, 'sku': {'name': 'Комод Берг'}}
SOFA = {'role': 'диван', 'x': 250.0, 'y': 300.0, 'rot': 180, 'w': 200.0, 'd': 90.0, 'h': 80.0, 'sku': {'name': 'Диван'}}
ROOM = (500, 400)
TOL = (0.8, 1.1)


def lamp(eid, h=40, name='Лампа настольная'):
    return {'mid': 9, 'eid': str(eid), 'name': f'{name} {eid}', 'w': 25, 'd': 25, 'h': h, 'price': 4000}


def sets_for(style: str, *lamps):
    return {'style': style, 'items': {('лампа' if k == 0 else f'лампа {k + 1}'): it for k, it in enumerate(lamps)}}


def any_model(it):
    return True, None


def nb_scandi(style):
    return {'джапанди': ['сканди', 'минимализм'], 'лофт': ['джапанди', 'современный']}.get(style, [])


def test_band_min_lowers_floor_only_and_is_optional():
    slot = {'ideal': {'h': 45}, 'band': ['h']}
    assert CC.band_of(slot, TOL) == {'h': [36.0, 49.5]}                              # без band_min — как было
    assert CC.band_of(dict(slot, band_min={'h': 33}), TOL) == {'h': [33.0, 49.5]}    # нижняя граница ниже, верх не тронут
    assert CC.band_of(dict(slot, band_min={'h': 40}), TOL) == {'h': [36.0, 49.5]}    # выше расчётной не поднимает
    assert CC.band_of(dict(slot, band_min={'w': 10}), TOL) == {'h': [36.0, 49.5]}    # чужая сторона — игнор


def test_rules_file_has_lamp_band_from_33_and_neighbour_spare_everywhere():
    doc = json.load(open(RULES, encoding='utf-8'))
    n = 0
    for name, purpose in doc['purposes'].items():
        dc = (purpose.get('decor') or {}).get('лампа')
        if not dc:
            continue
        n += 1
        assert dc['band_min'] == {'h': 33}, name
        assert dc['neighbour_spare'] is True, name
        assert CC.band_of(dict(dc, role='лампа'), TOL)['h'] == [33.0, 49.5], name
    assert n >= 1


def test_own_lamp_wins_no_style_from():
    sets = [sets_for('джапанди', lamp(1)), sets_for('сканди', lamp(2))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model, neighbours=nb_scandi)
    assert it['eid'] == '1' and 'style_from' not in it and pls


def test_no_own_lamp_takes_neighbour_marked_style_from():
    sets = [sets_for('джапанди'), sets_for('сканди', lamp(2))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model, neighbours=nb_scandi)
    assert it and it['eid'] == '2' and it['style_from'] == 'сканди' and pls
    # без запаса (neighbours не передан) — как раньше: лампы нет
    none, no_pls, _ = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model)
    assert none is None and no_pls is None


def test_own_lamp_without_model_falls_to_neighbour_in_order():
    sets = [sets_for('лофт', lamp(1)), sets_for('джапанди', lamp(2)), sets_for('современный', lamp(3))]

    def model(it):
        return (None, 'нет модели на сервере') if it['eid'] == '1' else (True, None)
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, model, neighbours=nb_scandi)
    assert it['eid'] == '2' and it['style_from'] == 'джапанди'                       # порядок соседей — данными: джапанди раньше современного
    assert any('нет модели на сервере' in w for w in why)


def test_lamp_already_borrowed_in_neighbour_keeps_real_origin():
    """Лампа лофта из набора джапанди, которая сама взята у сканди, остаётся «из сканди» — цепочка не прячет настоящий стиль."""
    sets = [sets_for('лофт'), sets_for('джапанди', dict(lamp(2), style_from='сканди'))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model, neighbours=nb_scandi)
    assert it['eid'] == '2' and it['style_from'] == 'сканди'


def test_neighbour_without_model_too_means_no_lamp_and_honest_journal():
    sets = [sets_for('лофт', lamp(1)), sets_for('джапанди', lamp(2))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, lambda i: (None, 'нет модели на сервере'), neighbours=nb_scandi)
    assert it is None and pls is None and len([w for w in why if 'нет модели' in w]) == 2


def test_neighbour_style_from_survives_in_sku():
    """`flat215_demo._sku` кладёт `style_from` в товар строки декора (причина видна в данных набора)."""
    import flat215_demo as FD
    sk = FD._sku({'лампа': dict(lamp(2), style_from='сканди')}, 'лампа')
    assert sk['style_from'] == 'сканди'
    assert 'style_from' not in FD._sku({'лампа': lamp(2)}, 'лампа')


# ---- сборщик спальни: лампа с моделью раньше лампы без модели (T-20261118-04/4, владелец П1.70)
import compose_bedroom as CB  # noqa: E402
import demo_room  # noqa: E402
import room_ready as RR  # noqa: E402


class _Lay:
    placements = []        # тумб нет в раскладке — лампы на тумбы не ставим, проверяем только выбор товара


ALL_STYLES = {x: 1.0 for x in ('сканди', 'современный', 'минимализм', 'лофт', 'джапанди', 'неоклассика')}   # вне своего стиля — ниже порога


def _ldecor(eid, style, price=4000, mesh=None, h=40):
    return {'mid': 9, 'eid': str(eid), 'sid': f'9:{eid}', 'role': 'лампа', 'name': f'Светильник настольный Лампа {eid}', 'w': 12, 'd': 12,
            'h': h, 'price': price, 'mesh': mesh, 'styles': dict(ALL_STYLES, **{style: 9.0}), 'fam': str(eid), 'cls': 'neutral_light', 'cls2': 'neutral_light',
            'rgb': [235, 235, 230]}


def _pick(decor, style, purpose='couple', quarantined=()):
    R = copy.deepcopy(CB.rules())
    R['purposes'][purpose]['decor'] = {'лампа': R['purposes'][purpose]['decor']['лампа']}      # только лампа: ковёр/шторы здесь не нужны
    ready = {d['sid'] for d in decor if d['mesh'] == 'ready'}
    gen = {d['sid'] for d in decor if d['mesh'] == 'generated'}       # Composer метит меш по этим множествам
    comp = CB.Composer([], decor, ready, gen, R, CB.tolerance(), 6.6, quarantined=set(quarantined))
    picks, _alts, gaps, _lay, _slots, _rx = comp.decor_pick(purpose, style, 'комфорт', {}, _Lay(), type('R', (), {'openings': []})(),
                                                          {'тумба прикроватная': {'qty': 2}})
    return picks.get('лампа'), gaps


def _nb(style):
    return demo_room.neighbour_styles(style)[0]


def test_own_lamp_with_mesh_stays_own():
    st = 'лофт'
    it, gaps = _pick([_ldecor(1, st, mesh='ready'), _ldecor(2, _nb(st), mesh='ready')], st)
    assert it['eid'] == '1' and not it.get('style_from') and not any('взята у соседа' in g for g in gaps)


def test_own_lamp_without_mesh_loses_to_neighbour_with_mesh():
    st = 'лофт'
    it, gaps = _pick([_ldecor(1, st), _ldecor(2, _nb(st), mesh='generated')], st)
    assert it['eid'] == '2' and it['style_from'] == _nb(st)
    assert any('есть модель' in g for g in gaps)


def test_quarantined_own_lamp_counts_as_no_model():
    st = 'лофт'
    it, gaps = _pick([_ldecor(1, st, mesh='generated'), _ldecor(2, _nb(st), mesh='ready')], st, quarantined={'9:1'})
    assert it['eid'] == '2' and it['style_from'] == _nb(st)                    # карантин → как «нет модели» → лампа соседа с моделью
    it, _ = _pick([_ldecor(1, st, mesh='generated'), _ldecor(2, _nb(st), mesh='ready')], st)
    assert it['eid'] == '1'                                                     # без карантина — своя с моделью, как было


def test_no_lamp_with_mesh_anywhere_keeps_own_so_cell_waits_for_model():
    st = 'лофт'
    it, gaps = _pick([_ldecor(1, st), _ldecor(2, _nb(st))], st)
    assert it['eid'] == '1' and not it.get('style_from') and it.get('mesh') is None


def test_no_own_lamps_prefers_neighbour_with_mesh_over_first_neighbour():
    st = 'лофт'
    nbs = demo_room.neighbour_styles(st)
    assert len(nbs) >= 2
    it, _ = _pick([_ldecor(1, nbs[0]), _ldecor(2, nbs[1], mesh='ready')], st)
    assert it['eid'] == '2' and it['style_from'] == nbs[1]
    it, _ = _pick([_ldecor(1, nbs[0])], st)              # нигде нет модели — первый сосед, как было
    assert it['eid'] == '1' and it['style_from'] == nbs[0]


def test_rules_have_mesh_first_and_dep_gate_in_bank_rules():
    doc = json.load(open(RULES, encoding='utf-8'))
    assert all(p['decor']['лампа']['mesh_first'] is True for p in doc['purposes'].values() if (p.get('decor') or {}).get('лампа'))
    bank = json.load(open(os.path.join(HERE, '..', 'rules', 'bank-candidate.json'), encoding='utf-8'))
    assert bank['rooms']['bedroom']['dep_gate'] == ['лампа'] and bank['rooms']['bedroom']['dep_gate_demand'] is True        # директор 18.11: спрос мешей штатно


def _facts(demand=False):
    rows = {'1:a': {'status': 'ready', 'asset_id': 'a:' + 'f' * 64, 'mesh_id': '1_a', 'local_path': '/x/m.glb', 'representative_offer_id': None,
                    'via_family': False, 'generation_key': 'g', 'revision_key': 'r', 'source_sha': 's', 'orientation': None, 'passport': None,
                    'local_3d': True, 'solver': True, 'appearance': True, 'published_3d': True, 'reasons': [], 'warnings': [],
                    'snapshot_id': 'snap' * 4}}
    return RR.Facts(rows, '', {'1_a'}, {}, 'orient', ('лампа',), demand)


def test_cell_with_usable_lamp_is_ready_cell_with_lamp_without_model_waits_without_paid_demand():
    F = _facts()
    assert RR.classify('лампа', '1:a', None, F)[0] == 'ready' and RR.classify('лампа 2', '1:a', None, F)[0] == 'ready'
    t, why, need = RR.classify('лампа', '9:z', None, F)
    assert t == 'wait_asset' and why and need is None                 # ждёт, но платный меш в спрос не встаёт
    assert RR.classify('лампа', '9:z', None, _facts(True))[2] == 'mesh'
    assert RR.classify('лампа', '9:z', None, RR.Facts({}, '', set(), {}))[0] == 'ready'     # без dep_gate — как было


def test_lamp_without_model_goes_to_mesh_demand_once_per_product(monkeypatch):
    """Директор 18.11: dep_gate_demand=true — лампа без модели у ячейки → need=mesh, в спросе ровно один раз на товар (на семейство),
    лампа с моделью и прочее готовое в спрос не идёт."""
    import bank_pending as BP
    import room_bank_spec as RBS
    monkeypatch.setattr(BP, 'SPEC', RBS.for_room('bedroom'))
    F = _facts(True)

    def cell(i, lamp_eid, style='сканди', tier='комфорт'):
        it = {'mid': 1, 'eid': 'a', 'url': 'u/1:a'}
        return {'room_id': f'bedroom-{i}', 'purpose': 'couple', 'band': '13.2', 'style': style, 'tier': tier, 'set_id': f'bed-{i}',
                'items': {'кровать': dict(it), 'лампа': {'mid': 9, 'eid': lamp_eid, 'url': f'u/9:{lamp_eid}'},
                          'лампа 2': {'mid': 9, 'eid': lamp_eid, 'url': f'u/9:{lamp_eid}'}}}
    cand = [cell(1, 'z'), cell(2, 'z'), cell(3, 'y', 'лофт', 'премиум')]
    # у кровати 1:a модель годна; лампы 9:z и 9:y в привязке нет
    state, _ = BP.update({}, cand, F, now=1000)
    assert all(c['status'] == 'wait_asset' and c['mesh_missing'] == 1 for c in state['cells'].values())
    dem = BP.demand(state, set(), set())
    assert sorted(d['sku'] for d in dem) == ['9:y', '9:z']                      # по одному разу на товар: две ячейки с 9:z и «лампа 2» — один заказ
    assert BP.update({}, [cell(1, 'z')], _facts(False), now=1000)[0]['cells'].popitem()[1]['mesh_missing'] == 0   # флаг выключен — спроса нет
