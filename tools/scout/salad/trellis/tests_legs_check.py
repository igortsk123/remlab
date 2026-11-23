"""Тесты сверки ножек (T-191/3): синтетические маски без видеокарты и реальных товаров. Запуск: python tests_legs_check.py → «ошибок 0»."""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import legs_check as LC  # noqa: E402

FAILS = []


def ok(cond: bool, msg: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        FAILS.append(msg)


def masks(shift: int = 0, n_mesh: int = 3, dy: int = 0, w: int = 14) -> tuple:
    """Корпус 260×130, три ножки толщиной w; у формы ножки сдвинуты на shift по x и dy по y, число n_mesh."""
    pa = np.zeros((220, 300), bool)
    pa[10:140, 20:280] = True
    for x in (30, 140, 250):
        pa[140:190, x:x + w] = True
    S = np.zeros_like(pa)
    S[10:140, 20:280] = True
    for x in (30, 140, 250)[:n_mesh]:
        S[140 + dy:190 + dy, x + shift:x + shift + w] = True
    return S, pa


def test_good_and_shifted() -> None:
    print('совпали / сдвинуты:')
    r = LC.legs_report(*masks(0)[::1])
    ok(r['applicable'] and not r['mismatch'] and r['n_photo'] == 3 and r['n_mesh'] == 3, f'ножки на месте — годная форма ({r["why"]})')
    ok(len(r['trusted_boxes']) == 3 and r['cut_row'] is not None and 130 <= r['cut_row'] <= 142, f'три доверенные рамки, граница ножек у низа корпуса (cut_row={r["cut_row"]})')
    r = LC.legs_report(*masks(3))
    ok(not r['mismatch'], f'сдвиг 3 px при толщине 14 (0,21) — ещё годная: {r["err_over_w_max"]}')
    r = LC.legs_report(*masks(12))
    ok(r['mismatch'] and r['trusted_boxes'] == [] and 'не годных 3 из 3' in r['why'], f'сдвиг 12 px при толщине 14 (0,86) — провал, доверенных нет: {r["why"]}')


def test_shift_relative_to_body() -> None:
    print('общий сдвиг корпуса не считается ошибкой ножек:')
    S, pa = masks(0)
    S2 = np.zeros_like(S)
    S2[:, 8:] = S[:, :-8]                                                    # вся форма сдвинута на 8 px вправо (корпус и ножки вместе — это камера, не ножки)
    r = LC.legs_report(S2, pa)
    ok(not r['mismatch'] and abs(r['body_shift_px'] - 8) < 1.5, f'форма целиком сдвинута — ножки к корпусу на месте, годная (сдвиг корпуса {r["body_shift_px"]})')


def test_count_floor_and_na() -> None:
    print('число, пол, не применима:')
    r = LC.legs_report(*masks(0, n_mesh=2))
    ok(r['mismatch'] and not r['count_ok'] and 'число ножек фото/формы 3/2' in r['why'], f'число ножек 3/2 — провал: {r["why"]}')
    r = LC.legs_report(*masks(0, dy=12))
    ok(r['mismatch'] and not r['floor_ok'] and r['trusted_boxes'] == [], f'пол формы ниже на 12 px (5,5 %) — провал, ни одной доверенной ножки: {r["why"]}')
    r = LC.legs_report(*masks(0, dy=2))
    ok(not r['mismatch'], f'пол ниже на 2 px (0,9 %) — допуск ±2,5 %: {r["floor_dy_pct"]}')
    one = np.zeros((100, 100), bool)
    one[:90, 20:80] = True
    r = LC.legs_report(one, one)
    ok(not r['applicable'] and not r['mismatch'], 'цоколь / одна широкая ножка — не применима, провала нет')
    r = LC.legs_report(np.zeros((50, 50), bool), np.zeros((50, 50), bool))
    ok(not r['applicable'] and r['why'] == 'маска фото пуста', 'пустая маска — не применима')


def test_noise_and_partial() -> None:
    print('шум и частичный провал:')
    S, pa = masks(0)
    pa[150:160, 5:7] = True                                                  # пылинка 2×10 = 20 px < min_area
    r = LC.legs_report(S, pa)
    ok(r['n_photo'] == 3 and not r['mismatch'], f'пылинка меньше min_area не считается ножкой (n_photo={r["n_photo"]})')
    S, pa = masks(0)
    S[140:190, 140:154] = False
    S[140:190, 152:166] = True                                               # средняя ножка формы сдвинута на 12 px, остальные на месте
    r = LC.legs_report(S, pa)
    ok(r['mismatch'] and len(r['trusted_boxes']) == 2 and sum(1 for l in r['legs'] if not l['ok']) == 1, f'одна из трёх не годна — доверены две: {r["why"]}')


def test_merged_component_not_trusted() -> None:
    print('слипшиеся ножки (царга + ножки в одном компоненте) не доверяем:')
    S, pa = masks(0)
    for m in (S, pa):
        m[160:170, 20:175] = True                                            # царга соединила две левые ножки в один широкий компонент; правая ножка отдельная
    r = LC.legs_report(S, pa)
    ok(r['applicable'] and r['n_photo'] == 2 and not r['mismatch'], f'ножки на месте: компонентов 2, провала нет ({r["why"]})')
    ok(len(r['trusted_boxes']) == 1 and r['trusted_boxes'][0][0] > 200 and r['legs'][0].get('merged'), f'доверена только отдельная правая ножка, слипшаяся — нет: {r["trusted_boxes"]}')


def test_compact_and_rules() -> None:
    print('запись и правила:')
    r = LC.legs_report(*masks(0))
    c = LC.compact(r)
    ok('trusted_boxes' not in c and c['ok'] is True and len(c['legs']) == 3, 'compact — без рамок, с ножками')
    R = LC.load_rules()
    ok(R['err_over_w_max'] == 0.6 and R['floor_dy_pct_max'] == 2.5 and R['min_area'] == 100, f'пороги из camera-check.json: {R["err_over_w_max"]}/{R["floor_dy_pct_max"]}/{R["min_area"]}')
    ok(LC.load_rules('/нет/файла.json')['band'] == 0.18, 'нет файла правил — значения по умолчанию')
    rep = LC.legs_report(*masks(12))
    ex = LC.extra_fields(rep)
    ok(ex['legs_mismatch'] is True and ex['legs_block'] is False and R['block_photo'] is False, 'по умолчанию block_photo выкл: legs_mismatch пишется, legs_block ложь (observe)')
    ok(LC.extra_fields(rep, dict(R, block_photo=True))['legs_block'] is True, 'block_photo включён и сверка провалена — legs_block истинна')
    ok(LC.extra_fields(LC.legs_report(*masks(0)), dict(R, block_photo=True))['legs_block'] is False, 'сверка пройдена — legs_block ложь и при включённом переключателе')
    ok(LC.body_bottom_row(np.zeros((5, 5), bool)) is None, 'body_bottom_row: пустая маска → None')
    S, _ = masks(0)
    ok(LC.body_bottom_row(S) == 139, f'body_bottom_row: низ корпуса 139 ({LC.body_bottom_row(S)})')


def main() -> int:
    test_good_and_shifted()
    test_shift_relative_to_body()
    test_count_floor_and_na()
    test_noise_and_partial()
    test_merged_component_not_trusted()
    test_compact_and_rules()
    print(f'tests_legs_check: ошибок {len(FAILS)}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
