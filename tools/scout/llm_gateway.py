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
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

GATEWAY_URL = 'https://ai-gateway.vercel.sh/v1/chat/completions'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'


def _env(name: str) -> str | None:
    """Ключ — `env_keys.get` (T-20261105-52): окружение → своё дерево → основная копия из worktree → чужой mltest с WARN."""
    import env_keys
    return env_keys.get(name)


def chat(model: str, messages: list, timeout: int = 240, tries: int = 6, direct_fallback: bool = True, **extra) -> dict:
    """Один вызов chat/completions через канал по умолчанию, с повтором и фолбэком.

    Фолбэк на прямой OpenAI — только на ОШИБКИ КАНАЛА (нет ключа, 401/403 шлюза), не на 429:
    лимит темпа лечится паузой, а не сменой канала с другим биллингом. `direct_fallback=False` — только шлюз
    (модели не OpenAI, `google/…`: прямой канал их не знает; деньги продукта — шлюз, ADR-0301; conv-15).
    """
    routes = []
    gk = _env('VERCEL_AI_GATEWAY_KEY')
    if gk:
        routes.append((GATEWAY_URL, gk, f'openai/{model}' if '/' not in model else model))
    ok = _env('OPENAI_API_KEY') if direct_fallback else None
    if ok:
        routes.append((OPENAI_URL, ok, model.split('/', 1)[-1]))
    if not routes:
        raise SystemExit('нет ни VERCEL_AI_GATEWAY_KEY, ни OPENAI_API_KEY' if direct_fallback else 'нет VERCEL_AI_GATEWAY_KEY')
    last = None
    broke = []                                # каналы без денег — в итоговую ошибку, чтобы её понял человек
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
                # НЕТ ДЕНЕГ — НЕ ТЕМП (13.10): шлюз Vercel при исчерпанном бюджете отвечает 402, OpenAI без
                # кредитов — 429 `insufficient_quota`. Раньше 402 ронял вызов без фолбэка, а 429 «без денег»
                # повторялся 6 раз с паузами до минуты — ночной шаг висел, ничего не делая.
                txt = ''
                try:
                    txt = e.read()[:600].decode(errors='replace')
                except Exception:  # noqa: BLE001 — тело ошибки необязательно
                    pass
                if e.code == 402 or (e.code == 429 and ('insufficient_quota' in txt or 'credit_balance' in txt)):
                    broke.append('шлюз Vercel' if url == GATEWAY_URL else 'OpenAI')
                    break
                if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
                if e.code in (401, 403, 404):
                    break                     # канал недоступен — пробуем следующий
                raise
    if broke and len(broke) == len(routes):
        raise NoCredits('нет денег на всех каналах LLM: ' + ', '.join(broke) + ' — нужно пополнение')
    raise last or RuntimeError('LLM не ответил')


class NoCredits(RuntimeError):
    """На всех каналах кончились деньги: повторять бессмысленно, нужен человек."""
