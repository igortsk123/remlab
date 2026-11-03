"""design-02 П4б (T-20261103-12): правки текстов «Как пользоваться» по howto-renames.md для одной книги.
Запуск: python3 gen-howto-p4b.py <mobile|desktop> <папка выгрузки П4б>  → <папка>/howto-<книга>.json
Каждая правка: [id, старый текст, новый, длина жирного начала до, после]. Старый текст сверяется с выгрузкой «до»
дословно (не сходится — ошибка, правки нет). «Кнопки — 9 секций» → 14 секций (решение ведущего, naming.json leadDecisions).
Новая строка «Нюансов» — поле add: вставить копией соседней строки (141:8 / 80:8) сразу после неё.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
book, outdir = sys.argv[1], sys.argv[2]
md = open(os.path.join(HERE, 'howto-renames.md')).read()
dump = [json.loads(l) for l in open(os.path.join(outdir, 'before', book, 'dump.jsonl')) if l.strip()]
txt = {i: t for d in dump if d['page']['id'] == '0:1' for i, t in d['txt']}

rows = []  # (mobileId|None, desktopId|None, old, new)
for line in md.splitlines():
    m = re.match(r'\| (\d+:\d+)(?: \((\d+:\d+)\))? \| (.+?) \| (.+?) \|$', line)
    if not m:
        continue
    a, b, old, new = m.groups()
    if old.startswith('…'):  # строка «Нюансов» с фрагментом — ниже отдельно
        continue
    mob = a if a.startswith('130:') else None
    desk = b if b else (a if a.startswith('57:') else None)
    rows.append((mob, desk, old, new))

EXTRA_BTN = ', Button, Segmented / Item, Button / Undo Redo, Badge / Count, Button / Arrow'
out, errors = [], []
for mob, desk, old, new in rows:
    nid = mob if book == 'mobile' else desk
    if not nid:
        continue
    if new.startswith('Buttons — 9 секций'):
        new = new.replace('9 секций', '14 секций') + EXTRA_BTN
    cur = txt.get(nid)
    if cur != old:
        errors.append('%s: в книге «%s» ≠ «%s»' % (nid, cur, old))
        continue
    out.append([nid, old, new, old.index(' — '), new.index(' — ')])

# 141:8 / 80:8 — только ссылки на страницы
nid = '141:8' if book == 'mobile' else '80:8'
cur = txt.get(nid, '')
pairs = [('(«Образцы», «Карточка товара»)', '(«Swatches», «Product Detail»)'),
         ('в средней карточке «Избранного»', 'в средней карточке «Favorites»'),
         ('в две строки («Диалог»)', 'в две строки («Modal»)')]
new = cur
for a, b in pairs:
    if new.count(a) != 1:
        errors.append('%s: фрагмент «%s» встречается %d раз' % (nid, a, new.count(a)))
    new = new.replace(a, b)
head = 'Доведено вручную.'
if not cur.startswith(head):
    errors.append('%s: начало не «%s»' % (nid, head))
out.append([nid, cur, new, len(head), len(head)])

add_text = re.search(r'^> (Кнопки внутри карточек.+)$', md, re.M).group(1)
res = {'edits': out, 'add': {'after': nid, 'text': add_text, 'bold': add_text.index(' — '),
                             'name': 'Нюанс «Кнопки в карточках»'}, 'errors': errors}
fn = os.path.join(outdir, 'howto-%s.json' % book)
json.dump(res, open(fn, 'w'), ensure_ascii=False, indent=1)
print(fn, 'правок', len(out), 'ошибок', len(errors))
for e in errors:
    print('  ', e)
