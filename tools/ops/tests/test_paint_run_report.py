"""Тесты сводки и страниц прогона покраски `tools/ops/paint_run_report.py` (T-20261122-180/4): сумма сходится, расхождение → ошибка → ненулевой код.

Только на временных папках и подставных кадрах (правила конвейера и рендер не нужны): проверяем счёт, самопроверку, слова для владельца и страницы.
Запуск: `python -m pytest tools/ops/tests/test_paint_run_report.py -q`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paint_run_report as prr  # noqa: E402

ST = ['01-trellis', '04-camera', '08-material', '09-check']
REPO = Path(__file__).resolve().parents[3]


def rows(*statuses, reasons=None):
    return [{'stage': s, 'status': st, 'reason': (reasons or {}).get(s, '')} for s, st in zip(ST, statuses)]


PER = {
    'a': rows('ok', 'ok', 'ok', 'ok'),                                                                            # покрашен, строго
    'b': rows('ok', 'ok', 'ok', 'soft'),                                                                          # покрашен, с замечаниями
    'c': rows('ok', 'refused', 'missing', 'refused', reasons={'04-camera': 'IoU силуэта 0.7 < 0.85'}),            # остановился на 04
    'd': rows('ok', 'ok', 'refused', 'refused', reasons={'08-material': 'confident_share 0.7'}),                  # остановился на 08, модели нет
    'e': rows('ok', 'ok', 'ok', 'refused', reasons={'09-check': 'охват'}),                                        # покрашен, не прошёл
}
PAINTED = {'a', 'b', 'e'}
NAMES = {k: f'Товар {k.upper()}' for k in PER}


def test_summary_sums():
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3, names=NAMES, cards=5)
    assert s['n'] == 5 and s['stopped'] == 2 and s['painted'] == 3
    assert {x['stage']: x['count'] for x in s['stopped_by_stage']} == {'04-camera': 1, '08-material': 1}
    assert s['painted_final'] == {'ok': 1, 'soft': 1, 'refused': 1, 'missing': 0} and s['painted_strict'] == 1
    assert s['stopped_by_stage'][0]['items'][0]['name'] == 'Товар C' and s['errors'] == []


def test_stop_prefers_refused_over_missing():
    assert prr.stop_of(PER['c']) == ('04-camera', 'IoU силуэта 0.7 < 0.85')
    assert prr.stop_of(rows('ok', 'ok', 'ok', 'missing'))[0] == '09-check'
    st, why = prr.stop_of(rows('ok', 'ok', 'ok', 'ok'))
    assert why and st == '09-check'                                                                                 # прошёл всё, а модели нет — это причина, а не пустота


def test_verify_catches_mismatch():
    assert any('папок товаров' in e for e in prr.summarise(PER, PAINTED, 't', n_dirs=6, frames=3)['errors'])
    assert any('кадров' in e for e in prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=2)['errors'])
    assert any('карточек' in e for e in prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3, cards=4)['errors'])
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3)
    s['stopped'] += 1
    assert prr.verify(s)                                                                                            # подкрутили число — ошибка
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3)
    s['stopped_by_stage'][0]['items'][0]['reason'] = ''
    assert any('причины' in e for e in prr.verify(s))


def test_words_for_owner():
    W = prr.load_words(REPO)                                                                                        # настоящие json рядом с правилами
    assert prr.stage_name(W, '04-camera') == 'камера как на фото' and prr.stage_name(W, '02-prep') == 'подготовка формы'
    assert prr.say(W, 'IoU силуэта 0.721 < 0.85; форма вне фото: extra 0.160') == 'форма не совпадает с фото'
    assert prr.say(W, 'shape_mismatch: …; IoU силуэта 0.777 < 0.85') == 'форма не совпадает с фото'                    # две строки таблицы, одна фраза — без повтора
    assert prr.say(W, 'форма вне фото внизу: extra_bottom 0.744 > 0.6') == 'низ формы шире фото'
    assert prr.say(W, 'known_share 0.04 (нужно >= 0.15); edge_corr 0.37') == 'на фото мало видно этой стороны'
    assert prr.say(W, 'не прошли: far_excess_pct 18.41 <= 10.0') == 'заливка дала много чужого цвета'
    assert prr.say(W, 'normal_dev_p99_deg 55.8 > 32.0') == 'складки на гладкой поверхности'
    assert prr.say(W, 'тонкие куски (ножки/стойки) остались в объёмной части') == 'ножки не отделились'
    assert prr.say(W, 'странная причина без фразы') == 'странная причина без фразы'                                  # нет фразы — показываем текст
    assert prr.say({}, 'IoU силуэта') == 'IoU силуэта' and prr.stage_name({}, '07-fill') == '07-fill'                # нет json — не падаем
    assert prr.stage_pct(W, 'cutout') is not None and prr.stage_pct(W, 'нет-такого') is None


def test_md_and_page_have_the_numbers():
    W = prr.load_words(REPO)
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3, names=NAMES, cards=5)
    md = prr.render_md(s, W)
    assert 'Вошло: 5' in md and 'Не дошли до готовой модели: 2' in md and 'Покрашено (есть итоговая модель этапа 8): 3' in md and 'карточек на странице: 5' in md and 'ОШИБКА' not in md
    assert 'камера как на фото' in md and 'Товар C' in md and 'форма не совпадает с фото' in md
    bad = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=2)
    assert 'ОШИБКА СВОДКИ' in prr.render_md(bad)
    cards = [{'sku': k, 'name': NAMES[k], 'final': 'ok', 'strict': True, 'reason': '', 'foto': f'img/{k}_1.jpg', 'view3d': f'img/{k}_2.jpg'} for k in ('a', 'b', 'e')]
    stop = [{'sku': 'c', 'name': NAMES['c'], 'stop_stage': '04-camera', 'reason': PER['c'][1]['reason'], 'foto': 'img/c1.jpg', 'frame': 'img/c2.jpg', 'frame_stage': '04-camera'},
            {'sku': 'd', 'name': NAMES['d'], 'stop_stage': '08-material', 'reason': 'x', 'foto': None, 'frame': None, 'frame_stage': None}]
    page = prr.render_page(s, cards, stop, 'T', W)
    assert page.count('<img ') == 8 and '<script' not in page and 'viewport' in page
    assert 'встал на: камера как на фото (04-camera)' in page and 'форма не совпадает с фото' in page and '<details>' in page and 'прошёл проверку' in page
    assert 'кадра нет' in page and 'фото нет' in page                                                               # карточка есть и без картинок
    assert '>Товар A<' in page and "class='id'>a<" in page                                                          # название — заголовком, id — мелко


def _fake_run(root: Path, skus, painted):
    for k in skus:
        for st in ('01-trellis', '09-check'):
            (root / k / st).mkdir(parents=True)
        if k in painted:
            (root / k / '08-material').mkdir(parents=True)
            (root / k / '08-material' / 'material.glb').write_bytes(b'g')


def test_report_end_to_end(tmp_path, capsys):
    run = tmp_path / 'run'
    _fake_run(run, list(PER), PAINTED)
    ok = lambda repo, runof, skus, out: {'ok': {k: {'foto': f'img/{k}_1.jpg', 'view3d': f'img/{k}_2.jpg'} for k in skus}, 'errors': {}}      # noqa: E731
    out = tmp_path / 'out'
    assert prr.report([str(run)], {'run': PER}, str(out), str(REPO), frames_fn=ok, with_stages=False) == 0
    s = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    assert (s['n'], s['stopped'], s['painted'], s['frames'], s['cards']) == (5, 2, 3, 3, 5) and (out / 'index.html').exists() and (out / 'summary.md').exists()
    short = lambda repo, runof, skus, out: {'ok': {k: {'foto': 'x', 'view3d': 'y'} for k in skus[:-1]}, 'errors': {skus[-1]: 'boom'}}          # noqa: E731
    assert prr.report([str(run)], {'run': PER}, str(tmp_path / 'out2'), str(REPO), frames_fn=short, with_stages=False) == 1                  # кадр не построился — ненулевой код
    assert 'ОШИБКА СВОДКИ' in capsys.readouterr().out


def test_report_dir_count_mismatch(tmp_path):
    run = tmp_path / 'run'
    _fake_run(run, list(PER) + ['extra'], PAINTED)                                                                  # на диске товар, которого нет в решениях
    ok = lambda repo, runof, skus, out: {'ok': {k: {'foto': 'x', 'view3d': 'y'} for k in skus}, 'errors': {}}       # noqa: E731
    assert prr.report([str(run)], {'run': PER}, str(tmp_path / 'o'), str(REPO), frames_fn=ok, with_stages=False) == 1


def test_union_takes_first_run(tmp_path):
    r1, r2 = tmp_path / 'r1', tmp_path / 'r2'
    _fake_run(r1, ['a', 'c'], {'a'})
    _fake_run(r2, ['a', 'b'], {'a', 'b'})
    seen = {}

    def fake(repo, runof, skus, out):
        seen.update(runof)
        return {'ok': {k: {'foto': 'x', 'view3d': 'y'} for k in skus}, 'errors': {}}
    per1 = {k: PER[k] for k in ('a', 'c')}
    per2 = {k: PER[k] for k in ('a', 'b')}
    assert prr.report([str(r1), str(r2)], {'r1': per1, 'r2': per2}, str(tmp_path / 'o'), str(REPO), frames_fn=fake, with_stages=False) == 0
    s = json.loads((tmp_path / 'o' / 'summary.json').read_text(encoding='utf-8'))
    assert s['n'] == 3 and seen['a'] == str(r1)                                                                     # повтор sku — из первого прогона; N без повторов


def test_stage_summary_sums():
    for st in ST:
        s = prr.stage_summary(PER, st)
        assert s['reached'] == s['ok'] + s['soft'] + s['refused'] and s['reached'] + s['not_reached'] == s['n'] == 5 and s['errors'] == []
    s = prr.stage_summary(PER, '04-camera')
    assert (s['reached'], s['ok'], s['refused']) == (5, 4, 1) and s['items']['c']['reason'] == 'IoU силуэта 0.7 < 0.85'
    assert prr.stage_summary(PER, '08-material')['not_reached'] == 1                                                # у «c» нет check.json этапа 8


def test_stage_pages_and_stopped_frames(tmp_path):
    from PIL import Image
    run = tmp_path / 'run'
    _fake_run(run, list(PER), PAINTED)
    photos = {}
    for k in PER:
        Image.new('RGBA', (40, 30), (200, 10, 10, 255)).save(tmp_path / f'{k}.png')
        photos[k] = str(tmp_path / f'{k}.png')
        for st in ST:
            (run / k / st).mkdir(parents=True, exist_ok=True)
            if not (k == 'c' and st in ('08-material', '09-check')):                                                # у «c» кадров дальше камеры нет
                Image.new('RGBA', (50, 20), (10, 10, 200, 255)).save(run / k / st / 'frame.png')
    runof = {k: str(run) for k in PER}
    W = prr.load_words(REPO)
    out = tmp_path / 'o'
    sums, errs = prr.stage_pages(PER, runof, str(out), W, 'T', NAMES, photos)
    assert errs == [] and set(sums) == set(ST)
    page = (out / '04-camera' / 'index.html').read_text(encoding='utf-8')
    assert 'камера как на фото' in page and 'готовность этапа 50 %' in page and 'вошло 5' in page and "href='../01-trellis/'" in page and page.count('<img ') == 10 and '<script' not in page
    assert '>Товар C<' in page and 'форма не совпадает с фото' in page and 'встал' in page
    assert (out / '04-camera' / 'img' / 'a_2-04.jpg').exists() and (out / 'stages.json').exists()
    assert sums['09-check']['no_frame'] == 1                                                                        # у «c» этап 9 запускался (refused), кадра нет — видно числом, не молчанием
    page9 = (out / '09-check' / 'index.html').read_text(encoding='utf-8')
    assert 'без кадра этапа 1' in page9 and 'кадра нет' in page9
    sf = prr.stopped_frames(runof, PER, [('c', '04-camera'), ('d', '08-material')], photos, str(tmp_path / 'sf'))
    assert sf['c']['frame_stage'] == '04-camera' and sf['d']['frame_stage'] == '08-material' and (tmp_path / 'sf' / sf['c']['frame']).exists()
    (run / 'd' / '08-material' / 'frame.png').unlink()
    sf = prr.stopped_frames(runof, PER, [('d', '08-material')], photos, str(tmp_path / 'sf2'))
    assert sf['d']['frame_stage'] == '04-camera'                                                                    # нет кадра этапа остановки — берём последний, что есть


def test_stage_pages_without_words_json(tmp_path):
    run = tmp_path / 'run'
    _fake_run(run, list(PER), PAINTED)
    runof = {k: str(run) for k in PER}
    out = tmp_path / 'o'
    sums, errs = prr.stage_pages(PER, runof, str(out), {}, 'T', NAMES, {k: None for k in PER})
    assert errs == [] and 'готовность этапа не задана' in (out / '04-camera' / 'index.html').read_text(encoding='utf-8')   # нет файла готовности — не падаем


def test_names_photos_for_early_stopped(tmp_path):
    run = tmp_path / 'run'
    (run / 'c').mkdir(parents=True)
    ph = tmp_path / 'c.rgba.png'
    ph.write_bytes(b'x')
    (run / 'c' / 'run_all.json').write_text(json.dumps({'steps': [{'cmd': ['x', '--photo', str(ph)]}]}), encoding='utf-8')
    assert prr.photo_paths({'c': []}, {'c': str(run)}) == {'c': str(ph)}                                            # у остановившегося до этапа 5 нет манифеста — фото из run_all.json
    assert prr.photo_paths({'z': []}, {'z': str(run)}) == {'z': None}
    cat = tmp_path / 'cat.json'
    cat.write_text(json.dumps([{'id': 'c', 'name': 'Торшер', 'role': 'торшер'}, {'sid': 'd', 'name': 'Стол'}]), encoding='utf-8')
    assert prr.load_catalog(str(cat))['c']['name'] == 'Торшер' and prr.load_catalog(str(cat))['d']['name'] == 'Стол' and prr.load_catalog(None) == {}


def test_names_ru_from_repo():
    ru = prr.load_names_ru(str(REPO))
    assert len(ru) > 100 and all(isinstance(v, str) and v for v in ru.values())                                     # запасной источник названий — витрина репозитория
    assert prr.load_names_ru('/нет/такой/папки') == {}


def test_catalog_items_wrapper(tmp_path):
    p = tmp_path / 'set.json'
    p.write_text(json.dumps({'count': 1, 'items': [{'id': 'x', 'name': 'Ваза', 'role': 'ваза'}]}), encoding='utf-8')
    assert prr.load_catalog(str(p))['x']['name'] == 'Ваза'                                                          # формат набора р.2 (set40.json) читается как каталог


def test_stage9_entered_only_those_reached_material():
    s = prr.stage_summary(PER, '09-check')
    # у «c» (08 нет check.json) и у «d» (08 refused, но этап 8 запускался): вошли только те, у кого этап 8 был — a, b, d, e
    assert s['entered'] == 4 and s['not_reached'] == 1 and s['reached'] == 4 and s['items']['c']['status'] == 'missing' and s['errors'] == []
    assert prr.stage_summary(PER, '04-camera')['entered'] == 5


def test_frame_captions():
    W = prr.load_words(REPO)
    assert prr.frame_caption(W, '04-camera') == 'красное — наша форма, зелёная линия — контур фото'
    assert all(prr.frame_caption(W, st) for st in ('01-trellis', '02-prep', '03-parts', '05-delight', '06-visible', '07-fill', '08-material', '09-check'))
    assert prr.frame_caption({}, '04-camera') == ''


def test_removed_product_name(tmp_path):
    run = tmp_path / 'run'
    _fake_run(run, ['a', 'z'], {'a'})
    cat = tmp_path / 'cat.json'
    cat.write_text(json.dumps([{'id': 'a', 'name': 'Стул'}]), encoding='utf-8')
    ok = lambda repo, runof, skus, out: {'ok': {k: {'foto': 'x', 'view3d': 'y'} for k in skus}, 'errors': {}}       # noqa: E731
    per = {'a': PER['a'], 'z': PER['c']}
    assert prr.report([str(run)], {'run': per}, str(tmp_path / 'o'), str(REPO), frames_fn=ok, with_stages=False, catalog=str(cat)) == 0
    page = (tmp_path / 'o' / 'index.html').read_text(encoding='utf-8')
    assert '>Стул<' in page and 'товар снят с продажи' in page and "class='id'>z<" in page                         # нет в базе — «снят с продажи» + id мелко


def test_slug_keeps_case():
    assert prr.slug('e2eHD-1121-union') == 'paint-e2eHD-1121-union' and prr.slug('a b/c') == 'paint-a-b-c' and prr.slug('') == 'paint-run'
