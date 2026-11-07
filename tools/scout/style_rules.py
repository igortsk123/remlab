"""Ступень 1 оценки стиля — ПРАВИЛА (бесплатно, без сети): слова стиля в тексте товара, дерево/металл/ткань и стиль из
названия (`style_tags.tag`), правила по материалу комнаты (`style_material_rules`). Вынесено из `style_score.py` без
изменений формулы (T-20261107-43/1): импорт `style_score` исполняет полный прогон, а отчёту детской нужна та же
формула. Чистые функции.

    python3 style_rules.py --selftest
"""
from __future__ import annotations

import re
import sys

from style_tags import tag


def mfired(p: dict, mrules: list) -> list:
    """id сработавших правил по материалу: материал из фида, цвет и название — чтобы золото/хром не ушли в лофт."""
    return [r['id'] for r in mrules if re.search(r['mat'], p['mat'], re.I) and not re.search(r['not'], p['mat'], re.I)
            and not re.search(r['not_col'], p['col'] + ' ' + p['name'], re.I)
            and re.search(r.get('col', ''), p['col'] + ' ' + p['name'], re.I)]


def rule_score(p: dict, styles: dict, mrules: list = (), fired: list | None = None) -> dict:
    """{стиль: балл правил}. p — name, mat, uph, stp, desc (и col для правил по материалу); styles — `styles.json`
    styles (порядок ключей = порядок стилей); fired — id правил по материалу (None — сработавшие сейчас)."""
    fired = mfired(p, mrules) if fired is None else fired
    txt = ' '.join((p['name'], p['mat'], p['uph'], p['stp'], p['desc'])).lower()
    t = tag(p['name'])
    out = {}
    for st in styles:
        sc = styles[st]['score']
        s = 0.0
        if re.search(sc['pos'], txt):
            s += 2.5
        if re.search(sc['neg'], txt):
            s -= 2.5
        for dim in ('wood', 'metal', 'fabric'):
            v = t.get(dim)
            if v and v in sc.get(dim, {}):
                s += sc[dim][v] * 0.6
        if t.get('style'):
            s += 2.0 if t['style'] == st else 0.0
        out[st] = s
    for r in mrules:
        if r['id'] in fired:
            for st, v in r['add'].items():
                out[st] += v
    return out


def _selftest() -> int:
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    S = json.load(open(os.path.join(here, 'styles.json'), encoding='utf-8'))['styles']
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    p = dict(name='Кровать детская divan.ru Лора', mat='', uph='', stp='скандинавский', desc='', col='')
    r = rule_score(p, S)
    ok('ярлык магазина «скандинавский» → сканди +2.5', r['сканди'] == 2.5 and list(r) == list(S))
    q = dict(name='Тумба Селтик', mat='металл', uph='', stp='', desc='', col='чёрный')
    M = [{'id': 'm', 'mat': 'металл', 'not': 'дерев', 'not_col': 'золот', 'add': {'лофт': 4.0}}]
    ok('правило по материалу: металл без дерева → лофт +4', mfired(q, M) == ['m'] and rule_score(q, S, M)['лофт'] >= 4.0)
    ok('прежний список правил (сдвиг без прогона) — fired=[] не добавляет', rule_score(q, S, M, [])['лофт'] < 4.0)
    print('OK: 0 провалов' if not bad else f'ПРОВАЛОВ: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
