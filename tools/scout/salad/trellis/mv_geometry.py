"""Геометрия кадра MV-Adapter для сторожа покраски `tex_coverage.py` — малый общий модуль без тяжёлых зависимостей (только numpy).

ЗАЧЕМ (T-20261120-147/1). Сторож покрытия текстуры брал эти константы и функции из `worker_trellis.py` (2 831 строка воркера пробы TRELLIS.2 на Salad,
в `main` его нет). Тянуть весь воркер ради четырёх мелких функций — лишний код в `main`, поэтому нужное вынесено сюда БЕЗ изменения формул: тела
скопированы из `worker_trellis.py` (ветка trial/tex-fill, коммит 796427e7) дословно; когда воркер попадёт в `main`, он должен импортировать эти же функции
из этого модуля (одна копия, не две).

Что здесь:
- `MV_ORTHO`, `MV_AZ` — ортографическая камера и азимуты видов апстрима MV-Adapter (`scripts/texture_i2tex.py`, source: external:github huanngzh/MV-Adapter, Apache-2.0);
- `rot_x`, `rot_y`, `to_cube` — кадр формы: поворот на yaw/pitch, центр габарита в ноль, наибольшая сторона = 0,99999 (как `preprocess_mesh` апстрима);
- `mv_ortho_uv` — куда ортографическая камера вида 0 кладёт точки куба, кадр [0, 1]².
Тест: `tests_mv_geometry.py` (CI, job `scout-selftest`/`planner` — см. `.github/workflows/ci.yml`)."""
from __future__ import annotations

MV_ORTHO = 1.1                  # сторона ортографической камеры апстрима (left/right/bottom/top = ±0,55)
MV_AZ = [x - 90 for x in [0, 90, 180, 270, 180, 180]]          # как в `scripts/texture_i2tex.py:118`; `TexturePipeline` вычитает ещё 90° и сама поворачивает форму (front_x_to_y) — вместе кадр тот же


def rot_y(deg: float):
    """Поворот вокруг вертикали Y (кадр сетки Pixal3D: Y вверх, лицом к камере +Z); кратные 90° — точные."""
    import numpy as np
    k = int(round(deg / 90.0)) if abs(deg / 90.0 - round(deg / 90.0)) < 1e-9 else None
    if k is not None:
        c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][k % 4]
    else:
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=np.float64)


def rot_x(deg: float):
    """Поворот вокруг горизонтальной оси X (наклон формы к камере/от неё); 0° — точная единица."""
    import numpy as np
    if deg == 0:
        return np.eye(3)
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=np.float64)


def to_cube(verts, yaw_deg: float = 0.0, pitch_deg: float = 0.0):
    """Вершины входного GLB (Y вверх) → кадр сетки: поворот на yaw, центр габарита в ноль, наибольшая сторона = 0,99999 (как `preprocess_mesh` апстрима, без его
    обмена осей). `pitch_deg` — наклон формы вокруг X (после поворота на yaw). Возвращает (p, center, scale, R)."""
    import numpy as np
    v = np.asarray(verts, dtype=np.float64)
    R = rot_x(pitch_deg) @ rot_y(yaw_deg)
    vr = v @ R.T
    lo, hi = vr.min(axis=0), vr.max(axis=0)
    c = (lo + hi) / 2.0
    ext = float((hi - lo).max())
    if not ext > 0:
        raise ValueError('форма вырождена: габарит нулевой')
    s = 0.99999 / ext
    return (vr - c) * s, c, s, R


def mv_ortho_uv(p):
    """Куда ортографическая камера вида 0 (азимут −90°: смотрит на сторону +Z формы, вверх +Y, вправо +X; ±0,55) кладёт точки куба; кадр [0, 1]²."""
    import numpy as np
    p = np.asarray(p, dtype=np.float64)
    return 0.5 + p[:, 0] / MV_ORTHO, 0.5 - p[:, 1] / MV_ORTHO
