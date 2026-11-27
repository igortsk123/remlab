"""T-175/hvosty (а): test_cwd_free::test_solver_from_root без sets3.json — пропуск с причиной, пока GITHUB_ACTIONS не равна true; при GITHUB_ACTIONS=true — красный с понятной причиной.
Тест не зависит от ~/venvs/scout (у test_cwd_free модуль целиком пропускается без него): проверяем решение и саму функцию-тест на подставном корне и окружении."""
import os

import pytest

from tests import test_cwd_free as T


def _root(tmp_path, with_bank):
    d = tmp_path / 'tools' / 'scout'
    d.mkdir(parents=True, exist_ok=True)
    if with_bank:
        (d / 'sets3.json').write_text('{}')
    return str(tmp_path)


def test_no_bank_not_ci_is_skip_with_reason(tmp_path):
    v, why = T.sets3_verdict(_root(tmp_path, False), {})
    assert v == 'пропуск' and 'нет sets3.json' in why and 'не CI' in why
    assert T.sets3_verdict(_root(tmp_path, False), {'GITHUB_ACTIONS': ''})[0] == 'пропуск'
    assert T.sets3_verdict(_root(tmp_path, False), {'GITHUB_ACTIONS': 'false'})[0] == 'пропуск'
    # одной CI=true мало (владелец условия: красный ТОЛЬКО при GITHUB_ACTIONS=true) — отрицательный контроль прежнего поведения
    assert T.sets3_verdict(_root(tmp_path, False), {'CI': 'true'})[0] == 'пропуск'


def test_no_bank_in_ci_is_red_with_reason(tmp_path):
    v, why = T.sets3_verdict(_root(tmp_path, False), {'GITHUB_ACTIONS': 'true'})
    assert v == 'красный' and 'GITHUB_ACTIONS=true' in why and 'sets3.json' in why and 'не пропускаем' in why


def test_bank_present_runs_everywhere(tmp_path):
    root = _root(tmp_path, True)
    assert T.sets3_verdict(root, {}) == ('есть', None)
    assert T.sets3_verdict(root, {'GITHUB_ACTIONS': 'true'}) == ('есть', None)


def test_solver_test_itself_skips_outside_ci(tmp_path, monkeypatch):
    monkeypatch.setattr(T, 'ROOT', _root(tmp_path, False))
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setenv('CI', 'true')   # CI без GITHUB_ACTIONS — по-прежнему пропуск
    with pytest.raises(pytest.skip.Exception, match='нет sets3.json'):
        T.test_solver_from_root()


def test_solver_test_itself_fails_in_ci(tmp_path, monkeypatch):
    """Именно ЭТОТ тест краснеет, если убрать условие GITHUB_ACTIONS в sets3_verdict (отрицательный контроль)."""
    monkeypatch.setattr(T, 'ROOT', _root(tmp_path, False))
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    with pytest.raises(pytest.fail.Exception, match='GITHUB_ACTIONS=true'):
        T.test_solver_from_root()
