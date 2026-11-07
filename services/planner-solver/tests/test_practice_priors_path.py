"""Где планировщик ищет приоры практики (T-20261107-07): env `PRACTICE_PRIORS_PATH` → `rules/` рядом с пакетом → `tools/scout/rules/`.
07.11: в образе запасного рендера путь вёл в несуществующий /tools/scout/rules/ — приоры молча были пустыми. Теперь «не нашёл» —
строка в stderr, а файл читается один раз на путь (раньше — на каждую возможность каждой гипотезы).
Раскладку образа как есть проверяет `tools/scout/tests/test_draft_image_rules.py`."""
import json
import os

import pytest

from planner import opportunities as O

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
REPO_PRIORS = os.path.join(ROOT, 'tools', 'scout', 'rules', 'practice_priors.json')


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv('PRACTICE_PRIORS_PATH', raising=False)
    O._PRIORS_CACHE.clear()
    yield
    O._PRIORS_CACHE.clear()


def test_order_and_repo_default():
    c = O.priors_candidates()
    assert c[0].endswith(os.path.join('planner-solver', 'rules', 'practice_priors.json')), c   # рядом с пакетом (/app/rules)
    assert c[1] == os.path.abspath(REPO_PRIORS), c                                              # источник истины в репо
    assert O.priors_path() == os.path.abspath(REPO_PRIORS)
    assert O.priors()['opportunities']['window']['outcomes'], 'в репо приоры окна не пусты'


def test_env_wins(monkeypatch, tmp_path):
    p = tmp_path / 'pp.json'
    p.write_text(json.dumps({'opportunities': {'window': {'outcomes': [{'id': 'x', 'roles': ['кресло']}]}}}), encoding='utf-8')
    monkeypatch.setenv('PRACTICE_PRIORS_PATH', str(p))
    assert O.priors_candidates() == [str(p)]
    assert O._rank_map('window') == {'x': 0}


def test_env_missing_is_loud_not_fallback(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('PRACTICE_PRIORS_PATH', str(tmp_path / 'нет.json'))
    assert O.priors() == {'opportunities': {}, 'item_presence_pct': {}}, 'явный путь мимо файла не подменяется репо-файлом'
    err = capsys.readouterr().err
    assert 'приоры практики не найдены' in err and 'нет.json' in err, err


def test_broken_json_is_loud(monkeypatch, tmp_path, capsys):
    p = tmp_path / 'bad.json'
    p.write_text('{не json', encoding='utf-8')
    monkeypatch.setenv('PRACTICE_PRIORS_PATH', str(p))
    assert O.priors()['opportunities'] == {}
    assert 'JSONDecodeError' in capsys.readouterr().err


def test_cache_one_read_one_warning(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('PRACTICE_PRIORS_PATH', str(tmp_path / 'нет.json'))
    for _ in range(5):
        O.priors()
    assert capsys.readouterr().err.count('не найдены') == 1, 'предупреждение — одно на путь, не на каждый вызов'
    monkeypatch.delenv('PRACTICE_PRIORS_PATH')
    a, b = O.priors(), O.priors()
    assert a is b, 'файл читается один раз (кэш на путь)'
