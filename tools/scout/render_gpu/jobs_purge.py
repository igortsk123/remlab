#!/usr/bin/env python3
"""УБОРКА ЗАДАНИЙ МАШИНЫ РЕНДЕРА на приёмнике (T-20261117-24/2): каталоги `renderjobs/<задание>` старше N часов (по умолчанию 24).

Только префиксы `renderjobs` и (с fmt 2, T-20261117-24/5) `renderassets` — меши и всё остальное не трогаем (чужой префикс в аргументах отвергается).
АССЕТЫ (`renderassets/<ab>/<sha256>`): убираем по давности (последнее «использован»/«спросили есть ли» — mtime, `RENDERASSETS_KEEP_H`, 168 ч) и по размеру (`RENDERASSETS_KEEP_GB`,
1,2 ГБ — давние вперёд), НО не трогаем: ассеты, на которые ссылается лежащее в `renderjobs` задание (читаем `job.json` fmt 2), и всё моложе 15 минут (исполнитель мог только
что досылать их перед `job.json`). Удаление — через `DELETE /prefix/…` приёмника
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
ASSET_KEEP_H = float(os.environ.get('RENDERASSETS_KEEP_H', '168'))
ASSET_KEEP_GB = float(os.environ.get('RENDERASSETS_KEEP_GB', '1.2'))
ASSET_MIN_AGE_S = 900
import re  # noqa: E402
_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def old_jobs(listing: dict, now: float, keep_h: float) -> list:
    """Имена каталогов старше keep_h (по mtime каталога; свежие — в работе — не трогаем). Чистая функция."""
    return sorted(d['name'] for d in listing.get('dirs', []) if d.get('name') and not d['name'].startswith('.') and '/' not in d['name']
                  and d['name'] != JP.HOT_DIR and now - float(d.get('mtime', now)) > keep_h * 3600)      # `_hot` — горячий список витрины, не задание


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


ABORTED_MIN_AGE_S = 900


def aborted_jobs(sink, listing: dict, now: float, min_age_s: float = ABORTED_MIN_AGE_S) -> list:
    """Брошенные отправки (T-20261118-09/5): каталог задания БЕЗ `job.json`, `result.json` и `cancel.json` — отправку оборвали (перезапуск сервиса, убитая проба) до записи `job.json`.
    Воркер на машине обходит такие каталоги на КАЖДОМ круге выбора задания (≈0,6 с на каталог — ls + чтение job.json, до 2 ч) — до 2–4 с на заказ (замер 18.11: 3 брошенных).
    Моложе `min_age_s` не трогаем (отправка может идти: `job.json` пишется последним). Чистая функция над данными приёмника: список имён."""
    out = []
    for d in listing.get('dirs', []):
        n = d.get('name', '')
        if not n or n.startswith('.') or '/' in n or n == JP.HOT_DIR or now - float(d.get('mtime', now)) <= min_age_s:
            continue
        try:
            names = {f.get('name') for f in sink.ls(f'{JP.PREFIX}/{n}').get('files', [])}
        except JP.SinkError:
            continue
        if not names & {'job.json', 'result.json', 'cancel.json'}:
            out.append(n)
    return sorted(out)


def run_aborted(sink, listing: dict, now: float, apply: bool) -> int:
    ab = aborted_jobs(sink, listing, now)
    print(f'renderjobs: брошенных отправок (нет job.json/result.json) старше {ABORTED_MIN_AGE_S // 60} мин: {len(ab)}')
    done = 0
    for n in ab:
        if apply:
            sink.delete(f'{JP.PREFIX}/{n}')
            done += 1
        print(('удалено ' if apply else 'удалил бы ') + f'{JP.PREFIX}/{n} (брошена)')
    return done


def list_assets(sink) -> list:
    """Все ассеты приёмника: [(shard, sha, size, mtime)]. Имена не из хеша и не из своего шарда пропускаем (чужое не удаляем)."""
    out = []
    for d in sink.ls(JP.ASSET_PREFIX).get('dirs', []):
        shard = d.get('name', '')
        if not re.match(r'^[0-9a-f]{2}$', shard):
            continue
        for f in sink.ls(f'{JP.ASSET_PREFIX}/{shard}').get('files', []):
            n = f.get('name', '')
            if _HEX64.match(n) and n[:2] == shard:
                out.append((shard, n, int(f.get('size', 0)), float(f.get('mtime', 0))))
    return out


def live_refs(sink, listing: dict) -> set:
    """Ассеты, на которые ссылаются лежащие сейчас задания fmt 2 (читаем их `job.json`; нет файла/не fmt 2/сбой чтения — задание считается без ссылок,
    а ассеты моложе ASSET_MIN_AGE_S всё равно защищены)."""
    refs: set = set()
    try:                                                # ГОРЯЧИЙ СПИСОК витрины (T-24/7): ассеты /demo и туров уборка не трогает, пока они в списке
        refs |= {h for h, _ in JP.parse_hot(sink.get_json(JP.HOT_REL))}
    except (JP.SinkError, ValueError):
        pass
    for d in listing.get('dirs', []):
        n = d.get('name', '')
        if not n or n.startswith('.') or '/' in n or n == JP.HOT_DIR:
            continue
        try:
            job = sink.get_json(f'{JP.PREFIX}/{n}/job.json')
        except (JP.SinkError, ValueError):
            continue
        if isinstance(job, dict) and job.get('v') == JP.PROTO2 and isinstance(job.get('assets'), list):
            refs |= {a.get('sha256') for a in job['assets'] if isinstance(a, dict)}
    return refs


def plan_assets(files: list, refs: set, now: float, keep_h: float = ASSET_KEEP_H, keep_gb: float = ASSET_KEEP_GB, min_age_s: float = ASSET_MIN_AGE_S) -> list:
    """Что убрать: [(shard, sha, size, причина)]. Чистая функция. Защищены: ссылки живых заданий и всё моложе `min_age_s`. Сперва старше `keep_h`; если осталось больше
    `keep_gb` — давние вперёд, пока не уложимся."""
    safe_ = lambda f: f[1] in refs or now - f[3] < min_age_s  # noqa: E731
    drop = [(f[0], f[1], f[2], 'давность') for f in files if not safe_(f) and now - f[3] > keep_h * 3600]
    gone = {d[1] for d in drop}
    left = [f for f in files if f[1] not in gone]
    total = sum(f[2] for f in left)
    for f in sorted((f for f in left if not safe_(f)), key=lambda f: f[3]):
        if total <= keep_gb * 2 ** 30:
            break
        drop.append((f[0], f[1], f[2], 'размер'))
        total -= f[2]
    return drop


def run_assets(sink, listing: dict, now: float, apply: bool, keep_h: float = ASSET_KEEP_H, keep_gb: float = ASSET_KEEP_GB) -> int:
    files = list_assets(sink)
    drop = plan_assets(files, live_refs(sink, listing), now, keep_h, keep_gb)
    print(f'renderassets: файлов {len(files)}, {sum(f[2] for f in files) / 2 ** 20:.0f} МБ; убрать {len(drop)} ({sum(d[2] for d in drop) / 2 ** 20:.0f} МБ)')
    done = 0
    for shard, sha, size, why in drop:
        if apply:
            sink.delete(f'{JP.ASSET_PREFIX}/{shard}/{sha}')
            done += 1
        print(('удалено ' if apply else 'удалил бы ') + f'{JP.ASSET_PREFIX}/{shard}/{sha[:12]}… ({size // 1024} КБ, {why})')
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
    # ассеты
    h = lambda c: c * 64  # noqa: E731
    H = 3600
    files = [('aa', h('a'), 100, now - 200 * H), ('bb', h('b'), 100, now - 200 * H), ('cc', h('c'), 100, now - 10 * H), ('dd', h('d'), 100, now - 60)]
    ok('давность 168 ч: старше уходит, свежее и моложе 15 мин — нет', [d[1] for d in plan_assets(files, set(), now)] == [h('a'), h('b')])
    ok('ссылка живого задания защищает старый ассет', [d[1] for d in plan_assets(files, {h('a')}, now)] == [h('b')])
    big = [('aa', h('a'), 600, now - 5 * H), ('bb', h('b'), 600, now - 3 * H), ('cc', h('c'), 600, now - 1 * H), ('dd', h('d'), 600, now - 60)]
    ok('по размеру: давние вперёд, пока не уложились; защищённые и молодые целы', [d[1] for d in plan_assets(big, {h('b')}, now, keep_gb=1200 / 2 ** 30)] == [h('a'), h('c')])
    ok('чужое имя не из хеша в список не попадает', all(_HEX64.match(f[1]) for f in files))

    class A:
        def __init__(self):
            self.deleted = []

        def ls(self, rel):
            if rel == 'renderassets':
                return {'dirs': [{'name': 'aa'}, {'name': '.x'}, {'name': 'zz'}]}
            if rel == 'renderassets/aa':
                return {'files': [{'name': h('a'), 'size': 10, 'mtime': now - 300 * H}, {'name': 'oops', 'size': 1, 'mtime': 0}, {'name': h('b'), 'size': 10, 'mtime': now - 300 * H}]}
            return {'dirs': [], 'files': []}

        def get_json(self, rel):
            if rel == 'renderjobs/j1/job.json':
                return {'v': 2, 'assets': [{'sha256': h('b')}]}
            if rel == JP.HOT_REL and getattr(self, 'hot', None):
                return JP.new_hot([{'sha256': x, 'size': 5} for x in self.hot])
            raise JP.SinkError('x', 404)

        def delete(self, rel):
            self.deleted.append(rel)
    a = A()
    ok('run_assets --apply: удалён только незащищённый ассет с именем-хешем', run_assets(a, {'dirs': [{'name': 'j1'}, {'name': 'j2'}]}, now, True) == 1 and a.deleted == [f'renderassets/aa/{h("a")}'])
    a = A()
    a.hot = [h('a')]
    ok('горячий список защищает ассет витрины: удаляется только то, что не в списке и не в задании', run_assets(a, {'dirs': [{'name': 'j1'}, {'name': '_hot'}]}, now, True) == 0 and a.deleted == [])
    ok('каталог `_hot` — не задание: по возрасту не удаляется', old_jobs({'dirs': [{'name': '_hot', 'mtime': 0}, {'name': 'x', 'mtime': 0}]}, now, 24) == ['x'])
    a = A()
    ok('run_assets без --apply ничего не удаляет', run_assets(a, {'dirs': []}, now, False) == 0 and a.deleted == [])
    # брошенные отправки
    class J:
        files = {'ab1': [{'name': 'bundle-x.tgz'}], 'ok1': [{'name': 'bundle-x.tgz'}, {'name': 'job.json'}], 'done1': [{'name': 'result.json'}, {'name': 'C1.jpg'}],
                 'cx': [{'name': 'cancel.json'}], 'new1': [{'name': 'bundle-x.tgz'}], 'ab2': []}

        def __init__(self):
            self.deleted = []

        def ls(self, rel):
            return {'files': J.files[rel.split('/')[-1]]}

        def delete(self, rel):
            self.deleted.append(rel)
    lsj = {'dirs': [{'name': n, 'mtime': now - (60 if n == 'new1' else 3000)} for n in ('ab1', 'ok1', 'done1', 'cx', 'new1', 'ab2')] + [{'name': '_hot', 'mtime': 0}, {'name': '.s', 'mtime': 0}]}
    j = J()
    ok('брошенные: без job/result/cancel и старше 15 мин — ab1, ab2; с job.json, с результатом, отменённая, свежая, _hot — нет', aborted_jobs(j, lsj, now) == ['ab1', 'ab2'])
    ok('run_aborted: без --apply не удаляет, с --apply удаляет только брошенные', run_aborted(j, lsj, now, False) == 0 and j.deleted == [] and run_aborted(j, lsj, now, True) == 2
       and j.deleted == ['renderjobs/ab1', 'renderjobs/ab2'])
    print('итог:', 'чисто' if not bad else f'ПРОВАЛЕНО {len(bad)}')
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--hours', type=float, default=KEEP_H)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--aborted-only', action='store_true', help='только брошенные отправки (дёшево, годится для частого крона)')
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
    sink = JP.Sink(sink_health.SINK_URL, tok)
    now = time.time()
    listing = sink.ls(JP.PREFIX)
    run_aborted(sink, listing, now, a.apply)
    if a.aborted_only:
        return 0
    run(sink, now, a.hours, a.apply)
    run_assets(sink, listing, now, a.apply)
    return 0


if __name__ == '__main__':
    sys.exit(main())
