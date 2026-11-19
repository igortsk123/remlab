#!/usr/bin/env python3
"""ПРОБА ВТОРОГО ПРАВИЛА ОЧИСТКИ на готовых GLB (бесплатно, без записи в боевые файлы): правило A (куски, как сейчас) vs B (плита по нормалям и высоте) vs A+B; числа и аудит-GLB для кадров.
  python3 slab_probe.py <метка=путь.glb> ... [--out папка]"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_clean as MC


def load(path):
    import trimesh
    sc = trimesh.load(path, force='scene')
    parts = [g for g in sc.dump() if len(g.faces)]
    offs = np.cumsum([0] + [len(g.vertices) for g in parts])
    v = np.concatenate([np.asarray(g.vertices) for g in parts])
    f = np.concatenate([np.asarray(g.faces) + o for g, o in zip(parts, offs)])
    return parts, v, f


def audit(parts, f, rem, out):
    import trimesh
    fo = np.cumsum([0] + [len(g.faces) for g in parts])
    kept, removed = [], []
    for k, g in enumerate(parts):
        m = ~rem[fo[k]:fo[k + 1]]
        if m.any():
            kept.append(g.submesh([np.nonzero(m)[0]], append=True, repair=False))
        if (~m).any():
            removed.append(g.submesh([np.nonzero(~m)[0]], append=True, repair=False))
    red = trimesh.visual.material.PBRMaterial(baseColorFactor=[230, 20, 20, 255], metallicFactor=0.0, roughnessFactor=0.9)
    for g in removed:
        g.visual = trimesh.visual.TextureVisuals(material=red, uv=np.zeros((len(g.vertices), 2)))
    trimesh.Scene(kept + removed).export(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('items', nargs='+')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    res = {}
    for it in a.items:
        label, path = it.split('=', 1)
        parts, v, f = load(path)
        area = MC.tri_areas(v, f)
        _, keepA = MC.analyse(__import__('trimesh').Trimesh(v, f, process=False))
        remA = ~keepA
        slab, info = MC.slab_faces(v, f)
        remB = slab
        remAB = remA | slab
        remC = (remA & ~MC.footprint_inside(v, f)) | slab                 # вариант 3: A только для граней ЗА следом корпуса + B
        remE = MC.slab_rule_e(v, f, remA)                                  # правка E = D + «пыль»
        remD = MC.slab_pieces(v, f, remA) | slab                           # вариант 3б: куски A, выступающие из-под предмета, целиком + B
        none = np.ones(len(f), dtype=bool)
        r = {'tris': int(len(f)), 'area': round(float(area.sum()), 4)}
        for name, rem in (('A_куски', remA), ('B_нормали', remB), ('A+B', remAB), ('C_вариант3', remC), ('D_куски_целиком', remD), ('E', remE)):
            r[name] = {'удалено_треуг': int(rem.sum()), 'доля_площади': round(float(area[rem].sum() / area.sum()), 3), 'пятна_опоры': MC.floor_contacts(v, f, ~rem)}
        r['пятна_опоры_до'] = MC.floor_contacts(v, f, none)
        r['B_только_новое_площадь'] = round(float(area[remB & ~remA].sum() / area.sum()), 3)
        r['B_группы'] = info.get('groups')
        res[label] = r
        audit(parts, f, remB, os.path.join(a.out, f'{label}.B.audit.glb'))
        audit(parts, f, remAB, os.path.join(a.out, f'{label}.AB.audit.glb'))
        audit(parts, f, remC, os.path.join(a.out, f'{label}.C.audit.glb'))
        audit(parts, f, remD, os.path.join(a.out, f'{label}.D.audit.glb'))
        audit(parts, f, remE, os.path.join(a.out, f'{label}.E.audit.glb'))
        print(label, json.dumps({k: r[k] for k in r if k != 'B_группы'}, ensure_ascii=False), flush=True)
    json.dump(res, open(os.path.join(a.out, 'slab-probe.json'), 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
