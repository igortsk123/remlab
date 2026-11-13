#!/usr/bin/env python3
"""Опытные ручки покраски (план mesh-color-03, круг 2; T-20261112-49/3) — без GPU и весов.

Подмена апстрима — как в `tests_paint_only.py`, но у сети видов есть `.pipeline` и `forward_one`, повторяющие
`multiview_utils.multiviewDiffusionNet` ревизии 82920d643c0d: guidance_scale=3.0 и генератор seed 0 зашиты в вызов.

Закрепляет:
  1) без ручек в params — апстримный вызов не тронут (CFG 3.0, seed 0, виды как отдала сеть), журнала ручек нет;
  2) `_paint_cfg`/`_paint_seed` доходят до вызова диффузии, после задания пайплайн — снова апстримный;
  3) `_mv_cal` меняет светлоту видов альбедо до увеличения (вид после SR темнее, как фото), сырые виды — `dbg-mv-raw-*`;
  4) сбой поправки не валит задание: виды идут как были, ошибка — в `dbg-knobs.json`;
  5) мусор в ручке (`_paint_cfg: 99`) — в журнал, вызов по апстриму;
  6) `mv_color_cal`: монотонная кривая, сдвиг в пределах MAX_DL, фон и материал вне участков не трогаются.
  7) сторож цветности: участок, чьи пары фото другого цвета (ab дальше AB_MAX), не правится, соседний свой — правится.

  ~/venvs/scout/bin/python tests_paint_knobs.py
"""
import json
import os
import sys
import tempfile
import textwrap

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_paint_knobs')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tests_paint_only as TPO  # noqa: E402

FAKES = dict(TPO.FAKES)
FAKES['torch.py'] = '''
    class Generator:
        def __init__(self, device=None):
            self.seed = None
        def manual_seed(self, seed):
            self.seed = seed
            return self
    class cuda:
        max_memory_allocated = staticmethod(lambda: 0)
        empty_cache = staticmethod(lambda: None)
        reset_peak_memory_stats = staticmethod(lambda: None)
        get_device_name = staticmethod(lambda i=0: 'FAKE GPU')
'''
FAKES['textureGenPipeline.py'] = '''
    import numpy as np, trimesh, torch
    from PIL import Image
    CALLS = []
    BREAK = []
    class Hunyuan3DPaintConfig:
        def __init__(self, *a):
            pass
    class _Diff:
        device = 'cpu'
        view_size = 64
        def __call__(self, images, guidance_scale=None, generator=None, **kw):
            CALLS.append({'cfg': guidance_scale, 'seed': getattr(generator, 'seed', None)})
            return 'imgs'
    class _MV:
        def __init__(self):
            self.pipeline = _Diff()
        def __call__(self, images, conditions, prompt=None, custom_view_size=None, resize_input=False):
            self.pipeline(images[0:1], guidance_scale=3.0, generator=torch.Generator(device='cpu').manual_seed(0))
            n = len(conditions) // 2
            if BREAK:
                return {'albedo': [], 'mr': []}
            # светлый «сеть вытянула к середине» корпус на сером фоне; на фото он тёмный (см. тест)
            alb = []
            for _ in range(n):
                a = np.full((64, 64, 3), 131, np.uint8)
                a[16:48, 20:44] = 200
                alb.append(Image.fromarray(a))
            return {'albedo': alb, 'mr': [Image.new('RGB', (64, 64), (0, 128, 255)) for _ in range(n)]}
    class _SR:
        def __call__(self, img):
            return img.resize((256, 256))
    class _VP:
        def bake_from_multiview(self, views, elevs, azims, weights):
            return np.full((128, 128, 3), 0.25, np.float32), np.ones((128, 128, 1), bool)
        def texture_inpaint(self, texture, mask):
            return texture + 0.01
    class Hunyuan3DPaintPipeline:
        def __init__(self, cfg):
            self.models = {'multiview_model': _MV(), 'super_model': _SR()}
            self.view_processor = _VP()
            self.sr_seen = []
        def __call__(self, mesh_path=None, image_path=None):
            mesh = trimesh.load(mesh_path, force='mesh')
            img = image_path.resize((512, 512)).convert('RGB')
            azims = [0, 90, 180]
            normals = []
            for _ in azims:
                n = np.full((64, 64, 3), 255, np.uint8)
                n[16:48, 20:44] = (128, 128, 255)
                normals.append(Image.fromarray(n))
            pos = [Image.new('RGB', (64, 64), (10, 20, 30)) for _ in azims]
            mv = self.models['multiview_model']([img], normals + pos, prompt='high quality')
            alb = [self.models['super_model'](a) for a in mv['albedo']]
            self.sr_seen = alb
            mr = [self.models['super_model'](m) for m in mv['mr']]
            t, m = self.view_processor.bake_from_multiview(alb, [0, 0, 0], azims, [1, 0.1, 0.1])
            self.view_processor.bake_from_multiview(mr, [0, 0, 0], azims, [1, 0.1, 0.1])
            self.view_processor.texture_inpaint(t, m)
            return mesh
'''


def main() -> int:
    bad = 0

    def ok(name: str, cond: bool, extra: object = '') -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    with tempfile.TemporaryDirectory(prefix='paint-knobs-') as tmp:
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
        import mv_color_cal as CAL  # noqa: PLC0415
        assert P.torch.__file__.startswith(fakes), P.torch.__file__
        P.STAGE_PROC, P.STAGED = False, False      # пайплайн покраски живёт между заданиями — видно, что ручки сняты
        # фото: тёмный (L≈45, сдвиг 36 < MAX_DL) прямоугольник на прозрачном, силуэт как у вида
        ph = np.zeros((64, 64, 4), np.uint8)
        ph[16:48, 20:44] = (105, 105, 107, 255)
        img = Image.fromarray(ph, 'RGBA')
        shape = os.path.join(tmp, 'prev-shape.glb')
        trimesh.creation.box(extents=(0.4, 0.9, 0.3)).export(shape)

        def run(name, params):
            TG.CALLS.clear()
            res = P.generate(img, os.path.join(tmp, name), params=params, paint_image=img, shape_glb=shape)
            pipe = P._PAINT or P.paint_pipeline()
            d = res['dump_dir']
            kn = os.path.join(d, 'dbg-knobs.json') if d else ''
            return res, pipe, (json.load(open(kn, encoding='utf-8')) if kn and os.path.exists(kn) else None)

        # 1: без ручек
        res, pipe, kn = run('plain', {'_dump': 1})
        sr0 = np.asarray(pipe.sr_seen[0])[128, 128]
        ok('без ручек: CFG 3.0 и seed 0 апстрима, вид не тронут, журнала ручек нет',
           TG.CALLS == [{'cfg': 3.0, 'seed': 0}] and tuple(sr0) == (200, 200, 200) and kn is None, (TG.CALLS, sr0, kn))

        # 2: CFG/seed
        res, pipe, kn = run('cfg', {'_dump': 1, '_paint_cfg': 4.5, '_paint_seed': 7})
        ok('CFG/seed: до диффузии дошли 4.5 и 7, журнал видел апстримные 3.0',
           TG.CALLS == [{'cfg': 4.5, 'seed': 7}] and kn and kn['hooks'] == ['cfg', 'seed']
           and kn.get('seen_cfg') == [3.0, 4.5] and not kn['errors'], (TG.CALLS, kn))
        ok('CFG/seed: после задания пайплайн сети видов снова апстримный',
           type(pipe.models['multiview_model'].pipeline).__name__ == '_Diff')
        res, pipe, kn = run('plain2', {})
        ok('следующее задание без ручек — снова 3.0 / 0', TG.CALLS == [{'cfg': 3.0, 'seed': 0}], TG.CALLS)

        # 3: поправка видов
        res, pipe, kn = run('cal', {'_dump': 1, '_mv_cal': 1})
        a = np.asarray(pipe.sr_seen[0])
        lab_now = CAL.rgb_to_lab(a[128, 128])[0]
        lab_photo = CAL.rgb_to_lab(np.array([105, 105, 107]))[0]
        files = sorted(os.listdir(res['dump_dir']))
        ok('mv_cal: вид после увеличения стал тёмным, как фото (|ΔL| < 3), фон не тронут',
           abs(lab_now - lab_photo) < 3 and tuple(a[5, 5]) == (131, 131, 131), (lab_now, lab_photo, a[5, 5]))
        ok('mv_cal: в журнале участок и IoU, сырые виды сохранены, dbg-mv-* — уже поправленные',
           kn and kn['hooks'] == ['mv_cal'] and kn['cal'].get('iou', 0) > 0.9 and kn['cal'].get('regions')
           and 'dbg-mv-raw-albedo-0.png' in files
           and np.asarray(Image.open(os.path.join(res['dump_dir'], 'dbg-mv-albedo-0.png')))[32, 32][0] < 150,
           (kn, files))
        ok('mv_cal: после задания сеть видов — снова апстримная', type(pipe.models['multiview_model']).__name__ == '_MV')

        # 4: сбой поправки
        TG.BREAK.append(1)
        try:
            res, pipe, kn = run('calbreak', {'_dump': 1, '_mv_cal': 1})
        finally:
            TG.BREAK.clear()
        ok('сбой поправки: задание доехало, ошибка в журнале',
           os.path.getsize(res['glb']) > 0 and kn and any('mv_cal' in e for e in kn['errors']), kn)

        # 5: мусор в ручке
        res, pipe, kn = run('junk', {'_dump': 1, '_paint_cfg': 99})
        ok('CFG 99: в журнал, вызов по апстриму', TG.CALLS == [{'cfg': 3.0, 'seed': 0}] and kn
           and any('вне' in e for e in kn['errors']), (TG.CALLS, kn))

        # 6: модуль кривой
        lut = CAL.curve(np.linspace(60, 80, 500), np.linspace(20, 45, 500))
        ok('кривая: монотонна, сдвиг не больше MAX_DL',
           np.all(np.diff(lut) >= 0) and np.max(np.abs(lut - np.linspace(0, 100, 1001))) <= CAL.MAX_DL + 1e-6)
        lut2 = CAL.curve(np.r_[np.full(900, 78.4), np.linspace(69, 79, 100)], np.linspace(43, 73, 1000))
        ok('кривая: узкая полоса вида — медиана вида уходит в медиану фото',
           abs(lut2[784] - 58.0) < 1.5, lut2[784])
        v = np.full((40, 40, 3), 131, np.uint8)
        v[10:30, 10:30] = 200
        v[10:30, 25:30] = (200, 140, 80)            # «дерево» на боку — на фото его нет
        m = np.zeros((40, 40), bool)
        m[10:30, 10:30] = True
        model = {'regions': [{'view_lab': CAL.rgb_to_lab(np.array([200, 200, 200])).tolist(), 'sigma': 8.0,
                              'lut': np.clip(np.linspace(0, 100, 1001) - 30, 0, 100)}]}
        out = CAL.apply(model, v, m)
        ok('применение: участок темнеет, дерево вне участка почти не тронуто, фон вне маски — нет',
           out[15, 15, 0] < 150 and abs(int(out[15, 27, 0]) - 200) <= 3 and tuple(out[2, 2]) == (131, 131, 131),
           (out[15, 15], out[15, 27], out[2, 2]))
        # T-49/4: узкая полоса цвета участка посреди другого материала (выдумка сети) — без поправки, панель — с поправкой
        v = np.full((200, 200, 3), 131, np.uint8)
        v[20:180, 20:180] = (200, 140, 80)          # дерево
        v[40:160, 40:150] = 200                    # панель
        v[30:170, 166:170] = 200                   # полоса 4 px по дереву
        v[60:70, 60:70] = (200, 140, 80)           # сучок в панели — дыра фактуры
        m = np.zeros((200, 200), bool)
        m[20:180, 20:180] = True
        st = {}
        out = CAL.apply(model, v, m, st)
        ok('опора: панель темнеет (и вокруг сучка), узкая полоса её цвета по дереву — нет',
           out[100, 100, 0] < 150 and out[58, 65, 0] < 150 and abs(int(out[100, 168, 0]) - 200) <= 3
           and st.get('radius_px', 0) >= 3, (out[100, 100], out[58, 65], out[100, 168], st.get('radius_px')))
        # T-49/5: сторож цветности — пары участка с чужого материала (розовые ножки вида против серого корпуса фото)
        v = np.full((256, 256, 3), 255, np.uint8)
        v[30:150, 30:226] = 200                    # корпус: серый, светлее фото
        v[150:226, 30:226] = (230, 150, 200)       # «ножки»: розовые; на фото на этом месте серое
        m = np.zeros((256, 256), bool)
        m[30:226, 30:226] = True
        ph = np.zeros((256, 256), np.uint8)
        ph[30:226, 30:226] = 255
        prgb = np.full((256, 256, 3), 120, np.uint8)
        model, info = CAL.fit(prgb, ph, v, m)
        regs = info.get('regions') or []
        pink = [r for r in regs if r['view_lab'][1] > 15]
        grey = [r for r in regs if r['view_lab'][1] <= 15]
        out = CAL.apply(model, v, m) if model else v
        ok('сторож цветности: чужой участок без поправки, свой — темнеет',
           len(pink) == 1 and pink[0]['keep'] and pink[0]['dab'] > CAL.AB_MAX and len(grey) == 1 and not grey[0]['keep']
           and np.abs(out[190, 128].astype(int) - (230, 150, 200)).max() <= 3 and out[90, 128, 0] < 170,
           (regs, out[190, 128], out[90, 128]))

    print('ИТОГ:', 'ok' if not bad else f'{bad} провал(ов)')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
