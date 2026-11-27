"""Метка формы `form_meta.py` (T-20261127-175/10-zapisi): есть `.model` и лесенка → generator/stage из них; нет — код ≠ 0 и причина, файл не пишется.
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
import form_meta as FM  # noqa: E402

FAIL = []


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        FAIL.append(msg)


def put(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def cli(*args):
    p = subprocess.run([sys.executable, '-I', os.path.join(HERE, '..', 'form_meta.py'), *args], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


with tempfile.TemporaryDirectory() as d:
    lad = os.path.join(d, 'ladder.json')
    put(lad, json.dumps([{'name': 'hd', 'input': 'hd', 'res': 1024}, {'name': 'x-hd', 'input': 'cur'}]))
    g = os.path.join(d, '112923_1-hd.glb')
    put(g, 'glb')
    put(os.path.join(d, '112923_1-hd.model'), 'trellis2\n')
    out = os.path.join(d, '112923_1-hd.form.json')

    print('есть .model и лесенка → метка из них')
    rc, txt = cli(g, '--ladder', lad)
    rec = json.load(open(out, encoding='utf-8')) if os.path.isfile(out) else {}
    ok(rc == 0 and rec.get('generator') == 'trellis2' and rec.get('stage') == 'hd', f'код 0, generator=trellis2, stage=hd (код {rc}, {rec.get("generator")}/{rec.get("stage")})')
    ok(rec.get('source', {}).get('model_file') == '112923_1-hd.model' and len(rec['source'].get('ladder_sha256', '')) == 64, 'в метке — откуда взято (файл .model, sha256 лесенки)')

    print('повтор — та же метка, код 0, файл не меняется')
    before = open(out, 'rb').read()
    rc, txt = cli(g, '--ladder', lad)
    ok(rc == 0 and 'та же метка' in txt and open(out, 'rb').read() == before, 'повторный запуск: 0, «та же метка», байты те же')

    print('чужая метка на месте → отказ, не перезаписываю')
    put(out, json.dumps({'generator': 'hunyuan', 'stage': 'hd'}))
    rc, txt = cli(g, '--ladder', lad)
    ok(rc == 1 and 'не перезаписываю' in txt and 'hunyuan' in open(out, encoding='utf-8').read(), 'код 1, причина строкой, файл не тронут')
    os.replace(out, out + '.old')

    print('нет .model → НЕ ВЫПОЛНЕНО, код 1, файла нет')
    g2 = os.path.join(d, '112923_2-hd.glb')
    put(g2, 'glb')
    rc, txt = cli(g2, '--ladder', lad)
    ok(rc == 1 and 'НЕ ВЫПОЛНЕНО' in txt and 'нет `112923_2-hd.model`' in txt and not os.path.exists(os.path.join(d, '112923_2-hd.form.json')), 'нет .model: код 1, причина, метка не создана')

    print('пустой .model → отказ')
    put(os.path.join(d, '112923_2-hd.model'), '  \n')
    rc, txt = cli(g2, '--ladder', lad)
    ok(rc == 1 and 'пуст' in txt and not os.path.exists(os.path.join(d, '112923_2-hd.form.json')), 'пустой .model: код 1')

    print('ступени нет в лесенке → отказ')
    g3 = os.path.join(d, '112923_3-lo.glb')
    put(g3, 'glb')
    put(os.path.join(d, '112923_3-lo.model'), 'trellis2')
    rc, txt = cli(g3, '--ladder', lad)
    ok(rc == 1 and 'ступень неизвестна' in txt, 'имя формы без ступени из лесенки: код 1')

    print('самое длинное имя ступени побеждает (x-hd, не hd)')
    g4 = os.path.join(d, '112923_4-x-hd.glb')
    put(g4, 'glb')
    put(os.path.join(d, '112923_4-x-hd.model'), 'trellis2')
    rc, txt = cli(g4, '--ladder', lad)
    ok(rc == 0 and json.load(open(os.path.join(d, '112923_4-x-hd.form.json')))['stage'] == 'x-hd', 'stage=x-hd')

    print('лесенка: нет файла / не список → отказ; без --ladder и без форм — код 2')
    rc, txt = cli(g, '--ladder', os.path.join(d, 'нет.json'))
    ok(rc == 1 and 'нет файла лесенки' in txt, 'лесенки нет: код 1 (форма с чужой меткой/или без — причина про лесенку)')
    put(os.path.join(d, 'bad.json'), '{}')
    rc, txt = cli(g2, '--ladder', os.path.join(d, 'bad.json'))
    ok(rc == 1, 'лесенка не список: код 1')
    rc, txt = cli(g)
    ok(rc == 2 and 'НЕ ВЫПОЛНЕНО' in txt, 'без --ladder: код 2 и строка')
    rc, txt = cli('--ladder', lad)
    ok(rc == 2 and 'НЕ ВЫПОЛНЕНО' in txt, 'без форм: код 2 и строка')

    print('нет самого GLB → отказ; --dry ничего не пишет')
    rc, txt = cli(os.path.join(d, 'нет.glb'), '--ladder', lad)
    ok(rc == 1 and 'нет файла формы' in txt, 'нет GLB: код 1')
    g5 = os.path.join(d, '112923_5-hd.glb')
    put(g5, 'glb')
    put(os.path.join(d, '112923_5-hd.model'), 'trellis2')
    rc, txt = cli(g5, '--ladder', lad, '--dry')
    ok(rc == 0 and 'dry:' in txt and not os.path.exists(os.path.join(d, '112923_5-hd.form.json')), '--dry: код 0, файла нет')

    print('смесь: одна форма не выполнена → общий код 1 и итоговая строка')
    rc, txt = cli(g5, g2, '--ladder', lad, '--dry')
    ok(rc == 1 and 'НЕ ВЫПОЛНЕНО у 1 из 2' in txt, 'общий код 1, «у 1 из 2»')

if FAIL:
    print(f'\nКРАСНЫЙ: {len(FAIL)}')
    sys.exit(1)
print('\nвсе проверки зелёные')
