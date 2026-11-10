"""Пересборка готового тура «как есть» (план agent-trial-08; T-20261110-05): обставленный тур → новая версия на текущем коде сборщика,
мебель та же (роль, место, поворот, модель, размеры), имена товаров — по-новому, исходы комнат прежние, ни подбора, ни разбора.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_trial_reissue.py -q"""
import copy
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
import trial_bundle as TB  # noqa: E402
import trial_reissue as RI  # noqa: E402
from test_trial_bundle import CTX, JOB, _names_unique, bedroom_part, flat_with_bedrooms, scene_for  # noqa: E402


def furniture(d):
    """Выбор мебели тура по комнатам (по ключу плана): что стоит и где — без имён."""
    keys = RI.room_keys(d)
    return {(keys[v['room_id']], v['style']): sorted((it['role'], it['x'], it['y'], it['rot'], it['sku'].get('msid'), it['sku'].get('w'),
                                                     it['sku'].get('d'), it['sku'].get('colour_en')) for it in v['items'])
            for v in d['variants']}


def old_tour(flat=None):
    """Готовый тур, собранный «старым» сборщиком: имена без размеров, у кровати без `sleep_w`, лента спальни под голой ролью."""
    flat = flat or flat_with_bedrooms()
    parts = [bedroom_part(), bedroom_part('bedroom-2')]
    parts[1]['variants'][0]['items'].append(copy.deepcopy(parts[1]['variants'][0]['items'][0]) | {'role': 'тумба прикроватная', 'x': 10})
    d = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=parts)
    for v in d['variants']:
        for it in v['items']:
            ru, en = TB.neutral_names(TB._base_role(it['role']))
            sw = it['sku'].pop('sleep_w', None)
            it['sku'].update(name=f'{ru} {sw} см' if sw else ru, name_en=en)
            it['sku'].pop('colour_ru', None)
    d['feeds'] = {'кровать': [], 'диван': []}
    return flat, d


def test_furnished_tour_new_naming_same_furniture_same_outcomes():
    flat, old = old_tour()
    assert len({it['sku']['name'] for v in old['variants'] for it in v['items'] if it['role'] == 'диван'}) == 1   # старые имена — одни
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    assert furniture(new) == furniture(old)                                   # мебель та же
    names = _names_unique(new)                                                # имена — по текущему правилу: уникальные, с размером
    assert 'Кровать 160 см · 170×210 см' in names and any(n.startswith('Диван · 200×90 см') for n in names)
    bed = next(it for v in new['variants'] if v['room_id'] == 'bedroom-1' for it in v['items'])
    assert bed['sku']['sleep_w'] == 160                                      # ширина спального места — из прежнего имени
    assert 'bedroom-1:кровать' in new['feeds'] and 'кровать' not in new['feeds'] and new['sofa_feed'] == new['feeds']['диван']
    st = lambda d: {r['id']: (r['furniture_state'], r['furniture_code'], r.get('photo_ok')) for r in d['apartment_rooms']}  # noqa: E731
    assert st(new) == st(old) and new['trial']['complete'] is True and new['trial']['furniture'] == old['trial']['furniture']
    assert rep['kept_furniture'] == ['living', 'bedroom-1', 'bedroom-2'] and rep['no_source'] == [] and rep['renamed_rooms'] == {}
    assert new['quiz'] == CTX['quiz'] and new['trial']['panels'] == old['trial']['panels']
    json.dumps(new)                                                            # годный JSON


def test_box_under_furniture_kept_titles_from_current_code():
    """Предметы стоят в координатах прежней коробки комнаты — её размеры и проёмы не пересчитываем; подписи — текущим кодом."""
    flat, old = old_tour()
    old['rooms_geo']['bedroom-1'].update(w=777, d=333, title='старая подпись', title_en='old title')
    new, _ = RI.reissue(JOB, flat, old, ctx=CTX)
    g = new['rooms_geo']['bedroom-1']
    assert (g['w'], g['d']) == (777, 333) and g['title'] != 'старая подпись' and g['title_en'].startswith('Bedroom')


def test_box_of_empty_carried_room_kept_too():
    """Пустая перенесённая комната («ждёт проверки» / отказ) — коробку тоже не пересчитываем: её проёмы считала стадия подбора, текущий
    сборщик без стадии считает иначе (прод 10.11: петля двери пустой спальни переворачивалась)."""
    flat = flat_with_bedrooms()
    flat['scale']['status'] = 'not_verified'
    old = TB.build(JOB, flat, None, ctx=CTX, parts=[bedroom_part()])
    by = {r['id']: r for r in old['apartment_rooms']}
    assert by['living']['furniture_state'] == 'awaiting_check'
    g = old['rooms_geo']['living']
    g['openings'] = [dict(o, hinge='right' if o.get('hinge') != 'right' else 'left') for o in g.get('openings') or []] or \
        [{'wall': 'north', 'offset_cm': 10, 'width_cm': 80, 'kind': 'door', 'hinge': 'right'}]
    g.update(w=g['w'] + 7, title='старая подпись')
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    ng = new['rooms_geo']['living']
    assert 'living' in rep['kept_outcome']
    assert (ng['w'], ng['openings']) == (g['w'], g['openings']) and ng['title'] != 'старая подпись'


def test_rooms_matched_by_plan_not_by_page_id():
    """Нумерация комнат страницы сменилась (старая версия звала спальни наоборот) — мебель идёт за комнатой плана."""
    flat, old = old_tour()
    swap = {'bedroom-1': 'bedroom-2', 'bedroom-2': 'bedroom-1'}
    for p in old['trial']['panels']:
        for r in p['rooms']:
            r['id'] = swap.get(r['id'], r['id'])
    for r in old['apartment_rooms']:
        r['id'] = swap.get(r['id'], r['id'])
    for v in old['variants']:
        v['room_id'] = swap.get(v['room_id'], v['room_id'])
        v['id'] = v['id'].replace('bedroom-1', 'X').replace('bedroom-2', 'bedroom-1').replace('X', 'bedroom-2')
    old['rooms_geo'] = {swap.get(k, k): g for k, g in old['rooms_geo'].items()}
    want = furniture(old)
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    assert furniture(new) == want and rep['renamed_rooms'] == swap
    assert {v['id'] for v in new['variants'] if v['room_id'] == 'bedroom-1'} == {'bedroom-1-scandi'}


def test_target_room_without_old_furniture_is_honest_refusal_not_spinner():
    """Новый код видит спальню, которой прежняя версия не знала: подбор не делаем — отказ с текстом, `complete` не ломается."""
    flat, old = old_tour()
    flat['panels'][0]['rooms'].append(b3 := {**flat['panels'][0]['rooms'][1], 'id': 'b3', 'name': 'Bedroom 3'})
    b3['contour'] = [[1600, 0], [2000, 0], [2000, 350], [1600, 350]]
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    e = next(r for r in new['apartment_rooms'] if r['id'] == 'bedroom-3')
    assert (e['furniture_state'], e['furniture_code']) == ('refused', RI.NO_SOURCE) and e['furniture_text']
    assert rep['no_source'] == ['bedroom-3'] and new['trial']['complete'] is True
    assert [v['items'] for v in new['variants'] if v['room_id'] == 'bedroom-3'] == [[]]


def test_living_picked_from_other_room_keeps_its_furniture_and_outcome():
    """Гостиная с подписью, но вида `other` (разбор не узнал вид) — сборщик берёт её гостиной. Её мебель или отказ переносятся, как у
    любой цели; раньше комнату пропускали по виду — сборщик оставлял «подбирается», `complete` становился False (T-20261110-10)."""
    flat = flat_with_bedrooms()
    next(r for r in flat['panels'][0]['rooms'] if r['id'] == 'r1')['kind'] = 'other'
    _, old = old_tour(flat)
    by_old = {r['id']: r for r in old['apartment_rooms']}
    assert by_old['living']['kind'] == 'other' and by_old['living']['furniture_state'] == 'ready'
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    assert furniture(new) == furniture(old) and 'living' in rep['kept_furniture'] and new['trial']['complete'] is True
    # отказ гостиной «нет подходящих товаров» — остаётся отказом с текстом, не крутилкой
    for r in old['apartment_rooms']:
        if r['id'] == 'living':
            r.update(TB._outcome('refused', 'no_products'))
    old['variants'] = [v for v in old['variants'] if v['room_id'] != 'living'] + [
        TB._empty_variant('living', old['rooms_geo']['living'], 'failed', {'code': 'no_products'})]
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    e = next(r for r in new['apartment_rooms'] if r['id'] == 'living')
    assert (e['furniture_state'], e['furniture_outcome']) == ('refused', 'no_products') and e['furniture_text']
    assert 'living' in rep['kept_outcome'] and new['trial']['complete'] is True
    assert [v['items'] for v in new['variants'] if v['room_id'] == 'living'] == [[]]


def test_guessed_living_without_label_is_not_resurrected():
    """Прежний сборщик угадывал гостиной комнату `other` без подписи (прод 10.11, FYyX…/Jsfx…: ванная, отказ «гостиная мала»). Текущий
    не угадывает (`no_living`, T-20261110-12) — «как есть» не переносит её прежний исход: комната без подписи — «не обставляем»."""
    flat = flat_with_bedrooms()
    r1 = next(r for r in flat['panels'][0]['rooms'] if r['id'] == 'r1')
    r1['kind'] = 'other'
    _, old = old_tour(flat)
    assert next(r for r in old['apartment_rooms'] if r['id'] == 'living')['furniture_state'] == 'ready'
    r1['name'] = ''                                          # тот же план, прочитанный без подписи гостиной
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    keys = RI.room_keys(new)
    e = next(r for r in new['apartment_rooms'] if keys.get(r['id']) == ('p0', 'r1'))
    assert e['kind'] == 'other' and e['furniture_state'] == 'not_furnished'
    assert not [v for v in new['variants'] if v['room_id'] == e['id'] and v['items']]
    assert e['id'] not in rep['kept_furniture'] + rep['kept_outcome'] and 'living' not in rep['renamed_rooms']
    assert 'no_living' in new['trial']['flags'] and new['trial']['complete'] is True
    assert furniture(new) == {k: v for k, v in furniture(old).items() if k[0] != ('p0', 'r1')}


def test_waiting_and_consented_rooms_keep_their_state():
    """«Ждёт проверки» остаётся ждать (мебели не появится), «размеры примерные» агента — остаётся отметкой, фото по правилу."""
    flat = flat_with_bedrooms()
    flat['scale']['status'] = 'not_verified'
    b1 = next(r for r in flat['panels'][0]['rooms'] if r['id'] == 'b1')
    b1['flags'] = ['approx_consent']
    old = TB.build(JOB, flat, None, ctx=CTX, parts=[bedroom_part()])
    b1['flags'] = []                                         # в сохранённом результате флага нет — его ставила копия «Обустроить»
    new, rep = RI.reissue(JOB, flat, old, ctx=CTX)
    by = {r['id']: r for r in new['apartment_rooms']}
    assert by['living']['furniture_state'] == 'awaiting_check' and by['bedroom-1']['furniture_state'] == 'ready'
    assert by['bedroom-1']['approx_consent'] is True and by['bedroom-1']['photo_ok'] is False
    assert 'living' in rep['kept_outcome'] and rep['kept_furniture'] == ['bedroom-1']


def test_other_job_refused():
    flat, old = old_tour()
    with pytest.raises(TB.BundleRefused) as e:
        RI.reissue('X' * 22, flat, old, ctx=CTX)
    assert e.value.code == 'wrong_job'


def test_shop_names_in_old_items_do_not_pass():
    """Прежняя версия — тоже вход: предметы проходят общий разрешённый список, ссылка магазина — отказ, а не публикация."""
    flat, old = old_tour()
    old['variants'][0]['items'][0]['sku']['url'] = 'https://shop.example/a'      # SKU_KEYS снимет поле
    old['variants'][0]['items'][0]['sku']['colour_en'] = 'see https://shop.example'
    with pytest.raises(TB.BundleRefused) as e:
        RI.reissue(JOB, flat, old, ctx=CTX)
    assert e.value.code == 'shop_leak'
