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


def test_tone_guard():
    rules = ST.load_rules()
    P = np.array([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 0, 1), (1, 0, 1), (2, 0, 1), (0, 0, 0), (0, 0, 1), (0, -1, 0), (0, -1, 1)], np.float64)
    F = np.array([[0, 3, 4], [0, 4, 1], [1, 4, 5], [1, 5, 2], [6, 8, 9], [6, 9, 7]], np.int64)
    area = TO.face_areas(P, F)
    _n, comp = TO.panels(P, F, rules['roles']['crease_deg'], rules['roles']['weld_scale'])
    fg = np.array([0, 0, 0, 2, 1, 1])
    fg2 = np.array([0, 0, 0, 0, 1, 1])
    names = ['верх', 'ножки']
    both = np.array([True, True])
    ids, rgb, valid, cos = _frame(TONES[0])
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, rules, cos)
    check(not r['стоп'] and r['по_группам']['верх']['вердикт'] == 'ок' and r['по_группам']['верх']['dE2000'] < 1, 'сторож: область owner своего тона — пропуск, ΔE ≈ 0: %s' % r['по_группам'])
    check(abs(r['доля_отдано_площади'] - float(area[3] / area.sum())) < 1e-3 and 'ножки' not in r['по_группам'], 'доля площади, розданной owner (одна грань из шести): %s' % r['доля_отдано_площади'])
    ids, rgb, valid, cos = _frame((240, 240, 240))
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, rules, cos)
    check(r['стоп'] and 'роль/группа не сходится с фото' in r['причина'] and r['по_группам']['верх']['вердикт'] == 'стоп' and r['по_группам']['верх']['dE2000'] > 10, 'сторож: область owner белая на фото, тон группы — оранжевый → СТОП с причиной: %s' % r['причина'])
    r2 = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, {**rules, 'tone_guard': {**rules['tone_guard'], 'de_max': 99.0}}, cos)
    check(not r2['стоп'], 'ключ tone_guard.de_max меняет выход: при 99 тот же белый не стоп')
    ids, rgb, valid, cos = _frame((240, 240, 240), show3=False)
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, rules, cos)
    check(not r['стоп'] and r['по_группам']['верх']['вердикт'].startswith('не проверено') and 'не видна' in r['по_группам']['верх']['вердикт'], 'сторож: область не видна на фото → «не проверено», НЕ стоп: %s' % r['по_группам']['верх']['вердикт'])
    ids, rgb, valid, cos = _frame((240, 240, 240))
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, rules, cos * 0.1)
    check(not r['стоп'] and 'не видна' in r['по_группам']['верх']['вердикт'], 'сторож: косой угол (cos < cos_min) в тон не считается → «не проверено»')
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, np.array([False, True]), names, rules, cos)
    check(not r['стоп'] and r['по_группам']['верх']['вердикт'].startswith('не проверено: узорная'), 'сторож: узорная группа (painted_group=false) не проверяется')
    r = TO.guard_tone(ids, rgb, valid, fg, fg, comp, area, TONES, both, names, rules, cos)
    check(not r['стоп'] and r['по_группам'] == {} and r['доля_отдано_площади'] == 0.0, 'сторож: owner ничего не менял — нечего проверять')
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, {**rules, 'tone_guard': {**rules['tone_guard'], 'min_area_frac': 0.5}}, cos)
    check(not r['стоп'] and 'мала' in r['по_группам']['верх']['вердикт'], 'сторож: область меньше min_area_frac не проверяется (ключ меняет выход)')
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, {**rules, 'tone_guard': {**rules['tone_guard'], 'bad_min_px': 5000}}, cos)
    check(not r['стоп'] and r['по_группам']['верх']['вердикт'] == 'ок' and r['по_группам']['верх']['плохих_px'] > 0, 'сторож: плохих пикселей меньше bad_min_px — не стоп, но в следе (ключ меняет выход)')
    # свет, а не материал: тот же серый материал темнее на ~20 L (другая сторона к свету) — при kl=2.5 пропуск, при kl=1 стоп; эталон — фото своих граней
    ids, rgb, valid, cos = _frame((85, 85, 85), own=(128, 128, 128))
    r = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, rules, cos)
    r1 = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, TONES, both, names, {**rules, 'tone_guard': {**rules['tone_guard'], 'kl': 1.0}}, cos)
    check(not r['стоп'] and r1['стоп'] and 'фото своих граней' in r['по_группам']['верх']['эталон'], 'сторож: разница только в светлоте — ослабление kl=2.5 пропускает, kl=1 стопит; эталон — фото своих граней группы: dE %s / %s' % (r['по_группам']['верх']['dE2000'], r1['по_группам']['верх']['dE2000']))
    ids, rgb, valid, cos = _frame((240, 240, 240))
    valid2 = valid.copy()
    valid2[50:, :50] = False                                           # своих пикселей группы на фото нет → эталон — тон Ш4а
    r = TO.guard_tone(ids, rgb, valid2, fg, fg2, comp, area, TONES, both, names, rules, cos)
    check(r['стоп'] and 'тон Ш4а' in r['по_группам']['верх']['эталон'], 'сторож: своих пикселей группы на фото нет → эталон — тон Ш4а (и белое против оранжевого — стоп)')
    # стадия: кадр из rel.npz Ш4а; стоп = воздержание шага (в конвейере abstain_is_stop), visible.glb и npz не тронуты
    for label, kw, want in (('белая область → стоп', dict(face3_rgb=(240, 240, 240)), 'stop'), ('свой тон → пропуск', dict(face3_rgb=TONES[0]), 'pass'), ('область не видна → не проверено', dict(face3_rgb=(240, 240, 240), show3=False), 'unseen')):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_run(tmp)
            i2, c2, v2, k2 = _frame(**kw)
            os.makedirs(os.path.join(d, '_partmaterial'))
            np.savez_compressed(os.path.join(d, '_partmaterial', 'rel.npz'), ids=i2, prgb_reg=c2, valid=v2, cosf=k2, known=np.zeros((T, T), bool))
            vis, npz = os.path.join(d, 'visible.glb'), os.path.join(d, 'part_material_masks.npz')
            s0, n0 = sha(vis), sha(npz)
            ST.main(['--run', os.path.join(tmp, 'run'), '--sku', 'sku', '--force'])
            rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
            tg = rep.get('tone_guard') or {}
            if want == 'stop':
                check(bool(rep['abstain']) and 'роль/группа не сходится с фото' in rep['abstain'] and tg.get('стоп') and sha(vis) == s0 and sha(npz) == n0 and not os.path.exists(os.path.join(d, ST.PRE)), 'стадия, %s: воздержание с причиной, visible.glb и npz не тронуты' % label)
            elif want == 'pass':
                check(rep['abstain'] is None and tg.get('стоп') is False and sha(vis) != s0, 'стадия, %s: шаг идёт, текстура переписана' % label)
            else:
                check(rep['abstain'] is None and tg['по_группам']['верх']['вердикт'].startswith('не проверено') and sha(vis) != s0, 'стадия, %s: шаг идёт, в следе «не проверено»' % label)
    with tempfile.TemporaryDirectory() as tmp:
        d = make_run(tmp)
        ST.main(['--run', os.path.join(tmp, 'run'), '--sku', 'sku', '--force'])
        rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
        check(rep['abstain'] is None and 'нет фото/позы' in rep['tone_guard']['не_проверено'], 'стадия: нет ни фото+позы, ни rel.npz → «не проверено», шаг идёт как раньше')
    for bad in ({'de_max': 0}, {'min_px': 0}, {'cos_min': 1.5}):
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
