#!/usr/bin/env python3
"""Шаг form_gate (Ш0, T-184/9, директор 22.11): GLB + кадры приёмки → `<out>/<sku>/form_checks.json` + строка сводки `<out>/form_gate.tsv`. OBSERVE: ничего не бракует и не меняет код возврата рендера.
Зовётся в конце `tools/ops/forms_render.py --accept` (флаг `--no-form-gate` выключает) — кадры приёмки рождаются там, значит Ш0 идёт сразу после них для любой новой формы; можно и отдельно:
  python form_gate.py --out <папка кадров приёмки> --glbs <папка GLB> --skus a,b [--roles roles.json] [--photos DIR] [--vlm-cache DIR] [--rules F]
Проверки — `form_checks.run_sku` (пороги и виды — `tools/scout/rules/form-checks.json`); оценщик по картинке (vlm_judge, платный ≈$0,003 на корпусную форму, ответы кэшируются) — только если есть `--photos` и `--vlm-cache`.
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


def eye_row(rec: dict, role: str = '') -> list[str]:
    """Строка сводки по записи `run_sku`: статус, нужно ли глазам, флаги и пояснения флагов оценщика/перекоса."""
    flags = rec.get('flags') or []
    why = '; '.join(f"{c['name']}: {c.get('note', '')}"[:140] for c in rec.get('checks', []) if c.get('flag') and (c['name'].startswith('vlm_') or c['name'] == 'body_skew'))
    return [rec['sku'], role or '—', rec.get('status', '?'), 'да' if rec.get('status') in ('needs_review', 'shape_reject') else 'нет', ','.join(flags) or '—', why or '—']


def gate(out: str, glbs: str, skus: list[str], roles: dict | None = None, photos: str = '', photo_name: str = '{sku}.hd.rgba.png', vlm_cache: str = '',
         rules_path: str = '', pose_roots: list[str] | None = None, chat=None, find_glb=None) -> list[dict]:
    """Проверки по каждому товару, у которого есть кадры в `<out>/<sku>`; пишет form_checks.json и form_gate.tsv. Возвращает записи."""
    import form_checks as FC
    if find_glb is None:
        import forms_render as FR
        find_glb = FR.find_glb_
    rules = FC.load_rules(rules_path) if rules_path else FC.load_rules()
    roles = roles or {}
    recs, rows = [], []
    for s in skus:
        fr = os.path.join(out, s)
        if not os.path.isdir(fr):
            continue
        photo = os.path.join(photos, photo_name.format(sku=s)) if photos else None
        rec = FC.run_sku(s, find_glb(glbs, s), photo, fr, rules, pose_roots or [], None, roles.get(s, ''), (vlm_cache or None) if photo else None, chat)
        json.dump(rec, open(os.path.join(fr, 'form_checks.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        recs.append(rec)
        rows.append(eye_row(rec, roles.get(s, '')))
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
    ap.add_argument('--photo-name', default='{sku}.hd.rgba.png')
    ap.add_argument('--vlm-cache', default='')
    ap.add_argument('--pose-roots', default='')
    ap.add_argument('--rules', default='')
    a = ap.parse_args()
    roles = json.load(open(os.path.expanduser(a.roles), encoding='utf-8')) if a.roles else {}
    recs = gate(os.path.expanduser(a.out), os.path.expanduser(a.glbs), [s for s in a.skus.split(',') if s], roles, os.path.expanduser(a.photos) if a.photos else '', a.photo_name,
                os.path.expanduser(a.vlm_cache) if a.vlm_cache else '', a.rules, [x for x in a.pose_roots.split(',') if x])
    for r in recs:
        print(f"form_gate {r['sku']} {r['status']} {r['flags']}", flush=True)
    print(f'form_gate: проверено {len(recs)}, к глазам {sum(1 for r in recs if r["status"] in ("needs_review", "shape_reject"))}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
