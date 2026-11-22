"""Тесты сводки и страницы прогона покраски `tools/ops/paint_run_report.py` (T-20261122-180/4): сумма сходится, расхождение → ошибка → ненулевой код.

Только на временных папках и подставных кадрах (картинки и правила конвейера не нужны): проверяем счёт и самопроверку, а не рендер.
Запуск: `python -m pytest tools/ops/tests/test_paint_run_report.py -q`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paint_run_report as prr  # noqa: E402

ST = ['01-trellis', '04-camera', '08-material', '09-check']


def rows(*statuses, reasons=None):
    return [{'stage': s, 'status': st, 'reason': (reasons or {}).get(s, '')} for s, st in zip(ST, statuses)]


PER = {
    'a': rows('ok', 'ok', 'ok', 'ok'),                                                                            # покрашен, строго
    'b': rows('ok', 'ok', 'ok', 'soft'),                                                                          # покрашен, мягко
    'c': rows('ok', 'refused', 'missing', 'refused', reasons={'04-camera': 'IoU 0.7 < 0.85'}),                    # остановился на 04
    'd': rows('ok', 'ok', 'refused', 'refused', reasons={'08-material': 'confident_share 0.7'}),                  # остановился на 08, модели нет
    'e': rows('ok', 'ok', 'ok', 'refused', reasons={'09-check': 'охват'}),                                        # покрашен, не готов
}
PAINTED = {'a', 'b', 'e'}


def test_summary_sums():
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3)
    assert s['n'] == 5 and s['stopped'] == 2 and s['painted'] == 3
    assert {x['stage']: x['count'] for x in s['stopped_by_stage']} == {'04-camera': 1, '08-material': 1}
    assert s['painted_final'] == {'ok': 1, 'soft': 1, 'refused': 1, 'missing': 0} and s['painted_strict'] == 1
    assert s['errors'] == []


def test_stop_prefers_refused_over_missing():
    assert prr.stop_of(PER['c']) == ('04-camera', 'IoU 0.7 < 0.85')
    assert prr.stop_of(rows('ok', 'ok', 'ok', 'missing'))[0] == '09-check'
    st, why = prr.stop_of(rows('ok', 'ok', 'ok', 'ok'))
    assert why and st == '09-check'                                                                                 # прошёл всё, а модели нет — это причина, а не пустота


def test_verify_catches_mismatch():
    assert any('папок товаров' in e for e in prr.summarise(PER, PAINTED, 't', n_dirs=6, frames=3)['errors'])
    assert any('кадров на странице' in e for e in prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=2)['errors'])
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3)
    s['stopped'] += 1
    assert prr.verify(s)                                                                                            # подкрутили число — ошибка
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3)
    s['stopped_by_stage'][0]['items'][0]['reason'] = ''
    assert any('причины' in e for e in prr.verify(s))


def test_md_and_page_have_the_numbers():
    s = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=3)
    md = prr.render_md(s)
    assert 'Вошло: 5' in md and 'Остановились, крашеной модели нет: 2' in md and 'Покрашено (есть итоговая модель этапа 8): 3' in md and 'Кадров на странице: 3' in md and 'ОШИБКА' not in md
    bad = prr.summarise(PER, PAINTED, 't', n_dirs=5, frames=2)
    assert 'ОШИБКА СВОДКИ' in prr.render_md(bad)
    cards = [{'sku': k, 'name': k, 'role': 'r', 'final': 'ok', 'strict': True, 'reason': '', 'foto': f'img/{k}_1.jpg', 'view3d': f'img/{k}_2.jpg'} for k in ('a', 'b', 'e')]
    page = prr.render_page(s, cards, 'T')
    assert page.count('<img ') == 6 and '<script' not in page and 'viewport' in page


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
    assert prr.report([str(run)], {'run': PER}, str(out), '.', frames_fn=ok) == 0
    s = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    assert (s['n'], s['stopped'], s['painted'], s['frames']) == (5, 2, 3, 3) and (out / 'index.html').exists() and (out / 'summary.md').exists()
    short = lambda repo, runof, skus, out: {'ok': {k: {'foto': 'x', 'view3d': 'y'} for k in skus[:-1]}, 'errors': {skus[-1]: 'boom'}}          # noqa: E731
    assert prr.report([str(run)], {'run': PER}, str(tmp_path / 'out2'), '.', frames_fn=short) == 1                                           # кадр не построился — ненулевой код
    assert 'ОШИБКА СВОДКИ' in capsys.readouterr().out


def test_report_dir_count_mismatch(tmp_path):
    run = tmp_path / 'run'
    _fake_run(run, list(PER) + ['extra'], PAINTED)                                                                  # на диске товар, которого нет в решениях
    ok = lambda repo, runof, skus, out: {'ok': {k: {'foto': 'x', 'view3d': 'y'} for k in skus}, 'errors': {}}       # noqa: E731
    assert prr.report([str(run)], {'run': PER}, str(tmp_path / 'o'), '.', frames_fn=ok) == 1


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
    assert prr.report([str(r1), str(r2)], {'r1': per1, 'r2': per2}, str(tmp_path / 'o'), '.', frames_fn=fake) == 0
    s = json.loads((tmp_path / 'o' / 'summary.json').read_text(encoding='utf-8'))
    assert s['n'] == 3 and seen['a'] == str(r1)                                                                     # повтор sku — из первого прогона; N без повторов
