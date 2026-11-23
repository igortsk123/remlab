#!/usr/bin/env python3
"""Тест автосверки реестра правил (T-20261123-48, 48/2): сверка ПОВЕДЕНИЯ — символ через ast и вызов боевым кодом, флаг/observe → «выключено», парные тесты и run_id у active,
структурная сверка прогона (--run), --json для обхода, --strict-types. CI красный на active без кода/теста. Запуск: python tools/scout/tests/test_rule_registry_audit.py (стандартная библиотека)."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rule_registry_audit')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))   # tools/ops первым: рядом в tools/scout есть свой rules_audit
import rule_registry_audit as RA  # noqa: E402
import mesh_type_passports as MP  # noqa: E402  (digest_of — тот же, что в боевых check.json)

CODE = 'CONST = 1\n\n\ndef consumer_fn():\n    return 1\n\n\ndef lonely_fn():\n    return 2\n'
CALLER = 'from code import consumer_fn\n\nx = consumer_fn()\ny = CONST\n'
TEST = 'def test_x():\n    pass\n\n\ndef test_pos():\n    pass\n\n\ndef test_neg():\n    pass\n'
GOOD = dict(state='active', consumer='tools/code.py:consumer_fn', runtime='enforce', test='tests/t.py::test_x', test_positive='tests/t.py::test_pos',
            test_negative='tests/t.py::test_neg', run_id='run-1')


def rule(**kw):
    r = {'rule_id': 'R-T-1', 'title': 't', 'state': 'proposed', 'source': ['TG 1'], 'applies': {'types': ['all']}, 'executor': 'x', 'consumer': None,
         'runtime': 'none', 'test': None, 'test_positive': None, 'test_negative': None, 'run_id': None, 'flag': None, 'check_field': None, 'enabled': None}
    r.update(kw)
    return r


def world(rules, ci='run: python tests/t.py', code=CODE, caller=CALLER, test=TEST, passports=None, flags=None):
    d = tempfile.mkdtemp(prefix='rra-')
    for name, text in (('tools/code.py', code), ('tools/caller.py', caller), ('tests/t.py', test), ('tools/f.json', json.dumps(flags or {'on': True, 'off': False, 'mode': 'observe'}))):
        os.makedirs(os.path.dirname(os.path.join(d, name)), exist_ok=True)
        open(os.path.join(d, name), 'w').write(text)
    json.dump({'rules': rules}, open(os.path.join(d, 'reg.json'), 'w'), ensure_ascii=False)
    json.dump({'types': passports if passports is not None else {'комод': {'family': 'корпусное', 'paint': {'hidden_pattern': 'body'}}}},
              open(os.path.join(d, 'pass.json'), 'w'), ensure_ascii=False)
    open(os.path.join(d, 'ci.yml'), 'w').write(ci)
    return d


def run(rules, run_dir='', **kw):
    d = world(rules, **kw)
    res = RA.audit(os.path.join(d, 'reg.json'), os.path.join(d, 'pass.json'), os.path.join(d, 'ci.yml'), d, run_dir)
    text, errs = RA.report(res)
    return res, text, errs, d


def classes(res):
    return {(p['rule_id'], p['cls'], p['error']) for p in res['problems']}


def test_good_active_is_clean():
    res, text, errs, _ = run([rule(**GOOD)])
    assert errs == 0 and not res['problems'], (errs, text)


def test_active_without_code_fails():
    res, text, errs, _ = run([rule(**dict(GOOD, consumer=None, runtime='none'))])
    assert errs >= 1 and ('R-T-1', RA.C_NOCODE, True) in classes(res), text


def test_symbol_checked_by_ast_not_by_word():
    # слово есть только в комментарии/строке — это НЕ определение
    res, _, errs, _ = run([rule(state='trial', consumer='tools/code.py:ghost_fn', runtime='observe')], code='# ghost_fn\nX = "ghost_fn"\n')
    assert errs >= 1 and ('R-T-1', RA.C_BROKEN, True) in classes(res)
    # константа существует и используется
    res, _, errs, _ = run([rule(state='trial', consumer='tools/code.py:CONST', runtime='observe')])
    assert errs == 0 and ('R-T-1', RA.C_NOCALL, False) not in classes(res), res


def test_defined_but_not_called_is_class_and_active_fails():
    res, _, errs, _ = run([rule(state='trial', consumer='tools/code.py:lonely_fn', runtime='enforce')])
    assert errs == 0 and ('R-T-1', RA.C_NOCALL, False) in classes(res), res
    res, _, errs, _ = run([rule(**dict(GOOD, consumer='tools/code.py:lonely_fn'))])
    assert errs >= 1 and ('R-T-1', RA.C_NOCALL, True) in classes(res)


def test_call_from_tests_only_does_not_count():
    res, _, errs, _ = run([rule(**GOOD)], caller='', test=TEST + '\n\ndef helper():\n    from code import consumer_fn\n    return consumer_fn()\n')
    assert ('R-T-1', RA.C_NOCALL, True) in classes(res) and errs >= 1


def test_intentionally_disabled_rule_is_not_active():
    # runtime=observe у active → ошибка, класс «код есть, но выключен»
    res, _, errs, _ = run([rule(**dict(GOOD, runtime='observe'))])
    assert errs >= 1 and ('R-T-1', RA.C_OBSERVE, True) in classes(res)
    # runtime=enforce, но флаг в правилах выключен → всё равно «выключено»
    res, _, errs, _ = run([rule(**dict(GOOD, flag='tools/f.json#off'))])
    assert errs >= 1 and ('R-T-1', RA.C_OBSERVE, True) in classes(res), res
    res, _, errs, _ = run([rule(**dict(GOOD, flag='tools/f.json#mode'))])               # «observe» — не «включено»
    assert errs >= 1 and ('R-T-1', RA.C_OBSERVE, True) in classes(res)
    # флаг включён → чисто
    res, _, errs, _ = run([rule(**dict(GOOD, flag='tools/f.json#on'))])
    assert errs == 0, res
    # блок-словарь: {"mode": "active"} — включено, {"mode": "observe"} / {"enabled": false} — выключено
    fl = {'blk': {'mode': 'active', 'x': 1}, 'blk_obs': {'mode': 'observe'}, 'blk_off': {'enabled': False, 'mode': 'active'}}
    res, _, errs, _ = run([rule(**dict(GOOD, flag='tools/f.json#blk'))], flags=fl)
    assert errs == 0, res
    for k in ('blk_obs', 'blk_off'):
        res, _, errs, _ = run([rule(**dict(GOOD, flag='tools/f.json#' + k))], flags=fl)
        assert errs >= 1 and ('R-T-1', RA.C_OBSERVE, True) in classes(res), k
    # у trial то же — только класс, без ошибки
    res, _, errs, _ = run([rule(**dict(GOOD, state='trial', runtime='observe'))])
    assert errs == 0 and ('R-T-1', RA.C_OBSERVE, False) in classes(res)
    # флаг-ключа нет → битая ссылка
    res, _, errs, _ = run([rule(**dict(GOOD, flag='tools/f.json#нет.такого'))])
    assert errs >= 1


def test_active_needs_pair_tests_and_run_id():
    for drop in ('test_positive', 'test_negative', 'run_id'):
        res, _, errs, _ = run([rule(**dict(GOOD, **{drop: None}))])
        assert errs >= 1 and ('R-T-1', RA.C_NOPAIR, True) in classes(res), drop
    # у trial без парных тестов — не ошибка
    res, _, errs, _ = run([rule(**dict(GOOD, state='trial', test_positive=None, test_negative=None, run_id=None))])
    assert errs == 0, res
    # парный тест называет несуществующую функцию (ast)
    res, _, errs, _ = run([rule(**dict(GOOD, test_negative='tests/t.py::test_нет'))])
    assert errs >= 1 and ('R-T-1', RA.C_BROKEN, True) in classes(res)


def test_active_test_not_in_ci_fails():
    res, _, errs, _ = run([rule(**GOOD)], ci='run: echo нет')
    assert errs >= 1 and ('R-T-1', RA.C_NOTEST, True) in classes(res)


def test_proposed_without_code_is_class_not_error():
    res, text, errs, _ = run([rule()])
    assert errs == 0 and ('R-T-1', RA.C_NOCODE, False) in classes(res), text


def test_broken_reference_is_error_even_for_proposed():
    res, _, errs, _ = run([rule(consumer='tools/нет.py:f', runtime='observe')])
    assert errs >= 1 and ('R-T-1', RA.C_BROKEN, True) in classes(res)
    res, _, errs, _ = run([rule(consumer='tools/code.py:нет_такой', runtime='observe')])
    assert errs >= 1
    res, _, errs, _ = run([rule(test='tests/t.py::test_нет')])
    assert errs >= 1


def test_schema_errors():
    res, _, errs, _ = run([rule(), rule()])                                         # дубль id
    assert any(p['why'] == 'rule_id повторяется' for p in res['problems']) and errs >= 1
    for bad in (dict(rule_id='bad id'), dict(state='включено'), dict(applies={'types': ['нет-такого-типа']}), dict(applies={'families': ['нет-такого-семейства']})):
        res, _, errs, _ = run([rule(**bad)])
        assert errs >= 1, bad
    r = rule()
    del r['consumer']
    res, _, errs, _ = run([r])
    assert errs >= 1


def test_retired_skips_code_checks():
    res, _, errs, _ = run([rule(state='retired', consumer='tools/нет.py:f')])
    assert errs == 0, res


def test_types_without_policy_is_class_and_strict_switch():
    res, text, errs, _ = run([rule()], passports={'комод': {'family': 'корпусное', 'paint': {}}})
    assert errs == 0 and any(p['cls'] == RA.C_NOPOLICY for p in res['problems'])
    _, errs = RA.report(res, strict_types=True)
    assert errs >= 1


def _run_dir(d, entries_by_sku, stage='09-check'):
    rd = os.path.join(d, 'run')
    for sku, entries in entries_by_sku.items():
        os.makedirs(os.path.join(rd, sku, stage), exist_ok=True)
        json.dump({'passed': True, 'extra': {'rules': entries}}, open(os.path.join(rd, sku, stage, 'check.json'), 'w'))
    return rd


def _entry(t='комод', **kw):
    p = RA.load_passports()
    e = {'rule_id': 'R-T-1', 'type': t, 'digest': MP.digest_of(p[t]), 'applied': True}
    e.update(kw)
    return e


def _run_audit(entries_by_sku, rule_kw=None, types=('комод',)):
    d = world([rule(**dict(GOOD, check_field='09-check.rules', **(rule_kw or {})))])
    rd = _run_dir(d, entries_by_sku)
    res = RA.audit(os.path.join(d, 'reg.json'), RA.PASSPORTS, os.path.join(d, 'ci.yml'), d, rd)
    return res


def test_run_structural_ok_and_abstain():
    res = _run_audit({'s1': [_entry()], 's2': [_entry(applied=False, abstain='нет рельефа на заду')]})
    assert not res['problems'], res
    # отказ без причины — ошибка
    res = _run_audit({'s1': [_entry(applied=False)]})
    assert ('R-T-1', RA.C_NOTREACHED, True) in classes(res)
    res = _run_audit({'s1': [_entry(applied=False, abstain='  ')]})
    assert ('R-T-1', RA.C_NOTREACHED, True) in classes(res)


def test_run_digest_mismatch_and_wrong_rule_id():
    res = _run_audit({'s1': [_entry(digest='0' * 64)]})
    assert ('R-T-1', RA.C_NOTREACHED, True) in classes(res) and any('digest' in p['why'] for p in res['problems'])
    res = _run_audit({'s1': [_entry(rule_id='R-OTHER-1')]})                       # записи чужого правила — у нашего пустой охват
    assert any('пустой охват' in p['why'] for p in res['problems'])


def test_run_empty_coverage_is_error():
    d = world([rule(**dict(GOOD, check_field='09-check.rules'))])
    rd = os.path.join(d, 'run')
    os.makedirs(rd)
    res = RA.audit(os.path.join(d, 'reg.json'), RA.PASSPORTS, os.path.join(d, 'ci.yml'), d, rd)             # нет ни одного check.json
    assert any('пустой охват' in p['why'] and p['error'] for p in res['problems']), res
    res = _run_audit({'s1': []})                                                   # check.json есть, записей правила нет
    assert any('пустой охват' in p['why'] and p['error'] for p in res['problems']), res


def test_run_every_applicable_type_present_in_run_must_be_covered():
    # в прогоне встретились два типа корпусного семейства (другое правило записало «шкаф»), у нашего правила записи только по «комоду» → ошибка
    other = _entry('шкаф', rule_id='R-OTHER-1')
    res = _run_audit({'s1': [_entry(), other]}, rule_kw={'applies': {'families': ['корпусное']}})
    assert any('без записи правила' in p['why'] and 'шкаф' in p['why'] for p in res['problems']), res
    res = _run_audit({'s1': [_entry(), _entry('шкаф'), other]}, rule_kw={'applies': {'families': ['корпусное']}})
    assert not res['problems'], res


def test_json_report_and_main_exit_codes():
    d = world([rule(**GOOD), rule(rule_id='R-T-2')])
    out = os.path.join(d, 'o.json')
    base = ['--registry', os.path.join(d, 'reg.json'), '--root', d, '--passports', os.path.join(d, 'pass.json'), '--ci', os.path.join(d, 'ci.yml')]
    assert RA.main(['--check', '--json', out] + base) == 0
    j = json.load(open(out, encoding='utf-8'))
    assert j['rules'] == 2 and j['errors'] == 0 and len(j['registry_sha256']) == 64 and 'code_sha' in j
    assert any(x['rule_id'] == 'R-T-2' for x in j['by_class'][RA.C_NOCODE]), j
    d = world([rule(**dict(GOOD, runtime='observe'))])
    base = ['--registry', os.path.join(d, 'reg.json'), '--root', d, '--passports', os.path.join(d, 'pass.json'), '--ci', os.path.join(d, 'ci.yml')]
    assert RA.main(['--check'] + base) == 1
    assert RA.main(base) == 0


def test_real_registry_is_clean_strict():
    """Боевой реестр: active проверен по поведению (код вызывается, включён, парные тесты в CI, run_id), типы и семейства — из паспорта, у всех типов политика."""
    res = RA.audit()
    text, errs = RA.report(res, strict_types=True)
    assert res['rules'] >= 20 and errs == 0, text
    reg = json.load(open(RA.REGISTRY, encoding='utf-8'))['rules']
    assert len({r['rule_id'] for r in reg}) == len(reg)
    assert all(r['state'] != 'active' or (r['runtime'] == 'enforce' and r['test_positive'] and r['test_negative'] and r['run_id']) for r in reg)


if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
    print('OK: test_rule_registry_audit %d проверок' % n)
