#!/usr/bin/env python3
"""Запись «правило типа отработало / воздержалось» в check.json этапа (T-20261123-48/3; план type-rules-code-01 § Б; аудит Codex a-dupes § 3 п.1).

ЗАЧЕМ. `tools/ops/rule_registry_audit.py --run <прогон>` проверяет, что у каждого active-правила в `*/<этап>/check.json` есть запись в `extra.rules[]`: rule_id, тип, digest паспорта типа
и `applied: true` либо `abstain` с причиной. Без общей функции каждый этап (р.2/р.4/р.6) писал бы запись по-своему и тип/digest брал бы из разных мест. Здесь — ОДНА функция:
тип и digest берутся из `mesh_type_passports.paint_policy(роль)` (тот же digest, что у 07 и оценки), причина воздержания обязательна.

Запись (формат — докстринг rule_registry_audit):
  {"rule_id": "R-WIND-09", "type": "комод", "digest": "<sha256 паспорта типа>", "applied": true}
  {"rule_id": "R-BACKPANEL-06", "type": "диван", "digest": "…", "abstain": "тип не допускает: hidden_pattern=same_fabric, нужен body"}
Роль неизвестна/без типа → `type: null`, `digest: null`, всегда `abstain` (применить правило «без типа» нельзя — причина `no_type` попадёт в запись).

  import rule_record as RR
  RR.record(check, 'R-BACKPANEL-06', role, applied=False, reason='нет камеры этапа 4')   # check — словарь check.json; пишет в check['extra']['rules']
  RR.record_file('<этап>/check.json', 'R-WIND-09', role, applied=True)                  # то же в файле, атомарно
  write_check(..., rules=[RR.entry('R-WIND-09', role, True)])                           # или готовая запись → paint_stage.write_check(extra)
Повторная запись того же (rule_id, type) ЗАМЕНЯЕТ прежнюю (повторный запуск этапа не плодит дубли). Чисел порогов и ID товаров здесь нет.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mesh_type_passports as MTP  # noqa: E402


def entry(rule_id: str, role: str | None, applied: bool, reason: str = '', reg: dict | None = None) -> dict:
    """→ запись extra.rules[]. applied=True — применено (reason необязательна, идёт в `note`); applied=False — воздержание, `reason` ОБЯЗАТЕЛЬНА (иначе ValueError).
    Типа нет (роль неизвестна, реестр не читается) — применить нельзя: запись становится воздержанием с причиной типа (`no_type`/`registry_error:…`)."""
    if not (isinstance(rule_id, str) and rule_id.strip()):
        raise ValueError('rule_id пуст')
    pol = MTP.paint_policy(role, reg)
    e = {'rule_id': rule_id, 'type': pol.get('type'), 'digest': pol.get('digest')}
    why = (reason or '').strip()
    if e['type'] is None:
        e['abstain'] = 'тип не определён (%s)%s' % (pol.get('reason') or 'no_type', ': ' + why if why else '')
        return e
    if applied:
        e['applied'] = True
        if why:
            e['note'] = why
        return e
    if not why:
        raise ValueError('воздержание без причины: %s %s' % (rule_id, e['type']))
    e['abstain'] = why
    return e


def record(check: dict, rule_id: str, role: str | None, applied: bool, reason: str = '', reg: dict | None = None) -> dict:
    """Добавляет запись в `check['extra']['rules']` (создаёт, если нет); та же пара (rule_id, type) заменяется. → запись."""
    e = entry(rule_id, role, applied, reason, reg)
    ex = check.setdefault('extra', {})
    if not isinstance(ex, dict):
        raise ValueError('check.extra не словарь')
    rules = [x for x in (ex.get('rules') or []) if not (isinstance(x, dict) and x.get('rule_id') == e['rule_id'] and x.get('type') == e['type'])]
    rules.append(e)
    ex['rules'] = rules
    return e


def record_file(check_path: str, rule_id: str, role: str | None, applied: bool, reason: str = '', reg: dict | None = None) -> dict:
    """То же в файле `check.json` (читает, дописывает, пишет атомарно). Файла нет — FileNotFoundError (этап должен был его создать)."""
    with open(check_path, encoding='utf-8') as f:
        check = json.load(f)
    e = record(check, rule_id, role, applied, reason, reg)
    tmp = check_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(check, f, ensure_ascii=False, indent=1)
    os.replace(tmp, check_path)
    return e
