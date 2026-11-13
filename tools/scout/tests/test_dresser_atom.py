"""T-20261112-122 (план `dresser-optional-atom-01`): комод + лампа — необязательный атом малой гостиной, выбор набора — по ядру.

  1) ключ выбора (`bank_invariants.selection_key`) не награждает за число предметов: лишний комод нейтрален, набор с полным
     ядром (диван, столик, носитель ТВ) обгоняет «богатый» набор без столика;
  2) туры (`trial_demo._pick_styles`) и /demo (`flat215_demo.pick_banks`) на одном банке берут один и тот же набор стиля;
  3) атом: лампа на комоде не встала — комод снимается (`bank_invariants.dresser_atom_drop`), встала — остаётся.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_dresser_atom.py -q"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..')))
import bank_invariants as BI  # noqa: E402
import flat215_demo as FD  # noqa: E402
import trial_demo as TD  # noqa: E402


def _it(role: str, n: int) -> dict:
    return {'mid': 1, 'eid': f'{role}-{n}', 'w': 100, 'd': 50, 'h': 50, 'name': role}


def _set(style: str, roles: list, n: int, band: str = '14-16') -> dict:
    return {'style': style, 'band': band, 'm2': 15, 'set_id': f'{style}-{n}', 'items': {r: _it(r, n) for r in roles}}


CORE = ['диван', 'столик', 'тв-тумба']


def test_extra_dresser_is_neutral():
    """Тот же набор с комодом и без — ключ одинаковый: предмет «сверх ядра» не делает набор лучше или хуже."""
    a, b = _set('сканди', CORE + ['ковёр'], 1), _set('сканди', CORE + ['ковёр', 'комод'], 2)
    assert BI.selection_key(a) == BI.selection_key(b)


def test_full_core_beats_richer_set_without_table():
    """Набор без столика, но с комодом, пуфом и стеллажом — хуже набора с полным ядром (прежде выигрывал по числу предметов,
    и гостиная выходила пустой: столик выпадал из геометрии)."""
    full = _set('современный', CORE, 1)
    rich = _set('современный', ['диван', 'тв-тумба', 'комод', 'пуф', 'стеллаж', 'кресло'], 2)
    assert BI.selection_key(full) < BI.selection_key(rich)
    assert BI.core_missing(rich) == ['столик']
    # модель ядра важнее модели прочего: ядро без модели проигрывает комоду без модели
    assert BI.selection_key(full, no_mesh_core=0, no_mesh=1) < BI.selection_key(full, no_mesh_core=1, no_mesh=1)


def _bank() -> list:
    return [_set('сканди', ['диван', 'тв-тумба', 'комод', 'пуф', 'стеллаж'], 1),     # без столика, «богаче»
            _set('сканди', CORE + ['ковёр'], 2),                                   # полное ядро
            _set('сканди', CORE + ['ковёр', 'комод'], 3),                          # полное ядро + комод (номер дальше)
            _set('лофт', CORE + ['комод', 'торшер'], 4),
            _set('лофт', CORE, 5),
            _set('минимализм', ['диван', 'столик', 'стенка', 'комод'], 6),
            _set('минимализм', ['диван', 'тв-тумба', 'комод', 'пуф'], 7)]


def test_tours_and_demo_pick_same_set(monkeypatch):
    """Один банк, все модели есть — туры и /demo выбирают по стилю один и тот же набор; комод выбор не решает."""
    bank = _bank()
    monkeypatch.setattr(TD, 'item_has_mesh', lambda it: True)
    monkeypatch.setattr(FD, '_mesh_index', lambda: {f"{it['mid']}_{it['eid']}" for s in bank for it in s['items'].values()})
    monkeypatch.setattr(FD, '_msid', lambda sid: sid)
    tours = TD._pick_styles(bank, '14-16')
    demo = FD.pick_banks(bank, '14-16')
    assert tours == demo == [2, 6, 4]           # сканди — полное ядро (не «богатый» 1), минимализм — со столиком, лофт — по номеру
    rank = TD._style_ranking(bank, '14-16')
    assert rank['сканди'] == [2, 3, 1]          # следующий набор стиля для повтора (`RETRY_SETS`) — тоже по ядру


def test_dresser_atom_drop():
    """Атом «комод + лампа»: лампа не встала — снимаем комод (и второй комод тоже), встала — ничего не снимаем."""
    roles = ['диван', 'столик', 'комод', 'комод 2', 'тв-тумба']
    assert BI.dresser_atom_drop(roles, lamp_placed=False) == ['комод', 'комод 2']
    assert BI.dresser_atom_drop(roles, lamp_placed=True) == []
    assert BI.dresser_atom_drop(['диван', 'столик'], lamp_placed=False) == []


def test_core_lost_by_fact():
    """T-20261113-12 (владелец TG 1406: «комод уступает ТВ и столику»): ядро — по факту, набор против вставших предметов.
    Роль, которой нет в наборе, потерей не считается; носитель ТВ — тумба или стенка; номера ролей («комод 2») не мешают."""
    full = CORE + ['комод', 'ковёр']
    assert BI.core_lost(full, ['диван', 'столик', 'тв-тумба']) == []
    assert BI.core_lost(full, ['диван', 'тв-тумба', 'комод']) == ['столик']
    assert BI.core_lost(full, ['диван', 'столик', 'комод']) == ['носитель ТВ']
    assert BI.core_lost(['диван', 'столик', 'стенка'], ['диван', 'столик', 'стенка 2']) == []
    assert BI.core_lost(['диван', 'тв-тумба', 'комод'], ['диван', 'тв-тумба', 'комод']) == []   # столика в наборе нет — не потеря


def test_dresser_yields_to_core():
    """Комод с лампой стоит только при полном ядре: столик или носитель ТВ не встали — комод снимается (и его лампа — `place`)."""
    full = CORE + ['комод', 'ковёр']
    assert BI.dresser_yield_drop(full, ['диван', 'тв-тумба', 'комод', 'ковёр']) == ['комод']
    assert BI.dresser_yield_drop(full, ['диван', 'столик', 'комод 2']) == ['комод 2']
    assert BI.dresser_yield_drop(full, ['диван', 'столик', 'тв-тумба', 'комод']) == []
    assert BI.dresser_yield_drop(full, ['диван', 'тв-тумба']) == []                     # комода нет — снимать нечего


def test_tours_use_core_by_fact():
    """Туры: `place` снимает комод при неполном ядре (по набору стиля ДО среза под геометрию), `retry_next.lost` и `rescue`
    считают ядро по вставшим предметам; `rescue` не принимает «один диван», пока есть подстановка с полным ядром."""
    import inspect
    src = inspect.getsource(TD.build)
    assert 'BI.dresser_yield_drop(list(((chosen_sets.get(n) or st)' in src
    assert "{'role': r, 'why': 'core_first'} for r in yld" in src
    lost = src[src.index('def lost(v):'):src.index('_, draft, _ = assemble')]
    assert 'BI.core_lost(' in lost and "v.get('absent_roles')" not in lost
    res = src[src.index('def rescue('):src.index('return got')]
    assert 'BI.core_lost(' in res and 'spare' in res
    assert res.index('if not lost:') < res.index('spare = (lost, cur, cn, cst)')
