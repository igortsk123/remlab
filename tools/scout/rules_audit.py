#!/usr/bin/env python3
"""Аудит правил: число без обоснования — находка RULE-NO-PROOF (ADR template-integrity).

Зачем (владелец 12.08): «пуф от 70 см» и «ковёр ≤30% пола» попали в правила без
источника и перекрыли канон с пруфом. Число, которое нельзя проверить, — это не
правило, а чья-то догадка. Аудит показывает такие места списком.

  ~/venvs/scout/bin/python rules_audit.py            # отчёт
  ~/venvs/scout/bin/python rules_audit.py --strict   # ненулевой код возврата, если есть находки
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = [os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules', f)
         for f in ('zones.json', 'templates.json', 'occupancy.json')]
PROOF_KEYS = ('why', '_why', 'source', '_source', 'proof', '_note', 'note', '_purpose')


def walk(node, path, out, covered=False):
    """Группа чисел обязана нести обоснование — своё или у предка (пруф наследуется:
    у слота есть `why`, значит его подтаблицы размеров обоснованы им же)."""
    if isinstance(node, dict):
        covered = covered or any(k in node for k in PROOF_KEYS)
        has_num = any(isinstance(v, (int, float)) and not isinstance(v, bool)
                      for v in node.values())
        has_numlist = any(isinstance(v, list) and v and
                          all(isinstance(x, (int, float)) for x in v)
                          for v in node.values())
        if (has_num or has_numlist) and not covered:
            out.append(path or '/')
        for k, v in node.items():
            walk(v, f'{path}/{k}', out, covered)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f'{path}[{i}]', out, covered)


def registry_sync() -> int:
    """R3 (rules-consistency-audit): реестр ↔ код. Два направления:
    REG-CODE-GONE — hard-правило из registry.json не найдено в своём файле
    (код ушёл, реестр отстал); CODE-NOT-REG — hard-код в validate.py, которого
    нет в реестре (код вырос, приоритет/стадия не назначены)."""
    import re
    reg_p = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules',
                         'registry.json')
    val_p = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'planner',
                         'validate.py')
    if not (os.path.exists(reg_p) and os.path.exists(val_p)):
        return 0
    reg = json.load(open(reg_p, encoding='utf-8'))
    rules = reg.get('правила', [])
    code = open(val_p, encoding='utf-8').read()
    n = 0
    for r in rules:
        if r.get('вид') != 'hard':
            continue
        rid = r.get('id', '')
        if rid and rid not in code:
            print(f'  REG-CODE-GONE: {rid} — в validate.py не найдено (реестр отстал?)')
            n += 1
    reg_ids = {r.get('id') for r in rules}
    for cid in sorted(set(re.findall(r'_v\(\s*"([A-Z][A-Z0-9_]{3,})"', code))):
        if cid not in reg_ids:
            print(f'  CODE-NOT-REG: {cid} — hard-код без записи в registry.json')
            n += 1
    if n == 0:
        print('  реестр ↔ validate.py: синхронны')
    return n


def main() -> int:
    total = 0
    # occupancy.json собирается из KB-экспорта (services/knowledge-db/kdb/export_rules.py):
    # провенанс у чисел там на уровне слоёв KB, а не поля why. Отчитываемся, но в strict
    # не валим — иначе гейт требовал бы правок в сгенерированном файле.
    GENERATED = {'occupancy.json'}
    for p in RULES:
        if not os.path.exists(p):
            continue
        data = json.load(open(p, encoding='utf-8'))
        found: list[str] = []
        walk(data, '', found)
        name = os.path.basename(p)
        print(f'\n{name}: RULE-NO-PROOF {len(found)}')
        for f in found[:40]:
            print(f'  {f}')
        if len(found) > 40:
            print(f'  … ещё {len(found) - 40}')
        if os.path.basename(p) not in GENERATED:
            total += len(found)
        elif found:
            print(f'  (файл собирается из KB — провенанс в export_rules.py, в strict не входит)')
    print('\nреестр правил (R3):')
    total += registry_sync()
    print(f'\nВСЕГО без обоснования: {total}')
    return 1 if ('--strict' in sys.argv and total) else 0


if __name__ == '__main__':
    sys.exit(main())
