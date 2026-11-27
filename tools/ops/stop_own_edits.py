#!/usr/bin/env python3
"""Обёртка Stop-хука для машины, где лежит СТЕНОГРАММА, а хук идёт через `r` на другую (T-20261127-175 / гейт на common).

ЗАЧЕМ. На common сессия пишет стенограмму в /home/common/.claude/projects/…, а `tools/session-reminder.mjs` (node есть только на pakardev) запускается через `r` — на pakardev, где такого
пути нет. Гейт «только свои правки» на common не работал никогда: «стенограмма не читается» → менеджер видел то всех грязных файлов, то ничего. Здесь стенограмма читается НА СВОЕЙ стороне
(кусками — у менеджера она ~1 ГБ), свои правки (Edit/Write/MultiEdit/NotebookEdit) кладутся в stdin-JSON хука полями `own_edits_abs` (абсолютные пути) и `own_meta` ({skipped, bytes, source}
или {why}), и тот же JSON уходит дальше в команду (`r node tools/session-reminder.mjs …`); `tools/stop-gate-own.mjs: transcriptFromInput` берёт список оттуда.

ЗАПУСК (в команде Stop-хука вместо голого `r node …`):
    python3 tools/ops/stop_own_edits.py r node tools/session-reminder.mjs . --block --own-edits --strazh
Код возврата, stdout и stderr — команды. Нет stdin-JSON / нет transcript_path — JSON идёт как есть (хук сам скажет «не читается»). Стенограмма не открылась — в `own_meta.why` причина
(хук покажет её: директору блок, остальным — видимое предупреждение). Пределы чтения для теста: STOP_GATE_CHUNK_BYTES / STOP_GATE_MAX_LINE_BYTES (боевой запуск их не задаёт).

Стандартная библиотека. Те же правила, что в readOwnEdits (JS): строка длиннее предела пропускается с учётом (skipped), «tool_use» отсеивается по байтам до JSON."""
from __future__ import annotations

import json
import os
import subprocess
import sys

EDIT_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
CHUNK_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024 * 1024


def _limit(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, ''))
        return v if v > 0 else default
    except ValueError:
        return default


def _paths_of(line: bytes, cwd: str) -> list[str]:
    try:
        rec = json.loads(line.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return []
    content = (rec.get('message') or {}).get('content') if isinstance(rec, dict) else None
    out = []
    if not isinstance(content, list):
        return out
    for c in content:
        if not isinstance(c, dict) or c.get('type') != 'tool_use' or c.get('name') not in EDIT_TOOLS:
            continue
        inp = c.get('input') if isinstance(c.get('input'), dict) else {}
        p = inp.get('file_path') or inp.get('notebook_path')
        if isinstance(p, str) and p:
            out.append(p if os.path.isabs(p) else os.path.normpath(os.path.join(cwd, p)))
    return out


def scan(path: str, cwd: str, chunk: int | None = None, max_line: int | None = None) -> dict:
    """→ {'own': [абсолютные пути], 'skipped': N, 'bytes': M}. Читает кусками, в памяти — кусок + недочитанная строка. Ошибки чтения — наружу (OSError)."""
    chunk = chunk or _limit('STOP_GATE_CHUNK_BYTES', CHUNK_BYTES)
    max_line = max_line or _limit('STOP_GATE_MAX_LINE_BYTES', MAX_LINE_BYTES)
    own: dict[str, None] = {}
    skipped = total = 0
    carry: list[bytes] = []
    carry_len = 0
    overflow = False

    def handle(line: bytes) -> None:
        if b'"tool_use"' not in line:
            return
        for p in _paths_of(line, cwd):
            own[p] = None

    with open(path, 'rb') as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            total += len(buf)
            start = 0
            while start < len(buf):
                nl = buf.find(b'\n', start)
                if nl == -1:
                    piece = buf[start:]
                    if not overflow:
                        if carry_len + len(piece) > max_line:
                            overflow, carry, carry_len = True, [], 0
                        else:
                            carry.append(piece)
                            carry_len += len(piece)
                    break
                piece = buf[start:nl]
                if overflow:
                    skipped += 1
                    overflow = False
                elif carry_len + len(piece) > max_line:
                    skipped += 1
                else:
                    handle(b''.join(carry) + piece if carry_len else piece)
                carry, carry_len = [], 0
                start = nl + 1
    if overflow:
        skipped += 1
    elif carry_len:
        handle(b''.join(carry))
    return {'own': list(own), 'skipped': skipped, 'bytes': total}


def augment(raw: str, cwd: str) -> str:
    """stdin-JSON хука → он же с `own_edits_abs`/`own_meta`. Не JSON / нет пути — как есть."""
    try:
        d = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(d, dict):
        return raw
    tp = d.get('transcript_path')
    if not tp:
        return raw
    base = d.get('cwd') if isinstance(d.get('cwd'), str) else cwd
    try:
        r = scan(tp, base)
        d['own_edits_abs'] = r['own']
        d['own_meta'] = {'source': 'обёртка', 'skipped': r['skipped'], 'bytes': r['bytes']}
    except OSError as e:
        d['own_meta'] = {'source': 'обёртка', 'why': '%s: %s (%s)' % (type(e).__name__, getattr(e, 'strerror', None) or e, tp)}
    return json.dumps(d, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == '--':
        argv = argv[1:]
    if not argv:
        print('stop_own_edits: нет команды (ожидалось: stop_own_edits.py r node tools/session-reminder.mjs …)', file=sys.stderr)
        return 2
    raw = '' if sys.stdin.isatty() else sys.stdin.read()
    payload = augment(raw, os.getcwd()) if raw.strip() else raw
    try:
        return subprocess.run(argv, input=payload.encode('utf-8'), check=False).returncode
    except OSError as e:
        print('stop_own_edits: команда не запустилась: %s (%s)' % (argv[0], e), file=sys.stderr)   # не молчим: хук скажет о поломке сам кодом ≠0
        return 127


if __name__ == '__main__':
    sys.exit(main())
