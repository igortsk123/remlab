"""Атомарная запись выходных файлов сборки демо (T-20261105-59).

ЗАЧЕМ. `demo-data.json` и соседние json писались `json.dump(..., open(path, 'w'))`: файл обрезается в ноль и
пишется заново. Упала сборка посреди записи (сторож памяти, тайм-аут, нехватка места) — на диске остаётся
обрывок, и `publish_demo.sh` честно увозит его на прод. Здесь пишем во временный файл В ТОЙ ЖЕ ПАПКЕ
(иначе rename — не атомарный перенос между дисками), сбрасываем на диск и подменяем `os.replace`:
читатель видит либо старый файл целиком, либо новый целиком. Ошибка — временный файл убран, старый цел.

  python atomic_io.py --selftest
"""
from __future__ import annotations

import json
import os
import sys
import tempfile


def write_text(path: str, text: str, encoding: str = 'utf-8') -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:  # права как у прежнего файла (mkstemp даёт 0600 — веб-сервер и rsync увезли бы «только владельцу»)
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except FileNotFoundError:
            os.chmod(tmp, 0o666 & ~_umask())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def write_json(path: str, obj, **kw) -> None:
    """`json.dumps` целиком в памяти (ошибка сериализации — до касания диска), затем `write_text`."""
    write_text(path, json.dumps(obj, **kw))


def _umask() -> int:
    m = os.umask(0)
    os.umask(m)
    return m


def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('atomic_io-selftest')
    import stat
    bad = []

    def ok(cond, msg):
        print(('OK   ' if cond else 'FAIL ') + msg)
        if not cond:
            bad.append(msg)

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'demo-data.json')
        write_json(p, {'a': 1}, ensure_ascii=False)
        ok(json.load(open(p)) == {'a': 1}, 'новый файл записан')
        mode = stat.S_IMODE(os.stat(p).st_mode)
        ok(mode & 0o044 == 0o044 or _umask() & 0o044, f'права нового файла по umask, не 0600 ({oct(mode)})')
        os.chmod(p, 0o644)
        ino = os.stat(p).st_ino
        write_json(p, {'a': 'кириллица'}, ensure_ascii=False, indent=1)
        ok(json.load(open(p, encoding='utf-8')) == {'a': 'кириллица'}, 'перезапись: новое содержимое целиком')
        ok(os.stat(p).st_ino != ino, 'перезапись — подменой (новый inode), не обрезкой старого')
        ok(stat.S_IMODE(os.stat(p).st_mode) == 0o644, 'права прежнего файла сохранены')
        # ошибка сериализации — до диска: старый файл цел, мусора нет
        try:
            write_json(p, {'x': object()})
            ok(False, 'несериализуемое должно упасть')
        except TypeError:
            pass
        ok(json.load(open(p, encoding='utf-8')) == {'a': 'кириллица'}, 'ошибка сериализации: старый файл цел')
        # обрыв посреди записи (на диске места нет и т.п.) — старый цел, временный убран
        real = os.replace

        def boom(*a):
            raise OSError(28, 'No space left on device')
        os.replace = boom
        try:
            write_text(p, '{"half": ')
            ok(False, 'обрыв должен поднять ошибку')
        except OSError:
            pass
        finally:
            os.replace = real
        ok(json.load(open(p, encoding='utf-8')) == {'a': 'кириллица'}, 'обрыв записи: старый файл цел')
        ok(sorted(os.listdir(d)) == ['demo-data.json'], f'временных файлов не осталось: {os.listdir(d)}')
    print('итог:', 'OK' if not bad else f'FAIL ({len(bad)})')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        raise SystemExit(_selftest())
    raise SystemExit(__doc__)
