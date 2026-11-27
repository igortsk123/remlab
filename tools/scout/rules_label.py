#!/usr/bin/env python3
"""МЕТКА НАБОРА ПРАВИЛ (T-20261127-175/12, Fable 29 § 3 ступень А): один набор чисел правил — проба = ветка = основная копия по составу.

ЗАЧЕМ. Экзамен на «замороженных правилах» нечем проверить, пока в отчёте этапа не написано, ПО КАКИМ правилам он посчитан. Профиль пробы (копия дерева с
накладкой ключей — `mk_probe15.sh`, `merge_new_keys.py`, `set_rules.py`) раньше расходился с основной копией молча: «проба прошла» ≠ «ветка пройдёт».

ЧТО ЭТО.
  метка  — первые 12 знаков sha256 ВСЕХ файлов правил набора (по умолчанию `tools/scout/rules/**.json`, кроме перечисленных в `rules/rules-label.json:exclude`):
           путь от корня + содержимое. JSON берётся КАНОНИЧЕСКИ (ключи по алфавиту, без пробелов, ключи на «_» — комментарии `_about/_why` — не в счёт):
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
DEFAULT_CFG = {'include': ['tools/scout/rules'], 'exclude': [], 'env': [], 'length': 12}


def load_cfg(path: str = CFG_PATH) -> dict:
    """Конфиг — из ЭТОГО дерева (одним конфигом считаются метки обоих сравниваемых деревьев); нет файла — встроенные значения."""
    cfg = dict(DEFAULT_CFG)
    try:
        with open(path, encoding='utf-8') as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith('_')})
    except (OSError, ValueError):
        pass
    return cfg


def _strip(o):
    """Убрать ключи-комментарии («_about», «_why») на любой глубине."""
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if not str(k).startswith('_')}
    if isinstance(o, list):
        return [_strip(v) for v in o]
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


def _canon(path: str):
    """→ (каноническое представление для хеша, разобранный JSON или None). Не разобрался — байты как есть (метка не валит этап)."""
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        data = _strip(json.loads(raw.decode('utf-8')))
        return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), data
    except (ValueError, UnicodeDecodeError):
        return raw, None


def _env_part(cfg: dict) -> dict:
    """Выставленные переменные из `env`: имя → значение; у «путь к правилам» (…RULES) добавляется sha файла, на который указывает."""
    out = {}
    for name in cfg.get('env') or []:
        v = os.environ.get(name)
        if v is None:
            continue
        item = {'value': v}
        if name.endswith('RULES') and os.path.isfile(v):
            item['sha'] = hashlib.sha256(_canon(v)[0]).hexdigest()[:12]
        out[name] = item
    return out


def label(root: str | None = None, cfg: dict | None = None) -> dict:
    """→ {id, n, env, root, files{путь: sha[:12]}}; `id` — метка набора правил."""
    root = os.path.abspath(root or ROOT)
    cfg = cfg or load_cfg()
    h, n, files = hashlib.sha256(), 0, {}
    for rel in rule_files(root, cfg):
        canon, _ = _canon(os.path.join(root, rel))
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
    for rel in rule_files(root, cfg):
        _c, data = _canon(os.path.join(root, rel))
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


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Метка набора правил и разница двух деревьев списком ключей (T-175/12)')
    ap.add_argument('--root', default=None, help='корень дерева (по умолчанию — дерево этого файла)')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--expect', default=None, metavar='ID', help='код 1, если метка дерева ≠ ID')
    ap.add_argument('--diff', nargs=2, metavar=('A', 'B'), help='сравнить два дерева (A — проба/ветка, B — основная копия)')
    ap.add_argument('--declared', default='', help='ключи, которым разрешено отличаться (через запятую)')
    ap.add_argument('--declared-file', default='', help='JSON-список таких ключей')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
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
