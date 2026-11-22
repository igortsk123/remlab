#!/usr/bin/env python3
"""Сведение шва «фото | заливка» на текстуре (T-196/1/1, П1.136; ответ советника §4б: `~/remlab-logs/codex/a-world-1122.md`).
Цель — «краска одним слоем»: на границе фото-текселей (этап 06) и заливки (этап 07) нет каймы, скачка оттенка и гладкой полосы рядом с фактурой.
Чистые функции над растром развёртки `Tex` (tex_fill.py): ввода-вывода нет, tex_fill не импортируется (его вызывает). Расстояния — по графу граней меша в мм поверхности
(склеенные вершины `Tex.W`; шов развёртки — не разрыв), не по соседству в атласе. Размер предмета в мм (`size_mm`) — от вызывающего (кадр = нормированный размер предмета).
Порядок (советник): ① доверие к фото-текселю 0..1 (карта этапа 6; нет — запасное от границы известного) → ② тон широкой полосы заливки по материальной зоне (плавное поле сдвига,
чужая зона не трогается) → ③ узкая полоса: выравнивание контраста фактуры заливки под фото + плавный переход на сомнительных краевых тексел фото → ④ мерка шва по парам точек.
Числа — только из `rules/paint-fill.json` → `seam`."""
from __future__ import annotations

import numpy as np


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _graph(tx):
    """Граф склеенных вершин меша: рёбра без дублей, вес = длина ребра (кадр предмета); кэш на `tx`."""
    g = getattr(tx, '_seam_graph', None)
    if g is None:
        from scipy.sparse import coo_matrix
        FW = tx.FW
        e = np.concatenate([FW[:, [0, 1]], FW[:, [1, 2]], FW[:, [2, 0]]])
        e = np.sort(e[e[:, 0] != e[:, 1]], axis=1)
        n = int(FW.max()) + 1
        _, ix = np.unique(e[:, 0].astype(np.int64) * n + e[:, 1], return_index=True)
        e = e[ix]
        w = np.linalg.norm(tx.PW[e[:, 0]] - tx.PW[e[:, 1]], axis=1)
        g = coo_matrix((np.concatenate([w, w]), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(n, n)).tocsr()
        tx._seam_graph = g
    return g


def panel_zone(tx, crease_deg: float, smooth_iters: int = 3, min_faces: int = 30) -> np.ndarray:
    """Зона тексела = материальная часть × ПАНЕЛЬ. Панель — область граней, нормаль которых (сглаженная по соседям `smooth_iters` раз, шум сетки не рвёт панель) отличается от
    нормали затравки не больше crease_deg: излом больше — другая панель (у корпусной мебели другая панель — другой свет на фото, стык не равняем). Рост области — по смежности граней
    (склеенные вершины), затравка — первая неразобранная грань; обрывки < min_faces вливаются в соседа с наибольшей общей границей. Номера — по занятым текселям; кэш на `tx`."""
    key_ = (crease_deg, smooth_iters, min_faces)
    z = getattr(tx, '_seam_zone', None)
    if z is not None and getattr(tx, '_seam_zone_key', None) == key_:
        return z
    from scipy.sparse import coo_matrix
    F, FW = tx.F, tx.FW
    nf = len(F)
    ew = np.concatenate([FW[:, [0, 1]], FW[:, [1, 2]], FW[:, [2, 0]]])
    fi = np.concatenate([np.arange(nf)] * 3)
    ok = ew[:, 0] != ew[:, 1]
    ew, fi = np.sort(ew[ok], axis=1), fi[ok]
    key = ew[:, 0].astype(np.int64) * (int(FW.max()) + 1) + ew[:, 1]
    o = np.argsort(key, kind='stable')
    key, fi = key[o], fi[o]
    same = key[1:] == key[:-1]
    a, b = fi[:-1][same], fi[1:][same]
    keep = (a != b) & (tx.part_f[a] == tx.part_f[b])                # материальная часть — граница панели всегда
    a, b = a[keep], b[keep]
    A = coo_matrix((np.ones(2 * len(a)), (np.concatenate([a, b]), np.concatenate([b, a]))), shape=(nf, nf)).tocsr()
    A.sum_duplicates()
    nrm = tx.fnorm.copy()
    for _ in range(max(int(smooth_iters), 0)):
        nrm = nrm + A @ nrm
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-30)[:, None]
    cos_t = float(np.cos(np.radians(crease_deg)))
    ptr, ind = A.indptr, A.indices
    lab = np.full(nf, -1, np.int64)
    nxt, pos = 0, 0
    while True:
        while pos < nf and lab[pos] >= 0:
            pos += 1
        if pos >= nf:
            break
        lab[pos] = nxt
        m = nrm[pos]
        fr = np.array([pos])
        while len(fr):
            st, cnt = ptr[fr], ptr[fr + 1] - ptr[fr]
            if cnt.sum() == 0:
                break
            idx = np.repeat(st, cnt) + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))
            nb = np.unique(ind[idx])
            nb = nb[(lab[nb] < 0) & (nrm[nb] @ m >= cos_t)]
            lab[nb] = nxt
            fr = nb
        nxt += 1
    for _ in range(12):                                             # обрывки < min_faces вливаем в соседа с наибольшей общей границей (сосед тоже может быть обрывком — раунды)
        size = np.bincount(lab, minlength=nxt)
        small = size < min_faces
        ca, cb = lab[a], lab[b]
        d = ca != cb
        if not small.any() or not d.any():
            break
        ca, cb = ca[d], cb[d]
        x, y = np.concatenate([ca, cb]), np.concatenate([cb, ca])
        m = small[x]
        x, y = x[m], y[m]
        if not len(x):
            break
        pk, pc = np.unique(x * nxt + y, return_counts=True)
        r0, r1 = pk // nxt, pk % nxt
        o = np.lexsort((-pc, r0))
        r0, r1 = r0[o], r1[o]
        first = np.r_[True, r0[1:] != r0[:-1]]
        src, dst = r0[first], r1[first]
        tgt = np.arange(nxt)
        tgt[src] = dst
        mut = (tgt[tgt[src]] == src) & small[dst] & (src < dst)     # два обрывка выбрали друг друга — меньший номер остаётся корнем
        tgt[src[mut]] = src[mut]
        for _k in range(30):
            nt = tgt[tgt]
            if (nt == tgt).all():
                break
            tgt = nt
        lab = tgt[lab]
    _, lab = np.unique(lab, return_inverse=True)
    z = lab.reshape(-1)[tx.f].astype(np.int64)
    tx._seam_zone, tx._seam_zone_key = z, key_
    return z


def surface_dist(tx, src: np.ndarray, size_mm: float, cap_mm: float) -> np.ndarray:
    """Расстояние по поверхности (мм) от тексела до ближайшего из `src` (bool по занятым текселям); дальше cap_mm и недостижимое — inf; у самих src — 0."""
    from scipy.sparse.csgraph import dijkstra
    src = np.asarray(src, bool)
    out = np.full(len(tx.ti), np.inf)
    if not src.any():
        return out
    seeds = np.unique(tx.FW[np.unique(tx.f[src])].ravel())
    dv = dijkstra(_graph(tx), directed=False, indices=seeds, min_only=True, limit=cap_mm / size_mm)
    d = np.min(np.stack([dv[tx.FW[tx.f, k]] + np.linalg.norm(tx.Q - tx.PW[tx.FW[tx.f, k]], axis=1) for k in range(3)], axis=1), axis=1) * size_mm
    d[src] = 0.0
    d[d > cap_mm] = np.inf
    return d


def texel_mm(tx, size_mm: float) -> float:
    """Медианный шаг текселя по поверхности, мм (по площади граней в 3D и в текселях карты)."""
    P, F = tx.P, tx.F
    a3 = 0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)
    xy = tx.UV * tx.T
    au = 0.5 * np.abs((xy[F[:, 1], 0] - xy[F[:, 0], 0]) * (xy[F[:, 2], 1] - xy[F[:, 0], 1]) - (xy[F[:, 1], 1] - xy[F[:, 0], 1]) * (xy[F[:, 2], 0] - xy[F[:, 0], 0]))
    sel = (a3 > 1e-14) & (au > 1e-9)
    return float(np.median(np.sqrt(a3[sel] / au[sel])) * size_mm) if sel.any() else 1.0


def _mad_sigma(v) -> float:
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if len(v) else 0.0


def high_pass(tx, L: np.ndarray, mask: np.ndarray, sigma_px: float) -> np.ndarray:
    """Яркость минус её размытие ВНУТРИ маски (нормировка по весу; чужая сторона шва в размытие не входит): → по занятым текселям; вне маски — 0."""
    from scipy.ndimage import gaussian_filter
    T = tx.T
    img = np.zeros(T * T)
    w = np.zeros(T * T)
    img[tx.ti[mask]] = L[mask]
    w[tx.ti[mask]] = 1.0
    num = gaussian_filter(img.reshape(T, T), sigma_px, mode='nearest')
    den = gaussian_filter(w.reshape(T, T), sigma_px, mode='nearest')
    base = (num / np.maximum(den, 1e-9)).reshape(-1)[tx.ti]
    return np.where(mask, L - base, 0.0)


def photo_weight(conf: np.ndarray | None, known: np.ndarray, s_in0: np.ndarray, c: dict) -> np.ndarray:
    """① Доверие к фото-текселю → вес фото 0..1 (1 = довериться целиком). Карта этапа 6 `conf` — как есть; нет — запасное: от границы известного (край фото ненадёжен)."""
    cf = np.where(known, np.clip(conf, 0.0, 1.0), 0.0) if conf is not None else np.where(known, np.clip(s_in0 / max(c['edge_mm'], 1e-6), 0.0, 1.0), 0.0)
    return np.where(known, smoothstep((cf - c['conf_min']) / max(c['conf_full'] - c['conf_min'], 1e-6)), 0.0)


def _cell_means(tx, zone: np.ndarray, lab: np.ndarray, idx: np.ndarray, cell: float, min_cell: int) -> tuple:
    """Средние Lab по ячейкам поверхности (ячейка = зона × куб cell): → (зона (m,), центр (m,3), среднее Lab (m,3)) только для ячеек с ≥ min_cell текселей."""
    keys = np.column_stack([zone[idx], np.floor(tx.Q[idx] / cell).astype(np.int64)])
    uk, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    m = len(uk)
    cnt = np.bincount(inv, minlength=m).astype(np.float64)
    ctr = np.stack([np.bincount(inv, weights=tx.Q[idx, k], minlength=m) for k in range(3)], 1) / np.maximum(cnt, 1.0)[:, None]
    mean = np.stack([np.bincount(inv, weights=lab[idx, k], minlength=m) for k in range(3)], 1) / np.maximum(cnt, 1.0)[:, None]
    v = cnt >= min_cell
    return uk[v, 0], ctr[v], mean[v]


def _idw(kd, vals: np.ndarray, pts: np.ndarray, reach: float, eps: float) -> tuple:
    """Обратно-расстояние по ≤4 ближайшим ячейкам в пределах reach → (значение (n,3), есть опора (n,))."""
    kq = min(4, len(vals))
    dist, ix = kd.query(pts, k=kq, distance_upper_bound=reach)
    dist, ix = dist.reshape(len(pts), -1), ix.reshape(len(pts), -1)
    okn = np.isfinite(dist)
    w = np.where(okn, 1.0 / (dist + eps), 0.0)
    num = (vals[np.where(okn, ix, 0)] * w[..., None]).sum(axis=1)
    den = w.sum(axis=1)
    return num / np.maximum(den, 1e-12)[:, None], den > 0


def tone_field(tx, zone: np.ndarray, lab: np.ndarray, solid: np.ndarray, fillpure: np.ndarray, s_in: np.ndarray, s_out: np.ndarray, c: dict, size_mm: float) -> tuple:
    """② Поле сдвига Lab для заливки: у границы — (среднее фото − среднее заливки) по ячейкам поверхности ОДНОЙ материальной зоны (часть), по узкой полосе probe_mm с каждой
    стороны (ячейки сторон считаются отдельно и сводятся IDW, граница ячеек не мешает); вглубь заливки — затухание exp(−s/tone_decay_mm). Чужая зона и конструктивный стык материалов
    поле не пересекает (зона без общей границы с фото сдвига не получает). → (сдвиг (n,3), отчёт по зонам)."""
    from scipy.spatial import cKDTree
    n = len(lab)
    delta = np.zeros((n, 3))
    rep = {}
    ph = np.nonzero(solid & (s_in <= c['probe_mm']))[0]
    fl = np.nonzero(fillpure & (s_out <= c['probe_mm']))[0]
    tgt = np.nonzero(fillpure & (s_out <= c['tone_decay_mm'] * 3.0))[0]
    if len(ph) < c['min_cell'] or len(fl) < c['min_cell'] or not len(tgt):
        return delta, rep
    cell, reach = c['cell_mm'] / size_mm, c['reach_mm'] / size_mm
    zp, cp, mp = _cell_means(tx, zone, lab, ph, cell, c['min_cell'])
    zf, cf, mf = _cell_means(tx, zone, lab, fl, cell, c['min_cell'])
    lim = np.asarray(c['tone_max'], float)
    for p in np.unique(zone[tgt]):
        ap, af = zp == p, zf == p
        if not ap.any() or not af.any():
            continue
        tz = tgt[zone[tgt] == p]
        eps = 0.25 * cell
        vp, okp = _idw(cKDTree(cp[ap]), mp[ap], tx.Q[tz], reach, eps)
        vf, okf = _idw(cKDTree(cf[af]), mf[af], tx.Q[tz], reach, eps)
        zmed = np.median(mp[ap], axis=0) - np.median(mf[af], axis=0)
        fld = np.where((okp & okf)[:, None], vp - vf, zmed)
        delta[tz] = np.clip(fld, -lim, lim) * np.exp(-s_out[tz] / c['tone_decay_mm'])[:, None]
        rep[int(p)] = {'cells_photo': int(ap.sum()), 'cells_fill': int(af.sum()), 'median_shift_Lab': [round(float(x), 2) for x in np.clip(zmed, -lim, lim)]}
    return delta, rep


def contrast_gain(tx, zone: np.ndarray, lab: np.ndarray, solid: np.ndarray, fillpure: np.ndarray, s_in: np.ndarray, s_out: np.ndarray, c: dict, size_mm: float, tmm: float) -> tuple:
    """③а Контраст фактуры: у границы σ высоких частот яркости заливки приводится к σ фото (по зоне; g зажат в [gmin, gmax], плоская заливка не оживляется), затухает вглубь
    заливки exp(−s/contrast_decay_mm) — убирает «гладкую полосу рядом с фактурой» и «грубую рядом с гладкой». → (добавка к L (n,), отчёт по зонам)."""
    sig = max(c['hi_sigma_mm'] / max(tmm, 1e-6), 1.0)
    L = lab[:, 0]
    hp = high_pass(tx, L, solid, sig)
    hf = high_pass(tx, L, fillpure, sig)
    add = np.zeros(len(L))
    rep = {}
    stp, stf = solid & (s_in <= c['probe_mm']), fillpure & (s_out <= c['probe_mm'])
    for p in np.unique(zone[fillpure & np.isfinite(s_out)]):
        a, b = stp & (zone == p), stf & (zone == p)
        if a.sum() < c['min_cell'] or b.sum() < c['min_cell']:
            continue
        sp, sf = _mad_sigma(hp[a]), _mad_sigma(hf[b])
        if sf < c['contrast_floor'] or sp < 1e-6:
            rep[int(p)] = {'sigma_photo': round(sp, 3), 'sigma_fill': round(sf, 3), 'gain': 1.0}
            continue
        g = float(np.clip(sp / sf, c['contrast_gmin'], c['contrast_gmax']))
        z = fillpure & (zone == p) & np.isfinite(s_out)
        add[z] = (g - 1.0) * hf[z] * np.exp(-s_out[z] / c['contrast_decay_mm'])
        rep[int(p)] = {'sigma_photo': round(sp, 3), 'sigma_fill': round(sf, 3), 'gain': round(g, 3)}
    return add, rep


def nearest_fill(tx, lab: np.ndarray, src: np.ndarray, tgt: np.ndarray, reach_mm: float, size_mm: float) -> tuple:
    """Для текселей tgt — цвет ближайшего (в 3D, та же зона) тексела из src: чем заменить сомнительное фото. → (lab (len(tgt),3), найден (len(tgt),))."""
    from scipy.spatial import cKDTree
    out = np.zeros((len(tgt), 3))
    found = np.zeros(len(tgt), bool)
    for p in np.unique(tx.part[tgt]):
        s = np.nonzero(src & (tx.part == p))[0]
        t = np.nonzero(tx.part[tgt] == p)[0]
        if not len(s) or not len(t):
            continue
        d, j = cKDTree(tx.Q[s]).query(tx.Q[tgt[t]], k=1, distance_upper_bound=reach_mm / size_mm)
        ok = np.isfinite(d)
        out[t[ok]] = lab[s[j[ok]]]
        found[t[ok]] = True
    return out, found


def seam_metric(tx, zone: np.ndarray, lab_full: np.ndarray, lab_mip: np.ndarray, solid: np.ndarray, s_in: np.ndarray, s_out: np.ndarray, c: dict, size_mm: float, tmm: float, de2000) -> dict:
    """④ Мерка шва «не видно»: пары точек по обе стороны границы фото|заливка в одной зоне и на одной поверхности (нормали cos ≥ pair_cos), в пределах pair_mm от границы (граница ищется по
    смежности на меше). Цвет пары — среднее 5 ближайших текселей своей стороны (небольшое размытие), на текстуре ПОСЛЕ mip1 (lab_mip). → ΔE00 медиана/p95, доля и длина (мм) плохого
    шва (ΔE00 > de_bad), отношение контраста фактуры заливка/фото у границы (lab_full, до mip)."""
    from scipy.spatial import cKDTree
    pm = c['pair_mm']
    fl = np.nonzero(~solid & (s_out <= pm))[0]
    ph = np.nonzero(solid & (s_in <= pm))[0]
    res = {'pairs': 0, 'dE00_median': None, 'dE00_p95': None, 'bad_share_pct': None, 'bad_len_mm': None, 'boundary_len_mm': None, 'contrast_ratio': None}
    if len(fl) < 5 or len(ph) < 5:
        return res
    kp, kf = cKDTree(tx.Q[ph]), cKDTree(tx.Q[fl])
    d, j = kp.query(tx.Q[fl], k=1, distance_upper_bound=2.0 * pm / size_mm)
    ok = np.isfinite(d)
    jj = np.where(ok, j, 0)
    ok &= (zone[fl] == zone[ph[jj]]) & ((tx.N[fl] * tx.N[ph[jj]]).sum(axis=1) >= c['pair_cos'])
    if ok.sum() < 5:
        return res

    def smooth(kd, idx, lab, pts):
        _, nn = kd.query(tx.Q[pts], k=min(5, len(idx)))
        return lab[idx[np.asarray(nn).reshape(len(pts), -1)]].mean(axis=1)
    lf = smooth(kf, fl, lab_mip, fl[ok])
    lp = smooth(kp, ph, lab_mip, ph[jj[ok]])
    de = de2000(lf, lp)
    bad = de > c['de_bad']
    blen = float(ok.sum()) * tmm
    res.update({'pairs': int(ok.sum()), 'dE00_median': round(float(np.median(de)), 3), 'dE00_p95': round(float(np.percentile(de, 95)), 3), 'bad_share_pct': round(100.0 * float(bad.mean()), 2),
                'bad_len_mm': round(float(bad.mean()) * blen, 1), 'boundary_len_mm': round(blen, 1)})
    sig = max(c['hi_sigma_mm'] / max(tmm, 1e-6), 1.0)
    hp, hf = high_pass(tx, lab_full[:, 0], solid, sig), high_pass(tx, lab_full[:, 0], ~solid, sig)
    sp, sf = _mad_sigma(hp[ph]), _mad_sigma(hf[fl])
    res['contrast_ratio'] = round(sf / sp, 3) if sp > 1e-6 else None
    return res


def mip1_lab(tx, rgb: np.ndarray, rgb2lab) -> np.ndarray:
    """Lab текселей после одного mip-уровня (среднее 2×2 по растру, как у KTX2/mip на сайте) — по занятым текселям."""
    T = tx.T
    a = np.asarray(rgb, np.float64)[..., :3]
    if T % 2:
        return rgb2lab(np.asarray(rgb)[..., :3].reshape(-1, 3)[tx.ti].astype(np.uint8))
    m = a.reshape(T // 2, 2, T // 2, 2, 3).mean(axis=(1, 3))
    up = np.repeat(np.repeat(m, 2, axis=0), 2, axis=1)
    return rgb2lab(np.clip(np.rint(up.reshape(-1, 3)[tx.ti]), 0, 255).astype(np.uint8))


def blend_seam(tx, out_lab: np.ndarray, photo_lab: np.ndarray, keep0: np.ndarray, conf: np.ndarray | None, skip: np.ndarray, c: dict, size_mm: float) -> dict:
    """Один растр: ① вес фото по доверию → ② сдвиг тона заливки → ③ контраст фактуры + плавный переход на сомнительных краевых текселях фото.
    out_lab (n,3) — результат заливки (у фото-текселей = фото); photo_lab — Lab фото; keep0 — известное и покрашенное (защита k0); skip — зоны без перекраски (не трогаем вовсе).
    → {'lab' (n,3), 'keep' (n,) bool: текселы, которые остаются 1:1 фото, 'solid', 's_in', 's_out', 'report'}. Середина фото (вес 1) не меняется ни на единицу."""
    n = len(out_lab)
    cap = max(c['tone_decay_mm'] * 3.0, c['reach_mm'], c['probe_mm']) + 5.0
    k0 = keep0 & ~skip
    s0 = surface_dist(tx, ~k0, size_mm, c['edge_mm'] * 2.0 + 1.0) if conf is None else np.zeros(n)
    w = photo_weight(conf, k0, s0, c)
    solid = k0 & (w >= 1.0 - 1e-9)
    demoted = k0 & ~solid
    fillpure = ~keep0 & ~skip
    zone = panel_zone(tx, c['crease_deg'], c['normal_smooth_iters'], c['min_panel_faces'])
    s_out = surface_dist(tx, solid, size_mm, cap)
    s_in = surface_dist(tx, ~solid, size_mm, cap)
    tmm = texel_mm(tx, size_mm)
    lab = out_lab.copy()
    rep = {'demoted_texels': int(demoted.sum()), 'solid_texels': int(solid.sum()), 'texel_mm': round(tmm, 3)}
    if fillpure.any() and solid.any():
        dl, rep['tone'] = tone_field(tx, zone, lab, solid, fillpure, s_in, s_out, c, size_mm)
        lab[fillpure] += dl[fillpure]
        add, rep['contrast'] = contrast_gain(tx, zone, lab, solid, fillpure, s_in, s_out, c, size_mm, tmm)
        lab[fillpure, 0] += add[fillpure]
    if demoted.any():
        idx = np.nonzero(demoted)[0]
        prox, found = nearest_fill(tx, lab, fillpure, idx, c['reach_mm'], size_mm)
        wd = w[idx][:, None]
        lab[idx] = np.where(found[:, None], wd * photo_lab[idx] + (1.0 - wd) * prox, photo_lab[idx])
        rep['demoted_without_fill'] = int((~found).sum())
        keep = solid.copy()
        keep[idx[~found]] = True                                   # заливки рядом нет — фото остаётся
    else:
        keep = solid
    rep['zones'] = int(len(np.unique(zone)))
    return {'lab': lab, 'keep': keep, 'solid': solid, 'zone': zone, 's_in': s_in, 's_out': s_out, 'tmm': tmm, 'report': rep}


def atlas_with_gutter(tx, rgb_n: np.ndarray, gutter: int = 8) -> np.ndarray:
    """Растр T×T uint8 из цветов занятых текселей; пустое у островов — цвет ближайшего занятого (как желоб итоговой текстуры), чтобы mip не темнел на краях."""
    from scipy.ndimage import distance_transform_edt
    T = tx.T
    img = np.zeros((T * T, 3), np.uint8)
    img[tx.ti] = rgb_n
    img = img.reshape(T, T, 3)
    occ = np.zeros(T * T, bool)
    occ[tx.ti] = True
    occ = occ.reshape(T, T)
    dist, (iy, ix) = distance_transform_edt(~occ, return_indices=True)
    g = (~occ) & (dist <= gutter)
    img[g] = img[iy[g], ix[g]]
    return img
