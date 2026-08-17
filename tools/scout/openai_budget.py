#!/usr/bin/env python3
"""Учёт стоимости запросов OpenAI и ДНЕВНОЙ ЛИМИТ (решение владельца 17.08: «не более $5 в день на все
модели, скажу если поднять»).

- `log_spend(model, usage, n, note, batch=False)` — токены каждого ответа → openai-spend.jsonl, доллары
  по rules/openai_prices.json (за 1M токенов; Batch API ×0.5). Нет цены модели → cost_usd=null и
  консервативная оценка по fallback_per_request_usd (лимит считает ХУДШИЙ случай, не выдумывает дешёвое).
- `spent_today()` — сумма за сегодня (UTC-дата сервера).
- `allow(model, n_req, batch, note)` — гейт ПЕРЕД отправкой: если потрачено + оценка партии > лимита →
  пишет причину, шлёт алерт в TG (alert.sh) и возвращает False; вызывающий обязан НЕ отправлять.
- CLI: `openai_budget.py --report [days]` (по дням/моделям), `--check <model> <n> [--batch]`.

Файл-рубильник openai.off (refresh_daily/enrich_wait) — отдельный уровень: он вообще выключает платные шаги.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPEND_LOG = os.path.join(HERE, 'openai-spend.jsonl')
PRICES = os.path.join(HERE, 'rules', 'openai_prices.json')


def _cfg() -> dict:
    try:
        return json.load(open(PRICES, encoding='utf-8'))
    except Exception:
        return {'daily_cap_usd': 5.0, 'models': {}, 'fallback_per_request_usd': 0.10}


def price_of(model: str, pt: int, ct: int, batch: bool = False) -> float | None:
    m = (_cfg().get('models') or {}).get(model)
    if not m or m.get('input_per_1m') is None or m.get('output_per_1m') is None:
        return None
    k = 0.5 if batch else 1.0
    return round(k * (pt / 1e6 * float(m['input_per_1m']) + ct / 1e6 * float(m['output_per_1m'])), 6)


def estimate_request(model: str, batch: bool = False) -> float:
    """Оценка ОДНОГО запроса до отправки: типовые токены модели из конфига (typical_prompt/typical_output),
    иначе fallback_per_request_usd (консервативно)."""
    c = _cfg(); m = (c.get('models') or {}).get(model) or {}
    pt, ct = m.get('typical_prompt_tokens'), m.get('typical_output_tokens')
    if pt and ct:
        p = price_of(model, int(pt), int(ct), batch)
        if p is not None:
            return p
    return float(m.get('fallback_per_request_usd') or c.get('fallback_per_request_usd') or 0.10)


def log_spend(model: str, usage: dict | None, n_req: int = 1, note: str = '', batch: bool = False) -> None:
    try:
        u = usage or {}
        pt = int(u.get('prompt_tokens') or u.get('input_tokens') or 0)
        ct = int(u.get('completion_tokens') or u.get('output_tokens') or 0)
        cost = price_of(model, pt, ct, batch) if (pt or ct) else None
        est = None if cost is not None else round(estimate_request(model, batch) * n_req, 6)
        with open(SPEND_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': time.strftime('%Y-%m-%d %H:%M'), 'model': model, 'n': n_req, 'batch': bool(batch),
                                'prompt_tokens': pt, 'completion_tokens': ct, 'cost_usd': cost, 'est_usd': est,
                                'note': note}, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _rows(days: int) -> list[dict]:
    if not os.path.exists(SPEND_LOG):
        return []
    since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    out = []
    for line in open(SPEND_LOG, encoding='utf-8'):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get('ts', '')[:10] >= since:
            out.append(r)
    return out


def spent_today() -> float:
    today = _dt.date.today().isoformat()
    return round(sum((r.get('cost_usd') if r.get('cost_usd') is not None else (r.get('est_usd') or 0.0))
                     for r in _rows(0) if r.get('ts', '')[:10] == today), 4)


def allow(model: str, n_req: int, batch: bool = False, note: str = '') -> bool:
    cap = float(_cfg().get('daily_cap_usd') or 5.0)
    spent = spent_today()
    plan = round(estimate_request(model, batch) * max(1, n_req), 4)
    if spent + plan > cap:
        msg = (f'OpenAI дневной лимит ${cap:.2f}: потрачено ${spent:.2f}, партия {note or model} '
               f'({n_req} запр., {model}{", batch" if batch else ""}) ≈ ${plan:.2f} — ОТПРАВКА ОТМЕНЕНА')
        print(msg)
        try:
            subprocess.run(['bash', os.path.join(HERE, 'alert.sh'), 'remlab: ' + msg], timeout=30)
        except Exception:
            pass
        with open(SPEND_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': time.strftime('%Y-%m-%d %H:%M'), 'model': model, 'n': 0, 'blocked': True,
                                'planned_usd': plan, 'note': note}, ensure_ascii=False) + '\n')
        return False
    print(f'бюджет OpenAI: потрачено сегодня ${spent:.2f} + партия ≈ ${plan:.2f} ≤ ${cap:.2f} — ок')
    return True


def report(days: int = 7) -> None:
    rows = _rows(days)
    if not rows:
        print('openai-spend.jsonl пуст за период — расходов через конвейер не было')
        return
    by: dict = {}
    for r in rows:
        if r.get('blocked'):
            print(f"  {r['ts']} БЛОК лимита: {r.get('note')} ≈ ${r.get('planned_usd')}")
            continue
        k = (r['ts'][:10], r['model'])
        d = by.setdefault(k, {'n': 0, 'pt': 0, 'ct': 0, 'usd': 0.0, 'est': 0.0})
        d['n'] += r.get('n', 1); d['pt'] += r.get('prompt_tokens', 0); d['ct'] += r.get('completion_tokens', 0)
        if r.get('cost_usd') is not None:
            d['usd'] += r['cost_usd']
        else:
            d['est'] += r.get('est_usd') or 0.0
    print('date       model             req   prompt_tok  compl_tok      usd (факт)   usd (оценка)')
    tot = 0.0
    for (dte, m), d in sorted(by.items()):
        tot += d['usd'] + d['est']
        print(f"{dte} {m:16} {d['n']:>6} {d['pt']:>11} {d['ct']:>10}   {d['usd']:>10.3f}   {d['est']:>10.3f}")
    print(f'итого за {days} дн.: ≈ ${tot:.2f}; лимит в день: ${float(_cfg().get("daily_cap_usd") or 5):.2f}; сегодня: ${spent_today():.2f}')


if __name__ == '__main__':
    a = sys.argv
    if '--report' in a:
        i = a.index('--report'); report(int(a[i + 1]) if len(a) > i + 1 and a[i + 1].isdigit() else 7)
    elif '--check' in a:
        i = a.index('--check'); ok = allow(a[i + 1], int(a[i + 2]), '--batch' in a, 'check'); sys.exit(0 if ok else 2)
    else:
        print(__doc__)
