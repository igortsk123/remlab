#!/usr/bin/env python3
"""ПРОВЕРКА ПОКРЫТИЯ КАТАЛОГОМ (заявка владельца 11.08): хватает ли мебели, чтобы
наполнить КАЖДЫЙ шаблон в КАЖДОМ стиле — с учётом конвертов габаритов (−20%/+10%)
и правила разнообразия (`compose2.overlap_ok`: «лицо ≤1» между стилями, запрет
повторных связок крупных пар).

Логика: шаблон = набор слотов (роль + идеал габарита по band). Для слота считаем,
сколько SKU попадает в конверт И проходит стилевой порог. Дальше — сколько РАЗНЫХ
сетов можно собрать, не нарушая разнообразие: каждый «лицевой» крупный предмет
(диван/кресло/столик/стол) может уйти максимум в 1 сет внутри стиля (иначе связки
повторяются) — значит потолок вариантов = минимум по лицевым слотам.

  ~/venvs/scout/bin/python template_coverage.py [--publish]
"""
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
STYLE_MIN = 6.0          # порог стилевого соответствия (как в подборе)
ENV_LO, ENV_HI = 0.80, 1.10      # конверт габаритов: −20% / +10% (решение владельца)

# слоты шаблонов: роль → идеальная ШИРИНА (см) по диапазону площади
TEMPLATES = {
    'диван + столик + ковёр (12+ м²)': {'диван': 180, 'столик': 90, 'ковёр': 200},
    'диван + кресло (15+ м²)': {'диван': 180, 'кресло': 76, 'столик': 90, 'ковёр': 200},
    'диван + 2 кресла (23+ м²)': {'диван': 220, 'кресло': 85, 'кресло 2': 85,
                                  'столик': 110, 'ковёр': 290},
    'диван + 4 кресла (32+ м²)': {'диван': 220, 'кресло': 85, 'кресло 2': 85,
                                  'кресло 3': 85, 'кресло 4': 85, 'столик': 110,
                                  'ковёр': 290},
    'угловой + 2 кресла (24+ м²)': {'диван': 260, 'кресло': 85, 'кресло 2': 85,
                                    'столик': 90, 'ковёр': 290},
    '2 кресла без дивана (12+ м²)': {'кресло': 76, 'кресло 2': 76, 'столик': 90,
                                     'ковёр': 160},
    '2 дивана П-стык (45+ м²)': {'диван': 230, 'диван 2': 230, 'кресло': 85,
                                 'кресло 2': 85, 'столик': 110, 'ковёр': 290},
    '2 дивана визави (32+ м²)': {'диван': 220, 'диван 2': 220, 'столик': 110,
                                 'ковёр': 290},
    'U-композиция (40+ м²)': {'диван': 220, 'кресло': 85, 'кресло 2': 85,
                              'кресло 3': 85, 'кресло 4': 85, 'столик': 130,
                              'ковёр': 290},
    'столовая 2 стула (15+ м²)': {'стол обеденный': 90, 'стул': 45, 'стул 2': 45},
    'столовая 4 стула (25+ м²)': {'стол обеденный': 140, 'стул': 45, 'стул 2': 45,
                                  'стул 3': 45, 'стул 4': 45},
    'столовая 6 стульев (45+ м²)': {'стол обеденный': 180, 'стул': 45, 'стул 2': 45,
                                    'стул 3': 45, 'стул 4': 45, 'стул 5': 45,
                                    'стул 6': 45},
    'медиа: тумба (8+ м²)': {'тв-тумба': 120},
    'медиа: стенка (13+ м²)': {'стенка': 280},
    'каминная зона (10+ м²)': {'камин': 120, 'стеллаж': 80, 'стеллаж 2': 80},
    'стеллаж-стена (10+ м²)': {'стеллаж': 90, 'комод': 120, 'кашпо': 40},
    'уголок чтения (8+ м²)': {'кресло 3': 80, 'торшер': 35, 'приставной': 45},
}
FACE_ROLES = {'диван', 'диван 2', 'кресло', 'столик', 'стол обеденный'}
OPTIONAL = {'приставной', 'кашпо', 'торшер', 'ковёр'}   # блок собирается и без них


def base(role: str) -> str:
    p = role.split(' ')
    return p[0] if p[-1].isdigit() else role


def main() -> None:
    idx = json.load(open(os.path.join(HERE, 'candidates-index.json')))
    items, index = idx['items'], idx['index']
    styles = json.load(open(os.path.join(HERE, 'style-scores.json')))

    # роль → список товаров (ключи индекса вида «роль|подтип|размерность»)
    by_role: dict[str, list] = {}
    for key, keys_list in index.items():
        role = key.split('|')[0]
        by_role.setdefault(role, []).extend(keys_list)

    def fits(it: dict, ideal: float, role: str) -> bool:
        # у ковров в фидах «w» — КОРОТКАЯ сторона (80×150): меряем длинную
        if base(role) == 'ковёр':
            w = max(float(it.get('w') or 0), float(it.get('d') or 0)) or None
        else:
            w = it.get('w') or it.get('dia')
        return bool(w) and ideal * ENV_LO <= float(w) <= ideal * ENV_HI

    def style_ok(k: str, st: str) -> bool:
        sc = styles.get(k.replace(':', '-'))
        if not sc:
            return False
        return bool(sc.get('universal')) or float(sc.get(st, 0)) >= STYLE_MIN

    rows = []
    for tname, slots in TEMPLATES.items():
        row = {'template': tname, 'styles': {}}
        for st in STYLES:
            per_slot, face_caps = {}, []
            for role, ideal in slots.items():
                b = base(role)
                cands = [k for k in by_role.get(b, [])
                         if k in items and fits(items[k], ideal, role) and style_ok(k, st)]
                per_slot[role] = len(cands)
                if b in FACE_ROLES:
                    face_caps.append(len(cands))
            # экземпляры одной роли («кресло», «кресло 2») делят один пул
            inst = {}
            for role in slots:
                inst[base(role)] = inst.get(base(role), 0) + 1
            enough = all(per_slot[r] >= inst[base(r)] for r in slots
                         if base(r) not in OPTIONAL)
            missing_opt = [r for r in slots
                           if base(r) in OPTIONAL and per_slot[r] < inst[base(r)]]
            # правило разнообразия: лицевой предмет не повторяется между сетами
            # внутри стиля → сколько РАЗНЫХ сетов даёт самый узкий лицевой слот
            variants = 0
            if enough and face_caps:
                variants = min(cnt // inst[base(r)]
                               for r, cnt in per_slot.items() if base(r) in FACE_ROLES)
            elif enough:
                variants = min(per_slot.values()) if per_slot else 0
            row['styles'][st] = {
                'ok': enough, 'variants': variants, 'missing_opt': missing_opt,
                'worst': min(per_slot.items(), key=lambda kv: kv[1]) if per_slot else None,
                'slots': per_slot,
            }
        rows.append(row)

    out = {'styles': STYLES, 'envelope': [ENV_LO, ENV_HI], 'rows': rows}
    json.dump(out, open(os.path.join(HERE, 'template-coverage.json'), 'w'),
              ensure_ascii=False, indent=1)

    print(f"конверт {int(ENV_LO*100)}–{int(ENV_HI*100)}% от идеала; порог стиля {STYLE_MIN}\n")
    hdr = f"{'шаблон':34s}" + ''.join(f"{s[:11]:>12s}" for s in STYLES)
    print(hdr)
    for r in rows:
        line = f"{r['template'][:34]:34s}"
        for st in STYLES:
            c = r['styles'][st]
            line += f"{(str(c['variants']) + ' сет' if c['ok'] else 'НЕТ'):>12s}"
        print(line)
    print('\nУзкие места (минимальный слот по каждому шаблону/стилю):')
    for r in rows:
        bad = [(st, c['worst']) for st, c in r['styles'].items()
               if not c['ok'] or c['variants'] <= 1]
        if bad:
            for st, w in bad[:6]:
                print(f"  {r['template'][:32]:32s} {st:14s} {w[0]}: {w[1]} шт")

    if '--publish' in sys.argv:
        publish(out)


def publish(out: dict) -> None:
    rows_html = ''
    for r in out['rows']:
        cells = ''
        for st in out['styles']:
            c = r['styles'][st]
            if not c['ok']:
                cells += (f"<td class='bad'>нет<br><small>{html.escape(str(c['worst'][0]))}: "
                          f"{c['worst'][1]}</small></td>")
            else:
                cls = 'good' if c['variants'] >= 3 else 'warn'
                extra = (' · без ' + ','.join(c.get('missing_opt', []))
                         if c.get('missing_opt') else '')
                cells += (f"<td class='{cls}'>{c['variants']} сет<br>"
                          f"<small>узкий: {html.escape(str(c['worst'][0]))} "
                          f"{c['worst'][1]}{html.escape(extra)}</small></td>")
        rows_html += f"<tr><th>{html.escape(r['template'])}</th>{cells}</tr>"
    hdr = ''.join(f"<th>{html.escape(s)}</th>" for s in out['styles'])
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><meta http-equiv="cache-control" content="no-cache">
<title>Покрытие шаблонов каталогом</title>
<style>body{{margin:0;background:#fff;color:#1A1F1C;font:16px/1.5 system-ui}}
.wrap{{max-width:1100px;margin:0 auto;padding:22px 14px 60px}}
h1{{font-size:21px}} table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{border:1px solid #EDEFEC;padding:6px 8px;text-align:center}}
th:first-child,td:first-child{{text-align:left}}
td.good{{background:#EAF6EE}} td.warn{{background:#FDF6E3}} td.bad{{background:#FBECE9}}
small{{color:#5C655E}}
.note{{margin:12px 0;padding:10px 12px;border-left:3px solid #3B76A2;background:#F4F7FA;font-size:14.5px}}
</style></head><body><div class="wrap">
<h1>Хватает ли мебели на шаблоны — по стилям</h1>
<div class="note">Конверт габаритов <b>−20% / +10%</b> от идеала слота; стилевой порог
{STYLE_MIN}/10. «N сет» — сколько РАЗНЫХ сетов даёт стиль с учётом правила разнообразия
(лицевой предмет — диван/кресло/столик/обеденный стол — не повторяется между сетами;
`compose2.overlap_ok`). Зелёный ≥3 сетов · жёлтый 1–2 · красный — слот пуст.</div>
<table><tr><th>Шаблон</th>{hdr}</tr>{rows_html}</table>
</div></body></html>"""
    dst = os.path.expanduser('~/scout-scenes/coverage-page')
    os.makedirs(dst, exist_ok=True)
    open(os.path.join(dst, 'index.html'), 'w').write(page)
    subprocess.run(['scp', '-q', os.path.join(dst, 'index.html'),
                    'root@89.167.127.0:/tmp/cov.html'], check=True)
    subprocess.run(['ssh', 'root@89.167.127.0',
                    'mkdir -p /opt/remlab/test/coverage && '
                    'mv /tmp/cov.html /opt/remlab/test/coverage/index.html'], check=True)
    print('опубликовано: /test/coverage/')


if __name__ == '__main__':
    main()
