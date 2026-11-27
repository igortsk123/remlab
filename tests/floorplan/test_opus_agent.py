"""T-20261127-176: Opus-агент по подписке (tools/floorplan/opus_agent.py). Без сети и без подписки: вместо `claude` — поддельная программа (FAKE_MODE).
Каждая проверка с отрицательным контролем «сломано → говорит»: код ≠ 0 / отказ со строкой причины / STOP-файл, а не молчание."""
import base64
import hashlib
import json
import os
import stat
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'floorplan'))
import opus_agent as AG  # noqa: E402

FAKE = '''#!%s
import base64, hashlib, json, os, sys
a = sys.argv[1:]
if '--version' in a:
    print('2.1.332 (Claude Code)'); sys.exit(0)
with open(os.environ['FAKE_DIR'] + '/count', 'a') as f:
    f.write('x\\n')
msg = json.loads(sys.stdin.readline())
cont = msg['message']['content']
img = [c for c in cont if c['type'] == 'image']
with open(os.environ['FAKE_DIR'] + '/seen.json', 'w') as f:
    json.dump({'argv': a, 'env': sorted(os.environ), 'cwd': os.getcwd(), 'text_sha': hashlib.sha256(cont[0]['text'].encode()).hexdigest(),
               'img_sha': hashlib.sha256(base64.b64decode(img[0]['source']['data'])).hexdigest() if img else None}, f)
mode = os.environ.get('FAKE_MODE', 'ok')
if mode == 'stderr-limit':
    sys.stderr.write('Claude AI usage limit reached|1796295600'); sys.exit(1)
if mode == 'crash':
    sys.stderr.write('boom'); sys.exit(7)
over = int(os.environ.get('FAKE_OVERHEAD', '574'))
print(json.dumps({'type': 'system', 'subtype': 'init', 'apiKeySource': os.environ.get('FAKE_SRC', 'none'), 'model': 'claude-opus-5-5', 'tools': []}))
st = 'allowed' if mode != 'limit-event' else 'rejected'
print(json.dumps({'type': 'rate_limit_event', 'rate_limit_info': {'status': st, 'resetsAt': 1796295600, 'rateLimitType': 'five_hour'}}))
res = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '```json\\n{"version": 1}\\n```', 'stop_reason': 'end_turn', 'total_cost_usd': 0.17,
       'usage': {'input_tokens': 2, 'cache_creation_input_tokens': (over if not img else 5201), 'cache_read_input_tokens': 0, 'output_tokens': 123, 'output_tokens_details': {'thinking_tokens': 2100}}}
if mode == 'empty':
    res['result'] = '  '
if mode == 'refusal':
    res.update(stop_reason='refusal', result='I cannot help with that')
if mode == 'length':
    res.update(stop_reason='max_tokens')
if mode == 'limit-text':
    res.update(is_error=True, result='You have hit your usage limit. It will reset at 5pm')
print(json.dumps(res))
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    fdir = tmp_path / 'fake'
    fdir.mkdir()
    prog = fdir / 'claude'
    prog.write_text(FAKE % sys.executable)
    prog.chmod(prog.stat().st_mode | stat.S_IEXEC)
    lim = fdir / 'limit'
    lim.write_text('#!/bin/sh\ncat %s/limit.txt\n' % fdir)
    lim.chmod(lim.stat().st_mode | stat.S_IEXEC)
    (fdir / 'limit.txt').write_text('0 0 39 4102444800\n')
    out = tmp_path / 'out'
    (out / 'vetka-a').mkdir(parents=True)
    monkeypatch.setenv('FAKE_DIR', str(fdir))
    for k in ('FAKE_MODE', 'FAKE_SRC', 'FAKE_OVERHEAD'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(AG, 'CLAUDE', str(prog))
    monkeypatch.setattr(AG, 'LIMIT_CMD', str(lim))
    monkeypatch.setattr(AG, 'CWD', str(tmp_path / 'cwd-empty'))
    monkeypatch.setattr(AG, 'A', str(out / 'vetka-a'))
    monkeypatch.setattr(AG, 'OUT', str(out))
    monkeypatch.setitem(AG.STATE, 'fails', 0)
    monkeypatch.setitem(AG.STATE, 'version', '2.1.332')
    (tmp_path / 'cwd-empty').mkdir()

    class E:
        pass
    e = E()
    e.fdir, e.out, e.tmp, e.mp = fdir, out, tmp_path, monkeypatch
    e.count = lambda: len((fdir / 'count').read_text().split()) if (fdir / 'count').exists() else 0
    e.rows = lambda: [json.loads(x) for x in (out / 'vetka-a' / 'calls.jsonl').read_text().splitlines()]
    e.seen = lambda: json.loads((fdir / 'seen.json').read_text())
    e.limit = lambda s: (fdir / 'limit.txt').write_text(s + '\n')
    return e


PROMPT = 'PROMPT TEXT\n\nFrom the listing: "комнат 2; общая 54,8 м²"'
IMG = b'\xff\xd8\xff\xe0fake-jpeg-bytes' * 50


def test_one_ok_writes_answer_and_journal(env):
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is True
    assert (env.out / 'vetka-a/raw/opus/kazan-1__b.txt').read_text() == '```json\n{"version": 1}\n```'
    r = env.rows()
    assert len(r) == 1 and env.count() == 1                      # строк в журнале = вызовов
    r = r[0]
    assert r['ok'] and r['usd'] == 0.0 and r['usd_list'] == 0.17 and r['вход'] == 'подписка' and r['tokens_out'] == 123 and r['called'] is True
    assert r['text_sha256'] == hashlib.sha256(PROMPT.encode()).hexdigest() and r['img_sha256'] == hashlib.sha256(IMG).hexdigest()


def test_input_is_byte_identical_and_env_clean(env):
    env.mp.setenv('ANTHROPIC_API_KEY', 'x')
    env.mp.setenv('AI_GATEWAY_API_KEY', 'x')
    env.mp.setenv('OPENAI_API_KEY', 'x')
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG)
    s = env.seen()
    assert s['text_sha'] == hashlib.sha256(PROMPT.encode()).hexdigest() and s['img_sha'] == hashlib.sha256(IMG).hexdigest()   # текст и картинка дошли без изменений
    assert not [k for k in s['env'] if AG.KEY_RX.search(k) and k != 'CLAUDE_CODE_MAX_OUTPUT_TOKENS']                  # ни одного ключа в окружении запуска
    assert s['cwd'] == str(env.tmp / 'cwd-empty')
    a = s['argv']
    assert '--bare' not in a and '--tools' in a and a[a.index('--tools') + 1] == '' and a[a.index('--setting-sources') + 1] == ''
    assert '--strict-mcp-config' in a and '--no-session-persistence' in a and a[a.index('--model') + 1] == 'claude-opus-5-5' and '--system-prompt' in a


def test_clean_env_reports_removed_names():
    e, removed = AG.clean_env({'PATH': '/bin', 'ANTHROPIC_API_KEY': 'a', 'MY_GATEWAY_URL': 'b', 'HOME': '/h'})
    assert removed == ['ANTHROPIC_API_KEY', 'MY_GATEWAY_URL'] and 'ANTHROPIC_API_KEY' not in e and e['HOME'] == '/h'


def test_program_missing_says_so(env):
    env.mp.setattr(AG, 'CLAUDE', str(env.tmp / 'net-takoy-programmy'))
    with pytest.raises(AG.AgentStop, match='не найдена'):
        AG.preflight(str(env.out))
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is False
    r = env.rows()[0]
    assert 'не найдена' in r['error'] and r['stop'] and r['ok'] is False and env.count() == 0


def test_empty_answer_is_refusal_without_retry(env):
    env.mp.setenv('FAKE_MODE', 'empty')
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is False
    assert env.rows()[0]['error'] == 'пустой ответ' and env.count() == 1
    assert not (env.out / 'vetka-a/raw/opus/kazan-1__b.txt').exists()


@pytest.mark.parametrize('mode,text', [('refusal', 'модель отказалась'), ('length', 'обрыв по длине')])
def test_model_refusal_and_length_no_retry(env, mode, text):
    env.mp.setenv('FAKE_MODE', mode)
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is False
    assert text in env.rows()[0]['error'] and env.count() == 1


def test_crash_retried_once_then_refusal(env):
    env.mp.setenv('FAKE_MODE', 'crash')
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is False
    r = env.rows()[0]
    assert env.count() == 2 and r['attempts'] == 2 and 'сбой программы rc=7' in r['error']


@pytest.mark.parametrize('mode', ['limit-event', 'limit-text', 'stderr-limit'])
def test_limit_stops_whole_batch(env, mode):
    env.mp.setenv('FAKE_MODE', mode)
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is False
    assert env.count() == 1                                      # повторов нет
    assert (env.out / 'STOP').read_text().strip()
    err = env.rows()[0]['error'].lower()
    assert 'лимит' in err or 'limit' in err
    env.mp.delenv('FAKE_MODE')
    assert AG.one('kazan-2__b', 'opus', PROMPT, IMG) is False    # со STOP-файлом листы не читаются
    assert env.count() == 1 and 'STOP' in env.rows()[1]['error']


def test_three_failures_in_a_row_stop_batch(env):
    env.mp.setenv('FAKE_MODE', 'empty')
    for i in range(3):
        assert AG.one('kazan-%d__b' % i, 'opus', PROMPT, IMG) is False
    assert (env.out / 'STOP').exists() and '3 отказа подряд' in (env.out / 'STOP').read_text()
    assert '3 отказа подряд' in env.rows()[2]['error']


def test_success_resets_failure_streak(env):
    env.mp.setenv('FAKE_MODE', 'empty')
    for i in range(2):
        AG.one('kazan-%d__b' % i, 'opus', PROMPT, IMG)
    env.mp.setenv('FAKE_MODE', 'ok')
    assert AG.one('kazan-9__b', 'opus', PROMPT, IMG)
    env.mp.setenv('FAKE_MODE', 'empty')
    AG.one('kazan-10__b', 'opus', PROMPT, IMG)
    assert not (env.out / 'STOP').exists()


def test_week_limit_stops_without_call(env):
    env.limit('10 4102444800 61 4102444800')
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is False
    assert env.count() == 0 and 'неделя 61' in (env.out / 'STOP').read_text()


def test_five_hour_pause_then_goes(env):
    reset = int(time.time()) + 3600
    env.limit('75 %d 20 4102444800' % reset)
    slept = []

    def fake_sleep(s):
        slept.append(s)
        env.limit('0 0 20 4102444800')                           # окно сбросилось
    env.mp.setattr(AG, 'sleep', fake_sleep)
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is True
    assert slept and slept[0] > 0 and '5 часов 75' in env.rows()[0]['pauses'][0]


def test_limit_counter_missing_or_garbage_says_so(env):
    env.mp.setattr(AG, 'LIMIT_CMD', str(env.tmp / 'net-schetchika'))
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG) is False
    assert 'нет счётчика лимита' in env.rows()[0]['error'] and env.count() == 0
    env.mp.setattr(AG, 'LIMIT_CMD', str(env.fdir / 'limit'))
    env.limit('мусор')
    assert AG.one('kazan-2__b', 'opus', PROMPT, IMG) is False
    assert 'ответил не' in env.rows()[1]['error'] and env.count() == 0


def test_preflight_ok_writes_report(env):
    p = AG.preflight(str(env.out))
    assert p['вход'] == 'подписка' and p['накладные входные токены'] == 576 and p['версия'].startswith('2.1.332')
    assert json.loads((env.out / 'agent-preflight.json').read_text())['apiKeySource'] == 'none'


def test_preflight_overhead_leak_refuses(env):
    env.mp.setenv('FAKE_OVERHEAD', '4200')
    with pytest.raises(AG.AgentStop, match='накладные входные токены 4202'):
        AG.preflight(str(env.out))


def test_preflight_paid_key_refuses(env):
    env.mp.setenv('FAKE_SRC', 'ANTHROPIC_API_KEY')
    with pytest.raises(AG.AgentStop, match='НЕ по подписке'):
        AG.preflight(str(env.out))


def test_preflight_control_call_failure_refuses(env):
    env.mp.setenv('FAKE_MODE', 'crash')
    with pytest.raises(AG.AgentStop, match='контрольный вызов не удался'):
        AG.preflight(str(env.out))


def test_no_addendum_refused_without_call(env):
    assert AG.refuse_no_addendum('kazan-1__b', 'opus') is False
    r = env.rows()[0]
    assert r['error'] == AG.NO_ADDENDUM and r['called'] is False and env.count() == 0
    env.mp.setenv('FAKE_MODE', 'empty')                          # отказ без вызова в «три подряд» не входит
    for i in range(2):
        AG.refuse_no_addendum('kazan-%d__b' % i, 'opus')
    assert AG.STATE['fails'] == 0


def test_has_addendum_cases(tmp_path):
    def mk(sid, d):
        (tmp_path / sid).mkdir()
        (tmp_path / sid / 'listing.json').write_text(json.dumps(d))
    mk('a', {'obyavlenie': {'dlya_llm': 'комнат 1; общая 34,6 м²'}})
    mk('b', {})
    mk('c', {'obyavlenie': {'dlya_llm': ''}})
    mk('d', {'obyavlenie': {'dlya_llm': None}})
    mk('e', {'obyavlenie': {'dlya_llm': '   '}})
    assert AG.has_addendum(str(tmp_path), 'a') is True
    assert [AG.has_addendum(str(tmp_path), s) for s in 'bcde'] == [False] * 4
    assert AG.has_addendum(str(tmp_path), 'нет-такого') is False  # нет listing.json


def test_jobs_for_reader():
    jobs = (('opus', 'b'), ('gpt', 'd'))
    assert AG.jobs_for('paid', jobs) == jobs                     # платный — без изменений
    assert AG.jobs_for('agent', jobs) == (('opus', 'b'),)        # агент: GPT не зовём


def test_attach_replaces_paid_reader(env):
    class R:
        A = str(env.out / 'vetka-a')
        one = None
    AG.attach(R, str(env.out))
    assert R.one is AG.one and R.spent_total() == 0.0


def test_gate_thresholds():
    now = 1000
    assert AG.gate((69, 2000, 59, 2000), now)[0] == 'ok'
    assert AG.gate((70, 2000, 10, 2000), now)[0] == 'pause'
    assert AG.gate((10, 2000, 60, 2000), now)[0] == 'stop'
    assert AG.gate((90, 900, 10, 900), now)[0] == 'ok'            # окно уже сброшено — старый процент не считаем


def test_parse_stream_ignores_garbage():
    p = AG.parse_stream('мусор\n{"type":"result","result":"x"}\n[1]\n')
    assert p['result']['result'] == 'x' and p['init'] is None
    assert AG.parse_stream('')['result'] is None


# ---- правка 27.11 (после 15:50): усилие параметром, ключи запуска, счёт исходов, подписи labels5 при агенте, входные картинки b и d ----
def test_launch_keys_rule_build_cmd():
    """ПРАВИЛО (директор/Fable 27.11): без этих ключей каждый claude -p поднимает Telegram-плагин и выбивает канал владельца. Убрали любой — красный."""
    cmd = AG.build_cmd('claude')
    assert cmd[cmd.index('--setting-sources') + 1] == ''
    assert '--strict-mcp-config' in cmd
    assert cmd[cmd.index('--tools') + 1] == ''
    assert '--bare' not in cmd and '--no-session-persistence' in cmd


def test_telegram_state_dir_and_keys_not_in_launch_env(env):
    env.mp.setenv('TELEGRAM_STATE_DIR', '/x')
    env.mp.setenv('ANTHROPIC_API_KEY', 'k')
    assert AG.one('kazan-1__b', 'opus', PROMPT, IMG)
    seen = env.seen()['env']
    assert 'TELEGRAM_STATE_DIR' not in seen and 'ANTHROPIC_API_KEY' not in seen
    _, removed = AG.clean_env({'TELEGRAM_STATE_DIR': '/x', 'PATH': '/bin'})
    assert removed == ['TELEGRAM_STATE_DIR']


def test_effort_default_param_and_journal(env):
    assert AG.EFFORT == 'medium'
    AG.set_effort('high')
    try:
        assert AG.one('kazan-1__b', 'opus', PROMPT, IMG)
        a = env.seen()['argv']
        assert a[a.index('--effort') + 1] == 'high'
        r = env.rows()[0]
        assert r['effort'] == 'high' and r['thinking_tokens'] == 2100
    finally:
        AG.set_effort('medium')


def test_effort_invalid_says_so():
    with pytest.raises(AG.AgentStop, match='не из'):
        AG.set_effort('turbo')
    assert AG.EFFORT == 'medium'


def test_effort_line_numbers_not_just_name():
    rows = [{'ok': True, 'thinking_tokens': 2000}, {'ok': True, 'thinking_tokens': 2200}, {'ok': False, 'thinking_tokens': 9999}, {'ok': True}]
    s = AG.effort_line(rows)
    assert s == 'усилие medium; рассуждений на лист: агент 2100 (по 2 листам) / платный 5800'
    assert 'нет данных' in AG.effort_line([])


def test_count_outcomes_verified_needs_laid():
    """kazan-14793283 run2: «проверено» при «не легло» — в верные НЕ идёт."""
    def row(v, st):
        return {'opus': v, 'overlay': {'overlay_status': st} if st else {}}
    rows = [row('проверено', 'легло'), row('проверено', 'не легло'), row('проверено', 'частично'), row('проверено', None),
            row('звонок: П4', 'легло'), row('отказ: пустой ответ', None), row('сбой разбора: x', None)]
    c = AG.count_outcomes(rows)
    assert c['верно (проверено И легло)'] == 1
    assert c['проверено, но не легло/частично/не проверено'] == 3
    assert c['звонок'] == 1 and c['отказ/прочее'] == 2 and c['всего'] == 7
    assert 'верно (проверено И легло) 1' in AG.outcomes_line(rows)


def test_labels5_budget_cap_three_and_refusal():
    assert AG.labels5_budget(None, 33.0) == 3.0                    # по умолчанию $3
    assert AG.labels5_budget(1.5, 33.0) == 1.5
    assert AG.labels5_budget(3.0, 2.0) == 2.0                      # не больше остатка общего потолка
    with pytest.raises(AG.AgentStop, match='больше допустимых'):
        AG.labels5_budget(3.5, 33.0)                               # сверх 3 — отказ с причиной


def test_labels5_stops_over_cap_with_reason():
    assert AG.labels5_may_call(0.0, 3.0) is None
    assert AG.labels5_may_call(2.92, 3.0) is None                  # 2,92 + 0,07 ≤ 3
    assert AG.labels5_may_call(2.94, 3.0) is not None              # 2,94 + 0,07 > 3 — стоп
    assert 'потолок шага $3.00' in AG.labels5_may_call(2.95, 3.0)
    assert 'потолок шага' in AG.labels5_may_call(3.5, 3.0)


def test_save_input_jpegs_both_names_same_bytes(tmp_path):
    from PIL import Image                                          # нет PIL — тест падает громко, не пропускается
    im = Image.new('RGB', (40, 30), (200, 100, 50))
    paths = AG.save_input_jpegs(im, str(tmp_path), 'kazan-11904669')
    assert [os.path.basename(p) for p in paths] == ['kazan-11904669__b.jpg', 'kazan-11904669__d.jpg']
    assert open(paths[0], 'rb').read() == open(paths[1], 'rb').read()
    with pytest.raises(AG.AgentStop, match='ни одной'):
        AG.save_input_jpegs(im, str(tmp_path), 'x', variants=())
