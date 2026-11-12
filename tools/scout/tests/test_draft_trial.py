"""Фото тура пробы в сервисе кадров (T-20261109-34, `draft_trial`): суточный предел задания, только по кадрам из 3D, фото товаров из каталога
по модели (ссылкам страницы не верим), без общего реестра и без запасного рендера прода. Ручки — на настоящем HTTP-сервере, рендер и
постановка в фон подменены: платных вызовов нет."""

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import draft_trial as DT  # noqa: E402

TID = 'A' * 22
VIEWS = [{'camera': 'C1', 'id': 'a' * 64}, {'camera': 'C2', 'id': 'b' * 64}]


def test_trial_id_and_views():
    assert DT.trial_id({}) is None and DT.trial_id({'trial': TID}) == TID
    assert DT.trial_id({'trial': '../x'}) == '' and DT.trial_id({'trial': 5}) == ''
    assert DT.has_views({'views': VIEWS}) and not DT.has_views({'views': VIEWS[:1]}) and not DT.has_views({})
    assert DT.daily_limit({}) == 10 and DT.daily_limit({'TRIAL_PHOTO_DAILY': '3'}) == 3 and DT.daily_limit({'TRIAL_PHOTO_DAILY': 'x'}) == 10


def test_daily_counts_per_job_for_a_rolling_day(tmp_path):
    d = DT.TrialDaily(str(tmp_path / 'share' / 'trial-photos.json'), 2)
    assert d.take(TID, 1000) and d.take(TID, 1001) and not d.take(TID, 1002)
    assert d.take('B' * 22, 1002)                                    # другое задание — свой счёт
    later = 1001 + DT.DAY_S
    assert d.take(TID, later) and d.take(TID, later + 1)             # через сутки места освободились
    # счёт переживает перезапуск (файл), битый файл — с нуля, а не отказ навсегда
    assert not DT.TrialDaily(d.path, 2).take(TID, later + 2)
    open(d.path, 'w').write('{oops')
    assert DT.TrialDaily(d.path, 2).take(TID, 5000)


def test_fill_imgs_from_catalog_only_by_model():
    p = {'items': [{'role': 'диван', 'msid': '112923_607', 'img': 'https://evil.example/x.jpg', 'url': 'u', 'price': 1},
                   {'role': 'ковёр', 'msid': None, 'img': '/demo/img/a.jpg'}, {'role': 'кресло', 'msid': '5_zz'}]}
    seen = []

    def lookup(ms):
        seen.append(sorted(ms))
        return {'112923_607': '//img.example/sofa.jpg'}
    assert DT.fill_imgs(p, lookup) == (3, 1)
    assert seen == [['112923_607', '5_zz']]
    assert p['items'][0] == {'role': 'диван', 'msid': '112923_607', 'img': '//img.example/sofa.jpg'}
    assert 'img' not in p['items'][1] and 'img' not in p['items'][2]


def test_catalog_imgs_one_query_cached_and_safe(monkeypatch):
    monkeypatch.setattr(DT, '_IMG_CACHE', {})
    sqls = []

    def fetch(sql):
        sqls.append(sql)
        return [['112923', '607', '//img/sofa.jpg'], ['7', "o'k", None]]
    got = DT.catalog_imgs(['112923_607', "7_o'k", 'bad', '112923_607'], fetch)
    assert got == {'112923_607': '//img/sofa.jpg'} and len(sqls) == 1
    assert "(112923,'607')" in sqls[0] and "(7,'o''k')" in sqls[0] and 'bad' not in sqls[0]
    assert DT.catalog_imgs(['112923_607', "7_o'k"], fetch) == {'112923_607': '//img/sofa.jpg'} and len(sqls) == 1   # кэш, и пустых тоже

    def broken(sql):
        raise RuntimeError('нет базы')
    assert DT.catalog_imgs(['9_x'], broken) == {}


def _jpeg(color=(200, 10, 10)) -> bytes:
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (900, 700), color).save(b, 'JPEG')
    return b.getvalue()


def test_warm_photos_showcase_copy_first_then_shop_with_retries(tmp_path):
    import hashlib
    from PIL import Image
    u1, u2, u3 = '//img.shop/a.jpg', '//img.shop/b.jpg', '//img.shop/c.jpg'
    n = {u: hashlib.md5(u.encode()).hexdigest()[:16] for u in (u1, u2, u3)}
    assert DT.photo_sources(u1, 'https://x.test') == [f'https://x.test/demo/img/{n[u1]}-l.jpg', f'https://x.test/demo/img/{n[u1]}.jpg',
                                                      'https:' + u1]
    calls = []
    store = {f'https://x.test/demo/img/{n[u1]}-l.jpg': _jpeg(), 'https://img.shop/b.jpg': _jpeg((0, 0, 200)), 'https://img.shop/c.jpg': b'oops'}

    def get(url, tries):
        calls.append((url, tries))
        return store.get(url)
    assert DT.warm_photos([u1, u2, u3, u1, None], str(tmp_path), 'https://x.test', get) == 2
    # u1 — копия витрины, магазин не тронут; u2 — копии нет → магазин с 3 попытками; u3 — магазин отдал не картинку → нет фото
    assert [c for c in calls if c[0] == 'https://img.shop/a.jpg' or n[u1] in c[0]] == [(f'https://x.test/demo/img/{n[u1]}-l.jpg', 1)]
    assert ('https://img.shop/b.jpg', 3) in calls
    im = Image.open(tmp_path / f'{n[u1]}.png')
    assert max(im.size) == 640                                         # тот же размер, что кладёт draft_render.photo
    assert not (tmp_path / f'{n[u3]}.png').exists()
    calls.clear()
    assert DT.warm_photos([u1, u2], str(tmp_path), 'https://x.test', get) == 2 and calls == []   # уже в кэше — сети нет


# ───────── ручки сервиса ─────────

@pytest.fixture()
def svc(tmp_path, monkeypatch):
    import draft_service as S
    monkeypatch.setattr(S, 'TRIAL_DAY', DT.TrialDaily(str(tmp_path / 'trial-photos.json'), 2))
    monkeypatch.setattr(S, 'JOBS', S.JobStore(str(tmp_path / 'jobs.json')))
    monkeypatch.setattr(S, '_paid_gate', lambda: None)
    monkeypatch.setattr(S, '_work', lambda jid: None)
    calls = {'render': [], 'registry': []}

    def render(layout=None, **kw):
        calls['render'].append(json.loads(json.dumps(layout)))
        return {'shots': [{'camera': 'C1', 'url': '/x.jpg'}], 'url': '/x.jpg', 'model': 'm', 'diag': {}}
    monkeypatch.setattr(S.DR, 'render', render)
    monkeypatch.setattr(S, '_registry_add', lambda p, o: calls['registry'].append(p))
    monkeypatch.setattr(S.DT, 'fill_imgs', lambda p: (len(p['items']), 0))
    monkeypatch.setattr(S.DT, 'warm_photos', lambda *a, **k: 0)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), S.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}'

    def post(body, ip='10.0.0.1'):
        req = urllib.request.Request(base + '/render', data=json.dumps(body).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'X-Forwarded-For': ip})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield S, post, calls, monkeypatch
    srv.shutdown()


def order(**over):
    return {'room': {'w': 400, 'd': 300}, 'items': [{'role': 'диван', 'x': 1, 'y': 1, 'msid': '1_a'}], 'trial': TID, 'views': VIEWS,
            'quality': 'realistic', 'async': 1, **over}


def test_service_trial_needs_views_and_valid_id(svc):
    S, post, calls, _ = svc
    assert post(order(views=VIEWS[:1]))[0] == 422 and post(order(views=VIEWS[:1]))[1]['code'] == 'no_views'
    assert post(order(trial='x/../y'))[1]['code'] == 'bad_trial'
    assert calls['render'] == []


LIVING = {'w': 439, 'd': 325, 'openings': [{'kind': 'window', 'wall': 'west', 'offset_cm': 70, 'width_cm': 150},
                                           {'kind': 'door', 'wall': 'east', 'offset_cm': 205, 'width_cm': 90}]}
BED1 = {'w': 597, 'd': 293, 'openings': [{'kind': 'door', 'wall': 'south', 'offset_cm': 24, 'width_cm': 90},
                                         {'kind': 'window', 'wall': 'east', 'offset_cm': 40, 'width_cm': 210},
                                         {'kind': 'window', 'wall': 'north', 'offset_cm': 197, 'width_cm': 240}]}


def test_room_sig_matches_page_rule():
    # тот же текст, что `roomSig` страницы: размеры, проёмы по алфавиту, округление половины вверх, порядок проёмов не важен
    assert DT.room_sig(LIVING) == '439x325|door:east:205:90;window:west:70:150'
    assert DT.room_sig({**LIVING, 'openings': LIVING['openings'][::-1]}) == DT.room_sig(LIVING)
    assert DT.room_sig({'w': 438.5, 'd': '325', 'openings': [{'kind': 'door', 'wall': 'east', 'offset_cm': 0.5, 'width_cm': None}]}) \
        == '439x325|door:east:1:0'
    assert DT.room_sig(None) == '' and DT.room_sig({}) == '0x0|'


def test_views_of_another_room_are_refused(svc):
    # заказ f24c0cc7 (T-20261112-108/2): мебель гостиной, кадры — из сцены спальни 1 → отказ до любых трат, и в демо, и в туре
    S, post, calls, _ = svc
    bed = [dict(v, room=DT.room_sig(BED1)) for v in VIEWS]
    for extra in ({}, {'trial': None}):
        st, body = post(order(room=LIVING, views=bed, **extra))
        assert st == 422 and body['code'] == 'scene_room'
    assert calls['render'] == [] and calls['registry'] == []
    # кадры этой комнаты и кадры без подписи (страница до правила) — проходят
    assert post(order(room=LIVING, views=[dict(v, room=DT.room_sig(LIVING)) for v in VIEWS]))[0] == 200
    assert post(order(room=LIVING, trial='B' * 22))[0] == 200
    assert DT.views_room_mismatch({'room': LIVING, 'views': bed}) and not DT.views_room_mismatch({'room': LIVING})


def test_service_trial_daily_limit_on_async_and_direct(svc):
    S, post, calls, mp = svc
    assert post(order())[0] == 200 and post(order())[0] == 200
    st, body = post(order())
    assert st == 429 and body['code'] == 'photo_limit'
    assert post(order(trial='B' * 22))[0] == 200                   # другое задание
    # прямой заказ без фона (мимо ручки приложения) — тот же счёт; внутренний вызов фонового задания (`_job`) не считается
    mp.setattr(S, '_proxy_url', lambda: '')
    st, body = post(order(trial='B' * 22, **{'async': 0}))
    assert st == 200 and len(calls['render']) == 1
    assert post(order(trial='B' * 22, **{'async': 0}))[1]['code'] == 'photo_limit'
    assert post(order(trial='B' * 22, _job='j1', **{'async': 0}))[0] == 200


def test_service_trial_renders_without_registry_and_never_locally_on_proxy_failure(svc):
    S, post, calls, mp = svc
    mp.setattr(S, '_proxy_url', lambda: '')                         # DEV: рисует сам
    st, _ = post(order(src_id='s1', quality='draft', **{'async': 0}))
    sent = calls['render'][-1]
    assert st == 200 and sent['quality'] == 'realistic' and sent['no_registry'] == 1 and 'src_id' not in sent
    assert calls['registry'] and all(p.get('trial') for p in calls['registry'])   # вызов есть — сама запись ниже отсекается
    # прод: DEV молчит — тур не рисуется запасным путём
    mp.setattr(S, '_proxy_url', lambda: 'http://127.0.0.1:9/render')
    n = len(calls['render'])
    st, body = post(order(**{'async': 0}))
    assert st == 503 and body['code'] == 'unavailable' and len(calls['render']) == n


def test_registry_skips_trial(tmp_path, monkeypatch):
    import draft_service as S
    monkeypatch.setattr(S, 'load_pub', lambda *a: (_ for _ in ()).throw(AssertionError('реестр тронут')))
    S._registry_add({'trial': TID, 'items': []}, {'shots': [{'url': '/x.jpg'}]})   # не падает и ничего не пишет
