"""ТАРИФ ФОТО «mass» (план photo-tariff-mass-01, T-20261117-03; Codex `_intake/codex/2026-11-17-photo-tariff-mass-answer.md` п.5). Без сети и модели:
кадры, фото товаров и вызов модели — поддельные (`_tariff_fixture.py`). Что доказывают тесты:
  1) standard — побайтно прежний: отпечаток текста и PNG-входов (золото снято с кода до тарифов), ключ ответа тот же;
  2) mass с декором и без — число входов, нет ссылки на несуществующий IMAGE 3, размеры, качество low, абзац согласованности;
  3) нет данных — пропадает только абзац; 4) геометрия комнаты, камеры, предметы и версия правила меняют ключ mass;
  5) повтор — одна оплата, одновременный повтор — одна оплата, другой тариф не берётся из кэша ни в ту, ни в другую сторону;
  6) `paid_gate` отказывает ДО вызова, пропавшая полоса — ПОСЛЕ (ответ негоден и в кэш не пишется);
  7) mass только у тура с доверенным полем; правило тарифов читается, неизвестное имя — standard.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_photo_tariff.py -q"""
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest
from PIL import Image

import _tariff_fixture as F

DR, IM = F.DR, F.IM
MODEL = 'openai/gpt-image-2.5-sunburst'

# золото: отпечатки входов standard, снятые на коде ДО тарифов (`_tariff_golden_dump.py`, ветка main a14af82f)
GOLD_INPUTS = {
    'decor': {'prompt_sha': '3c2972ac70fb1f54ee5f', 'prompt_len': 12911, 'sizes': [[2048, 3072], [1560, 500], [1040, 500]],
              'png': ['f88e4a977510f2c1679f', '683b3ea9c1ca5953cbf9', '9610bb937f33dd14ff98'], 'size': '2048x3072'},
    'nodecor': {'prompt_sha': '68ec7358a3376a7ffb5c', 'prompt_len': 11758, 'sizes': [[2048, 3072], [1560, 500]],
                'png': ['f88e4a977510f2c1679f', '683b3ea9c1ca5953cbf9'], 'size': '2048x3072'},
}
# золото: ключи ответа standard старого `frames_key` (`_tariff_golden_key.py`, он же `git show main:…`)
GOLD_KEYS = {'decor': '25da53f2028afebf5f8bfc6aceb06f00', 'nodecor': 'd223c48d4aa2da1c749a0c9770e70277', 'portrait': '3b0c6b3b0811cc80843dc61a8e31f866'}


def with_tariff(pl: dict, name: str = 'mass') -> dict:
    return {**pl, '_tariff': name}


# ───────── 1. standard — побайтно прежний ─────────

@pytest.mark.parametrize('name,decor', [('decor', True), ('nodecor', False)])
def test_standard_inputs_are_byte_identical(name, decor):
    pl = F.payload(with_decor=decor)
    assert F.fingerprint(F.build(pl)) == GOLD_INPUTS[name]
    assert F.fingerprint(F.build(pl, tariff='standard')) == GOLD_INPUTS[name]              # явный standard — то же
    assert F.fingerprint(F.build(with_tariff(pl))) == GOLD_INPUTS[name]                    # сама сборка тариф берёт только параметром


def test_standard_key_is_byte_identical():
    m, q = MODEL, 'medium'
    assert IM.frames_key(F.payload(), m, q) == GOLD_KEYS['decor'] == IM.frames_key(F.payload(), m, q, 'standard')
    assert IM.frames_key(F.payload(with_decor=False), m, q) == GOLD_KEYS['nodecor']
    pp = {**F.payload(), 'sheet': 'portrait'}
    assert IM.frames_key(pp, m, q) == GOLD_KEYS['portrait']


# ───────── 2. mass: входы, номера IMAGE, размеры, качество ─────────

def test_mass_with_decor_two_inputs_one_reference():
    pl = F.payload(with_decor=True)
    b = F.build(pl, tariff='mass')
    imgs = F.inputs_of(b)
    assert len(imgs) == 2 and b['dsheet'] is None                         # лист двух видов + ОДНА справочная картинка
    assert imgs[0].size == (832, 1248) and b['size'] == '2048x3072'       # вход меньше, выход прежний
    assert imgs[1].size == (round(1560 * 0.44), round((500 + 500 + 16) * 0.44))       # товары над декором, ×0,44
    p = b['prompt']
    assert 'IMAGE 3' not in p and 'THREE' not in p and 'You are given TWO images' in p and 'the DECOR part' in p     # нет несуществующего IMAGE 3
    assert 'VIEW CONSISTENCY' in p and p.rfind('VIEW CONSISTENCY') < p.rfind('\nOUTPUT')
    assert (b['n_items'], b['n_photos']) == (3, 3) and b['tariff'] == 'mass'            # счёт фото листа — по исходному листу товаров
    assert IM.tariff_quality('mass', 'medium') == 'low' and IM.tariff_quality('standard', 'medium') == 'medium'


def test_mass_band_survives_downscale():
    b = F.build(F.payload(), tariff='mass')
    sheet = b['sheet']
    k = 832 / 2048
    y = round((1489 + DR.BAND_PX / 2) * k)
    assert sheet.getpixel((400, y)) == DR.BAND_RGB                              # полоса-разделитель на месте
    pieces = [DR._trim_band(x) for x in DR._split_pair(sheet)]
    assert len(pieces) == 2 and all(abs(p.width - 832) <= 2 for p in pieces)


def test_mass_without_decor_has_no_third_sheet_wording():
    b = F.build(F.payload(with_decor=False), tariff='mass')
    imgs = F.inputs_of(b)
    assert len(imgs) == 2 and imgs[0].size == (832, 1248) and imgs[1].size == (round(1560 * 0.44), round(500 * 0.44))
    p = b['prompt']
    assert 'IMAGE 3' not in p and 'DECOR part' not in p and 'one reference sheet' not in p and 'VIEW CONSISTENCY' in p
    # текст = standard + абзац согласованности (ничего лишнего не меняется)
    std = F.build(F.payload(with_decor=False))['prompt']
    assert p.replace(p[p.index('VIEW CONSISTENCY'):p.rindex('\nOUTPUT')], '').replace('\n\n\n\n', '\n\n') .replace('\n\n\n', '\n\n') == std.replace('\n\n\n', '\n\n')


# ───────── 3. нет данных — пропадает только абзац ─────────

def test_missing_data_drops_only_the_paragraph(capsys):
    base = F.build(F.payload(), tariff='mass')
    cases = {'cams': lambda p: p.update(cams=[]), 'openings': lambda p: p['room'].update(openings=[]),
             'room': lambda p: p.update(room={}), 'pose': lambda p: p['cams'][0].pop('rot')}
    for name, brk in cases.items():
        pl = F.payload()
        brk(pl)
        b = F.build(pl, tariff='mass')
        imgs = F.inputs_of(b)
        assert 'VIEW CONSISTENCY' not in b['prompt'], name
        assert len(imgs) == 2 and imgs[0].size == (832, 1248) and 'IMAGE 3' not in b['prompt'], name         # тариф остался mass
        assert IM.effective_tariff({**pl, 'trial': 'T' * 22, '_tariff': 'mass'}) == 'mass'
    assert capsys.readouterr().out.count('consistency: skip') == len(cases)
    assert 'VIEW CONSISTENCY' in base['prompt']


# ───────── 4. ключ mass зависит от геометрии, поз, предметов и версии правила ─────────

def test_mass_key_depends_on_geometry_and_version(monkeypatch):
    pl = F.payload()
    k = IM.frames_key(pl, MODEL, 'low', 'mass')
    assert k == IM.frames_key(F.payload(), MODEL, 'low', 'mass') and k != IM.frames_key(pl, MODEL, 'low')
    cam = F.payload(); cam['cams'][1]['rot'] += 15
    opening = F.payload(); opening['room']['openings'][0]['offset_cm'] += 20
    size = F.payload(); size['room']['w'] += 30
    item = F.payload(); item['items'][0]['x'] += 25
    for other in (cam, opening, size, item):
        assert IM.frames_key(other, MODEL, 'low', 'mass') != k
        assert IM.frames_key(other, MODEL, 'medium') == IM.frames_key(pl, MODEL, 'medium')        # у standard геометрия в ключ не входит — как было
    monkeypatch.setattr(IM, 'tariffs_version', lambda name: 'v2-other')
    assert IM.frames_key(pl, MODEL, 'low', 'mass') != k                                          # правка правила = новый ключ


def test_tariff_rules_file_is_valid():
    d = IM._load_tariffs()
    assert d['default'] == 'standard' and set(d['tariffs']) >= {'standard', 'mass'}
    m = d['tariffs']['mass']
    assert (m['quality'], m['frame_w'], m['combine_scale'], m['consistency']) == ('low', 832, 0.44, True)
    auto = json.load(open(os.path.join(IM.HERE, 'rules', 'tour-auto-photos.json'), encoding='utf-8'))
    assert auto['photo_tariff'] in d['tariffs']


def test_effective_tariff_only_for_tours_with_trusted_field():
    tour = {'trial': 'T' * 22, '_tariff': 'mass'}
    assert IM.effective_tariff(tour) == 'mass'
    assert IM.effective_tariff({'_tariff': 'mass'}) == 'standard'                   # не тур (кнопка человека, /demo)
    assert IM.effective_tariff({'trial': 'T' * 22}) == 'standard'                   # поля нет
    assert IM.effective_tariff({'trial': 'T' * 22, '_tariff': 'standard'}) == 'standard'
    assert IM.effective_tariff({'trial': 'T' * 22, '_tariff': 'nope'}) == 'standard'
    assert IM.effective_tariff({'trial': 'T' * 22, 'photo_tariff': 'mass'}) == 'standard'    # поле из браузера не читается
    assert IM.effective_tariff(None) == 'standard'


# ───────── 5–6. сквозной путь `DR.render`: кэш, одна оплата, ворота, полоса ─────────

class Rig:
    """Поддельная среда `draft_render.render`: серверной сцены нет, кадры/фото — из заготовки, вызов модели записывается и возвращает лист с полосой."""

    def __init__(self, mp, photos=True, band=True, delay=0.0):
        self.calls, self.store, self.delay = [], {}, delay
        out = IM.sheet_from_views([F.fake_frame(F.FRAME_IDS[0]), F.fake_frame(F.FRAME_IDS[1])]) if band else Image.new('RGB', (2048, 3072), (90, 90, 90))
        mp.delenv('GPT_IMAGE_QUALITY', raising=False)
        mp.setattr(IM, 'load_frame', F.fake_frame)
        mp.setattr(DR, 'photo', F.fake_photo if photos else (lambda u: None))
        mp.setattr(DR, '_publish_sources', lambda *a, **k: None)
        mp.setattr(DR, 'scene_from_request', lambda layout: (None, [], {}))
        mp.setattr(DR, 'cams_from_request', lambda room, pl, layout: [SimpleNamespace(name='C1'), SimpleNamespace(name='C2')])
        mp.setattr(DR, '_publish_frame', lambda img, name: f'/frames/{name}')
        mp.setattr(DR, '_improve_cache', self._cache)

        def gpt(images, prompt, size='2048x3072', quality='medium', model='', mask=None, cost_label=None, cost_tariff=None):
            self.calls.append({'n': len(images), 'sizes': [im.size for im in images], 'prompt': prompt, 'size': size, 'quality': quality,
                               'tariff': cost_tariff, 'label': cost_label})
            time.sleep(self.delay)
            return out.copy()
        mp.setattr(DR, 'gpt_edit', gpt)

    def _cache(self, key, res=None):
        if res is None:
            return self.store.get(key)
        self.store[key] = res

    def render(self, pl):
        return DR.render(layout=pl, quality='realistic')


@pytest.fixture()
def rig(monkeypatch):
    return Rig(monkeypatch)


def test_render_standard_and_mass_calls(rig):
    r1 = rig.render(F.payload())
    c = rig.calls[-1]
    assert (c['n'], c['quality'], c['tariff']) == (3, 'medium', 'standard') and c['sizes'][0] == (2048, 3072)
    assert r1['tariff'] == 'standard' and r1['image_quality'] == 'medium'
    r2 = rig.render(with_tariff(F.payload()))
    c = rig.calls[-1]
    assert (c['n'], c['quality'], c['tariff'], c['label']) == (2, 'low', 'mass', 'trial') and c['sizes'][0] == (832, 1248) and c['size'] == '2048x3072'
    assert 'VIEW CONSISTENCY' in c['prompt'] and 'IMAGE 3' not in c['prompt']
    assert r2['tariff'] == 'mass' and r2['image_quality'] == 'low' and len(r2['shots']) == 2
    assert len(rig.calls) == 2


def test_render_non_tour_never_mass(rig):
    pl = {**with_tariff(F.payload()), 'trial': None}                                  # не тур: поле игнорируется
    r = rig.render(pl)
    assert r['tariff'] == 'standard' and rig.calls[-1]['quality'] == 'medium' and rig.calls[-1]['n'] == 3


def test_render_repeat_is_one_payment_and_tariffs_do_not_mix(rig):
    mass = with_tariff(F.payload())
    a = rig.render(mass)
    b = rig.render(mass)
    assert len(rig.calls) == 1 and b == a                                              # повтор — из кэша, одна оплата
    s = rig.render(F.payload())                                                       # другой тариф — не из кэша mass
    assert len(rig.calls) == 2 and s['tariff'] == 'standard'
    rig.render(F.payload())
    assert len(rig.calls) == 2                                                         # и standard повторно — из своего кэша
    m2 = rig.render(mass)
    assert len(rig.calls) == 2 and m2['tariff'] == 'mass'                              # mass всё ещё из своего


def test_render_foreign_tariff_entry_under_same_key_is_rejected(rig):
    # запись кэша без поля тарифа (старая, standard) под ключом mass не отдаётся как mass
    mass = with_tariff(F.payload())
    key = 'bf-' + IM.frames_key(mass, DR.REALISTIC_MODEL, 'low', 'mass')
    rig.store[key] = {'model': f'improve/{DR.REALISTIC_MODEL}', 'image_quality': 'low', 'prompt_version': IM.PROMPT_VERSION, 'shots': [], 'url': '/old'}
    r = rig.render(mass)
    assert len(rig.calls) == 1 and r['tariff'] == 'mass' and r['url'] != '/old'


def test_render_geometry_change_is_a_new_payment(rig):
    mass = with_tariff(F.payload())
    rig.render(mass)
    turned = with_tariff(F.payload())
    turned['cams'][0]['rot'] += 20
    rig.render(turned)
    assert len(rig.calls) == 2                                                         # от поз зависит абзац — другое задание, другой ключ


def test_render_concurrent_same_order_pays_once(monkeypatch):
    rig = Rig(monkeypatch, delay=0.4)
    mass = with_tariff(F.payload())
    out = []
    ts = [threading.Thread(target=lambda: out.append(rig.render(dict(mass)))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(rig.calls) == 1 and len(out) == 3 and all(o['tariff'] == 'mass' for o in out)


@pytest.mark.parametrize('tariff', ['standard', 'mass'])
def test_paid_gate_refuses_before_the_call(monkeypatch, tariff):
    rig = Rig(monkeypatch)
    pl = with_tariff(F.payload()) if tariff == 'mass' else F.payload()
    for it in pl['items']:
        it['img'] = None                                                               # фото товаров нет — на листе пустые карточки, порог 3/4 не пройден
    with pytest.raises(DR.NoProductSheet):
        rig.render(pl)
    assert rig.calls == [] and rig.store == {}


@pytest.mark.parametrize('tariff', ['standard', 'mass'])
def test_missing_band_is_refused_after_the_call_and_not_cached(monkeypatch, tariff):
    rig = Rig(monkeypatch, band=False)
    pl = with_tariff(F.payload()) if tariff == 'mass' else F.payload()
    with pytest.raises(RuntimeError, match='разделительную полосу'):
        rig.render(pl)
    assert len(rig.calls) == 1 and rig.store == {}                                     # деньги ушли, ответ негоден, в кэш не пишется
