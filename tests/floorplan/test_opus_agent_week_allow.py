"""T-20261127-176/week-allow: разовый допуск стража недели в tools/floorplan/opus_agent.py (владелец TG 3758, директор 27.11 22:12).
OPUS_AGENT_WEEK_ALLOW='<N>:<YYYY-MM-DD>[/<YYYY-MM-DD>]:<TG>' пускает не больше N листов СВЕРХ недельного стопа (WEEK_STOP=60 %) и только в названные даты UTC; OPUS_AGENT_WEEK_HARD — потолок, выше которого стоп всегда.
Без сети и подписки: вместо `claude` — поддельная программа; «сейчас» заморожено (27.11.2026 23:00 UTC). Каждая проверка с отрицательным контролем (сломал проверку даты/N/потолка/счёта по журналу → красный):
`OPUS_AGENT_DIR=<папка с испорченной копией opus_agent.py> python -m pytest tests/floorplan/test_opus_agent_week_allow.py` (скрипт порчи — в отчёте задачи)."""
import calendar
import json
import os
import stat
import sys
import threading
import time

import pytest

sys.path.insert(0, os.environ.get('OPUS_AGENT_DIR') or os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'floorplan'))
import opus_agent as AG  # noqa: E402

NOW = calendar.timegm((2026, 11, 27, 23, 0, 0))   # 2026-11-27 UTC
FAR = 4102444800                                   # сброс недели «далеко» (2100 г.)
FAKE = '''#!%s
import json, os, sys
a = sys.argv[1:]
if '--version' in a:
    print('2.1.332 (Claude Code)'); sys.exit(0)
with open(os.environ['FAKE_DIR'] + '/count', 'a') as f:
    f.write('x\\n')
sys.stdin.readline()
if os.environ.get('FAKE_MODE') == 'crash':
    sys.stderr.write('boom'); sys.exit(7)
print(json.dumps({'type': 'system', 'subtype': 'init', 'apiKeySource': 'none', 'model': 'claude-opus-5-5', 'tools': []}))
print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '{"version": 1}', 'stop_reason': 'end_turn', 'total_cost_usd': 0.1,
                  'usage': {'input_tokens': 2, 'cache_creation_input_tokens': 574, 'cache_read_input_tokens': 0, 'output_tokens': 5}}))
'''
PROMPT = 'PROMPT TEXT'
IMG = b'\xff\xd8fake'


@pytest.fixture
def wk(tmp_path, monkeypatch):
    fdir = tmp_path / 'fake'
    fdir.mkdir()
    prog = fdir / 'claude'
    prog.write_text(FAKE % sys.executable)
    prog.chmod(prog.stat().st_mode | stat.S_IEXEC)
    lim = fdir / 'limit'
    lim.write_text('#!/bin/sh\ncat %s/limit.txt\n' % fdir)
    lim.chmod(lim.stat().st_mode | stat.S_IEXEC)
    (fdir / 'limit.txt').write_text('0 0 65 %d\n' % FAR)         # неделя 65 % — выше WEEK_STOP
    out = tmp_path / 'out'
    (out / 'vetka-a').mkdir(parents=True)
    monkeypatch.setenv('FAKE_DIR', str(fdir))
    for k in ('FAKE_MODE', 'OPUS_AGENT_WEEK_ALLOW', 'OPUS_AGENT_WEEK_HARD'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(AG, 'CLAUDE', str(prog))
    monkeypatch.setattr(AG, 'LIMIT_CMD', str(lim))
    monkeypatch.setattr(AG, 'CWD', str(tmp_path / 'cwd-empty'))
    monkeypatch.setattr(AG, 'A', str(out / 'vetka-a'))
    monkeypatch.setattr(AG, 'OUT', str(out))
    monkeypatch.setitem(AG.STATE, 'fails', 0)
    monkeypatch.setitem(AG.STATE, 'version', '2.1.332')
    monkeypatch.setitem(AG.STATE, 'allow_pending', 0)
    (tmp_path / 'cwd-empty').mkdir()
    real = AG.gate_reserve
    monkeypatch.setattr(AG, 'gate_reserve', lambda nums, now=None: real(nums, NOW))

    class E:
        pass
    e = E()
    e.fdir, e.out, e.tmp, e.mp = fdir, out, tmp_path, monkeypatch
    e.count = lambda: len((fdir / 'count').read_text().split()) if (fdir / 'count').exists() else 0
    e.rows = lambda: [json.loads(x) for x in (out / 'vetka-a' / 'calls.jsonl').read_text().splitlines()]
    e.limit = lambda s: (fdir / 'limit.txt').write_text(s + '\n')
    def allow(s, hard='70'):                                       # допуск открывает что-то только при HARD выше WEEK_STOP — по умолчанию ставим 70
        monkeypatch.setenv('OPUS_AGENT_WEEK_ALLOW', s)
        if hard:
            monkeypatch.setenv('OPUS_AGENT_WEEK_HARD', hard)
    e.allow = allow
    e.stop = lambda: (out / 'STOP').read_text() if (out / 'STOP').exists() else ''
    e.sheet = lambda i: AG.one('kazan-%d__b' % i, 'opus', PROMPT, IMG)
    return e


def test_no_allow_stops(wk):
    assert wk.sheet(1) is False
    assert wk.count() == 0 and 'неделя 65 % ≥ 60 %' in wk.stop()
    assert 'допуск_ключ' not in wk.rows()[0]


def test_other_date_stops(wk):
    wk.allow('5:2026-11-26:TG3758')                              # вчера
    assert wk.sheet(1) is False
    assert wk.count() == 0 and 'не на сегодня' in wk.stop() and '2026-11-27' in wk.stop()
    wk.allow('5:2026-11-28:TG3758')                              # завтра
    assert wk.sheet(2) is False and wk.count() == 0              # (STOP-файл уже лежит — всё равно ни одного вызова)


def test_in_date_and_within_n_goes_and_records_reason(wk):
    wk.allow('2:2026-11-27:TG3758')
    assert wk.sheet(1) is True and wk.sheet(2) is True
    r = wk.rows()
    assert wk.count() == 2 and not wk.stop()
    assert r[0]['допуск'].startswith('допуск TG3758: лист 1 из 2 (осталось 1)') and r[0]['допуск_осталось'] == 1 and r[0]['допуск_лист'] == 1
    assert r[1]['допуск'].startswith('допуск TG3758: лист 2 из 2 (осталось 0)') and r[1]['допуск_осталось'] == 0 and r[1]['допуск_n'] == 2
    assert r[0]['допуск_ключ'] == r[1]['допуск_ключ'] == 'TG3758|2026-11-27'


def test_two_dates_both_allowed(wk):
    wk.allow('1:2026-11-26/2026-11-27:TG3758')
    assert wk.sheet(1) is True and wk.count() == 1


def test_n_plus_one_stops(wk):
    wk.allow('2:2026-11-27:TG3758')
    assert wk.sheet(1) and wk.sheet(2)
    assert wk.sheet(3) is False
    assert wk.count() == 2 and 'исчерпан: 2 из 2' in wk.stop()
    assert 'допуск_ключ' not in wk.rows()[2]                     # отказанный лист допуска не получил


def test_above_hard_stops_even_with_allow(wk):
    wk.allow('5:2026-11-27:TG3758')
    wk.mp.setenv('OPUS_AGENT_WEEK_HARD', '70')
    assert wk.sheet(1) is True                                   # 65 % < потолка 70 % — допуск работает
    wk.limit('0 0 71 %d' % FAR)
    assert wk.sheet(2) is False
    assert wk.count() == 1 and 'жёсткий потолок 70 %' in wk.stop()


def test_default_hard_equals_week_stop_so_allow_opens_nothing_without_hard(wk):
    """без OPUS_AGENT_WEEK_HARD потолок = WEEK_STOP: допуск сам по себе ничего не открывает (так задано заданием; пускать — только вместе с HARD выше 60)"""
    wk.allow('5:2026-11-27:TG3758', hard=None)
    assert wk.sheet(1) is False and wk.count() == 0 and 'неделя 65' in wk.stop()
    assert AG.week_hard() == AG.WEEK_STOP


@pytest.mark.parametrize('bad', ['мусор', '0:2026-11-27:TG1', 'x:2026-11-27:TG1', '5:2026-13-45:TG1', '5:2026-11-27:', '5:2026-11-27', '5:2026-11-27/:TG1', '5:27.11.2026:TG1'])
def test_broken_allow_stops_with_reason(wk, bad):
    wk.mp.setenv('OPUS_AGENT_WEEK_HARD', '80')
    wk.allow(bad)
    assert wk.sheet(1) is False
    assert wk.count() == 0 and 'битая OPUS_AGENT_WEEK_ALLOW' in wk.stop() and 'допуск_ключ' not in wk.rows()[0]
    with pytest.raises(AG.AgentStop, match='битая OPUS_AGENT_WEEK_ALLOW'):
        AG.week_allow()


def test_broken_allow_stops_even_below_week_stop(wk):
    wk.limit('0 0 39 %d' % FAR)
    wk.allow('мусор')
    assert wk.sheet(1) is False and wk.count() == 0 and 'битая' in wk.stop()      # опечатка в допуске не должна тихо уйти в обычный прогон


def test_broken_hard_stops_with_reason(wk):
    wk.mp.setenv('OPUS_AGENT_WEEK_HARD', 'много')
    assert wk.sheet(1) is False and wk.count() == 0 and 'битая OPUS_AGENT_WEEK_HARD' in wk.stop()


def test_preflight_refuses_broken_allow(wk):
    wk.allow('мусор')
    with pytest.raises(AG.AgentStop, match='битая OPUS_AGENT_WEEK_ALLOW'):
        AG.preflight(str(wk.out))
    assert wk.count() == 0                                        # дальше контрольный вызов не шёл


def test_restart_continues_count_from_journal(wk):
    wk.allow('3:2026-11-27:TG3758')
    assert wk.sheet(1) and wk.sheet(2)
    wk.mp.setitem(AG.STATE, 'allow_pending', 0)                   # «перезапуск пачки»: память пуста, журнал на месте
    assert wk.sheet(3) is True                                    # третий — последний
    assert wk.sheet(4) is False
    assert wk.count() == 3 and 'исчерпан: 3 из 3' in wk.stop()


def test_below_week_stop_goes_without_allow_and_is_not_counted(wk):
    wk.limit('0 0 39 %d' % FAR)
    wk.allow('1:2026-11-27:TG3758')
    assert wk.sheet(1) and wk.sheet(2)
    assert all('допуск_ключ' not in r for r in wk.rows())          # допуск тратится только на листы СВЕРХ стопа
    wk.limit('0 0 65 %d' % FAR)
    wk.mp.setenv('OPUS_AGENT_WEEK_HARD', '70')
    assert wk.sheet(3) is True and wk.rows()[2]['допуск_лист'] == 1


def test_counts_sheets_not_attempts(wk):
    wk.allow('2:2026-11-27:TG3758')
    wk.mp.setenv('OPUS_AGENT_WEEK_HARD', '70')
    wk.mp.setenv('FAKE_MODE', 'crash')
    assert wk.sheet(1) is False                                   # два захода программы, один лист
    assert wk.count() == 2
    wk.mp.delenv('FAKE_MODE')
    assert wk.sheet(2) is True
    r = wk.rows()
    assert [x['допуск_лист'] for x in r] == [1, 2]                # второй лист — лист №2 из 2, не №3
    assert wk.sheet(3) is False and 'исчерпан' in wk.stop()


def test_five_hour_pause_unchanged_and_does_not_spend_allow(wk):
    wk.allow('1:2026-11-27:TG3758')
    wk.mp.setenv('OPUS_AGENT_WEEK_HARD', '70')
    wk.limit('75 %d 65 %d' % (NOW + 3600, FAR))
    slept = []

    def fake_sleep(s):
        slept.append(s)
        wk.limit('0 0 65 %d' % FAR)                               # окно сбросилось
    wk.mp.setattr(AG, 'sleep', fake_sleep)
    assert wk.sheet(1) is True
    assert slept and slept[0] > 0 and '5 часов 75' in wk.rows()[0]['pauses'][0]
    assert wk.rows()[0]['допуск_лист'] == 1 and wk.rows()[0]['допуск_осталось'] == 0      # пауза лист допуска не потратила


def test_parallel_threads_never_exceed_n(wk):
    wk.allow('2:2026-11-27:TG3758')
    wk.mp.setenv('OPUS_AGENT_WEEK_HARD', '70')
    res = []
    th = [threading.Thread(target=lambda i=i: res.append(wk.sheet(i))) for i in range(8)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert wk.count() == 2 and res.count(True) == 2
    assert len([r for r in wk.rows() if r.get('допуск_ключ')]) == 2


def test_gate_pure_cases():
    allow = AG.week_allow('3:2026-11-27/2026-11-28:TG3758')
    assert allow == {'n': 3, 'dates': ['2026-11-27', '2026-11-28'], 'tg': 'TG3758', 'key': 'TG3758|2026-11-27/2026-11-28'}
    near = (0, 0, 65, FAR)
    assert AG.gate(near, NOW, None, 0, 60)[0] == 'stop'
    assert AG.gate(near, NOW, allow, 0, 60)[0] == 'stop'          # потолок = 60: допуск не действует
    v, why, _ = AG.gate(near, NOW, allow, 2, 70)
    assert v == 'ok' and why.startswith('допуск TG3758: лист 3 из 3 (осталось 0)')
    assert AG.gate(near, NOW, allow, 3, 70)[0] == 'stop'
    assert AG.gate((0, 0, 70, FAR), NOW, allow, 0, 70)[0] == 'stop'      # ровно на потолке — стоп
    assert AG.gate((0, 0, 59, FAR), NOW, allow, 0, 70) == ('ok', '', 0)   # ниже стопа допуск не нужен и не тратится
    assert AG.gate(near, NOW + 5 * 86400, allow, 0, 70)[0] == 'stop'     # дата вышла
    assert AG.gate((90, FAR, 65, FAR), NOW, allow, 0, 70)[0] == 'pause'  # пауза впереди допуска
