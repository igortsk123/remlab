"""Таблица размеров по каждой подписанной комнате: подпись A×B → наше A×B, разница в см или почему не измерена.
Запуск: python tools/floorplan/dims.py <run-папка> [A B C] → печать и <run>/dims.txt (T-20261109-02/3)."""
import json
import sys
from pathlib import Path

GOLD = Path(__file__).resolve().parent / 'gold'


def table(run: Path, plan: str) -> tuple[list[str], dict]:
    gold = json.loads((GOLD / f'{plan}.json').read_text())
    met = json.loads((run / plan / f'metrics-{plan}.json').read_text())
    rows = {}
    for p in met['panels']:
        for d in p.get('dims', []):
            rows[d['id']] = (p['panel'], d)
    lines, cnt = [], {'всего': 0, 'измерено': 0, 'не измерено': 0}
    bk = {'≤15': 0, '15–25': 0, '>25 с флагом': 0, '>25 без флага': 0, 'не измерено': 0, 'плохих': 0,
          'плохих без флага': 0}
    for g in gold['rooms']:
        if 'dims_m' not in g:
            continue
        cnt['всего'] += 1
        a, b = g['dims_m']
        lab = f'{a:.2f}×{b:.2f}'
        if g['name'] not in rows:
            lines.append(f'{plan} | {g["panel"]:<12} | {g["name"]:<24} | {lab:>11} | не измерена: не попала в панель')
            cnt['не измерено'] += 1
            bk['не измерено'] += 1
            continue
        pan, d = rows[g['name']]
        fl = d.get('flag_level', 0) or 0
        ftxt = f' · флаг: {d["flag"]}' if fl else ''
        if 'ours' in d:
            oa, ob = d['ours']
            da, db = d['diff_cm']
            scale = 'по остальным комнатам' if d['status'] == 'loo' else 'масштаб листа'
            lines.append(f'{plan} | {pan:<12} | {g["name"]:<24} | {lab:>11} | {oa:.2f}×{ob:.2f} | {da:+d} / {db:+d} см ({scale})'
                         + ftxt)
            cnt['измерено'] += 1
            e = max(abs(da), abs(db))
            if e <= 15:
                bk['≤15'] += 1
            elif e <= 25:
                bk['15–25'] += 1
            elif fl:
                bk['>25 с флагом'] += 1
            else:
                bk['>25 без флага'] += 1
            if e > max(25, 5 * max(a, b)):        # критерий этапа 2: > max(0,25 м; 5 %)
                bk['плохих'] += 1
                bk['плохих без флага'] += 0 if fl else 1
        else:
            lines.append(f'{plan} | {pan:<12} | {g["name"]:<24} | {lab:>11} | не измерена: {d["status"]}' + ftxt)
            cnt['не измерено'] += 1
            bk['не измерено'] += 1
    cnt['корзины'] = bk
    return lines, cnt


def main():
    run = Path(sys.argv[1])
    plans = sys.argv[2:] or ['A', 'B', 'C']
    out = ['план | панель | комната | подпись | наше | разница (сторона 1 / сторона 2)']
    for plan in plans:
        lines, cnt = table(run, plan)
        out += lines
        out.append(f'{plan}: подписанных {cnt["всего"]}, измерено {cnt["измерено"]}, не измерено {cnt["не измерено"]}')
        out.append(f'{plan} корзины (наибольшая сторона): ' + ', '.join(f'{k} {v}' for k, v in cnt['корзины'].items()))
        out.append('')
    text = '\n'.join(out)
    (run / 'dims.txt').write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
