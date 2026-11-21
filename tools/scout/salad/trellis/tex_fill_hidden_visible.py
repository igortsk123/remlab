#!/usr/bin/env python3
"""Мерка заливки невидимого БЕЗ настоящего зада — «скрытое видимое» (T-164, Codex+директор 21.11).
Правды о заду одной фотографии нет, но есть настоящее фото ВИДИМОЙ части: прячем её связный кусок (оставляя 15/30/50 % известных текселей части), заливаем А/Б/C и сравниваем залитое с настоящим фото на спрятанном.
  python3 tex_fill_hidden_visible.py [--keep 0.15,0.3,0.5] [--sources stat,trellis,trellis_relief] [--draft-dir <папка родных GLB TRELLIS.2>] [--draft-pattern '{base}-1024-42-0.glb'] [--dirs 2] [--cfg '{"part_class": {"0": "body"}}'] <выход> <корень этапа 6: <root>/<sku>/06-visible> <sku> [<sku> …]
Для каждого товара берётся ЧАСТЬ с наибольшим числом известных текселей (части — `03-parts/parts.npz`, нет — по геометрии); спрятанный кусок — срез по случайному направлению в 3D (связный, один «сектор»), --dirs направлений на товар.
Метрики на спрятанном (ХУЖЕ = больше, кроме band_ratio, где цель 1):
  • dE_low — ΔE00 низких частот (средняя яркость/цвет в окне ≈ σ_hi) между залитым и настоящим — цвет и крупная форма;
  • band_ratio — энергия полосы (МАД-σ DoG яркости в масштабе поверхности, как в C) залитого / настоящего; 1 — фактура той же силы, <1 — слишком гладко, >1 — шум/крошка;
  • spec_dist — расстояние радиальных спектров мощности (окна 32×32 целиком внутри спрятанного; L1 по log-мощности) — «та же зернистость и масштаб»;
  • ori_dist — расстояние гистограмм ориентаций градиентов (8 корзин по удвоенному углу, веса — модуль) — «те же направления» (стёжка, волокна).
Строка на (товар, направление, доля, источник) — `<выход>/hidden.jsonl`; свод (среднее по источникам и долям, попарно «C против stat»: победы/ничьи/поражения по метрикам, ничья < 5 % отн.) — `<выход>/summary.txt`.
Пиксель-MSE главной мерой не берём: допустимая фактура может иметь другую фазу. Бесплатно (процессор) — только под heavy-slot."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'stablegen'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np  # noqa: E402
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402

METRICS = ('dE_low', 'band_ratio', 'spec_dist', 'ori_dist')


def hide_sector(Q: np.ndarray, cand: np.ndarray, keep: float, rng: np.random.RandomState) -> np.ndarray:
    """Связный кусок: срез по случайному направлению в 3D. Q (n,3) точки текселей; cand (n,) bool — из каких прятать; keep — доля cand, что остаётся известной. → bool (n,) спрятанные."""
    d = rng.normal(size=3)
    d /= np.linalg.norm(d)
    proj = Q @ d
    pc = proj[cand]
    thr = np.quantile(pc, keep)                     # keep доли с наименьшей проекцией остаются, остальное — спрятано
    return cand & (proj > thr)


def band_pass(lum: np.ndarray, mask: np.ndarray, s_lo: float, s_hi: float) -> np.ndarray:
    """Полоса яркости (DoG) по маске — как в C (`TF._band`)."""
    return TF._band(lum, mask, s_lo, s_hi)[0]


def spec_signature(lum: np.ndarray, mask: np.ndarray, rng: np.random.RandomState, win: int = 32, n: int = 24):
    """Радиальный спектр мощности (log), усреднённый по окнам win×win целиком внутри mask (до n случайных окон, шаг win//2); нет окон → None."""
    H, W = lum.shape
    ii = mask.astype(np.int64).cumsum(0).cumsum(1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    ys, xs = np.mgrid[0:H - win + 1:win // 2, 0:W - win + 1:win // 2]
    full = (ii[ys + win, xs + win] - ii[ys, xs + win] - ii[ys + win, xs] + ii[ys, xs]) == win * win
    cand = np.stack([ys[full], xs[full]], 1)
    if len(cand) == 0:
        return None
    pick = cand[rng.choice(len(cand), min(n, len(cand)), replace=False)]
    w2 = np.hanning(win)[:, None] * np.hanning(win)[None, :]
    fy, fx = np.meshgrid(np.fft.fftfreq(win), np.fft.fftfreq(win), indexing='ij')
    rbin = np.minimum((np.hypot(fy, fx) * win).astype(int), win // 2 - 1)
    acc = np.zeros(win // 2)
    for y, x in pick:
        p = lum[y:y + win, x:x + win]
        P = np.abs(np.fft.fft2((p - p.mean()) * w2)) ** 2
        acc += np.bincount(rbin.ravel(), P.ravel(), minlength=win // 2)[:win // 2] / np.maximum(np.bincount(rbin.ravel(), minlength=win // 2)[:win // 2], 1)
    return np.log10(acc[1:] / len(pick) + 1e-6)


def orient_hist(lum: np.ndarray, mask: np.ndarray, bins: int = 8) -> np.ndarray:
    """Гистограмма ориентаций градиента яркости внутри mask (угол ×2 — направление без знака), вес — модуль; нормирована на 1."""
    from scipy.ndimage import binary_erosion, gaussian_filter
    sm = gaussian_filter(lum, 0.8)
    gy, gx = np.gradient(sm)
    m = binary_erosion(mask, iterations=2)
    ang = (np.arctan2(gy, gx) * 2.0) % (2 * np.pi)
    h = np.bincount((ang[m] / (2 * np.pi) * bins).astype(int) % bins, np.hypot(gx, gy)[m], minlength=bins)
    return h / max(h.sum(), 1e-12)


def metrics_hidden(lab_fill: np.ndarray, lab_true: np.ndarray, mask: np.ndarray, s_lo: float, s_hi: float, rng: np.random.RandomState) -> dict:
    """Метрики залитого против настоящего на mask (T×T bool); lab_* (T,T,3)."""
    out = {}
    bf = TF._blur_norm(lab_fill, mask, s_hi)[0]
    bt = TF._blur_norm(lab_true, mask, s_hi)[0]
    out['dE_low'] = float(np.mean(TC.de2000_v(bf[mask], bt[mask])))
    mf, mt = TF._mad_sigma(band_pass(lab_fill[..., 0], mask, s_lo, s_hi)[mask]), TF._mad_sigma(band_pass(lab_true[..., 0], mask, s_lo, s_hi)[mask])
    out['band_ratio'] = float(mf / max(mt, 1e-6))
    sd = int(rng.randint(0, 2 ** 31 - 1))                                           # одни и те же окна у залитого и настоящего
    sf, st = spec_signature(lab_fill[..., 0], mask, np.random.RandomState(sd)), spec_signature(lab_true[..., 0], mask, np.random.RandomState(sd))
    out['spec_dist'] = None if sf is None or st is None else float(np.mean(np.abs(sf - st)))
    out['ori_dist'] = float(0.5 * np.abs(orient_hist(lab_fill[..., 0], mask) - orient_hist(lab_true[..., 0], mask)).sum())
    return out


def run_item(root: str, sku: str, sources: list, keeps: list, ndirs: int, cfg0: dict, drafts: dict, seed: int = 7) -> list:
    """Одна форма: все (направление, доля, источник). → список записей."""
    vis = os.path.join(root, sku, '06-visible')
    geoms = TC.load_geoms(os.path.join(vis, 'visible.glb'))
    known = TF.load_known_png(vis)
    npz = os.path.join(root, sku, '03-parts', 'parts.npz')
    parts, _ = TF.parts_from_npz(npz, geoms) if os.path.exists(npz) else TF.parts_from_geometry(geoms)
    txs = [TF.Tex(g, np.asarray(g['V'], np.float64), TF._grid(g), parts[gi]) for gi, g in enumerate(geoms)]
    ids = sorted({int(p) for pp in parts for p in np.unique(pp)})
    cnt = {p: sum(int((kn.reshape(-1)[tx.ti] & (tx.part == p)).sum()) for kn, tx in zip(known, txs)) for p in ids}
    part = max(cnt, key=cnt.get)
    recs = []
    for di in range(ndirs):
        for keep in keeps:
            rng = np.random.RandomState(seed + 101 * di)
            Qall = np.concatenate([tx.Q for tx in txs])
            cand = np.concatenate([kn.reshape(-1)[tx.ti] & (tx.part == part) for kn, tx in zip(known, txs)])
            hid = hide_sector(Qall, cand, keep, rng)
            o = 0
            hidden, kn_h, geoms_h = [], [], []
            for gi, tx in enumerate(txs):
                h = np.zeros(tx.T * tx.T, bool)
                h[tx.ti[hid[o:o + len(tx.ti)]]] = True
                o += len(tx.ti)
                h = h.reshape(tx.T, tx.T)
                hidden.append(h)
                kn_h.append(known[gi] & ~h)
                tex = np.asarray(geoms[gi]['tex']).copy()
                tex[h] = 0                                          # спрятанное — «непокрашено»
                geoms_h.append(dict(geoms[gi], tex=tex))
            nh = int(sum(h.sum() for h in hidden))
            if nh < 400:
                continue
            for src in sources:
                cfg = dict({'erode_known': 0, 'source': src}, **cfg0)
                dr = None
                if src in ('trellis', 'trellis_relief'):
                    if drafts.get(sku) is None:
                        continue
                    dr = TF.draft_texels(geoms_h, drafts[sku], cfg)
                if src == 'trellis':
                    cfg.setdefault('draft_fallback', False)
                res = TF.fill(geoms_h, kn_h, parts, cfg=cfg, mirror=True, draft=dr)
                spac = float(np.median(np.concatenate([TF.texel_spacing(tx)[tx.part == part] for tx in txs])))
                R = TF.RULES['trellis_relief']
                s_lo = float(np.clip(R['band_lo'] / spac, R['sigma_lo_min'], R['sigma_lo_max']))
                s_hi = float(np.clip(R['band_hi'] / spac, 2.0 * s_lo, R['sigma_hi_max']))
                agg = {m: [] for m in METRICS}
                for gi, tx in enumerate(txs):
                    if hidden[gi].sum() < 100:
                        continue
                    mt = metrics_hidden(TF.rgb2lab(res['tex'][gi].reshape(-1, 3)).reshape(tx.T, tx.T, 3), TF.rgb2lab(np.asarray(geoms[gi]['tex']).reshape(-1, 3)).reshape(tx.T, tx.T, 3),
                                        hidden[gi], s_lo, s_hi, np.random.RandomState(seed))
                    for k, v in mt.items():
                        if v is not None:
                            agg[k].append((v, int(hidden[gi].sum())))
                rec = {'sku': sku, 'part': part, 'dir': di, 'keep': keep, 'source': src, 'hidden_texels': nh, 'sigma_lo_px': round(s_lo, 2), 'sigma_hi_px': round(s_hi, 2)}
                for k, v in agg.items():
                    rec[k] = None if not v else round(sum(a * w for a, w in v) / sum(w for _, w in v), 4)
                if src == 'trellis_relief':
                    rec['relief'] = {str(p): {k: x for k, x in v.items() if k in ('fallback', 'gain', 'outlier_pct', 'family', 'homog_std')} for p, v in res['report'].get('relief', {}).items()}
                    rec['relief_texels'] = res['report'].get('relief_texels', 0)
                    rec['relief_smooth_parts'] = res['report'].get('relief_smooth_parts')
                recs.append(rec)
    return recs


def _cost(m: str, v: float) -> float:
    return abs(np.log(max(v, 1e-6))) if m == 'band_ratio' else v


def summarize(recs: list) -> str:
    """Свод: среднее по (источник, доля); попарно «C против stat» по каждой метрике на одинаковых (товар, направление, доля): победы/ничьи/поражения (ничья — разница < 5 % отн.)."""
    lines = []
    srcs = sorted({r['source'] for r in recs})
    keeps = sorted({r['keep'] for r in recs})
    lines.append('Среднее по метрикам (dE_low, spec_dist, ori_dist — меньше лучше; band_ratio — ближе к 1):')
    for k in keeps:
        for s in srcs:
            rs = [r for r in recs if r['keep'] == k and r['source'] == s]
            if not rs:
                continue
            mean = lambda m: np.mean([r[m] for r in rs if r.get(m) is not None]) if any(r.get(m) is not None for r in rs) else float('nan')  # noqa: E731
            lines.append(f"  оставлено {int(k * 100):>2} % · {s:<15} n={len(rs):>3} · dE_low {mean('dE_low'):6.2f} · band_ratio {mean('band_ratio'):5.2f} · spec_dist {mean('spec_dist'):5.3f} · ori_dist {mean('ori_dist'):5.3f}")
    idx = {(r['sku'], r['dir'], r['keep'], r['source']): r for r in recs}
    for ch in [s for s in srcs if s != 'stat']:
        lines.append(f'Попарно {ch} против stat (победа = лучше на >5 % отн.):')
        for m in METRICS:
            w = t = l = 0
            for (sku, di, k, s), r in idx.items():
                if s != ch or (sku, di, k, 'stat') not in idx:
                    continue
                a, b = r.get(m), idx[(sku, di, k, 'stat')].get(m)
                if a is None or b is None:
                    continue
                ca, cb = _cost(m, a), _cost(m, b)
                if ca < cb * 0.95:
                    w += 1
                elif ca > cb * 1.05:
                    l += 1
                else:
                    t += 1
            lines.append(f'  {m:<11} побед {w} · ничьих {t} · поражений {l}')
    return '\n'.join(lines)


def main(argv: list) -> int:
    keeps, sources, draft_dir, draft_pat, ndirs, cfg0 = [0.15, 0.3, 0.5], ['stat', 'trellis', 'trellis_relief'], None, '{base}-1024-42-0.glb', 2, {}
    a = list(argv)
    while a and a[0].startswith('--'):
        k, v = a[0], a[1]
        if k == '--keep':
            keeps = [float(x) for x in v.split(',')]
        elif k == '--sources':
            sources = v.split(',')
        elif k == '--draft-dir':
            draft_dir = v
        elif k == '--draft-pattern':
            draft_pat = v
        elif k == '--dirs':
            ndirs = int(v)
        elif k == '--cfg':
            cfg0 = json.loads(v)
        else:
            print(__doc__)
            return 2
        a = a[2:]
    if len(a) < 3:
        print(__doc__)
        return 2
    out, root, skus = a[0], a[1], a[2:]
    os.makedirs(out, exist_ok=True)
    recs, bad = [], 0
    for sku in skus:
        try:
            drafts = {}
            if draft_dir:
                dg = os.path.join(draft_dir, draft_pat.format(base=sku))
                drafts[sku] = TC.load_geoms(dg) if os.path.exists(dg) else None
            rr = run_item(root, sku, sources, keeps, ndirs, cfg0, drafts)
        except Exception as e:  # noqa: BLE001 — один сбой не рушит пакет, счётчик отказов в итоге
            rr = [{'sku': sku, 'error': f'{type(e).__name__}: {e}'}]
            bad += 1
        recs += [r for r in rr if 'error' not in r]
        with open(os.path.join(out, 'hidden.jsonl'), 'a', encoding='utf-8') as f:
            for r in rr:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(json.dumps({'sku': sku, 'записей': len(rr), 'error': rr[0].get('error') if rr and 'error' in rr[0] else None}, ensure_ascii=False), flush=True)
    txt = summarize(recs) if recs else 'нет записей'
    with open(os.path.join(out, 'summary.txt'), 'w', encoding='utf-8') as f:
        f.write(txt + '\n')
    print(txt)
    print(f'мерка: ошибок {bad} из {len(skus)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
