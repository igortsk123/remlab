#!/usr/bin/env python3
"""Тесты меры «есть рисунок» / «узор, не волокно» (T-20261125-93/3): выключатель байт в байт, окна и доля, три признака «узор» (повтор шага, направление от осей панели), порядок для «не видно»
(наследование → карточка → ровный), плоские/ровные ловушки (щели фасада, серая плита) без волокна, волокно вдоль оси остаётся. Синтетика (CI без данных товаров); реальные контроли — скрипт отчёта T-93/3."""
import copy
import os
import sys
import types

import numpy as np
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import part_grain as PG  # noqa: E402
import part_grain_measure as PGM  # noqa: E402

R = PG.load_rules()
PM = R['pattern_measure']
OK = []


def check(cond, msg):
    OK.append(bool(cond))
    print(('ok   ' if cond else 'FAIL ') + msg)


T = 256


def mesh():
    """Плита 120×60 см в плоскости XZ (нормаль Y), сетка 8×4 квадрата → 64 грани, развёртка — прямоугольник 230×115 px в текстуре T×T, линейная (оси панели ‖ осям развёртки)."""
    nx, ny = 8, 4
    V, UV = [], []
    for j in range(ny + 1):
        for i in range(nx + 1):
            V.append((i / nx * 1.2, 0.0, j / ny * 0.6))
            UV.append((0.05 + 0.90 * i / nx, 1.0 - (0.30 + 0.45 * j / ny)))
    F = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            F += [(a, a + 1, a + nx + 2), (a, a + nx + 2, a + nx + 1)]
    return np.array(V), np.array(F, np.int64), np.array(UV)


def frame(V, F, UV):
    fp, pn = PG.planes_for(V, F)
    return PGM.FaceFrame(V, F, UV, T, fp, pn, R)


def gmask_of(ff):
    return ff.ids >= 0


def fiber_img(seed=0, sig=1.2, n=T):
    """Волокно: горизонтальные нерегулярные линии (шаг не повторяется), слабая вариация вдоль."""
    rng = np.random.default_rng(seed)
    n2 = ndi.gaussian_filter(rng.normal(0, 1, (n, n)), (sig, 25.0), mode='wrap')            # линии длиной ~25 px, дальше узор другой (у настоящего волокна нет точного повтора вдоль оси)
    return 60.0 + 6.0 * n2 / n2.std() + rng.normal(0, 0.4, (n, n))


def rot_irregular(deg, seed=1):
    """Нерегулярные линии под углом deg к оси панели (повтора шага нет — признак «направление»)."""
    big = fiber_img(seed, 1.2, T * 2)
    r = ndi.rotate(big, deg, reshape=False, mode='reflect', order=1)
    return r[T // 2:T // 2 + T, T // 2:T // 2 + T]


def sine_img(deg, period=6.0):
    """Регулярные полосы (рейки/тиснение): синус, линии под углом deg к оси x."""
    y, x = np.mgrid[0:T, 0:T].astype(np.float64)
    a = np.radians(deg)
    return 60.0 + 4.0 * np.sin(2 * np.pi * (-x * np.sin(a) + y * np.cos(a)) / period)


def measure(img, ff, known=None):
    known = np.ones((T, T), bool) if known is None else known
    return PGM.measure_group(img, known, np.ones((T, T)), gmask_of(ff), PM, ff)


def main():
    V, F, UV = mesh()
    ff = frame(V, F, UV)
    pm_on = copy.deepcopy(R)
    pm_on['pattern_measure']['enabled'] = True

    # 0. правила и выключатель
    check(PM['enabled'] is False, 'pattern_measure по умолчанию: enabled=false')
    check(PGM.pm_rules(R) is None and PGM.pm_rules(pm_on) is not None, 'pm_rules: выкл → None, вкл → правила')
    check(abs(PM['p_center'] - (PM['p_yes'] + PM['p_no']) / 2) < 0.01 and PM['p_no'] < PM['p_yes'], 'пороги: p_center в середине полосы «не видно» (0,30–0,43), p_no < p_yes')
    tx = types.SimpleNamespace(ti=np.arange(100), Q=np.zeros((100, 3)), N=np.tile([0.0, 1.0, 0.0], (100, 1)), f=np.zeros(100, np.int64))
    parts = [{'id': 1, 'name': 'Panel', 'is_wood': True, 'tone_lab': [67.4, 9.8, 15.9], 'tone_sigma': 0.3, 'n_texels': 7200, 'photo_sigma': 1.5, 'role': 'top', 'card': {'Материал корпуса': 'ЛДСП 16 мм'}}]
    p_off = PG.plan_grain(parts, R)
    no_key = copy.deepcopy(R)
    no_key.pop('pattern_measure')
    p_nk = PG.plan_grain(parts, no_key)
    check('measure' not in p_off[1] and p_off[1]['apply'] == p_nk[1]['apply'] and p_off[1]['reason'] == p_nk[1]['reason'] and p_off[1]['amp'] == p_nk[1]['amp'],
          'выкл: решение part_grain такое же, как без ключа pattern_measure (мера ничего не добавляет)')
    tex = np.full((64, 64, 3), 150, np.uint8)
    o1 = PG.apply_grain(tex, tx, parts, {1: np.ones(100, bool)}, np.array([0]), np.array([[0.0, 1.0, 0.0]]), 100.0, (1, 0, 0), R, enabled=True)
    o2 = PG.apply_grain(tex, tx, parts, {1: np.ones(100, bool)}, np.array([0]), np.array([[0.0, 1.0, 0.0]]), 100.0, (1, 0, 0), no_key, enabled=True)
    check(o1[0].tobytes() == o2[0].tobytes() and 'measure' not in o1[1]['parts'][1], 'выкл: текстура и отчёт apply_grain байт в байт как без ключа')

    # 1. окна и доля
    m = measure(fiber_img(), ff)
    check(m['n_windows'] >= 10 and m['share'] is not None and m['share'] >= PM['p_yes'] and m['verdict'] == 'fiber' and m['ac_peak'] is not None and m['ac_peak'] < PM['ac_pattern_min'],
          f'волокно вдоль оси панели → «есть» и класс fiber ({m})')
    flat = np.full((T, T), 60.0) + np.random.default_rng(3).normal(0, 0.25, (T, T))
    m = measure(flat, ff)
    check(m['verdict'] in ('no', 'unseen') and m['verdict'] != 'fiber' and m['verdict'] != 'pattern', f'ровная плита с шумом (серый комод, щели не видны) → без рисунка ({m["verdict"]}, доля {m["share"]})')
    # щели фасада: три узкие тёмные линии на ровном фоне — перепады вырезаются как швы, группа остаётся «нет»/«не видно», не волокно
    sl = flat.copy()
    for xx in (60, 120, 180):
        sl[:, xx:xx + 2] -= 25.0
    m = measure(sl, ff)
    check(m['verdict'] != 'fiber', f'щели фасада на ровном фоне → не волокно ({m["verdict"]}, доля {m["share"]})')
    # мало надёжных → «не видно»
    kn = np.zeros((T, T), bool)
    kn[40:60, 40:60] = True
    m = measure(fiber_img(), ff, kn)
    check(m['verdict'] == 'unseen' and m['n_windows'] < PM['windows_min'] + 5, f'надёжной площади мало (A<{PM["area_min_px"]}) → «не видно» ({m["verdict"]}, A {m["area"]})')
    check(PGM.share_verdict(0.37, 10, 5000, PM) == 'не видно' and PGM.share_verdict(0.30, 10, 5000, PM) == 'не видно' and PGM.share_verdict(0.43, 10, 5000, PM) == 'есть'
          and PGM.share_verdict(0.299, 10, 5000, PM) == 'нет' and PGM.share_verdict(0.9, 1, 5000, PM) == 'не видно' and PGM.share_verdict(0.9, 10, 100, PM) == 'не видно', 'share_verdict: p=0,37 — «не видно»; ≥0,43 «есть»; <0,30 «нет»; мало окон/площади «не видно»')

    # 2. класс «узор»
    m = measure(sine_img(40.0), ff)
    check(m['verdict'] == 'pattern', f'регулярные диагональные полосы 40° (рельеф-ёлочка) → «узор» ({m})')
    m = measure(sine_img(90.0), ff)          # вертикальные регулярные рейки: направление вдоль оси панели, но повтор шага
    check(m['verdict'] == 'pattern' and m['ac_peak'] is not None and m['ac_peak'] >= PM['ac_pattern_min'], f'регулярные рейки вдоль оси → «узор» по повтору шага (направление не нужно) ({m})')
    m = measure(rot_irregular(40.0), ff)
    no_ac = copy.deepcopy(PM)
    no_ac['ac_pattern_min'] = 9.0                                  # признак повтора выключен — остаётся только направление
    m = PGM.measure_group(rot_irregular(40.0), np.ones((T, T), bool), np.ones((T, T)), gmask_of(ff), no_ac, ff)
    check(m['verdict'] == 'pattern' and m['dev_med'] is not None and m['dev_med'] >= PM['dev_pattern_min_deg'], f'нерегулярные линии под 40° к оси → «узор» по направлению (повтор шага выключен) ({m})')
    no_dev = copy.deepcopy(PM)
    no_dev['dev_pattern_min_deg'] = 99.0                           # направление выключено — остаётся повтор шага
    m = PGM.measure_group(sine_img(90.0), np.ones((T, T), bool), np.ones((T, T)), gmask_of(ff), no_dev, ff)
    check(m['verdict'] == 'pattern' and m['ac_peak'] >= PM['ac_pattern_min'], f'регулярные рейки → «узор» по повтору шага (направление выключено) ({m})')
    # синтетическое «волокно» регулярнее настоящего (ac_peak 0,2 против 0,00–0,02 у реального дерева стола) — повтор шага в этих двух проверках выключен, чтобы проверять именно направление; реальное волокно — контроль на данных
    m = PGM.measure_group(rot_irregular(10.0), np.ones((T, T), bool), np.ones((T, T)), gmask_of(ff), no_ac, ff)
    check(m['verdict'] == 'fiber', f'нерегулярные линии в 10° от оси (допуск волокна) → волокно остаётся ({m})')
    # круглая плоскость — ось неизвестна → признак направления «не видно»
    Vr, Fr, UVr = mesh()
    ffr = frame(Vr, Fr, UVr)
    for k in list(ffr.axes):
        c1, c2, _rl = ffr.axes[k]
        ffr.axes[k] = (c1, c2, True)
    m = PGM.measure_group(rot_irregular(40.0), np.ones((T, T), bool), np.ones((T, T)), gmask_of(ffr), no_ac, ffr)
    check(m['n_dev'] == 0 and m['verdict'] == 'fiber', f'круглая плоскость: ось неизвестна, по направлению «узор» не объявляем ({m["verdict"]}, окон с осью {m["n_dev"]})')

    # 3. порядок для «не видно»: наследование → карточка → ровный
    def pt(pid, verdict, tone, role='top', card=None, name='Panel'):
        return {'id': pid, 'name': name, 'role': role, 'tone_lab': tone, 'card': card, 'measure': {'verdict': verdict, 'why': 'тест'}}
    card_b = {'Материал корпуса': 'ЛДСП 16 мм', 'Материал ножек (опор)': 'деревянные (сращенный массив)'}
    res = PGM.resolve_patterns([pt(1, 'fiber', [60, 5, 15]), pt(2, 'unseen', [62, 5, 15], card=card_b)], pm_on)
    check(res[2]['decision'] == 'fiber' and res[2]['path'] == 'material' and res[2]['from'] == 1, 'не видно → материал товара: «есть» соседней группы того же тона решает (приоритет над карточкой ЛДСП)')
    res = PGM.resolve_patterns([pt(1, 'no', [60, 5, 15]), pt(2, 'unseen', [61, 5, 15], card={'Материал корпуса': 'массив дуба'})], pm_on)
    check(res[2]['decision'] == 'flat' and res[2]['path'] == 'inherit', 'не видно → наследует «нет» (ровный) даже при карточке «массив»')
    res = PGM.resolve_patterns([pt(1, 'pattern', [60, 5, 15]), pt(2, 'unseen', [61, 5, 15])], pm_on)
    check(res[1]['decision'] == 'flat' and res[2]['decision'] == 'flat' and res[2]['from'] == 1, '«узор» — ровный тон, наследуется как «нет»')
    res = PGM.resolve_patterns([pt(1, 'fiber', [30, 2, 5]), pt(2, 'unseen', [62, 5, 15], card=card_b)], pm_on)
    check(res[2]['path'] == 'card' and res[2]['decision'] == 'flat', 'тон дальше inherit_de76 → не наследует; карточка «ЛДСП» → ровный')
    res = PGM.resolve_patterns([pt(1, 'unseen', [60, 5, 15], role='legs', card=card_b), pt(2, 'unseen', [60, 5, 15], card=card_b)], pm_on)
    check(res[1]['decision'] == 'fiber' and res[1]['path'] == 'card' and res[2]['decision'] == 'flat' and res[2]['path'] == 'card', 'ножки: «сращенный массив» → волокно; корпус «ЛДСП» → ровный (семья по роли)')
    res = PGM.resolve_patterns([pt(1, 'fiber', [60, 5, 15], role='top'), pt(2, 'unseen', [60, 5, 15], role='legs', card={'Материал ножек': 'Металл'})], pm_on)
    check(res[2]['path'] != 'inherit' and res[2]['decision'] == 'flat', 'ножки не наследуют от столешницы (другая семья)')
    res = PGM.resolve_patterns([pt(1, 'unseen', [60, 5, 15], card=None)], pm_on)
    check(res[1]['decision'] == 'flat' and res[1]['path'] == 'default', 'карточки нет → ровный тон (default)')
    res = PGM.resolve_patterns([pt(1, 'unseen', [60, 5, 15], card={'Материал столешницы': 'Шпон МДФ'})], pm_on)
    check(res[1]['decision'] == 'fiber' and res[1]['path'] == 'card', '«шпон МДФ» — шпон главнее МДФ → волокно')
    res = PGM.resolve_patterns([pt(1, 'unseen', [60, 5, 15], card={'Материал фасада': 'МДФ 19 мм в пленке ПВХ', 'Материал корпуса': 'ЛДСП 16 мм'})], pm_on)
    check(res[1]['decision'] == 'flat', 'МДФ в плёнке ПВХ + ЛДСП → ровный (плёнка «под дуб» не даёт волокна, пока мера не увидела)')
    res = PGM.resolve_patterns([pt(1, 'unseen', [60, 5, 15], role='body', name='Seat Cushion', card={'Материал каркаса': 'фанера, древесные плиты'})], pm_on)
    check(res[1]['decision'] == 'flat' and res[1]['path'] == 'card', 'подушка/сиденье по имени — не дерево: карточка каркаса «фанера» к ней не относится (велюр Нумо)')
    res = PGM.resolve_patterns([pt(1, 'unseen', [60, 5, 15], card={'Материал корпуса': 'Пластик'})], pm_on)
    check(res[1]['decision'] == 'flat', 'слово «пластик» не принимается за породу (…тик)')

    # 4. plan_grain: ровный по мере/узору; волокно — как раньше
    base = {'name': 'Panel', 'is_wood': True, 'tone_lab': [67.4, 9.8, 15.9], 'tone_sigma': 0.3, 'n_texels': 7200, 'photo_sigma': 1.5, 'role': 'top', 'card': card_b}
    plan = PG.plan_grain([dict(base, id=1, measure={'verdict': 'fiber', 'why': 'т'}), dict(base, id=2, measure={'verdict': 'pattern', 'why': 'т'}),
                          dict(base, id=4, measure={'verdict': 'unseen', 'why': 'т'}), dict(base, id=5, role='legs', measure={'verdict': 'unseen', 'why': 'т'})], pm_on)
    check(plan[1]['apply'] and plan[1]['measure']['path'] == 'measure', 'plan_grain: «есть» → волокно кладётся')
    check(not plan[2]['apply'] and plan[2]['reason'] == 'measure_flat' and plan[2]['measure']['verdict'] == 'pattern', 'plan_grain: «узор» → библиотечное волокно не кладём (даже рядом с «есть» того же материала)')
    plan_no = PG.plan_grain([dict(base, id=3, measure={'verdict': 'no', 'why': 'т'})], pm_on)
    check(not plan_no[3]['apply'] and plan_no[3]['reason'] == 'measure_flat', 'plan_grain: «нет» → ровный тон')
    check(plan[4]['measure']['path'] == 'material' and plan[4]['apply'], 'plan_grain: «не видно» → материал товара: «есть» той же группы тона решает')
    check(plan[5]['measure']['path'] == 'card' and plan[5]['apply'], 'plan_grain: ножки «не видно» → карточка «массив» → волокно')
    nw = PG.plan_grain([dict(base, id=1, is_wood=False, measure={'verdict': 'fiber', 'why': 'т'})], pm_on)
    check(nw[1]['reason'] == 'not_wood' and 'measure' not in nw[1], 'не дерево по карточке — отказ not_wood раньше меры (мера только гасит, не включает)')

    # 5. T-93/4 А: «нет» — только у группы шире 2 окон и с окон ≥ порога
    flat = np.full((T, T), 60.0) + np.random.default_rng(3).normal(0, 0.25, (T, T))
    gm_all = gmask_of(ff)
    m = PGM.measure_group(flat, np.ones((T, T), bool), np.ones((T, T)), gm_all, PM, ff)
    check(m['verdict'] == 'no' and m['width'] >= 2 * PM['window_px'] * (1 + PM['edge_frac']) and m['n_windows'] >= PM['no_windows_min'] * (1 + PM['edge_frac']),
          f'А: широкая группа (ширина {m["width"]} px, окон {m["n_windows"]}) без рисунка → уверенное «нет»')
    strip = np.zeros((T, T), bool)
    strip[100:140, :] = True
    strip &= gm_all
    m = PGM.measure_group(flat, np.ones((T, T), bool), np.ones((T, T)), strip, PM, ff)
    check(m['verdict'] == 'unseen' and 'слабое' in m['why'] and m['width'] < 2 * PM['window_px'], f'А: узкая полоса (ножка, ширина {m["width"]} px < 2 окон) без рисунка → «не видно», не «нет» ({m["why"]})')
    few = np.zeros((T, T), bool)
    few[80:190, 20:100] = True
    few &= gm_all
    m = PGM.measure_group(flat, np.ones((T, T), bool), np.ones((T, T)), few, PM, ff)
    check(m['verdict'] == 'unseen' and m['n_windows'] < PM['no_windows_min'], f'А: широкая, но окон мало ({m["n_windows"]} < {PM["no_windows_min"]}) → «не видно» ({m["why"]})')
    check(PGM.group_width(np.zeros((8, 8), bool)) == 0 and PGM.group_width(np.ones((40, 40), bool)) >= 38, 'group_width: пусто — 0; квадрат 40×40 — ≈40')

    # Г: «на грани» — ближе edge_frac к порогу → «не видно» (повтор шага, направление)
    m0 = measure(sine_img(90.0), ff)
    a0 = m0['ac_peak']
    pm_t = copy.deepcopy(PM)
    pm_t['ac_pattern_min'] = a0                                    # значение РОВНО на пороге — внутри полосы
    m = PGM.measure_group(sine_img(90.0), np.ones((T, T), bool), np.ones((T, T)), gm_all, pm_t, ff)
    check(m['verdict'] == 'unseen' and 'на грани' in m['why'], f'Г: повтор шага на пороге (ac {a0}) → «не видно» ({m["why"]})')
    pm_t['ac_pattern_min'] = a0 / (1 + PM['edge_frac']) / 1.05     # значение выше полосы → уверенный «узор»
    m = PGM.measure_group(sine_img(90.0), np.ones((T, T), bool), np.ones((T, T)), gm_all, pm_t, ff)
    check(m['verdict'] == 'pattern', f'Г: повтор шага выше полосы порога → «узор» ({m["why"]})')
    pm_t['ac_pattern_min'] = a0 / (1 - PM['edge_frac']) * 1.05     # значение ниже полосы → не «узор»
    m = PGM.measure_group(sine_img(90.0), np.ones((T, T), bool), np.ones((T, T)), gm_all, pm_t, ff)
    check(m['verdict'] != 'pattern' and 'на грани' not in m['why'], f'Г: повтор шага ниже полосы порога → не «узор» ({m["verdict"]})')
    check(PM['dev_unsure_deg'][0] < PM['dev_pattern_min_deg'] < PM['dev_unsure_deg'][1], 'Г: полоса направления вокруг порога 20°')
    mid = 0.5 * (PM['dev_unsure_deg'][0] + PM['dev_unsure_deg'][1])
    pm_d = copy.deepcopy(PM)
    pm_d['ac_pattern_min'] = 9.0
    m = PGM.measure_group(rot_irregular(mid), np.ones((T, T), bool), np.ones((T, T)), gm_all, pm_d, ff)
    check(m['verdict'] == 'unseen' and 'направление' in m['why'], f'Г: направление {m["dev_med"]}° внутри полосы {PM["dev_unsure_deg"]} → «не видно» ({m["why"]})')

    # 6. T-93/4 Б, В: материал товара
    def pm_(pid, verdict, tone, role, name, card=None):
        return {'id': pid, 'name': name, 'role': role, 'tone_lab': tone, 'card': card, 'measure': {'verdict': verdict, 'why': 'тест'}}
    legs = [pm_(0, 'fiber', [60, 14, 24], 'legs', 'Leg'), pm_(8, 'unseen', [69, 13, 27], 'legs', 'Leg'), pm_(9, 'unseen', [72, 11, 23], 'legs', 'Leg')]
    res = PGM.resolve_patterns(legs, pm_on)
    check(all(res[i]['decision'] == 'fiber' for i in (0, 8, 9)) and res[8]['path'] == 'material' and res[9]['path'] == 'material' and res[9]['from'] == 0,
          'Б: ножки товара — один материал: «есть» у одной (g0) решает за «не видно» остальных (ножки Крита; тон ΔE 10 не мешает)')
    legs2 = [pm_(0, 'fiber', [60, 14, 24], 'legs', 'Leg'), pm_(8, 'no', [69, 13, 27], 'legs', 'Leg')]
    res = PGM.resolve_patterns(legs2, pm_on)
    check(res[8]['decision'] == 'fiber' and res[8]['path'] == 'material' and 'переопределено' in res[8]['why'], 'Б: уверенное «нет» той же семьи переопределяется «есть» материала (по слову: «есть» решает за все) — и помечается')
    res = PGM.resolve_patterns([pm_(0, 'fiber', [60, 14, 24], 'legs', 'Leg'), pm_(1, 'pattern', [60, 14, 24], 'legs', 'Leg')], pm_on)
    check(res[1]['decision'] == 'flat' and res[1]['path'] == 'measure', 'Б: «узор» — свойство поверхности, «есть» материала его не переопределяет')
    res = PGM.resolve_patterns([pm_(0, 'fiber', [60, 14, 24], 'legs', 'Leg'), pm_(1, 'no', [60, 14, 24], 'body', 'Seat Cushion'), pm_(2, 'unseen', [60, 14, 24], 'body', 'Back Cushion', card={'Материал каркаса': 'массив'})], pm_on)
    check(res[1]['decision'] == 'flat' and res[2]['decision'] == 'flat' and res[2]['path'] == 'card', 'Б: части с именем «не дерево» (подушки) в материал не входят: ни «есть» ножек, ни карточка «массив» им не подходят')
    res = PGM.resolve_patterns([pm_(0, 'fiber', [60, 14, 24], 'unknown', 'Leg'), pm_(1, 'unseen', [60, 14, 24], None, 'Foot')], pm_on)
    check(res[1]['decision'] == 'fiber' and res[1]['path'] == 'material', 'Б: роль не названа/unknown — ножки по имени (Leg/Foot) тоже один материал')
    res = PGM.resolve_patterns([pm_(0, 'fiber', [60, 14, 24], 'frame', 'Support Structure'), pm_(1, 'unseen', [60, 14, 24], 'legs', 'Leg', card={'Материал ножек': 'Металл'})], pm_on)
    check(res[1]['decision'] == 'flat' and res[1]['path'] == 'default', 'Б: рама с известной ролью frame — не ножки (слово support в имени не считается, когда роль названа)')
    res = PGM.resolve_patterns([pm_(1, 'no', [60, 5, 15], 'top', 'Panel'), pm_(2, 'pattern', [62, 5, 15], 'body', 'Panel'), pm_(3, 'unseen', [64, 5, 15], 'body', 'Panel')], pm_on)
    check(res[3]['from'] == 2 and res[3]['path'] == 'inherit', 'В: «не видно» наследует СНАЧАЛА от группы той же роли (body), хоть тон другой группы (top) ближе')
    res = PGM.resolve_patterns([pm_(1, 'no', [60, 5, 15], 'top', 'Panel'), pm_(3, 'unseen', [64, 5, 15], 'body', 'Panel')], pm_on)
    check(res[3]['from'] == 1 and res[3]['path'] == 'inherit', 'В: нет группы той же роли — берёт любую из того же материала')
    res = PGM.resolve_patterns([pm_(1, 'no', [30, 5, 15], 'top', 'Panel'), pm_(3, 'unseen', [64, 5, 15], 'body', 'Panel', card={'Материал корпуса': 'массив'})], pm_on)
    check(res[3]['path'] == 'card' and res[3]['decision'] == 'fiber', 'В: другой материал (тон дальше ΔE 6, не ножки) — не наследует, идёт по карточке')

    bad_n = sum(1 for x in OK if not x)
    print(f'\n{len(OK) - bad_n}/{len(OK)} ok')
    sys.exit(1 if bad_n else 0)


main()
