"""Ценовые ступени роли — ОДНО место правила границ (владелец TG 1975, 18.11; план T-20261118-61/2).

Границы ступени (эконом / комфорт / премиум = ключи `lo` / `mid` / `hi`) — доли распределения цен РОЛИ (`rules/price-tiers.json`):
«комфортный» торшер и «комфортный» диван — разные деньги. Зовут: лента «Заменить» (`demo_swap_pool.pick`, квота на
«подкатегория × стиль × ступень») и фото-каталог комнат (`flat215_demo.room_photo_catalog`). Только стандартная библиотека.

  python3 price_tiers.py --selftest
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = json.load(open(os.path.join(HERE, 'rules', 'price-tiers.json'), encoding='utf-8'))
KEYS = tuple(RULES['quantiles'])                                  # порядок = от дешёвого к дорогому
LABELS = {'ru': dict(RULES['ru']), 'en': dict(RULES['en'])}


def _pc(ps: list, q: float) -> float:
    return ps[max(0, min(len(ps) - 1, int(q * len(ps))))]


def bounds(prices) -> dict:
    """{ключ: (низ, верх)} по ценам роли. Цен нет — {} (ступеней нет: `tiers_of` вернёт первую)."""
    ps = sorted(float(x) for x in prices if x)
    if not ps:
        return {}
    return {k: (_pc(ps, q[0]), _pc(ps, q[1])) for k, q in RULES['quantiles'].items()}


def tiers_of(price, bnd: dict) -> list:
    """Ступени товара: по границам (ступени перекрываются — их может быть две); ниже эконома — эконом, выше премиума — премиум
    (хвосты не теряем); цены или границ нет — эконом."""
    x = float(price or 0)
    if not bnd or not x:
        return [KEYS[0]]
    got = [k for k in KEYS if bnd[k][0] <= x <= bnd[k][1]]
    if got:
        return got
    return [KEYS[0]] if x < bnd[KEYS[0]][0] else [KEYS[-1]]


def _selftest() -> int:
    bad = 0
    b = bounds(range(1, 101))                                      # 1…100: ступени = ровно доли
    if b['lo'] != (6, 46) or b['mid'] != (36, 81) or b['hi'] != (71, 98):
        bad += 1
        print('  FAIL: границы по долям', b)
    if tiers_of(10, b) != ['lo'] or tiers_of(40, b) != ['lo', 'mid'] or tiers_of(75, b) != ['mid', 'hi']:
        bad += 1
        print('  FAIL: перекрытие — две ступени', tiers_of(40, b), tiers_of(75, b))
    if tiers_of(1, b) != ['lo'] or tiers_of(100, b) != ['hi'] or tiers_of(None, b) != ['lo'] or tiers_of(50, {}) != ['lo']:
        bad += 1
        print('  FAIL: хвосты → ближайшая ступень, нет цены/границ → эконом')
    if bounds([]) != {} or bounds([None, 0]) != {}:
        bad += 1
        print('  FAIL: пустая роль')
    if set(LABELS['ru']) != set(KEYS) or set(LABELS['en']) != set(KEYS):
        bad += 1
        print('  FAIL: подписи RU/EN — пара на каждый ключ')
    print(f'price_tiers selftest: случаев 5, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
