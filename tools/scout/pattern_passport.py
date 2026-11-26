#!/usr/bin/env python3
"""T-99/12 шаг 1 (Fable 19 §2): «паспорт рисунка» дерева — три числа, сравнение НАША / ФОТО на одной грани, размеры в сантиметрах товара.
  ясность линий     — местная согласованность направления (1 — чёткие линии волокон, 0 — шум); медиана по грани
  длина штриха      — сдвиг ВДОЛЬ волокна (см), на котором рисунок перестаёт быть похож сам на себя (автокорреляция < corr_min)
  доля крупного     — доля энергии рисунка в деталях крупнее coarse_from_cm (полосы и дуги, а не только рябь)
Четвёртым числом остаётся старая «сила» (σ мелкого рисунка; paint_t99 / part_grain.photo_hf_sigma) — не главное.
Пороги (наша/фото) — rules/pattern-passport.json, стартовые (Fable 19: названы по двум товарам, проверить на 7–8 столах). ID товаров в коде нет.
Считать только на гранях, которые фото видит в лоб (cos ≥ …), по фото без теней (этап 05, если есть) — иначе тень под столешницей сойдёт за «дугу».
  pattern_passport.py measure <run> <photo.rgba.png> <glb> [--tag имя] [--json out.json] [--card-px-per-cm N]   фото против нашей текстуры в кадре камеры 04, по частям (верх плиты / кромка / тумба)
Модуль без побочных эффектов: чистые функции (passport / ratios / verdict) используют шаг 2 (выбор образца по рисунку) и отчёты."""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def load_rules(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, 'rules', 'pattern-passport.json'), encoding='utf-8') as f:
        return json.load(f)


def _s(cm: float, ppc: float) -> float:
    return max(0.5, float(cm) * float(ppc))                          # меньше полпикселя размытие бессмысленно


def _nblur(L, m, s):
    import cv2
    a = cv2.GaussianBlur(L * m, (0, 0), s)
    b = cv2.GaussianBlur(m, (0, 0), s)
    return a / np.maximum(b, 1e-3)


def clarity(L, er, ppc: float, R: dict) -> tuple:
    """(взвешенная, медиана) местной согласованности направления по маске er."""
    import cv2
    c = R['clarity']
    L = np.asarray(L, np.float32)
    hf = cv2.GaussianBlur(L, (0, 0), _s(c['hf_sigma_cm'][0], ppc)) - cv2.GaussianBlur(L, (0, 0), _s(c['hf_sigma_cm'][1], ppc))
    gx = cv2.Sobel(hf, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(hf, cv2.CV_32F, 0, 1, ksize=3)
    w_ = _s(c['win_cm'], ppc)
    a = cv2.GaussianBlur(gx * gx, (0, 0), w_)
    b = cv2.GaussianBlur(gy * gy, (0, 0), w_)
    cc = cv2.GaussianBlur(gx * gy, (0, 0), w_)
    coh = np.hypot(a - b, 2 * cc) / np.maximum(a + b, 1e-9)
    w = (a + b)[er]
    return float((coh[er] * w).sum() / max(float(w.sum()), 1e-9)), float(np.median(coh[er]))


def stroke_cm(L, m, er, ang_deg: float, ppc: float, R: dict) -> tuple:
    """(вдоль, поперёк) — сдвиг в см, где автокорреляция мелкого рисунка падает ниже corr_min (до maxlag_cm)."""
    import cv2
    c = R['stroke']
    mf = m.astype(np.float32)
    L = np.asarray(L, np.float32)
    hf = _nblur(L, mf, _s(c['hf_sigma_cm'][0], ppc)) - _nblur(L, mf, _s(c['hf_sigma_cm'][1], ppc))
    hf = np.where(er, hf, 0).astype(np.float32)
    erf = er.astype(np.float32)
    maxlag = max(2, int(round(float(c['maxlag_cm']) * ppc)))
    res = []
    for a in (ang_deg, ang_deg + 90.0):
        dx, dy = np.cos(np.radians(a)), -np.sin(np.radians(a))
        got = None
        for lag in range(1, maxlag + 1):
            M = np.float32([[1, 0, dx * lag], [0, 1, dy * lag]])
            sh = cv2.warpAffine(hf, M, (hf.shape[1], hf.shape[0]), flags=cv2.INTER_LINEAR)
            ms = cv2.warpAffine(erf, M, (hf.shape[1], hf.shape[0]), flags=cv2.INTER_NEAREST) > 0.5
            k = er & ms
            if int(k.sum()) < int(c['min_pairs']):
                break
            x, y = hf[k], sh[k]
            r = float((x * y).mean() / max(np.sqrt((x * x).mean() * (y * y).mean()), 1e-9))
            if r < float(c['corr_min']):
                got = lag
                break
        res.append(round((got if got is not None else maxlag) / ppc, 2))
    return res[0], res[1]


def coarse_share(L, m, er, ppc: float, R: dict) -> tuple:
    """(доля энергии крупнее coarse_from_cm, энергии по полосам) — полосы: разность размытий σ и 2σ (нормированная свёртка в маске)."""
    mf = m.astype(np.float32)
    L = np.asarray(L, np.float32)
    bands = [float(x) for x in R['bands_cm']]
    en = []
    for s_cm in bands:
        d = _nblur(L, mf, _s(s_cm, ppc)) - _nblur(L, mf, _s(2 * s_cm, ppc))
        en.append(float(d[er].std()))
    e2 = np.asarray(en) ** 2
    big = np.asarray([b >= float(R['coarse_from_cm']) - 1e-9 for b in bands])
    return float(e2[big].sum() / max(float(e2.sum()), 1e-12)), en


def dominant_angle(L, er, R: dict) -> tuple:
    """Угол волокна (град, 0 = вправо, 90 = вертикально) и когерентность по структурному тензору мелкого рисунка (волокно ⟂ градиенту)."""
    import cv2
    L = np.asarray(L, np.float32)
    hf = cv2.GaussianBlur(L, (0, 0), 1.5) - cv2.GaussianBlur(L, (0, 0), 6.0)
    gx = cv2.Sobel(hf, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(hf, cv2.CV_32F, 0, 1, ksize=3)
    a, b, c = float((gx * gx)[er].sum()), float((gy * gy)[er].sum()), float((gx * gy)[er].sum())
    th = 0.5 * np.degrees(np.arctan2(2 * c, a - b))
    return float((th + 90.0) % 180.0), float(np.hypot(a - b, 2 * c) / max(a + b, 1e-9))


def passport(L, mask, ppc: float, ang_deg: float | None, R: dict) -> dict | None:
    """Паспорт рисунка по яркости L в маске: {clarity, clarity_w, stroke_cm, stroke_across_cm, coarse, angle, n_px}; мало пикселей → None."""
    import cv2
    m = np.asarray(mask, bool)
    k = int(R['erode_px'])
    er = cv2.erode(m.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
    if int(er.sum()) < int(R['min_px']):
        return None
    L = np.asarray(L, np.float32)
    ang = dominant_angle(L, er, R)[0] if ang_deg is None else float(ang_deg)
    cw, cmed = clarity(L, er, ppc, R)
    sa, sx = stroke_cm(L, m, er, ang, ppc, R)
    cs, _en = coarse_share(L, m, er, ppc, R)
    return {'clarity': round(cmed, 3), 'clarity_w': round(cw, 3), 'stroke_cm': sa, 'stroke_across_cm': sx, 'coarse': round(cs, 3), 'angle': round(ang, 1), 'n_px': int(er.sum())}


def ratios(ours: dict | None, photo: dict | None) -> dict | None:
    """наша/фото по трём числам паспорта (нет данных → None)."""
    if not ours or not photo:
        return None
    return {'clarity': round(ours['clarity'] / max(photo['clarity'], 1e-6), 3), 'stroke': round(ours['stroke_cm'] / max(photo['stroke_cm'], 1e-6), 3),
            'coarse': round(ours['coarse'] / max(photo['coarse'], 1e-6), 3)}


def verdict(rt: dict | None, R: dict) -> dict:
    """Вердикт против целей rules.targets: {ok, parts{clarity, stroke, coarse}}; нет чисел → ok None (не «ок»)."""
    if not rt:
        return {'ok': None, 'parts': {}, 'why': 'нет паспорта (мало пикселей грани)'}
    t = R['targets']
    parts = {k: bool(rt[k] >= float(t[k])) for k in ('clarity', 'stroke', 'coarse')}
    return {'ok': all(parts.values()), 'parts': parts, 'targets': dict(t)}


def distance(a: dict, b: dict, R: dict) -> float:
    """Расстояние между двумя паспортами (для выбора образца библиотеки по рисунку фото): сумма |ln(a/b)| по трём числам с весами rules.pick.weights."""
    w = R['pick']['weights']
    d = 0.0
    for key, name in (('clarity', 'clarity'), ('stroke_cm', 'stroke'), ('coarse', 'coarse')):
        d += float(w[name]) * abs(float(np.log(max(a[key], 1e-3) / max(b[key], 1e-3))))
    return d


# ------------------------------------------------------------------ CLI: фото против нашей текстуры в кадре камеры 04 ----------------------------------
def _measure(run: str, photo: str, glb: str, tag: str, ppc_photo: float | None):
    sys.path[:0] = [HERE, os.path.join(HERE, 'salad', 'trellis')]
    import tex_coverage as TC
    import tex_visible as TV
    import paint_t99_checks as C
    from PIL import Image
    R = load_rules()
    geoms = TV.load_shape(glb)
    st = TV.load_stage(run)
    st, _ = TV.zbuffer_fix(geoms, st)
    g = geoms[0]
    V, F = np.asarray(g['V'], np.float64), np.asarray(g['F'], np.int64)
    n3 = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n3 = n3 / np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    ph = np.asarray(Image.open(photo).convert('RGBA'))
    prgb, okp = TV.photo_to_frame(ph, st['P'], st['px'])
    px = int(st['px'])
    Lp = TC.rgb2lab(prgb.reshape(-1, 3)).reshape(px, px, 3)[..., 0]
    ours = TV.frame_from_tex(st, geoms, [np.asarray(g['tex'])[..., :3].astype(np.uint8)])
    Lo = TC.rgb2lab(ours.reshape(-1, 3)).reshape(px, px, 3)[..., 0]
    ids = st['ids']
    fid = np.clip(ids, 0, len(F) - 1)
    valid = st['mask'] & okp & (ids >= 0)
    T = int(np.asarray(g['tex']).shape[0])
    _i, _s, _v, plate = C.face_classes(g, T)
    cls = np.where(plate, np.where(np.abs(n3[:, 1]) > 0.8, 0, 1), 2)
    gpix = np.where(valid, cls[fid], -1)
    if ppc_photo is None:
        pj = os.path.join(run, '06-visible', 'part_material.json')
        ppc_photo = float(json.load(open(pj, encoding='utf-8')).get('px_per_cm') or 0) if os.path.exists(pj) else 0.0
    if not ppc_photo:
        raise SystemExit('нет px_per_cm (part_material.json) — задать --card-px-per-cm')
    ppc = ppc_photo * px / float(max(ph.shape[0], ph.shape[1]))
    out = {'кадр_px': px, 'px_на_см_фото': ppc_photo, 'px_на_см_кадра': round(ppc, 2), 'rules': 'pattern-passport.json'}
    for k, (nm, cos_min) in enumerate((('плита-верх', None), ('плита-кромка', 0.3), ('тумба', 0.5))):
        m = (gpix == k)
        m = m & (np.abs(n3[fid, 1]) > 0.8) if cos_min is None else m & (st['cos'] >= cos_min)
        er0 = m
        pp = passport(Lp, m, ppc, None, R)
        if pp is None:
            out[nm] = {'вывод': 'мало пикселей грани в лоб', 'пикселей': int(er0.sum())}
            continue
        po = passport(Lo, m, ppc, pp['angle'], R)                     # наша — вдоль того же угла волокна, что нашло фото
        rt = ratios(po, pp)
        out[nm] = {'фото': pp, 'наша': po, 'наша/фото': rt, 'вердикт': verdict(rt, R)}
    return {tag: out}


def main(argv: list | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if len(a) >= 4 and a[0] == 'measure':
        tag = a[a.index('--tag') + 1] if '--tag' in a else os.path.basename(a[3])
        ppc = float(a[a.index('--card-px-per-cm') + 1]) if '--card-px-per-cm' in a else None
        res = _measure(a[1], a[2], a[3], tag, ppc)
        if '--json' in a:
            with open(a[a.index('--json') + 1], 'w', encoding='utf-8') as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
