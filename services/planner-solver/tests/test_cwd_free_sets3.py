"""T-175/hvosty: test_cwd_free::test_solver_from_root без tools/scout/sets3.json — ВСЕГДА пропуск с причиной (красной ветки нет; решение директора/Fable 27.11, цикл 2).
Причина: prepush сам ставит CI=true и GITHUB_ACTIONS=true (prepush_check.py) — любая «красная по окружению» ветка краснела бы в каждом worktree без банка.
Тест не зависит от ~/venvs/scout (у test_cwd_free модуль целиком пропускается без него): проверяем решение и саму функцию-тест на подставном корне и окружении."""
import pytest

from tests import test_cwd_free as T


def _root(tmp_path, with_bank):
    d = tmp_path / 'tools' / 'scout'
    d.mkdir(parents=True, exist_ok=True)
    if with_bank:
        (d / 'sets3.json').write_text('{}')
    return str(tmp_path)


def test_no_bank_is_skip_with_reason(tmp_path):
    v, why = T.sets3_verdict(_root(tmp_path, False))
    assert v == 'пропуск' and 'нет sets3.json' in why and 'prepush' in why


def test_bank_present_runs(tmp_path):
    assert T.sets3_verdict(_root(tmp_path, True)) == ('есть', None)


@pytest.mark.parametrize('env', [
    {},
    {'CI': 'true'},
    {'GITHUB_ACTIONS': 'true'},                       # настоящий CI без банка — тоже пропуск (решение: красной ветки нет)
    {'CI': 'true', 'GITHUB_ACTIONS': 'true'},         # то, что ставит prepush_check.py
])
def test_solver_test_itself_skips_without_bank_in_any_env(tmp_path, monkeypatch, env):
    """Именно функция-тест: чистая копия без sets3.json под prepush-окружением (CI=true, GITHUB_ACTIONS=true) → пропуск, не красный.
    Отрицательный контроль: вернуть ветку «GITHUB_ACTIONS=true → pytest.fail» — случаи с GITHUB_ACTIONS станут красными."""
    monkeypatch.setattr(T, 'ROOT', _root(tmp_path, False))
    for k in ('CI', 'GITHUB_ACTIONS'):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(pytest.skip.Exception, match='нет sets3.json'):
        T.test_solver_from_root()
