#!/usr/bin/env python3
"""Части меша по кадрам облёта: области SAM2 на каждом кадре → общие части на гранях голосованием (paint-photo-fill-01, этап 3, T-20261120-169).

ЗАЧЕМ. Цвет и материал красим ЧАСТЯМИ (ножки, столешница, каркас, обивка, стекло). Геометрия `material_parts.py` умеет только «ножки / не ножки»;
SAM2 (Apache) обводит области на картинке любого вида — но на одном кадре область не знает граней, а на разных кадрах одна часть получает разные номера.
Здесь — чистая математика без torch и Blender: ей на вход идут готовые карты областей кадров и видимость граней (`parts_orbit_blender.py`).

КАК. 1) `label_map` — маски кадра → карта «номер области на пиксель» (мелкая область перекрывает крупную; слишком малые и слишком крупные — прочь).
2) `view_face_regions` — каждая видимая грань берёт область под своей проекцией. 3) `merge_regions` — области разных кадров, у которых совпали грани
(IoU по граням, видимым в обоих кадрах), сливаются в одну часть (union-find). 4) `vote_faces` — грань получает часть с наибольшим весом (вес — косинус угла к камере);
согласие кадров = доля веса победителя. 5) `fill_unlabeled` — грани, которых не видел ни один кадр, берут часть ближайших граней по сетке (не сквозь пустоту).
6) `small_parts_to_neighbours` — мелкие части (< доли граней) уходят в соседей. 7) `geometry_overlap` — сверка с ножками из `material_parts.py`: часть, которая на ≥ порога лежит на ножках, получает роль `legs`.
Пороги — в `data/flat3d/parts-sam-rules.json`; ID товаров в код не попадают.
"""
from __future__ import annotations

import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RULES_PATH = os.path.join(ROOT, "data", "flat3d", "parts-sam-rules.json")


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def duplicate_face_map(faces: np.ndarray) -> dict:
    """Карта «грань меша ↔ грань Blender» при парных дублях (T-20261126-163/3): TRELLIS отдаёт пары соседних граней с одним и тем же набором из 3 вершин
    (обычно обратная намотка = двусторонняя плёнка), Blender при импорте GLB снимает лишнюю из пары, и число граней сходится только после снятия дублей.
    Дубль — грань, чей отсортированный набор вершин уже был у грани с меньшим номером; остаётся ПЕРВАЯ из группы. Учтённой считается группа из подряд идущих номеров
    (порядок оставшихся граней тогда один и тот же, какую бы из пары ни снял Blender); дубль не в ряд с предыдущим членом группы — `nonconsecutive` (не учтён, этап откажет).
    Нет дублей → {"n_dup": 0, "nonconsecutive": 0, "keep": None, "rep": None} (тождественная карта, прежний путь без изменений).
    keep — маска оставляемых граней меша (длина = граней меша); rep[i] — номер грани в МЕШЕ БЕЗ ДУБЛЕЙ (= грань Blender) для i-й грани меша (дубль → номер её пары)."""
    f = np.asarray(faces)
    n = len(f)
    if n < 2:
        return {"n_dup": 0, "nonconsecutive": 0, "bad_groups": 0, "keep": None, "rep": None}
    s = np.sort(f, axis=1)
    order = np.lexsort((s[:, 2], s[:, 1], s[:, 0]))                      # устойчивая: внутри группы номера граней по возрастанию
    ss = s[order]
    new = np.ones(n, dtype=bool)
    new[1:] = (ss[1:] != ss[:-1]).any(axis=1)
    n_dup = int(n - new.sum())
    if n_dup == 0:
        return {"n_dup": 0, "nonconsecutive": 0, "bad_groups": 0, "keep": None, "rep": None}
    gid = np.cumsum(new) - 1
    first_of_group = order[new][gid]
    first = np.empty(n, dtype=np.int64)
    first[order] = first_of_group
    keep = first == np.arange(n)
    pos = np.nonzero(~new)[0]                                             # позиции дублей в отсортированном порядке
    nonconsecutive = int((order[pos] != order[pos - 1] + 1).sum())
    # T-163/4: учтена только схема TRELLIS — группа РОВНО из двух граней с ОБРАТНОЙ намоткой (двусторонняя плёнка); группа из 3+ или пара с одной намоткой — `bad_groups` (этап откажет)
    parity = ((f[:, 0] > f[:, 1]).astype(np.int8) + (f[:, 0] > f[:, 2]) + (f[:, 1] > f[:, 2])) % 2   # чётность перестановки (a,b,c) относительно отсортированной = направление обхода
    size = np.bincount(gid)
    par_sum = np.bincount(gid, weights=parity[order].astype(np.float64))
    multi = size > 1
    bad_groups = int((multi & ((size != 2) | (par_sum != 1))).sum())
    newidx = np.cumsum(keep) - 1
    return {"n_dup": n_dup, "nonconsecutive": nonconsecutive, "bad_groups": bad_groups, "keep": keep, "rep": newidx[first]}


def face_fingerprint(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Отпечаток каждой грани, НЕ зависящий от поворота и сдвига (Blender вращает GLB из Y-вверх в Z-вверх): площадь, три длины рёбер по возрастанию,
    расстояние центра грани до центра масс поверхности (по площади). float32, форма (граней, 5). T-163/4: сверка порядка граней Blender ↔ меш."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    e = np.sort(np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], axis=1), axis=1)
    cent = (a + b + c) / 3.0
    tot = float(area.sum())
    com = (cent * area[:, None]).sum(axis=0) / tot if tot > 0 else cent.mean(axis=0)
    dist = np.linalg.norm(cent - com, axis=1)
    return np.concatenate([area[:, None], e, dist[:, None]], axis=1).astype(np.float32)


def fingerprint_match(fp_a: np.ndarray, fp_b: np.ndarray, rel: float = 1e-4, abs_len: float = 1e-6) -> dict:
    """Сверка отпечатков грань к грани (одинаковый порядок). Допуск каждой клетки = rel·значение + абсолютный: длины (рёбра, расстояние) — abs_len·диагональ;
    площадь — abs_len·диагональ·(наибольшее ребро грани) (у сливера площадь ≈ 0, а погрешность вершин float32 — нет). Диагональ — удвоенное макс. расстояние до центра масс.
    Замер T-163/4 на 5 реальных формах (в т.ч. с дублями): расхождение Blender ↔ меш 0 (побитно), сдвиг порядка на 1 грань ловится у 99,96 % граней; допуск — запас на неточные повороты/масштаб узлов.
    Число граней разное → ok=False. Возвращает {ok, n_bad, first_bad, max_rel}."""
    if fp_a.shape != fp_b.shape:
        return {"ok": False, "n_bad": -1, "first_bad": None, "max_rel": None, "why": f"форма {fp_a.shape} ≠ {fp_b.shape}"}
    a, b = fp_a.astype(np.float64), fp_b.astype(np.float64)
    diag = 2.0 * max(float(a[:, 4].max()), float(b[:, 4].max()), 1e-12)
    tol = np.full(a.shape, abs_len * diag)
    tol[:, 0] = abs_len * diag * np.maximum(a[:, 3], b[:, 3])
    diff = np.abs(a - b)
    bad = (diff > (tol + rel * np.maximum(np.abs(a), np.abs(b)))).any(axis=1)
    rel_err = (diff / np.maximum(np.maximum(np.abs(a), np.abs(b)), tol)).max(axis=1)
    return {"ok": not bool(bad.any()), "n_bad": int(bad.sum()), "first_bad": (int(np.argmax(bad)) if bad.any() else None), "max_rel": float(rel_err.max()) if len(rel_err) else 0.0}


def label_map(masks: list[np.ndarray], object_mask: np.ndarray, rules: dict) -> np.ndarray:
    """Маски кадра → карта областей (−1 — нет). Крупные рисуются первыми, мелкие поверх; считается только то, что внутри предмета (`object_mask`)."""
    area_obj = max(1, int(object_mask.sum()))
    lo, hi = rules["region"]["min_area_share"], rules["region"]["max_area_share"]
    keep = []
    for m in masks:
        mm = m & object_mask
        share = mm.sum() / area_obj
        if lo <= share <= hi:
            keep.append((int(mm.sum()), mm))
    keep.sort(key=lambda t: -t[0])
    out = np.full(object_mask.shape, -1, dtype=np.int32)
    for i, (_, mm) in enumerate(keep):
        out[mm] = i
    return out


def view_face_regions(lmap: np.ndarray, u: np.ndarray, v: np.ndarray, vis: np.ndarray) -> np.ndarray:
    """Область под проекцией каждой видимой грани (−1 — не видна или вне областей). u, v — пиксельные координаты центров граней."""
    h, w = lmap.shape
    out = np.full(len(u), -1, dtype=np.int32)
    ok = vis & (u >= 0) & (u < w) & (v >= 0) & (v < h)
    iu, iv = u[ok].astype(int), v[ok].astype(int)
    out[ok] = lmap[iv, iu]
    return out


class _DSU:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def merge_regions(view_regions: list[np.ndarray], view_vis: list[np.ndarray], rules: dict) -> tuple[list[dict[int, int]], int]:
    """Области кадров → общие части. Возвращает (на кадр: {номер области → номер части}, число частей). Пары с IoU по общим видимым граням ≥ порога сливаются."""
    from scipy import sparse

    nv = len(view_regions)
    nodes = []                                   # (кадр, область)
    rows, cols = [], []
    for i, reg in enumerate(view_regions):
        for r in np.unique(reg[reg >= 0]):
            k = len(nodes)
            nodes.append((i, int(r)))
            idx = np.nonzero(reg == r)[0]
            rows.extend([k] * len(idx))
            cols.extend(idx.tolist())
    n = len(nodes)
    if n == 0:
        return [dict() for _ in range(nv)], 0
    nf = len(view_regions[0])
    m = sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n, nf))
    vmat = sparse.csr_matrix(np.array(view_vis, dtype=np.float32))          # кадры × грани
    inter = (m @ m.T).tocoo()
    seen = np.asarray((m @ vmat.T).todense())                                # узел × кадр: сколько граней узла видно в кадре j
    dsu = _DSU(n)
    thr, min_f = rules["merge"]["iou"], rules["merge"]["min_faces"]
    for a, b, c in zip(inter.row, inter.col, inter.data):
        if a >= b or nodes[a][0] == nodes[b][0] or c < min_f:
            continue
        ia, ib = nodes[a][0], nodes[b][0]
        union = seen[a, ib] + seen[b, ia] - c
        if union > 0 and c / union >= thr:
            dsu.union(a, b)
    roots = {}
    per_view: list[dict[int, int]] = [dict() for _ in range(nv)]
    for k, (i, r) in enumerate(nodes):
        root = dsu.find(k)
        per_view[i][r] = roots.setdefault(root, len(roots))
    return per_view, len(roots)


def vote_faces(view_regions: list[np.ndarray], mapping: list[dict[int, int]], weights: list[np.ndarray], n_parts: int, with_acc: bool = False):
    """Часть на грань по весу кадров. Возвращает (часть −1/0.., согласие 0..1 — доля веса победителя от всего веса грани); with_acc — ещё и копилку голосов грань × сырая часть."""
    nf = len(view_regions[0])
    acc = np.zeros((nf, max(1, n_parts)), dtype=np.float32)
    for reg, mp, w in zip(view_regions, mapping, weights):
        for r, p in mp.items():
            sel = reg == r
            acc[sel, p] += w[sel]
    tot = acc.sum(axis=1)
    part = np.where(tot > 0, acc.argmax(axis=1), -1).astype(np.int32)
    agree = np.where(tot > 0, acc.max(axis=1) / np.maximum(tot, 1e-9), 0.0).astype(np.float32)
    return (part, agree, acc) if with_acc else (part, agree)


def final_agreement(acc: np.ndarray, raw_part: np.ndarray, final_part: np.ndarray) -> np.ndarray:
    """Согласие кадров относительно ИТОГОВЫХ частей: сырые части, склеенные в одну итоговую (мелкие слиты, номера сведены), голосуют вместе.
    Сырая часть → итоговая, на чьих гранях её вес больше; согласие грани = доля веса, поданная за итоговую часть этой грани."""
    nf, nraw = acc.shape
    tot = acc.sum(axis=1)
    lab = final_part >= 0
    nfin = int(final_part.max()) + 1 if lab.any() else 0
    raw_to_final = np.full(nraw, -1, dtype=np.int64)
    if nfin:
        w = np.zeros((nfin, nraw), dtype=np.float64)                         # вес сырой части на гранях каждой итоговой
        for f in range(nfin):
            w[f] = acc[final_part == f].sum(axis=0)
        has = w.sum(axis=0) > 0
        raw_to_final[has] = w[:, has].argmax(axis=0)
    out = np.zeros(nf, dtype=np.float32)
    for f in np.unique(raw_to_final[raw_to_final >= 0]):
        cols = np.nonzero(raw_to_final == f)[0]
        sel = (final_part == f) & (tot > 0)
        out[sel] = acc[sel][:, cols].sum(axis=1) / tot[sel]
    return out


def fill_nearest(part: np.ndarray, verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Грани, до которых не дотянулась заливка по соседству (отдельные острова: внутренности, не видные ни с одного ракурса) берут часть ближайшей по центру грани с частью."""
    from scipy.spatial import cKDTree

    todo = part < 0
    if not todo.any() or todo.all():
        return part
    c = verts[faces].mean(axis=1)
    _, idx = cKDTree(c[~todo]).query(c[todo])
    out = part.copy()
    out[todo] = part[~todo][idx]
    return out


def weld_adjacency(vertices: np.ndarray, faces: np.ndarray, decimals: int = 5):
    """Соседство граней по общим вершинам с совмещёнными по положению копиями (швы развёртки не рвут соседство). Разреженная матрица граней × граней."""
    from scipy import sparse

    key = np.round(vertices.astype(np.float64), decimals)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    wf = np.asarray(inv).reshape(-1)[faces]                                  # грани в сваренных индексах
    nf = len(faces)
    nvw = int(wf.max()) + 1
    vf = sparse.csr_matrix((np.ones(wf.size, dtype=np.float32), (wf.ravel(), np.repeat(np.arange(nf), 3))), shape=(nvw, nf))
    adj = (vf.T @ vf).tocsr()
    adj.setdiag(0)
    adj.eliminate_zeros()
    return adj


def fill_unlabeled(part: np.ndarray, adj, max_rounds: int = 200) -> np.ndarray:
    """Грани без части берут часть соседей (волной по сетке; несколько раундов, пока есть кому). Остались без соседей с частью — −1."""
    from scipy import sparse

    part = part.copy()
    nf = len(part)
    for _ in range(max_rounds):
        todo = part < 0
        if not todo.any() or not (~todo).any():
            break
        lab = np.nonzero(~todo)[0]
        onehot = sparse.csr_matrix((np.ones(len(lab), dtype=np.float32), (lab, part[lab])), shape=(nf, int(part.max()) + 1))
        votes = (adj @ onehot).tocsr()                                       # грань × часть: голоса соседей
        got = np.asarray(votes.max(axis=1).todense()).ravel() > 0
        sel = todo & got
        if not sel.any():
            break
        part[sel] = np.asarray(votes[sel].argmax(axis=1)).ravel()
    return part


def small_parts_to_neighbours(part: np.ndarray, adj, min_share: float) -> np.ndarray:
    """Часть меньше доли граней отдаётся самому частому соседу (по ребру/вершине); одинокая — остаётся."""
    part = part.copy()
    nf = max(1, int((part >= 0).sum()))
    changed = True
    while changed:
        changed = False
        ids, cnt = np.unique(part[part >= 0], return_counts=True)
        for p, c in sorted(zip(ids, cnt), key=lambda t: t[1]):
            if c / nf >= min_share:
                continue
            fs = np.nonzero(part == p)[0]
            nb = np.concatenate([adj[f].indices for f in fs]) if len(fs) else np.array([], dtype=int)
            lab = part[nb]
            lab = lab[(lab >= 0) & (lab != p)]
            if len(lab):
                part[fs] = np.bincount(lab).argmax()
                changed = True
                break
    return part


def renumber(part: np.ndarray) -> np.ndarray:
    """Номера частей подряд от 0, по убыванию числа граней."""
    ids, cnt = np.unique(part[part >= 0], return_counts=True)
    order = ids[np.argsort(-cnt, kind="stable")]
    out = np.full_like(part, -1)
    for new, old in enumerate(order):
        out[part == old] = new
    return out


def geometry_overlap(part: np.ndarray, legs: np.ndarray, rules: dict) -> dict:
    """Сверка с ножками геометрии: доля части на ножках → роль `legs`; согласие = IoU(объединение ножечных частей, маска геометрии)."""
    thr = rules["geometry"]["legs_overlap"]
    roles, legs_parts = {}, []
    for p in np.unique(part[part >= 0]):
        sel = part == p
        share = float((sel & legs).sum() / max(1, sel.sum()))
        roles[int(p)] = {"legs_share": round(share, 3), "role": "legs" if share >= thr and legs.any() else None}
        if roles[int(p)]["role"]:
            legs_parts.append(p)
    union = np.isin(part, legs_parts) if legs_parts else np.zeros_like(legs)
    iou = float((union & legs).sum() / max(1, (union | legs).sum())) if legs.any() or union.any() else None
    return {"roles": roles, "legs_iou": None if iou is None else round(iou, 3), "geometry_legs_faces": int(legs.sum())}


def colour_verdict(has_texture: bool, texture_std: float | None, rules: dict) -> tuple[bool, str]:
    """Годен ли вход по цвету. SAM2 на форме без цвета («глина») идёт за тенями и рвёт столешницу на клинья, а ножки — на отдельные части (T-169: стол, 16 частей, согласие кадров 0,49),
    поэтому вход без baseColor или с плоской текстурой — отказ этапа, а не «ноль частей»."""
    if not has_texture:
        return False, "вход без цвета (нет baseColor): SAM2 по теням рвёт части — нужен родной цвет TRELLIS.2 или покраска"
    lo = rules["check"]["input_min_texture_std"]
    if texture_std is None or texture_std < lo:
        return False, f"текстура входа плоская (разброс яркости {texture_std if texture_std is None else round(texture_std, 1)} < {lo}): цвета для частей нет"
    return True, "ok"


def quality(part: np.ndarray, agree: np.ndarray, seen_any: np.ndarray, rules: dict, linear_in_blob: float | None = None) -> dict:
    """Мерки этапа 3 для check.json: доля граней с частью, число частей, согласие кадров, доля граней, увиденных хотя бы одним кадром."""
    nf = len(part)
    lab = part >= 0
    ids, cnt = np.unique(part[lab], return_counts=True)
    seen_n = int(seen_any.sum())
    agree_seen = agree[seen_any & lab] if (seen_any & lab).any() else np.array([0.0])
    m = {
        "faces": nf,
        "faces_with_part_share": round(float(lab.mean()), 4),
        "faces_seen_by_views_share": round(seen_n / max(1, nf), 4),
        "n_parts": int(len(ids)),
        "part_face_shares": [round(float(c) / max(1, lab.sum()), 4) for c in cnt[np.argsort(-cnt)]],
        "frames_agreement_mean": round(float(agree_seen.mean()), 4),
        "frames_agreement_share_ge": round(float((agree_seen >= rules["check"]["agreement_face"]).mean()), 4),
    }
    ck = rules["check"]
    reasons = []
    if m["faces_with_part_share"] < ck["min_faces_with_part"]:
        reasons.append("мало граней с частью")
    if not (ck["min_parts"] <= m["n_parts"] <= ck["max_parts"]):
        reasons.append(f"число частей {m['n_parts']} вне {ck['min_parts']}–{ck['max_parts']}")
    if m["frames_agreement_mean"] < ck["min_agreement"]:
        reasons.append("кадры спорят о частях")
    if linear_in_blob is not None:
        m["linear_in_blob_part_share"] = linear_in_blob
        if linear_in_blob > ck["max_linear_in_blob"]:
            reasons.append("тонкие куски (ножки/стойки) остались в объёмной части")
    m["ok"] = not reasons
    m["reason"] = "; ".join(reasons) if reasons else "ok"
    return m


def run_vote(view_regions: list[np.ndarray], view_vis: list[np.ndarray], weights: list[np.ndarray], vertices: np.ndarray, faces: np.ndarray, rules: dict) -> dict:
    """Всё голосование разом: области кадров → части на гранях + мерки."""
    mapping, n_parts = merge_regions(view_regions, view_vis, rules)
    raw_part, agree, acc = vote_faces(view_regions, mapping, weights, n_parts, with_acc=True)
    seen_any = raw_part >= 0
    adj = weld_adjacency(vertices, faces)
    part = fill_unlabeled(raw_part, adj)
    part = fill_nearest(part, vertices, faces)
    part = small_parts_to_neighbours(part, adj, rules["region"]["min_part_face_share"])
    part = renumber(part)
    agree = final_agreement(acc, raw_part, part)                              # согласие — по итоговым частям, не по сырым номерам
    return {"part": part, "agree": agree, "seen_any": seen_any, "adj": adj, "n_parts_raw": n_parts, "acc": acc, "raw_part": raw_part}
