#!/usr/bin/env python3
"""Тесты part_grain (T-20261124-69/4): выключатель байт в байт, два предохранителя амплитуды, только L, тон держится, оси по плоскости/круглая плита, детерминизм, только маска части."""
import os as _rt_os  # noqa: E402
import sys as _rt_sys  # noqa: E402
_rt_sys.path.append(_rt_os.path.join(_rt_os.path.dirname(_rt_os.path.abspath(__file__)), '../..'))
import remlab_tmp  # noqa: E402,I001  — временное теста на диске и с уборкой при выходе (T-20261107-13)
remlab_tmp.use('tests_part_grain')
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
    R_nn = dict(R, amp_from_neighbors=False)                                   # лазейка закрыта: свой σ ниже порога/нет фото → ровный тон, даже при соседях с рисунком
    pl = PG.plan_grain([part(1, photo_sigma=2.0), part(2, photo_sigma=3.0), part(3, photo_sigma=0.5), part(4, photo_sigma=None)], R_nn)
    check(pl[1]['apply'] and pl[1]['amp_source'] == 'photo' and pl[2]['apply'], 'лазейка закрыта: части с рисунком на фото — зерно по своему фото')
    check(not pl[3]['apply'] and pl[3]['reason'] == 'no_photo_evidence' and pl[3]['pat'] is None and not pl[4]['apply'] and pl[4]['reason'] == 'no_photo_evidence', 'лазейка закрыта: σ ниже порога и нет фото — ровный тон (no_photo_evidence), амплитуду у соседей не берём')
    check(PG.plan_grain([part(1, photo_sigma=2.0), part(3, photo_sigma=0.5)], R)[3]['amp_source'] == 'neighbors', 'флаг не задан — как раньше (соседи)')

    # 5б. T-97/1 фаза 4: пол размаха amp_floor_L (σ узора = amp × pat_std не ниже пола, в единицах L); 0 = выкл
    check(R['amp_floor_L'] == 0.0 and R['photo_sigma_min'] == 0.8, 'по умолчанию пол выключен (0), порог photo_sigma_min — одно число 0,8')
    p0 = PG.plan_grain([part(1, photo_sigma=R['photo_sigma_min'] + 0.01)], R)[1]
    sig0 = p0['amp'] * p0['pat_std']
    check('floor' not in p0 and not p0['amp_source'].endswith('+floor'), 'пол выкл: амплитуда как была, строки floor нет')
    R_hi = dict(R, amp_floor_L=sig0 * 2.0)
    p1 = PG.plan_grain([part(1, photo_sigma=R['photo_sigma_min'] + 0.01)], R_hi)[1]
    check(p1['amp'] > p0['amp'] and abs(p1['amp'] * p1['pat_std'] - min(sig0 * 2.0, p1['pat_std'])) < 1e-9 and p1['amp_source'] == 'photo+floor' and p1['floor']['raised'], 'пол выше σ: амплитуда поднята до пола/σ узора, источник «+floor», в следе raised')
    R_lo = dict(R, amp_floor_L=sig0 * 0.5)
    p2 = PG.plan_grain([part(1, photo_sigma=R['photo_sigma_min'] + 0.01)], R_lo)[1]
    check(p2['amp'] == p0['amp'] and p2['floor']['raised'] is False and p2['amp_source'] == 'photo', 'пол ниже σ: амплитуда не тронута, raised=false')
    p3 = PG.plan_grain([part(1, photo_sigma=R['photo_sigma_min'] + 0.01)], dict(R, amp_floor_L=19.0))[1]
    check(p3['amp'] == 1.0, 'пол не поднимает амплитуду выше 1,0')
    pn_ = PG.plan_grain([part(1, photo_sigma=2.0), part(3, photo_sigma=0.5)], dict(R, amp_floor_L=19.0))
    check(pn_[3]['amp_source'] == 'neighbors+floor' and pn_[1]['amp_source'] == 'photo+floor', 'пол действует и на амплитуду «у соседей»')
    o_off, rp_off = PG.apply_grain(tex, tx, [part(1, photo_sigma=R['photo_sigma_min'] + 0.01)], {1: mask}, fp, pn, 100.0, (1, 0, 0), R, enabled=True)
    o_hi, rp_hi = PG.apply_grain(tex, tx, [part(1, photo_sigma=R['photo_sigma_min'] + 0.01)], {1: mask}, fp, pn, 100.0, (1, 0, 0), R_hi, enabled=True)
    check(not np.array_equal(o_off, o_hi) and 'floor' not in rp_off['parts'][1] and rp_hi['parts'][1]['floor']['raised'], 'ключ amp_floor_L меняет выход (текстура) и след; выкл — без строки floor')
    try:
        import json as _j
        import tempfile as _t
        rr = copy.deepcopy(R)
        rr['amp_floor_L'] = 25.0
        with _t.TemporaryDirectory() as _d:
            _p = os.path.join(_d, 'r.json')
            _j.dump(rr, open(_p, 'w'))
            PG.load_rules(_p)
        check(False, 'amp_floor_L вне пределов отвергается')
    except ValueError:
        check(True, 'amp_floor_L вне пределов отвергается')

    # 5в. T-97/1 фаза 5: «дерево — волокно всегда» (rules.wood_always); выкл по умолчанию = прежний plan_grain
    WA0 = R['wood_always']
    check(WA0['enabled'] is False, 'wood_always: по умолчанию выключено')
    pl_off = PG.plan_grain([part(1, role='top', card={'Материал столешницы': 'массив дуба'}, photo_sigma=2.0)], R)
    check('wood' not in pl_off[1], 'wood_always выкл: ветка не выполняется (в плане нет строки wood)')
    RW = copy.deepcopy(R)
    RW['wood_always']['enabled'] = True
    RW['amp_floor_L'] = 1.4
    lib_ = PG._library(PG.TP.load_rules())
    st_ = [n for n, v in lib_['items'].items() if v.get('family', 'wood') == 'wood' and v.get('pattern_class', 'straight') == 'straight']
    check(st_ and all(lib_['items'][n].get('grain_marks') and set(lib_['items'][n]['grain_marks']) == {'sigma_L', 'low_freq', 'directionality'} for n in st_), 'разметка библиотеки: у каждого straight-бина есть grain_marks {sigma_L, low_freq, directionality} (%d бинов)' % len(st_))
    try:
        import part_grain_marks as PGMK
        bad_ = [n for n, m in PGMK.compute(lib_).items() if lib_['items'][n].get('grain_marks') != m]
        check(not bad_, 'разметка библиотеки == пересчёт по сканам (part_grain_marks.py --check): расхождений %d' % len(bad_))
    except ImportError as e_:
        print('SKIP пересчёт разметки: нет модуля (%s)' % e_)

    def wplan(parts_, rules_=None):
        return PG.plan_grain(parts_, rules_ or RW)
    w1 = wplan([part(1, role='top', card={'Материал столешницы': 'массив дуба'}, photo_sigma=2.0)])[1]
    check(w1['apply'] and w1['amp_source'].startswith('photo') and w1['wood']['class'] == 'дерево' and w1['wood']['source'] == 'фото' and w1['bin']['bin'], 'дерево по карточке роли + фото видно: волокно из фото (источник «фото»)')
    check(wplan([part(1, role='legs', card={'Материал ножек (опор)': 'металл'}, photo_sigma=2.0)])[1]['reason'] == 'not_wood', 'металл — не дерево, ровно')
    check(wplan([part(1, role='legs', card={'Материал ножек (опор)': 'ткань велюр'}, photo_sigma=2.0)])[1]['reason'] == 'not_wood', 'обивка — не дерево, ровно')
    wb = wplan([part(1, role='top', card={'Материал столешницы': 'лдсп'}, photo_sigma=2.0)])[1]
    check(wb['reason'] == 'not_wood' and wb['wood']['class'] == 'плита', 'плита без породы (ЛДСП) — ровно, класс «плита»')
    check(wplan([part(1, role='top', card={}, photo_sigma=2.0)])[1]['reason'] == 'material_not_named', 'материал не назван — ровно (material_not_named)')
    wc = wplan([part(1, role='top', card={'Материал столешницы': 'массив'}, tone_lab=[80.0, 2.0, 3.0], photo_sigma=0.3)])[1]
    check(wc['reason'] == 'colourless_no_photo' and not wc['apply'], 'бесцветный «массив» без волокна на фото — крашеный, ровно')
    wc2 = wplan([part(1, role='top', card={'Материал столешницы': 'массив'}, tone_lab=[80.0, 2.0, 3.0], photo_sigma=2.0)])[1]
    check(wc2['apply'], 'бесцветный «массив», но фото волокно показывает — волокно')
    wf = wplan([part(1, role='top', card={'Основной материал': 'шпон дуба'}, photo_sigma=2.0)])[1]
    check(wf['apply'] and 'запасное поле' in wf['wood']['field'], 'поля роли нет — запасное поле «Основной материал», помечено в следе (%s)' % wf['wood']['field'])
    # запас: фото молчит
    r_dub = wplan([part(1, role='top', card={'Материал столешницы': 'массив дуба'}, photo_sigma=0.3)])[1]
    r_buk = wplan([part(1, role='top', card={'Материал столешницы': 'массив бука'}, photo_sigma=0.3)])[1]
    r_non = wplan([part(1, role='top', card={'Материал столешницы': 'массив'}, photo_sigma=None)])[1]
    rows_ = sorted((float(lib_['items'][n]['grain_marks']['sigma_L']), n) for n in st_)
    k_ = max(1, len(rows_) // 3)
    check(all(x['apply'] and x['amp_source'] == 'reserve' for x in (r_dub, r_buk, r_non)), 'фото молчит, соседа нет — запас по породе (источник «reserve») у дуба, бука и «не названа»')
    check(r_dub['bin']['bin'] in [n for _s, n in rows_[-k_:]] and abs(r_dub['amp'] - min(2.0 / r_dub['pat_std'], 3.0)) < 1e-9, 'дуб/ясень: «выраженный» бин (верхняя треть по σ узора), размах 2,0 L')
    cm_ = lambda n: lib_['items'][n]['grain_marks']  # noqa: E731
    calm_ = [n for _s, n in rows_ if cm_(n)['sigma_L'] <= 5.5 and cm_(n)['directionality'] >= 1.5 and cm_(n)['low_freq'] <= 0.4]
    check(calm_ and r_buk['bin']['bin'] in calm_ and r_non['bin']['bin'] in calm_ and abs(r_buk['amp'] - min(1.5 / r_buk['pat_std'], 3.0)) < 1e-9, 'бук/«не названа»: «спокойный» бин (σ≤5,5, направленность≥1,5, низких≤0,4 — по разметке), размах 1,5 L')
    check(r_non['bin']['bin'] == min(calm_, key=lambda n: (cm_(n)['low_freq'], cm_(n)['sigma_L'])), 'порода не названа: самый спокойный бин (наименьшая доля низких частот)')
    check(not any(cm_(x['bin']['bin'])['low_freq'] > 0.4 for x in (r_buk, r_non)), 'запас без пятен и сучков: доля низких частот выбранных бинов ≤ 0,4')
    ws = wplan([part(1, role='legs', card={'Материал ножек (опор)': 'массив бука'}, photo_sigma=2.0), part(2, role='legs', card={'Материал ножек (опор)': 'массив бука'}, photo_sigma=0.3)])
    check(ws[2]['amp_source'] == 'material' and abs(ws[2]['amp'] - min(2.0 / ws[2]['pat_std'], 3.0)) < 1e-9, 'фото молчит, на товаре тот же материал с фото: размах переносится (источник «material», цель σ 2,0 L)')
    wh = copy.deepcopy(RW)
    wh['wood_always']['reserve_amp_max'] = 0.2
    check(wplan([part(1, role='top', card={'Материал столешницы': 'массив дуба'}, photo_sigma=0.3)], wh)[1]['amp'] == 0.2, 'ключ reserve_amp_max ограничивает амплитуду запаса')
    wl = copy.deepcopy(RW)
    wl['wood_always']['reserve_sigma_L'] = 1.0
    wl['amp_floor_L'] = 1.4
    rl = wplan([part(1, role='top', card={'Материал столешницы': 'массив бука'}, photo_sigma=0.3)], wl)[1]
    check(abs(rl['amp'] - min(1.4 / rl['pat_std'], 3.0)) < 1e-9, 'пол amp_floor_L держит и запас: цель σ = max(reserve_sigma_L 1,0; пол 1,4) = 1,4 L')
    wr = copy.deepcopy(RW)
    wr['wood_always']['strong_species'] = ['бук']
    check(wplan([part(1, role='top', card={'Материал столешницы': 'массив бука'}, photo_sigma=0.3)], wr)[1]['bin']['bin'] in [n for _s, n in rows_[-k_:]], 'ключ strong_species меняет выбор: бук объявлен «выраженной» породой — бин из верхней трети по σ')
    wd = copy.deepcopy(RW)
    wd['library_max_de00'] = 0.5
    w_far = wplan([part(1, role='top', card={'Материал столешницы': 'массив дуба'}, photo_sigma=2.0, tone_lab=[30.0, 40.0, -30.0])], wd)[1]
    check(w_far['apply'] and 'дальше лимита' in w_far['wood']['source'], 'бин дальше лимита ΔE00 — ближайший straight без лимита, с пометкой в следе')
    o_def, _r1 = PG.apply_grain(tex, tx, [part(1, role='top', card={'Материал столешницы': 'массив дуба'}, photo_sigma=0.3)], {1: mask}, fp, pn, 100.0, (1, 0, 0), R, enabled=True)
    o_wa, rep_wa = PG.apply_grain(tex, tx, [part(1, role='top', card={'Материал столешницы': 'массив дуба'}, photo_sigma=0.3)], {1: mask}, fp, pn, 100.0, (1, 0, 0), RW, enabled=True)
    check(np.array_equal(o_def, tex) and not np.array_equal(o_wa, tex) and rep_wa['parts'][1]['wood']['decision'] == 'волокно', 'ключ wood_always меняет выход: фото молчит — раньше ровно, теперь волокно; в следе строка wood')
    miss_ = copy.deepcopy(RW)
    del miss_['wood_always']['reserve_amp_max']
    try:
        import json as _j2
        import tempfile as _t2
        with _t2.TemporaryDirectory() as _d2:
            _p2 = os.path.join(_d2, 'r.json')
            _j2.dump(miss_, open(_p2, 'w'))
            PG.load_rules(_p2)
        check(False, 'wood_always без обязательного ключа отвергается')
    except ValueError:
        check(True, 'wood_always без обязательного ключа отвергается')

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

    # ---------- проверка оси зерна верха (T-20261124-57/5): только отчёт ----------
    AC = dict(R['axis_check'])
    check(AC['enabled'] is False, 'axis_check: по умолчанию выключена')
    yy = np.arange(200)[:, None] * np.ones((1, 200))
    L_h = 50.0 + 20.0 * np.sin(2 * np.pi * yy / 6.0)                           # полосы вдоль оси X кадра: волокна идут горизонтально
    L_v = L_h.T                                                                  # полосы вдоль Y кадра: волокна вертикальны
    L_g = 50.0 + 0.1 * np.arange(200)[None, :] * np.ones((200, 1)) + 0.05 * yy                # плавный свет/тень без рисунка: градиент есть, волокон нет
    L_n = np.random.RandomState(1).uniform(40, 60, (200, 200))                  # без рисунка: подсказки нет

    NX, NZ = 6, 3                                                               # сетка граней плиты: у плоскости много граней, как у настоящего меша

    def grid_mesh(half_x, half_z):
        xs, zs = np.linspace(-half_x, half_x, NX + 1), np.linspace(-half_z, half_z, NZ + 1)
        P = np.array([[x, 0.0, z] for z in zs for x in xs])
        F = []
        for j in range(NZ):
            for i in range(NX):
                a0 = j * (NX + 1) + i
                F += [[a0, a0 + 1, a0 + NX + 2], [a0, a0 + NX + 2, a0 + NX + 1]]
        return P, np.array(F)

    def cell_face(x, z, half_x, half_z):
        i = np.clip(((x + half_x) / (2 * half_x) * NX).astype(int), 0, NX - 1)
        j = np.clip(((z + half_z) / (2 * half_z) * NZ).astype(int), 0, NZ - 1)
        return 2 * (j * NX + i)

    def ctx_for(Lx, half_x=0.6, half_z=0.3):
        P, F = grid_mesh(half_x, half_z)
        px = (np.arange(200)[None, :] - 100) / 100.0 * np.ones((200, 1))
        pz = (np.arange(200)[:, None] - 100) / 100.0 * np.ones((1, 200))
        ids = np.where((np.abs(px) < half_x) & (np.abs(pz) < half_z), cell_face(px, pz, half_x, half_z), -1)
        return {'L': Lx, 'ids': ids, 'valid': ids >= 0, 'xy': P[:, [0, 2]] * 100 + 100, 'P': P, 'F': F}

    def with_faces(tx_, half_x, half_z):
        return types.SimpleNamespace(ti=tx_.ti, Q=tx_.Q, N=tx_.N, f=cell_face(tx_.Q[:, 0], tx_.Q[:, 2], half_x, half_z))

    RA = copy.deepcopy(R)
    RA['axis_check'] = dict(AC, enabled=True)
    pt = part(1, name='верх')
    txr0, texr = plate(nx=60, ny=60)
    txr0.Q[:, 0] *= 0.5                                                          # квадрат 60×60 см: ось не из формы
    txr = with_faces(txr0, 0.3, 0.3)
    tx = with_faces(tx, 0.6, 0.3)
    n_faces = len(grid_mesh(0.6, 0.3)[1])

    def run_axis(rules, tx_, tex_, ctx, wa=(1, 0, 0)):
        m_ = np.ones(len(tx_.ti), bool)
        return PG.apply_grain(tex_, tx_, [pt], {1: m_}, fp, pn, 100.0, wa, rules, enabled=True, axis_ctx=ctx)

    fp, pn = np.zeros(n_faces, np.int64), np.array([[0.0, 1.0, 0.0]])
    out_off, rep_off = run_axis(R, tx, tex, ctx_for(L_h))
    out_on, rep_on = run_axis(RA, tx, tex, ctx_for(L_h))
    check('axis' not in rep_off['parts'][1], 'axis_check выключена: в отчёте части ключа axis нет')
    check(np.array_equal(out_off, out_on), 'axis_check включена: текстура побайтно та же (только отчёт)')
    a = rep_on['parts'][1]['axis'][0]
    check(a['verdict'] == 'axis_ok_photo' and not a['would_flag'] and a['d_deg'] < 5 and not a['round_like'], f'вытянутая плита, волокна фото вдоль длинной оси → ось верна, не метка ({a})')
    a = run_axis(RA, tx, tex, ctx_for(L_v))[1]['parts'][1]['axis'][0]
    check(a['verdict'] == 'axis_off_photo' and a['would_flag'] and a['d_deg'] > 80, f'вытянутая плита, волокна фото поперёк выбранной оси → метка ({a})')
    a = run_axis(RA, txr, texr, ctx_for(L_n, 0.3, 0.3))[1]['parts'][1]['axis'][0]
    check(a['round_like'] and a['verdict'] == 'imposed_no_hint' and a['would_flag'], f'квадратная плита без подсказки на фото: рисунок навязан → метка ({a})')
    a = run_axis(RA, txr, texr, ctx_for(L_h, 0.3, 0.3))[1]['parts'][1]['axis'][0]
    check(a['round_like'] and a['verdict'] == 'axis_ok_photo' and not a['would_flag'], f'квадратная плита, ось ширины совпала с волокнами фото → не метка ({a})')
    a = run_axis(RA, txr, texr, ctx_for(L_h, 0.3, 0.3), wa=(0, 0, 1))[1]['parts'][1]['axis'][0]
    check(a['round_like'] and a['verdict'] == 'axis_off_photo' and a['would_flag'], f'квадратная плита, ось ширины ⟂ волокнам фото → метка ({a})')
    a = run_axis(RA, tx, tex, ctx_for(L_n))[1]['parts'][1]['axis'][0]
    check(a['verdict'] == 'long_side_no_hint' and not a['would_flag'], f'вытянутая плита без подсказки: ось по длинной стороне, не метка ({a})')
    a = run_axis(RA, txr, texr, ctx_for(L_g, 0.3, 0.3))[1]['parts'][1]['axis'][0]
    check(a['photo_coh'] is None and a['photo_hf'] < RA['photo_sigma_min'] and a['verdict'] == 'imposed_no_hint' and a['would_flag'], f'плавный свет на фото — не волокна: подсказки нет, квадрат → метка ({a})')
    cx = ctx_for(L_h, 0.3, 0.3)
    cx['valid'] = np.zeros((200, 200), bool)
    a = run_axis(RA, txr, texr, cx)[1]['parts'][1]['axis'][0]
    check(a['verdict'] == 'not_visible' and not a['would_flag'], f'плоскости на фото нет → not_visible, не метка ({a})')
    rep_n = PG.apply_grain(tex, tx, [part(1, name='ножки')], {1: mask}, fp, pn, 100.0, (1, 0, 0), RA, enabled=True, axis_ctx=ctx_for(L_h))[1]
    check('axis' not in rep_n['parts'][1], 'не-верх (имя без part_words) — проверка не считается')
    check(PG.ang_diff180(10, 170) == 20 and PG.ang_diff180(0, 90) == 90 and PG.ang_diff180(179, 1) == 2, 'ang_diff180: ось — прямая, разница 0…90°')

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

    # 10. круглая деталь (диск), запасной путь: оси деталь не имеет → ось ширины товара (X); без правила — случайная главная ось (чуть вытянутый по Z диск → Z)
    cx, cz = (ij[:, 0] - 60.0), (ij[:, 1] - 30.0)
    disc = (cx / 29.0) ** 2 + (cz / 30.0) ** 2 < 1.0                                       # эллипс 58×60 см: отношение осей ≈ 1,07 ≤ 1,1
    tx3 = types.SimpleNamespace(ti=tx0.ti[disc], Q=tx0.Q[disc], N=tx0.N[disc], f=np.zeros(int(disc.sum()), np.int64))
    fp3 = np.array([-1])
    def disc_run(**k):
        return PG.apply_grain(tex, tx3, [dict(part(1), role='legs')], {1: np.ones(int(disc.sum()), bool)}, fp3, pn, 100.0, (1, 0, 0), dict(base_r, **k), enabled=True, face_part=np.array([0]))[0]
    def disc_aniso(o):
        img = np.full((ny, nx), np.nan)
        img[ij[disc][:, 1], ij[disc][:, 0]] = TC.rgb2lab(o.reshape(-1, 3)[tx3.ti])[:, 0]
        dx = np.abs(np.diff(img, axis=1))
        dz = np.abs(np.diff(img, axis=0))
        return float(np.nanmean(dx) / max(float(np.nanmean(dz)), 1e-9))                  # изменение вдоль X / вдоль Z
    d_off, d_on = disc_run(axis_per_part=True, axis_per_part_roles=['legs'], axis_per_part_round_ratio=1.0), disc_run(axis_per_part=True, axis_per_part_roles=['legs'])
    check(not np.array_equal(d_off, d_on), 'круглая деталь: порог axis_per_part_round_ratio меняет текстуру (ключ не «молчит»)')
    check(disc_aniso(d_on) < disc_aniso(d_off), f'диск: ось = ширина товара X (изменение вдоль X / вдоль Z {disc_aniso(d_on):.2f} < {disc_aniso(d_off):.2f} при главной оси части)')

    # 11. классы бина по роли (T-63 р.5g): ножки/рама — straight; ключ включён → бин меняется со swirl (Wood047 — «завитки/глазки») на straight, выход меняется
    npz_c = dict(npz_r, roles=np.array(['legs', 'legs']), names=np.array(['ножки', 'рама']))
    pr0, _m0 = PG.parts_from_masks(npz_c, tx, tex, {'Материал ножек': 'дерево'}, None, R)
    pr1, _m1 = PG.parts_from_masks(npz_c, tx, tex, {'Материал ножек': 'дерево'}, None, dict(R, bin_classes_by_role={'legs': ['straight']}))
    check(all(x['classes'] is None for x in pr0) and all(x['classes'] == ['straight'] for x in pr1), 'bin_classes_by_role: по умолчанию classes=None; при ключе у роли legs — [straight]')
    b_sw, _p, _s = PG.load_pattern([60.07, 8.21, 23.7], R, None)
    b_st, _p, _s = PG.load_pattern([60.07, 8.21, 23.7], R, ['straight'])
    check(b_sw['bin'] is not None and b_st['bin'] is not None and b_st.get('pattern_class') == 'straight' and b_sw['bin'] != b_st['bin'], f'тон ножек: без класса бин {b_sw["bin"]} ({b_sw.get("pattern_class")}), с классом straight — {b_st["bin"]}')

    # 12. library_max_de00 (T-63, замена no_grain_groups по имени): ключ меняет решение; светлая плита без близкого бина → ровный тон, тон дерева ножек — зерно
    white = dict(part(1, photo_sigma=2.0), tone_lab=[92.0, 0.5, 2.0], name='плита')
    legs = dict(part(2, photo_sigma=2.0), tone_lab=[60.07, 8.21, 23.7], name='ножки')
    p_off = PG.plan_grain([white, legs], dict(R, library_max_de00=None))
    p_on = PG.plan_grain([white, legs], dict(R, library_max_de00=12.0))
    check(p_off[1]['apply'] and p_off[2]['apply'], 'library_max_de00 не задан: любой тон получает ближайший бин (светлая плита тоже — как было)')
    check((not p_on[1]['apply']) and p_on[1]['reason'] == 'no_bin' and p_on[2]['apply'], f'library_max_de00=12: светлая плита → ровный тон (no_bin), ножки → зерно (бин {p_on[2]["bin"]["bin"]})')
    odd = dict(part(3, photo_sigma=2.0), tone_lab=[30.0, 40.0, -40.0], name='синяя')
    q_off = PG.plan_grain([odd], dict(R, library_max_de00=None))
    q_on = PG.plan_grain([odd], dict(R, library_max_de00=12.0))
    check(q_off[3]['apply'] and (not q_on[3]['apply']), 'library_max_de00 меняет выход и у цветной детали (без порога — бин дерева на синюю часть, с порогом — ровный тон)')

    bad_n = sum(1 for x in OK if not x)
    print(f'\n{len(OK) - bad_n}/{len(OK)} ok')
    sys.exit(1 if bad_n else 0)


main()
