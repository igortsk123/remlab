#!/usr/bin/env python3
"""Тест сторожа выключателей правил (T-20261127-173, задача 2): каждый выключатель в файлах правил — в реестре или в списке «обычных настроек»; счётчик вне обоих только убывает.
Запуск: python tools/scout/tests/test_rule_switch_guard.py (стандартная библиотека)."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rule_switch_guard')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))
import rule_switch_guard as SG  # noqa: E402

RULES = 'tools/scout/rules/'
FILE_A = {'_about': 'комментарий с true внутри не считается', 'enabled': False, 'nested': {'on': True, 'limit': 5, 'name': 'x'}, 'mode': 'dry',
          'list': [{'enabled': True}], '_skip': {'enabled': True}}
A_SWITCHES = ['tools/scout/rules/a.json#enabled', 'tools/scout/rules/a.json#nested.on', 'tools/scout/rules/a.json#mode']


def world(files=None, registry=None, settings=None, threshold=None):
    """Мини-репозиторий: rules/a.json (+ другие), реестр, настройки сторожа, порог."""
    d = tempfile.mkdtemp(prefix='rsg-')
    os.makedirs(os.path.join(d, RULES), exist_ok=True)
    files = {'a.json': FILE_A} if files is None else files
    for name, body in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, RULES, name)), exist_ok=True)
        json.dump(body, open(os.path.join(d, RULES, name), 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(registry if registry is not None else {'rules': [], 'groups': {}}, open(os.path.join(d, RULES, 'rule-registry.json'), 'w'), ensure_ascii=False)
    json.dump(settings if settings is not None else {'scan': [RULES + 'a.json'], 'skip_files': {}, 'settings': {}},
              open(os.path.join(d, RULES, 'switch-settings.json'), 'w'), ensure_ascii=False)
    if threshold is not False:
        json.dump(threshold if threshold is not None else {'max_uncovered': 0, 'known': []}, open(os.path.join(d, RULES, 'switch-guard-threshold.json'), 'w'), ensure_ascii=False)
    return d


def run(d):
    return SG.guard(d, os.path.join(d, RULES, 'rule-registry.json'), os.path.join(d, RULES, 'switch-settings.json'), os.path.join(d, RULES, 'switch-guard-threshold.json'))


def cli(d, *args):
    return SG.main(list(args) + ['--root', d])


def thr(n, known):
    return {'max_uncovered': n, 'known': known}


def test_switch_detection_bool_and_mode_but_not_comments_lists_numbers():
    res = run(world(threshold=thr(3, A_SWITCHES)))
    assert res['switches'] == 3 and sorted(u['name'] for u in res['uncovered']) == sorted(A_SWITCHES) and not res['errors'], res


def test_new_switch_without_record_is_error():
    d = world()                                               # порог 0, known пуст, три выключателя нигде не записаны
    res = run(d)
    assert len(res['errors']) == 4 and sum('НОВЫЙ выключатель' in e for e in res['errors']) == 3 and any('> порога' in e for e in res['errors']), res
    assert cli(d, '--check') == 1 and cli(d) == 0


def test_switch_in_registry_is_ok_flag_block_and_group_flags():
    reg = {'rules': [{'rule_id': 'R-A-1', 'flag': 'tools/scout/rules/a.json#enabled'},
                     {'rule_id': 'R-A-2', 'flag': None, 'flags': ['tools/scout/rules/a.json#nested']}],      # блок-родитель охватывает nested.on
           'groups': {'G1': {'flags': ['tools/scout/rules/a.json#mode']}}}
    res = run(world(registry=reg))
    assert not res['errors'] and not res['uncovered'] and res['in_registry'] == 3, res
    assert cli(world(registry=reg), '--check') == 0
    reg2 = {'rules': [{'rule_id': 'R-A-1', 'flag': 'tools/scout/rules/a.json#enable'}], 'groups': {}}          # похожее имя — не родитель
    res = run(world(registry=reg2, threshold=thr(3, A_SWITCHES)))
    assert len(res['uncovered']) == 3, res


def test_switch_in_settings_is_ok_reason_required():
    st = {'scan': [RULES + 'a.json'], 'skip_files': {}, 'settings': {'tools/scout/rules/a.json#*': 'все три — просто настройки пробы'}}
    res = run(world(settings=st))
    assert not res['errors'] and res['in_settings'] == 3 and not res['uncovered'], res
    st['settings'] = {'tools/scout/rules/a.json#*': ' '}
    res = run(world(settings=st, threshold=thr(3, A_SWITCHES)))
    assert any('нет причины' in e for e in res['errors']) and len(res['uncovered']) == 3, res


def test_count_below_threshold_is_ok_with_hint_and_lower_only_down():
    d = world(threshold=thr(5, A_SWITCHES + ['tools/scout/rules/gone.json#x', 'tools/scout/rules/gone.json#y']))
    res = run(d)
    assert not res['errors'] and len(res['uncovered']) == 3 and any('опусти порог' in h for h in res['hints']) and any('known' in h for h in res['hints']), res
    assert cli(d, '--check') == 0
    assert cli(d, '--lower') == 0
    t = json.load(open(os.path.join(d, RULES, 'switch-guard-threshold.json'), encoding='utf-8'))
    assert t['max_uncovered'] == 3 and t['known'] == sorted(A_SWITCHES), t
    assert not run(d)['hints']
    # поднять командой нельзя: --init не перезаписывает, --lower при ошибках порог не трогает
    assert 'не перезаписывает' in SG.init_threshold({'uncovered': []}, os.path.join(d, RULES, 'switch-guard-threshold.json'))
    d2 = world(threshold=thr(1, A_SWITCHES[:1]))
    assert cli(d2, '--lower') == 0
    assert json.load(open(os.path.join(d2, RULES, 'switch-guard-threshold.json'), encoding='utf-8'))['max_uncovered'] == 1


def test_count_over_threshold_is_error_even_if_names_known():
    res = run(world(threshold=thr(2, A_SWITCHES)))
    assert any('3 > порога 2' in e for e in res['errors']) and not any('НОВЫЙ' in e for e in res['errors']), res


def test_swap_one_for_another_is_still_error():
    """Один выключатель убрали, другой добавили: число то же, но имя не из known — ошибка (счётчика мало)."""
    d = world(threshold=thr(3, A_SWITCHES[:2] + ['tools/scout/rules/old.json#x']))
    res = run(d)
    assert len(res['errors']) == 1 and 'НОВЫЙ' in res['errors'][0] and 'a.json#mode' in res['errors'][0], res


def test_unclassified_rule_file_is_error_skip_needs_reason():
    files = {'a.json': FILE_A, 'new-rule.json': {'enabled': True}}
    res = run(world(files=files, threshold=thr(3, A_SWITCHES)))
    assert res['unclassified'] == ['tools/scout/rules/new-rule.json'] and any('не отнесён' in e for e in res['errors']), res
    st = {'scan': [RULES + 'a.json'], 'skip_files': {RULES + 'new-*.json': 'каталог, не конвейер'}, 'settings': {}}
    res = run(world(files=files, settings=st, threshold=thr(3, A_SWITCHES)))
    assert not res['errors'] and not res['unclassified'], res
    st['skip_files'] = {RULES + 'new-*.json': ''}
    res = run(world(files=files, settings=st, threshold=thr(3, A_SWITCHES)))
    assert any('нет причины' in e for e in res['errors']), res
    st = {'scan': [RULES + 'a.json', RULES + 'new-rule.json'], 'skip_files': {}, 'settings': {}}      # новый файл в области: его выключатель — новый и требует записи
    res = run(world(files=files, settings=st, threshold=thr(3, A_SWITCHES)))
    assert any('new-rule.json#enabled' in e for e in res['errors']), res


def test_no_threshold_or_settings_file_is_error():
    d = world(threshold=False)
    assert any('нет порога' in e for e in run(d)['errors']) and cli(d, '--check') == 1
    assert cli(d, '--init') == 0 and json.load(open(os.path.join(d, RULES, 'switch-guard-threshold.json')))['max_uncovered'] == 3
    d = world()
    os.remove(os.path.join(d, RULES, 'switch-settings.json'))
    assert any('нет файла настроек' in e for e in run(d)['errors'])


def test_registry_name_missing_in_file_is_error():
    """T-175/В-реестр ❓3: реестр называет выключатель, которого в файле правил нет (удалили/опечатка) — сторож говорит, код ≠0 и причина в строке."""
    ok = {'rules': [{'rule_id': 'R-A-1', 'flag': 'tools/scout/rules/a.json#enabled', 'flags': ['tools/scout/rules/a.json#nested.on', 'tools/scout/rules/a.json#mode']}], 'groups': {}}
    d = world(registry=ok)
    assert not [e for e in run(d)['errors'] if 'которого нет' in e] and cli(d, '--check') == 0       # целое — молчит
    cases = {'a.json#enabledX': 'нет ключа', 'a.json#nested.off': 'нет ключа', 'gone.json#enabled': 'gone.json нет', 'a.json': 'нет «#»'}
    for name, why in cases.items():
        reg = {'rules': [{'rule_id': 'R-A-1', 'flag': None, 'flags': ['tools/scout/rules/' + name]}], 'groups': {}}
        d = world(registry=reg, threshold=thr(3, A_SWITCHES))
        errs = [e for e in run(d)['errors'] if 'которого нет' in e]
        assert len(errs) == 1 and why in errs[0] and name in errs[0], (name, errs)
        assert cli(d, '--check') == 1, name
    reg = {'rules': [], 'groups': {'G1': {'flags': ['tools/scout/rules/a.json#nested.gone']}}}              # и в flags группы
    assert any('которого нет' in e for e in run(world(registry=reg, threshold=thr(3, A_SWITCHES)))['errors'])
    d = world(files={'a.json': FILE_A, 'b.json': {'x': {'k.dot': True}}}, registry={'rules': [{'rule_id': 'R-B-1', 'flag': 'tools/scout/rules/b.json#x.k.dot'}], 'groups': {}},
              settings={'scan': [RULES + 'a.json'], 'skip_files': {RULES + 'b.json': 'тест'}, 'settings': {}}, threshold=thr(3, A_SWITCHES))
    assert not [e for e in run(d)['errors'] if 'которого нет' in e], run(d)['errors']                          # ключ с точкой внутри имени находится
    broken = os.path.join(d, RULES, 'b.json')
    open(broken, 'w').write('{not json')
    assert any('не читается как JSON' in e for e in run(d)['errors']) and cli(d, '--check') == 1


def test_registry_unreadable_is_error_not_silence():
    """Реестр пропал/сломан — не «0 находок», а ошибка с причиной."""
    d = world(threshold=thr(3, A_SWITCHES))
    os.remove(os.path.join(d, RULES, 'rule-registry.json'))
    errs = run(d)['errors']
    assert any('реестр' in e and 'не читается' in e for e in errs) and cli(d, '--check') == 1, errs
    open(os.path.join(d, RULES, 'rule-registry.json'), 'w').write('{нет')
    assert any('реестр' in e and 'не читается' in e for e in run(d)['errors'])


def test_real_repo_is_clean_and_threshold_matches():
    """Боевой репозиторий: все файлы правил отнесены; новых выключателей вне реестра и списка нет; число не выше порога."""
    res = SG.guard()
    assert not res['errors'], SG.report(res)
    assert res['switches'] >= 100 and res['in_registry'] >= 20 and len(res['uncovered']) <= res['max'], SG.report(res)
    assert SG.main(['--check']) == 0


if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
    print('OK: test_rule_switch_guard %d проверок' % n)
