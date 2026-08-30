#!/usr/bin/env python3
"""Локальный ремонт скачанных мешей перед публикацией: срез пола и обломков.

Зачем локально, а не только в образе. Правка резака на нодах требует перевыкатки группы —
это перекачка весов на каждой машине посреди прогона. Ремонт после drain даёт тот же
результат немедленно: галерея и дальнейшие потребители видят уже чищеное. В образе те же
функции тоже живут — свежие ноды после следующей выкатки будут чистить сами, а повторный
проход здесь безвреден (резакам нечего срезать второй раз).
"""
import glob
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('salad_pipeline', os.path.join(HERE, 'pipeline.py'))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

SRC = os.environ.get('REPAIR_SRC',
                     os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))

sys.path.insert(0, os.path.join(HERE, '..'))
RESEED = os.path.join(HERE, '..', 'mesh-reseed.json')
# роли, симметричные в плане: пустая глубина паспорта = ширине, иначе профильный гейт слеп
# (кашпо-доска 30.08 прошла именно из-за пустой d)
SQUARE_ROLES = {'кашпо', 'ваза', 'торшер', 'лампа', 'стол', 'пуф'}


def accept(d: str, man: dict) -> str:
    """Приёмка одного меша: геометрия + профиль по паспорту + PBR. Возвращает статус."""
    import mesh_gate as G
    import mesh_gate_pbr as PBR
    from PIL import Image
    glb = os.path.join(d, 'model.glb')
    role = man.get('role')
    dims = (man.get('input') or {}).get('dims_cm') or {}
    w = dims.get('w') or dims.get('dia')
    dd = dims.get('d') or (w if role in SQUARE_ROLES else None)
    h = dims.get('h')
    geo_ok = True
    prof_ok = True
    try:
        geo_ok = bool(G.geometry_layer(glb).get('ok', True))
    except Exception:  # noqa: BLE001
        pass
    if w and dd and h and os.path.exists(os.path.join(d, 'cutout.png')):
        try:
            v = G.view_layer(glb, Image.open(os.path.join(d, 'cutout.png')),
                             float(w), float(dd), float(h), 0)
            prof_ok = bool(v.get('profile_ok', True))
        except Exception:  # noqa: BLE001
            pass
    st = PBR.status(glb, role=role, geometry_ok=geo_ok and prof_ok)
    return st['status']


def main() -> None:
    fixed = 0
    verdicts = {}
    reseed = json.load(open(RESEED, encoding='utf-8')) if os.path.exists(RESEED) else []
    seen = {(r['sku'], r.get('seed')) for r in reseed}
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
        d = os.path.dirname(mp)
        glb = os.path.join(d, 'model.glb')
        if not os.path.exists(glb):
            continue
        man = json.load(open(mp, encoding='utf-8'))
        role = man.get('role')
        gen = os.path.join(d, 'model.generated.glb')
        if not os.path.exists(gen):
            import shutil
            shutil.copy(glb, gen)          # неизменяемый «до ремонта» — для отката и сверки
        before = os.path.getsize(glb)
        P.cut_base_slab(glb, role)
        P.cut_alien_debris(glb)
        try:
            import importlib.util as _il
            _sp = _il.spec_from_file_location('tf', os.path.join(HERE, 'texture_fix.py'))
            _tf = _il.module_from_spec(_sp); _sp.loader.exec_module(_tf)
            n = _tf.despeckle_glb(glb)
            if n:
                print(f'  текстура: закрашено {n} px крапинок')
        except Exception as e:  # noqa: BLE001 — страховка не должна валить конвейер
            print(f'  despeckle пропущен: {str(e)[:80]}')
        if os.path.getsize(glb) != before:
            fixed += 1
            json.dump({'ops': ['slab', 'despeckle'], 'bytes_before': before,
                       'bytes_after': os.path.getsize(glb)},
                      open(os.path.join(d, 'repair.json'), 'w'))
            print(f'  починен: {os.path.basename(os.path.dirname(d))} ({role})')
        status = accept(d, man)
        verdicts[man['sku']] = status
        json.dump({'status': status}, open(os.path.join(d, 'verdict.json'), 'w'))
        # СЛОЙ ЛЕЧЕНИЯ: не дотянул до scene_ready → перегон другим seed, максимум два захода
        seed = int(man.get('seed') or 0)
        if status in ('generated', 'geometry_valid') and seed < 2:
            key = (man['sku'], seed + 1)
            if key not in seen:
                seen.add(key)
                inp = man.get('input') or {}
                reseed.append({'sku': man['sku'], 'role': role,
                               'image_url': inp.get('image_url'),
                               'dims_cm': inp.get('dims_cm'), 'seed': seed + 1, 'params': {}})
    json.dump(reseed, open(RESEED, 'w'), ensure_ascii=False, indent=1)
    import collections
    print(f'ремонт: изменено {fixed} | приёмка: {dict(collections.Counter(verdicts.values()))} '
          f'| на перегон: {len(reseed)}')

if __name__ == '__main__':
    main()
