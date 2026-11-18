#!/usr/bin/env python3
"""ВХОДЫ КАДРА, КОТОРЫХ НЕТ В СНИМКЕ (T-20261118-09/1, решение директора 18.11): хеши ФАЙЛОВ, которые сцена читает с диска или с сайта.
Кадр и подготовленная сцена зависят не только от расстановки, но и от содержимого файлов: меш товара (GLB), картинки окружения и материалов,
фото-текстуры (ковёр, картины). Раньше ключ их не видел — правка файла при том же `sid`/имени отдавала старые кадры. `render_snapshot.canonicalize`
кладёт эти хеши в `brief` (а значит в `scene_hash`): перегенерация меша или замена картинки сдвигает ключ только тех комнат, где они стоят.

  mesh_sha(sid)        sha256 GLB меша товара. Источники по порядку: кэш мешей сервиса (`SCENE3D_CACHE` / `rules/dev-tmp.json`) →
                       галерея `~/scout-scenes/mesh-pilot-gallery/<sid>/model.glb` (то же, что отдаёт сайт). Файла нет (кэш вытеснил старые) —
                       ПОСЛЕДНИЙ ИЗВЕСТНЫЙ хеш из индекса `~/scout-cache/scene-inputs-sha.json`: иначе вытеснение из кэша сдвигало бы ключ и
                       перерисовывало (за деньги) комнату, где ничего не менялось. Нигде нет — '' (в контейнере прода дисков мешей нет: ключ не зависит от них).
  env_sha()            одним хешем: `public/flat3d/{env,materials,plants}` и `public/scene/views` — окружение, материалы отделки, растения
                       (их сцена берёт с диска этой копии репо, `demo_scene_dump.mjs`). Нет папки — ''.
  img_sha(rel)         файл `img/…` витрины (фото товара: ковёр, картины) в `DEMO_LOCAL_DIR` (по умолчанию `~/scout-scenes/flat215-demo`); нет — ''.

Хеш файла кэшируется в памяти по (путь, размер, время) — повторный заказ ничего не читает с диска. Всё из окружения (`SCENE_INPUTS_*`) — для тестов.
"""
import hashlib
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
_LOCK = threading.Lock()
_MEMO: dict = {}          # путь → ((размер, mtime_ns), sha)
_INDEX: dict | None = None
_ENV_MEMO: dict = {}


def _public() -> str:
    return os.environ.get('SCENE_INPUTS_PUBLIC') or os.path.join(REPO, 'public')


def _index_path() -> str:
    return os.environ.get('SCENE_INPUTS_INDEX') or os.path.expanduser('~/scout-cache/scene-inputs-sha.json')


def _mesh_cache_dir() -> str:
    env = os.environ.get('SCENE3D_CACHE')
    if env:
        return env
    try:
        cfg = json.load(open(os.path.join(HERE, 'rules', 'dev-tmp.json'), encoding='utf-8'))
        disk = os.path.expanduser(cfg.get('mesh3d_cache_dir') or '')
        if disk and os.path.isdir(os.path.dirname(disk)):
            return disk
    except (OSError, ValueError):
        pass
    return '/tmp/mesh3d-cache'


def _gallery_dir() -> str:
    return os.environ.get('SCENE_INPUTS_GALLERY') or os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')


def demo_dir() -> str:
    return os.environ.get('DEMO_LOCAL_DIR') or os.path.expanduser('~/scout-scenes/flat215-demo')


def file_sha(path: str) -> str:
    """sha256 файла (короткий, 16 знаков); нет файла — ''. Память по (размер, время изменения)."""
    try:
        st = os.stat(path)
    except OSError:
        return ''
    sig = (st.st_size, st.st_mtime_ns)
    with _LOCK:
        hit = _MEMO.get(path)
        if hit and hit[0] == sig:
            return hit[1]
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return ''
    sha = h.hexdigest()[:16]
    with _LOCK:
        _MEMO[path] = (sig, sha)
    return sha


def _load_index() -> dict:
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = json.load(open(_index_path(), encoding='utf-8'))
            if not isinstance(_INDEX, dict):
                _INDEX = {}
        except (OSError, ValueError):
            _INDEX = {}
    return _INDEX


def _save_index() -> None:
    try:
        p = _index_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f'{p}.tmp-{os.getpid()}-{threading.get_ident()}'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_INDEX, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, p)
    except OSError:
        pass


def mesh_sha(sid) -> str:
    sid = str(sid or '')
    if not sid or '/' in sid or sid.startswith('.'):
        return ''
    for p in (os.path.join(_mesh_cache_dir(), sid + '.glb'), os.path.join(_gallery_dir(), sid, 'model.glb')):
        if os.path.isfile(p) and os.path.getsize(p) > 1000:      # как `_scene3d_glb`: огрызок меньше 1 КБ — не меш
            sha = file_sha(p)
            if sha:
                with _LOCK:
                    idx = _load_index()
                    if idx.get(sid) != sha:
                        idx[sid] = sha
                        _save_index()
                return sha
    with _LOCK:
        return str(_load_index().get(sid) or '')


ENV_TTL_S = 20.0           # обход ~300 файлов — не на каждый заказ; правка картинки подхватывается за секунды, не мгновенно


def env_sha() -> str:
    root = _public()
    with _LOCK:
        hit = _ENV_MEMO.get(root)
    if hit and time.time() - hit[0] < ENV_TTL_S:
        return hit[1]
    sha = _env_sha(root)
    with _LOCK:
        _ENV_MEMO[root] = (time.time(), sha)
    return sha


def _env_sha(root: str) -> str:
    parts = []
    for sub in ('flat3d/env', 'flat3d/materials', 'flat3d/plants', 'scene/views'):
        base = os.path.join(root, sub)
        for dp, dn, fs in os.walk(base):
            dn.sort()
            for f in sorted(fs):
                p = os.path.join(dp, f)
                parts.append(f'{os.path.relpath(p, root)}:{file_sha(p)}')
    if not parts:
        return ''
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:16]


def img_sha(rel) -> str:
    """`rel` — путь фото товара как в данных (`img/<файл>` без ведущего слэша); защита от выхода из папки."""
    rel = str(rel or '').lstrip('/')
    if not rel or '..' in rel.split('/'):
        return ''
    return file_sha(os.path.join(demo_dir(), rel))
