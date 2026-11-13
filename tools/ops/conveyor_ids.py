#!/usr/bin/env python3
"""ЛИНТ ОСОБЫХ СЛУЧАЕВ: ID товара / меша / тура / набора банка в КОДЕ (T-20261112-121, план conveyor-guards-01 шаг 6;
владелец TG 1366/1370: «всё по конвейеру», Codex `_intake/codex/2026-11-12-conveyor-guards-answer.md` п. P1).

Правило: поведение задают правила, шаблоны и данные (`rules/**`, банки, каталог), а не ветка «если товар такой-то» в коде.
Номер конкретного товара, меша, тура или набора в исходнике = заплатка под один случай — на других планировках, турах и
после пересборки банка она молча не работает или работает не там. Где ему место: правило в `rules/**`, тест/эталон.

Что ищем (литералы строк и чисел, без комментариев и докстрингов):
  msid — товар/меш «магазин:товар» или «магазин_товар» (`112923:3989998131928467167`, `112923_10153166443740156800`);
  eid  — голый номер товара фида, 17–20 цифр (круглые числа вроде отметок времени — нет);
  tour — номер тура агента: 22 знака base64url вперемешку (`SxH_Doc4_QNFeEA-SK2F6A`);
  set  — номер набора банка (`set-62dc91d1`, `bed-0badc0de-2`).
Где НЕ ищем: тесты и эталоны (`NOT_CODE`), `rules/**`, функции самопроверки (`selftest`, `test_*`), а также области вне
конвейера (`OUT_OF_SCOPE`, у каждой причина).

Исключения — `tools/ops/conveyor-exceptions.yml`: путь и (имя `symbol` у .py — функция/класс/переменная верхнего уровня —
или точный литерал `literal`), детектор, причина, ADR или план, срок `until`. Звёздочек нет: путь и имя — точные. Истёкшее
и лишнее (ничего не покрывает) — WARN. Реестр кривой — код 1 в любом режиме.

РЕЖИМ (план: «неделю предупреждение, затем блок»): `MODE = 'warn'` — находки печатаются строкой WARN, код 0; переключение
на 'block' (находка или истёкшее исключение → код 1) — решением директора после замера ложных срабатываний.

  python tools/ops/conveyor_ids.py              # проверка дерева (CI scout-selftest, prepush — всегда)
  python tools/ops/conveyor_ids.py --block      # как будет после переключения
  python tools/ops/conveyor_ids.py --selftest
"""
from __future__ import annotations

import ast
import datetime as dt
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..'))
EXC_FILE = 'tools/ops/conveyor-exceptions.yml'
MODE = 'warn'

CODE = re.compile(r'\.(py|ts|tsx|mjs|cjs|js|sh|html)$')
NOT_CODE = re.compile(r'(^|/)(tests?|__tests__|fixtures|e2e)/|(^|/)tests?_[^/]*\.py$|_test\.py$|\.(test|spec)\.(ts|tsx|mjs|cjs|js)$'
                      r'|(^|/)rules/|(^|/)node_modules/|selftest[^/]*$'
                      r'|^tools/ops/demo-walk/[^/]*-check\.(cjs|mjs|js)$')   # проверки страницы в браузере = тесты (номера проб)
OUT_OF_SCOPE = (   # (начало пути или regex, почему не конвейер)
    (re.compile(r'^public/vendor/|\.min\.js$'), 'чужие библиотеки, сжатые'),
    (re.compile(r'^tools/design/figma/'), 'скрипты Фигмы: ключи узлов макета, не данные товаров/туров'),
    (re.compile(r'^remlab_knowledge_db_v1/|^services/knowledge-db/'), 'база знаний из книг — отдельный проект, не конвейер витрины'),
)
SELFTEST_FN = re.compile(r'^_?(selftest|self_test|test)(_|$)')
CTX_TOUR = re.compile(r'jid|job|tour|trial|тур', re.I)

DETECTORS = (   # порядок важен: msid раньше eid — номер внутри msid второй раз не считаем
    ('msid', re.compile(r'(?<![\w.])\d{4,7}[_:]\d{5,20}(?![\w.])')),
    ('eid', re.compile(r'(?<![\w.:])\d{17,20}(?![\w.])')),
    ('tour', re.compile(r'(?<![\w-])[A-Za-z0-9_-]{22}(?![\w-])')),
    ('set', re.compile(r'(?<![\w-])(?:set|bed|hall|kit|liv)-[0-9a-f]{8}(?:-\d{1,3})?(?![\w-])')),
)


def _tour_like(s: str, line: str) -> bool:
    if not (re.search(r'[A-Z]', s) and re.search(r'[a-z]', s) and re.search(r'\d', s)):
        return False
    words = re.search(r'[a-z]{5,}', s) or s.count('_') + s.count('-') > 3
    return bool(CTX_TOUR.search(line)) or not words      # слово в номере — имя, а не случайный ключ; рядом «tour/jid» — всё равно ID


def _round(s: str) -> bool:
    return bool(re.search(r'0{5,}$', s)) or len(set(s)) == 1


def find_ids(text: str, line: str = '') -> list[tuple[str, str]]:
    """→ [(детектор, литерал)] в одной строке-литерале `text`; `line` — строка исходника (контекст для tour)."""
    out, taken = [], []
    for name, rx in DETECTORS:
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            s = m.group(0)
            if name == 'eid' and _round(s):
                continue
            if name == 'tour' and not _tour_like(s, line or text):
                continue
            out.append((name, s))
            taken.append(m.span())
    return out


def _py_hits(src: str) -> list[tuple[int, str, str, str]] | None:
    """→ [(строка, детектор, литерал, symbol)] по .py: литералы строк/чисел вне докстрингов и функций самопроверки."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    lines = src.split('\n')
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    out = []

    def symbol_of(node) -> str:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            tg = node.targets[0] if isinstance(node, ast.Assign) else node.target
            return tg.id if isinstance(tg, ast.Name) else ''
        return ''

    def walk(node, sym: str):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) and SELFTEST_FN.match(ch.name):
                continue
            s = sym or symbol_of(ch) if isinstance(node, ast.Module) else sym
            if isinstance(ch, ast.Constant) and id(ch) not in docs and isinstance(ch.value, (str, int)) \
                    and not isinstance(ch.value, bool):
                ln = getattr(ch, 'lineno', 0)
                for det, lit in find_ids(str(ch.value), lines[ln - 1] if 0 < ln <= len(lines) else ''):
                    out.append((ln, det, lit, s))
            walk(ch, s)
    walk(tree, '')
    return out


# JS/TS/HTML слева направо: что началось раньше, то и есть — `//` внутри строки остаётся строкой, кавычка в комментарии — комментарием
JS_TOK = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`', re.S)
JS_NUM = re.compile(r'(?<![\w.])\d{17,20}(?=n?(?![\w.]))')


def _js_hits(src: str) -> list[tuple[int, str, str, str]]:
    """JS/TS/HTML: литералы в кавычках и голые длинные числа; комментарии // и /* */ — мимо."""
    lines, out, pos = src.split('\n'), [], 0

    def add(at: int, text: str):
        ln = src.count('\n', 0, at) + 1
        for det, lit in find_ids(text, lines[ln - 1]):
            out.append((ln, det, lit, ''))

    def gap(a: int, b: int):
        for m in JS_NUM.finditer(src, a, b):
            add(m.start(), m.group(0))

    for m in JS_TOK.finditer(src):
        gap(pos, m.start())
        pos = m.end()
        if not m.group(0).startswith('/'):
            add(m.start(), m.group(0)[1:-1])
    gap(pos, len(src))
    return out


def _sh_hits(src: str) -> list[tuple[int, str, str, str]]:
    out = []
    for i, ln in enumerate(src.split('\n'), 1):
        if ln.lstrip().startswith('#'):
            continue
        code = re.sub(r'(^|\s)#.*$', '', ln)
        for det, lit in find_ids(code, code):
            out.append((i, det, lit, ''))
    return out


def scan_text(path: str, src: str) -> list[dict]:
    if path.endswith('.py'):
        hits = _py_hits(src)
        if hits is None:
            hits = _sh_hits(src)    # не разобрался как python — грубо по строкам, без комментариев
    elif path.endswith('.sh'):
        hits = _sh_hits(src)
    else:
        hits = _js_hits(src)
    return [dict(path=path, line=ln, detector=det, literal=lit, symbol=sym) for ln, det, lit, sym in hits]


def in_scope(path: str) -> str:
    """'' — проверяем; иначе причина, почему нет."""
    if not CODE.search(path):
        return 'не код'
    if NOT_CODE.search(path):
        return 'тесты/эталоны/правила'
    for rx, why in OUT_OF_SCOPE:
        if rx.search(path):
            return why
    return ''


def git_files(root: str) -> list[str]:
    r = subprocess.run(['git', '-C', root, 'ls-files', '-z'], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f'git ls-files: {r.stderr.strip()[:200]}')
    return [p for p in r.stdout.split('\0') if p]


def scan_tree(root: str, files: list[str] | None = None) -> list[dict]:
    out = []
    for p in files if files is not None else git_files(root):
        if in_scope(p):
            continue
        try:
            with open(os.path.join(root, p), encoding='utf-8') as f:
                src = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        out.extend(scan_text(p, src))
    return out


# ------------------------------------------------------------------------------------------------ реестр исключений
EXC_KEYS = {'path', 'detector', 'symbol', 'literal', 'why', 'adr', 'plan', 'until'}


def validate_exceptions(items, root: str) -> list[str]:
    """→ ошибки реестра (пусто — годен)."""
    errs = []
    if not isinstance(items, list):
        return ['exceptions: нужен список']
    dets = {d for d, _ in DETECTORS}
    for i, e in enumerate(items):
        tag = f'исключение #{i + 1}'
        if not isinstance(e, dict):
            errs.append(f'{tag}: нужен словарь')
            continue
        extra = set(e) - EXC_KEYS
        if extra:
            errs.append(f'{tag}: лишние поля {sorted(extra)}')
        for k in ('path', 'detector', 'why', 'until'):
            if not str(e.get(k) or '').strip():
                errs.append(f'{tag}: нет поля {k}')
        if not (str(e.get('adr') or '').strip() or str(e.get('plan') or '').strip()):
            errs.append(f'{tag}: нужен adr (ADR-NNNN) или plan (slug плана)')
        if e.get('adr') and not re.fullmatch(r'ADR-\d{4}', str(e['adr'])):
            errs.append(f'{tag}: adr — вида ADR-NNNN')
        if e.get('plan') and not re.fullmatch(r'[a-z0-9][a-z0-9-]*', str(e['plan'])):
            errs.append(f'{tag}: plan — slug плана')
        if bool(e.get('symbol')) == bool(e.get('literal')):
            errs.append(f'{tag}: ровно одно из symbol (имя в .py) или literal (точный ID)')
        for k in ('path', 'symbol', 'literal'):
            if re.search(r'[*?\[\]{}]', str(e.get(k) or '')):
                errs.append(f'{tag}: {k} без звёздочек и масок')
        if e.get('detector') and e['detector'] not in dets:
            errs.append(f'{tag}: detector — один из {sorted(dets)}')
        if e.get('path') and not os.path.isfile(os.path.join(root, str(e['path']))):
            errs.append(f'{tag}: файла {e["path"]} нет')
        if e.get('symbol') and not str(e.get('path', '')).endswith('.py'):
            errs.append(f'{tag}: symbol — только у .py, иначе literal')
        u = e.get('until')
        try:
            if not isinstance(u, dt.date):
                dt.date.fromisoformat(str(u))
        except ValueError:
            errs.append(f'{tag}: until — дата ГГГГ-ММ-ДД')
    return errs


def load_exceptions(root: str) -> list:
    p = os.path.join(root, EXC_FILE)
    if not os.path.exists(p):
        return []
    import yaml
    with open(p, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data.get('exceptions') or [] if isinstance(data, dict) else data


def _until(e) -> dt.date:
    u = e['until']
    return u if isinstance(u, dt.date) else dt.date.fromisoformat(str(u))


def apply_exceptions(hits: list[dict], items: list, today: dt.date) -> tuple[list[dict], list[str], list[str]]:
    """→ (непокрытые находки, истёкшие исключения, лишние исключения)."""
    used, left = set(), []
    for h in hits:
        cover = None
        for i, e in enumerate(items):
            if e['path'] == h['path'] and e['detector'] == h['detector'] and \
                    ((e.get('symbol') and e['symbol'] == h['symbol']) or (e.get('literal') and str(e['literal']) == h['literal'])):
                cover = i
                break
        if cover is None:
            left.append(h)
        else:
            used.add(cover)
    expired = [f"{e['path']} {e.get('symbol') or e.get('literal')} (срок {_until(e)})" for i, e in enumerate(items)
               if i in used and _until(e) < today]
    unused = [f"{e['path']} {e.get('symbol') or e.get('literal')}" for i, e in enumerate(items) if i not in used]
    return left, expired, unused


def run(root: str, block: bool, today: dt.date | None = None, files: list[str] | None = None, out=sys.stdout) -> int:
    today = today or dt.date.today()
    items = load_exceptions(root)
    errs = validate_exceptions(items, root)
    if errs:
        for e in errs:
            print(f'FAIL:conveyor_ids: {EXC_FILE}: {e}', file=out)
        return 1
    left, expired, unused = apply_exceptions(scan_tree(root, files), items, today)
    lvl = 'FAIL' if block else 'WARN'
    for h in left:
        where = f" в {h['symbol']}" if h['symbol'] else ''
        print(f"{lvl}:special-id: {h['path']}:{h['line']} {h['detector']} {h['literal']}{where} — ID в коде; место ему в rules/** "
              f"или тесте, иначе — исключение в {EXC_FILE} (причина, ADR/план, срок)", file=out)
    for s in expired:
        print(f'{lvl}:special-id: исключение истекло — {s}: убрать особый случай или продлить с причиной', file=out)
    for s in unused:
        print(f'WARN:special-id: исключение ничего не покрывает — {s}: убрать из {EXC_FILE}', file=out)
    print(f'особые случаи (ID в коде): находок {len(left)}, истёкших исключений {len(expired)}, лишних {len(unused)}, '
          f'исключений {len(items)} · режим {"блок" if block else "предупреждение"}', file=out)
    return 1 if block and (left or expired) else 0


# ------------------------------------------------------------------------------------------------------ самопроверка
def _selftest() -> int:
    import io
    import tempfile
    bad = []

    def ok(c, m, info=''):
        print(('OK  ' if c else 'BAD ') + m + ('' if c else f' :: {info}'))
        if not c:
            bad.append(m)

    def dets(path, src):
        return [(h['detector'], h['literal'], h['symbol']) for h in scan_text(path, src)]

    py = ('"""Докстринг: 112923:3989998131928467167 — пример, не код."""\n'
          '# комментарий 112923_10153166443740156800\n'
          "SKU = {'bed': '112923:3989998131928467167'}\n"
          'def pick(x):\n'
          '    """тур SxH_Doc4_QNFeEA-SK2F6A в докстринге — нет"""\n'
          "    if x == '112923_10153166443740156800':\n"
          '        return 15016742574867170700\n'
          "    return 'set-62dc91d1'\n"
          'def _selftest():\n'
          "    assert pick('112923:1') and 'SxH_Doc4_QNFeEA-SK2F6A'\n"
          'TS = 1760000000000000000\n'
          "JID = 'SxH_Doc4_QNFeEA-SK2F6A'\n"
          "NAME = 'matrixWorldNeedsUpdate'\n"
          "SHA = 'abcdef0123456789abcdef'\n")
    got = dets('tools/scout/x.py', py)
    ok(('msid', '112923:3989998131928467167', 'SKU') in got, 'py: msid в словаре — находка, symbol = имя переменной', got)
    ok(('msid', '112923_10153166443740156800', 'pick') in got, 'py: сравнение с номером меша в функции — находка', got)
    ok(('eid', '15016742574867170700', 'pick') in got, 'py: голый номер товара числом — находка', got)
    ok(('set', 'set-62dc91d1', 'pick') in got, 'py: номер набора банка — находка', got)
    ok(('tour', 'SxH_Doc4_QNFeEA-SK2F6A', 'JID') in got, 'py: номер тура — находка', got)
    ok(sum(1 for d in got if d[1] == '112923:3989998131928467167') == 1, 'py: докстринг и комментарий — не находки', got)
    ok(not any(d[2] == '_selftest' for d in got) and sum(1 for d in got if d[0] == 'tour') == 1,
       'py: функция самопроверки и докстринг функции — не находки', got)
    ok(not any(d[1].startswith('1760') for d in got), 'py: круглое число (отметка времени) — не номер товара', got)
    ok(not any(d[1] in ('matrixWorldNeedsUpdate', 'abcdef0123456789abcdef') for d in got), 'py: имя и шестнадцатеричная строка — не тур', got)
    ok(not any(d[0] == 'eid' and d[1] in '112923:3989998131928467167' for d in got), 'py: номер внутри msid второй раз не считается', got)
    js = ('// const A = "112923:3989998131928467167";\n'
          '/* блок 114667:13118255813066192472 */\n'
          'const B = "114667_13118255813066192472"; const url = "https://x/a"; // 112923:1111111111\n'
          "if (jid === 'SxH_Doc4_QNFeEA-SK2F6A') {}\n"
          'const n = 15016742574867170700n;\n'
          'const t = `bed-0badc0de-2`;\n')
    got = dets('lib/x.ts', js)
    ok(('msid', '114667_13118255813066192472', '') in got and ('tour', 'SxH_Doc4_QNFeEA-SK2F6A', '') in got
       and ('eid', '15016742574867170700', '') in got and ('set', 'bed-0badc0de-2', '') in got, 'js: строки, шаблон и число — находки', got)
    ok(not any(d[1] in ('112923:3989998131928467167', '112923:1111111111') for d in got)
       and sum(1 for d in got if d[1] == '114667:13118255813066192472') == 0, 'js: комментарии // и /* */ — не находки', got)
    sh = '# 112923:3989998131928467167\nX=112923_10153166443740156800  # 99272:2147763667486905198\n'
    got = dets('tools/x.sh', sh)
    ok(got == [('msid', '112923_10153166443740156800', '')], 'sh: код — находка, комментарии — нет', got)
    ok(in_scope('tools/scout/tests/test_x.py') and in_scope('tools/scout/rules/a.json') and in_scope('public/vendor/a.js')
       and in_scope('tools/design/figma/link/a.js') and not in_scope('tools/scout/a.py') and not in_scope('lib/a.ts'),
       'область: тесты, правила, чужие библиотеки, Фигма — мимо; конвейер — проверяем')
    with tempfile.TemporaryDirectory(prefix='conveyor-ids-') as d:
        os.makedirs(os.path.join(d, 'tools/ops'))
        with open(os.path.join(d, 'a.py'), 'w', encoding='utf-8') as f:
            f.write(py)
        base = dict(path='a.py', detector='msid', symbol='SKU', why='эскиз', plan='bedroom-groups-01', until='2026-12-01')
        ok(validate_exceptions([base], d) == [], 'реестр: годная запись', validate_exceptions([base], d))
        for bad_e, what in ((dict(base, path='*.py'), 'звёздочка в пути'), (dict(base, symbol='SK*'), 'маска в имени'),
                            (dict(base, why=''), 'без причины'), (dict(base, plan=None), 'без ADR и плана'),
                            (dict(base, until='скоро'), 'кривой срок'), (dict(base, literal='1'), 'и symbol, и literal'),
                            (dict(base, path='b.py'), 'нет файла'), (dict(base, detector='x'), 'чужой детектор'),
                            (dict(base, adr='0016'), 'adr не ADR-NNNN'), (dict(base, extra=1), 'лишнее поле')):
            ok(validate_exceptions([bad_e], d) != [], f'реестр: отказ — {what}')
        hits = scan_tree(d, ['a.py'])
        left, exp, unused = apply_exceptions(hits, [base, dict(base, symbol='NOPE')], dt.date(2026, 11, 13))
        ok(not any(h['symbol'] == 'SKU' for h in left) and any(h['symbol'] == 'pick' for h in left), 'исключение по имени покрывает только своё', left)
        ok(exp == [] and len(unused) == 1 and 'NOPE' in unused[0], 'лишнее исключение — в списке лишних', unused)
        _, exp, _ = apply_exceptions(hits, [base], dt.date(2026, 12, 2))
        ok(len(exp) == 1, 'исключение после срока — истекло', exp)
        lit = dict(base, symbol=None, literal='112923_10153166443740156800')
        left, _, _ = apply_exceptions(hits, [lit], dt.date(2026, 11, 13))
        ok(not any(h['literal'] == lit['literal'] for h in left), 'исключение по точному литералу')
        buf = io.StringIO()
        rc_w = run(d, block=False, files=['a.py'], out=buf)
        rc_b = run(d, block=True, files=['a.py'], out=io.StringIO())
        ok(rc_w == 0 and 'WARN:special-id: a.py:' in buf.getvalue() and rc_b == 1, 'режим: предупреждение — код 0, блок — код 1',
           (rc_w, rc_b, buf.getvalue()[:300]))
        with open(os.path.join(d, EXC_FILE), 'w', encoding='utf-8') as f:
            f.write('exceptions:\n  - {path: "*.py", detector: msid, symbol: SKU, why: x, plan: p, until: 2026-12-01}\n')
        ok(run(d, block=False, files=['a.py'], out=io.StringIO()) == 1, 'кривой реестр — код 1 и в режиме предупреждения')
    print('итог:', 'OK' if not bad else f'FAIL ({len(bad)})')
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ['--selftest']:
        return _selftest()
    block = MODE == 'block' or '--block' in argv
    root = ROOT_DEFAULT
    if '--root' in argv:
        root = argv[argv.index('--root') + 1]
    return run(root, block)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
