#!/usr/bin/env python3
"""УБОРКА ЗАДАНИЙ МАШИНЫ РЕНДЕРА на приёмнике (T-20261117-24/2): каталоги `renderjobs/<задание>` старше N часов (по умолчанию 24).

Только префикс `renderjobs` — меши и всё остальное не трогаем (чужой префикс в аргументах отвергается). Удаление — через `DELETE /prefix/…` приёмника
(счётчик каталога приёмника сходится только так, см. `salad/receiver_purge.py`). По умолчанию показывает, что удалил бы; удаляет только с `--apply`.

    ~/venvs/scout/bin/python jobs_purge.py                 # показать
    ~/venvs/scout/bin/python jobs_purge.py --apply         # удалить старше RENDERJOBS_KEEP_H (24 ч)
    ~/venvs/scout/bin/python jobs_purge.py --apply --hours 6
    ~/venvs/scout/bin/python jobs_purge.py --selftest

Крон (строку ставит директор): `17 * * * *  <venv>/python <репо>/tools/scout/render_gpu/jobs_purge.py --apply >> ~/remlab-logs/renderjobs-purge.log 2>&1`"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, '..', 'salad'))
import jobs_proto as JP  # noqa: E402

KEEP_H = float(os.environ.get('RENDERJOBS_KEEP_H', '24'))


def old_jobs(listing: dict, now: float, keep_h: float) -> list:
    """Имена каталогов старше keep_h (по mtime каталога; свежие — в работе — не трогаем). Чистая функция."""
    return sorted(d['name'] for d in listing.get('dirs', []) if d.get('name') and not d['name'].startswith('.') and '/' not in d['name']
                  and now - float(d.get('mtime', now)) > keep_h * 3600)


def run(sink, now: float, keep_h: float, apply: bool) -> int:
    ls = sink.ls(JP.PREFIX)
    stale = old_jobs(ls, now, keep_h)
    print(f'renderjobs: заданий {len(ls.get("dirs", []))}, старше {keep_h:g} ч: {len(stale)}')
    done = 0
    for n in stale:
        if apply:
            sink.delete(f'{JP.PREFIX}/{n}')
            done += 1
        print(('удалено ' if apply else 'удалил бы ') + f'{JP.PREFIX}/{n}')
    return done


def _selftest() -> int:
    bad = []

    def ok(n, c):
        print(('OK   ' if c else 'FAIL ') + n)
        if not c:
            bad.append(n)
    now = 1_000_000.0
    ls = {'dirs': [{'name': 'a', 'mtime': now - 25 * 3600}, {'name': 'b', 'mtime': now - 3600}, {'name': '.staging', 'mtime': 0}, {'name': 'x/y', 'mtime': 0}]}
    ok('старше 24 ч — только a (свежее, скрытое и с / — нет)', old_jobs(ls, now, 24) == ['a'])
    ok('порог меняется данными', old_jobs(ls, now, 0.5) == ['a', 'b'])

    class S:
        def __init__(self):
            self.deleted = []

        def ls(self, rel):
            assert rel == 'renderjobs'
            return ls

        def delete(self, rel):
            self.deleted.append(rel)
    s = S()
    ok('без --apply ничего не удаляет', run(s, now, 24, False) == 0 and s.deleted == [])
    ok('--apply удаляет только renderjobs/<старое>', run(s, now, 24, True) == 1 and s.deleted == ['renderjobs/a'])
    print('итог:', 'чисто' if not bad else f'ПРОВАЛЕНО {len(bad)}')
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--hours', type=float, default=KEEP_H)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--prefix', default=JP.PREFIX)
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.prefix != JP.PREFIX:
        print('чужой префикс не убираем: только', JP.PREFIX)
        return 2
    import migrate_groups
    import sink_health
    migrate_groups.env_from_file()      # ключ Salad и SALAD_GROUP из salad.env (вне git) — тот же путь токена, что у исполнителя и сторожей
    tok = sink_health.sink_token()
    if not tok:
        print('нет токена приёмника — ничего не делаю')
        return 1
    run(JP.Sink(sink_health.SINK_URL, tok), time.time(), a.hours, a.apply)
    return 0


if __name__ == '__main__':
    sys.exit(main())
