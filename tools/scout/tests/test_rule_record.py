#!/usr/bin/env python3
"""Тест общего помощника записи правила в check.json (T-20261123-48/3): тип и digest — из паспорта, воздержание — только с причиной, повтор заменяет запись,
запись принимается структурной сверкой `rule_registry_audit --run`. Запуск: python tools/scout/tests/test_rule_record.py (стандартная библиотека)."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rule_record')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import mesh_type_passports as MP  # noqa: E402
import rule_record as RR  # noqa: E402
import rule_registry_audit as RA  # noqa: E402

REG = MP.load()
ROLE = 'комод'


def test_entry_takes_type_and_digest_from_passport():
    e = RR.entry('R-X-1', ROLE, True)
    assert e == {'rule_id': 'R-X-1', 'type': 'комод', 'digest': MP.digest_of(REG['types']['комод']), 'applied': True}, e
    e = RR.entry('R-X-1', ROLE, True, 'порог 0.9')
    assert e['applied'] is True and e['note'] == 'порог 0.9'


def test_abstain_needs_reason():
    e = RR.entry('R-X-1', ROLE, False, 'нет камеры этапа 4')
    assert e['abstain'] == 'нет камеры этапа 4' and 'applied' not in e and e['digest']
    for bad in ('', '   '):
        try:
            RR.entry('R-X-1', ROLE, False, bad)
        except ValueError:
            continue
        raise AssertionError('воздержание без причины принято')
    try:
        RR.entry('', ROLE, True)
    except ValueError:
        pass
    else:
        raise AssertionError('пустой rule_id принят')


def test_unknown_role_is_always_abstain():
    for role in (None, '', 'нет-такой-роли-в-паспорте'):
        e = RR.entry('R-X-1', role, True)
        assert e['type'] is None and e['digest'] is None and 'applied' not in e and e['abstain'].startswith('тип не определён'), e
    e = RR.entry('R-X-1', None, False, 'нет роли в каталоге')
    assert 'нет роли в каталоге' in e['abstain']


def test_record_replaces_same_rule_and_type_keeps_others():
    c = {'passed': True}
    RR.record(c, 'R-X-1', ROLE, False, 'сначала нет камеры')
    RR.record(c, 'R-X-2', ROLE, True)
    RR.record(c, 'R-X-1', ROLE, True)                                              # повторный запуск этапа: замена, не дубль
    rules = c['extra']['rules']
    assert len(rules) == 2 and [r['rule_id'] for r in rules].count('R-X-1') == 1, rules
    assert next(r for r in rules if r['rule_id'] == 'R-X-1').get('applied') is True
    RR.record(c, 'R-X-1', 'диван', True)                                           # другой тип — отдельная запись
    assert len(c['extra']['rules']) == 3
    c2 = {'extra': {'camera': {'az': 1}}}
    RR.record(c2, 'R-X-1', ROLE, True)
    assert c2['extra']['camera'] == {'az': 1}                                      # чужие поля extra не трогаем


def test_record_file_atomic_and_missing():
    d = tempfile.mkdtemp(prefix='rr-')
    p = os.path.join(d, 'check.json')
    json.dump({'passed': True, 'extra': {'k': 1}}, open(p, 'w'))
    RR.record_file(p, 'R-X-1', ROLE, True)
    j = json.load(open(p, encoding='utf-8'))
    assert j['extra']['k'] == 1 and j['extra']['rules'][0]['rule_id'] == 'R-X-1' and not os.path.exists(p + '.tmp')
    try:
        RR.record_file(os.path.join(d, 'нет.json'), 'R-X-1', ROLE, True)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError('нет файла — должна быть ошибка')


def test_audit_run_accepts_records_made_by_helper():
    """Сквозное: этап записал запись помощником → `rule_registry_audit --run` её принимает; воздержание без типа/с чужим digest — нет."""
    d = tempfile.mkdtemp(prefix='rr-run-')
    rule = {'rule_id': 'R-X-1', 'check_field': '06-visible.rules', 'applies': {'types': ['комод']}}
    run = os.path.join(d, 'run')
    for sku, applied, why in (('a', True, ''), ('b', False, 'нет камеры этапа 4')):
        os.makedirs(os.path.join(run, sku, '06-visible'))
        p = os.path.join(run, sku, '06-visible', 'check.json')
        json.dump({'passed': True}, open(p, 'w'))
        RR.record_file(p, 'R-X-1', ROLE, applied, why)
    problems = []
    RA.check_run(rule, run, REG['types'], ROOT, lambda rid, cls, why, err=False: problems.append((rid, cls, why, err)))
    assert not problems, problems
    p = os.path.join(run, 'a', '06-visible', 'check.json')                         # паспорт «изменился» после записи → digest не совпал
    j = json.load(open(p))
    j['extra']['rules'][0]['digest'] = '0' * 64
    json.dump(j, open(p, 'w'))
    RA.check_run(rule, run, REG['types'], ROOT, lambda rid, cls, why, err=False: problems.append((rid, cls, why, err)))
    assert any('digest' in x[2] and x[3] for x in problems), problems


if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
    print('OK: test_rule_record %d проверок' % n)
