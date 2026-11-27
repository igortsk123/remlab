"""Метка формы `form_meta.py` (T-20261127-175/10-zapisi): generator/stage — из ЖУРНАЛА генерации (`summary-trial-*.json`); нет журнала — код ≠ 0 и причина, файл не пишется.
Запуск: python3 tools/scout/tests/test_form_meta.py   (только stdlib)"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_form_meta')
import tempfile  # noqa: E402

FAIL = []


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        FAIL.append(msg)


def put(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def journal(path, jobs, model='trellis2'):
    put(path, json.dumps({'group': 'trial-x', 'model': model, 'image': 'img@sha256:abc', 'jobs': jobs}))


def job(jid, status='done', step='hd', **kw):
    return {'sku': '112923:' + jid.split('_')[1].split('-')[0], 'job_id': jid, 'status': status, 'ladder_step': step, 'seed': 42, 'res': 1024, **kw}


def cli(*args):
    p = subprocess.run([sys.executable, '-I', os.path.join(HERE, '..', 'form_meta.py'), *args], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def form(d, n, glb=True):
    g = os.path.join(d, f'112923_{n}-hd.glb')
    put(g, 'glb')
    return g


def meta(d, n):
    p = os.path.join(d, f'112923_{n}-hd.form.json')
    return json.load(open(p, encoding='utf-8')) if os.path.isfile(p) else None


with tempfile.TemporaryDirectory() as d:
    jr = os.path.join(d, 'summary-trial-trellis2-x.json')
    journal(jr, [job('112923_1-hd'), job('112923_2-hd', status='failed'), job('112923_3-hd', step='')])
    g1 = form(d, 1)

    print('журнал в папке формы, задание done → generator/stage из журнала')
    rc, txt = cli(g1)
    m = meta(d, 1) or {}
    ok(rc == 0 and m.get('generator') == 'trellis2' and m.get('stage') == 'hd', f'код 0, generator=trellis2, stage=hd (код {rc}, {m.get("generator")}/{m.get("stage")})')
    ok(m.get('source', {}).get('job_id') == '112923_1-hd' and len(m['source'].get('journal_sha256', '')) == 64 and m['source'].get('seed') == 42, 'в метке — откуда взято (журнал, sha256, job_id, seed)')

    print('значения берутся из журнала, не константа: другая модель и ступень → они же в метке')
    journal(os.path.join(d, 'summary-trial-other.json'), [job('112923_7-hd', step='hd2')], model='hunyuan3')
    g7 = form(d, 7)
    rc, txt = cli(g7, '--journal', os.path.join(d, 'summary-trial-other.json'))
    m = meta(d, 7) or {}
    ok(rc == 0 and m.get('generator') == 'hunyuan3' and m.get('stage') == 'hd2', f'generator=hunyuan3, stage=hd2 (из журнала: {m.get("generator")}/{m.get("stage")}); разрешён ли — решают ворота')

    print('повтор — та же метка, код 0, байты те же')
    before = open(os.path.join(d, '112923_1-hd.form.json'), 'rb').read()
    rc, txt = cli(g1)
    ok(rc == 0 and 'та же метка' in txt and open(os.path.join(d, '112923_1-hd.form.json'), 'rb').read() == before, 'повторный запуск: 0, «та же метка»')

    print('чужая метка на месте → отказ, не перезаписываю')
    out = os.path.join(d, '112923_1-hd.form.json')
    put(out, json.dumps({'generator': 'hunyuan', 'stage': 'hd'}))
    rc, txt = cli(g1)
    ok(rc == 1 and 'не перезаписываю' in txt and 'hunyuan' in open(out, encoding='utf-8').read(), 'код 1, причина строкой, файл не тронут')

    print('задание есть, но не выполнено (failed) → отказ')
    g2 = form(d, 2)
    rc, txt = cli(g2)
    ok(rc == 1 and 'НЕ ВЫПОЛНЕНО' in txt and 'не выполнено' in txt and 'status failed' in txt and meta(d, 2) is None, 'failed: код 1, причина, метки нет')

    print('в журнале нет ступени (ladder_step пуст) → отказ')
    g3 = form(d, 3)
    rc, txt = cli(g3)
    ok(rc == 1 and 'нет `ladder_step`' in txt and meta(d, 3) is None, 'нет ladder_step: код 1')

    print('в журнале нет задания этой формы → отказ')
    g4 = form(d, 4)
    rc, txt = cli(g4)
    ok(rc == 1 and 'нет задания этой формы' in txt and meta(d, 4) is None, 'нет задания: код 1')

    print('НЕТ ЖУРНАЛА → отказ «нет журнала генерации» (даже если рядом есть .model — константой не подменяю)')
    with tempfile.TemporaryDirectory() as e:
        g = os.path.join(e, '112923_9-hd.glb')
        put(g, 'glb')
        put(os.path.join(e, '112923_9-hd.model'), 'trellis2')
        rc, txt = cli(g)
        ok(rc == 1 and 'нет журнала генерации' in txt and not os.path.exists(os.path.join(e, '112923_9-hd.form.json')), 'без журнала: код 1, «нет журнала генерации», метки нет')
        rc, txt = cli(g, '--journal', os.path.join(e, 'нет.json'))
        ok(rc == 1 and 'нет файла' in txt, '--journal на несуществующий файл: код 1 с причиной')

    print('журнал битый → отказ')
    with tempfile.TemporaryDirectory() as e:
        g = os.path.join(e, '112923_9-hd.glb')
        put(g, 'glb')
        put(os.path.join(e, 'summary-trial-trellis2-bad.json'), '{не json')
        rc, txt = cli(g)
        ok(rc == 1 and 'не читается' in txt, 'битый журнал: код 1')

    print('журналы спорят → отказ; одинаковые — ок')
    with tempfile.TemporaryDirectory() as e:
        g = os.path.join(e, '112923_5-hd.glb')
        put(g, 'glb')
        journal(os.path.join(e, 'summary-trial-a.json'), [job('112923_5-hd')])
        journal(os.path.join(e, 'summary-trial-b.json'), [job('112923_5-hd', step='hd2')])
        rc, txt = cli(g)
        ok(rc == 1 and 'журналы спорят' in txt, 'разные ступени в двух журналах: код 1')
        journal(os.path.join(e, 'summary-trial-b.json'), [job('112923_5-hd')])
        rc, txt = cli(g)
        ok(rc == 0, 'одинаковые журналы: код 0')

    print('.model расходится с журналом → отказ; совпадает — ок')
    g8 = form(d, 8)
    journal(os.path.join(d, 'summary-trial-trellis2-y.json'), [job('112923_8-hd')])
    put(os.path.join(d, '112923_8-hd.model'), 'hunyuan3d')
    rc, txt = cli(g8)
    ok(rc == 1 and 'расходятся' in txt and meta(d, 8) is None, '.model=hunyuan3d против журнала trellis2: код 1')
    put(os.path.join(d, '112923_8-hd.model'), 'trellis2\n')
    rc, txt = cli(g8)
    ok(rc == 0 and meta(d, 8) is not None, '.model совпадает: код 0')

    print('без форм — код 2; нет самого GLB — код 1; --dry ничего не пишет; смесь — общий код 1')
    rc, txt = cli()
    ok(rc == 2 and 'НЕ ВЫПОЛНЕНО' in txt, 'без форм: код 2 и строка')
    rc, txt = cli(os.path.join(d, 'нет.glb'))
    ok(rc == 1 and 'нет файла формы' in txt, 'нет GLB: код 1')
    g6 = form(d, 6)
    journal(os.path.join(d, 'summary-trial-trellis2-z.json'), [job('112923_6-hd')])
    rc, txt = cli(g6, '--dry')
    ok(rc == 0 and 'dry:' in txt and meta(d, 6) is None, '--dry: код 0, файла нет')
    rc, txt = cli(g6, g2, '--dry')
    ok(rc == 1 and 'НЕ ВЫПОЛНЕНО у 1 из 2' in txt, 'смесь: общий код 1, «у 1 из 2»')

if FAIL:
    print(f'\nКРАСНЫЙ: {len(FAIL)}')
    sys.exit(1)
print('\nвсе проверки зелёные')
