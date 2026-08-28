#!/usr/bin/env python3
"""3d-orienter+flipper (ICML 2025) на CPU: GLB → каноническая ориентация (ADR-0131).

Запускается ИЗ ОТДЕЛЬНОГО venv (~/venvs/orienter — torch CPU; в scout-venv torch не ставим),
репозиторий — ~/igor/3d-orienter (клон github.com/cscarv/3d-orienter, патч cuda→cpu в DGCNN*).
Модели грузятся один раз на процесс, дальше ~5 с/меш.

Поворот НЕ восстанавливаем сравнением файлов: orient() мутирует вершины, поэтому матрицу
берём Кабшем между вершинами до и после (соответствие 1:1, решение точное). det=+1 проверяем.

  ~/venvs/orienter/bin/python orient_infer.py --list files.txt --out results.json
Формат результата: {путь: {"R": [[..]x3], "quat_wxyz": [...], "flip_prob": p,
                            "pset_size": n, "secs": t} | {"error": ...}}
"""
import argparse
import json
import os
import sys
import time

ORIENTER = os.path.expanduser(os.environ.get('ORIENTER_DIR', '~/igor/3d-orienter'))
sys.path.insert(0, ORIENTER)


def quat_wxyz(R) -> list[float]:
    """Матрица → кватернион (w,x,y,z), знак фиксирован w≥0 (q25: канонический вид)."""
    import numpy as np
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0:
        s = (t + 1.0) ** 0.5 * 2
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] >= R[1, 1] and R[0, 0] >= R[2, 2]:
        s = (1.0 + R[0, 0] - R[1, 1] - R[2, 2]) ** 0.5 * 2
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] >= R[2, 2]:
        s = (1.0 - R[0, 0] + R[1, 1] - R[2, 2]) ** 0.5 * 2
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = (1.0 - R[0, 0] - R[1, 1] + R[2, 2]) ** 0.5 * 2
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    q = [w, x, y, z]
    if q[0] < 0:
        q = [-v for v in q]
    n = sum(v * v for v in q) ** 0.5
    return [round(float(v / n), 8) for v in q]


def load_models():
    import argparse as ap

    import json5
    import torch
    from ml_models.orienter_model.DGCNNFlipper import DGCNNFlipper
    from ml_models.orienter_model.DGCNNOrienter import DGCNNOrienter
    from pl_models.FlipperTrainerModel import FlipperTrainerModel
    from pl_models.OrienterTrainerModel import OrienterTrainerModel

    specs = json5.load(open(os.path.join(ORIENTER, 'config/default/specs.json5')))
    specs['exp_dir'] = os.path.join(ORIENTER, 'config/default')
    idx = os.path.join(ORIENTER, 'data/sample_index.txt')
    common = dict(specs=specs, train_index_file_path=idx, val_index_file_path=idx,
                  inference_index_file_path=idx, preload=False, num_points_per_cloud=2000,
                  train_batch_size=48, val_batch_size=48, unlock_every_k_epochs=10, start_lr=1e-4)
    a = ap.Namespace(); a.k = 20; a.emb_dims = 1024; a.dropout = 0.5
    om = OrienterTrainerModel.load_from_checkpoint(
        os.path.join(ORIENTER, 'pretrained_ckpts/orienter.ckpt'), map_location='cpu',
        core_model=DGCNNOrienter(a, rotation_representation='procrustes'),
        train_loss_fn='octahedral_invariant', rotation_representation='6d', **common).model.eval()
    b = ap.Namespace(); b.k = 20; b.emb_dims = 1024; b.dropout = 0.5
    fm = FlipperTrainerModel.load_from_checkpoint(
        os.path.join(ORIENTER, 'pretrained_ckpts/flipper.ckpt'), map_location='cpu',
        core_model=DGCNNFlipper(b, output_channels=24), confusion_matrices=False,
        up_flipper=False, **common).model.eval()
    flips = torch.load(os.path.join(ORIENTER, 'utils/24_cube_flips.pt')).cpu()
    return om, fm, flips


def infer(path: str, om, fm, flips) -> dict:
    import numpy as np
    import torch
    import trimesh
    from utils.inference_helpers import normalize_mesh, orient

    t0 = time.time()
    tm = trimesh.load(path, force='mesh')
    verts, faces = normalize_mesh(tm.vertices, tm.faces)
    mesh = trimesh.Trimesh(verts, faces)
    v0 = np.asarray(mesh.vertices).copy()

    feats = orient(mesh, om, num_candidates=20)          # мутирует mesh
    with torch.no_grad():
        logits = fm(feats)
    probs = torch.softmax(logits, dim=1).squeeze()
    top = int(torch.argmax(probs))
    ordered = torch.argsort(probs, descending=True)
    csum, pset = 0.0, 0
    for i in ordered:                                     # prediction set: кумулятив 0.5
        csum += float(probs[i]); pset += 1
        if csum >= 0.5:
            break
    Rf4 = np.eye(4); Rf4[:3, :3] = flips[top].numpy().T
    mesh.apply_transform(Rf4)
    v1 = np.asarray(mesh.vertices)

    # Кабш: точная матрица «сырой → канон» по соответствию вершин
    c0, c1 = v0 - v0.mean(0), v1 - v1.mean(0)
    U, _, Vt = np.linalg.svd(c0.T @ c1)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = (Vt.T @ np.diag([1.0, 1.0, d]) @ U.T)
    if abs(np.linalg.det(R) - 1.0) > 1e-3:
        return {'error': f'det={np.linalg.det(R):.3f}'}
    resid = float(np.abs(c1 - c0 @ R.T).max())
    return {'R': [[round(float(x), 8) for x in row] for row in R],
            'quat_wxyz': quat_wxyz(R), 'flip_prob': round(float(probs[top]), 4),
            'pset_size': pset, 'kabsch_resid': round(resid, 6),
            'secs': round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', required=True, help='файл со списком путей GLB/OBJ')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    os.chdir(ORIENTER)   # upstream грузит utils/24_cube_flips.pt относительным путём
    om, fm, flips = load_models()
    out = {}
    for p in [ln.strip() for ln in open(args.list) if ln.strip()]:
        try:
            out[p] = infer(p, om, fm, flips)
        except Exception as e:  # noqa: BLE001 — один битый меш не валит пакет
            out[p] = {'error': str(e)[:200]}
        print(f'{os.path.basename(p)}: {json.dumps(out[p], ensure_ascii=False)[:100]}', flush=True)
    tmp = args.out + '.tmp'
    json.dump(out, open(tmp, 'w'), ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)


if __name__ == '__main__':
    main()
