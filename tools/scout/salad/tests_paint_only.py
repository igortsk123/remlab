#!/usr/bin/env python3
"""Только покраска готовой формы и промежуточные шаги покраски (план mesh-color-03, T-20261106-85) — без GPU и весов.

Подменены torch, fastapi и апстримная покраска `textureGenPipeline`; подмена повторяет ПОРЯДОК вызовов апстрима ревизии
82920d643c0d (`Hunyuan3DPaintPipeline.__call__`): multiview_model(images, normal+position) → super_model попеременно
альбедо/MR на каждый вид → bake_from_multiview альбедо, затем MR → texture_inpaint альбедо, затем MR. Остальное настоящее:
`pipeline.py`, `worker.py` (фото, хранилище и сеть — заглушки на уровне функций).

Закрепляет:
  1) `generate(shape_glb=…)` не зовёт стадию формы и ножи, красит именно переданную болванку;
  2) `params._dump` — файлы каждого шага (вход сети, виды, после увеличения, UV до/после дорисовки, ракурсы) и журнал;
     перехваты сняты после вызова (следующее задание без флага идёт по чистому апстриму);
  3) сбой записи промежуточного файла не валит задание, а пишется в журнал;
  4) воркер: `shape_url` → болванка скачана, её хеш в номере задания (перекраска ≠ полной генерации), промежуточные
     уехали в комплект `dbg-*`, болванка обратно не возится, в паспорте `mode: paint_only`; не-GLB по ссылке — input_failed;
  5) задание без новых полей идёт как раньше (полная генерация, номер задания не сдвинулся).

  ~/venvs/scout/bin/python tests_paint_only.py
"""
import io
import json
import os
import sys
import tempfile
import textwrap
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_paint_only')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))

FAKES = {
    'torch.py': '''
        class Generator:
            def __init__(self, device=None):
                pass
            def manual_seed(self, seed):
                return self
        class cuda:
            max_memory_allocated = staticmethod(lambda: 0)
            empty_cache = staticmethod(lambda: None)
            reset_peak_memory_stats = staticmethod(lambda: None)
            get_device_name = staticmethod(lambda i=0: 'FAKE GPU')
    ''',
    'fastapi.py': '''
        class HTTPException(Exception):
            def __init__(self, status_code=500, detail=''):
                super().__init__(detail)
                self.status_code = status_code
        class FastAPI:
            def _deco(self, *a, **k):
                return lambda f: f
            get = post = on_event = _deco
    ''',
    'hy3dshape/__init__.py': '',
    'hy3dshape/pipelines.py': '''
        import os, trimesh
        CALLS = []
        class Hunyuan3DDiTFlowMatchingPipeline:
            @classmethod
            def from_pretrained(cls, path):
                return cls()
            def __call__(self, image=None, generator=None, **kw):
                CALLS.append('shape')
                return [trimesh.creation.box(extents=(0.5, 0.8, 0.5))]
    ''',
    'textureGenPipeline.py': '''
        import numpy as np, trimesh
        from PIL import Image
        SEEN = []
        class Hunyuan3DPaintConfig:
            def __init__(self, *a):
                pass
        class _MV:
            def __call__(self, images, conditions, prompt=None, custom_view_size=None, resize_input=False):
                n = len(conditions) // 2
                return {'albedo': [Image.new('RGB', (64, 64), (60, 60, 60)) for _ in range(n)],
                        'mr': [Image.new('RGB', (64, 64), (0, 128, 255)) for _ in range(n)]}
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
            def __call__(self, mesh_path=None, image_path=None):
                SEEN.append(mesh_path)
                mesh = trimesh.load(mesh_path, force='mesh')
                img = image_path.resize((512, 512)).convert('RGB')
                elevs, azims, w = [0, 0, 0], [0, 90, 180], [1, 0.1, 0.1]
                normals = [Image.new('RGB', (64, 64), (128, 128, 255)) for _ in azims]
                pos = [Image.new('RGB', (64, 64), (10, 20, 30)) for _ in azims]
                mv = self.models['multiview_model']([img], normals + pos, prompt='high quality')
                alb = [self.models['super_model'](a) for a in mv['albedo']]
                mr = [self.models['super_model'](m) for m in mv['mr']]
                t, m = self.view_processor.bake_from_multiview(alb, elevs, azims, w)
                tm, mm = self.view_processor.bake_from_multiview(mr, elevs, azims, w)
                t = self.view_processor.texture_inpaint(t, m)
                tm = self.view_processor.texture_inpaint(tm, mm)
                return mesh
    ''',
}


def main() -> int:
    bad = 0

    def ok(name: str, cond: bool, extra: object = '') -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    with tempfile.TemporaryDirectory(prefix='paint-only-') as tmp:
        fakes = os.path.join(tmp, 'fakes')
        for rel, body in FAKES.items():
            p = os.path.join(fakes, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'w', encoding='utf-8').write(textwrap.dedent(body))
        sys.path[:0] = [fakes, HERE]
        import trimesh  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
        import pipeline as P  # noqa: PLC0415
        import textureGenPipeline as TG  # noqa: PLC0415
        import hy3dshape.pipelines as HS  # noqa: PLC0415
        assert P.torch.__file__.startswith(fakes), P.torch.__file__
        P.STAGE_PROC, P.STAGED = False, True
        img = Image.new('RGBA', (96, 96), (200, 180, 160, 255))

        # болванка «прошлого прогона»
        shape = os.path.join(tmp, 'prev-shape.glb')
        trimesh.creation.box(extents=(0.4, 0.9, 0.3)).export(shape)

        # 1–2: только покраска + промежуточные
        out = os.path.join(tmp, 'po')
        res = P.generate(img, out, seed=0, params={'_dump': 1}, paint_image=img, role='шкаф', shape_glb=shape)
        ok('только покраска: стадия формы не звалась, ножи не звались, покрашена переданная болванка',
           HS.CALLS == [] and TG.SEEN[-1] == os.path.join(out, 'shape.glb')
           and open(shape, 'rb').read() == open(os.path.join(out, 'shape.glb'), 'rb').read(), (HS.CALLS, TG.SEEN))
        ok('только покраска: итог model.glb, режим paint_only, время формы 0, имя карты из процесса стадии',
           os.path.getsize(res['glb']) > 0 and res['mode'] == 'paint_only' and res['timings']['shape'] == 0.0
           and res['gpu']['name'] == 'FAKE GPU', res)
        d = res['dump_dir']
        files = sorted(os.listdir(d)) if d and os.path.isdir(d) else []
        want = ['dbg-paint-input.png', 'dbg-in-0.png', 'dbg-cond-normal-0.png', 'dbg-cond-pos-2.png', 'dbg-mv-albedo-0.png',
                'dbg-mv-mr-2.png', 'dbg-sr-albedo-0.png', 'dbg-sr-albedo-2.png', 'dbg-sr-mr-2.png',
                'dbg-uv-albedo-baked.png', 'dbg-uv-albedo-mask.png', 'dbg-uv-albedo-inpainted.png', 'dbg-uv-mr-baked.png',
                'dbg-uv-mr-inpainted.png', 'dbg-log.json']
        ok('промежуточные: каждый шаг покраски на диске', all(w in files for w in want), [w for w in want if w not in files])
        log = json.load(open(os.path.join(d, 'dbg-log.json'), encoding='utf-8')) if 'dbg-log.json' in files else {}
        ok('журнал: встали все 4 перехвата, ракурсы альбедо и MR, ошибок нет',
           log.get('hooks') == ['multiview', 'super', 'bake_from_multiview', 'texture_inpaint']
           and [c['kind'] for c in log.get('cams', [])] == ['albedo', 'mr'] and log['cams'][0]['azims'] == [0, 90, 180]
           and not log.get('errors'), log)
        ok('журнал: UV до дорисовки — доля 0.25 (мин/макс), после — светлее на 0.01 (видно по пикселю)',
           log['files']['dbg-uv-albedo-baked.png'].get('max') == 0.25
           and Image.open(os.path.join(d, 'dbg-uv-albedo-inpainted.png')).getpixel((5, 5))[0] == round(0.26 * 255), log['files'])
        pipe = P._PAINT or P.paint_pipeline()
        ok('перехваты сняты: модели и методы — снова апстримные',
           type(pipe.models['multiview_model']).__name__ == '_MV' and type(pipe.models['super_model']).__name__ == '_SR'
           and 'bake_from_multiview' not in vars(pipe.view_processor)
           and 'texture_inpaint' not in vars(pipe.view_processor), (pipe.models, vars(pipe.view_processor)))

        # 3: сбой записи не валит задание
        orig_save = Image.Image.save

        def broken(self, fp, *a, **k):
            if isinstance(fp, str) and os.path.basename(fp).startswith('dbg-sr-'):
                raise OSError('диск полон (проверка)')
            return orig_save(self, fp, *a, **k)
        Image.Image.save = broken
        try:
            res2 = P.generate(img, os.path.join(tmp, 'po2'), params={'_dump': 1}, paint_image=img, shape_glb=shape)
        finally:
            Image.Image.save = orig_save
        log2 = json.load(open(os.path.join(res2['dump_dir'], 'dbg-log.json'), encoding='utf-8'))
        ok('сбой записи промежуточного: задание доехало, ошибка — в журнале',
           os.path.getsize(res2['glb']) > 0 and any('диск полон' in e for e in log2['errors']), log2.get('errors'))

        # без флага — промежуточных нет; полная генерация зовёт форму
        res3 = P.generate(img, os.path.join(tmp, 'full'), seed=1, params={}, paint_image=img, role='шкаф')
        ok('без _dump и без shape_glb: полная генерация (форма звалась), промежуточных нет',
           HS.CALLS == ['shape'] and res3['mode'] == 'full' and res3['dump_dir'] is None
           and not os.path.exists(os.path.join(tmp, 'full', 'dbg')), (HS.CALLS, res3))

        # STAGE_PROC (так идут живые группы): перехваты ставятся в процессе стадии, файлы доезжают до родителя
        P.STAGE_PROC = True
        try:
            res4 = P.generate(img, os.path.join(tmp, 'po-proc'), params={'_dump': 1}, paint_image=img, shape_glb=shape)
        finally:
            P.STAGE_PROC = False
        files4 = sorted(os.listdir(res4['dump_dir'])) if res4.get('dump_dir') else []
        ok('STAGE_PROC: только покраска в своём процессе, промежуточные и журнал на диске',
           res4['mode'] == 'paint_only' and res4['gpu']['stage_proc'] is True
           and all(w in files4 for w in want), [w for w in want if w not in files4])

        # 4–5: воркер
        import manifest as M  # noqa: PLC0415
        import preprocess as PRE  # noqa: PLC0415
        import storage as S  # noqa: PLC0415
        import worker as W  # noqa: PLC0415
        shape_bytes = open(shape, 'rb').read()
        src = io.BytesIO()
        Image.new('RGB', (40, 40), (90, 90, 90)).save(src, 'JPEG')
        net = {'https://x/shape.glb': shape_bytes, 'https://x/bad.glb': b'<html>404</html>', 'https://x/p.jpg': src.getvalue()}
        PRE.fetch = lambda url, timeout=120: net[url]
        PRE.prepare = lambda url, role=None: (img, img, img, 'inputhash0001', {'hybrid': False})
        pub = []
        S.already_done = lambda prefix: None
        S.publish = lambda prefix, files, complete: (pub.append((prefix, dict(files), json.load(open(files['manifest.json'])))),
                                                     {k: 1 for k in files})[1]
        W.STATE['warm'] = True
        job = {'sku': '1:2', 'role': 'шкаф', 'image_url': 'https://x/p.jpg', 'seed': 0}
        r_full = W.generate({**job, 'params': {}})
        r_po = W.generate({**job, 'params': {'_dump': 1}, 'shape_url': 'https://x/shape.glb'})
        ok('воркер: перекраска и полная генерация — разные номера задания (хеш болванки в params)',
           r_full.get('status') == 'ok' and r_po.get('status') == 'ok' and r_full['job_id'] != r_po['job_id'], (r_full, r_po))
        ok('воркер: номер полной генерации без новых полей не сдвинулся',
           r_full['job_id'] == M.job_id('1:2', 'inputhash0001', {}, 0), r_full)
        files_full, files_po, man_po = pub[0][1], pub[1][1], pub[1][2]
        ok('воркер: в комплекте перекраски — dbg-* и журнал, болванки нет; у полной — болванка есть, dbg нет',
           'dbg-uv-albedo-inpainted.png' in files_po and 'dbg-log.json' in files_po and 'shape.glb' not in files_po
           and 'shape.glb' in files_full and not any(k.startswith('dbg-') for k in files_full), (sorted(files_po), sorted(files_full)))
        ok('воркер: паспорт — mode paint_only, shape_url, хеш болванки в params',
           man_po.get('mode') == 'paint_only' and man_po.get('shape_url') == 'https://x/shape.glb'
           and (man_po.get('params') or {}).get('_shape') == M.sha(shape_bytes), man_po)
        r_bad = W.generate({**job, 'params': {}, 'shape_url': 'https://x/bad.glb'})
        ok('воркер: по ссылке не GLB — input_failed, покраска не запускалась',
           r_bad.get('status') == 'input_failed' and 'не GLB' in r_bad.get('error', '') and len(pub) == 2, r_bad)

        # 6: машина отрезана от нашего сервера (T-85 06.11: Connection reset на входе и у приёмника)
        import urllib.error  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415
        import node_health as NH  # noqa: PLC0415
        W.SINK_HEALTH_PAUSES = (0,)
        os.environ['MESH_SINK_URL'] = 'https://sink.test/mesh-sink'
        S.BACKEND = 'http'
        orig_open = urllib.request.urlopen
        reset = urllib.error.URLError(ConnectionResetError(104, 'Connection reset by peer'))
        sink = {'mode': 'reset', 'calls': 0}

        def fake_open(req, timeout=None):
            sink['calls'] += 1
            if sink['mode'] == 'reset':
                raise reset
            if sink['mode'] == 'http503':
                raise urllib.error.HTTPError(req.full_url, 503, 'busy', {}, None)
            return io.BytesIO(b'{"ok":true}')
        urllib.request.urlopen = fake_open

        def raise_(e):
            raise e
        try:
            W.STATE.update({'warm': True, 'phase': 'ready'})
            PRE.prepare = lambda url, role=None: raise_(reset)
            r_cut = W.generate({**job, 'params': {}})
            ok('воркер: вход оборван сетью и приёмник недоступен — node/cut_off, машина снята с готовности',
               r_cut.get('status') == 'input_failed' and r_cut['error'].startswith(W.CUT_OFF)
               and W.STATE['phase'] == 'failed' and W.STATE['warm'] is False, (r_cut, W.STATE.get('phase')))
            ok('node_health: node/cut_off — вина машины (повтор на другой, товар не винить), класс node/cut_off',
               NH.classify(r_cut) == NH.FAULT_NODE and NH.error_class(r_cut) == 'node/cut_off',
               (NH.classify(r_cut), NH.error_class(r_cut)))

            for mode in ('ok', 'http503'):
                sink['mode'] = mode
                W.STATE.update({'warm': True, 'phase': 'ready'})
                r_net = W.generate({**job, 'params': {}})
                ok(f'воркер: вход оборван, приёмник отвечает ({mode}) — обычный input_failed, машина остаётся готовой',
                   r_net.get('status') == 'input_failed' and W.CUT_OFF not in r_net['error']
                   and W.STATE['phase'] == 'ready' and NH.classify(r_net) == NH.FAULT_UNKNOWN, (r_net, W.STATE.get('phase')))

            sink['mode'], sink['calls'] = 'reset', 0
            PRE.prepare = lambda url, role=None: raise_(urllib.error.HTTPError(url, 404, 'nf', {}, None))
            W.STATE.update({'warm': True, 'phase': 'ready'})
            r_404 = W.generate({**job, 'params': {}})
            ok('воркер: 404 на входе — вина товара, приёмник даже не опрашивается',
               r_404.get('status') == 'input_failed' and sink['calls'] == 0 and W.STATE['phase'] == 'ready'
               and NH.classify(r_404) == NH.FAULT_JOB, (r_404, sink['calls']))

            PRE.prepare = lambda url, role=None: (img, img, img, 'inputhash0001', {'hybrid': False})
            net['https://x/gone.glb'] = None
            PRE.fetch = lambda url, timeout=120: net[url] if net.get(url) else raise_(reset)
            r_sh = W.generate({**job, 'params': {}, 'shape_url': 'https://x/gone.glb'})
            ok('воркер: болванка оборвана сетью при недоступном приёмнике — тоже node/cut_off',
               r_sh.get('error', '').startswith(W.CUT_OFF) and 'shape_url' in r_sh['error'], r_sh)

            import fetch_weights  # noqa: PLC0415
            fetch_weights.ensure = lambda: {}          # веса в тесте не качаем
            W.STATE.update({'warm': False, 'phase': 'warming'})
            W.warmup()
            ok('воркер: прогрев кончается проверкой приёмника — недоступен, машина не ready (phase failed, cut_off)',
               W.STATE['phase'] == 'failed' and W.CUT_OFF in (W.STATE.get('warmup_error') or ''), W.STATE.get('warmup_error'))
            sink['mode'] = 'ok'
            W.STATE.update({'warm': False, 'phase': 'warming'})
            W.warmup()
            ok('воркер: приёмник отвечает — прогрев как раньше, ready', W.STATE['phase'] == 'ready' and W.STATE['warm'],
               W.STATE.get('warmup_error'))
            del os.environ['MESH_SINK_URL']
            ok('воркер: без MESH_SINK_URL (локальная отладка) проверять нечего', W.sink_reachable() == (True, ''))
        finally:
            urllib.request.urlopen = orig_open
            os.environ.pop('MESH_SINK_URL', None)
    print(f'tests_paint_only: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
