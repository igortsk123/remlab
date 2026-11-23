#!/usr/bin/env python3
"""Тест plan_evidence (T-20261123-48/4): процент пункта плана — из доказательств. Настоящий временный git-репозиторий и заглушка плана; сети нет (версия прода подставляется).
Запуск: python tools/tests/test_plan_evidence.py (стандартная библиотека + git)."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_plan_evidence')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import plan_evidence as PE  # noqa: E402
import rule_record as RR  # noqa: E402
import mesh_type_passports as MP  # noqa: E402


def sh(d, *a):
    p = subprocess.run(['git', '-C', d, '-c', 'user.name=t', '-c', 'user.email=t@x', *a], capture_output=True, text=True)
    assert p.returncode == 0, (a, p.stderr)
    return p.stdout.strip()


def repo():
    """c1 (код) ← c2 (только доки) ← c3 (код) = origin/main; s1 — ветка feat/side, не влита."""
    d = tempfile.mkdtemp(prefix='pe-')
    sh(d, 'init', '-q', '-b', 'main')
    os.makedirs(os.path.join(d, 'tools'))
    os.makedirs(os.path.join(d, '.memory_bank'))
    sh_ = {}
    for name, path, text in (('c1', 'tools/a.py', '1'), ('c2', '.memory_bank/n.md', '2'), ('c3', 'tools/a.py', '3')):
        open(os.path.join(d, path), 'w').write(text)
        sh(d, 'add', '-A')
        sh(d, 'commit', '-q', '-m', name)
        sh_[name] = sh(d, 'rev-parse', 'HEAD')
    sh(d, 'update-ref', 'refs/remotes/origin/main', sh_['c3'])
    sh(d, 'checkout', '-q', '-b', 'feat/side', sh_['c1'])
    open(os.path.join(d, 'tools', 'side.py'), 'w').write('x')
    sh(d, 'add', '-A')
    sh(d, 'commit', '-q', '-m', 's1')
    sh_['s1'] = sh(d, 'rev-parse', 'HEAD')
    sh(d, 'checkout', '-q', 'main')
    return d, sh_


def registry_world(d):
    """Реестр-заглушка с одним правилом + прогон с записями помощника (rule_record)."""
    reg = os.path.join(d, 'reg.json')
    json.dump({'rules': [{'rule_id': 'R-X-1', 'check_field': '06-visible.rules', 'applies': {'types': ['комод']}}]}, open(reg, 'w'))
    run = os.path.join(d, 'run-ok')
    os.makedirs(os.path.join(run, 'a', '06-visible'))
    p = os.path.join(run, 'a', '06-visible', 'check.json')
    json.dump({'passed': True}, open(p, 'w'))
    RR.record_file(p, 'R-X-1', 'комод', True)
    bad = os.path.join(d, 'run-empty-rules')
    os.makedirs(os.path.join(bad, 'a', '06-visible'))
    json.dump({'passed': True}, open(os.path.join(bad, 'a', '06-visible', 'check.json'), 'w'))
    return reg, run, bad


def ctx(d, prod=None):
    reg, _, _ = registry_world(d) if not os.path.exists(os.path.join(d, 'reg.json')) else (os.path.join(d, 'reg.json'), 0, 0)
    return PE.Ctx(d, 'origin/main', prod, reg, PE.RA.PASSPORTS, fetch_prod=False)


def ev(text, c):
    e, bad = PE.parse_ev(text)
    assert not bad, bad
    return PE.evaluate(e, c)


def test_phases_from_evidence():
    d, s = repo()
    run = registry_world(d)[1]
    open(os.path.join(d, 'report.md'), 'w').write('отчёт')
    c = ctx(d, prod=s['c3'])
    assert ev('', c)['phase'] == 0
    assert ev('task=T-20261123-48', c)['phase'] == 10
    assert ev('task=T-1; branch=feat/side', c)['phase'] == 40
    assert ev('wt=tools', c)['phase'] == 40
    assert ev('task=T-1; report=report.md', c)['phase'] == 70
    assert ev('report=%s' % s['s1'][:10], c)['phase'] == 70                       # отчёт = найденный коммит
    assert ev('sha=%s' % s['c1'][:10], c)['phase'] == 90                          # влито, прод = c3 ≥ c1 → CI зелёный
    r = ev('sha=%s; run=%s; rules=R-X-1' % (s['c1'], run), c)
    assert r['phase'] == 95, r
    r = ev('sha=%s; run=%s; rules=R-X-1; live=https://remont-lab.online/demo 23.11' % (s['c1'], run), c)
    assert r['phase'] == 100, r


def test_merged_is_not_pass_and_unmerged_stays_low():
    d, s = repo()
    c = ctx(d, prod=s['c1'])                                                      # прод позади: на проде c1, код c3 не выкачан
    r = ev('sha=%s' % s['c3'], c)
    assert r['phase'] == 80 and any('прод позади' in b for b in r['blockers']), r
    r = ev('sha=%s; live=https://x.example/p 23.11' % s['c3'], c)                 # живая проверка без CI не даёт 100
    assert r['phase'] == 80 and any('влито ≠ принято' in b for b in r['blockers']), r
    r = ev('task=T-1; sha=%s' % s['s1'], ctx(d, prod=s['c3']))                    # ветка не влита → 10, не 80
    assert r['phase'] == 10 and any('влито не всё' in b for b in r['blockers']), r
    r = ev('sha=%s' % ('0' * 12), c)
    assert r['phase'] == 0 and any('не найден' in b for b in r['blockers']), r
    assert ev('sha=%s,%s' % (s['c1'], s['s1']), ctx(d, prod=s['c3']))['phase'] == 0   # один из двух не влит → не 80


def test_ci_docs_only_rule_and_unknown_prod():
    d, s = repo()
    assert ev('sha=%s' % s['c2'], ctx(d, prod=s['c1']))['phase'] == 90            # от кода прода до c2 менялись только доки (deploy-need)
    r = ev('sha=%s' % s['c3'], ctx(d, prod=None))                                 # версия прода не прочитана → CI не подтверждён
    assert r['phase'] == 80 and any('не прочитана' in b for b in r['blockers']), r
    r = ev('sha=%s' % s['c3'], ctx(d, prod='f' * 40))
    assert r['phase'] == 80 and any('не найден локально' in b for b in r['blockers']), r


def test_run_and_rules_structural():
    d, s = repo()
    reg, run, bad = registry_world(d)
    c = ctx(d, prod=s['c3'])
    base = 'sha=%s; ' % s['c1']
    assert ev(base + 'run=%s' % run, c)['phase'] == 95                            # только «папка есть»
    r = ev(base + 'run=%s; rules=R-X-1' % bad, c)                                 # правило в check.json не записано → пустой охват
    assert r['phase'] == 90 and any('пустой охват' in b for b in r['blockers']), r
    r = ev(base + 'run=%s; rules=R-НЕТ' % run, c)
    assert r['phase'] == 90 and any('нет в реестре' in b for b in r['blockers']), r
    r = ev(base + 'run=%s' % os.path.join(d, 'нет-такой'), c)
    assert r['phase'] == 90 and any('не найдена' in b for b in r['blockers']), r
    # digest паспорта поменялся после прогона → не 95
    p = os.path.join(run, 'a', '06-visible', 'check.json')
    j = json.load(open(p))
    j['extra']['rules'][0]['digest'] = '0' * 64
    json.dump(j, open(p, 'w'))
    r = ev(base + 'run=%s; rules=R-X-1' % run, c)
    assert r['phase'] == 90 and any('digest' in b for b in r['blockers']), r


def test_live_needs_link_and_date():
    d, s = repo()
    c = ctx(d, prod=s['c3'])
    for live in ('https://x.example/p', '23.11', 'проверил глазами'):
        r = ev('sha=%s; live=%s' % (s['c1'], live), c)
        assert r['phase'] == 90 and any('ссылка и дата' in b for b in r['blockers']), (live, r)


def plan_text(d, s):
    run = os.path.join(d, 'run-ok')
    summ = os.path.join(d, 'summary.json')
    json.dump({'eval': {'items': 29, 'passed_all': 5, 'passed_all_pct': 17.2}}, open(summ, 'w'))
    return """---
tier: 2
---
<!--
КАК ВЕСТИ. Пример в комментарии — НЕ пункт:
**П9.9 · р.1 · 50 % — не должно читаться** <!-- ev: task=T-1 -->
-->
# План задач · ≈ 54 %
**Конвейер покраски — 59 %** · кругов 5 <!-- ev: paint=@summ@ -->
## П1 · сейчас
**П1.1 · р.1 · 70 % — выдано, но не начато** <!-- T-1 · ev: task=T-20261123-01 -->
**П1.2 · р.2 · 90 % — влито, CI не подтверждён** <!-- ev: sha=@c3@ -->
П1.3 · р.3 · 100 % — всё есть
<!-- ev: sha=@c1@; run=@run@; rules=R-X-1; live=https://remont-lab.online/demo 23.11 -->
**П1.4 · 90 % — без доказательств**
П1.5 · 40 % — без доказательств, ручной невысокий
**П1.6 · р.4 · 55 % — совпадает** <!-- ev: sha=@c1@ -->
<!-- ДЛЯ %
**П1.7 · 90 %** · **П1.8 · 90 %**
-->
""".replace('@summ@', summ).replace('@c1@', s['c1']).replace('@c3@', s['c3']).replace('@run@', run)


def test_parse_plan_skips_hidden_blocks_and_reads_next_line_ev():
    d, s = repo()
    registry_world(d)
    items = PE.parse_plan(plan_text(d, s))
    ids = [i['id'] for i in items]
    assert ids == ['Конвейер покраски', 'П1.1', 'П1.2', 'П1.3', 'П1.4', 'П1.5', 'П1.6'], ids
    by = {i['id']: i for i in items}
    assert by['П1.3']['ev'] and 'live=' in by['П1.3']['ev'] and by['П1.3']['manual'] == 100     # ev в строке под пунктом
    assert by['П1.4']['ev'] is None and by['П1.4']['manual'] == 90 and by['П1.5']['manual'] == 40
    assert by['Конвейер покраски']['manual'] == 59


def test_analyse_counters_divergence_and_paint():
    d, s = repo()
    registry_world(d)
    res = PE.analyse(plan_text(d, s), ctx(d, prod=s['c3']))
    by = {r['id']: r for r in res['rows']}
    assert by['П1.1']['computed'] == 10 and by['П1.1']['diff'] == -60
    assert by['П1.2']['computed'] == 90 and by['П1.2']['diff'] == 0
    assert by['П1.3']['computed'] == 100 and by['П1.6']['computed'] == 90
    assert res['measured'] == 4 and res['unmeasured'] == 2                       # П1.4 и П1.5 — не измерено, в среднее не идут
    assert res['avg'] == round((10 + 90 + 100 + 90) / 4, 1), res['avg']
    assert [r['id'] for r in res['diverged']] == ['П1.1', 'П1.6'] and [r['id'] for r in res['no_ev_high']] == ['П1.4']
    p = by['Конвейер покраски']
    assert p['measured'] and p['paint'] == {'passed': 5, 'measured': 29, 'items': 29, 'pct': 17} and p['steps'] == 59
    out = PE.render(res)
    assert 'прошло 5 признаков 5 из 29 (17 %) · шаги 59 %' in out and '✗ расхождение -60' in out and 'Не измерено: П1.4 П1.5' in out


def test_paint_without_summary_is_not_measured():
    d, s = repo()
    registry_world(d)
    t = '**Конвейер покраски — 59 %** <!-- ev: paint=нет/такого.json -->\n'
    res = PE.analyse(t, ctx(d, prod=s['c3']))
    assert res['rows'][0]['measured'] is False and 'не измерено' in PE.render(res)


def test_write_overwrites_manual_and_is_idempotent():
    d, s = repo()
    registry_world(d)
    c = ctx(d, prod=s['c3'])
    t = plan_text(d, s)
    new, n = PE.write_plan(t, PE.analyse(t, c))
    assert n == 3, n                                                             # П1.1 70→10, П1.3 100 остаётся?, П1.6 55→90, покраска
    assert '**П1.1 · р.1 · 10 % — выдано' in new and '**П1.6 · р.4 · 90 % — совпадает**' in new
    assert '**П1.4 · 90 % — без доказательств**' in new and 'П1.5 · 40 %' in new          # не измерено — не трогаем
    assert '**Конвейер покраски — прошло 5 признаков 5 из 29 · шаги 59 %** · кругов 5' in new
    assert '<!-- T-1 · ev: task=T-20261123-01 -->' in new                        # комментарии не тронуты
    new2, n2 = PE.write_plan(new, PE.analyse(new, c))
    assert n2 == 0 and new2 == new                                               # повтор ничего не меняет
    assert PE.parse_plan(new)[0]['manual'] == 59                                 # строка покраски после записи читается (шаги 59)


def test_infer_is_preview_only():
    d, s = repo()
    registry_world(d)
    t = '**П1.9 · р.1 · 80 %% — влито %s, ветка feat/side, T-20261123-77**\n' % s['c1'][:10]
    c = ctx(d, prod=s['c3'])
    res = PE.analyse(t, c, infer=True)
    r = res['rows'][0]
    assert r['inferred'] and r['computed'] == 90, r
    assert PE.analyse(t, c)['rows'][0]['measured'] is False                       # без --infer — «не измерено»
    new, n = PE.write_plan(t, res)
    assert n == 0 and new == t                                                   # предпросмотр в файл не пишется


def test_main_modes_and_exit_codes():
    d, s = repo()
    registry_world(d)
    plan = os.path.join(d, 'plan.md')
    open(plan, 'w', encoding='utf-8').write(plan_text(d, s))
    base = ['--plan', plan, '--root', d, '--prod-sha', s['c3'], '--registry', os.path.join(d, 'reg.json')]
    before = open(plan, encoding='utf-8').read()
    assert PE.main(base + ['--dry']) == 0 and open(plan, encoding='utf-8').read() == before   # --dry не пишет
    assert PE.main(base + ['--check']) == 1                                      # ручной 90 без ev, расхождения
    assert PE.main(base + ['--write']) == 0 and open(plan, encoding='utf-8').read() != before
    assert PE.main(base + ['--check']) == 1                                      # П1.4 («90 без ev») остался
    out = os.path.join(d, 'o.json')
    assert PE.main(base + ['--json', out]) == 0 and json.load(open(out))['measured'] == 4
    try:
        PE.main(base + ['--infer', '--write'])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError('--infer --write должен быть запрещён')


if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
    print('OK: test_plan_evidence %d проверок' % n)
