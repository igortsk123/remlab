#!/usr/bin/env python3
"""Ворота пула подбора и порог качества обогащения — ОДНО место (план mesh-14, 21.10).

ЗАЧЕМ. Порог «quality ≥ 0.65» жил шестью копиями SQL (`cutout_sync`, `candidates`, `mesh_queue`, `compose2`,
`pipeline_funnel`), и все сравнивали НЕ ТО: `product_enrichment.quality` — `real`, а литерал 0.65 — `numeric`;
`0.65::real` хранится как 0.6499999…, и `0.65::real >= 0.65` даёт false. Товары с оценкой ровно 0.65 молча выпадали
из пула подбора (377 активных на 21.10) и из хеширования фото (23 из 176 вечных stale). Сравнение — по округлённому
до сотых значению: оценка обогащения дискретна с шагом 0.05, округление ничего не сдвигает, кроме самой границы.

  python3 pool_gate.py --selftest
"""
import sys

MIN_QUALITY = 0.65


def quality_ok(col: str = 'e.quality') -> str:
    """SQL-условие «качество обогащения не ниже порога», включительно."""
    return f'round({col}::numeric, 2) >= {MIN_QUALITY}'


# Пул подбора: всё, что ТЕОРЕТИЧЕСКИ может попасть в сет (роль, активен, в наличии, фото и цена, активное обогащение
# с качеством не ниже порога). Его режет вырезка (`cutout_sync`), его считает воронка (`pipeline_funnel`).
POOL_SQL = (" from products p join product_enrichment e using (shop_mid, external_id)"
            " where p.cat_role is not null and p.status='active' and p.in_stock"
            " and p.image_url is not null and p.price_rub is not null"
            f" and e.status='active' and e.payload is not null and {quality_ok('e.quality')} ")


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    ok('порог сравнивается по округлённому numeric (real 0.65 = 0.6499999… не теряется)',
       quality_ok('x.q') == 'round(x.q::numeric, 2) >= 0.65')
    ok('пул подбора несёт ту же границу', quality_ok('e.quality') in POOL_SQL and '>= 0.65' not in
       POOL_SQL.replace(quality_ok('e.quality'), ''))
    # округление до сотых не сдвигает соседние ступени оценки (шаг 0.05)
    ok('0.60 не проходит, 0.65 и 0.70 проходят (как в базе: real → round 2)',
       [round(float(f'{v:.7f}'), 2) >= MIN_QUALITY for v in (0.6000000238, 0.6499999762, 0.6999999881)] == [False, True, True])
    print(f'pool_gate selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
