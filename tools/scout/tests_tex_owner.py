#!/usr/bin/env python3
"""Тест шага «владелец текселя» tex_owner (+ стадия tex_owner_stage; T-20261126-97/1 фаза 2) на синтетике: плита-верх 2×1 клетки (4 грани в одной плоскости) + вертикальная ножка (2 грани, свои вершины, сварены по позиции),
текстура — шум. Проверяем: панели по излому 15°; D3 грань без роли берёт роль панели; D4 чужая роль (≤25 % панели) → большинство; D5 панель без ролей — голос смежных граней; владелец текселя (внутренность перекрывает
пограничное); отступ 5×5 только на непокрытые; узорная группа не красится; сторож «покрытые без покраски» = 0; стадия: выключено → ничего не пишет (байт в байт), «флаг меняет выход» (вкл ≠ выкл), исходник сохранён,
повтор даёт тот же результат, нет npz Ш4а → воздержание с причиной и visible.glb не тронут."""
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


def main():
    test_roles()
    with tempfile.TemporaryDirectory() as tmp:
        test_owner(tmp)
    test_stage()
    bad = OK.count(False)
    print('\n%d проверок, провалов: %d' % (len(OK), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
