"""Сторож процессов стенда паритета (room-pipeline-01 Б-3, T-20261105-41): ставится через `sitecustomize` в КАЖДЫЙ
Python-процесс стенда (сам стенд, compose2, экзамен и его солверы, сборка демо).

ЗАЧЕМ (уроки 525–527). Стенд гоняет код гостиной в отдельной копии на замороженных данных. Три способа соврать:
  1. запись мимо копии — в основную копию или живое демо (урок 526: «оверлей» со ссылками писал в main, страницу публикует крон);
  2. вход мимо копии — код читает файл основной копии по абсолютному пути, или нужного файла в копии нет и код молча
     берёт запасное значение (урок 525);
  3. сеть — индекс мешей и развороты прода меняются в течение дня: «до» и «после» видели бы разное.
Сторож: (1) запись только в разрешённые корни, иначе PermissionError + строка в журнал; файл-жёсткая ссылка на замороженные
данные перед записью заменяется своей копией (данные не портятся); (2) каждое чтение — в журнал (путь, был ли файл);
(3) `urllib.request.urlopen` — запись ответов на эталоне, воспроизведение на сверке (нет записи — отказ запроса и строка).

Включается переменными окружения (их ставит `parity_living.py`); без `PARITY_ROOT` ничего не делает.
"""
import hashlib
import json
import os
import sys
import threading

_tls = threading.local()
_STATE: dict = {}


def _norm_url(url: str) -> str:
    """Ключ записи сети: адрес без параметров «мимо кэша» (`v`, `_`, `t`) — иначе каждый прогон был бы новым запросом."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    s = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if k not in ('v', '_', 't')]
    return urlunsplit((s.scheme, s.netloc, s.path, urlencode(q), ''))


def net_key(url: str) -> str:
    return hashlib.sha1(_norm_url(url).encode()).hexdigest()


def _log(kind: str, **kw) -> None:
    fd = _STATE.get('fd')
    if fd is None:
        return
    line = json.dumps({'k': kind, 'pid': os.getpid(), **kw}, ensure_ascii=False) + '\n'
    os.write(fd, line.encode())       # os.write — без события аудита, без рекурсии


def _real(p) -> str | None:
    if isinstance(p, int):
        return None
    try:
        p = os.fsdecode(p)
    except TypeError:
        return None
    return os.path.realpath(p)


def _under(path: str, roots) -> bool:
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def _writing(mode, flags) -> bool:
    if isinstance(mode, str) and any(c in mode for c in 'wax+'):
        return True
    if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        return True
    return False


def _deny(op: str, path: str) -> None:
    _log('deny', op=op, path=path)
    raise PermissionError(f'стенд паритета: {op} {path} — запись вне копии стенда запрещена (parity_guard)')


def _cow(path: str) -> None:
    """Жёсткая ссылка на замороженные данные → своя копия до записи (open('w') иначе испортил бы замороженный файл)."""
    try:
        st = os.stat(path)
    except OSError:
        return
    if st.st_nlink > 1 and os.path.isfile(path):
        import shutil
        tmp = f'{path}.parity-cow-{os.getpid()}'
        shutil.copy2(path, tmp)
        os.replace(tmp, path)
        _log('cow', path=path)


def _check_write(op: str, p) -> None:
    path = _real(p)
    if path is None:
        return
    # решает самый длинный подходящий корень: запись ответов сети лежит внутри замороженных данных (deny), но разрешена
    best = max(((len(r), kind) for kind in ('allow', 'deny') for r in _STATE[kind] if _under(path, [r])), default=(0, 'deny'))
    if best[1] == 'deny':
        _deny(op, path)
    if _under(path, _STATE['stand']):
        _cow(path)


def _hook(event: str, args) -> None:
    if getattr(_tls, 'busy', False) or not _STATE:
        return
    _tls.busy = True
    try:
        if event == 'open':
            path, mode, flags = (list(args) + [None, None, None])[:3]
            if _writing(mode, flags):
                _check_write('open', path)
            else:
                rp = _real(path)
                if rp and rp not in _STATE['seen'] and not rp.startswith(('/proc/', '/dev/', '/sys/')):
                    _STATE['seen'].add(rp)
                    _log('read', path=rp, exists=os.path.exists(rp))
        elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.truncate', 'os.chmod', 'os.utime', 'shutil.rmtree'):
            _check_write(event, args[0])
        elif event in ('os.rename', 'os.link', 'os.symlink', 'shutil.copyfile', 'shutil.copytree', 'shutil.move'):
            _check_write(event, args[1])
        elif event == 'subprocess.Popen':
            argv = args[1]
            _log('exec', argv=[os.fsdecode(a) for a in (argv if isinstance(argv, (list, tuple)) else [argv])][:8])
        elif event == 'socket.connect':
            addr = args[1]
            if isinstance(addr, tuple) and addr and addr[0] not in ('127.0.0.1', '::1', 'localhost') \
                    and not getattr(_tls, 'net', False):
                _log('socket', addr=str(addr[:2]))
    finally:
        _tls.busy = False


def _patch_urlopen(mode: str, store: str) -> None:
    import io
    import urllib.error
    import urllib.request
    import urllib.response
    from email.message import Message
    real = urllib.request.urlopen

    def urlopen(url, *a, **kw):
        full = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)
        key = net_key(full)
        body_p, meta_p = os.path.join(store, key + '.bin'), os.path.join(store, key + '.json')
        if mode == 'replay':
            if not os.path.exists(meta_p):
                _log('net_miss', url=_norm_url(full))
                raise urllib.error.URLError(f'стенд паритета: нет записи ответа {_norm_url(full)}')
            meta = json.load(open(meta_p, encoding='utf-8'))
            _log('net', url=meta['url'], ok=meta['ok'])
            if not meta['ok']:
                raise urllib.error.URLError(meta.get('err', 'ошибка при записи'))
            body = open(body_p, 'rb').read()
        else:
            _tls.net = True                   # соединения самой записи — не «мимо записи»
            try:
                with real(url, *a, **kw) as f:
                    body = f.read()
                meta = {'url': _norm_url(full), 'ok': True, 'sha': hashlib.sha256(body).hexdigest()}
                open(body_p, 'wb').write(body)
            except Exception as e:  # noqa: BLE001 — ошибку тоже записываем: на сверке она повторится
                meta = {'url': _norm_url(full), 'ok': False, 'err': repr(e)[:300]}
            finally:
                _tls.net = False
            json.dump(meta, open(meta_p, 'w', encoding='utf-8'), ensure_ascii=False)
            _log('net', url=meta['url'], ok=meta['ok'], rec=True)
            if not meta['ok']:
                raise urllib.error.URLError(meta['err'])
        return urllib.response.addinfourl(io.BytesIO(body), Message(), full, 200)

    urllib.request.urlopen = urlopen


LIVE_DB = 'remlab'

def route_db(argv, db: str):
    """Вызов `docker exec … remlab-devdb psql` → замороженная копия базы `db` (вместо живой `remlab`). Код конвейера не меняем:
    одни читатели берут `REMLAB_DEVDB_NAME`, другие пишут `-d remlab` в коде — перехватываем все. → (argv, routed: bool|None)
    None — вызов не к базе; False — к базе, но не к живой (`-d postgres` и т.п.)."""
    import re
    if isinstance(argv, (str, bytes)):
        a = os.fsdecode(argv)
        if 'remlab-devdb' not in a:
            return argv, None
        b, n = re.subn(r'(remlab-devdb\s+(?:psql|pg_dump)\b[^|;&]*?(?:-d\s+|--dbname=))' + LIVE_DB + r'\b', r'\g<1>' + db, a)
        return b, bool(n)
    if not isinstance(argv, (list, tuple)):
        return argv, None
    a = [os.fsdecode(x) if isinstance(x, (str, bytes)) else x for x in argv]
    if 'remlab-devdb' not in a:
        return argv, None
    i = next((k for k, x in enumerate(a) if isinstance(x, str) and os.path.basename(x) in ('psql', 'pg_dump')), None)
    if i is None:
        return argv, None
    for k in range(i + 1, len(a)):
        if a[k] in ('-d', '--dbname') and k + 1 < len(a):
            if a[k + 1] == db:               # уже в копии (читатель взял REMLAB_DEVDB_NAME)
                return argv, True
            if a[k + 1] != LIVE_DB:
                return argv, False
            return a[:k + 1] + [db] + a[k + 2:], True
        if isinstance(a[k], str) and a[k].startswith('--dbname='):
            return (a[:k] + [f'--dbname={db}'] + a[k + 1:], True) if a[k] == f'--dbname={LIVE_DB}' else (argv, False)
    return a[:i + 1] + ['-d', db] + a[i + 1:], True        # без -d psql берёт базу по имени пользователя (remlab)


def _patch_popen(db: str) -> None:
    import subprocess
    real_init = subprocess.Popen.__init__

    def __init__(self, args, *a, **kw):
        new, routed = route_db(args, db)
        if routed is not None:
            _log('db', routed=routed, argv=[str(x) for x in (new if isinstance(new, (list, tuple)) else [new])][:10])
        return real_init(self, new, *a, **kw)
    subprocess.Popen.__init__ = __init__


def install() -> None:
    root = os.environ.get('PARITY_ROOT')
    if not root or _STATE:
        return
    stand = os.path.realpath(root)
    split = lambda v: [os.path.realpath(os.path.expanduser(x)) for x in v.split(os.pathsep) if x]  # noqa: E731
    allow = [stand] + split(os.environ.get('PARITY_ALLOW', ''))
    deny = split(os.environ.get('PARITY_DENY', ''))
    os.makedirs(os.path.join(stand, '_trace'), exist_ok=True)
    fd = os.open(os.path.join(stand, '_trace', f'trace-{os.getpid()}.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    _STATE.update(stand=[stand], allow=allow, deny=deny, fd=fd, seen=set())
    net = os.environ.get('PARITY_NET', '')
    if net in ('record', 'replay'):
        store = os.path.realpath(os.environ['PARITY_NET_DIR'])
        os.makedirs(store, exist_ok=True) if net == 'record' else None
        if net == 'record':
            _STATE['allow'].append(store)
        _patch_urlopen(net, store)
    if os.environ.get('PARITY_DB'):
        _patch_popen(os.environ['PARITY_DB'])
    _log('start', argv=sys.argv[:6], cwd=os.getcwd())
    sys.addaudithook(_hook)


SITECUSTOMIZE = '''# стенд паритета: сторож процессов (tools/scout/parity_guard.py, копия на время прогона)
import importlib.util as _u, os as _os
_p = _os.environ.get("PARITY_GUARD")
if _p and _os.path.exists(_p):
    _s = _u.spec_from_file_location("parity_guard", _p); _m = _u.module_from_spec(_s); _s.loader.exec_module(_m); _m.install()
'''
