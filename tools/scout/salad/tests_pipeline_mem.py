#!/usr/bin/env python3
"""Память генерации (T-20261022-10 В) — без GPU и без весов: torch и модели Hunyuan подменены, остальное настоящее
(`pipeline.py`, trimesh, glibc).

ЗАЧЕМ. Замер 22.10 на живой машине: после выгрузки покраски на карте 0.5 ГБ, а собственная память процесса так и
осталась 15 ГБ; загрузка весов следующей стадии добавляла 7+ ГБ, и машина с 33 ГБ ОЗУ падала на старте следующего
задания. Стенд закрепляет три вещи:
  1) `_trim` действительно возвращает системе освобождённую, но раздробленную кучу (так держатся веса — тысячи
     тензоров меньше порога mmap);
  2) в обычном режиме после задания память воркера возвращается к исходной, а телеметрия ОЗУ (`ram_*_gb`) едет в
     ответ — оттуда в манифест;
  3) `STAGE_PROC=1`: стадии идут отдельными процессами, их память в воркере не остаётся вовсе, а процесс, убитый за
     нехватку памяти, — внятная ошибка, а не зависание.

Запуск: ~/venvs/scout/bin/python tests_pipeline_mem.py
"""
import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
CHUNK, N_CHUNKS = 1536, 200_000      # ≈ 300 МБ кусками меньше порога mmap — как веса в куче glibc

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
    'hy3dshape/__init__.py': '',
    # «Веса» держит объект пайплайна (как настоящий): куча кусков меньше порога mmap; каждый тысячный кусок
    # остаётся жить после выгрузки — это и дробит кучу, без `malloc_trim` она системе не вернётся.
    'hy3dshape/pipelines.py': f'''
        import os, trimesh
        KEEP = []
        class Hunyuan3DDiTFlowMatchingPipeline:
            @classmethod
            def from_pretrained(cls, path):
                if os.environ.get('FAKE_DIE') == '1':
                    os._exit(9)          # как убийство процесса системой за нехватку памяти
                p = cls()
                p.w = [bytes({CHUNK}) for _ in range({N_CHUNKS})]
                KEEP.extend(p.w[::1000])
                return p
            def __call__(self, image=None, generator=None, **kw):
                return [trimesh.creation.box(extents=(0.5, 0.8, 0.5))]
    ''',
    'textureGenPipeline.py': f'''
        import trimesh
        class Hunyuan3DPaintConfig:
            def __init__(self, *a):
                pass
        class Hunyuan3DPaintPipeline:
            def __init__(self, cfg):
                self.w = [bytes({CHUNK}) for _ in range({N_CHUNKS})]
            def __call__(self, mesh_path=None, image_path=None):
                return trimesh.load(mesh_path, force='mesh')
    ''',
}


def anon_mb() -> float:
    for line in open('/proc/self/status', encoding='ascii'):
        if line.startswith('RssAnon:'):
            return int(line.split()[1]) / 1024
    return 0.0


def fragment_and_free(trim) -> float:
    """Набить кучу, оставить каждый тысячный кусок, освободить остальное — сколько МБ вернулось системе."""
    keep = []
    before = anon_mb()
    w = [bytes(CHUNK) for _ in range(N_CHUNKS)]
    keep.extend(w[::1000])
    full = anon_mb()
    del w
    if trim:
        trim()
    after = anon_mb()
    assert full - before > 200, f'набивка не набила: {before:.0f} → {full:.0f} МБ'
    return full - after


def case_trim(P) -> None:
    got_plain = fragment_and_free(None)
    got_trim = fragment_and_free(P._trim)
    assert got_trim > 200, f'_trim вернул системе {got_trim:.0f} МБ из ~300 — куча не отдаётся'
    print(f'  ✓ _trim: раздробленная куча возвращена ({got_trim:.0f} МБ; без него — {got_plain:.0f} МБ)')


def case_in_process(P, img, tmp) -> None:
    P.STAGE_PROC, P.STAGED = False, True
    base = anon_mb()
    res = P.generate(img, os.path.join(tmp, 'inproc'), seed=1)
    g = res['gpu']
    assert os.path.getsize(res['glb']) > 0 and os.path.exists(res['shape_glb']), res
    for k in ('ram_shape_gb', 'ram_paint_gb', 'ram_left_gb', 'shape_gb', 'paint_gb'):
        assert k in g, f'нет {k} в ответе: {g}'
    assert g['ram_shape_gb'] >= 0.25 and g['ram_paint_gb'] >= 0.25, f'пик стадии не виден: {g}'
    left_mb = g['ram_left_gb'] * 1024 - base
    assert left_mb < 120, f'после задания в воркере осталось +{left_mb:.0f} МБ — удержание не лечится'
    assert g['stage_proc'] is False and g['name'] == 'FAKE GPU', g
    print(f'  ✓ обычный режим: пик формы {g["ram_shape_gb"]} ГБ, покраски {g["ram_paint_gb"]} ГБ, '
          f'после задания +{max(left_mb, 0):.0f} МБ к исходному')


def case_stage_proc(P, img, tmp) -> None:
    P.STAGE_PROC = True
    base = anon_mb()
    res = P.generate(img, os.path.join(tmp, 'proc'), seed=1)
    g = res['gpu']
    assert os.path.getsize(res['glb']) > 0, res
    assert g['stage_proc'] is True and g['name'] == 'FAKE GPU', g
    assert g['ram_shape_gb'] >= 0.25 and g['ram_paint_gb'] >= 0.25, f'пик процесса стадии не дошёл: {g}'
    assert P._SHAPE is None and P._PAINT is None, 'модели загружены в воркер, а не в процесс стадии'
    grew = anon_mb() - base
    assert grew < 60, f'воркер вырос на {grew:.0f} МБ — память стадий осталась в нём'
    os.environ['FAKE_DIE'] = '1'
    try:
        P.generate(img, os.path.join(tmp, 'die'), seed=1)
    except RuntimeError as e:
        assert 'убит' in str(e), e
    else:
        raise AssertionError('убитый процесс стадии не дал ошибки')
    finally:
        os.environ.pop('FAKE_DIE', None)
        P.STAGE_PROC = False
    print(f'  ✓ STAGE_PROC: стадии в своих процессах (пики {g["ram_shape_gb"]}/{g["ram_paint_gb"]} ГБ), '
          f'воркер +{max(grew, 0):.0f} МБ; убитая стадия — ошибка')


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fakes = os.path.join(tmp, 'fakes')
        for rel, body in FAKES.items():
            path = os.path.join(fakes, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(textwrap.dedent(body))
        # подмены — первыми: настоящий torch (если он есть) не должен перехватить импорт; дети `spawn` получают тот же путь
        sys.path[:0] = [fakes, HERE]
        import pipeline as P  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
        assert P.torch.__file__.startswith(fakes), P.torch.__file__
        img = Image.new('RGBA', (64, 64), (200, 180, 160, 255))
        case_trim(P)
        case_in_process(P, img, tmp)
        case_stage_proc(P, img, tmp)
    print('память генерации: ВСЁ ЗЕЛЁНОЕ')


if __name__ == '__main__':
    main()
