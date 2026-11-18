"""СТОРОЖ ЧТЕНИЙ PYTHON-ВЫГРУЗЧИКА (T-20261118-04/17/1, план `render-key-01`, этап 1б).

Ключ кадра v2 (`render_input.py`) честен, пока ВСЁ, что выгрузчик (`export_scene.main_export`) читает, лежит во входе комнаты. Дампер (Chromium) это уже пишет в `dump/reads.json`;
здесь — то же для Python: на время заказа с `data['hermetic']` хук аудита Python (`sys.addaudithook`) пишет каждое открытие файла на чтение и ЗАПРЕЩАЕТ сеть (`socket.connect`,
`getaddrinfo`, `urllib.Request`): попытка — нарушение в списке + исключение. Исключение код выгрузчика может проглотить (`except Exception` → «нет фото»), поэтому нарушение остаётся
в `reads-py.json` = {v, hermetic, violations, reads:[{path, sha256, kind:'local'}]}, и заказ отказывает по нему (`render_exec.check_export_reads`).

Рядом с каталогом сцены (`<job>/reads-py.json`, не внутри `scene/`: пакет задания GPU этот файл не везёт). Выключено (нет `hermetic`) — хук ничего не делает.
Хук ставится один раз на процесс (постоянный процесс выгрузки живёт между заказами); `begin`/`end` включают его на один заказ.
"""
import hashlib
import json
import os
import sys
import threading

_LOCK = threading.Lock()
_S: dict = {'on': False, 'reads': {}, 'viol': [], 'installed': False, 'skip': ()}
# системное и библиотеки Python: на картинку не влияют (исходники самой программы — в renderer_digest)
_SKIP_PREFIX = ('/usr/', '/proc/', '/sys/', '/lib/', '/lib64/', '/etc/', '/dev/', '/opt/', '/run/', '/var/')
_SKIP_SUFFIX = ('.py', '.pyc', '.so', '.pth')
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _under(p: str, d: str) -> bool:
    return bool(d) and (p == d or p.startswith(d.rstrip(os.sep) + os.sep))


def _hook(ev: str, args: tuple) -> None:
    if not _S['on']:
        return
    if ev == 'open':
        path, mode, flags = (list(args) + [None, None])[:3]
        if not isinstance(path, (str, bytes, os.PathLike)):
            return                                          # открытие по дескриптору
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & _WRITE_FLAGS):
            return                                          # запись
        p = os.path.abspath(os.fsdecode(path))
        if p.startswith(_SKIP_PREFIX) or p.endswith(_SKIP_SUFFIX) or '/__pycache__/' in p or '/site-packages/' in p or '/venvs/' in p:
            return
        if any(_under(p, d) for d in _S['skip']):
            return
        with _LOCK:
            _S['reads'][p] = True
    elif ev == 'socket.connect':
        addr = args[1] if len(args) > 1 else None
        if isinstance(addr, tuple):                         # AF_INET/INET6; unix-сокеты (str) — свои процессы, не сеть
            _violate(f'сеть: connect {addr[0]}:{addr[1] if len(addr) > 1 else ""}')
    elif ev == 'socket.getaddrinfo':
        _violate(f'сеть: getaddrinfo {args[0]}')
    elif ev == 'urllib.Request':
        _violate(f'сеть: {args[0]}')


def _violate(msg: str) -> None:
    with _LOCK:
        if msg not in _S['viol']:
            _S['viol'].append(msg)
    raise RuntimeError('герметичный выгрузчик: ' + msg)


def violation(msg: str) -> None:
    """Нарушение, найденное самим кодом (например, фото не из витрины) — без исключения: код идёт дальше как без файла, заказ откажет по списку."""
    with _LOCK:
        if msg not in _S['viol']:
            _S['viol'].append(msg)


def begin(out: str, D: dict) -> bool:
    """Включить сторож на заказ (`D['hermetic']`); `out` — каталог сцены заказа (его чтения — свои, не входы)."""
    if not (D or {}).get('hermetic'):
        return False
    with _LOCK:
        if not _S['installed']:
            sys.addaudithook(_hook)
            _S['installed'] = True
        _S.update(reads={}, viol=[], skip=(os.path.abspath(os.path.dirname(out.rstrip(os.sep)) or '.'),), on=True)
    return True


def end(out: str) -> dict | None:
    """Выключить, посчитать sha256 прочитанного, записать `<job>/reads-py.json`. → отчёт или None, если сторож не был включён."""
    with _LOCK:
        if not _S['on']:
            return None
        _S['on'] = False
        paths, viol = sorted(_S['reads']), list(_S['viol'])
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    import scene_inputs as SI
    reads = [{'path': p, 'sha256': SI.full_sha(p) or None, 'kind': 'local'} for p in paths]
    rep = {'v': 1, 'hermetic': True, 'violations': viol, 'reads': reads}
    dst = os.path.join(os.path.dirname(out.rstrip(os.sep)), 'reads-py.json')
    tmp = dst + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False)
    os.replace(tmp, dst)
    return rep


def _selftest() -> int:
    import tempfile
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + 'read_guard: ' + name)
        bad += 0 if c else 1
    d = tempfile.mkdtemp(prefix='rg-')
    a, b = os.path.join(d, 'a.txt'), os.path.join(d, 'sub')
    os.makedirs(b)
    open(a, 'w').write('x')
    out = os.path.join(d, 'job', 'scene')
    os.makedirs(out)
    open(os.path.join(d, 'job', 'own.txt'), 'w').write('y')
    ok(begin(out, {}) is False, 'без hermetic — выключен')
    ok(begin(out, {'hermetic': 1}) is True, 'с hermetic — включён')
    open(a).read()
    open(os.path.join(d, 'job', 'own.txt')).read()          # свой каталог заказа — не вход
    open(os.path.join(d, 'w.txt'), 'w').write('z')           # запись — не чтение
    import socket
    err = ''
    try:
        socket.create_connection(('127.0.0.1', 9), timeout=1)
    except RuntimeError as e:
        err = str(e)
    except OSError:
        err = 'passed'
    ok('герметичный' in err, 'сеть запрещена (исключение)')
    try:
        import urllib.request
        urllib.request.urlopen('http://example.invalid/x', timeout=1)
    except RuntimeError:
        pass
    except Exception:  # noqa: BLE001
        pass
    violation('своё нарушение')
    rep = end(out)
    ps = [r['path'] for r in rep['reads']]
    ok(a in ps and len(ps) == 1, f'прочитан только a.txt ({[os.path.basename(p) for p in ps]})')
    ok(rep['reads'][0]['sha256'] == hashlib.sha256(b'x').hexdigest(), 'sha256 файла')
    ok(any('127.0.0.1' in v for v in rep['violations']) and any('example.invalid' in v for v in rep['violations']), f'нарушения сети записаны ({rep["violations"]})')
    ok('своё нарушение' in rep['violations'], 'нарушение кода записано')
    ok(os.path.isfile(os.path.join(d, 'job', 'reads-py.json')) and json.load(open(os.path.join(d, 'job', 'reads-py.json')))['v'] == 1, 'reads-py.json лежит рядом с каталогом сцены')
    open(a).read()
    ok(end(out) is None, 'после end — выключен, чтения не пишутся')
    return bad


if __name__ == '__main__':
    sys.exit(1 if _selftest() else 0)
