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
        # 3б. ключ правил axis_per_part ВКЛЮЧЁН → выход шага меняется (защита от «флаг молча не включился»: карту частей шаг грузит при любом ключе «ось детали», T-63 р.5d)
        os.makedirs(os.path.join(tmp, 'run', 'sku', '03-parts'), exist_ok=True)
        np.savez_compressed(os.path.join(tmp, 'run', 'sku', '03-parts', 'parts.npz'), part=np.array([0, 1], np.int64))     # грань 0 и грань 1 — разные части
        mpath = os.path.join(d, 'part_material_masks.npz')
        orig_npz = open(mpath, 'rb').read()
        zz = dict(np.load(mpath))
        gm2 = np.asarray(zz['group_map']).copy()
        gm2[gm2 == 1] = 0                                                                                                    # обе грани в одну группу «верх» (деталей в группе две — есть что разделять)
        np.savez_compressed(mpath, **dict(zz, group_map=gm2, face_group=np.array([0, 0], np.int16)))
        r0 = PG.load_rules()
        rp0, rp1 = os.path.join(tmp, 'rules0.json'), os.path.join(tmp, 'rules1.json')
        json.dump(dict(r0, axis_per_part=False, axis_per_part_roles=['top']), open(rp0, 'w', encoding='utf-8'))
        json.dump(dict(r0, axis_per_part=True, axis_per_part_roles=['top']), open(rp1, 'w', encoding='utf-8'))
        ST.main(args + ['--force', '--rules', rp0])
        ta = np.asarray(TV.load_shape(vis)[0]['tex']).copy()
        ST.main(args + ['--force', '--rules', rp1])
        tb = np.asarray(TV.load_shape(vis)[0]['tex'])
        check(not np.array_equal(ta, tb), 'axis_per_part=true меняет текстуру на синтетике (флаг включился, карта частей загружена)')
        open(mpath, 'wb').write(orig_npz)
        ST.main(args + ['--force'])                                                                                          # вернуть состояние для следующих проверок
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
    # 7. T-99/11 шаг 4: размах по фото (amp_strip) и ось по фото (axis_check.apply) — выключены по умолчанию; strip_sigma
    rl = PG.load_rules()
    check((rl.get('amp_strip') or {}).get('enabled') is False and (rl.get('axis_check') or {}).get('apply') is False, 'amp_strip.enabled и axis_check.apply выключены в rules-json (выкл = как в main)')
    n2 = 256
    rg = np.random.default_rng(3)
    base = np.linspace(40, 60, n2 * n2, dtype=np.float32).reshape(n2, n2)
    m_all = np.ones((n2, n2), bool)
    s_a = ST.strip_sigma(base + rg.normal(0, 1.0, (n2, n2)).astype(np.float32), m_all, 0.0073, 5, 100)
    s_b = ST.strip_sigma(base + rg.normal(0, 3.0, (n2, n2)).astype(np.float32), m_all, 0.0073, 5, 100)
    check(s_a is not None and s_b is not None and 2.4 < s_b / s_a < 3.6, 'strip_sigma растёт с размахом рисунка (σ 1 → 3): %.2f → %.2f; плавный свет (градиент 40…60) в полосу не входит' % (s_a, s_b))
    check(ST.strip_sigma(base, np.zeros((n2, n2), bool), 0.0073, 5, 100) is None, 'strip_sigma: маска пуста → None (нет оценки)')
    # T-99/12 шаг 5: полосы деталей фото — тень (плавный градиент шире blur_cm) вычтена, полоса рисунка 1–4 см остаётся
    pdr = json.load(open(os.path.join(HERE, 'rules', 'part-grain.json'), encoding='utf-8'))['photo_detail']
    check(pdr['enabled'] is False, 'photo_detail выкл по умолчанию')
    ppc_t, n3_ = 10.0, 400
    xx = np.arange(n3_, dtype=np.float32)[None, :].repeat(n3_, 0)
    shadow = (30.0 * xx / n3_).astype(np.float32)                          # плавный свет/тень на ВСЮ грань (40 см)
    stripes = (4.0 * np.sin(2 * np.pi * xx / (10.0 * ppc_t))).astype(np.float32)    # рисунок — период 10 см (дуги)
    sel_ = np.ones((n3_, n3_), bool)
    co_s, fi_s = ST.detail_bands(60.0 + shadow, sel_, ppc_t, pdr)
    co_t, fi_t = ST.detail_bands(60.0 + shadow + stripes, sel_, ppc_t, pdr)
    mid = (slice(100, 300), slice(100, 300))
    check(float(np.std(co_s[mid])) < 0.4 and float(np.std(fi_s[mid])) < 0.2, 'detail_bands: тень без рисунка — деталей ≈ 0 (крупное %.2f, мелкое %.2f)' % (float(np.std(co_s[mid])), float(np.std(fi_s[mid]))))
    check(float(np.std(co_t[mid])) > 1.5, 'detail_bands: полосы 10 см выживают в «крупном» (σ %.2f из 2,8)' % float(np.std(co_t[mid])))
    check(abs(float(np.mean(co_t[mid]))) < 0.5, 'detail_bands: деталь без сдвига тона (среднее ≈ 0: %.2f)' % float(np.mean(co_t[mid])))
    check(float(np.abs(co_t[~sel_]).sum()) == 0.0 and float(np.abs(fi_t[~sel_]).sum()) == 0.0, 'detail_bands: вне маски — ноль')
    # T-99/12 шаг 5: непокрытые тексели той же грани берут рисунок с видимой части по оси волокна (вертикаль), не старый шум
    rr = np.random.default_rng(3)
    gx, gz = np.meshgrid(np.linspace(0, 1, 60), np.linspace(0, 1, 80))        # боковая грань: x — глубина (горизонталь), z — высота (вертикаль, ось 2)
    side = np.stack([np.zeros(gx.size), gx.ravel(), gz.ravel()], 1)          # нормаль по оси 0
    Qs = np.vstack([side, side + np.array([0.0, 0.0, 0.0])])[: side.shape[0]]
    Ns_ = np.tile(np.array([-1.0, 0.0, 0.0]), (len(Qs), 1))
    stripes_ = np.sin(2 * np.pi * 4 * Qs[:, 1]).astype(np.float32)           # вертикальные полосы: зависят только от глубины (оси 1)
    covered = Qs[:, 2] < 0.5                                                 # нижняя половина видна, верхняя — за плитой
    d_ = np.where(covered, stripes_, 0.0).astype(np.float32)
    ing_ = np.ones(len(Qs), bool)
    nf_ = ST.fibre_fill(Qs, Ns_, ing_, covered.copy(), d_, 2, 0.05, 20.0, 200)
    check(int(nf_.sum()) == int((~covered).sum()), 'fibre_fill: заполнены все непокрытые тексели грани (%d)' % int(nf_.sum()))
    check(float(np.abs(d_[nf_] - stripes_[nf_]).max()) < 0.2, 'fibre_fill: рисунок продолжен вдоль волокна (полосы совпадают с полным, ошибка %.2f)' % float(np.abs(d_[nf_] - stripes_[nf_]).max()))
    d0_ = np.zeros(len(Qs), np.float32)
    check(int(ST.fibre_fill(Qs, Ns_, ing_, np.zeros(len(Qs), bool), d0_, 2, 0.05, 20.0, 200).sum()) == 0, 'fibre_fill: нет покрытых текселей — ничего не придумывает')
    top_n = np.tile(np.array([0.0, 0.0, 1.0]), (len(Qs), 1))                 # горизонтальная плоскость (нормаль по оси волокна) не заполняется
    check(int(ST.fibre_fill(Qs, top_n, ing_, covered.copy(), d_.copy(), 2, 0.05, 20.0, 200).sum()) == 0, 'fibre_fill: верх/низ (нормаль по оси волокна) не трогает')
    corner = np.stack([np.full(40, -0.01), np.linspace(0.3, 0.7, 40), np.linspace(0.0, 1.0, 40)], 1)    # скруглённое ребро рядом с гранью: нормаль 45° (|N|max < 0.8)
    Qc2 = np.vstack([Qs, corner])
    Nc2 = np.vstack([Ns_, np.tile(np.array([-0.7071, -0.7071, 0.0]), (40, 1))])
    cov2 = np.concatenate([covered, np.zeros(40, bool)])
    d2_ = np.concatenate([d_, np.zeros(40, np.float32)])
    nc_ = ST.fibre_fill(Qc2, Nc2, np.ones(len(Qc2), bool), cov2.copy(), d2_, 2, 0.05, 20.0, 200, 0.05)
    check(bool(nc_[-40:].all()), 'fibre_fill: скруглённое ребро (нормаль 45°) получает деталь ближайшей грани (%d/40)' % int(nc_[-40:].sum()))
    d3_ = np.concatenate([d_, np.zeros(40, np.float32)])
    nc0 = ST.fibre_fill(Qc2, Nc2, np.ones(len(Qc2), bool), cov2.copy(), d3_, 2, 0.05, 20.0, 200, 0.0)
    check(not bool(nc0[-40:].any()), 'fibre_fill: corner_max=0 — ребро не трогает (как раньше)')
    # оборот лица: боковая грань берёт рисунок лица (расстояние от лица = расстояние от ребра), внутренняя стенка и верх не трогаются
    rg2 = np.random.default_rng(5)
    zz, yy = np.meshgrid(np.linspace(-0.15, 0.15, 40), np.linspace(-0.24, 0.24, 50))
    front = np.stack([rg2.uniform(-0.24, 0.24, 2000), yy.ravel()[:2000], np.full(2000, -0.15)], 1)       # лицо: z=-0.15, нормаль -z, видно (use)
    left = np.stack([np.full(zz.size, -0.24), yy.ravel(), zz.ravel()], 1)                                # левая внешняя: x=-0.24, нормаль -x, фото не видит
    inner = np.stack([np.full(500, -0.22), rg2.uniform(-0.2, 0.2, 500), rg2.uniform(-0.1, 0.1, 500)], 1)  # внутренняя стенка левой: x=-0.22, нормаль +x
    right = np.stack([np.full(zz.size, 0.24), yy.ravel(), zz.ravel()], 1)                                # правая внешняя: x=+0.24, нормаль +x
    Qb = np.vstack([front, left, inner, right])
    Nb = np.vstack([np.tile([0.0, 0.0, -1.0], (len(front), 1)), np.tile([-1.0, 0.0, 0.0], (len(left), 1)), np.tile([1.0, 0.0, 0.0], (len(inner), 1)), np.tile([1.0, 0.0, 0.0], (len(right), 1))])
    use_b = np.zeros(len(Qb), bool)
    use_b[: len(front)] = True
    use_b[len(front) + len(left) + len(inner):] = rg2.uniform(size=len(right)) < 0.3        # правая видна на 30 % (< 0,9) → тоже оборачивается
    Qw_, wm_ = ST.wrap_points(Qb, Nb, np.ones(len(Qb), bool), use_b, np.zeros(len(Qb), int), 1, 0.9, 0.02)
    il_ = slice(len(front), len(front) + len(left))
    check(bool(wm_[il_].all()) and abs(float(np.abs(Qw_[il_, 2] + 0.15).max())) < 1e-9, 'wrap_points: левая внешняя грань → плоскость лица z=-0,15 (%d текс.)' % int(wm_[il_].sum()))
    check(float(np.abs(Qw_[il_, 0] - (-0.24 + (zz.ravel() + 0.15))).max()) < 1e-9, 'wrap_points: расстояние от ребра = расстоянию от лица (шпон оборачивает угол)')
    check(not bool(wm_[len(front) + len(left): len(front) + len(left) + len(inner)].any()), 'wrap_points: внутренняя стенка (не на краю детали) не оборачивается')
    check(bool(wm_[len(front) + len(left) + len(inner):].all()) and float(np.abs(Qw_[len(front) + len(left) + len(inner):, 0] - (0.24 - (zz.ravel() + 0.15))).max()) < 1e-9, 'wrap_points: правая грань (видна 30 %) оборачивается внутрь с другого края')
    Qw_off, _wm_off = ST.wrap_points(Qb, Nb, np.ones(len(Qb), bool), use_b, np.zeros(len(Qb), int), 1, 0.9, 0.02, 0.1)
    check(float(np.abs(Qw_off[il_, 0] - (-0.24 + 0.1 + (zz.ravel() + 0.15))).max()) < 1e-9, 'wrap_points: offset сдвигает источник от ребра вглубь лица (рисунок у ребра не зеркалится)')
    Qo = np.vstack([Qb, [[-0.5, 0.0, 0.0]]])
    No = np.vstack([Nb, [[-1.0, 0.0, 0.0]]])
    uo = np.concatenate([use_b, [False]])
    Qwo, wmo = ST.wrap_points(Qo, No, np.ones(len(Qo), bool), uo, np.zeros(len(Qo), int), 1, 0.9, 0.02)
    check(bool(wmo[len(front): len(front) + len(left)].all()), 'wrap_points: одинокий тексел-выброс далеко от края не смещает край детали (грань %d/%d)' % (int(wmo[len(front): len(front) + len(left)].sum()), len(left)))
    use_full = use_b.copy()
    use_full[len(front) + len(left) + len(inner):] = True
    _Qw2, wm2 = ST.wrap_points(Qb, Nb, np.ones(len(Qb), bool), use_full, np.zeros(len(Qb), int), 1, 0.9, 0.02)
    check(not bool(wm2[len(front) + len(left) + len(inner):].any()), 'wrap_points: грань, которую фото видит целиком (≥ 0,9) — прямой рисунок, не оборачивается')
    # проверка рваных границ: плавный стык двух источников → ratio ≈ 1; скачок на линии → ratio ≫ 1
    Tt = 64
    ti_t = np.arange(Tt * Tt)
    tag_t = np.where((ti_t % Tt) < 32, 1, 3).astype(np.int8)
    smooth_d = np.sin(ti_t % Tt / 10.0).astype(np.float32)
    jump_d = smooth_d + np.where(tag_t == 3, 6.0, 0.0).astype(np.float32)
    st_ok = ST.seam_stats(ti_t, Tt, np.zeros(Tt * Tt, int), tag_t, smooth_d, np.ones(Tt * Tt, bool))
    st_bad = ST.seam_stats(ti_t, Tt, np.zeros(Tt * Tt, int), tag_t, jump_d, np.ones(Tt * Tt, bool))
    check(st_ok['ratio'] < 2.0 and st_bad['ratio'] > 5.0, 'seam_stats: плавный стык ratio %.2f, скачок 6 L на линии ratio %.1f' % (st_ok['ratio'], st_bad['ratio']))
    xs_i = Qs[:, 1] * 100 + 3.0
    ys_i = 500 - Qs[:, 2] * 200                                              # кадр: y вдоль оси 2 (вертикаль), x вдоль оси 1
    check(ST.fibre_axis(Qs, xs_i, ys_i, covered, Ns_) == 2, 'fibre_axis: вертикаль кадра ↔ ось 2 модели')
    check(ST.fibre_axis(Qs, xs_i, ys_i, np.zeros(len(Qs), bool), Ns_) is None, 'fibre_axis: нет текселей «в лоб» → None')
    src_ = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'part_grain_stage.py'), encoding='utf-8').read()
    gm = np.zeros((200, 200), bool)
    gm[20:180, 20:120] = True                                                  # широкая грань 100 px
    gm[20:180, 130:150] = True                                                 # узкая деталь 20 px (кромка)
    sm_ = ST.sel_margin(gm, 3, 12)
    check(bool(sm_[100, 25:30].sum() == 0) and bool(sm_[100, 40]) and bool(sm_[100, 140]) and bool(sm_[100, 131 + 3 - 3 + 3] or sm_[100, 140]), 'sel_margin: у широкой грани отступ 12 px, узкая деталь (20 px) не съедена')
    check(int(sm_[:, 125:155].sum()) > 0.6 * int(gm[:, 125:155].sum()) * 0.5, 'sel_margin: узкая деталь сохраняет заметную долю площади')
    check("sel_s[yim, xim]" in src_ and "sel_s[yiw, xiw]" in src_ and pdr.get('sel_smooth_px', 0) >= 3, 'зеркало и оборот берут рисунок из гладкой маски sel_s (медиана маски: гладкий край), не из рваной')
    import cv2 as _cv
    rg3 = np.random.default_rng(7)
    m_jag = np.zeros((120, 120), bool)
    m_jag[40:, :] = True
    m_jag[34:40, :] = rg3.uniform(size=(6, 120)) < 0.45                        # рваная кромка (бахрома 6 px)
    m_sm = _cv.medianBlur(m_jag.astype(np.uint8) * 255, 15).astype(bool)
    top_j = np.array([int(np.argmax(m_jag[:, c])) for c in range(120)])
    top_s = np.array([int(np.argmax(m_sm[:, c])) for c in range(120)])
    check(float(np.std(top_s)) < 0.5 * float(np.std(top_j)), 'медиана маски: бахрома кромки сглажена (σ границы %.2f → %.2f)' % (float(np.std(top_j)), float(np.std(top_s))))
    check("rules.get('photo_detail') or {}).get('enabled')" in src_, 'шаг 5 идёт только под photo_detail.enabled')
    check("rules.get('amp_strip') or {}).get('enabled')" in src_ and 'plan=plan2' in src_, 'второй проход зерна идёт только под amp_strip.enabled')
    bad = sum(1 for x in OK if not x)
    print(f'\n{len(OK) - bad}/{len(OK)} ok')
    sys.exit(1 if bad else 0)


main()
