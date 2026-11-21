#!/usr/bin/env python3
"""Мерка этапа 7 «слепое продолжение поверхности» (Ш7′, Codex раунд 2 §Б). Это НЕ «точность зада»: проверяем, умеет ли 07 продолжить известную поверхность там, где мы её спрятали.
Правила: фото остаётся для камеры и частей; выбранные тексели видимой части ЗАПРЕЩЕНЫ как доноры 07 (маска known без них; значение в них — «не покрашено», не информация); оценочный участок связный, с отступом
от силуэта, заслонений (неизвестное рядом), границ материала (другая часть) и бликов/теней (выбросы L части); эталон — albedo после 05 в известных текселях (его и несёт 06-visible/visible.glb: фото, перенесённое
после снятия света); цвет не подгоняем. Режимы: local — связный кусок ≈35 % допустимого; far — дальняя половина по оси «на камеру»; side — боковые грани (|n·n_front| < 0,5). Симметрия: mirror вкл и выкл.
  python3 tex_fill_blind.py freeze [--margin N] [--spec-win N] <выход> <корень:метка> [<корень:метка> …]      — посчитать и ЗАМОРОЗИТЬ маски (frozen.json с хешами входов и масок + masks.npz)
  python3 tex_fill_blind.py run <выход> <папка frozen> [--cfg '{…}'] [--tag имя] [--modes far,side] [--source trellis_relief --draft-dir <папка>]   — прогнать 07 на замороженных масках (хеши сверяются; расхождение — отказ), метрики и свод
Метрики на оценочном участке (как в tex_fill_hidden_visible): dE_low (ΔE00 тона), band_ratio (фактура залитого/настоящего, 1 — та же сила, цель ≥0,5 «не гладко»), spec_dist, ori_dist; рисунок: macro_true / macro_fill
(MAD-σ полосы σ_hi…4σ_hi) и pattern_invented — залитое имеет макро-рисунка заметно больше, чем настоящее (выдумано). Бесплатно (процессор), только под heavy-slot."""
from __future__ import annotations

import hashlib
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
import tex_fill_hidden_visible as HV  # noqa: E402
from scipy.ndimage import binary_dilation, binary_erosion, distance_transform_edt, label  # noqa: E402

MODES = ('local', 'far', 'side')
PARAMS = {'margin_px': 6, 'highlight_q': [0.04, 0.96], 'highlight_dilate': 2, 'local_keep_q': 0.65, 'side_cos': 0.5, 'min_blob': 300, 'min_hidden': 800, 'eval_erode': 2, 'seed': 7, 'spec_win': 32}


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


def sha_arr(a: np.ndarray) -> str:
    return hashlib.sha256(np.packbits(np.asarray(a, bool)).tobytes()).hexdigest()


def load_item(root: str, sku: str):
    vis = os.path.join(root, sku, '06-visible')
    geoms = TC.load_geoms(os.path.join(vis, 'visible.glb'))
    known = TF.load_known_png(vis)
    npz = os.path.join(root, sku, '03-parts', 'parts.npz')
    parts, _ = TF.parts_from_npz(npz, geoms) if os.path.exists(npz) else TF.parts_from_geometry(geoms)
    txs = [TF.Tex(g, np.asarray(g['V'], np.float64), TF._grid(g), parts[gi]) for gi, g in enumerate(geoms)]
    return vis, npz, geoms, known, parts, txs


def inputs_hash(root: str, sku: str) -> dict:
    vis = os.path.join(root, sku, '06-visible')
    out = {'visible.glb': sha_file(os.path.join(vis, 'visible.glb'))}
    for i in range(64):
        fp = os.path.join(vis, 'known.png' if i == 0 else f'known{i}.png')
        if not os.path.exists(fp):
            break
        out[os.path.basename(fp)] = sha_file(fp)
    npz = os.path.join(root, sku, '03-parts', 'parts.npz')
    if os.path.exists(npz):
        out['parts.npz'] = sha_file(npz)
    return out


def make_masks(geoms, known, txs) -> dict:
    """→ {'part': p, 'modes': {mode: [bool (T,T) по геометриям] | None}, 'why': {mode: str}} — оценочные (спрятанные) участки."""
    P = PARAMS
    ids = sorted({int(p) for tx in txs for p in np.unique(tx.part)})
    cnt = {p: sum(int((kn.reshape(-1)[tx.ti] & (tx.part == p)).sum()) for kn, tx in zip(known, txs)) for p in ids}
    part = max(cnt, key=cnt.get)
    labs = [TF.rgb2lab(np.asarray(g['tex']).reshape(-1, 3)).reshape(tx.T, tx.T, 3) for g, tx in zip(geoms, txs)]
    Lall = np.concatenate([labs[gi][..., 0].reshape(-1)[tx.ti][known[gi].reshape(-1)[tx.ti] & (tx.part == part)] for gi, tx in enumerate(txs)])
    lo, hi = np.quantile(Lall, P['highlight_q'])
    elig = []
    for gi, tx in enumerate(txs):
        T = tx.T
        pm = np.zeros(T * T, bool)
        pm[tx.ti[tx.part == part]] = True
        pk = (pm & known[gi].reshape(-1)).reshape(T, T)                    # известное и своей части
        core = distance_transform_edt(pk) >= P['margin_px']                # отступ от силуэта/заслонения (неизвестное рядом) и границы материала (другая часть)
        L = labs[gi][..., 0]
        bad = binary_dilation((L < lo) | (L > hi), iterations=P['highlight_dilate'])      # блики и тени своей части
        elig.append(core & ~bad)
    Qall = np.concatenate([tx.Q for tx in txs])
    sg = np.concatenate([np.where((tx.Q * tx.N).sum(1) >= 0, 1.0, -1.0) for tx in txs])
    Nout = np.concatenate([tx.N for tx in txs]) * sg[:, None]
    kk = np.concatenate([known[gi].reshape(-1)[tx.ti] & (tx.part == part) for gi, tx in enumerate(txs)])
    nf = Nout[kk].mean(axis=0)
    nf /= max(np.linalg.norm(nf), 1e-9)                                    # ось «на камеру»: средняя нормаль известного
    ek = np.concatenate([elig[gi].reshape(-1)[tx.ti] for gi, tx in enumerate(txs)])
    rng = np.random.RandomState(P['seed'])
    d = rng.normal(size=3)
    d /= np.linalg.norm(d)
    modes, why = {}, {}
    for mode in MODES:
        if ek.sum() < 2 * P['min_hidden']:
            modes[mode], why[mode] = None, f'допустимых текселей {int(ek.sum())} — мало'
            continue
        if mode == 'local':
            pr = Qall @ d
            hid = ek & (pr > np.quantile(pr[ek], P['local_keep_q']))
        elif mode == 'far':
            pr = Qall @ nf
            hid = ek & (pr <= np.median(pr[ek]))
        else:
            hid = ek & (np.abs(Nout @ nf) < P['side_cos'])
        o, ms, tot = 0, [], 0
        for gi, tx in enumerate(txs):
            h = np.zeros(tx.T * tx.T, bool)
            h[tx.ti[hid[o:o + len(tx.ti)]]] = True
            o += len(tx.ti)
            h = h.reshape(tx.T, tx.T)
            lab_, n = label(h)                                             # связные куски: мелкие (< min_blob) — не оценочные
            if n:
                sz = np.bincount(lab_.ravel())
                keep = sz >= P['min_blob']
                keep[0] = False
                h = keep[lab_]
            ms.append(h)
            tot += int(h.sum())
        if tot < P['min_hidden']:
            modes[mode], why[mode] = None, f'спрятанных связных {tot} < {P["min_hidden"]}'
        else:
            modes[mode], why[mode] = ms, f'спрятано {tot} текселей из допустимых {int(ek.sum())}'
    return {'part': int(part), 'modes': modes, 'why': why, 'front_axis': [round(float(x), 4) for x in nf]}


def _opts(a: list) -> list:
    """--margin N (отступ, текс.) и --spec-win N (окно спектра) до <выход>; пишутся в frozen.json и возвращаются при run."""
    while len(a) > 2 and a[0] in ('--margin', '--spec-win'):
        PARAMS['margin_px' if a[0] == '--margin' else 'spec_win'] = int(a[1])
        a = a[2:]
    return a


def cmd_freeze(argv: list) -> int:
    argv = _opts(list(argv))
    out, items = argv[0], argv[1:]
    fd = os.path.join(out, 'frozen')
    os.makedirs(fd, exist_ok=True)
    fz, arrs = {'params': PARAMS, 'code_sha256': sha_file(os.path.join(HERE, 'tex_fill.py')), 'tool_sha256': sha_file(os.path.abspath(__file__)), 'items': []}, {}
    for it in items:
        root, sku = it.rsplit(':', 1)
        _, _, geoms, known, parts, txs = load_item(root, sku)
        m = make_masks(geoms, known, txs)
        rec = {'root': root, 'sku': sku, 'part': m['part'], 'front_axis': m['front_axis'], 'inputs': inputs_hash(root, sku), 'modes': {}}
        for mode, ms in m['modes'].items():
            if ms is None:
                rec['modes'][mode] = {'skipped': m['why'][mode]}
                continue
            rec['modes'][mode] = {'why': m['why'][mode], 'sha256': [sha_arr(x) for x in ms], 'texels': [int(x.sum()) for x in ms]}
            for gi, x in enumerate(ms):
                arrs[f'{sku}|{mode}|{gi}'] = np.packbits(x)
                arrs[f'{sku}|{mode}|{gi}|shape'] = np.array(x.shape)
        fz['items'].append(rec)
        print(sku, 'часть', m['part'], {k: v for k, v in m['why'].items()}, flush=True)
    np.savez_compressed(os.path.join(fd, 'masks.npz'), **arrs)
    fz['masks_npz_sha256'] = sha_file(os.path.join(fd, 'masks.npz'))
    with open(os.path.join(fd, 'frozen.json'), 'w', encoding='utf-8') as f:
        json.dump(fz, f, ensure_ascii=False, indent=1)
    print('заморожено:', fd, 'masks.npz', fz['masks_npz_sha256'][:16])
    return 0


def macro_sigma(lab_l: np.ndarray, mask: np.ndarray, s_hi: float) -> float:
    return float(TF._mad_sigma(TF._band(lab_l, mask, s_hi, 4.0 * s_hi)[0][mask]))


def cmd_run(argv: list) -> int:
    cfg0, tag, a = {}, 'now', list(argv)
    modes_only, source, draft_dir = None, None, None
    while len(a) > 2 and a[0].startswith('--'):
        if a[0] == '--cfg':
            cfg0 = json.loads(a[1])
        elif a[0] == '--tag':
            tag = a[1]
        elif a[0] == '--modes':                       # напр. far,side — для вариантов с черновиком TRELLIS (в «локальном куске» черновик видел фото → утечка)
            modes_only = a[1].split(',')
        elif a[0] == '--source':                      # stat | trellis | trellis_relief
            source = a[1]
        elif a[0] == '--draft-dir':                   # папка черновиков TRELLIS: <метка>-1024-42-0.glb
            draft_dir = a[1]
        a = a[2:]
    out, fd = a[0], a[1]
    fz = json.load(open(os.path.join(fd, 'frozen.json'), encoding='utf-8'))
    PARAMS.update(fz['params'])                                                # параметры заморозки (v1 без spec_win → 32)
    _orig_spec = HV.spec_signature
    HV.spec_signature = lambda lum, mask, rng, win=PARAMS['spec_win'], n=24: _orig_spec(lum, mask, rng, win, n)
    mp = os.path.join(fd, 'masks.npz')
    if sha_file(mp) != fz['masks_npz_sha256']:
        print('ОТКАЗ: masks.npz изменён (хеш не совпал)')
        return 3
    Z = np.load(mp)
    os.makedirs(out, exist_ok=True)
    recs, bad = [], 0
    for it in fz['items']:
        root, sku = it['root'], it['sku']
        try:
            if inputs_hash(root, sku) != it['inputs']:
                raise RuntimeError('входы товара изменились после заморозки (хеш)')
            vis, npz, geoms, known, parts, txs = load_item(root, sku)
            cfgb, _pcn = TF.resolve_part_class(dict(cfg0, source='trellis_relief') if cfg0.get('part_class') is None else cfg0, npz if os.path.exists(npz) else None, os.path.exists(npz))
            cfgb = {k: v for k, v in cfgb.items() if k != 'source'}
            labs_true = [TF.rgb2lab(np.asarray(g['tex']).reshape(-1, 3)).reshape(tx.T, tx.T, 3) for g, tx in zip(geoms, txs)]
            part = it['part']
            spac = float(np.median(np.concatenate([TF.texel_spacing(tx)[tx.part == part] for tx in txs])))
            R = TF.RULES['trellis_relief']
            s_lo = float(np.clip(R['band_lo'] / spac, R['sigma_lo_min'], R['sigma_lo_max']))
            s_hi = float(np.clip(R['band_hi'] / spac, 2.0 * s_lo, R['sigma_hi_max']))
            draft_g = None
            if source in ('trellis', 'trellis_relief'):
                dgp = os.path.join(draft_dir, f'{sku.split(":")[-1]}-1024-42-0.glb')
                if not os.path.exists(dgp):
                    raise RuntimeError(f'нет черновика {dgp}')
                draft_g = TC.load_geoms(dgp)
            for mode, md in it['modes'].items():
                if 'skipped' in md or (modes_only and mode not in modes_only):
                    continue
                hidden = []
                for gi, tx in enumerate(txs):
                    k = f'{sku}|{mode}|{gi}'
                    shp = tuple(Z[k + '|shape'])
                    h = np.unpackbits(Z[k])[:shp[0] * shp[1]].astype(bool).reshape(shp)
                    if sha_arr(h) != md['sha256'][gi]:
                        raise RuntimeError(f'маска {mode}/{gi}: хеш не совпал')
                    hidden.append(h)
                geoms_h, kn_h = [], []
                for gi, g in enumerate(geoms):
                    tex = np.asarray(g['tex']).copy()
                    tex[hidden[gi]] = 0                                  # спрятанное — «не покрашено»; донором не служит (kn_h)
                    geoms_h.append(dict(g, tex=tex))
                    kn_h.append(known[gi] & ~hidden[gi])
                for sym in (True, False):
                    cfg = dict({'erode_known': 0}, **cfgb)
                    dr = None
                    if draft_g is not None:
                        cfg['source'] = source
                        dr = TF.draft_texels(geoms_h, draft_g, cfg)
                    res = TF.fill(geoms_h, kn_h, parts, cfg=cfg, mirror=sym, draft=dr)
                    agg = {}
                    for gi, tx in enumerate(txs):
                        ev = binary_erosion(hidden[gi], iterations=PARAMS['eval_erode'])
                        if ev.sum() < 100:
                            continue
                        lf = TF.rgb2lab(res['tex'][gi].reshape(-1, 3)).reshape(tx.T, tx.T, 3)
                        mt = HV.metrics_hidden(lf, labs_true[gi], ev, s_lo, s_hi, np.random.RandomState(PARAMS['seed']))
                        mt['macro_true'] = macro_sigma(labs_true[gi][..., 0], ev, s_hi)
                        mt['macro_fill'] = macro_sigma(lf[..., 0], ev, s_hi)
                        for kx, v in mt.items():
                            if v is not None:
                                agg.setdefault(kx, []).append((v, int(ev.sum())))
                    rec = {'sku': sku, 'part': part, 'mode': mode, 'mirror': sym, 'hidden_texels': int(sum(int(h.sum()) for h in hidden)), 'tag': tag}
                    for kx, v in agg.items():
                        rec[kx] = round(sum(x * w for x, w in v) / sum(w for _, w in v), 4)
                    if 'macro_true' in rec:
                        rec['pattern_invented'] = bool(rec['macro_fill'] > 1.5 * rec['macro_true'] + 0.5)
                    rec['no_patch'] = res['report'].get('no_patch')
                    recs.append(rec)
                    print(json.dumps(rec, ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001 — один сбой не рушит пакет, счётчик отказов в итоге
            bad += 1
            recs.append({'sku': sku, 'error': f'{type(e).__name__}: {e}'})
            print(json.dumps(recs[-1], ensure_ascii=False), flush=True)
    with open(os.path.join(out, f'blind-{tag}.jsonl'), 'w', encoding='utf-8') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    good = [r for r in recs if 'error' not in r]
    lines = [f'метка {tag} · код tex_fill {sha_file(os.path.join(HERE, "tex_fill.py"))[:12]} (заморожено на {fz["code_sha256"][:12]}) · записей {len(good)} · ошибок {bad}',
             'режим · симметрия · n · dE_low (меньше лучше) · band_ratio (цель ≥0,5; 1 — как фото) · доля band_ratio≥0,5 · spec_dist · ori_dist · macro заливка/фото · выдуман рисунок']
    for mode in MODES:
        for sym in (True, False):
            rs = [r for r in good if r['mode'] == mode and r['mirror'] == sym]
            if not rs:
                continue
            mean = lambda k: float(np.mean([r[k] for r in rs if r.get(k) is not None])) if any(r.get(k) is not None for r in rs) else float('nan')  # noqa: E731
            lines.append(f"{mode:<5} · зеркало {'вкл ' if sym else 'выкл'} · n={len(rs)} · dE_low {mean('dE_low'):5.2f} · band {mean('band_ratio'):4.2f} · ≥0,5: {100 * np.mean([r['band_ratio'] >= 0.5 for r in rs]):3.0f} % · spec {mean('spec_dist'):5.3f} · ori {mean('ori_dist'):5.3f} · macro {mean('macro_fill'):4.2f}/{mean('macro_true'):4.2f} · выдуман {100 * np.mean([bool(r.get('pattern_invented')) for r in rs]):3.0f} %")
    txt = '\n'.join(lines)
    with open(os.path.join(out, f'summary-{tag}.txt'), 'w', encoding='utf-8') as f:
        f.write(txt + '\n')
    print(txt)
    return 1 if bad else 0


def main(argv: list) -> int:
    if len(argv) >= 3 and argv[0] == 'freeze':
        return cmd_freeze(argv[1:])
    if len(argv) >= 3 and argv[0] == 'run':
        return cmd_run(argv[1:])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
