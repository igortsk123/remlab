"""КЛЮЧ КАДРА ПО КОМНАТЕ — ТЕСТ-МАТРИЦА МУТАЦИЙ (T-20261118-04/16/1, план `render-key-01`): правка поля комнаты меняет ключ ровно её комнаты, правка файла — ровно потребителей,
лишний файл (растение/материал/меш, которых сцена не берёт) и правила экрана (photo-pick, quiz, swap, цены, метка выкладки) — ни одного ключа, программа и пресет — все.
Сторож чтений: все чтения дампера внутри входа; нарочно добавленное чтение, сеть, другой файл — красные.
Без Blender и браузера:  python tools/scout/tests/test_render_input.py            (синтетика: 4 варианта в 2 комнатах, временные папки)
На живых 16 вариантах (pakardev):  python tools/scout/tests/test_render_input.py --live [папка с <вариант>/dump/reads.json]"""
import copy
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver')]
LIVE = '--live' in sys.argv
fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


def w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def wj(path, obj):
    w(path, json.dumps(obj, ensure_ascii=False))


# ——— временный мир: «репозиторий» с кодом и каталогами, диски мешей/картинок/окружения
TMP = tempfile.mkdtemp(prefix='rkey-')
REPO, PUB, MC, GAL, DEMO = (os.path.join(TMP, n) for n in ('repo', 'public', 'mcache', 'gallery', 'demo'))
if not LIVE:
    os.environ.update(RENDER_INPUT_REPO=REPO, SCENE_INPUTS_PUBLIC=PUB, SCENE3D_CACHE=MC, SCENE_INPUTS_GALLERY=GAL, DEMO_LOCAL_DIR=DEMO,
                      SCENE_INPUTS_INDEX=os.path.join(TMP, 'idx', 'i.json'), SCENE_INPUTS_ORIENT=os.path.join(TMP, 'orient.json'), RENDER_ORIENT_FETCH='0')
import render_exec as RX  # noqa: E402
import render_input as RI  # noqa: E402
import render_snapshot as RS  # noqa: E402
import scene_inputs as SI  # noqa: E402

if not LIVE:
    PLANTS = {'rev': '6', 'base': '/flat3d/plants/', 'hosts': {'кашпо': 'green', 'ваза': 'dry'}, 'fit': {'green': {'floor': {'k': 1}}},
              'plants': [{'id': 'pA', 'kind': 'green', 'styles': ['any'], 'mounts': ['floor']}, {'id': 'pB', 'kind': 'dry', 'styles': ['scandi']},
                         {'id': 'pC', 'kind': 'dry', 'styles': ['japandi']}, {'id': 'pD', 'kind': 'green', 'styles': ['any']}]}
    MATS = {'baseUrl': '/flat3d/materials/', '_seal': 'x', 'materials': [
        {'id': 'finish-wall', 'baseColorUrl': 'fw.webp', 'baseColorLiteUrl': 'fw-lite.webp'}, {'id': 'finish-floor', 'baseColorUrl': 'ff.webp'},
        {'id': 'finish-accent-brick', 'baseColorUrl': 'fb.webp'}, {'id': 'carpet-grey', 'baseColorUrl': 'cg.webp'}]}
    ORIENT = {sid: {'yaw': 90.0, 'status': 'auto_resolved', 'png': sid + '.png'} for sid in ('s1', 's2', 'b1', 'b2', 'vase1', 'lamp9', 'cand', 'other-sid')}
    wj(os.path.join(TMP, 'orient.json'), ORIENT)
    wj(os.path.join(REPO, 'data/flat3d/plants.json'), PLANTS)
    wj(os.path.join(REPO, 'data/flat3d/materials.json'), MATS)
    wj(os.path.join(REPO, 'data/flat3d/finish-cc0.json'), {'surfaces': {'wall': {'id': 'finish-wall'}, 'floor': {'id': 'finish-floor'}, 'accent-brick': {'id': 'finish-accent-brick'}},
                                                          'accentWalls': {'styles': {'лофт': 'accent-brick'}}})
    wj(os.path.join(REPO, 'data/flat3d/runtime-meshes.json'), {'meshes': {}})
    wj(os.path.join(REPO, 'data/flat3d/light-rules.json'), {'k': 1})
    w(os.path.join(REPO, 'lib/viewer3d/a.ts'), 'export const a = 1')
    w(os.path.join(REPO, 'lib/viewer3d/scene-export.ts'), 'export const SCENE_EXPORT_VERSION = 1')
    w(os.path.join(REPO, 'lib/configurator/b.ts'), 'export const b = 1')
    P = os.path.join(REPO, 'tools/scout/cycles_probe')
    for n in ('demo_scene_entry.ts', 'build_entry.mjs', 'demo_scene_dump.mjs', 'file_sig.mjs', 'render_cycles.py', 'export_server.py'):
        w(os.path.join(P, n), '# ' + n)
    w(os.path.join(P, 'export_scene.py'), 'import helper\nfrom pkg import mod\n\ndef f():\n    import lazy\n')
    w(os.path.join(REPO, 'tools/scout/helper.py'), 'x = 1')
    w(os.path.join(REPO, 'tools/scout/lazy.py'), 'y = 1')
    w(os.path.join(REPO, 'tools/scout/pkg/__init__.py'), '')
    w(os.path.join(REPO, 'tools/scout/pkg/mod.py'), 'z = 1')
    w(os.path.join(REPO, 'tools/scout/unrelated.py'), 'u = 1')
    for f in ('env/outside.webp', 'scene/views/yard.webp', 'scene/views/park.webp', 'scene/views/city-day.webp'):
        w(os.path.join(PUB, 'flat3d' if f.startswith('env') else '', f), 'png-' + f)
    for f in ('fw.webp', 'fw-lite.webp', 'ff.webp', 'fb.webp', 'cg.webp'):
        w(os.path.join(PUB, 'flat3d/materials', f), 'm-' + f)
    for p in ('pA', 'pB', 'pC', 'pD'):
        w(os.path.join(PUB, 'flat3d/plants', p + '.glb'), 'glb-' + p)
    for sid in ('s1', 's2', 'b1', 'b2', 'vase1', 'lamp9', 'cand'):
        w(os.path.join(MC, sid + '.glb'), b'GLB' + sid.encode() * 1200)
    for im in ('rug1.jpg', 'rug2.jpg', 'sofa1.jpg', 'art1.jpg'):
        w(os.path.join(DEMO, 'img', im), 'jpg-' + im)

    def sku(sid, **kw):
        return {'sid': sid, 'msid': sid, 'name': 'Товар ' + sid, 'price': 1000, 'url': 'https://x/' + sid, 'shop': 'shop', 'name_en': 'Item ' + sid,
                'w': 100, 'd': 50, 'h': 80, 'img': 'img/sofa1.jpg', **kw}

    def item(role, sid, x, y, **kw):
        return {'role': role, 'x': x, 'y': y, 'rot': 0, 'w': 100, 'd': 50, 'h': 80, 'dims_src': 'каталог', 'corner': False, 'corner_left': False, 'section': None,
                'sku': sku(sid, **kw)}
    cams = [{'name': 'C1', 'x': 50, 'y': 40, 'rot': 105, 'fov': 90, 'pose': 3, 'pshift': -0.04, 'crop': {'x': 1}}, {'name': 'C2', 'x': 400, 'y': 280, 'rot': -69, 'fov': 90}]

    def variant(vid, room, style, style_id, items, decor):
        return {'id': vid, 'title': 'T ' + vid, 'style': style, 'style_id': style_id, 'room_id': room, 'fill_pct': 20.0, 'cams': copy.deepcopy(cams), 'cam_level': 0,
                'items': items, 'decor': decor, 'purpose': 'couple'}
    rug = item('ковёр', 's1', 200, 150, img='img/rug1.jpg')
    vase = {'role': 'ваза', 'strategy': 'hunyuan3d', 'sku': sku('vase1'), 'place': {'x': 10, 'y': 10}}
    cur = {'role': 'шторы', 'strategy': 'textile_abstract', 'sku': sku('lamp9', img_art='img/art1.jpg'), 'place': {'x': 0, 'y': 5, 'kind': 'curtain'}, 'look': {'hex': '#aabbcc'}}
    DATA = {'apartment_id': 'a1', 'build': 'git1.rules1', 'room': {'w': 439, 'd': 325, 'title': 'Гостиная'}, 'rules': {'soft_roles': ['плед'], 'photo_pick': 1},
            'rooms_geo': {'living': {'w': 439, 'd': 325, 'title': 'Гостиная', 'height_cm': 270, 'window_view': 'yard', 'openings': [{'kind': 'window', 'wall': 'west'}], 'radiators': [],
                                     'finish': {'wall': {'id': 'paint-white', 'colorHex': '#f2f0ed'}}, 'fixtures_ir': [], 'openings_ir': []},
                          'bedroom-1': {'w': 597, 'd': 293, 'title': 'Спальня', 'window_view': 'park', 'openings': [], 'radiators': [], 'finish': {}}},
            'variants': [variant('v1', 'living', 'сканди', 'scandi', [item('диван', 's1', 220, 270), rug], [vase, cur]),
                         variant('v2', 'living', 'лофт', 'loft', [item('диван', 's2', 220, 270)], []),
                         variant('v3', 'bedroom-1', 'сканди', 'scandi', [item('кровать', 'b1', 298, 106)], [copy.deepcopy(vase)]),
                         variant('v4', 'bedroom-1', 'лофт', 'loft', [item('кровать', 'b2', 298, 106)], [])]}
    HOSTS_PLANTS = {'v1': {'pB'}, 'v3': {'pB'}}          # кандидаты растений-ваз по стилю «сканди»; у v2/v4 носителей нет
else:
    DATA = json.load(open(os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json'), encoding='utf-8'))

VIDS = [v['id'] for v in DATA['variants']]
ROOM_OF = {v['id']: v.get('room_id') or 'living' for v in DATA['variants']}
RD, PD = 'r' * 64, 'p' * 64


def snaps(data):
    return {vid: RS.canonicalize(data, {'v': 1, 'variant_id': vid}) for vid in VIDS}


def digests(data):
    return {vid: s['scene_digest'] for vid, s in snaps(data).items()}


def keys(data, rd=RD, pd=PD):
    return {vid: RI.frame_key(d, rd, pd) for vid, d in digests(data).items()}


def diff(a, b):
    return {k for k in a if a[k] != b[k]}


def mut(fn):
    d = copy.deepcopy(DATA)
    fn(d)
    return d


BASE = snaps(DATA)
K0 = {vid: RI.frame_key(s['scene_digest'], RD, PD) for vid, s in BASE.items()}
check(f'база: {len(VIDS)} вариантов — {len(set(K0.values()))} разных ключей', len(set(K0.values())) == len(VIDS))
check('ключ — 32 hex (адреса кадров прежней длины), digest — 64 hex', all(len(k) == 32 for k in K0.values()) and all(len(s['scene_digest']) == 64 for s in BASE.values()))
check('база: все файлы сцены на месте (missing пусто)', all(not s['frame_inputs']['missing'] for s in BASE.values()))
check('повтор того же снимка — тот же ключ', keys(DATA) == K0)
check('выключатель: `scene_hash` прежний (с меткой выкладки), `scene_digest` рядом', all(s['scene_hash'] == s['legacy_hash'] != s['scene_digest'] for s in BASE.values()) or RI.v2_on())

# ——— 1) поля комнаты: ровно её ключи
rooms = sorted(set(ROOM_OF.values()))
R0 = rooms[0]
users = lambda room: {v for v in VIDS if ROOM_OF[v] == room}  # noqa: E731
for field, val in (('height_cm', 999), ('openings', [{'kind': 'window', 'wall': 'north', 'offset_cm': 1}]), ('radiators', [{'wall': 'east'}]), ('window_view', 'zzz'),
                   ('finish', {'wall': {'id': 'x', 'colorHex': '#000000'}}), ('fixtures_ir', [{'k': 1}]), ('openings_ir', [{'k': 2}]), ('w', 777)):
    if field == 'window_view':
        continue                                      # вид — отдельным случаем ниже (файл вида)
    ch = diff(K0, keys(mut(lambda d, f=field, v=val: d['rooms_geo'][R0].__setitem__(f, v))))
    check(f'поле комнаты «{field}» ({R0}) меняет ключи ровно этой комнаты', ch == users(R0))
check('название комнаты (title) ключ не меняет', not diff(K0, keys(mut(lambda d: d['rooms_geo'][R0].__setitem__('title', 'Другое')))))

# ——— 2) предметы, декор, камеры
v0 = DATA['variants'][0]['id']
ch = diff(K0, keys(mut(lambda d: d['variants'][0]['items'][0].__setitem__('x', d['variants'][0]['items'][0]['x'] + 5))))
check('сдвиг предмета — только его вариант', ch == {v0})
ch = diff(K0, keys(mut(lambda d: d['variants'][0]['cams'][0].__setitem__('rot', 1.5))))
check('поза камеры — только её вариант', ch == {v0})
ch = diff(K0, keys(mut(lambda d: d['variants'][0]['items'][0]['sku'].__setitem__('tint', [1.2, 1.0, 0.9]))))
check('подкраска товара — только его вариант', ch == {v0})
ch = diff(K0, keys(mut(lambda d: d['variants'][0]['items'][0]['sku'].__setitem__('swatch', '#112233'))))
check('образец ткани — только его вариант', ch == {v0})
ch = diff(K0, keys(mut(lambda d: d['variants'][0].__setitem__('style', 'минимализм'))))
check('стиль варианта — только его вариант', ch == {v0})
ch = diff(K0, keys(mut(lambda d: d['variants'][0]['decor'][0].__setitem__('place', {'x': 99, 'y': 9}))))
check('место декора — только его вариант', ch == {v0})

# ——— 3) правила экрана, цены, метка выкладки — ни одного ключа
def screen_only(d):
    d['build'] = 'gitNEW.rulesNEW'
    d['rules']['photo_pick'] = 2
    d['rules']['quiz'] = {'a': 1}
    d['rules']['tariffs'] = {'b': 2}
    d['quiz'] = {'x': 1}
    d['feeds'] = {'ковёр': [1]}
    d['apartment_id'] = 'zzz'
    for v in d['variants']:
        v['fill_pct'] = 1.0
        v['title'] = 'Другое имя'
        v['purpose'] = 'family'
        v['cam_level'] = 3
        v['id_alias'] = 1
        for it in v['items'] + v['decor']:
            s = it['sku']
            s.update(price=1, price_at='2030-01-01', url='https://other', shop='other', name_en='other', basis='x')
check('правила экрана, цены, ссылки, метка выкладки, название варианта — НИ ОДНОГО ключа', not diff(K0, keys(mut(screen_only))))

# ——— 4) файлы: ассет меняет только потребителей
def consumers(logical):
    return {vid for vid, s in BASE.items() if any(a['logical'] == logical for a in s['frame_inputs']['assets'])}


def poke(path_fn, tag='x'):
    """подменить содержимое файла (в тесте — настоящий файл во временной папке; на живых данных — подмена хеша, файлы не трогаем)"""
    if LIVE:
        orig = SI.full_sha
        SI.full_sha = lambda p, o=orig: o(p) + ('+' + tag if p == path_fn else '')
        try:
            return keys(DATA)
        finally:
            SI.full_sha = orig
    with open(path_fn, 'ab') as f:
        f.write(b'-' + tag.encode())
    SI._FULL_MEMO.clear()
    try:
        return keys(DATA)
    finally:
        with open(path_fn, 'rb') as f:
            b = f.read()
        with open(path_fn, 'wb') as f:
            f.write(b[:-len(tag) - 1])
        SI._FULL_MEMO.clear()


def path_of(logical):
    kind, name = logical.split(':', 1)
    return {'mesh': lambda: SI.mesh_file(name), 'img': lambda: SI.img_file(name), 'env': lambda: SI.public_file('flat3d/env/outside.webp'),
            'view': lambda: SI.public_file(f'scene/views/{name}.webp'), 'material': lambda: SI.public_file('flat3d/materials/' + name),
            'plant': lambda: SI.public_file(f'flat3d/plants/{name}.glb')}[kind]()


all_logical = sorted({a['logical'] for s in BASE.values() for a in s['frame_inputs']['assets'] if a['kind'] in ('mesh', 'img', 'env', 'view', 'material-map', 'plant')})
bad_rows = []
for lg in all_logical:
    lgk = lg.replace('material-map', 'material')
    p = path_of(lgk if not lg.startswith('material') else lg)
    if not p:
        bad_rows.append(f'{lg}: файла нет')
        continue
    ch = diff(K0, poke(p))
    if ch != consumers(lg):
        bad_rows.append(f'{lg}: изменились {sorted(ch)}, потребители {sorted(consumers(lg))}')
check(f'правка каждого из {len(all_logical)} файлов сцены меняет ключи ровно его потребителей', not bad_rows)
for r in bad_rows[:6]:
    print('   ', r)
check('общее окружение (outside.webp) — все комнаты', consumers('env:outside') == set(VIDS))
check('вид за окном — только комнаты с этим видом', all(consumers(f'view:{v}') == {x for x in VIDS if (DATA['rooms_geo'].get(ROOM_OF[x]) or DATA['room']).get('window_view') == v}
                                                  for v in {(DATA['rooms_geo'].get(r) or {}).get('window_view') for r in rooms} if v))

# лишние файлы: ни одного ключа
if not LIVE:
    w(os.path.join(MC, 'unused-sid.glb'), b'GLB' * 500)
    w(os.path.join(DEMO, 'img/unused.jpg'), 'u')
    w(os.path.join(PUB, 'flat3d/plants/unusedX.glb'), 'u')
    w(os.path.join(PUB, 'flat3d/materials/unused.webp'), 'u')
    w(os.path.join(PUB, 'scene/views/city-day.webp'), 'changed-view-not-used')
    SI._FULL_MEMO.clear()
    check('лишние файлы (меш, фото, растение, материал, чужой вид) — НИ ОДНОГО ключа', not diff(K0, keys(DATA)))
    # растения: кандидаты по типу и стилю
    ch = diff(K0, poke(os.path.join(PUB, 'flat3d/plants/pC.glb')))
    check('растение другого стиля (japandi) — ни одного ключа у «сканди»', not ch)
    ch = diff(K0, poke(os.path.join(PUB, 'flat3d/plants/pB.glb')))
    check('растение-кандидат ваз «сканди» — только комнаты с вазой этого стиля', ch == {'v1', 'v3'})
    ch = diff(K0, poke(os.path.join(PUB, 'flat3d/plants/pD.glb')))
    check('кашпо-растение, а носителей-кашпо нет — ни одного ключа', not ch)
    # запись растения и каталоги
    d = mut(lambda dd: None)
    pl = json.load(open(os.path.join(REPO, 'data/flat3d/plants.json')))
    pl['plants'][1]['minThroatCm'] = 7
    wj(os.path.join(REPO, 'data/flat3d/plants.json'), pl)
    ch = diff(K0, keys(DATA))
    check('запись растения-кандидата (json) — только его потребители', ch == {'v1', 'v3'})
    renderer_before = RI.renderer_digest('b')
    wj(os.path.join(REPO, 'data/flat3d/plants.json'), PLANTS)
    mats = copy.deepcopy(MATS)
    mats['materials'][0]['roughness'] = 0.5
    wj(os.path.join(REPO, 'data/flat3d/materials.json'), mats)
    ch = diff(K0, keys(DATA))
    check('запись отделки finish-wall — все комнаты (стены у всех), но не «программа»', ch == set(VIDS))
    mats = copy.deepcopy(MATS)
    mats['materials'][2]['roughness'] = 0.5
    wj(os.path.join(REPO, 'data/flat3d/materials.json'), mats)
    ch = diff(K0, keys(DATA))
    check('запись акцентной стены (кирпич) — только варианты «лофт»', ch == {'v2', 'v4'})
    wj(os.path.join(REPO, 'data/flat3d/materials.json'), MATS)
    # недекларированный файл рядом с растениями другого вида не появляется в ассетах
    check('нет «пустого» хеша: у объявленных файлов sha256 — 64 hex', all(len(a['sha256']) == 64 for s in BASE.values() for a in s['frame_inputs']['assets']))
    # отсутствие файла
    os.rename(os.path.join(MC, 's1.glb'), os.path.join(MC, 's1.glb.off'))
    sn = RS.canonicalize(DATA, {'v': 1, 'variant_id': 'v1'})
    check('нет меша на диске — в `missing`, а не пустой хеш', 'mesh:s1' in sn['frame_inputs']['missing'])
    v2 = {'space': RI.SPACE, 'renderer_digest': RD, 'preset_digest': PD}
    try:
        RX.frame_key_of(sn, v2)
        check('v2: нет файла сцены — ключ не считаем (RenderError inputs_missing)', False)
    except RX.RenderError as e:
        check('v2: нет файла сцены — ключ не считаем (RenderError inputs_missing)', e.code == 'inputs_missing')
    os.rename(os.path.join(MC, 's1.glb.off'), os.path.join(MC, 's1.glb'))

# ——— 4б) Python-выгрузчик: разворот мешей закреплён в сцене, фактура пола — актив комнаты (T-20261118-04/17/1)
def set_orient(fn):
    """подменить таблицу разворота: синтетика — файл таблицы, живые данные — подмена `SI.orient_table`"""
    if LIVE:
        base_t = SI.orient_table()
        t = copy.deepcopy(base_t)
        fn(t)
        orig = SI.orient_table
        SI.orient_table = lambda fetch=True: t
        return orig
    t = json.load(open(os.path.join(TMP, 'orient.json')))
    fn(t)
    wj(os.path.join(TMP, 'orient.json'), t)
    SI._ORIENT.update(t=0.0, data=None)
    return None


def restore_orient(orig):
    if LIVE:
        SI.orient_table = orig
    else:
        wj(os.path.join(TMP, 'orient.json'), ORIENT)
        SI._ORIENT.update(t=0.0, data=None)


def mesh_consumers_of(sid):
    return {vid for vid, sn in BASE.items() if any(a['logical'] == f'mesh:{sid}' for a in sn['frame_inputs']['assets'])}


sids_all = sorted({a['logical'][5:] for sn in BASE.values() for a in sn['frame_inputs']['assets'] if a['kind'] == 'mesh'})
bad_rows = []
for sid in sids_all:
    o = set_orient(lambda t, sid=sid: t.__setitem__(sid, dict(t.get(sid) or {}, yaw=(float((t.get(sid) or {}).get('yaw') or 0) + 45.0))))
    try:
        ch = diff(K0, keys(DATA))
    finally:
        restore_orient(o)
    if ch != mesh_consumers_of(sid):
        bad_rows.append(f'{sid}: изменились {sorted(ch)}, потребители меша {sorted(mesh_consumers_of(sid))}')
check(f'правка записи разворота (orient.json) каждого из {len(sids_all)} мешей меняет ключи ровно комнат с этим мешем', not bad_rows and bool(sids_all))
for r in bad_rows[:6]:
    print('   ', r)
o = set_orient(lambda t: t.__setitem__('sid-ne-iz-komnat', {'yaw': 1.0}))
try:
    check('запись разворота меша, которого нет ни в одной комнате, — НИ ОДНОГО ключа', not diff(K0, keys(DATA)))
finally:
    restore_orient(o)
check('закреплённые записи лежат в сцене: по одной на меш комнаты', all(set((sn['frame_inputs']['scene'].get('orient') or {})) == {a['logical'][5:] for a in sn['frame_inputs']['assets'] if a['kind'] == 'mesh'}
                                                                  for sn in BASE.values()))
if not LIVE:
    os.rename(os.path.join(TMP, 'orient.json'), os.path.join(TMP, 'orient.json.off'))
    SI._ORIENT.update(t=0.0, data=None)
    sn = RS.canonicalize(DATA, {'v': 1, 'variant_id': 'v1'})
    check('нет таблицы разворота вообще — `orient:table` в `missing` (раньше молча «разворотов нет»)', 'orient:table' in sn['frame_inputs']['missing'])
    os.rename(os.path.join(TMP, 'orient.json.off'), os.path.join(TMP, 'orient.json'))
    SI._ORIENT.update(t=0.0, data=None)
    # фактура пола ночной сборки (room.finish.floor.tex.src) — актив комнаты
    w(os.path.join(PUB, 'flat3d/materials/ff2.webp'), 'floor-two')
    fl = mut(lambda d: d['rooms_geo']['living']['finish'].__setitem__('floor', {'id': 'f2', 'tex': {'src': 'ff2.webp', 'tile': [60, 60]}}))
    SI._FULL_MEMO.clear()
    sf = RS.canonicalize(fl, {'v': 1, 'variant_id': 'v1'})
    check('фактура пола комнаты (`finish.floor.tex.src`) — актив `material:ff2.webp`', any(a['logical'] == 'material:ff2.webp' and a['sha256'] for a in sf['frame_inputs']['assets']))
    k_a = keys(fl)
    with open(os.path.join(PUB, 'flat3d/materials/ff2.webp'), 'ab') as f:
        f.write(b'-edit')
    SI._FULL_MEMO.clear()
    k_b = keys(fl)
    check('правка файла фактуры пола — только комнаты с этой фактурой (гостиная: v1, v2)', diff(k_a, k_b) == {'v1', 'v2'})
    os.remove(os.path.join(PUB, 'flat3d/materials/ff2.webp'))
    SI._FULL_MEMO.clear()
    sf = RS.canonicalize(fl, {'v': 1, 'variant_id': 'v1'})
    check('нет файла фактуры пола — в `missing`', 'material:ff2.webp' in sf['frame_inputs']['missing'])
    check('невалидное имя фактуры (путь наружу) — не актив и не чтение', 'material:..' not in {a['logical'] for a in RS.canonicalize(
        mut(lambda d: d['rooms_geo']['living']['finish'].__setitem__('floor', {'tex': {'src': '../x.webp'}})), {'v': 1, 'variant_id': 'v1'})['frame_inputs']['assets']})

# ——— 5) программа и пресет — все ключи; код вне замыкания — никого
v2 = {'space': RI.SPACE, 'renderer_digest': RD, 'preset_digest': PD}
sn0 = BASE[VIDS[0]]
k_a = RX.frame_key_of(sn0, v2)
check('frame_key_of (v2) = frame_key(scene_digest, программа, пресет)', k_a == K0[VIDS[0]])
check('другая программа — другой ключ у всех', all(RI.frame_key(s['scene_digest'], 'q' * 64, PD) != K0[v] for v, s in BASE.items()))
check('другой пресет — другой ключ у всех', all(RI.frame_key(s['scene_digest'], RD, 'q' * 64) != K0[v] for v, s in BASE.items()))
check('прежний ключ (без space) не тронут: cache_key по scene_hash и версиям', RX.cache_key('h', {'a': 1}) == RX.cache_key('h', {'a': 1}) != RX.cache_key('h2', {'a': 1}))
preset = RX.preset()
check('пресет: `_doc`, `limits`, `min_gb` ключ не меняют', RI.preset_digest(preset) == RI.preset_digest({**preset, '_doc': 'другой текст', 'limits': {'exportSec': 1}, 'min_gb': 99}))
check('пресет: флаги, сэмплы, качество — меняют', all(RI.preset_digest(preset) != RI.preset_digest({**preset, k: v}) for k, v in (('samples', 1), ('flags', ['--x']), ('jpegQuality', 1), ('pct', 1))))

if not LIVE:
    RI.clear_memo()
    r0 = RI.renderer_digest('b')
    ps = RI.renderer_parts('b')
    check(f'программа: замыкание Python-импортов выгрузчика ({ps["n_py"]} файлов) и JS ({ps["n_js"]})', ps['n_py'] >= 5 and ps['n_js'] >= 8)

    def renderer_changes(path, content, name):
        old = open(path, 'rb').read() if os.path.exists(path) else None
        w(path, content)
        SI._FULL_MEMO.clear()
        RI.clear_memo()
        changed = RI.renderer_digest('b') != r0
        if old is None:
            os.remove(path)
        else:
            w(path, old)
        SI._FULL_MEMO.clear()
        RI.clear_memo()
        return changed
    S = os.path.join(REPO, 'tools/scout')
    check('программа: правка выгрузчика (export_scene.py) — меняет у всех', renderer_changes(os.path.join(S, 'cycles_probe/export_scene.py'), 'import helper\nfrom pkg import mod\n# правка\n', 'e'))
    check('программа: правка импортируемого модуля (helper.py) — меняет', renderer_changes(os.path.join(S, 'helper.py'), 'x = 2', 'h'))
    check('программа: правка модуля из пакета (pkg/mod.py) — меняет', renderer_changes(os.path.join(S, 'pkg/mod.py'), 'z = 2', 'm'))
    check('программа: правка отложенного импорта внутри функции (lazy.py) — меняет', renderer_changes(os.path.join(S, 'lazy.py'), 'y = 2', 'l'))
    check('программа: правка постороннего модуля (unrelated.py) — НЕ меняет', not renderer_changes(os.path.join(S, 'unrelated.py'), 'u = 2', 'u'))
    check('программа: правка JS движка (lib/viewer3d/a.ts) — меняет', renderer_changes(os.path.join(REPO, 'lib/viewer3d/a.ts'), 'export const a = 2', 'a'))
    check('программа: правка общих правил (data/flat3d/light-rules.json) — меняет', renderer_changes(os.path.join(REPO, 'data/flat3d/light-rules.json'), '{"k": 2}', 'l'))
    check('программа: правка данных, что читает Python-выгрузчик (rules/asset-strategies.json, occupancy.json), — меняет у всех',
          renderer_changes(os.path.join(REPO, RI.PROGRAM_DATA[0]), '{"k": 5}', 'a') and renderer_changes(os.path.join(REPO, RI.PROGRAM_DATA[1]), '{"k": 6}', 'o'))
    check('программа: правило экрана рядом (rules/photo-pick.json — выгрузчик его не читает) — НЕ меняет', not renderer_changes(os.path.join(S, 'rules/photo-pick.json'), '{"k": 7}', 'p'))
    check('программа: runtime-meshes.json (метаданные) — НЕ меняет', not renderer_changes(os.path.join(REPO, 'data/flat3d/runtime-meshes.json'), '{"meshes": {"a": 1}}', 'r'))
    pl2 = {**PLANTS, 'plants': PLANTS['plants'] + [{'id': 'pZ', 'kind': 'dry', 'styles': ['any']}], 'rev': '7'}
    check('программа: новая запись растения и rev (каталог-данные) — НЕ меняет', not renderer_changes(os.path.join(REPO, 'data/flat3d/plants.json'), json.dumps(pl2), 'p'))
    check('программа: правило посадки (fit) в plants.json — меняет', renderer_changes(os.path.join(REPO, 'data/flat3d/plants.json'), json.dumps({**PLANTS, 'fit': {'green': {'floor': {'k': 2}}}}), 'p'))
    m2 = copy.deepcopy(MATS)
    m2['materials'][3]['roughness'] = 0.1
    check('программа: запись материала НЕ отделки (carpet-grey) — меняет (её читает не только комната)', renderer_changes(os.path.join(REPO, 'data/flat3d/materials.json'), json.dumps(m2), 'm'))
    m3 = copy.deepcopy(MATS)
    m3['materials'][0]['roughness'] = 0.1
    check('программа: запись отделки (finish-wall) — НЕ меняет (едет активом комнаты)', not renderer_changes(os.path.join(REPO, 'data/flat3d/materials.json'), json.dumps(m3), 'm'))

# ——— 5б) переключатель RENDER_KEY_V2: заказ, заготовка и страница получают один и тот же ключ; выключен — прежние ключи
old_flag = os.environ.get('RENDER_KEY_V2')
try:
    os.environ['RENDER_KEY_V2'] = '1'
    RI.clear_memo()
    ver = RX.render_version('/opt/blender-5.3.0-linux-x64/blender')
    sv = RS.canonicalize(DATA, {'v': 1, 'variant_id': VIDS[0]})
    check('v2 включён: `scene_hash` снимка = scene_digest, версии несут space/renderer_digest/preset_digest',
          sv['scene_hash'] == sv['scene_digest'] and ver.get('space') == RI.SPACE and len(ver['renderer_digest']) == 64 and len(ver['preset_digest']) == 64)
    check('v2 включён: `cache_key(scene_hash, версии)` (заготовка) = `frame_key_of(снимок, версии)` (заказ, страница)', RX.cache_key(sv['scene_hash'], ver) == RX.frame_key_of(sv, ver))
    ver2 = RX.render_version('/opt/blender-5.4.0-linux-x64/blender')
    check('v2: другой Blender — другой ключ у всех', RX.frame_key_of(sv, ver) != RX.frame_key_of(sv, ver2))
    ks = {RX.frame_key_of(RS.canonicalize(DATA, {'v': 1, 'variant_id': v}), ver) for v in VIDS}
    check('v2: ключи всех вариантов разные', len(ks) == len(VIDS))
    leg = mut(lambda d: d.__setitem__('build', 'gitNEW.rulesNEW'))
    n_leg = sum(RS.canonicalize(DATA, {'v': 1, 'variant_id': v})['legacy_hash'] != RS.canonicalize(leg, {'v': 1, 'variant_id': v})['legacy_hash'] for v in VIDS)
    n_v2 = sum(RS.canonicalize(DATA, {'v': 1, 'variant_id': v})['scene_digest'] != RS.canonicalize(leg, {'v': 1, 'variant_id': v})['scene_digest'] for v in VIDS)
    print(f'     выкладка с новой меткой правил: прежний ключ сбросил бы {n_leg} из {len(VIDS)} комнат, v2 — {n_v2}')
    check('выкладка с новой меткой правил: прежний ключ сбрасывал все комнаты, v2 — ни одной', n_leg == len(VIDS) and n_v2 == 0)
    # заготовка кадров (`render_prewarm.Prewarmer.missing`): кадры лежат под v2-ключами; после выкладки правил экрана не считается НИ ОДНА комната, правка комнаты — только её
    import types
    import render_prewarm as RP

    class Store:
        def __init__(self):
            self.have = set()

        def cached(self, k):
            return {} if k in self.have else None

        def brak_of(self, k):
            return None
    st = Store()
    pw = RP.Prewarmer.__new__(RP.Prewarmer)
    pw.q, pw.versions, pw.failed = types.SimpleNamespace(store=st), ver, {}

    def missing_in(data):
        sc = [(v, RS.canonicalize(data, {'v': 1, 'variant_id': v})) for v in VIDS]
        return {lb for lb, _, _ in pw.missing(sc, {'fail_max': 3})}
    check('заготовка: кадров нет — не хватает всех комнат', missing_in(DATA) == set(VIDS))
    st.have = {RX.frame_key_of(RS.canonicalize(DATA, {'v': 1, 'variant_id': v}), ver) for v in VIDS}
    check('заготовка: кадры лежат — не хватает 0', missing_in(DATA) == set())
    check('заготовка: ПОСЛЕ ВЫКЛАДКИ правил экрана (метка, photo-pick, quiz, цены) — не пересчитывает ни одной комнаты', missing_in(mut(screen_only)) == set())
    check('заготовка: правка одной комнаты — пересчёт только её вариантов', missing_in(mut(lambda d: d['rooms_geo'][R0].__setitem__('height_cm', 321))) == users(R0))
    os.environ['RENDER_KEY_V2'] = '0'
    ver0 = RX.render_version('/opt/blender-5.3.0-linux-x64/blender')
    s0 = RS.canonicalize(DATA, {'v': 1, 'variant_id': VIDS[0]})
    check('v2 выключен: версии без space, `scene_hash` прежний, ключ как раньше', 'space' not in ver0 and s0['scene_hash'] == s0['legacy_hash']
          and RX.frame_key_of(s0, ver0) == RX.cache_key(s0['scene_hash'], ver0))
finally:
    if old_flag is None:
        os.environ.pop('RENDER_KEY_V2', None)
    else:
        os.environ['RENDER_KEY_V2'] = old_flag
    RI.clear_memo()

# ——— 6) сторож чтений
inp = BASE[VIDS[0]]['frame_inputs']


def reads_of(inp_):
    rows = []
    for a in inp_['assets']:
        k, name = a['logical'].split(':', 1)
        url = {'mesh': f'/test/mesh-pilot10/{name}/model.glb', 'img': f'/demo/{name}', 'env': '/flat3d/env/outside.webp', 'view': f'/scene/views/{name}.webp',
               'material': f'/flat3d/materials/{name}', 'plant': f'/flat3d/plants/{name}.glb?v=6'}.get(k.replace('-map', ''))
        if url and a['kind'] != 'plant-record':
            rows.append({'url': url, 'sha256': a['sha256'], 'kind': 'local'})
    return {'v': 1, 'hermetic': True, 'reads': rows}


rd = reads_of(inp)
check(f'сторож: чтения, равные входу ({len(rd["reads"])}), — чисто', RI.check_reads(inp, rd) == [])
rd2 = {**rd, 'reads': rd['reads'][:3]}
check('сторож: часть входа не прочитана (кэш страницы) — чисто (недочитать можно)', RI.check_reads(inp, rd2) == [])
check('сторож: ПИН таблицы runtime-мешей — допустим', RI.check_reads(inp, {'reads': rd['reads'] + [{'url': 'pinned:data/flat3d/runtime-meshes.json', 'sha256': 'a', 'kind': 'pinned'}]}) == [])
bad = RI.check_reads(inp, {'reads': rd['reads'] + [{'url': '/flat3d/plants/neizvestnoe.glb?v=6', 'sha256': 'f' * 64, 'kind': 'local'}]})
check('сторож: нарочно добавленное чтение вне входа — КРАСНЫЙ', len(bad) == 1 and 'вне входа' in bad[0])
check('сторож: чтение из сети — красный', RI.check_reads(inp, {'reads': [{'url': '/demo/img/x.jpg', 'sha256': 'f' * 64, 'kind': 'remote'}]}) != [])
chg = copy.deepcopy(rd)
chg['reads'][0]['sha256'] = '0' * 64
check('сторож: файл прочитан не тот, что в ключе (другой sha256) — красный', len(RI.check_reads(inp, chg)) == 1)
check('сторож: неизвестный адрес — красный', RI.check_reads(inp, {'reads': [{'url': '/etc/passwd', 'sha256': 'a', 'kind': 'local'}]}) != [])
try:
    d_ = tempfile.mkdtemp(dir=TMP)
    RX.check_dump_reads(d_, inp)
    _raises = False
except RX.RenderError as e:
    _raises = e.code == 'reads_missing'
check('исполнитель: нет `dump/reads.json` — отказ reads_missing до рендера', _raises)
d_ = tempfile.mkdtemp(dir=TMP)
wj(os.path.join(d_, 'reads.json'), {'reads': rd['reads'] + [{'url': '/demo/img/lishnee.jpg', 'sha256': 'a' * 64, 'kind': 'local'}]})
try:
    RX.check_dump_reads(d_, inp)
    _raises = False
except RX.RenderError as e:
    _raises = e.code == 'inputs_undeclared'
check('исполнитель: лишнее чтение — отказ inputs_undeclared до рендера', _raises)
wj(os.path.join(d_, 'reads.json'), rd)
try:
    RX.check_dump_reads(d_, inp)
    ok_ = True
except RX.RenderError:
    ok_ = False
check('исполнитель: чтения внутри входа — проходит', ok_)

# ——— 6б) сторож чтений Python-выгрузчика (`reads-py.json`)
def py_reads(inp_):
    rows = []
    for a in inp_['assets']:
        if a['kind'] in ('mesh', 'img', 'env', 'view', 'material-map', 'plant'):
            kk, name = a['logical'].split(':', 1)
            p = path_of(name and (a['logical'] if a['kind'] != 'material-map' else a['logical']))
            if p:
                rows.append({'path': p, 'sha256': a['sha256'], 'kind': 'local'})
    return {'v': 1, 'hermetic': True, 'violations': [], 'reads': rows}


pr = py_reads(inp)
check(f'сторож Python: чтения, равные входу ({len(pr["reads"])}), — чисто', RI.check_reads_py(inp, pr) == [])
check('сторож Python: часть входа не прочитана — чисто', RI.check_reads_py(inp, {**pr, 'reads': pr['reads'][:2]}) == [])
rules_rel = RI.PROGRAM_DATA[0]
prog_path = os.path.join(RI.repo(), rules_rel)
if not LIVE:
    wj(prog_path, {'k': 1})
    wj(os.path.join(REPO, RI.PROGRAM_DATA[1]), {'k': 2})
    SI._FULL_MEMO.clear()
check('сторож Python: данные программы (asset-strategies, occupancy) — свой файл, чисто',
      RI.check_reads_py(inp, {'reads': [{'path': prog_path, 'sha256': SI.full_sha(prog_path), 'kind': 'local'}]}) == [])
check('сторож Python: данные программы другим содержимым — красный', len(RI.check_reads_py(inp, {'reads': [{'path': prog_path, 'sha256': 'f' * 64, 'kind': 'local'}]})) == 1)
check('сторож Python: служебное (dev-tmp.json, индекс хешей, кэш текстур выгрузчика) — не вход',
      RI.check_reads_py(inp, {'reads': [{'path': os.path.join(RI.repo(), 'tools/scout/rules/dev-tmp.json'), 'sha256': 'a', 'kind': 'local'},
                                         {'path': '/home/x/scout-cache/scene-inputs-sha.json', 'sha256': 'a', 'kind': 'local'},
                                         {'path': '/home/x/scout-cache/render-tex/ab-3.png', 'sha256': 'a', 'kind': 'local'}]}) == [])
extra_p = SI.public_file('flat3d/materials/' + sorted(os.listdir(os.path.join(SI._public(), 'flat3d/materials')))[-1])
declared_logicals = {a['logical'] for a in inp['assets']}
other = next((f for f in sorted(os.listdir(os.path.join(SI._public(), 'flat3d/materials'))) if f'material:{f}' not in declared_logicals), None)
if other:
    bad = RI.check_reads_py(inp, {'reads': [{'path': os.path.join(SI._public(), 'flat3d/materials', other), 'sha256': 'a' * 64, 'kind': 'local'}]})
    check('сторож Python: нарочно добавленное чтение материала вне входа — КРАСНЫЙ', len(bad) == 1 and 'вне входа' in bad[0])
bad = RI.check_reads_py(inp, {'reads': [{'path': '/home/x/scout-scenes/draft-photos/abc.png', 'sha256': 'a' * 64, 'kind': 'local'}]})
check('сторож Python: чтение нигде не объявленного файла (кэш «фото из сети») — красный', len(bad) == 1 and 'неизвестный' in bad[0])
check('сторож Python: попытка сети из `violations` — красный', RI.check_reads_py(inp, {'violations': ['сеть: getaddrinfo remont-lab.online'], 'reads': []}) != [])
chg = copy.deepcopy(pr)
chg['reads'][0]['sha256'] = '0' * 64
check('сторож Python: прочитан файл с другим sha256 — красный', len(RI.check_reads_py(inp, chg)) == 1)
jd = tempfile.mkdtemp(dir=TMP)
try:
    RX.check_export_reads(jd, inp)
    _raises = False
except RX.RenderError as e:
    _raises = e.code == 'reads_missing'
check('исполнитель: нет `reads-py.json` — отказ reads_missing до рендера', _raises)
wj(os.path.join(jd, 'reads-py.json'), {**pr, 'violations': ['сеть: getaddrinfo remont-lab.online']})
try:
    RX.check_export_reads(jd, inp)
    _raises = False
except RX.RenderError as e:
    _raises = e.code == 'inputs_undeclared'
check('исполнитель: выгрузчик полез в сеть — отказ inputs_undeclared до рендера', _raises)
wj(os.path.join(jd, 'reads-py.json'), pr)
try:
    RX.check_export_reads(jd, inp)
    ok_ = True
except RX.RenderError:
    ok_ = False
check('исполнитель: чтения выгрузчика внутри входа — проходит', ok_)

# ——— 6в) Blender-этап: карты из public/, которые он возьмёт по scene-export.json, — активы комнаты (T-20261118-04/18/1)
def surf(files):
    return {'rooms': [{'wall': {'maps': {'color': '/flat3d/materials/' + files[0]}, 'tileCm': [50, 50]},
                       'floor': {'maps': {'color': '/flat3d/materials/' + files[1], 'normal': None}}}], 'other': '/flat3d/materials/nikto.webp'}


declared_mats = sorted(a['logical'][9:] for a in inp['assets'] if a['kind'] == 'material-map')
if len(declared_mats) >= 2:
    exp_ok = surf(declared_mats[:2])
    check('Blender: карты отделки комнаты (maps в scene-export) — все во входе, тот же sha256', RI.check_blender_maps(inp, exp_ok) == [])
    other = next((f for f in sorted(os.listdir(os.path.join(SI._public(), 'flat3d/materials'))) if f not in declared_mats), None)
    if other:
        bad = RI.check_blender_maps(inp, surf([declared_mats[0], other]))
        check('Blender: карта вне входа комнаты — КРАСНЫЙ (правка такого файла отдала бы старый кадр)', len(bad) == 1 and 'вне входа' in bad[0])
    check('Blender: строки-пути вне `maps` (не читаются) — не нарушение', RI.check_blender_maps(inp, {'x': '/flat3d/materials/nikto.webp'}) == [])
    if not LIVE:
        p0 = SI.public_file('flat3d/materials/' + declared_mats[0])
        with open(p0, 'ab') as f:
            f.write(b'-late')
        SI._FULL_MEMO.clear()
        bad = RI.check_blender_maps(inp, exp_ok)
        check('Blender: карта изменилась между ключом и рендером — красный', len(bad) == 1 and 'другая' in bad[0])
        with open(p0, 'rb') as f:
            b = f.read()
        with open(p0, 'wb') as f:
            f.write(b[:-5])
        SI._FULL_MEMO.clear()
    dd = tempfile.mkdtemp(dir=TMP)
    try:
        RX.check_blender_inputs(dd, inp)
        _raises = False
    except RX.RenderError as e:
        _raises = e.code == 'reads_missing'
    check('исполнитель: нет scene-export.json — отказ reads_missing до Blender', _raises)
    wj(os.path.join(dd, 'scene-export.json'), surf([declared_mats[0], other or declared_mats[1]]) if other else exp_ok)
    try:
        RX.check_blender_inputs(dd, inp)
        ok_ = not other
    except RX.RenderError as e:
        ok_ = bool(other) and e.code == 'inputs_undeclared'
    check('исполнитель: карта вне входа — отказ inputs_undeclared до Blender', ok_)
# программа Blender-этапа в digest (настоящий репозиторий — на живых данных): render_cycles.py, frame_qa.py, wall_art.py и их данные
if LIVE:
    pf = RI.program_files('b')
    check('Blender: render_cycles.py, frame_qa.py, wall_art.py и data/flat3d/{wall-art,frame-qa-rules,textile}.json — в renderer_digest', all(x in set(pf['py']) | set(pf['js']) for x in (
        'tools/scout/cycles_probe/render_cycles.py', 'tools/scout/cycles_probe/frame_qa.py', 'tools/scout/wall_art.py', 'data/flat3d/wall-art.json',
        'data/flat3d/frame-qa-rules.json', 'data/flat3d/textile.json')))

# ——— 7) живые дампы (на pakardev): reads.json всех вариантов внутри входа
if LIVE:
    rdir = next((a for a in sys.argv[1:] if not a.startswith('--')), os.path.expanduser('~/remlab-logs/t04-1118/rk'))
    n_ok = n_all = 0
    for vid in VIDS:
        f = os.path.join(rdir, vid, 'dump', 'reads.json')
        if not os.path.isfile(f):
            continue
        n_all += 1
        bad = RI.check_reads(BASE[vid]['frame_inputs'], json.load(open(f, encoding='utf-8')))
        n_ok += not bad
        if bad:
            print('   ', vid, bad[:4])
    check(f'ЖИВЫЕ дампы: чтения {n_all} из {len(VIDS)} вариантов — внутри входа, 0 нарушений', n_all == len(VIDS) and n_ok == n_all)
    pdir = next((a for a in sys.argv[1:] if a.startswith('--py=')), '--py=' + os.path.expanduser('~/remlab-logs/t04-1118/rk/py-1'))[5:]
    n_ok = n_all = 0
    for vid in VIDS:
        f = os.path.join(pdir, vid + '.json')
        if not os.path.isfile(f):
            continue
        n_all += 1
        bad = RI.check_reads_py(BASE[vid]['frame_inputs'], json.load(open(f, encoding='utf-8')))
        n_ok += not bad
        if bad:
            print('   ', vid, bad[:4])
    check(f'ЖИВЫЕ чтения Python-выгрузчика: {n_all} из {len(VIDS)} вариантов — внутри входа, 0 нарушений, 0 попыток сети', n_all == len(VIDS) and n_ok == n_all)
else:
    shutil.rmtree(TMP, ignore_errors=True)
print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
