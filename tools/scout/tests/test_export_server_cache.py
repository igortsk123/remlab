"""КЭШ РАЗОБРАННЫХ МЕШЕЙ ПОСТОЯННОГО ПРОЦЕССА ВЫГРУЗКИ (T-20261118-10/2 (б)): `export_server.PartsCache` держит меши, которыми пользуются, и убирает неиспользуемые.
Прежняя ошибка: время использования писали по пути файла, а ключ кэша — пара (путь, режим) → со 2-го заказа ВСЁ считалось «старым» и кэш выбрасывался целиком (каждый заказ — холодная
разборка мешей). Без Blender и мешей: файлы-заглушки и словарь вместо `draft_render._S3_PARTS`. python tools/scout/tests/test_export_server_cache.py"""
import gc
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', 'cycles_probe')]
sys.path.append(os.path.join(HERE, '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_export_server_cache')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
import export_server as ESV  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='partscache-')
files = {}
for n in 'abcdefg':
    p = os.path.join(tmp, f'{n}.glb')
    open(p, 'w').write(n)
    files[n] = p
loads = []


def parse(glb):
    """Как `draft_render._scene3d_parts`: ключ кэша — ПАРА (путь, режим), «сырой» путь в кэше не лежит."""
    key = (glb, False)
    if key not in DR._S3_PARTS:
        loads.append(os.path.basename(glb))
        DR._S3_PARTS[key] = [object()]
    return DR._S3_PARTS[key]


DR = types.SimpleNamespace(_S3_PARTS={}, _scene3d_parts=parse, S3_LITE=[False])
cache = ESV.PartsCache(DR)


def order(names):
    cache.begin()
    for n in names:
        DR._scene3d_parts(files[n])
    cache.end()


ESV.KEEP_REQUESTS, ESV.MAX_PARTS = 2, 16
for _ in range(5):
    order('abc')
check('те же меши из заказа в заказ — разбор один раз, кэш не пуст на 5-м заказе', sorted(loads) == ['a.glb', 'b.glb', 'c.glb'] and cache.count() == 3)

order('abcd')                                    # новый диван d
order('abc')                                     # d не использован 1 заказ — ещё держим (быстрый «отмена/повтор»)
check('меш, не использованный один заказ, ещё в кэше; общие — тоже', cache.count() == 4)
order('abc')                                     # d не использован 2 заказа подряд — долой
check('не использованный KEEP_REQUESTS заказов убран', cache.count() == 3 and (files['d'], False) not in DR._S3_PARTS)
n0 = len(loads)
order('abcd')
check('вернулся убранный — разбирается заново (один раз)', len(loads) == n0 + 1)

# потолок по числу: самые давно использованные — долой, свежие остаются
ESV.MAX_PARTS = 3
order('abcde')
check('потолок MAX_PARTS: остаётся не больше, самые свежие — на месте', cache.count() == 3 and (files['e'], False) in DR._S3_PARTS)

# после выброса меши собирает сборщик мусора (иначе память растёт до потолка процесса)
calls = []
orig = gc.collect
gc.collect = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
try:
    order('a')
    order('a')
    order('a')                                   # b, c, e не используются — выброшены
finally:
    gc.collect = orig
check('выброс мешей из кэша → явная сборка мусора', len(calls) >= 1)
calls.clear()
gc.collect = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
try:
    order('a')
finally:
    gc.collect = orig
check('ничего не выброшено — сборки нет (лишних секунд на заказе нет)', calls == [])

# кэш GLB отмечает каждое обращение `os.utime` (`draft_render._touch`): время изменения не признак «заменили» — иначе каждый заказ разбирал бы все меши заново
order('b')
n0 = len(loads)
for n in 'bc':
    os.utime(files[n], (1_700_000_000, 1_700_000_000))
order('b')
check('отметка обращения (utime) — не замена файла: меши не разбираются заново', len(loads) == n0)
# файл заменили на диске (новый файл, тот же размер, другое содержимое) — тоже сбрасывается
os.replace(files['b'], files['b'] + '.old')
open(files['b'], 'w').write('B')
n0 = len(loads)
order('b')
check('файл заменили другим того же размера — разбор заново', len(loads) == n0 + 1)

# файл заменили на диске — запись сбрасывается и разбирается заново
open(files['a'], 'w').write('aaaa')
n0 = len(loads)
order('a')
check('файл меша изменился — разбор заново', len(loads) == n0 + 1)

# ПРОГРЕВ (T-20261118-10/5): меш, разобранный заранее, живёт вне правил «последние заказы» и вне потолка MAX_PARTS, пока его не возьмёт заказ; взятый — как обычный
DR._S3_PARTS.clear()
cache.sig.clear(); cache.used_at.clear(); cache.hot.clear(); loads.clear()
for _ in range(3):
    order('ab')
n0 = len(loads)
check('прогрев: новый меш разбирается один раз → warmed, повтор → have', cache.warm(files['f']) == 'warmed' and cache.warm(files['f']) == 'have' and len(loads) == n0 + 1)
for _ in range(4):
    order('ab')                                  # прогретый f не использован уже 4 заказа подряд, но прогретый — не «старый»
check('прогретый меш не вытесняется правилом «последние KEEP_REQUESTS заказов»', (files['f'], False) in DR._S3_PARTS and files['f'] in cache.hot)
ESV.MAX_PARTS = 2
order('ab')
check('прогретые не считаются в потолок MAX_PARTS (использованные a,b на месте, f тоже)', cache.count() == 3)
ESV.MAX_PARTS = 16
n0 = len(loads)
order('abf')                                     # заказ берёт прогретый f: разбора нет, меш больше не «прогретый»
check('заказ с прогретым мешем: разбора нет, меш перешёл в обычные', len(loads) == n0 and files['f'] not in cache.hot)
order('ab'); order('ab')
check('взятый заказом и забытый — убирается по обычному правилу', (files['f'], False) not in DR._S3_PARTS)
cache.warm(files['g'])
open(files['g'], 'w').write('GGGG')               # файл прогретого меша заменили до заказа
cache.begin()
check('файл прогретого меша заменили — запись долой (заказ разберёт заново)', (files['g'], False) not in DR._S3_PARTS)
cache.end()
check('после заказа прогретых в списке нет (замена учтена)', files['g'] not in cache.hot)

print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
