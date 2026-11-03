#!/usr/bin/env python3
"""design-02 П4а (T-20261103-11): проверка таблицы имён naming.json по выгрузке книг (только чтение файлов).

Запуск: python3 -I check-naming-p4a.py <папка выгрузки с mobile/sets.txt и desktop/sets.txt> [naming.json]
Проверки: 1) каждый набор обеих книг покрыт строкой таблицы (и id/старое имя совпадают);
2) новые имена уникальны в книге; 3) имена вариантов после пересчёта уникальны в наборе, у всех вариантов
одинаковый список свойств (после fill); 4) все свойства и значения покрыты правилами (общими или строки).
Пишет check-naming.txt и variants-new.json в папку выгрузки. Код выхода 0 — чисто, 1 — есть находки.
"""
import json
import re
import sys
from pathlib import Path

shots = Path(sys.argv[1])
naming = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).with_name('naming.json')).read_text(encoding='utf-8'))


def unesc(s):
    return s.replace('\\n', '\n').replace('\\|', '|').replace('\\¦', '¦')


def split_esc(s, sep):
    out, cur, i = [], '', 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            cur += s[i:i + 2]; i += 2; continue
        if s[i] == sep:
            out.append(cur); cur = ''; i += 1; continue
        cur += s[i]; i += 1
    out.append(cur)
    return out


def parse_defs(pd):
    """'Текст#205:0:T=Открыть;Язык:V=RU{RU/EN}' -> список (имя, тип, по_умолчанию, варианты)"""
    res = []
    if not pd:
        return res
    for part in pd.split(';'):
        m = re.match(r'^(.*?):([VTBI])=(.*?)(\{(.*)\})?$', part)
        name, typ, dflt, opts = m.group(1), m.group(2), m.group(3), m.group(5)
        base = name.split('#')[0]
        res.append({'name': name, 'base': base, 'type': typ, 'default': dflt,
                    'options': opts.split('/') if opts is not None else None})
    return res


def load(book):
    sets, page = {}, None
    for line in (shots / book / 'sets.txt').read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            pid, pname = line[3:].split('|', 1); page = (pid, pname); continue
        if not line.strip():
            continue
        f = split_esc(line, '|')
        kind, sid, name, desc, pd, vars_ = f[0], f[1], unesc(f[2]), unesc(f[3]), unesc(f[4]), f[5]
        defs = parse_defs(pd)
        vlist = []
        for v in split_esc(vars_, '¦') if vars_ else []:
            vals, _, full = v.partition('!')
            vlist.append({'vals': [unesc(x) for x in split_esc(vals, ',')] if vals else [], 'name': unesc(full) if full else None})
        sets[sid] = {'page': page, 'kind': kind, 'name': name, 'desc': desc, 'defs': defs, 'variants': vlist}
    return sets


books = {'mobile': load('mobile'), 'desktop': load('desktop')}
prop_rule = {p['old']: p['new'] for p in naming['properties']}
val_rule = {v['old']: v['new'] for v in naming['values']}
findings, notes = [], []
variants_new = {'mobile': {}, 'desktop': {}}

# 1) покрытие
for book, sets in books.items():
    covered = {}
    for row in naming['components']:
        sid = row.get(book)
        if sid is None:
            continue
        if sid not in sets:
            findings.append(f'{book}: id {sid} из таблицы нет в книге ({row["old"]})'); continue
        if sets[sid]['name'] != row['old']:
            findings.append(f'{book}: {sid} старое имя «{sets[sid]["name"]}» ≠ таблице «{row["old"]}»')
        covered[sid] = row
    for sid, s in sets.items():
        if sid not in covered:
            findings.append(f'{book}: набор {sid} «{s["name"]}» не покрыт таблицей')
    # 2) уникальность новых имён
    seen = {}
    for sid, row in covered.items():
        seen.setdefault(row['new'], []).append(sid)
    for n, ids in seen.items():
        if len(ids) > 1:
            findings.append(f'{book}: новое имя «{n}» у нескольких наборов {ids}')
    # страницы
    pages_dump = {s['page'][0]: s['page'][1] for s in sets.values()}
    for pg in naming['pages']:
        if pg[book] not in pages_dump or pages_dump[pg[book]] != pg['old']:
            findings.append(f'{book}: страница {pg[book]} «{pg["old"]}» не совпала с выгрузкой')
    if len({pg['new'] for pg in naming['pages']}) != len(naming['pages']):
        findings.append('новые имена страниц не уникальны')
    missing_pages = set(pages_dump) - {pg[book] for pg in naming['pages']}
    for mp in missing_pages:
        findings.append(f'{book}: страница {mp} «{pages_dump[mp]}» без нового имени')

    # 3) и 4) свойства, значения, варианты
    for sid, row in covered.items():
        s = sets[sid]
        pov, vov, fill = row.get('props', {}), row.get('values', {}), row.get('fill', {})
        fixv = row.get('fixVariantNames', {})
        newprops = []
        for d in s['defs']:
            nn = pov.get(d['base'], prop_rule.get(d['base']))
            if nn is None:
                findings.append(f'{book}: {sid} свойство «{d["base"]}» не покрыто правилом')
                nn = '?' + d['base']
            newprops.append(nn)
            if d['options']:
                for o in d['options']:
                    if o not in vov and o not in val_rule:
                        findings.append(f'{book}: {sid} значение «{o}» свойства «{d["base"]}» не покрыто')
        if len(set(newprops)) != len(newprops):
            findings.append(f'{book}: {sid} два свойства получили одно новое имя: {newprops}')
        vdefs = [d for d in s['defs'] if d['type'] == 'V']
        names_new = []
        for i, v in enumerate(s['variants']):
            # значения варианта: из полного имени (если разошлось с каноном) или по совпадению с вариантами свойства
            pairs = {}
            if v['name'] is not None and '=' in v['name']:
                for kv in v['name'].split(', '):
                    k, _, val = kv.partition('=')
                    pairs[k] = val
            elif v['name'] is not None:
                notes.append(f'{book}: {sid} вариант {i + 1} с испорченным именем «{v["name"]}» (нет «=»)')
                fixed = next((fv for fv in fixv.values()), None) if fixv else None
                if fixed:
                    for kv in fixed.split(', '):
                        k, _, val = kv.partition('=')
                        pairs[k] = val
                else:
                    findings.append(f'{book}: {sid} испорченное имя варианта без правки в fixVariantNames')
            else:
                for val in v['vals']:
                    owners = [d['base'] for d in vdefs if d['options'] and val in d['options']]
                    if len(owners) != 1:
                        findings.append(f'{book}: {sid} значение «{val}» не однозначно по свойствам: {owners}')
                        continue
                    pairs[owners[0]] = val
            parts = []
            for d in vdefs:
                nk = pov.get(d['base'], prop_rule.get(d['base'], '?'))
                if d['base'] in pairs:
                    o = pairs[d['base']]
                    nv = vov.get(o, val_rule.get(o, '?' + o))
                else:
                    f = fill.get(d['base'])
                    if isinstance(f, dict):
                        lang = next((p for p in parts if p.startswith('lang=')), '')
                        f = f.get(lang)
                    if f is None:
                        findings.append(f'{book}: {sid} вариант {i + 1} без свойства «{d["base"]}», fill не задан')
                        nv = '?'
                    else:
                        nv = f
                parts.append(f'{nk}={nv}')
            names_new.append(', '.join(parts))
        dup = {n for n in names_new if names_new.count(n) > 1}
        for n in dup:
            findings.append(f'{book}: {sid} «{row["new"]}» конфликт имён вариантов: «{n}» ×{names_new.count(n)}')
        variants_new[book][sid] = {'new': row['new'], 'variants': names_new}

# одинаковые по смыслу наборы двух книг — одной строкой: проверим, что набор свойств совпадает
for row in naming['components']:
    if row.get('mobile') and row.get('desktop'):
        a = [d['base'] for d in books['mobile'][row['mobile']]['defs']]
        b = [d['base'] for d in books['desktop'][row['desktop']]['defs']]
        if sorted(a) != sorted(b):
            notes.append(f'{row["new"]}: свойства Mobile {a} ≠ Desktop {b}')

# описания с именами свойств в «»
old_props = set(prop_rule)
for book, sets in books.items():
    for sid, s in sets.items():
        for q in re.findall(r'свойств[оа] «([^»]+)»', s['desc']):
            if q in old_props:
                notes.append(f'описание {book} {sid} «{s["name"]}»: «свойство «{q}»» → «{prop_rule[q]}»')

cnt = {b: len(s) for b, s in books.items()}
cov = {b: len(variants_new[b]) for b in books}
nvar = {b: sum(len(s['variants']) for s in books[b].values()) for b in books}
lines = [f'Наборов: Mobile {cnt["mobile"]} (покрыто {cov["mobile"]}, вариантов {nvar["mobile"]}), '
         f'Desktop {cnt["desktop"]} (покрыто {cov["desktop"]}, вариантов {nvar["desktop"]}); '
         f'строк таблицы {len(naming["components"])}, страниц {len(naming["pages"])}, '
         f'правил свойств {len(naming["properties"])}, значений {len(naming["values"])}',
         f'НАХОДКИ: {len(findings)}'] + ['  ' + f for f in findings] + [f'ЗАМЕТКИ: {len(notes)}'] + ['  ' + n for n in notes]
out = '\n'.join(lines)
(shots / 'check-naming.txt').write_text(out + '\n', encoding='utf-8')
(shots / 'variants-new.json').write_text(json.dumps(variants_new, ensure_ascii=False, indent=1), encoding='utf-8')
print(out)
sys.exit(1 if findings else 0)
