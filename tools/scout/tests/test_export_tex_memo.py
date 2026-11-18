"""ПАМЯТКА ПО КАРТИНКАМ МЕШЕЙ В ВЫГРУЗКЕ (T-20261118-10/1 (в)): `export_scene._tex_memo` / `put_png(key=…)` дают те же имена и те же файлы, что прежний путь «массив → md5 → PNG в общий кэш».
Blender и браузер не нужны: синтетические картинки PIL, временный каталог кэша. python tools/scout/tests/test_export_tex_memo.py"""
import gc
import hashlib
import os
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', 'cycles_probe')]
sys.path.append(os.path.join(HERE, '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_export_tex_memo')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
import export_scene as ES  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='texmemo-')
ES.TEX_CACHE = os.path.join(tmp, 'cache')
rng = np.random.default_rng(7)
arr = rng.integers(0, 255, (64, 48, 3), dtype=np.uint8)
img = Image.fromarray(arr)

# 1) имя в кэше: то же, что считал прежний put_png (md5 пикселей + форма + уровень)
old_key = hashlib.md5(arr.tobytes() + str(arr.shape).encode()).hexdigest() + f'-{ES.PNG_LEVEL}.png'
check('png_key = прежнее имя файла кэша', ES.png_key(arr) == old_key)

# 2) put_png с готовым ключом и без него кладёт ОДИН И ТОТ ЖЕ файл
d1, d2, d3 = (os.path.join(tmp, n) for n in ('a.png', 'b.png', 'c.png'))
ES.put_png(arr, d1)
files_after_first = sorted(os.listdir(ES.TEX_CACHE))
ES.put_png(lambda: arr, d2, key=old_key)
check('кэш не плодит копий (то же имя)', sorted(os.listdir(ES.TEX_CACHE)) == files_after_first and len(files_after_first) == 1)
check('файлы побайтно те же', open(d1, 'rb').read() == open(d2, 'rb').read())
# файла в кэше нет — массив берётся из функции и пишется тот же PNG
os.remove(os.path.join(ES.TEX_CACHE, old_key))
called = []
ES.put_png(lambda: (called.append(1), arr)[1], d3, key=old_key)
check('нет файла в кэше — пиксели запрашиваются и PNG пишется заново', called == [1] and open(d3, 'rb').read() == open(d1, 'rb').read())
# файл есть — пиксели НЕ запрашиваются (в этом вся польза)
called.clear()
ES.put_png(lambda: (called.append(1), arr)[1], os.path.join(tmp, 'd.png'), key=old_key)
check('файл в кэше есть — функция пикселей не вызывается', called == [])

# 3) памятка: имя tex/<md5[:12]>.png и форма — как у прежнего save_tex; повтор по той же картинке — тот же объект записи
m1 = ES._tex_memo(img)
check('памятка: хеш картинки = md5(пиксели)[:12]', m1[1] == hashlib.md5(arr.tobytes()).hexdigest()[:12])
check('памятка: форма = (высота, ширина)', m1[3] == (64, 48))
check('памятка: ключ кэша PNG = png_key', m1[2] == old_key)
check('повтор по той же картинке — из памятки (тот же кортеж)', ES._tex_memo(img) is m1)
# другая картинка — свои хеши; чужой id не подхватывается
img2 = Image.fromarray(arr[::-1].copy())
m2 = ES._tex_memo(img2)
check('другая картинка — другие хеши', m2[1] != m1[1] and m2[2] != m1[2])
# картинка исчезла — запись исчезает (память не копится)
n_before = len(ES._TEXMEMO)
del img2, m2
gc.collect()
check('картинка собрана сборщиком — запись памятки ушла', len(ES._TEXMEMO) == n_before - 1)
# режим не RGB — приводится как раньше (convert('RGB'))
rgba = Image.fromarray(np.dstack([arr, np.full(arr.shape[:2], 255, np.uint8)]), 'RGBA')
m3 = ES._tex_memo(rgba)
check('RGBA приводится к RGB, как у прежнего пути', m3[1] == m1[1] and m3[3] == (64, 48))

# 4) _tex_image: как mesh_render.texture_of по выбору картинки и UV, но массив не строит
class V:
    pass
class M:
    pass
mesh = M()
mesh.visual = V()
mesh.visual.uv = np.zeros((3, 2))
mesh.visual.material = V()
mesh.visual.material.baseColorTexture = img
im, uv = ES._tex_image(mesh)
check('_tex_image: картинка и UV на месте', im is img and uv.dtype == np.float32 and uv.shape == (3, 2))
mesh.visual.material.baseColorTexture = None
mesh.visual.material.image = img
check('_tex_image: запасное поле material.image', ES._tex_image(mesh)[0] is img)
mesh.visual.uv = None
check('_tex_image: нет UV — (None, None)', ES._tex_image(mesh) == (None, None))

print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
