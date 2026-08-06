#!/usr/bin/env python3
"""Промпт и схема ПОД РОЛЬ: у каждой вещи спрашиваем то, что её выдаёт.

У дивана стиль читается по подлокотнику и стёжке, у комода — по ручкам и основанию, у люстры —
по каркасу и плафону, у ковра — по ворсу и узору. Общий список вопросов на всех терял ровно эти
различия: в первом заходе модель видела 2–4 признака из восьми, и оценка жалась к нейтральной
пятёрке (замер 2026-08-05).

Вопросы взяты не из головы — источники в `style_questions.json` (глоссарии подлокотников и ножек,
руководства по основаниям столов, определение мебели по ручкам, типология люстр, словарь ковров).

  ~/venvs/scout/bin/python role_prompt.py диван      # показать вопросы для роли
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
Q = json.load(open(os.path.join(HERE, 'style_questions.json')))['groups']

_BY_ROLE = {}
for gname, g in Q.items():
    for r in g['roles']:
        _BY_ROLE[r] = gname


def group_of(role: str) -> str | None:
    return _BY_ROLE.get((role or '').strip())


def attrs_for(role: str) -> dict:
    g = group_of(role)
    return Q[g]['attrs'] if g else {}


def schema_block(role: str) -> dict | None:
    """Кусок JSON-схемы с вопросами именно этой роли."""
    attrs = attrs_for(role)
    if not attrs:
        return None
    props = {k: {'type': 'string', 'enum': v['opts'], 'description': v['q']}
             for k, v in attrs.items()}
    return {'type': 'object', 'additionalProperties': False,
            'required': list(props), 'properties': props}


def prompt_block(role: str) -> str:
    """Человеческая часть промпта: что именно смотреть у этого предмета."""
    attrs = attrs_for(role)
    if not attrs:
        return ''
    lines = [f'   · {v["q"]}: {" / ".join(o for o in v["opts"] if o not in ("не_видно", "неясно"))}'
             for v in attrs.values()]
    return ('\nПо этому предмету дополнительно ответь в блоке "specific" — смотри ТОЛЬКО на фото '
            'и отвечай «не_видно»/«неясно», если признак не разглядеть:\n' + '\n'.join(lines))


def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else None
    if not role:
        for g, v in Q.items():
            print(f'{g:10s} ({len(v["attrs"])} вопросов): {", ".join(v["roles"])}')
        return
    print(f'роль «{role}» → группа «{group_of(role)}»')
    print(prompt_block(role))


if __name__ == '__main__':
    main()
