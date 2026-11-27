#!/usr/bin/env python3
"""МЕТКА НАБОРА ПРАВИЛ (T-20261127-175/12, Fable 29 § 3 ступень А): один набор чисел правил — проба = ветка = основная копия по составу.

ЗАЧЕМ. Экзамен на «замороженных правилах» нечем проверить, пока в отчёте этапа не написано, ПО КАКИМ правилам он посчитан. Профиль пробы (копия дерева с
накладкой ключей — `mk_probe15.sh`, `merge_new_keys.py`, `set_rules.py`) раньше расходился с основной копией молча: «проба прошла» ≠ «ветка пройдёт».

ЧТО ЭТО.
  метка  — первые 12 знаков sha256 ВСЕХ файлов правил набора (по умолчанию `tools/scout/rules/**.json`, кроме перечисленных в `rules/rules-label.json:exclude`):
           путь от корня + содержимое. JSON берётся КАНОНИЧЕСКИ (ключи по алфавиту, без пробелов, ТЕКСТОВЫЕ ключи на «_» — комментарии `_about/_why` — не в счёт; «_»-ключ с числом/флагом/объектом — данные, в счёте):
           перенос строк, порядок ключей и правка комментария метку не двигают, значение числа/флага — двигает. Плюс переменные окружения из `env`, если выставлены
           (`DELIGHT_RULES`, `SHADOW_LEAK`, …): они подменяют правило мимо файла, поэтому входят в метку и видны в отчёте.
  отчёт  — `paint_stage.write_check` кладёт в КАЖДЫЙ `check.json` поле `rules_label` = {id, n, env, root}, `paint_run_all` — в `run_all.json` ту же запись.
           ОДНО ПОЛЕ для всех читателей (договорено с T-175/10, `circle_origin.py`): `rules_label.id` — строка из 12 hex; нет модуля/сбой — `id: "нет"` + `why`.
  разница — `rules_label.py --diff A B`: список КЛЮЧЕЙ (`файл::ключ.путь  A=… B=…`), которыми два дерева (проба, ветка, основная копия) различаются, отдельно
           «состав» (ключ/файл есть только с одной стороны) и «значения». Нет разницы — метки совпадают, код возврата 0.

Что метка НЕ обещает: два прогона с одной меткой считаны по ОДНИМ правилам и одним окружением правил; результат совпадёт, если совпадает и код/модели/вход (их
сверяет проверка происхождения входа T-175/10). Метка не охватывает код этапа (его версию пишет та проверка) и правила вне набора (`include`).

Использование (только стандартная библиотека):
  rules_label.py [--root КОРЕНЬ] [--json]                  метка дерева (корень по умолчанию — дерево, где лежит этот файл)
  rules_label.py --expect ID [--root КОРЕНЬ]              код 1, если метка дерева ≠ ID
  rules_label.py --diff A B [--declared к1,к2|--declared-file f.json] [--json]
                                                           разница деревьев списком ключей; --declared — ключи, которым РАЗРЕШЕНО отличаться (флаги пробы): прочие — «не объявлено», код 1
  rules_label.py --env-check [--root КОРЕНЬ]             сторож окружения (код 1: скрипт конвейера читает переменную, которой нет в env / env_ignore)
  rules_label.py --env-table [--root КОРЕНЬ]             то же + таблица «переменная → файл:строка → env / не влияет → причина»
  rules_label.py --text-check [--root КОРЕНЬ]            сторож текстовых «_»-ключей (код 1: код читает такой ключ из правил, а в text_data / text_display его нет)
  rules_label.py --selftest
В коде: `from rules_label import label, field, diff_trees`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
CFG_PATH = os.path.join(HERE, 'rules', 'rules-label.json')
DEFAULT_CFG = {'include': ['tools/scout/rules'], 'exclude': [], 'env': [], 'length': 12, 'text_data': [], 'text_display': {}}


def load_cfg(path: str = CFG_PATH) -> dict:
    """Конфиг — из ЭТОГО дерева (одним конфигом считаются метки обоих сравниваемых деревьев); нет файла — встроенные значения."""
    cfg = dict(DEFAULT_CFG)
    try:
        with open(path, encoding='utf-8') as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith('_')})
    except (OSError, ValueError):
        pass
    return cfg


def text_data_names(cfg: dict | None = None) -> frozenset:
    """Имена текстовых «_»-ключей, которые — ДАННЫЕ (код читает значение как настройку: `_default: "hunyuan3d"` в asset-strategies.json): входят в метку. Список — `rules-label.json:text_data`."""
    return frozenset((cfg if cfg is not None else load_cfg()).get('text_data') or [])


def _is_comment(k, v, data=frozenset()) -> bool:
    """Комментарий — ключ на «_» с ТЕКСТОМ (`_about`, `_why`), если его имени нет в `text_data`. Ключ на «_» с числом/флагом/объектом/списком — ДАННЫЕ (`_default: 0`, `_any: {…}`):
    входит в метку; текстовый «_»-ключ с данными (`_default: "hunyuan3d"`) — по списку `text_data` (T-20261127-175/12-дыра: раньше все текстовые «_»-ключи считались комментариями,
    и правка `_default` метку не двигала)."""
    return str(k).startswith('_') and isinstance(v, str) and k not in data


def _strip(o, data=frozenset()):
    """Убрать ключи-комментарии (текстовые «_about», «_why», кроме `text_data`) на любой глубине; «_»-ключи с данными остаются."""
    if isinstance(o, dict):
        return {k: _strip(v, data) for k, v in o.items() if not _is_comment(k, v, data)}
    if isinstance(o, list):
        return [_strip(v, data) for v in o]
    return o


def rule_files(root: str, cfg: dict | None = None) -> list[str]:
    """→ пути файлов правил набора от корня, по порядку (один порядок на любой машине)."""
    cfg = cfg or load_cfg()
    ex = set(cfg.get('exclude') or [])
    out = set()
    for inc in cfg.get('include') or []:
        top = os.path.join(root, inc)
        if os.path.isfile(top):
            out.add(inc.replace(os.sep, '/'))
            continue
        for dp, _dn, fn in os.walk(top):
            for f in fn:
                rel = os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/')
                if f.endswith('.json') and rel not in ex and f not in ex:
                    out.add(rel)
    return sorted(out)


def _canon(path: str, data_names=frozenset()):
    """→ (каноническое представление для хеша, разобранный JSON или None). Не разобрался — байты как есть (метка не валит этап)."""
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        data = _strip(json.loads(raw.decode('utf-8')), data_names)
        return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), data
    except (ValueError, UnicodeDecodeError):
        return raw, None


def _env_part(cfg: dict) -> dict:
    """Выставленные переменные из `env`: имя → значение; у «путь к файлу правил» (`env_files` и всё на …RULES) добавляется sha файла, на который указывает."""
    out = {}
    files = set(cfg.get('env_files') or [])
    for name in cfg.get('env') or []:
        v = os.environ.get(name)
        if v is None:
            continue
        item = {'value': v}
        if (name in files or name.endswith('RULES')) and os.path.isfile(v):
            item['sha'] = hashlib.sha256(_canon(v, text_data_names(cfg))[0]).hexdigest()[:12]
        out[name] = item
    return out


def label(root: str | None = None, cfg: dict | None = None) -> dict:
    """→ {id, n, env, root, files{путь: sha[:12]}}; `id` — метка набора правил."""
    root = os.path.abspath(root or ROOT)
    cfg = cfg or load_cfg()
    h, n, files = hashlib.sha256(), 0, {}
    data = text_data_names(cfg)
    for rel in rule_files(root, cfg):
        canon, _ = _canon(os.path.join(root, rel), data)
        h.update(rel.encode('utf-8') + b'\0' + canon + b'\0')
        files[rel] = hashlib.sha256(canon).hexdigest()[:12]
        n += 1
    env = _env_part(cfg)
    if env:
        h.update(json.dumps(env, sort_keys=True, ensure_ascii=False).encode('utf-8'))
    ln = int(cfg.get('length', 12))
    return {'id': h.hexdigest()[:ln] if n else 'norules', 'n': n, 'env': env, 'root': root, 'files': files}


_CACHE: dict = {}


def field(root: str | None = None) -> dict:
    """Поле `rules_label` для check.json / run_all.json: {id, n, env, root}. НИКОГДА не бросает: сбой → {id: 'нет', why}. Считается один раз на процесс и корень."""
    key = os.path.abspath(root or ROOT)
    if key not in _CACHE:
        try:
            lb = label(key)
            _CACHE[key] = {'id': lb['id'], 'n': lb['n'], 'env': lb['env'], 'root': lb['root']}
        except Exception as e:  # noqa: BLE001 — отчёт этапа важнее метки; отсутствие метки видно и проверяется читателем
            _CACHE[key] = {'id': 'нет', 'why': f'{type(e).__name__}: {e}'[:200]}
    return dict(_CACHE[key])


def _flatten(o, prefix='') -> dict:
    """Листья JSON: путь через точку → значение (пустой словарь и список — лист)."""
    if isinstance(o, dict) and o:
        out = {}
        for k, v in o.items():
            out.update(_flatten(v, f'{prefix}.{k}' if prefix else str(k)))
        return out
    return {prefix: o}


def _tree_keys(root: str, cfg: dict) -> dict:
    """→ {путь_файла: {ключ.через.точку: значение} | None (не JSON)}."""
    out = {}
    names = text_data_names(cfg)
    for rel in rule_files(root, cfg):
        _c, data = _canon(os.path.join(root, rel), names)
        out[rel] = _flatten(data) if data is not None else None
    return out


def diff_trees(a: str, b: str, cfg: dict | None = None) -> list[dict]:
    """Разница двух деревьев (A — например проба, B — основная копия) списком ключей.
    Запись: {kind, file, key, a, b}; kind — `значение` (есть с обеих сторон, различается), `только_A` / `только_B` (ключ), `файл_только_A` / `файл_только_B`.
    `состав` — все kind кроме `значение`. Пусто — наборы совпадают по составу и значениям."""
    cfg = cfg or load_cfg()
    ta, tb = _tree_keys(a, cfg), _tree_keys(b, cfg)
    out = []
    for f in sorted(set(ta) | set(tb)):
        if f not in tb:
            out.append({'kind': 'файл_только_A', 'file': f, 'key': '', 'a': None, 'b': None})
            continue
        if f not in ta:
            out.append({'kind': 'файл_только_B', 'file': f, 'key': '', 'a': None, 'b': None})
            continue
        ka, kb = ta[f], tb[f]
        if ka is None or kb is None:
            if ka != kb:
                out.append({'kind': 'значение', 'file': f, 'key': '(файл не JSON)', 'a': 'другое содержимое', 'b': 'другое содержимое'})
            continue
        for k in sorted(set(ka) | set(kb)):
            if k not in kb:
                out.append({'kind': 'только_A', 'file': f, 'key': k, 'a': ka[k], 'b': None})
            elif k not in ka:
                out.append({'kind': 'только_B', 'file': f, 'key': k, 'a': None, 'b': kb[k]})
            elif ka[k] != kb[k]:
                out.append({'kind': 'значение', 'file': f, 'key': k, 'a': ka[k], 'b': kb[k]})
    return out


def _short(v) -> str:
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 60 else s[:57] + '…'


def split_declared(diffs: list[dict], declared) -> tuple[list[dict], list[dict], list[str]]:
    """→ (объявленные, НЕ объявленные, объявленные-но-не-отличающиеся). Объявление — `файл::ключ` либо `ключ` (любой файл), `файл::` — весь файл,
    префикс по точке (`gate.photo_denominator` покрывает `gate.photo_denominator.enabled`)."""
    decl = [d.strip() for d in (declared or []) if d and d.strip()]

    def covers(d: str, e: dict) -> bool:
        if '::' in d:
            f, k = d.split('::', 1)
            if not (e['file'] == f or e['file'].endswith('/' + f)):
                return False
        else:
            k = d
        return k == '' or e['key'] == k or e['key'].startswith(k + '.')
    ok = [e for e in diffs if any(covers(d, e) for d in decl)]
    bad = [e for e in diffs if e not in ok]
    unused = [d for d in decl if not any(covers(d, e) for e in diffs)]
    return ok, bad, unused


def render(diffs: list[dict], declared=None, name_a='A', name_b='B') -> list[str]:
    """Печать разницы: сперва состав, потом значения; у каждой строки — объявлена ли."""
    ok, bad, unused = split_declared(diffs, declared) if declared is not None else ([], diffs, [])
    mark = {id(e): '✓ объявлено' for e in ok}
    lines = []
    comp = [e for e in diffs if e['kind'] != 'значение']
    vals = [e for e in diffs if e['kind'] == 'значение']
    short_kind = {'только_A': f'ключ только в {name_a}', 'только_B': f'ключ только в {name_b}',
                  'файл_только_A': f'файл только в {name_a}', 'файл_только_B': f'файл только в {name_b}'}
    if comp:
        lines.append(f'СОСТАВ (что есть только с одной стороны): {len(comp)}')
        for e in comp:
            tail = f'  {name_a if e["kind"] == "только_A" else name_b}={_short(e["a"] if e["kind"] == "только_A" else e["b"])}' if e['kind'].startswith('только') else ''
            lines.append(f'  {e["file"]}::{e["key"]}  — {short_kind[e["kind"]]}{tail}  {mark.get(id(e), "❗ не объявлено" if declared is not None else "")}'.rstrip())
    if vals:
        lines.append(f'ЗНАЧЕНИЯ (есть с обеих сторон, различаются): {len(vals)}')
        for e in vals:
            lines.append(f'  {e["file"]}::{e["key"]}  {name_a}={_short(e["a"])}  {name_b}={_short(e["b"])}  {mark.get(id(e), "❗ не объявлено" if declared is not None else "")}'.rstrip())
    for d in unused:
        lines.append(f'  ⚠ объявлено «{d}», но по этому ключу разницы нет (флаг не выставлен или уже в основной копии)')
    return lines


# ───────────── сторож текстовых «_»-ключей (T-20261127-175/12-дыра, проверка Fable 27.11) ─────────────
# Текстовый ключ на «_» — по умолчанию комментарий, метку не двигает. Но `asset-strategies.json roles._default = "hunyuan3d"` — настройка (4 модуля читают её как данные),
# а метка этого не видела. Сторож: имя текстового «_»-ключа из файлов правил, которое КОД читает (`.get('_x')`, `['_x']`), обязано стоять в `text_data` (данные → в метке) или
# в `text_display` {имя: причина} (читается только для показа в отчётах). Плюс эвристика: текстовое значение без пробелов и короче 40 знаков (похоже на настройку, не на фразу)
# у имени из обоих списков отсутствующего — находка. Динамическое чтение (`for k in d: if k.startswith('_')`) сторож не видит — это ограничение, оно записано здесь.
import re  # noqa: E402

_CODE_EXT = ('.py', '.mjs', '.js', '.ts', '.tsx')
_CODE_SKIP = {'node_modules', '.git', '__pycache__', '.next', 'tests', '_intake', 'archive', 'completed_plans'}


def _text_keys(root: str, cfg: dict) -> dict:
    """→ {имя: [(файл, путь_ключа, значение)]} — текстовые «_»-ключи во всех файлах набора."""
    out: dict = {}

    def walk(o, path, rel):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).startswith('_') and isinstance(v, str):
                    out.setdefault(k, []).append((rel, path, v))
                walk(v, f'{path}.{k}' if path else str(k), rel)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f'{path}[{i}]', rel)
    for rel in rule_files(root, cfg):
        try:
            with open(os.path.join(root, rel), encoding='utf-8') as f:
                walk(json.load(f), '', rel)
        except (OSError, ValueError):
            pass
    return out


def _code_reads(root: str, names, scan) -> dict:
    """→ {имя: [файл:строка]} — где код читает ключ с этим именем (`.get('_x'`, `['_x']`; запись `d['_x'] = …` не чтение). Тесты (`test_*`, `tests_*`, `tests/`) не смотрим."""
    want = set(names)
    rx = re.compile(r'(?:\.get\(\s*|\[\s*)[\'"](_\w+)[\'"]')   # один проход по строке: имя берём из совпадения и сверяем со списком
    wr = re.compile(r'^\s*\]?\s*=[^=]')
    hits: dict = {}
    for top in scan:
        for dp, dn, fn in os.walk(os.path.join(root, top)):
            dn[:] = sorted(d for d in dn if d not in _CODE_SKIP)
            for f in sorted(fn):
                if not f.endswith(_CODE_EXT) or f.startswith(('test_', 'tests_')):
                    continue
                p = os.path.join(dp, f)
                try:
                    with open(p, encoding='utf-8') as fh:
                        lines = fh.read().split('\n')
                except (OSError, UnicodeDecodeError):
                    continue
                for i, ln in enumerate(lines, 1):
                    if '_' not in ln:
                        continue
                    for m in rx.finditer(ln):
                        if m.group(1) in want and not (ln[m.end():].lstrip().startswith(']') and wr.match(ln[m.end():].lstrip()[1:])):   # `d['_x'] = …` — запись, не чтение
                            hits.setdefault(m.group(1), []).append(f'{os.path.relpath(p, root).replace(os.sep, "/")}:{i}')
    return hits


def text_key_gaps(root: str | None = None, cfg: dict | None = None) -> list:
    """Сторож: пусто = каждый текстовый «_»-ключ, который читает код, отнесён либо к данным (`text_data`), либо к «только показ» (`text_display` с причиной)."""
    root = os.path.abspath(root or ROOT)
    cfg = cfg or load_cfg(os.path.join(root, 'tools', 'scout', 'rules', 'rules-label.json'))
    data, disp = set(cfg.get('text_data') or []), (cfg.get('text_display') or {})
    gaps = []
    for n, why in sorted(disp.items()):
        if not isinstance(why, str) or not why.strip():
            gaps.append(f'{n} — запись в text_display без причины (одной строкой: где код читает её только для показа)')
        if n in data:
            gaps.append(f'{n} — одновременно в text_data и в text_display: данные это или показ?')
    keys = _text_keys(root, cfg)
    known = data | set(disp)
    scan = [d for d in (cfg.get('code_roots') or ['tools', 'services', 'lib', 'app', 'components']) if os.path.isdir(os.path.join(root, d))]
    if not scan:
        gaps.append(f'в корне {root} нет ни одной папки кода из code_roots — сторож текстовых «_»-ключей слеп (ничего не проверено)')
    reads = _code_reads(root, [n for n in keys if n not in known], scan)
    for n, where in sorted(reads.items()):
        f, p, _v = keys[n][0]
        gaps.append(f'{n} — {where[0]} (всего чтений {len(where)}) — код читает текстовый «_»-ключ из файлов правил ({f}::{p}); метка считает его комментарием. '
                    f'Данные — добавьте в text_data (rules/rules-label.json), только показ — в text_display с причиной')
    for n, vals in sorted(keys.items()):
        if n in known or n in reads:
            continue
        for f, p, v in vals:
            if v.strip() and not re.search(r'\s', v.strip()) and len(v.strip()) < 40:
                gaps.append(f'{n} — {f}::{p} = «{v}» — значение без пробелов, похоже на настройку, а не на фразу: данные → text_data, комментарий → text_display с причиной')
    return gaps


# ───────────── сторож окружения (T-20261127-175/12-дыра) ─────────────
# Метка видит только переменные из `env`. Скрипт конвейера прочёл новую переменную, а в конфиге её нет → метка молчит, хотя результат уже другой.
# Сторож по AST читает все скрипты рецепта `paint-run-all.json` и то, что они импортируют (кроме `env_stop`), и для КАЖДОГО чтения окружения требует запись:
# `env` (влияет на результат → в метку) или `env_ignore` {имя: причина} (не влияет: путь, ключ, отладка, потоки, кэш). Нет записи / нет причины → находка.
_ENV_ATTRS = ('get', 'pop', 'setdefault')


def _is_environ(n) -> bool:
    """Узел — `os.environ` / `environ` / `(os.environ if env is None else env)` (так прячут окружение за подменой в тестах)."""
    import ast
    if isinstance(n, ast.Attribute):
        return n.attr == 'environ'
    if isinstance(n, ast.Name):
        return n.id == 'environ'
    if isinstance(n, ast.IfExp):
        return _is_environ(n.body) or _is_environ(n.orelse)
    return False


def env_reads(path: str) -> list:
    """Чтения окружения в файле → [(имя | None, строка)]; None — имя не литерал (`environ.get(k)`). Ловит `os.environ[..]`, `.get/.pop/.setdefault`, `os.getenv`, `getenv`,
    `'X' in os.environ`, в т.ч. через подмену `(os.environ if env is None else env).get('X')`."""
    import ast
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read(), path)
    res = []

    def lit(a):
        return (a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None)
    for n in ast.walk(tree):
        a = None
        hit = False
        if isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Attribute) and ((fn.attr in _ENV_ATTRS and _is_environ(fn.value)) or (fn.attr == 'getenv' and isinstance(fn.value, ast.Name) and fn.value.id == 'os')):
                hit, a = True, (n.args[0] if n.args else None)
            elif isinstance(fn, ast.Name) and fn.id == 'getenv':
                hit, a = True, (n.args[0] if n.args else None)
        elif isinstance(n, ast.Subscript) and _is_environ(n.value):
            hit, a = True, n.slice
        elif isinstance(n, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops) and any(_is_environ(c) for c in n.comparators):
            hit, a = True, n.left
        if hit:
            res.append((lit(a) if a is not None else None, n.lineno))
    return sorted(res, key=lambda t: (t[1], str(t[0])))


def _py_names(root: str) -> dict:
    """имя модуля → [пути .py от корня] по `tools/` (без тестов, node_modules)."""
    idx: dict = {}
    for dp, dn, fn in os.walk(os.path.join(root, 'tools')):
        dn[:] = [d for d in dn if d not in ('node_modules', '__pycache__', '.git', 'tests')]
        for f in fn:
            if f.endswith('.py') and not f.startswith(('test_', 'tests_')):
                idx.setdefault(f[:-3], []).append(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/'))
    return idx


def _imported(path: str) -> set:
    import ast
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read(), path)
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split('.')[-1] for a in n.names} | {a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                out |= {n.module.split('.')[0], n.module.split('.')[-1]}
            out |= {a.name for a in n.names}
    return out


def conveyor_files(root: str, cfg: dict | None = None) -> tuple:
    """→ (файлы конвейера от корня, находки). Старт — скрипты `{root}/….py` из рецепта `cfg.env_recipe`; дальше — импорты (одноимённые модули — ближайший по пути, при ничьей все);
    файлы из `cfg.env_stop` (путь → причина) не открываются и дальше не идут; из `cfg.env_leaf` — открываются, но их импорты не разворачиваются; `cfg.env_extra` (путь → причина) — добавочные стартовые скрипты (форма, вырезка). Рецепт или скрипт не открылся / не разобрался — находка (сторож не слепнет молча)."""
    cfg = cfg or load_cfg()
    stop, leaf = set((cfg.get('env_stop') or {}).keys()), set((cfg.get('env_leaf') or {}).keys())
    rec_rel = cfg.get('env_recipe') or 'tools/scout/rules/paint-run-all.json'
    gaps, start = [], []
    try:
        with open(os.path.join(root, rec_rel), encoding='utf-8') as f:
            rec = json.load(f)
        for st in (rec.get('stages') or {}).values():
            for step in st.get('steps', []):
                for tok in step.get('argv') or []:
                    if isinstance(tok, str) and tok.startswith('{root}/') and tok.endswith('.py'):
                        start.append(tok[len('{root}/'):])
    except (OSError, ValueError) as e:
        return [], [f'рецепт {rec_rel} не прочитан ({type(e).__name__}) — сторож окружения слеп']
    start += [x for x in (cfg.get('env_extra') or {}) if isinstance(x, str)]   # скрипты формы/вырезки вне рецепта покраски (путь → причина)
    idx = _py_names(root)
    seen, queue = set(), sorted(set(start))
    while queue:
        rel = queue.pop()
        if rel in seen or rel in stop:
            continue
        seen.add(rel)
        if rel in leaf:                                 # читается сам, но его импорты дальше не идут (тянут каталог/комнаты/демо)
            continue
        try:
            names = _imported(os.path.join(root, rel))
        except (OSError, SyntaxError) as e:
            gaps.append(f'{rel}: скрипт конвейера не разобран ({type(e).__name__}) — сторож окружения его не видит')
            continue
        here = os.path.dirname(rel)
        for m in sorted(names):
            cands = idx.get(m) or []
            if len(cands) > 1:
                score = {c: len(os.path.commonpath([os.path.dirname(c) or '.', here or '.'])) for c in cands}
                best = max(score.values())
                cands = [c for c in cands if score[c] == best]
            for c in cands:
                if c not in seen:
                    queue.append(c)
    return sorted(seen), gaps


def env_gaps(root: str | None = None, cfg: dict | None = None) -> list:
    """Сторож окружения: пусто = каждое чтение окружения в скриптах конвейера учтено. Находка — строка «ИМЯ — файл:строка — …» (имя и место видны в красной проверке).
    Учтено = имя в `cfg.env` (входит в метку) ИЛИ в `cfg.env_ignore` с непустой причиной. Динамическое чтение (имя не литерал) — запись `<динамическое>:файл.py` в `env_ignore`.
    Имя в обоих списках, запись `env_ignore` без причины — тоже находки."""
    root = os.path.abspath(root or ROOT)
    cfg = cfg or load_cfg(os.path.join(root, 'tools', 'scout', 'rules', 'rules-label.json'))
    env, ign = set(cfg.get('env') or []), (cfg.get('env_ignore') or {})
    files, gaps = conveyor_files(root, cfg)
    for name, why in sorted(ign.items()):
        if not isinstance(why, str) or not why.strip():
            gaps.append(f'{name} — запись в env_ignore без причины (одной строкой: почему переменная не влияет на результат)')
        if name in env:
            gaps.append(f'{name} — одновременно в env и в env_ignore: определитесь, влияет ли она на результат')
    for rel in files:
        try:
            reads = env_reads(os.path.join(root, rel))
        except (OSError, SyntaxError) as e:
            gaps.append(f'{rel}: не разобран ({type(e).__name__})')
            continue
        for name, ln in reads:
            if name is None:
                if f'<динамическое>:{os.path.basename(rel)}' not in ign:
                    gaps.append(f'<динамическое чтение> — {rel}:{ln} — имя переменной не литерал; запишите «<динамическое>:{os.path.basename(rel)}» в env_ignore с причиной')
            elif name not in env and name not in ign:
                gaps.append(f'{name} — {rel}:{ln} — скрипт конвейера читает переменную, которой нет ни в env, ни в env_ignore (rules/rules-label.json): метка её не видит')
    return gaps


def env_table(root: str | None = None, cfg: dict | None = None) -> list:
    """Таблица для отчёта: [(имя, 'env'|'не влияет'|'НЕТ ЗАПИСИ', причина, 'файл:строка; …')] по всем читаемым в конвейере переменным."""
    root = os.path.abspath(root or ROOT)
    cfg = cfg or load_cfg(os.path.join(root, 'tools', 'scout', 'rules', 'rules-label.json'))
    env, ign = set(cfg.get('env') or []), (cfg.get('env_ignore') or {})
    files, _ = conveyor_files(root, cfg)
    where: dict = {}
    for rel in files:
        try:
            for name, ln in env_reads(os.path.join(root, rel)):
                where.setdefault(name or f'<динамическое>:{os.path.basename(rel)}', []).append(f'{rel}:{ln}')
        except (OSError, SyntaxError):
            pass
    return [(n, 'env' if n in env else ('не влияет' if n in ign else 'НЕТ ЗАПИСИ'), ign.get(n, ''), '; '.join(w)) for n, w in sorted(where.items())]


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Метка набора правил и разница двух деревьев списком ключей (T-175/12)')
    ap.add_argument('--root', default=None, help='корень дерева (по умолчанию — дерево этого файла)')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--expect', default=None, metavar='ID', help='код 1, если метка дерева ≠ ID')
    ap.add_argument('--diff', nargs=2, metavar=('A', 'B'), help='сравнить два дерева (A — проба/ветка, B — основная копия)')
    ap.add_argument('--declared', default='', help='ключи, которым разрешено отличаться (через запятую)')
    ap.add_argument('--declared-file', default='', help='JSON-список таких ключей')
    ap.add_argument('--env-check', action='store_true', help='сторож окружения: код 1, если скрипт конвейера читает переменную без записи в env / env_ignore')
    ap.add_argument('--env-table', action='store_true', help='таблица «переменная → файл:строка → env / не влияет → причина» по скриптам конвейера')
    ap.add_argument('--text-check', action='store_true', help='сторож текстовых «_»-ключей: код 1, если код читает такой ключ из файлов правил, а в text_data / text_display его нет')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.text_check:
        gaps = text_key_gaps(os.path.abspath(a.root or ROOT))
        for g in gaps:
            print('✗', g, file=sys.stderr)
        print(f'сторож текстовых «_»-ключей: {"красный, находок " + str(len(gaps)) if gaps else "чисто"}')
        return 1 if gaps else 0
    if a.env_check or a.env_table:
        root = os.path.abspath(a.root or ROOT)
        if a.env_table:
            for n, kind, why, wh in env_table(root):
                print(f'{n} | {kind} | {why} | {wh}')
        gaps = env_gaps(root)
        for g in gaps:
            print('✗', g, file=sys.stderr)
        print(f'сторож окружения: {"красный, находок " + str(len(gaps)) if gaps else "чисто"}')
        return 1 if gaps else 0
    if a.selftest:
        print('самопроверка — tools/scout/tests/test_rules_label.py')
        return 0
    if a.diff:
        declared = None
        if a.declared or a.declared_file:
            declared = [x for x in a.declared.split(',') if x.strip()]
            if a.declared_file:
                declared += json.load(open(a.declared_file, encoding='utf-8'))
        d = diff_trees(a.diff[0], a.diff[1])
        la, lb = label(a.diff[0])['id'], label(a.diff[1])['id']
        if a.json:
            print(json.dumps({'A': la, 'B': lb, 'diff': d}, ensure_ascii=False, indent=1))
        else:
            print(f'метка A {la} ({a.diff[0]})  |  метка B {lb} ({a.diff[1]})')
            if not d:
                print('наборы правил совпадают по составу и значениям')
            for line in render(d, declared):
                print(line)
        if declared is None:
            return 1 if d else 0
        return 1 if split_declared(d, declared)[1] else 0
    lb = label(a.root)
    if a.json:
        print(json.dumps(lb, ensure_ascii=False, indent=1))
    else:
        env = f', env: {", ".join(lb["env"])}' if lb['env'] else ''
        print(f'метка {lb["id"]}  ({lb["n"]} файлов{env})  {lb["root"]}')
    if a.expect and a.expect != lb['id']:
        print(f'✗ метка дерева {lb["id"]} ≠ ожидаемой {a.expect}: правила не те, по которым считан эталон', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
