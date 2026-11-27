#!/usr/bin/env python3
"""Тест стража правил (T-20261127-175/3): строка-счётчик, оповещения, напоминания о сроках. Стандартная библиотека.
Запуск: python tools/scout/tests/test_rules_guard.py"""
import datetime
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rules_guard')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import rule_registry_audit as RA  # noqa: E402
import rules_guard as RG  # noqa: E402
import zhurnal_vladeltsa as ZV  # noqa: E402

RULES = 'tools/scout/rules/'
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
TODAY = datetime.date(2026, 11, 27)
CFG = RG.load_config()


def reg(groups=None, rules=None):
    return {'version': 3, 'decide_by_max': '2026-12-01', 'groups': groups or {}, 'rules': rules or []}


def world(registry=None, files=None, threshold=None, settings=None):
    """Мини-репозиторий для стража: правила a.json (+другие), реестр, настройки и порог сторожа выключателей."""
    d = tempfile.mkdtemp(prefix='rg-')
    os.makedirs(os.path.join(d, RULES), exist_ok=True)
    files = {'a.json': {'enabled': False, 'nested': {'on': True}}} if files is None else files
    for name, body in files.items():
        json.dump(body, open(os.path.join(d, RULES, name), 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(registry if registry is not None else reg(), open(os.path.join(d, RULES, 'rule-registry.json'), 'w'), ensure_ascii=False)
    json.dump(settings if settings is not None else {'scan': [RULES + 'a.json', RULES + 'b.json'], 'skip_files': {}, 'settings': {}}, open(os.path.join(d, RULES, 'switch-settings.json'), 'w'), ensure_ascii=False)
    json.dump(threshold if threshold is not None else {'max_uncovered': 2, 'known': [RULES + 'a.json#enabled', RULES + 'a.json#nested.on']},
              open(os.path.join(d, RULES, 'switch-guard-threshold.json'), 'w'), ensure_ascii=False)
    return d


def journal(lines):
    p = os.path.join(tempfile.mkdtemp(prefix='rgj-'), 'journal.jsonl')
    with open(p, 'w', encoding='utf-8') as f:
        for ln in lines:
            f.write((ln if isinstance(ln, str) else json.dumps(ln, ensure_ascii=False)) + '\n')
    return p


def trial(rid, gid, **kw):
    return dict({'rule_id': rid, 'state': 'trial', 'group': gid}, **kw)


def test_deadlines_count_only_live_trial_groups_and_own_dates():
    r = reg({'G1': {'decide_by': '2026-11-26'}, 'G2': {'decide_by': '2026-12-01'}, 'G3': {'decide_by': '2026-11-01'}},
            [trial('R-1', 'G1'), trial('R-2', 'G2'), trial('R-3', 'G2', decide_by='2026-11-20'), {'rule_id': 'R-4', 'state': 'retired', 'group': 'G3'}, {'rule_id': 'R-5', 'state': 'active'}])
    dl = RG.deadlines(r, TODAY)
    left = {d['what']: d['days_left'] for d in dl}
    assert left == {'группа G1': -1, 'группа G2': 4, 'правило R-3 (группа G2)': -7}, left      # G3 — только retired: срока нет; active — не пробное
    assert RG.deadlines({'version': 2, 'groups': {'G': {'decide_by': '2020-01-01'}}, 'rules': [trial('R', 'G')]}, TODAY) == []


def test_overdue_agrees_with_registry_audit_on_real_registry():
    """Один счёт с аудитом: группы с «срок вышел» у аудита = группы с days_left < 0 у стража — на сегодня и на даты после срока (расхождение = дрейф условия)."""
    real = json.load(open(RG.REGISTRY, encoding='utf-8'))
    for day in ('2026-11-27', '2026-11-30', '2026-12-02', '2027-01-15'):
        d = datetime.date.fromisoformat(day)
        a = RA.audit(today=d)
        audit_groups = {p['rule_id'] for p in a['problems'] if 'вышел' in p['why'] and p['rule_id'].startswith('группа ')}
        mine = {x['what'] for x in RG.deadlines(real, d) if x['days_left'] < 0 and x['gid']}
        assert audit_groups == mine, (day, audit_groups, mine)
    assert any(RG.deadlines(real, datetime.date(2027, 1, 15))), 'на 15.01.2027 у боевого реестра должны быть просроченные группы'


def test_switches_new_and_unclassified_count_but_legacy_does_not():
    d = world()
    res = RG.evaluate(d, CFG, {}, NOW, TODAY, journal([]))
    assert res['outside'] == 0 and res['outside_old'] == 2, res                      # два старых из known — справка, не M
    d = world(files={'a.json': {'enabled': False, 'nested': {'on': True}}, 'b.json': {'fresh': True}})
    res = RG.evaluate(d, CFG, {}, NOW, TODAY, journal([]))
    assert res['outside'] == 1 and any('b.json#fresh' in x for x in res['outside_items']), res
    d = world(files={'a.json': {'enabled': False, 'nested': {'on': True}}, 'zz.json': {'x': True}})       # zz.json — ни в scan, ни в skip_files
    res = RG.evaluate(d, CFG, {}, NOW, TODAY, journal([]))
    assert res['outside'] == 1 and any('zz.json' in x for x in res['outside_items']), res
    assert RG.line_of(res).startswith('правила: просрочено 0, вне реестра: новых 1 (старый долг 2), ')


def test_line_shows_legacy_debt_not_hides_it():
    """Fable proverka-t175-3 § 2 п.2: «вне реестра 0» рядом с долгом в сотни выключателей — ложный ноль. Долг — в самой строке; на «новых» он не влияет (is_clean)."""
    d = world()                                                                       # два старых из known, новых нет
    res = RG.evaluate(d, CFG, {}, NOW, TODAY, journal([]))
    assert res['outside'] == 0 and res['outside_old'] == 2 and RG.is_clean(res), res
    assert 'вне реестра: новых 0 (старый долг 2)' in res['line'], res['line']
    d = world(threshold={'max_uncovered': 9, 'known': []})                            # те же два — теперь НОВЫЕ: долга 0, новых 2
    res = RG.evaluate(d, CFG, {}, NOW, TODAY, journal([]))
    assert 'вне реестра: новых 2 (старый долг 0)' in res['line'] and not RG.is_clean(res), res['line']


def test_off_remove_counts_after_off_days_from_first_seen():
    unc = [{'name': 'a#x', 'value': False}, {'name': 'a#y', 'value': True}, {'name': 'a#m', 'value': 'observe'}]
    due, seen = RG.off_remove(unc, {}, TODAY, 14)
    assert due == [] and set(seen) == {'a#x', 'a#m'}, (due, seen)                     # включённый (y) не наблюдается; первые сутки — не «на удаление»
    old = {'off_first_seen': {'a#x': '2026-11-10', 'gone#z': '2026-10-01'}}
    due, seen = RG.off_remove(unc, old, TODAY, 14)
    assert due == ['a#x'] and 'gone#z' not in seen and seen['a#m'] == TODAY.isoformat(), (due, seen)    # 17 суток → на удаление; исчезнувший выпал


def msg_ev(i, ts, text='сообщение', bot='tg-remlab'):
    """Строка сообщения в НАСТОЯЩЕМ формате журнала (tools/ops/zhurnal_vladeltsa.py; пишет плагин Telegram, T-175/4)."""
    return {'t': 'msg', 'bot': bot, 'id': i, 'ts': ts, 'chat': '95903801', 'user': 'igor', 'tip': 'text', 'nachalo': text}


def test_journal_pending_old_missing_and_closed_by_later_line():
    p = journal([msg_ev(1, '2026-11-27T11:00:00.000Z', 'новое'), msg_ev(2, '2026-11-27T08:00:00.000Z', 'старое'), msg_ev(3, '2026-11-27T07:00:00.000Z', 'закрытое'),
                 {'t': 'zakryt', 'bot': 'tg-remlab', 'id': 3, 'ts': '2026-11-27T07:30:00.000Z', 'adres': 'задача T-20261127-175', 'kto': 'директор'},
                 {'t': 'napom', 'bot': 'tg-remlab', 'chat': '95903801', 'ts': '2026-11-27T10:00:00.000Z', 'ids': [2]},          # напоминание — не сообщение
                 '{битая строка', msg_ev(4, (NOW - datetime.timedelta(minutes=10)).isoformat(), 'свежее')])
    j = RG.read_journal(p, NOW, 2)
    assert [x['n'] for x in j['pending']] == ['tg-remlab №1', 'tg-remlab №2', 'tg-remlab №4'] and [x['n'] for x in j['old']] == ['tg-remlab №2'] and j['bad'] == 1, j
    miss = RG.read_journal(os.path.join(tempfile.mkdtemp(prefix='rgm-'), 'нет.jsonl'), NOW, 2)
    assert miss['exists'] is False
    res = RG.evaluate(world(), CFG, {}, NOW, TODAY, os.path.join(tempfile.mkdtemp(prefix='rgm-'), 'нет.jsonl'))
    assert res['unreviewed'] is None and 'без разбора ?,' in res['line'] and RG.is_clean(res)    # нет журнала — «?», не ошибка


def test_guard_reads_journal_exactly_as_zhurnal_vladeltsa_does():
    """T-175/fix-3-5-7 п.6 (Fable 27, proverka-t175-4 § 2 п.1): страж и журнал говорили на разных форматах — страж показывал «?». Теперь страж читает журнал КОДОМ журнала:
    его число = `zhurnal-vladeltsa schet` (все ждущие) и `schet --starshe-min 120` (дольше 2 ч); запись плагина → строка стража → закрытие командой → строка стража."""
    old = (NOW - datetime.timedelta(hours=3)).isoformat()
    p = journal([msg_ev(3612, old, 'Регламент — жду'), msg_ev(3613, (NOW - datetime.timedelta(minutes=30)).isoformat(), 'свежее'), msg_ev(50, old, 'другой бот', bot='tg-tamara')])
    res = RG.evaluate(world(), CFG, {}, NOW, TODAY, p)
    assert res['unreviewed'] == ZV.cmd_schet(p, 0, None, NOW) == 3 and res['unreviewed_old'] == ZV.cmd_schet(p, 120, None, NOW) == 2, res
    assert 'без разбора 3,' in res['line'] and not RG.is_clean(res), res['line']                         # строка стража ПОКАЗЫВАЕТ ждущие, а не «?»
    assert any('Регламент — жду' in x for x in res['unreviewed_items']), res['unreviewed_items']
    msgs, _ = RG.plan_alerts(res, {}, NOW, CFG)
    assert len(msgs) == 1 and 'без разбора дольше 2 ч: 2' in msgs[0][0], msgs                                  # ждущий дольше 2 ч → сигнал
    rc, out = ZV.cmd_zakryt(p, '3612', 'разобрано', 'tg-remlab')                                                  # «разобрано» без пояснения — отказ (п.5), строка осталась ждать
    assert rc == 2 and RG.evaluate(world(), CFG, {}, NOW, TODAY, p)['unreviewed_old'] == 2, out
    rc, out = ZV.cmd_zakryt(p, '3612', 'задача T-20261127-175', 'tg-remlab')
    assert rc == 0, out
    res = RG.evaluate(world(), CFG, {}, NOW, TODAY, p)
    assert res['unreviewed'] == ZV.cmd_schet(p, 0, None, NOW) == 2 and res['unreviewed_old'] == ZV.cmd_schet(p, 120, None, NOW) == 1, res
    # путь по умолчанию: $OWNER_JOURNAL перекрывает journal_path из настроек (его же читает команда журнала)
    os.environ['OWNER_JOURNAL'] = p
    try:
        assert RG.evaluate(world(), CFG, {}, NOW, TODAY)['unreviewed'] == 2
    finally:
        del os.environ['OWNER_JOURNAL']
    # старый, придуманный стражем формат ({"n","status"}) журнал НЕ читает — единственный формат один, в журнале
    legacy = journal([{'n': 1, 'ts': old, 'text': 'x', 'status': 'ждёт разбора'}])
    assert RG.evaluate(world(), CFG, {}, NOW, TODAY, legacy)['unreviewed'] == 0


def res_with(**kw):
    base = {'overdue': 0, 'overdue_items': [], 'outside': 0, 'outside_items': [], 'off_remove': 0, 'off_remove_items': [], 'off_first_seen': {}, 'unreviewed': 0,
            'unreviewed_old': 0, 'unreviewed_items': [], 'deadlines': [], 'line': 'правила: …'}
    base.update(kw)
    return base


def test_alert_only_after_threshold_then_not_more_often_than_realert():
    r = res_with(overdue=1, overdue_items=['группа G1 — срок 2026-11-26, прошло 1 дн.'])
    msgs, st = RG.plan_alerts(r, {}, NOW, CFG)
    assert msgs == [] and 'overdue' in st['since']                                  # первый раз увидели — порог (60 мин) ещё не прошёл
    later = NOW + datetime.timedelta(minutes=61)
    msgs, st2 = RG.plan_alerts(r, st, later, CFG)
    assert len(msgs) == 1 and 'просрочено 1' in msgs[0][0] and msgs[0][1] == ['alert:overdue'], msgs
    RG.commit_sent(st2, msgs[0][1], later)
    assert RG.plan_alerts(r, st2, later + datetime.timedelta(hours=5), CFG)[0] == []           # повтор — не раньше 6 ч
    assert len(RG.plan_alerts(r, st2, later + datetime.timedelta(hours=7), CFG)[0]) == 1
    msgs, st3 = RG.plan_alerts(res_with(), st2, later + datetime.timedelta(hours=8), CFG)      # счётчик снова ноль — отметка начала сбрасывается
    assert msgs == [] and 'overdue' not in st3['since']


def test_unreviewed_old_alerts_immediately():
    r = res_with(unreviewed=2, unreviewed_old=1, unreviewed_items=['2: старое'])
    msgs, _ = RG.plan_alerts(r, {}, NOW, CFG)
    assert len(msgs) == 1 and 'без разбора дольше 2 ч' in msgs[0][0]


def test_reminders_once_per_group_deadline_and_again_after_move():
    dl = [{'what': 'группа G1', 'gid': 'G1', 'decide_by': '2026-12-01', 'days_left': 4, 'rules': ['R']}]
    assert RG.plan_alerts(res_with(deadlines=dl), {}, NOW, CFG)[0] == []                       # за 4 дня — рано
    dl[0]['days_left'] = 3
    msgs, st = RG.plan_alerts(res_with(deadlines=dl), {}, NOW, CFG)
    assert len(msgs) == 1 and 'до срока 3 дн.' in msgs[0][0], msgs
    RG.commit_sent(st, msgs[0][1], NOW)
    assert RG.plan_alerts(res_with(deadlines=dl), st, NOW, CFG)[0] == []                       # то же напоминание — один раз
    dl[0]['days_left'] = 1
    msgs, st = RG.plan_alerts(res_with(deadlines=dl), st, NOW, CFG)
    assert len(msgs) == 1 and 'до срока 1 дн.' in msgs[0][0]                                     # за день — своё
    RG.commit_sent(st, msgs[0][1], NOW)
    dl[0].update(decide_by='2026-12-05', days_left=3)                                           # срок перенесён → напоминание о новом сроке приходит снова
    assert len(RG.plan_alerts(res_with(deadlines=dl), st, NOW, CFG)[0]) == 1
    dl[0].update(days_left=0)
    assert 'срок сегодня' in RG.plan_alerts(res_with(deadlines=[dict(dl[0], decide_by='2026-11-27')]), {}, NOW, CFG)[0][0][0]


def test_cli_notify_end_to_end_failed_send_is_retried_and_files_written():
    r = reg({'G1': {'decide_by': '2026-11-26', 'enable_if': 'на 29 — 5 признаков'}}, [trial('R-1', 'G1')])
    d = world(registry=r)
    sd = os.path.join(tempfile.mkdtemp(prefix='rgs-'), 'st')
    jp = journal([])
    sent = []

    def fail(text):
        sent.append(text)
        return 1

    def ok(text):
        sent.append(text)
        return 0
    args = ['--notify', '--root', d, '--state-dir', sd, '--journal', jp]
    assert RG.main(args + ['--now', '2026-11-27T12:00:00+00:00'], sender=fail) == 0 and sent == []              # первый взгляд — порога нет
    assert RG.main(args + ['--now', '2026-11-27T13:05:00+00:00'], sender=fail) == 0 and len(sent) == 1          # Telegram не ответил (rc 1)
    assert RG.main(args + ['--now', '2026-11-27T13:35:00+00:00'], sender=ok) == 0 and len(sent) == 2            # не отмечено доставленным → повтор
    assert RG.main(args + ['--now', '2026-11-27T14:05:00+00:00'], sender=ok) == 0 and len(sent) == 2            # доставлено → тишина до realert
    line = open(os.path.join(sd, 'line.txt'), encoding='utf-8').read().strip()
    assert line.startswith('правила: просрочено 1, вне реестра: новых 0 (старый долг 2), сообщений владельца без разбора 0, выключателей на удаление 0'), line
    rep = json.load(open(os.path.join(sd, 'report.json'), encoding='utf-8'))
    assert rep['overdue'] == 1 and rep['journal']['exists'] is True
    assert RG.main(['--check', '--root', d, '--state-dir', sd, '--journal', jp, '--now', '2026-11-27T14:05:00+00:00']) == 1
    assert RG.main(['--check', '--root', world(), '--state-dir', sd, '--journal', jp, '--now', '2026-11-27T14:05:00+00:00']) == 0
    # без --notify ничего не пишется
    sd2 = os.path.join(tempfile.mkdtemp(prefix='rgs-'), 'st')
    RG.main(['--root', d, '--state-dir', sd2, '--journal', jp])
    assert not os.path.exists(sd2)


def test_real_repo_line_is_zero_today_and_has_four_counters():
    res = RG.evaluate(ROOT, CFG, {}, NOW, TODAY, os.path.join(tempfile.mkdtemp(prefix='rgm-'), 'нет.jsonl'))
    assert res['overdue'] == 0 and res['outside'] == 0 and res['off_remove'] == 0, res['line']
    import re
    assert re.fullmatch(r'правила: просрочено 0, вне реестра: новых 0 \(старый долг \d+\), сообщений владельца без разбора \?, выключателей на удаление 0', res['line']), res['line']

if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
    print('OK: test_rules_guard %d проверок' % n)
