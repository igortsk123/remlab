#!/usr/bin/env python3
"""Приёмка PBR-ассета: карты материалов и бюджет рантайма. Дополняет `mesh_gate.py`.

ЗАЧЕМ ОТДЕЛЬНЫЙ СЛОЙ. `mesh_gate` писался под Trellis-меши с ЗАПЕЧЁННОЙ текстурой и умеет
ровно две вещи: цела ли геометрия и похож ли силуэт на фото. Для Hunyuan 2.1 этого мало по
двум причинам.

Первая: смысл 2.1 — разделённые PBR-карты, и именно они могут оказаться мусором при идеальной
геометрии. Пустая или константная roughness-карта означает, что материал не различает дерево и
стекло; запечённая в albedo тень означает, что в сцене со своим светом предмет будет светиться
чужим. Ни то, ни другое силуэтная проверка не видит.

Вторая: стеклянный плафон без `KHR_materials_transmission` и лампа без emissive пройдут любую
геометрическую проверку, а в квартире будут выглядеть кусками пластика. Для люстр — а их в
пуле 3 732 — это главный вопрос, ради которого их вообще включили в пилот.

Отдельно считается БЮДЖЕТ РАНТАЙМА. Меш может быть верным и при этом непригодным: канвас
планировщика держит 10–20 предметов одновременно, и ассет на 800 тысяч треугольников с
текстурами 4096² убьёт кадр. «Годен» без этой проверки — самообман.

Итоговый статус ассета (4 ступени плана):
  generated → geometry_valid (mesh_gate) → scene_ready (+PBR) → web_ready (+бюджет)

  ~/venvs/scout/bin/python mesh_gate_pbr.py model.glb [--role люстра]
"""
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

# Бюджет одного ассета для канваса с 10–20 предметами. Числа — стартовые, перекалибровать
# после первого замера времени загрузки в браузере (задача плана).
MAX_TRIS = 150_000
MAX_MATERIALS = 4
MAX_TEX_PX = 2048
MAX_GLB_MB = 8.0

# Роли, которым прозрачность и свечение НУЖНЫ по существу: без них предмет неверен в сцене.
GLASS_ROLES = {'люстра', 'бра', 'торшер', 'лампа', 'витрина'}
EMISSIVE_ROLES = {'люстра', 'бра', 'торшер', 'лампа'}

CONST_STD = 3.0        # ниже — карта считается константной (в единицах 0..255)
FLAT_SHARE = 0.98      # доля пикселей в одном значении, при которой карта бесполезна


def glb_json(path: str) -> dict:
    """JSON-чанк GLB напрямую.

    trimesh при загрузке теряет расширения материалов (`KHR_materials_transmission`,
    `KHR_materials_emissive_strength`), а именно они решают судьбу стекла и ламп. Поэтому
    структуру читаем из файла, а не из объектной модели.
    """
    with open(path, 'rb') as f:
        magic, _, _ = struct.unpack('<III', f.read(12))
        if magic != 0x46546C67:
            raise ValueError('не GLB')
        length, ctype = struct.unpack('<II', f.read(8))
        if ctype != 0x4E4F534A:
            raise ValueError('первый чанк не JSON')
        return json.loads(f.read(length))


def _tex_stats(img: Image.Image) -> dict:
    a = np.asarray(img.convert('RGB'), dtype=np.float32)
    per_channel_std = [float(a[..., c].std()) for c in range(3)]
    vals, counts = np.unique(a.reshape(-1, 3), axis=0, return_counts=True)
    flat = float(counts.max()) / max(a.shape[0] * a.shape[1], 1)
    return {'std': round(max(per_channel_std), 2), 'flat_share': round(flat, 3),
            'size': list(img.size)}


def _load_textures(path: str, doc: dict) -> dict:
    """Картинки GLB по индексу. Внешние файлы игнорируем: наш конвейер пишет самодостаточный
    GLB, и ссылка наружу сама по себе — брак для канваса."""
    import trimesh
    out = {}
    try:
        scene = trimesh.load(path, force='scene')
    except Exception:  # noqa: BLE001
        return out
    for name, geom in getattr(scene, 'geometry', {}).items():
        mat = getattr(getattr(geom, 'visual', None), 'material', None)
        if mat is None:
            continue
        for attr, key in (('baseColorTexture', 'baseColor'),
                          ('metallicRoughnessTexture', 'metallicRoughness'),
                          ('normalTexture', 'normal'),
                          ('emissiveTexture', 'emissive'),
                          ('occlusionTexture', 'occlusion')):
            img = getattr(mat, attr, None)
            if isinstance(img, Image.Image):
                out.setdefault(key, img)
    return out


def baked_shadow(albedo: Image.Image) -> dict:
    """Признак запечённой тени в albedo: сильный НИЗКОЧАСТОТНЫЙ перепад яркости.

    Альбедо обязано нести только собственный цвет материала. Если генератор впечатал в него
    студийный свет, у карты появляется плавный градиент сверху вниз — и в сцене предмет
    остаётся подсвеченным «своим» солнцем независимо от освещения комнаты.
    Меряем по сильно уменьшенной копии: детали текстуры при этом усредняются, а градиент нет.
    """
    small = np.asarray(albedo.convert('L').resize((16, 16)), dtype=np.float32)
    rows = small.mean(axis=1)
    grad = float(rows[:4].mean() - rows[-4:].mean())     # верх минус низ
    span = float(small.max() - small.min())
    return {'vertical_gradient': round(grad, 1), 'span': round(span, 1),
            'suspect': bool(abs(grad) > 28 and span > 60)}


def pbr_layer(path: str, role: str | None = None) -> dict:
    doc = glb_json(path)
    mats = doc.get('materials') or []
    used_ext = set()
    for m in mats:
        used_ext |= set((m.get('extensions') or {}).keys())

    has_pbr = any('pbrMetallicRoughness' in m for m in mats)
    tex = _load_textures(path, doc)
    stats = {k: _tex_stats(v) for k, v in tex.items()}

    problems = []
    if not mats:
        problems.append('нет материалов')
    if not has_pbr:
        problems.append('нет pbrMetallicRoughness')
    if 'baseColor' not in tex:
        problems.append('нет baseColor-карты')
    # ОТСУТСТВИЕ metallicRoughness — это и есть «запечённая текстура», ради ухода от которой
    # затевался переход на 2.1. Проверено 28.08 на Trellis-мешах: без этой строки они
    # получали web_ready, то есть гейт называл годным ровно то, что мы заменяем.
    # Постоянные факторы материала карту не заменяют: они одинаковы для всей поверхности,
    # а нам нужно различать ткань сиденья и металл ножек в пределах одного предмета.
    if 'metallicRoughness' not in tex:
        problems.append('нет карты metallicRoughness — текстура запечённая, не PBR')
    if 'normal' not in tex:
        problems.append('нет normal-карты — рельеф будет плоским под любым светом')
    # Константная metallicRoughness = материал не различает дерево, ткань и металл.
    for key in ('baseColor', 'metallicRoughness'):
        s = stats.get(key)
        if s and (s['std'] < CONST_STD or s['flat_share'] > FLAT_SHARE):
            problems.append(f'{key}: карта константная (std {s["std"]}, '
                            f'однотонность {s["flat_share"]})')

    shadow = baked_shadow(tex['baseColor']) if 'baseColor' in tex else None
    if shadow and shadow['suspect']:
        problems.append(f'в albedo запечён свет (градиент {shadow["vertical_gradient"]})')

    # Роль решает, что считать браком: у дивана прозрачность не нужна, у плафона — обязательна.
    transmission = 'KHR_materials_transmission' in used_ext
    emissive = any(any(v > 0 for v in (m.get('emissiveFactor') or [0, 0, 0])) for m in mats) \
        or 'emissive' in tex
    if role in GLASS_ROLES and not transmission:
        problems.append('роль со стеклом, но нет KHR_materials_transmission')
    if role in EMISSIVE_ROLES and not emissive:
        problems.append('светильник без emissive — в сцене будет куском пластика')

    return {'ok': not problems, 'problems': problems, 'materials': len(mats),
            'extensions': sorted(used_ext), 'maps': sorted(tex),
            'texture_stats': stats, 'baked_shadow': shadow,
            'transmission': transmission, 'emissive': emissive}


def runtime_layer(path: str) -> dict:
    """Влезает ли ассет в кадр канваса вместе с полутора десятками соседей."""
    doc = glb_json(path)
    tris = 0
    for mesh in doc.get('meshes') or []:
        for prim in mesh.get('primitives') or []:
            idx = prim.get('indices')
            if idx is not None and idx < len(doc.get('accessors') or []):
                tris += (doc['accessors'][idx].get('count') or 0) // 3
    tex_px = max([max(_tex_stats(i)['size']) for i in _load_textures(path, doc).values()]
                 or [0])
    size_mb = os.path.getsize(path) / 2 ** 20
    n_mat = len(doc.get('materials') or [])

    problems = []
    if tris > MAX_TRIS:
        problems.append(f'треугольников {tris} > {MAX_TRIS}')
    if n_mat > MAX_MATERIALS:
        problems.append(f'материалов {n_mat} > {MAX_MATERIALS}')
    if tex_px > MAX_TEX_PX:
        problems.append(f'текстура {tex_px}px > {MAX_TEX_PX}')
    if size_mb > MAX_GLB_MB:
        problems.append(f'GLB {size_mb:.1f} МБ > {MAX_GLB_MB}')
    return {'ok': not problems, 'problems': problems, 'triangles': tris,
            'materials': n_mat, 'max_texture_px': tex_px, 'size_mb': round(size_mb, 2)}


def status(path: str, role: str | None = None, geometry_ok: bool | None = None) -> dict:
    """Четыре ступени готовности. Считаем ЧЕСТНО: ассет получает высший статус только если
    прошёл все нижние — иначе «годен» будет означать разное для разных товаров."""
    pbr = pbr_layer(path, role)
    rt = runtime_layer(path)
    if geometry_ok is False:
        st = 'generated'
    elif not pbr['ok']:
        st = 'geometry_valid'
    elif not rt['ok']:
        st = 'scene_ready'
    else:
        st = 'web_ready'
    return {'status': st, 'role': role, 'pbr': pbr, 'runtime': rt}


if __name__ == '__main__':
    glb = sys.argv[1]
    role = sys.argv[sys.argv.index('--role') + 1] if '--role' in sys.argv else None
    print(json.dumps(status(glb, role), ensure_ascii=False, indent=1))
