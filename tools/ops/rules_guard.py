#!/usr/bin/env python3
"""Страж правил (T-20261127-175/3; Fable 27 § 2–3 п.3; владелец TG 3612/3614 «жёстко автоматически»). Одна строка-счётчик вместо памяти директора.

ЗАЧЕМ. Запись и снятие правил держались на памяти директора: 27.11 срок решения по четырём группам прошёл незамеченным, ~15 выключателей жили мимо реестра, слова владельца
лежали только в блокноте. Обход сессии — просьба к модели, её можно пропустить; страж — код по расписанию (systemd --user, каждые 30 мин), и не ноль он сам несёт в Telegram.

СТРОКА (всегда одна, первая в памятке обхода и в сводке владельцу; цель — четыре нуля):
  правила: просрочено N, вне реестра: новых M (старый долг X), сообщений владельца без разбора K, выключателей на удаление D
  • X — выключатели вне реестра, что были до порога (`known`); в цель «четыре нуля» не входят, но владелец видит их в самой строке, а не в справке (Fable 27 proverka-t175-3 § 2 п.2).
    Читающий строку (гейт `tools/stop-gate-own.mjs`) берёт M, а не X;
  • N — группы пробных правил (и правила со своим сроком), у которых decide_by вышел (по Лондону); тот же счёт, что у `rule_registry_audit` (тест сверяет оба);
  • M — НОВЫЕ выключатели вне реестра и вне списка настроек (сверх `known` порога сторожа выключателей) + файлы правил, не отнесённые к области сторожа. Старые (`known`) считает
    сам сторож выключателей — они только убывают, здесь печатаются справкой («старых … из порога …»), в M не входят;
  • K — строки журнала сообщений владельца со статусом «ждёт разбора» (журнал ведёт плагин Telegram, задача 175/4). Нет файла журнала — K = «?» (не ноль и не «чисто»: не мерится);
  • D — выключатели вне реестра, ВЫКЛЮЧЕНЫ дольше `off_days` (14) суток. «С какого дня выключен» код не знает из файла — страж сам ведёт дату первого наблюдения
    (state.json, `off_first_seen`): первые 14 суток после установки D честно 0 по незнанию, дальше считает.

ЧТО ДЕЛАЕТ С ЭТИМ (`--notify`, так его зовёт таймер):
  • счётчик N / M / D не ноль дольше `alert_after_min` (60) → сообщение в Telegram (`tools/scout/alert.sh`; ключи вне git, здесь не читаются), повтор не чаще раза в `realert_hours` (6);
  • K: есть сообщение владельца без разбора дольше `unreviewed_hours` (2) → Telegram (тот же повтор);
  • срок решения группы: напоминание за `remind_days` (3 и 1) суток и в день срока — по одному разу на (группа, срок, порог): новое напоминание после переноса срока приходит снова;
  • строка и отчёт — в `state_dir` (line.txt, report.json), чтобы обход и гейт читали их, а не пересчитывали.
Telegram не ответил / не настроен (alert.sh rc 1 / 2) — отправка НЕ считается состоявшейся (повтор в следующий запуск), причина — в stderr и в журнале alert.sh.

  python tools/ops/rules_guard.py                   # печатает строку и подробности, ничего не пишет и не шлёт
  python tools/ops/rules_guard.py --check           # то же, rc=1 если любой счётчик не ноль (K «?» — журнала нет, не мерится — не ошибка)
  python tools/ops/rules_guard.py --notify          # + состояние, Telegram, line.txt/report.json (так — таймер)
  python tools/ops/rules_guard.py --json out.json   # + отчёт в файл
Числа, сроки и пути — в `tools/scout/rules/rules-guard.json`. Таймер — `infra/server/rules-guard/` (файлы готовит рабочий, включает менеджер).

Журнал сообщений владельца: формат и разбор — ТОЛЬКО в `tools/ops/zhurnal_vladeltsa.py` (события msg / zakryt / tekst / napom; ждёт = нет zakryt по паре бот+номер); страж его
импортирует и считает так же, как `zhurnal-vladeltsa schet --starshe-min 120`. Путь: `--journal`, иначе `$OWNER_JOURNAL`, иначе `journal_path` из настроек (тот же, что по умолчанию у журнала).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import rule_registry_audit as RA  # noqa: E402  (_date, london_today — один источник дат и «сегодня по Лондону»)
import rule_switch_guard as SG  # noqa: E402  (guard, is_off — один источник «выключатель вне реестра»)
import zhurnal_vladeltsa as ZV  # noqa: E402  (read_events, fold, pending, parse_ts — один источник формата журнала сообщений владельца, T-175/4)

CONFIG = os.path.join(ROOT, 'tools', 'scout', 'rules', 'rules-guard.json')
REGISTRY = os.path.join(ROOT, 'tools', 'scout', 'rules', 'rule-registry.json')
ALERT = os.path.join(ROOT, 'tools', 'scout', 'alert.sh')
CFG_KEYS = ('alert_after_min', 'realert_hours', 'remind_days', 'off_days', 'unreviewed_hours', 'journal_path', 'state_dir')


def _load(path: str):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_config(path: str = CONFIG) -> dict:
    cfg = _load(path)
    if not isinstance(cfg, dict):
        raise SystemExit('rules_guard: нет файла настроек %s' % path)
    miss = [k for k in CFG_KEYS if k not in cfg]
    if miss:
        raise SystemExit('rules_guard: в %s нет ключей: %s' % (path, ', '.join(miss)))
    return cfg


def _utc(dt: 'datetime.datetime') -> 'datetime.datetime':
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _parse_ts(v) -> 'datetime.datetime | None':
    """Время записи журнала: эпоха (число) или ISO-строка; не разобрали — None (запись всё равно считается неразобранной, но «дольше N ч» про неё неизвестно)."""
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return datetime.datetime.fromtimestamp(float(v), datetime.timezone.utc)
        if isinstance(v, str) and v.strip():
            return _utc(datetime.datetime.fromisoformat(v.strip().replace('Z', '+00:00')))
    except (ValueError, OverflowError, OSError):
        pass
    return None


# ── N: сроки решений ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def deadlines(reg: dict, today: 'datetime.date') -> list:
    """Сроки решений ЖИВЫХ пробных правил → [{'what', 'gid', 'decide_by', 'days_left', 'rules'}]. Мерка та же, что у аудита (`check_deadline`): срок группы, у которой есть
    trial-правила, и собственный срок trial-правила, если он задан. Реестр не v3 / нет groups — пусто (сроков нет)."""
    out = []
    if not isinstance(reg, dict) or not (isinstance(reg.get('version'), int) and reg['version'] >= 3):
        return out
    groups = reg.get('groups') if isinstance(reg.get('groups'), dict) else {}
    trial = [r for r in (reg.get('rules') or []) if isinstance(r, dict) and r.get('state') == 'trial']
    used = {}
    for r in trial:
        used.setdefault(r.get('group'), []).append(r.get('rule_id'))
    for gid, rids in sorted(used.items(), key=lambda x: str(x[0])):
        g = groups.get(gid)
        d = RA._date((g or {}).get('decide_by')) if isinstance(g, dict) else None
        if d:
            out.append({'what': 'группа %s' % gid, 'gid': gid, 'decide_by': d, 'days_left': (d - today).days, 'rules': sorted(str(x) for x in rids)})
    for r in trial:
        g = groups.get(r.get('group')) if isinstance(r.get('group'), str) else None
        if 'decide_by' in r and isinstance(g, dict) and r.get('decide_by') != g.get('decide_by'):
            d = RA._date(r.get('decide_by'))
            if d:
                out.append({'what': 'правило %s (группа %s)' % (r.get('rule_id'), r.get('group')), 'gid': None, 'decide_by': d, 'days_left': (d - today).days, 'rules': [str(r.get('rule_id'))]})
    return out


# ── M и D: выключатели ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def switches(root: str) -> dict:
    """→ {'new': [имена НОВЫХ вне реестра/списка], 'unclassified': [файлы], 'uncovered': [{name, value}], 'max': порог, 'errors': [...]} по сторожу выключателей."""
    rules = os.path.join(root, 'tools', 'scout', 'rules')
    res = SG.guard(root, os.path.join(rules, 'rule-registry.json'), os.path.join(rules, 'switch-settings.json'), os.path.join(rules, 'switch-guard-threshold.json'))
    thr = SG._load(os.path.join(rules, 'switch-guard-threshold.json')) or {}
    known = set(thr.get('known') or [])
    new = sorted(u['name'] for u in res['uncovered'] if u['name'] not in known)
    over = max(0, len(res['uncovered']) - res['max']) if isinstance(res.get('max'), int) else 0
    # сторож сам не отработал (нет файла настроек / нет порога) → его «0 новых» ничего не значит; находки («НОВЫЙ выключатель…», «порог превышен») — не поломка, их считают счётчики
    broken = None
    if res.get('max') is None:
        e0 = next((e for e in res['errors'] if e.startswith(('нет файла настроек', 'нет порога'))), 'порог не прочитан')
        broken = e0.split(' (')[0]
    return {'new': new, 'over': over, 'unclassified': list(res['unclassified']), 'uncovered': res['uncovered'], 'max': res.get('max'), 'errors': list(res['errors']), 'broken': broken}


def off_remove(uncovered: list, state: dict, today: 'datetime.date', off_days: int) -> tuple:
    """Выключенные выключатели вне реестра дольше off_days суток → (список имён на удаление, новый словарь первых наблюдений). Включённый или охваченный реестром выпадает из словаря."""
    prev = state.get('off_first_seen') if isinstance(state.get('off_first_seen'), dict) else {}
    seen, due = {}, []
    for u in uncovered:
        if not SG.is_off(u['value']):
            continue
        first = RA._date(prev.get(u['name'])) or today
        seen[u['name']] = first.isoformat()
        if (today - first).days >= off_days:
            due.append(u['name'])
    return sorted(due), seen


# ── K: журнал сообщений владельца ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def read_journal(path: str, now: 'datetime.datetime', old_hours: float) -> dict:
    """→ {'exists', 'pending': [{n, ts, text}], 'old': [… ждут дольше old_hours], 'bad', 'path'}. Журнал читается КОДОМ ЖУРНАЛА (`zhurnal_vladeltsa`: read_events → fold → pending — тот же
    разбор, что у `zhurnal-vladeltsa schet --starshe-min N`; формат — в его докстринге), а не своим: события `msg` / `zakryt` / `tekst` / `napom`, ждёт = нет `zakryt` по паре (бот, номер).
    Нет файла — exists False (K «?»). Битые строки считаются в `bad` (молча терять нельзя — идёт в отчёт). «Дольше» — `>=`, как у `schet`."""
    path = os.path.expanduser(path)
    out = {'exists': False, 'pending': [], 'old': [], 'bad': 0, 'path': path}
    if not os.path.isfile(path):
        return out
    try:
        events = ZV.read_events(path)
        with open(path, encoding='utf-8') as f:
            nonblank = sum(1 for ln in f if ln.strip())
    except (OSError, ValueError) as e:     # нет доступа / не UTF-8: журнал не прочитан — «?», причина в `error` (а не «0 ждущих» и не падение без строки)
        out['error'] = '%s: %s' % (type(e).__name__, str(e)[:80])
        return out
    out['exists'] = True
    out['bad'] = max(0, nonblank - len(events))
    for r in ZV.pending(ZV.fold(events)):
        try:
            ts = ZV.parse_ts(r['ts']) if r.get('ts') else None
        except (ValueError, TypeError):
            ts = None
        item = {'n': '%s №%s' % (r['bot'], r['id']), 'ts': ts.isoformat() if ts else None, 'text': str(r.get('nachalo', ''))[:60]}
        out['pending'].append(item)
        if ts and (now - ts).total_seconds() >= old_hours * 3600:
            out['old'].append(item)
    return out


# ── сборка ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def registry_problem(reg) -> str | None:
    """Реестр читается? → None, иначе причина по-русски. Нет файла / не JSON → `_load` даёт None; JSON не того вида (не словарь, нет `rules` списком / `groups` словарём) — тоже не реестр."""
    if reg is None:
        return 'файла нет или он не JSON'
    if not isinstance(reg, dict):
        return 'верх файла не словарь'
    if not isinstance(reg.get('rules'), list):
        return 'нет списка rules'
    if not isinstance(reg.get('groups'), dict):
        return 'нет словаря groups'
    return None


def evaluate(root: str, cfg: dict, state: dict, now: 'datetime.datetime', today: 'datetime.date', journal_path: str | None = None) -> dict:
    """Реестр не читается → счётчики «просрочено» и «вне реестра» НЕЛЬЗЯ мерить (без реестра все выключатели «новые» — ложные «новых 23»): они None, в строке «?», а причина — `registry_error`
    (T-175 fix, Fable 27 (б)). Первые наблюдения выключенных сохраняются как были — сломанный реестр не стирает 14-дневный счёт."""
    reg = _load(os.path.join(root, 'tools', 'scout', 'rules', 'rule-registry.json'))
    rerr = registry_problem(reg)
    dl = [] if rerr else deadlines(reg, today)
    overdue = [d for d in dl if d['days_left'] < 0]
    sw = {'new': [], 'over': 0, 'unclassified': [], 'uncovered': [], 'max': None, 'errors': [], 'broken': None} if rerr else switches(root)
    serr = sw['broken']   # сторож выключателей не отработал (нет настроек/порога): «вне реестра» и «на удаление» НЕ меряются — не «0»
    nomeas = bool(rerr or serr)
    m_items = sw['new'] + ['файл правил не отнесён: %s' % f for f in sw['unclassified']]
    m = max(len(sw['new']), sw['over']) + len(sw['unclassified'])
    if nomeas:
        due, seen = [], dict(state.get('off_first_seen') if isinstance(state.get('off_first_seen'), dict) else {})
    else:
        due, seen = off_remove(sw['uncovered'], state, today, int(cfg['off_days']))
    j = read_journal(journal_path or os.environ.get('OWNER_JOURNAL') or cfg['journal_path'], now, float(cfg['unreviewed_hours']))
    res = {
        'now': now.isoformat(), 'today': today.isoformat(), 'registry_error': rerr, 'switch_error': None if rerr else serr,
        'overdue': None if rerr else len(overdue), 'overdue_items': ['%s — срок %s, прошло %d дн.' % (d['what'], d['decide_by'].isoformat(), -d['days_left']) for d in overdue],
        'outside': None if nomeas else m, 'outside_items': m_items, 'outside_old': None if nomeas else max(0, len(sw['uncovered']) - len(sw['new'])), 'outside_max': sw['max'], 'switch_errors': sw['errors'],
        'unreviewed': len(j['pending']) if j['exists'] else None, 'unreviewed_old': len(j['old']), 'unreviewed_items': ['%s: %s' % (x['n'], x['text']) for x in j['pending']],
        'journal': {'exists': j['exists'], 'path': j['path'], 'bad': j['bad'], 'error': j.get('error')},
        'off_remove': None if nomeas else len(due), 'off_remove_items': due, 'off_first_seen': seen,
        'deadlines': [{'what': d['what'], 'gid': d['gid'], 'decide_by': d['decide_by'].isoformat(), 'days_left': d['days_left'], 'rules': d['rules']} for d in dl],
    }
    res['line'] = line_of(res)
    return res


def line_of(res: dict) -> str:
    k = '?' if res['unreviewed'] is None else str(res['unreviewed'])
    if res.get('registry_error'):
        # три счётчика, зависящих от реестра, не мерятся — «?»; гейт директора по «реестр не читается» блокирует (tools/stop-gate-own.mjs: strazhAnswer)
        return 'правила: реестр не читается (%s), просрочено ?, вне реестра: ? (старый долг ?), сообщений владельца без разбора %s, выключателей на удаление ?' % (res['registry_error'], k)
    if res.get('switch_error'):
        # реестр цел — «просрочено» мерится; сторож выключателей не отработал — его два счётчика «?»
        return 'правила: сторож выключателей не работает (%s), просрочено %d, вне реестра: ? (старый долг ?), сообщений владельца без разбора %s, выключателей на удаление ?' % (res['switch_error'], res['overdue'], k)
    return 'правила: просрочено %d, вне реестра: новых %d (старый долг %d), сообщений владельца без разбора %s, выключателей на удаление %d' % (
        res['overdue'], res['outside'], res['outside_old'], k, res['off_remove'])


def is_clean(res: dict) -> bool:
    return not (res.get('registry_error') or res.get('switch_error') or res['overdue'] or res['outside'] or res['off_remove'] or res['unreviewed'] or res['unreviewed_old'])


def details(res: dict) -> list:
    out = []
    for key, title in (('overdue_items', 'просрочено'), ('outside_items', 'вне реестра (новые)'), ('off_remove_items', 'на удаление (выключены дольше срока)'), ('unreviewed_items', 'без разбора')):
        for x in res[key][:8]:
            out.append('  · %s: %s' % (title, x))
        if len(res[key]) > 8:
            out.append('  · %s: …и ещё %d' % (title, len(res[key]) - 8))
    if res.get('registry_error'):
        out.append('  · реестр правил не читается (tools/scout/rules/rule-registry.json): %s — сроки и выключатели не меряются, починить файл' % res['registry_error'])
    elif res.get('switch_error'):
        out.append('  · сторож выключателей не работает (tools/ops/rule_switch_guard.py): %s — «вне реестра» и «на удаление» не меряются, починить файл' % res['switch_error'])
    else:
        out.append('  справка: вне реестра старых %d из порога %s (только убывают — сторож выключателей); срок ближайшей группы: %s' % (
            res['outside_old'], res['outside_max'], min((d['decide_by'] for d in res['deadlines']), default='—')))
    if res['journal'].get('error'):
        out.append('  · журнал сообщений владельца не читается (%s): %s — K не мерится' % (res['journal']['path'], res['journal']['error']))
    elif not res['journal']['exists']:
        out.append('  справка: журнала сообщений владельца нет (%s) — K не мерится (задача 175/4)' % res['journal']['path'])
    elif res['journal']['bad']:
        out.append('  справка: в журнале %d нечитаемых строк (пропущены)' % res['journal']['bad'])
    return out


# ── оповещения ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def plan_alerts(res: dict, state: dict, now: 'datetime.datetime', cfg: dict) -> tuple:
    """→ (сообщения [(текст, ключи-отметки)], новое состояние БЕЗ отметок отправки). Отметки (last_alert / reminded) ставит `commit_sent` после доставки — не доставлено = повторится."""
    st = json.loads(json.dumps(state))
    since = st.setdefault('since', {})
    last = st.setdefault('last_alert', {})
    reminded = set(st.get('reminded') or [])
    st['off_first_seen'] = res['off_first_seen']
    msgs = []
    after = float(cfg['alert_after_min']) * 60
    again = float(cfg['realert_hours']) * 3600
    due_lines, marks = [], []
    # реестр не читается — свой счётчик (1 = сломан), тот же срок «дольше alert_after_min» и повтор; три остальных при этом None и сбрасываются вместе с «since»
    for key, val, title, items in (('registry', 1 if res.get('registry_error') else 0, 'реестр не читается', [res.get('registry_error') or '']),
                                   ('switch_tool', 1 if res.get('switch_error') else 0, 'сторож выключателей не работает', [res.get('switch_error') or ''])):
        if not val:
            since.pop(key, None)
            continue
        t0 = _ts_or(since.setdefault(key, now.isoformat()), now)
        if (now - t0).total_seconds() >= after and not (key in last and (now - _ts_or(last[key], now)).total_seconds() < again):
            due_lines.append('• %s: %s' % (title, items[0]))
            marks.append(key)
    for key, val, title, items in (('overdue', res['overdue'], 'просрочено', res['overdue_items']), ('outside', res['outside'], 'вне реестра', res['outside_items']),
                                   ('off_remove', res['off_remove'], 'выключателей на удаление', res['off_remove_items'])):
        if not val:
            since.pop(key, None)
            continue
        t0 = _ts_or(since.setdefault(key, now.isoformat()), now)
        if (now - t0).total_seconds() < after:
            continue
        if key in last and (now - _ts_or(last[key], now)).total_seconds() < again:
            continue
        due_lines.append('• %s %d: %s' % (title, val, '; '.join(items[:4]) + (' …' if len(items) > 4 else '')))
        marks.append(key)
    if res['unreviewed_old']:
        if 'unreviewed' not in last or (now - _ts_or(last['unreviewed'], now)).total_seconds() >= again:
            due_lines.append('• сообщений владельца без разбора дольше %s ч: %d (%s)' % (cfg['unreviewed_hours'], res['unreviewed_old'], '; '.join(res['unreviewed_items'][:3])))
            marks.append('unreviewed')
    else:
        last.pop('unreviewed', None)
    if due_lines:
        msgs.append(('⚠️ ' + res['line'] + '\n' + '\n'.join(due_lines) + '\nЧто делать: закрыть строку счётчика (решить правило / записать в реестр / разобрать сообщение) — страж пересчитает сам.', ['alert:' + k for k in marks]))
    rem_lines, rem_marks = [], []
    for d in res['deadlines']:
        for lim in sorted(cfg['remind_days']):
            key = '%s|%s|%d' % (d['what'], d['decide_by'], lim)
            if 0 <= d['days_left'] <= lim and key not in reminded:
                lead = 'срок сегодня' if d['days_left'] == 0 else 'до срока %d дн.' % d['days_left']
                rem_lines.append('• %s: %s (%s) — правил: %d' % (d['what'], lead, d['decide_by'], len(d['rules'])))
                rem_marks.append('remind:' + key)
                break
    if rem_lines:
        msgs.append(('⏰ Срок решения пробных правил. Решить (включить или снять группу) либо ОДИН раз перенести с причиной — иначе сборка покраснеет.\n' + '\n'.join(rem_lines), rem_marks))
    return msgs, st


def _ts_or(s, now):
    t = _parse_ts(s)
    return t if t else now


def commit_sent(state: dict, marks: list, now: 'datetime.datetime') -> None:
    """Отметить доставленное: тревоги — время последней, напоминания — список уже отправленных."""
    last = state.setdefault('last_alert', {})
    rem = list(state.get('reminded') or [])
    for m in marks:
        kind, _, key = m.partition(':')
        if kind == 'alert':
            last[key] = now.isoformat()
        elif kind == 'remind' and key not in rem:
            rem.append(key)
    state['reminded'] = rem[-300:]


def send_telegram(text: str) -> int:
    """`tools/scout/alert.sh` (rc 0 доставлено · 1 не ответил · 2 не настроен). ALERT_DRY=1 в окружении — сухо (тесты)."""
    r = subprocess.run(['bash', ALERT, text], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    if r.returncode:
        print('rules_guard: Telegram rc=%d (%s)' % (r.returncode, (r.stdout + r.stderr).strip()[:200]), file=sys.stderr)
    return r.returncode


# ── состояние на диске ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def state_path(cfg: dict, state_dir: str | None = None) -> str:
    return os.path.join(os.path.expanduser(state_dir or cfg['state_dir']), 'state.json')


def load_state(path: str) -> dict:
    d = _load(path)
    return d if isinstance(d, dict) else {}


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, path)


def main(argv=None, sender=send_telegram) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='rc=1, если любой счётчик не ноль')
    ap.add_argument('--notify', action='store_true', help='обновить состояние, послать Telegram, записать line.txt/report.json (так — таймер)')
    ap.add_argument('--json', default='', metavar='ФАЙЛ')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--config', default=CONFIG)
    ap.add_argument('--state-dir', default=None, help='вместо state_dir из настроек (тесты)')
    ap.add_argument('--journal', default=None, help='вместо journal_path из настроек (тесты)')
    ap.add_argument('--now', default='', help='ISO-время «сейчас» (тесты); по умолчанию — настоящее')
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    now = _parse_ts(a.now) if a.now else datetime.datetime.now(datetime.timezone.utc)
    if now is None:
        raise SystemExit('rules_guard: --now — не время: %r' % a.now)
    today = RA.london_today() if not a.now else now.astimezone(zoneinfo.ZoneInfo('Europe/London')).date()
    sp = state_path(cfg, a.state_dir)
    state = load_state(sp)
    res = evaluate(a.root, cfg, state, now, today, a.journal)
    print(res['line'])
    for ln in details(res):
        print(ln)
    rc = 0
    if a.notify:
        msgs, st = plan_alerts(res, state, now, cfg)
        for text, marks in msgs:
            if sender(text) == 0:
                commit_sent(st, marks, now)
        save_json(sp, st)
        d = os.path.dirname(sp)
        with open(os.path.join(d, 'line.txt'), 'w', encoding='utf-8') as f:
            f.write(res['line'] + '\n')
        save_json(os.path.join(d, 'report.json'), res)
    if a.json:
        save_json(a.json, res)
    if a.check and not is_clean(res):
        rc = 1
    return rc


if __name__ == '__main__':
    sys.exit(main())
