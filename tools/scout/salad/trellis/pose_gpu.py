#!/usr/bin/env python3
"""GPU-бэкенд этапа 04 «камера по фото» (T-185/1, решение директора 22.11: шаги А и Б). Тот же алгоритм, что в `pose_fit.py` на numpy/cv2, но две самые дорогие части — на torch:
  А. силуэт `splat_mask` (проекция облака вершин → маска n×n): проекция в float64 по тем же формулам, маска — целочисленный scatter, замыкание 3×3 — max-pool (то же, что cv2.MORPH_CLOSE с границей
     «вне кадра не мешает»): маска совпадает с numpy побитно (IoU, доли miss/extra — целые счёты); Нелдер–Мид остаётся scipy на CPU, поэтому путь поиска тот же;
  Б. кадр для ПОИСКА `render_persp(..., search=True)` (кромки в `edge_score`/`refine_by_edges`): та же логика «дальние первыми по средней глубине граней, ближние поверх» — z-буфер по рангу грани
     (scatter amax) вместо цикла `cv2.fillConvexPoly` по 400+ тыс. граней в Python (≈1 с на кадр); барицентры → UV/нормаль/cos — те же формулы, что в numpy-хвосте `render_persp`.
Чистовой кадр (`render_persp(geo, cam, px)` без `search`) и `write_stages` остаются на cv2 — файлы для этапа 06 при той же камере не меняются.
Покрытие грани пикселем: центр пикселя внутри треугольника, расширенного на `RASTER_EPS` px (cv2 рисует рёбра линией и тем самым чуть «толще» геометрической границы; число подобрано сверкой с cv2 на
реальных формах, `rules/camera-check.json` его не трогает) + пиксели округлённых вершин (даже субпиксельная грань красит ≥ 1 пиксель, как у cv2).
Устройство: 'cpu' (проверка алгоритма без видеокарты) или 'cuda'. Зависит только от torch и numpy."""
from __future__ import annotations

import numpy as np
import torch

RASTER_EPS = 0.5          # расширение треугольника, px (подобрано сверкой с cv2.fillConvexPoly)
SHIFT = 4                 # субпиксель, как у cv2-варианта (pose_fit.SHIFT)
CAPS = (4, 8, 16, 32, 64, 128)      # грани крупнее 128 px по стороне — по одной (их единицы)
CHUNK = 6_000_000         # кандидатов «грань × пиксель окна» за раз


class Backend:
    def __init__(self, device: str = 'cpu'):
        self.dev = torch.device(device)
        self._pts = None          # (исходный массив, тензор): держим ссылку на массив, чтобы адрес не переиспользовался
        self._gc = None           # (геометрия-источник, тензоры)

    # ——— общее ———
    def _t(self, a, dtype=torch.float64):
        return torch.as_tensor(np.ascontiguousarray(a), dtype=dtype, device=self.dev)

    def _points(self, P: np.ndarray) -> torch.Tensor:
        if self._pts is None or self._pts[0] is not P:
            self._pts = (P, self._t(P))
        return self._pts[1]

    def _basis(self, cam: dict):
        import pose_fit as PF
        C, right, up, fwd = PF.cam_basis(cam['az'], cam['el'], cam['d'])
        return self._t(C), self._t(right), self._t(up), self._t(fwd)

    # ——— А. силуэт ———
    def splat_mask(self, P: np.ndarray, cam: dict, n: int) -> np.ndarray:
        t = self._points(P)
        C, right, up, fwd = self._basis(cam)
        rel = t - C
        Z = rel @ fwd
        Zs = torch.clamp(Z, min=1e-6)
        x = cam['cx'] + cam['f'] * (rel @ right) / Zs
        y = cam['cy'] - cam['f'] * (rel @ up) / Zs
        xi = torch.floor(x * n).to(torch.int64)
        yi = torch.floor(y * n).to(torch.int64)
        ins = (Z > 1e-3) & (xi >= 0) & (xi < n) & (yi >= 0) & (yi < n)
        m = torch.zeros(n * n, dtype=torch.bool, device=self.dev)
        m[yi[ins] * n + xi[ins]] = True
        m = m.view(1, 1, n, n)
        dil = torch.nn.functional.max_pool2d(m.to(torch.float32), 3, 1, 1) > 0                 # граница при расширении — «пусто»
        ero = ~(torch.nn.functional.max_pool2d((~dil).to(torch.float32), 3, 1, 1) > 0)         # граница при сжатии — «занято» (как cv2: +inf)
        return ero.view(n, n).cpu().numpy()

    # ——— Б. кадр для поиска ———
    def _geometry(self, geo: dict) -> dict:
        if self._gc is None or self._gc[0] is not geo:
            self._gc = (geo, {'V': self._t(geo['V']), 'F': torch.as_tensor(np.ascontiguousarray(geo['F']), dtype=torch.int64, device=self.dev),
                              'N': self._t(geo['N']), 'UV': self._t(geo['UV'])})
        return self._gc[1]

    def _ids(self, sx, sy, Z, F, n: int, eps: float) -> torch.Tensor:
        dev = self.dev
        nf = F.shape[0]
        zf = Z[F].mean(1)
        order = torch.argsort(-zf, stable=True)                                    # дальние первыми; ближе = позже = выше ранг
        rank = torch.empty_like(order)
        rank[order] = torch.arange(nf, device=dev)
        k = float(1 << SHIFT)
        pts = torch.round(torch.stack([sx[F], sy[F]], -1) * k - 0.5 * k) / k      # узлы решётки; центр пикселя (i, j) = (i, j)
        a, b, c = pts[:, 0], pts[:, 1], pts[:, 2]
        px, py = pts[..., 0], pts[..., 1]
        x0r, x1r = torch.floor(px.min(1).values - eps), torch.ceil(px.max(1).values + eps)
        y0r, y1r = torch.floor(py.min(1).values - eps), torch.ceil(py.max(1).values + eps)
        keep = (x1r >= 0) & (x0r <= n - 1) & (y1r >= 0) & (y0r <= n - 1)
        x0, x1 = x0r.clamp(0, n - 1), x1r.clamp(0, n - 1)
        y0, y1 = y0r.clamp(0, n - 1), y1r.clamp(0, n - 1)
        side = torch.maximum(x1 - x0, y1 - y0).to(torch.int64) + 1
        ab, bc, ca = b - a, c - b, a - c
        area2 = ab[:, 0] * (c - a)[:, 1] - ab[:, 1] * (c - a)[:, 0]
        sgn = torch.where(area2 >= 0, 1.0, -1.0).to(torch.float64)
        live = keep & (area2.abs() > 1e-9)
        lens = [torch.clamp(torch.sqrt((e ** 2).sum(1)), min=1e-9) for e in (ab, bc, ca)]
        best = torch.full((n * n,), -1, dtype=torch.int64, device=dev)
        lo = 0
        for cap in CAPS:
            sel = torch.nonzero(live & (side > lo) & (side <= cap)).flatten()
            lo = cap
            if sel.numel() == 0:
                continue
            ar = torch.arange(cap, device=dev, dtype=torch.float64)
            dx = ar.repeat(cap)                                                    # cap² смещений окна
            dy = ar.repeat_interleave(cap)
            step = max(1, CHUNK // (cap * cap))
            for s in range(0, sel.numel(), step):
                ii = sel[s:s + step]
                X = x0[ii][:, None] + dx[None, :]
                Y = y0[ii][:, None] + dy[None, :]
                ok = (X <= x1[ii][:, None]) & (Y <= y1[ii][:, None])
                inside = ok
                for (u, e, ln) in ((a, ab, lens[0]), (b, bc, lens[1]), (c, ca, lens[2])):
                    ex, ey = e[ii][:, 0:1], e[ii][:, 1:2]
                    cr = (ex * (Y - u[ii][:, 1:2]) - ey * (X - u[ii][:, 0:1])) * sgn[ii][:, None] / ln[ii][:, None]
                    inside = inside & (cr >= -eps)
                idx = (Y.to(torch.int64) * n + X.to(torch.int64))[inside]
                rk = rank[ii][:, None].expand_as(X)[inside]
                best.scatter_reduce_(0, idx, rk, 'amax', include_self=True)
        for i in torch.nonzero(live & (side > CAPS[-1])).flatten().tolist():       # крупные грани: окно целиком, по одной
            xs_ = torch.arange(int(x0[i]), int(x1[i]) + 1, device=dev, dtype=torch.float64)
            ys_ = torch.arange(int(y0[i]), int(y1[i]) + 1, device=dev, dtype=torch.float64)
            Y, X = torch.meshgrid(ys_, xs_, indexing='ij')
            inside = torch.ones_like(X, dtype=torch.bool)
            for (u, e, ln) in ((a, ab, lens[0]), (b, bc, lens[1]), (c, ca, lens[2])):
                cr = (e[i, 0] * (Y - u[i, 1]) - e[i, 1] * (X - u[i, 0])) * sgn[i] / ln[i]
                inside = inside & (cr >= -eps)
            idx = (Y.to(torch.int64) * n + X.to(torch.int64))[inside]
            best.scatter_reduce_(0, idx, torch.full_like(idx, int(rank[i])), 'amax', include_self=True)
        for j in range(3):                                                         # пиксели вершин: даже вырожденная/субпиксельная грань красит ≥ 1 пиксель (cv2 рисует рёбра линией)
            vx, vy = torch.round(pts[:, j, 0]).to(torch.int64), torch.round(pts[:, j, 1]).to(torch.int64)
            ok = (vx >= 0) & (vx < n) & (vy >= 0) & (vy < n)
            best.scatter_reduce_(0, (vy * n + vx)[ok], rank[ok], 'amax', include_self=True)
        return torch.where(best >= 0, order[best.clamp(min=0)], torch.full_like(best, -1)).view(n, n)

    def render(self, geo: dict, cam: dict, n: int, eps: float | None = None) -> dict:
        """Те же поля, что у `pose_fit.render_persp`: ids, mask, uv, normal, cos, depth, px_len (numpy)."""
        g = self._geometry(geo)
        V, F, N, UV = g['V'], g['F'], g['N'], g['UV']
        C0, right, up, fwd = self._basis(cam)
        rel = V - C0
        Z = rel @ fwd
        Zs = torch.clamp(Z, min=1e-6)
        x = cam['cx'] + cam['f'] * (rel @ right) / Zs
        y = cam['cy'] - cam['f'] * (rel @ up) / Zs
        sx, sy = x * n, y * n
        ids = self._ids(sx, sy, Z, F, n, RASTER_EPS if eps is None else eps)
        mask = ids >= 0
        ys, xs = torch.nonzero(mask, as_tuple=True)
        f = ids[ys, xs]
        a, b, c = F[f, 0], F[f, 1], F[f, 2]
        A_, B_, C_ = (torch.stack([sx[i], sy[i]], 1) for i in (a, b, c))
        p = torch.stack([xs.to(torch.float64) + 0.5, ys.to(torch.float64) + 0.5], 1)
        den = (B_[:, 0] - A_[:, 0]) * (C_[:, 1] - A_[:, 1]) - (B_[:, 1] - A_[:, 1]) * (C_[:, 0] - A_[:, 0])
        den = torch.where(den.abs() < 1e-12, torch.full_like(den, 1e-12), den)
        wa = ((B_[:, 0] - p[:, 0]) * (C_[:, 1] - p[:, 1]) - (B_[:, 1] - p[:, 1]) * (C_[:, 0] - p[:, 0])) / den
        wb = ((C_[:, 0] - p[:, 0]) * (A_[:, 1] - p[:, 1]) - (C_[:, 1] - p[:, 1]) * (A_[:, 0] - p[:, 0])) / den
        wc = 1.0 - wa - wb
        wa, wb, wc = (torch.clamp(w, 0.0, 1.0) for w in (wa, wb, wc))
        qa, qb, qc = wa / torch.clamp(Z[a], min=1e-6), wb / torch.clamp(Z[b], min=1e-6), wc / torch.clamp(Z[c], min=1e-6)
        s = torch.clamp(qa + qb + qc, min=1e-12)
        la, lb, lc = qa / s, qb / s, qc / s
        zpix = 1.0 / s
        u = la * UV[a, 0] + lb * UV[b, 0] + lc * UV[c, 0]
        v = la * UV[a, 1] + lb * UV[b, 1] + lc * UV[c, 1]
        nw = la[:, None] * N[a] + lb[:, None] * N[b] + lc[:, None] * N[c]
        nw = nw / torch.clamp(torch.linalg.norm(nw, dim=1, keepdim=True), min=1e-12)
        Pw = la[:, None] * V[a] + lb[:, None] * V[b] + lc[:, None] * V[c]
        vv = C0 - Pw
        vv = vv / torch.clamp(torch.linalg.norm(vv, dim=1, keepdim=True), min=1e-12)
        dot = (nw * vv).sum(1)
        cosv = dot.abs()
        nf_ = nw * torch.where(dot[:, None] < 0, -1.0, 1.0)
        f32 = torch.float32
        uv = torch.zeros((n, n, 2), dtype=f32, device=self.dev)
        uv[ys, xs, 0] = u.to(f32)
        uv[ys, xs, 1] = (1.0 - v).to(f32)
        ncam = torch.zeros((n, n, 3), dtype=f32, device=self.dev)
        ncam[ys, xs] = torch.stack([nf_ @ right, nf_ @ up, -(nf_ @ fwd)], 1).to(f32)
        cos = torch.zeros((n, n), dtype=f32, device=self.dev)
        cos[ys, xs] = cosv.to(f32)
        depth = torch.zeros((n, n), dtype=f32, device=self.dev)
        depth[ys, xs] = zpix.to(f32)
        zp = zpix.cpu().numpy()
        px_len = float(np.median(zp) / (cam['f'] * n)) if len(zp) else 0.0
        return {'ids': ids.to(torch.int32).cpu().numpy(), 'mask': mask.cpu().numpy(), 'uv': uv.cpu().numpy(), 'normal': ncam.cpu().numpy(), 'cos': cos.cpu().numpy(),
                'depth': depth.cpu().numpy(), 'px_len': px_len}
