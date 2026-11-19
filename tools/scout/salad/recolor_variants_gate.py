#!/usr/bin/env python3
"""T-20261119-03/1: ГЕЙТ ЗАПИСИ ПЕРЕКРАСКИ ДЛЯ СЕМЕЙСТВ С ПОДКРАСКОЙ ВАРИАНТОВ (решение директора 19.11 после №37 и №35).

Проблема: перекраска подгоняет меш под фото ПРЕДСТАВИТЕЛЯ, а варианты семьи показываются тем же мешом, умноженным на подкраску сцены
(`mesh_color_check.tint_from_mesh`: множитель в границах lo…hi_mesh). Если семья по яркости шире ~×5, новый цвет меша выталкивает
множитель варианта на потолок (текстура светлее не станет) или на пол — вариант выходит темнее/серее фото, хотя представитель стал точным
(№37: два варианта из трёх потемнели на dL −12…−15, №35: кремовый вариант стал розовее). Ночная проверка такое ловит позже, чем запись.

Правило гейта (прогноз по ночным правилам ДО записи, функции `mesh_color_check.judge` как есть):
  для каждого варианта семьи считаем вердикт и множитель при СТАРОМ цвете меша (без перекраски) и при НОВОМ (после) и отказываем, если
  у какого-то варианта стало хуже — любое из трёх:
    ① новый «упор» множителя (потолок hi_mesh, пол lo или SPREAD — каналы разошлись), которого не было до перекраски;
    ② вердикт был ok, стал не ok;
    ③ вердикта «расхождение» (mismatch) не было, стал — новый mismatch.
  Вариант, который и до, и после «расхождение» (на сайт не попадает — `family_colour_mismatch`), в счёт не идёт; «неизвестно» (нет фото) — тоже.
  Семейство без вариантов — гейт пропускает (проверять нечего); если фото нет ни у одного варианта — ok=None (прогноза нет, запись не идёт). Улучшение вариантов не обязательно: «не хуже» — этого достаточно.
Применение: `recolor_put_v2.py` (запись в v2 — отказ с причиной, код 3) и `recolor_lp.process` (статус «отказ: варианты семьи …» до записи),
значит и ночной шаг, когда он будет применять перекраску, идёт через тот же гейт.

  ~/venvs/scout/bin/python recolor_variants_gate.py <sku семьи> <новый.glb> <старый.glb> [--table current.json]   # печатает JSON гейта, код 3 — отказ
  ~/venvs/scout/bin/python recolor_variants_gate.py --selftest
Только чтение (таблица цвета, БД каталога — фото вариантов); ничего не пишет.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import mesh_color_check as M  # noqa: E402

KIND = {'hi': 'потолок', 'lo': 'пол', 'spread': 'разброс каналов'}


def family_variants(fam: str, rows: dict) -> list:
    """Варианты семьи по таблице цвета: строки с `owner` = семья, через семью, кроме самого представителя."""
    return sorted(k for k, r in (rows or {}).items() if r.get('owner') == fam and k != fam and r.get('via_family'))


def _mesh(rgb) -> dict | None:
    """Замер меша для `judge` по одному цвету (без частей: опорная часть не считается — прогноз по общему цвету)."""
    return M.summary(np.array([rgb], np.float64)) if rgb is not None else None


def _kinds(row: dict, R: dict) -> set:
    """Какие упоры у подкраски варианта: потолок/пол множителя, SPREAD."""
    t, lim = row.get('tint'), R['tint']
    out = set()
    if row.get('tint_spread'):
        out.add('spread')
    if t:
        if max(t) >= lim.get('hi_mesh', lim['hi']) - 1e-6:
            out.add('hi')
        if min(t) <= lim['lo'] + 1e-6:
            out.add('lo')
    return out


def predict(fam: str, variants: list, photo_of, mesh_rgb, R: dict | None = None) -> dict:
    """Строки вердикта вариантов при меше такого цвета — `judge` ночной проверки, как есть. photo_of(sku) → путь фото | None."""
    R = R or M.rules()
    mesh = _mesh(mesh_rgb)
    pairs = [{'sku': v, 'glb': 'x', 'via': True, 'owner': fam, 'asset_id': None} for v in variants]
    return M.judge(pairs, lambda g: mesh, photo_of, R) if pairs else {}


def gate(fam: str, variants: list, photo_of, old_rgb, new_rgb, R: dict | None = None) -> dict:
    """→ {ok, reasons[], n_variants, per_variant[{sku, before, after, verdict}]}. Чистая функция над цветами меша и фото вариантов."""
    R = R or M.rules()
    if not variants:
        return {'ok': True, 'reasons': [], 'n_variants': 0, 'per_variant': [], 'note': 'у семьи нет вариантов с подкраской — гейт пропускает'}
    before, after = predict(fam, variants, photo_of, old_rgb, R), predict(fam, variants, photo_of, new_rgb, R)
    reasons, per = [], []
    for v in variants:
        a, b = before[v], after[v]
        ka, kb = _kinds(a, R), _kinds(b, R)
        va, vb = a['verdict'], b['verdict']
        info = {'sku': v, 'before': {'verdict': va, 'tint': a.get('tint'), 'упор': sorted(ka), **(a.get('seen_vs_sku') or {})},
                'after': {'verdict': vb, 'tint': b.get('tint'), 'упор': sorted(kb), **(b.get('seen_vs_sku') or {})}, 'worse': []}
        per.append(info)
        if vb == 'unknown' or (va == 'mismatch' and vb == 'mismatch'):
            continue                                              # на сайт не попадает или оценить нечем — в счёт не идёт
        new_kinds = kb - ka
        if new_kinds:
            info['worse'].append('новый упор: ' + ', '.join(KIND[x] for x in sorted(new_kinds)))
        if va == 'ok' and vb != 'ok':
            info['worse'].append(f'вердикт ok → {vb}')
        elif vb == 'mismatch' and va != 'mismatch':
            info['worse'].append(f'новое расхождение ({va} → mismatch)')
        for w in info['worse']:
            d = b.get('seen_vs_sku') or {}
            reasons.append(f'{v}: {w}' + (f' (dL {d.get("dL")}, dab {d.get("dab")})' if d else ''))
    if all(x['after']['verdict'] == 'unknown' for x in per):
        # ни у одного варианта нет фото/замера — «ничего не хуже» тут пустое: прогноза нет (ok=None, запись без него не идёт)
        return {'ok': None, 'reasons': ['фото вариантов не найдены ни у одного из %d — прогнозировать нечем' % len(variants)],
                'n_variants': len(variants), 'per_variant': per}
    return {'ok': not reasons, 'reasons': reasons, 'n_variants': len(variants), 'per_variant': per}


def gate_for_family(fam: str, new_glb: str, old_glb: str, table_path: str | None = None, photo_of=None, rows: dict | None = None) -> dict:
    """Гейт для записи: варианты — из живой таблицы цвета, фото — малые копии каталога, цвет меша — `surface_colour` старого и нового GLB.
    Не смогли прочитать таблицу/меш — ok=None и причина (вызывающий отказывает записи: без прогноза не пишем)."""
    try:
        R = M.rules()
        if rows is None:
            rows, why = M.load_table(table_path, R)
            if rows is None:
                return {'ok': None, 'reasons': [f'нет таблицы цвета вариантов ({why}) — прогнозировать нечем']}
        variants = family_variants(fam, rows)
        if not variants:
            return {'ok': True, 'reasons': [], 'n_variants': 0, 'per_variant': [], 'note': 'у семьи нет вариантов с подкраской — гейт пропускает'}
        if photo_of is None:
            photo_of = M.thumbs_of(M.photo_urls(variants)).get
        old, new = M.surface_colour(old_glb), M.surface_colour(new_glb)
        if not old or not new:
            return {'ok': None, 'reasons': ['цвет меша не измерен (старый или новый GLB не открылся) — прогнозировать нечем']}
        res = gate(fam, variants, photo_of, old['rgb'], new['rgb'], R)
        res['mesh_rgb'] = {'before': old['rgb'], 'after': new['rgb']}
        return res
    except Exception as e:  # noqa: BLE001 — без прогноза не пишем, причина в отчёте
        return {'ok': None, 'reasons': ['гейт не посчитан: ' + repr(e)[:200]]}


def refusal_text(g: dict) -> str:
    """Одна строка для статуса/отчёта."""
    return 'варианты семьи — ' + ('; '.join(g.get('reasons') or []) or 'гейт не посчитан')


def main() -> int:
    if '--selftest' in sys.argv:
        import subprocess
        return subprocess.call([sys.executable, os.path.join(os.path.dirname(HERE), 'tests', 'test_recolor_variants_gate.py')])
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    tp = sys.argv[sys.argv.index('--table') + 1] if '--table' in sys.argv else None
    g = gate_for_family(sys.argv[1], sys.argv[2], sys.argv[3], tp)
    print(json.dumps(g, ensure_ascii=False, indent=1))
    return 0 if g.get('ok') else 3


if __name__ == '__main__':
    sys.exit(main())
