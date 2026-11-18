"""ПРОБА T-20261117-02: выгрузка 3D-сцены демо (та же, что у серверного кадра T-61) для Blender Cycles. 0 ₽.

  ~/venvs/scout/bin/python cycles_probe/export_scene.py --out <папка> --scene living-scandi=0 --scene bed2-japandi=15

Сцена собирается тем же кодом, что серверный кадр (`draft_render.scene3d_frame`): растеризатор подменён «записью» — вместо
рисования в буфер каждый меш (мировые вершины, текстура, UV) пишется в файл. Ни `draft_render.py`, ни `scene_mesh.py` не правятся.
Мир Blender = (x, −z, y)/100 м (сцена: X вправо, Y вверх, Z — вглубь плана; поворот собственный, зеркала нет).

Выход на сцену (<out>/<имя>/): scene.json (комната, проёмы, камеры, список объектов), m000.npz…, tex/*.png.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
import weakref
import zlib

import numpy as np
from PIL import Image

# ТРАССА (T-20261118-09/1): `TRACE py <шаг> <секунды от старта скрипта>`; `acc:<функция>` — накопленное время и число вызовов (шаги внутри `scene3d_frame`).
# Исполнитель собирает строки в `timing.trace.py`; на результат не влияет.
_T0 = time.time()
_ACC: dict = {}


# ОТДЕЛКА ПО УМОЛЧАНИЮ (T-20261118-03/9): у комнаты тура паспорта отделки нет (он из карточки квартиры застройщика, у /demo есть) — Blender падал на
# `M['finish']['wall']` до первого кадра. Набор тот же, что у страницы: `lib/viewer3d/finish-passport.ts:DEFAULT_FINISH` (сверка — `tests/test_export_finish_default.py`).
DEFAULT_FINISH = {'wall': {'id': 'paint-white', 'colorHex': '#f2f0ed'}, 'floor': {'id': 'demo-floor', 'colorHex': '#dcc7a6'},
                  'ceiling': {'id': 'ceiling-white', 'colorHex': '#f6f5f2'}, 'skirting': {'id': 'skirting-white', 'colorHex': '#f4f2ee'}}


def with_default_finish(fin) -> dict:
    """Паспорт комнаты как у страницы (`finish-passport.ts:finishPassport`): поверхность с верным цветом `#rrggbb` — своя (цвет в нижнем регистре, `id` верный
    или по умолчанию), иначе — по умолчанию; `floor.tex` (фактура пола ночной сборки) не теряется."""
    fin = fin if isinstance(fin, dict) else {}
    out = {}
    for k, d in DEFAULT_FINISH.items():
        v = fin.get(k) if isinstance(fin.get(k), dict) else {}
        ok = isinstance(v.get('colorHex'), str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v['colorHex'])
        s_ = {**v} if ok else {}                 # прочие поля поверхности (фактура, выбор застройщика) едут как были — /demo не меняется
        s_ |= {'id': v['id'] if ok and isinstance(v.get('id'), str) and re.fullmatch(r'[a-z0-9-]{1,40}', v['id']) else d['id'],
              'colorHex': v['colorHex'].lower() if ok else d['colorHex']}
        if not ok and v.get('tex'):
            s_['tex'] = v['tex']
        out[k] = s_
    return out


def trace(name):
    print(f'TRACE py {name} {time.time() - _T0:.2f}', flush=True)


def reset_trace():
    """Постоянный процесс (`export_server.py`): трасса каждого заказа — от его начала."""
    global _T0
    _T0 = time.time()
    _ACC.clear()


_WRAPPED = [False]


def _wrap_once(MR, DR, OIR):
    """Замеры накопителей вешаются ОДИН раз на процесс (иначе в постоянном процессе обёртки копились бы стопкой)."""
    if _WRAPPED[0]:
        return
    _WRAPPED[0] = True
    MR.load_parts = timed('load_parts', MR.load_parts)
    DR._push_from_supports = timed('push_from_supports', DR._push_from_supports)
    DR.compile_scene = timed('compile_scene', DR.compile_scene)
    OIR.paint_beyond = timed('paint_beyond', OIR.paint_beyond)
    import scene_mesh as _SM
    _SM.world_vertices = timed('world_vertices', _SM.world_vertices)


def preload():
    """Тяжёлые импорты выгрузки — заранее (постоянный процесс делает это один раз, не на каждый заказ)."""
    import draft_render as DR  # noqa: F401
    import scene_mesh as SM  # noqa: F401
    import mesh_render as MR
    import opening_ir as OIR
    from planner.scene import Camera  # noqa: F401
    import improve_mode  # noqa: F401
    _wrap_once(MR, DR, OIR)


def timed(name, fn):
    def w(*a, **k):
        t = time.time()
        try:
            return fn(*a, **k)
        finally:
            c = _ACC.setdefault(name, [0.0, 0])
            c[0] += time.time() - t
            c[1] += 1
    return w


HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
sys.path.insert(0, SCOUT)
sys.path.insert(0, os.path.join(SCOUT, '..', '..', 'services', 'planner-solver'))
os.environ.setdefault('SCENE3D_QUALITY', 'full')

DEMO = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
BASE_URL = 'https://remont-lab.online/demo/'

# КЭШ PNG ПО СОДЕРЖИМОМУ (T-20261117-24/4): кодирование 18 текстур давало 18 из 22 с экспорта. Тот же набор пикселей — тот же файл:
# кэшируется один раз (compress_level 3: вдвое быстрее и на 15 % крупнее уровня 6 по замеру), в сцену — жёсткая ссылка/копия.
# Холодный путь (новый товар) кодирует как раньше, только быстрее; повтор — 0 с кодирования. Ключ — md5 пикселей + форма (имя в сцене не меняется).
TEX_CACHE = os.environ.get('RENDER_TEX_CACHE') or os.path.expanduser('~/scout-cache/render-tex')
PNG_LEVEL = int(os.environ.get('RENDER_PNG_LEVEL', '3'))


def png_key(arr):
    """Имя файла в общем кэше PNG по содержимому (md5 пикселей + форма + уровень сжатия)."""
    return hashlib.md5(arr.tobytes() + str(arr.shape).encode()).hexdigest() + f'-{PNG_LEVEL}.png'


def ensure_png(arr, key=None):
    """PNG в общем кэше по содержимому (создаётся, если нет) → путь файла кэша. `key` — готовое имя из `png_key`; `arr` может быть функцией — пиксели нужны, только если файла нет.
    Отдельно от `put_png`, чтобы заготовка (`render_texwarm.py`) наполняла кэш заранее, не раскладывая файлы по заданиям."""
    if key is None:
        arr = np.ascontiguousarray(np.asarray(arr, np.uint8))
        key = png_key(arr)
    c = os.path.join(TEX_CACHE, key)
    if not os.path.isfile(c):
        if callable(arr):
            arr = arr()
        arr = np.ascontiguousarray(np.asarray(arr, np.uint8))
        os.makedirs(TEX_CACHE, exist_ok=True)
        tmp = f'{c}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp'      # атомарно: временный → переименование; после записи — только чтение
        Image.fromarray(arr).save(tmp, 'PNG', compress_level=PNG_LEVEL)
        os.chmod(tmp, 0o444)
        os.replace(tmp, c)
    return c


def put_png(arr, dst, key=None):   # (обёрнут в timed ниже)
    """Положить PNG в `dst` из общего кэша (жёсткая ссылка). `key` — готовое имя из `png_key` (хеш уже считали); `arr` может быть функцией — пиксели нужны, только если файла в кэше нет."""
    c = ensure_png(arr, key)
    try:
        os.link(c, dst)
    except OSError:
        shutil.copyfile(c, dst)


put_png = timed('put_png', put_png)


# КЭШ СЖАТЫХ МЕШЕЙ ВЫГРУЗКИ (T-20261118-10/2 (б)): `np.savez_compressed` мира вершин/граней/UV одного меша — ≈0,04 с на меш, ≈0,5 с на гостиную, а при смене дивана меняется один
# меш из 12–14: остальные — те же массивы (та же поза, тот же меш). Файл кладём в общий кэш ПО СОДЕРЖИМОМУ массивов (md5 + версии numpy/zlib: байты сжатия зависят от них) и
# даём жёсткой ссылкой — те же байты `m###.npz`, что у прямой записи (проверка — тест и побайтное сравнение `scene/`).
NPZ_CACHE = os.environ.get('RENDER_NPZ_CACHE') or os.path.expanduser('~/scout-cache/render-npz')
NPZ_CACHE_MB = float(os.environ.get('RENDER_NPZ_CACHE_MB', '1500'))
_NPZ_TAG = f'{np.__version__}|{zlib.ZLIB_VERSION}'.encode()
_NPZ_WRITES = [0]


def npz_key(data):
    h = hashlib.md5(_NPZ_TAG)
    for k in sorted(data):
        a = np.ascontiguousarray(data[k])
        h.update(f'|{k}|{a.dtype.str}|{a.shape}|'.encode())
        h.update(a.data)
    return h.hexdigest() + '.npz'


def _prune_npz(cap_mb):
    """Кэш не растёт без предела: за потолок — самые старые (по времени записи) долой до 80 %. Жёсткие ссылки в каталогах заданий от этого живы."""
    try:
        fs = [(e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(NPZ_CACHE) if e.name.endswith('.npz')]
    except OSError:
        return
    total = sum(f[1] for f in fs)
    if total <= cap_mb * 1048576:
        return
    for _m, sz, path in sorted(fs):
        if total <= cap_mb * 1048576 * 0.8:
            break
        try:
            os.remove(path)
            total -= sz
        except OSError:
            pass


def put_npz(data, dst):
    key = npz_key(data)
    c = os.path.join(NPZ_CACHE, key)
    if not os.path.isfile(c):
        os.makedirs(NPZ_CACHE, exist_ok=True)
        tmp = f'{c}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp'      # атомарно: временный → переименование; после записи — только чтение
        with open(tmp, 'wb') as f:
            np.savez_compressed(f, **data)
        os.chmod(tmp, 0o444)
        os.replace(tmp, c)
        _NPZ_WRITES[0] += 1
        wrote = True
    else:
        wrote = False
    try:
        os.link(c, dst)
    except OSError:
        shutil.copyfile(c, dst)
    if wrote and _NPZ_WRITES[0] % 20 == 0:
        _prune_npz(NPZ_CACHE_MB)         # после ссылки: выданный файл — жёсткая ссылка, чистка кэша его не трогает


put_npz = timed('put_npz', put_npz)


# ПАМЯТКА ПО КАРТИНКАМ МЕШЕЙ (T-20261118-10/1 (в)): текстура меша — одна и та же картинка PIL, пока жив кэш разобранных мешей постоянного процесса (`export_server.PartsCache`);
# её пересчёт в массив и два md5 по 12 МБ на каждый заказ (≈1 с на гостиную) не нужны. Ключ — сама картинка (слабая ссылка: исчезла из кэша — исчезла и запись; `id` не переиспользуется
# под чужую картинку, это проверяется `ref() is img`). Результат тот же: имя `tex/<md5[:12]>.png`, файл — из общего кэша PNG по содержимому.
_TEXMEMO: dict = {}


def _tex_image(mesh):
    """Картинка текстуры меша и UV — как `mesh_render.texture_of`, но картинку в массив не переводит (это делает `save_tex_img` и только при промахе памятки)."""
    vis = getattr(mesh, 'visual', None)
    uv = getattr(vis, 'uv', None)
    mat = getattr(vis, 'material', None)
    img = getattr(mat, 'baseColorTexture', None) if mat is not None else None
    if img is None and mat is not None:
        img = getattr(mat, 'image', None)
    if uv is None or img is None:
        return None, None
    return img, np.asarray(uv, np.float32)


def _tex_memo(img):
    m = _TEXMEMO.get(id(img))
    if m is not None and m[0]() is img:
        return m
    arr = np.ascontiguousarray(np.asarray(img.convert('RGB')))
    m = (weakref.ref(img, lambda _r, k=id(img): _TEXMEMO.pop(k, None)), hashlib.md5(arr.tobytes()).hexdigest()[:12], png_key(arr), tuple(arr.shape[:2]))
    _TEXMEMO[id(img)] = m
    return m


def to_b(p):
    """сцена (x, y, z) см → Blender (x, −z, y) м."""
    p = np.asarray(p, np.float64)
    return np.stack([p[..., 0], -p[..., 2], p[..., 1]], -1) / 100.0


def payload_of(D, idx):
    v = D['variants'][idx]
    geo = D['rooms_geo'].get(v['room_id']) or D['room']
    items = []
    for it in v['items']:
        sk = it.get('sku') or {}
        items.append({'role': it['role'], 'x': it['x'], 'y': it['y'], 'rot': it.get('rot') or 0, 'w': it['w'], 'd': it['d'],
                      'h': it.get('h') or sk.get('h'), 'corner': bool(it.get('corner')), 'corner_left': bool(it.get('corner_left')),
                      'section': it.get('section'), 'sid': sk.get('sid'), 'msid': sk.get('msid') or sk.get('sid'),
                      'name': sk.get('name'), 'hung': sk.get('hung'), 'pack': sk.get('pack'),
                      'img': (BASE_URL + sk['img']) if sk.get('img') else None, 'swatch': sk.get('swatch'), 'tint': sk.get('tint')})
    decor = []
    for d in v.get('decor') or []:
        d = json.loads(json.dumps(d))
        if (d.get('sku') or {}).get('img'):
            d['sku']['img'] = BASE_URL + d['sku']['img']
        decor.append(d)
    return {'room': geo, 'style': v['style'], 'variant': v['id'], 'decor': decor, 'developerOptions': {}, 'floor': None, 'walls': None,
            'cams': v['cams'], 'items': items}


def tint_of(sk):
    """Подкраска товара — три множителя 0,2–3 (как `lib/configurator/fromDemo.ts:tintOf`: чужим данным не доверяем); нет — None."""
    t = (sk or {}).get('tint')
    if isinstance(t, (list, tuple)) and len(t) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0.2 <= x <= 3 for x in t):
        return [float(x) for x in t]
    return None


def main_export(D, idx, out):
    trace('imports_base')
    import draft_render as DR
    import scene_mesh as SM
    import mesh_render as MR
    import opening_ir as _OIR
    from planner.scene import Camera as Cam
    import improve_mode as IM
    trace('imports_scene')
    DR.S3_LITE[0] = False                      # ПОЛНЫЕ меши — как у платного кадра
    _wrap_once(MR, DR, _OIR)
    payload = payload_of(D, idx)
    os.makedirs(os.path.join(out, 'tex'), exist_ok=True)
    room, placements, photos = DR.scene_from_request(payload)
    trace('plan_scene_from_request')
    cams = DR.cams_from_request(room, placements, payload)[:2]
    rw, rh_total = (int(x) for x in IM.SIZE.split('x'))
    per = (rh_total - DR.BAND_PX) // 2
    cams = [Cam(name=c.name, eye=c.eye, target=c.target, fov_deg=c.fov_deg, width=rw, height=per, shift_y=getattr(c, 'shift_y', 0.0))
            for c in cams]
    sid_by_role = {it['role']: (it.get('msid') or it.get('sid')) for it in payload['items'] if it.get('role')}
    for role, sid in list(sid_by_role.items()):
        if not sid:
            base = re.sub(r'\s+\d+$', '', role)
            if base != role and sid_by_role.get(base):
                sid_by_role[role] = sid_by_role[base]
    for d in DR.decor_split(payload)[0]:
        sk = d.get('sku') or {}
        if d.get('role') and (sk.get('msid') or sk.get('sid')):
            sid_by_role[d['role']] = sk.get('msid') or sk.get('sid')

    # ПОДКРАСКА ПОД ТОВАР — то же правило, что у живой 3D (`lib/configurator/fromDemo.ts:tintOf` → `lib/viewer3d/meshes.ts:placeMesh`): три множителя
    # 0,2–3, цвет материала меша × множитель, в линейном пространстве, на все материалы меша. Не три числа в этих пределах — подкраски нет
    tint_by_role = {it['role']: tint_of(it) for it in payload['items'] if it.get('role') and tint_of(it)}
    for d in DR.decor_split(payload)[0]:
        if d.get('role') and tint_of(d.get('sku')):
            tint_by_role[d['role']] = tint_of(d.get('sku'))
    objs, rugs, planes = [], [], []
    tex_seen = {}

    def save_tex(arr):
        h = hashlib.md5(arr.tobytes()).hexdigest()[:12]
        rel = f'tex/{h}.png'
        if h not in tex_seen:
            put_png(arr, os.path.join(out, rel))
            tex_seen[h] = list(arr.shape[:2])
        return rel

    def save_tex_img(img):
        h, key, shape = _tex_memo(img)[1:4]
        rel = f'tex/{h}.png'
        if h not in tex_seen:
            put_png(lambda: np.asarray(img.convert('RGB')), os.path.join(out, rel), key=key)
            tex_seen[h] = list(shape)
        return rel, shape

    save_tex_img = timed('save_tex', save_tex_img)

    def rec_raster(img, zbuf, parts, place, cam, W, Hpx, front_yaw, name2h=None, inst_buf=None, inst_id=0, mirror=False):
        worlds, Ra, R, h_src, aniso, scale = SM.world_vertices(parts, place, front_yaw, name2h, mirror)
        flip = float(np.prod(np.sign(scale))) < 0
        for k, (mesh, wv) in enumerate(zip(parts, worlds)):
            f = np.asarray(mesh.faces, np.int32)
            if flip:
                f = f[:, ::-1]
            tex, uvm = _tex_image(mesh)
            rec = {'role': place.role, 'file': f'm{len(objs):03d}.npz', 'tex': None, 'rgb': None,
                   'n_faces': int(len(f)), 'elev': float(getattr(place, 'elev_cm', 0) or 0)}
            if tint_by_role.get(place.role):
                rec['tint'] = tint_by_role[place.role]
            data = {'v': to_b(wv).astype(np.float32), 'f': f.astype(np.int32)}
            if tex is not None and uvm is not None:
                rec['tex'], _shape = save_tex_img(tex)
                rec['tex_px'] = list(_shape)
                data['uv'] = np.asarray(uvm, np.float32)
                # собственная карта шероховатости/металла меша (glTF: G — шероховатость, B — металл): «как есть», ничего не придумываем
                mrt = getattr(getattr(mesh.visual, 'material', None), 'metallicRoughnessTexture', None)
                if mrt is not None:
                    rec['mr'] = save_tex_img(mrt)[0]
            else:
                cols = MR.flat_colors(mesh)
                rec['rgb'] = [float(x) for x in np.asarray(cols).mean(axis=0)]
            _t_sz = time.time()
            put_npz(data, os.path.join(out, rec['file']))
            _ACC.setdefault('savez', [0.0, 0]); _ACC['savez'][0] += time.time() - _t_sz; _ACC['savez'][1] += 1
            objs.append(rec)
        return {}

    def rec_rug(canvas, zbuf, place, cam, W, H, ph):
        if ph is None:
            return False
        rel = f'tex/rug{len(rugs)}.png'
        put_png(np.asarray(ph.convert('RGB')), os.path.join(out, rel))
        it = place.item
        rugs.append({'role': place.role, 'x': place.x, 'y': place.y, 'rot': float(place.rot or 0), 'w': float(it.w_cm), 'd': float(it.d_cm), 'tex': rel})
        return True

    def rec_plane(canvas, zbuf, place, cam, W, H, mirror, ph=None):
        q = DR.wall_plane_quads(place)
        rec = {'role': place.role, 'mirror': bool(mirror), 'outer': to_b(np.array(q['outer'])).tolist(),
               'inner': to_b(np.array(q['inner'])).tolist(), 'tex': None}
        if not mirror and ph is not None:
            rel = f'tex/plane{len(planes)}.png'
            put_png(np.asarray(ph.convert('RGB')), os.path.join(out, rel))
            rec['tex'] = rel
        planes.append(rec)
        return True

    o_r, o_p, o_w = SM.raster_mesh, DR._paste_rug, DR._paint_wall_plane
    SM.raster_mesh, DR._paste_rug, DR._paint_wall_plane = timed('rec_raster', rec_raster), rec_rug, rec_plane
    trace('before_scene3d_frame')
    try:
        # PREVIEW=0 (RENDER_PREP_FAST=0 в исполнителе) — прежний путь с рисованием превью; по умолчанию превью не рисуется (результат выгрузки тот же — A/B в плане render-prep-speed-01)
        DR.scene3d_frame(room, placements, cams[0], sid_by_role, photos, preview=os.environ.get('EXPORT_PREVIEW') == '1')
    finally:
        SM.raster_mesh, DR._paste_rug, DR._paint_wall_plane = o_r, o_p, o_w
    trace('scene3d_frame')

    fin = with_default_finish(getattr(room, 'finish', None))
    floor_tex = ((fin.get('floor') or {}).get('tex'))
    floor_rel = None
    if floor_tex:
        img = DR._floor_image(floor_tex['src'])
        if img is not None:
            floor_rel = save_tex(np.clip(np.asarray(img), 0, 255).astype(np.uint8))
    from planner.scene import _ir_cuts
    cuts = {w: [{'u0': c[0], 'u1': c[1], 'bottom': c[2], 'top': c[3], 'kind': k} for c, k in lst] for w, lst in _ir_cuts(room).items()}
    import opening_ir as OIR
    backdrops = []
    for e in (getattr(room, 'openings_ir', None) or []):
        bd = (e.get('ir') or {}).get('backdrop')
        img = OIR.view_image(bd.get('assetId', '')) if bd else None
        if img is not None:
            backdrops.append({'wall': e['wall'], 'bd': bd, 'tex': save_tex(np.clip(img, 0, 255).astype(np.uint8))})
    cam_out = []
    for c in cams:
        eye, fwd, right, up = c.basis()
        cam_out.append({'name': c.name, 'eye': to_b(eye).tolist(), 'fwd': to_b(fwd * 100).tolist(), 'right': to_b(right * 100).tolist(),
                        'up': to_b(up * 100).tolist(), 'fov': c.fov_deg, 'shift_y': c.shift_y, 'w': rw, 'h': per})
    meta = {'idx': idx, 'variant': payload['variant'], 'style': payload['style'], 'room_title': payload['room'].get('title'),
            'W': float(room.width_cm), 'D': float(room.depth_cm), 'H': 270.0, 'finish': fin, 'floor_tex': floor_rel,
            'floor_tile': (floor_tex or {}).get('tile'), 'cuts': cuts,
            'openings': [{'wall': e.get('wall'), 'kind': (e.get('ir') or {}).get('kind')} for e in (room.openings_ir or [])],
            'backdrops': backdrops, 'cams': cam_out, 'objs': objs, 'rugs': rugs, 'planes': planes, 'tex_px': tex_seen}
    trace('post_floor_cuts_backdrops')
    json.dump(meta, open(os.path.join(out, 'scene.json'), 'w'), ensure_ascii=False, indent=1)
    trace('scene_json_written')
    for k, (sec, n) in sorted(_ACC.items()):
        print(f'TRACE py acc:{k} {sec:.2f} n={n}', flush=True)
    big = sorted(tex_seen.items(), key=lambda kv: -kv[1][0] * kv[1][1])[:5]
    print(f'  объектов {len(objs)}, ковров {len(rugs)}, плоскостей {len(planes)}, текстур {len(tex_seen)}, крупнейшие {big}', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--scene', action='append', required=True)
    ap.add_argument('--data', default=DEMO, help='данные витрины (demo-data.json); сервер рендера даёт файл с ОДНИМ вариантом снимка (T-20261117-19)')
    a = ap.parse_args()
    D = json.load(open(a.data, encoding='utf-8'))
    for s in a.scene:
        name, idx = s.split('=')
        print(f'сцена {name} (вариант {idx})', flush=True)
        main_export(D, int(idx), os.path.join(a.out, name))
