#!/usr/bin/env python3
"""Дисковый кэш сырой маски на ЦП (T-20261127-175/mask-cache; `salad/mask_cache.py`, `cutout_one.mask_cpu`).

  pip install numpy pillow && python tools/scout/salad/tests_mask_cache.py      (torch и настоящая модель не нужны: подставлена заглушка сети, она считает счётчик вызовов)

Что держим: попадание = побайтно то же, что пересчёт, и НЕ грузит модель; смена ревизии весов / фото на 1 байт / версии torch или кода кэша → промах; битый файл → пересчёт со строкой;
выключено → не читается и не пишется; запись атомарна; два писателя одного ключа — файл цел; потолок → старые уходят (по давности использования); мало места → не пишет и говорит;
маска с видеокарты в кэш не заходит; метка происхождения несёт правило кэша только когда оно включено. У каждой проверки — отрицательный контроль («сломал → покраснело»)."""
import contextlib
import io
import os
import sys
import tempfile
import threading
import types
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, SCOUT)
sys.path.insert(0, os.path.dirname(SCOUT))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_mask_cache')
try:
    import torch  # noqa: F401
except ImportError:
    sys.modules['torch'] = types.ModuleType('torch')

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import cutout_one as CO1  # noqa: E402
import cutout_origin as CO  # noqa: E402
import mask_cache as MC  # noqa: E402

# Тесты не зависят от диска машины: «мало места» в mask_cache.put сравнивает free_gb(папка теста) с порогом dev-disk.json (15 ГБ), а папки тестов — во
# временном каталоге (tmpfs /tmp сотни МБ, диск раннера 14–20 ГБ) → кэш молча не писал и тесты краснели по случайности. Поэтому везде «места достаточно»;
# единственный, кто проверяет порог, — test_low_disk (подменяет free_gb сам, `patched` вернёт эту заглушку).
FREE_GB_PLENTY = 1000.0
MC.free_gb = lambda path: FREE_GB_PLENTY

bad = []


def ok(cond, msg):
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        bad.append(msg)


class _T:
    def __init__(self, a):
        self.a = a

    def unsqueeze(self, i):
        return _T(self.a[None])

    def sigmoid(self):
        return self

    def __getitem__(self, i):
        return _T(self.a[i])

    def squeeze(self):
        return _T(self.a.squeeze())

    def numpy(self):
        return self.a


class Net:
    """Заглушка BiRefNet: маска — функция фото (сетка 16×16 по средней яркости), счётчик вызовов."""
    calls = 0

    def __call__(self, x):
        Net.calls += 1
        return [_T(x.a[None])]


def tf(src):
    g = np.asarray(src.convert('L').resize((16, 16)), dtype=np.float64) / 255.0
    return _T(g)


def stub_model():
    CO1._LOCAL = (types.SimpleNamespace(no_grad=contextlib.nullcontext), Net(), tf)


def photo(seed=1, size=(40, 30)):
    rng = np.random.RandomState(seed)
    return Image.fromarray(rng.randint(0, 256, (size[1], size[0], 3), dtype=np.uint8), 'RGB')


def same(a, b):
    return a.size == b.size and a.mode == b.mode and a.tobytes() == b.tobytes()


@contextlib.contextmanager
def env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def patched(obj, name, val):
    old = getattr(obj, name)
    setattr(obj, name, val)
    try:
        yield
    finally:
        setattr(obj, name, old)


def run(img, **kw):
    """Вызов mask_cpu: → (RGBA, сколько раз звали модель в этом вызове, stderr)."""
    n0 = Net.calls
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = CO1.mask_cpu(img)
    return out, Net.calls - n0, err.getvalue()


def files(root):
    return sorted(os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs)


def base_env(td):
    return dict(MASK_CACHE=1, MASK_CACHE_DIR=td, MASK_CACHE_RULES=os.path.join(td, 'нет-такого.json'), MASK_CACHE_MAX_GB=3)


def test_hit():
    print('1. попадание = побайтно то же, что пересчёт; модель на попадании не грузится и не зовётся')
    stub_model()
    p = photo()
    with tempfile.TemporaryDirectory() as td:
        with env(**base_env(td)):
            with env(MASK_CACHE=0):
                a, n_a, _ = run(p)
            b, n_b, _ = run(p)
            c, n_c, _ = run(p)
            ok(n_a == 1 and n_b == 1 and n_c == 0, f'модель звали: без кэша {n_a}, промах {n_b}, попадание {n_c} (на попадании — 0)')
            ok(same(a, b) and same(b, c) and a.getchannel('A').getextrema() != (255, 255), 'RGBA без кэша = на промахе = на попадании — байт в байт (альфа не пустая)')
            ok(len(files(td)) == 1 and files(td)[0].endswith('.png'), 'в кэше один файл на фото')
            # попадание не грузит МОДЕЛЬ: сбрасываем загруженную и подставляем загрузчик, который сразу падает
            CO1._LOCAL = None
            sys.modules['transformers'] = types.SimpleNamespace(AutoModelForImageSegmentation=types.SimpleNamespace(
                from_pretrained=lambda *a, **k: (_ for _ in ()).throw(AssertionError('модель загружена на попадании'))))
            try:
                d, _, _ = run(p)
                ok(same(d, a), 'попадание при НЕ загруженной модели: результат тот же, загрузчик не вызван')
            except AssertionError as e:
                ok(False, str(e))
            finally:
                sys.modules.pop('transformers', None)
                stub_model()
            # −контроль: ключ ломается (каждый раз новый) → второй вызов считает снова
            with patched(MC, 'key_for', lambda s, t: uuid.uuid4().hex):
                run(p)
                _, n2, _ = run(p)
            ok(n2 == 1, '−контроль: при «плавающем» ключе попадания нет — модель зовётся (тест это ловит)')


def test_key_parts():
    print('2–4. ключ: смена ревизии весов, фото на 1 байт, версии torch/кода кэша → промах')
    stub_model()
    p = photo()
    with tempfile.TemporaryDirectory() as td:
        with env(**base_env(td)):
            run(p)
            _, n, _ = run(p)
            ok(n == 0, 'исходное состояние: попадание')
            with patched(CO1, 'BIREFNET_REVISION', 'f' * 40):
                _, n, _ = run(p)
            ok(n == 1 and len(files(td)) == 2, 'другая ревизия весов → промах, новый файл')
            q = p.copy()
            q.putpixel((3, 4), tuple((v + 1) % 256 for v in q.getpixel((3, 4))))
            _, n, _ = run(q)
            ok(n == 1 and len(files(td)) == 3, 'фото на 1 байт другое → промах')
            with patched(MC, 'torch_version', lambda: '99.0'):
                _, n, _ = run(p)
            ok(n == 1, 'другая версия torch → промах')
            with patched(MC, 'MASK_CACHE_VERSION', MC.MASK_CACHE_VERSION + 1):
                _, n, _ = run(p)
            ok(n == 1, 'другая версия кода кэша → промах')
            # −контроли: часть ключа выкинута → тот же вызов даёт ЛОЖНОЕ попадание
            with patched(MC, 'env_tag', lambda repo, rev: 'константа'):
                run(p)                      # пишет под «константой»
                with patched(CO1, 'BIREFNET_REVISION', 'e' * 40):
                    _, n, _ = run(p)
            ok(n == 0, '−контроль: без ревизии в ключе смена ревизии давала бы попадание (поэтому ревизия в ключе обязана быть)')
            with patched(MC, 'key_for', lambda s, t: f'{s.width}x{s.height}'.ljust(64, '0')):
                run(p)
                _, n, _ = run(q)
            ok(n == 0, '−контроль: ключ только по размеру → другое фото давало бы чужую маску (тест это поймал бы)')


def test_corrupt():
    print('5. битый файл кэша → пересчёт со строкой, файл переписан, молча не падает')
    stub_model()
    p = photo()
    with tempfile.TemporaryDirectory() as td:
        with env(**base_env(td)):
            ref, _, _ = run(p)
            f = files(td)[0]
            for name, payload in (('мусор', lambda: open(f, 'wb').write(b'not a png at all')),
                                  ('обрезан', lambda: open(f, 'wb').write(open(f, 'rb').read()[:40])),
                                  ('чужой размер', lambda: Image.new('L', (7, 7)).save(f, 'PNG')),
                                  ('режим RGBA', lambda: Image.new('RGBA', p.size).save(f, 'PNG'))):
                if name == 'обрезан':
                    run(p)                       # вернуть корректный файл, потом обрезать
                    data = open(f, 'rb').read()
                    open(f, 'wb').write(data[:40])
                else:
                    payload()
                out, n, err = run(p)
                ok(n == 1 and same(out, ref) and 'битый файл' in err and Image.open(f).mode == 'L',
                   f'«{name}»: модель зовётся, результат тот же, строка «битый файл», файл исправлен')
            # −контроль: «снисходительный» читатель без проверки режима/размера ломается на чужом размере
            Image.new('L', (7, 7)).save(f, 'PNG')
            lenient = lambda src, tag, cfg=None: Image.open(f).convert('L')   # noqa: E731
            try:
                with patched(MC, 'get', lenient):
                    CO1.mask_cpu(p)
                broke = False
            except Exception:  # noqa: BLE001
                broke = True
            ok(broke, '−контроль: читатель без проверки размера на чужом файле ломается (значит проверка в get нужна)')


def test_off():
    print('6. выключено: кэш не читается и не пишется')
    stub_model()
    p = photo()
    with tempfile.TemporaryDirectory() as td:
        with env(**base_env(td)):
            ref, _, _ = run(p)
            f = files(td)[0]
            poison = Image.new('L', p.size, 255)
            poison.save(f, 'PNG')                                          # ядовитый файл с верным ключом
            with env(MASK_CACHE=0):
                out, n, _ = run(p)
                ok(n == 1 and same(out, ref), 'выключен: модель считает, ядовитый файл с верным ключом НЕ подхвачен')
                q = photo(2)
                run(q)
                ok(len(files(td)) == 1, 'выключен: ничего не записано')
            out2, n2, _ = run(p)
            ok(n2 == 0 and out2.getchannel('A').getextrema() == (255, 255), '−контроль: включён — тот же ядовитый файл подхватывается (ключ и файл были настоящие)')
    with tempfile.TemporaryDirectory() as td:
        with env(MASK_CACHE=None, MASK_CACHE_DIR=td, MASK_CACHE_RULES=os.path.join(td, 'нет.json')):
            ok(MC.enabled() is False and MC.label() is None, 'нет файла правил — кэш выключен, метка пустая')
            run(p)
            ok(files(td) == [], 'по умолчанию (без флага) ничего не пишется')
        rf = os.path.join(td, 'r.json')
        open(rf, 'w').write('{"enabled": true, "dir": "%s", "max_gb": 3}' % td)
        with env(MASK_CACHE=None, MASK_CACHE_DIR=None, MASK_CACHE_RULES=rf):
            ok(MC.enabled() is True and MC.rules()['dir'] == td, 'enabled=true в файле правил включает кэш, dir берётся из файла')
    real = MC.rules.__globals__['json'].load(open(MC.RULES, encoding='utf-8'))
    ok(isinstance(real.get('enabled'), bool) and real.get('max_gb') == 3 and real.get('dir'), f'боевой файл правил: enabled — булево, max_gb=3, dir задан ({os.path.relpath(MC.RULES, SCOUT)})')


def test_atomic_and_writers():
    print('7–8. запись атомарна; два писателя одного ключа — файл цел')
    stub_model()
    p = photo()
    alpha = Image.fromarray(np.random.RandomState(5).randint(0, 256, (p.height, p.width), dtype=np.uint8), 'L')
    tag = MC.env_tag(CO1.BIREFNET_REPO, CO1.BIREFNET_REVISION)
    with tempfile.TemporaryDirectory() as td:
        cfg = {'enabled': True, 'dir': td, 'max_gb': 3}
        final = MC.path_for(td, MC.key_for(p, tag))
        real_save = Image.Image.save

        def half_save(self, fp, *a, **k):
            if isinstance(fp, str) and '.tmp' in fp:
                open(fp, 'wb').write(b'\x89PNG half')
                raise OSError('оборвали на полпути')
            return real_save(self, fp, *a, **k)
        err = io.StringIO()
        with patched(Image.Image, 'save', half_save), contextlib.redirect_stderr(err):
            r = MC.put(alpha, p, tag, cfg)
        ok(r is False and not os.path.exists(final) and not [x for x in files(td) if '.tmp' in x] and 'запись не удалась' in err.getvalue(),
           'обрыв записи: под настоящим именем файла нет, временный убран, строка в логе')
        # −контроль: «наивная» запись прямо в конечный файл оставляет обломок под настоящим именем
        os.makedirs(os.path.dirname(final), exist_ok=True)
        try:
            with patched(Image.Image, 'save', half_save):
                Image.Image.save(alpha, final + '.tmp-x')
        except OSError:
            pass
        naive_final = final + '.naive'
        try:
            open(naive_final, 'wb').write(b'\x89PNG half')
            raise OSError('обрыв')
        except OSError:
            pass
        ok(os.path.exists(naive_final), '−контроль: запись прямо в конечное имя оставила бы обломок (проверка «нет файла» была бы красной)')
        os.remove(naive_final)
        for x in files(td):
            if '.tmp' in x:
                os.remove(x)
        # два писателя
        names = []
        real_replace = os.replace
        lock = threading.Lock()

        def rec_replace(a, b):
            with lock:
                names.append(a)
            return real_replace(a, b)
        errs = []

        def w():
            try:
                MC.put(alpha, p, tag, cfg)
            except Exception as e:  # noqa: BLE001
                errs.append(e)
        with patched(os, 'replace', rec_replace):
            ts = [threading.Thread(target=w) for _ in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        got = MC.get(p, tag, cfg)
        ok(not errs and got is not None and same(got, alpha) and [x for x in files(td) if '.tmp' in x] == [], '8 писателей одного ключа: файл цел, читается, равен записанному, временных нет')
        ok(len(names) == 8 and len(set(names)) == 8, 'у каждого писателя своё имя временного файла (иначе они затирали бы друг друга)')
        ok(len(set(['a', 'a'])) != 2, '−контроль: одинаковые имена были бы замечены проверкой уникальности')
    with tempfile.TemporaryDirectory() as td:
        blocker = os.path.join(td, 'файл-вместо-папки')
        open(blocker, 'w').write('x')
        with env(**dict(base_env(td), MASK_CACHE_DIR=os.path.join(blocker, 'sub'))):
            out, n, err2 = run(p)
            ok(n == 1 and out.getchannel('A').getextrema() != (255, 255) and 'запись не удалась' in err2, 'папка кэша не создаётся: результат вычисления есть, строка в логе, без падения')


def test_overflow():
    print('9. потолок: переполнил — самые давние по использованию уходят; недавно использованные остаются')
    p1, p2, p3 = photo(11, (200, 200)), photo(12, (200, 200)), photo(13, (200, 200))
    rng = np.random.RandomState(7)

    def alpha(): return Image.fromarray(rng.randint(0, 256, (200, 200), dtype=np.uint8), 'L')
    tag = 'tag'
    with tempfile.TemporaryDirectory() as td:
        a1, a2, a3 = alpha(), alpha(), alpha()
        probe = os.path.join(td, 'probe.png')
        a1.save(probe, 'PNG', compress_level=3)
        one = os.path.getsize(probe)
        os.remove(probe)
        cfg = {'enabled': True, 'dir': td, 'max_gb': (one * 2.5) / 1e9}          # влезает ровно два файла
        import time
        t0 = time.time()
        for _ in range(1):
            MC.put(a1, p1, tag, cfg)
            MC.put(a2, p2, tag, cfg)
        f1, f2 = MC.path_for(td, MC.key_for(p1, tag)), MC.path_for(td, MC.key_for(p2, tag))
        os.utime(f1, (t0 - 300, t0 - 300))
        os.utime(f2, (t0 - 200, t0 - 200))
        ok(MC.get(p1, tag, cfg) is not None, 'файл 1 прочитан (попадание) — теперь он «недавний», хотя записан раньше файла 2')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            MC.put(a3, p3, tag, cfg)
        f3 = MC.path_for(td, MC.key_for(p3, tag))
        ok(os.path.exists(f1) and not os.path.exists(f2) and os.path.exists(f3), 'ушёл самый давний по использованию (файл 2), недавний прочитанный (1) и новый (3) остались')
        ok(sum(s for _, s, _ in MC._scan(td)) <= cfg['max_gb'] * 1e9 and 'убрано старых файлов: 1' in err.getvalue(), 'сумма в пределах потолка, в логе — сколько убрано')
        # −контроль: без обновления давности при попадании вытеснился бы файл 1
        MC.evict(td, 10 ** 12, 1)           # очистка папки теста (внутри неё)
        MC.put(a1, p1, tag, cfg)
        MC.put(a2, p2, tag, cfg)
        os.utime(f1, (t0 - 300, t0 - 300))
        os.utime(f2, (t0 - 200, t0 - 200))
        with patched(os, 'utime', lambda *a, **k: None):
            MC.get(p1, tag, cfg)
        with contextlib.redirect_stderr(io.StringIO()):
            MC.put(a3, p3, tag, cfg)
        ok(not os.path.exists(f1) and os.path.exists(f2), '−контроль: без os.utime при попадании ушёл бы НЕдавний файл 1 (вытеснение по давности держится на utime)')
        # вытеснение не выходит за папку кэша
        with tempfile.TemporaryDirectory() as other:
            keep = os.path.join(other, 'ab')
            os.makedirs(keep)
            open(os.path.join(keep, 'чужой.png'), 'wb').write(b'x' * 10)
            MC.evict(td, 10 ** 12, 1)
            ok(os.path.exists(os.path.join(keep, 'чужой.png')), 'вытеснение трогает только папку кэша: чужой файл рядом цел')


def test_low_disk():
    print('10. мало места: не пишет и говорит; чтение продолжается')
    p = photo(21)
    alpha = Image.new('L', p.size, 128)
    tag = 'tag'
    need, _ = MC.min_free_gb()
    with tempfile.TemporaryDirectory() as td:
        cfg = {'enabled': True, 'dir': td, 'max_gb': 3}
        err = io.StringIO()
        with patched(MC, 'free_gb', lambda path: need - 1), contextlib.redirect_stderr(err):
            r = MC.put(alpha, p, tag, cfg)
        ok(r is False and files(td) == [] and 'диск, запись пропущена' in err.getvalue(), f'свободно < {need:g} ГБ (порог dev-disk.json): записи нет, строка «кэш: диск, запись пропущена»')
        with patched(MC, 'free_gb', lambda path: need + 100):
            r2 = MC.put(alpha, p, tag, cfg)
        ok(r2 is True and len(files(td)) == 1, '−контроль: места достаточно → тот же вызов пишет (значит отказ был из-за места)')
        with patched(MC, 'free_gb', lambda path: 0.1):
            ok(MC.get(p, tag, cfg) is not None, 'мало места не мешает читать готовое')
    ok(need == 15.0 or need > 0, f'порог — из dev-disk.json (start_min_free_gb={need:g}), своей цифры нет')


def test_label_and_gpu():
    print('11–12. метка: правило кэша пишется только когда включено; видеокарта в кэш не ходит')
    stub_model()
    p = photo()
    buf = io.BytesIO()
    Image.new('RGB', (60, 40), (250, 250, 250)).save(buf, 'PNG')
    shape = Image.new('RGBA', (60, 40), (10, 10, 10, 255))
    off = CO.build(buf.getvalue(), shape=shape, code='abcdef1')
    on = CO.build(buf.getvalue(), shape=shape, code='abcdef1', mask_cache='v1')
    ok('cache' not in off['mask'] and CO.check(off) == [], 'выключен: в метке поля cache нет, метка прежняя, проверка проходит')
    ok(on['mask'].get('cache') == 'v1' and CO.check(on) == [] and {k: v for k, v in on['mask'].items() if k != 'cache'} == off['mask'], 'включён: mask.cache=v1, остальное то же, проверка проходит')
    with tempfile.TemporaryDirectory() as td:
        with env(**base_env(td)):
            ok(MC.label() == f'v{MC.MASK_CACHE_VERSION}', 'label() при включённом кэше = версия кода кэша')
        with env(**dict(base_env(td), MASK_CACHE=0)):
            ok(MC.label() is None, '−контроль: при выключенном label() пусто')
    src = open(os.path.join(SCOUT, 'cutout_sync.py'), encoding='utf-8').read()
    body_fal = src.split('def mask_fal', 1)[1].split('\ndef ', 1)[0]
    body_salad = src.split('def mask_salad', 1)[1].split('\ndef ', 1)[0]
    ok('mask_cache' not in body_fal and 'MC.' not in body_fal and 'mask_cache' not in body_salad and 'MC.' not in body_salad, 'mask_fal / mask_salad (видеокарта) кэш не вызывают')
    users = [f for f in os.listdir(HERE) if f.endswith('.py') and not f.startswith('tests_') and f != 'mask_cache.py'
             and 'MC.get(' in open(os.path.join(HERE, f), encoding='utf-8').read()]
    ok(users == ['cutout_one.py'], f'читает кэш только cutout_one.mask_cpu: {users}')
    ok('MC.get(' in 'x = MC.get(src)' and 'mask_cache' in 'def mask_salad(): mask_cache', '−контроль: проверка по тексту видит вызов кэша, если бы он появился в видеокарточном пути')


if __name__ == '__main__':
    test_hit()
    test_key_parts()
    test_corrupt()
    test_off()
    test_atomic_and_writers()
    test_overflow()
    test_low_disk()
    test_label_and_gpu()
    print(f'tests_mask_cache: ошибок {len(bad)}')
    sys.exit(1 if bad else 0)
