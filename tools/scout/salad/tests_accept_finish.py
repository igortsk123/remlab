#!/usr/bin/env python3
"""Автоприёмка (T-20261105-36/2): нет normal-карты — отделка, не брак; на перегон — только брак формы.

  1) Меш как у Hunyuan 2.1 (baseColor + metallicRoughness, normal нет) — PBR-слой ok, normal в notes, статус web_ready;
  2) без metallicRoughness — по-прежнему брак отделки (geometry_valid): прочие правила PBR не ослаблены;
  3) геометрия не прошла — generated, как раньше;
  4) перегон: generated + seed 0 → да; geometry_valid / scene_ready / web_ready → нет; seed ≥ 1 → нет, а generated
     с seed ≥ 1 — кандидат на ручной разбор (geometry_valid — нет);
  5) крупная тонкая плита — заметка геометрии, а не брак (флаг пропал, notes есть).
Без сети, GPU и мешей: разбор GLB и текстуры подменены.
Запуск (DEV, нужен numpy): ~/venvs/scout/bin/python tools/scout/salad/tests_accept_finish.py"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
import apply_repairs as AR  # noqa: E402
import mesh_gate_pbr as PBR  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


rng = np.random.default_rng(7)


def noise():
    return Image.fromarray(rng.integers(40, 220, (64, 64, 3), dtype=np.uint8))


MAPS = {}
PBR.glb_json = lambda path: {'materials': [{'pbrMetallicRoughness': {}}], 'meshes': [], 'accessors': []}
PBR._load_textures = lambda path, doc: dict(MAPS)
open_size = os.path.getsize
os.path.getsize = lambda p: 1024 * 1024 if p == 'fake.glb' else open_size(p)

MAPS.clear(); MAPS.update(baseColor=noise(), metallicRoughness=noise())
st = PBR.status('fake.glb', role='кровать', geometry_ok=True)
check('1) Hunyuan-набор карт: PBR ok, normal — заметка, статус web_ready',
      st['pbr']['ok'] and any('normal' in n for n in st['pbr']['notes'])
      and not any('normal' in p for p in st['pbr']['problems']) and st['status'] == 'web_ready',
      f"status={st['status']} problems={st['pbr']['problems']}")

MAPS.clear(); MAPS.update(baseColor=noise())
st = PBR.status('fake.glb', role='кровать', geometry_ok=True)
check('2) без metallicRoughness — брак отделки, geometry_valid', st['status'] == 'geometry_valid'
      and any('metallicRoughness' in p for p in st['pbr']['problems']), f"status={st['status']}")

MAPS.clear(); MAPS.update(baseColor=noise(), metallicRoughness=noise())
st = PBR.status('fake.glb', role='кровать', geometry_ok=False)
check('3) геометрия не прошла — generated', st['status'] == 'generated', f"status={st['status']}")

check('4) перегон: generated, seed 0 — да', AR.wants_reseed('generated', 0))
for s in ('geometry_valid', 'scene_ready', 'web_ready'):
    check(f'4) перегон: {s}, seed 0 — нет', not AR.wants_reseed(s, 0))
check('4) перегон: generated, seed 1 — нет (один reseed)', not AR.wants_reseed('generated', 1))
check('4) ручной разбор: generated, seed 1 — да', AR.manual_repair('generated', 1))
check('4) ручной разбор: geometry_valid, seed 1 — нет', not AR.manual_repair('geometry_valid', 1))
check('4) ручной разбор: generated, seed 0 — нет (сперва перегон)', not AR.manual_repair('generated', 0))

# 5) «тонкая плита» — заметка, не брак (ведущий 05.11): корпус + широкая тонкая плита отдельным куском у пола,
#    выступает за корпус — geometry_layer ok, плита в notes; пороги прежние (та же плита раньше давала flags).
import tempfile  # noqa: E402

import trimesh  # noqa: E402

import mesh_gate as G  # noqa: E402

body = trimesh.creation.box(extents=(1.0, 0.8, 0.6))
plate = trimesh.creation.box(extents=(1.3, 0.01, 0.7))   # 1/3 площади — правило срабатывает (> 0.18)
plate.apply_translation((0, -0.405, 0))
with tempfile.TemporaryDirectory(prefix='accept-plate-') as td:
    glb = os.path.join(td, 'model.glb')
    trimesh.Scene([body, plate]).export(glb)
    g = G.geometry_layer(glb)
check('5) тонкая плита у пола: geometry ok, плита — заметка',
      g.get('ok') and any('flat_component' in n for n in g.get('notes') or [])
      and not any('flat_component' in f for f in g.get('flags') or []), f'{g}')

print('tests_accept_finish:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
