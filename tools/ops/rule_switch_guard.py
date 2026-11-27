#!/usr/bin/env python3
"""Сторож выключателей правил (T-20261127-173, задача 2; Fable 27 § 3 п.2; владелец TG 3585/3598 «жёстко автоматически»).

ЗАЧЕМ. Правила покраски/конвейера живут выключателями в файлах правил (`tools/scout/rules/*.json`), а реестр `rule-registry.json` их не знал: к 27.11 — около 15 новых
выключателей мимо реестра, 73 выключенных. Решение «это правило, а это просто настройка» принимал только тот, кто помнил. Здесь его принимает сборка.

ЧТО ЗНАЧИТ «ВЫКЛЮЧАТЕЛЬ». Лист JSON-файла из области сторожа (`scan` в `switch-settings.json`; списки внутри файлов — данные, не обходятся; ключи с `_` — комментарии),
который — булево (true/false) ИЛИ режим: ключ `mode`/`state` со значением off/on/observe/dry/shadow/enforce/active. Имя — `файл.json#a.b.c` (как поле `flag` реестра).

ОБРАТНОЕ НАПРАВЛЕНИЕ (T-175/В-реестр): каждое имя из `flag`/`flags[]` реестра обязано существовать в файле правил (файл, ключ) — иначе после удаления выключателя запись молча остаётся и числится «охваченной»; реестр не читается — ошибка.

КАЖДЫЙ ВЫКЛЮЧАТЕЛЬ — ЛИБО В РЕЕСТРЕ, ЛИБО В СПИСКЕ «ОБЫЧНЫХ НАСТРОЕК»:
  • реестр: имя (или его родитель-блок) — в поле `flag` правила или в `flags: [...]` правила/группы `rule-registry.json`;
  • список: `settings` в `tools/scout/rules/switch-settings.json` — «имя или шаблон (`*` — любая часть) → почему это не правило» (причина обязательна).
Файл правил, которого нет ни в `scan`, ни в `skip_files` (с причиной), — ошибка: новый файл правил надо отнести к области сторожа или объяснить, почему он не про покраску/конвейер.

СЧЁТЧИК ТОЛЬКО УБЫВАЕТ. `tools/scout/rules/switch-guard-threshold.json`: `max_uncovered` (число выключателей вне реестра и вне списка) и `known` (их имена на дату записи).
  • новый выключатель вне реестра и списка (его нет в `known`) — ошибка; число больше порога — ошибка;
  • число меньше порога — не ошибка: печатается «опусти порог» (`--lower` перезаписывает порог и `known` текущим, но только вниз — поднять порог командой нельзя);
  • порог поднимается только правкой файла (видно в diff, решение директора).
Не охвачено (честно): значения-числа (0 = выкл), списки внутри файлов, переменные окружения (`FORM_RESEED`, `TEX_VISIBLE_ISLAND`), профили пробы вне репозитория.

  python tools/ops/rule_switch_guard.py --check          # CI: rc=1 при ошибках
  python tools/ops/rule_switch_guard.py --list           # поимённо: вне реестра и списка (+ выключен ли)
  python tools/ops/rule_switch_guard.py --lower          # опустить порог до текущего числа (только вниз)
  python tools/ops/rule_switch_guard.py --json out.json  # + отчёт для обхода
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(ROOT, 'tools', 'scout', 'rules', 'rule-registry.json')
SETTINGS = os.path.join(ROOT, 'tools', 'scout', 'rules', 'switch-settings.json')
THRESHOLD = os.path.join(ROOT, 'tools', 'scout', 'rules', 'switch-guard-threshold.json')
RULES_GLOB = 'tools/scout/rules/*.json'
SELF_FILES = ('rule-registry.json', 'switch-settings.json', 'switch-guard-threshold.json')   # сами файлы сторожа выключателями не считаются
MODE_KEYS = ('mode', 'state')
MODE_VALUES = ('off', 'on', 'observe', 'dry', 'shadow', 'enforce', 'active', 'dry_run', 'dry-run')


def _load(path: str):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, '/')


def is_off(v) -> bool:
    return v is False or (isinstance(v, str) and v.lower() in ('off', 'dry', 'dry_run', 'dry-run', 'observe', 'shadow'))


def leaves(o, path=()):
    """Выключатели внутри одного JSON: (путь через точку, значение). Списки — данные, `_ключи` — комментарии."""
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, str) and k.startswith('_'):
                continue
            yield from leaves(v, path + (str(k),))
    elif isinstance(o, bool):
        if path:
            yield '.'.join(path), o
    elif isinstance(o, str) and path and path[-1] in MODE_KEYS and o.lower() in MODE_VALUES:
        yield '.'.join(path), o


def match_any(name: str, patterns) -> str | None:
    for p in patterns:
        if fnmatch.fnmatchcase(name, p):
            return p
    return None


def collect(root: str, cfg: dict) -> tuple:
    """→ ({имя: значение}, [файлы правил вне scan и skip_files], [ошибки конфига])."""
    scan = list(cfg.get('scan') or [])
    skip = cfg.get('skip_files') if isinstance(cfg.get('skip_files'), dict) else {}
    errs = []
    for k, why in skip.items():
        if not (isinstance(why, str) and why.strip()):
            errs.append('skip_files «%s»: нет причины (почему файл не про покраску/конвейер)' % k)
    files = sorted(glob.glob(os.path.join(root, RULES_GLOB)))
    rels = [_rel(root, f) for f in files if os.path.basename(f) not in SELF_FILES]
    unclassified = [r for r in rels if not match_any(r, scan) and not match_any(r, skip)]
    # scan может вести и за пределы rules/ (data/flat3d/…): берём все файлы, подходящие под шаблоны
    in_scope = set(r for r in rels if match_any(r, scan))
    for pat in scan:
        for f in glob.glob(os.path.join(root, pat)):
            if os.path.basename(f) not in SELF_FILES:
                in_scope.add(_rel(root, f))
    out = {}
    for rel in sorted(in_scope):
        d = _load(os.path.join(root, rel))
        if d is None:
            errs.append('область сторожа: файл %s не читается как JSON' % rel)
            continue
        for p, v in leaves(d):
            out['%s#%s' % (rel, p)] = v
    return out, unclassified, errs


def registry_flags(reg) -> set:
    """Имена выключателей, названных реестром: `flag` правила, `flags[]` правила и группы."""
    out = set()
    if not isinstance(reg, dict):
        return out
    for r in reg.get('rules') or []:
        if isinstance(r, dict):
            if isinstance(r.get('flag'), str) and r['flag']:
                out.add(r['flag'])
            for x in r.get('flags') or []:
                if isinstance(x, str):
                    out.add(x)
    for g in (reg.get('groups') or {}).values():
        if isinstance(g, dict):
            for x in g.get('flags') or []:
                if isinstance(x, str):
                    out.add(x)
    return out


def in_registry(name: str, flags: set) -> bool:
    return any(name == f or name.startswith(f + '.') for f in flags)


def _resolve(d, parts) -> bool:
    """Есть ли в JSON путь parts (ключ может сам содержать точку; число — индекс списка)."""
    if not parts:
        return True
    for i in range(1, len(parts) + 1):
        k = '.'.join(parts[:i])
        if isinstance(d, dict) and k in d and _resolve(d[k], parts[i:]):
            return True
    if isinstance(d, list) and parts[0].isdigit() and int(parts[0]) < len(d):
        return _resolve(d[int(parts[0])], parts[1:])
    return False


def dead_flags(root: str, flags: set) -> list:
    """Имена из реестра (`flag`, `flags[]`), которых нет в файле правил: [(имя, причина)]. Запись про выключатель, которого уже нет, — ложное «охвачено» (T-175/В-реестр, ❓3)."""
    out = []
    for n in sorted(flags):
        if '#' not in n:
            out.append((n, 'нет «#» — имя должно быть «файл.json#путь.к.ключу»'))
            continue
        f, p = n.split('#', 1)
        fp = os.path.join(root, f)
        if not os.path.isfile(fp):
            out.append((n, 'файла %s нет' % f))
            continue
        d = _load(fp)
        if d is None:
            out.append((n, 'файл %s не читается как JSON' % f))
        elif not _resolve(d, p.split('.')):
            out.append((n, 'в файле нет ключа «%s»' % p))
    return out


def guard(root: str = ROOT, registry_path: str = REGISTRY, settings_path: str = SETTINGS, threshold_path: str = THRESHOLD) -> dict:
    """→ {'switches', 'in_registry', 'in_settings', 'uncovered': [{name, value}], 'max', 'errors': [...], 'hints': [...], 'unclassified': [...]}."""
    cfg = _load(settings_path)
    res = {'switches': 0, 'in_registry': 0, 'in_settings': 0, 'uncovered': [], 'max': None, 'errors': [], 'hints': [], 'unclassified': []}
    if not isinstance(cfg, dict):
        res['errors'].append('нет файла настроек сторожа %s (scan, skip_files, settings)' % _rel(root, settings_path))
        return res
    sw, unclassified, cfg_errs = collect(root, cfg)
    res['errors'] += cfg_errs
    res['unclassified'] = unclassified
    for r in unclassified:
        res['errors'].append('файл правил %s не отнесён: впиши его в scan (если в нём выключатели покраски/конвейера) или в skip_files с причиной — в switch-settings.json' % r)
    settings = cfg.get('settings') if isinstance(cfg.get('settings'), dict) else {}
    for k, why in settings.items():
        if not (isinstance(why, str) and why.strip()):
            res['errors'].append('settings «%s»: нет причины (почему это настройка, а не правило)' % k)
    reg = _load(registry_path)
    if not isinstance(reg, dict):
        res['errors'].append('реестр %s не читается (нет файла или не JSON) — без него охват выключателей не проверить' % _rel(root, registry_path))
    flags = registry_flags(reg)
    for n, why in dead_flags(root, flags):
        res['errors'].append('реестр называет выключатель, которого нет: %s — %s (удалён из файла правил? убери имя из flag/flags записи реестра или поправь опечатку)' % (n, why))
    res['switches'] = len(sw)
    unc = []
    for name, v in sw.items():
        if in_registry(name, flags):
            res['in_registry'] += 1
        elif match_any(name, [k for k, w in settings.items() if isinstance(w, str) and w.strip()]):
            res['in_settings'] += 1
        else:
            unc.append({'name': name, 'value': v})
    res['uncovered'] = unc
    res['stale_settings'] = sorted(k for k in settings if not any(fnmatch.fnmatchcase(n, k) for n in sw))
    thr = _load(threshold_path)
    if not isinstance(thr, dict) or not isinstance(thr.get('max_uncovered'), int):
        res['errors'].append('нет порога %s (max_uncovered — число, known — имена; первая запись — python tools/ops/rule_switch_guard.py --init)' % _rel(root, threshold_path))
        return res
    res['max'] = thr['max_uncovered']
    known = set(thr.get('known') or [])
    names = {u['name'] for u in unc}
    for u in unc:
        if u['name'] not in known:
            res['errors'].append('НОВЫЙ выключатель вне реестра и списка настроек: %s = %r — запиши правило в реестр (flag/flags) или строку в settings (с причиной)' % (u['name'], u['value']))
    if len(unc) > thr['max_uncovered']:
        res['errors'].append('выключателей вне реестра и списка %d > порога %d — счётчик только убывает' % (len(unc), thr['max_uncovered']))
    if len(unc) < thr['max_uncovered']:
        res['hints'].append('вне реестра и списка стало %d (порог %d) — опусти порог: python tools/ops/rule_switch_guard.py --lower' % (len(unc), thr['max_uncovered']))
    gone = sorted(known - names)
    if gone:
        res['hints'].append('в known %d имён уже охвачены или исчезли — уберёт --lower' % len(gone))
    return res


def report(res: dict) -> str:
    off = sum(1 for u in res['uncovered'] if is_off(u['value']))
    lines = ['rule_switch_guard: выключателей %d · в реестре %d · в списке настроек %d · ВНЕ обоих %d (из них выключено %d) · порог %s' %
             (res['switches'], res['in_registry'], res['in_settings'], len(res['uncovered']), off, res['max'])]
    for e in res['errors']:
        lines.append('  ✗ %s' % e)
    for h in res['hints']:
        lines.append('  · %s' % h)
    if res.get('stale_settings'):
        lines.append('  · settings без выключателей (устарели): %s' % ', '.join(res['stale_settings']))
    lines.append('ИТОГ: ошибок %d' % len(res['errors']))
    return '\n'.join(lines)


def lower(root: str, res: dict, threshold_path: str) -> str:
    """Опустить порог и known до текущего. Вверх — нельзя: новое без записи в known и число больше порога сюда не пускаются."""
    if res['max'] is None:
        return 'нет порога — нечего опускать'
    if res['errors']:
        return 'есть ошибки — порог не трогаю'
    thr = _load(threshold_path) or {}
    thr['max_uncovered'] = len(res['uncovered'])
    thr['known'] = sorted(u['name'] for u in res['uncovered'])
    with open(threshold_path, 'w', encoding='utf-8') as f:
        json.dump(thr, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return 'порог опущен: %d → %d' % (res['max'], thr['max_uncovered'])


def init_threshold(res: dict, threshold_path: str) -> str:
    """Первая запись порога — только если файла порога ещё нет (стартовое значение = текущее число). Файл есть — отказ: поднимать порог командой нельзя."""
    if os.path.exists(threshold_path):
        return 'порог уже есть — --init не перезаписывает (опустить: --lower; поднять — только правкой файла, решение директора)'
    thr = {'_about': 'Порог сторожа выключателей (T-20261127-173): число выключателей вне реестра и вне списка настроек только убывает. known — их имена на дату записи. '
                     'Опустить — `python tools/ops/rule_switch_guard.py --lower`; поднять — только правкой, решение директора.',
           'max_uncovered': len(res['uncovered']), 'known': sorted(u['name'] for u in res['uncovered'])}
    with open(threshold_path, 'w', encoding='utf-8') as f:
        json.dump(thr, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return 'порог записан: %d' % thr['max_uncovered']


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='rc=1 при ошибках (CI)')
    ap.add_argument('--list', action='store_true', help='поимённо: выключатели вне реестра и списка')
    ap.add_argument('--lower', action='store_true', help='опустить порог и known до текущего (только вниз)')
    ap.add_argument('--init', action='store_true', help='записать порог впервые (файла порога ещё нет)')
    ap.add_argument('--json', default='', metavar='ФАЙЛ')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--registry', default=None)
    ap.add_argument('--settings', default=None)
    ap.add_argument('--threshold', default=None)
    a = ap.parse_args(argv)
    reg = a.registry or os.path.join(a.root, 'tools', 'scout', 'rules', 'rule-registry.json')
    st = a.settings or os.path.join(a.root, 'tools', 'scout', 'rules', 'switch-settings.json')
    th = a.threshold or os.path.join(a.root, 'tools', 'scout', 'rules', 'switch-guard-threshold.json')
    res = guard(a.root, reg, st, th)
    if a.init:
        print(init_threshold({'uncovered': res['uncovered']}, th))
        res = guard(a.root, reg, st, th)
    print(report(res))
    if a.list:
        for u in sorted(res['uncovered'], key=lambda x: x['name']):
            print('  %s %s = %r' % ('○' if is_off(u['value']) else '●', u['name'], u['value']))
    if a.lower:
        print(lower(a.root, res, th))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return 1 if (a.check and res['errors']) else 0


if __name__ == '__main__':
    sys.exit(main())
