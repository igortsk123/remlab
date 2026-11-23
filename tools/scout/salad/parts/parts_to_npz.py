#!/usr/bin/env python3
"""Части PartLLM (этап 03, T-198/1) → вход этапа 07: `<корень частей>/<товар>/03-parts/parts.npz` (ключ `part`, int32, ОДИН массив на все грани GLB в порядке геометрий —
ровно то, что читает `tex_fill.parts_from_npz`) + `parts.json` (номер части → имя PartLLM, доля граней; поля `role` нет — роли этапа 3 не придумываем). Выбор источника зон для 07 —
флаг `zones_from` в rules/paint-fill.json: `parts` (по умолчанию, при наличии годного parts.npz) | `panels` (только панели формы, как до T-198).
Здесь только то, что знает PartLLM-часть: перевод выхода воркера (`parts_trial.py`: faces.npy = метка части на грань в порядке граней входного glb) и проверка «число граней совпало».

  python parts_to_npz.py convert --items items.json --src <папка с <товар>/faces.npy> --out <корень частей> [--prompt-set fine]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.abspath(os.path.join(HERE, '..', '..', 'rules', 'paint-fill.json'))
MODES = ('parts', 'panels')


def zones_mode(rules_path: str | None = None) -> str:
    """`zones_from` из rules/paint-fill.json; нет ключа — `parts`; чужое значение — ValueError (молча не угадываем)."""
    with open(rules_path or RULES, encoding='utf-8') as f:
        v = json.load(f).get('zones_from', 'parts')
    if v not in MODES:
        raise ValueError(f'rules/paint-fill.json: zones_from={v!r}, ожидалось одно из {MODES}')
    return v


def glb_face_count(path: str) -> int:
    """Число граней ВСЕХ геометрий GLB подряд (как считает `parts_from_npz`)."""
    import trimesh
    sc = trimesh.load(path, process=False)
    geoms = list(sc.geometry.values()) if hasattr(sc, 'geometry') else [sc]
    return int(sum(len(g.faces) for g in geoms))


def convert(src_dir: str, glb: str, out_dir: str, prompt_set: str = 'fine') -> dict:
    """Один товар: `<src_dir>/faces.npy` (+ meta.json) → `<out_dir>/parts.npz`, `parts.json`. → {ok, reason, n_faces, n_parts, ...}. Число граней не совпало — файлов нет, ok=False."""
    import numpy as np
    fp = os.path.join(src_dir, 'faces.npy')
    if not os.path.isfile(fp):
        return {'ok': False, 'reason': 'нет faces.npy (PartLLM не отдал части)'}
    lab = np.load(fp).astype(np.int64)
    n = glb_face_count(glb)
    if lab.shape != (n,):
        return {'ok': False, 'reason': f'меток {lab.shape[0] if lab.ndim else lab.size}, граней в GLB {n} — части другого меша', 'n_faces': n}
    names = []
    mp = os.path.join(src_dir, 'meta.json')
    if os.path.isfile(mp):
        names = (json.load(open(mp, encoding='utf-8')) or {}).get('names') or []
    ids, cnt = np.unique(lab[lab >= 0], return_counts=True)
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, 'parts.npz'), part=lab.astype(np.int32))
    parts = [{'id': int(i), 'name': names[int(i)] if 0 <= int(i) < len(names) else '', 'face_share': round(float(c) / n, 4)} for i, c in zip(ids, cnt)]
    doc = {'source': 'partllm', 'prompt_set': prompt_set, 'n_faces': n, 'share_unlabeled': round(float((lab < 0).mean()), 4), 'parts': parts}
    json.dump(doc, open(os.path.join(out_dir, 'parts.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {'ok': True, 'reason': f'{len(parts)} частей', 'n_faces': n, 'n_parts': len(parts), 'share_unlabeled': doc['share_unlabeled']}


def pick_parts(parts_root: str, sku: str, face_glb: str, mode: str) -> tuple:
    """Что кладём в задание 07 по товару: (путь parts.npz | None, строка-причина). `panels` → None; `parts`: файл есть и граней столько же, сколько в `face_glb` → путь,
    иначе None + причина (07 не падает, идёт по панелям формы — отдельная строка в зонах, не молчком)."""
    if mode == 'panels':
        return None, 'zones_from=panels'
    npz = os.path.join(parts_root, sku, '03-parts', 'parts.npz')
    if not os.path.isfile(npz):
        return None, 'panels: нет parts.npz'
    import numpy as np
    n_lab = int(np.load(npz)['part'].shape[0])
    n = glb_face_count(face_glb)
    if n_lab != n:
        return None, f'panels: parts.npz граней {n_lab}, в GLB {n} — части другого меша'
    return npz, 'parts'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['convert'])
    ap.add_argument('--items', required=True, help='JSON [{"sid","path"}] — GLB формы (как у parts_trial)')
    ap.add_argument('--src', required=True, help='папка выхода parts_trial: <товар>/faces.npy')
    ap.add_argument('--out', required=True, help='корень частей: <товар>/03-parts/parts.npz')
    ap.add_argument('--prompt-set', default='fine')
    a = ap.parse_args()
    items = json.load(open(a.items, encoding='utf-8'))
    res, bad = {}, 0
    os.makedirs(a.out, exist_ok=True)
    for it in items:
        r = convert(os.path.join(a.src, str(it['sid'])), os.path.expanduser(it['path']), os.path.join(a.out, str(it['sid']), '03-parts'), a.prompt_set)
        res[str(it['sid'])] = r
        bad += 0 if r['ok'] else 1
        print(('ok  ' if r['ok'] else 'ОТКАЗ'), it['sid'], r['reason'])
    json.dump(res, open(os.path.join(a.out, 'convert-report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'итого: {len(items) - bad} из {len(items)}, отказов {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
