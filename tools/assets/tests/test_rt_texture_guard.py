#!/usr/bin/env python3
"""Сторож текстур лёгких копий (T-20261107-15, `tools/assets/runtime_mesh.py:copy_problems/build_copy`): ночью 07.11 gltfpack
при квоте /tmp записал вместо текстуры `data:image/png;base64,ERR/` с кодом 0, и 14 моделей стали белыми на проде.
Проверяем на подложенных GLB: битый data-URI, неверная подпись в бинарном чанке, годные PNG/JPEG/KTX2; перепаковку без KTX2;
отказ без записи копии. gltfpack не нужен — упаковка подменена. Запуск: python tools/assets/tests/test_rt_texture_guard.py"""
import base64
import io
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import runtime_mesh as RM  # noqa: E402

FAILS = []


def ok(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), (120, 100, 90)).save(buf, format='PNG')
    return buf.getvalue()


def jpeg_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), (120, 100, 90)).save(buf, format='JPEG')
    return buf.getvalue()


def ktx2_bytes():
    """Минимальный целый KTX2: подпись, 4×4, один уровень внутри файла (схема 0)."""
    hdr = RM_KTX2_ID + struct.pack('<9I', 0, 1, 4, 4, 0, 0, 1, 1, 0) + struct.pack('<4I2Q', 0, 0, 0, 0, 0, 0)
    level_off = len(hdr) + 24
    return hdr + struct.pack('<3Q', level_off, 16, 16) + b'\x00' * 16


RM_KTX2_ID = b'\xabKTX 20\xbb\r\n\x1a\n'


def glb(image: dict, payload: bytes = b'') -> bytes:
    """GLB с одним материалом и картой цвета: картинка — `image` (uri или bufferView на `payload`)."""
    js = {'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
          'textures': [{'source': 0}], 'images': [image], 'buffers': [{'byteLength': len(payload)}],
          'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(payload)}] if payload else []}
    if image.get('mimeType') == 'image/ktx2':
        js['textures'] = [{'extensions': {'KHR_texture_basisu': {'source': 0}}}]
    return RM.write_glb(js, payload)


def put(d, name, data):
    p = os.path.join(d, name)
    with open(p, 'wb') as fh:
        fh.write(data)
    return p


with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as d:
    err = put(d, 'err.glb', glb({'uri': 'data:image/png;base64,ERR/'}))
    ok('data-URI «ERR/» (ночь 07.11) — битая', bool(RM.copy_problems(err)), RM.copy_problems(err))
    junk = put(d, 'junk.glb', glb({'uri': 'data:image/png;base64,' + base64.b64encode(b'not an image').decode()}))
    ok('data-URI декодируется, но без подписи PNG — битая', bool(RM.copy_problems(junk)))
    good_uri = put(d, 'uri.glb', glb({'uri': 'data:image/png;base64,' + base64.b64encode(png_bytes()).decode()}))
    ok('data-URI с целым PNG — годна', RM.copy_problems(good_uri) == [], RM.copy_problems(good_uri))
    bad_bin = put(d, 'badbin.glb', glb({'bufferView': 0, 'mimeType': 'image/jpeg'}, b'\x00' * 64))
    ok('бинарный чанк без подписи JPEG — битая', bool(RM.copy_problems(bad_bin)))
    jpg = put(d, 'jpg.glb', glb({'bufferView': 0, 'mimeType': 'image/jpeg'}, jpeg_bytes()))
    ok('JPEG в бинарном чанке — годна', RM.copy_problems(jpg) == [], RM.copy_problems(jpg))
    ktx = put(d, 'ktx.glb', glb({'bufferView': 0, 'mimeType': 'image/ktx2'}, ktx2_bytes()))
    ok('целый KTX2 — годна', RM.copy_problems(ktx) == [], RM.copy_problems(ktx))
    bad_ktx = put(d, 'badktx.glb', glb({'bufferView': 0, 'mimeType': 'image/ktx2'}, RM_KTX2_ID + b'\x00' * 20))
    ok('KTX2 с обрезанным заголовком — битая', bool(RM.copy_problems(bad_ktx)))
    notex = put(d, 'notex.glb', RM.write_glb({'asset': {'version': '2.0'}, 'materials': [{}]}, b''))
    ok('без карты цвета, исходник без картинок — годна', RM.copy_problems(notex, expect_texture=False) == [])
    ok('без карты цвета, а у исходника были — битая', bool(RM.copy_problems(notex, expect_texture=True)))
    ok('не GLB — битая (не падаем)', bool(RM.copy_problems(put(d, 'x.glb', b'garbage'))))

    # ——— build_copy: упаковка подменена ———
    src = put(d, 'src.glb', open(jpg, 'rb').read())
    real_pack = RM.pack
    calls = []

    def fake(results):
        def pack(s, dst, simplify=0.0, ktx2=True):
            calls.append(ktx2)
            data = results.get(ktx2)
            if data is None:
                return False, 'нет бинаря'
            put(os.path.dirname(dst), os.path.basename(dst), data)
            return True, ''
        return pack

    try:
        dst = os.path.join(d, 'm1.glb')
        calls.clear()
        RM.pack = fake({True: open(ktx, 'rb').read()})
        packed, how, probs = RM.build_copy(src, dst, 0, True, True)
        ok('KTX2 цел — копия KTX2 с первого раза', (packed, how, probs, calls) == (True, 'KTX2', [], [True]), (how, probs, calls))

        dst = os.path.join(d, 'm2.glb')
        calls.clear()
        RM.pack = fake({True: open(err, 'rb').read(), False: open(jpg, 'rb').read()})
        packed, how, probs = RM.build_copy(src, dst, 0, True, True)
        ok('KTX2 битый → перепаковка без KTX2', (how, probs, calls) == ('без KTX2', [], [True, False]), (how, probs, calls))
        ok('  записанная копия цела', RM.copy_problems(dst) == [])
        ok('  временный .new убран', not os.path.exists(dst[:-4] + '.new.glb'))

        dst = os.path.join(d, 'm3.glb')
        old = put(d, 'm3.glb', b'OLD')
        bad_src = put(d, 'badsrc.glb', open(err, 'rb').read())
        RM.pack = fake({True: open(err, 'rb').read(), False: open(bad_bin, 'rb').read()})
        packed, how, probs = RM.build_copy(bad_src, dst, 0, True, True)
        ok('битое всё — отказ с причинами', bool(probs) and how == '', (how, probs))
        ok('  прежний файл не тронут (копию не пишем)', open(old, 'rb').read() == b'OLD')
        ok('  временный .new убран', not os.path.exists(dst[:-4] + '.new.glb'))

        dst = os.path.join(d, 'm4.glb')
        RM.pack = fake({})
        packed, how, probs = RM.build_copy(src, dst, 0, True, True)
        ok('gltfpack не упаковал — исходная копия, если цела', (packed, how, probs) == (False, 'без сжатия', []), (how, probs))
    finally:
        RM.pack = real_pack

if FAILS:
    print(f'\n{len(FAILS)} провал(ов)')
    sys.exit(1)
print('\nвсе проверки прошли')
