#!/usr/bin/env python3
"""Тест шага «владелец текселя» tex_owner (+ стадия tex_owner_stage; T-20261126-97/1 фаза 2) на синтетике: плита-верх 2×1 клетки (4 грани в одной плоскости) + вертикальная ножка (2 грани, свои вершины, сварены по позиции),
текстура — шум. Проверяем: панели по излому 15°; D3 грань без роли берёт роль панели; D4 чужая роль (≤25 % панели) → большинство; D5 панель без ролей — голос смежных граней; владелец текселя (внутренность перекрывает
пограничное); отступ 5×5 только на непокрытые; узорная группа не красится; сторож «покрытые без покраски» = 0; стадия: выключено → ничего не пишет (байт в байт), «флаг меняет выход» (вкл ≠ выкл), исходник сохранён,
повтор даёт тот же результат, нет npz Ш4а → воздержание с причиной и visible.glb не тронут. Фаза 3 (tex_gutter_stage): дилатация — покрытые не меняются, поле = цвет ближайшего покрытого, ключ uv_gutter_px
(0 = выкл, байт в байт) меняет выход, сторож «непокрытые в полосе с |ΔL| > порога» = 0 после, повтор идемпотентен."""
import hashlib
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'salad', 'trellis'), HERE]
import remlab_tmp  # noqa: E402  (временное — в общий каталог с чисткой)
remlab_tmp.use('tests_tex_owner')
import tex_owner as TO  # noqa: E402
import tex_owner_stage as ST  # noqa: E402
from PIL import Image  # noqa: E402

OK = []
T = 64
TONES = np.array([[200, 120, 60], [40, 90, 160]], np.uint8)


def check(c, m):
    OK.append(bool(c))
    print(('ok   ' if c else 'FAIL ') + m)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def make_glb(path):
    import trimesh
    top = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 0, 1), (1, 0, 1), (2, 0, 1)]
    leg = [(0, 0, 0), (0, 0, 1), (0, -1, 0), (0, -1, 1)]                  # позиции верхней кромки x=0 повторены (свои вершины), в развёртке — отдельный остров
    V = np.array(top + leg, np.float64)
    uv_top = [(x / 2 * 0.4 + 0.1, z * 0.6 + 0.2) for x, _y, z in top]
    uv_leg = [(0.6 + z * 0.3, 0.2 + (-y) * 0.6) for _x, y, z in leg]
    UV = np.array(uv_top + uv_leg, np.float64)
    F = np.array([[0, 3, 4], [0, 4, 1], [1, 4, 5], [1, 5, 2], [6, 8, 9], [6, 9, 7]], np.int64)
    rng = np.random.default_rng(3)
    img = Image.fromarray(rng.integers(0, 256, (T, T, 3), dtype=np.uint8))
    m = trimesh.Trimesh(V, F, process=False, visual=trimesh.visual.TextureVisuals(uv=UV, material=trimesh.visual.material.PBRMaterial(baseColorTexture=img)))
    m.export(path)


def make_run(tmp, painted=(True, True), fg=(0, 0, 0, 2, 1, 1)):
    d = os.path.join(tmp, 'run', 'sku', '06-visible')
    os.makedirs(d)
    make_glb(os.path.join(d, 'visible.glb'))
    np.savez_compressed(os.path.join(d, 'part_material_masks.npz'), group_map=np.full((T, T), -1, np.int16), names=np.array(['верх', 'ножки']), tone_srgb=TONES, roles=np.array(['top', 'legs']),
                        texture_size=np.int32(T), painted_group=np.array(painted), material=np.array([0, 1], np.int32), face_group=np.array(fg, np.int16))
    return d


def test_roles():
    P = np.array([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 0, 1), (1, 0, 1), (2, 0, 1), (0, 0, 0), (0, 0, 1), (0, -1, 0), (0, -1, 1)], np.float64)
    F = np.array([[0, 3, 4], [0, 4, 1], [1, 4, 5], [1, 5, 2], [6, 8, 9], [6, 9, 7]], np.int64)
    rules = ST.load_rules()
    rr = rules['roles']
    nc, comp = TO.panels(P, F, rr['crease_deg'], rr['weld_scale'])
    check(nc == 2 and len(set(comp[:4])) == 1 and len(set(comp[4:])) == 1 and comp[0] != comp[4], 'панели: плита (4 грани) и ножка (2 грани) — две, излом 90° > 15°')
    fg, info = TO.face_roles(P, F, np.array([0, 0, 0, 2, 1, 1]), 2, rules)
    check(list(fg) == [0, 0, 0, 0, 1, 1] and info['граней_без_роли'] == 1, 'D3: грань без роли (значение ≥ числа групп) берёт роль большинства панели: %s' % fg.tolist())
    fg, info = TO.face_roles(P, F, np.array([0, 0, 0, 1, 1, 1]), 2, rules)
    check(list(fg) == [0, 0, 0, 0, 1, 1] and info['чужих_граней_на_панелях_других_ролей'] == 1, 'D4: чужая роль у 1 из 4 граней панели (25 %%) → большинство панели: %s' % fg.tolist())
    fg, _ = TO.face_roles(P, F, np.array([0, 0, 1, 1, 1, 1]), 2, rules)
    check(list(fg) == [0, 0, 1, 1, 1, 1], 'D4: чужих 2 из 4 (50 %%) > 25 %% — роли остаются как есть: %s' % fg.tolist())
    fg, info = TO.face_roles(P, F, np.array([0, 0, 0, 0, 2, 2]), 2, rules)
    check(list(fg) == [0, 0, 0, 0, 0, 0] and info['волн_по_сетке'] >= 1 and info['без_роли_осталось'] == 0, 'D5: панель без единой роли берёт голос смежных граней по сетке (сварено по позиции): %s' % fg.tolist())
    fg, info = TO.face_roles(P, F, np.array([2, 2, 2, 2, 2, 2]), 2, rules)
    check(info['без_роли_осталось'] == 6, 'нет ни одной роли — остаётся без роли (не выдумываем): %s' % info)
    rr2 = {**rules, 'roles': {**rr, 'alien_max_frac': 0.6}}
    fg, _ = TO.face_roles(P, F, np.array([0, 0, 1, 1, 1, 1]), 2, rr2)
    check(list(fg) == [0, 0, 0, 0, 1, 1], 'ключ alien_max_frac меняет выход: при 0,6 два чужих из четырёх уходят в большинство панели')


def test_owner(tmp):
    d = make_run(tmp)
    rules = ST.load_rules()
    P, UV, F = TO.read_geom(os.path.join(d, 'visible.glb'))
    ids = TO.owner_ids(UV, F, T, rules)
    cov = ids >= 0
    check(cov.any() and ids.max() < len(F), 'владелец текселя: покрытые тексели есть, номера граней в пределах')
    ids0 = TO.owner_ids(UV, F, T, {**rules, 'owner': {**rules['owner'], 'shrink_texel': 0.0}})
    inner = TO.owner_ids(UV, F, T, {**rules, 'owner': {**rules['owner'], 'shrink_texel': 0.75}})
    check(cov.sum() == (ids0 >= 0).sum() and (ids0 != inner).any(), 'проход 2 (сжатая грань) не меняет покрытие, но перераспределяет спорные тексели; ключ shrink_texel меняет выход')
    tex = np.random.default_rng(1).integers(0, 256, (T, T, 3), dtype=np.uint8)
    fg2 = np.array([0, 0, 0, 0, 1, 1])
    gm = np.full((T, T), -1, np.int16)
    new, gmap, per = TO.apply_owner(tex, gm.copy(), ids, fg2, np.array([True, True]), TONES, ['верх', 'ножки'], rules)
    rt = np.where(cov, fg2[np.clip(ids, 0, 5)], -1)
    check(bool((new[rt == 0] == TONES[0]).all()) and bool((new[rt == 1] == TONES[1]).all()), 'тексели граней группы = тон группы Ш4а')
    check(bool((gmap[rt == 0] == 0).all()) and bool((gmap[rt == 1] == 1).all()), 'group_map расширен на тексели владельца')
    import cv2
    near = cv2.dilate(cov.astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool)
    check(bool((new[~near] == tex[~near]).all()), 'далеко от островов (дальше отступа) текстура не тронута')
    pad_t = (~cov) & (gmap >= 0)
    check(pad_t.any() and bool((new[pad_t] == TONES[gmap[pad_t]]).all()), 'отступ на непокрытые тексели — тон ближайшей группы (%d текселей)' % int(pad_t.sum()))
    check(bool((new[cov & (rt == 0)] == TONES[0]).all()) and per['верх']['тексели_владельца'] == int((rt == 0).sum()), 'отчёт по группе: тексели_владельца = число текселей группы')
    g = TO.guard_unpainted(ids, gmap, None)
    check(g['не_покрашено'] == 0 and g['покрыто_текселей'] == int(cov.sum()), 'сторож «покрытые без покраски» = 0: %s' % g)
    g0 = TO.guard_unpainted(ids, gm, np.zeros((T, T), bool))
    check(g0['не_покрашено'] == int(cov.sum()) and g0['из_них_не_известно_с_06'] == int(cov.sum()), 'сторож считает: до шага все покрытые без покраски, «не известно с 06» — отдельно')
    new2, gmap2, per2 = TO.apply_owner(tex, gm.copy(), ids, fg2, np.array([True, False]), TONES, ['верх', 'ножки'], rules)
    check(bool((new2[rt == 1] == tex[rt == 1]).all()) and 'ножки' not in per2 and bool((gmap2[rt == 1] == -1).all()), 'узорная группа (painted_group=false) не красится и в group_map не входит')
    r5 = {**rules, 'owner': {**rules['owner'], 'pad_px': 1}}
    new3, _g3, _p3 = TO.apply_owner(tex, gm.copy(), ids, fg2, np.array([True, True]), TONES, ['верх', 'ножки'], r5, )
    check(int((new3 != tex).any(-1).sum()) < int((new != tex).any(-1).sum()), 'ключ pad_px меняет выход: отступ 1 перекрашивает меньше, чем 5')


def test_stage():
    with tempfile.TemporaryDirectory() as tmp:
        d = make_run(tmp)
        args = ['--run', os.path.join(tmp, 'run'), '--sku', 'sku']
        vis, pre, npz = os.path.join(d, 'visible.glb'), os.path.join(d, ST.PRE), os.path.join(d, 'part_material_masks.npz')
        s0, n0 = sha(vis), sha(npz)
        ST.main(args)
        check(sha(vis) == s0 and sha(npz) == n0 and not os.path.exists(pre) and not os.path.exists(os.path.join(d, ST.OUT)), 'выключено (enabled=false): ни один байт не изменён, следа нет')
        rp = os.path.join(tmp, 'rules-on.json')
        r = json.load(open(ST.RULES_PATH, encoding='utf-8'))
        r['enabled'] = True
        json.dump(r, open(rp, 'w', encoding='utf-8'), ensure_ascii=False)
        ST.main(args + ['--rules', rp])
        rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
        check(rep['abstain'] is None and sha(vis) != s0, 'включено: текстура переписана (флаг меняет выход), воздержания нет')
        check(os.path.exists(pre) and sha(pre) == s0, 'исходник сохранён как visible.pre-owner.glb (байт в байт)')
        z = np.load(npz)
        check(int((z['group_map'] >= 0).sum()) > 0 and rep['guard']['не_покрашено'] == 0, 'group_map расширен, сторож = 0: %s' % rep['guard'])
        js, binb = TO.read_glb(vis)
        tex = TO.tex_of(js, binb, 0)
        P, UV, F = TO.read_geom(vis)
        ids = TO.owner_ids(UV, F, T, ST.load_rules())
        rt = np.where(ids >= 0, np.array([0, 0, 0, 0, 1, 1])[np.clip(ids, 0, 5)], -1)
        check(bool((tex[rt == 0] == TONES[0]).all()) and bool((tex[rt == 1] == TONES[1]).all()), 'в GLB: грань без роли (4-я плиты) покрашена тоном панели, ножка — своим')
        s1 = sha(vis)
        ST.main(args + ['--rules', rp])
        check(sha(vis) == s1 and sha(pre) == s0, 'повторный запуск идёт от исходника и даёт тот же результат')
        ST.main(args + ['--force'])
        check(sha(vis) == s1, '--force при выключенных правилах = то же, что enabled=true')
    with tempfile.TemporaryDirectory() as tmp:
        d = make_run(tmp)
        os.remove(os.path.join(d, 'part_material_masks.npz'))
        s0 = sha(os.path.join(d, 'visible.glb'))
        ST.main(['--run', os.path.join(tmp, 'run'), '--sku', 'sku', '--force'])
        rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
        check(rep['abstain'] and 'part_material_masks' in rep['abstain'] and sha(os.path.join(d, 'visible.glb')) == s0, 'нет npz Ш4а → воздержание с причиной, visible.glb не тронут')
    with tempfile.TemporaryDirectory() as tmp:
        d = make_run(tmp, fg=(0, 0, 0, 2))
        ST.main(['--run', os.path.join(tmp, 'run'), '--sku', 'sku', '--force'])
        rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
        check(rep['abstain'] and 'разошлись' in rep['abstain'], 'face_group другой длины, чем граней → воздержание «меши разошлись»')
    for bad in ({'roles': {'crease_deg': 0}}, {'owner': {'pad_px': 4}}):
        r = json.load(open(ST.RULES_PATH, encoding='utf-8'))
        for k, v in bad.items():
            r[k] = {**r[k], **v}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'r.json')
            json.dump(r, open(p, 'w', encoding='utf-8'))
            try:
                ST.load_rules(p)
                check(False, 'правила вне пределов отвергаются: %s' % bad)
            except ValueError:
                check(True, 'правила вне пределов отвергаются: %s' % bad)
    check(json.load(open(ST.RULES_PATH, encoding='utf-8'))['enabled'] is False, 'в репозитории шаг выключен по умолчанию')


def _frame(face3_rgb, show3=True, n=100, own=None):
    """Кадр камеры на синтетике: грань 3 (без роли, отдана owner группе «верх») — квадрат 50×50 px; грани 0 (верх) и 4 (ножки) — свои квадраты."""
    ids = np.full((n, n), -1, np.int32)
    rgb = np.zeros((n, n, 3), np.uint8)
    h = n // 2
    if show3:
        ids[:h, :h] = 3
        rgb[:h, :h] = face3_rgb
    ids[h:, :h] = 0
    rgb[h:, :h] = TONES[0] if own is None else own
    ids[:h, h:] = 4
    rgb[:h, h:] = TONES[1]
    return ids, rgb, np.ones((n, n), bool), np.ones((n, n), np.float32)


def _tg(rules, **kw):
    return {**rules, 'tone_guard': {**rules['tone_guard'], **kw}}


def test_tone_guard():
    """Сторож «не отдавать» (T-20261126-121/2, уточнение директора по Fable 15 § 2): панель, чей цвет до owner далёк от тона группы, группе не отдаётся (роль остаётся прежней, метки зерна нет);
    СТОП — только при большой доле не отданной площади."""
    rules = ST.load_rules()
    P = np.array([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 0, 1), (1, 0, 1), (2, 0, 1), (0, 0, 0), (0, 0, 1), (0, -1, 0), (0, -1, 1)], np.float64)
    F = np.array([[0, 3, 4], [0, 4, 1], [1, 4, 5], [1, 5, 2], [6, 8, 9], [6, 9, 7]], np.int64)
    UV = np.array([(x / 2 * 0.4 + 0.1, z * 0.6 + 0.2) for x, _y, z in P[:6]] + [(0.6 + z * 0.3, 0.2 + (-y) * 0.6) for _x, y, z in P[6:]], np.float64)
    area = TO.face_areas(P, F)
    _n, comp = TO.panels(P, F, rules['roles']['crease_deg'], rules['roles']['weld_scale'])
    fg = np.array([0, 0, 0, 2, 1, 1])
    fg2 = np.array([0, 0, 0, 0, 1, 1])
    names = ['верх', 'ножки']
    both = np.array([True, True])
    share3 = float(area[3] / area.sum())

    def run(frame, rl=None, pg=both, f2=fg2, tex=None, ids_tex=None):
        i, c, v, k = frame
        return TO.guard_tone(i, c, v, fg, f2, comp, area, TONES, pg, names, rl or rules, k, tex, ids_tex)

    def row(r):
        return r['детали'][0] if r['детали'] else {}

    # 1. свой тон на фото → отдаётся
    r = run(_frame(TONES[0]))
    check(not r['стоп'] and r['не_отдать'] == [] and row(r)['решение'] == 'отдана' and abs(row(r)['dL']) < 1 and r['по_группам']['верх']['вердикт'] == 'ок', 'сторож: область owner своего тона — отдаётся, dL≈0: %s' % row(r))
    check(abs(r['доля_отдано_площади'] - share3) < 1e-3 and 'ножки' not in r['по_группам'], 'доля площади, розданной owner (одна грань из шести): %s' % r['доля_отдано_площади'])
    # 2. белая область → не отдаётся (грань 3), НЕ стоп (доля 1/6 < 0,25), причина в строке
    r = run(_frame((240, 240, 240)))
    check(r['не_отдать'] == [3] and row(r)['решение'] == 'не отдана' and 'ΔL' in row(r)['почему'] and not r['стоп'] and abs(r['доля_не_отдано_площади'] - share3) < 1e-3, 'сторож: белая область (тон группы оранжевый) — не отдаётся, но и не стоп: %s' % row(r))
    # 3. СТОП только при большой доле: порог stop_area_frac 0,1 < 1/6
    r = run(_frame((240, 240, 240)), _tg(rules, stop_area_frac=0.1))
    check(r['стоп'] and 'роль/группа не сходится с фото' in r['причина'] and 'чужой группе отдано' in r['причина'], 'сторож: не отдано больше stop_area_frac площади → СТОП с причиной (ключ меняет выход)')
    # 4. ключи dl_max / dab_max меняют выход
    r = run(_frame((240, 240, 240)), _tg(rules, dl_max=99.0, dab_max=199.0))
    check(r['не_отдать'] == [] and row(r)['решение'] == 'отдана', 'ключи dl_max/dab_max меняют выход: при 99/199 тот же белый отдаётся')
    # 5. тот же цвет по светлоте, другая цветность → по dab не отдаётся; лёгкий оттенок своего материала (dL < 5) — отдаётся
    r = run(_frame((140, 140, 140)))
    check(row(r)['решение'] == 'не отдана' and abs(row(r)['dL']) < 5 and 'цветности' in row(r)['почему'], 'сторож: светлота та же, цветность иная (серое вместо оранжевого) — не отдаётся по dab: %s' % row(r))
    r = run(_frame((200, 115, 58)))
    check(row(r)['решение'] == 'отдана' and abs(row(r)['dL']) < 5, 'сторож: лёгкий оттенок того же материала — отдаётся')
    # 6. не видна на фото и нет 06 → «не проверено», отдаётся
    r = run(_frame((240, 240, 240), show3=False))
    check(r['не_отдать'] == [] and not r['стоп'] and row(r)['решение'] == 'отдана' and 'не проверено' in row(r)['почему'] and r['по_группам']['верх']['вердикт'].startswith('не проверено'), 'сторож: не видна и нет 06 — «не проверено», отдаётся: %s' % row(r))
    # 7. косой угол (cos < cos_min) в цвет не считается
    i, c, v, k = _frame((240, 240, 240))
    r = TO.guard_tone(i, c, v, fg, fg2, comp, area, TONES, both, names, rules, k * 0.1)
    check(r['не_отдать'] == [] and 'не проверено' in row(r)['почему'], 'сторож: косой угол (cos < cos_min) — «не проверено»')
    # 8. узорная группа, owner ничего не менял, мелкая панель
    r = run(_frame((240, 240, 240)), pg=np.array([False, True]))
    check(r['не_отдать'] == [] and r['по_группам']['верх']['вердикт'].startswith('не проверено: узорная'), 'сторож: узорная группа (painted_group=false) не проверяется')
    r = run(_frame((240, 240, 240)), f2=fg)
    check(not r['стоп'] and r['по_группам'] == {} and r['доля_отдано_площади'] == 0.0 and r['не_отдать'] == [], 'сторож: owner ничего не менял — нечего проверять')
    r = run(_frame((240, 240, 240)), _tg(rules, min_area_frac=0.5))
    check(r['не_отдать'] == [3] and len(r['детали']) == 1, 'сторож: min_area_frac только прячет строки малых панелей, не отдаёт их без проверки (не отданная всё равно в строках)')
    r = run(_frame(TONES[0]), _tg(rules, min_area_frac=0.5))
    check(r['не_отдать'] == [] and r['детали'] == [], 'сторож: min_area_frac прячет строки малых ОТДАННЫХ панелей (ключ меняет выход)')
    # «сильно чужой» — только он считается для СТОПа: (140,140,140) — не отдана по цветности, но не сильно (dab 45 > 30 → сильно); тот же материал темнее на 17 L — не отдана, НЕ сильно (17 < stop_dl 20)
    r = run(_frame((85, 85, 85), own=(128, 128, 128)), _tg(rules, stop_area_frac=0.05))
    check(r['не_отдать'] == [3] and r['доля_сильно_чужой_площади'] == 0.0 and not r['стоп'], 'сторож: не отдана, но не «сильно чужая» (|ΔL| 17 < stop_dl) — не стоп даже при низком stop_area_frac')
    r = run(_frame((240, 240, 240)), _tg(rules, stop_area_frac=0.05))
    check(r['стоп'] and abs(r['доля_сильно_чужой_площади'] - share3) < 1e-3, 'сторож: белое — «сильно чужое» (|ΔL| ≥ stop_dl) — стоп при stop_area_frac 0,05: %s' % r['доля_сильно_чужой_площади'])
    # остаток: панели без данных (панель_min_px больше, чем пикселей у каждой) решаются пулом группы
    r = run(_frame((240, 240, 240)), _tg(rules, panel_min_px=100000, min_px=100000))
    check(r['не_отдать'] == [] and 'не проверено' in row(r)['почему'], 'сторож: данных не хватает и пулу — «не проверено», отдаётся')
    r = run(_frame((240, 240, 240)), _tg(rules, panel_min_px=2600, min_px=300))
    check(r['не_отдать'] == [3] and str(row(r)['панель']).startswith('остаток'), 'сторож: панель без данных идёт в остаток группы и решается там (белый остаток — не отдан): %s' % row(r).get('панель'))
    # 9. эталон: фото своих граней; своих пикселей мало — тон Ш4а
    i, c, v, k = _frame((240, 240, 240))
    v2 = v.copy()
    v2[50:, :50] = False
    r = run((i, c, v2, k))
    check(row(r)['решение'] == 'не отдана' and 'тон Ш4а' in row(r)['эталон'], 'сторож: своих пикселей группы на фото нет → эталон — тон Ш4а')
    r = run(_frame((85, 85, 85), own=(128, 128, 128)))
    check(row(r)['решение'] == 'не отдана' and 'фото своих граней' in row(r)['эталон'] and row(r)['dL'] < -5, 'сторож: эталон — фото своих граней; тот же материал темнее на 17 L — по критерию ΔL>5 не отдаётся')
    # 10. невидимая панель — по текстуре 06: белая не отдаётся, своего тона — отдаётся
    ids_t = TO.owner_ids(UV, F, T, rules)
    for label, col, want in (('белая', (240, 240, 240), 'не отдана'), ('своего тона', tuple(int(x) for x in TONES[0]), 'отдана')):
        tex = np.random.default_rng(5).integers(0, 256, (T, T, 3), dtype=np.uint8)
        for f in range(6):
            tex[ids_t == f] = TONES[0] if f != 3 else col
        r = run(_frame((240, 240, 240), show3=False), tex=tex, ids_tex=ids_t)
        d3 = row(r)
        check(d3.get('решение') == want and d3.get('цвет_из') == '06' and (want == 'отдана' or r['не_отдать'] == [3]), 'сторож: панель не видна на фото — цвет из текстуры 06, %s → %s: %s' % (label, want, d3))
    # 11. стадия: кадр из rel.npz Ш4а; не отдана → фасет остаётся без роли (текстура грани 3 не перекрашена), стоп = воздержание, файлы не тронуты
    def stage(frame, rl_over=None, with_rel=True):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_run(tmp)
            if with_rel:
                i2, c2, v2_, k2 = frame
                os.makedirs(os.path.join(d, '_partmaterial'))
                np.savez_compressed(os.path.join(d, '_partmaterial', 'rel.npz'), ids=i2, prgb_reg=c2, valid=v2_, cosf=k2, known=np.zeros((T, T), bool))
            vis, npz = os.path.join(d, 'visible.glb'), os.path.join(d, 'part_material_masks.npz')
            s0, n0 = sha(vis), sha(npz)
            args = ['--run', os.path.join(tmp, 'run'), '--sku', 'sku', '--force']
            if rl_over:
                r = json.load(open(ST.RULES_PATH, encoding='utf-8'))
                r['tone_guard'].update(rl_over)
                p = os.path.join(tmp, 'r.json')
                json.dump(r, open(p, 'w', encoding='utf-8'))
                args += ['--rules', p]
            ST.main(args)
            rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
            out = {'rep': rep, 'changed': sha(vis) != s0, 'npz_same': sha(npz) == n0, 'pre': os.path.exists(os.path.join(d, ST.PRE))}
            if not rep.get('abstain'):
                js, binb = TO.read_glb(vis)
                t1 = TO.tex_of(js, binb, 0)
                out['face3_painted'] = bool((t1[ids_t == 3] == TONES[0]).all())
                out['face0_painted'] = bool((t1[ids_t == 0] == TONES[0]).all())
            return out
    s = stage(_frame((240, 240, 240)))
    check(not s['rep']['abstain'] and s['changed'] and not s['face3_painted'] and s['face0_painted'] and s['rep']['tone_guard']['не_отдано_граней'] == 1, 'стадия: белая область не отдана — грань 3 НЕ закрашена тоном группы, грань 0 закрашена, в следе 1 грань')
    s = stage(_frame(TONES[0]))
    check(not s['rep']['abstain'] and s['face3_painted'] and s['rep']['tone_guard']['не_отдано_граней'] == 0, 'стадия: свой тон — область отдана и закрашена тоном группы')
    s = stage(_frame((240, 240, 240)), {'stop_area_frac': 0.1})
    check(bool(s['rep']['abstain']) and 'роль/группа не сходится с фото' in s['rep']['abstain'] and not s['changed'] and s['npz_same'] and not s['pre'], 'стадия: не отдано > stop_area_frac → воздержание (abstain_is_stop), visible.glb и npz не тронуты, pre-owner не создан')
    s = stage(_frame((240, 240, 240)), with_rel=False)
    check(not s['rep']['abstain'] and 'только текстура 06' in s['rep']['tone_guard']['кадр'], 'стадия: нет фото/позы и rel.npz — проверка по текстуре 06, шаг идёт: %s' % s['rep']['tone_guard'].get('кадр'))
    # 11б. счётчик «не проверено по фото» (T-121/3): панель решена по фото → не считается; по 06 → считается; нет данных → считается; узорные → считается; сумма = отданная доля
    def npf(r):
        return r['не_проверено_по_фото']
    r = run(_frame(TONES[0]))
    check(npf(r)['доля_площади'] == 0.0 and abs(npf(r)['по_фото'] - share3) < 1e-3 and npf(r)['доля_от_отданного'] == 0.0, 'счётчик: панель решена по пикселям фото — не считается (0), по_фото = отданная доля: %s' % npf(r))
    r = run(_frame((240, 240, 240), show3=False))
    check(abs(npf(r)['доля_площади'] - share3) < 1e-3 and abs(npf(r)['без_данных'] - share3) < 1e-3 and npf(r)['по_текстуре_06'] == 0.0 and npf(r)['доля_от_отданного'] == 1.0, 'счётчик: не видна и нет 06 — «без данных» = вся отданная доля: %s' % npf(r))
    tex = np.random.default_rng(5).integers(0, 256, (T, T, 3), dtype=np.uint8)
    for f in range(6):
        tex[ids_t == f] = TONES[0]
    r = run(_frame((240, 240, 240), show3=False), tex=tex, ids_tex=ids_t)
    check(abs(npf(r)['по_текстуре_06'] - share3) < 1e-3 and npf(r)['без_данных'] == 0.0 and abs(npf(r)['доля_площади'] - share3) < 1e-3, 'счётчик: панель решена по текстуре 06 — считается (по_текстуре_06): %s' % npf(r))
    r = run(_frame((240, 240, 240)), pg=np.array([False, True]))
    check(abs(npf(r)['узорные_группы'] - share3) < 1e-3 and abs(npf(r)['доля_площади'] - share3) < 1e-3, 'счётчик: узорная группа (не красится, не проверяется) — считается отдельной строкой: %s' % npf(r))
    r = run(_frame((240, 240, 240)), f2=fg)
    check(npf(r) == TO.not_photo_counter(0.0, 0.0, 0.0), 'счётчик: owner ничего не менял — все нули')
    for rr in (run(_frame(TONES[0])), run(_frame((240, 240, 240), show3=False)), run(_frame((240, 240, 240)), _tg(rules, panel_min_px=2600, min_px=300))):
        n_ = npf(rr)
        check(abs(n_['доля_площади'] + n_['по_фото'] - rr['доля_отдано_площади']) < 2e-4, 'счётчик: «не по фото» + «по фото» = отданная доля площади (%s + %s ≈ %s)' % (n_['доля_площади'], n_['по_фото'], rr['доля_отдано_площади']))
    check(TO.not_photo_counter(0.0, 0.0, 0.0)['доля_от_отданного'] == 0.0 and TO.not_photo_counter(0.1, 0.0, 0.0, 0.1)['доля_от_отданного'] == 0.5, 'счётчик: доля от отданного — 0 при пустом, 0,5 при половине')
    s = stage(_frame((240, 240, 240), show3=False), with_rel=False)
    check(not s['rep']['abstain'] and s['rep']['не_проверено_по_фото']['доля_площади'] > 0 and s['rep']['не_проверено_по_фото'] == s['rep']['tone_guard']['не_проверено_по_фото'], 'стадия: счётчик «не проверено по фото» в итоге шага и в следе tone_guard (одни и те же цифры): %s' % s['rep'].get('не_проверено_по_фото'))
    s = stage(_frame(TONES[0]))
    check(s['rep']['не_проверено_по_фото']['доля_площади'] == 0.0, 'стадия: все панели по фото — счётчик 0')
    # 12. правила: вне пределов отвергаются, _why есть
    for bad in ({'dl_max': 0}, {'min_px': 0}, {'cos_min': 1.5}, {'stop_area_frac': 2}, {'panel_min_texels': 0}):
        r = json.load(open(ST.RULES_PATH, encoding='utf-8'))
        r['tone_guard'] = {**r['tone_guard'], **bad}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'r.json')
            json.dump(r, open(p, 'w', encoding='utf-8'))
            try:
                ST.load_rules(p)
                check(False, 'правила tone_guard вне пределов отвергаются: %s' % bad)
            except ValueError:
                check(True, 'правила tone_guard вне пределов отвергаются: %s' % bad)
    check(json.load(open(ST.RULES_PATH, encoding='utf-8'))['tone_guard']['_why'], 'в правилах tone_guard есть _why')


def test_gutter():
    import tex_gutter_stage as GS
    with tempfile.TemporaryDirectory() as tmp:
        d = make_run(tmp)
        rules = ST.load_rules()
        P, UV, F = TO.read_geom(os.path.join(d, 'visible.glb'))
        ids = TO.owner_ids(UV, F, T, rules)
        cov = ids >= 0
        tex = np.random.default_rng(2).integers(0, 256, (T, T, 3), dtype=np.uint8)
        new0, n0 = TO.dilate_gutter(tex, ids, 0)
        check(n0 == 0 and new0 is tex, 'дилатация px=0 — текстура та же, ничего не перекрашено')
        new, n = TO.dilate_gutter(tex, ids, 2)
        check(bool((new[cov] == tex[cov]).all()), 'дилатация: покрытые тексели не меняются ни на байт')
        from scipy import ndimage
        dist = ndimage.distance_transform_edt(~cov)
        band = (~cov) & (dist <= 2)
        check(n == int(band.sum()) and n > 0 and bool((new[(~cov) & (dist > 2)] == tex[(~cov) & (dist > 2)]).all()), 'перекрашены ровно непокрытые не дальше 2 px (%d), дальше — как было' % n)
        _d, (iy, ix) = ndimage.distance_transform_edt(~cov, return_indices=True)
        check(bool((new[band] == tex[iy[band], ix[band]]).all()) and bool(cov[iy[band], ix[band]].all()), 'цвет поля = цвет ближайшего ПОКРЫТОГО тексела')
        new4, n4 = TO.dilate_gutter(tex, ids, 4)
        check(n4 > n and not np.array_equal(new4, new), 'ключ uv_gutter_px меняет выход: 4 px перекрашивает больше, чем 2')
        g0 = TO.guard_gutter(tex, ids, 2, 2.0)
        g1 = TO.guard_gutter(new, ids, 2, 2.0)
        check(g0['с_расхождением_L_больше_порога'] > 0 and g1['с_расхождением_L_больше_порога'] == 0 and g1['в_полосе_текселей'] == n, 'сторож: на шуме до дилатации расхождений много, после = 0: %s → %s' % (g0, g1))
        args = ['--run', os.path.join(tmp, 'run'), '--sku', 'sku']
        vis, pre = os.path.join(d, 'visible.glb'), os.path.join(d, GS.PRE)
        s0 = sha(vis)
        GS.main(args)
        check(sha(vis) == s0 and not os.path.exists(pre) and not os.path.exists(os.path.join(d, GS.OUT)), 'uv_gutter_px=0 (по умолчанию): ни один байт не изменён, следа нет')
        rp = os.path.join(tmp, 'rules-g2.json')
        r = json.load(open(ST.RULES_PATH, encoding='utf-8'))
        r['dilate']['uv_gutter_px'] = 2
        json.dump(r, open(rp, 'w', encoding='utf-8'), ensure_ascii=False)
        GS.main(args + ['--rules', rp])
        rep = json.load(open(os.path.join(d, GS.OUT), encoding='utf-8'))
        check(rep['abstain'] is None and sha(vis) != s0 and sha(pre) == s0, 'uv_gutter_px=2: текстура переписана (ключ меняет выход), исходник сохранён')
        check(rep['после']['с_расхождением_L_больше_порога'] == 0 and rep['перекрашено_текселей'] == n, 'в следе: сторож после = 0, перекрашено %d' % n)
        js, binb = TO.read_glb(vis)
        got = TO.tex_of(js, binb, 0)
        want, _n = TO.dilate_gutter(TO.tex_of(*TO.read_glb(pre), 0), ids, 2)
        check(np.array_equal(got, want), 'текстура в GLB = расчёт дилатации исходной текстуры (PNG без потерь)')
        s1 = sha(vis)
        GS.main(args + ['--rules', rp])
        check(sha(vis) == s1, 'повторный запуск идёт от исходника и даёт тот же результат')
        GS.main(args + ['--force-px', '2'])
        check(sha(vis) == s1, '--force-px 2 при нулевом ключе = то же, что uv_gutter_px=2')
        os.remove(vis)
        os.remove(pre)
        GS.main(args + ['--force-px', '2'])
        rep = json.load(open(os.path.join(d, GS.OUT), encoding='utf-8'))
        check(rep['abstain'] and 'visible.glb' in rep['abstain'], 'нет visible.glb → воздержание с причиной')
    for bad in ({'uv_gutter_px': -1}, {'uv_gutter_px': 65}, {'guard_dl_max': 0}):
        r = json.load(open(ST.RULES_PATH, encoding='utf-8'))
        r['dilate'] = {**r['dilate'], **bad}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'r.json')
            json.dump(r, open(p, 'w', encoding='utf-8'))
            try:
                ST.load_rules(p)
                check(False, 'правила dilate вне пределов отвергаются: %s' % bad)
            except ValueError:
                check(True, 'правила dilate вне пределов отвергаются: %s' % bad)
    check(json.load(open(ST.RULES_PATH, encoding='utf-8'))['dilate']['uv_gutter_px'] == 0, 'в репозитории дилатация выключена по умолчанию (uv_gutter_px=0)')


def main():
    test_roles()
    with tempfile.TemporaryDirectory() as tmp:
        test_owner(tmp)
    test_stage()
    test_tone_guard()
    test_gutter()
    bad = OK.count(False)
    print('\n%d проверок, провалов: %d' % (len(OK), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
