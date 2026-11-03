"""design-02 П4б: из plan-<книга>.json собирает скрипты записи по страницам (шаблон apply-names-p4b.js).
Запуск: python3 gen-apply-p4b.py <mobile|desktop> <папка выгрузки П4б>  → <папка>/gen/<книга>-<страница>.js
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
book, outdir = sys.argv[1], sys.argv[2]
plan = json.load(open(os.path.join(outdir, 'plan-%s.json' % book)))
naming = json.load(open(os.path.join(HERE, 'naming.json')))
tpl = open(os.path.join(HERE, 'apply-names-p4b.js')).read()
jsx = {c[book]: c['jsx'] for c in naming['components'] if c.get(book)}
desc_map = {p['old']: p['new'] for p in naming['properties']}
os.makedirs(os.path.join(outdir, 'gen'), exist_ok=True)
for pid, pg in plan['pages'].items():
    ops = [{'id': o['id'], 'o': o['oldName'], 'n': o['name'], 'j': jsx[o['id']], 'p': o['props'],
            'v': [[v[0], v[2]] for v in o['variants']]} for o in pg['sets']]
    # в описаниях встречаются только «Стрелка», «Текст», «Число» — карту держим короткой
    dm = {k: v for k, v in desc_map.items() if any('свойство «%s»' % k in o['oldDesc'] for o in pg['sets'])}
    code = tpl.replace('__PAGE__', pid).replace('__OPS__', json.dumps(ops, ensure_ascii=False)) \
        .replace('__DESC_MAP__', json.dumps(dm, ensure_ascii=False))
    fn = os.path.join(outdir, 'gen', '%s-%s.js' % (book, pid.replace(':', '-')))
    open(fn, 'w').write(code)
    print(fn, len(code))
