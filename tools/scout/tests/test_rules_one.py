"""ОДИН НАБОР ПРАВИЛ ДЛЯ ДЕМО И ДЛЯ ЗАГРУЖЕННОГО ПЛАНА (T-20261112-96; владелец TG 940/942: «если завтра я загружу новый план на
лендинге — планировка должна создаться по ВСЕМ отработанным правилам»).

Тест красный, если путь демо (`flat215_demo` + ночная сборка банка спальни `compose_bedroom`) и путь тура загруженного плана
(`trial_bundle.build`, `trial_bedroom`) разошлись в решении правила:
  - поля 3D-сцены у товара — подкраска цветового варианта `tint`, разворот модели `yaw`, «подвесная» `hung`, плоскость
    зеркала/картины `strategy`, семья цветов `fam`: одни и те же товары через `flat215_demo.annotate_*` и через `trial_bundle.build`;
  - предмет решателя спальни (название → тип шкафа, боковая спинка кровати): тур передаёт решателю то же, что сборка банка демо;
  - предпроверка тура «кровать с проходами влезает» не строже движка: на спальнях демо-квартиры flat215 и планов из объявлений
    (`tools/floorplan/gold/*.json`) там, где движок ставит кровать, тур её не отсекает.
Новое правило в одном пути без другого — этот тест должен покраснеть; правило добавляйте в общий код (`sku_scene`,
`compose_bedroom.solver_item`, `bedroom_checks.bed_clear_min`), а не копией."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
ROOT = os.path.join(SCOUT, '..', '..')
sys.path.insert(0, SCOUT)
sys.path.insert(0, os.path.join(ROOT, 'services', 'planner-solver'))
import compose_bedroom as CB  # noqa: E402
import flat215_demo as FD  # noqa: E402
import mesh_color_check as MCC  # noqa: E402
import sku_scene as SS  # noqa: E402
import trial_bedroom as TBR  # noqa: E402
import trial_bundle as TB  # noqa: E402

# ───────────────────────── поля 3D-сцены: один товар — одно решение на обоих путях ─────────────────────────

SOFA, TV, MIRROR = '1_2', '3_4', '5_6'
GOODS = {SOFA: {'name': 'Диван Викс Латте', 'price': 25990, 'img': 'img/aaaaaaaaaaaaaaaa.jpg', 'url': 'https://shop.example/s', 'shop': 'a'},
         TV: {'name': 'Тумба ТВ подвесная Ларс', 'price': 9990, 'img': 'img/bbbbbbbbbbbbbbbb.jpg', 'url': 'https://shop.example/t', 'shop': 'b'},
         MIRROR: {'name': 'Зеркало Круг', 'price': 1990, 'img': 'img/cccccccccccccccc.jpg', 'url': 'https://shop.example/m', 'shop': 'c'}}
ROLE_SID = {'диван': SOFA, 'тумба тв': TV, 'зеркало': MIRROR}
MSID = {SOFA: '9_rep', TV: TV, MIRROR: MIRROR}                   # диван — цветовой вариант на модели представителя 9_rep
TONES = {'aaaaaaaaaaaaaaaa.jpg': (0.30, 0.22, 0.16), 'bbbbbbbbbbbbbbbb.jpg': (0.5, 0.5, 0.5), 'cccccccccccccccc.jpg': (0.6, 0.6, 0.6)}
REP_TONES = {'9_rep': (0.80, 0.76, 0.70)}                       # фото представителя — его нет среди товаров страницы
ORIENT = {'9_rep': {'yaw': 90}, TV: {'yaw': 180}}
OVER = {MIRROR: {'yawDeg': 270}}                                 # ручная поправка сильнее калибровки
FAMILY = {SOFA: '9_fam'}                                         # семья цветов ≠ модели сцены → `fam`


@pytest.fixture
def sources(monkeypatch):
    """Живые источники (сеть, база, фото) — одни и те же подставные для обоих путей."""
    monkeypatch.setattr(SS, 'orient_tables', lambda orient=None, over=None: (ORIENT, OVER))
    monkeypatch.setattr(SS, 'tone', lambda path: TONES.get(os.path.basename(path)))
    monkeypatch.setattr(SS, 'rep_tones', lambda need: {m: REP_TONES[m] for m in need if m in REP_TONES})
    monkeypatch.setattr(FD, '_rep_tones', lambda need: {m: REP_TONES[m] for m in need if m in REP_TONES})
    monkeypatch.setattr(MCC, 'load_table', lambda R=None: ({}, 'test'))
    monkeypatch.setattr(FD, '_mesh_rep', lambda: dict(FAMILY))


def _tour() -> dict:
    """Тур загруженного плана: гостиная 5×4 м, сцена с тремя товарами — `trial_bundle.build` с живой частью `scene_live`."""
    rect = [[0, 0], [500, 0], [500, 400], [0, 400]]
    res = {'version': 1, 'units': 'cm', 'source': {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 1, 'imageH': 1},
           'scale': {'status': 'listing', 'ppm': 50, 'inliers': 3, 'n': 3}, 'flags': [], 'timings': {}, 'costUsd': 0,
           'panels': [{'id': 'p0', 'title': 'Plan 1', 'walls': [{'z0': 0, 'z1': 270, 'polys': []}],
                       'rooms': [{'id': 'r1', 'name': 'Lounge', 'kind': 'living', 'contour': rect, 'bbox': {'x': 0, 'y': 0, 'w': 500, 'd': 400},
                                  'areaM2': 20.0, 'flags': []}],
                       'openings': [{'kind': 'window', 'c': [250, 0], 'widthCm': 120, 'exterior': False},
                                    {'kind': 'door', 'c': [500, 200], 'widthCm': 90, 'exterior': False}]}]}
    rows = [{'role': r, 'name': f'{r} A', 'mid': s.split('_')[0], 'eid': s.split('_')[1], 'sid': s, 'w': 100.0, 'd': 40.0, 'h': 60.0,
             'x': 100.0 + 100 * i, 'y': 100.0, 'rot': 0.0, 'corner': False} for i, (r, s) in enumerate(ROLE_SID.items())]
    place = [{'role': r['role'], 'x': r['x'], 'y': r['y'], 'rot': 0.0, 'w': r['w'], 'd': r['d'], 'h': r['h'], 'elev': 0.0, 'corner': False,
              'corner_left': False, 'section': None} for r in rows]
    ops = [{'wall': 'south', 'offset_cm': 190.0, 'width_cm': 120.0, 'kind': 'window', 'sill_cm': 85, 'height_cm': 150},
           {'kind': 'door', 'wall': 'east', 'offset_cm': 155.0, 'width_cm': 90.0, 'swing_cm': 90, 'hinge': 'left'}]
    scene = {'trial_id': 'AbCdEfGhIjKlMnOpQrStUv', 'status': 'ok', 'flags': [], 'problems': [],
             'room': {'id': 'r1', 'name': 'Lounge', 'kind': 'living', 'panel': 'p0'},
             'core': {'rect': [0, 0, 500, 400], 'w': 500.0, 'd': 400.0, 'area_m2': 20.0}, 'openings_core': ops,
             'geometries': [{'id': 'g0', 'openings_core': ops}],
             'variants': [{'style': 'сканди', 'set_index': 1, 'set_id': 's1', 'geometry': 0, 'items': rows, 'absent_roles': [], 'hard': [],
                           'post_ok': True, 'problems': [], 'placements': place, 'placements_core': place}]}
    ctx = {'rules': {'sofa_tv_cm': [180, 300]}, 'msid_of': lambda sid: MSID.get(sid), 'quiz': {'questions': [{'id': 'style', 'ru': 'Какой стиль?', 'en': 'Which style?'}]},
           'goods': lambda sid, role: dict(GOODS[sid]) if sid in GOODS else None, 'scene_live': TB.scene_live}
    stats: dict = {}
    d = TB.build('AbCdEfGhIjKlMnOpQrStUv', res, scene, ctx=ctx, stats=stats)
    d['_stats'] = stats
    return d


def _demo() -> dict:
    """Те же товары в данных /demo (`flat215_demo._sku`: `sid`, `msid`, `hung` по названию) и шаги сборки демо `annotate_*`."""
    items = [{'role': r, 'sku': {'sid': s, 'msid': MSID[s], 'name': GOODS[s]['name'], 'img': GOODS[s]['img'],
                                 'hung': FD._hung(GOODS[s]['name'])}} for r, s in ROLE_SID.items()]
    data = {'variants': [{'items': items, 'decor': []}], 'feeds': {}}
    FD.annotate_yaw(data)
    FD.annotate_strategy(data)
    FD.annotate_tint(data, FD.OUT)
    FD.annotate_swatch(data, FD.OUT)                 # семья цветов `fam` (образец по фото — свой шаг, здесь не сравнивается)
    return data


def _scene(it: dict) -> dict:
    sk = it['sku']
    return {'tint': sk.get('tint'), 'yaw': sk.get('yaw'), 'hung': bool(sk.get('hung')), 'fam': sk.get('fam'), 'strategy': it.get('strategy')}


def test_scene_fields_tour_same_as_demo(sources):
    tour = {it['role']: _scene(it) for v in _tour()['variants'] for it in v['items']}
    demo = {it['role']: _scene(it) for v in _demo()['variants'] for it in v['items']}
    assert tour == demo
    # сам тест что-то проверяет: у дивана есть подкраска и семья, тумба подвесная, зеркало — плоскость с ручным разворотом
    assert demo['диван']['tint'] and demo['диван']['fam'] == '9_fam' and demo['диван']['yaw'] == 90.0
    assert demo['тумба тв']['hung'] and demo['тумба тв']['yaw'] == 180.0
    assert demo['зеркало']['strategy'] == 'procedural_plane' and demo['зеркало']['yaw'] == 270.0


def test_scene_fields_reach_page_without_supplier_key(sources):
    d = _tour()
    assert d['_stats']['scene_fields'] == {'hung': 1, 'strategy': 1, 'yaw': 3, 'tint': 1, 'fam': 1}
    for v in d['variants']:
        for it in v['items']:
            assert set(it) <= TB.ITEM_KEYS and set(it['sku']) <= TB.PUBLIC_SKU_KEYS and '_sid' not in it['sku']


# ───────────────────────── предмет решателя спальни: тот же конструктор ─────────────────────────

BED = {'w': 176, 'd': 214, 'h': 100, 'name': 'Кровать угловая Рио', 'mid': 7, 'eid': 'b', 'side_back': 'left'}
WARDROBE = {'w': 160, 'd': 60, 'h': 220, 'name': 'Шкаф-купе Лайт', 'mid': 8, 'eid': 'w', 'side_back': 'right'}


def test_bedroom_solver_item_same_as_bank_build(monkeypatch):
    """Тур (`trial_bedroom._solve_kit`) отдаёт решателю те же предметы, что ночная сборка банка демо (`compose_bedroom.solver_item`):
    с названием (купе мерится проходом 70, распашной 90) и боковой спинкой кровати."""
    import planner.bedroom as PB

    class Got(Exception):
        pass

    seen = []

    def solve(room, items, purpose):
        seen.extend(items)
        raise Got

    monkeypatch.setattr(PB, 'solve_bedroom', solve)
    monkeypatch.setattr(TBR, 'build_room', lambda cand, cfg, hinge, purpose: (None, []))
    with pytest.raises(Got):
        TBR._solve_kit({'hinges': ['left']}, {}, {}, {'кровать': BED, 'шкаф': WARDROBE}, 'single')
    bank = [CB.solver_item('кровать', dict(BED, sid='7:b')), CB.solver_item('шкаф', dict(WARDROBE, sid='8:w'))]
    assert seen == bank
    assert seen[0].side_back == 'left' and seen[1].side_back is None and seen[1].name == 'Шкаф-купе Лайт'
    from planner.passage_norms import wardrobe_kind
    assert wardrobe_kind(seen[1]) == 'sliding'


# ───────────────────────── предпроверка тура не строже движка: демо-квартира и планы из объявлений ─────────────────────────

DOOR_WINDOW = lambda w: [{'kind': 'door', 'wall': 'south', 'offset_cm': 10, 'width_cm': 80, 'swing_cm': 80, 'hinge': 'left'},  # noqa: E731
                         {'kind': 'window', 'wall': 'north', 'offset_cm': max(0, w / 2 - 60), 'width_cm': min(120, w - 20), 'sill_cm': 85}]


def _rooms() -> list:
    out = [(f"flat215 {r['id']}/{r['variant']}", r) for r in json.load(open(CB.FLAT, encoding='utf-8'))['rooms']
           if r['id'].startswith('bedroom')]
    # спальни и кабинеты планов из объявлений (UK, разметка gold): в A#1 (2,64×3,45) и C#21 (3,28×2,68) движок ставит кровать пары,
    # а прежняя предпроверка тура (проход 75/60 вместо норм движка 50) её отсекала
    for g in 'ABC':
        for i, r in enumerate(json.load(open(os.path.join(ROOT, 'tools', 'floorplan', 'gold', f'{g}.json'), encoding='utf-8'))['rooms']):
            if r.get('dims_m') and any(k in (r.get('name') or '').lower() for k in ('bed', 'study')):
                w, d = (round(x * 100) for x in r['dims_m'])
                if g == 'A' or (g == 'C' and min(w, d) < 300):    # узкие и средние — где решают проходы; крупные B/C не меняют ответ
                    out.append((f'gold {g}#{i} {w}x{d}', {'w': w, 'd': d, 'openings': DOOR_WINDOW(w)}))
    return out


BEDS = [(126, 210, 'single'), (145, 210, 'single'), (155, 214, 'couple'), (176, 214, 'couple')]


def test_prefilter_numbers_are_engine_numbers():
    from planner.bedroom_checks import bed_clear_min
    assert TBR._clear('couple') == bed_clear_min(True) and TBR._clear('single') == bed_clear_min(False)


@pytest.mark.parametrize('name,spec', _rooms(), ids=lambda x: x if isinstance(x, str) else '')
def test_tour_prefilter_never_stricter_than_engine(name, spec):
    from planner.bedroom import solve_bedroom
    from planner.models import Item, Opening, Room
    ops = [Opening(**{k: v for k, v in o.items() if not k.startswith('_')}) for o in spec.get('openings', [])]
    stricter = []
    for w, d, purpose in BEDS:
        room = Room(width_cm=spec['w'], depth_cm=spec['d'], contour=spec.get('contour'), openings=ops, radiators=[], room_type='bedroom',
                    purpose=purpose)
        lay = solve_bedroom(room, [Item(role='кровать', w_cm=w, d_cm=d, h_cm=100)], purpose)
        placed = any(p.role == 'кровать' for p in lay.placements)
        if placed and not TBR.fits_core(TBR.frame_need({'w': w, 'd': d}, purpose), {'w': spec['w'], 'd': spec['d']}):
            stricter.append((w, purpose))
    assert not stricter, f'{name}: движок ставит кровать {stricter}, а предпроверка тура её отсекает'
