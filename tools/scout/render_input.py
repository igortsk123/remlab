#!/usr/bin/env python3
"""ВХОД РЕНДЕРА КОМНАТЫ V2 И КЛЮЧ КАДРА ПО КОМНАТЕ (T-20261118-04/16/1, план `render-key-01`, этап 1; Codex `_intake/codex/2026-11-18-render-key-answer.md`).

Три разные вещи (раньше слитые в один `scene_hash`):
  метка выкладки (`data['build']`, git, правила экрана) — происхождение; в ключ кадра НЕ входит;
  scene_digest — отпечаток СЦЕНЫ ОДНОЙ комнаты: её полная проекция, выбранные предметы и декор, камеры + sha256 файлов, которые сцена реально читает;
  frame_key — scene_digest + программа рендера (renderer_digest) + пресет (preset_digest). Пространство кэша `room-frame/v2`; старый кэш v2 не считается.

  RenderInputV2 = {'schema', 'scene', 'assets'}:
    scene   — комната (всё, кроме названия), стиль, предметы и декор (всё, кроме цен, ссылок магазина, английских подписей), позы C1/C2, `soft_roles`.
              Порядок предметов НЕ сортируется (рендерер получает его как есть; сортировать можно только после устойчивых slot_id — этап 2).
    assets  — отсортированный список {kind, logical, sha256}: меш каждого предмета и декора, фото-текстуры (`img`, `img_art`), окружение (`outside.webp`),
              вид за окном (только выбранный), карты материалов отделки стен и пола (`finish-wall`, `finish-floor`, акцентная стена по стилю — запись и файлы),
              растения-кандидаты носителей комнаты (запись и GLB). Нет файла — `sha256: None` и строка в `missing` (ключ в строгом режиме откажет).
  Растение выбирает страница по геометрии горла носителя (`lib/viewer3d/kits/plants.ts:pickPlant`), поэтому до сборки сцены точный выбор неизвестен:
  объявляем ВСЕХ кандидатов подходящего типа и стиля (надмножество). Точный выбор и сверка фактического пакета — этап 2.
  renderer_digest — код программы рендера БЕЗ каталогов-данных: JS (`lib/viewer3d`, `lib/configurator`, выгрузчик, `data/flat3d/*.json`, где из `plants.json` убраны
              записи растений, а из `materials.json` — записи отделки: они едут активами комнат) + замыкание Python-импортов выгрузчика и Blender-скрипта + контракт + Blender.
  preset_digest — эффективный пресет (без `_doc`, `limits`, `min_gb`).

Сторож чтений (`check_reads`): дампер пишет `dump/reads.json` — {url, sha256, kind} каждого файла, что страница взяла; чтение вне `assets` комнаты, с другим sha256 или из сети — нарушение.
Самопроверка (без Blender и браузера): `python tools/scout/render_input.py --selftest`; на живых 16 вариантах: `--live`.
"""
import ast
import hashlib
import json
import os
import re
import threading
import time

import scene_inputs as SI

SPACE = 'room-frame/v2'
INPUT_VERSION = 2
SCENE_PREFIX = 'room-scene/v2\0'
HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, 'cycles_probe')

# коммерческие и справочные поля карточки: цена, ссылка, магазин, английские подписи — картинку не меняют
SKU_DROP = frozenset({'price', 'price_at', 'price_basis', 'url', 'shop', 'basis', 'name_en', 'colour_en', 'fam', 'dims_by', 'style_from'})
ROOM_DROP = frozenset({'title'})
FINISH_IDS = ('finish-wall', 'finish-floor')           # `lib/viewer3d/finish-textures.ts:IDS`
MATERIAL_URL_KEYS = ('baseColorUrl', 'baseColorLiteUrl', 'normalUrl', 'roughnessUrl', 'aoUrl', 'heightUrl', 'variationUrl', 'previewUrl')
_LOCK = threading.Lock()
_MEMO: dict = {}
TTL_S = 20.0
# файлы-данные ПРОГРАММЫ, что читает Python-выгрузчик (не репозиторные картинки): входят в renderer_digest; новое чтение файла из репо вне списка — нарушение сторожа
PROGRAM_DATA = ('tools/scout/rules/asset-strategies.json', 'services/planner-solver/rules/occupancy.json')
# служебное, на картинку не влияет: пути каталогов (dev-tmp.json), индекс хешей, кэш собственных текстур выгрузчика (по содержимому)
NEUTRAL_NAMES = frozenset({'dev-tmp.json', 'scene-inputs-sha.json'})
NEUTRAL_DIRS = ('/render-tex/',)


class MissingInput(Exception):
    """В строгом режиме: у сцены нет файла, который она читает — ключ не считаем (кадр под неверным ключом хуже отсутствующего)."""

    def __init__(self, missing: list):
        super().__init__('нет файлов входа рендера: ' + ', '.join(missing[:8]))
        self.missing = missing


def repo() -> str:
    return os.environ.get('RENDER_INPUT_REPO') or os.path.abspath(os.path.join(HERE, '..', '..'))


def canon_num(o):
    """ЕДИНЫЙ КАНОН ЧИСЕЛ НА ВХОДЕ КЛЮЧА (T-20261118-21/1): целое, записанное вещественным (`86.0`), — то же число, что `86`. Воркер (Python) пишет данные с `86.0`/`95.0`,
    приложение режет их через `JSON.parse/stringify` и отдаёт `86`/`95`; без этого один и тот же заказ получал два ключа (28 из 28 на свежем туре), а `section: 95.0`
    молча становился None. Применяется к ВХОДУ `render_snapshot.canonicalize` (данные и запрос), не к хешу: числа, которые снимок сам округляет (`_num` → float), остаются
    как были — ключи, посчитанные из целых данных приложения (туры), не сдвигаются. Нецелые, строки, bool, None — как есть."""
    if isinstance(o, dict):
        return {k: canon_num(x) for k, x in o.items()}
    if isinstance(o, (list, tuple)):
        return [canon_num(x) for x in o]
    if isinstance(o, float) and o == o and abs(o) < 2 ** 53 and o == int(o):
        return int(o)
    return o


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha(x) -> str:
    return hashlib.sha256(x if isinstance(x, bytes) else x.encode()).hexdigest()


def v2_on() -> bool:
    """Переключатель кэша кадров на v2 (включает директор после приёмки): `RENDER_KEY_V2=1`."""
    return os.environ.get('RENDER_KEY_V2', '0') == '1'


# ——— данные-каталоги (читаются как данные, не как код)
def _data_json(name: str) -> dict:
    try:
        with open(os.path.join(repo(), 'data', 'flat3d', name), encoding='utf-8') as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def accent_id(style) -> str | None:
    """Акцентная стена по стилю (`finish-textures.ts:ACCENT_BY_STYLE`): стиль → поверхность → id материала."""
    cfg = _data_json('finish-cc0.json')
    surface = ((cfg.get('accentWalls') or {}).get('styles') or {}).get(str(style or '').lower())
    return ((cfg.get('surfaces') or {}).get(surface) or {}).get('id') if surface else None


def _material_ids() -> set:
    cfg = _data_json('finish-cc0.json')
    ids = {(s or {}).get('id') for s in (cfg.get('surfaces') or {}).values()}
    ids |= {(cfg.get('surfaces') or {}).get(s, {}).get('id') for s in ((cfg.get('accentWalls') or {}).get('styles') or {}).values()}
    return {i for i in ids if i} | set(FINISH_IDS)


# ——— сцена
def _sku(sku: dict) -> dict:
    return {k: v for k, v in (sku or {}).items() if k not in SKU_DROP}


def _entry(o: dict) -> dict:
    out = {k: v for k, v in o.items() if k != 'sku'}
    if isinstance(o.get('sku'), dict):
        out['sku'] = _sku(o['sku'])
    return out


def scene_of(room: dict, variant: dict, cams: list, rules: dict | None = None) -> dict:
    sr = (rules or {}).get('soft_roles')
    return {'room': {k: v for k, v in (room or {}).items() if k not in ROOM_DROP}, 'style': variant.get('style') or '',
            'items': [_entry(i) for i in variant.get('items') or []], 'decor': [_entry(d) for d in variant.get('decor') or []],
            'cams': cams, 'soft_roles': sr if isinstance(sr, list) else None}


# ——— файлы, которые сцена читает
def _asset(kind: str, logical: str, path: str | None, out: list, extra: dict | None = None) -> None:
    s = SI.full_sha(path) if path else ''
    out.append({'kind': kind, 'logical': logical, 'sha256': s or None, **(extra or {})})


def _rec_asset(kind: str, logical: str, rec: dict | None, out: list) -> None:
    out.append({'kind': kind, 'logical': logical, 'sha256': sha(canon(rec)) if rec else None})


NO_MESH = frozenset({'procedural_plane', 'textile_abstract'})       # ковёр/картина/зеркало и ткань рисуются процедурно: файла меша у них часто нет, хоть `msid` в данных и есть


def _mesh_sid(row: dict, decor: bool) -> tuple:
    """→ (sid меша | None, обязателен ли файл). У процедурных (ковёр, ткань) файл не обязателен, но если он лежит на диске, страница его может взять (подушка) — тогда он в ключе."""
    import asset_strategy as AS
    sku = row.get('sku') or {}
    optional = (row.get('strategy') or AS.strategy(row.get('role'))) in NO_MESH
    sid = sku.get('msid') or (None if decor else sku.get('sid'))
    return (str(sid), not optional) if sid else (None, False)


def orient_pins(assets: list) -> tuple:
    """Записи разворота (`orient.json` прода) для мешей, которые комната реально читает (актив `mesh:` объявлен) → ({sid: запись | None}, [нет таблицы]). Python-выгрузчик читает ТОЛЬКО их
    (герметично): правка записи другого меша комнату не трогает, правка своей — меняет ключ. Нет таблицы вообще — комната не заказывается (раньше молча «разворотов нет»)."""
    sids = sorted(a['logical'][5:] for a in assets if a['kind'] == 'mesh')
    table = SI.orient_table()
    if table is None:
        return None, ['orient:table']
    return {sid: table.get(sid) for sid in sids}, []


DEFAULT_VIEW = 'yard'      # вид из окна по умолчанию = `DEFAULT_WINDOW_VIEW` страницы (`lib/viewer3d/window-views.ts`); тест `test_render_input.py` сверяет их


DOOR_KIT_MESH = 'kit-door'   # меш двери для комнат БЕЗ `openings_ir`: Python-выгрузчик берёт его всегда (`draft_render._fixture_openings` → `FIXTURE_MESH['дверь']`); тест сверяет имя


def has_window(room: dict) -> bool:
    """Есть ли у комнаты окно так, как его видит страница (`fromDemo.openings`: `kind: window`, ширина > 0) — только такая комната рисует вид из окна (`scene-export.ts`)."""
    return any(isinstance(o, dict) and o.get('kind') == 'window' and (o.get('width_cm') or 0) > 0 for o in (room.get('openings') or []))


def assets_of(scene: dict) -> list:
    out: list = []
    seen: set = set()

    def once(key) -> bool:
        if key in seen:
            return False
        seen.add(key)
        return True
    for decor, rows in ((False, scene['items']), (True, scene['decor'])):
        for r in rows:
            sku = r.get('sku') or {}
            sid, need = _mesh_sid(r, decor)
            if sid and once(('mesh', sid)) and (need or SI.mesh_file(sid)):
                _asset('mesh', f'mesh:{sid}', SI.mesh_file(sid), out)
            for k in ('img', 'img_art'):
                rel = sku.get(k)
                if rel and once(('img', rel)):
                    _asset('img', f'img:{rel}', SI.img_file(rel), out)
    room, style = scene['room'], scene['style']
    _asset('env', 'env:outside', SI.public_file('flat3d/env/outside.webp'), out)
    view = room.get('window_view')
    if not (view and re.fullmatch(r'[A-Za-z0-9._-]+', str(view))):
        view = DEFAULT_VIEW if has_window(room) else None        # у комнаты есть окно, а вида в данных нет (комнаты тура) — страница берёт вид по умолчанию и читает его файл: он во входе (T-20261118-22/5)
    if view:
        _asset('view', f'view:{view}', SI.public_file(f'scene/views/{view}.webp'), out)
    if not room.get('openings_ir') and once(('mesh', DOOR_KIT_MESH)) and SI.mesh_file(DOOR_KIT_MESH):      # нет описания проёмов со страницы (комнаты тура) — выгрузчик ставит дверь мешем набора и читает его файл
        _asset('mesh', f'mesh:{DOOR_KIT_MESH}', SI.mesh_file(DOOR_KIT_MESH), out)
    ft = ((((room.get('finish') or {}).get('floor') or {}).get('tex')) or {}).get('src')       # фактура пола ночной сборки: `draft_render._floor_image` берёт её с диска
    if isinstance(ft, str) and re.fullmatch(r'[a-z0-9-]{2,60}\.(?:webp|jpg|png)', ft) and once(('mat', ft)):
        _asset('material-map', f'material:{ft}', SI.public_file(f'flat3d/materials/{ft}'), out)
    # материалы отделки: записи finish-wall / finish-floor и акцентной стены стиля + их карты
    mats = {m.get('id'): m for m in (_data_json('materials.json').get('materials') or []) if isinstance(m, dict)}
    base = str(_data_json('materials.json').get('baseUrl') or '/flat3d/materials/')
    want = list(FINISH_IDS) + ([accent_id(style)] if accent_id(style) else [])
    for mid in want:
        rec = mats.get(mid)
        _rec_asset('material-record', f'material-record:{mid}', rec, out)
        for k in MATERIAL_URL_KEYS:
            v = (rec or {}).get(k)
            if isinstance(v, str) and once(('mat', os.path.basename(v))):
                rel = v.lstrip('/') if re.match(r'^https?:|^/', v) and not v.startswith('http') else (base.strip('/') + '/' + v)
                _asset('material-map', f'material:{os.path.basename(v)}', SI.public_file(rel), out)
    # растения: кандидаты носителей комнаты (тип — по роли носителя, стиль — any или стиль варианта)
    pl = _data_json('plants.json')
    hosts = pl.get('hosts') or {}
    base_role = lambda r: re.sub(r'\s+\d+$', '', str(r or '').strip())  # noqa: E731
    kinds = {hosts[base_role(r.get('role'))] for r in list(scene['items']) + list(scene['decor']) if base_role(r.get('role')) in hosts}
    styles = {str(style).lower()} | {str(x).lower() for x in (scene.get('style_id'),) if x}
    for p in pl.get('plants') or []:
        if p.get('kind') not in kinds:
            continue
        if 'any' not in (p.get('styles') or []) and not styles & {str(s).lower() for s in p.get('styles') or []}:
            continue
        _rec_asset('plant-record', f"plant-record:{p['id']}", p, out)
        if once(('plant', p['id'])):
            _asset('plant', f"plant:{p['id']}", SI.public_file(f"flat3d/plants/{p['id']}.glb"), out)
    out.sort(key=lambda a: (a['kind'], a['logical']))
    return out


def build(room: dict, variant: dict, cams: list, rules: dict | None = None) -> dict:
    """RenderInputV2 комнаты → {'schema', 'scene', 'assets', 'missing', 'digest'} (digest — scene_digest, 64 hex)."""
    scene = scene_of(room, variant, cams, rules)
    scene_for_assets = dict(scene, style_id=variant.get('style_id'))
    assets = assets_of(scene_for_assets)
    pins, no_orient = orient_pins(assets)
    scene['orient'] = pins
    missing = no_orient + [a['logical'] for a in assets if not a['sha256']]
    body = {'schema': SPACE, 'scene': scene, 'assets': assets}
    return {**body, 'missing': missing, 'digest': sha(SCENE_PREFIX + canon(body))}


# ——— программа рендера и пресет
def _py_closure(starts: list, roots: list) -> list:
    """Файлы репозитория, до которых доходят импорты `starts` (статический разбор, без запуска): [(относительный путь, путь)]."""
    seen: dict = {}
    todo = [p for p in starts if os.path.isfile(p)]

    def find(mod: str, base_dir: str | None, level: int) -> list:
        parts = mod.split('.') if mod else []
        bases = [base_dir] if level else roots
        if level:
            for _ in range(level - 1):
                bases = [os.path.dirname(bases[0])]
        res = []
        for b in bases:
            if not b:
                continue
            for cand in (os.path.join(b, *parts) + '.py', os.path.join(b, *parts, '__init__.py')):
                if parts and os.path.isfile(cand):
                    res.append(cand)
            for i in range(1, len(parts)):                      # пакеты по пути
                init = os.path.join(b, *parts[:i], '__init__.py')
                if os.path.isfile(init):
                    res.append(init)
        return res
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen[p] = True
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except (OSError, SyntaxError, ValueError):
            continue
        for n in ast.walk(tree):
            mods: list = []
            if isinstance(n, ast.Import):
                mods = [(a.name, 0) for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods = [(n.module or '', n.level)] + [((n.module + '.' if n.module else '') + a.name, n.level) for a in n.names]
            for m, lv in mods:
                for f in find(m, os.path.dirname(p), lv):
                    if f not in seen:
                        todo.append(f)
    r = repo()
    return sorted((os.path.relpath(p, r), p) for p in seen)


def _js_files() -> list:
    r = repo()
    out = []
    for sub in ('lib/viewer3d', 'lib/configurator'):
        for dp, dn, fs in os.walk(os.path.join(r, sub)):
            dn.sort()
            out += [os.path.join(dp, f) for f in sorted(fs) if f.endswith(('.ts', '.tsx', '.json'))]
    for f in ('demo_scene_entry.ts', 'build_entry.mjs', 'demo_scene_dump.mjs', 'file_sig.mjs'):
        out.append(os.path.join(r, 'tools', 'scout', 'cycles_probe', f))
    d = os.path.join(r, 'data', 'flat3d')
    for dp, dn, fs in os.walk(d):
        dn[:] = sorted(x for x in dn if x != 'plants')            # каталоги исходников растений — не код программы (растения едут активами комнат)
        out += [os.path.join(dp, f) for f in sorted(fs) if f.endswith('.json')]
    return out


def _program_json(path: str) -> str:
    """Каталоги-данные в коде программы: без записей, что едут активами комнат (растения, материалы отделки); `runtime-meshes.json` — метаданные, картинку не меняет."""
    name = os.path.basename(path)
    if name == 'runtime-meshes.json':
        return 'skip'
    try:
        d = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return SI.full_sha(path)
    if name == 'plants.json' and isinstance(d, dict):
        d = {k: v for k, v in d.items() if k not in ('plants', 'rev')}
    elif name == 'materials.json' and isinstance(d, dict):
        ids = _material_ids()
        d = {k: v for k, v in d.items() if k not in ('materials', '_seal')}
        d['materials_other'] = sorted(canon(m) for m in _data_json('materials.json').get('materials') or [] if isinstance(m, dict) and m.get('id') not in ids)
    return sha(canon(d))


def renderer_parts(blender: str = '') -> dict:
    key = ('parts', repo(), blender)
    with _LOCK:
        hit = _MEMO.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    r = repo()
    js = []
    for p in _js_files():
        rel = os.path.relpath(p, r)
        s = _program_json(p) if os.path.dirname(rel) == os.path.join('data', 'flat3d') and os.path.basename(p) in ('plants.json', 'materials.json', 'runtime-meshes.json') else SI.full_sha(p)
        if s != 'skip':
            js.append(f'{rel}:{s}')
    roots = [os.path.join(r, 'tools', 'scout', 'cycles_probe'), os.path.join(r, 'tools', 'scout'), os.path.join(r, 'services', 'planner-solver')]
    starts = [os.path.join(roots[0], n) for n in ('export_scene.py', 'render_cycles.py', 'export_server.py')]
    py = [f'{rel}:{SI.full_sha(p)}' for rel, p in _py_closure(starts, roots)]
    rules = [f'{rel}:{SI.full_sha(os.path.join(r, rel))}' for rel in PROGRAM_DATA]
    m = re.search(r'SCENE_EXPORT_VERSION\s*=\s*(\d+)', _read(os.path.join(r, 'lib', 'viewer3d', 'scene-export.ts')))
    parts = {'js': sha('\n'.join(js)), 'py': sha('\n'.join(py)), 'rules': sha('\n'.join(rules)), 'scene_export': m.group(1) if m else '', 'input': INPUT_VERSION, 'blender': blender,
             'n_js': len(js), 'n_py': len(py)}
    with _LOCK:
        _MEMO[key] = (time.time(), parts)
    return parts


def program_files(blender: str = '') -> dict:
    """Какие файлы программы входят в renderer_digest (без хешей): {'py': [путь от корня репо], 'js': [...], 'rules': [...]}. Для сверки «читаемое Blender-этапом покрыто программой» (`tools/ops/render_inputs.py`)."""
    r = repo()
    roots = [os.path.join(r, 'tools', 'scout', 'cycles_probe'), os.path.join(r, 'tools', 'scout'), os.path.join(r, 'services', 'planner-solver')]
    starts = [os.path.join(roots[0], n) for n in ('export_scene.py', 'render_cycles.py', 'export_server.py')]
    js = [os.path.relpath(p, r) for p in _js_files() if not (os.path.basename(p) == 'runtime-meshes.json' and os.path.dirname(os.path.relpath(p, r)) == os.path.join('data', 'flat3d'))]
    return {'py': sorted(rel for rel, _ in _py_closure(starts, roots)), 'js': sorted(js), 'rules': list(PROGRAM_DATA)}


def _read(p: str) -> str:
    try:
        return open(p, encoding='utf-8').read()
    except OSError:
        return ''


def renderer_digest(blender: str = '') -> str:
    p = renderer_parts(blender)
    return sha(canon({k: v for k, v in p.items() if not k.startswith('n_')}))


def preset_digest(preset: dict) -> str:
    return sha(canon({k: v for k, v in preset.items() if k not in ('_doc', 'limits', 'min_gb')}))


def clear_memo() -> None:
    with _LOCK:
        _MEMO.clear()


def frame_key(scene_digest: str, renderer: str, preset: str) -> str:
    """Ключ кадров комнаты: 32 hex (как раньше — адреса кадров `/render/cycles/frame/<32 hex>/C1.jpg`), из полного SHA-256 по `room-frame/v2`."""
    return sha(f'{SPACE}\0{scene_digest}\0{renderer}\0{preset}')[:32]


# ——— сторож чтений дампера
_URL_RULES = (
    (re.compile(r'^/test/mesh-pilot10/([^/]+)/model\.glb$'), lambda m: f'mesh:{m.group(1)}'),
    (re.compile(r'^/demo/(img/[A-Za-z0-9._-]+)$'), lambda m: f'img:{m.group(1)}'),
    (re.compile(r'^/flat3d/materials/([A-Za-z0-9._-]+)$'), lambda m: f'material:{m.group(1)}'),
    (re.compile(r'^/flat3d/plants/([A-Za-z0-9._-]+)\.glb$'), lambda m: f'plant:{m.group(1)}'),
    (re.compile(r'^/flat3d/env/outside\.webp$'), lambda m: 'env:outside'),
    (re.compile(r'^/scene/views/([A-Za-z0-9._-]+)\.webp$'), lambda m: f'view:{m.group(1)}'),
)


def logical_of(url: str) -> str | None:
    u = url.split('?')[0]
    for rx, f in _URL_RULES:
        m = rx.match(u)
        if m:
            return f(m)
    return None


def check_reads(inp: dict, reads: dict) -> list:
    """Чтения дампера против входа комнаты → список нарушений (пусто — чисто). `reads` — содержимое `dump/reads.json`."""
    declared = {a['logical']: a for a in inp['assets']}
    bad = []
    for r in (reads or {}).get('reads') or []:
        url = str(r.get('url') or '')
        if r.get('kind') == 'remote':
            bad.append(f'сеть: {url}')
            continue
        if r.get('kind') == 'pinned':                       # зафиксированная таблица runtime-мешей (метаданные, не картинка)
            continue
        lg = logical_of(url)
        if lg is None:
            bad.append(f'неизвестный адрес: {url}')
        elif lg not in declared:
            bad.append(f'вне входа: {lg}')
        elif declared[lg]['sha256'] != r.get('sha256'):
            bad.append(f'другой файл: {lg} (в ключе {str(declared[lg]["sha256"])[:10]}, прочитан {str(r.get("sha256"))[:10]})')
    return bad


# ——— сторож чтений Python-выгрузчика (`cycles_probe/read_guard.py` пишет `reads-py.json` рядом с каталогом сцены)
def logical_of_path(path: str) -> str | None:
    """Путь прочитанного файла → логический id входа (меш, картинка витрины, файл public) или `program:<путь>` для данных программы."""
    p = os.path.normpath(path)
    pairs = ((os.path.normpath(SI._mesh_cache_dir()), 'mesh-cache'), (os.path.normpath(SI._gallery_dir()), 'gallery'), (os.path.normpath(SI.demo_dir()), 'demo'),
             (os.path.normpath(SI._public()), 'public'))
    for base, kind in pairs:
        if p.startswith(base + os.sep):
            rel = p[len(base) + 1:]
            if kind == 'mesh-cache' and '/' not in rel and rel.endswith('.glb'):
                return f'mesh:{rel[:-4]}'
            if kind == 'gallery' and rel.endswith('/model.glb') and rel.count('/') == 1:
                return f'mesh:{rel.split("/")[0]}'
            if kind == 'demo' and rel.startswith('img/'):
                return f'img:{rel}'
            if kind == 'public':
                return logical_of('/' + rel)
    rr = os.path.normpath(repo())
    if p.startswith(rr + os.sep) and p[len(rr) + 1:] in PROGRAM_DATA:
        return f'program:{p[len(rr) + 1:]}'
    return None


def check_reads_py(inp: dict, reads: dict) -> list:
    """Чтения Python-выгрузчика (`reads-py.json` = {v, hermetic, violations, reads:[{path, sha256, kind}]}) против входа комнаты → нарушения. Меш, картинка, материал — как у дампера
    (логический id в `assets`, тот же sha256); данные программы — тот же файл, что в renderer_digest; сеть и всё остальное в репо/на диске — нарушение."""
    declared = {a['logical']: a for a in inp['assets']}
    bad = [f'выгрузчик: {v}' for v in (reads or {}).get('violations') or []]
    for r in (reads or {}).get('reads') or []:
        path = str(r.get('path') or '')
        if os.path.basename(path) in NEUTRAL_NAMES or any(d in path for d in NEUTRAL_DIRS):
            continue
        lg = logical_of_path(path)
        if lg is None:
            bad.append(f'выгрузчик читал неизвестный файл: {path}')
        elif lg.startswith('program:'):
            if SI.full_sha(path) != r.get('sha256'):
                bad.append(f'другой файл данных программы: {lg}')
        elif lg not in declared:
            bad.append(f'выгрузчик: вне входа: {lg}')
        elif declared[lg]['sha256'] != r.get('sha256'):
            bad.append(f'выгрузчик: другой файл: {lg} (в ключе {str(declared[lg]["sha256"])[:10]}, прочитан {str(r.get("sha256"))[:10]})')
    return bad


# ——— Blender-этап: карты материалов, которые он берёт из public/ по scene-export.json (`render_cycles.py:finish_material` → `PUB/<maps[key]>`)
def check_blender_maps(inp: dict, exp: dict) -> list:
    """Каждая карта в `maps` поверхностей `scene-export.json` — файл `public/…`, который прочитает Blender, — должна быть активом комнаты (`material:<файл>`) с тем же sha256: иначе правка карты
    отдала бы старый кадр под прежним ключом. Остальное Blender читает из каталога сцены и дампа (их собрали выгрузчик и дампер под сторожами) и из программы (renderer_digest)."""
    declared = {a['logical']: a for a in inp['assets']}
    bad, seen = [], set()

    def note(v: str) -> None:
        lg = 'material:' + os.path.basename(v)
        if lg in seen:
            return
        seen.add(lg)
        a = declared.get(lg)
        f = SI.public_file(v.lstrip('/'))
        if a is None:
            bad.append(f'Blender: карта вне входа: {lg}')
        elif f and SI.full_sha(f) != a['sha256']:
            bad.append(f'Blender: карта другая, чем в ключе: {lg}')

    def walk(o) -> None:
        if isinstance(o, dict):
            m = o.get('maps')
            if isinstance(m, dict):
                for v in m.values():
                    if isinstance(v, str) and v.startswith('/'):
                        note(v)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(exp)
    return bad
