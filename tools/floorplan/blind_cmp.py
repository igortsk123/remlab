#!/usr/bin/env python3
"""Сравнение слепого прогона с эталоном (T-20261109-04) — только ПОСЛЕ прогона, для настройки не используется.
  python tools/floorplan/blind_cmp.py <run-папка> <план> <эталон: X-dims.txt | gold/X.json> → печать и <run>/cmp-<план>.txt

Эталон-текст: строки «имя | лист | стороны | заметка»; стороны «3.77 x 4.20» (или футы), «-» — не читается,
«~» — неуверенно. Сопоставление по ключу имени (`listing.norm_name`); одинаковых имён несколько — по ближайшему
размеру и листу, один-к-одному; близкие альтернативы — «неоднозначно». Корзины — по наибольшей ошибке стороны
(порядок сторон не важен): ≤15 / 15–25 / >25 с флагом / >25 без флага (молча неверно) / не измерено."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import listing  # noqa: E402


def parse_sides(txt: str):
    """→ (стороны (a, b) м | None, неуверенно, не читается)."""
    t = txt.strip()
    unsure = '~' in t or '?' in t
    if not t or re.fullmatch(r'[-–—\s?]+', t):
        return None, unsure, True
    r = listing.parse_line('x ' + t.replace('~', ''))
    if r:
        return tuple(r['dims_m']), unsure, False
    nums = [float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', t)]
    if len(nums) >= 2 and all(0.3 <= v <= 40 for v in nums[:2]):
        return (nums[0], nums[1]), unsure, False
    return None, unsure, True


def load_ref(path: Path) -> list[dict]:
    out = []
    if path.suffix == '.json':
        for g in json.loads(path.read_text())['rooms']:
            name = re.sub(r'\s+\d+(?:\.\d+)?x\d+(?:\.\d+)?$', '', g['name'])     # «Bedroom 3.12x3.45» → «Bedroom»
            out.append({'name': name, 'sheet': g.get('panel', ''), 'sides': tuple(g['dims_m']) if g.get('dims_m') else None,
                        'unsure': False, 'unreadable': 'dims_m' not in g, 'note': ''})
        return out
    for line in path.read_text(errors='replace').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '|' not in line:
            continue
        f = [x.strip() for x in line.split('|')] + ['', '', '']
        if f[0].lower() in ('имя', 'name', 'комната'):
            continue
        sides, unsure, unread = parse_sides(f[2])
        out.append({'name': f[0], 'sheet': f[1], 'sides': sides, 'unsure': unsure, 'unreadable': unread, 'note': f[3]})
    return out


def load_ours(run: Path, plan: str) -> tuple[list[dict], dict]:
    met = json.loads((run / plan / f'metrics-{plan}.json').read_text())
    gold = json.loads((run / plan / f'gold-{plan}.json').read_text())
    by = {g['name']: g for g in gold['rooms']}
    rows, seen = [], set()
    extra = {'pieces': 0, 'unnamed': 0, 'panels': len(met['panels'])}
    for p in met['panels']:
        t = p['topology']
        extra['pieces'] += t.get('extra_rooms', 0)
        extra['unnamed'] += len(t.get('extra_unnamed_m2', []))
        for d in p.get('dims', []):
            g = by.get(d['id'], {})
            seen.add(d['id'])
            flagged = bool(d.get('flag_level')) or bool(g.get('text_flags')) or bool(g.get('unsure'))
            rows.append({'name': g.get('name0', d['id']), 'id': d['id'], 'panel': p['panel'],
                         'label': tuple(d['gold']) if d.get('gold') else None, 'src': g.get('dims_src'),
                         'ours': tuple(d['ours']) if 'ours' in d else None, 'status': d['status'], 'flagged': flagged,
                         'flags': ([d['flag']] if d.get('flag_level') else []) + g.get('text_flags', [])
                         + (['VLM не уверен'] if g.get('unsure') else [])})
    for g in gold['rooms']:
        if g['name'] not in seen:
            rows.append({'name': g.get('name0', g['name']), 'id': g['name'], 'panel': g['panel'],
                         'label': tuple(g['dims_m']) if g.get('dims_m') else None, 'src': g.get('dims_src'), 'ours': None,
                         'status': 'комната не найдена', 'flagged': True, 'flags': g.get('text_flags', [])})
    return rows, extra


def err(a, b):
    """Наибольшая ошибка стороны, м, при лучшем порядке сторон."""
    return min(max(abs(a[0] - b[0]), abs(a[1] - b[1])), max(abs(a[0] - b[1]), abs(a[1] - b[0])))


def sheet_pen(ref_sheet: str, panel: str) -> float:
    a, b = set(listing.norm_name(ref_sheet).split()), set(listing.norm_name(panel).split())
    return 0.0 if not a or (a & b) else 0.5


def pair(refs: list[dict], ours: list[dict]):
    """Один-к-одному: по ключу имени; среди одноимённых — наименьшая (ошибка размера + штраф листа)."""
    cand = []
    for i, r in enumerate(refs):
        k = listing.norm_name(r['name'])
        same = [j for j, o in enumerate(ours) if listing.norm_name(o['name']) == k]
        for j in same:
            o = ours[j]
            s = o['label'] or o['ours']
            d = err(r['sides'], s) if (r['sides'] and s) else 1.0
            cand.append((d + sheet_pen(r['sheet'], o['panel']), i, j, len(same)))
    cand.sort()
    ri, oj, res = set(), set(), {}
    for c, i, j, n in cand:
        if i in ri or j in oj:
            continue
        alt = [x for x in cand if x[1] == i and x[2] != j and x[2] not in oj]
        amb = n > 1 and (not alt or alt[0][0] - c < 0.3)
        res[i] = (j, amb)
        ri.add(i); oj.add(j)
    return res, [j for j in range(len(ours)) if j not in oj]


def main():
    run, plan, refp = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    refs = load_ref(refp)
    ours, extra = load_ours(run, plan)
    res, unpaired = pair(refs, ours)
    bk = {'≤15': 0, '15–25': 0, '>25 с флагом': 0, '>25 без флага': 0, 'не измерено': 0}
    n_sized = n_unread = n_read_ok = n_amb = 0
    lines = [f'{plan}: эталон {refp.name} — имя | лист | эталон | наше имя | подпись прочитана (источник) | наше | ошибка | корзина | флаги']
    for i, r in enumerate(refs):
        j, amb = res.get(i, (None, False))
        o = ours[j] if j is not None else None
        ref_s = (f'{r["sides"][0]:.2f}×{r["sides"][1]:.2f}' + ('~' if r['unsure'] else '')) if r['sides'] else '-'
        if r['sides']:
            n_sized += 1
        b, e_txt = '', ''
        if r['sides'] is None:
            b = 'эталон не читается'
        elif o is None or o['ours'] is None:
            b = 'не измерено'
            bk[b] += 1
        else:
            e = err(r['sides'], o['ours'])
            e_txt = f'{round(100 * e)} см'
            b = '≤15' if e <= 0.15 else '15–25' if e <= 0.25 else '>25 с флагом' if o['flagged'] else '>25 без флага'
            bk[b] += 1
        if r['sides'] and (o is None or o['label'] is None):
            n_unread += 1
        if r['sides'] and o is not None and o['label'] and err(r['sides'], o['label']) <= max(0.05, 0.02 * max(r['sides'])):
            n_read_ok += 1
        n_amb += int(amb)
        lab = (f'{o["label"][0]:.2f}×{o["label"][1]:.2f} ({o["src"]})' if o and o['label'] else 'нет') if o else '—'
        our = f'{o["ours"][0]:.2f}×{o["ours"][1]:.2f}' if o and o['ours'] else (o['status'] if o else 'нет пары')
        lines.append(f'{r["name"]:<24} | {r["sheet"][:14]:<14} | {ref_s:<11} | {(o["id"] if o else "—"):<24} | {lab:<22} | '
                     f'{our:<11} | {e_txt:<6} | {b}{" · неоднозначно" if amb else ""}'
                     + (f' · {"; ".join(o["flags"])}' if o and o['flags'] else ''))
    for j in unpaired:
        o = ours[j]
        lines.append(f'(лишняя подпись) {o["id"]} | {o["panel"]} | подпись {o["label"]} | наше {o["ours"]} | {o["status"]}')
    summ = {'эталон комнат': len(refs), 'с размером': n_sized, 'найдено пар': len(res), 'корзины': bk,
            'молча неверных': bk['>25 без флага'], 'не прочитал размер': n_unread, 'подпись прочитана верно': n_read_ok,
            'неоднозначных пар': n_amb, 'наших подписей без пары': len(unpaired), 'лишних кусков': extra['pieces'],
            'из них без имени': extra['unnamed'], 'панелей': extra['panels']}
    lines.append('ИТОГ ' + json.dumps(summ, ensure_ascii=False))
    text = '\n'.join(lines)
    (run / f'cmp-{plan}.txt').write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
