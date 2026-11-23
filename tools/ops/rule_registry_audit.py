#!/usr/bin/env python3
"""Автосверка реестра правил (T-20261123-48, 48/2; план type-rules-code-01 § Б; владелец TG 2308; аудит Codex a-dupes-1123 § 3 п.1, 2, 4, 5).

ЗАЧЕМ. «Правило записано» ≠ «правило работает»: код бывает выключен (observe/off/флаг), не вызывается, не имеет теста на плохом и хорошем примере, не доходит до
прогона. Сверка часа (P-068) делалась глазами и пропускала таблицу К1–К8. Здесь — машинная сверка `tools/scout/rules/rule-registry.json` с репозиторием; стандартная библиотека.

ЧТО СВЕРЯЕТ (на каждое правило не-retired) — ПОВЕДЕНИЕ, не слово:
  • схема: rule_id уникален и по шаблону, state/runtime из закрытых списков, applies.types ⊂ типы паспорта (или «all»), applies.families ⊂ семейства;
  • consumer `путь:символ` — разбор через ast: функция/класс/константа с этим именем ОПРЕДЕЛЕНА в файле (упоминание в строке/комментарии не считается) и ИСПОЛЬЗУЕТСЯ
    боевым кодом (вызов/ссылка вне своего определения, вне тестов); есть, но не используется → «символ есть, но не вызывается»;
  • flag `файл.json#a.b` — значение ключа должно быть включено (True / «enforce» / «on» / «active»); выключено → «код есть, но observe/выключен», что бы ни писал runtime;
  • test / test_positive / test_negative `путь::функция` — файл есть, функция найдена через ast, файл прописан в ci.yml;
  • active = consumer определён и используется + runtime=enforce и флаг включён + тест в CI + ПОЛОЖИТЕЛЬНЫЙ и ОТРИЦАТЕЛЬНЫЙ тесты на пример типа + `run_id` прогона.
    Иначе — ОШИБКА (rc=1, CI красный): правило с такими пробелами должно быть trial;
  • trial/proposed с объявленными, но НЕ существующими путями/символами — ошибка (битая ссылка);
  • типы паспорта без политики покраски (`paint.hidden_pattern`) — «тип без политики» (ошибка при `--strict-types`; в CI включено, А1 влит);
  • `--run <папка прогона>` — СТРУКТУРНО: у active в `*/<этап>/check.json` (этап — до точки в `check_field`) в `extra.rules[]` есть записи правила: rule_id, type,
    digest паспорта типа (= `mesh_type_passports.digest_of`) и `applied: true` либо `abstain` с причиной. Пустой охват (нет check.json / нет записей правила) = ошибка;
    применимые типы, встреченные в прогоне, но без записи правила = ошибка.
КЛАССЫ: «битая ссылка/схема» · «нет кода» · «символ есть, но не вызывается» · «код есть, но observe/выключен» · «нет теста / тест не в CI» · «нет парных тестов/прогона» ·
«включено, в прогоне не достигнуто» · «тип без политики».

  python tools/ops/rule_registry_audit.py                     # отчёт классами (rc=0 кроме --check)
  python tools/ops/rule_registry_audit.py --check --strict-types   # CI: rc=1 при ошибках
  python tools/ops/rule_registry_audit.py --json out.json     # + отчёт в JSON для обхода ЧЧ:02 (по классу — список правил → задачи)
  python tools/ops/rule_registry_audit.py --run <папка прогона>
"""
from __future__ import annotations

import argparse
import ast
import collections
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(ROOT, 'tools', 'scout', 'rules', 'rule-registry.json')
PASSPORTS = os.path.join(ROOT, 'tools', 'scout', 'rules', 'mesh-type-passports.json')
CI = os.path.join(ROOT, '.github', 'workflows', 'ci.yml')

STATES = ('proposed', 'trial', 'active', 'retired')
RUNTIMES = ('enforce', 'observe', 'off', 'none')
ID_RE = re.compile(r'^R-[A-Z0-9]+(-[A-Z0-9]+)*$')
RUN_ID_RE = re.compile(r'^[\w.\-/]+$')
REQ = ('rule_id', 'title', 'state', 'source', 'applies', 'executor', 'consumer', 'runtime', 'test', 'test_positive', 'test_negative', 'run_id', 'flag',
       'check_field', 'enabled')
ON_VALUES = (True, 'enforce', 'on', 'active')
SKIP_DIRS = ('node_modules', '__pycache__', '.git', 'tests', 'test', 'fixtures')

C_BROKEN = 'битая ссылка/схема'
C_NOCODE = 'нет кода'
C_NOCALL = 'символ есть, но не вызывается'
C_OBSERVE = 'код есть, но observe/выключен'
C_NOTEST = 'нет теста / тест не в CI'
C_NOPAIR = 'нет парных тестов/прогона'
C_NOTREACHED = 'включено, в прогоне не достигнуто'
C_NOPOLICY = 'тип без политики'
CLASSES = (C_BROKEN, C_NOCODE, C_NOCALL, C_OBSERVE, C_NOTEST, C_NOPAIR, C_NOTREACHED, C_NOPOLICY)


def _read(path: str) -> str:
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def split_ref(ref: str | None) -> tuple:
    """'путь:символ' → (путь, символ); 'путь::имя' → (путь, имя); 'путь' → (путь, '')."""
    if not ref:
        return ('', '')
    if '::' in ref:
        p, n = ref.split('::', 1)
        return (p, n)
    if ':' in ref:
        p, n = ref.rsplit(':', 1)
        return (p, n)
    return (ref, '')


def _parse(path: str):
    try:
        return ast.parse(_read(path), filename=path)
    except (SyntaxError, ValueError):
        return None


def defined_nodes(tree, name: str) -> list:
    """Узлы, где `name` ОПРЕДЕЛЁН: функция/класс (любой вложенности) или присваивание имени на уровне модуля/класса."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            out.append(n)
        elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            out.append(n)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name:
            out.append(n)
    return out


def symbol_status(root: str, path: str, name: str) -> dict:
    """→ {'defined': bool, 'kind': 'ast'|'text', 'used': bool}. Для .py — ast; для прочих файлов (json/js) — слово в тексте (kind=text, used=True)."""
    full = os.path.join(root, path)
    if not path.endswith('.py'):
        t = _read(full)
        return {'defined': bool(t) and (not name or bool(re.search(r'\b%s\b' % re.escape(name), t))), 'kind': 'text', 'used': True}
    tree = _parse(full)
    if tree is None:
        return {'defined': False, 'kind': 'ast', 'used': False, 'why': 'файл не разобран ast'}
    defs = defined_nodes(tree, name) if name else []
    if name and not defs:
        return {'defined': False, 'kind': 'ast', 'used': False}
    return {'defined': True, 'kind': 'ast', 'used': (not name) or is_used(root, full, name, defs)}


def _production_files(root: str):
    base = os.path.join(root, 'tools')
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in fns:
            if fn.endswith('.py') and not fn.startswith(('test_', 'tests_')) and not fn.endswith(('_test.py', 'dbtest.py')) and fn != 'rule_registry_audit.py':
                yield os.path.join(dp, fn)


def is_used(root: str, def_file: str, name: str, def_nodes: list) -> bool:
    """Имя используется боевым кодом: Name/Attribute/импорт вне собственного определения (рекурсия и сам `def` не считаются), файлы тестов не считаются."""
    own = set()
    for dn in def_nodes:
        own.update(id(x) for x in ast.walk(dn))
    for f in _production_files(root):
        text = _read(f)
        if name not in text:
            continue
        tree = ast.parse(text, filename=f) if _safe(text) else None
        if tree is None:
            continue
        same = os.path.realpath(f) == os.path.realpath(def_file)
        for n in ast.walk(tree):
            if same and id(n) in own:
                continue
            if (isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)) or (isinstance(n, ast.Attribute) and n.attr == name):
                return True
            if isinstance(n, (ast.ImportFrom, ast.Import)) and any((a.name.split('.')[-1] == name) for a in n.names):
                return True
    return False


def _safe(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except (SyntaxError, ValueError):
        return False


def test_exists(root: str, ref: str) -> tuple:
    """`путь::функция` → (ok, why). Функция ищется через ast (def на любом уровне, в т.ч. метод)."""
    p, n = split_ref(ref)
    t = _read(os.path.join(root, p))
    if not t:
        return False, 'файла нет — %s' % p
    if n:
        tree = _parse(os.path.join(root, p))
        if tree is None or not any(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == n for x in ast.walk(tree)):
            return False, 'функция «%s» не найдена (ast) в %s' % (n, p)
    return True, ''


def flag_state(root: str, flag: str | None):
    """`файл.json#a.b` → (значение, текст). None-флаг = нет проверки."""
    if not flag:
        return (None, '')
    f, _, key = flag.partition('#')
    try:
        d = json.loads(_read(os.path.join(root, f)))
    except ValueError:
        return ('<ошибка>', 'флаг %s: файл не читается' % flag)
    cur = d
    for k in [x for x in key.split('.') if x]:
        if not isinstance(cur, dict) or k not in cur:
            return ('<нет ключа>', 'флаг %s: нет ключа' % flag)
        cur = cur[k]
    return (cur, '')


def load_passports(path: str = PASSPORTS) -> dict:
    d = json.loads(_read(path) or '{}')
    t = d.get('types') or {}
    return dict(t) if isinstance(t, dict) else {}


def _digest_fn(root: str):
    sc = os.path.join(root, 'tools', 'scout')
    if sc not in sys.path:
        sys.path.insert(0, sc)
    try:
        import mesh_type_passports as MP
        return MP.digest_of
    except Exception:  # noqa: BLE001
        return None


def check_run(rule: dict, run_dir: str, passports: dict, root: str, add) -> None:
    """Структурная сверка прогона для active-правила (см. докстринг). Ошибки — add(..., error=True)."""
    rid = rule['rule_id']
    stage = str(rule.get('check_field') or '').partition('.')[0]
    if not stage:
        add(rid, C_NOTREACHED, 'у active нет check_field (этап прогона)', True)
        return
    files = sorted(glob.glob(os.path.join(run_dir, '*', stage, 'check.json')))
    if not files:
        add(rid, C_NOTREACHED, 'пустой охват: в %s нет */%s/check.json' % (run_dir, stage), True)
        return
    dg = _digest_fn(root)
    ap = rule.get('applies') or {}
    fams = set(ap.get('families') or [])
    tps = set(ap.get('types') or [])
    allowed = {t for t, v in passports.items() if 'all' in tps or t in tps or (fams and (v or {}).get('family') in fams)}
    covered, seen, entries = set(), set(), 0
    for f in files:
        try:
            ex = (json.loads(_read(f)).get('extra') or {})
        except ValueError:
            add(rid, C_NOTREACHED, 'check.json не читается: %s' % f, True)
            continue
        for e in ex.get('rules') or []:
            if not isinstance(e, dict):
                continue
            if e.get('type'):
                seen.add(e['type'])
            if e.get('rule_id') != rid:
                continue
            entries += 1
            t = e.get('type')
            covered.add(t)
            if t not in passports:
                add(rid, C_NOTREACHED, 'запись с типом «%s» не из паспорта (%s)' % (t, f), True)
                continue
            want = dg(passports[t]) if dg else None
            if dg is None:
                add(rid, C_NOTREACHED, 'не удалось импортировать mesh_type_passports.digest_of — digest не проверить', True)
            elif e.get('digest') != want:
                add(rid, C_NOTREACHED, 'digest паспорта «%s» в %s не совпал с текущим' % (t, f), True)
            if not (e.get('applied') is True or (isinstance(e.get('abstain'), str) and e['abstain'].strip())):
                add(rid, C_NOTREACHED, 'тип «%s» в %s: нет ни applied=true, ни abstain с причиной' % (t, f), True)
    if not entries:
        add(rid, C_NOTREACHED, 'пустой охват: в %d check.json этапа %s нет записей extra.rules[] правила' % (len(files), stage), True)
        return
    missing = sorted((allowed & seen) - covered)
    if missing:
        add(rid, C_NOTREACHED, 'применимые типы из прогона без записи правила: %s' % ', '.join(missing), True)


def audit(registry_path: str = REGISTRY, passports_path: str = PASSPORTS, ci_path: str = CI, root: str = ROOT, run_dir: str = '') -> dict:
    """→ {'rules': n, 'problems': [{rule_id, cls, why, error}], 'by_state': {...}}. error=True — валит CI."""
    out = {'problems': [], 'by_state': {}, 'rules': 0}
    try:
        reg = json.loads(_read(registry_path))
    except ValueError as e:
        out['problems'].append({'rule_id': '-', 'cls': C_BROKEN, 'why': 'реестр не читается: %s' % e, 'error': True})
        return out
    rules = reg.get('rules') if isinstance(reg, dict) else None
    if not isinstance(rules, list) or not rules:
        out['problems'].append({'rule_id': '-', 'cls': C_BROKEN, 'why': 'нет списка rules', 'error': True})
        return out
    passports = load_passports(passports_path)
    families = {v.get('family') for v in passports.values() if isinstance(v, dict) and v.get('family')}
    ci = _read(ci_path)
    seen = set()
    out['rules'] = len(rules)

    def add(rid, cls, why, error=False):
        out['problems'].append({'rule_id': rid, 'cls': cls, 'why': why, 'error': bool(error)})

    for r in rules:
        rid = str(r.get('rule_id') or '?')
        miss = [k for k in REQ if k not in r]
        if miss:
            add(rid, C_BROKEN, 'нет полей: %s' % ', '.join(miss), True)
            continue
        if not ID_RE.match(rid):
            add(rid, C_BROKEN, 'rule_id не по шаблону R-XXX', True)
        if rid in seen:
            add(rid, C_BROKEN, 'rule_id повторяется', True)
        seen.add(rid)
        st, rt = r['state'], r['runtime']
        out['by_state'][st] = out['by_state'].get(st, 0) + 1
        if st not in STATES:
            add(rid, C_BROKEN, 'state «%s» не из %s' % (st, STATES), True)
            continue
        if rt not in RUNTIMES:
            add(rid, C_BROKEN, 'runtime «%s» не из %s' % (rt, RUNTIMES), True)
        if not isinstance(r['source'], list) or not r['source']:
            add(rid, C_BROKEN, 'source пуст (откуда правило — TG/ADR/план)', True)
        ap = r['applies'] if isinstance(r['applies'], dict) else {}
        if not ap or not (ap.get('types') or ap.get('families')):
            add(rid, C_BROKEN, 'applies без types/families', True)
        for t in ap.get('types') or []:
            if t != 'all' and passports and t not in passports:
                add(rid, C_BROKEN, 'тип «%s» не из паспорта типов' % t, True)
        for fam in ap.get('families') or []:
            if families and fam not in families:
                add(rid, C_BROKEN, 'семейство «%s» не из паспорта типов' % fam, True)
        if st == 'retired':
            continue
        active = st == 'active'
        # consumer: определён (ast) и используется боевым кодом
        cpath, csym = split_ref(r['consumer'])
        code_ok = used = False
        if cpath:
            info = symbol_status(root, cpath, csym)
            if not _read(os.path.join(root, cpath)):
                add(rid, C_BROKEN, 'consumer: файла нет — %s' % cpath, True)
            elif not info['defined']:
                add(rid, C_BROKEN, 'consumer: «%s» не определён в %s (ast; упоминание в тексте не считается)' % (csym, cpath), True)
            else:
                code_ok, used = True, info['used']
                if not used:
                    add(rid, C_NOCALL, '%s: «%s» определён в %s, но боевой код его не вызывает и не ссылается' % (st, csym, cpath), active)
        elif not cpath:
            add(rid, C_NOCODE, '%s: исполнителя-кода нет (%s)' % (st, r.get('executor')), active)
        # включено ли: runtime и флаг
        on = True
        if code_ok and rt in ('observe', 'off', 'none'):
            add(rid, C_OBSERVE, '%s: код есть (%s), runtime=%s — конвейер не применяет' % (st, r['consumer'], rt), active)
            on = False
        if r['flag']:
            val, why = flag_state(root, r['flag'])
            if why:
                add(rid, C_BROKEN, why, True)
                on = False
            elif val not in ON_VALUES:
                add(rid, C_OBSERVE, '%s: флаг %s = %r — выключено, что бы ни писал runtime' % (st, r['flag'], val), active)
                on = False
        # тесты: общий + парные; все — в CI
        refs = {k: r[k] for k in ('test', 'test_positive', 'test_negative') if r[k]}
        for k, ref in refs.items():
            ok, why = test_exists(root, ref)
            if not ok:
                add(rid, C_BROKEN, '%s: %s' % (k, why), True)
                continue
            if split_ref(ref)[0] not in ci:
                add(rid, C_NOTEST, '%s: %s не прописан в ci.yml' % (k, split_ref(ref)[0]), active)
        if code_ok and not r['test'] and not r['test_positive']:
            add(rid, C_NOTEST, '%s: теста нет' % st, active)
        if active:
            gaps = []
            if not r['test_positive']:
                gaps.append('положительного теста на пример типа')
            if not r['test_negative']:
                gaps.append('отрицательного теста на пример типа')
            if not (isinstance(r['run_id'], str) and RUN_ID_RE.match(r['run_id'] or '')):
                gaps.append('run_id прогона')
            if gaps:
                add(rid, C_NOPAIR, 'active без: %s — такое правило должно быть trial' % ', '.join(gaps), True)
            if not (code_ok and used and on and rt == 'enforce'):
                add(rid, C_BROKEN, 'active требует consumer (определён и вызывается) + runtime=enforce + включённый флаг', True)
            if run_dir:
                check_run(r, run_dir, passports, root, add)
    for t, v in passports.items():
        pol = ((v.get('paint') or {}).get('hidden_pattern')) if isinstance(v, dict) else None
        if not pol:
            out['problems'].append({'rule_id': 'тип «%s»' % t, 'cls': C_NOPOLICY, 'why': 'нет paint.hidden_pattern (план А1 р.6)', 'error': False, 'strict': True})
    return out


def report(res: dict, strict_types: bool = False) -> tuple:
    """→ (текст, число ошибок)."""
    errs = 0
    lines = ['rule_registry_audit: правил %d · %s' % (res['rules'], ' · '.join('%s %d' % (k, res['by_state'].get(k, 0)) for k in STATES if res['by_state'].get(k)))]
    by = collections.defaultdict(list)
    for p in res['problems']:
        err = p['error'] or (strict_types and p.get('strict'))
        errs += 1 if err else 0
        by[p['cls']].append((p, err))
    for cls in CLASSES:
        if not by.get(cls):
            continue
        lines.append('')
        lines.append('■ %s — %d' % (cls, len(by[cls])))
        for p, err in by[cls]:
            lines.append('  %s %s: %s' % ('✗' if err else '·', p['rule_id'], p['why']))
    lines.append('')
    lines.append('ИТОГ: ошибок %d%s' % (errs, '' if errs else ' — реестр чист (active-правила проверены по поведению: код вызывается, включён, парные тесты в CI)'))
    return '\n'.join(lines), errs


def to_json(res: dict, strict_types: bool, registry_path: str, root: str) -> dict:
    """Отчёт для обхода ЧЧ:02: по классу — список правил и причин (одна задача на класс/правило); digest реестра и SHA кода — чтобы «проверено на SHA» было видно."""
    by = collections.defaultdict(list)
    for p in res['problems']:
        by[p['cls']].append({'rule_id': p['rule_id'], 'why': p['why'], 'error': bool(p['error'] or (strict_types and p.get('strict')))})
    try:
        sha = subprocess.run(['git', '-C', root, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001
        sha = None
    return {'code_sha': sha, 'registry_sha256': hashlib.sha256(_read(registry_path).encode('utf-8')).hexdigest(), 'rules': res['rules'], 'by_state': res['by_state'],
            'errors': sum(1 for p in res['problems'] if p['error'] or (strict_types and p.get('strict'))), 'by_class': {c: by[c] for c in CLASSES if by.get(c)},
            'run_checked': bool(res.get('run_checked'))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='rc=1 при ошибках (CI)')
    ap.add_argument('--strict-types', action='store_true', help='«тип без политики» — ошибка (в CI: А1 влит)')
    ap.add_argument('--run', default='', help='папка прогона: структурная сверка extra.rules[] у active')
    ap.add_argument('--json', default='', metavar='ФАЙЛ', help='записать отчёт в JSON (для обхода ЧЧ:02)')
    ap.add_argument('--registry', default=REGISTRY)
    ap.add_argument('--root', default=ROOT, help='корень репозитория (для тестов на заглушках)')
    ap.add_argument('--passports', default=PASSPORTS)
    ap.add_argument('--ci', default=CI)
    a = ap.parse_args(argv)
    res = audit(registry_path=a.registry, passports_path=a.passports, ci_path=a.ci, root=a.root, run_dir=a.run)
    res['run_checked'] = bool(a.run)
    text, errs = report(res, a.strict_types)
    print(text)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(to_json(res, a.strict_types, a.registry, a.root), f, ensure_ascii=False, indent=1)
    return 1 if (a.check and errs) else 0


if __name__ == '__main__':
    sys.exit(main())
