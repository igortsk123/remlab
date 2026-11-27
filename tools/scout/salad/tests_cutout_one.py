#!/usr/bin/env python3
"""Единый модуль вырезки (T-20261127-175/9, шаги 9.1–9.2): цепочка не изменила байты, шаги старой цепочки — за флагом, метка происхождения.

  pip install scipy numpy pillow && python tools/scout/salad/tests_cutout_one.py      (torch не нужен: `preprocess` берёт torch только внутри функций — подставляем пустой модуль)

1. ЗАМОРОЖЕННЫЕ ФОТО. `tools/scout/tests/fixtures/cutout_one/`: 4 случая (комод и белый фон; комод на сером фоне — `net_only`; стол; шкаф) — фото 288 px и сырая маска BiRefNet
   (`<случай>.photo.png`, `.net.png`) и ЭТАЛОН — результат СТАРОГО кода `cutout_sync.chain_shape` (база 2d96f89ff, до переноса) в `.shape.png`. Новый код обязан дать тот же
   массив RGBA до последнего бита (не файл PNG: кодировщик от версии Pillow зависит, пиксели — нет).
2. Шаги старой цепочки выключены по умолчанию (ночная оценка прежняя); включённые работают на синтетике (пара стульев; хвост у пола дивана) и не работают у других ролей.
3. Метка происхождения: запись, проверка, PNG с текстовым блоком (пиксели те же), отказы на старой/чужой/подменённой метке."""
import io
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, SCOUT)
sys.path.insert(0, os.path.dirname(SCOUT))      # tools/ — remlab_tmp
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_cutout_one')               # временные файлы — в папку проекта, не в /tmp (квота DEV)
try:
    import torch  # noqa: F401
except ImportError:                      # CI без torch: preprocess использует его только внутри функций
    sys.modules['torch'] = types.ModuleType('torch')

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import cutout_one as CO1  # noqa: E402
import cutout_origin as CO  # noqa: E402
import preprocess as PRE  # noqa: E402

FIX = os.path.join(SCOUT, 'tests', 'fixtures', 'cutout_one')
bad = []


def ok(cond, msg):
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        bad.append(msg)


def cs_module():
    try:
        import cutout_sync as CS
        return CS
    except Exception as e:  # noqa: BLE001 — окружение без зависимостей ночного шага (БД-клиент и т.п.)
        print(f'  (cutout_sync не импортируется здесь: {type(e).__name__}: {str(e)[:80]} — сверка через него пропущена, через cut_shape — есть)')
        return None


def load_case(name):
    photo = Image.open(os.path.join(FIX, f'{name}.photo.png')).convert('RGB')
    net = Image.open(os.path.join(FIX, f'{name}.net.png'))
    net.load()
    exp = np.asarray(Image.open(os.path.join(FIX, f'{name}.shape.png')).convert('RGBA'))
    return photo, net, exp


def test_frozen():
    print('1. замороженные фото: цепочка даёт тот же массив, что старый код')
    cases = json.load(open(os.path.join(FIX, 'cases.json'), encoding='utf-8'))
    CS = cs_module()
    ok(len(cases) >= 4, f'в наборе {len(cases)} случаев (комод, комод на сером, стол, шкаф)')
    for name, c in sorted(cases.items()):
        photo, net, exp = load_case(name)
        shape, info = CO1.cut_shape(photo, net, role=c['role'])
        got = np.asarray(shape)
        ok(got.shape == exp.shape and np.array_equal(got, exp), f'{name} ({c["role"]}): cut_shape = эталон старого кода, различий {int((got != exp).any(-1).sum()) if got.shape == exp.shape else "размер"} px')
        ok(info['bg_mode'] == c['bg_mode'] and 'chain' not in info, f'{name}: bg_mode={info["bg_mode"]}, у ночной оценки в отчёте нет поля chain (отчёт прежний)')
        if CS is not None:
            s2, i2 = CS.chain_shape(photo, net, role=c['role'])
            ok(np.array_equal(np.asarray(s2), exp), f'{name}: cutout_sync.chain_shape = эталон')
            cut, ci = CS.chain(photo, net, role=c['role'])
            ok(np.array_equal(np.asarray(cut), np.asarray(PRE.trim_alpha(shape))) and ci['photo']['object_xy'] == list(CO1.crop_box(shape)[:2]),
               f'{name}: cutout_sync.chain = обрезка того же кадра + photo.object_xy')
    modes = {c['bg_mode'] for c in cases.values()}
    ok(modes == {'white_flat', 'net_only'}, f'покрыты оба режима фона: {sorted(modes)}')


def test_wrapper_is_thin():
    print('1б. cutout_sync.chain_shape / chain / mask_local — вызовы единого модуля (копии тела нет)')
    import ast
    src = open(os.path.join(SCOUT, 'cutout_sync.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    fn = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name, callee in (('chain_shape', 'cut_shape'), ('mask_local', 'mask_cpu')):
        calls = {c.func.attr for c in ast.walk(fn[name]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        ok(callee in calls and len(fn[name].body) <= 3, f'{name} вызывает CO1.{callee} (тело ≤ 3 операторов)')
    kws = [k.arg for c in ast.walk(fn['chain_shape']) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == 'cut_shape' for k in c.keywords]
    ok(kws == ['role'], f'chain_shape (ночная оценка) зовёт cut_shape только с role — без шагов старой цепочки (ключи: {kws})')
    calls = {c.func.id for c in ast.walk(fn['chain']) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    ok('chain_shape' in calls, 'chain берёт вырезку из chain_shape (шаги цепочки — только в модуле; хвост обрезки/вердикта остаётся в chain — тест паспортов (г))')
    ok('hybrid_mask.refine' not in src and 'studio_bg.' not in src, 'в cutout_sync нет шагов цепочки (hybrid_mask / studio_bg — только в cutout_one)')
    ok(CO1.CO.CHAIN_VERSION != getattr(PRE, 'ASSESSOR_VERSION', None) and PRE.ASSESSOR_VERSION == 'a1', 'ASSESSOR_VERSION не тронута (a1), метка цепочки — своя')


def white(w, h):
    return np.full((h, w, 3), 255, np.uint8)


def scene(boxes, w=320, h=240, bridge=None):
    """Белое фото с серыми прямоугольниками-«предметами» и сырая маска (альфа 255 в прямоугольниках)."""
    img = white(w, h)
    a = np.zeros((h, w), np.uint8)
    for (x0, y0, x1, y1) in boxes:
        img[y0:y1, x0:x1] = (110, 100, 95)
        a[y0:y1, x0:x1] = 255
    if bridge:
        x0, y0, x1, y1 = bridge
        img[y0:y1, x0:x1] = (115, 105, 100)
        a[y0:y1, x0:x1] = 255
    net = Image.fromarray(np.dstack([img, a]), 'RGBA')
    return Image.fromarray(img), net


def ncomp(shape, thr=128):
    from scipy import ndimage
    return int(ndimage.label(np.asarray(shape)[..., 3] > thr)[1])


def test_old_chain_steps():
    print('2. шаги старой цепочки (решение Fable 27.11): main_object — за флагом, левый при равных; «хвосты у пола» — только счётчик «срезал бы»')
    pair = [(40, 60, 130, 200), (170, 70, 270, 200)]                   # два одинаковых по площади предмета рядом (пара стульев)
    photo, net = scene(pair)
    s0, _ = CO1.cut_shape(photo, net, role='стул')
    s1, i1 = CO1.cut_shape(photo, net, role='стул', steps=('main_object',))
    ok(ncomp(s0) == 2 and ncomp(s1) == 1 and i1.get('dual_object_trimmed') is True, f'пара стульев: без шага {ncomp(s0)} предмета, с шагом {ncomp(s1)} (dual_object_trimmed)')
    # равные площади (12 600 и 13 000 px, 0,97 ≥ EQUAL_SHARE) → ЛЕВЫЙ, хотя правый на 3 % больше; в записи — «взят один из двух, левый»
    left_px = int((np.asarray(s1)[..., 3][:, :150] > 40).sum())
    right_px = int((np.asarray(s1)[..., 3][:, 150:] > 40).sum())
    ok(left_px > 5000 and right_px == 0 and i1.get('picked') == 'left_of_two', f'равные пары → левый (слева {left_px} px, справа {right_px}), picked={i1.get("picked")}')
    s1b, i1b = CO1.cut_shape(photo, net, role='стул', steps=('main_object',))
    ok(np.array_equal(np.asarray(s1), np.asarray(s1b)) and i1['picked'] == i1b['picked'], 'два запуска подряд на одном входе — побайтно одна вырезка')
    mph, mnet = Image.fromarray(np.asarray(photo)[:, ::-1].copy()), Image.fromarray(np.asarray(net)[:, ::-1].copy(), 'RGBA')       # зеркало: теперь БОЛЬШИЙ стул слева
    sm, im = CO1.cut_shape(mph, mnet, role='стул', steps=('main_object',))
    ok(int((np.asarray(sm)[..., 3][:, :150] > 40).sum()) > 5000 and int((np.asarray(sm)[..., 3][:, 150:] > 40).sum()) == 0 and im.get('picked') == 'left_of_two',
       'зеркальная пара: опять левый (выбор не зависит от того, какой из двух чуть больше)')
    uph, unet = scene([(40, 60, 130, 200), (170, 120, 240, 200)])          # второй заметно меньше (доля ≈ 0,44 < EQUAL_SHARE) → больший (передний), не «левый»
    su, iu = CO1.cut_shape(uph, unet, role='стул', steps=('main_object',))
    ok(iu.get('picked') == 'larger_of_two' and int((np.asarray(su)[..., 3][:, 150:] > 40).sum()) == 0, f'разные площади → больший (picked={iu.get("picked")}, второй/первый={iu.get("second_share")})')
    ok(i1.get('chain') == {'version': CO.CHAIN_VERSION, 'steps': ['main_object']}, 'у входа формы в отчёте: версия цепочки и набор шагов')
    s2, _ = CO1.cut_shape(photo, net, role='стол обеденный', steps=('main_object',))
    ok(ncomp(s2) == 2, 'у другой роли (стол) шаг «главный предмет» не режет — одобрено владельцем только для стульев')
    try:
        CO1.cut_shape(photo, net, role='стул', steps=('attached_prune',))
        ok(False, 'шага attached_prune в модуле нет — отказ')
    except ValueError as e:
        ok('attached_prune' in str(e), 'шага «хвосты у пола» в модуле нет (steps=(attached_prune,) → ValueError с причиной)')
    ok(CO.STEPS_ALL == ('main_object',) and CO.CHAIN_VERSION == 'c2', 'допустим только шаг main_object; версия цепочки c2')

    sofa = [(90, 40, 230, 110)]                                        # тело дивана, под ним у пола — тонкая перемычка и обломок (тень/артефакт)
    photo, net = scene(sofa, bridge=(158, 110, 160, 132))
    arr = np.asarray(net).copy()
    arr[132:142, 148:172] = (118, 108, 100, 255)
    photo = Image.fromarray(arr[..., :3])
    net = Image.fromarray(arr, 'RGBA')

    def tail_px(sh):
        return int((np.asarray(sh)[132:142, 148:172, 3] > 128).sum())
    a0, ia = CO1.cut_shape(photo, net, role='диван')
    w = ia.get('attached_prune_would') or {}
    ok(tail_px(a0) > 100, f'хвост у пола дивана ОСТАЁТСЯ в маске (шаг убран): {tail_px(a0)} px')
    ok(w.get('applied') is False and w.get('pieces') == 1 and w.get('would_cut_px', 0) > 100, f'счётчик «срезал бы» считает хвост, а не молчит нулём: {w}')
    a0b, _ = CO1.cut_shape(photo, net, role='диван', steps=('main_object',))
    ok(np.array_equal(np.asarray(a0), np.asarray(a0b)), 'диван: шаг main_object (роль не «стул») и счётчик маску не меняют')
    b0, ib = CO1.cut_shape(photo, net, role='стол')
    wb = ib.get('attached_prune_would') or {}
    ok(tail_px(b0) > 100 and wb.get('would_cut_px') == 0 and wb.get('pieces') == 0, 'роль не из белого списка (стол): счётчик 0 — белый список внутри prune_attached сохранён, хвост остаётся')
    c0, ic = CO1.cut_shape(*scene([(90, 40, 230, 110)]), role='диван')
    wc = ic.get('attached_prune_would') or {}
    ok(wc.get('would_cut_px') == 0 and wc.get('mask_px', 0) > 5000 and 'skip' in wc, f'диван без хвоста: счётчик 0, поле есть (молчаливого «нет поля» нет): {wc}')
    ok(set(wc) >= {'applied', 'pieces', 'would_cut_px', 'blocked_px', 'skip', 'mask_px'}, 'счётчик «срезал бы»: все поля на месте')
    body0 = int((np.asarray(a0)[40:110, 90:230, 3] > 128).sum())
    ok(body0 > 8000, f'тело дивана цело ({body0} px)')
    try:
        CO1.cut_shape(photo, net, role='диван', steps=('teleport',))
        ok(False, 'неизвестный шаг отвергается')
    except ValueError:
        ok(True, 'неизвестный шаг отвергается (ValueError)')


def tiny_shape():
    a = np.zeros((20, 30, 4), np.uint8)
    a[5:15, 8:22] = (200, 50, 50, 255)
    return Image.fromarray(a, 'RGBA')


def test_origin():
    print('3. метка происхождения')
    shape = tiny_shape()
    raw = b'photo-bytes'
    o = CO.build(raw, ('main_object',), code='abc1234', shape=shape, pick='left_of_two')
    ok(CO.check(o) == [] and o['chain_version'] == CO.CHAIN_VERSION and o['method'] == 'cutout_one', 'свежая запись актуальна')
    ok(set(o) == set(CO.FIELDS), f'поля записи = {CO.FIELDS}')
    ok(o['photo_sha256'] == __import__('hashlib').sha256(raw).hexdigest() and o['pixels_sha256'] == CO.pixels_sha256(shape), 'хеш фото — от исходных байтов, хеш вырезки — от пикселей')
    other = CO.build(raw, (), code='abc1234', shape=shape.copy())
    ok(other['pixels_sha256'] == o['pixels_sha256'], 'хеш вырезки не зависит от шагов/даты/метки — только от пикселей')
    for name, mut in (('нет метки', None), ('старая версия цепочки', dict(o, chain_version='c0')), ('не тот способ', dict(o, method='cutout_sync')),
                      ('чужие веса', dict(o, mask=dict(o['mask'], revision='0' * 40))), ('чужой источник маски', dict(o, mask=dict(o['mask'], source='fal-light'))),
                      ('код неизвестен', dict(o, code='unknown')), ('нет хеша фото', {k: v for k, v in o.items() if k != 'photo_sha256'}),
                      ('плохой хеш вырезки', dict(o, pixels_sha256='x')), ('плохая дата', dict(o, created='вчера')), ('чужой шаг', dict(o, steps=['teleport']))):
        errs = CO.check(mut)
        ok(bool(errs) and all(isinstance(e, str) and e for e in errs), f'отказ: {name} → «{errs[0][:70] if errs else ""}»')
    ok(CO.check({}) != [] and CO.check('x') != [] and CO.check([]) != [], 'пустое / не словарь — отказ, не исключение')
    try:
        CO.build(raw, ('teleport',), shape=shape)
        ok(False, 'build: неизвестный шаг отвергается')
    except ValueError:
        ok(True, 'build: неизвестный шаг отвергается')

    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'a_1.rgba.png')
        data = CO.png_bytes(shape, o)
        open(p, 'wb').write(data)
        back = Image.open(p).convert('RGBA')
        ok(np.array_equal(np.asarray(back), np.asarray(shape)), 'метка в PNG пиксели не меняет')
        ok(CO.read_png(p) == o, 'метка читается из PNG и равна записи')
        import hashlib
        entry = {'origin': o, 'input_png_sha256': hashlib.sha256(data).hexdigest()}
        ok(CO.check_png(p, entry) == [], 'файл + запись inputs.json согласованы')
        ok(CO.inputs_errors({'a:1': entry}, ['a:1'], td) == [], 'inputs_errors: чисто')
        ok(CO.inputs_errors({'a:1': entry}, ['b:2'], td)[0].startswith('b:2'), 'нет записи товара — отказ с именем товара')
        ok(any('нет метки' in e for e in CO.inputs_errors({'a:1': {'input_png_sha256': 'x'}}, ['a:1'])), 'запись без origin (как у старых входов) — отказ «нет метки»')
        plain = os.path.join(td, 'b_2.rgba.png')
        shape.save(plain)
        ok(any('нет метки' in e for e in CO.check_png(plain)), 'PNG без метки — отказ')
        stale = CO.png_bytes(shape, dict(o, chain_version='c0'))
        open(os.path.join(td, 'c_3.rgba.png'), 'wb').write(stale)
        ok(any('версия цепочки' in e for e in CO.check_png(os.path.join(td, 'c_3.rgba.png'))), 'PNG со старой версией — отказ')
        ok(any('расходится' in e for e in CO.check_png(os.path.join(td, 'c_3.rgba.png'), {'origin': o})), 'метка в PNG ≠ origin в inputs.json — отказ')
        ok(any('подменён' in e for e in CO.check_png(p, dict(entry, input_png_sha256='0' * 64))), 'sha файла ≠ input_png_sha256 — отказ («подменён»)')
        e2 = {'a:1': dict(entry, origin=dict(o, chain_version='c0'))}
        ok(any('версия цепочки' in e for e in CO.inputs_errors(e2, ['a:1'], td)), 'inputs_errors: старая версия в inputs.json — отказ')
        # «проверка сломана / не смогла запуститься → говорит об этом» (урок дня 27.11): ни один из этих случаев не должен дать пустой список ошибок
        ok(any('нет в' in e for e in CO.inputs_errors({'z:9': entry}, ['z:9'], td)), 'нет файла вырезки рядом с inputs.json — отказ с причиной, не «чисто»')
        junk = os.path.join(td, 'd_4.rgba.png')
        open(junk, 'wb').write(b'not a png at all')
        ok(any('нет метки' in e for e in CO.check_png(junk)), 'файл не PNG — отказ «нет метки»')
        open(os.path.join(td, 'e_5.rgba.png'), 'wb').write(data[:len(data) // 2])
        ok(CO.check_png(os.path.join(td, 'e_5.rgba.png'), entry) != [], 'обрезанный PNG — отказ (метка или sha не сходятся)')
        ok(CO.check_png(os.path.join(td, 'нет-такого.png'), entry) != [], 'файла нет вовсе — отказ')
        ok(any('pick' in e for e in CO.check(dict(o, pick='right'))) and any('нет полей' in e for e in CO.check({k: v for k, v in o.items() if k != 'pick'})), 'метка: pick вне списка / без pick — отказ')
        ok(any('версия цепочки' in e for e in CO.check(dict(o, chain_version='c1'))), 'метка прежней версии c1 — отказ (результат для пар изменился)')
        for bad_origin in ('строка', 5, [], {}, {'format': 1}, dict(o, code='unknown'), dict(o, created='вчера'), dict(o, steps=['сам-придумал'])):
            ok(CO.check(bad_origin) != [], f'check({str(bad_origin)[:40]}): негодная метка — отказ с причиной')
        ok(CO.inputs_errors(None, ['a:1'], td) != [] and CO.inputs_errors({'a:1': 'x'}, ['a:1']) != [], 'inputs.json пустой/кривой — отказ')
    big = Image.new('RGBA', (4000, 3000), (1, 2, 3, 255))
    ok(CO.read_png.__doc__ is not None and len(CO.png_text(o)) < 1000, 'метка короткая (одна строка JSON)')
    del big
    ok(CO.code_version() == 'unknown' or len(CO.code_version()) >= 7, 'code_version: хеш коммита или «unknown» (без git)')


def test_make_input_uses_one_module():
    print('4. make_input: маска → цепочка → запись, одним вызовом')
    photo, net = scene([(60, 50, 260, 200)])
    buf = io.BytesIO()
    photo.save(buf, 'PNG')
    shape, cut, info, origin = CO1.make_input(buf.getvalue(), 'комод', net=net)
    ok(origin['pick'] == 'none', 'у комода шаг «главный предмет» не резал: pick=none')
    ok(CO.check(origin) == [] and origin['steps'] == sorted(CO.STEPS_ALL) and origin['pixels_sha256'] == CO.pixels_sha256(shape), 'запись актуальна, шаги — все, хеш вырезки = хеш shape')
    ok(info['chain']['version'] == CO.CHAIN_VERSION and cut.size[0] <= shape.size[0], 'отчёт несёт версию цепочки; обрезанная копия есть')
    pphoto, pnet = scene([(40, 60, 130, 200), (170, 70, 270, 200)])          # пара равных стульев → в запись входа формы идёт «взят один из двух, левый»
    pbuf = io.BytesIO()
    pphoto.save(pbuf, 'PNG')
    pshape, _, pinfo, porigin = CO1.make_input(pbuf.getvalue(), 'стул', net=pnet)
    ok(pinfo.get('picked') == 'left_of_two' and porigin['pick'] == 'left_of_two' and CO.check(porigin) == [] and porigin['steps'] == ['main_object'],
       f'пара стульев: в записи входа pick={porigin["pick"]!r} (взят один из двух, левый), запись актуальна')
    ok(porigin['pixels_sha256'] == CO.pixels_sha256(pshape) and porigin['pixels_sha256'] != origin['pixels_sha256'], 'хеш вырезки записи — от вырезки с выбранным стулом')


def test_make_inputs_script():
    print('5. salad/trellis/make_inputs.py: годный вход пишется с меткой; негодный — НЕ пишется, в inputs.json причина (отказ не молчит)')
    import importlib.util
    import json
    import tempfile
    import types
    spec = importlib.util.spec_from_file_location('make_inputs_under_test', os.path.join(HERE, 'trellis', 'make_inputs.py'))
    MI = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MI)
    import mesh_photo as MP
    import preprocess as PRE
    photo, net = scene([(60, 50, 260, 200)])
    buf = io.BytesIO()
    photo.save(buf, 'PNG')
    raw = buf.getvalue()
    good_shape, good_cut, good_info, good_origin = CO1.make_input(raw, 'комод', net=net)
    fake_cm = types.ModuleType('catalog_media')
    fake_cm.media = lambda mid, eid: {} if mid == '0' else {'img': 'http://x/p.png'}
    saved = (sys.modules.get('catalog_media'), PRE.fetch, CO1.make_input)
    sys.modules['catalog_media'] = fake_cm
    PRE.fetch = lambda url: raw
    cur = {}

    def fake_make(raw_, role, steps=CO.STEPS_ALL, net=None):
        if cur.get('raise'):
            raise RuntimeError('сеть упала')
        return good_shape, good_cut, dict(good_info, **cur.get('info', {})), good_origin
    CO1.make_input = fake_make
    old_rules = MP.load_rules
    MP.load_rules = lambda *a, **k: {'min_cut_side_px': 10, 'measure': 'min'}      # размер синтетики не должен мешать остальным случаям
    try:
        with tempfile.TemporaryDirectory() as td:
            def run(sku, **c):
                cur.clear()
                cur.update(c)
                out = os.path.join(td, sku.replace(':', '_') + '-out')
                old_argv = sys.argv
                sys.argv = ['make_inputs.py', '--out', out, '--role', 'комод', sku]
                try:
                    with __import__('contextlib').redirect_stdout(io.StringIO()):
                        rc = MI.main()
                finally:
                    sys.argv = old_argv
                return rc, out, json.load(open(os.path.join(out, 'inputs.json'), encoding='utf-8'))[sku]
            rc, out, e = run('1:1')
            png = os.path.join(out, '1_1.rgba.png')
            ok(rc == 0 and 'error' not in e and CO.check(e['origin']) == [] and os.path.exists(png) and CO.check_png(png, e) == [],
               'годный товар: вход записан, метка в inputs.json и в PNG, sha файла сходится')
            rc, out, e = run('0:2')
            ok('error' in e and not os.path.exists(os.path.join(out, '0_2.rgba.png')), 'нет адреса фото — error в inputs.json, файл не записан')
            rc, out, e = run('1:3', **{'raise': True})
            ok('RuntimeError' in e.get('error', '') and not os.path.exists(os.path.join(out, '1_3.rgba.png')), 'исключение вырезки — error с причиной, файл не записан')
            rc, out, e = run('1:4', info={'hybrid_error': 'ValueError: гибрид упал'})
            ok('гибрид' in e.get('error', '') and not os.path.exists(os.path.join(out, '1_4.rgba.png')), 'сбой гибридной маски — отказ с причиной, файл не записан')
            rc, out, e = run('1:5', info={'verdict': 'bad', 'reason': 'коллаж'})
            ok('коллаж' in e.get('error', '') and not os.path.exists(os.path.join(out, '1_5.rgba.png')), 'маска не годна — отказ с причиной, файл не записан')
            MP.load_rules = lambda *a, **k: {'min_cut_side_px': 10 ** 6, 'measure': 'min'}
            rc, out, e = run('1:6')
            ok('размера' in e.get('error', '') and not os.path.exists(os.path.join(out, '1_6.rgba.png')), 'вырезка мельче правила размера — отказ с причиной, файл не записан')
    finally:
        if saved[0] is None:
            sys.modules.pop('catalog_media', None)
        else:
            sys.modules['catalog_media'] = saved[0]
        PRE.fetch, CO1.make_input = saved[1], saved[2]
        MP.load_rules = old_rules


def test_night_report_field():
    print('6. отчёт ночной оценки несёт счётчик attached_prune_would и от него ничего не ломается (замечание Fable 27.11, п.3)')
    import photo_fit
    CS = cs_module()
    sofa = [(90, 40, 230, 110)]
    photo, net = scene(sofa, bridge=(158, 110, 160, 132))
    arr = np.asarray(net).copy()
    arr[132:142, 148:172] = (118, 108, 100, 255)
    photo, net = Image.fromarray(arr[..., :3]), Image.fromarray(arr, 'RGBA')
    if CS is not None:
        _, info = CS.chain(photo, net, role='диван')           # ровно то, что ночной `cutout_sync.one` кладёт в photo_assessment.metrics
    else:
        _, _, info = CO1.chain_cut(photo, net, role='диван')
    w = info.get('attached_prune_would')
    ok(isinstance(w, dict) and w.get('applied') is False and w.get('would_cut_px', 0) > 100, f'поле есть в отчёте ночной оценки и считает: {w}')
    back = json.loads(json.dumps(info, ensure_ascii=False))           # ночь пишет отчёт в jsonb через json.dumps — поле обязано пройти туда и обратно
    ok(back.get('attached_prune_would') == w, 'поле проходит json.dumps → loads без потерь (jsonb)')
    stripped = {k: v for k, v in info.items() if k != 'attached_prune_would'}
    ok(photo_fit.verdict_from_metrics('диван', info) == photo_fit.verdict_from_metrics('диван', stripped),
       'вердикт `verdict_from_metrics` с полем и без него один и тот же (читатель отчёта поле не замечает)')
    ok(info.get('photo') and 'object_wh' in info['photo'], 'остальные поля, которые читают потребители (photo.object_wh), на месте')
    # −контроль: читатель, который бы ломался на лишнем поле, был бы пойман этой же проверкой
    bad_reader = lambda m: [m[k] for k in sorted(m) if not isinstance(m[k], (dict, list, str, int, float, bool, type(None)))]  # noqa: E731
    ok(bad_reader(info) == [], 'в отчёте только json-типы (нет numpy/Image-значений)')
    ok(bad_reader(dict(info, evil=np.float32(1))) != [], '−контроль: numpy-значение в отчёте проверка ловит')
    src = open(os.path.join(HERE, 'trellis', 'make_inputs.py'), encoding='utf-8').read()

    def hd_first(s):
        return 'm.get(\'img_hd\') or m.get(\'img\')' in s and s.index('img_hd') < s.index("m.get('img')")
    ok(hd_first(src) and 'ВЫСОКОГО разрешения' in src, 'вход формы: адрес фото высокого разрешения (img_hd) берётся первым, и это названо в описании')
    ok('хвосты у пола» и «главный' not in src.split('Раньше здесь')[0], 'в описании сборки входа нет устаревшего «два шага старой цепочки: хвосты у пола…»')
    ok('хвосты у пола» и «главный' in 'два шага старой цепочки: «хвосты у пола» и «главный предмет»', '−контроль: старую формулировку проверка видит')
    ok(not hd_first(src.replace("m.get('img_hd') or m.get('img')", "m.get('img') or m.get('img_hd')")), '−контроль: порядок img → img_hd проверка ловит')


if __name__ == '__main__':
    test_frozen()
    test_wrapper_is_thin()
    test_old_chain_steps()
    test_origin()
    test_make_input_uses_one_module()
    test_make_inputs_script()
    test_night_report_field()
    print(f'tests_cutout_one: ошибок {len(bad)}')
    sys.exit(1 if bad else 0)
