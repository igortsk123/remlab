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


def _row(room, purpose, role, style, fit, styled, unknown, ready, tiers):
    return {'room': room, 'purpose': purpose, 'role': role, 'style': style, 'по размеру': fit, 'в стиле': styled,
            'без оценки стиля': unknown, 'меш готов': ready, 'ступени': tiers}


def bedroom_rows() -> list[dict]:
    import catalog_items as CI
    import compose_bedroom as CB
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
                fit = sum(1 for it in C.cat if it['role'] == sl['role'] and CB.gate(it, sl, CB.band_of(sl, C.tol)) is None)
                ready_n = sum(1 for it in C.cat if it['role'] == sl['role'] and it.get('mesh') == 'ready'
                              and (it.get('styles') or {}).get(style, 0) >= thr
                              and CB.gate(it, sl, CB.band_of(sl, C.tol)) is None)
                rows.append(_row('bedroom', purpose, sl['role'], style, fit, styled, 0, ready_n, tiers))
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
                rows.append(_row('hall', 'hall', sl['role'] + tag, style, sh['годных по размеру'], sh['в стиле'],
                                 sh['без оценки стиля'], sh['с готовым мешом'], per))
    return rows


THIN = 3


def markdown(rows: list[dict], styles_new: set) -> str:
    out = ['# Покрытие каталога комнат по стилям', '',
           f'«в стиле» — балл ≥ порога профиля; ступени — сколько из них в квантилях цены ступени (0 — сборщик ослабит ступень '
           f'внутри стиля или роль пуста); тонко — «в стиле» < {THIN}. Новый стиль помечен ★.', '']
    by = {}
    for r in rows:
        by.setdefault((r['room'], r['purpose']), []).append(r)
    for (room, purpose), rs in by.items():
        tiers = list(rs[0]['ступени'])
        out += [f'## {room} · {purpose}', '',
                '| роль | стиль | по размеру | в стиле | без оценки | меш готов | ' + ' | '.join(tiers) + ' | |',
                '|---|---|---|---|---|---|' + '---|' * len(tiers) + '---|']
        for r in rs:
            n = r['в стиле'] + r['без оценки стиля']
            mark = 'ПУСТО' if n == 0 else ('тонко' if n < THIN else '')
            out.append(f"| {r['role']} | {r['style']}{' ★' if r['style'] in styles_new else ''} | {r['по размеру']} | {r['в стиле']} | "
                       f"{r['без оценки стиля']} | {r['меш готов']} | " + ' | '.join(str(r['ступени'][t]) for t in tiers) + f' | {mark} |')
        out.append('')
    return '\n'.join(out)


def main(argv: list) -> int:
    if '--out' not in argv:
        print(__doc__)
        return 2
    out = os.path.expanduser(argv[argv.index('--out') + 1])
    os.makedirs(out, exist_ok=True)
    extra = argv[argv.index('--hall-tiers') + 1].split(',') if '--hall-tiers' in argv else []
    rows = bedroom_rows() + hall_rows(extra)
    new = {'неоклассика'}
    json.dump(rows, open(os.path.join(out, 'room-coverage.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(out, 'room-coverage.md'), 'w', encoding='utf-8').write(markdown(rows, new))
    empty = [r for r in rows if r['в стиле'] + r['без оценки стиля'] == 0]
    print(f'покрытие: строк {len(rows)}, пустых ролей {len(empty)} (из них неоклассика {sum(r["style"] in new for r in empty)}); '
          f'{out}/room-coverage.md', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
