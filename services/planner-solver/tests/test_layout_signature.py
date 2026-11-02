"""demo-31 (T-20261102-01): подпись гипотезы (стена дивана | стена ТВ | угол обеда) и фильтр beam по ней — только по env.

Без env фильтр не трогает гипотезы (прочие расстановки не меняются); с файлом подписи — оставляет совпавшие; совпавших нет —
прежний выбор и громкая строка `SIGFILTER MISS` (ворота демо сверяют подпись итога сами)."""
from __future__ import annotations

import json
from types import SimpleNamespace

from planner.models import Placement, Room
from planner.zones import _signature_filter, _signature_widen, layout_signature, signature_xy

ROOM = Room(width_cm=439, depth_cm=325)


def _hyp(name: str, sofa_y: float, tv_y: float, dining: tuple | None):
    ps = [Placement(role='диван', x=155, y=sofa_y), Placement(role='тв-тумба', x=155, y=tv_y)]
    if dining:
        ps += [Placement(role='стол обеденный', x=dining[0], y=dining[1]), Placement(role='стул 2', x=330, y=50)]
    return (name, 'g', [SimpleNamespace(placements=ps)], (0, 0, 0))


CANDS = [_hyp('greedy', 50, 300, None), _hyp('sofa_lamp#1', 280, 25, (394, 50)), _hyp('sofa_lamp#2', 50, 300, (394, 50))]


def test_signature_walls_and_corner():
    assert signature_xy(439, 325, {'диван': (155, 280), 'тв-тумба': (155, 25), 'стол обеденный': (394, 50)}) == \
        'диван:S|тв:N|обед:NE'
    assert signature_xy(439, 325, {'диван': (20, 160), 'стенка': (420, 160)}) == 'диван:W|тв:E|обед:-'
    assert layout_signature(ROOM, CANDS[1][2][0].placements) == 'диван:S|тв:N|обед:NE'


def test_filter_off_by_default(monkeypatch):
    monkeypatch.delenv('LAYOUT_SIGNATURE_FILE', raising=False)
    monkeypatch.delenv('LAYOUT_SIG_TRACE', raising=False)
    assert _signature_filter(ROOM, CANDS) is CANDS
    assert _signature_widen() == {}


def test_filter_keeps_reference(monkeypatch, tmp_path, capsys):
    f = tmp_path / 'sig.json'
    f.write_text(json.dumps({'signature': 'диван:S|тв:N|обед:NE', 'widen': {'blocks_per_step': 8}}), encoding='utf-8')
    monkeypatch.setenv('LAYOUT_SIGNATURE_FILE', str(f))
    assert [c[0] for c in _signature_filter(ROOM, CANDS)] == ['sofa_lamp#1']
    assert 'SIGFILTER ok' in capsys.readouterr().out
    assert _signature_widen() == {'blocks_per_step': 8}


def test_filter_miss_keeps_choice(monkeypatch, tmp_path, capsys):
    f = tmp_path / 'sig.json'
    f.write_text(json.dumps({'signature': 'диван:W|тв:E|обед:-'}), encoding='utf-8')
    monkeypatch.setenv('LAYOUT_SIGNATURE_FILE', str(f))
    assert _signature_filter(ROOM, CANDS) == CANDS
    assert 'SIGFILTER MISS' in capsys.readouterr().out
