#!/usr/bin/env python3
"""Шаг form_gate (Ш0, T-184/9, директор 22.11): GLB + кадры приёмки → `<out>/<sku>/form_checks.json` + строка сводки `<out>/form_gate.tsv`. OBSERVE: найденный брак ничего не бракует и код возврата рендера не меняет; сам сбой Ш0 — меняет (`forms_render`: «Ш0 НЕ ВЫПОЛНЕН: причина», код 3).
Зовётся в конце `tools/ops/forms_render.py --accept` (флаг `--no-form-gate` выключает) — кадры приёмки рождаются там, значит Ш0 идёт сразу после них для любой новой формы; можно и отдельно:
  python form_gate.py --out <папка кадров приёмки> --glbs <папка GLB> --skus a,b [--roles roles.json] [--photos DIR] [--vlm-cache DIR] [--rules F]
Проверки — `form_checks.run_sku` (пороги и виды — `tools/scout/rules/form-checks.json`). Оценщик по картинке (vlm_judge, платный, ответы кэшируются) идёт САМ: фото — `--photos` или рядом с прогоном (`find_photo`), кэш — `--vlm-cache` или `<out>/vlm-cache`;
по умолчанию только 3 observe-вида (rules `vlm_judge.default_kinds`: no_gaps, count_mismatch, skewed_body) и только для корпусных ролей; остальные виды — `--vlm-all`; `--no-vlm` — без оценщика.
Перед платным вызовом — строка оценки расхода в лог (`<out>/form_gate.log`), потолок на запуск `--vlm-budget` ($; по умолчанию rules `vlm_judge.budget_usd_per_form` × число оцениваемых форм, не больше `budget_usd_max`; при `--vlm-all` — оценка запуска, тоже не больше предела): не влезает — группа пропускается с флагом `vlm_skipped_budget` (не ошибка).
«К глазам» = статус needs_review/shape_reject (любой флаг, кроме чисто камерного) — такую форму директор смотрит сам; pass → «нет». Нужны numpy/trimesh/pillow (venv scout)."""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'ops'))

COLS = ('sku', 'роль', 'статус', 'к_глазам', 'флаги', 'пояснение')
PHOTO_NAMES = ('{sku}.hd.rgba.png', '{sku}.rgba.png')


def find_photo(sku: str, photos: str, glbs: str, out: str) -> str | None:
    """Фото товара: сначала `--photos`, затем места рядом с прогоном (`<glbs>/../forms-inputs|inputs|photos`, `<out>/../forms-inputs|inputs|photos`, `<out>/photos`)."""
    dirs = ([photos] if photos else []) + [os.path.join(b, d) for b in (os.path.join(glbs, '..'), os.path.join(out, '..'), out) for d in ('forms-inputs', 'inputs', 'photos')]
    for d in dirs:
        for n in PHOTO_NAMES:
            p = os.path.join(d, n.format(sku=sku))
            if os.path.isfile(p):
                return p
    return None


def eye_row(rec: dict, role: str = '') -> list[str]:
    """Строка сводки по записи `run_sku`: статус, нужно ли глазам, флаги и пояснения флагов оценщика/перекоса."""
    flags = rec.get('flags') or []
    why = '; '.join(f"{c['name']}: {c.get('note', '')}"[:140] for c in rec.get('checks', []) if c.get('flag') and (c['name'].startswith('vlm_') or c['name'] == 'body_skew'))
    return [rec['sku'], role or '—', rec.get('status', '?'), 'да' if rec.get('status') in ('needs_review', 'shape_reject') else 'нет', ','.join(flags) or '—', why or '—']


def gate(out: str, glbs: str, skus: list[str], roles: dict | None = None, photos: str = '', photo_name: str = '', vlm_cache: str = '', rules_path: str = '',
         pose_roots: list[str] | None = None, chat=None, find_glb=None, vlm: bool = True, vlm_all: bool = False, vlm_budget: float | None = None, log=None, cards: dict | None = None) -> list[dict]:
    """Проверки по каждому товару, у которого есть кадры в `<out>/<sku>`; пишет form_checks.json и form_gate.tsv. Оценщик — по умолчанию 3 вида × корпусные роли × потолок; возвращает записи."""
    import form_checks as FC
    import form_reseed as FR
    import vlm_judge as VJ
    if find_glb is None:
        import forms_render as FRN                                                        # своё имя: `FR` ниже — form_reseed (annotate); общее имя перекрывало его и роняло Ш0 (T-20261127-175/Ш0-fix)
        find_glb = FRN.find_glb_
    rules = FC.load_rules(rules_path) if rules_path else FC.load_rules()
    J = rules.get('vlm_judge') or {}
    roles = roles or {}
    lg_path = os.path.join(out, 'form_gate.log')

    def say(line: str) -> None:
        (log or print)(line)
        with open(lg_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    use_vlm = bool(vlm and J)
    kinds_only = None if vlm_all else list(J.get('default_kinds') or [])
    cache = vlm_cache or os.path.join(out, 'vlm-cache')
    have = [s for s in skus if os.path.isdir(os.path.join(out, s))]
    kinds_of = {s: [k for k in VJ.applicable(roles.get(s, ''), J['kinds']) if kinds_only is None or k in kinds_only] for s in have} if use_vlm else {}
    n_judged = sum(1 for ks in kinds_of.values() if ks)                              # формы, у которых вообще есть что спрашивать (по умолчанию — корпусные)
    cap = float(J.get('budget_usd_max', 0.30))
    up = sum(int(J['runs']) * VJ.call_cost(J, g) for ks in kinds_of.values() for g in {J['kinds'][k]['group'] for k in ks})       # верхняя оценка до запуска: оцениваемые × группы × прогоны × цена вызова, кэш не считаем
    if vlm_budget is not None:
        limit = float(vlm_budget)
    elif vlm_all:
        limit = up                                                                    # --vlm-all — осознанный выбор дорогого режима: потолок = оценка запуска, но не больше общего предела
    else:
        limit = float(J.get('budget_usd_per_form', 0.015)) * n_judged                  # по умолчанию: по форме × число оцениваемых (корпусных) форм
    budget = {'limit': min(limit, cap), 'capped': limit > cap}
    budget['left'] = budget['limit']
    if use_vlm:
        say(f"vlm оценка до запуска: форм {len(have)}, оцениваемых {n_judged}, верхняя оценка без кэша ≈${up:.4f}, потолок ${budget['limit']:.4f}"
            + (f" (по ${J.get('budget_usd_per_form', 0.015)} на форму{', при --vlm-all — по оценке' if vlm_all else ''}, общий предел ${cap:.2f}" + (', предел сработал' if budget['capped'] else '') + ')')
            + (' — если кэш пуст, потолок меньше: часть групп будет пропущена (vlm_skipped_budget)' if up > budget['limit'] + 1e-12 else ''))
    recs, rows = [], []
    for s in have:
        fr = os.path.join(out, s)
        photo = find_photo(s, photos, glbs, out) if not photo_name else os.path.join(photos, photo_name.format(sku=s))
        if use_vlm and not photo:
            say(f'vlm {s}: нет фото рядом с прогоном (--photos) — оценщик пропущен')
        kw = {'kinds_only': kinds_only, 'budget': budget, 'log': say}
        rec = FC.run_sku(s, find_glb(glbs, s), photo, fr, rules, pose_roots or [], fr, roles.get(s, ''), cache if (use_vlm and photo) else None, chat, kw,
                         None if cards is None else cards.get(s.replace(':', '_'), {}))               # размеры карточки (T-20261124-11): dims_depth/dims_axes в observe
        rec = FR.annotate(rec)                                                                # правило повтора формы (T-20261126-99/8): FORM_RESEED=0 — запись не меняется
        json.dump(rec, open(os.path.join(fr, 'form_checks.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        recs.append(rec)
        rows.append(eye_row(rec, roles.get(s, '')))
        if rec.get('not_run'):
            say(f"{s}: проверки НЕ ВЫПОЛНЕНЫ (не «прошли»): {', '.join(rec['not_run'])} — {next((c['note'] for c in rec['checks'] if c.get('skipped')), '')}")
    if use_vlm:
        say(f"vlm итог: оценка израсходованного ≈${budget.get('spent', 0.0):.4f} из потолка ${budget['limit']:.4f}, групп пропущено по потолку {budget.get('skipped', 0)}")
    if rows:
        with open(os.path.join(out, 'form_gate.tsv'), 'w', encoding='utf-8') as f:
            f.write('\t'.join(COLS) + '\n' + '\n'.join('\t'.join(r) for r in rows) + '\n')
    return recs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='папка кадров приёмки: <out>/<sku>/NN_<вид>_clay*.png')
    ap.add_argument('--glbs', required=True)
    ap.add_argument('--skus', required=True)
    ap.add_argument('--roles', default='', help='JSON {sku: роль каталога}')
    ap.add_argument('--photos', default='')
    ap.add_argument('--photo-name', default='', help='шаблон имени фото в --photos (по умолчанию ищет find_photo)')
    ap.add_argument('--vlm-cache', default='', help='по умолчанию <out>/vlm-cache')
    ap.add_argument('--no-vlm', action='store_true', help='без оценщика по картинке (только геометрия)')
    ap.add_argument('--vlm-all', action='store_true', help='все виды оценщика (invented_detail, faceted …) и для всех ролей — дороже; по умолчанию 3 observe-вида × корпусные')
    ap.add_argument('--vlm-budget', type=float, default=None, help='потолок оценки расхода оценщика на запуск, $ (по умолчанию rules: budget_usd_per_form × число оцениваемых форм); не больше rules budget_usd_max')
    ap.add_argument('--pose-roots', default='')
    ap.add_argument('--rules', default='')
    ap.add_argument('--cards', default='', help='JSON {sku: {w,d,h,len,dia,src}} (см) для мерки форма÷карточка; по умолчанию — из базы (cards_from_db, только чтение)')
    ap.add_argument('--no-cards', action='store_true', help='без мерки форма÷карточка (dims_depth/dims_axes)')
    a = ap.parse_args()
    import form_checks as FC
    skus = [s for s in a.skus.split(',') if s]
    cards = None if a.no_cards else (json.load(open(os.path.expanduser(a.cards), encoding='utf-8')) if a.cards else FC.cards_from_db(skus))
    roles = json.load(open(os.path.expanduser(a.roles), encoding='utf-8')) if a.roles else {}
    recs = gate(os.path.expanduser(a.out), os.path.expanduser(a.glbs), skus, roles, os.path.expanduser(a.photos) if a.photos else '', a.photo_name,
                os.path.expanduser(a.vlm_cache) if a.vlm_cache else '', a.rules, [x for x in a.pose_roots.split(',') if x], vlm=not a.no_vlm, vlm_all=a.vlm_all, vlm_budget=a.vlm_budget, cards=cards)
    for r in recs:
        print(f"form_gate {r['sku']} {r['status']} {r['flags']}", flush=True)
    nr = [r for r in recs if r.get('not_run')]
    if nr:
        print(f"form_gate: проверки НЕ ВЫПОЛНЕНЫ у {len(nr)} из {len(recs)} форм: {', '.join(sorted({n for r in nr for n in r['not_run']}))}", flush=True)
    print(f'form_gate: проверено {len(recs)}, к глазам {sum(1 for r in recs if r["status"] in ("needs_review", "shape_reject"))}', flush=True)
    return 3 if nr else 0                                                            # не выполнено — не «прошла»: код 3 (T-20261127-175/Ш0-fix-2)


if __name__ == '__main__':
    sys.exit(main())
