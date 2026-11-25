#!/usr/bin/env python3
"""Тесты part_grain (T-20261124-69/4): выключатель байт в байт, два предохранителя амплитуды, только L, тон держится, оси по плоскости/круглая плита, детерминизм, только маска части."""
import copy
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import part_grain as PG  # noqa: E402
import tex_coverage as TC  # noqa: E402

R = PG.load_rules()
TONE = [67.4, 9.8, 15.9]
OK = []


def check(cond, msg):
    OK.append(bool(cond))
    print(('ok   ' if cond else 'FAIL ') + msg)


def plate(nx=120, ny=60, T=128):
    """Плоская плита 120×60 см в плоскости XZ (нормаль +Y), одна грань на плоскость 0; текстура T×T, тексели в левом верхнем углу."""
    ij = np.array([(j, i) for i in range(ny) for j in range(nx)])
    ti = ij[:, 1] * T + ij[:, 0]
    q = np.stack([(ij[:, 0] / nx - 0.5) * 1.2, np.zeros(len(ij)), (ij[:, 1] / ny - 0.5) * 0.6], 1)       # единицы кадра: 1 ед = 100 см
    tx = types.SimpleNamespace(ti=ti, Q=q, N=np.tile([0.0, 1.0, 0.0], (len(ij), 1)), f=np.zeros(len(ij), np.int64))
    tex = np.full((T, T, 3), 200, np.uint8)
    tone_rgb = TC_lab2rgb(TONE)
    tex.reshape(-1, 3)[ti] = tone_rgb
    return tx, tex


def TC_lab2rgb(lab):
    import tex_fill as TF
    return TF.lab2rgb(np.asarray([lab], np.float64))[0]


def part(pid, **kw):
    d = {'id': pid, 'name': 'Surface Panel', 'is_wood': True, 'tone_lab': TONE, 'tone_sigma': 0.3, 'n_texels': 7200, 'photo_sigma': 1.5}
    d.update(kw)
    return d


def main():
    tx, tex = plate()
    n = len(tx.ti)
    fp, pn = np.array([0]), np.array([[0.0, 1.0, 0.0]])
    mask = np.ones(n, bool)

    # 0. правила
    check(R['enabled'] is False, 'правило по умолчанию: enabled=false')
    bad = copy.deepcopy(R)
    bad['amp_max'] = 1.5
    try:
        import json
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as fh:
            json.dump(bad, fh)
        PG.load_rules(fh.name)
        check(False, 'правило с amp_max>1 отвергается')
    except ValueError:
        check(True, 'правило с amp_max>1 отвергается')

    # 1. выключатель: текстура та же и объект тот же, отчёт enabled=False
    out, rep = PG.apply_grain(tex, tx, [part(1)], {1: mask}, fp, pn, 100.0, (1, 0, 0), R)
    check(out is tex and rep['enabled'] is False and rep['applied'] == 0, 'enabled=false → текстура без изменений (тот же объект), отчёт enabled=False')
    out, rep = PG.apply_grain(tex, tx, [part(1)], {1: mask}, fp, pn, 100.0, (1, 0, 0), R, enabled=True)
    check(out is not tex and np.array_equal(tex.reshape(-1, 3)[tx.ti], np.tile(TC_lab2rgb(TONE), (n, 1))), 'enabled=true → копия, исходная текстура не тронута')

    # 2. включено: тон держится, a/b не трогаем, меняется только L, вне маски — байт в байт
    lab_out = TC.rgb2lab(out.reshape(-1, 3)[tx.ti])
    med = np.median(lab_out, 0)
    de = float(TC.de2000_v(med[None], np.asarray([TONE]))[0])
    check(rep['applied'] == 1 and rep['texels_changed'] == n, f'зерно легло на часть ({rep["texels_changed"]} текселей)')
    check(de < 1.0, f'тон после зерна держится: ΔE00 медианы к тону {de:.2f} < 1')
    check(float(lab_out[:, 0].std()) > 0.3, f'узор виден: σL {lab_out[:, 0].std():.2f} > 0,3')
    check(float(np.abs(np.median(lab_out[:, 1:], 0) - np.asarray(TONE[1:])).max()) < 1.0 and float(lab_out[:, 1].std()) < 1.0, 'a/b не трогаем: разброс a < 1 (узор только по L)')
    outside = np.ones(tex.shape[:2], bool).reshape(-1)
    outside[tx.ti] = False
    check(np.array_equal(out.reshape(-1, 3)[outside], tex.reshape(-1, 3)[outside]), 'вне текселей части текстура байт в байт')
    half = np.zeros(n, bool)
    half[: n // 2] = True
    out_h, _ = PG.apply_grain(tex, tx, [part(1)], {1: half}, fp, pn, 100.0, (1, 0, 0), R, enabled=True)
    check(np.array_equal(out_h.reshape(-1, 3)[tx.ti][~half], tex.reshape(-1, 3)[tx.ti][~half]) and not np.array_equal(out_h.reshape(-1, 3)[tx.ti][half], tex.reshape(-1, 3)[tx.ti][half]),
          'меняются только тексели маски части')

    # 3. детерминизм
    out2, _ = PG.apply_grain(tex, tx, [part(1)], {1: mask}, fp, pn, 100.0, (1, 0, 0), R, enabled=True)
    check(np.array_equal(out, out2), 'тот же вход → тот же результат')

    # 4. предохранитель 1: потолок амплитуды (σ фото огромна → amp_max)
    pl = PG.plan_grain([part(1, photo_sigma=9.0)], R)
    check(abs(pl[1]['amp'] - R['amp_max']) < 1e-9 and pl[1]['amp_source'] == 'photo', f'потолок: σ фото 9 → amp = amp_max {R["amp_max"]}')
    pl = PG.plan_grain([part(1, photo_sigma=R['photo_sigma_min'] + 0.01)], R)
    check(R['amp_min'] <= pl[1]['amp'] <= R['amp_max'], 'амплитуда в [amp_min, amp_max]')

    # 5. предохранитель 2: σ фото < порога → медиана соседей с рисунком; соседей нет → зерна нет
    pl = PG.plan_grain([part(1, photo_sigma=2.0), part(2, photo_sigma=3.0), part(3, photo_sigma=0.5), part(4, photo_sigma=None)], R)
    med = float(np.median([pl[1]['amp'], pl[2]['amp']]))
    check(pl[3]['apply'] and pl[3]['amp_source'] == 'neighbors' and abs(pl[3]['amp'] - med) < 1e-9, 'σ фото ниже порога → амплитуда = медиана соседей с рисунком')
    check(pl[4]['apply'] and pl[4]['amp_source'] == 'neighbors', 'фото нет → то же правило (соседи)')
    pl = PG.plan_grain([part(1, photo_sigma=0.5), part(2, photo_sigma=None)], R)
    check(not pl[1]['apply'] and pl[1]['reason'] == 'no_photo_evidence' and not pl[2]['apply'], 'ни у кого рисунка на фото нет → зерна нет (no_photo_evidence)')
    check(pl[1]['pat'] is None, 'у отказа узор не хранится')

    # 6. отказы с причинами
    pl = PG.plan_grain([part(1, is_wood=False), part(2, n_texels=100), part(3, tone_sigma=5.0), part(4, tone_lab=None), part(5, photo_sigma=2.0)], R)
    check(pl[1]['reason'] == 'not_wood' and pl[2]['reason'] == 'too_small' and pl[3]['reason'] == 'tone_not_even' and pl[4]['reason'] == 'no_tone', 'причины отказа: не дерево / мало текселей / градиент / нет тона')
    _, rep = PG.apply_grain(tex, tx, [part(1, is_wood=False), part(3, tone_sigma=5.0)], {1: mask, 3: mask}, fp, pn, 100.0, (1, 0, 0), R, enabled=True)
    check(rep['skipped'] == {'not_wood': 1, 'tone_not_even': 1} and rep['applied'] == 0, f'счётчик отказов в отчёте: {rep["skipped"]}')

    # 7. материал по карточке
    card = {'Материал корпуса': 'МДФ, шпон дуба', 'Материал ножек': 'металл', 'Основной материал': 'дерево'}
    check(PG.part_is_wood('Table Frame', card, R) and not PG.part_is_wood('Leg', card, R) and not PG.part_is_wood('Seat Cushion', card, R) and not PG.part_is_wood('Door Handle', card, R),
          'материал части: корпус — дерево, ножки металл — нет, подушка/ручка — нет')

    # 8. оси: вытянутая плоскость — длинная ось; круглая — ось ширины
    rng = np.random.default_rng(1)
    q = np.stack([rng.uniform(-60, 60, 4000), np.zeros(4000), rng.uniform(-20, 20, 4000)], 1)
    c1, c2, rl = PG.plane_axes(q, (0, 1, 0), (0, 0, 1), R)
    check(abs(c1[0]) > 0.99 and not rl, 'вытянутая плоскость: ось зерна вдоль длинной стороны (X), а не ширины товара')
    ang = rng.uniform(0, 2 * np.pi, 4000)
    rr = 50 * np.sqrt(rng.uniform(0, 1, 4000))
    qr = np.stack([rr * np.cos(ang), np.zeros(4000), rr * np.sin(ang)], 1)
    c1, c2, rl = PG.plane_axes(qr, (0, 1, 0), (0, 0, 1), R)
    check(rl and abs(c1[2]) > 0.99, 'круглая плита: ось зерна = ось ширины товара (Z)')
    c1, c2, rl = PG.plane_axes(qr, (0, 1, 0), (0, 1, 0), R)
    check(rl and abs(np.linalg.norm(c1) - 1) < 1e-9 and abs(c1 @ np.array([0, 1, 0])) < 1e-9, 'ось ширины вдоль нормали (вырожденная) → запасная ось в плоскости')
    check(abs(c1 @ c2) < 1e-9, 'c1 ⟂ c2')

    # 9. плитка: период по tile_cm; сдвиг/зеркало по ключу плоскости различают соседей
    pat = np.random.default_rng(2).normal(size=(64, 64))
    u = np.linspace(0, 200, 500)
    a = PG.sample_pat(pat, u, np.full(500, 7.0), (40.0, 40.0), 5, [1.0])
    b = PG.sample_pat(pat, u + 40.0, np.full(500, 7.0), (40.0, 40.0), 5, [1.0])
    check(float(np.abs(a - b).max()) < 1e-9, 'один слой: сдвиг на tile_cm даёт то же значение (период = tile_cm)')
    c = PG.sample_pat(pat, u, np.full(500, 7.0), (40.0, 40.0), 6, [1.0])
    check(float(np.abs(a - c).mean()) > 0.1, 'другая плоскость (ключ) → другая фаза/зеркало')
    two = PG.sample_pat(pat, u, np.full(500, 7.0), (40.0, 40.0), 5, [1.0, 1.37])
    check(abs(float(two.std()) - float(a.std())) < 0.5 * float(a.std()) + 0.2, 'два слоя / sqrt(2): разброс узора сохраняется')

    # 10. фото: σL высокочастотная — плавный градиент рисунком не считается, зерно — да
    h = w = 200
    mask2 = np.ones((h, w), bool)
    grad = np.tile(np.linspace(40, 80, w, dtype=np.float32), (h, 1))
    s_g = PG.photo_hf_sigma(grad, mask2, R)
    noise = grad + np.random.default_rng(3).normal(0, 2.0, (h, w)).astype(np.float32)
    s_n = PG.photo_hf_sigma(noise, mask2, R)
    check(s_g is not None and s_g < 0.3 and s_n is not None and 1.4 < s_n < 2.6, f'photo_hf_sigma: градиент {s_g:.2f} (<0,3), шум σ=2 → {s_n:.2f}')
    check(PG.photo_hf_sigma(grad, np.zeros((h, w), bool), R) is None, 'мало пикселей → None')

    # 11. плитка отказ: бин flat/нет — зерна нет с причиной (искусственно: тон вне библиотеки при заданном пороге)
    r2 = dict(R, library_max_de00=0.01)
    pl = PG.plan_grain([part(1, tone_lab=[30.0, 60.0, -60.0])], r2)
    check(not pl[1]['apply'] and pl[1]['reason'] == 'no_bin', 'нет бина ближе порога → no_bin, зерна нет')

    # 12. вход от Ш4а: part_material_masks.npz → части и маски
    T = tex.shape[0]
    gm = np.full((T, T), -1, np.int16)
    gmf = gm.reshape(-1)
    gmf[tx.ti[: n // 2]] = 0
    gmf[tx.ti[n // 2:]] = 1
    npz = {'group_map': gm, 'names': np.array(['Surface Panel', 'Leg']), 'tone_srgb': np.array([TC_lab2rgb(TONE), TC_lab2rgb(TONE)]), 'painted_group': np.array([True, False]), 'material': np.array([0, 1])}
    card = {'Материал столешницы': 'дерево'}
    pp, mm = PG.parts_from_masks(npz, tx, tex, card, {0: 2.0}, R)
    check(len(pp) == 1 and pp[0]['id'] == 0 and pp[0]['is_wood'] and mm[0].sum() == n // 2 and pp[0]['n_texels'] == n // 2, 'вход Ш4а: берутся только painted_group, маска по group_map')
    check(pp[0]['tone_sigma'] is not None and pp[0]['tone_sigma'] < 0.5 and pp[0]['photo_sigma'] == 2.0, 'вход Ш4а: ровность тона измерена по текстуре, σ фото передана')
    out3, rep3 = PG.apply_grain(tex, tx, pp, mm, fp, pn, 100.0, (1, 0, 0), R, enabled=True)
    rest = out3.reshape(-1, 3)[tx.ti][n // 2:]
    check(rep3['applied'] == 1 and np.array_equal(rest, tex.reshape(-1, 3)[tx.ti][n // 2:]), 'вход Ш4а → зерно только на группе 0, группа 1 нетронута')
    npz_r = dict(npz, names=np.array(['верх', 'ножки']), roles=np.array(['top', 'legs']), texture_size=np.array(T), painted_group=np.array([True, True]))
    pr, _m = PG.parts_from_masks(npz_r, tx, tex, {'Материал столешницы': 'дерево', 'Материал ножек': 'металл'}, None, R)
    check([x['is_wood'] for x in pr] == [True, False], 'роли Ш4а: верх — по столешнице (дерево), ножки — по «Материал ножек» (металл → не дерево)')
    try:
        PG.parts_from_masks(dict(npz_r, texture_size=np.array(T + 1)), tx, tex, card, None, R)
        check(False, 'texture_size не совпал — отказ')
    except ValueError:
        check(True, 'texture_size не совпал — отказ')
    bad_npz = dict(npz, group_map=np.full((T // 2, T), -1, np.int16))
    try:
        PG.parts_from_masks(bad_npz, tx, tex, card, None, R)
        check(False, 'group_map другого размера отвергается')
    except ValueError:
        check(True, 'group_map другого размера отвергается')

    # 9. ключи правил «ось детали» (T-63 р.5d): ВКЛЮЧЁННЫЙ ключ обязан менять выход (молча не включившийся флаг = красный тест)
    nx, ny, T2 = 120, 60, 128
    tx0, tex = plate(nx, ny, T2)
    n = len(tx0.ti)
    pn = np.array([[0.0, 1.0, 0.0]])
    ij = np.array([(j, i) for i in range(ny) for j in range(nx)])
    tx2 = types.SimpleNamespace(ti=tx0.ti, Q=tx0.Q, N=tx0.N, f=(ij[:, 0] >= 100).astype(np.int64))     # грань 0 — левые 100 см, грань 1 — полоса 20×60 вдоль Z
    fp2, fpart2 = np.array([0, 0]), np.array([0, 1])
    base_r = dict(copy.deepcopy(R), enabled=True)
    run = lambda **k: PG.apply_grain(tex, tx2, [dict(part(1), role='legs')], {1: np.ones(n, bool)}, fp2, pn, 100.0, (1, 0, 0), dict(base_r, **k), enabled=True, face_part=fpart2)[0]
    o_off = run()
    o_on = run(axis_per_part=True, axis_per_part_roles=['legs'])
    check(not np.array_equal(o_off, o_on), 'axis_per_part=true меняет текстуру (флаг не «молчит»)')
    check(np.array_equal(o_off, run(axis_per_part=True, axis_per_part_roles=['top'])), 'axis_per_part: роль не из axis_per_part_roles → без изменений')
    check(np.array_equal(o_off, PG.apply_grain(tex, tx2, [dict(part(1), role='legs')], {1: np.ones(n, bool)}, fp2, pn, 100.0, (1, 0, 0), dict(base_r, axis_per_part=True), enabled=True)[0]), 'axis_per_part без face_part → без изменений (нет данных о частях)')
    strip = (ij[:, 0] >= 100)
    def aniso(o):
        L = TC.rgb2lab(o.reshape(-1, 3)[tx2.ti])[:, 0].reshape(ny, nx)[:, 100:]
        return float(np.abs(np.diff(L, axis=0)).mean() / max(float(np.abs(np.diff(L, axis=1)).mean()), 1e-9))        # вдоль Z / поперёк (X)
    check(aniso(o_on) < aniso(o_off), f'полоса вдоль Z: при axis_per_part волокно идёт вдоль неё (изменение вдоль/поперёк {aniso(o_on):.2f} < {aniso(o_off):.2f} без правила)')
    fpt_all = np.full(2, -1)
    o_fb_off = PG.apply_grain(tex, tx2, [dict(part(1), role='legs')], {1: np.ones(n, bool)}, fpt_all, pn, 100.0, (1, 0, 0), base_r, enabled=True, face_part=fpart2)[0]
    o_fb_on = PG.apply_grain(tex, tx2, [dict(part(1), role='legs')], {1: np.ones(n, bool)}, fpt_all, pn, 100.0, (1, 0, 0), dict(base_r, axis_per_part=True), enabled=True, face_part=fpart2)[0]
    check(not np.array_equal(o_fb_off, o_fb_on), 'запасной путь (не плоскость): axis_per_part=true меняет текстуру')

    bad_n = sum(1 for x in OK if not x)
    print(f'\n{len(OK) - bad_n}/{len(OK)} ok')
    sys.exit(1 if bad_n else 0)


main()
