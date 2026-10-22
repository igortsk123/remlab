#!/usr/bin/env python3
"""Карантин ВХОДА меша: фото товара, которое магазин не отдаёт, не гоняем по машинам повторно.

ЗАЧЕМ (T-20261022-10 Г, владелец 22.10). `input_failed` с «HTTP Error 403: Forbidden» классифицируется как
«непонятно» (`node_health.classify`): задание возвращается в очередь, едет на другую машину и снова платит
за её время. 22.10 один товар (99272:15853195173478605519) так прошёл через четыре машины. 403 — ответ
сервера магазина (сеть машины в порядке), но может быть и временным, поэтому не «навсегда», а карантин
с повторной проверкой.

Правила — `rules/mesh-input.json`: `after_n` ответов подряд с одной из `forbidden_marks` по одному товару →
карантин на `recheck_h` часов. Состояние — `~/scout-scenes/mesh-input-quarantine.json` (вне git), запись
атомарная. Карантинное задание прогон закрывает сам, без машины (`ssh_run.Jobs.preclose`, статус
`input_quarantined` — терминальный, курсор идёт дальше); по истечении срока `release_due` один раз отдаёт
задание в спул повторов: снова запрет — снова карантин (серия уже набрана), готовый меш — запись снимается.

403 БЫВАЕТ ВИНОЙ МАШИНЫ (T-20261022-13): 22.10 машина 65141c32 получила 403 на 5 разных товарах подряд, другая машина
их сделала — магазин не пускал её адрес. `node_after_n` разных товаров с запретом подряд на одной машине (без скачанного
фото между ними, `fetched`) — уходит машина (`ssh_run.reject_node`), а запреты из этой серии с товаров снимаются (`forgive`).
"""
from __future__ import annotations

import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.environ.get('MESH_INPUT_RULES') or os.path.join(HERE, '..', 'rules', 'mesh-input.json')
STATE = os.environ.get('MESH_INPUT_QUARANTINE') or os.path.expanduser('~/scout-scenes/mesh-input-quarantine.json')
STATUS = 'input_quarantined'
_lock = threading.Lock()
_rules: dict | None = None


def rules() -> dict:
    global _rules
    if _rules is None:
        try:
            with open(RULES, encoding='utf-8') as f:
                _rules = json.load(f)
        except (OSError, ValueError) as e:
            print(f'  !! {RULES} не читается ({type(e).__name__}) — карантин входа выключен', flush=True)
            _rules = {}
    return _rules


def _load() -> dict:
    try:
        with open(STATE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        # битый файл — не повод ронять прогон; худшее — лишний повтор за деньги, но не потеря задания
        print(f'  !! {STATE} не читается ({type(e).__name__}) — карантин входа пуст', flush=True)
        return {}


def _save(d: dict) -> None:
    tmp = STATE + '.tmp'
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE)
    except OSError as e:
        print(f'  !! {STATE}: не записан ({type(e).__name__}) — карантин входа не сохранён', flush=True)


def forbidden(res: dict) -> bool:
    """Отказ входа с запретом сервера (403 и т. п. из правил)."""
    if (res or {}).get('status') != 'input_failed':
        return False
    err = str((res or {}).get('error') or '').lower()
    return any(m in err for m in (rules().get('forbidden_marks') or []))


# Фото скачано: генерация шла (успех или содержательный отказ) — машине магазин фото отдаёт, её серия 403 рвётся.
# `cached` — нет: готовый меш берётся из приёмника без загрузки фото, про доступ машины к магазину он ничего не говорит.
FETCHED = frozenset({'ok', 'failed', 'flat_shape', 'bad_cutout', 'slab_suspect'})


def node_after_n() -> int:
    """Сколько РАЗНЫХ товаров подряд с запретом на одной машине — уже вина машины, а не товаров (0 — выключено)."""
    return int(rules().get('node_after_n') or 0)


def fetched(res: dict) -> bool:
    return (res or {}).get('status') in FETCHED


def forgive(sku: str) -> bool:
    """Снять с товара один запрет: его дала машина (T-20261022-13 — серия 403 на разных товарах одной машины),
    а не магазин. Карантин, который этот запрет довёл до порога, снимается. True — товар был в карантине."""
    with _lock:
        d = _load()
        e = d.get(sku or '')
        if not e:
            return False
        was = bool(e.get('until'))
        e['streak'] = int(e.get('streak', 0)) - 1
        if e['streak'] <= 0:
            d.pop(sku)
        elif e['streak'] < int(rules().get('after_n') or 0):
            e.pop('until', None)
            e.pop('released_at', None)
        _save(d)
        return was and not (sku in d and d[sku].get('until'))


def note(job: dict, res: dict, now: float | None = None) -> float:
    """Учесть результат задания. Возвращает срок карантина (unix), если товар ТОЛЬКО ЧТО в него ушёл, иначе 0.
    Готовый меш снимает запись; запрет растит серию; прочие исходы (обрыв машины, таймаут) серию не трогают."""
    sku = (job or {}).get('sku')
    n_max = int(rules().get('after_n') or 0)
    if not sku or n_max <= 0:
        return 0.0
    now = time.time() if now is None else now
    st = (res or {}).get('status')
    with _lock:
        d = _load()
        if st in ('ok', 'cached'):
            if sku in d:
                d.pop(sku)
                _save(d)
            return 0.0
        if not forbidden(res):
            return 0.0
        e = d.setdefault(sku, {'streak': 0, 'first_at': round(now)})
        e['streak'] = int(e.get('streak', 0)) + 1
        e['last_at'] = round(now)
        e['error'] = str((res or {}).get('error') or '')[:160]
        e['job'] = {k: v for k, v in (job or {}).items() if k != '_retries'}
        until = 0.0
        if e['streak'] >= n_max:
            until = now + float(rules().get('recheck_h') or 24) * 3600
            e['until'] = round(until)
            e.pop('released_at', None)
        _save(d)
        return until


def quarantined(sku: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    e = _load().get(sku or '')
    return bool(e and float(e.get('until') or 0) > now)


def active(now: float | None = None) -> set:
    """Товары в карантине сейчас."""
    now = time.time() if now is None else now
    return {k for k, e in _load().items() if float(e.get('until') or 0) > now}


def release_due(now: float | None = None, skip: set | frozenset = frozenset()) -> list[dict]:
    """Задания, чей срок карантина вышел и которые ещё не отданы на проверку: помечаются `released_at` и
    возвращаются (вызывающий кладёт их в спул повторов). Серия остаётся — новый запрет вернёт карантин сразу.
    `skip` — товары, которые и так идут в текущем прогоне: помечаются, но не возвращаются (иначе проверка вдвойне)."""
    now = time.time() if now is None else now
    out = []
    with _lock:
        d = _load()
        hit = False
        for sku, e in d.items():
            if e.get('until') and float(e['until']) <= now and not e.get('released_at') and e.get('job'):
                e['released_at'] = round(now)
                hit = True
                if sku not in skip:
                    out.append(dict(e['job']))
        if hit:
            _save(d)
    return out
