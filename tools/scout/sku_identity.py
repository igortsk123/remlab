#!/usr/bin/env python3
"""SKU-identity проверка финальных кадров — T4 truth-first. ПОКА ADVISORY, НЕ ворота.

Почему не ворота: порог берётся только из sku_bench.py, а базовый эмбеддер (CLIP) бенч
НЕ прошёл — same-series негативы неотделимы от positives (AUC 0.547, замер 08.08).
Инструмент печатает сходства и ранги, помогает глазам, и откажется гейтить, пока
sku-bench-report.json не покажет AUC ≥ 0.90 (тогда же появится калиброванный порог).

  --scene N [--cam C1]   кропы предметов из финала vs их карточки: сходство + ранг
                         среди same-series соседей (retrieval своего SKU)
  --cross N              C1 ↔ C2: один и тот же предмет в двух видах (кросс-вью
                         консистентность, рефери §34)
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES = os.path.expanduser('~/scout-scenes')
REPORT = os.path.join(HERE, 'sku-bench-report.json')
GATE_AUC = 0.90


def _bench_ok() -> tuple[bool, dict]:
    try:
        rep = json.load(open(REPORT))
    except (OSError, json.JSONDecodeError):
        return False, {}
    return rep.get('auc', 0) >= GATE_AUC, rep


def _embed(paths):
    from fastembed import ImageEmbedding
    model = ImageEmbedding('Qdrant/clip-ViT-B-32-vision')
    a = np.array(list(model.embed(paths)))
    return a / np.linalg.norm(a, axis=1, keepdims=True)


def _crops(n: int, cam: str):
    """Кропы предметов из финала: боксы — из карты painted.png (пиксель = id вклейки,
    id → роль в paint.json.ids) — те же боксы, которыми пользуется viz_qa."""
    from PIL import Image
    paint = json.load(open(f'{SCENES}/scene{n}-{cam}-paint.json'))
    ids = {int(k): v for k, v in paint.get('ids', {}).items()}
    final = Image.open(f'{SCENES}/scene{n}-{cam}-final.jpg').convert('RGB')
    mask = np.array(Image.open(f'{SCENES}/scene{n}-{cam}-painted.png').convert('L'))
    sx = final.size[0] / mask.shape[1]
    sy = final.size[1] / mask.shape[0]
    out = {}
    pasted = set(paint.get('pasted', []))
    for pid, role in ids.items():
        if pasted and role not in pasted:
            continue                      # роль рисует модель — кропать нечего
        ys, xs = np.where(mask == pid)   # painted.png хранит сырой id (×8 — у instances.png)
        if len(xs) < 400:                    # < ~20×20 px — мусор/не видно
            continue
        box = (int(xs.min() * sx), int(ys.min() * sy),
               int(xs.max() * sx), int(ys.max() * sy))
        out[role] = final.crop(box)
    return out


def scene(n: int, cam: str) -> None:
    ok, rep = _bench_ok()
    print(f"[advisory] эмбеддер бенч {'ПРОШЁЛ' if ok else 'НЕ прошёл'} "
          f"(AUC {rep.get('auc', '—')}, порог гейта {GATE_AUC}) — "
          f"{'порог применим' if ok else 'вердикты справочные, ворот нет'}")
    import tempfile
    crops = _crops(n, cam)
    if not crops:
        print('боксов в paint.json нет — нечего проверять')
        return
    # референсы: refs/<mid>-<eid>.jpg; связка роль→товар — из sets3.json
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    items = (sets[n - 1].get('items') or {}) if 0 < n <= len(sets) else {}
    refs = {}
    for role in crops:
        it = items.get(role) or {}
        mid, eid = it.get('mid'), it.get('eid')
        if mid and eid:
            for suffix in ('.jpg', '-up.jpg', '-cut.png'):
                p = os.path.join(HERE, 'refs', f'{mid}-{eid}{suffix}')
                if os.path.exists(p):
                    refs[role] = p
                    break
    tmp = tempfile.mkdtemp(prefix='sku-', dir=os.environ.get('TMPDIR', '/tmp'))
    crop_paths = {}
    for role, im in crops.items():
        q = os.path.join(tmp, f'{role}.jpg'.replace(' ', '_'))
        im.save(q, quality=92)
        crop_paths[role] = q
    roles = [r for r in crops if r in refs]
    if not roles:
        print(f'референсов в refs/ не найдено для сета {n} — только кропы, без сравнения')
        return
    E_crop = _embed([crop_paths[r] for r in roles])
    E_ref = _embed([refs[r] for r in roles])
    for i, r in enumerate(roles):
        sim = float(E_crop[i] @ E_ref[i])
        others = [float(E_crop[i] @ E_ref[j]) for j in range(len(roles)) if j != i]
        rank = 1 + sum(1 for o in others if o > sim)
        print(f'  {r:16} sim со своей карточкой {sim:.3f}, ранг среди рефов сета: {rank}')


def cross(n: int) -> None:
    _, rep = _bench_ok()
    print(f"[advisory] кросс-вью C1↔C2 (эмбеддер: {rep.get('embedder', 'clip')})")
    a, b = _crops(n, 'C1'), _crops(n, 'C2')
    common = sorted(set(a) & set(b))
    if not common:
        print('общих предметов в двух видах нет')
        return
    import tempfile
    tmp = tempfile.mkdtemp(prefix='skux-', dir=os.environ.get('TMPDIR', '/tmp'))
    pa, pb = [], []
    for r in common:
        qa = os.path.join(tmp, f'a_{r}.jpg'.replace(' ', '_'))
        qb = os.path.join(tmp, f'b_{r}.jpg'.replace(' ', '_'))
        a[r].save(qa, quality=92)
        b[r].save(qb, quality=92)
        pa.append(qa)
        pb.append(qb)
    EA, EB = _embed(pa), _embed(pb)
    for i, r in enumerate(common):
        print(f'  {r:16} C1↔C2 sim {float(EA[i] @ EB[i]):.3f}')


if __name__ == '__main__':
    a = sys.argv
    if '--scene' in a:
        n = int(a[a.index('--scene') + 1])
        cam = a[a.index('--cam') + 1] if '--cam' in a else 'C1'
        scene(n, cam)
    elif '--cross' in a:
        cross(int(a[a.index('--cross') + 1]))
    else:
        print(__doc__)
