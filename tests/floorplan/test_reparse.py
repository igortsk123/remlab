"""«Перечитать планировку» по оператору (план trial-reparse-01; T-20261111-02): пары комнат и проёмов прежнего и перечитанного плана,
перевод правок агента и строгое наложение, сторож регресса (`regress.guard_*`), пересборка `conveyor.Reparse` целиком против поддельного
прода из `test_worker.py` (claim с навыком reparse, лист под арендой, публикация с `result` и картой, отказы кодом)."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import opening_edits as OE  # noqa: E402
import regress as RG  # noqa: E402
import room_edits as RE  # noqa: E402
from test_worker import JID, RID, mk, prod  # noqa: E402,F401 — фикстуры поддельного прода

TEXT = 'Общая площадь 41 м², потолки 2,7 м'


def rect(rid, name, kind, x0, y0, x1, y1, k=1.0, **over):
    x0, y0, x1, y1 = (v * k for v in (x0, y0, x1, y1))
    area = round((x1 - x0) * (y1 - y0) / 1e4 / k / k, 2)
    return {'id': rid, 'name': name, 'kind': kind, 'contour': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            'bbox': {'x': x0, 'y': y0, 'w': x1 - x0, 'd': y1 - y0}, 'areaM2': area, 'flags': [], **over}


def op(kind, x, y, k=1.0, w=90):
    return {'kind': kind, 'c': [x * k, y * k], 'widthCm': w, 'exterior': kind == 'window'}


def plan(ppm=50.0, k=1.0, ids=('r1', 'b1', 'k1'), order=(0, 1, 2), ops_order=(0, 1, 2, 3), bedroom=(500, 0, 800, 400), drop=(),
         flags=None):
    """Гостиная 5×4, спальня 3×4 справа, кухня 3×3 снизу; двери гостиная–спальня и гостиная–кухня, окно у гостиной и у спальни.
    `k` — см нового на см прежнего (другой масштаб: те же пиксели листа), `ids`/`order` — другие номера и порядок."""
    rooms = [rect(ids[0], 'Гостиная', 'living', 0, 0, 500, 400, k), rect(ids[1], 'Спальня', 'bedroom', *bedroom, k),
             rect(ids[2], 'Кухня', 'kitchen', 0, 400, 300, 700, k)]
    for r in rooms:
        r['flags'] = list((flags or {}).get(r['kind'], []))
    rooms = [rooms[i] for i in order if rooms[i]['kind'] not in drop]
    ops = [op('door', 500, 200, k), op('window', 250, 0, k), op('window', 650, 0, k), op('door', 150, 400, k)]
    return {'version': 1, 'units': 'cm', 'scale': {'status': 'area', 'ppm': ppm}, 'ceilingCm': 270.0, 'timings': {'walls': 1.0},
            'costUsd': 0.01, 'panels': [{'id': 'p0', 'rooms': rooms, 'walls': [], 'openings': [ops[i] for i in ops_order]}]}


# ───────────────────────── пары и сторож ─────────────────────────

def test_pairs_by_geometry_not_ids_even_with_new_scale():
    """Новый масштаб (см ×0,5, ppm ×2 — те же пиксели листа), другие номера и порядок → все три пары, `k` = 0,5."""
    old, new = plan(), plan(ppm=100.0, k=0.5, ids=('a', 'b', 'c'), order=(2, 0, 1))
    pc = RG.pair_canon(old, new)
    assert pc['pairs'] == {('p0', 'r1'): 'a', ('p0', 'b1'): 'b', ('p0', 'k1'): 'c'} and pc['lost'] == {} and pc['added'] == []
    assert pc['k'] == pytest.approx(0.5)


def test_merged_rooms_block_and_say_with_whom():
    """Гостиная и спальня слились в одну комнату → у спальни нет пары: блок «слилась с «Гостиная»»."""
    old, new = plan(), plan(bedroom=(500, 0, 800, 400), drop=('bedroom',))
    new['panels'][0]['rooms'][0] = rect('r1', 'Гостиная', 'living', 0, 0, 800, 400)
    pc = RG.pair_canon(old, new)
    assert pc['lost'] == {('p0', 'b1'): 'слилась с «Гостиная»'}
    f = {x['key']: x for x in RG.guard_canon(old, new, pc)}
    assert f['p0/b1:lost']['level'] == 'block' and f['p0/r1:area:20.0→32.0']['level'] == 'block'


def test_split_room_is_named():
    old = plan()
    new = plan()
    rooms = new['panels'][0]['rooms']
    rooms[1:2] = [rect('b1', 'Спальня', 'bedroom', 500, 0, 600, 400), rect('b2', 'Кабинет', 'other', 600, 0, 700, 400),
                  rect('b3', 'Гардероб', 'other', 700, 0, 800, 400)]
    pc = RG.pair_canon(old, new)
    assert pc['lost'][('p0', 'b1')] == 'распалась на «Спальня» + «Кабинет» + «Гардероб»'


def test_same_plan_no_findings_and_canon_equal_despite_jsonb_numbers():
    old = plan()
    new = json.loads(json.dumps(plan()).replace('270.0', '270'))           # jsonb Postgres: 270 вместо 270.0
    new['timings'], new['costUsd'] = {'walls': 9.9}, 0.5
    pc = RG.pair_canon(old, new)
    assert RG.guard_canon(old, new, pc) == [] and RG.verdict([], ['x']) == ('clean', [])
    assert RG.same_canon(old, new) and not RG.same_canon(old, plan(ids=('r1', 'b1', 'kX')))


def test_losses_block_other_differences_need_approval():
    """Спальня вдвое меньше и без дверей — блок; у гостиной дверей 2 → 1 — изменение; новая комната и другой масштаб — изменение."""
    old = plan()
    new = plan(ppm=51.0, bedroom=(500, 0, 650, 400), ops_order=(1, 2, 3))
    new['panels'][0]['rooms'].append(rect('h1', 'Холл', 'hall', 300, 400, 500, 700))
    f = {x['key']: x['level'] for x in RG.guard_canon(old, new, RG.pair_canon(old, new))}
    assert f == {'scale:area/50.0→area/51.0': 'change', 'p0/b1:area:12.0→6.0': 'block', 'p0/b1:doors:1→0': 'block',
                 'p0/r1:doors:2→1': 'change', 'p0/+h1:new:hall': 'change'}


def test_living_kind_change_blocks_kitchen_loss_is_change():
    old = plan()
    new = plan(drop=('kitchen',))
    new['panels'][0]['rooms'][1]['kind'] = 'living'
    f = {x['key']: x['level'] for x in RG.guard_canon(old, new, RG.pair_canon(old, new))}
    assert f == {'p0/b1:kind:bedroom→living': 'block', 'p0/k1:lost': 'change'}


def bundle(rooms, goods=None, bad=0):
    """Страница: [(id страницы, id плана, состояние, исход)], товары по комнате (с ценой и ссылкой) и `bad` без цены у гостиной."""
    var = []
    for pid, n in (goods or {}).items():
        roles = ('диван', 'столик', 'тв-тумба', 'ковёр', 'торшер', 'кресло')    # от 3 предметов у гостиной полное ядро
        var.append({'room_id': pid, 'items': [{'role': roles[i % len(roles)], 'sku': {'price': 100, 'url': 'https://x'}} for i in range(n)] +
                    ([{'sku': {'price': 0, 'url': 'https://x'}} for _ in range(bad)] if pid == 'living' else [])})
    return {'apartment_rooms': [{'id': p, 'kind': p.split('-')[0], 'furniture_state': s, 'furniture_outcome': o} for p, _, s, o in rooms],
            'variants': var, 'trial': {'panels': [{'id': 'p0', 'rooms': [{'id': p, 'src_id': s} for p, s, *_ in rooms]}]}}


def test_page_guard_furnished_room_must_stay_furnished_with_goods_prices_links():
    pc = RG.pair_canon(plan(), plan(ids=('a', 'b', 'c')))
    was = bundle([('living', 'r1', 'ready', 'furnished'), ('bedroom-1', 'b1', 'ready', 'furnished')], {'living': 5, 'bedroom-1': 3})
    ok = bundle([('living', 'a', 'ready', 'furnished'), ('bedroom-1', 'b', 'ready', 'furnished')], {'living': 4, 'bedroom-1': 3})
    assert RG.guard_page(was, ok, pc) == []
    bad = bundle([('living', 'a', 'awaiting_check', 'awaiting_check'), ('bedroom-1', 'b', 'ready', 'furnished')],
                 {'living': 0, 'bedroom-1': 0}, bad=1)
    f = {x['key']: x['level'] for x in RG.guard_page(was, bad, pc)}
    assert f == {'p0/r1:page:awaiting_check/awaiting_check': 'block', 'p0/r1:page:bad:0→1': 'block', 'p0/b1:page:goods:3→0': 'block'}


def test_page_guard_style_lost_blocks():
    """T-20261113-23 (директор, прод 13.11): перечитка oTlA… v22 → v23 — гостиная 6 стилей → 4 (минимализм пустой, лофта нет), а сторож
    видел только «обставлена, товары есть». Стилей с мебелью стало меньше — блок с ключом; столько же или больше — чисто."""
    pc = RG.pair_canon(plan(), plan(ids=('a', 'b', 'c')))

    core = ('диван', 'столик', 'тв-тумба', 'ковёр', 'торшер', 'кресло', 'стеллаж', 'кашпо', 'полка')

    def page(styles, sid):
        b = bundle([('living', sid, 'ready', 'furnished')])
        b['variants'] = [{'room_id': 'living', 'style': s,
                          'items': [{'role': r, 'sku': {'price': 100, 'url': 'https://x'}} for r in (roles if isinstance(roles, tuple) else core[:roles])]}
                         for s, roles in styles]
        return b
    was = page([('сканди', 9), ('современный', 9), ('минимализм', 8), ('лофт', 6), ('неоклассика', 9), ('джапанди', 9)], 'r1')
    lost = page([('сканди', 8), ('современный', 8), ('неоклассика', 8), ('джапанди', 6), ('минимализм', 0)], 'a')
    f = RG.guard_page(was, lost, pc)
    assert [(x['key'], x['level']) for x in f] == [('p0/r1:page:styles:6→4', 'block')]
    assert 'нет: лофт, минимализм' in f[0]['text'] and 'с мебелью и ядром 6 → 4' in f[0]['text']
    assert RG.verdict(f)[0] == 'block' and RG.verdict(f, ['p0/r1:page:styles:6→4'])[0] == 'approved'
    same = page([(s, 5) for s in ('сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди')], 'a')
    assert RG.guard_page(was, same, pc) == []
    # T-20261113-23/2 (директор): «стиль с мебелью» гостиной = стиль с полным ядром, до и после. Прод — 5 стилей, у двух нет столика или
    # тумбы ТВ (`(...)` — роли без ядра); честная перечитка даёт 3 с ядром → чисто: дырявые стили и раньше не считались.
    holey = page([('сканди', 8), ('современный', 8), ('неоклассика', 8), ('минимализм', ('диван', 'столик', 'ковёр')),
                  ('джапанди', ('диван', 'тв-тумба', 'стеллаж'))], 'r1')
    assert RG.page_rooms(holey)[('p0', 'r1')]['styles'] == ['неоклассика', 'сканди', 'современный']
    honest = page([('сканди', 8), ('современный', 8), ('неоклассика', 8)], 'a')
    assert RG.guard_page(holey, honest, pc) == []
    # стенка — тоже носитель ТВ; столик у стиля пропал на перечитке — потеря стиля с ядром, блок
    assert RG.guard_page(holey, page([('сканди', ('диван', 'столик', 'стенка')), ('современный', 8),
                                      ('неоклассика', ('диван', 'тв-тумба'))], 'a'), pc)[0]['key'] == 'p0/r1:page:styles:3→2'
    # прод yb3_DQ: 5 стилей, ни у одного нет полного ядра → перечитка честно отказала гостиной («нет места») — не блок
    hollow = page([('сканди', ('диван', 'тв-тумба', 'ковёр')), ('лофт', ('диван', 'столик'))], 'r1')
    refused = bundle([('living', 'a', 'ready', 'no_space')])
    assert RG.guard_page(hollow, refused, pc) == []
    # а у честной гостиной тот же отказ — блок, как раньше
    assert RG.guard_page(page([('сканди', 8)], 'r1'), refused, pc)[0]['key'] == 'p0/r1:page:ready/no_space'
    # не гостиная: ядро не требуется — спальня с мебелью считается стилем как раньше
    bed = bundle([('bedroom', 'b1', 'ready', 'furnished')], goods={'bedroom': 3})
    bed['variants'][0]['style'] = 'сканди'
    assert RG.page_rooms(bed)[('p0', 'b1')]['styles'] == ['сканди']


def test_verdict_and_detail():
    fs = [{'key': 'a', 'level': 'change', 'text': 'дверей 2 → 1'}, {'key': 'b', 'level': 'block', 'text': 'площадь'}]
    assert RG.verdict(fs) == ('block', fs)
    assert RG.verdict(fs, ['b'])[0] == 'change' and RG.verdict(fs, ['a', 'b']) == ('approved', [])
    assert RG.detail_of(fs).splitlines() == ['БЛОК площадь [b]', 'изм. дверей 2 → 1 [a]']
    assert len(RG.detail_of(fs * 200)) == 2000


# ───────────────────────── правки агента: перевод и строгое наложение ─────────────────────────

def test_room_edit_strict_has_no_anchor_fallback():
    e = {'panel': 'p0', 'srcId': 'gone', 'anchor': {'x': 0.31, 'y': 0.29}, 'name': 'Зал'}
    assert len(RE.apply(plan(), [e])[1]) == 1                              # обычная пересборка: ближайшая по центру
    assert RE.apply(plan(), [e], strict=True)[1] == []


def test_room_edits_follow_pairs_with_new_ids_and_anchor():
    old, new = plan(), plan(ids=('b1', 'r1', 'k9'))                       # номера гостиной и спальни поменялись местами
    pc = RG.pair_canon(old, new)
    edits = [{'panel': 'p0', 'srcId': 'r1', 'anchor': {'x': 0.31, 'y': 0.29}, 'name': 'Зал'},
             {'panel': 'p0', 'srcId': 'b1', 'anchor': {'x': 0.81, 'y': 0.29}, 'wCm': 320, 'dCm': 410}, {'panel': 'p0', 'srcId': 'nope'}]
    out, cmap, bad = RE.translate(edits, old, new, pc['pairs'])
    assert [(m['from'], m['to']) for m in cmap] == [('r1', 'b1'), ('b1', 'r1')] and [why for _, why in bad] == ['комнаты правки нет в прежнем плане']
    assert cmap[0]['anchor'] == {'x': round(250 / 800, 4), 'y': round(200 / 700, 4)}
    res, done = RE.apply(new, out, strict=True)
    names = {r['id']: r['name'] for r in res['panels'][0]['rooms']}
    assert len(done) == 2 and names['b1'] == 'Зал' and res['panels'][0]['rooms'][1]['edited'] == {'w': 320, 'd': 410}


def test_opening_edits_follow_new_numbers_and_scale():
    """Масштаб ×0,5 и обратный порядок проёмов: дверь s0 → s3 нового плана, центры — в новых см; добавленная у стены — с новым
    центром; добавленная посреди комнаты — не легла; строгое наложение — по точному центру."""
    old, new = plan(), plan(ppm=100.0, k=0.5, ops_order=(3, 2, 1, 0))
    k = RG.pair_canon(old, new)['k']
    edits = [{'panel': 'p0', 'key': 's0', 'srcIdx': 0, 'srcC': [500, 200], 'kind': 'door', 'c': [500, 220], 'widthCm': 80},
             {'panel': 'p0', 'key': 'uAbcdef12', 'srcIdx': None, 'srcC': None, 'kind': 'window', 'c': [0, 200], 'widthCm': 120},
             {'panel': 'p0', 'key': 'uMiddle01', 'srcIdx': None, 'srcC': None, 'kind': 'door', 'c': [250, 200], 'widthCm': 80}]
    out, omap, bad = OE.translate(edits, old, new, k)
    assert omap[0] == {'panel': 'p0', 'key': 's0', 'to': 's3', 'srcIdx': 3, 'srcC': [250.0, 100.0], 'c': [250.0, 110.0]}
    assert omap[1]['to'] == 'uAbcdef12' and omap[1]['c'] == [0.0, 100.0]
    assert [why for _, why in bad] == ['добавленный проём не у стены перечитанного плана']
    res, done = OE.apply(new, out, strict=True)
    assert len(done) == 2 and res['panels'][0]['openings'][3]['c'] == [250.0, 110.0]
    off = [dict(out[0], srcC=[252.0, 100.0])]
    assert OE.apply(new, off, strict=True)[1] == [] and len(OE.apply(new, off)[1]) == 1   # обычная — ближайший в 30 см


def test_opening_edit_ambiguous_pair_does_not_land():
    old, new = plan(), plan()
    new['panels'][0]['openings'].append(op('door', 510, 190))
    e = {'panel': 'p0', 'key': 's0', 'srcIdx': 0, 'srcC': [500, 200], 'kind': 'door', 'c': [500, 200], 'widthCm': 80}
    assert [why for _, why in OE.translate([e], old, new, 1.0)[2]] == ['нет однозначной пары проёма']


# ───────────────────────── пересборка целиком (`conveyor.Reparse` против поддельного прода) ─────────────────────────

def old_bundle(res):
    """Страница прежней версии — как её собирает поддельный сборщик (`test_worker.FAKE_BUNDLE`): id страницы по виду."""
    n, pages = {}, []
    for r in res['panels'][0]['rooms']:
        n[r['kind']] = n.get(r['kind'], 0) + 1
        pages.append(('living' if r['kind'] == 'living' and n['living'] == 1 else f"{r['kind']}-{n[r['kind']]}", r['id']))
    return json.dumps({'apartment_rooms': [{'id': p, 'kind': p.split('-')[0], 'furniture_state': 'ready'} for p, _ in pages],
                       'trial': {'panels': [{'id': 'p0', 'rooms': [{'id': p, 'src_id': s} for p, s in pages]}]}})


def reparse(prod, monkeypatch, tmp_path, new, old=None, rooms=(), edits=(), ops=(), **over):
    old = old or plan()
    p = tmp_path / 'reread.json'
    p.write_text(json.dumps(new))
    monkeypatch.setenv('FAKE_REREAD', str(p))
    b = old_bundle(old)
    import hashlib
    prod.rebuilds.append({'id': RID, 'jobId': JID, 'attempt': 1, 'leaseToken': 'R' * 32, 'leaseUntil': 'x', 'rooms': list(rooms),
                          'baseVersion': 7, 'result': old, 'kind': 'reparse', 'listingText': TEXT, 'inputMime': 'image/png', 'bundle': b,
                          'baseSha': hashlib.sha256(b.encode()).hexdigest(), 'edits': list(edits), 'openingEdits': list(ops), **over})
    return b


def fails(prod):
    return [(f['code'], f['retryable']) for f in prod.by('/api/trial/worker/rebuild/fail')]


def test_reparse_same_reading_publishes_old_bytes_no_new_version(prod, mk, monkeypatch, tmp_path):
    """Прочитано то же самое (другие только время и расход) → прежние байты страницы без `result` и карты: сервер — «та же версия».
    Читается по ИСХОДНОМУ тексту объявления, лист — под арендой, только кэш (0 $); claim — с навыком reparse."""
    new = plan()
    new['timings'] = {'walls': 99}
    b = reparse(prod, monkeypatch, tmp_path, new)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    claim = prod.by('/api/trial/worker/claim')[0]
    assert claim['reparse'] is True and claim['edit'] is True
    sent = prod.by('/api/trial/worker/rebuild/publish')
    assert len(sent) == 1 and sent[0]['bundle'] == b and 'result' not in sent[0] and 'reparse' not in sent[0]
    assert w.done == [(RID, 'rebuilt')] and prod.bundles == [] and fails(prod) == []
    wd = next((tmp_path / 'trial' / JID).glob('r1-*'))
    argv = json.loads((wd / 'plan' / 'argv.json').read_text())
    assert '--cache-only' in argv and argv[argv.index('--cap-usd') + 1] == '0'
    assert (wd / 'plan' / 'listing-seen.txt').read_text(encoding='utf-8') == TEXT
    assert [h for p, _, h in prod.reqs if p == f'/api/trial/worker/rebuild/{RID}/input'][0]['X-Trial-Lease'] == 'R' * 32


def test_reparse_renumbered_plan_publishes_with_result_and_map(prod, mk, monkeypatch, tmp_path):
    """Номера и порядок комнат и проёмов сменились, разница не потеря → ОДНА версия с новым `result` и картой: снятая гостиная — по
    новому id страницы, правка спальни и двери — на новые номера; правка легла на новую спальню строго."""
    old = plan(flags={'living': ['dims_mismatch']})
    new = plan(ids=('n1', 'n2', 'n3'), order=(2, 1, 0), ops_order=(3, 2, 1, 0), flags={'living': ['dims_mismatch']})
    edits = [{'panel': 'p0', 'srcId': 'b1', 'anchor': {'x': 0.81, 'y': 0.29}, 'name': 'Детская', 'kind': 'bedroom', 'built': True}]
    ops = [{'panel': 'p0', 'key': 's0', 'srcIdx': 0, 'srcC': [500, 200], 'kind': 'door', 'c': [500, 210], 'widthCm': 80, 'built': True}]
    reparse(prod, monkeypatch, tmp_path, new, old=old, rooms=['living'], edits=edits, ops=ops)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert fails(prod) == [] and w.done == [(RID, 'rebuilt')]
    sent = prod.by('/api/trial/worker/rebuild/publish')
    assert len(sent) == 1 and sent[0]['result'] == new
    m = sent[0]['reparse']
    assert m['released'] == ['living'] and [(x['from'], x['to']) for x in m['rooms']] == [('b1', 'n2')]
    assert [(x['key'], x['to'], x['srcIdx']) for x in m['openings']] == [('s0', 's3', 3)]
    rooms = {r['id']: r for r in prod.bundles[0]['data']['apartment_rooms']}
    assert rooms['living']['furniture_state'] == 'ready'                    # снятая раньше гостиная снята и сейчас
    wd = next((tmp_path / 'trial' / JID).glob('r1-*'))
    ed = json.loads((wd / 'result-edited.json').read_text())
    assert {r['id']: r['name'] for r in ed['panels'][0]['rooms']}['n2'] == 'Детская'
    assert ed['panels'][0]['openings'][3]['user'] is True


def test_reparse_loss_is_regress_with_detail_nothing_published(prod, mk, monkeypatch, tmp_path):
    reparse(prod, monkeypatch, tmp_path, plan(bedroom=(500, 0, 650, 400)))
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert fails(prod) == [('regress', False)] and prod.by('/api/trial/worker/rebuild/publish') == []
    detail = prod.by('/api/trial/worker/rebuild/fail')[0]['detail']
    assert 'БЛОК «Спальня»: площадь 12.0 → 6.0 м² [p0/b1:area:12.0→6.0]' in detail


def test_reparse_approved_difference_is_published(prod, mk, monkeypatch, tmp_path):
    """Ведущий одобрил КОНКРЕТНУЮ разницу тура (файл воркера) → публикуется; одобрение чужого ключа не помогает."""
    reparse(prod, monkeypatch, tmp_path, plan(bedroom=(500, 0, 650, 400)))
    w = mk(furnish=True)
    d = w.cfg.base / 'reparse-approve'
    d.mkdir(parents=True)
    (d / f'{JID}.json').write_text(json.dumps({'keys': ['p0/b1:area:12.0→6.0', 'p0/b1:windows:1→1']}))
    w.loop(max_iter=1)
    assert fails(prod) == [] and len(prod.by('/api/trial/worker/rebuild/publish')) == 1


def test_reparse_cache_miss_keeps_tour(prod, mk, monkeypatch, tmp_path):
    reparse(prod, monkeypatch, tmp_path, plan())
    monkeypatch.setenv('FAKE_CACHE', 'gone')
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert fails(prod) == [('cache_miss', False)] and prod.by('/api/trial/worker/rebuild/publish') == []


def test_reparse_edit_without_pair_is_conflict(prod, mk, monkeypatch, tmp_path):
    """Кухни в перечитанном плане нет (изменение одобрено), а у агента правка кухни → `edits_conflict`, тур прежний."""
    edits = [{'panel': 'p0', 'srcId': 'k1', 'anchor': {'x': 0.2, 'y': 0.8}, 'name': 'Кухня-столовая', 'built': True}]
    reparse(prod, monkeypatch, tmp_path, plan(drop=('kitchen',)), edits=edits)
    w = mk(furnish=True)
    d = w.cfg.base / 'reparse-approve'
    d.mkdir(parents=True)
    (d / f'{JID}.json').write_text(json.dumps({'keys': ['p0/k1:lost', 'p0/r1:doors:2→1']}))
    w.loop(max_iter=1)
    assert fails(prod) == [('edits_conflict', False)] and prod.by('/api/trial/worker/rebuild/publish') == []
    assert 'p0/k1: у комнаты правки нет однозначной пары' in prod.by('/api/trial/worker/rebuild/fail')[0]['detail']


def test_reparse_drafts_follow_map_and_lost_ones_are_dropped_with_reason(prod, mk, monkeypatch, tmp_path):
    """Черновики (T-20261111-16/2): в сборку не идут, но переводятся той же картой; черновик кухни, которой больше нет, и проём, номер
    которого взял подтверждённый, перечитывание НЕ валят: они в `drafts.dropped` с причиной. В карте — масштаб `k`."""
    new = plan(ids=('n1', 'n2', 'n3'), order=(2, 1, 0), ops_order=(3, 2, 1, 0), drop=('kitchen',))
    drafts = [{'panel': 'p0', 'srcId': 'r1', 'anchor': {'x': 0.31, 'y': 0.29}, 'name': 'Зал', 'kind': 'living', 'built': False},
              {'panel': 'p0', 'srcId': 'k1', 'anchor': {'x': 0.2, 'y': 0.8}, 'name': 'Кухня-столовая', 'built': False}]
    ops = [{'panel': 'p0', 'key': 's0', 'srcIdx': 0, 'srcC': [500, 200], 'kind': 'door', 'c': [500, 210], 'widthCm': 80, 'built': True}]
    dops = [{'panel': 'p0', 'key': 's1', 'srcIdx': 1, 'srcC': [250, 0], 'kind': 'window', 'c': [260, 0], 'widthCm': 150, 'built': False},
            {'panel': 'p0', 'key': 's0', 'srcIdx': 0, 'srcC': [500, 200], 'kind': 'door', 'c': [500, 220], 'widthCm': 80, 'built': False}]
    reparse(prod, monkeypatch, tmp_path, new, ops=ops, draftEdits=drafts, draftOpeningEdits=dops)
    w = mk(furnish=True)
    d = w.cfg.base / 'reparse-approve'
    d.mkdir(parents=True)
    (d / f'{JID}.json').write_text(json.dumps({'keys': ['p0/k1:lost', 'p0/r1:doors:2→1']}))
    w.loop(max_iter=1)
    assert fails(prod) == [] and w.done == [(RID, 'rebuilt')]
    m = prod.by('/api/trial/worker/rebuild/publish')[0]['reparse']
    assert m['k'] == pytest.approx(1.0) and [(x['key'], x['to']) for x in m['openings']] == [('s0', 's3')]
    dr = m['drafts']
    assert [(x['from'], x['to']) for x in dr['rooms']] == [('r1', 'n1')]
    assert [(x['key'], x['to']) for x in dr['openings']] == [('s1', 's2')]
    assert [(x['kind'], x['key'], x['why']) for x in dr['dropped']] == [
        ('room', 'k1', 'у комнаты правки нет однозначной пары'), ('opening', 's0', 'два проёма на одном')]
    wd = next((tmp_path / 'trial' / JID).glob('r1-*'))
    ed = json.loads((wd / 'result-edited.json').read_text())          # в сборку легла только подтверждённая дверь, черновики — нет
    assert 'Зал' not in {r['name'] for r in ed['panels'][0]['rooms']} and [o.get('user') for o in ed['panels'][0]['openings']].count(True) == 1


def test_reparse_without_bundle_bytes_fails_internal(prod, mk, monkeypatch, tmp_path):
    reparse(prod, monkeypatch, tmp_path, plan(), bundle=None)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert fails(prod) == [('internal', False)]


def test_old_worker_skill_off_gets_no_reparse(prod, mk, monkeypatch, tmp_path):
    """Без конвейера мебели воркер навыков не заявляет — строка reparse ему не отдаётся."""
    reparse(prod, monkeypatch, tmp_path, plan())
    w = mk(furnish=False)
    w.loop(max_iter=1)
    assert 'reparse' not in prod.by('/api/trial/worker/claim')[0] and prod.rebuilds


def test_dry_run_refuses_without_furniture_banks(monkeypatch, tmp_path):
    """Пробный прогон без банков мебели (worktree: они вне git) не идёт: иначе все комнаты `refused/no_products` — ложный блок
    (T-20261111-02/2, FjiO/UwBX в первом прогоне)."""
    from types import SimpleNamespace
    import reissue
    import worker as wk
    for k in ('TRIAL_SETS', 'TRIAL_BEDROOM_SETS', 'BEDROOM_STYLE_SCORES'):
        monkeypatch.setenv(k, str(tmp_path / f'{k}.json'))
    assert len(reissue.missing_banks()) == 3
    cfg = wk.Cfg.from_env({'TRIAL_WORKER_TOKEN': 'w' * 40, 'TRIAL_WORK_DIR': str(tmp_path / 'w')})
    a = SimpleNamespace(dry_run=True, out=str(tmp_path / 'out'), approve=None, sheets=None)
    assert reissue.reparse_main(a, None, cfg, [JID]) == 2 and not (tmp_path / 'out').exists()
    for k in ('TRIAL_SETS', 'TRIAL_BEDROOM_SETS', 'BEDROOM_STYLE_SCORES'):
        (tmp_path / f'{k}.json').write_text('{}')
    assert reissue.missing_banks() == []


def test_copy_is_untouched():
    """Перевод правок не меняет входные правки (их же шлёт сервер повторно при новой попытке)."""
    e = [{'panel': 'p0', 'key': 's0', 'srcIdx': 0, 'srcC': [500, 200], 'kind': 'door', 'c': [500, 210], 'widthCm': 80}]
    keep = copy.deepcopy(e)
    OE.translate(e, plan(), plan(ops_order=(3, 2, 1, 0)), 1.0)
    assert e == keep


def test_reparse_published_with_preview_sends_drawing_after_publish(prod, mk, monkeypatch, tmp_path):
    """T-20261112-52: перечитанный план принят с новым `result`, в нём превью чертежа → картинка уходит ПОСЛЕ публикации версии
    (не принятая версия не разведёт раскладку вырезов и картинку), Bearer, без аренды."""
    new = plan(ids=('n1', 'n2', 'n3'))
    new['source'] = {'preview': {'w': 10, 'h': 10, 'crops': [{'panel': 'p0', 'sheet': [0, 0, 10, 10], 'at': [0, 0, 10, 10]}]}}
    reparse(prod, monkeypatch, tmp_path, new)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert w.done == [(RID, 'rebuilt')]
    paths = [p for p, _, _ in prod.reqs]
    src = f'/api/trial/worker/{JID}/source'
    assert paths.count(src) == 1 and paths.index(src) > paths.index('/api/trial/worker/rebuild/publish')
    body = prod.by(src)[0]
    import base64
    assert body['id'] == JID and base64.b64decode(body['webp']).startswith(b'RIFF') and b'reread' in base64.b64decode(body['webp'])


def test_reparse_same_reading_sends_no_drawing(prod, mk, monkeypatch, tmp_path):
    """Прочитано то же самое — новой версии с `result` нет, картинку не шлём (у тура прежняя раскладка)."""
    reparse(prod, monkeypatch, tmp_path, plan())
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert prod.by(f'/api/trial/worker/{JID}/source') == []
