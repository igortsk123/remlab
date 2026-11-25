#!/usr/bin/env python3
"""Тест шага part_grain_stage на синтетике (T-20261124-69/4): плита-верх, два участка (дерево «верх» / металл «ножки»), камера этапа 4 и фото — поддельные файлы. Проверяем: выключено → ничего не пишет;
--force → зерно только на дереве, тон держится, исходник сохранён, повтор даёт тот же результат; нет npz Ш4а → воздержание с причиной, visible.glb не тронут; σL фото по группам; масштаб по карточке."""
import io
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'salad', 'trellis'), HERE]
import remlab_tmp  # noqa: E402  (временное — в общий каталог с чисткой)
remlab_tmp.use('tests_part_grain_stage')
import part_grain as PG  # noqa: E402
import part_grain_stage as ST  # noqa: E402
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402
import tex_visible as TV  # noqa: E402
from PIL import Image  # noqa: E402

OK = []
TONE = [67.4, 9.8, 15.9]


def check(c, m):
    OK.append(bool(c))
    print(('ok   ' if c else 'FAIL ') + m)


def make_glb(path, T=128):
    import trimesh
    V = np.array([[-0.6, 0, -0.3], [0.6, 0, -0.3], [0.6, 0, 0.3], [-0.6, 0, 0.3]], np.float64)
    F = np.array([[0, 2, 1], [0, 3, 2]], np.int64)                 # нормаль +Y
    UV = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float64)
    rgb = TF.lab2rgb(np.asarray([TONE], np.float64))[0]
    img = Image.fromarray(np.tile(rgb, (T, T, 1)).astype(np.uint8))
    m = trimesh.Trimesh(V, F, process=False, visual=trimesh.visual.TextureVisuals(uv=UV, material=trimesh.visual.material.PBRMaterial(baseColorTexture=img)))
    m.export(path)


def make_run(tmp):
    d = os.path.join(tmp, 'run', 'sku', '06-visible')
    os.makedirs(d)
    make_glb(os.path.join(d, 'visible.glb'))
    g = TV.load_shape(os.path.join(d, 'visible.glb'))[0]
    ctr, size = TF.frame_of([g])
    P = (np.asarray(g['V']) - ctr) / size
    tx = TF.Tex(g, P, TF._grid(g), None)
    gm = np.full(g['tex'].shape[:2], -1, np.int16)
    gm.reshape(-1)[tx.ti] = tx.f.astype(np.int16)                  # грань 0 → группа 0 («верх», дерево), грань 1 → группа 1 («ножки», металл)
    rgb = TF.lab2rgb(np.asarray([TONE, TONE], np.float64))
    np.savez_compressed(os.path.join(d, 'part_material_masks.npz'), group_map=gm, names=np.array(['верх', 'ножки']), tone_srgb=rgb, roles=np.array(['top', 'legs']),
                        texture_size=np.int32(gm.shape[0]), painted_group=np.array([True, True]), material=np.array([0, 1], np.int32), face_group=np.array([0, 1], np.int16))
    pr = os.path.join(tmp, 'pose')
    rv = os.path.join(pr, 'stages', 'render_view0')
    os.makedirs(rv)
    n = 64
    ids = np.zeros((n, n), np.int32)
    ids[:, n // 2:] = 1
    np.savez_compressed(os.path.join(rv, 'ids.npz'), ids=ids)
    np.savez_compressed(os.path.join(rv, 'uv.npz'), uv=np.zeros((n, n, 2), np.float32))
    np.savez_compressed(os.path.join(rv, 'depth.npz'), depth=np.ones((n, n), np.float32), px_len=1.0)
    Image.fromarray(np.full((n, n), int(0.9 * 65535), np.uint16)).save(os.path.join(rv, 'aoi_cos16.png'))
    Image.fromarray(np.full((n, n), 255, np.uint8)).save(os.path.join(rv, 'mask.png'))
    json.dump({'registration': {'P': [1, 0, 0, 0, 1, 0, 0, 0, 1], 'iou': 1.0}, 'camera': {'az': 30.0, 'el': 40.0, 'd': 3.0}}, open(os.path.join(pr, 'stage_loss.json'), 'w'))
    rng = np.random.default_rng(5)
    ph = np.clip(150 + rng.normal(0, 8, (n, n, 1)), 0, 255).repeat(3, 2)
    Image.fromarray(np.concatenate([ph, np.full((n, n, 1), 255)], 2).astype(np.uint8)).save(os.path.join(tmp, 'photo.png'))
    json.dump({'Материал столешницы': 'массив дуба', 'Материал ножек': 'металл', 'Габаритные размеры, длина, см': '120'}, open(os.path.join(tmp, 'card.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return d, pr


def main():
    TV.zbuffer_fix = lambda geoms, st: (st, {})                     # синтетический кадр без глубины — подгонка z-буфера не нужна
    with tempfile.TemporaryDirectory() as tmp:
        d, pr = make_run(tmp)
        args = ['--run', os.path.join(tmp, 'run'), '--sku', 'sku', '--photo', os.path.join(tmp, 'photo.png'), '--pose-run', pr, '--card', os.path.join(tmp, 'card.json')]
        vis, pre = os.path.join(d, 'visible.glb'), os.path.join(d, ST.PRE)
        b0 = open(vis, 'rb').read()
        # 1. выключено (rules.enabled=false, без --force): ничего не пишет
        check(PG.load_rules()['enabled'] is False and ST.main(args) == 0 and open(vis, 'rb').read() == b0 and not os.path.exists(os.path.join(d, ST.OUT)) and not os.path.exists(pre), 'выключено: ни visible.glb, ни следа, ни копии не создано')
        # 2. --force: зерно на дереве, металл нетронут, тон держится
        check(ST.main(args + ['--force']) == 0, 'шаг отработал (rc=0)')
        rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
        check(rep['abstain'] is None and rep['applied'] == 1 and rep['skipped'] == {'not_wood': 1}, f'след: applied=1, пропуск not_wood=1 ({rep["skipped"]})')
        check(rep['groups']['0']['amp_source'] == 'photo' and rep['photo_sigma']['верх'] is not None and rep['photo_sigma']['верх'] > 0.8, f'σL фото группы «верх» {rep["photo_sigma"]["верх"]} ≥ 0,8 → амплитуда по фото')
        check(rep['cm_source'] == 'card', 'масштаб по карточке (Габаритные размеры 120 см)')
        check(open(pre, 'rb').read() == b0, 'исходный visible.glb сохранён как visible.pre-grain.glb')
        g0 = TV.load_shape(pre)[0]
        g1 = TV.load_shape(vis)[0]
        mp = np.load(os.path.join(d, 'part_material_masks.npz'))
        gm = mp['group_map']
        t0, t1 = np.asarray(g0['tex']), np.asarray(g1['tex'])
        top, leg = gm == 0, gm == 1
        check(np.array_equal(t0[~top], t1[~top]), 'вне группы «верх» (металл, непокрытое) текстура байт в байт')
        lab = TC.rgb2lab(t1[top])
        de = float(TC.de2000_v(np.median(lab, 0)[None], np.asarray([TONE]))[0])
        check(float(lab[:, 0].std()) > 0.3 and de < 1.0, f'зерно легло: σL {lab[:, 0].std():.2f}, тон держится ΔE00 {de:.2f}')
        check(np.array_equal(np.asarray(g0['V']), np.asarray(g1['V'])) and np.array_equal(np.asarray(g0['F']), np.asarray(g1['F'])) and np.allclose(np.asarray(g0['UV']), np.asarray(g1['UV'])), 'геометрия и UV те же')
        mkp = os.path.join(d, ST.MASK)
        mk = np.asarray(Image.open(mkp).convert('L')) > 127
        check(mk.shape == gm.shape and np.array_equal(mk, top) and not (mk & leg).any(), 'метка part_grain_mask.png: ровно тексели группы-дерева, металл не помечен (07 там фактуру кладёт сам)')
        # 3. повтор идёт от исходника: результат тот же, исходник не перезаписан
        ST.main(args + ['--force'])
        t2 = np.asarray(TV.load_shape(vis)[0]['tex'])
        check(np.array_equal(t1, t2) and open(pre, 'rb').read() == b0, 'повторный запуск: тот же результат, исходник цел (зерно не накладывается дважды)')
        # 3б. плоское фото (photo_grain False): зерна нет, текстура = исходник, но метка «фактуру не класть» стоит — 07 не кладёт своей на ровной МДФ (T-69/6)
        n = 64
        Image.fromarray(np.concatenate([np.full((n, n, 3), 150), np.full((n, n, 1), 255)], 2).astype(np.uint8)).save(os.path.join(tmp, 'photo.png'))
        check(ST.main(args + ['--force']) == 0, 'плоское фото: шаг отработал')
        rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
        check(rep['abstain'] is None and rep['applied'] == 0 and rep['flat_groups'] == ['верх'] and rep['groups']["0"]["reason"] == "no_photo_grain", f'плоское фото: applied=0, flat_groups={rep.get("flat_groups")}, причина {rep["groups"]["0"]["reason"]}')
        check(open(vis, 'rb').read() == b0, 'плоское фото: visible.glb = исходник (зерно прежнего прогона не осталось)')
        mk = np.asarray(Image.open(mkp).convert('L')) > 127
        check(np.array_equal(mk, top) and not (mk & leg).any(), 'плоское фото: метка стоит на тексельях «верха» (07 фактуру не кладёт), на металле — нет')
        # 4. нет npz Ш4а → воздержание с причиной, visible.glb не тронут
        os.remove(os.path.join(d, 'part_material_masks.npz'))
        before = open(vis, 'rb').read()
        ST.main(args + ['--force'])
        rep = json.load(open(os.path.join(d, ST.OUT), encoding='utf-8'))
        check(not os.path.exists(mkp), 'воздержание: старая метка зерна удалена (07 не пропускает фактуру там, где зерна нет)')
        check('part_material_masks' in (rep['abstain'] or '') and open(vis, 'rb').read() == before, f'нет npz → воздержание: «{rep["abstain"]}», visible.glb не тронут')
    # 5. σL по группам: верх — грани вверх, остальные — по cos
    n = 40
    rng = np.random.default_rng(1)
    L = (50 + rng.normal(0, 2.0, (n, n))).astype(np.float32)
    ids = np.zeros((n, n), np.int32)
    ids[:, n // 2:] = 1
    s = ST.group_photo_sigma(L, np.ones((n, n), bool), ids, np.full((n, n), 0.9, np.float32), np.array([0, 1]), ['top', 'legs'], np.array([1.0, 0.0]), PG.load_rules())
    check(s[0] is not None and 1.2 < s[0] < 2.8 and s[1] is not None and 1.2 < s[1] < 2.8, f'σL по группам: верх (грань вверх) {s[0]:.2f}, боковая (cos 0,9) {s[1]:.2f}')
    s2 = ST.group_photo_sigma(L, np.ones((n, n), bool), ids, np.full((n, n), 0.1, np.float32), np.array([0, 1]), ['top', 'legs'], np.array([1.0, 0.0]), PG.load_rules())
    check(s2[1] is None and s2[0] is not None, 'скользящий угол (cos<0,3): у боковой группы σL нет (None), у верха — считается с любого угла')
    # 6. масштаб по карточке
    cm = PG.cm_per_unit(2.0, {'Габаритные размеры, длина, см': '120', 'Габаритные размеры, высота, см': '75'}, PG.load_rules())
    check(abs(cm - 60.0) < 1e-9 and PG.cm_per_unit(2.0, {}, PG.load_rules()) is None and PG.cm_per_unit(2.0, None, PG.load_rules()) is None, 'cm_per_unit: наибольший габарит карточки / габарит меша; нет карточки → None')
    bad = sum(1 for x in OK if not x)
    print(f'\n{len(OK) - bad}/{len(OK)} ok')
    sys.exit(1 if bad else 0)


main()
