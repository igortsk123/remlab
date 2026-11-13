#!/usr/bin/env python3
"""Роли спальни и прихожей переводятся на EN-странице витрины (T-20261106-77 Д6: в списке окна спальни шли «кровать»,
«тумба прикроватная», «шкаф»). Словарь — `flat215-demo/index.html` (`var ROLE={…}`); роли — профили комнат
(`rules/profiles/<тип>.json:roles`), каталоги показа (`rules/<комната>-roles.json:roles_enabled`) и места спальни
(`demo_bedroom.PLACE_ROLES`). Новая роль без перевода — красный CI, а не русское слово у покупателя.
Запуск: python tools/scout/tests/test_demo_en_roles.py"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
sys.path.insert(0, SCOUT)
import demo_bedroom as DB  # noqa: E402

PAGE = open(os.path.join(SCOUT, 'flat215-demo', 'index.html'), encoding='utf-8').read()
m = re.search(r"var ROLE=\{(.*?)\};", PAGE, re.S)
ROLE = dict(re.findall(r"'([^']+)':'([^']+)'", re.sub(r'//[^\n]*', '', m.group(1)))) if m else {}


def rules(name):
    return json.load(open(os.path.join(SCOUT, 'rules', name), encoding='utf-8'))


need = {}
for t in ('bedroom', 'hall'):
    for r in rules(f'profiles/{t}.json')['roles']:
        need.setdefault(r, f'профиль {t}')
for f in ('bedroom-roles.json', 'hall-roles.json'):
    for r in rules(f).get('roles_enabled') or []:
        need.setdefault(r, f)
for r in DB.PLACE_ROLES + DB.LIST_ROLES + DB.DEP_ROLES:
    need.setdefault(r, 'demo_bedroom.PLACE_ROLES')

miss = sorted(f'{r} ({src})' for r, src in need.items() if r.lower() not in ROLE)
print(f'словарь ROLE: {len(ROLE)} ролей; проверено ролей спальни и прихожей: {len(need)}')
print(('FAIL без перевода: ' + ', '.join(miss)) if miss else 'OK   все роли спальни и прихожей переводятся')
bad = sorted(k for k, v in ROLE.items() if re.search('[а-яё]', v, re.I))
print(('FAIL перевод по-русски: ' + ', '.join(bad)) if bad else 'OK   переводы — латиницей')
ok = bool(ROLE) and not miss and not bad
print(f'\nитог: {"OK" if ok else "FAIL"}')
sys.exit(0 if ok else 1)
