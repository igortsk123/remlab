#!/usr/bin/env python3
"""ЦЕНА ПЛАТНОГО AI-ФОТО по журналу `~/scout-scenes/photo-cost.jsonl` (T-20261109-28): последние N удачных кадров — каждый
(время, метка, модель, размер, $), среднее/мин/макс в $ и ₽ по курсу ЦБ. Запись пишет `draft_render._photo_cost` на каждый вызов
шлюза картинок; цена — разница баланса ключа до/после (`balance_delta`). Кадры с пересечением (`overlap`: параллельно шёл другой
платный вызов — в том же процессе по счётчику или в другом по окнам времени в журнале) — отдельным списком, в среднее не входят.

    python tools/ops/photo-cost.py                 # последние 10, все метки
    python tools/ops/photo-cost.py 10 --label demo # только кадры /demo
    python tools/ops/photo-cost.py --rub 92.5      # курс руками (нет сети)
    python tools/ops/photo-cost.py --file путь.jsonl
"""
import argparse
import json
import os
import sys
import urllib.request

LOG = os.environ.get('PHOTO_COST_LOG', os.path.expanduser('~/scout-scenes/photo-cost.jsonl'))
CBR_URL = 'https://www.cbr-xml-daily.ru/daily_json.js'
SETTLE_S = 2.5          # окно записи после ответа, если замер ПОСЛЕ не записан (как `_PC_SETTLE_S` в draft_render)


def load(path: str) -> list:
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError as e:
                    print(f'строка {i} журнала не JSON — пропущена ({e})', file=sys.stderr)
    except FileNotFoundError:
        pass
    return out


def window(r: dict):
    """Окно, в которое разница баланса записи могла поймать чужое списание: старт запроса → замер ПОСЛЕ."""
    t0 = r.get('t_start')
    t1 = r.get('t_bal1') or ((r.get('t_end') or t0 or 0) + SETTLE_S)
    return (t0, t1) if t0 is not None else None


def mark_overlaps(recs: list) -> None:
    """`overlap_any` = своя пометка процесса ИЛИ окно пересекается с окном другой записи журнала (другой процесс)."""
    ws = [window(r) for r in recs]
    order = sorted((w[0], w[1], i) for i, w in enumerate(ws) if w)
    for r in recs:
        r['overlap_any'] = bool(r.get('overlap'))
    for a in range(len(order)):
        s0, e0, i = order[a]
        for b in range(a + 1, len(order)):
            s1, e1, j = order[b]
            if s1 >= e0:
                break
            recs[i]['overlap_any'] = recs[j]['overlap_any'] = True


def cbr_usd(timeout: float = 6.0):
    try:
        with urllib.request.urlopen(CBR_URL, timeout=timeout) as r:
            j = json.loads(r.read().decode('utf-8'))
        return float(j['Valute']['USD']['Value']), str(j.get('Date', ''))[:10]
    except Exception as e:  # noqa: BLE001 — нет сети: отчёт в $ без ₽, причина видна
        print(f'курс ЦБ не получен ({type(e).__name__}: {e}) — укажите --rub', file=sys.stderr)
        return None, None


def summarize(recs: list, n: int = 10, label=None) -> dict:
    """Последние n удачных записей (с меткой `label`, если дана) → {'rows', 'clean', 'overlap', 'no_cost', 'mean', 'min', 'max'}."""
    mark_overlaps(recs)
    rows = [r for r in recs if r.get('ok') and (label is None or r.get('label') == label)][-n:] if n > 0 else []
    clean = [r for r in rows if not r['overlap_any'] and isinstance(r.get('cost_usd'), (int, float))]
    costs = [float(r['cost_usd']) for r in clean]
    return {'rows': rows, 'clean': clean,
            'overlap': [r for r in rows if r['overlap_any']],
            'no_cost': [r for r in rows if not r['overlap_any'] and not isinstance(r.get('cost_usd'), (int, float))],
            'mean': sum(costs) / len(costs) if costs else None,
            'min': min(costs) if costs else None, 'max': max(costs) if costs else None}


def _money(usd, rub_rate) -> str:
    if usd is None:
        return '—'
    return f'${usd:.4f}' + (f' ≈ {usd * rub_rate:.2f} ₽' if rub_rate else '')


def _row(r: dict, rub_rate) -> str:
    cost = r.get('cost_usd')
    extra = []
    if r.get('gateway_cost_usd') is not None:
        extra.append(f"шлюз ${r['gateway_cost_usd']:.4f}")
    if r.get('usage'):
        u = r['usage']
        extra.append('токены ' + ('/'.join(str(u.get(k)) for k in ('input_tokens', 'output_tokens', 'total_tokens') if k in u)
                                   if isinstance(u, dict) else str(u)[:40]))
    if r.get('cost_note') and cost is None:
        extra.append(r['cost_note'])
    return (f"  {r.get('ts', '?')}  {r.get('label', '?'):<8} {r.get('model', '?')}  {r.get('size', '?')}/{r.get('quality', '?')}"
            f"  {r.get('dur_s', '?')} с  {_money(cost, rub_rate)}" + (f"  [{'; '.join(extra)}]" if extra else ''))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Цена платного AI-фото по журналу photo-cost.jsonl')
    ap.add_argument('n', nargs='?', type=int, default=10, help='сколько последних удачных кадров (10)')
    ap.add_argument('--label', help='только эта метка: demo / hero / …')
    ap.add_argument('--rub', type=float, help='курс ₽ за $ руками (иначе — ЦБ)')
    ap.add_argument('--file', default=LOG, help=f'журнал (по умолчанию {LOG})')
    a = ap.parse_args(argv)
    recs = load(a.file)
    if not recs:
        print(f'журнал пуст или его нет: {a.file}')
        return 1
    s = summarize(recs, a.n, a.label)
    rate, rate_date = (a.rub, 'руками') if a.rub else cbr_usd()
    print(f"Журнал {a.file}: записей {len(recs)}; последние {len(s['rows'])} удачных"
          + (f" с меткой «{a.label}»" if a.label else '') + (f'; курс {rate:.4f} ₽/$ ({rate_date})' if rate else ''))
    print('Кадры в среднем:')
    for r in s['clean']:
        print(_row(r, rate))
    if s['overlap']:
        print('С пересечением (параллельно шёл другой платный вызов — разница баланса общая), в среднее НЕ входят:')
        for r in s['overlap']:
            print(_row(r, rate))
    if s['no_cost']:
        print('Без цены (баланс не узнан или не успел измениться), в среднее НЕ входят:')
        for r in s['no_cost']:
            print(_row(r, rate))
    if s['mean'] is None:
        print('Итог: чистых кадров с ценой нет — среднее не посчитать.')
        return 2
    print(f"Итог по {len(s['clean'])} кадр.: среднее {_money(s['mean'], rate)}; мин {_money(s['min'], rate)}; "
          f"макс {_money(s['max'], rate)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
