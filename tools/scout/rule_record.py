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


SURFACE_RULES = ('R-KNOWN-SOURCE-07', 'R-LIGHT-FLOOR-07', 'R-RELEASE-WEAK-07', 'R-EDGE-BODY-07', 'R-GRAIN-CAP-07', 'R-TOP-SYNTH-07', 'R-TOP-FOLLOW-07')


def _gate(role: str | None, cfg: dict | None, reg: dict | None = None) -> tuple:
    """(действует ли правило у этого товара, причина): выключено в rules / не тот тип по политике паспорта (`require_hidden_pattern` лежит в rules у самого правила)."""
    c = cfg or {}
    if not c.get('enabled', False):
        return False, 'правило выключено (enabled=false)'
    ok, why = MTP.allows_hidden_pattern(role, c.get('require_hidden_pattern'), reg)
    return (True, why) if ok else (False, 'не тот тип: ' + why)


def surface_group_entries(role: str | None, R: dict | None, ctx: dict | None, pas: dict | None, sg_rep: dict | None, top_rep: dict | None, known_gate: dict | None, reg: dict | None = None) -> list:
    """Записи extra.rules[] для семи правил «по типу» этапа 07 (T-20261123-28/1; ADR-0469 п.1): по одной на правило, у каждого товара — применено (с числами) или воздержание с причиной
    (не тот тип / выключено / условие не выполнено). R — rules `surface_groups` (+ `_card_role`), ctx/pas — паспорт поверхностей после apply_groups, sg_rep — его отчёт, top_rep — отчёт top_prior,
    known_gate — `report.known_source` ({synth_trusted, why}). Паспорт поверхностей выключен (R/pas = None) — воздержание «паспорт выключен»; число и причина — из отчёта, порогов здесь нет."""
    R, ctx, sg_rep, top_rep = R or {}, ctx or {}, sg_rep or {}, top_rep or {}
    out = []

    def add(rid, applied, why):
        out.append(entry(rid, role, applied, why, reg))
    if known_gate is None:
        add('R-KNOWN-SOURCE-07', False, 'условие не выполнено: шлюз «известного» не записан')
    elif not known_gate.get('synth_trusted', True):
        add('R-KNOWN-SOURCE-07', True, str(known_gate.get('why') or 'synth не известное'))
    else:
        add('R-KNOWN-SOURCE-07', False, str(known_gate.get('why') or 'synth известный (как main)'))
    sg_off = pas is None
    err = sg_rep.get('error')
    BO = R.get('body_override') or {}

    def passport_rule(rid, cfg, applied_fn):
        if sg_off:
            return add(rid, False, 'паспорт поверхностей выключен')
        ok, why = _gate(role, cfg, reg)
        if not ok:
            return add(rid, False, why)
        if err:
            return add(rid, False, 'условие не выполнено: применение групп не завершилось (%s)' % err)
        a, note = applied_fn()
        add(rid, a, note)

    def _lf():
        n = int(ctx.get('light_floor_texels') or 0)
        return (True, 'пол света поднял %d текселей' % n) if n > 0 else (False, 'условие не выполнено: нет группы «свет» выше порога L, где невидимое темнее тона группы')
    passport_rule('R-LIGHT-FLOOR-07', R.get('light_floor'), _lf)

    def _rw():
        n = sg_rep.get('release_weak_known')
        if n is None:
            return False, 'условие не выполнено: освобождение не вызывалось (нет маски слабого фото или нет корпусных граней)'
        return (True, 'освобождено %d текселей слабого фото на корпусных гранях' % int(n)) if int(n) > 0 else (False, 'условие не выполнено: слабого фото на корпусных гранях нет')
    passport_rule('R-RELEASE-WEAK-07', BO.get('release_weak_known'), _rw)

    def _eb():
        ebs = [r_['edge_body'] for r_ in ((pas or {}).get('body_override') or {}).get('rules') or [] if isinstance(r_, dict) and r_.get('edge_body')]
        good = [e for e in ebs if e.get('ok')]
        if good:
            e = good[0]
            return True, 'тон корпуса по фото-текселям не-фасада: n=%s, ΔE00 от тона группы %s' % (e.get('n'), e.get('de00'))
        if ebs:
            return False, 'условие не выполнено: ' + str(ebs[0].get('why'))
        return False, 'условие не выполнено: невидимых граней фасадной группы нет (корпус не строился)'
    passport_rule('R-EDGE-BODY-07', BO.get('edge_body'), _eb)

    def _gc():
        cap = [(g, i['grain_capped']) for g, i in (sg_rep.get('apply') or {}).items() if isinstance(i, dict) and i.get('grain_capped')]
        if cap:
            return True, 'σ зерна заливки до→после: ' + '; '.join('группа %s %s→%s' % (g, c['sigma_measured'], c['max_sigma_l']) for g, c in cap)
        return False, 'условие не выполнено: σ зерна групп не выше потолка'
    passport_rule('R-GRAIN-CAP-07', R.get('grain_cap'), _gc)
    sc = top_rep.get('synth_candidate')
    if not top_rep:
        add('R-TOP-SYNTH-07', False, 'Ш3в (top_prior) не выполнялся')
    elif sc is None:
        add('R-TOP-SYNTH-07', False, 'условие не выполнено: кандидат тона верха не считался (Ш3в не применён)')
    elif sc.get('skipped'):
        add('R-TOP-SYNTH-07', False, str(sc['skipped']))
    elif sc.get('use') == 'synth':
        add('R-TOP-SYNTH-07', True, 'тон верха Ш3в %s → synth %s (dL %s)' % (sc.get('top_lab'), sc.get('synth_lab'), sc.get('dL')))
    else:
        add('R-TOP-SYNTH-07', False, 'условие не выполнено: use=%s (%s)' % (sc.get('use'), sc.get('why')))
    tf = top_rep.get('follow_group')
    if sg_off:
        add('R-TOP-FOLLOW-07', False, 'паспорт поверхностей выключен')
    elif tf is None:
        ok, why = _gate(role, R.get('top_follow'), reg)
        add('R-TOP-FOLLOW-07', False, why if not ok else 'условие не выполнено: Ш3в не применён — верх не рассчитан')
    elif tf.get('follow'):
        n_top = max(int(top_rep.get('n_top') or 0), 1)
        add('R-TOP-FOLLOW-07', True, 'верх следует группе: L верха Ш3в %s → тон группы %s, ΔE00 %s, фото верха %.1f %%' % (
            (tf.get('top_tone') or [None])[0], (tf.get('group_tone') or [None])[0], tf.get('de00'), 100.0 * float(top_rep.get('photo_top_n') or 0) / n_top))
    else:
        add('R-TOP-FOLLOW-07', False, str(tf.get('why')))
    return out


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
