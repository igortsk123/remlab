#!/usr/bin/env python3
"""Сравнение двух банков комплектов (старый vs новый) — покрытие стилей и честность размеров (Р1).
  bank_compare.py sets3.json.bak-pre-dims-0309 sets3.json
"""
import json
import sys

sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from footprint import footprint_known, is_floor  # noqa: E402


def stats(path: str) -> dict:
    sets = json.load(open(path, encoding='utf-8'))
    by_style, sofas, sofa_nod, floor_nofp, filled = {}, {}, {}, 0, 0
    for s in sets:
        st = s.get('style') or '?'
        by_style[st] = by_style.get(st, 0) + 1
        items = s.get('items') or {}
        for role, it in items.items():
            if not it:
                continue
            filled += 1
            if role == 'диван':
                sofas[st] = sofas.get(st, 0) + 1
                if not it.get('d') and not it.get('dia'):
                    sofa_nod[st] = sofa_nod.get(st, 0) + 1
            if is_floor(role) and not footprint_known(it):
                floor_nofp += 1
    return {'sets': len(sets), 'by_style': by_style, 'sofas': sofas, 'sofa_no_depth': sofa_nod,
            'floor_without_footprint': floor_nofp, 'items': filled}


if __name__ == '__main__':
    a, b = sys.argv[1], sys.argv[2]
    A, B = stats(a), stats(b)
    print(f'{"":22s} {"было":>10s} {"стало":>10s}')
    print(f'{"комплектов":22s} {A["sets"]:>10d} {B["sets"]:>10d}')
    print(f'{"позиций":22s} {A["items"]:>10d} {B["items"]:>10d}')
    print(f'{"напольных без размера":22s} {A["floor_without_footprint"]:>10d} {B["floor_without_footprint"]:>10d}')
    for st in sorted(set(A['by_style']) | set(B['by_style'])):
        print(f'{st:22s} {A["by_style"].get(st, 0):>10d} {B["by_style"].get(st, 0):>10d}   диванов без глубины: '
              f'{A["sofa_no_depth"].get(st, 0)}/{A["sofas"].get(st, 0)} → {B["sofa_no_depth"].get(st, 0)}/{B["sofas"].get(st, 0)}')
