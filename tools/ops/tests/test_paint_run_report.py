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


def test_cutout_status_and_reason():
    ok = {'sku': 'a:1', 'sha': 'h', 'status': 'ok', 'verdict': 'ok', 'mask_verdict': 'ok'}
    assert prr.cut_status(ok, True) == 'ok' and prr.cut_status(ok, False) == 'refused' and prr.cut_status(None, False) == 'missing'
    assert prr.cut_status({**ok, 'verdict': 'photo_too_small'}, True) == 'soft' and prr.cut_status({**ok, 'mask_verdict': 'suspect'}, True) == 'soft'
    assert prr.cut_status({**ok, 'verdict': 'collage'}, True) == 'refused' and prr.cut_status({**ok, 'mask_verdict': 'bad'}, True) == 'refused' and prr.cut_status({**ok, 'status': 'fail'}, True) == 'refused'
    W = prr.load_words(REPO)
    assert prr.say(W, prr.cut_reason({**ok, 'verdict': 'collage', 'mask_verdict': 'bad'})) == 'на фото коллаж, а не один товар; вырезка плохая' and prr.cut_reason(ok) == ''


def test_cutout_page(tmp_path):
    from PIL import Image
    (tmp_path / 'photos').mkdir()
    (tmp_path / 'cut').mkdir()
    chain = {}
    for sku, verdict in (('a_1', 'ok'), ('b_2', 'photo_too_small'), ('c_3', 'collage')):
        sha = 'sha' + sku
        Image.new('RGB', (30, 20), (9, 9, 9)).save(tmp_path / 'photos' / f'{sha}.img', 'JPEG')
        Image.new('RGBA', (30, 20), (200, 0, 0, 255)).save(tmp_path / 'cut' / f'{sha}.png')
        chain[sku] = {'sku': sku.replace('_', ':'), 'sha': sha, 'status': 'ok', 'verdict': verdict, 'mask_verdict': 'ok'}
    items = [{'id': k, 'name': f'Товар {k}'} for k in ('a_1', 'b_2', 'c_3', 'd_4')]                                  # d_4 нет в журнале
    W = prr.load_words(REPO)
    s, errs = prr.cutout_page(items, chain, str(tmp_path / 'photos'), str(tmp_path / 'cut'), str(tmp_path / 'o'), W, 'T')
    assert errs == [] and (s['n'], s['ok'], s['soft'], s['refused'], s['missing'], s['made'], s['cards']) == (4, 1, 1, 1, 1, 2, 4)
    page = (tmp_path / 'o' / 'index.html').read_text(encoding='utf-8')
    assert 'готовность этапа 90 %' in page and 'вошло 4' in page and 'на фото коллаж, а не один товар' in page and 'нет в журнале вырезки' in page and '<script' not in page
    assert page.count('<img ') == 6 and 'слева исходное фото' in page


def test_read_chain(tmp_path):
    p = tmp_path / 'c.jsonl'
    p.write_text('{"sku":"112923:5","sha":"x","status":"fail"}\nмусор\n{"sku":"112923:5","sha":"y","status":"ok"}\n', encoding='utf-8')
    assert read_chain_ok(prr.read_chain(str(p)))


def read_chain_ok(d):
    return list(d) == ['112923_5'] and d['112923_5']['sha'] == 'y'                                                   # повтор — последняя строка


# ---- цепочка этапов (директор 22.11): вошло(N+1) = вошло(N) − встало(N); нет данных этапа — отдельно; 08 при готовой модели — «с замечаниями» ----

ST9 = ['01-trellis', '02-prep', '03-parts', '04-camera', '05-delight', '06-visible', '07-fill', '08-material', '09-check']


def r9(s: str, reasons=None):
    sym = {'o': 'ok', 's': 'soft', 'R': 'refused', '-': 'missing'}
    return [{'stage': st, 'status': sym[ch], 'reason': (reasons or {}).get(st, 'причина ' + st if ch == 'R' else '')} for st, ch in zip(ST9, s)]


# строки как в настоящем прогоне t180-1122 (пример: раннер гнал дальше отказа 03, у одного товара нет check.json этапа 3 при данных дальше)
PER9 = {
    'p1': r9('ooooosoos'), 'p2': r9('ooooooooo'), 'p3': r9('ooooosso-'),                                            # покрашены, у p3 нет этапа 9
    'p4': r9('ooooossRR'),                                                                                          # 08 «встал», но модель есть → с замечаниями
    'x2': r9('oR------R'),                                                                                          # встал на 02, 09 «отказ» — не его проверка
    'x3': r9('ooRooss-R'),                                                                                          # встал на 03, а данные дальше есть — не считаются
    'x4': r9('oo-R-----'),                                                                                          # 03 без данных, дальше шёл, встал на 04
    'x7': r9('ooooosR-R'),
}
PAINTED9 = {'p1', 'p2', 'p3', 'p4'}


def test_effective_rules():
    e = prr.effective(PER9['x3'], False)
    assert e['03-parts']['status'] == 'refused' and e['04-camera']['status'] == 'after' and e['09-check']['status'] == 'after'
    e = prr.effective(PER9['x4'], False)
    assert e['03-parts']['status'] == 'nodata' and e['04-camera']['status'] == 'refused' and e['05-delight']['status'] == 'after'
    e = prr.effective(PER9['p4'], True)
    assert e['08-material']['status'] == 'soft' and e['08-material']['note'] and e['09-check']['status'] == 'refused'   # модель есть: отказ 08 — «с замечаниями», итог 9 — отказ
    assert prr.effective(PER9['p3'], True)['09-check']['status'] == 'nodata'


def test_chain_sums_and_painted():
    stages, tb = prr.stage_table(PER9, PAINTED9)
    assert prr.verify_table(stages, tb, 8, 4) == []
    ent = [tb[s]['entered'] for s in stages]
    ref = [tb[s]['refused'] for s in stages]
    assert all(ent[i + 1] == ent[i] - ref[i] for i in range(len(stages) - 1))                                       # вошло(N+1) = вошло(N) − встало(N)
    assert ent[0] == 8 and tb['03-parts']['nodata'] == 1 and tb['08-material']['refused'] == 0 and tb['08-material']['soft'] >= 1
    assert tb['09-check']['entered'] == 4 and tb['09-check']['nodata'] == 1 and tb['09-check']['refused'] == 1        # на 09 вошли только дошедшие до материала


def test_chain_mismatch_is_error():
    stages, tb = prr.stage_table(PER9, PAINTED9)
    tb['04-camera']['entered'] += 1
    assert any('цепочка' in e for e in prr.verify_table(stages, tb, 8, 4))
    stages, tb = prr.stage_table(PER9, PAINTED9)
    assert any('покрашено' in e for e in prr.verify_table(stages, tb, 8, 5))                                        # вошло(08) − встало(08) ≠ покрашено


def test_stage_pages_chain(tmp_path):
    from PIL import Image
    run = tmp_path / 'run'
    photos = {}
    for k in PER9:
        for st in ST9:
            (run / k / st).mkdir(parents=True, exist_ok=True)
            Image.new('RGBA', (50, 20), (10, 10, 200, 255)).save(run / k / st / 'frame.png')
        Image.new('RGBA', (40, 30), (200, 10, 10, 255)).save(tmp_path / f'{k}.png')
        photos[k] = str(tmp_path / f'{k}.png')
    runof = {k: str(run) for k in PER9}
    names = {k: f'Товар {k}' for k in PER9}
    W = prr.load_words(REPO)
    out = tmp_path / 'o'
    sums, errs = prr.stage_pages(PER9, PAINTED9, runof, str(out), W, 'T', names, photos)
    assert errs == [] and set(sums) == set(ST9)
    p4 = (out / '04-camera' / 'index.html').read_text(encoding='utf-8')
    assert 'вошло 6' in p4 and 'встало 1' in p4 and 'камера как на фото' in p4 and 'встал раньше: деление на части (03-parts)' in p4 and '<script' not in p4
    p3 = (out / '03-parts' / 'index.html').read_text(encoding='utf-8')
    assert 'нет данных этапа 1' in p3 and 'check.json этапа не записан' in p3                                         # пропущенный этап — отдельной строкой, не молча
    p8 = (out / '08-material' / 'index.html').read_text(encoding='utf-8')
    assert 'итоговая модель есть, а проверка этапа не прошла' in p8 and 'встало 0' in p8
    assert 'вошло 4' in (out / '09-check' / 'index.html').read_text(encoding='utf-8')
    assert (out / 'stages.json').exists() and (out / '04-camera' / 'img' / 'p1_2-04.jpg').exists()


def test_stopped_frames(tmp_path):
    from PIL import Image
    run = tmp_path / 'run'
    for k in ('c', 'd'):
        for st in ST:
            (run / k / st).mkdir(parents=True, exist_ok=True)
            if not (k == 'c' and st in ('08-material', '09-check')):
                Image.new('RGBA', (50, 20), (10, 10, 200, 255)).save(run / k / st / 'frame.png')
        Image.new('RGBA', (40, 30), (200, 10, 10, 255)).save(tmp_path / f'{k}.png')
    runof = {k: str(run) for k in ('c', 'd')}
    photos = {k: str(tmp_path / f'{k}.png') for k in ('c', 'd')}
    sf = prr.stopped_frames(runof, PER, [('c', '04-camera'), ('d', '08-material')], photos, str(tmp_path / 'sf'))
    assert sf['c']['frame_stage'] == '04-camera' and sf['d']['frame_stage'] == '08-material' and (tmp_path / 'sf' / sf['c']['frame']).exists()
    (run / 'd' / '08-material' / 'frame.png').unlink()
    sf = prr.stopped_frames(runof, PER, [('d', '08-material')], photos, str(tmp_path / 'sf2'))
    assert sf['d']['frame_stage'] == '04-camera'                                                                    # нет кадра этапа остановки — берём последний, что есть


def test_photo_from_inputs_next_to_form(tmp_path):
    from PIL import Image
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'hd-forms').mkdir()
    Image.new('RGBA', (20, 20), (1, 2, 3, 255)).save(tmp_path / 'inputs' / 'k_1.hd.rgba.png')
    run = tmp_path / 'run' / 'k_1'
    run.mkdir(parents=True)
    (run / 'run_all.json').write_text(json.dumps({'stages': [{'steps': [{'cmd': ['x', '--glb', str(tmp_path / 'hd-forms' / 'k_1-hd.glb')]}]}]}, indent=1), encoding='utf-8')
    got = prr.photo_paths({'k_1': []}, {'k_1': str(tmp_path / 'run')})
    assert got['k_1'] == str(tmp_path / 'inputs' / 'k_1.hd.rgba.png')


def test_partial_chain_and_pages(tmp_path):
    from PIL import Image
    codes = ['04-camera', '06-visible']
    sym = {'o': 'ok', 's': 'soft', 'R': 'refused', '-': 'missing'}
    per = {'a': 'oo', 'b': 'sR', 'c': 'R-', 'd': 'o-'}                      # c встал на 04; d прошёл 04, 06 не запускали
    per = {k: [{'stage': st, 'status': sym[ch], 'reason': 'причина ' + st if ch == 'R' else ''} for st, ch in zip(codes, v)] for k, v in per.items()}
    e = prr.effective(per['d'], False, True)
    assert e['06-visible']['status'] == 'nodata' and prr.effective(per['c'], False, True)['06-visible']['status'] == 'after'
    stages, tb = prr.stage_table(per, set(), True)
    assert prr.verify_table(stages, tb, 4, None) == []
    assert [(tb[s]['entered'], tb[s]['refused'], tb[s]['nodata']) for s in stages] == [(4, 1, 0), (3, 1, 1)]
    run = tmp_path / 'run'
    photos, runof = {}, {}
    for k in per:
        for st in codes:
            (run / k / st).mkdir(parents=True)
            Image.new('RGBA', (50, 20), (10, 10, 200, 255)).save(run / k / st / 'frame.png')
        Image.new('RGBA', (40, 30), (200, 10, 10, 255)).save(tmp_path / f'{k}.png')
        photos[k], runof[k] = str(tmp_path / f'{k}.png'), str(run)
    W = prr.load_words(REPO)
    sums, errs = prr.stage_pages(per, set(), runof, str(tmp_path / 'o'), W, 'T', {k: k for k in per}, photos, partial=True)
    assert errs == [] and 'нет данных этапа 1' in (tmp_path / 'o' / '06-visible' / 'index.html').read_text(encoding='utf-8')


def test_frame_tiles(tmp_path):
    from PIL import Image
    Image.new('RGB', (400, 100), (9, 9, 9)).save(tmp_path / 'strip.png')
    assert len(prr._tiles(str(tmp_path / 'strip.png'), str(tmp_path / 't'), 4)) == 4 and prr._tiles(str(tmp_path / 'strip.png'), str(tmp_path / 'u'), 2) == []   # 200×100 — не квадрат ±20 %: не режем
    W = prr.load_words(REPO)
    assert prr.frame_tiles(W, '06-visible') == 4 and prr.frame_tiles(W, '07-fill') == 2 and prr.frame_tiles(W, '04-camera') == 1
    card = {'sku': 'k', 'name': 'k', 'foto': 'img/a.jpg', 'photo_ar': 1.333, 'frame': 'img/t_1.jpg', 'tiles': ['img/t_%d.jpg' % i for i in range(1, 5)]}
    page = prr._card(card, 'ok', 'ок', W, '', 'фото', 'ракурсы')
    assert page.count("<div class='tiles' style='--ar:1.333'>") == 1 and page.count('alt=\'ракурс') == 4


def test_tiles_crop_common_box(tmp_path):
    from PIL import Image
    im = Image.new('RGB', (400, 100), (255, 255, 255))
    for k in range(4):
        im.paste((10, 10, 10), (k * 100 + 40, 30, k * 100 + 60, 70))                                                  # товар 20×40 в середине каждого ракурса
    im.save(tmp_path / 's.png')
    got = prr._tiles(str(tmp_path / 's.png'), str(tmp_path / 't'), 4)
    sizes = {Image.open(g).size for g in got}
    assert len(got) == 4 and len(sizes) == 1 and list(sizes)[0][1] < 100                                              # одинаковая рамка у всех, поля обрезаны


# ---- метка свежести данных (директор 22.11): «данные на ЧЧ:ММ (Лондон), прогон закончен / ещё идёт» ----

def _old(path, age_s):
    import os, time
    t = time.time() - age_s
    for dp, dn, fn in os.walk(path):
        for n in dn + fn:
            os.utime(os.path.join(dp, n), (t, t))
    os.utime(path, (t, t))


def _mkrun(tmp_path, progress=None):
    run = tmp_path / 'run'
    (run / 'k_1' / '04-camera').mkdir(parents=True)
    (run / 'k_1' / '04-camera' / 'check.json').write_text('{}', encoding='utf-8')
    if progress:
        (run / 'progress.log').write_text(progress, encoding='utf-8')
    return run


def test_state_finished(tmp_path):
    run = _mkrun(tmp_path, '2026-11-21 12:00:00 старт k_1 дерево x\n2026-11-21 12:46:30 конец k_1 дерево x rc=0 10 с\n2026-11-21 12:46:30 ВСЁ, обработано 1\n')
    _old(run, 3 * 3600)
    st = prr.run_state([str(run)], state_dir=str(tmp_path / 'нет-такой'))
    assert st['running'] is False and 'прогон закончен' in st['text'] and 'Лондон' in st['details'] and 'Лондон' not in st['text'] and st['jobs'] == []


def test_state_running_by_heavy_slot_job(tmp_path):
    import os
    run = _mkrun(tmp_path)
    _old(run, 5 * 3600)
    hs = tmp_path / 'hs'
    (hs / 'wait').mkdir(parents=True)
    (hs / 'wait' / '1-1').write_text(f'label=paint-03-2-1\npid={os.getpid()}\ncmd=python x.py {run}/k_1/work/m.json\n', encoding='utf-8')       # живой процесс, команда называет прогон
    (hs / 'wait' / '2-2').write_text(f'label=чужой\npid={os.getpid()}\ncmd=python x.py {tmp_path}/другой-прогон/k\n', encoding='utf-8')
    (hs / 'wait' / '4-4').write_text(f'label=t183-wardrobe\\npid={os.getpid()}\\ncmd=python facade.py --glb {run}/k_1/m.glb\\n', encoding='utf-8')                       # живая, но не задание прогона (метка не paint-) — не считается
    (hs / 'wait' / '3-3').write_text(f'label=умер\npid=999999999\ncmd=python x.py {run}\n', encoding='utf-8')                                   # процесса нет — не считается
    st = prr.run_state([str(run)], state_dir=str(hs))
    assert st['running'] is True and st['jobs'] == ['paint-03-2-1'] and 'ещё идёт' in st['text'] and 'heavy-slot' in st['details'] and 'heavy-slot' not in st['text']


def test_state_running_by_progress_log_and_fresh_folder(tmp_path):
    import time
    run = _mkrun(tmp_path, '2026-11-21 12:46:30 ВСЁ, обработано 1\n' + time.strftime('%Y-%m-%d %H:%M:%S') + ' старт k_2 дерево x\n')                  # старый «ВСЁ» выше, последнее событие — старт
    _old(run, 5 * 3600)
    st = prr.run_state([str(run)], state_dir=str(tmp_path / 'нет'))
    assert st['running'] is True and 'пакет run не закончен' in st['details'] and 'пакет' not in st['text'] and st['progress'][0]['unfinished'] is True
    run2 = _mkrun(tmp_path / 'b')                                                                                                                  # журнала и заданий нет, папка свежая (< 10 мин)
    assert prr.run_state([str(run2)], state_dir=str(tmp_path / 'нет'))['running'] is True
    old = _mkrun(tmp_path / 'c', '2026-11-20 10:00:00 старт k_1 дерево x\n')                                                                       # пакет «не закончил», но молчит давно и заданий нет → не идёт
    _old(old, 30 * 3600)
    st = prr.run_state([str(old)], state_dir=str(tmp_path / 'нет'))
    assert st['running'] is False and 'молчит' in st['details']


def test_state_on_pages_and_summary(tmp_path):
    W = prr.load_words(REPO)
    st = {'at': '12:34', 'tz': 'Europe/London', 'running': True, 'jobs': [], 'progress': [], 'last_change_min_ago': 1, 'text': 'данные на 12:34 · прогон ещё идёт — числа могут измениться', 'details': 'время — по Лондону: папка менялась 1 мин назад'}
    h = prr.state_html(st)
    assert 'данные на 12:34 · прогон ещё идёт' in h and '<summary>подробно</summary>время — по Лондону' in h and prr.state_html(None) == ''
    stages, tb = prr.stage_table(PER9, PAINTED9)
    s = {'label': 'T', 'n': 8, 'stopped': 4, 'stopped_by_stage': [], 'painted': 4, 'painted_final': {'ok': 1, 'soft': 3, 'refused': 0, 'missing': 0}, 'painted_strict': 0, 'frames': 4, 'cards': 8, 'errors': [], 'data_state': st}
    assert 'данные на 12:34 · прогон ещё идёт' in prr.render_md(s, W)


def test_cutout_v2_log_format(tmp_path):
    """Журнал make_cut_v2.py (T-178/2): `refused` вместо `status`, файлы по товару (`photos/<товар>.img`, `cut/<товар>.png`), без sha."""
    from PIL import Image
    (tmp_path / 'photos').mkdir()
    (tmp_path / 'cut').mkdir()
    rows = [{'sku': 'a_1', 'hybrid_error': None, 'mask_verdict': 'ok'},
            {'sku': 'b_2', 'hybrid_error': None, 'mask_verdict': 'ok', 'refused': 'сторож размера: мелкая вырезка'},
            {'sku': 'c_3', 'refused': 'вырезка упала: RuntimeError: нет адреса фото'}]
    for r in rows[:2]:
        Image.new('RGB', (30, 20), (9, 9, 9)).save(tmp_path / 'photos' / f"{r['sku']}.img", 'JPEG')
        Image.new('RGBA', (30, 20), (200, 0, 0, 255)).save(tmp_path / 'cut' / f"{r['sku']}.png")
    p = tmp_path / 'cut.jsonl'
    p.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    chain = prr.read_chain(str(p))
    items = [{'id': k, 'name': f'Товар {k}'} for k in ('a_1', 'b_2', 'c_3')]
    s, errs = prr.cutout_page(items, chain, str(tmp_path / 'photos'), str(tmp_path / 'cut'), str(tmp_path / 'o'), prr.load_words(REPO), 'T')
    assert errs == [] and (s['n'], s['ok'], s['refused'], s['missing'], s['made'], s['cards']) == (3, 1, 2, 0, 1, 3)
    page = (tmp_path / 'o' / 'index.html').read_text(encoding='utf-8')
    assert 'сторож размера: мелкая вырезка' in page and 'нет адреса фото' in page
