"""Q6a свода №13: capability-проекция каталога (`tools/scout/capabilities.py`, правила
`tools/scout/rules/capabilities.json`). Фикстуры с контрпримерами (Codex 17.08): capability
не выводится из одних габаритов; true ⇒ достаточное evidence; unknown ≠ false; идемпотентность."""
import importlib.util
import json
import os

import pytest

SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')
_spec = importlib.util.spec_from_file_location('capabilities', os.path.join(SCOUT, 'capabilities.py'))
C = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(C)
R = C.rules()


def _row(**kw):
    base = dict(shop_mid=1, external_id='x', cat_role='пуф', category_path='', name='', w=None, d=None, h=None, params={}, enr=None)
    base.update(kw); return base


def test_rules_have_provenance_and_versions():
    assert R['_meta']['version'] and len(R['_meta']['provenance']) > 40
    for k in ('bench', 'daybed', 'shallow_storage', 'extension_mechanism', 'dining_seat', 'seats'):
        assert '_why' in R[k] or k in ('seats',), k
    assert R['extension_mechanism']['status'] == 'sleeping'


def test_bench_with_params_is_wall_and_dining_seat():
    caps, ev, pr = C.project(_row(category_path='Мебель/Пуфы и банкетки', name='Банкетка Лира', w=120, d=40, h=45,
                                  params={'Посадочное место: Длина посадочного места': '118см',
                                          'Посадочное место: Высота посадочного места': '45см'}), R)
    assert caps['wall_seat_capable']['value'] is True and caps['wall_seat_capable']['state'] == 'known'
    assert caps['dining_seat_capable']['value'] is True and caps['seat_height_cm']['source'] == 'params'
    assert caps['guaranteed_seats']['value'] == 1 and caps['nominal_seats']['value'] == 2
    assert pr == ['банкетка']
    for k, v in caps.items():
        assert {'state', 'source', 'rule_id', 'confidence'} <= set(v), k        # структура evidence
    assert 'value' not in ev['wall_seat_capable']                                 # evidence без value


def test_pouf_without_bench_name_is_not_bench_even_if_dims_fit():
    """fail-closed: габариты банкетки у «пуфа» без подтипа — не capability."""
    caps, _, pr = C.project(_row(category_path='Пуфы и банкетки', name='Пуф Куб большой', w=120, d=40, h=45), R)
    assert caps['wall_seat_capable']['value'] is False and caps['subtype']['state'] == 'unknown'
    assert pr == []


def test_bench_without_params_is_inferred_not_known():
    """17.08 (Q6b): у BACKLESS-банкетки общая высота = высота сиденья — dining_seat_capable
    выводится как `inferred` (confidence medium), иначе вся категория банкеток недостижима
    для уголка (0 годных SKU при 20 подходящих в каталоге). Для НЕ-банкеток и при неизвестной
    спинке остаётся unknown ≠ false."""
    caps, _, pr = C.project(_row(category_path='Пуфы и банкетки', name='Банкетка Норд', w=110, d=38, h=46), R)
    assert caps['wall_seat_capable']['value'] is True and caps['wall_seat_capable']['state'] == 'inferred'
    assert caps['seat_length_cm']['state'] == 'inferred' and caps['seat_length_cm']['confidence'] == 'medium'
    assert caps['dining_seat_capable']['state'] == 'inferred' and caps['dining_seat_capable']['value'] is True
    assert caps['dining_seat_capable']['confidence'] == 'medium'
    # сиденье вне вилки 42–49 → доказанное «нет», не unknown
    high, _, _ = C.project(_row(category_path='Пуфы и банкетки', name='Банкетка Барная', w=130, d=38, h=62), R)
    assert high['dining_seat_capable']['value'] is False


def test_daybed_missing_depth_is_unknown_not_false():
    caps, _, _ = C.project(_row(cat_role='диван', category_path='Кушетки', name='Кушетка Наск', w=120, d=None, h=83,
                                params={'Посадочное место: Длина посадочного места': '110см'}), R)
    assert caps['wall_seat_capable']['state'] == 'unknown' and caps['wall_seat_capable']['value'] is None


def test_daybed_too_deep_is_false_with_reason():
    caps, _, _ = C.project(_row(cat_role='диван', category_path='Кушетки', name='Кушетка Соло', w=160, d=90, h=80,
                                params={'Посадочное место: Длина посадочного места': '150см'}), R)
    assert caps['wall_seat_capable']['value'] is False and 'd>' in caps['wall_seat_capable']['reason']


def test_shallow_storage_and_wall_hung_modes():
    c1, _, _ = C.project(_row(cat_role='комод', name='Комод узкий', w=120, d=35, h=80), R)
    assert c1['shallow_storage_capable']['value'] is True and c1['front_access_kind']['value'] == 'drawers'
    assert set(c1['placement_modes']['value']) == {'wall_console', 'behind_sofa_candidate'}
    assert c1['behind_sofa_console_capable']['state'] == 'unknown'          # сертификат — только при расстановке
    c2, _, _ = C.project(_row(cat_role='тв-тумба', name='Тумба подвесная Лайн', w=150, d=35, h=40), R)
    assert c2['mounting_mode']['value'] == 'wall_hung' and c2['placement_modes']['value'] == ['wall_console']
    c3, _, _ = C.project(_row(cat_role='комод', name='Комод глубокий', w=120, d=50, h=80), R)
    assert c3['shallow_storage_capable']['value'] is False


def test_extension_mechanism_sleeping():
    c, _, _ = C.project(_row(cat_role='стол обеденный', name='Стол раскладной Орион', w=120, d=80, h=75), R)
    assert c['extension_mechanism_present']['value'] is True and c['extension_mechanism_present']['status'] == 'sleeping'
    c2, _, _ = C.project(_row(cat_role='стол обеденный', name='Стол Орион', w=120, d=80, h=75,
                              params={'Механизм трансформации': 'без механизма'}), R)
    assert c2['extension_mechanism_present']['value'] is False and c2['extension_mechanism_present']['state'] == 'known'


def test_input_hash_stable():
    r = _row(category_path='Пуфы и банкетки', name='Банкетка', w=110, d=38, h=46, params={'a': '1'})
    assert C._input_hash(r) == C._input_hash(json.loads(json.dumps(r)))


def test_true_capabilities_have_evidence():
    """true ⇒ достаточное evidence: state ≠ unknown и source ≠ none."""
    rows = [_row(category_path='Пуфы и банкетки', name='Банкетка А', w=120, d=40, h=45,
                 params={'Посадочное место: Длина посадочного места': '118см'}),
            _row(cat_role='комод', name='Комод', w=120, d=35, h=80)]
    for r in rows:
        caps, _, _ = C.project(r, R)
        for k, v in caps.items():
            if v.get('value') is True:
                assert v['state'] in ('known', 'inferred') and v['source'] != 'none', k


def test_pipeline_wiring():
    for f in ('refresh_daily.sh', 'enrich_wait.sh'):
        assert 'capabilities.py --build' in open(os.path.join(SCOUT, f), encoding='utf-8').read(), f
