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


REGISTRY = os.path.join(HERE, 'rules', 'rule-registry.json')
TYPE_POLICY_EFFECT = os.path.join(HERE, 'rules', 'type-policy-effect.json')


def _in_scope(applies: dict, type_name: str, family: str | None) -> bool:
    """Область правила (`applies` реестра): тип по имени, семейство паспорта или `all`."""
    ts = applies.get('types') or []
    return 'all' in ts or type_name in ts or bool(family and family in (applies.get('families') or []))


def type_policy_entries(pol: dict, modes: list | None, reg: dict | None = None, rules: dict | None = None, effect: dict | None = None) -> list:
    """Записи extra.rules[] для четырёх правил «политика невидимых сторон по типу» (К1/К3/К4/К5–К7; T-20261123-51/1): по одной записи на правило, у каждого товара.
    pol — `paint_policy_for(cfg)` 07 (type, role, hidden_pattern, mode, reason); modes — `paint_policy.groups_synth` (режимы синтеза невидимого по группам: quilt/smooth/skip) или None, если паспорт
    поверхностей выключен. Правила и их область берутся из реестра (`applies`), что исполняет правило — из `type-policy-effect.json`.
    Применено: тип в области правила, режим политики active, hidden_pattern из `patterns` правила и — если по `needs_synth_for` нужен рисунок — квилтинг реально построен (`quilt` в modes).
    Иначе — воздержание с причиной (вне области / режим не active / другой hidden_pattern / рисунок не построен: smooth/skip, no_synth)."""
    effect = effect or json.load(open(TYPE_POLICY_EFFECT, encoding='utf-8'))
    rules = rules if rules is not None else {r['rule_id']: r for r in json.load(open(REGISTRY, encoding='utf-8'))['rules']}
    role, tname = pol.get('role'), pol.get('type')
    family = None
    if tname:
        try:
            family = (MTP.load()['types'].get(tname) or {}).get('family')
        except Exception:  # noqa: BLE001 — битый паспорт: запись всё равно будет (без семейства), entry сам напишет причину
            family = None
    hp, mode = pol.get('hidden_pattern'), pol.get('mode')
    out = []
    for rid, eff in effect['rules'].items():
        applies = (rules.get(rid) or {}).get('applies') or {}
        if not tname:
            out.append(entry(rid, role, False, 'нет типа — политику применить нельзя'))
        elif not _in_scope(applies, tname, family):
            out.append(entry(rid, role, False, 'тип вне области правила'))
        elif mode != 'active' or pol.get('reason'):
            out.append(entry(rid, role, False, 'политика типа не active: mode=%s%s' % (mode, ', ' + str(pol['reason']) if pol.get('reason') else '')))
        elif hp not in eff['patterns']:
            out.append(entry(rid, role, False, 'hidden_pattern=%s — это правило исполняет %s' % (hp, '/'.join(eff['patterns']))))
        elif hp in eff['needs_synth_for']:
            if modes is None:
                out.append(entry(rid, role, False, 'паспорт поверхностей выключен — рисунок невидимого не строился'))
            elif 'quilt' in modes:
                out.append(entry(rid, role, True, 'hidden_pattern=%s: рисунок невидимого построен (groups_synth=%s)' % (hp, ','.join(modes))))
            else:
                out.append(entry(rid, role, False, 'hidden_pattern=%s: рисунок не построен (groups_synth=%s → no_synth)' % (hp, ','.join(modes) or 'пусто')))
        else:
            out.append(entry(rid, role, True, 'hidden_pattern=%s: синтез по типу не нужен — тон/зерно группы' % hp))
    return out
