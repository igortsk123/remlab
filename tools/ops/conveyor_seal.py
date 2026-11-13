"""ПЕЧАТЬ СОБРАННОГО ФАЙЛА (T-20261112-121, план conveyor-guards-01 шаг 2; владелец TG 1366/1370: «любые ручные правки пресекать»).

Собранный файл в git, который в CI не пересобрать (вход — живая витрина или фото вне репо), генератор пишет с печатью: ключ
`"_seal": "<sha256>"` — хеш текста файла, где значение печати пустое. Ручная правка любого байта ломает печать → красный
`tools/ops/conveyor_check.py` (CI, prepush). Пара для node — `tools/ops/conveyor-seal.mjs` (тот же алгоритм, по тексту, не по
JSON: числа и порядок ключей у python и node пишутся по-разному).

    from conveyor_seal import dump_sealed       # dump_sealed(payload, path) — payload с ключом '_seal'
"""
import hashlib
import json
import os
import re

SEAL = re.compile(r'"_seal":\s*"([0-9a-f]*)"')


def seal_text(text: str) -> str:
    """Текст с проставленной печатью. Ключ `_seal` в тексте обязателен."""
    m = SEAL.search(text)
    if not m:
        raise ValueError('в тексте нет ключа "_seal" — генератор обязан его писать')
    blank = text[:m.start(1)] + text[m.end(1):]
    return blank[:m.start(1)] + hashlib.sha256(blank.encode('utf-8')).hexdigest() + blank[m.start(1):]


def verify_text(text: str):
    """True — печать цела; False — сломана (ручная правка); None — печати нет."""
    m = SEAL.search(text)
    if not m:
        return None
    return seal_text(text) == text


def with_seal(payload: dict) -> dict:
    """Тот же словарь с ключом `_seal` сразу после `_about` (или первым)."""
    out, put = {}, False
    for k, v in payload.items():
        if k == '_seal':
            continue
        out[k] = v
        if k == '_about':
            out['_seal'], put = '', True
    return out if put else {'_seal': '', **out}


def dump_sealed(payload: dict, path: str) -> None:
    """Записать JSON (indent 1, как раньше) с печатью — атомарно (временный файл рядом + os.replace)."""
    text = seal_text(json.dumps(with_seal(payload), ensure_ascii=False, indent=1) + '\n')
    tmp = f'{path}.tmp{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(text)
    os.replace(tmp, path)
