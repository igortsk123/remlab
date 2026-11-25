"""Тесты tools/ops/inputs_check.py (T-20261125-75/2): входы набора — копии с MANIFEST, проверка «пути существуют, sha совпадает». Только временные папки.

Запуск: `python -m pytest tools/ops/tests/test_inputs_check.py -q -p no:cacheprovider`."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inputs_check as ic  # noqa: E402

SKUS = ['112923_111', '114667_222', '99272_333']


@pytest.fixture
def world(tmp_path, monkeypatch):
    logs = tmp_path / 'logs'
    runs = {}
    for i, sku in enumerate(SKUS):
        (logs / 'forms-out').mkdir(parents=True, exist_ok=True)
        (logs / 'forms-in').mkdir(parents=True, exist_ok=True)
        (logs / 'cards').mkdir(parents=True, exist_ok=True)
        (logs / 'pose' / sku).mkdir(parents=True, exist_ok=True)
        glb, photo, card = logs / 'forms-out' / f'{sku}-hd.glb', logs / 'forms-in' / f'{sku}.hd.rgba.png', logs / 'cards' / f'{sku}.card.json'
        glb.write_bytes(b'GLB' + bytes([i]) * 50)
        photo.write_bytes(b'PNG' + bytes([i]) * 20)
        card.write_text(json.dumps({'sku': sku}))
        (logs / 'run').mkdir(exist_ok=True)
        rp = logs / 'run' / f'{sku}.png'
        rp.write_bytes(b'copy')
        runs[sku] = {'glb': str(glb), 'photo': str(rp), 'pose_run': str(logs / 'pose' / sku), 'body_only': False,
                     'args': ['--photo', '@in/photo.png'], 'extra_in': {'card.json': str(card), 'photo.png': str(photo)}}
    (logs / 'circle').mkdir()
    (logs / 'circle' / 'inputs-q0.json').write_text(json.dumps(runs))
    other = logs / 'old-cut.png'
    other.write_bytes(b'OLDCUT')
    rules = {'root': str(tmp_path / 'inputs'), 'sets': {'s3': {
        'manifest': 's3/MANIFEST.tsv', 'expect': 3, 'lists': [str(logs / 'circle' / 'inputs-q*.json')],
        'also': [{'sku': SKUS[0], 'kind': 'other', 'dest': f'other/{SKUS[0]}.old.png', 'path': str(other), 'note': 'другая версия: старая вырезка'}]}}}
    rp = tmp_path / 'rules.json'
    rp.write_text(json.dumps(rules))
    monkeypatch.setenv('INPUTS_CHECK_RULES', str(rp))
    return tmp_path, logs, runs, tmp_path / 'inputs' / 's3'


def build_ok(capsys):
    assert ic.main(['--build', 's3']) == 0
    capsys.readouterr()


def test_build_copies_everything_and_writes_manifest_then_check_is_clean(world, capsys):
    tmp, logs, runs, sdir = world
    assert ic.main(['--build', 's3']) == 0
    out = capsys.readouterr().out
    assert 'MANIFEST записан' in out and '(10 строк)' in out                 # 3 товара × (photo+card+glb) + 1 другая версия
    for sku in SKUS:
        assert (sdir / 'photo' / f'{sku}.hd.rgba.png').is_file() and not (sdir / 'photo' / f'{sku}.hd.rgba.png').is_symlink()
        assert (sdir / 'card' / f'{sku}.card.json').is_file() and (sdir / 'glb' / f'{sku}-hd.glb').is_file()
    assert (sdir / 'other' / f'{SKUS[0]}.old.png').read_bytes() == b'OLDCUT'
    rows, bad = ic.read_manifest(str(sdir / 'MANIFEST.tsv'))
    assert not bad and len(rows) == 10 and any('другая версия' in r['note'] for r in rows)
    assert ic.main([]) == 0
    assert 'чисто' in capsys.readouterr().out


def test_build_never_overwrites_and_keeps_existing_manifest(world, capsys):
    tmp, logs, runs, sdir = world
    build_ok(capsys)
    man = (sdir / 'MANIFEST.tsv').read_bytes()
    assert ic.main(['--build', 's3']) == 0                                   # повтор: всё есть, MANIFEST не переписан
    assert 'MANIFEST уже есть' in capsys.readouterr().out and (sdir / 'MANIFEST.tsv').read_bytes() == man
    (sdir / 'photo' / f'{SKUS[1]}.hd.rgba.png').write_bytes(b'EDITED')       # на месте другой файл — отказ, не затирает
    assert ic.main(['--build', 's3']) == 1
    assert 'не перезаписываю' in capsys.readouterr().out and (sdir / 'photo' / f'{SKUS[1]}.hd.rgba.png').read_bytes() == b'EDITED'


def test_build_reports_missing_source_and_writes_no_manifest(world, capsys):
    tmp, logs, runs, sdir = world
    os.remove(runs[SKUS[2]]['extra_in']['photo.png'])
    assert ic.main(['--build', 's3']) == 1
    out = capsys.readouterr().out
    assert 'источника нет' in out and not (sdir / 'MANIFEST.tsv').exists()


def test_check_catches_changed_copy_missing_copy_and_symlink(world, capsys):
    tmp, logs, runs, sdir = world
    build_ok(capsys)
    (sdir / 'glb' / f'{SKUS[0]}-hd.glb').write_bytes(b'broken')
    os.remove(sdir / 'card' / f'{SKUS[1]}.card.json')
    p = sdir / 'photo' / f'{SKUS[2]}.hd.rgba.png'
    data = p.read_bytes()
    os.remove(p)
    real = tmp / 'elsewhere.png'
    real.write_bytes(data)
    p.symlink_to(real)
    assert ic.main([]) == 1
    out = capsys.readouterr().out
    assert 'sha256 не совпал' in out and 'нет файла card/' in out and 'ссылка, а не копия' in out


def test_check_catches_vanished_input_path_in_circle_list(world, capsys):
    tmp, logs, runs, sdir = world
    build_ok(capsys)
    os.remove(runs[SKUS[0]]['extra_in']['photo.png'])                        # как 24.11: файл из папки логов исчез
    assert ic.main([]) == 1
    out = capsys.readouterr().out
    assert f'{SKUS[0]} [' in out and 'extra_in.photo.png: пути нет' in out
    dang = logs / 'dangling'
    dang.symlink_to(tmp / 'no-such-place')
    runs[SKUS[1]]['glb'] = str(dang)                                         # висячая ссылка — тоже «нет»
    (logs / 'circle' / 'inputs-q0.json').write_text(json.dumps(runs))
    assert ic.main([]) == 1
    assert 'висячая ссылка' in capsys.readouterr().out


def test_check_catches_circle_running_another_version_and_names_it(world, capsys):
    tmp, logs, runs, sdir = world
    build_ok(capsys)
    other = Path(runs[SKUS[0]]['extra_in']['photo.png'])
    other.write_bytes(b'OLDCUT')                                             # список указывает тот же путь, но там уже «другая версия» (sha как у other/)
    assert ic.main([]) == 1
    out = capsys.readouterr().out
    assert 'гонит ДРУГУЮ версию photo' in out and 'другая версия: старая вырезка' in out


def test_check_requires_expected_count_and_all_three_kinds(world, capsys):
    tmp, logs, runs, sdir = world
    build_ok(capsys)
    man = (sdir / 'MANIFEST.tsv').read_text(encoding='utf-8').split('\n')
    keep = [ln for ln in man if not (ln.startswith(SKUS[2] + '\t') and '\tcard\t' in ln)]
    (sdir / 'MANIFEST.tsv').write_text('\n'.join(keep), encoding='utf-8')
    assert ic.main([]) == 1
    assert f'{SKUS[2]}: нет в MANIFEST основных входов: card' in capsys.readouterr().out
    keep = [ln for ln in man if not ln.startswith(SKUS[1] + '\t')]
    (sdir / 'MANIFEST.tsv').write_text('\n'.join(keep), encoding='utf-8')
    assert ic.main([]) == 1
    out = capsys.readouterr().out
    assert 'в наборе 2 товаров вместо 3' in out and f'{SKUS[1]}: есть в списке прогонов, но нет в наборе' in out


def test_check_without_manifest_or_list_and_bad_rules(world, capsys, monkeypatch, tmp_path):
    tmp, logs, runs, sdir = world
    assert ic.main([]) == 1                                                  # копий и MANIFEST ещё нет
    assert 'нет MANIFEST' in capsys.readouterr().out
    build_ok(capsys)
    os.remove(logs / 'circle' / 'inputs-q0.json')
    assert ic.main([]) == 1
    assert 'список не найден' in capsys.readouterr().out
    assert ic.main(['--set', 'нет-такого']) == 2
    monkeypatch.setenv('INPUTS_CHECK_RULES', str(tmp_path / 'нет.json'))
    assert ic.main([]) == 2


def test_json_output_and_real_rules_file_parses():
    rules = json.load(open(ic.RULES_PATH, encoding='utf-8'))
    s = rules['sets']['set29']
    assert rules['root'] == '~/remlab-inputs' and s['expect'] == 29 and s['lists'] and s['manifest'] == 'set29/MANIFEST.tsv'
    assert any(a['kind'] == 'other' and 'другая версия' in a['note'] for a in s['also'])


def test_set_inputs_returns_main_paths_and_raises_when_unreadable(world, capsys):
    tmp, logs, runs, sdir = world
    with pytest.raises(ic.InputsError, match='MANIFEST'):
        ic.set_inputs('s3')                                                  # копий ещё нет
    build_ok(capsys)
    got = ic.set_inputs('s3')
    assert set(got) == set(SKUS) and set(got[SKUS[0]]) == {'photo', 'card', 'glb'}          # «другая версия» (other) в основные входы не попадает
    assert got[SKUS[0]]['photo'] == str(sdir / 'photo' / f'{SKUS[0]}.hd.rgba.png') and os.path.isfile(got[SKUS[0]]['glb'])
    os.remove(sdir / 'card' / f'{SKUS[1]}.card.json')
    with pytest.raises(ic.InputsError, match='нет файла входа'):
        ic.set_inputs('s3')
    with pytest.raises(ic.InputsError, match='не описан'):
        ic.set_inputs('нет-такого')


def test_set_photo_dirs_lists_existing_photo_dirs_only(world, capsys):
    tmp, logs, runs, sdir = world
    assert ic.set_photo_dirs() == []                                          # набор ещё не собран
    build_ok(capsys)
    assert ic.set_photo_dirs() == [str(sdir / 'photo')]
