#!/usr/bin/env python3
"""ПОКРЫТИЕ КАТАЛОГА КОМНАТ ПО СТИЛЯМ (room-bank-nightly-04 шаг 4, T-20261106-89): сколько товаров на роль × стиль × ступень цены
у спальни и прихожей — по ТЕМ ЖЕ правилам отбора, что у сборщиков (`Composer.pool`: полоса размера слота, порог «в стиле»
профиля, квантили цены ступени, у прихожей — роли без оценки стиля и напольная вешалка-хранение).

ЗАЧЕМ. Владелец 06.11: «вся квартира во всех стилях» — составы спальни и прихожей получили шестой стиль (неоклассика). Пороги
под каталог не подгоняем: если товаров мало — это вход К9 (каталог шире), а не повод ослабить правило. Отчёт — честная
таблица «где пусто/тонко». Только чтение (каталог из БД через адаптеры сборщиков), ничего не пишет, кроме `--out`.

  ~/venvs/scout/bin/python room_coverage.py --out DIR [--hall-tiers эконом,комфорт,премиум]
      → DIR/room-coverage.json и DIR/room-coverage.md
`--hall-tiers`: ступени прихожей для отчёта (в состав не включаются); нет в правилах прихожей — берутся квантили спальни.
Тонко — «в стиле» < `THIN` (запас замен сборщика спальни `SPARE_MIN`): замена в демо беднее; 0 — роль в ячейке пуста.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _row(room, purpose, role, style, fit, styled, unknown, ready, tiers, fam=None):
    """Строка покрытия. Счёт SKU — ключи без приставки; второй счёт — модели (семейства): `fam` = (по размеру, в стиле,
    без оценки) — владелец ещё решает, что считать товаром (T-20261106-90); какой из двух главный — `count_unit`."""
    f = fam or (None, None, None)
    return {'room': room, 'purpose': purpose, 'role': role, 'style': style, 'по размеру': fit, 'в стиле': styled,
            'без оценки стиля': unknown, 'меш готов': ready, 'ступени': tiers,
            'семейств по размеру': f[0], 'семейств в стиле': f[1], 'семейств без оценки': f[2]}


def count_unit(room: str) -> str:
    """Главный счёт отчёта — тот же, что у квоты мешей (`rules/demo-swap.json → room_count_unit`, sku | family)."""
    import room_mesh_demand as RMD
    return RMD.room_count_unit(room)


def main_count(r: dict, unit: str) -> int:
    """«в стиле» + «без оценки» в главном счёте строки: sku — товары, family — модели (нет счёта семейств — SKU)."""
    if unit == 'family' and r.get('семейств в стиле') is not None:
        return r['семейств в стиле'] + (r.get('семейств без оценки') or 0)
    return r['в стиле'] + r['без оценки стиля']


def bedroom_rows() -> list[dict]:
    import catalog_items as CI
    import compose_bedroom as CB
    import room_profile as RP
    R = CB.rules()
    thr = float(CB.PROFILE['style']['in_style_min'])
    cat, decor = CB.load_items(R)
    ready, gen, rejected = CI.mesh_state()
    C = CB.Composer(cat, decor, ready, gen, R, CB.tolerance(), thr, rejected)
    rows = []
    for purpose, pc in R['purposes'].items():
        if pc.get('empty'):
            continue
        C.purpose = purpose
        for sl in pc['slots']:
            for style in R['styles']:
                tiers = {t: len(C.pool(sl, style, t, C.cat)[0]) for t in R['tiers']}
                styled, mesh = C.shortage[(sl['role'], style, purpose)]
                fits = [it for it in C.cat if it['role'] == sl['role'] and CB.gate(it, sl, CB.band_of(sl, C.tol)) is None]
                fit = len(fits)
                fam = lambda L: len({it.get('fam') or it.get('sid') for it in L})  # noqa: E731
                fam3 = (fam(fits), fam([it for it in fits if RP.in_style(it.get('styles'), style, thr)]), 0)
                ready_n = sum(1 for it in C.cat if it['role'] == sl['role'] and it.get('mesh') == 'ready'
                              and RP.in_style(it.get('styles'), style, thr)
                              and CB.gate(it, sl, CB.band_of(sl, C.tol)) is None)
                rows.append(_row('bedroom', purpose, sl['role'], style, fit, styled, 0, ready_n, tiers, fam3))
    return rows


def hall_rows(extra_tiers: list[str]) -> list[dict]:
    import compose_bedroom as CB
    import compose_hall as CH
    R = CH.rules()
    tiers = dict(R['tiers'])
    for t in extra_tiers:                   # только для отчёта: квантили спальни, в состав прихожей не идут
        tiers.setdefault(t, CB.rules()['tiers'][t])
    R = dict(R, tiers=tiers)
    thr = float(CH.PROFILE['style']['in_style_min'])
    C = CH.Composer(CH.load_items(), R, CH.tolerance(), thr)
    rows = []
    cfg = R['purposes'][CH.ROOM]
    for sl in cfg['slots']:
        variants = [('', None)]
        if sl['role'] == 'вешалка' and 'вешалка' in cfg['storage']:
            variants.append((' (хранение)', lambda it: CH.floor_hanger(it, R)))
        for tag, extra in variants:
            for style in R['styles']:
                per = {t: len(C.pool(sl, style, t, extra, tag)[0]) for t in tiers}
                sh = C.shortage[(sl['role'] + tag, style)]
                r = _row('hall', 'hall', sl['role'] + tag, style, sh['годных по размеру'], sh['в стиле'],
                         sh['без оценки стиля'], sh['с готовым мешом'], per,
                         (sh['семейств по размеру'], sh['семейств в стиле'], sh['семейств без оценки']))
                r['по типоразмерам'] = sh.get('по типоразмерам')
                rows.append(r)
    return rows


THIN = 3

# ЯДРО СПАЛЬНИ (T-20261106-89/2, ведущий 06.11): стиль без хотя бы одной группы ядра ни в одном назначении ночью не собирается —
# группы те же, что у суда `compose_bedroom.check_bank` («ядро неполное (кровать + шкаф/комод)», «пара без двух тумб»)
CORE = (('кровати', ('кровать',), None), ('шкафа/комода', ('шкаф', 'комод'), None),
        ('тумбы', ('тумба прикроватная',), 'couple'))


def core_gaps(counts: dict, R: dict) -> dict[str, list[str]]:
    """{стиль: [группы ядра без единого товара в стиле]} по счёту `counts[(роль, стиль, назначение)]` → «в стиле».
    Группа с назначением (тумба — у пары) считается только по таким назначениям; назначений этого вида нет — группа не нужна.
    Чистая функция: ни БД, ни каталога (тест и селфтест — на словаре)."""
    live = [p for p, pc in R['purposes'].items() if not pc.get('empty')]
    out = {}
    for style in R['styles']:
        miss = []
        for label, roles, kind in CORE:
            ps = [p for p in live if kind is None or p.split(':')[0] == kind]
            if ps and not any(counts.get((r, style, p), 0) for p in ps for r in roles):
                miss.append(label)
        if miss:
            out[style] = miss
    return out


def bedroom_core_counts(C, R: dict) -> dict:
    """Счёт «в стиле» у ролей ядра по назначениям — тем же `Composer.pool`, что у сборщика (первая ступень: число «в стиле»
    от ступени не зависит). Состояние сборщика (`purpose`) возвращается как было."""
    roles = {r for _, rs, _ in CORE for r in rs}
    tier = next(iter(R['tiers']))
    was, out = C.purpose, {}
    try:
        for purpose, pc in R['purposes'].items():
            if pc.get('empty'):
                continue
            C.purpose = purpose
            for sl in pc['slots']:
                if sl['role'] in roles:
                    for style in R['styles']:
                        C.pool(sl, style, tier, C.cat)
                        out[(sl['role'], style, purpose)] = C.shortage[(sl['role'], style, purpose)][0]
    finally:
        C.purpose = was
    return out


def live_styles(room: str) -> set[str] | None:
    """Стили живого банка комнаты — их правило ядра исключать не вправе (исключился — FAIL, не WARN). Нет банка — None."""
    import room_bank_spec as RBS
    try:
        bank = json.load(open(RBS.for_room(room).live, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return None
    return {s.get('style') for s in (bank['sets'] if isinstance(bank, dict) else bank) if s.get('style')}


def skip_text(style: str, miss: list[str]) -> str:
    return f'спальня: {style} пропущена — нет {"/".join(miss)} в стиле'


UNIT_RU = {'sku': 'товары (SKU, цвета — отдельно)', 'family': 'модели (семейства)'}


def markdown(rows: list[dict], styles_new: set, units: dict | None = None) -> str:
    units = units or {}
    out = ['# Покрытие каталога комнат по стилям', '',
           f'«в стиле» — балл ≥ порога профиля (`room_profile.in_style`: 6,6, universal не в счёт); два счёта — товары (SKU) / '
           f'модели (семейства), «по размеру» — в полосе любого типоразмера слота; ступени — SKU в квантилях цены ступени '
           f'(0 — сборщик ослабит ступень внутри стиля или роль пуста); тонко/ПУСТО — по главному счёту комнаты (как у квоты '
           f'мешей) < {THIN}. Новый стиль помечен ★.', '']
    by = {}
    for r in rows:
        by.setdefault((r['room'], r['purpose']), []).append(r)
    for (room, purpose), rs in by.items():
        tiers = list(rs[0]['ступени'])
        unit = units.get(room, 'sku')
        f = lambda a, b: f'{a} / {b}' if b is not None else f'{a}'  # noqa: E731
        out += [f'## {room} · {purpose} — главный счёт: {UNIT_RU.get(unit, unit)}', '',
                '| роль | стиль | по размеру SKU / сем. | в стиле SKU / сем. | без оценки SKU / сем. | меш готов | '
                + ' | '.join(tiers) + ' | |',
                '|---|---|---|---|---|---|' + '---|' * len(tiers) + '---|']
        for r in rs:
            n = main_count(r, unit)
            mark = 'ПУСТО' if n == 0 else ('тонко' if n < THIN else '')
            out.append(f"| {r['role']} | {r['style']}{' ★' if r['style'] in styles_new else ''} | "
                       f"{f(r['по размеру'], r.get('семейств по размеру'))} | {f(r['в стиле'], r.get('семейств в стиле'))} | "
                       f"{f(r['без оценки стиля'], r.get('семейств без оценки'))} | {r['меш готов']} | "
                       + ' | '.join(str(r['ступени'][t]) for t in tiers) + f' | {mark} |')
        out.append('')
    return '\n'.join(out)


def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    R = {'styles': ['сканди', 'неоклассика'], 'purposes': {'couple': {}, 'single': {}, 'child:0-3': {'empty': 'PENDING'}}}
    full = {(r, 'сканди', p): 3 for p in ('couple', 'single') for r in ('кровать', 'шкаф', 'тумба прикроватная')}
    neo = {('кровать', 'неоклассика', 'couple'): 46}
    ok('сканди с ядром — не пропускается', 'сканди' not in core_gaps(full, R))
    ok('неоклассика без шкафа/комода и тумбы — пропуск с обеими группами',
       core_gaps({**full, **neo}, R).get('неоклассика') == ['шкафа/комода', 'тумбы'])
    ok('комод вместо шкафа — ядро есть', 'неоклассика' not in core_gaps(
        {**full, **neo, ('комод', 'неоклассика', 'single'): 1, ('тумба прикроватная', 'неоклассика', 'couple'): 2}, R))
    ok('тумба только у одиночной — паре не хватает', core_gaps(
        {**full, **neo, ('шкаф', 'неоклассика', 'couple'): 1, ('тумба прикроватная', 'неоклассика', 'single'): 5}, R)
       .get('неоклассика') == ['тумбы'])
    R1 = dict(R, purposes={'single': {}})
    ok('пар нет — тумба не нужна', core_gaps({('кровать', 'неоклассика', 'single'): 1, ('шкаф', 'неоклассика', 'single'): 1},
                                               dict(R1, styles=['неоклассика'])) == {})
    ok('строка сводки', skip_text('неоклассика', ['шкафа/комода', 'тумбы'])
       == 'спальня: неоклассика пропущена — нет шкафа/комода/тумбы в стиле')
    # два счёта (T-20261106-90): 3 цвета одной модели — 3 товара, 1 модель; «тонко» — по главному счёту комнаты
    r = _row('hall', 'hall', 'обувница', 'лофт', 5, 3, 0, 0, {'комфорт': 2}, (2, 1, 0))
    ok('главный счёт: sku — 3 товара, family — 1 модель', main_count(r, 'sku') == 3 and main_count(r, 'family') == 1)
    md = markdown([r], set(), {'hall': 'family'})
    ok('отчёт: обе колонки «SKU / сем.», главный счёт в заголовке, «тонко» по моделям',
       '| 5 / 2 | 3 / 1 |' in md and 'главный счёт: модели' in md and md.rstrip().endswith('| тонко |'))
    ok('без счёта семейств (старая строка) — главный счёт по SKU', main_count(_row('b', 'p', 'r', 's', 1, 4, 0, 0, {}), 'family') == 4)
    ok('единица счёта отчёта = единица квоты (правила)', count_unit('hall') in ('sku', 'family'))
    print('ИТОГ:', 'OK' if not bad else f'FAIL {bad}')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    if '--out' not in argv:
        print(__doc__)
        return 2
    out = os.path.expanduser(argv[argv.index('--out') + 1])
    os.makedirs(out, exist_ok=True)
    extra = argv[argv.index('--hall-tiers') + 1].split(',') if '--hall-tiers' in argv else []
    rows = bedroom_rows() + hall_rows(extra)
    new = {'неоклассика'}
    json.dump(rows, open(os.path.join(out, 'room-coverage.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    units = {room: count_unit(room) for room in {r['room'] for r in rows}}
    open(os.path.join(out, 'room-coverage.md'), 'w', encoding='utf-8').write(markdown(rows, new, units))
    empty = [r for r in rows if main_count(r, units[r['room']]) == 0]
    print(f'покрытие: строк {len(rows)}, пустых ролей {len(empty)} (из них неоклассика {sum(r["style"] in new for r in empty)}); '
          f'{out}/room-coverage.md', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
