#!/usr/bin/env python3
"""T-173/3 Ш2б ⑤: DINOv2 как ТРЕТИЙ голос «перёд или зад» (тень, вместе с силуэтом, цветом и геометрией фасада из pose_rank.orientation_*).
Идея (отчёт советника 21.11.2026): признаки самосупервизорной модели видят, ТОТ ли это вид предмета (фасад с ручками, а не спинка), даже когда контур и цвет молчат.
Что считает: вектор DINOv2 (CLS и средний по патчам) для (а) фото предмета на нейтральном фоне, обрезанного по маске, (б) рендера с текстурой с выбранной позы, (в) рендера с позы yaw+180°,
обрезанных так же (по маске, квадрат с полем). Сходство = косинус. Голос «за» выбранную позу — если у неё сходство больше на ≥ rules.dino.gap, «против» — если меньше на ≥ gap, иначе «—».
Разделение: ЧИСТОЕ ядро (`dino_vote`, `crop_masked`, `cosine`) — numpy, тестируется без torch; `embed`/`dino_sims` — torch + transformers (venv-dino, `HF_HOME=~/remlab-logs/t173-1121/hf`, офлайн),
в основной конвейер подключается отдельным шагом (`rank.dino` кладёт `cue_dino.py` по pose.json), потому что основной подбор идёт в окружении без torch.
Пороги — `rules/pose-rank.json` → dino; пробные, не подгонялись."""
from __future__ import annotations

import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def crop_masked(img: np.ndarray, mask: np.ndarray, size: int = 518, pad_frac: float = 0.08, bg: int = 235) -> np.ndarray | None:
    """Обрезка кадра (uint8 RGB) по маске предмета в квадрат с полем pad_frac, фон вне маски — нейтральный серый bg, масштаб до size. Пустая маска → None.
    Обрезка по маске делает сравнение независимым от того, насколько предмет занимает кадр у фото и у рендера (масштаб камеры разный)."""
    import cv2
    m = np.asarray(mask, bool)
    if int(m.sum()) < 64:
        return None
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = int(max(y1 - y0, x1 - x0) * (1 + 2 * pad_frac)) + 1
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    canvas = np.full((side, side, 3), bg, np.uint8)
    sy0, sx0 = cy - side // 2, cx - side // 2
    ya, yb, xa, xb = max(sy0, 0), min(sy0 + side, m.shape[0]), max(sx0, 0), min(sx0 + side, m.shape[1])
    sub = np.where(m[ya:yb, xa:xb, None], np.asarray(img, np.uint8)[ya:yb, xa:xb, :3], bg).astype(np.uint8)
    canvas[ya - sy0:yb - sy0, xa - sx0:xb - sx0] = sub
    return cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, np.float64).ravel(), np.asarray(b, np.float64).ravel()
    return float(a @ b / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12))


def dino_vote(sim_pick: float | None, sim_flip: float | None, gap: float) -> str:
    """Голос по сходству с фото: «за» выбранную позу, «против» (ближе к фото вид +180°), «—» — разница меньше gap, «нет» — не посчитано."""
    if sim_pick is None or sim_flip is None:
        return 'нет'
    d = sim_pick - sim_flip
    return 'за' if d >= gap else ('против' if d <= -gap else '—')


# ---------- torch (venv-dino; офлайн) ----------

_MODEL: dict = {}


def _load(name: str = 'facebook/dinov2-base'):
    if 'm' not in _MODEL:
        os.environ.setdefault('HF_HOME', os.path.expanduser('~/remlab-logs/t173-1121/hf'))
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        import torch
        from transformers import AutoModel
        torch.set_num_threads(1)
        _MODEL['m'] = AutoModel.from_pretrained(name).eval()      # в офлайн-кэше только config.json и веса: препроцессор (preprocessor_config.json) не нужен — см. prep()
    return _MODEL['m']


IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], np.float32)


def prep(img: np.ndarray) -> np.ndarray:
    """Кадр uint8 RGB (H, W кратны 14, у нас 518×518) → float32 [1, 3, H, W], нормализация ImageNet — как у штатного процессора DINOv2 без обрезки по центру."""
    x = (np.asarray(img, np.float32)[..., :3] / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


def embed(img: np.ndarray) -> dict:
    """Вектор DINOv2 кадра: {'cls': (768,), 'patch_mean': (768,)}."""
    import torch
    model = _load()
    with torch.no_grad():
        h = model(pixel_values=torch.from_numpy(prep(img))).last_hidden_state[0]
    return {'cls': h[0].numpy(), 'patch_mean': h[1:].mean(0).numpy()}


def dino_sims(PF, geo: dict, cam_pick: dict, cam_flip: dict, photo: np.ndarray, alpha: np.ndarray, cv: dict, tex, n: int = 768) -> dict | None:
    """Сходство (косинус CLS и средних патчей) фото с рендером выбранной позы и с рендером +180°. Нет текстуры → None (рендер без текстуры к фото не сравнить)."""
    if tex is None:
        return None
    import pose_rank as PR
    ia, ph, Sa, A_fr = PR._common(PF, geo, cam_pick, photo, alpha, cv, tex, n)
    ib, _, Sb, _ = PR._common(PF, geo, cam_flip, photo, alpha, cv, tex, n)
    cp, ca, cb = crop_masked(ph, A_fr), crop_masked(ia, Sa), crop_masked(ib, Sb)
    if cp is None or ca is None or cb is None:
        return None
    ep, ea, eb = embed(cp), embed(ca), embed(cb)
    return {k: {'pick': round(cosine(ep[k], ea[k]), 4), 'flip': round(cosine(ep[k], eb[k]), 4)} for k in ('cls', 'patch_mean')}
