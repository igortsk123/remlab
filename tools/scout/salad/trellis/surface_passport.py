#!/usr/bin/env python3
"""ПАСПОРТ ПОВЕРХНОСТЕЙ (T-20261123-09/1, m4 «один материал — один тон», П1.147; владелец TG 1922/1934/1936, разбор Codex 23.11).
Правило владельца: «Невидимый бок — по видимому. Основной материал — один тон (~2/3 предмета), другим цветом — только другие материалы. Зад обычно по основному цвету. Исключение — рисунок и узоры».
Дефект, который лечим (проверено наложением масок, T-209/1 п.0): 07 красила тон по ЧАСТИ этапа 3, а части режут одну плоскую панель (граница части — рваная линия на плоском заду) → светлая треть, тёмное пятно.

Единица покраски — ГРУППА МАТЕРИАЛА, а не часть 03. Между 06 и 07 (эта функция `build`) строится паспорт:
  • группы: части, соприкасающиеся поверхностями, сливаются, если роль не «отдельный материал» (ножки, каркас, ручки, плафон, стекло) и видимые тона совместимы (ΔE00 базовых тонов ≤ порога; порог мягче, если граница — одна плоскость);
    часть без своего видимого тона берёт группу донора по `tex_fill.choose_tone_sources` (та же роль, наибольшая общая граница). Причина каждого слияния и отказа — в паспорте;
  • базовый Lab группы — робастная (площадь × тексель) медиана по чистым видимым текселям (без краёв известного, теней, бликов, выбросов полосы);
  • класс: «тон + зерно» / «узор» (хроматический разброс ИЛИ двугорбое распределение L — серый рисунок) / «свет» (почти нет зерна: гладко, по свету);
  • σL зерна группы — по ПОЛОСЕ (L минус размытие), а не по всему фото.
`apply_groups` (внутри 07, после всех хуков, до итоговых мерок): невидимые тексели группы получают ТОН ГРУППЫ + зерно (то, что дала заливка, минус медиана ячейки (часть×панель); для «тон+зерно» срез выбросов, и если зерна мало — гауссово зерно по σ группы, без пула блоков, значит без тёмных швов); у стыка с видимым — растушёвка `seam_px`
(Codex: узкая растушёвка только внутри группы). Известное НЕ меняется (маска). Узор — тот же тон, рисунок не трогаем.
`measure` — мерки по группам для check 07 (пилотные пороги — гипотеза, rules/paint-fill.json → surface_groups.thresholds).
Числа — только в rules; ID товаров в коде нет.
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import tex_coverage as TC  # noqa: E402
import texture_synth as TS  # noqa: E402


# ------------------------------------------------------------------------------------------ вспомогательное
def wmedian(v: np.ndarray, w: np.ndarray) -> float:
    """Взвешенная медиана одномерного массива."""
    if len(v) == 0:
        return float('nan')
    o = np.argsort(v, kind='stable')
    cw = np.cumsum(w[o])
    return float(v[o][min(int(np.searchsorted(cw, 0.5 * cw[-1])), len(v) - 1)])


def wmedian3(lab: np.ndarray, w: np.ndarray) -> np.ndarray:
    return np.array([wmedian(lab[:, k], w) for k in range(3)])


def grouped_median(cell: np.ndarray, vals: np.ndarray, k: int) -> np.ndarray:
    """Медиана vals по ячейкам cell (0..k−1); пустая ячейка — 0."""
    out = np.zeros(k)
    if len(vals) == 0:
        return out
    o = np.lexsort((vals, cell))
    cnt = np.bincount(cell, minlength=k)
    st = np.cumsum(cnt) - cnt
    ok = cnt > 0
    out[ok] = vals[o][st[ok] + cnt[ok] // 2]
    return out


def _de(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return TC.de2000_v(np.asarray(a, float).reshape(-1, 3), np.asarray(b, float).reshape(-1, 3))


# Кэши по содержимому маски (T-157/В): знаменатель нормированного размытия и расстояние до известного зависят только от маски (и σ) — до/после и по группам маски повторяются.
# Отдаются без копий и ТОЛЬКО на чтение (writeable=False). Объём ограничен (LRU по байтам); REMLAB_BLUR_CACHE=0 — выключить, REMLAB_BLUR_CACHE_MB — потолок (по умолчанию 192).
import collections as _collections
import hashlib as _hashlib

_BLUR_CACHE = _collections.OrderedDict()
_BLUR_BYTES = [0]
_BLUR_STATS = {'hit': 0, 'miss': 0}


def _mask_key(a) -> bytes:
    a = np.ascontiguousarray(a)
    h = _hashlib.blake2b(digest_size=16)
    h.update(repr((a.shape, str(a.dtype))).encode())
    h.update(a.tobytes())
    return h.digest()


def _cached(key, compute):
    if os.environ.get('REMLAB_BLUR_CACHE', '1') == '0':
        return compute()
    hit = _BLUR_CACHE.get(key)
    if hit is not None:
        _BLUR_CACHE.move_to_end(key)
        _BLUR_STATS['hit'] += 1
        return hit
    _BLUR_STATS['miss'] += 1
    v = compute()
    v.flags.writeable = False
    cap = int(float(os.environ.get('REMLAB_BLUR_CACHE_MB', '192')) * 1e6)
    if v.nbytes <= cap:
        _BLUR_CACHE[key] = v
        _BLUR_BYTES[0] += v.nbytes
        while _BLUR_BYTES[0] > cap and len(_BLUR_CACHE) > 1:
            _, old = _BLUR_CACHE.popitem(last=False)
            _BLUR_BYTES[0] -= old.nbytes
    return v


def _den(known, sigma):
    """gaussian_filter(known как float64, σ, 'nearest') — с памятью по содержимому маски."""
    from scipy.ndimage import gaussian_filter
    kn = np.asarray(known)
    return _cached(('den', _mask_key(kn), float(sigma)), lambda: gaussian_filter(kn.astype(np.float64), float(sigma), mode='nearest'))


def _edt(k0):
    """distance_transform_edt(~k0), пустая маска — 1e6 (как раньше в measure/apply_groups); с памятью по содержимому маски."""
    from scipy.ndimage import distance_transform_edt
    k = np.asarray(k0, bool)
    return _cached(('edt', _mask_key(k)), lambda: distance_transform_edt(~k) if k.any() else np.full(k.shape, 1e6))


def _blur_norm(img, known, sigma):
    from scipy.ndimage import gaussian_filter
    w = known.astype(np.float64)
    den = _den(known, sigma)
    if img.ndim == 2:
        return gaussian_filter(img * w, sigma, mode='nearest') / np.maximum(den, 1e-9)
    return np.stack([gaussian_filter(img[..., k] * w, sigma, mode='nearest') for k in range(img.shape[-1])], -1) / np.maximum(den, 1e-9)[..., None]


def ac_peak(img: np.ndarray, mask: np.ndarray, lo: int, hi: int, clip_k: float = 0.0) -> float:
    """Пик нормированной автокорреляции полосы img внутри маски на лагах lo..hi px (маска-нормированная, через FFT): случайное зерно — ≈0 за пределами своей длины корреляции, повторяющийся рисунок — заметный пик."""
    T = img.shape[0]
    m = mask.astype(np.float64)
    x = img.astype(np.float64)
    if clip_k > 0:                                    # щели/ручки/швы дверей — тонкие выбросы: срезаем до ±clip_k·σ, иначе они дают «повтор» у гладкой плиты
        med = float(np.median(x[mask]))
        sg = 1.4826 * float(np.median(np.abs(x[mask] - med))) + 1e-6
        x = np.clip(x, med - clip_k * sg, med + clip_k * sg)
    v = np.where(mask, x - float(x[mask].mean()), 0.0)
    Fv, Fm = np.fft.rfft2(v), np.fft.rfft2(m)
    num = np.fft.irfft2(Fv * np.conj(Fv), s=v.shape)
    den = np.fft.irfft2(Fm * np.conj(Fm), s=v.shape)
    f = np.fft.fftfreq(T) * T
    fx, fy = np.meshgrid(f, f)
    rr = np.hypot(fy, fx)
    ac = num / np.maximum(den, 1.0)
    ac0 = float(ac[0, 0])
    if ac0 <= 1e-9:
        return 0.0
    ac = ac / ac0
    ok = (rr >= lo) & (rr <= hi) & (den > 0.5 * den[0, 0])
    if not ok.any():
        return 0.0
    # одиночная точка автокорреляции шумит (±0.2–0.4 у гладкой плиты) — берём среднее по ячейке «кольцо 1 px × сектор 22,5°»: повторяющийся рисунок держит пик в ячейке, шум усредняется
    ang = np.mod(np.arctan2(fy, fx), np.pi)
    cell = (np.floor(rr).astype(np.int64) - lo) * 8 + np.minimum((ang / (np.pi / 8)).astype(np.int64), 7)
    c = cell[ok]
    a_ = ac[ok]
    cnt = np.bincount(c)
    sm = np.bincount(c, weights=a_)
    good = cnt >= 12
    return float((sm[good] / cnt[good]).max()) if good.any() else 0.0


class UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


# ------------------------------------------------------------------------------------------ карты тексель → грань/часть/панель
class Maps:
    """По каждой геометрии: T, ids (грань тексела, −1 вне развёртки), part, panel (панель формы с делением по частям, как в ref_zone.panel_ids), w (вес = площадь грани / число её текселей)."""

    def __init__(self, geoms: list, parts: list, grid):
        import ref_zone as RZ
        self.T, self.ids, self.part, self.panel, self.w, self.F, self.V = [], [], [], [], [], [], []
        off = 0
        for gi, g in enumerate(geoms):
            T = int(grid(g))
            F = np.asarray(g['F'], np.int64)
            V = np.asarray(g['V'], np.float64)
            UV = np.asarray(g['UV'], np.float64)
            ids, _ = TC.raster(np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1), F, T)
            ids = np.asarray(ids).reshape(-1).astype(np.int64)
            occ = ids >= 0
            pf = np.asarray(parts[gi], np.int32)
            pid = RZ.panel_ids(V, F, pf)
            part = np.full(T * T, -1, np.int32)
            part[occ] = pf[ids[occ]]
            panel = np.full(T * T, -1, np.int64)
            panel[occ] = pid[ids[occ]] + off
            off += int(pid.max()) + 1
            ar = np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1) / 2.0
            cnt = np.bincount(ids[occ], minlength=len(F)).astype(np.float64)
            w = np.zeros(T * T)
            w[occ] = ar[ids[occ]] / np.maximum(cnt[ids[occ]], 1.0)
            self.T.append(T)
            self.ids.append(ids.reshape(T, T))
            self.part.append(part.reshape(T, T))
            self.panel.append(panel.reshape(T, T))
            self.w.append(w.reshape(T, T))
            self.F.append(F)
            self.V.append(V)


def part_borders_geom(geoms: list, parts: list, plane_deg: float) -> dict:
    """{(a, b) a<b: {'n': число рёбер границы, 'plane': из них с изломом ≤ plane_deg}} по граням разных частей (общее ребро по сваренным вершинам)."""
    import ref_zone as RZ
    out: dict = {}
    for gi, g in enumerate(geoms):
        i, j, _w, dih, _n = RZ.face_graph(np.asarray(g['V']), np.asarray(g['F']))
        pf = np.asarray(parts[gi])
        d = pf[i] != pf[j]
        a = np.minimum(pf[i][d], pf[j][d])
        b = np.maximum(pf[i][d], pf[j][d])
        pl = dih[d] <= plane_deg
        for x, y, p in zip(a.tolist(), b.tolist(), pl.tolist()):
            e = out.setdefault((x, y), {'n': 0, 'plane': 0})
            e['n'] += 1
            e['plane'] += int(p)
    return out


# ------------------------------------------------------------------------------------------ построение паспорта
def _bimodal(h: np.ndarray, R: dict) -> dict:
    """Серый рисунок: двугорбое распределение медленной полосы L (2-means по гистограмме): разрыв, критерий Эшмана D, доля меньшей моды."""
    if len(h) < 1000:
        return {'bimodal': False, 'why': 'мало текселей'}
    lo, hi = np.quantile(h, [0.01, 0.99])
    if hi - lo < 1e-6:
        return {'bimodal': False, 'why': 'нет разброса'}
    c1, c2 = lo, hi
    for _ in range(25):
        m1 = np.abs(h - c1) <= np.abs(h - c2)
        if m1.all() or (~m1).all():
            return {'bimodal': False, 'why': 'одна мода'}
        n1, n2 = h[m1].mean(), h[~m1].mean()
        if abs(n1 - c1) + abs(n2 - c2) < 1e-4:
            break
        c1, c2 = n1, n2
    s1, s2 = h[m1].std(), h[~m1].std()
    gap = float(abs(c1 - c2))
    D = float(1.4142 * gap / max(np.sqrt(s1 * s1 + s2 * s2), 1e-9))
    share = float(min(m1.mean(), 1 - m1.mean()))
    ok = gap >= float(R['pattern_gap_l']) and D >= float(R['pattern_ashman_d']) and share >= float(R['pattern_min_share'])
    return {'bimodal': bool(ok), 'gap_L': round(gap, 2), 'ashman_D': round(D, 2), 'minor_share': round(share, 3)}


def build(geoms: list, tex_rgb: list, known: list, parts: list, roles: dict | None, R: dict, fill_cfg: dict, tf, maps: Maps | None = None) -> tuple:
    """Паспорт поверхностей. geoms/tex_rgb — геометрия и текстуры (видимое — как с фото); known — маски «взято с фото» (T×T bool); parts — части граней по геометриям; roles — {часть: роль этапа 3};
    R — rules surface_groups; fill_cfg — FILL (пороги узора); tf — модуль tex_fill (rgb2lab, choose_tone_sources, unpainted_mask, _grid). → (passport dict, ctx для apply/measure)."""
    from scipy.ndimage import binary_erosion
    roles = roles or {}
    maps = maps or Maps(geoms, parts, tf._grid)
    ng = len(geoms)
    all_parts = sorted({int(p) for pf in parts for p in np.unique(pf)})
    samp = {p: {'lab': [], 'w': [], 'band': [], 'hp': [], 'n': 0} for p in all_parts}
    total = {p: 0 for p in all_parts}
    kn_clean, labs, fine_imgs = [], [], []
    rng = np.random.RandomState(11)
    cap = int(R['sample_cap'])
    for gi in range(ng):
        T = maps.T[gi]
        rgb = np.asarray(tex_rgb[gi])[..., :3]
        lab = tf.rgb2lab(rgb.reshape(-1, 3)).reshape(T, T, 3)
        labs.append(lab)
        k = np.asarray(known[gi], bool) & ~tf.unpainted_mask(rgb)
        kc = binary_erosion(k, iterations=int(R['known_erode_px'])) if int(R['known_erode_px']) > 0 else k
        kn_clean.append(kc)
        pm = maps.part[gi]
        for p in np.unique(pm[pm >= 0]):
            total[int(p)] += int((pm == p).sum())
        band = lab[..., 0] - _blur_norm(lab[..., 0], kc, float(R['band_px']))
        slow = lab[..., 0] - _blur_norm(lab[..., 0], kc, float(R['slow_px']))
        fine = lab[..., 0] - _blur_norm(lab[..., 0], kc, float(R['grain_fine_px']))
        fine_imgs.append(fine.astype(np.float32))
        hp = lab[..., 1:] - _blur_norm(lab[..., 1:], kc, float(fill_cfg['pattern_blur_px']))
        for p in np.unique(pm[kc & (pm >= 0)]):
            sel = kc & (pm == p)
            idx = np.flatnonzero(sel.reshape(-1))
            if len(idx) > cap:
                idx = idx[np.sort(rng.choice(len(idx), cap, replace=False))]
            L = lab.reshape(-1, 3)[idx]
            ok = np.ones(len(idx), bool)
            if len(idx) >= 50:
                ok &= L[:, 0] >= np.quantile(L[:, 0], float(R['shadow_q']))
                ok &= L[:, 0] <= np.quantile(L[:, 0], 1.0 - float(R['highlight_q']))
            b = band.reshape(-1)[idx]
            mad = 1.4826 * np.median(np.abs(b - np.median(b))) + 1e-9
            ok &= np.abs(b) <= float(R['band_outlier_k']) * max(mad, float(R['band_floor']))
            s = samp[int(p)]
            s['lab'].append(L[ok])
            s['w'].append(maps.w[gi].reshape(-1)[idx][ok] * (float(sel.sum()) / max(len(idx), 1)))
            s['band'].append(np.stack([b[ok], slow.reshape(-1)[idx][ok], fine.reshape(-1)[idx][ok]], 1))
            s['hp'].append(hp.reshape(-1, 2)[idx][ok])
            s['n'] += int(sel.sum())
    for p in all_parts:
        s = samp[p]
        for k_ in ('lab', 'w', 'band', 'hp'):
            s[k_] = np.concatenate(s[k_]) if s[k_] else (np.zeros((0, 3)) if k_ in ('lab', 'band') else np.zeros((0,)) if k_ == 'w' else np.zeros((0, 2)))
    reliable = {p: samp[p]['n'] >= int(R['min_part_texels']) and len(samp[p]['lab']) > 0 for p in all_parts}
    tones = {p: (wmedian3(samp[p]['lab'], samp[p]['w']) if reliable[p] else np.array([50.0, 0.0, 0.0])) for p in all_parts}
    borders = part_borders_geom(geoms, parts, float(R['plane_deg']))
    uf = UF(all_parts)
    gw = {p: float(samp[p]['w'].sum()) if reliable[p] else 0.0 for p in all_parts}
    gtone = {p: tones[p].copy() if reliable[p] else None for p in all_parts}
    log = {'merged': [], 'refused': []}
    sep = set(R['separate_roles'])
    role_of = lambda p: roles.get(p, roles.get(str(p)))  # noqa: E731

    def regroup_tone(a, b):
        ra, rb = uf.find(a), uf.find(b)
        wa, wb = gw[ra], gw[rb]
        ta, tb = gtone[ra], gtone[rb]
        uf.union(a, b)
        r = uf.find(a)
        if ta is None or tb is None:
            gtone[r] = ta if tb is None else tb
        else:
            gtone[r] = (ta * wa + tb * wb) / max(wa + wb, 1e-9)
        gw[r] = wa + wb

    for (a, b), e in sorted(borders.items(), key=lambda kv: -kv[1]['n']):
        ra, rb = role_of(a), role_of(b)
        rec = {'parts': [a, b], 'edges': e['n'], 'plane_share': round(e['plane'] / max(e['n'], 1), 2), 'roles': [ra, rb]}
        if uf.find(a) == uf.find(b):
            continue
        if e['n'] < int(R['min_border_edges']):
            log['refused'].append(dict(rec, why='касание короче порога'))
            continue
        if ra in sep or rb in sep:
            log['refused'].append(dict(rec, why=f'роль «{ra if ra in sep else rb}» — отдельный материал'))
            continue
        if not (reliable[a] and reliable[b]):
            continue                                                         # без своего тона — по choose_tone_sources ниже
        de = float(_de(gtone[uf.find(a)], gtone[uf.find(b)])[0])
        coplanar = e['plane'] / max(e['n'], 1) >= float(R['plane_share_min'])
        lim = float(R['merge_de_plane']) if coplanar else float(R['merge_de_edge'])
        if de <= lim:
            log['merged'].append(dict(rec, de00=round(de, 2), limit=lim, why='одна плоскость, тона совместимы' if coplanar else 'тона совместимы'))
            regroup_tone(a, b)
        else:
            log['refused'].append(dict(rec, de00=round(de, 2), limit=lim, why='контрастные тона — другой материал'))
    # части без своего видимого тона: донор по choose_tone_sources (та же роль, самая длинная общая граница, совместимый тон)
    need = [p for p in all_parts if not reliable[p]]
    donors = {}
    if need:
        c = dict(fill_cfg, min_known=int(R['min_part_texels']), no_role_global='skip', catalog_tone=None)
        by_n = {p: samp[p]['n'] for p in all_parts}
        ch = tf.choose_tone_sources(all_parts, roles, by_n, total, {p: not reliable[p] for p in all_parts}, {p: tones[p] for p in all_parts}, {k: v['n'] for k, v in borders.items()}, c)
        for p in need:
            src = ch.get(p, {})
            q = src.get('donor')
            if src.get('source') == 'donor' and q is not None and role_of(p) not in sep:
                regroup_tone(p, q)
                donors[p] = q
                log['merged'].append({'parts': [p, q], 'why': 'нет своего видимого тона — группа донора (choose_tone_sources)', 'de00': src.get('de')})
            else:
                log['refused'].append({'parts': [p], 'why': f"нет своего тона, донора нет ({src.get('source', 'skip')})"})
    # сироты (нет видимого тона, донора нет): по умолчанию — тот же материал, что у соседа с самой длинной границей (правило владельца: основной материал — один тон; отдельный — по роли/каналу или по своему видимому тону);
    # нет соседа с границей ≥ min_edges → группа предмета (самая «видимая»). Счётчик — pas['orphans'].
    AO = R['attach_orphans']
    tot_all = max(sum(total.values()), 1)
    orph_before = [p for p in need if uf.find(p) == p and not any(uf.find(p) == uf.find(q) for q in all_parts if q != p)]
    orph = {'before': {'parts': [int(p) for p in orph_before], 'texels_share_pct': round(100.0 * sum(total[p] for p in orph_before) / tot_all, 2)}, 'attached': []}
    if AO['enabled']:
        for p in sorted(orph_before):
            rp = role_of(p)
            if rp in sep or total[p] > float(AO['max_total_share']) * tot_all:
                continue
            own = wmedian3(samp[p]['lab'], samp[p]['w']) if len(samp[p]['lab']) >= int(AO['evidence_texels']) else None   # свой (малый) видимый тон — доказательство «другого материала»

            def usable(q):
                if not reliable[q] or role_of(q) in sep:
                    return False
                if rp is not None and role_of(q) is not None and rp != role_of(q):          # разные роли/каналы материала — не сливаем
                    return False
                if own is not None and float(_de(own, gtone[uf.find(q)])[0]) > float(AO['evidence_de']):
                    return False
                return True
            cand = [(e['n'], (b if a == p else a)) for (a, b), e in borders.items() if p in (a, b) and e['n'] >= int(AO['min_edges']) and usable(b if a == p else a)]
            if cand:
                n_, q = max(cand)
                why = 'нет видимого тона и донора — тот же материал, что у соседа с самой длинной границей (attach_orphans)'
            elif AO['fallback_main']:
                mains = [(gw[uf.find(q)], q) for q in all_parts if reliable[q] and role_of(q) not in sep and usable(q)]
                if not mains:
                    continue
                n_, q = 0, max(mains)[1]
                why = f'нет соседа с границей ≥ {AO["min_edges"]} рёбер — тон предмета (основная группа, attach_orphans)'
            else:
                continue
            regroup_tone(p, q)
            donors[p] = q
            orph['attached'].append(int(p))
            log['merged'].append({'parts': [p, q], 'edges': n_, 'why': why})
    left = [p for p in orph_before if p not in orph['attached']]
    orph['after'] = {'parts': [int(p) for p in left], 'texels_share_pct': round(100.0 * sum(total[p] for p in left) / tot_all, 2)}
    # группы
    gid_of = {p: uf.find(p) for p in all_parts}
    groups = []
    for r in sorted(set(gid_of.values())):
        ps = [p for p in all_parts if gid_of[p] == r]
        rel = [p for p in ps if reliable[p]]
        Ls = np.concatenate([samp[p]['lab'] for p in rel]) if rel else np.zeros((0, 3))
        Ws = np.concatenate([samp[p]['w'] for p in rel]) if rel else np.zeros(0)
        B = np.concatenate([samp[p]['band'] for p in rel]) if rel else np.zeros((0, 3))
        H = np.concatenate([samp[p]['hp'] for p in rel]) if rel else np.zeros((0, 2))
        g = {'id': int(r), 'parts': ps, 'texels_known': int(sum(samp[p]['n'] for p in ps)), 'texels_total': int(sum(total[p] for p in ps)), 'tone_lab': None, 'sigma_band_L': None, 'class': 'нет тона', 'applied': False}
        if len(Ls) >= int(R['min_group_texels']):
            tone = wmedian3(Ls, Ws)
            b = B[:, 0]
            sig = float(1.4826 * np.median(np.abs(b - np.median(b))))
            bf = B[:, 2]
            sig_f = float(1.4826 * np.median(np.abs(bf - np.median(bf))))
            chroma_std = float(np.hypot(H[:, 0].std(), H[:, 1].std())) if len(H) else 0.0
            chroma_eff = chroma_std * min(1.0, max(float(tone[0]), 0.0) / float(fill_cfg['pattern_dark_ref'])) if float(fill_cfg['pattern_dark_ref']) > 0 else chroma_std
            bm = _bimodal(B[:, 1], R)
            acp = 0.0
            for gi in range(ng):
                gmk = _gmap(maps, gi, gid_of)
                msk = kn_clean[gi] & (gmk == r) & (maps.part[gi] >= 0)
                if int(msk.sum()) >= int(R['ac_min_texels']):
                    acp = max(acp, ac_peak(fine_imgs[gi], msk, int(R['ac_lag_lo_px']), int(R['ac_lag_hi_px']), float(R['ac_clip_k'])))
            if chroma_eff > float(fill_cfg['pattern_chroma']):
                cls, why = 'узор', f'хромный разброс {chroma_eff:.2f} > {fill_cfg["pattern_chroma"]}'
            elif bm['bimodal']:
                cls, why = 'узор', f'двугорбое L (серый рисунок): разрыв {bm["gap_L"]}, D {bm["ashman_D"]}, доля {bm["minor_share"]}'
            elif acp >= float(R['pattern_ac_peak']):
                cls, why = 'узор', f'повтор в зерне: пик автокорреляции {acp:.2f} ≥ {R["pattern_ac_peak"]} на лагах {R["ac_lag_lo_px"]}–{R["ac_lag_hi_px"]} px (печать/рисунок, не зерно)'
            elif sig_f < float(R['light_sigma_l']):
                cls, why = 'свет', f'σL зерна {sig_f:.2f} < {R["light_sigma_l"]}'
            else:
                cls, why = 'тон + зерно', f'σL зерна {sig_f:.2f}, полосы {sig:.2f}, хромный разброс {chroma_eff:.2f}'
            gradfit = None
            if cls in ('тон + зерно', 'свет') and R['gradient']['enabled']:
                xs_, ls_ = [], []
                for gi in range(ng):
                    gmk = _gmap(maps, gi, gid_of)
                    msk = kn_clean[gi] & (gmk == r) & (maps.part[gi] >= 0)
                    idx = np.flatnonzero(msk.reshape(-1))
                    if len(idx) > 60000:
                        idx = idx[np.sort(np.random.RandomState(13).choice(len(idx), 60000, replace=False))]
                    if len(idx):
                        xs_.append(_cen(maps, gi)[maps.ids[gi].reshape(-1)[idx]])
                        ls_.append(labs[gi].reshape(-1, 3)[idx])
                if xs_:
                    gradfit = fit_gradient(np.concatenate(xs_), np.concatenate(ls_), R['gradient'])
                if gradfit and gradfit.get('accepted'):
                    cls, why = 'градиент', f'тон плавно меняется вдоль оси: R² {gradfit["r2"]}, размах L {gradfit["span_L"]} ≥ {R["gradient"]["span_l"]} — на невидимом продолжаем эту зависимость, не одну медиану'
            g.update({'gradient': gradfit, 'tone_lab': [round(float(x), 2) for x in tone], 'sigma_band_L': round(sig, 3), 'sigma_grain_L': round(sig_f, 3), 'class': cls, 'class_why': why, 'chroma_eff': round(chroma_eff, 2), 'ac_peak': round(acp, 3), 'bimodal': bm, 'applied': True})
        else:
            g['why_not_applied'] = f'чистых видимых текселей {len(Ls)} < {R["min_group_texels"]}'
        groups.append(g)
    tot_known = max(sum(g['texels_known'] for g in groups), 1)
    for g in groups:
        g['known_share'] = round(g['texels_known'] / tot_known, 3)
    pas = {'groups': groups, 'part_group': {str(p): int(gid_of[p]) for p in all_parts}, 'donors': {str(k): int(v) for k, v in donors.items()}, 'merges': log['merged'], 'orphans': orph, 'refusals': log['refused'], 'rules_version': R.get('version', 1)}
    over, virt, orep = body_override(geoms, parts, maps, kn_clean, groups, gid_of, R, tf, labs)
    pas['groups'].extend(virt)
    pas['body_override'] = orep
    ctx = {'maps': maps, 'labs': labs, 'kn_clean': kn_clean, 'gid_of': gid_of, 'over': over, 'cen': [_cen(maps, gi) for gi in range(ng)], 'samp': None, 'bo_parts': parts}
    return pas, ctx


def rebuild_body_from_top(pas: dict, ctx: dict, geoms: list, R: dict, tf, top_rep: dict) -> dict:
    """После хука Ш3в (top_prior): если корпус по группам/фото не найден, а Ш3в применён (тон по кромке той же части, не «другой материал»), корпус берёт его тон (роль панели по геометрии: фасад — плоскость,
    остальное — корпус). Пересчитывает виртуальные группы `body_override` с `fallback_tone`; ctx['over'] и pas['groups'] обновляются. Правило `body_override.edge_body.use_top_tone`. → отчёт."""
    O = R.get('body_override') or {}
    E = O.get('edge_body') or {}
    if not (O.get('enabled') and E.get('enabled') and E.get('use_top_tone', False)):
        return {'rebuilt': False, 'why': 'body_override.edge_body.use_top_tone = false'}
    t_ok, t_why = type_allows_body(R)
    if not t_ok:
        return {'rebuilt': False, 'why': t_why}
    if not top_rep.get('applied') or not top_rep.get('tone_lab') or top_rep.get('other_material_hint'):
        return {'rebuilt': False, 'why': 'Ш3в не применён или «другой материал» по кромке≠плоскости'}
    if str(top_rep.get('top_source')) != 'same_part_inference':
        return {'rebuilt': False, 'why': f'источник верха «{top_rep.get("top_source")}» — не по кромке той же части'}
    groups = [g for g in pas['groups'] if 'virtual_for' not in g]
    if any('virtual_for' in g for g in pas['groups']):
        return {'rebuilt': False, 'why': 'виртуальная группа корпуса уже есть (корпус найден по группам/фото)'}
    over, virt, orep = body_override(geoms, ctx['bo_parts'], ctx['maps'], ctx['kn_clean'], groups, ctx['gid_of'], R, tf, ctx['labs'], fallback_tone=top_rep['tone_lab'])
    if not virt:
        pas['body_override'] = orep
        return {'rebuilt': False, 'why': 'правило не сработало', 'rules': orep.get('rules')}
    pas['groups'].extend(virt)
    pas['body_override'] = orep
    ctx['over'] = over
    return {'rebuilt': True, 'tone': virt[0]['tone_lab'], 'virtual_groups': [v['id'] for v in virt], 'texels': sum(v['texels_total'] for v in virt), 'rules': orep.get('rules')}


def _cen(maps: Maps, gi: int) -> np.ndarray:
    """Центр каждой грани, нормированный габаритом формы в [0,1]³ (общая система для подгонки и применения градиента)."""
    V, F = np.asarray(maps.V[gi], np.float64), np.asarray(maps.F[gi], np.int64)
    lo, hi = V.min(0), V.max(0)
    return (V[F].mean(1) - lo) / np.maximum(hi - lo, 1e-9)


def fit_gradient(xyz: np.ndarray, lab: np.ndarray, G: dict) -> dict | None:
    """Монотонный градиент тона вдоль одной оси (тёмный верх → светлый низ): линейная регрессия L по положению (xyz нормированы габаритом), ось = направление градиента.
    Принимается: R² по L ≥ r2_min и размах L вдоль оси ≥ span_l. Свет отличаем от градиента по тому, что градиент держится по всей длине поверхности (R² по положению, не по нормали). → dict или None."""
    if len(xyz) < int(G['min_texels']):
        return None
    A = np.concatenate([xyz, np.ones((len(xyz), 1))], 1)
    coef, *_ = np.linalg.lstsq(A, lab[:, 0], rcond=None)
    pred = A @ coef
    ss = float(((lab[:, 0] - lab[:, 0].mean()) ** 2).sum())
    r2 = 1.0 - float(((lab[:, 0] - pred) ** 2).sum()) / max(ss, 1e-9)
    ax = coef[:3]
    nrm = float(np.linalg.norm(ax))
    if nrm < 1e-9:
        return None
    ax = ax / nrm
    sp = xyz @ ax
    lo, hi = float(np.percentile(sp, 2)), float(np.percentile(sp, 98))
    if hi - lo < 1e-6:
        return None
    ch = []
    for c in range(3):
        B = np.stack([sp - lo, np.ones(len(sp))], 1)
        k, *_ = np.linalg.lstsq(B, lab[:, c], rcond=None)
        ch.append([float(k[1]), float(k[0])])                             # [значение при s=lo, наклон на единицу s]
    span = abs(ch[0][1]) * (hi - lo)
    if r2 < float(G['r2_min']) or span < float(G['span_l']):
        return {'accepted': False, 'r2': round(r2, 3), 'span_L': round(span, 2)}
    return {'accepted': True, 'axis': [round(float(x), 4) for x in ax], 's_lo': lo, 's_hi': hi, 'coef': ch, 'r2': round(r2, 3), 'span_L': round(span, 2)}


def _tone_arr(grp: dict, ctx: dict, gi: int, m: np.ndarray) -> np.ndarray:
    """Тон группы для текселей маски m: у «градиента» — линейная зависимость от положения вдоль оси (s зажат в диапазон видимого — не экстраполируем), иначе один тон. (N, 3)."""
    n = int(m.sum())
    gr = grp.get('gradient')
    if not gr or not gr.get('accepted'):
        return np.broadcast_to(np.asarray(grp['tone_lab'], float), (n, 3)).copy()
    maps = ctx['maps']
    cen = ctx['cen'][gi]
    ids = maps.ids[gi][m]
    s = np.clip(cen[ids] @ np.asarray(gr['axis'], float), gr['s_lo'], gr['s_hi']) - gr['s_lo']
    return np.stack([gr['coef'][c][0] + gr['coef'][c][1] * s for c in range(3)], 1)


def type_allows_rule(R: dict, rule_cfg: dict | None, reg: dict | None = None) -> tuple:
    """Правило этапа 07 действует только у типов, чей паспорт говорит `paint.hidden_pattern` == `rule_cfg.require_hidden_pattern` (T-28/1; ключ — в rules/paint-fill.json у самого правила, не ID и не роль в коде).
    Роль товара — `R['_card_role']` (card.json `role`). Нет роли / типа / поля / реестра — правило НЕ действует (причина в отчёте). → (bool, причина)."""
    import mesh_type_passports as MTP
    return MTP.allows_hidden_pattern(R.get('_card_role'), (rule_cfg or {}).get('require_hidden_pattern'), reg)


def type_allows_body(R: dict, reg: dict | None = None) -> tuple:
    """Роль панели (корпус ≠ фасад; T-28/1) — только у типов `paint.hidden_pattern` == `body_override.edge_body.require_hidden_pattern` (кресло/диван: обивка, не «фасад»). Одна проверка закрывает body_override и edge_body."""
    return type_allows_rule(R, (R.get('body_override') or {}).get('edge_body'), reg)


def light_floor(tgt_L, tone_L, cls: str, F: dict):
    """«Светлое не темнеет» (T-28/1, директор): у группы класса «свет» с L тона ≥ `min_L` невидимое не темнее тона группы больше чем на `max_darker_dL`. Чистая функция по L (массив/число)."""
    if not F.get('enabled', False) or cls != 'свет':
        return tgt_L
    tl = np.asarray(tone_L, float)
    return np.where(tl >= float(F['min_L']), np.maximum(tgt_L, tl - float(F['max_darker_dL'])), tgt_L)


def edge_body_tone(lab_obs: np.ndarray, grp_tone, E: dict, min_de: float, de_fn=None) -> dict:
    """Тон «корпуса» по ФОТО-текселям не-фасадных граней группы (кромки, верх, видимая боковина; роль панели — по геометрии: не на плоскости фасада). Чистая функция.
    lab_obs — Lab фото-текселей этих граней; берётся, если их ≥ `min_texels`, и их медиана — другой материал: ΔE00 от тона группы > `min_de`. → {'ok', 'tone', 'n', 'de00', 'why'}"""
    de_fn = de_fn or (lambda a, b: float(_de(np.asarray(a, float), np.asarray(b, float))[0]))
    n = int(len(lab_obs))
    if n < int(E['min_texels']):
        return {'ok': False, 'n': n, 'why': f'фото-текселей не-фасада {n} < {E["min_texels"]}'}
    med = np.median(np.asarray(lab_obs, float), axis=0)
    de = de_fn(grp_tone, med)
    if de <= min_de:
        return {'ok': False, 'n': n, 'de00': round(de, 1), 'why': f'не-фасад близок к тону группы (ΔE00 {de:.1f} ≤ {min_de})'}
    return {'ok': True, 'n': n, 'de00': round(de, 1), 'tone': [round(float(x), 2) for x in med], 'why': 'корпус по фото-текселям не-фасадных граней'}


def facade_relief(cen: np.ndarray, plane_axes: np.ndarray, dep: np.ndarray, dsup: float, ext: float, side: np.ndarray, sup: np.ndarray, O: dict) -> np.ndarray:
    """Рельеф фасада (T-28/1, дефект 2 листа 10887): боковые грани щелей/пазов между дверями лежат у плоскости фасада (глубина ≤ `relief_depth_frac` габарита от неё) и ВНУТРИ её контура
    (отступ `relief_margin_frac` от краёв видимого фасада); они остаются тоном фасада, а не корпуса. Стенка корпуса (кромка фасадной плоскости) на границе контура — не рельеф. → bool по граням."""
    fr = float(O.get('relief_depth_frac', 0.0))
    if fr <= 0 or not np.asarray(sup).any():
        return np.zeros(len(cen), bool)
    uv = cen @ plane_axes
    lo, hi = np.percentile(uv[sup], 1, axis=0), np.percentile(uv[sup], 99, axis=0)
    mg = float(O.get('relief_margin_frac', 0.03)) * (hi - lo)
    inside = np.all((uv > lo + mg) & (uv < hi - mg), axis=1)
    return side & inside & (np.abs(dep - dsup) <= fr * ext)


def release_weak_known(known_keep: list, weak: list, over: list, R: dict) -> tuple:
    """Слабое фото на корпусных гранях (T-28/1, дефект 1б): известное с prov 2/3 (splat/дыра: цвет фасада, растёкшийся на зад/бок/низ) там, где паспорт назначил «корпус» (карта over ≥ 0), перестаёт быть
    «известным» — его красит корпус; прямое фото (prov 1) остаётся. Правило `body_override.release_weak_known`. → (новая known_keep, число текселей)."""
    Rr = (R.get('body_override') or {}).get('release_weak_known') or {}
    if not Rr.get('enabled', False) or not weak:
        return known_keep, 0
    if not type_allows_rule(R, Rr)[0]:                                      # только у типа по политике паспорта (T-28/1)
        return known_keep, 0
    out, n = [], 0
    for k, w, o in zip(known_keep, weak, over):
        m = np.asarray(k, bool) & np.asarray(w, bool) & (np.asarray(o) >= 0)
        n += int(m.sum())
        out.append(np.asarray(k, bool) & ~m)
    return out, n


def body_override(geoms: list, parts: list, maps: Maps, kn_clean: list, groups: list, gid_of: dict, R: dict, tf, labs: list | None = None, fallback_tone=None) -> tuple:
    """«Фасад на зад не идёт» (владелец TG 1954): группа, чьё видимое лежит на ОДНОЙ плоскости (фасад/лицо), не красит невидимые грани других сторон (зад, бока, верх/низ) —
    они берут тон «корпуса»: другой группы с надёжным видимым тоном (≠ тон фасада). Нет такой группы (одноцветный предмет, диван) — ничего не меняется.
    Панель — геометрическая (RZ.panel_ids без частей): одна плоскость зада, разрезанная частями 03, красится целиком. → (over[gi] карта виртуальной группы или −1, виртуальные группы, отчёт)."""
    import ref_zone as RZ
    O = R['body_override']
    rep = {'enabled': bool(O['enabled']), 'rules': []}
    over = [np.full((maps.T[gi], maps.T[gi]), -1, np.int64) for gi in range(len(geoms))]
    virt = []
    if not O['enabled']:
        return over, virt, rep
    t_ok, t_why = type_allows_body(R)                                       # роль панели «фасад/корпус» — только у типов paint.hidden_pattern = body (кресло/диван: обивка не «фасад»)
    rep['type_gate'] = {'allowed': bool(t_ok), 'why': t_why}
    if not t_ok:
        rep['skipped_by_type'] = t_why
        return over, virt, rep
    app = {g['id']: g for g in groups if g.get('applied')}
    kmax = max([h['texels_known'] for h in app.values()] or [0])
    main_body = None                                                   # тон «корпуса» самой большой группы: мелкие группы (ручки, ножки, обрывки части) берут его же, а не тон крупного фасада
    for G, gg in sorted(app.items(), key=lambda kv: -kv[1]['texels_known']):
        small = main_body is not None and gg['texels_known'] < float(O['small_group_frac']) * kmax
        if small:
            top = main_body['top']
            near = main_body['near']
            btone = main_body['btone']
        else:
            cand = [h for h in app.values() if h['id'] != G and h['texels_known'] >= int(R['min_group_texels'])
                    and float(_de(np.asarray(gg['tone_lab'], float), np.asarray(h['tone_lab'], float))[0]) > float(O['min_de'])]          # корпус — ДРУГОЙ материал (ΔE00 > min_de), а не оттенок того же: стол 1040 (L59 ↔ L70) не перекрашивался
            area = max(sum(h.get('texels_total') or 0 for h in app.values()), 1)
            tiny = [h['id'] for h in cand if (h.get('texels_total') or 0) < float(O.get('body_min_area_frac', 0.0)) * area]
            if tiny:                                                                                  # контрастная мелочь (ниша, ручка, ножка) — не корпус: её тон на зад не переносится (T-28/1, шкаф с нишей: зад стал тёмно-рыжим)
                rep.setdefault('rejected_tiny', []).append({'group': int(G), 'rejected': tiny, 'min_area_frac': float(O.get('body_min_area_frac', 0.0)),
                                                            'area_frac': {str(h['id']): round((h.get('texels_total') or 0) / area, 3) for h in cand if h['id'] in tiny}})
                cand = [h for h in cand if h['id'] not in tiny]
            edge_mode = False
            if not cand:
                if not (O.get('edge_body') or {}).get('enabled', False) or labs is None:
                    continue
                edge_mode = True                                                  # другой группы нет: тон корпуса возьмём по фото-текселям не-фасадных граней (внутри цикла по геометриям)
                top, near, btone = gg, [], np.asarray(gg['tone_lab'], float)
            else:
                top = max(cand, key=lambda h: h['texels_known'])
                near = [h for h in cand if float(_de(np.asarray(top['tone_lab'], float), np.asarray(h['tone_lab'], float))[0]) <= float(O['back_merge_de'])]
                wts = np.array([h['texels_known'] for h in near], float)
                btone = (np.stack([np.asarray(h['tone_lab'], float) for h in near]) * wts[:, None]).sum(0) / wts.sum()
        vid = 100000 + int(G)
        vg = {'id': vid, 'virtual_for': int(G), 'parts': [], 'class': top['class'], 'class_why': 'виртуальная группа «корпус» для невидимых граней фасадной группы', 'tone_lab': [round(float(x), 2) for x in btone],
              'sigma_grain_L': top['sigma_grain_L'], 'sigma_band_L': top.get('sigma_band_L'), 'applied': True, 'texels_known': 0, 'texels_total': 0, 'from_groups': [h['id'] for h in near]}
        n_over = 0
        edge_done = False
        for gi, g in enumerate(geoms):
            V = np.asarray(g['V'], np.float64)
            F = np.asarray(g['F'], np.int64)
            lut = np.full(int(max(gid_of)) + 2, -1, np.int64)
            for p, q in gid_of.items():
                lut[p] = q
            faceG = lut[np.asarray(parts[gi], np.int64)]
            ids = maps.ids[gi].reshape(-1)
            occ = ids >= 0
            kn = np.asarray(kn_clean[gi], bool).reshape(-1)
            nF = len(F)
            kn_f = np.bincount(ids[occ & kn], minlength=nF).astype(np.float64)
            n3 = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
            ar = np.linalg.norm(n3, axis=1) / 2
            nrm = n3 / np.maximum(np.linalg.norm(n3, axis=1, keepdims=True), 1e-12)
            cen = V[F].mean(1)
            sup = (faceG == G) & (kn_f > 0)
            if not sup.any():
                continue
            wv = kn_f[sup]
            M = (nrm[sup, :, None] * nrm[sup, None, :] * wv[:, None, None]).sum(0)
            ev, evec = np.linalg.eigh(M)
            planar = float(ev[-1] / max(ev.sum(), 1e-12))
            rec = {'group': int(G), 'geom': gi, 'support_planar': round(planar, 3), 'body_tone': vg['tone_lab'], 'body_from': vg['from_groups']}
            if planar < float(O['support_planar_min']):
                rec['fired'] = False
                rec['why'] = 'видимое группы не на одной плоскости — правило не применяется'
                rep['rules'].append(rec)
                continue
            ax = evec[:, -1]
            dep = cen @ ax
            o = np.argsort(dep[sup])
            cw = np.cumsum(wv[o])
            dsup = float(dep[sup][o][min(int(np.searchsorted(cw, 0.5 * cw[-1])), len(o) - 1)])
            ext = float((V @ ax).max() - (V @ ax).min())
            pg = RZ.panel_ids(V, F, None)
            tot_q = np.bincount(pg[ids[occ]], minlength=int(pg.max()) + 1)
            kn_q = np.bincount(pg[ids[occ & kn]], minlength=int(pg.max()) + 1)
            unobs_q = kn_q < float(O['obs_share']) * np.maximum(tot_q, 1)
            side = np.abs(nrm @ ax) < np.cos(np.radians(float(O['side_deg'])))
            far = np.abs(dep - dsup) > float(O['depth_frac']) * ext
            ebo = edge_mode and bool((O.get('edge_body') or {}).get('all_nonfacade', False))               # тип «body»: все не-фасадные грани (в т.ч. мелкие «наблюдаемые» панели и сироты) — корпус
            relief = facade_relief(cen, evec[:, :2], dep, dsup, ext, side, sup, O)
            foreign = ((faceG == G) | ((faceG < 0) if ebo else False)) & (unobs_q[pg] | ebo) & (side | far) & ~relief
            f_pct = 100 * float(ar[foreign].sum() / max(ar.sum(), 1e-12))
            if not small and f_pct < float(O['min_foreign_area_pct']):          # «зад» — большая доля площади (шкаф, комод); у каркаса стула/ножек невидимого мало — материал сквозной, тон корпуса не подставляем
                rec['fired'] = False
                rec['foreign_area_pct'] = round(f_pct, 1)
                rec['why'] = f'невидимых чужих граней {f_pct:.1f} % площади < {O["min_foreign_area_pct"]} % — не «зад», правило не применяется'
                rep['rules'].append(rec)
                continue
            if edge_mode:
                obs_f = (faceG == G) & (side | far) & (kn_f > 0)                  # не-фасадные грани группы, у которых есть фото-тексели
                tx_o = occ & kn & obs_f[np.maximum(ids, 0)]
                eb = edge_body_tone(np.asarray(labs[gi]).reshape(-1, 3)[tx_o], gg['tone_lab'], O['edge_body'], float(O['min_de']), lambda a, b: float(_de(np.asarray(a, float), np.asarray(b, float))[0]))
                if not eb['ok'] and fallback_tone is not None and eb['n'] < int(O['edge_body']['min_texels']):                      # фото-текселей не-фасада мало: тон верха/кромки той же части (Ш3в) как корпус, если другой материал
                    dfb = float(_de(np.asarray(gg['tone_lab'], float), np.asarray(fallback_tone, float))[0])
                    if dfb > float(O['min_de']):
                        eb = {'ok': True, 'n': eb['n'], 'de00': round(dfb, 1), 'tone': [round(float(x), 2) for x in fallback_tone], 'why': f'корпус по тону верха/кромки (Ш3в): фото-текселей не-фасада {eb["n"]} мало, ΔE00 к группе {dfb:.1f}', 'from_top_prior': True}
                rec['edge_body'] = eb
                if not eb['ok'] or edge_done:
                    rec['fired'] = False
                    rec['why'] = eb['why'] if not eb['ok'] else 'корпус по фото уже взят на другой геометрии'
                    rep['rules'].append(rec)
                    continue
                vg['tone_lab'] = eb['tone']
                vg['class_why'] = 'виртуальная группа «корпус» по фото-текселям не-фасадных граней (edge_body)'
                rec['body_tone'] = eb['tone']
                edge_done = True
            tx = occ & foreign[np.maximum(ids, 0)]
            T = maps.T[gi]
            over[gi].reshape(-1)[tx] = vid
            n_over += int(tx.sum())
            rec.update({'fired': True, 'faces_total': int(nF), 'relief_area_pct': round(100 * float(ar[relief].sum() / max(ar.sum(), 1e-12)), 1), 'relief_faces': int(relief.sum()), 'foreign_faces': int(foreign.sum()), 'foreign_area_pct': round(100 * float(ar[foreign].sum() / max(ar.sum(), 1e-12)), 1), 'texels': int(tx.sum()), 'support_axis': [round(float(x), 2) for x in ax]})
            rep['rules'].append(rec)
        if n_over:
            vg['texels_total'] = n_over
            virt.append(vg)
            if main_body is None and not small:
                main_body = {'top': top, 'near': near, 'btone': np.asarray(vg['tone_lab'], float)}
    return over, virt, rep


def _lib_norm(s) -> str:
    return ' '.join(str(s or '').strip().lower().split())


def carcass_library_tone(card: dict | None, C: dict) -> dict:
    """Тон бока корпуса по ЛЕНТЕ (T-20261124-06, Ш2): «Цвет корпуса» + «Материал корпуса» карточки → запись библиотеки отделок `carcass_library.entries[ключ].members` ({товар: Lab бока по фото}).
    Тон — медиана Lab участников без самого товара (поле карточки `_sku`: leave-one-product-out в пробе; в проде поля нет — берутся все). Меньше `min_members` участников или разброс
    (макс. ΔE76 до медианы) > `max_spread_de` — отказ с причиной. → {'ok', 'key', 'tone', 'n', 'spread_de', 'why'}; чистая функция."""
    card = card or {}
    k = _lib_norm(card.get(C.get('key_field', '')))
    if not k:
        return {'ok': False, 'key': None, 'why': 'в карточке нет цвета корпуса (лента)'}
    key = k + '|' + _lib_norm(card.get(C.get('mat_field', '')))
    ent = (C.get('entries') or {}).get(key)
    if not ent:
        return {'ok': False, 'key': key, 'why': 'отделки нет в библиотеке'}
    me = {s: v for s, v in (ent.get('members') or {}).items() if s != card.get('_sku')}
    if len(me) < int(C.get('min_members', 2)):
        return {'ok': False, 'key': key, 'n': len(me), 'why': f'участников библиотеки {len(me)} < {C.get("min_members", 2)}'}
    arr = np.asarray(list(me.values()), float)
    tone = np.median(arr, axis=0)
    spread = float(np.linalg.norm(arr - tone, axis=1).max())
    if spread > float(C.get('max_spread_de', 10.0)):
        return {'ok': False, 'key': key, 'n': len(me), 'spread_de': round(spread, 1), 'why': f'разброс тона отделки {spread:.1f} > {C.get("max_spread_de", 10.0)} — библиотека не уверена'}
    return {'ok': True, 'key': key, 'tone': [round(float(x), 2) for x in tone], 'n': len(me), 'spread_de': round(spread, 1)}


def carcass_library_side(pas: dict, ctx: dict, geoms: list, R: dict, card: dict | None) -> dict:
    """Тон БОКОВ корпуса из библиотеки отделок (T-20261124-06, Ш2; первый выпуск — только бока; верх/зад/ножки — позже). Правило `carcass_library`: включено; тип с paint.hidden_pattern = body;
    в библиотеке есть отделка товара (цвет корпуса в карточке) и она уверена. Боковые грани = нормаль вдоль горизонтальной оси, перпендикулярной фасаду (фасад — ось с большей площадью×|n|
    у граней с фото), в панелях, где фото покрывает < `body_override.obs_share`. Их НЕ закрытые фото тексели красит виртуальная группа с тоном библиотеки (фото-тексели остаются; тон
    группы-корпуса body_override на них не действует). Диагностика: тон видимых боковых текселей по фото и ΔE к библиотеке (спорное — в отчёт, не отказ). → отчёт (pas['carcass_library'])."""
    import ref_zone as RZ
    C = R.get('carcass_library') or {}
    rep = {'enabled': bool(C.get('enabled', False)), 'applied': False}
    pas['carcass_library'] = rep
    if not rep['enabled']:
        return rep
    t_ok, t_why = type_allows_rule(R, C)
    rep['type_gate'] = {'allowed': bool(t_ok), 'why': t_why}
    if not t_ok:
        rep['why'] = t_why
        return rep
    lib = carcass_library_tone(card, C)
    rep['library'] = lib
    if not lib['ok']:
        rep['why'] = lib['why']
        return rep
    app = [g for g in pas['groups'] if g.get('applied') and 'virtual_for' not in g]
    if not app:
        rep['why'] = 'нет применимых групп'
        return rep
    gmain = max(app, key=lambda g: g['texels_known'])
    O = R.get('body_override') or {}
    obs_share = float(O.get('obs_share', 0.05))
    vid = 200000 + int(gmain['id'])
    maps = ctx['maps']
    cos_side = float(np.cos(np.radians(float(C.get('side_deg', 40.0)))))
    n_over, n_faces, geoms_rep, ph_lab, ph_w = 0, 0, [], [], []
    for gi, g in enumerate(geoms):
        V = np.asarray(g['V'], np.float64)
        F = np.asarray(g['F'], np.int64)
        ids = maps.ids[gi].reshape(-1)
        occ = ids >= 0
        kn = np.asarray(ctx['kn_clean'][gi], bool).reshape(-1)
        nF = len(F)
        kn_f = np.bincount(ids[occ & kn], minlength=nF).astype(np.float64)
        n3 = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        ar = np.linalg.norm(n3, axis=1) / 2
        nrm = n3 / np.maximum(np.linalg.norm(n3, axis=1, keepdims=True), 1e-12)
        w_ax = [float((kn_f * ar * np.abs(nrm[:, a])).sum()) for a in (0, 2)]          # горизонтальные оси (y — вверх, как в выходе TRELLIS): фасад — там, где больше видимого
        if sum(w_ax) <= 0:
            continue
        fa = 0 if w_ax[0] > w_ax[1] else 2
        sa = 2 if fa == 0 else 0
        pg = RZ.panel_ids(V, F, None)
        tot_q = np.bincount(pg[ids[occ]], minlength=int(pg.max()) + 1)
        kn_q = np.bincount(pg[ids[occ & kn]], minlength=int(pg.max()) + 1)
        unobs_q = kn_q < obs_share * np.maximum(tot_q, 1)
        side = np.abs(nrm[:, sa]) >= cos_side
        sel = side & unobs_q[pg]
        tx = occ & sel[np.maximum(ids, 0)]
        if int(tx.sum()):
            ctx['over'][gi].reshape(-1)[tx] = vid
        n_over += int(tx.sum())
        n_faces += int(sel.sum())
        obs = side & ~unobs_q[pg] & (kn_f > 0)                                          # диагностика: боковые грани, которые фото видит
        txo = occ & kn & obs[np.maximum(ids, 0)]
        if int(txo.sum()):
            ph_lab.append(np.asarray(ctx['labs'][gi]).reshape(-1, 3)[txo])
            ph_w.append(ar[ids[txo]])
        geoms_rep.append({'geom': gi, 'facade_axis': 'xyz'[fa], 'side_axis': 'xyz'[sa], 'side_faces_unobserved': int(sel.sum()), 'texels': int(tx.sum()), 'side_faces_observed': int(obs.sum())})
    rep['geoms'] = geoms_rep
    if ph_lab:
        L = np.concatenate(ph_lab)
        W = np.concatenate(ph_w)
        pt = [wmedian(L[:, c], W) for c in range(3)]
        rep['photo_side'] = {'n': int(len(L)), 'tone': [round(float(x), 1) for x in pt], 'de76_to_library': round(float(np.linalg.norm(np.asarray(pt) - np.asarray(lib['tone']))), 1),
                             'disputed': bool(np.linalg.norm(np.asarray(pt) - np.asarray(lib['tone'])) > float(C.get('dispute_de', 12.0)))}
    if not n_over:
        rep['why'] = 'боковых невидимых текселей нет'
        return rep
    sg = min(float(gmain.get('sigma_grain_L') or 0.0), float((R.get('grain_cap') or {}).get('max_sigma_l', 2.5)))
    vg = {'id': vid, 'virtual_for': int(gmain['id']), 'parts': [], 'class': 'тон + зерно', 'class_why': f'бока корпуса по библиотеке отделок «{lib["key"]}» (лента), n={lib["n"]}', 'tone_lab': lib['tone'],
          'sigma_grain_L': round(sg, 3), 'sigma_band_L': gmain.get('sigma_band_L'), 'applied': True, 'texels_known': 0, 'texels_total': int(n_over), 'from_library': lib['key']}
    pas['groups'].append(vg)
    rep.update({'applied': True, 'group': vid, 'texels': int(n_over), 'side_faces': int(n_faces), 'tone': lib['tone']})
    return rep


def top_follows_group(top_rep: dict, pas: dict, R: dict) -> dict:
    """Правило «верх следует группе» (T-28/1): тон верха от Ш3в (top_prior) заменяет тон группы только когда верх — другой материал. Откат хука, если (rules `top_follow`): включено; хук применён; `other_material_hint` нет;
    фото верха < `max_photo_share` от всех текселей верха; у основной группы (больше всего известного) класс в `classes` (однотон; «узор»/«зерно»/«градиент» не трогаем); ΔE00 (тон Ш3в, тон группы) > `min_de00`.
    → {'follow': bool, 'why': str, ...}; чистая функция."""
    F = R.get('top_follow') or {}
    if not F.get('enabled', False):
        return {'follow': False, 'why': 'top_follow.enabled = false'}
    t_ok, t_why = type_allows_rule(R, F)                                    # только у типа по политике паспорта (T-28/1)
    if not t_ok:
        return {'follow': False, 'why': 'по типу: ' + t_why}
    if not top_rep.get('applied') or not top_rep.get('tone_lab'):
        return {'follow': False, 'why': 'Ш3в не применён'}
    if top_rep.get('other_material_hint'):
        return {'follow': False, 'why': 'кромка и плоскость говорят «другой материал» — верх остаётся по Ш3в'}
    n_top = max(int(top_rep.get('n_top') or 0), 1)
    share = float(top_rep.get('photo_top_n') or 0) / n_top
    if share >= float(F['max_photo_share']):
        return {'follow': False, 'why': f'верх виден на фото ({100 * share:.1f} % ≥ {100 * float(F["max_photo_share"]):.0f} %)', 'photo_share': round(share, 4)}
    gs = [g for g in pas.get('groups', []) if g.get('applied') and 'virtual_for' not in g]
    if not gs:
        return {'follow': False, 'why': 'нет применимых групп'}
    G = max(gs, key=lambda g: g.get('texels_known') or 0)
    if G.get('class') not in F['classes']:
        return {'follow': False, 'why': f'класс основной группы «{G.get("class")}» не в {F["classes"]} — не трогаем', 'group': G.get('id')}
    de = float(_de(np.asarray(top_rep['tone_lab'], float), np.asarray(G['tone_lab'], float))[0])
    if de <= float(F['min_de00']):
        return {'follow': False, 'why': f'тон Ш3в близок к группе (ΔE00 {de:.1f} ≤ {F["min_de00"]})', 'de00': round(de, 1), 'group': G.get('id')}
    return {'follow': True, 'why': f'верх без фото ({100 * share:.1f} %), тон Ш3в на ΔE00 {de:.1f} > {F["min_de00"]} от тона группы «{G.get("class")}» — следует группе', 'de00': round(de, 1), 'group': G.get('id'),
            'group_tone': G['tone_lab'], 'top_tone': top_rep['tone_lab']}


# ------------------------------------------------------------------------------------------ применение (внутри 07)
def _gmap_ctx(ctx: dict, gi: int) -> np.ndarray:
    base = _gmap(ctx['maps'], gi, ctx['gid_of'])
    ov = ctx['over'][gi]
    g = np.where(ov >= 0, ov, base)
    sk = ctx.get('skip')
    if sk is not None:
        g = np.where(sk[gi], -1, g)                                          # сирота с уже заданным другим тоном (хуки: верх, свой кусок) — группа его не трогает
    return g


def orphan_skip(geoms: list, tex_after: list, known_keep: list, pas: dict, ctx: dict, R: dict, tf) -> None:
    """Сирота, присоединённая к группе, но уже получившая от хуков (top_prior, own_panel, донор) тон, далёкий от тона группы (ΔE00 > attach_orphans.apply_de), остаётся как есть: это другой материал/зона (верх комода дуб при графитовых фасадах),
    а не заплатка p5. Решается один раз по текстуре до apply; результат — ctx['skip'] и pas['orphans']['kept_own'/'after']."""
    maps = ctx['maps']
    AO = R['attach_orphans']
    orph = pas.get('orphans') or {'attached': []}
    byid = {g['id']: g for g in pas['groups'] if g.get('applied')}
    hk = ctx.get('hook_keep')
    skip = [np.asarray(hk[gi], bool).copy() if hk is not None else np.zeros((maps.T[gi], maps.T[gi]), bool) for gi in range(len(geoms))]       # + текселы, окрашенные верхом (top_prior): материал верха задан карточкой, группа его не перекрашивает
    kept = []
    for p in orph.get('attached', []):
        gid = ctx['gid_of'].get(p)
        grp = byid.get(gid)
        if grp is None:
            continue
        vals, ws = [], []
        for gi in range(len(geoms)):
            m = (maps.part[gi] == p) & ~np.asarray(known_keep[gi], bool)
            if int(m.sum()) < 50:
                continue
            idx = np.flatnonzero(m.reshape(-1))
            if len(idx) > 40000:
                idx = idx[np.random.RandomState(3).choice(len(idx), 40000, replace=False)]
            vals.append(tf.rgb2lab(np.asarray(tex_after[gi])[..., :3].reshape(-1, 3)[idx]))
        if not vals:
            continue
        cur = np.median(np.concatenate(vals), axis=0)
        dd = float(_de(cur, np.asarray(grp['tone_lab'], float))[0])
        if dd > float(AO['apply_de']):
            for gi in range(len(geoms)):
                skip[gi] |= (maps.part[gi] == p)
            kept.append({'part': int(p), 'de00_to_group': round(dd, 1), 'own_tone_lab': [round(float(x), 1) for x in cur]})
    ctx['skip'] = skip
    if 'attached' in orph:
        orph['kept_own'] = kept
        left = list(orph['after']['parts']) + [k['part'] for k in kept]
        tot = {}
        for gi in range(len(geoms)):
            for p, n in zip(*np.unique(maps.part[gi][maps.part[gi] >= 0], return_counts=True)):
                tot[int(p)] = tot.get(int(p), 0) + int(n)
        orph['after'] = {'parts': sorted(int(x) for x in left), 'texels_share_pct': round(100.0 * sum(tot.get(int(x), 0) for x in left) / max(sum(tot.values()), 1), 2)}


def _gmap(maps: Maps, gi: int, gid_of: dict) -> np.ndarray:
    lut = np.full(int(max(gid_of)) + 2, -1, np.int64)
    for p, g in gid_of.items():
        lut[p] = g
    pm = maps.part[gi]
    return np.where(pm >= 0, lut[np.maximum(pm, 0)], -1)


def apply_groups(geoms: list, tex_after: list, known_keep: list, pas: dict, ctx: dict, R: dict, tf) -> tuple:
    """Невидимое (не known_keep) каждой применимой группы: низкие частоты → тон группы, зерно — как дала заливка (клип выбросов; мало — гауссово зерно). Известное не меняется. → (текстуры, отчёт)."""
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    if ctx.get('skip') is None:
        orphan_skip(geoms, tex_after, known_keep, pas, ctx, R, tf)
    maps, gid_of = ctx['maps'], ctx['gid_of']
    byid = {g['id']: g for g in pas['groups'] if g.get('applied')}
    out_tex, rep_g = [], {}
    _lf_ok, _lf_why = type_allows_rule(R, R.get('light_floor'))                 # «светлое не темнеет» — только у типа по политике паспорта (T-28/1); у остальных — как в main
    _LF = (R.get('light_floor') or {}) if _lf_ok else {}
    _gc_ok, _gc_why = type_allows_rule(R, R.get('grain_cap'))                   # потолок зерна заливки — только у типа по политике паспорта (T-28/1); у остальных — как в main
    _gcap = float(R['grain_cap']['max_sigma_l']) if (_gc_ok and (R.get('grain_cap') or {}).get('enabled', False)) else None
    ctx['grain_cap_gate'] = {'allowed': _gcap is not None, 'max_sigma_l': _gcap, 'why': _gc_why}
    ctx['light_floor_gate'] = {'allowed': bool(_lf_ok and (R.get('light_floor') or {}).get('enabled', False)), 'why': _lf_why}
    for gi, g in enumerate(geoms):
        T = maps.T[gi]
        tex = np.asarray(tex_after[gi]).copy()
        lab = tf.rgb2lab(tex[..., :3].reshape(-1, 3)).reshape(T, T, 3)
        k0 = np.asarray(known_keep[gi], bool)
        gm = _gmap_ctx(ctx, gi)
        d = _edt(k0)
        wseam = np.clip(d / max(float(R['seam_px']), 1e-6), 0.0, 1.0)
        wseam = wseam * wseam * (3.0 - 2.0 * wseam)
        noise = np.random.RandomState(5003 + gi).randn(T, T)
        if float(R['grain_sigma_px']) > 0:
            noise = gaussian_filter(noise, float(R['grain_sigma_px']), mode='wrap')
        noise = noise - gaussian_filter(noise, float(R['grain_fine_px']), mode='wrap')               # та же полоса, в которой измерено σL видимого (мелкая), без крупных пятен
        noise /= max(float(1.4826 * np.median(np.abs(noise - np.median(noise)))), 1e-9)               # единичный робастный σ в этой полосе
        syn = R.get('synth') or {}
        pol = ctx.get('paint_policy') or {'hidden_pattern': 'unknown', 'mode': 'observe', 'reason': 'no_policy_in_ctx'}          # политика типа читается ДО build (tex_fill); нет её — воздержание, не «обычная мебель»
        uvm = TS.uv_field_maps(g['V'], g['F'], g['UV'], maps.ids[gi], T, float(syn.get('up_min', 0.5))) if syn.get('enabled') and 'UV' in g else None          # «вверх мира» и плотность атласа — для поворота/масштаба кусков
        new_all = lab.copy()
        touched = np.zeros((T, T), bool)
        for gid, grp in byid.items():
            m = (gm == gid) & ~k0
            if not m.any():
                continue
            tone = _tone_arr(grp, ctx, gi, m)
            cell_raw = maps.panel[gi][m]
            uq, cell = np.unique(cell_raw, return_inverse=True)
            K = len(uq)
            cur = lab[m]
            if grp['class'] == 'градиент':                                  # плавную зависимость от положения (и заливочную тоже) убираем низкочастотным фильтром, а не медианой ячейки
                low = _blur_norm(lab, m, float(R['slow_px']))[m]                    # три канала одним вызовом: знаменатель один (то же число, что по каналам)
                res = cur - low
                med = cur - res
            else:
                med = np.stack([grouped_median(cell, cur[:, c], K) for c in range(3)], 1)[cell]
                res = cur - med
            sig_g = float(grp['sigma_grain_L'])
            info = {'texels': int(m.sum()), 'class': grp['class']}
            if _gcap is not None and sig_g > _gcap:
                info['grain_capped'] = {'sigma_measured': round(sig_g, 3), 'max_sigma_l': _gcap}
                sig_g = _gcap
            if grp['class'] != 'узор':
                sr = float(1.4826 * np.median(np.abs(res[:, 0] - np.median(res[:, 0]))))
                lim = float(R['grain_clip_k']) * max(sig_g, 1e-6)                       # зерно залитого не выше измеренного на видимом (не по собственному разбросу заливки)
                amp0 = float(R['grain_amp_ratio']) * (sig_g if sig_g >= float(R['grain_floor_l']) else float(R['grain_low_factor']) * sig_g)
                ko = float(R['outlier_k']) * max(sig_g, float(R['outlier_floor_l']))     # выброс: дальше k·σ видимого от тона группы (по L) или заметная цветность (бежевые точки) — это перенос с фасада, не материал
                outl = (np.abs(res[:, 0]) > ko) | (np.hypot(res[:, 1], res[:, 2]) > float(R['outlier_chroma']))
                if grp['class'] in R['dark_keep_classes']:
                    outl[:] = False
                o2 = np.zeros((T, T), bool)
                o2[m] = outl
                if int(R['outlier_dilate_px']) > 0 and o2.any():
                    from scipy.ndimage import binary_dilation as _bd
                    o2 = _bd(o2, iterations=int(R['outlier_dilate_px'])) & m
                outl = o2[m]
                res[outl, 0] = amp0 * noise[m][outl]                                    # выброс заливается тоном группы с зерном (не зажимается у границы)
                res[outl, 1:] = 0.0
                info['outlier_texels'] = int(outl.sum())
                dark = (res[:, 0] < -float(R['dark_keep_l'])) if grp['class'] in R['dark_keep_classes'] else np.zeros(len(res), bool)   # у «узора» глубокая тёмная деталь остаётся; у «тон+зерно/свет» контур двери/ручки на заду — след проекции переднего вида (на заду щелей нет) → срезается
                nclip = int((np.abs(res[:, 0]) > lim).sum() - dark.sum())
                r0 = res[:, 0].copy()
                res[:, 0] = np.clip(r0, -lim, lim)
                res[dark, 0] = r0[dark]
                info['dark_kept_texels'] = int(dark.sum())
                info.update({'sigma_resid_L': round(sr, 3), 'clip_lim': round(lim, 2), 'clipped_texels': nclip})
                amp = float(R['grain_amp_ratio']) * (sig_g if sig_g >= float(R['grain_floor_l']) else float(R['grain_low_factor']) * sig_g)   # видимое зерно слабее порога → почти ноль
                if grp['class'] in ('тон + зерно', 'градиент') and sr < float(R['grain_min_ratio']) * amp:
                    add = float(np.sqrt(max(amp * amp - sr * sr, 0.0)))
                    res[:, 0] += add * noise[m]
                    info['grain_added_sigma'] = round(add, 3)
            syn_off = True
            hp = pol['hidden_pattern']
            if syn.get('enabled') and grp['class'] not in (syn.get('skip_classes') or []):
                if pol.get('mode') != 'active' or hp not in ('continue', 'same_fabric'):          # body — тон/фактура корпуса (прежнее зерно группы), plain — гладко, not_applicable/unknown/observe — воздержание с причиной; узор лица на невидимое НЕ переносим
                    why = pol.get('reason') or (f'политика типа в режиме {pol.get("mode")}' if pol.get('mode') != 'active' else f'hidden_pattern={hp}')
                    info['synth'] = {'mode': 'skip', 'hidden_pattern': hp, 'why': 'по типу: ' + str(why)}
                else:
                    syn_off = False
            if not syn_off:
                cfg = dict(syn['common'])
                cfg.update((syn.get('by_class') or {}).get(grp['class'], {}))
                cfg.update((syn.get('by_hidden_pattern') or {}).get(hp, {}))     # same_fabric: только фактура ткани (без деталей фасада)
                sres, sinfo = TS.synth_group(lab, (gm == gid) & k0, m, uvm, cfg, _blur_norm, keep_detail=(grp['class'] in R['dark_keep_classes'] and hp != 'same_fabric'), seed=int(syn.get('seed_step', 1009)) * (gi + 1) + int(gid))
                sinfo['hidden_pattern'] = hp
                info['synth'] = sinfo
                if sinfo['mode'] == 'quilt' or (sinfo['mode'] == 'smooth' and syn.get('smooth_fallback', True)):   # 'skip' (рисунка нет) — прежнее зерно, без синтеза
                    res = sres[m].astype(np.float64)                          # остаток фактуры из куска фото своей группы (нет донора — 0: гладко, не шум)
            tgt = tone + res
            _l0 = tgt[:, 0].copy()
            tgt[:, 0] = light_floor(tgt[:, 0], np.broadcast_to(np.asarray(tone, float)[..., 0], tgt[:, 0].shape), grp['class'], _LF)
            ctx['light_floor_texels'] = int(ctx.get('light_floor_texels', 0)) + int((tgt[:, 0] != _l0).sum())      # для записи правила (extra.rules[]): сколько текселей подняло
            dm = wseam[m][:, None]
            new_all[m] = cur + dm * (tgt - cur)
            touched |= m
            rep_g[str(gid)] = info
        if touched.any():
            rgb_new = tf.lab2rgb(new_all[touched])
            tex[touched, :3] = rgb_new
            # желоб вокруг островков: копирует ближайший цвет островка (как в fill) — обновить там, где источник изменён
            occ = maps.ids[gi] >= 0
            dist, (iy, ix) = distance_transform_edt(~occ, return_indices=True)
            gut = (~occ) & (dist <= float(R['gutter_px']))
            src_changed = touched[iy, ix]
            sel = gut & src_changed
            tex[sel, :3] = tex[iy[sel], ix[sel], :3]
        out_tex.append(tex)
    return out_tex, rep_g


# ------------------------------------------------------------------------------------------ мерки (check 07)
def _quant(v: np.ndarray, w: np.ndarray, q: float) -> float:
    if len(v) == 0:
        return float('nan')
    o = np.argsort(v)
    cw = np.cumsum(w[o])
    return float(v[o][min(int(np.searchsorted(cw, q * cw[-1])), len(v) - 1)])


def measure(geoms: list, tex_after: list, known_keep: list, pas: dict, ctx: dict, R: dict, tf) -> dict:
    """Мерки по группам (только невидимое, за пределами растушёвки): ΔE00 базового тона видимое↔залитое; разброс медиан ячеек (часть×панель) от медианы группы (площадь-взвешенный p95, max);
    скачок через границу частей внутри группы (медиана, p95; Lab размыт σ=2, пробы на ±offset px от границы); доля площади нарушений. Пороги пилота — rules surface_groups.thresholds (гипотеза)."""
    from scipy.ndimage import distance_transform_edt, gaussian_filter, binary_dilation
    if ctx.get('skip') is None:
        orphan_skip(geoms, tex_after, known_keep, pas, ctx, R, tf)
    maps, gid_of = ctx['maps'], ctx['gid_of']
    th = R['thresholds']
    mg = R['measure']
    per = {}
    acc = {gid: {'v': [], 'w': [], 'cell': [], 'jump': [], 'viol_w': 0.0, 'tot_w': 0.0} for gid, g in ((g['id'], g) for g in pas['groups']) if next(x for x in pas['groups'] if x['id'] == gid).get('applied')}
    for gi, g in enumerate(geoms):
        T = maps.T[gi]
        tex = np.asarray(tex_after[gi])
        lab = tf.rgb2lab(tex[..., :3].reshape(-1, 3)).reshape(T, T, 3)
        k0 = np.asarray(known_keep[gi], bool)
        gm = _gmap_ctx(ctx, gi)
        d = _edt(k0)
        away = d >= float(R['seam_px'])
        sm = None                                                         # размытие Lab для скачка — по требованию (нужно, только если на границе частей есть пары)
        pm = maps.part[gi]
        for gid in list(acc):
            tone = np.asarray(next(x for x in pas['groups'] if x['id'] == gid)['tone_lab'], float)
            m = (gm == gid) & ~k0 & away
            if not m.any():
                continue
            w = maps.w[gi][m]
            cur = lab[m]
            cell_raw = maps.panel[gi][m]
            uq, cell = np.unique(cell_raw, return_inverse=True)
            a = acc[gid]
            grp_m = next(x for x in pas['groups'] if x['id'] == gid)
            if grp_m['class'] == 'градиент':                                   # мерки считаем по остатку после вычета зависимости от положения
                cur = cur - _tone_arr(grp_m, ctx, gi, m) + np.asarray(grp_m['tone_lab'], float)
            a['v'].append(cur)
            a['w'].append(w)
            a['cell'].append(cell_raw)
            a['tot_w'] += float(w.sum())
            # скачок через границу частей: пары соседних текселей разных частей одной группы, пробы на ±off px
            off = int(mg['jump_offset_px'])
            for dy, dx in ((0, 1), (1, 0)):
                A = (slice(0, T - dy), slice(0, T - dx))
                B = (slice(dy, T), slice(dx, T))
                pa, pb = pm[A], pm[B]
                bd = (pa != pb) & (pa >= 0) & (pb >= 0) & m[A] & m[B]
                if not bd.any():
                    continue
                ys, xs = np.nonzero(bd)
                y0, x0 = ys - dy * off, xs - dx * off
                y1, x1 = ys + dy + dy * off, xs + dx + dx * off
                ok = (y0 >= 0) & (x0 >= 0) & (y1 < T) & (x1 < T)
                ys, xs, y0, x0, y1, x1 = ys[ok], xs[ok], y0[ok], x0[ok], y1[ok], x1[ok]
                ok2 = (pm[y0, x0] == pa[ys, xs]) & (pm[y1, x1] == pb[ys, xs]) & (gm[y0, x0] == gid) & (gm[y1, x1] == gid) & ~k0[y0, x0] & ~k0[y1, x1]
                if not ok2.any():
                    continue
                ys, xs, y0, x0, y1, x1 = ys[ok2], xs[ok2], y0[ok2], x0[ok2], y1[ok2], x1[ok2]
                if len(ys) > int(mg['jump_max_pairs']):
                    s = np.random.RandomState(7).choice(len(ys), int(mg['jump_max_pairs']), replace=False)
                    ys, xs, y0, x0, y1, x1 = ys[s], xs[s], y0[s], x0[s], y1[s], x1[s]
                if sm is None:
                    sm = np.stack([gaussian_filter(lab[..., c], float(mg['jump_blur_px']), mode='nearest') for c in range(3)], -1)
                a['jump'].append(_de(sm[y0, x0], sm[y1, x1]))
    gr_ratio = {}
    for gid in acc:
        grp = next(x for x in pas['groups'] if x['id'] == gid)
        if grp['class'] in ('узор', 'свет') or not grp.get('sigma_grain_L'):
            continue
        vals = []
        for gi in range(len(geoms)):
            gmk = _gmap_ctx(ctx, gi)
            mm = (gmk == gid) & ~np.asarray(known_keep[gi], bool)
            if int(mm.sum()) < 500:
                continue
            Lg = tf.rgb2lab(np.asarray(tex_after[gi])[..., :3].reshape(-1, 3)).reshape(maps.T[gi], maps.T[gi], 3)[..., 0]
            k0g = np.asarray(known_keep[gi], bool)
            dg = _edt(k0g)
            me = mm & (dg >= float(R['seam_px']))
            if int(me.sum()) < 500:
                continue
            fine = Lg - _blur_norm(Lg, mm, float(R['grain_fine_px']))
            f = fine[me]
            vals.append(float(1.4826 * np.median(np.abs(f - np.median(f)))))
        if vals:
            gr_ratio[gid] = round(max(vals) / max(float(grp['sigma_grain_L']), 1e-6), 2)
    worst = {'dE_base': 0.0, 'panel_p95': 0.0, 'panel_max': 0.0, 'jump_median': 0.0, 'jump_p95': 0.0, 'violation_pct': 0.0}
    for gid, a in acc.items():
        if not a['v']:
            continue
        grp = next(x for x in pas['groups'] if x['id'] == gid)
        V = np.concatenate(a['v'])
        W = np.concatenate(a['w'])
        C = np.concatenate(a['cell'])
        base = wmedian3(V, W)
        d_base = float(_de(np.asarray(grp['tone_lab']), base)[0])
        uq, cell = np.unique(C, return_inverse=True)
        K = len(uq)
        cnt = np.bincount(cell, minlength=K)
        cw = np.bincount(cell, weights=W, minlength=K)
        meds = np.stack([grouped_median(cell, V[:, c], K) for c in range(3)], 1)
        okc = cnt >= int(mg['min_cell_texels'])
        dev = _de(meds[okc], base[None, :].repeat(int(okc.sum()), 0)) if okc.any() else np.zeros(0)
        p95 = _quant(dev, cw[okc], 0.95) if len(dev) else 0.0
        mx = float(dev.max()) if len(dev) else 0.0
        J = np.concatenate(a['jump']) if a['jump'] else np.zeros(0)
        jm = float(np.median(J)) if len(J) else 0.0
        jp = float(np.quantile(J, 0.95)) if len(J) else 0.0
        viol = float(cw[okc][dev > float(th['panel_spread_de'][1])].sum() / max(cw.sum(), 1e-9) * 100.0) if len(dev) else 0.0
        per[str(gid)] = {'class': grp['class'], 'parts': grp['parts'], 'invisible_texels': int(len(V)), 'dE00_base': round(d_base, 2), 'panel_spread_p95': round(p95, 2), 'panel_spread_max': round(mx, 2),
                         'grain_ratio': gr_ratio.get(gid), 'cells': int(okc.sum()), 'jump_median': round(jm, 2), 'jump_p95': round(jp, 2), 'jump_pairs': int(len(J)), 'violation_area_pct': round(viol, 1)}
        wt = float(a['tot_w']) / max(sum(x['tot_w'] for x in acc.values()), 1e-9)
        if wt >= float(mg['min_group_share']):                                 # крохотные группы (метки) в «худшую» не идут: показаны в per_group
            worst['dE_base'] = max(worst['dE_base'], d_base)
            worst['panel_p95'] = max(worst['panel_p95'], p95)
            worst['panel_max'] = max(worst['panel_max'], mx)
            worst['jump_median'] = max(worst['jump_median'], jm)
            worst['jump_p95'] = max(worst['jump_p95'], jp)
            worst['violation_pct'] = max(worst['violation_pct'], viol)
    worst = {k: round(v, 2) for k, v in worst.items()}
    worst['grain_ratio'] = max(gr_ratio.values()) if gr_ratio else None
    slits = measure_slits(geoms, tex_after, known_keep, ctx, R, tf)
    ok = {'dE_base': worst['dE_base'] <= th['dE_base'][1], 'panel_p95': worst['panel_p95'] <= th['panel_spread_de'][1], 'jump_median': worst['jump_median'] <= th['jump_median'][1],
          'jump_p95': worst['jump_p95'] <= th['jump_p95'][1], 'grain_ratio': (worst['grain_ratio'] is None or worst['grain_ratio'] <= th['grain_ratio'][1])}
    return {'per_group': per, 'worst': worst, 'slits': slits, 'ok_hypothesis': ok, 'all_ok_hypothesis': bool(all(ok.values())), 'thresholds_hypothesis': th}


def ref_maps(geoms: list, known_keep: list, pas: dict, ctx: dict) -> list:
    """Опорный тон невидимого для мерки пятен far_excess: тон группы (у «градиента» — его значение в точке); NaN — вне групп (остаётся тон своей части)."""
    maps = ctx['maps']
    byid = {g['id']: g for g in pas['groups'] if g.get('applied')}
    out = []
    for gi in range(len(geoms)):
        T = maps.T[gi]
        ref = np.full((T, T, 3), np.nan)
        gm = _gmap_ctx(ctx, gi)
        k0 = np.asarray(known_keep[gi], bool)
        for gid, grp in byid.items():
            m = (gm == gid) & ~k0
            if m.any():
                ref[m] = _tone_arr(grp, ctx, gi, m)
        out.append(ref)
    return out


def measure_slits(geoms: list, tex_after: list, known_keep: list, ctx: dict, R: dict, tf) -> dict:
    """Скачок тона вдоль щелей фасада (владелец TG 1952: «прорези для ящиков — рваный шов»): щель = тонкая тёмная линия (L ниже размытого на slit_dl, не блок тени), полоса ±slit_band_px вокруг неё без самой щели;
    в полосе — граница «фото | заливка»: ΔE00 между средним Lab известной стороны и неизвестной (каждое — нормированное размытие только по СВОЕЙ стороне, без разбавления границей). Медиана и p95 по тексельным парам.
    Основная мерка (`photo`, директор 23.11): щели ТОЛЬКО из известного (фото) — там рельефа задней плиты нет; `all` — как раньше, по любым тёмным линиям (в т.ч. рельеф формы на заду) — информационная, в гейт не ставится."""
    from scipy.ndimage import binary_dilation, binary_opening, gaussian_filter
    maps = ctx['maps']
    mg = R['measure']
    acc = {'photo': [], 'all': []}
    ns = {'photo': 0, 'all': 0}
    for gi, g in enumerate(geoms):
        T = maps.T[gi]
        tex = np.asarray(tex_after[gi])
        lab = tf.rgb2lab(tex[..., :3].reshape(-1, 3)).reshape(T, T, 3)
        occ = maps.ids[gi] >= 0
        k0 = np.asarray(known_keep[gi], bool) & occ
        L = lab[..., 0]
        Dk = occ & (L < _blur_norm(L, occ, float(mg['slit_blur_px'])) - float(mg['slit_dl']))
        S_all = Dk & ~binary_opening(Dk, iterations=3)
        un = occ & ~k0
        Lk = Lu = None                                                    # размытия по своей стороне — по требованию (нужны, только если есть щели с границей фото|заливка)
        for key, S in (('photo', S_all & k0), ('all', S_all)):
            if S.sum() < 20:
                continue
            ns[key] += int(S.sum())
            ring = binary_dilation(S, iterations=int(mg['slit_band_px'])) & ~binary_dilation(S, iterations=int(mg['slit_core_px'])) & occ
            bk = ring & k0 & binary_dilation(un, iterations=1)
            sel = bk & (_den(un, 2.0) > 0.05)
            if sel.any():
                if Lk is None:
                    Lk = _blur_norm(lab, k0, 2.0)
                    Lu = _blur_norm(lab, un, 2.0)
                acc[key].append(_de(Lk[sel], Lu[sel]))
    out = {}
    for key in ('photo', 'all'):
        v = np.concatenate(acc[key]) if acc[key] else np.zeros(0)
        out[key] = {'slit_texels': ns[key], 'pairs': int(len(v)), 'median': round(float(np.median(v)), 2) if len(v) else None, 'p95': round(float(np.quantile(v, 0.95)), 2) if len(v) else None}
    res = dict(out['photo'])
    res['all'] = out['all']
    return res


# ------------------------------------------------------------------------------------------ CLI: проба на готовом выходе 07
def _cli(argv=None) -> int:
    """surface_passport.py probe <filled.glb> <parts.npz> <visible_dir> <out_dir> [--no-apply]: паспорт + мерки «как есть» + (по умолчанию) применение и мерки «после».
    Пишет out_dir/{surface-passport.json, measure-before.json, measure-after.json, after.glb}. Известное — known*.png этапа 6; текстуры filled.glb (известное в них = фото)."""
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['probe'])
    ap.add_argument('glb')
    ap.add_argument('parts_npz')
    ap.add_argument('visible')
    ap.add_argument('out')
    ap.add_argument('--no-apply', action='store_true')
    a = ap.parse_args(argv)
    import tex_fill as TF
    geoms = TC.load_geoms(a.glb)
    parts, _ = TF.parts_from_npz(a.parts_npz, geoms)
    known = TF.load_known_png(a.visible)
    roles = TF.roles_from_parts_json(os.path.join(os.path.dirname(a.parts_npz), 'parts.json'))
    R = TF.RULES['surface_groups']
    tex = [np.asarray(g['tex'])[..., :3] for g in geoms]
    os.makedirs(a.out, exist_ok=True)
    pas, ctx = build(geoms, tex, known, parts, roles, R, TF.FILL, TF)
    json.dump(pas, open(os.path.join(a.out, 'surface-passport.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    k0 = [np.asarray(k, bool) & ~TF.unpainted_mask(np.asarray(t)) for k, t in zip(known, tex)]
    m0 = measure(geoms, tex, k0, pas, ctx, R, TF)
    json.dump(m0, open(os.path.join(a.out, 'measure-before.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('groups:', [(g['id'], g['parts'], g['class'], g.get('tone_lab')) for g in pas['groups']])
    print('before worst:', m0['worst'], 'slits', m0['slits'])
    if not a.no_apply:
        t_after, rg = apply_groups(geoms, tex, k0, pas, ctx, R, TF)
        m1 = measure(geoms, t_after, k0, pas, ctx, R, TF)
        json.dump(dict(m1, apply=rg), open(os.path.join(a.out, 'measure-after.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        TF.write_glb(geoms, t_after, os.path.join(a.out, 'after.glb'))
        print('after worst:', m1['worst'], 'slits', m1['slits'])
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
