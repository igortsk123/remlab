#!/usr/bin/env python3
"""Пропорции как ОГРАНИЧЕНИЕ, а не как баллы.

Одна точка правды для сборки сета и для проверки каталога: `allowed` отсекает товар до всякой
эстетики, `preferred` даёт бонус уже среди прошедших. Так красивый, но не подходящий по размеру
товар не может выиграть за счёт цвета и стиля (владелец, 2026-08-05; та же архитектура в
Design-MLLM и FlairGPT — допустимость программно, эстетика только среди допустимых).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(os.path.join(HERE, 'proportions.json')))
DEF = P['defaults']


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def metrics(role: str, it: dict, corner: bool = False) -> dict:
    """Величины предмета, на которые ссылаются правила."""
    w, d, h = _num(it.get('w')), _num(it.get('d')), _num(it.get('h'))
    m = {'w': w, 'd': d, 'h': h}
    if w and d:
        m['area'] = w * d / 10000
        m['long'] = max(w, d)
    if role == 'диван' and h:
        m['seat_h'] = h * float(DEF['seat_h_ratio'])
        # у углового рабочая длина — прямая секция, без выступающего плеча
        m['seat_w'] = (w * (1 - float(DEF['corner_arm_ratio']))) if (corner and w) else w
    return m


def _side(spec: str, role: str, it: dict, ctx: dict):
    """Значение по ссылке вида `столик.w` — из кандидата или из уже выбранного предмета сета."""
    ref_role, field = spec.split('.')
    if ref_role == 'room':
        return ctx.get('wall')
    if ref_role == role:
        return metrics(role, it, ctx.get('corner_sofa', False)).get(field)
    other = (ctx.get('chosen') or {}).get(ref_role)
    if not other:
        return None
    return metrics(ref_role, other, ctx.get('corner_sofa', False)).get(field)


def check(role: str, it: dict, ctx: dict, subtype: str | None = None) -> tuple[bool, float, list]:
    """(проходит ли жёсткие рамки, бонус за попадание в предпочтительные, пояснения).

    Правило пропускается молча, если второй величины ещё нет — например, столик выбирается
    раньше пуфа. Это не поблажка: недостающую пару проверит `proportion_check` по готовому сету.
    """
    bonus, notes, ok = 0.0, [], True
    for r in P['rules']:
        if r.get('role') != role:
            continue
        if subtype and subtype in (r.get('only_if_subtype_not') or []):
            continue
        a = _side(r['a'], role, it, ctx)
        b = _side(r['b'], role, it, ctx)
        if not a or not b:
            continue
        ratio = a / b
        lo, hi = r['allowed']
        if not (lo <= ratio <= hi):
            # 5.1 (рефери 08.08): эстетические ratio (hard=false) штрафуют, но не выбраковывают
            if r.get('hard', True):
                ok = False
                notes.append(f"{r['id']} {ratio:.2f} вне {lo}–{hi}")
            else:
                bonus -= 1.5
                notes.append(f"{r['id']} {ratio:.2f} вне {lo}–{hi} (штраф)")
            continue
        plo, phi = r['preferred']
        if plo <= ratio <= phi:
            bonus += 1.5
            notes.append(f"{r['id']} {ratio:.2f} ок")
    return ok, bonus, notes
