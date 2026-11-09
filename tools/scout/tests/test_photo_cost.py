"""ЦЕНА КАЖДОГО ПЛАТНОГО КАДРА (T-20261109-28): `draft_render._photo_cost` + отчёт `tools/ops/photo-cost.py`. Без сети и без модели:
шлюз и баланс — поддельные.
  1) удачный вызов /images/edits → строка в журнале: метка, модель, размер, качество, картинок на входе, usage, id генерации и
     заголовки ответа, баланс до/после и `cost_usd` (`balance_delta`); счётчик активных вызовов возвращается к нулю;
  2) путь /chat/completions (не openai) пишется ОДИН раз (вложенный вызов не дублирует), цена шлюза из ответа — `gateway_cost_usd`;
  3) отказ шлюза (402) — запись с ok=false и причиной, без цены, исключение уходит наружу как раньше;
  4) два вызова одновременно — оба `overlap: true`; следующий одиночный — `overlap: false`;
  5) отчёт: среднее/мин/макс по последним N, overlap (своя пометка и пересечение окон разных процессов) и записи без цены
     в среднее не входят, фильтр метки, ₽ по курсу аргументом.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_photo_cost.py -q"""
import base64
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
ROOT = os.path.abspath(os.path.join(SCOUT, '..', '..'))
sys.path.insert(0, SCOUT)
sys.path.insert(0, os.path.join(ROOT, 'services', 'planner-solver'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_photo_cost')  # временное — на диске, не в /tmp; убирается при выходе (T-20261107-13)

from PIL import Image  # noqa: E402

import draft_render as DR  # noqa: E402

_spec = importlib.util.spec_from_file_location('photo_cost_report', os.path.join(ROOT, 'tools', 'ops', 'photo-cost.py'))
PC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PC)


def _png() -> str:
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), (200, 100, 50)).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()


class Resp:
    def __init__(self, body: dict, headers: dict):
        self.body, self.headers = json.dumps(body).encode(), headers

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Balance:
    """Поддельный баланс: каждое обращение — следующее значение (последнее повторяется)."""

    def __init__(self, *vals):
        self.vals, self.n, self.lock = list(vals), 0, threading.Lock()

    def __call__(self, max_age_s=60.0):
        with self.lock:
            v = self.vals[min(self.n, len(self.vals) - 1)]
            self.n += 1
            return v


@pytest.fixture()
def env(monkeypatch):
    d = tempfile.mkdtemp(prefix='photo-cost-')
    log = os.path.join(d, 'sub', 'photo-cost.jsonl')        # папки нет — запись создаёт её сама
    monkeypatch.setattr(DR, 'PHOTO_COST_LOG', log)
    monkeypatch.setattr(DR, '_PC_SETTLE_S', 0.05)
    monkeypatch.setattr(DR, 'gw_key', lambda: 'test-key')
    calls = []
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout=None: (_ for _ in ()).throw(
        AssertionError(f'сеть в тесте: {getattr(req, "full_url", req)}')))
    yield {'log': log, 'calls': calls, 'mp': monkeypatch}
    DR.photo_cost_wait()
    assert DR._PC_STATE['active'] == 0, DR._PC_STATE


def _lines(log):
    DR.photo_cost_wait()
    with open(log, encoding='utf-8') as f:
        return [json.loads(x) for x in f if x.strip()]


IMG = Image.new('RGB', (16, 16))


def test_success_record(env):
    env['mp'].setattr(DR, 'gw_credits', Balance(10.0, 9.95))

    def urlopen(req, timeout=None):
        env['calls'].append(req.full_url)
        return Resp({'created': 1, 'data': [{'b64_json': _png()}],
                     'usage': {'input_tokens': 1200, 'output_tokens': 6000, 'total_tokens': 7200}},
                    {'Content-Type': 'application/json', 'x-vercel-id': 'fra1::abc', 'X-Generation-Id': 'gen_01TEST',
                     'Set-Cookie': 'nope'})
    env['mp'].setattr(urllib.request, 'urlopen', urlopen)
    out = DR.gpt_edit([IMG, IMG, IMG], 'p', size='2048x3072', quality='medium', model='openai/gpt-image-test', cost_label='demo')
    assert out.size == (8, 8)
    assert env['calls'] == [DR.GATEWAY]
    (r,) = _lines(env['log'])
    assert r['label'] == 'demo' and r['fn'] == 'gpt_edit' and r['ok'] is True
    assert (r['model'], r['size'], r['quality'], r['n_images']) == ('openai/gpt-image-test', '2048x3072', 'medium', 3)
    assert r['usage']['total_tokens'] == 7200
    assert r['generation_id'] == 'gen_01TEST'
    assert r['headers']['x-vercel-id'] == 'fra1::abc' and 'set-cookie' not in r['headers']
    assert (r['bal0'], r['bal1'], r['cost_usd'], r['cost_source']) == (10.0, 9.95, 0.05, 'balance_delta')
    assert r['overlap'] is False and r['t_start'] <= r['t_end'] <= r['t_bal1']
    assert 'b64_json' not in json.dumps(r)


def test_chat_path_once_with_gateway_cost(env):
    env['mp'].setattr(DR, 'gw_credits', Balance(5.0, 4.96))
    url = 'data:image/png;base64,' + _png()

    def urlopen(req, timeout=None):
        env['calls'].append(req.full_url)
        return Resp({'id': 'gen_CHAT1', 'model': 'google/img', 'usage': {'prompt_tokens': 10, 'completion_tokens': 1290},
                     'choices': [{'message': {'role': 'assistant', 'content': '', 'images': [{'image_url': {'url': url}}],
                                              'provider_metadata': {'gateway': {'cost': '0.039'}}}}]}, {})
    env['mp'].setattr(urllib.request, 'urlopen', urlopen)
    DR.gpt_edit([IMG], 'p', model='google/img-test')          # без метки: имя скрипта или PHOTO_COST_LABEL
    lines = _lines(env['log'])
    assert len(lines) == 1, lines                              # gpt_edit → _chat_edit: одна запись
    r = lines[0]
    assert env['calls'] == [DR.CHAT_URL]
    assert r['generation_id'] == 'gen_CHAT1' and r['gateway_cost_usd'] == pytest.approx(0.039)
    assert r['cost_usd'] == pytest.approx(0.04) and r['label']


def test_gateway_refusal_recorded(env):
    env['mp'].setattr(DR, 'gw_credits', Balance(0.01, 0.01))

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 402, 'Payment Required', {'x-vercel-id': 'r1'},
                                     io.BytesIO(b'{"error":"insufficient funds"}'))
    env['mp'].setattr(urllib.request, 'urlopen', urlopen)
    with pytest.raises(DR.NoCreditsError):
        DR.gpt_edit([IMG], 'p', model='openai/gpt-image-test', cost_label='hero')
    (r,) = _lines(env['log'])
    assert r['ok'] is False and 'NoCreditsError' in r['error'] and r['label'] == 'hero'
    assert 'cost_usd' not in r and r['delta_usd'] == 0 and r['cost_note']
    assert r['headers'] == {'x-vercel-id': 'r1'}


def test_overlap(env):
    env['mp'].setattr(DR, 'gw_credits', Balance(10.0, 9.9, 9.8, 9.8, 9.7))

    def urlopen(req, timeout=None):
        time.sleep(0.3)
        return Resp({'data': [{'b64_json': _png()}]}, {})
    env['mp'].setattr(urllib.request, 'urlopen', urlopen)
    ths = [threading.Thread(target=DR.gpt_edit, args=([IMG], 'p'), kwargs={'model': 'openai/x', 'cost_label': 'demo'})
           for _ in range(2)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    two = _lines(env['log'])
    assert len(two) == 2 and all(r['overlap'] is True for r in two), two
    assert DR._PC_STATE['active'] == 0
    DR.gpt_edit([IMG], 'p', model='openai/x', cost_label='demo')
    third = _lines(env['log'])[2]
    assert third['overlap'] is False


def test_label_default(monkeypatch):
    monkeypatch.setenv('PHOTO_COST_LABEL', 'bench')
    assert DR._pc_label(None) == 'bench' and DR._pc_label('demo') == 'demo'
    monkeypatch.delenv('PHOTO_COST_LABEL')
    monkeypatch.setattr(sys, 'argv', ['/x/trial_hero.py'])
    assert DR._pc_label(None) == 'hero'


def _rec(t, cost, label='demo', overlap=False, ok=True, pid=1, dur=40.0):
    r = {'ts': f't{t}', 'label': label, 'model': 'openai/m', 'size': '2048x3072', 'quality': 'medium', 'ok': ok,
         'overlap': overlap, 'pid': pid, 't_start': float(t), 't_end': t + dur, 't_bal1': t + dur + 2.5, 'dur_s': dur}
    if cost is not None:
        r.update(cost_usd=cost, cost_source='balance_delta')
    return r


def test_report_summary():
    recs = [_rec(0, 9.99),                                    # старше окна N — не входит
            _rec(100, 0.20), _rec(200, 0.30), _rec(300, 0.10, overlap=True),
            _rec(400, 0.25, label='hero'), _rec(500, None), _rec(600, 0.5, ok=False),
            _rec(700, 0.40), _rec(720, 0.60, pid=2)]          # 700 и 720 — окна пересекаются (разные процессы)
    s = PC.summarize(recs, n=6, label='demo')
    assert [r['t_start'] for r in s['rows']] == [100, 200, 300, 500, 700, 720]
    assert [r['cost_usd'] for r in s['clean']] == [0.20, 0.30]
    assert sorted(r['t_start'] for r in s['overlap']) == [300, 700, 720]
    assert [r['t_start'] for r in s['no_cost']] == [500]
    assert s['mean'] == pytest.approx(0.25) and (s['min'], s['max']) == (0.20, 0.30)
    s_all = PC.summarize(recs, n=10)
    assert 400 in [r['t_start'] for r in s_all['clean']]


def test_report_main(capsys):
    d = tempfile.mkdtemp(prefix='photo-cost-rep-')
    p = os.path.join(d, 'log.jsonl')
    with open(p, 'w', encoding='utf-8') as f:
        for r in (_rec(100, 0.20), _rec(200, 0.30), _rec(300, 0.10, overlap=True)):
            f.write(json.dumps(r) + '\n')
        f.write('не json\n')
    assert PC.main(['10', '--label', 'demo', '--rub', '100', '--file', p]) == 0
    out = capsys.readouterr().out
    assert 'среднее $0.2500 ≈ 25.00 ₽' in out and 'мин $0.2000 ≈ 20.00 ₽' in out and 'макс $0.3000 ≈ 30.00 ₽' in out
    assert 'в среднее НЕ входят' in out
    assert PC.main(['--file', os.path.join(d, 'нет.jsonl'), '--rub', '100']) == 1
