#!/usr/bin/env python3
"""Идеальный размер слота комплекта — ОДНО место для правила (план conv-08, ADR-0270).

ЗАЧЕМ. Правило жило копиями: `compose2.slot_ideal` (сборка комплектов) держал в коде пороги обеденного стола
22/40 м², а отчёт покрытия `template_coverage.py` — свои «идеалы» (стол на 4 — 140 вместо 120 из правил), и
страница `/test/coverage/` показывала не то, что собирает сборка. Теперь все читают `zones.json →
template_slot_envelopes` через этот модуль; модуль без побочных эффектов (импорт `compose2` исполняет сборку).

Пороги стола — по ОБЩЕЙ площади комнаты (`seats_by_room_m2`, 22/40); у расстановки свой паспорт по ПОЛЕЗНОЙ
площади (`templates.json → dining.rules.seats_by_area`, 18/30) — это разные величины, а не расхождение.

  python3 slot_rules.py --selftest
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ZONES = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules', 'zones.json')
_ENV: dict | None = None


def slot_envelopes(path: str = ZONES) -> dict:
    global _ENV
    if _ENV is None or path != ZONES:
        try:
            env = json.load(open(path, encoding='utf-8')).get('template_slot_envelopes', {})
        except Exception:  # noqa: BLE001 — нет файла: правил нет, слоты без конверта (как раньше)
            env = {}
        if path != ZONES:
            return env
        _ENV = env
    return _ENV


def seats_for_room(cfg: dict, m2: float) -> str:
    """Число мест стола по общей площади комнаты: ключи «<N» по возрастанию, затем «>=N»."""
    sb = cfg.get('seats_by_room_m2') or {'<22': '2', '<40': '4', '>=40': '6'}
    for lim, k in sorted((float(k[1:]), k) for k in sb if k.startswith('<') and not k.startswith('<=')):
        if m2 < lim:
            return str(sb[k])
    ge = [k for k in sb if k.startswith('>=')]
    return str(sb[ge[0]]) if ge else '6'


def slot_ideal(role: str, m2: float, qty: int = 1, env: dict | None = None) -> float | None:
    """Идеальная ширина слота под каталог (решение владельца 11.08): подгоняем ИДЕАЛ под плотность фидов, не
    нарушая правил дизайна. None — правило для роли не задано."""
    cfg = ((env if env is not None else slot_envelopes()).get('slots') or {}).get(role)
    if not cfg:
        return None
    if 'ideal' in cfg:
        return float(cfg['ideal'])
    if 'by_seats' in cfg:                      # обеденный стол: 61 см кромки на едока
        return float(cfg['by_seats'][seats_for_room(cfg, m2)])
    if 'by_area_m2' in cfg:
        # ОБОБЩЁННЫЙ парсер ключей (13.08: фиксированный список ключей молча ронял
        # слот дивана '<=16'/'<=20' в ветку 230 — диван 230 проходил в комнату 15 м²)
        ba = cfg['by_area_m2']
        for lim, k in sorted((float(k[2:]), k) for k in ba if k.startswith('<=')):
            if m2 <= lim:
                return float(ba[k])
        for lim, k in sorted(((float(k[1:]), k) for k in ba if k.startswith('>')), reverse=True):
            if m2 > lim:
                return float(ba[k])
    return None


def _old_slot_ideal(role: str, m2: float, env: dict) -> float | None:
    """Прежняя реализация из compose2 (до 14.10) — эталон для селфтеста «поведение не изменилось»."""
    cfg = (env.get('slots') or {}).get(role)
    if not cfg:
        return None
    if 'ideal' in cfg:
        return float(cfg['ideal'])
    if 'by_seats' in cfg:
        seats = '6' if m2 >= 40 else ('4' if m2 >= 22 else '2')
        return float(cfg['by_seats'][seats])
    if 'by_area_m2' in cfg:
        ba = cfg['by_area_m2']
        for lim, k in sorted((float(k[2:]), k) for k in ba if k.startswith('<=')):
            if m2 <= lim:
                return float(ba[k])
        for lim, k in sorted(((float(k[1:]), k) for k in ba if k.startswith('>')), reverse=True):
            if m2 > lim:
                return float(ba[k])
    return None


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    env = slot_envelopes()
    roles = list((env.get('slots') or {}).keys())
    ok('правила слотов читаются из zones.json', len(roles) >= 10)
    diff = [(r, m) for r in roles for m in [x / 2 for x in range(10, 121)]
            if slot_ideal(r, m) != _old_slot_ideal(r, m, env)]
    ok('поведение не изменилось: все роли × площади 5–60 м² как у прежнего compose2.slot_ideal', not diff)
    t = env['slots']['стол обеденный']
    ok('стол: 21.9 м² → 2 места, 22 → 4, 39.9 → 4, 40 → 6',
       [seats_for_room(t, m) for m in (21.9, 22, 39.9, 40)] == ['2', '4', '4', '6'])
    alt = {'slots': {'стол обеденный': {'by_seats': {'2': 1, '4': 2, '6': 3}, 'seats_by_room_m2': {'<18': '2', '<30': '4', '>=30': '6'}}}}
    ok('порог берётся из правила, не из кода (подмена правила меняет результат)', slot_ideal('стол обеденный', 20, env=alt) == 2.0)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else (print(__doc__) or 0))
