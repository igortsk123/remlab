"""Форма дивана — прямой или угловой и с какой стороны оттоманка. Одно правило на расстановщик и ленту замен.

Правило расстановщика (`solver_run.py`, layout-quality п.1 и аудит 21.08): имя — первичный сигнал, глубина — вторичный.
«прям» в имени — прямой при любой глубине («Диван прямой Мисл» 163×160); иначе угловой, если «углов» в имени или глубина
> 150 (фид терял глубину у угловых). Сторона (LAF/RAF, веб 08.08) — «лев»/«прав» в имени; нет слова — сторона не задана,
солвер пробует обе, сцена зеркалит модель под место.

Лента замен (план demo-18 п.1): замена дивана — той же формы и стороны, пока опция не несёт свою форму в сцену (форму
места `fromDemo.ts` берёт из расстановки, не из товара).
"""
import re


def is_corner(name: str | None, d) -> bool:
    nm = (name or '').lower()
    return not re.search(r'прям', nm) and (bool(re.search(r'углов', nm)) or float(d or 0) > 150)


def corner_left(name: str | None) -> bool:
    """Оттоманка слева — так понимает расстановщик (`corner_left`): по слову «лев» в имени."""
    return bool(re.search(r'лев', (name or '').lower()))


def side_fixed(name: str | None) -> bool:
    """Сторона названа в имени товара — зеркалить его нельзя."""
    return bool(re.search(r'\bлев|\bправ', (name or '').lower()))


def shape(name: str | None, d) -> dict:
    """Пометка товара ленты: `corner` всегда; `corner_left` — только когда сторона названа в имени (иначе подходит любой)."""
    out: dict = {'corner': is_corner(name, d)}
    if out['corner'] and side_fixed(name):
        out['corner_left'] = corner_left(name)
    return out


def _selftest() -> int:
    cases = [
        (('Диван угловой Аронт Мини Велюр', 151), {'corner': True}),
        (('Диван прямой Мисл', 160), {'corner': False}),
        (('Диван Босс ХЛ', 155), {'corner': True}),
        (('Диван Викс', 90), {'corner': False}),
        (('Угловой диван Сеул левый', 160), {'corner': True, 'corner_left': True}),
        (('Угловой диван Сеул правый', 160), {'corner': True, 'corner_left': False}),
        (('Диван угловой', None), {'corner': True}),
    ]
    bad = 0
    for (nm, d), want in cases:
        got = shape(nm, d)
        if got != want:
            bad += 1
            print('  FAIL:', nm, d, got, '≠', want)
    print(f'sofa_shape selftest: случаев {len(cases)}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    import sys
    sys.exit(_selftest())
