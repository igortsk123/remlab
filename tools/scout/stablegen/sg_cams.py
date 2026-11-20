"""Камеры прогона StableGen как ДАННЫЕ для сторожа покрытия текстуры (T-20261120-152/1).

Зачем. Сторож `salad/trellis/tex_coverage.py` считал «виден ли тексель» по 6 ортографическим видам MV-Adapter. StableGen красит иначе: 8 перспективных камер
орбитального кольца (фокус 50 мм, подъём ≈26°, у каждой своё расстояние). Чтобы сторож мерил то, что на самом деле нарисовала сеть, камеры берутся из прогона, а не из констант.

Откуда берутся позы (по убыванию точности; в результате поле `source`):
  recorded       — файл `cameras.json` рядом с `painted.glb` (его пишет `sg_drive` у новых прогонов через `payload_from_scene`, либо `extract` достаёт его из session.blend).
  reconstructed  — session.blend уже удалён (`slim_run`): позы восстанавливаются по `status.json` (расстояние каждой камеры из `framing`) и числам кольца из `rules/sg-cameras.json`.
                   Совпадение с настоящими позами проверяется на прогонах, где session.blend цел (`compare`, тест `tests_sg_cams`).
Нет ни того, ни другого, или режим камер не `orbit_ring`/число не 8 → `None` (сторож отвечает «нет камер», а не гадает).

Кадр: файл — кадр Blender (Z вверх); `rig_glb` переводит в кадр GLB (Y вверх): (x, y, z) → (x, z, −y).

  blender -b session.blend --python sg_cams.py -- cameras.json     # достать позы из session.blend (внутри Blender)
  python3 sg_cams.py show RUN_DIR                                   # какие камеры будут у прогона и откуда
Без bpy и без trimesh: только numpy (внутри Blender — bpy)."""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.environ.get('SG_CAMERAS_RULES') or os.path.join(HERE, '..', 'rules', 'sg-cameras.json')
VERSION = 1


def rules() -> dict:
    r = json.load(open(RULES, encoding='utf-8'))
    for k in ('modes', 'num', 'ring_base_azimuth_deg', 'ring_step_deg', 'elevation_deg', 'lens', 'sensor_width', 'res', 'tolerance'):
        if k not in r:
            raise ValueError(f'{os.path.basename(RULES)}: нет поля {k}')
    return r


# ---- внутри Blender -------------------------------------------------------------------------------------------------
def payload_from_scene(scene) -> dict:
    """Позы всех камер сцены (кадр Blender). Вызывается из `sg_drive` после подгонки камер и из `extract` (одна и та же функция — её живая проверка на session.blend проверяет и запись нового прогона)."""
    from mathutils import Vector
    meshes = [o for o in scene.objects if o.type == 'MESH']
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    ctr = [round(sum(p[i] for p in pts) / len(pts), 5) for i in range(3)] if pts else [0.0, 0.0, 0.0]
    cams = []
    for o in sorted((o for o in scene.objects if o.type == 'CAMERA'), key=lambda o: o.name):
        d, m3 = o.data, o.matrix_world.to_3x3()
        cams.append({'name': o.name, 'location': [round(v, 5) for v in o.matrix_world.translation],
                     'forward': [round(v, 6) for v in (m3 @ Vector((0, 0, -1))).normalized()], 'up': [round(v, 6) for v in (m3 @ Vector((0, 1, 0))).normalized()],
                     'type': d.type, 'lens': d.lens, 'sensor_width': d.sensor_width, 'sensor_fit': d.sensor_fit, 'ortho_scale': d.ortho_scale,
                     # у каждой камеры своё разрешение кадра (аддон `apply_auto_aspect` подгоняет аспект по силуэту): свойства sg_res_x / sg_res_y
                     'res': [int(o.get('sg_res_x', scene.render.resolution_x)), int(o.get('sg_res_y', scene.render.resolution_y))]})
    return {'version': VERSION, 'source': 'recorded', 'frame': 'blender_z_up', 'res': [scene.render.resolution_x, scene.render.resolution_y],
            'centre': ctr, 'cameras': cams}


def _blender_main() -> None:
    import bpy
    out = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'cameras.json'
    doc = payload_from_scene(bpy.context.scene)
    tmp = out + '.tmp'
    json.dump(doc, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    print(f'sg_cams: камер {len(doc["cameras"])} → {out}')


# ---- вне Blender ----------------------------------------------------------------------------------------------------
def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def reconstruct(status: dict, cfg: dict, centre_b, rl: dict | None = None) -> dict | None:
    """Позы кольца по `status.json` (framing[].dist) и числам кольца. `centre_b` — центр габарита формы в кадре Blender. Режим не орбитальное кольцо / число не то / нет расстояний → None."""
    rl = rl or rules()
    cam = (cfg or {}).get('cameras') or {}
    fr = {f['cam']: f for f in (status or {}).get('framing') or []}
    n = int(cam.get('num', 0) or 0)
    if cam.get('mode', 'orbit_ring') not in rl['modes'] or n != int(rl['num']) or len(fr) != n or centre_b is None:
        return None
    cams = []
    for i in range(n):
        name = f'Camera_{i}'
        if name not in fr:
            return None
        az, el = math.radians(rl['ring_base_azimuth_deg'] + i * rl['ring_step_deg']), math.radians(rl['elevation_deg'])
        to_cam = [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)]
        fwd = [-x for x in to_cam]
        right = _unit(_cross(fwd, [0.0, 0.0, 1.0]))
        up = _unit(_cross(right, fwd))
        loc = [centre_b[k] + fr[name]['dist'] * to_cam[k] for k in range(3)]
        cams.append({'name': name, 'location': loc, 'forward': fwd, 'up': up, 'type': 'PERSP', 'lens': rl['lens'], 'sensor_width': rl['sensor_width'], 'sensor_fit': 'AUTO', 'ortho_scale': 6.0})
    return {'version': VERSION, 'source': 'reconstructed', 'frame': 'blender_z_up', 'res': list(rl['res']), 'centre': list(centre_b), 'cameras': cams}


def _read(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return None


def run_files(run_dir: str) -> tuple:
    """Где лежат данные прогона: (папка с painted.glb/status.json, cfg.json). Подходит и прогон (`<run>/blender/…`, `<run>/cfg.json`), и запись склада (`cameras.json` рядом с model.glb)."""
    d = os.path.join(run_dir, 'blender') if os.path.isdir(os.path.join(run_dir, 'blender')) else run_dir
    return d, os.path.join(run_dir, 'cfg.json')


def bbox_glb(path: str):
    """Габарит формы из GLB без зависимостей: min/max POSITION-акцессоров JSON-чанка (glTF их обязывает хранить) → (lo, hi) в кадре GLB или None. Экспорт Blender кладёт форму без трансформа узла."""
    import struct
    try:
        with open(path, 'rb') as fh:
            head = fh.read(20)
            n = struct.unpack('<I', head[12:16])[0]
            js = json.loads(fh.read(n).decode('utf-8')) if head[16:20] == b'JSON' else None
    except (OSError, ValueError, struct.error):
        return None
    if not js:
        return None
    lo, hi = None, None
    for m in js.get('meshes', []):
        for pr in m.get('primitives', []):
            a = js['accessors'][pr['attributes']['POSITION']]
            if 'min' not in a or 'max' not in a:
                return None
            lo = list(a['min']) if lo is None else [min(x, y) for x, y in zip(lo, a['min'])]
            hi = list(a['max']) if hi is None else [max(x, y) for x, y in zip(hi, a['max'])]
    return (lo, hi) if lo else None


def centre_blender(centre_glb):
    """Центр габарита в кадре Blender по центру в кадре GLB: (x, y, z)_glb → (x, −z, y)_blender."""
    if centre_glb is None:
        return None
    return [centre_glb[0], -centre_glb[2], centre_glb[1]]


def rig_for_run(run_dir: str, centre_glb=None, cams_dir: str | None = None, reconstruct_only: bool = False) -> dict | None:
    """Камеры прогона: записанные (`cameras.json`; `cams_dir/<имя папки прогона>.json` — позы, снятые `extract` из session.blend, прогон не трогаем) → иначе восстановленные
    (нужен центр габарита формы в кадре GLB) → иначе None. `reconstruct_only` — игнорировать записанные (сравнение «записанные ↔ восстановленные»)."""
    d, cfgp = run_files(run_dir)
    if not reconstruct_only:
        for p in ((os.path.join(cams_dir, os.path.basename(run_dir.rstrip('/')) + '.json'),) if cams_dir else ()) + (os.path.join(d, 'cameras.json'), os.path.join(run_dir, 'cameras.json')):
            doc = _read(p)
            if doc and doc.get('cameras'):
                return doc
    status, cfg = _read(os.path.join(d, 'status.json')), _read(cfgp)
    if not status:
        return None
    return reconstruct(status, cfg or {}, centre_blender(centre_glb))


def rig_glb(doc: dict) -> list:
    """Камеры в кадре GLB для `tex_coverage.analyze(rig=…)`: [{name, eye, forward, up, hx, hy}] — hx/hy: полуширина/полувысота кадра на единичном расстоянии (перспектива) либо в метрах (ортография, `ortho`=True)."""
    out = []
    conv = lambda v: [v[0], v[2], -v[1]]  # noqa: E731
    for c in doc['cameras']:
        w, h = c.get('res') or doc.get('res') or [1, 1]
        if c.get('type') == 'ORTHO':
            half, ortho = c['ortho_scale'] / 2.0, True
        elif c.get('type') == 'PERSP':
            half, ortho = c['sensor_width'] / 2.0 / c['lens'], False
        else:
            raise ValueError(f"камера {c.get('name')}: тип {c.get('type')} не поддержан (нужен PERSP или ORTHO)")
        hx, hy = (half, half * h / w) if w >= h else (half * w / h, half)
        out.append({'name': c['name'], 'eye': conv(c['location']), 'forward': conv(c['forward']), 'up': conv(c['up']), 'hx': hx, 'hy': hy, 'ortho': ortho})
    return out


def compare(rec: dict, rebuilt: dict, size: float) -> dict:
    """Расхождение восстановленных поз с записанными: max позиции (доли размера предмета `size`) и max угол направления взгляда."""
    a = {c['name']: c for c in rec['cameras']}
    pos, ang = 0.0, 0.0
    for c in rebuilt['cameras']:
        r = a[c['name']]
        pos = max(pos, math.dist(c['location'], r['location']) / size)
        dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(c['forward'], r['forward']))))
        ang = max(ang, math.degrees(math.acos(dot)))
    return {'position_frac': round(pos, 4), 'forward_deg': round(ang, 3)}


def extract(blend: str, out_json: str, blender: str | None = None, timeout: int = 600) -> dict:
    """Достать позы из session.blend запуском Blender без окна. Тяжёлое (≈10 с, 100 МБ файл) — снаружи под heavy-slot."""
    import subprocess
    blender = blender or os.environ.get('BLENDER_BIN') or os.path.expanduser('~/opt/blender-4.5.9/blender')
    subprocess.run(['nice', '-n', '10', blender, '-b', blend, '--python', os.path.abspath(__file__), '--', out_json], check=True, timeout=timeout,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(out_json, encoding='utf-8'))


if __name__ == '__main__':
    try:
        import bpy  # noqa: F401 — есть только внутри Blender
        _blender_main()
    except ImportError:
        if len(sys.argv) >= 4 and sys.argv[1] == 'compare':      # compare ПРОГОН ЗАПИСАННЫЕ.json → расхождение восстановленных поз с записанными (доли размера предмета, градусы)
            lo, hi = bbox_glb(os.path.join(run_files(sys.argv[2])[0], 'painted.glb') if os.path.isfile(os.path.join(run_files(sys.argv[2])[0], 'painted.glb')) else os.path.join(sys.argv[2], 'model.glb'))
            rec = json.load(open(sys.argv[3], encoding='utf-8'))
            reb = rig_for_run(sys.argv[2], [(a + b) / 2 for a, b in zip(lo, hi)], reconstruct_only=True)
            res = compare(rec, reb, max(b - a for a, b in zip(lo, hi))) if reb else {'error': 'восстановить нечем'}
            if reb:
                tol = rules()['tolerance']
                res['within_tolerance'] = res['position_frac'] <= tol['position_frac'] and res['forward_deg'] <= tol['forward_deg']
            print(json.dumps(res))
        elif len(sys.argv) >= 3 and sys.argv[1] == 'show':
            doc = rig_for_run(sys.argv[2])
            print(f"{sys.argv[2]}: " + ('нет камер' if not doc else f"{doc['source']}, камер {len(doc['cameras'])}, кадр {doc['res']}"))
        else:
            print(__doc__)
