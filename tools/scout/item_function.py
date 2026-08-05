#!/usr/bin/env python3
"""Функциональный подтип товара — что предмет ДЕЛАЕТ, а не как называется категория.

Зачем. «Пуф» в каталоге — это шесть разных вещей: подставка для ног, дополнительное сиденье,
мягкий журнальный стол, модуль дивана, пуф с хранением, декоративный пуф. Правила размеров у них
разные: подставка обязана быть НИЖЕ сиденья, а пуф-стол живёт по правилам столика. Пока роль одна
на всех, в сет попадает банкетка 71×57 рядом со столиком 85×55, и оба выглядят как два одинаковых
куба (владелец, 2026-08-05).

Та же болезнь у комода (хранение или опора под ТВ), стеллажа (перегородка, стена хранения,
витрина) и торшера (общий свет или чтение).

Подтип определяется ПО ДАННЫМ: габариты, параметры фида, слова названия. Если данных не хватает —
возвращаем `unknown`, и такой товар в сет не пускаем: угадывать нельзя, из-за угадывания и
случаются пуфы размером со столик.

  ~/venvs/scout/bin/python item_function.py --role пуф --report
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

SEAT_H = 44.0          # типовая высота сиденья дивана, см (заводской чертёж: 88 общая / 42 сиденье)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text(it: dict) -> str:
    return f"{it.get('name') or ''} {it.get('descr') or ''}".lower()


def pouf(it: dict) -> str:
    """Подтипы пуфа: подставка / сиденье / пуф-стол / хранение."""
    w, d, h = _num(it.get('w')), _num(it.get('d')), _num(it.get('h'))
    t = _text(it)
    if not h or not w:
        return 'unknown'
    area = (w * (d or w)) / 10000
    if re.search(r'ящик|хранени|короб|сундук', t):
        return 'storage_pouf'
    if re.search(r'банкетк|скамь|лавк', t) or (w >= 90 and h <= 50):
        return 'bench'                       # банкетка: это НЕ пуф, у неё свои правила
    if h <= SEAT_H - 4 and area <= 0.30:
        return 'footrest'                    # подставка для ног: ниже сиденья и небольшая
    if 0.30 < area and abs(h - 45) <= 8:
        return 'coffee_table_ottoman'        # мягкий журнальный стол: конкурент столику
    if SEAT_H - 6 <= h <= SEAT_H + 6 and area <= 0.30:
        return 'extra_seat'
    return 'unknown'


def chest(it: dict) -> str:
    """Комод: хранение, опора под ТВ или консоль."""
    w, h = _num(it.get('w')), _num(it.get('h'))
    t = _text(it)
    if re.search(r'под\s*тв|тв-?тумб|телевизор', t):
        return 'tv_chest'
    if not w or not h:
        return 'unknown'
    if h <= 60 and w >= 120:
        return 'tv_chest'                    # низкий и длинный — фактически ТВ-опора
    if h >= 75 and w <= 130:
        return 'storage_chest'
    if h <= 90 and w >= 100:
        return 'sideboard'
    return 'storage_chest'


def shelf(it: dict) -> str:
    """Стеллаж: перегородка, стена хранения, витрина, книжный."""
    w, d, h = _num(it.get('w')), _num(it.get('d')), _num(it.get('h'))
    t = _text(it)
    if re.search(r'витрин|стекл', t):
        return 'display_shelf'
    if not h:
        return 'unknown'
    if d and d <= 35 and h >= 180:
        return 'wall_storage'
    if h <= 140:
        return 'room_divider'
    return 'bookcase'


def lamp(it: dict) -> str:
    """Торшер: общий свет или свет для чтения."""
    h = _num(it.get('h'))
    if not h:
        return 'unknown'
    return 'reading_light' if h >= 150 else 'ambient_light'


def table(it: dict) -> str:
    """Стол: журнальный, приставной, обеденный, консоль."""
    w, h = _num(it.get('w')), _num(it.get('h'))
    t = _text(it)
    if re.search(r'обеденн|кухонн', t):
        return 'dining_table'
    if re.search(r'консол', t):
        return 'console_table'
    if not h:
        return 'unknown'
    if h <= 55:
        return 'coffee_table' if (w or 0) >= 70 else 'side_table'
    return 'dining_table'


RULES = {'пуф': pouf, 'комод': chest, 'стеллаж': shelf, 'торшер': lamp,
         'столик': table, 'стол': table, 'обеденный стол': table}

# Какие подтипы вообще допустимы в роли комплекта. Всё остальное (включая unknown) в сет не идёт.
ALLOWED = {
    'пуф': {'footrest', 'extra_seat', 'coffee_table_ottoman', 'storage_pouf'},
    'комод': {'storage_chest', 'sideboard'},
    'тв-тумба': {'tv_chest'},
    'стеллаж': {'wall_storage', 'bookcase', 'display_shelf', 'room_divider'},
    'торшер': {'reading_light', 'ambient_light'},
    'столик': {'coffee_table', 'side_table'},
}


def subtype(role: str, it: dict) -> str:
    """Функциональный подтип товара в этой роли; `unknown`, если данных не хватает."""
    fn = RULES.get(role)
    return fn(it) if fn else 'generic'


def fits_role(role: str, it: dict) -> tuple[bool, str]:
    """Годится ли товар для этой роли по СВОЕЙ функции. Возвращает (годен, подтип)."""
    st = subtype(role, it)
    allowed = ALLOWED.get(role)
    if allowed is None:
        return True, st
    return st in allowed, st


def main() -> None:
    role = sys.argv[sys.argv.index('--role') + 1] if '--role' in sys.argv else 'пуф'
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    seen, counts = set(), {}
    for s in sets:
        it = s['items'].get(role)
        if not it:
            continue
        key = f"{it['mid']}-{it['eid']}"
        if key in seen:
            continue
        seen.add(key)
        st = subtype(role, it)
        counts[st] = counts.get(st, 0) + 1
        if '--report' in sys.argv:
            print(f"{st:22s} {it.get('w')}×{it.get('d')}×{it.get('h')}  {str(it.get('name'))[:52]}")
    print(f'\n{role}: разных товаров {len(seen)}')
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        mark = '' if k in ALLOWED.get(role, {k}) else '  ← в сет НЕ пускаем'
        print(f'   {k:22s} {v}{mark}')


if __name__ == '__main__':
    main()
