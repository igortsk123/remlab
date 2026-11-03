"""design-02 П4б (T-20261103-12): из выгрузки «до» + naming.json + variants-new.json строит операции переименования
по страницам одной книги и обратную таблицу new → old (для отката).
Запуск: python3 plan-p4b.py <mobile|desktop> <папка выгрузки П4б>
Пишет в <папка>/plan-<книга>.json: {pages:{pageId:{sets:[op]}}, pageRenames, errors}; <папка>/rollback-<книга>.json.
op = {id, oldName, name, oldDesc, desc, props:[[ключ, новое имя]], variants:[[childId, старое, новое]]}.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
book, outdir = sys.argv[1], sys.argv[2]
naming = json.load(open(os.path.join(HERE, 'naming.json')))
vnew = json.load(open(os.path.join(HERE, '..', 'shots', '0311-1751-p4a', 'variants-new.json')))[book]
dump = [json.loads(l) for l in open(os.path.join(outdir, 'before', book, 'dump.jsonl')) if l.strip()]

PROPS = {p['old']: p['new'] for p in naming['properties']}
VALUES = {v['old']: v['new'] for v in naming['values']}
COMPS = {c[book]: c for c in naming['components'] if c.get(book)}
errors, notes = [], []


def parse(name, fix):
    if fix:
        name = fix
    out = []
    for part in name.split(', '):
        if '=' not in part:
            raise ValueError('битое имя варианта: ' + name)
        k, v = part.split('=', 1)
        out.append((k, v))
    return out


plan = {'pages': {}, 'pageRenames': [], 'errors': errors, 'notes': notes}
rollback = {'sets': {}, 'pages': {}}
seen = set()
for pg in dump:
    ops = []
    for s in pg['sets']:
        sid = s['id']
        c = COMPS.get(sid)
        if not c:
            if sid != '158:696':
                errors.append('нет строки в naming.json: %s %s' % (sid, s['n']))
            continue
        seen.add(sid)
        if s['n'] != c['old']:
            errors.append('имя %s в книге «%s» ≠ таблица «%s»' % (sid, s['n'], c['old']))
        pover = c.get('props', {})
        vover = c.get('values', {})
        fill = c.get('fill', {})
        fix = c.get('fixVariantNames', {})
        # TEXT/BOOLEAN — переименование по ключу
        props = []
        for k, t in s['p'].items():
            if t == 'V':
                continue
            old = k.split('#')[0]
            new = pover.get(old) or PROPS.get(old)
            if not new:
                errors.append('%s: свойство «%s» без нового имени' % (sid, old))
                continue
            props.append([k, new])
        # порядок свойств-вариантов — как в определениях набора
        vorder = [k for k, t in s['p'].items() if t == 'V']
        variants = []
        for ch in s['v']:
            cid, cname = ch[0], ch[1]
            try:
                kv = dict(parse(cname, fix.get(cid)))
            except ValueError as e:
                errors.append('%s: %s' % (sid, e))
                continue
            lang = None
            parts = []
            for k in vorder:
                nk = pover.get(k) or PROPS.get(k)
                if not nk:
                    errors.append('%s: свойство-вариант «%s» без нового имени' % (sid, k))
                    continue
                if k in kv:
                    v = kv[k]
                    nv = vover.get(v) or VALUES.get(v)
                    if nv is None:
                        errors.append('%s: значение «%s» без нового' % (sid, v))
                        continue
                    if k == 'Язык':
                        lang = nv
                else:
                    f = fill.get(k)
                    if f is None:
                        errors.append('%s/%s: нет значения «%s» и нет fill' % (sid, cid, k))
                        continue
                    nv = f['lang=' + (lang or '')] if isinstance(f, dict) else f
                parts.append('%s=%s' % (nk, nv))
            variants.append([cid, cname, ', '.join(parts)])
        names = [v[2] for v in variants]
        if len(set(names)) != len(names):
            errors.append('%s: имена вариантов не уникальны: %s' % (sid, names))
        exp = vnew.get(sid, {}).get('variants')
        if exp != names:
            errors.append('%s: не сходится с variants-new.json: %s ≠ %s' % (sid, names, exp))
        if vnew.get(sid, {}).get('new') != c['new']:
            errors.append('%s: новое имя ≠ variants-new.json' % sid)
        d = s['d']
        d2 = re.sub(r'свойство «([^»]+)»', lambda m: 'свойство ' + (pover.get(m.group(1)) or PROPS.get(m.group(1), m.group(0))), d)
        if d2 != d:
            notes.append('%s: описание — %s' % (sid, re.findall(r'свойство «[^»]+»', d)))
        desc = c['jsx'] + '\n' + d2
        ops.append({'id': sid, 'oldName': s['n'], 'name': c['new'], 'oldDesc': d, 'desc': desc,
                    'props': props, 'variants': variants})
        rollback['sets'][sid] = {'name': s['n'], 'desc': d,
                                 'props': {new: k.split('#')[0] for k, new in props},
                                 'variants': {v[0]: v[1] for v in variants}}
    if ops:
        plan['pages'][pg['page']['id']] = {'sets': ops}
for p in naming['pages']:
    if p.get(book):
        plan['pageRenames'].append([p[book], p['old'], p['new']])
        rollback['pages'][p[book]] = p['old']
missing = set(COMPS) - seen
if missing:
    errors.append('наборы из таблицы не найдены в книге: %s' % sorted(missing))
json.dump(plan, open(os.path.join(outdir, 'plan-%s.json' % book), 'w'), ensure_ascii=False, indent=1)
json.dump(rollback, open(os.path.join(outdir, 'rollback-%s.json' % book), 'w'), ensure_ascii=False, indent=1)
print('наборов', sum(len(v['sets']) for v in plan['pages'].values()),
      'TEXT/BOOL', sum(len(o['props']) for v in plan['pages'].values() for o in v['sets']),
      'вариантов', sum(len(o['variants']) for v in plan['pages'].values() for o in v['sets']),
      'страниц', len(plan['pageRenames']))
print('ОШИБКИ', len(errors))
for e in errors:
    print('  ', e)
for n in notes:
    print('  заметка', n)
