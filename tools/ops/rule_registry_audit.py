#!/usr/bin/env python3
"""Автосверка реестра правил (T-20261123-48; план type-rules-code-01 § Б; владелец TG 2308).

ЗАЧЕМ. «Правило записано» ≠ «правило работает»: код бывает выключен (observe/off), теста может не быть, тип может не иметь политики. Сверка часа
(P-068) делалась глазами и пропускала таблицу К1–К8. Здесь — машинная сверка `tools/scout/rules/rule-registry.json` с репозиторием; стандартная библиотека.

ЧТО СВЕРЯЕТ (на каждое правило не-retired):
  • схема: rule_id уникален и по шаблону, state/runtime из закрытых списков, applies.types ⊂ типы паспорта (или «all»), applies.families ⊂ семейства;
  • consumer `путь:символ` — файл есть и символ в нём найден (def/class/константа/слово); test `путь[::имя]` — файл есть, имя найдено, файл тестов прописан в ci.yml;
  • active = consumer и тест есть, runtime=enforce, тест в CI. Иначе — ОШИБКА (код возврата 1, CI красный);
  • trial/proposed с объявленными, но НЕ существующими путями — тоже ошибка (битая ссылка);
  • типы паспорта без политики покраски (`paint.hidden_pattern`) — класс «тип без политики» (справочно; с `--strict-types` — ошибка, включать после А1 р.6);
  • `--run <папка прогона>` — у active с `check_field` ищет в check.json товаров прогона rule_id/ключ: «включено, в прогоне не достигнуто».
КЛАССЫ ВЫВОДА: «нет кода» · «код есть, но observe/выключен» · «нет теста / тест не в CI» · «включено, в прогоне не достигнуто» · «тип без политики» · «битая ссылка/схема».

  python tools/ops/rule_registry_audit.py            # отчёт классами (всегда rc=0, кроме ошибок схемы/active)
  python tools/ops/rule_registry_audit.py --check    # то же, rc=1 при ошибках (CI)
  python tools/ops/rule_registry_audit.py --json     # машинный вид
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(ROOT, 'tools', 'scout', 'rules', 'rule-registry.json')
PASSPORTS = os.path.join(ROOT, 'tools', 'scout', 'rules', 'mesh-type-passports.json')
CI = os.path.join(ROOT, '.github', 'workflows', 'ci.yml')

STATES = ('proposed', 'trial', 'active', 'retired')
RUNTIMES = ('enforce', 'observe', 'off', 'none')
ID_RE = re.compile(r'^R-[A-Z0-9]+(-[A-Z0-9]+)*$')
REQ = ('rule_id', 'title', 'state', 'source', 'applies', 'executor', 'consumer', 'runtime', 'test', 'check_field', 'enabled')

C_NOCODE = 'нет кода'
C_OBSERVE = 'код есть, но observe/выключен'
C_NOTEST = 'нет теста / тест не в CI'
C_NOTREACHED = 'включено, в прогоне не достигнуто'
C_NOPOLICY = 'тип без политики'
C_BROKEN = 'битая ссылка/схема'
CLASSES = (C_BROKEN, C_NOCODE, C_OBSERVE, C_NOTEST, C_NOTREACHED, C_NOPOLICY)


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


def has_symbol(text: str, name: str) -> bool:
    if not name:
        return True
    n = re.escape(name)
    return bool(re.search(r'(^|\n)\s*(async\s+)?(def|class)\s+%s\b' % n, text) or re.search(r'(^|\n)\s*%s\s*[:=]' % n, text) or re.search(r'\b%s\b' % n, text))


def load_passports(path: str = PASSPORTS) -> dict:
    d = json.loads(_read(path) or '{}')
    t = d.get('types') or {}
    return {k: v for k, v in t.items()} if isinstance(t, dict) else {}


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
        cpath, csym = split_ref(r['consumer'])
        tpath, tname = split_ref(r['test'])
        code_ok = False
        if cpath:
            ctext = _read(os.path.join(root, cpath))
            if not ctext:
                add(rid, C_BROKEN, 'consumer: файла нет — %s' % cpath, True)
            elif not has_symbol(ctext, csym):
                add(rid, C_BROKEN, 'consumer: символ «%s» не найден в %s' % (csym, cpath), True)
            else:
                code_ok = True
        test_ok = False
        if tpath:
            ttext = _read(os.path.join(root, tpath))
            if not ttext:
                add(rid, C_BROKEN, 'test: файла нет — %s' % tpath, True)
            elif tname and not has_symbol(ttext, tname):
                add(rid, C_BROKEN, 'test: «%s» не найден в %s' % (tname, tpath), True)
            elif tpath not in ci:
                add(rid, C_NOTEST, 'тест %s не прописан в ci.yml' % tpath, st == 'active')
            else:
                test_ok = True
        if not code_ok and not cpath:
            add(rid, C_NOCODE, '%s: исполнителя-кода нет (%s)' % (st, r.get('executor')), st == 'active')
        elif code_ok and rt in ('observe', 'off', 'none'):
            add(rid, C_OBSERVE, '%s: код есть (%s), runtime=%s — конвейер не применяет' % (st, r['consumer'], rt), st == 'active')
        if code_ok and not tpath:
            add(rid, C_NOTEST, '%s: теста нет' % st, st == 'active')
        if st == 'active' and code_ok and rt != 'enforce':
            pass  # уже учтено классом observe как ошибка
        if st == 'active' and not (code_ok and test_ok and rt == 'enforce'):
            out['problems'].append({'rule_id': rid, 'cls': C_BROKEN, 'why': 'active требует consumer + тест в CI + runtime=enforce', 'error': True})
        if run_dir and st == 'active' and r.get('check_field'):
            stage, _, key = str(r['check_field']).partition('.')
            hits = glob.glob(os.path.join(run_dir, '*', stage, 'check.json'))
            found = sum(1 for h in hits if key.split('.')[-1] in _read(h))
            if not hits or not found:
                add(rid, C_NOTREACHED, 'в %s нет check.json с «%s» (%d файлов)' % (run_dir, r['check_field'], len(hits)))
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
    lines.append('ИТОГ: ошибок %d%s' % (errs, '' if errs else ' — реестр чист (active-правила имеют код и тест в CI)'))
    return '\n'.join(lines), errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='rc=1 при ошибках (CI)')
    ap.add_argument('--strict-types', action='store_true', help='«тип без политики» — ошибка (после А1 р.6)')
    ap.add_argument('--run', default='', help='папка прогона: сверить check_field у active')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--registry', default=REGISTRY)
    a = ap.parse_args(argv)
    res = audit(registry_path=a.registry, run_dir=a.run)
    text, errs = report(res, a.strict_types)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else text)
    return 1 if (a.check and errs) else 0


if __name__ == '__main__':
    sys.exit(main())
