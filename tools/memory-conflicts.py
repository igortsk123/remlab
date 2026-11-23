#!/usr/bin/env python3
"""Сторож конфликтов канона в памяти (аудит Codex a-dupes-1123 § 3 п.6; T-20261123-34/8).

ЧТО ЭТО. Старая формулировка в живом доке («UltraTex красит», «директор — pakardev») переживает смену канона и сбивает агента при возобновлении.
Сторож держит короткий список МАШИННО проверяемых фактов (`tools/scout/rules/canon-facts.json`): факт → канон-файл с ключевой фразой →
запрещённые формулировки в других доках памяти. Нашёл запрещённую вне истории — печатает `файл:строка` и падает (код 1).

КАК РАБОТАЕТ (стандартная библиотека, без сети).
  1. Канон: у каждого факта `canon[]` — файл и ключевая фраза (regex); нет файла или фразы → ошибка «канон потерян» (иначе сторож молча ничего не ловит).
  2. Область: `scan.roots` (по умолчанию .memory_bank и .claude/rules), только *.md; исключены `scan.exclude_dirs` (archive, changelog, _intake,
     completed_plans, _secrets) и `scan.history_paths` — журналы по самой природе (тома ADR, уроки с датой инцидента).
  3. Запрещённое (`forbidden[].pattern`, regex без учёта регистра) пропускается, если: строка несёт метку истории (`history_markers`: «устарело», «заменено»,
     «было», «до 23.11», «~~»…); или строка/блок под заголовком истории (`history_headings`: «История», «Ход …», «Было», «Журнал»…); или рядом явное
     `<!-- canon-ok: <id факта> причина -->` в той же или предыдущей строке; или факт у файла в `allow_files`.
  4. Вывод: `файл:строка [id] текст — почему нельзя; канон: файл`. Код 1 — есть конфликт/потерян канон, 2 — битый реестр.

  python tools/memory-conflicts.py --check          # CI: код 1 при конфликте (если mode реестра = block; warn — только печать)
  python tools/memory-conflicts.py --strict         # всегда код 1 при конфликте
  python tools/memory-conflicts.py --json           # то же в JSON
  python tools/memory-conflicts.py --facts          # список фактов реестра

Доки памяти сторож НЕ правит — только показывает, кто и где спорит с каналом.
"""
import argparse
import fnmatch
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
FACTS = os.environ.get('CANON_FACTS_PATH') or os.path.join(HERE, 'scout', 'rules', 'canon-facts.json')

_OK_RE = re.compile(r'<!--\s*canon-ok:\s*([\w\-*]+)\s*(.*?)-->', re.I)
_HEAD_RE = re.compile(r'^(#{1,6})\s+(.*)$')


class FactsError(RuntimeError):
    """Реестр фактов не прошёл схему."""


def load(path: str | None = None) -> dict:
    p = path or FACTS
    try:
        with open(p, encoding='utf-8') as fh:
            reg = json.load(fh)
    except (OSError, ValueError) as exc:
        raise FactsError(f'реестр {p}: {exc}') from exc
    errs = validate(reg)
    if errs:
        raise FactsError('реестр фактов: ' + '; '.join(errs))
    return reg


def validate(reg) -> list:
    errs = []
    if not isinstance(reg, dict) or not isinstance(reg.get('facts'), list) or not reg['facts']:
        return ['нет списка facts']
    seen = set()
    for i, f in enumerate(reg['facts']):
        fid = f.get('id') if isinstance(f, dict) else None
        if not fid or not isinstance(fid, str):
            errs.append(f'facts[{i}]: нет id')
            continue
        if fid in seen:
            errs.append(f'{fid}: дубль id')
        seen.add(fid)
        if not f.get('canon') or not all(isinstance(c, dict) and c.get('file') and c.get('phrase') for c in f['canon']):
            errs.append(f'{fid}: canon[] — у каждого file и phrase')
        if not f.get('forbidden') or not all(isinstance(x, dict) and x.get('pattern') and x.get('why') for x in f['forbidden']):
            errs.append(f'{fid}: forbidden[] — у каждого pattern и why')
        for key in ('canon', 'forbidden'):
            for x in f.get(key) or []:
                try:
                    re.compile(x.get('pattern') or x.get('phrase') or '')
                except re.error as exc:
                    errs.append(f'{fid}: regex {x.get("pattern") or x.get("phrase")!r}: {exc}')
    for k in ('history_markers', 'history_headings'):
        for pat in (reg.get(k) or []):
            try:
                re.compile(pat)
            except re.error as exc:
                errs.append(f'{k}: regex {pat!r}: {exc}')
    return errs


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, '/')


def iter_docs(root: str, reg: dict):
    """(абсолютный путь, относительный) всех *.md области проверки."""
    scan = reg.get('scan') or {}
    roots = scan.get('roots') or ['.memory_bank', '.claude/rules']
    excl = set(scan.get('exclude_dirs') or [])
    hist = scan.get('history_paths') or []
    for r in roots:
        base = os.path.join(root, r)
        for dp, dns, fns in os.walk(base):
            dns[:] = sorted(d for d in dns if d not in excl)
            for fn in sorted(fns):
                if not fn.endswith('.md'):
                    continue
                ap = os.path.join(dp, fn)
                rel = _rel(root, ap)
                if any(fnmatch.fnmatch(rel, h) for h in hist):
                    continue
                yield ap, rel


def _history_lines(lines: list[str], head_res: list) -> set:
    """Номера строк (0-based) внутри блока под заголовком истории — до следующего заголовка того же или более высокого уровня."""
    out, until = set(), None  # until = уровень заголовка, открывшего блок истории
    for i, ln in enumerate(lines):
        m = _HEAD_RE.match(ln)
        if m:
            lvl = len(m.group(1))
            if until is not None and lvl <= until:
                until = None
            if until is None and any(h.search(m.group(2)) for h in head_res):
                until = lvl
                out.add(i)
                continue
        if until is not None:
            out.add(i)
    return out


def check(root: str, reg: dict) -> dict:
    """{'conflicts': [{file, line, fact, text, why, canon}], 'canon_lost': [{fact, file, why}]}."""
    marks = [re.compile(p, re.I) for p in reg.get('history_markers') or []]
    heads = [re.compile(p, re.I) for p in reg.get('history_headings') or []]
    lost, conflicts = [], []
    canon_of = {}
    for f in reg['facts']:
        canon_of[f['id']] = ', '.join(c['file'] for c in f['canon'])
        for c in f['canon']:
            ap = os.path.join(root, c['file'])
            if not os.path.isfile(ap):
                lost.append({'fact': f['id'], 'file': c['file'], 'why': 'канон-файла нет'})
                continue
            with open(ap, encoding='utf-8') as fh:
                if not re.search(c['phrase'], fh.read(), re.I):
                    lost.append({'fact': f['id'], 'file': c['file'], 'why': f'в каноне нет фразы /{c["phrase"]}/ — канон поменяли, а реестр нет'})
    for ap, rel in iter_docs(root, reg):
        with open(ap, encoding='utf-8', errors='replace') as fh:
            lines = fh.read().split('\n')
        hist = _history_lines(lines, heads)
        for f in reg['facts']:
            if any(fnmatch.fnmatch(rel, a) for a in f.get('allow_files') or []):
                continue
            fmarks = marks + [re.compile(p, re.I) for p in f.get('exempt_markers') or []]
            for i, ln in enumerate(lines):
                for x in f['forbidden']:
                    if not re.search(x['pattern'], ln, re.I):
                        continue
                    if i in hist or any(m.search(ln) for m in fmarks):
                        break
                    near = ' '.join(lines[max(0, i - 1):i + 1])
                    if any(fnmatch.fnmatch(f['id'], m.group(1)) for m in _OK_RE.finditer(near)):
                        break
                    conflicts.append({'file': rel, 'line': i + 1, 'fact': f['id'], 'text': ln.strip()[:200], 'why': x['why'], 'canon': canon_of[f['id']]})
                    break
    return {'conflicts': conflicts, 'canon_lost': lost}


def render(res: dict) -> str:
    out = []
    for c in res['canon_lost']:
        out.append(f'КАНОН ПОТЕРЯН [{c["fact"]}] {c["file"]} — {c["why"]}')
    for c in res['conflicts']:
        out.append(f'{c["file"]}:{c["line"]} [{c["fact"]}] {c["text"]} — {c["why"]}; канон: {c["canon"]}')
    out.append(f'итог: конфликтов {len(res["conflicts"])}, потерян канон {len(res["canon_lost"])}')
    return '\n'.join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Сторож конфликтов канона в памяти')
    ap.add_argument('--root', default=ROOT, help='корень репозитория (где .memory_bank)')
    ap.add_argument('--facts-file', default=None)
    ap.add_argument('--check', action='store_true', help='CI: код 1 при конфликте, если режим реестра `mode` = block (по умолчанию); при warn — только печать')
    ap.add_argument('--strict', action='store_true', help='всегда код 1 при конфликте, режим реестра не учитывать')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--facts', action='store_true', help='показать факты реестра')
    a = ap.parse_args(argv)
    try:
        reg = load(a.facts_file)
    except FactsError as exc:
        print(f'ОШИБКА: {exc}', file=sys.stderr)
        return 2
    if a.facts:
        for f in reg['facts']:
            print(f'{f["id"]}: {f.get("claim", "")} (канон: {", ".join(c["file"] for c in f["canon"])})')
        return 0
    res = check(a.root, reg)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
    bad = bool(res['conflicts'] or res['canon_lost'])
    if not bad:
        return 0
    if a.check and not a.strict and reg.get('mode', 'block') == 'warn':
        print('⚠ режим реестра warn: конфликты не блокируют (после правки доков — mode: block)', file=sys.stderr)
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
