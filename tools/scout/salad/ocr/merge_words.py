#!/usr/bin/env python3
"""СЛИЯНИЕ строк кэша слов в words_flags.json (T-176/ocr-salad). Идущий прогон читает этот файл на КАЖДОМ листе и сам может дописывать промахи — файл нельзя ни обнулить, ни держать полузаписанным.
Порядок (бриф): 1) перечитать файл ПРЯМО перед заменой; 2) добавить только новые листы — уже посчитанные (тот же ключ-sha И та же версия правил) НЕ перезаписываются;
3) записать во временный файл РЯДОМ и `os.replace` (атомарно: читатель видит либо старый файл, либо новый целиком).
Свои параллельные слияния (10 нод → 10 драйверов) закрыты flock на `<файл>.lock`: перечитывание, слияние и замена идут под замком — строки не теряются.
Честный предел: чужой писатель без нашего замка (words_cached идущего прогона пишет в ДРУГОЙ файл — свою папку `WORDS_FLAGS_CACHE`; в наш файл он только читает) — окно гонки там сведено к «перечитал → rename».
Формат файла — как у words_on_sheet.words_cached: json.dump(ensure_ascii=False, indent=0); запись {words, found, conf, n_lines, rules, sheet}.
Запуск: merge_words.py --target <words_flags.json> --rules <12-знаковая версия> <results-*.json …>  (файлы — результаты драйвера: {"rules", "results": {sha: запись}})"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys

KEYS = ('words', 'found', 'conf', 'n_lines')


def _load(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}                                    # файла ещё нет — слияние его создаст
    # битый JSON НЕ глотаем: пусть упадёт с причиной (молча начать с пустого = стереть чужие строки)


def merge(target: str, entries: dict, rules: str, lock: bool = True, _between=None) -> dict:
    """entries: {sha: {words, found, conf, n_lines, sheet}} → в файл `target`. → {'added', 'kept', 'replaced_stale', 'total'}.
    `_between` — только тесты: пауза после перечитывания, до записи (расширяет окно гонки: без замка параллельные слияния теряют строки, с замком — нет)."""
    d = os.path.dirname(os.path.abspath(target))
    os.makedirs(d, exist_ok=True)
    lk = None
    if lock:
        lk = open(target + '.lock', 'a')
        fcntl.flock(lk, fcntl.LOCK_EX)
    try:
        cur = _load(target)                          # перечитано под замком, прямо перед заменой
        if _between:
            _between()
        added = kept = stale = 0
        for sha, e in entries.items():
            if not all(k in e for k in KEYS):
                raise ValueError(f'запись {sha[:12]}: нет полей {[k for k in KEYS if k not in e]}')
            old = cur.get(sha)
            if old is not None and old.get('rules') == rules:
                kept += 1                            # уже посчитано под этими правилами — не трогаем
                continue
            stale += old is not None
            added += old is None
            cur[sha] = {**{k: e[k] for k in KEYS}, 'rules': rules, 'sheet': e.get('sheet', '')}
        tmp = f'{target}.tmp{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cur, f, ensure_ascii=False, indent=0)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        return {'added': added, 'kept': kept, 'replaced_stale': stale, 'total': len(cur)}
    finally:
        if lk:
            fcntl.flock(lk, fcntl.LOCK_UN)
            lk.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--target', required=True)
    ap.add_argument('--rules', required=True, help='версия правил (words_on_sheet.rules_ver, 12 знаков) — ключ кэша')
    ap.add_argument('--dry', action='store_true', help='только счёт: сколько добавится/уже есть; файл не трогаем')
    ap.add_argument('files', nargs='+', help='results-*.json драйвера')
    a = ap.parse_args()
    entries: dict = {}
    for p in a.files:
        r = json.load(open(p, encoding='utf-8'))
        if r.get('rules') != a.rules:
            print(f'ОТКАЗ: {p}: версия правил {r.get("rules")} ≠ {a.rules} — не сливаю', file=sys.stderr)
            return 2
        entries.update(r['results'])
    if a.dry:
        cur = _load(a.target)
        new = [s for s in entries if cur.get(s, {}).get('rules') != a.rules]
        print(json.dumps({'в_файле': len(cur), 'пришло': len(entries), 'добавится': len(new), 'уже_есть': len(entries) - len(new)}, ensure_ascii=False))
        return 0
    print(json.dumps(merge(a.target, entries, a.rules), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
