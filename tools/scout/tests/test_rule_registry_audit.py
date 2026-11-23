#!/usr/bin/env python3
"""Тест автосверки реестра правил (T-20261123-48): CI падает на active без кода/теста; классы вывода; боевой реестр чист.
Запуск: python tools/scout/tests/test_rule_registry_audit.py (стандартная библиотека)."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rule_registry_audit')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import rule_registry_audit as RA  # noqa: E402


def rule(**kw):
    r = {'rule_id': 'R-T-1', 'title': 't', 'state': 'proposed', 'source': ['TG 1'], 'applies': {'types': ['all']}, 'executor': 'x',
         'consumer': None, 'runtime': 'none', 'test': None, 'check_field': None, 'enabled': None}
    r.update(kw)
    return r


def world(rules, ci='run: python tests/t.py', code='def consumer_fn():\n    pass\n', test='def test_x():\n    pass\n', passports=None):
    d = tempfile.mkdtemp(prefix='ra-')
    os.makedirs(os.path.join(d, 'tools'))
    for name, text in (('tools/code.py', code), ('tests/t.py', test)):
        os.makedirs(os.path.dirname(os.path.join(d, name)), exist_ok=True)
        open(os.path.join(d, name), 'w').write(text)
    json.dump({'rules': rules}, open(os.path.join(d, 'reg.json'), 'w'), ensure_ascii=False)
    json.dump({'types': passports if passports is not None else {'комод': {'family': 'корпусное', 'paint': {'hidden_pattern': 'body'}}}},
              open(os.path.join(d, 'pass.json'), 'w'), ensure_ascii=False)
    open(os.path.join(d, 'ci.yml'), 'w').write(ci)
    return d


def run(rules, **kw):
    d = world(rules, **kw)
    res = RA.audit(os.path.join(d, 'reg.json'), os.path.join(d, 'pass.json'), os.path.join(d, 'ci.yml'), d)
    text, errs = RA.report(res)
    return res, text, errs


def classes(res):
    return {(p['rule_id'], p['cls'], p['error']) for p in res['problems']}


def test_good_active_is_clean():
    res, text, errs = run([rule(state='active', consumer='tools/code.py:consumer_fn', runtime='enforce', test='tests/t.py::test_x')])
    assert errs == 0 and not res['problems'], (errs, text)


def test_active_without_code_fails():
    res, text, errs = run([rule(state='active', runtime='none', test='tests/t.py')])
    assert errs >= 1 and ('R-T-1', RA.C_NOCODE, True) in classes(res), text


def test_active_without_test_fails():
    res, _, errs = run([rule(state='active', consumer='tools/code.py:consumer_fn', runtime='enforce')])
    assert errs >= 1 and ('R-T-1', RA.C_NOTEST, True) in classes(res)


def test_active_test_not_in_ci_fails():
    res, _, errs = run([rule(state='active', consumer='tools/code.py:consumer_fn', runtime='enforce', test='tests/t.py')], ci='run: echo нет')
    assert errs >= 1 and ('R-T-1', RA.C_NOTEST, True) in classes(res)


def test_active_observe_fails_but_trial_observe_is_class_only():
    res, _, errs = run([rule(state='active', consumer='tools/code.py:consumer_fn', runtime='observe', test='tests/t.py')])
    assert errs >= 1 and ('R-T-1', RA.C_OBSERVE, True) in classes(res)
    res, text, errs = run([rule(state='trial', consumer='tools/code.py:consumer_fn', runtime='observe', test='tests/t.py')])
    assert errs == 0 and ('R-T-1', RA.C_OBSERVE, False) in classes(res), text


def test_proposed_without_code_is_class_not_error():
    res, text, errs = run([rule()])
    assert errs == 0 and ('R-T-1', RA.C_NOCODE, False) in classes(res), text


def test_broken_reference_is_error_even_for_proposed():
    res, _, errs = run([rule(consumer='tools/нет.py:f', runtime='observe')])
    assert errs >= 1 and ('R-T-1', RA.C_BROKEN, True) in classes(res)
    res, _, errs = run([rule(consumer='tools/code.py:нет_такой', runtime='observe')])
    assert errs >= 1
    res, _, errs = run([rule(test='tests/t.py::test_нет')])
    assert errs >= 1


def test_schema_errors():
    res, _, errs = run([rule(), rule()])                                         # дубль id
    assert any(p['why'] == 'rule_id повторяется' for p in res['problems']) and errs >= 1
    res, _, errs = run([rule(rule_id='bad id')])
    assert errs >= 1
    res, _, errs = run([rule(state='включено')])
    assert errs >= 1
    res, _, errs = run([rule(applies={'types': ['нет-такого-типа']})])
    assert errs >= 1
    res, _, errs = run([rule(applies={'families': ['нет-такого-семейства']})])
    assert errs >= 1
    r = rule()
    del r['consumer']
    res, _, errs = run([r])
    assert errs >= 1


def test_retired_skips_code_checks():
    res, _, errs = run([rule(state='retired', consumer='tools/нет.py:f')])
    assert errs == 0, res


def test_types_without_policy_is_class_and_strict_switch():
    res, text, errs = run([rule()], passports={'комод': {'family': 'корпусное', 'paint': {}}})
    assert errs == 0 and any(p['cls'] == RA.C_NOPOLICY for p in res['problems'])
    _, errs = RA.report(res, strict_types=True)
    assert errs >= 1


def test_run_dir_not_reached():
    d = world([rule(state='active', consumer='tools/code.py:consumer_fn', runtime='enforce', test='tests/t.py', check_field='09-check.winding')])
    run_dir = os.path.join(d, 'run')
    os.makedirs(os.path.join(run_dir, 'sku1', '09-check'))
    open(os.path.join(run_dir, 'sku1', '09-check', 'check.json'), 'w').write('{"x": 1}')
    res = RA.audit(os.path.join(d, 'reg.json'), os.path.join(d, 'pass.json'), os.path.join(d, 'ci.yml'), d, run_dir)
    assert ('R-T-1', RA.C_NOTREACHED, False) in classes(res), res
    open(os.path.join(run_dir, 'sku1', '09-check', 'check.json'), 'w').write('{"winding": 1}')
    res = RA.audit(os.path.join(d, 'reg.json'), os.path.join(d, 'pass.json'), os.path.join(d, 'ci.yml'), d, run_dir)
    assert not res['problems'], res


def test_main_exit_codes():
    d = world([rule(state='active')])
    assert RA.main(['--check', '--registry', os.path.join(d, 'reg.json')]) == 1
    d = world([rule()])
    assert RA.main(['--registry', os.path.join(d, 'reg.json')]) == 0


def test_real_registry_is_clean():
    """Боевой реестр: ни одного active без кода/теста/CI, ссылки живые, типы и семейства — из паспорта."""
    res = RA.audit()
    text, errs = RA.report(res)
    assert res['rules'] >= 20 and errs == 0, text
    ids = [p for p in json.load(open(RA.REGISTRY, encoding='utf-8'))['rules']]
    assert len({r['rule_id'] for r in ids}) == len(ids)
    assert all(r['state'] != 'active' or r['runtime'] == 'enforce' for r in ids)


if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
    print('OK: test_rule_registry_audit %d проверок' % n)
