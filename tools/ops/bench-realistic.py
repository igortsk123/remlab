#!/usr/bin/env python3
"""Сравнение моделей картинок для «Сделать реалистичнее» (владелец 17.10): тот же конвейер (лист из двух видов →
модель → резка на два вида), по ОДНОМУ прогону на модель, замер времени модели и денег шлюза, картинки на прод (/test/share/frames).
ПЛАТНО. Запуск: ~/venvs/scout/bin/python tools/ops/bench-realistic.py <payload.json> <out_dir> [model ...]
"""
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..', 'scout')
sys.path.insert(0, SCOUT)
os.chdir(SCOUT)
import draft_render as DR  # noqa: E402

DEFAULT = ['openai/gpt-image-2', 'google/gemini-3.1-flash-image', 'google/gemini-nano-banana-2.1',
           'google/gemini-3-pro-image', 'google/gemini-2.5-flash-image', 'openai/gpt-image-2.5-flare']


def credits():
    try:
        return DR.gw_credits(max_age_s=0)
    except Exception:  # noqa: BLE001
        return None


def main():
    payload = json.load(open(sys.argv[1], encoding='utf-8'))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    models = sys.argv[3:] or DEFAULT
    rows = []
    for m in models:
        DR.REALISTIC_MODEL = m
        tag = m.replace('/', '_')
        bal0 = credits()
        t0 = time.time()
        row = {'model': m, 'balance_before': bal0}
        try:
            res = DR.render(layout=payload, quality='realistic', save_prefix=os.path.join(out, tag))
            row.update({'ok': True, 'total_s': round(time.time() - t0, 1),
                        'shots': [s.get('url') for s in res.get('shots', [])], 'sources': res.get('sources')})
        except BaseException as e:  # noqa: BLE001 — SystemExit тоже ловим: одна модель не должна ронять остальные
            row.update({'ok': False, 'total_s': round(time.time() - t0, 1), 'error': str(e)[:300]})
            traceback.print_exc()
        bal1 = credits()
        row['balance_after'] = bal1
        row['cost_usd'] = round(bal0 - bal1, 4) if isinstance(bal0, (int, float)) and isinstance(bal1, (int, float)) else None
        rows.append(row)
        print('РЕЗУЛЬТАТ', json.dumps(row, ensure_ascii=False), flush=True)
        json.dump(rows, open(os.path.join(out, 'bench.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\nИТОГО')
    for r in rows:
        print(f"{r['model']:40} {'ok ' if r.get('ok') else 'ОШИБКА'} {r.get('total_s')} с  ${r.get('cost_usd')}  {r.get('error', '')[:80]}")


if __name__ == '__main__':
    main()
