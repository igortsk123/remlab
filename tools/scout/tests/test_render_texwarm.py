"""ЗАГОТОВКА ТЕКСТУР МЕШЕЙ (T-20261118-10/3 ❷): `render_texwarm` кладёт в общий кэш PNG ровно те файлы, что закодировал бы заказ (имя по содержимому), повтор ничего не кодирует,
список мешей витрины — по `msid`/`sid` предметов и корзин замены без повторов. Сеть не нужна: синтетический GLB, временные кэши. python tools/scout/tests/test_render_texwarm.py"""
import os
import sys
import tempfile

import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', 'cycles_probe')]
import export_scene as ES  # noqa: E402
import mesh_render as MR  # noqa: E402
import render_texwarm as W  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


data = {'variants': [{'items': [{'sku': {'msid': 'm1', 'sid': 's1'}}, {'sku': {'sid': 's2'}}, {'sku': {}}, {'msid': 'm9'}]}, {'items': [{'sku': {'msid': 'm1'}}]}],
        'feeds': {'диван': [{'sid': 's3', 'msid': 'm3'}, {'sid': 's4'}], 'ковёр': [{'sid': 's2'}]}}
sids = W.showcase_sids(data)
check('меши витрины: msid, иначе sid; без повторов, порядок стабильный', sids == ['m1', 's2', 'm9', 'm3', 's4'])

rng = np.random.default_rng(5)
tmp = tempfile.mkdtemp(prefix='tw-')
ES.TEX_CACHE = os.path.join(tmp, 'cache')
m = trimesh.creation.box()
tex = Image.fromarray(rng.integers(0, 255, (24, 24, 3), dtype=np.uint8))
mrt = Image.fromarray(rng.integers(0, 255, (24, 24, 3), dtype=np.uint8))
mat = trimesh.visual.material.PBRMaterial(baseColorTexture=tex)
mat.metallicRoughnessTexture = mrt
m.visual = trimesh.visual.TextureVisuals(uv=rng.random((len(m.vertices), 2)), material=mat)
glb = os.path.join(tmp, 'm.glb')
trimesh.Scene(m).export(glb)

r1 = W.warm_mesh(glb)
files1 = sorted(os.listdir(ES.TEX_CACHE))
check('заготовка: две текстуры (цвет и шероховатость) — два файла кэша, оба новые', r1 == {'tex': 2, 'new': 2} and len(files1) == 2)
r2 = W.warm_mesh(glb)
check('повтор: ничего не кодируется, файлов столько же', r2 == {'tex': 2, 'new': 0} and sorted(os.listdir(ES.TEX_CACHE)) == files1)

# заказ после заготовки берёт готовые файлы (те же имена, что считает выгрузка по пикселям загруженного меша)
part = MR.load_parts(glb)[0]
img, _uv = ES._tex_image(part)
_h, key, _shape = ES._tex_memo(img)[1:4]
dst = os.path.join(tmp, 'x.png')
before = {f: os.stat(os.path.join(ES.TEX_CACHE, f)).st_ino for f in os.listdir(ES.TEX_CACHE)}
ES.put_png(lambda: (_ for _ in ()).throw(AssertionError('пиксели не должны запрашиваться')), dst, key=key)
check('заказ после заготовки: файл из кэша без кодирования, имя то же', key in before and os.path.samefile(dst, os.path.join(ES.TEX_CACHE, key)))
check('PNG заготовки = пиксели текстуры меша', np.array_equal(np.asarray(Image.open(dst).convert('RGB')), np.asarray(img.convert('RGB'))))

print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
