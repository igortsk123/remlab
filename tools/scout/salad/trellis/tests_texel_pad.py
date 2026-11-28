"""Тесты заливки непокрытых текселей (tools/scout/texel_pad.py; T-20261125-70). Синтетика, без GPU и сети.
Остров + зазор: после заливки зазор у острова = цвет острова, покрытое не меняется ни на единицу, дальше `passes` — как было; правила — только из paint-fill.json;
писатель 07/шва `tex_fill.write_glb(pad=True)` пишет залитую текстуру и отдаёт отчёт, без pad — как раньше.
Запуск: python tests_texel_pad.py → «ошибок 0»."""
import os as _rt_os  # noqa: E402
import sys as _rt_sys  # noqa: E402
_rt_sys.path.append(_rt_os.path.join(_rt_os.path.dirname(_rt_os.path.abspath(__file__)), '../..'))
import remlab_tmp  # noqa: E402,I001  — временное теста на диске и с уборкой при выходе (T-20261107-13)
remlab_tmp.use('tests_texel_pad')
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np
from scipy.ndimage import distance_transform_edt
import tex_fill as TF
import texel_pad as TP

bad = 0


def ok(cond, msg):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        bad += 1


OLD = np.array([230, 120, 40], np.uint8)       # «цвет заготовки» (оранжевый) в зазорах
A = np.array([60, 90, 200], np.uint8)
B = np.array([40, 180, 70], np.uint8)


def two_islands(n=64):
    """Остров A [8:24, 8:24], остров B [8:24, 40:56]; зазор между ними 16 px; фон — OLD."""
    rgb = np.empty((n, n, 3), np.uint8)
    rgb[:] = OLD
    cov = np.zeros((n, n), bool)
    rgb[8:24, 8:24] = A
    rgb[8:24, 40:56] = B
    cov[8:24, 8:24] = True
    cov[8:24, 40:56] = True
    return rgb, cov


def main():
    R = TP.rules()
    print('правила: числа только из rules/paint-fill.json')
    ok(R['passes'] > 0 and R['kernel'] % 2 == 1 and R['band_rim_dE_max'] > 0, f'texel_fill прочитан: {R["passes"]} проходов, ядро {R["kernel"]}, цвет полосы против кромки ≤ {R["band_rim_dE_max"]}')
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'r.json')
        json.dump({'texel_fill': {'passes': 3, 'kernel': 3, 'keep_px': 8}}, open(p, 'w'))
        try:
            TP.rules(p)
            ok(False, 'нет band_rim_dE_max → KeyError')
        except KeyError:
            ok(True, 'нет band_rim_dE_max → KeyError')
        json.dump({'x': 1}, open(p, 'w'))
        try:
            TP.rules(p)
            ok(False, 'нет texel_fill → KeyError')
        except KeyError:
            ok(True, 'нет texel_fill → KeyError')
        json.dump({'texel_fill': {'passes': 3, 'kernel': 4, 'keep_px': 8, 'band_rim_dE_max': 1}}, open(p, 'w'))
        try:
            TP.rules(p)
            ok(False, 'чётное ядро → ValueError')
        except ValueError:
            ok(True, 'чётное ядро → ValueError')

    print('остров + зазор:')
    rgb, cov = two_islands()
    cfg = {'passes': 6, 'kernel': 3, 'keep_px': 0, 'band_rim_dE_max': 3.0}
    out, rep = TP.pad_texture(rgb, cov, cfg)
    ok(np.array_equal(out[cov], rgb[cov]), 'покрытое не изменилось ни на единицу')
    ok(tuple(out[16, 25]) == tuple(A) and tuple(out[16, 29]) == tuple(A), 'зазор у острова A (1 и 5 px от края) = цвет острова')
    ok(tuple(out[16, 38]) == tuple(B) and tuple(out[16, 34]) == tuple(B), 'зазор у острова B = цвет острова')
    ok(tuple(out[40, 40]) == tuple(OLD) and tuple(out[0, 0]) == tuple(OLD), 'дальше passes px от островов — как было (не выдумываем цвет)')
    ok(rep['band_unfilled'] == 0 and rep['band_texels'] > 0, f'в полосе passes px от острова не залитых 0 (полоса {rep["band_texels"]})')
    ok(rep['band_vs_rim_dE_before'] > 30 and rep['band_vs_rim_dE_after'] < 10.0, f'цвет полосы против кромки ΔE76: {rep["band_vs_rim_dE_before"]} → {rep["band_vs_rim_dE_after"]}')
    ok(abs(rep['uncovered_pct'] - 100.0 * (1 - 2 * 16 * 16 / 64 / 64)) < 0.01, f'доля непокрытых {rep["uncovered_pct"]} %')
    ok(rep['uncovered_mean_rgb_before'] == [230.0, 120.0, 40.0] or rep['uncovered_mean_rgb_before'][0] > 200, f'средний цвет непокрытых до заливки записан: {rep["uncovered_mean_rgb_before"]}')
    # стык двух островов: середина зазора — среднее соседей, не «грязь» OLD
    ok(tuple(out[16, 32]) == tuple(OLD), 'середина зазора шире 2·passes px остаётся как была (залито ровно passes px от острова)')
    o10, _ = TP.pad_texture(rgb, cov, dict(cfg, passes=10))
    mid = o10[16, 32].astype(int)
    ok(mid[0] < 200 and mid[2] > 60 and tuple(o10[16, 26]) == tuple(A) and tuple(o10[16, 37]) == tuple(B), f'при 10 проходах фронты сходятся: стык — цвет ближайшего острова {mid.tolist()}, не заготовки; заливка не «течёт» через остров')

    print('прежний отступ (keep_px) не перезаписывается; заливка — только дальше него:')
    kcfg = dict(cfg, keep_px=4, passes=6)
    rgb_k = rgb.copy()
    rgb_k[8:24, 24:28] = A                                   # отступ 4 px после gutter этапа: копия цвета острова A
    rgb_k[8:24, 36:40] = B
    rgb_k[7, 8:24] = (10, 10, 10)                            # «стёртый» ряд над островом A (1 px): внутри отступа, цвет не такой, как у соседа — всё равно не трогаем
    ko, kr = TP.pad_texture(rgb_k, cov, kcfg)
    keepm = ~cov & (distance_transform_edt(~cov) <= 4)
    ok(np.array_equal(ko[keepm], rgb_k[keepm]) and kr['keep_changed'] == 0 and kr['kept_texels'] == int(keepm.sum()), f'зона отступа (≤4 px от острова) байт в байт, изменено 0 из {kr["kept_texels"]}')
    ok(np.array_equal(ko[cov], rgb_k[cov]), 'покрытое тоже байт в байт')
    ok(tuple(ko[16, 29]) == tuple(A) and tuple(ko[16, 34]) == tuple(B), 'дальше отступа залито цветом отступа (зазор шире 4 px): 5 и 6 px от острова A, B')
    ok(tuple(ko[16, 32]) in {tuple(A), tuple(B)}, 'фронты, пошедшие от края отступа, сошлись в середине зазора (4 + 6 проходов)')
    ok(tuple(ko[40, 40]) == tuple(OLD), 'дальше keep_px + passes от острова — как было')
    ok(kr['band_unfilled'] == 0 and kr['band_texels'] > 0, f'в полосе passes px от края отступа незалитых 0 (полоса {kr["band_texels"]})')
    mk = TP.check_metrics(kr, kcfg)
    ok(mk['texel_keep_changed']['ok'] is True and mk['texel_keep_changed']['value'] == 0, 'мерка texel_keep_changed = 0 (судит этап)')
    ok(TP.check_metrics(dict(kr, keep_changed=3), kcfg)['texel_keep_changed']['ok'] is False, 'тронут отступ → мерка красная')
    ok(R['keep_px'] == TF.FILL['gutter'], f'keep_px правила = gutter этапа ({R["keep_px"]} px): один отступ, не два разных числа')

    print('полный охват, пустое покрытие, альфа:')
    o2, r2 = TP.pad_texture(rgb, np.ones((64, 64), bool), cfg)
    ok(np.array_equal(o2, rgb) and r2['uncovered_pct'] == 0.0 and r2['band_unfilled'] == 0, 'всё покрыто — картинка та же, отчёт «0 % непокрыто»')
    o3, r3 = TP.pad_texture(rgb, np.zeros((64, 64), bool), cfg)
    ok(np.array_equal(o3, rgb) and r3['uncovered_pct'] == 100.0, 'ничего не покрыто — заливать нечем, картинка та же')
    rgba = np.concatenate([rgb, np.full((64, 64, 1), 255, np.uint8)], axis=2)
    rgba[~cov, 3] = 7
    o4, _ = TP.pad_texture(rgba, cov, cfg)
    ok(o4.shape[2] == 4 and (o4[..., 3] == rgba[..., 3]).all() and tuple(o4[16, 25, :3]) == tuple(A), 'RGBA: альфа не тронута, цвет залит')
    o5, r5 = TP.pad_texture(rgb, cov, {'passes': 0, 'kernel': 3, 'keep_px': 0, 'band_rim_dE_max': 3.0})
    ok(np.array_equal(o5, rgb) and r5['changed_texels'] == 0, 'passes=0 — заливка выключена, ничего не меняется')

    print('мерки check.json:')
    mt = TP.check_metrics(rep, cfg)
    ok(mt['texel_band_unfilled']['ok'] is True and mt['texel_band_vs_rim_dE']['ok'] is None and mt['texel_uncovered_pct']['ok'] is None, 'полоса залита — зелёная; утечка и доля — справочные (этап не судят)')
    ok(mt['texel_band_vs_rim_dE']['before'] == rep['band_vs_rim_dE_before'] and mt['texel_band_vs_rim_dE']['value'] == rep['band_vs_rim_dE_after'], 'цвет полосы в check.json: до → после')
    mb = TP.check_metrics(dict(rep, band_unfilled=5, band_vs_rim_dE_after=9.0), cfg)
    ok(mb['texel_band_unfilled']['ok'] is False, 'остались незалитые тексели в полосе → мерка красная')

    print('покрытие по UV и писатель GLB:')
    n = 64
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0], [2, 1, 0]], np.float64)
    UV = np.array([[0.05, 0.05], [0.45, 0.05], [0.05, 0.45], [0.45, 0.45], [0.95, 0.05], [0.95, 0.45]], np.float64)
    F = np.array([[0, 1, 2], [1, 3, 2], [1, 4, 3], [4, 5, 3]], np.int64)
    cv = TP.coverage_from_uv(UV, F, n)
    ok(cv[40, 10] and not cv[5, 5] and not cv[5, 32] and 0.1 < cv.mean() < 0.4, f'покрытие: центр внутри грани = покрыт (доля {cv.mean():.2f})')
    tex = np.empty((n, n, 3), np.uint8)
    tex[:] = OLD
    tex[cv] = A
    dcv = distance_transform_edt(~cv)
    kp = R['keep_px']
    tex[~cv & (dcv <= kp)] = A                         # как после gutter этапа: отступ keep_px = копия цвета острова
    g = {'V': V, 'F': F, 'UV': UV, 'name': 'q'}
    with tempfile.TemporaryDirectory() as td:
        import trimesh
        rp = TF.write_glb([g], [tex], os.path.join(td, 'plain.glb'))
        ok(rp is None, 'write_glb без pad — как раньше (None)')
        rp = TF.write_glb([g], [tex], os.path.join(td, 'pad.glb'), pad=True)
        ok(rp is not None and rp['uncovered_pct'] > 50 and rp['band_unfilled'] == 0 and rp['band_vs_rim_dE_after'] < rp['band_vs_rim_dE_before'], f'write_glb(pad=True): отчёт «до → после» {rp["band_vs_rim_dE_before"]} → {rp["band_vs_rim_dE_after"]}')

        def tex_of(path):
            sc = trimesh.load(path, force='scene', process=False)
            return np.asarray(next(iter(sc.geometry.values())).visual.material.baseColorTexture.convert('RGB'))
        a, b = tex_of(os.path.join(td, 'plain.glb')), tex_of(os.path.join(td, 'pad.glb'))
        ok(np.array_equal(a[cv], b[cv]), 'в файле покрытые тексели одинаковы с pad и без')
        far = ~cv & (dcv > kp) & (dcv <= kp + 3)
        keepz = ~cv & (dcv <= kp)
        ok(far.any() and (a[far] == OLD).all() and (b[far] == A).all(), 'в файле: зазор дальше отступа без pad — цвет заготовки, с pad — цвет острова')
        ok(keepz.any() and np.array_equal(a[keepz], b[keepz]), 'в файле: зона отступа байт в байт с pad и без')
        ok(rp['keep_changed'] == 0 and rp['kept_texels'] > 0, f'отчёт: тексели отступа не тронуты (kept {rp["kept_texels"]}, изменено {rp["keep_changed"]})')

    print(f'ошибок {bad}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
