"""«Владелец текселя» (вариант А, шаги 5–6, T-20261126-97/1 фаза 2; правила — rules/tex-owner.json, стадия — tex_owner_stage.py).

ЗАЧЕМ. Ш4а красит группу ровным тоном по ГРАНЯМ, у которых группа проставлена; грани без роли и грани с чужой роли внутри плоской панели оставляют в развёртке куски старого цвета,
а на границах островов грань задевает тексель соседнего острова и берёт ЧУЖОЙ цвет (крап). Здесь: (5) роль панели и смежных граней, (6) у каждого текселя один владелец-грань
и отступ только на тексели, которых не покрывает ни одна грань. Расчёт — чистые функции (numpy/cv2/scipy), без GLB; чтение/запись GLB — внизу.

Порядок на конвейере: 06 → Ш4а (part_material_stage) → ЭТОТ ШАГ → зерно (part_grain_stage) → 07. Перенос из ~/remlab-logs/t94/mkD9dir.py без смены поведения."""
from __future__ import annotations

import io
import json
import struct

import cv2
import numpy as np
from PIL import Image


# ───────────────────────────── GLB ─────────────────────────────

def read_glb(path: str) -> tuple[dict, bytes]:
    raw = open(path, 'rb').read()
    off, js, binb = 12, None, b''
    while off < len(raw):
        cl, ct = struct.unpack('<II', raw[off:off + 8])
        ch = raw[off + 8:off + 8 + cl]
        if ct == 0x4E4F534A:
            js = json.loads(ch.decode('utf-8'))
        elif ct == 0x004E4942:
            binb = ch
        off += 8 + cl
    return js, binb


def tex_of(js: dict, binb: bytes, i: int = 0) -> np.ndarray:
    bv = js['bufferViews'][js['images'][i]['bufferView']]
    o = bv.get('byteOffset', 0)
    return np.asarray(Image.open(io.BytesIO(binb[o:o + bv['byteLength']])).convert('RGB'), np.uint8)


def write_glb_with_tex(src: str, tex: np.ndarray, dst: str, i: int = 0) -> None:
    """GLB как src, но baseColor-текстура заменена (PNG дописан в конец бинарника; остальное — как было)."""
    js, binb = read_glb(src)
    buf = io.BytesIO()
    Image.fromarray(tex).save(buf, 'PNG')
    data = buf.getvalue()
    binb = binb + b'\0' * ((-len(binb)) % 4)
    off = len(binb)
    binb = binb + data + b'\0' * ((-len(data)) % 4)
    bv = js['bufferViews'][js['images'][i]['bufferView']]
    bv['byteOffset'] = off
    bv['byteLength'] = len(data)
    js['buffers'][0]['byteLength'] = len(binb)
    j = json.dumps(js, separators=(',', ':')).encode('utf-8')
    j += b' ' * ((-len(j)) % 4)
    with open(dst, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(j) + 8 + len(binb)))
        f.write(struct.pack('<II', len(j), 0x4E4F534A) + j)
        f.write(struct.pack('<II', len(binb), 0x004E4942) + binb)


def read_geom(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """→ (вершины P, UV, грани F) всех примитивов подряд (индексы граней сдвинуты на число вершин прежних примитивов)."""
    js, binb = read_glb(path)
    Vs, UVs, Fs, base = [], [], [], 0
    for mesh in js['meshes']:
        for pr in mesh['primitives']:
            def acc(i):
                a = js['accessors'][i]
                bv = js['bufferViews'][a['bufferView']]
                o = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
                ct_ = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}[a['componentType']]
                n = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}[a['type']]
                return np.frombuffer(binb, ct_, a['count'] * n, o).reshape(-1, n) if n > 1 else np.frombuffer(binb, ct_, a['count'], o)
            P = acc(pr['attributes']['POSITION'])
            UV = acc(pr['attributes']['TEXCOORD_0'])
            F = acc(pr['indices']).reshape(-1, 3).astype(np.int64)
            Vs.append(P)
            UVs.append(UV)
            Fs.append(F + base)
            base += len(P)
    return np.concatenate(Vs), np.concatenate(UVs), np.concatenate(Fs)


# ───────────────────────────── шаг 5: роль панели ─────────────────────────────

def _welded(P: np.ndarray, F: np.ndarray, weld_scale: float) -> tuple[np.ndarray, int]:
    key = np.round(P.astype(np.float64) * weld_scale).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    Fw = inv.reshape(-1)[F]
    return Fw, int(Fw.max()) + 1


def _edge_pairs(Fw: np.ndarray, nv: int) -> tuple[np.ndarray, np.ndarray]:
    """Пары граней с общим ребром (вершины сварены по позиции) → (f1, f2)."""
    nf = len(Fw)
    e = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    fi = np.concatenate([np.arange(nf)] * 3)
    k = e.min(axis=1).astype(np.int64) * nv + e.max(axis=1)
    o = np.argsort(k, kind='stable')
    ks, fs = k[o], fi[o]
    same = ks[1:] == ks[:-1]
    return fs[:-1][same], fs[1:][same]


def panels(P: np.ndarray, F: np.ndarray, crease_deg: float, weld_scale: float) -> tuple[int, np.ndarray]:
    """Плоские панели: связные куски граней по общему ребру с углом нормалей < crease_deg (вершины сварены по позиции). → (число панелей, панель на грань)."""
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components
    Fw, nv = _welded(P, F, weld_scale)
    a, b, c = P[F[:, 0]].astype(np.float64), P[F[:, 1]].astype(np.float64), P[F[:, 2]].astype(np.float64)
    n = np.cross(b - a, c - a)
    n = n / np.maximum(np.linalg.norm(n, axis=1), 1e-20)[:, None]
    f1, f2 = _edge_pairs(Fw, nv)
    ok = (n[f1] * n[f2]).sum(axis=1) > np.cos(np.radians(crease_deg))
    f1, f2 = f1[ok], f2[ok]
    g = sparse.coo_matrix((np.ones(len(f1), np.int8), (f1, f2)), shape=(len(F), len(F)))
    return connected_components(g, directed=False)


def face_roles(P: np.ndarray, F: np.ndarray, fg: np.ndarray, nrole: int, rules: dict) -> tuple[np.ndarray, dict]:
    """Роль каждой грани: (D3) без роли — роль большинства своей панели; (D4) чужая роль, если чужих ≤ alien_max_frac граней панели — большинство панели;
    (D5) остаток (панель без единой грани с ролью) — голосом смежных граней по сетке, волнами. → (роль на грань (−1 — нет), счётчики для отчёта)."""
    from scipy import sparse
    rr = rules['roles']
    ncomp, comp = panels(P, F, float(rr['crease_deg']), float(rr['weld_scale']))
    fg = np.asarray(fg).astype(int)
    cm = np.zeros((ncomp, nrole), np.int64)
    for g in range(nrole):
        cm[:, g] = np.bincount(comp[fg == g], minlength=ncomp)
    has = cm.sum(axis=1) > 0
    rm = np.full(ncomp, -1)
    rm[has] = cm[has].argmax(axis=1)
    fg2 = fg.copy()
    nr = (fg < 0) | (fg >= nrole)
    fg2[nr] = rm[comp[nr]]
    tot = np.bincount(comp, minlength=ncomp)
    alien = (~nr) & (fg2 >= 0) & (fg2 < nrole) & (fg2 != rm[comp]) & (cm[comp, fg2.clip(0, nrole - 1)] <= float(rr['alien_max_frac']) * tot[comp])
    fg2[alien] = rm[comp[alien]]
    Fw, nv = _welded(P, F, float(rr['weld_scale']))
    f1, f2 = _edge_pairs(Fw, nv)
    nf = len(F)
    A = sparse.coo_matrix((np.ones(len(f1) * 2, np.float32), (np.concatenate([f1, f2]), np.concatenate([f2, f1]))), shape=(nf, nf)).tocsr()
    waves = 0
    while True:
        un = (fg2 < 0) | (fg2 >= nrole)
        if not un.any():
            break
        oh = np.zeros((nf, nrole), np.float32)
        lab_ = ~un
        oh[np.nonzero(lab_)[0], fg2[lab_]] = 1
        votes = A @ oh
        take = un & (votes.sum(1) > 0)
        if not take.any():
            break
        fg2[take] = votes[take].argmax(1)
        waves += 1
    info = {'панелей': int(ncomp), 'граней_без_роли': int(nr.sum()), 'чужих_граней_на_панелях_других_ролей': int(alien.sum()), 'волн_по_сетке': waves,
            'без_роли_осталось': int(((fg2 < 0) | (fg2 >= nrole)).sum())}
    return fg2, info


# ───────────────────────────── шаг 6: владелец текселя ─────────────────────────────

def owner_ids(UV: np.ndarray, F: np.ndarray, T: int, rules: dict) -> np.ndarray:
    """Грань-владелец каждого текселя (−1 — не покрыт ни одной гранью): проход 1 — все грани «жирно» по порядку (последняя нарисованная владеет спорным пограничным тексель);
    проход 2 — ВНУТРЕННОСТЬ каждой грани (вершины сжаты к центру на shrink_texel) перекрывает: тексель внутри грани — её, а не соседа."""
    ow = rules['owner']
    sh = int(ow['raster_bits'])
    k = float(1 << sh)
    shrink = float(ow['shrink_texel'])
    ids = np.full((T, T), -1, np.int32)
    tri_uv = UV[F].astype(np.float64) * T
    for f in range(len(F)):
        cv2.fillConvexPoly(ids, np.round(tri_uv[f] * k).astype(np.int32), int(f), lineType=cv2.LINE_8, shift=sh)
    cen_uv = tri_uv.mean(1, keepdims=True)
    v = tri_uv - cen_uv
    ln = np.maximum(np.linalg.norm(v, axis=2, keepdims=True), 1e-9)
    shr = cen_uv + v * np.maximum(ln - shrink, 0.0) / ln
    big = np.linalg.norm(v, axis=2).max(1) > shrink
    for f in np.nonzero(big)[0]:
        cv2.fillConvexPoly(ids, np.round(shr[f] * k).astype(np.int32), int(f), lineType=cv2.LINE_8, shift=sh)
    return ids


def apply_owner(tex: np.ndarray, gmap: np.ndarray, ids: np.ndarray, fg2: np.ndarray, painted_group: np.ndarray, tone: np.ndarray, names: list, rules: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    """Тексели граней покрашенной группы + отступ pad_px×pad_px ТОЛЬКО на непокрытые гранями тексели = тон группы Ш4а; group_map расширен тем же. Узорные группы (painted_group=False) не трогаем.
    → (новая текстура, новая group_map, по группам: тексели владельца / с отступом / в group_map было→стало)."""
    pad = int(rules['owner']['pad_px'])
    ker = np.ones((pad, pad), np.uint8)
    out, gm = tex.copy(), gmap.copy()
    allcov = ids >= 0
    role_tex = np.where(allcov, fg2[np.clip(ids, 0, len(fg2) - 1)], -1)
    per = {}
    for g in range(len(names)):
        if not painted_group[g]:
            continue
        rg = role_tex == g
        full = rg | (cv2.dilate(rg.astype(np.uint8), ker).astype(bool) & ~allcov)
        out[full] = tone[g]
        before = int((gm == g).sum())
        gm[full] = g
        per[names[g]] = {'тексели_владельца': int(rg.sum()), 'с_отступом': int(full.sum()), 'в_group_map_было': before, 'стало': int((gm == g).sum())}
    return out, gm, per


# ───────────────────────────── шаг 7: дилатация (поле вокруг островов) ─────────────────────────────

def dilate_gutter(tex: np.ndarray, ids: np.ndarray, px: int) -> tuple[np.ndarray, int]:
    """Непокрытые гранями тексели в пределах px от покрытых берут цвет БЛИЖАЙШЕГО покрытого (EDT с индексами); покрытые не меняются ни на байт. px=0 — ничего. → (текстура, число перекрашенных текселей).
    Зачем: при линейной выборке на границе острова видеокарта подмешивает тексель соседнего поля — оно должно быть цвета острова, а не чужого/заполнителя."""
    if px <= 0:
        return tex, 0
    from scipy import ndimage
    allcov = ids >= 0
    dist, (iy, ix) = ndimage.distance_transform_edt(~allcov, return_indices=True)
    take = (~allcov) & (dist <= px)
    out = tex.copy()
    out[take] = tex[iy[take], ix[take]]
    return out, int(take.sum())


def _lab_l(rgb: np.ndarray) -> np.ndarray:
    x = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2LAB).astype(np.float32)
    return x[..., 0] * (100.0 / 255.0)


def guard_gutter(tex: np.ndarray, ids: np.ndarray, px: int, dl_max: float) -> dict:
    """Сторож: непокрытые тексели в пределах px от покрытых, чья светлота L отличается от ближайшего покрытого больше dl_max (должно быть 0). Считает по ИТОГОВОЙ текстуре (после дилатации)."""
    from scipy import ndimage
    allcov = ids >= 0
    dist, (iy, ix) = ndimage.distance_transform_edt(~allcov, return_indices=True)
    band = (~allcov) & (dist <= max(px, 0))
    L = _lab_l(tex)
    bad = band & (np.abs(L - L[iy, ix]) > dl_max)
    return {'в_полосе_текселей': int(band.sum()), 'с_расхождением_L_больше_порога': int(bad.sum()), 'порог_L': float(dl_max), 'полоса_px': int(px)}


def guard_unpainted(ids: np.ndarray, gmap: np.ndarray, known: np.ndarray | None) -> dict:
    """Сторож: покрытые гранями тексели, оставшиеся без покраски (group_map < 0); из них — не «известные с 06»."""
    allcov = ids >= 0
    un = allcov & (gmap < 0)
    n_cov = int(allcov.sum())
    d = {'покрыто_текселей': n_cov, 'не_покрашено': int(un.sum()), 'доля_процент': round(100.0 * float(un.sum()) / max(n_cov, 1), 3)}
    if known is not None and known.shape == un.shape:
        d['из_них_не_известно_с_06'] = int((un & ~known).sum())
    return d


# ───────────────────────────── сторож: тон ФОТО области ↔ тон группы (T-20261126-121/2) ─────────────────────────────

def face_areas(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    a, b, c = P[F[:, 0]].astype(np.float64), P[F[:, 1]].astype(np.float64), P[F[:, 2]].astype(np.float64)
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)




def _grp_med(key: np.ndarray, lab: np.ndarray) -> dict:
    """Медиана Lab по ключу (панели): {ключ: (сколько точек, медиана Lab)}."""
    if len(key) == 0:
        return {}
    o = np.argsort(key, kind='stable')
    key, lab = key[o], lab[o]
    cuts = np.nonzero(np.diff(key))[0] + 1
    return {int(k[0]): (len(k), np.median(l, axis=0)) for k, l in zip(np.split(key, cuts), np.split(lab, cuts))}


def guard_tone(ids: np.ndarray, rgb: np.ndarray, valid: np.ndarray, fg: np.ndarray, fg2: np.ndarray, comp: np.ndarray, area: np.ndarray, tone_srgb: np.ndarray, painted_group: np.ndarray,
               names: list, rules: dict, cos: np.ndarray | None = None, tex: np.ndarray | None = None, ids_tex: np.ndarray | None = None) -> dict:
    """Сторож «цвет детали ≠ тон группы» — «не отдавать» (директор 26.11 по Fable 15 § 2). Область группы G, отданная owner = грани, чья роль изменилась шагом 5 и стала G; единица — ПАНЕЛЬ (comp, как у шага 5).
    Цвет панели ДО owner: медиана Lab ПИКСЕЛЕЙ ФОТО, где она видна (valid, cos ≥ cos_min, ≥ panel_min_px), иначе медиана Lab её текселей в текстуре 06 (tex, ids_tex; ≥ panel_min_texels).
    Панели, для которых данных мало (мелкие, косые, не видные), собираются в один остаток группы и решаются вместе (так белая ниша из сотен мелких панелей не проскакивает).
    Эталон — в той же области: фото (или 06) СВОИХ граней группы G (медиана); своих мало — тон Ш4а (для фото). Панель, у которой |ΔL| > dl_max или сдвиг цветности > dab_max, группе НЕ отдаётся:
    грани возвращают прежнюю роль (fg), метки зерна нет, 07 красит их как раньше со всеми хуками (sub_tone — ножки Крита). Нет данных вовсе — отдаётся («не проверено»).
    СТОП — только если СИЛЬНО чужой (|ΔL| > stop_dl или цветность > stop_dab) площади больше stop_area_frac площади изделия (роль/группа не сходится с фото целиком). Узорные группы не проверяются.
    → {'стоп', 'причина', 'доля_отдано_площади', 'доля_не_отдано_площади', 'доля_сильно_чужой_площади', 'не_отдать': [индексы граней], 'детали': [строка на панель ≥ min_area_frac и на каждую не отданную], 'по_группам': {...}}."""
    import part_material as PM
    tg = rules['tone_guard']
    nrole = len(names)
    fg = np.asarray(fg).astype(int)
    fg2 = np.asarray(fg2).astype(int)
    tot = float(area.sum()) or 1.0
    dl_max, dab_max = float(tg['dl_max']), float(tg['dab_max'])
    stop_dl, stop_dab = float(tg['stop_dl']), float(tg['stop_dab'])
    given = (fg2 >= 0) & (fg2 < nrole) & (fg2 != fg)
    out = {'доля_отдано_площади': round(float(area[given].sum()) / tot, 4), 'порог_dL': dl_max, 'порог_dab': dab_max, 'по_группам': {}, 'детали': [], 'не_отдать': [],
           'доля_не_отдано_площади': 0.0, 'доля_сильно_чужой_площади': 0.0, 'стоп': False, 'причина': ''}
    ok_px = valid & (ids >= 0) & (True if cos is None else (cos >= float(tg['cos_min'])))
    fid = np.clip(ids, 0, len(fg) - 1)
    have_tex = tex is not None and ids_tex is not None
    if have_tex:
        cov_t = ids_tex >= 0
        fidt = np.clip(ids_tex, 0, len(fg) - 1)
    lab = None
    withheld = np.zeros(len(fg), bool)
    strong = np.zeros(len(fg), bool)
    for g in range(nrole):
        m = given & (fg2 == g)
        if not m.any():
            continue
        row = {'доля_площади': round(float(area[m].sum()) / tot, 4), 'из_них_без_роли': round(float(area[m & ((fg < 0) | (fg >= nrole))].sum()) / tot, 4)}
        out['по_группам'][names[g]] = row
        if not painted_group[g]:
            row['вердикт'] = 'не проверено: узорная группа не красится'
            continue
        pan_px, ref_px, ref_px_how = {}, None, ''
        gv = ok_px & m[fid]
        row['пикселей_фото'] = int(gv.sum())
        if gv.sum() >= int(tg['min_px']):
            if lab is None:
                lab = PM.lab_of(rgb.astype(np.float64))
            own = ok_px & (fg[fid] == g)
            if own.sum() >= int(tg['min_px']):
                ref_px, ref_px_how = np.median(lab[own], axis=0), 'фото своих граней группы (%d px)' % int(own.sum())
            else:
                ref_px, ref_px_how = PM.lab_of(np.asarray(tone_srgb[g], np.float64)), 'тон Ш4а (своих пикселей на фото мало)'
            pan_px = _grp_med(comp[fid[gv]], lab[gv])
        pan_tx, ref_tx = {}, None
        if have_tex:
            mt = cov_t & m[fidt]
            own_t = cov_t & (fg[fidt] == g)
            if mt.sum() >= int(tg['panel_min_texels']) and own_t.sum() >= int(tg['panel_min_texels']):
                ref_tx = np.median(PM.lab_of(tex[own_t].astype(np.float64)), axis=0)
                pan_tx = _grp_med(comp[fidt[mt]], PM.lab_of(tex[mt].astype(np.float64)))

        def judge(med, ref):
            dl = float(med[0] - ref[0])
            dab = float(np.hypot(med[1] - ref[1], med[2] - ref[2]))
            bad = abs(dl) > dl_max or dab > dab_max
            why = ('|ΔL| %.1f > %g' % (abs(dl), dl_max) if abs(dl) > dl_max else 'сдвиг цветности %.1f > %g' % (dab, dab_max)) if bad else ''
            return dl, dab, bad, why, (abs(dl) > stop_dl or dab > stop_dab)

        checked = held = 0
        held_area = 0.0
        pool = []                                                      # панели без достаточных данных → остаток группы
        for pc in np.unique(comp[m]):
            fm = m & (comp == pc)
            a = float(area[fm].sum()) / tot
            med = ref = None
            d = {'группа': names[g], 'панель': int(pc), 'доля_площади': round(a, 4)}
            if int(pc) in pan_px and pan_px[int(pc)][0] >= int(tg['panel_min_px']):
                med, ref, d['цвет_из'], d['эталон'] = pan_px[int(pc)][1], ref_px, 'фото', ref_px_how
            elif int(pc) in pan_tx and pan_tx[int(pc)][0] >= int(tg['panel_min_texels']) and ref_tx is not None:
                med, ref, d['цвет_из'], d['эталон'] = pan_tx[int(pc)][1], ref_tx, '06', 'текстура 06 своих граней группы'
            else:
                pool.append((fm, a))
                continue
            dl, dab, bad, why, st = judge(med, ref)
            d.update({'dL': round(dl, 1), 'dab': round(dab, 1), 'цвет_Lab': [round(float(x), 1) for x in med], 'эталон_Lab': [round(float(x), 1) for x in ref], 'решение': 'не отдана' if bad else 'отдана'})
            checked += 1
            if bad:
                d['почему'] = why
                withheld |= fm
                held += 1
                held_area += a
                if st:
                    strong |= fm
            if a >= float(tg['min_area_frac']) or bad:
                out['детали'].append(d)
        if pool:                                                         # остаток: тексели/пиксели всех недостаточных панелей — одним замером
            pm = np.zeros(len(fg), bool)
            for fm, _a in pool:
                pm |= fm
            pa = sum(a for _fm, a in pool)
            d = {'группа': names[g], 'панель': 'остаток (%d панелей)' % len(pool), 'доля_площади': round(pa, 4)}
            med = ref = None
            pv = ok_px & pm[fid]
            if ref_px is not None and pv.sum() >= int(tg['min_px']):
                med, ref, d['цвет_из'], d['эталон'] = np.median(lab[pv], axis=0), ref_px, 'фото', ref_px_how
            elif have_tex and ref_tx is not None and (cov_t & pm[fidt]).sum() >= int(tg['panel_min_texels']):
                med, ref, d['цвет_из'], d['эталон'] = np.median(PM.lab_of(tex[cov_t & pm[fidt]].astype(np.float64)), axis=0), ref_tx, '06', 'текстура 06 своих граней группы'
            if med is None:
                d['решение'], d['почему'] = 'отдана', 'не проверено: мелкие панели не видны на фото и нет текселей 06'
            else:
                dl, dab, bad, why, st = judge(med, ref)
                d.update({'dL': round(dl, 1), 'dab': round(dab, 1), 'цвет_Lab': [round(float(x), 1) for x in med], 'эталон_Lab': [round(float(x), 1) for x in ref], 'решение': 'не отдана' if bad else 'отдана'})
                checked += 1
                if bad:
                    d['почему'] = why
                    withheld |= pm
                    held += len(pool)
                    held_area += pa
                    if st:
                        strong |= pm
            if pa >= float(tg['min_area_frac']) or d['решение'] == 'не отдана':
                out['детали'].append(d)
        row['панелей_проверено'] = checked
        row['не_отдано_панелей'] = held
        row['не_отдано_доля_площади'] = round(held_area, 4)
        row['вердикт'] = ('не проверено: нет ни пикселей фото, ни текселей 06' if not checked else
                          'ок' if not held else 'не отдано %d панелей (%.1f %% площади изделия)' % (held, 100 * held_area))
    out['не_отдать'] = [int(i) for i in np.nonzero(withheld)[0]]
    out['доля_не_отдано_площади'] = round(float(area[withheld].sum()) / tot, 4)
    out['доля_сильно_чужой_площади'] = round(float(area[strong].sum()) / tot, 4)
    if out['доля_сильно_чужой_площади'] > float(tg['stop_area_frac']):
        worst = sorted(((v.get('не_отдано_доля_площади', 0.0), k) for k, v in out['по_группам'].items()), reverse=True)[:3]
        out['стоп'] = True
        out['причина'] = ('роль/группа не сходится с фото: чужой группе отдано %.0f %% площади изделия (порог %.0f %%), цвет фото/06 детали резко далёк от тона группы (|ΔL| > %g или цветность > %g) — %s'
                          % (100 * out['доля_сильно_чужой_площади'], 100 * float(tg['stop_area_frac']), stop_dl, stop_dab, '; '.join('%s %.1f %%' % (k, 100 * s) for s, k in worst if s > 0)))
    return out
