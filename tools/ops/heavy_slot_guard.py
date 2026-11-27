#!/usr/bin/env python3
"""Сторож «браузер в крон-шаге — только через очередь тяжёлых прогонов» (T-20261127-175/demo-live-slot; директор 27.11: нагрузка 27 на 16 ядер,
~2,7 ядра ела ночная живая проверка демо — `refresh_daily` → `ops/demo-live.sh` → playwright — мимо `heavy-slot`).

ЧТО ЛОВИМ. Крон-вход (строка `infra/dev/crontab` или шаг `step <имя> …` в `tools/scout/refresh_daily.sh`) доходит до файла, который запускает браузер
(playwright / chromium / puppeteer / headless), а на пути от входа до этого файла НИГДЕ нет `heavy-slot` (ни в строке входа, ни в промежуточных скриптах, ни в
самом файле — так сам встаёт в очередь, например, `demo-realistic.mjs`). Нашли → код 1 и строка `FAIL <вход>: … → <файл с браузером>`.

КАК ХОДИМ. От строки входа берём упомянутые файлы репозитория (`*.sh *.py *.mjs *.cjs *.js *.ts`; путь `../ops/x.sh` и просто `x.sh` — по хвосту пути),
читаем их без комментариев и идём дальше (до 4 уровней). Не охвачено (честно): имена файлов, собранные в переменных (`"$DIR/$name"`), вызовы через
`eval`/`xargs`; обфускацию не ловим — это страховка от забытой обёртки, не граница безопасности.

ИСКЛЮЧЕНИЯ — ДАННЫЕ: `tools/scout/rules/heavy-slot-guard.json` → `exempt: {"<вход>": "почему браузер без очереди"}` (причина обязательна; вход, которого
нет, — ошибка: запись не копится мёртвой). Исключение — решение директора.

  python3 tools/ops/heavy_slot_guard.py            # проверка (CI): код 1 при находках
  python3 tools/ops/heavy_slot_guard.py --list     # все входы и что нашли (браузер / очередь)
  python3 tools/ops/heavy_slot_guard.py --root DIR # проверить другой корень (тесты: копия с поломкой)
  python3 tools/ops/heavy_slot_guard.py --selftest # сломанная проверка сама красная (код ≠0 и строка с причиной)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES = 'tools/scout/rules/heavy-slot-guard.json'
CRONTAB = 'infra/dev/crontab'
REFRESH = 'tools/scout/refresh_daily.sh'
CODE_EXT = ('.sh', '.py', '.mjs', '.cjs', '.js', '.ts')
FILE_RE = re.compile(r'[\w./${}~-]+\.(?:sh|py|mjs|cjs|js|ts)\b')
STEP_RE = re.compile(r'^\s*step\s+(\w+)\s+(.*)$')
MAX_DEPTH = 4


def _read(root: str, rel: str) -> str:
    with open(os.path.join(root, rel), encoding='utf-8', errors='replace') as f:
        return f.read()


def _git_files(root: str) -> list:
    r = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError('git ls-files: код %d: %s' % (r.returncode, r.stderr.strip()[:200]))
    return [f for f in r.stdout.split('\n') if f.endswith(CODE_EXT)]


def _code_only(text: str) -> str:
    """Без строк-комментариев (`#`, `//`, `*`): упоминание в пояснении — не запуск."""
    out = []
    for ln in text.split('\n'):
        s = ln.strip()
        if s.startswith(('#', '//', '*', '/*')):
            continue
        out.append(ln)
    return '\n'.join(out)


def _tail(tok: str) -> str:
    t = tok.strip('"\'')
    for pre in ('${HERE}/', '$HERE/', '$(dirname "$0")/', '$ROOT/', '$HOME/', '~/'):
        if t.startswith(pre):
            t = t[len(pre):]
    while t.startswith(('./', '../')):
        t = t[3:] if t.startswith('../') else t[2:]
    return t.lstrip('/')


def _resolve(tok: str, files: list) -> list:
    t = _tail(tok)
    if not t or '$' in t:
        return []
    if t in files:
        return [t]
    base = t.split('/')[-1]
    return [f for f in files if f == t or f.endswith('/' + t) or t.endswith('/' + f) or (('/' not in t) and f.split('/')[-1] == base)]


# из .py/.mjs/… идём дальше только по строкам, где файл ЗАПУСКАЮТ (в docstring/тексте имя файла — не вызов); из .sh — по любой строке кода
INVOKE_RE = re.compile(r'subprocess|Popen|check_call|check_output|\brun\(|spawn|execFile|exec\(|\bnode\b|\bbash\b|\bsh\b|\bpython3?\b|\$PY\b|\bnpx?\b|\bpnpm\b|\bsource\b|^\s*\.\s')


def _followable(rel: str, body: str) -> str:
    if rel.endswith('.sh'):
        return body
    return '\n'.join(ln for ln in body.split('\n') if INVOKE_RE.search(ln))


def entries(root: str) -> list:
    """[(имя входа, текст строки)] — строки крона и шаги refresh_daily."""
    out = []
    ct = os.path.join(root, CRONTAB)
    if os.path.exists(ct):
        for ln in _read(root, CRONTAB).split('\n'):
            s = ln.strip()
            if not s or s.startswith('#'):
                continue
            toks = FILE_RE.findall(s)
            out.append(('cron:' + (_tail(toks[-1]).split('/')[-1] if toks else s[:40]), s))
    rf = os.path.join(root, REFRESH)
    if os.path.exists(rf):
        buf, joined = '', []
        for ln in _read(root, REFRESH).split('\n'):
            if ln.rstrip().endswith('\\'):
                buf += ln.rstrip()[:-1] + ' '
                continue
            joined.append(buf + ln)
            buf = ''
        for ln in joined:
            m = STEP_RE.match(ln)
            if m:
                out.append(('step:' + m.group(1), m.group(2)))
    return out


def scan(root: str, rules: dict, files: list = None) -> tuple:
    """→ (находки [(вход, путь до файла с браузером)], справка {вход: (браузер, очередь)})."""
    files = files if files is not None else _git_files(root)
    browser = re.compile(rules['browser_pattern'])         # регистр важен: PLAYWRIGHT_* в node-env.sh — настройка окружения, не запуск
    slot = re.compile(rules['slot_pattern'])
    cache = {}

    def text(rel):
        if rel not in cache:
            try:
                cache[rel] = _code_only(_read(root, rel))
            except OSError:
                cache[rel] = ''
        return cache[rel]

    bad, info = [], {}
    for name, line in entries(root):
        found = {'browser': False, 'slot': False}
        seen = set()

        def walk(srcs, covered, path, depth):
            for tok in FILE_RE.findall(srcs):
                for rel in _resolve(tok, files):
                    key = (rel, covered)
                    if key in seen:
                        continue
                    seen.add(key)
                    body = text(rel)
                    cov = covered or bool(slot.search(body))
                    found['slot'] = found['slot'] or bool(slot.search(body))
                    if browser.search(body):
                        found['browser'] = True
                        if not cov:
                            bad.append((name, path + [rel]))
                    if depth < MAX_DEPTH and rel not in (REFRESH, CRONTAB):     # сам файл шагов — корень, не звено цепочки
                        walk(_followable(rel, body), cov, path + [rel], depth + 1)

        line_slot = bool(slot.search(line))
        found['slot'] = line_slot
        if browser.search(line):                       # браузер прямо в строке входа
            found['browser'] = True
            if not line_slot:
                bad.append((name, ['(сама строка входа)']))
        walk(line, line_slot, [], 1)
        info[name] = (found['browser'], found['slot'])
    # одна находка на вход (кратчайший путь)
    best = {}
    for name, path in bad:
        if name not in best or len(path) < len(best[name]):
            best[name] = path
    return sorted(best.items()), info


def load_rules(root: str) -> dict:
    d = json.loads(_read(root, RULES))
    for k in ('browser_pattern', 'slot_pattern', 'exempt'):
        if k not in d:
            raise ValueError('%s: нет ключа %s' % (RULES, k))
    return d


def check(root: str, files: list = None) -> list:
    """Строки ошибок (пусто — чисто)."""
    try:
        rules = load_rules(root)
    except (OSError, ValueError) as e:
        return ['FAIL сторож слота не запустился: %s' % e]
    errs = []
    exempt = rules['exempt']
    for k, why in exempt.items():
        if not isinstance(why, str) or len(why.strip()) < 15:
            errs.append('FAIL исключение %s без причины (нужно ≥15 знаков: почему браузер без очереди)' % k)
    try:
        found, info = scan(root, rules, files)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return errs + ['FAIL сторож слота не запустился: %s' % e]
    if not info:
        errs.append('FAIL сторож слота не нашёл ни одного крон-входа (%s, шаги %s) — проверка слепая' % (CRONTAB, REFRESH))
    for k in exempt:
        if k not in info:
            errs.append('FAIL исключение %s: такого входа нет (удалён или переименован) — убрать запись из %s' % (k, RULES))
    for name, path in found:
        if name in exempt:
            continue
        errs.append('FAIL %s: браузер без heavy-slot — %s. Оберни вызов: `tools/ops/heavy-slot.sh <метка> --min-gb 3 --cores 3 --timeout S -- …` '
                    '(ядра/порог — как у соседних вызовов) или внеси в exempt с причиной' % (name, ' → '.join(path)))
    return errs


def _selftest() -> int:
    bad = []

    def ok(name, cond, info=''):
        if not cond:
            bad.append(name + (' — ' + str(info) if info else ''))

    rules = {'browser_pattern': r'playwright test|exec playwright|chromium\.launch|puppeteer|--headless', 'slot_pattern': r'heavy[-_]slot|HEAVY_SLOT', 'exempt': {}}
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or None) as d:
        def put(rel, s):
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(s)

        def lay(step_line, browser_body='pnpm exec playwright test\n', wrapper=None):
            put(RULES, json.dumps(rules, ensure_ascii=False))
            put(REFRESH, 'step a echo\n' + step_line + '\n')
            put('tools/ops/b.sh', browser_body)
            if wrapper:
                put('tools/ops/w.sh', wrapper)
            put(CRONTAB, '# пусто\n')
            files = ['tools/ops/b.sh', 'tools/ops/w.sh'] if wrapper else ['tools/ops/b.sh']
            return files

        # 1. браузер без очереди → красный, имя шага в строке
        files = lay('step live bash ../ops/b.sh')
        errs = check(d, files)
        ok('без слота → красный', len(errs) == 1 and 'step:live' in errs[0] and 'b.sh' in errs[0], errs)
        # 2. тот же шаг под heavy-slot в строке → чисто
        files = lay('step live bash ../ops/heavy-slot.sh live --cores 3 -- bash ../ops/b.sh')
        ok('слот в строке → чисто', check(d, files) == [], check(d, files))
        # 3. браузер сам встаёт в очередь → чисто
        files = lay('step live bash ../ops/b.sh', browser_body='exec bash heavy-slot.sh x -- playwright test\n')
        ok('слот внутри файла → чисто', check(d, files) == [], check(d, files))
        # 4. цепочка через промежуточный скрипт без слота → красный; со слотом в нём → чисто
        files = lay('step live bash ../ops/w.sh', wrapper='bash b.sh\n')
        e4 = check(d, files)
        ok('цепочка без слота → красный', len(e4) == 1 and 'w.sh → tools/ops/b.sh' in e4[0], e4)
        files = lay('step live bash ../ops/w.sh', wrapper='heavy-slot.sh x -- bash b.sh\n')
        ok('слот в промежуточном → чисто', check(d, files) == [], check(d, files))
        # 5. упоминание в комментарии — не запуск
        files = lay('step live bash ../ops/b.sh', browser_body='# playwright тут не запускается\necho hi\n')
        ok('браузер только в комментарии → чисто', check(d, files) == [], check(d, files))
        # 6. исключение с причиной гасит находку; без причины и мёртвое — красные
        files = lay('step live bash ../ops/b.sh')
        rules['exempt'] = {'step:live': 'разовый ручной шаг, браузер лёгкий, очередь не нужна'}
        put(RULES, json.dumps(rules, ensure_ascii=False))
        ok('исключение с причиной → чисто', check(d, files) == [], check(d, files))
        rules['exempt'] = {'step:live': 'коротко'}
        put(RULES, json.dumps(rules, ensure_ascii=False))
        ok('исключение без причины → красный', any('без причины' in e for e in check(d, files)), check(d, files))
        rules['exempt'] = {'step:gone': 'такого входа давно нет в файле шагов'}
        put(RULES, json.dumps(rules, ensure_ascii=False))
        ok('мёртвое исключение → красный', any('такого входа нет' in e for e in check(d, files)), check(d, files))
        rules['exempt'] = {}
        # 7. крон-строка: браузерный скрипт в crontab без слота → красный
        files = lay('step a echo')
        put(CRONTAB, '0 3 * * * /home/x/remlab/tools/ops/b.sh\n')
        e7 = check(d, files)
        ok('крон без слота → красный', len(e7) == 1 and 'cron:b.sh' in e7[0], e7)
        # 8. сломана: нет файла правил / нет входов / битый JSON → красный с причиной, не молчание
        put(RULES, '{плохой json')
        e8 = check(d, files)
        ok('битый файл правил → красный с причиной', len(e8) == 1 and 'не запустился' in e8[0], e8)
        os.remove(os.path.join(d, RULES))
        e9 = check(d, files)
        ok('нет файла правил → красный с причиной', len(e9) == 1 and 'не запустился' in e9[0], e9)
        put(RULES, json.dumps(rules, ensure_ascii=False))
        put(REFRESH, '# ни одного шага\n')
        put(CRONTAB, '# пусто\n')
        e10 = check(d, files)
        ok('входов нет → красный (слепая проверка)', any('слепая' in e for e in e10), e10)
        # 9. git не отдал список файлов → красный с причиной, а не «чисто»
        global _git_files
        real = _git_files

        def broken(root):
            raise RuntimeError('git ls-files: код 128: not a git repository')
        _git_files = broken
        try:
            e11 = check(d)
        finally:
            _git_files = real
        ok('git не ответил → красный с причиной', any('не запустился' in e and 'git ls-files' in e for e in e11), e11)
    print('heavy_slot_guard selftest: ошибок %d' % len(bad))
    for b in bad:
        print('  ПРОВАЛ: ' + b)
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    root = ROOT
    if '--root' in argv and argv.index('--root') + 1 < len(argv):     # другой корень (тесты: копия с поломкой); по умолчанию — репозиторий сторожа
        root = os.path.abspath(argv[argv.index('--root') + 1])
    if '--list' in argv:
        rules = load_rules(root)
        found, info = scan(root, rules)
        bad = dict(found)
        for name in sorted(info):
            b, s = info[name]
            if b or s:
                print('%-28s браузер=%s очередь=%s%s' % (name, 'да' if b else 'нет', 'да' if s else 'нет', '  ← БЕЗ ОЧЕРЕДИ' if name in bad else ''))
        return 0
    errs = check(root)
    for e in errs:
        print(e)
    if not errs:
        print('heavy_slot_guard: крон-шаги с браузером идут через heavy-slot')
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
