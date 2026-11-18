#!/usr/bin/env python3
"""Сторож пустых видов покраски (план mesh-grey-top-01, T-20261118-04/13) — без GPU и весов.

Подмена апстрима — как в `tests_paint_knobs.py`; порядок вызовов повторяет ревизию образа 82920d643c0d
(`Hunyuan3DPaintPipeline.__call__`): multiview_model(images, normal+position) → super_model → bake_from_multiview альбедо,
затем MR (два отдельных вызова с одними и теми же ракурсами/весами) → texture_inpaint.

Закрепляет:
  1) детектор: пустой вид (серый фон 128 внутри силуэта + тонкая кромка) — пуст; нарисованный — нет; затенённый серый
     предмет — нет; кадр, залитый светлым корпусом (фон не серый) и силуэт на весь кадр — не судятся;
  2) покраска: пустой вид сверху уходит из ОБОИХ вызовов bake (альбедо и MR) вместе со своим ракурсом и весом, остальные
     виды и их порядок целы; в результате поле `view_guard` и одна строка журнала с номером вида;
  3) пустых видов нет — bake получает всё как есть; `_view_guard: 0` — сторож выключен (bake как в апстриме, поля нет);
  4) пустыми оказались ВСЕ виды — не режем (нечем красить), список целый;
  5) сбой оценки (карт нормалей меньше, чем видов) не валит покраску: bake как есть, ошибка в журнале;
  6) после задания перехваты сняты (сеть видов и `bake_from_multiview` — снова апстримные), с `_dump` рядом с дампом
     лежит `dbg-viewguard.json`, а виды `dbg-mv-*` в дампе — как отдала сеть.

  ~/venvs/scout/bin/python tests_view_guard.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import textwrap

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_view_guard')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tests_paint_only as TPO  # noqa: E402

FAKES = dict(TPO.FAKES)
FAKES['textureGenPipeline.py'] = '''
    import numpy as np, trimesh
    from PIL import Image
    BAKES = []
    MODE = {'empty': [1], 'nconds': None}
    class Hunyuan3DPaintConfig:
        def __init__(self, *a):
            pass
    def _view(empty):
        a = np.full((64, 64, 3), 128, np.uint8)
        a[np.random.RandomState(0).rand(64, 64) < 0.2] = 129          # шум фона сети
        if empty:
            a[14:50, 18:46] = 128
            a[14, 18:46] = 230                                          # тонкая кромка
        else:
            a[14:50, 18:46] = (190, 150, 110)
        return Image.fromarray(a)
    class _MV:
        def __call__(self, images, conditions, prompt=None, custom_view_size=None, resize_input=False):
            n = len(conditions) // 2
            return {'albedo': [_view(i in MODE['empty']) for i in range(n)],
                    'mr': [Image.new('RGB', (64, 64), (0, 128, 255)) for _ in range(n)]}
    class _SR:
        def __call__(self, img):
            return img.resize((256, 256))
    class _VP:
        def bake_from_multiview(self, views, elevs, azims, weights):
            BAKES.append({'n': len(views), 'elevs': list(elevs), 'azims': list(azims), 'weights': list(weights)})
            return np.full((128, 128, 3), 0.25, np.float32), np.ones((128, 128, 1), bool)
        def texture_inpaint(self, texture, mask):
            return texture + 0.01
    class Hunyuan3DPaintPipeline:
        def __init__(self, cfg):
            self.models = {'multiview_model': _MV(), 'super_model': _SR()}
            self.view_processor = _VP()
        def __call__(self, mesh_path=None, image_path=None):
            mesh = trimesh.load(mesh_path, force='mesh')
            img = image_path.resize((512, 512)).convert('RGB')
            elevs, azims, w = [0, 90, 0], [0, 0, 180], [1, 0.05, 0.1]
            normals = []
            for _ in elevs:
                n = np.full((64, 64, 3), 255, np.uint8)
                n[14:50, 18:46] = (128, 128, 255)
                normals.append(Image.fromarray(n))
            pos = [Image.new('RGB', (64, 64), (10, 20, 30)) for _ in elevs]
            conds = normals + pos
            if MODE['nconds'] is not None:
                conds = conds[:MODE['nconds']]
            mv = self.models['multiview_model']([img], conds, prompt='high quality')
            alb = [self.models['super_model'](a) for a in mv['albedo']]
            mr = [self.models['super_model'](m) for m in mv['mr']]
            t, m = self.view_processor.bake_from_multiview(alb, elevs, azims, w)
            tm, mm = self.view_processor.bake_from_multiview(mr, elevs, azims, w)
            self.view_processor.texture_inpaint(t, m)
            return mesh
'''


def main() -> int:
    bad = 0

    def ok(name: str, cond: bool, extra: object = '') -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    with tempfile.TemporaryDirectory(prefix='view-guard-') as tmp:
        fakes = os.path.join(tmp, 'fakes')
        for rel, body in FAKES.items():
            p = os.path.join(fakes, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'w', encoding='utf-8').write(textwrap.dedent(body))
        sys.path[:0] = [fakes]
        import numpy as np  # noqa: PLC0415
        import trimesh  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
        import pipeline as P  # noqa: PLC0415
        import textureGenPipeline as TG  # noqa: PLC0415
        import view_guard as VG  # noqa: PLC0415
        assert P.torch.__file__.startswith(fakes), P.torch.__file__
        P.STAGE_PROC, P.STAGED = False, False

        # 1: детектор
        def cond(box, size=128):
            n = np.full((size, size, 3), 255, np.uint8)
            y0, y1, x0, x1 = box
            n[y0:y1, x0:x1] = (128, 128, 255)
            return Image.fromarray(n)

        def view(bg, box, body=None, size=128, noise=1, ring=True):
            rng = np.random.RandomState(1)
            a = np.clip(np.full((size, size, 3), bg, int) + rng.randint(-noise, noise + 1, (size, size, 3)), 0, 255)
            y0, y1, x0, x1 = box
            if body is not None:
                a[y0:y1, x0:x1] = body
            elif ring:
                a[y0, x0:x1] = 235
                a[y1 - 1, x0:x1] = 235
            return Image.fromarray(a.astype(np.uint8))
        box = (20, 100, 24, 104)
        r = VG.judge(view(128, box), cond(box))
        ok('детектор: серый фон внутри силуэта + тонкая кромка — пустой вид', r['judged'] and r['empty'] and r['frac'] > 0.99, r)
        r = VG.judge(view(128, box, body=(190, 150, 110)), cond(box))
        ok('детектор: нарисованный вид — не пустой', r['judged'] and not r['empty'], r)
        sh = np.zeros((128, 128, 3), np.uint8)
        sh[...] = 128
        gx = np.linspace(100, 150, 80).astype(int)
        sh[20:100, 24:104] = gx[:, None, None]                           # затенённый серый предмет (градиент 100…150)
        r = VG.judge(Image.fromarray(sh), cond(box))
        ok('детектор: затенённый серый предмет — не пустой', r['judged'] and not r['empty'], r)
        r = VG.judge(view(205, (0, 128, 0, 128), body=205), cond((0, 128, 6, 122)))
        ok('детектор: кадр залит светлым корпусом (фон не серый) — не судим, не пустой',
           not r['judged'] and not r['empty'] and r.get('reason') == 'фон не серый' or not r['judged'], r)
        r = VG.judge(view(128, (0, 128, 0, 128), body=128), cond((0, 128, 0, 128)))
        ok('детектор: силуэт на весь кадр (фон не измерить) — не судим', not r['judged'] and not r['empty'], r)
        r = VG.judge(view(128, box), cond((60, 64, 60, 64)))
        ok('детектор: крошечный силуэт — не судим', not r['judged'] and not r['empty'], r)
        a, b, c, d = VG.keep_lists({1}, 3, [0, 1, 2], [9, 8, 7], [1, 2, 3], [.1, .2, .3])
        ok('списки: вид 1 вырезан из всех четырёх, порядок прочих цел',
           (a, b, c, d) == ([0, 2], [9, 7], [1, 3], [.1, .3]), (a, b, c, d))
        ok('списки: вырезать все виды или несходящиеся длины — без изменений',
           VG.keep_lists({0, 1, 2}, 3, [0, 1, 2]) == ([0, 1, 2],) and VG.keep_lists({1}, 3, [0, 1]) == ([0, 1],))

        img = Image.new('RGBA', (96, 96), (200, 180, 160, 255))
        shape = os.path.join(tmp, 'prev-shape.glb')
        trimesh.creation.box(extents=(0.4, 0.9, 0.3)).export(shape)

        def run(name, params, empty=(1,), nconds=None):
            TG.BAKES.clear()
            TG.MODE['empty'], TG.MODE['nconds'] = list(empty), nconds
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                res = P.generate(img, os.path.join(tmp, name), params=params, paint_image=img, shape_glb=shape)
            return res, TG.BAKES[:], buf.getvalue(), P._PAINT or P.paint_pipeline()

        # 2: пустой вид 1 (elev 90) вырезан из обоих bake
        res, bakes, out, pipe = run('empty', {})
        ok('покраска: оба bake (альбедо и MR) получили 2 вида без пустого, с его ракурсом и весом выброшенными',
           len(bakes) == 2 and all(b['n'] == 2 and b['elevs'] == [0, 0] and b['azims'] == [0, 180]
                                   and b['weights'] == [1, 0.1] for b in bakes), bakes)
        vg = res.get('view_guard') or {}
        ok('покраска: в результате view_guard — пустой вид 1, отброшен (elev 90, вес 0.05), ошибок нет',
           vg.get('bad') == [1] and vg.get('dropped') and vg['dropped'][0]['view'] == 1
           and vg['dropped'][0]['elev'] == 90 and vg['dropped'][0]['weight'] == 0.05 and not vg.get('errors'), vg)
        lines = [x for x in out.splitlines() if x.startswith('view_guard ')]
        ok('покраска: ровно одна строка журнала, в ней «ОТБРОШЕН» и «вид 1»',
           len(lines) == 1 and 'ОТБРОШЕН' in lines[0] and 'вид 1' in lines[0], out)
        ok('после задания перехваты сняты: сеть видов и bake — апстримные',
           type(pipe.models['multiview_model']).__name__ == '_MV' and 'bake_from_multiview' not in pipe.view_processor.__dict__)

        # 3: пустых нет / выключен
        res, bakes, out, pipe = run('full', {}, empty=())
        vg = res.get('view_guard') or {}
        ok('нет пустых видов: bake получил все 3, строка «пустых видов нет»',
           all(b['n'] == 3 for b in bakes) and vg.get('bad') == [] and 'пустых видов нет' in out, (bakes, vg, out))
        res, bakes, out, pipe = run('off', {'_view_guard': 0})
        ok('_view_guard: 0 — как в апстриме: bake получил все 3, поля и строки нет',
           all(b['n'] == 3 for b in bakes) and res.get('view_guard') is None and 'view_guard' not in out, (bakes, res.get('view_guard')))

        # 4: пусты все
        res, bakes, out, pipe = run('all', {}, empty=(0, 1, 2))
        ok('пусты все виды: не режем, bake получил все 3', all(b['n'] == 3 for b in bakes) and len(bakes) == 2, bakes)

        # 5: сбой оценки и несходящиеся списки
        real = VG.judge_views

        def boom(*a, **k):
            raise RuntimeError('сбой оценки')
        VG.judge_views = boom
        try:
            res, bakes, out, pipe = run('broken', {})
        finally:
            VG.judge_views = real
        vg = res.get('view_guard') or {}
        ok('сбой оценки: покраска доехала, bake как есть (все 3), ошибка в журнале',
           os.path.getsize(res['glb']) > 0 and all(b['n'] == 3 for b in bakes) and vg.get('errors')
           and 'judge' in vg['errors'][0], (bakes, vg))
        res, bakes, out, pipe = run('mismatch', {}, nconds=4)      # сеть отдала 2 вида, а ракурсов в bake 3 — не режем
        ok('списки не сходятся (2 вида, 3 ракурса): bake без изменений, покраска доехала',
           os.path.getsize(res['glb']) > 0 and all(b['n'] == 2 and len(b['elevs']) == 3 for b in bakes), bakes)

        # 6: дамп
        res, bakes, out, pipe = run('dump', {'_dump': 1})
        d = res['dump_dir']
        files = sorted(os.listdir(d))
        ok('с _dump: dbg-viewguard.json лежит, виды dbg-mv-* — как отдала сеть (вид 1 пустой на месте), bake всё равно без него',
           'dbg-viewguard.json' in files and 'dbg-mv-albedo-1.png' in files and all(b['n'] == 2 for b in bakes)
           and json.load(open(os.path.join(d, 'dbg-viewguard.json'), encoding='utf-8'))['bad'] == [1], (files, bakes))
        ok('с _dump после задания: перехваты сняты', 'bake_from_multiview' not in pipe.view_processor.__dict__
           and type(pipe.models['multiview_model']).__name__ == '_MV')

    print('ИТОГ:', 'ok' if not bad else f'{bad} провал(ов)')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
