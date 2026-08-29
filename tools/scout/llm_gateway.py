#!/usr/bin/env python3
"""Единая точка LLM-вызовов: Vercel AI Gateway по умолчанию, OpenAI напрямую — запасной.

Правило владельца 29.08: «Vercel — канал по умолчанию, там все модели; альтернативный канал —
OpenAI». Причина дня: прямой ключ OpenAI кончился («no credits remaining»), и добивка стилей
встала, при том что на шлюзе лежали кредиты. Один резолвер вместо ключей, разбросанных по
скриптам, значит: канал переключается в одном месте, и учёт расхода — тоже.

  from llm_gateway import chat
  out = chat('gpt-5-mini', messages, reasoning_effort='low')   # → полный ответ API

Модель называем БЕЗ префикса провайдера — префикс `openai/` добавляется для шлюза сам.
Повтор на 429/5xx с растущей паузой встроен: молчаливая деградация «не ответил → посчитали
без LLM» уже дважды портила кэш (уроки 320, 324).
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

GATEWAY_URL = 'https://ai-gateway.vercel.sh/v1/chat/completions'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v.strip()
    for p in (os.path.join(HERE, '.env'), os.path.join(HERE, '..', '..', '.env.local'),
              os.path.join(HERE, '..', '..', '.env'), '/home/pakar/mltest/.env'):
        try:
            for line in open(p, encoding='utf-8'):
                m = re.match(rf'{name}=(.+)', line.strip())
                if m:
                    return m.group(1).strip().strip('"\'')
        except OSError:
            continue
    return None


def chat(model: str, messages: list, timeout: int = 240, tries: int = 6, **extra) -> dict:
    """Один вызов chat/completions через канал по умолчанию, с повтором и фолбэком.

    Фолбэк на прямой OpenAI — только на ОШИБКИ КАНАЛА (нет ключа, 401/403 шлюза), не на 429:
    лимит темпа лечится паузой, а не сменой канала с другим биллингом.
    """
    routes = []
    gk = _env('VERCEL_AI_GATEWAY_KEY')
    if gk:
        routes.append((GATEWAY_URL, gk, f'openai/{model}' if '/' not in model else model))
    ok = _env('OPENAI_API_KEY')
    if ok:
        routes.append((OPENAI_URL, ok, model.split('/', 1)[-1]))
    if not routes:
        raise SystemExit('нет ни VERCEL_AI_GATEWAY_KEY, ни OPENAI_API_KEY')
    last = None
    for url, key, mname in routes:
        body = {'model': mname, 'messages': messages, **extra}
        for attempt in range(tries):
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
                if e.code in (401, 403, 404):
                    break                     # канал недоступен — пробуем следующий
                raise
    raise last or RuntimeError('LLM не ответил')
