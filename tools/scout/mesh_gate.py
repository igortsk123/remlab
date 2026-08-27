#!/usr/bin/env python3
"""Приёмка меша товара — двухслойная, с манифестом (план viz-mesh-orientation, q22).

Слой 1 — геометрия GLB (без фото): связные компоненты (trimesh.split), «плавающий» и крупный
плоский компонент, вырожденные треугольники.
Слой 2 — видовой (против фото и ПАСПОРТНЫХ габаритов): ПРОФИЛЬНЫЙ аспект против Г/В
(пруф 28.08: фронтальный силуэт брак с внутренней плитой НЕ ловит — 72% IoU у брака;
профиль ловит: 1.02 против ожидаемых 0.47) + extra/missing к дилатированной маске фото.

Вердикты: ready | mesh_invalid | geometry_suspect. Фолбэк-цепочка (решение владельца 28.08):
Trellis → fal-ai/hunyuan3d/v2/mini → REPLACE_PRODUCT (товар выбывает из сета, слот лечится
штатно; годный меш — 4-е условие контракта слота визуализируемых ролей).
Манифест пишется атомарно рядом с GLB и инвалидируется при смене модели/версии gate
(фикс бага mesh_trusted: отрицательный вердикт не должен переживать замену модели).
"""
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

import mesh_render as MR
from mesh_orient import photo_mask, render_sil, _fit

GATE_VERSION = 2
PROFILE_MAX = 1.8          # профиль/фронт не толще ожидаемого более чем в 1.8 раза
EXTRA_MAX = 0.30           # доля меша вне (дилатированного) силуэта фото
MISSING_MAX = 0.45         # доля фото, не покрытая мешем


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def manifest_path(glb_path: str) -> str:
    return glb_path[:-4] + '.manifest.json'


def load_manifest(glb_path: str) -> dict | None:
    """Манифест валиден, только если совпали hash модели и версия gate — иначе пересчёт."""
    mp = manifest_path(glb_path)
    if not os.path.exists(mp):
        return None
    try:
        m = json.load(open(mp, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None
    if m.get('gate_version') != GATE_VERSION or m.get('glb_sha') != _sha(glb_path):
        return None
    return m


def save_manifest(glb_path: str, data: dict) -> None:
    mp = manifest_path(glb_path)
    data = {**data, 'gate_version': GATE_VERSION, 'glb_sha': _sha(glb_path)}
    tmp = mp + '.tmp'
    json.dump(data, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, mp)


def geometry_layer(glb_path: str) -> dict:
    import trimesh
    scene = trimesh.load(glb_path, force='scene')
    meshes = list(scene.geometry.values()) if hasattr(scene, 'geometry') else [scene]
    comps = []
    for m in meshes:
        try:
            comps += m.split(only_watertight=False)
        except Exception:  # noqa: BLE001
            comps.append(m)
    if not comps:
        return {'ok': False, 'reason': 'нет геометрии'}
    areas = np.array([float(c.area) for c in comps])
    total = float(areas.sum()) or 1.0
    flags = []
    main = comps[int(areas.argmax())]
    mb = main.bounds
    for c, ar in zip(comps, areas):
        if ar / total < 0.08:
            continue
        ext = np.sort(c.extents)
        flat = ext[0] / max(ext[2], 1e-6) < 0.03          # тонкая плита
        b = c.bounds
        # «плавает»/выпирает из тела основного компонента более чем на 15% габарита
        overhang = float(np.maximum(mb[0] - b[0], b[1] - mb[1]).max()
                         / max(main.extents.max(), 1e-6))
        if flat and (c is not main) and (ar / total > 0.18 or overhang > 0.15):
            flags.append({'flat_component': round(ar / total, 2),
                          'overhang': round(overhang, 2)})
    return {'ok': bool(not flags), 'components': len(comps), 'flags': flags}


def view_layer(glb_path: str, photo: Image.Image, w_cm: float, d_cm: float,
               h_cm: float, front_yaw: int) -> dict:
    parts = MR.load_parts(glb_path)

    def aspect(yaw):
        m, _ = render_sil(parts, yaw)
        if m is None:
            return None
        return m.shape[1] / m.shape[0]

    # ОСЬ ДЛЯ ПРОФИЛЯ — ГЕОМЕТРИЕЙ, не цветовым фронтом (перед/зад на аспект не влияют):
    # из yaw 0/90 берём тот, чей аспект ближе к паспортному Ш/В — профиль перпендикулярен ему.
    a0, a90 = aspect(0), aspect(90)
    if a0 is None or a90 is None:
        return {'ok': False, 'reason': 'пустой рендер'}
    exp_front = w_cm / max(h_cm, 1e-6)
    axis = 0 if abs(a0 - exp_front) <= abs(a90 - exp_front) else 90
    af, ap = (a0, a90) if axis == 0 else (a90, a0)
    exp_ratio = (d_cm / h_cm) / max(w_cm / h_cm, 1e-6)
    ratio = ap / max(af, 1e-6)
    profile_ok = ratio <= exp_ratio * PROFILE_MAX
    pm, pc = photo_mask(photo)
    extra = missing = None
    if pm is not None:
        mm, _ = render_sil(parts, front_yaw)
        a, _ = _fit(mm, np.zeros((*mm.shape, 3)))
        b, _ = _fit(pm, np.zeros((*pm.shape, 3)))
        bd = np.asarray(Image.fromarray(b.astype(np.uint8) * 255)
                        .filter(ImageFilter.MaxFilter(9))) > 127
        ad = np.asarray(Image.fromarray(a.astype(np.uint8) * 255)
                        .filter(ImageFilter.MaxFilter(9))) > 127
        extra = float((a & ~bd).sum()) / max(a.sum(), 1)
        missing = float((b & ~ad).sum()) / max(b.sum(), 1)
    # HARD — только профиль (пруф 28.08); extra/missing на карточках с интерьерным фоном
    # честно шумят → это «suspect», не брак (разбор q22: hard только комбинация признаков)
    ok = bool(profile_ok)
    suspect = bool((extra is not None and extra > EXTRA_MAX)
                   or (missing is not None and missing > MISSING_MAX))
    return {'ok': ok, 'suspect': suspect, 'axis_yaw': axis, 'profile_ratio': round(ratio, 2),
            'profile_expected': round(exp_ratio, 2), 'profile_ok': bool(profile_ok),
            'extra': None if extra is None else round(extra, 2),
            'missing': None if missing is None else round(missing, 2)}


def gate(glb_path: str, photo: Image.Image, w_cm: float, d_cm: float, h_cm: float,
         front_yaw: int = 0, generator: str = 'trellis') -> dict:
    cached = load_manifest(glb_path)
    if cached is not None:
        return cached
    geo = geometry_layer(glb_path)
    view = view_layer(glb_path, photo, w_cm, d_cm, h_cm, front_yaw)
    if not view.get('ok'):
        status = 'mesh_invalid'                      # профиль — жёсткий признак паразитной массы
    elif not geo.get('ok') or view.get('suspect'):
        status = 'geometry_suspect'                  # годен с пометкой; на золотом сете уточним
    else:
        status = 'ready'
    data = {'status': status, 'generator': generator, 'front_yaw': front_yaw,
            'geometry': geo, 'view': view,
            'dims': {'w': w_cm, 'd': d_cm, 'h': h_cm}}
    save_manifest(glb_path, data)
    return data


def verdict_for_photo(img_url: str, mesh_dir: str) -> str | None:
    """Статус для контракта слота: 'replace_product' пишется в общий реестр после двойного брака."""
    reg = os.path.join(mesh_dir, 'replace-registry.json')
    if not os.path.exists(reg):
        return None
    try:
        r = json.load(open(reg, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None
    key = hashlib.md5((img_url or '').encode()).hexdigest()[:16]
    return r.get(key)


if __name__ == '__main__':
    import io
    import urllib.request
    glb, url = sys.argv[1], sys.argv[2]
    w, d, h = (float(x) for x in sys.argv[3:6])
    yaw = int(sys.argv[6]) if len(sys.argv) > 6 else 0
    ph = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=60).read()))
    print(json.dumps(gate(glb, ph, w, d, h, yaw), ensure_ascii=False, indent=1))
