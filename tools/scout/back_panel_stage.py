#!/usr/bin/env python3
"""Этап «задняя панель» после 06 (T-20261123-43, ❓2; правило R-BACKPANEL-06; политика типа — А1 type-rules-code-01).

ЗАЧЕМ. TRELLIS дорисовывает зад корпусной мебели по лицу (рамки дверей, «листья»): на заду это выглядит как заплатки. `edge_sharpen.back_panel_glb` сплющивает такой рельеф в плоскость,
но нужны три вещи, которых у него нет: (1) разрешение по ТИПУ товара — только там, где паспорт говорит «зад — тон корпуса» (`paint.hidden_pattern=body` и `paint.mode=active`, `mesh_type_passports.paint_policy`);
(2) камера этапа 4 и фото-сторона этапа 6 — поэтому шаг стоит ПОСЛЕ 04 и 06; (3) след в папке товара — решение, причина, digest паспорта.

Что делает: читает `<run>/<sku>/06-visible/{visible.glb, prov.png, check.json}`; тип не подходит (не body / не active / нет типа) → ничего не меняет, пишет причину; подходит → `back_panel_glb` на visible.glb
(азимут/высота камеры и согласие кромок — из check.json этапа 6; согласие неизвестно → отказ: камере без проверки не верим). Исходный visible.glb сохраняется как `visible.pre-backpanel.glb` (повторный запуск идёт от него),
этап 7 читает исправленный visible.glb. UV и карты (known/prov/conf) не трогаются — меняются только положения вершин зада. След — `06-visible/back_panel.json`.
Чисел порогов и ID товаров в коде нет: пороги — rules/edge-sharpen.json (back_panel), разрешение по типу — там же (back_panel.paint_gate), согласие кромок — rules/camera-check.json (edge_ref).

  python tools/scout/back_panel_stage.py --run RUN --sku SKU [--product-role РОЛЬ]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import edge_sharpen as ES  # noqa: E402
import mesh_type_passports as MTP  # noqa: E402
import paint_stage as PS  # noqa: E402

RULE_ID = 'R-BACKPANEL-06'
STAGE_DIR = '06-visible'
KEEP = 'visible.pre-backpanel.glb'
OUT = 'back_panel.json'


def gate(role: str | None, reg: dict | None = None, rules: dict | None = None) -> dict:
    """Разрешение по типу. → {allowed, reason, policy}. Нет роли / типа / политики → не allowed с кодом причины (воздержание, не «обычная мебель»)."""
    g = ((rules or ES.load_rules())['back_panel']).get('paint_gate') or {}
    pol = MTP.paint_policy(role, reg)
    want_hp, want_mode = g.get('hidden_pattern'), g.get('mode')
    if not want_hp or not want_mode:
        return {'allowed': False, 'reason': 'нет back_panel.paint_gate в rules/edge-sharpen.json', 'policy': pol}
    if pol['hidden_pattern'] != want_hp:
        why = pol.get('reason') or 'policy'
        return {'allowed': False, 'reason': f"тип «{pol.get('type')}»: hidden_pattern={pol['hidden_pattern']} ({why}), нужен {want_hp}", 'policy': pol}
    if pol['mode'] != want_mode:
        return {'allowed': False, 'reason': f"тип «{pol.get('type')}»: paint.mode={pol['mode']}, нужен {want_mode}", 'policy': pol}
    return {'allowed': True, 'reason': '', 'policy': pol}


def _json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def camera_of(check: dict) -> tuple[float | None, float | None, float | None]:
    """(az, el, согласие кромок позы, откуда согласие) из check.json этапа 6: extra.camera и extra.front_check.edge_agree; нет — pose.json рядом с папкой товара (`<sku>/04-camera/pose.json`, `<sku>/pose.json`)."""
    ex = check.get('extra') or {}
    cam = ex.get('camera') or {}
    az, el = cam.get('az'), cam.get('el')
    ag = (ex.get('front_check') or {}).get('edge_agree')
    return (None if az is None else float(az), None if el is None else float(el), None if ag is None else float(ag))


def pose_edge_from_files(sku_dir: str) -> float | None:
    for rel in ('04-camera/pose.json', 'pose.json'):
        e = ((_json(os.path.join(sku_dir, rel)).get('picked') or {}).get('edge') or {})
        if e and not e.get('no_edges') and e.get('agree') is not None:
            return float(e['agree'])
    return None


def run_stage(run: str, sku: str, role: str | None, reg: dict | None = None, rules: dict | None = None, glb_fn=None) -> dict:
    """Весь шаг; `glb_fn` подменяется тестами. Пишет `06-visible/back_panel.json`, возвращает его содержимое."""
    t0 = time.time()
    rules = rules or ES.load_rules()
    sku_dir = os.path.join(run, PS.safe_name(sku))
    d = os.path.join(sku_dir, STAGE_DIR)
    doc = {'rule_id': RULE_ID, 'sku': sku, 'role': role or '', 'applied': False, 'reason': '', 'policy': None}

    def done(reason: str = '', **kw):
        doc.update(kw)
        doc['reason'] = reason
        doc['seconds'] = round(time.time() - t0, 1)
        if os.path.isdir(d):
            with open(os.path.join(d, OUT), 'w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
        return doc
    g = gate(role, reg, rules)
    doc['policy'] = {k: g['policy'].get(k) for k in ('type', 'hidden_pattern', 'mode', 'digest', 'reason')}
    if not g['allowed']:
        return done('тип не допускает: ' + g['reason'])
    vis, prov = os.path.join(d, 'visible.glb'), os.path.join(d, 'prov.png')
    keep = os.path.join(d, KEEP)
    src = keep if os.path.exists(keep) else vis                      # повторный запуск — от исходного, не от уже выровненного
    if not os.path.exists(src):
        return done('нет входа: 06-visible/visible.glb')
    az, el, agree = camera_of(_json(os.path.join(d, 'check.json')))
    if az is None or el is None:
        return done('нет камеры этапа 4 в 06-visible/check.json (extra.camera)')
    if agree is None:
        agree = pose_edge_from_files(sku_dir)
    if agree is None:
        return done('согласие кромок камеры неизвестно: камере без проверки не верим, зад не трогаем')
    tmp = os.path.join(d, '_back_panel.tmp.glb')
    try:
        rep = (glb_fn or ES.back_panel_glb)(src, tmp, az, el, rules, pose_edge=agree, photo=(src, prov) if os.path.exists(prov) else None)
    except Exception as e:  # noqa: BLE001 — сбой шага не роняет конвейер, причина в следе
        if os.path.exists(tmp):
            os.remove(tmp)
        return done(f'сбой расчёта: {type(e).__name__}: {str(e)[:160]}')
    doc['camera'] = {'az': az, 'el': el, 'edge_agree': agree}
    if not rep.get('written'):
        if os.path.exists(tmp):
            os.remove(tmp)
        return done(str(rep.get('reason') or 'не применено'), report=_slim(rep))
    if not os.path.exists(keep):
        shutil.copy2(vis, keep)
    os.replace(tmp, vis)
    return done('', applied=True, report=_slim(rep))


def _slim(rep: dict) -> dict:
    return {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v)[:120]) for k, v in rep.items() if k not in ('moved',)}


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--run', required=True)
    ap.add_argument('--sku', required=True)
    ap.add_argument('--product-role', default='')
    a = ap.parse_args(argv)
    doc = run_stage(a.run, a.sku, a.product_role)
    print(json.dumps({'applied': doc['applied'], 'reason': doc['reason']}, ensure_ascii=False))
    return 0                                                         # отказ — не сбой: этап 7 идёт с прежним visible.glb


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
