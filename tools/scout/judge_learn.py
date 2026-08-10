#!/usr/bin/env python3
"""Петля обучения (владелец 10.08: «правки записываются в правила, чтобы не
повторять ошибку»): агрегирует вердикты судьи раскладок + принятые ходы +
замечания владельца → СИСТЕМАТИЧЕСКИЕ паттерны → кандидаты правок правил.

Ничего не меняет в правилах сам: выдаёт judge-rule-candidates.md — каждая
строка = «паттерн (N сцен) → предлагаемая правка (параметр/чек) → PROPOSED».
Применение кандидата — обычный гейт: правка в rules/*.json → приёмка 252 →
при регрессе бисект. Так урок фиксируется в правилах, а не в чатах.

  ~/venvs/scout/bin/python judge_learn.py
"""
import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LOOP = os.path.expanduser('~/scout-scenes/judge-loop/summary.json')
COMMENTS = os.path.join(HERE, 'owner-comments.jsonl')
OUT_MD = os.path.join(HERE, 'judge-rule-candidates.md')
OUT_JSON = os.path.join(HERE, 'judge-rule-candidates.json')

# ключевые темы → на какой параметр/чек движка это мапится (для подсказки)
THEME_MAP = [
    (r'ковр|ковёр|rug', 'rug_rules / центрирование ковра (candidates.py I1)'),
    (r'столик|coffee', 'sofa_coffee_table_* (occupancy)'),
    (r'проход|транзит|path|passage', 'passage_* (occupancy) / check_passages'),
    (r'телевизор|экран|тв|tv', 'sofa_tv_* (occupancy) / check_sofa_aim'),
    (r'кресл', 'зонные группы (zones.json) / joint-пары'),
    (r'диван', 'группы диванов / SOFA_BLOCKS_SOFA'),
    (r'окн|window', 'check_window_sofa / оконные правила'),
    (r'двер|door', 'check_openings / дуга двери'),
    (r'люстр|светильник|торшер|свет', 'chandelier_shift / светильники (scene_build)'),
    (r'камин|fire', 'fireplace (zones.json focal)'),
    (r'стол обеденный|стул|dining', 'dining_* (occupancy) / check_chairs_at_table'),
]


def theme_of(text: str) -> str:
    t = (text or '').lower()
    for pat, target in THEME_MAP:
        if re.search(pat, t):
            return target
    return 'без маппинга (новая тема — возможно, нужен НОВЫЙ чек)'


def main():
    issues = Counter()
    examples = defaultdict(list)
    moves_ok = Counter()
    moves_rej = Counter()

    if os.path.exists(LOOP):
        for row in json.load(open(LOOP)):
            for i in row.get('issues', []):
                key = (theme_of(i['why']), i['severity'])
                issues[key] += 1
                if len(examples[key]) < 3:
                    examples[key].append(f"{row['id']}: {i['why'][:110]}")
            for l in row.get('moves_log', []):
                tgt = theme_of(l['move'].get('why', '') + ' ' + l['move']['role'])
                (moves_ok if str(l['result']).startswith('ACCEPT')
                 else moves_rej)[tgt] += 1

    if os.path.exists(COMMENTS):
        for line in open(COMMENTS):
            if line.strip():
                c = json.loads(line)
                key = (theme_of(c['comment']), 'owner')
                issues[key] += 1
                if len(examples[key]) < 3:
                    examples[key].append(f"{c['id']}: {c['comment'][:110]}")

    rows = []
    for (target, sev), n in issues.most_common():
        rows.append({'target': target, 'severity': sev, 'count': n,
                     'accepted_moves': moves_ok.get(target, 0),
                     'rejected_moves': moves_rej.get(target, 0),
                     'examples': examples[(target, sev)],
                     'status': 'PROPOSED'})

    json.dump({'candidates': rows}, open(OUT_JSON, 'w'),
              ensure_ascii=False, indent=1)
    lines = ["# Кандидаты правок правил из петли судьи (авто-агрегация)",
             "",
             "Источники: вердикты судьи, принятые/отклонённые ходы, замечания "
             "владельца. Применение — только через гейт: правка → приёмка 252 "
             "→ бисект при регрессе. Статус меняет владелец.",
             "",
             "| Куда (параметр/чек) | Класс | Сцен | Ходы ✓/✗ | Примеры |",
             "|---|---|---|---|---|"]
    for r in rows:
        ex = '; '.join(r['examples'])[:180]
        lines.append(f"| {r['target']} | {r['severity']} | {r['count']} | "
                     f"{r['accepted_moves']}/{r['rejected_moves']} | {ex} |")
    if not rows:
        lines.append("| — | — | — | — | петля ещё не дала данных |")
    open(OUT_MD, 'w').write('\n'.join(lines) + '\n')
    print(f"кандидатов: {len(rows)} → {OUT_MD}")


if __name__ == '__main__':
    main()
