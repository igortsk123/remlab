"""Прогноз «часов до стопа» с учётом почасового переноса на HDD (П1.161 шаг 5, Fable otvet-52, директор 28.11).
Замер rab-1 (~/remlab-logs/disk-zamer5-1128/OTCHET.md): 43 тревоги WARN:disk_stop из 47 замеров за 26–28.11, стопа (< 15 ГБ) не было ни разу — прогноз считал валовой рост логов и не знал про перенос.
Фикстура `fixtures/disk_forecast_47.json` — те же 47 замеров (свободно и рост из журнала часового юнита, убыль ушедших на HDD папок из snap.json), пересыпаны в снимки размеров.
(а) на 47 замерах тревог было 43 → стало меньше; (б) −контроль: тот же рост, но перенос остановлен (HDD нет / за окно ничего не ушло / часовой запуск пропускал) → тревога обязана сработать, как раньше;
(в) обычный рост без переноса — прогноз как раньше. Запуск: `python -m pytest tools/ops/tests/test_disk_forecast.py -q -p no:cacheprovider`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import logs_archive as la  # noqa: E402

GB = 1024 ** 3
FIX = json.loads((Path(__file__).parent / 'fixtures' / 'disk_forecast_47.json').read_text(encoding='utf-8'))
ROWS, STOP, WARN_H = FIX['rows'], FIX['stop_gb'], FIX['warn_h']
RULE_OLD = {'grow_alert_gb': 20, 'grow_window_h': 24, 'grow_top': 3, 'grow_alert_every_h': 6, 'forecast_window_h': 6, 'forecast_warn_h': WARN_H, 'src': '/нет', 'dst': '/нет-hdd'}
RULE_NEW = dict(RULE_OLD, forecast_relief_enabled=True, forecast_relief_window_h=24, forecast_relief_cap=0.8, forecast_relief_gap_h=2)
ALIVE = lambda: (True, 'кандидатов 3, освободят 12.0 ГБ')                        # noqa: E731
DEAD = lambda: (False, 'HDD не смонтирован')                                      # noqa: E731


@pytest.fixture(autouse=True)
def no_alerts(monkeypatch):
    monkeypatch.setattr(la, 'alert', lambda text: None)


def replay(tmp_path, row, rules, transfer=None, moved_gb=None, gap_h=1.0, free=None, gross_gb=None):
    """Один замер: снимки размеров (папка g растёт, папка mv — ушла на HDD) → growth_check в момент замера. → (msg, warn)."""
    now = row['t']
    moved = row['moved_gb'] if moved_gb is None else moved_gb
    gross = row['gross6_gb'] if gross_gb is None else gross_gb
    snaps = []
    if row['relief_span_h'] > 6.5:
        snaps.append({'t': now - row['relief_span_h'] * 3600, 'sizes': {'g': 0, 'mv': int(moved * GB)}})     # начало окна переноса (≤ 24 ч назад)
        snaps.append({'t': now - 6 * 3600, 'sizes': {'g': 0, 'mv': 0}})                                       # начало окна роста (6 ч)
    else:
        snaps.append({'t': now - 6 * 3600, 'sizes': {'g': 0, 'mv': int(moved * GB)}})                        # истории меньше суток: оба окна — 6 ч (оценка переноса снизу)
    snaps.append({'t': now - gap_h * 3600, 'sizes': {'g': int(gross * GB * 5 / 6), 'mv': 0}})                 # прошлый часовой снимок
    sp = tmp_path / ('snap-%d.json' % int(now))
    sp.write_text(json.dumps({'snaps': snaps}), encoding='utf-8')
    return la.growth_check(rules, now=now, du=lambda src: {'g': int(gross * GB), 'mv': 0}, state_path=str(sp),
                           free=row['free_gb'] if free is None else free, stop_gb=STOP, transfer=transfer, is_moved=lambda n: n == 'mv')


def alarms(tmp_path, rules, **kw):
    return [r for r in ROWS if replay(tmp_path, r, rules, **kw)[1].count('WARN:disk_stop')]


def test_fixture_is_the_47_measurements():
    assert len(ROWS) == 47 and STOP == 15 and WARN_H == 12
    assert sum(1 for r in ROWS if r['h_journal'] < WARN_H) == 43                      # столько тревог напечатал журнал (замер rab-1)
    assert min(r['free_gb'] for r in ROWS) == 17.0                                    # ближайшее к стопу за период; реального стопа (< 15) не было
    assert sum(1 for r in ROWS if r['moved_gb'] > 5) >= 10                            # переносы на HDD в данных есть


def test_old_forecast_reproduces_43_alarms_of_47(tmp_path):
    old = alarms(tmp_path, RULE_OLD, transfer=ALIVE)                                  # ключей переноса в правилах нет — перенос не учитывается, как до П1.161
    assert len(old) == 43
    for r in ROWS:                                                                    # и часы совпадают с напечатанными журналом (фикстура держит рост с точностью 0,1 ГБ/ч — при росте < 0,7 ГБ/ч часы уже не сверяем)
        if r['h_journal'] >= 20:
            continue
        msg, _ = replay(tmp_path, r, RULE_OLD)
        h = float(msg.split('≈ ')[1].split(' ч')[0])
        assert h == pytest.approx(r['h_journal'], rel=0.07, abs=0.25), (r['t'], h, r['h_journal'])


def test_47_measurements_false_alarms_drop_with_hdd_transfer(tmp_path):
    old = alarms(tmp_path, RULE_OLD)
    new = alarms(tmp_path, RULE_NEW, transfer=ALIVE)
    print(f'ложных тревог на 47 замерах: было {len(old)} → стало {len(new)}')
    assert len(old) == 43 and len(new) == EXPECT_NEW
    assert {r['t'] for r in new} <= {r['t'] for r in old}                              # новых тревог не появилось — только убрали
    assert len(new) <= len(old) * 0.6                                                  # «заметно меньше»: минус не менее 40 %
    # запас не потерян: самый близкий к стопу замер (17,0 ГБ, рост выше переноса) тревогу сохраняет
    close = [r for r in ROWS if r['free_gb'] == 17.0][0]
    assert close in new
    # пояснение в строке дайджеста — кто сколько снял
    msg, warn = replay(tmp_path, [r for r in ROWS if r['moved_gb'] > 5][5], RULE_NEW, transfer=ALIVE)
    assert 'перенос на HDD снимает' in msg


def test_control_transfer_stopped_alarm_must_fire(tmp_path):
    """−контроль: тот же рост, но перенос остановлен → все 43 тревоги как раньше (иначе прогноз молчал бы перед настоящим стопом)."""
    old = alarms(tmp_path, RULE_OLD)
    assert len(old) == 43
    assert len(alarms(tmp_path, RULE_NEW, transfer=DEAD)) == 43                        # HDD не смонтирован / полон / кандидатов нет — transfer() говорит «не идёт»
    assert len(alarms(tmp_path, RULE_NEW, transfer=ALIVE, moved_gb=0.0)) == 43         # служба «отработала», но за окно на HDD ничего не ушло
    assert len(alarms(tmp_path, RULE_NEW, transfer=ALIVE, gap_h=3.0)) == 43            # часовой запуск пропускал (прошлый снимок 3 ч назад)
    assert len(alarms(tmp_path, RULE_NEW, transfer=None)) == 43                        # проверка переноса не передана — не верим
    row = [r for r in ROWS if r['moved_gb'] > 5][3]
    msg, warn = replay(tmp_path, row, RULE_NEW, transfer=DEAD)
    assert 'WARN:disk_stop' in warn and 'перенос на HDD не идёт (HDD не смонтирован)' in warn
    assert replay(tmp_path, row, RULE_NEW, transfer=ALIVE, gap_h=3.0)[1].count('пропускал') == 1


def test_plain_growth_without_transfer_is_as_before(tmp_path):
    """(в) обычный рост без переноса: час-в-час как hours_to_stop, без пояснений о переносе."""
    row = {'t': 1_800_000_000.0, 'free_gb': 40.0, 'gross6_gb': 33.0, 'moved_gb': 0.0, 'relief_span_h': 24.0}
    for rules in (RULE_OLD, RULE_NEW):
        msg, warn = replay(tmp_path, row, rules, transfer=ALIVE)
        assert '≈ 4.5 ч' in msg and 'WARN:disk_stop:' in warn and 'до стопа (15 ГБ) ≈ 5 ч' in warn and 'перенос' not in msg + warn
    assert la.hours_to_stop(40, 15, 33, 6) == pytest.approx(4.545, abs=0.01)
    quiet = dict(row, free_gb=300.0)                                                   # много места — тихо и до, и после
    assert 'WARN:disk_stop' not in replay(tmp_path, quiet, RULE_NEW, transfer=ALIVE)[1]


def test_relief_is_capped_so_alarm_stays_close_to_stop(tmp_path):
    """Перенос не может «съесть» весь рост: потолок forecast_relief_cap (0,8) — до стопа не больше ×5 от прогноза по валовому росту."""
    row = {'t': 1_800_000_000.0, 'free_gb': 20.0, 'gross6_gb': 12.0, 'moved_gb': 500.0, 'relief_span_h': 24.0}      # 2 ГБ/ч, запас 5 ГБ → 2,5 ч; перенос «500 ГБ» — нереально много
    msg, warn = replay(tmp_path, row, RULE_NEW, transfer=ALIVE)
    assert '≈ 12.5 ч' in msg                                                           # 5 ГБ ÷ (2 × (1 − 0,8)) = 12,5 ч
    assert warn == ''                                                                  # 12,5 ≥ 12 — тревоги нет, но ближе к стопу она бы осталась
    near = dict(row, free_gb=19.0)                                                     # запас 4 ГБ → 10 ч < 12
    assert 'WARN:disk_stop' in replay(tmp_path, near, RULE_NEW, transfer=ALIVE)[1]


def test_transfer_relief_counts_only_folders_that_went_to_hdd():
    ref = {'a': 10 * GB, 'b': 8 * GB, 'c': 5 * GB}
    cur = {'a': 0, 'b': 9 * GB, 'c': 1 * GB, 'd': 3 * GB}                              # a, c — убыль; b вырос; d новая
    assert la.transfer_relief(ref, cur, lambda n: n in ('a', 'b')) == pytest.approx(10.0)    # b вырос — не вычитается; c не уходила на HDD — не считается
    assert la.transfer_relief(ref, cur, lambda n: False) == 0


def test_moved_to_hdd_follows_symlink_under_dst(tmp_path):
    src, dst = tmp_path / 'src', tmp_path / 'hdd'
    (src).mkdir()
    (dst / 'moved').mkdir(parents=True)
    (tmp_path / 'other' / 'x').mkdir(parents=True)
    (src / 'moved').symlink_to(dst / 'moved')
    (src / 'foreign').symlink_to(tmp_path / 'other' / 'x')
    (src / 'plain').mkdir()
    assert la.moved_to_hdd('moved', str(src), str(dst)) is True
    assert la.moved_to_hdd('foreign', str(src), str(dst)) is False and la.moved_to_hdd('plain', str(src), str(dst)) is False
    assert la.moved_to_hdd('moved', None, str(dst)) is False


def test_transfer_alive_reasons(monkeypatch):
    r = {'dst': '/m/hdd', 'src': '/нет', 'days': 5, 'min_hdd_free_gb': 50, 'adaptive': []}
    todo = [{'name': 't1', 'total': 4 * GB, 'freed': 3 * GB}]
    monkeypatch.setattr(la, 'hdd_mounted', lambda d: '/m')
    monkeypatch.setattr(la, 'hdd_free_gb', lambda d: 200.0)
    monkeypatch.setattr(la, 'candidates', lambda rr, repo: (list(todo), []))
    ok, why = la.transfer_alive(r, '/repo')
    assert ok and 'кандидатов 1' in why
    monkeypatch.setattr(la, 'candidates', lambda rr, repo: ([], []))
    assert la.transfer_alive(r, '/repo') == (False, 'кандидатов на перенос нет')
    monkeypatch.setattr(la, 'candidates', lambda rr, repo: (list(todo), []))
    monkeypatch.setattr(la, 'hdd_free_gb', lambda d: 30.0)
    assert la.transfer_alive(r, '/repo')[0] is False and 'на HDD свободно 30' in la.transfer_alive(r, '/repo')[1]
    monkeypatch.setattr(la, 'hdd_free_gb', lambda d: 52.0)                              # 4 ГБ × 1,1 + 50 > 52 — не помещается
    assert 'не помещается' in la.transfer_alive(r, '/repo')[1]
    monkeypatch.setattr(la, 'hdd_free_gb', lambda d: 200.0)
    monkeypatch.setattr(la, 'hdd_mounted', lambda d: '')
    assert la.transfer_alive(r, '/repo') == (False, 'HDD не смонтирован')
    monkeypatch.setattr(la, 'hdd_mounted', lambda d: '/m')

    def boom(rr, repo):
        la.MONITOR_NOTES.append('наблюдатель pid 1 — чужая строка')
        raise OSError('git grep упал')
    monkeypatch.setattr(la, 'candidates', boom)
    monkeypatch.setattr(la, 'MONITOR_NOTES', [])
    ok, why = la.transfer_alive(r, '/repo')
    assert ok is False and 'OSError' in why and la.MONITOR_NOTES == []                  # строки наблюдателей проверка не оставляет


def test_rules_file_has_relief_keys_with_why():
    r = la.rules()
    assert r['forecast_relief_enabled'] is False                                        # по умолчанию ВЫКЛ: включать — после новой недели замеров (директор 28.11)
    assert r['forecast_relief_window_h'] == 24 and r['forecast_relief_cap'] == 0.8 and r['forecast_relief_gap_h'] == 2   # значения готовы, но не действуют
    assert r['forecast_warn_h'] == 12 and r['forecast_window_h'] == 6                   # порог тревоги не менялся
    d = json.loads((OPS.parent / 'scout' / 'rules' / 'dev-disk.json').read_text(encoding='utf-8'))
    assert 'otvet-52' in d['archive']['_forecast_relief_why'] and 'П1.161' in d['archive']['_forecast_relief_why']
    assert 'новой недели замеров' in d['archive']['_forecast_relief_why']


def test_relief_off_by_default_forecast_is_byte_identical(tmp_path):
    """−контроль «выкл = прежний»: ключи в dev-disk.json ВЫКЛ → после влития прогноз и тревоги ПОБАЙТНО прежние (строка дайджеста и WARN), даже когда перенос идёт и данные о нём есть."""
    file_rules = dict(la.rules(), src='/нет', dst='/нет-hdd')
    assert file_rules['forecast_relief_enabled'] is False
    off = dict(RULE_NEW, forecast_relief_enabled=False)
    for r in ROWS:
        base = replay(tmp_path, r, RULE_OLD)
        assert replay(tmp_path, r, file_rules, transfer=ALIVE) == base, r['t']
        assert replay(tmp_path, r, off, transfer=ALIVE) == base, r['t']
        assert 'перенос' not in ''.join(base)
    assert len(alarms(tmp_path, file_rules, transfer=ALIVE)) == 43


def test_enabled_with_file_values_47_measurements_43_to_25_and_stopped_43(tmp_path):
    """Те же значения, что лежат в dev-disk.json (24 / 0,8 / 2), но ВКЛЮЧЁННЫЕ: на 47 замерах 43 → 25; перенос остановлен — 43 из 43."""
    fr = la.rules()
    assert (fr['forecast_relief_window_h'], fr['forecast_relief_cap'], fr['forecast_relief_gap_h']) == (24, 0.8, 2)
    on = dict(fr, src='/нет', dst='/нет-hdd', forecast_relief_enabled=True)
    assert len(alarms(tmp_path, on, transfer=ALIVE)) == EXPECT_NEW == 25
    assert len(alarms(tmp_path, on, transfer=DEAD)) == 43
    assert len(alarms(tmp_path, on, transfer=ALIVE, moved_gb=0.0)) == 43


EXPECT_NEW = 25                                                                         # на тех же 47 замерах: было 43 → стало 25 (минус 42 %)
