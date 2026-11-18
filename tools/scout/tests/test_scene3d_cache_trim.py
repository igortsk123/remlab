"""ПОТОЛОК КЭША GLB НЕ СТИРАЕТ МЕШИ ТЕКУЩЕГО КАДРА (T-20261117-19/3): на полном кэше докачка нового меша удаляла самые давние по доступу файлы,
в том числе уже выбранные для этого же кадра, — экспорт печатал «диван пропущен (string is not a file)», подушка висела в воздухе.
    python tools/scout/tests/test_scene3d_cache_trim.py        # без сети
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
sys.path.append(os.path.join(HERE, '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_scene3d_cache_trim')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
import draft_render as DR  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp()
DR.SCENE3D_CACHE = tmp
old, fresh, hit = (os.path.join(tmp, n + '.glb') for n in ('old', 'fresh', 'hit'))
for f in (old, fresh, hit):
    open(f, 'wb').write(b'x' * (1024 * 1024))
t = time.time()
os.utime(old, (t - 7200, t - 7200))
os.utime(hit, (t - 7200, t - 7200))      # лежал давно, но кадр его только что выбрал
DR._scene3d_glb('hit')                   # попадание в кэш освежает файл
check('попадание в кэш освежает время доступа', time.time() - os.stat(hit).st_atime < 60)
n = DR._cache_trim(cap_mb=1.5)           # потолок ниже суммы: удалить надо, но не свежее
check('потолок удаляет давний файл', not os.path.exists(old) and n == 1)
check('потолок не трогает свежие файлы (выбранные для кадра и только что докачанные)', os.path.exists(hit) and os.path.exists(fresh))
print('итог:', 'чисто' if not fails else f'{len(fails)} провал(ов): {fails}')
sys.exit(1 if fails else 0)
