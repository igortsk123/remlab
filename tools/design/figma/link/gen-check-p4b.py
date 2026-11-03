"""design-02 П4б (T-20261103-12): ожидание «после» по страницам → скрипты сверки (шаблон check-p4b.js).
Запуск: python3 gen-check-p4b.py <mobile|desktop> <папка выгрузки П4б>  → <папка>/gen/<книга>-check-<страница>.js
Ожидание: имена/описания/свойства/варианты — из plan-<книга>.json; экземпляры по главному компоненту и отпечатки
работы дизайнера — из выгрузки «до» (должны совпасть один в один); тексты 0:1 — «до» + howto-<книга>.json.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
book, outdir = sys.argv[1], sys.argv[2]
plan = json.load(open(os.path.join(outdir, 'plan-%s.json' % book)))
howto = json.load(open(os.path.join(outdir, 'howto-%s.json' % book)))
dump = [json.loads(l) for l in open(os.path.join(outdir, 'before', book, 'dump.jsonl')) if l.strip()]
tpl = '\n'.join(l for l in open(os.path.join(HERE, 'check-p4b.js')).read().splitlines() if not l.startswith('//'))
naming = json.load(open(os.path.join(HERE, 'naming.json')))
jsx = {c[book]: c['jsx'] for c in naming['components'] if c.get(book)}
renames = {p: n for p, o, n in plan['pageRenames']}


def h(t):  # djb2 по кодам UTF-16, как charCodeAt в check-p4b.js
    b = t.encode('utf-16-le')
    x = 5381
    for i in range(0, len(b), 2):
        x = ((x * 33) ^ (b[i] | b[i + 1] << 8)) & 0xFFFFFFFF
    d, r = '0123456789abcdefghijklmnopqrstuvwxyz', ''
    while True:
        x, k = divmod(x, 36)
        r = d[k] + r
        if not x:
            return r


def esc(t):
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')


os.makedirs(os.path.join(outdir, 'gen'), exist_ok=True)
for pg in dump:
    pid = pg['page']['id']
    before = {s['id']: s for s in pg['sets']}
    sets = []
    for o in plan['pages'].get(pid, {}).get('sets', []):
        s = before[o['id']]
        j = jsx[o['id']]
        assert o['desc'].startswith(j + '\n')
        renamed = {k: n for k, n in o['props']}
        keys = set(renamed.values())
        keys |= {k.split('#')[0] for k, t in s['p'].items() if t != 'V' and k not in renamed}
        keys |= {kv.split('=')[0] for kv in o['variants'][0][2].split(', ')}
        d = o['desc'][len(j) + 1:]
        sets.append({'id': o['id'], 'n': o['name'], 'dh': sorted({h(j + '\n' + d), h(esc(j) + '\n' + d)}),
                     'keys': ','.join(sorted(keys)), 'vn': len(o['variants']),
                     'vh': h('|'.join(v[0] + '=' + v[2] for v in o['variants']))})
    txt = None
    if pid == '0:1':
        ed = {e[0]: e[2] for e in howto['edits']}
        txt = [[i, h(ed.get(i, t))] for i, t in pg['txt']] + [['*', h(howto['add']['text'])]]
    exp = {'page': pid, 'pageName': renames.get(pid, pg['page']['name']), 'sets': sets, 'inst': pg['inst'],
           'dz': pg['dz'] if pid == '123:2' else None, 'txt': txt}
    code = tpl.replace('__EXP__', json.dumps(exp, ensure_ascii=False))
    fn = os.path.join(outdir, 'gen', '%s-check-%s.js' % (book, pid.replace(':', '-')))
    open(fn, 'w').write(code)
    print(fn, len(code))
