#!/usr/bin/env python3
"""ШАГ «ЗАЛИТЬ АССЕТЫ ВИТРИНЫ» (T-20261117-24/7, Э2в «подогрев»): после публикации /demo и перевыпуска туров DEV собирает сцены вариантов витрины ТЕМ ЖЕ правилом,
что заказ «Сделать фото» (`render_exec.SceneExecutor._prepare` → `SaladGpuExecutor._bundle_files/_split_assets`), и досылает на приёмник ассеты, которых там нет
(`/have` → PUT, как fmt 2), — БЕЗ рендера и без включения машины. Потом пишет на приёмник «горячий список» (`renderjobs/_hot/hot.json`): машина при прогреве
подтягивает его в свой кэш, а уборка приёмника (`jobs_purge.py`) эти ассеты не трогает. Итог: первый заказ нового варианта на прогретой машине не ждёт ни выгрузки
(≈2,4 МБ/с), ни скачивания (4–7 с) — остаётся сборка сцены на DEV и Blender.

ЧТО ВХОДИТ: сперва варианты /demo (`demo-data.json` — тот же файл, что читает сервис кадров), потом туры — свежайшая версия данных каждого тура из последнего прохода
перевыпуска (`~/remlab-logs/trial/reissue/<проход>/<тур>/bundle-new.json`), новые туры вперёд, пока не упрёмся в потолок размера (`executor.hot_max_mb`, правила
`salad-groups.json`/render_machine; приёмник держит ассетов не больше `MESH_ASSET_MAX_GB`). Что не влезло — не горячее: такой заказ, как раньше, досылает недостающее сам.
КЭШ СБОРКИ: сцена варианта, не менявшаяся с прошлого прохода (тот же `scene_hash`, версии выгрузчиков и сборка выгрузчика), второй раз не собирается: берём список
ассетов из файла `~/scout-cache/showcase-assets.json` и только спрашиваем приёмник «есть ли»; нет — собираем заново и досылаем. Ассеты вида code/data (программа рендера и её
данные) от сцены не зависят и считаются каждый раз заново.

    ~/venvs/scout/bin/python showcase_assets.py [--dry] [--demo-only] [--tours N] [--max-mb M] [--no-cache] [--prio 0|1]
Код выхода: 0 — список записан (или --dry), 1 — часть сцен не собралась/не ушла (список всё равно записан, если что-то годное есть), 2 — нечего записывать/нет приёмника.
Самопроверка: `showcase_assets.py --selftest`."""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, '..'), os.path.join(HERE, '..', 'salad')]
import jobs_proto as JP  # noqa: E402

CACHE_FILE = os.environ.get('SHOWCASE_ASSETS_CACHE') or os.path.expanduser('~/scout-cache/showcase-assets.json')
REISSUE_ROOT = os.environ.get('SHOWCASE_REISSUE_ROOT') or os.path.expanduser('~/remlab-logs/trial/reissue')
DEMO_DATA = os.environ.get('DEMO_DATA_FILE') or os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
DEFAULT_MAX_MB = 900.0           # потолок горячего списка по размеру (приёмник: ассетов ≤ 1,5 ГБ, уборка держит ≤ 1,2 ГБ, диск машины — кэш 4 ГБ)
CACHE_KEEP = 3000                # записей кэша сборки


def tour_sources(root: str = REISSUE_ROOT, max_tours: int | None = None) -> list:
    """[(метка тура, путь к данным)] — по каждому туру САМАЯ СВЕЖАЯ `bundle-new.json` из проходов перевыпуска; туры — с самым свежим файлом вперёд."""
    best: dict = {}
    for p in glob.glob(os.path.join(root, '*', '*', 'bundle-new.json')):
        tid = os.path.basename(os.path.dirname(p))
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if tid not in best or mt > best[tid][0]:
            best[tid] = (mt, p)
    rows = sorted(best.items(), key=lambda kv: -kv[1][0])
    return [('tour:' + t[:8], v[1]) for t, v in rows][:max_tours]


def load_cache(path: str = CACHE_FILE) -> dict:
    try:
        d = json.load(open(path, encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict, path: str = CACHE_FILE) -> None:
    if len(cache) > CACHE_KEEP:                                   # старые вперёд: у записи метка времени `t`
        for k in sorted(cache, key=lambda k: cache[k].get('t', 0))[:len(cache) - CACHE_KEEP]:
            cache.pop(k, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, path)


class Pusher:
    """Досылка недостающих ассетов одной сцены: `/have` → PUT (параллельно). Один и тот же хеш за проход спрашиваем/шлём один раз."""

    def __init__(self, sink, par: int = 4, log=print):
        self.sink, self.par, self.log = sink, max(1, par), log
        self.known: set = set()          # хеши, которые на приёмнике точно есть (спросили или залили в этом проходе)
        self.sent_mb, self.sent_n, self.sent_s = 0.0, 0, 0.0

    def missing(self, refs: list) -> list:
        """Какие из ссылок [{sha256,size}] приёмнику ещё нужны (спрашиваем только про не известные нам)."""
        todo = [{'sha256': h, 'size': s} for h, s in {r['sha256']: r['size'] for r in refs if r['sha256'] not in self.known}.items()]
        miss = set(self.sink.have_assets(todo)) if todo else set()
        self.known |= {t['sha256'] for t in todo} - miss
        return sorted(miss)

    def push(self, miss: list, src: dict, size: dict) -> None:
        t = time.time()
        with ThreadPoolExecutor(max_workers=self.par) as pool:
            for f in [pool.submit(self.sink.put_asset, h, src[h]) for h in miss]:
                f.result()
        self.known |= set(miss)
        self.sent_n += len(miss)
        self.sent_mb += sum(size[h] for h in miss) / 2 ** 20
        self.sent_s += time.time() - t


class Showcase:
    def __init__(self, ex, sink, log=print, par: int = 4, cache: dict | None = None, use_cache: bool = True, dry: bool = False, now=time.time, prio: int = 0):
        self.ex, self.sink, self.log, self.now, self.prio = ex, sink, log, now, prio
        self.push = Pusher(sink, par, log)
        self.cache = cache if cache is not None else {}
        self.use_cache = use_cache
        self.dry = dry
        self.stat = {'scenes': 0, 'cached': 0, 'built': 0, 'failed': 0, 'skipped': 0, 'export_s': 0.0}
        self._fixed = None

    # ——— ключ кэша сборки: всё, что меняет ассеты, зависящие от сцены (tex, glb, карты)
    def _key(self, snap: dict) -> str:
        import render_exec as RX
        v = self.ex.versions()
        part = {**{k: v.get(k) for k in ('export_scene', 'dump', 'scene_export')}, 'asset_rules': RX.ASSET_RULES}      # правило «что ассет» сменилось — прежние списки ассетов не годятся
        return RX.cache_key(snap['scene_hash'], part)

    def fixed_refs(self) -> list:
        """Ассеты, не зависящие от сцены (программа рендера, правило картин, их данные): те же `_bundle_files`/`_split_assets`, что у заказа, на пустом каталоге задания."""
        if self._fixed is None:
            empty = os.path.join(self.ex.work, 'gjob-h-empty')
            small, assets, src = self.ex._split_assets(self.ex._bundle_files(empty))
            self._fixed = ([a for a in assets if a['kind'] in ('code', 'data')], {h: p for h, p in src.items()})
        return self._fixed

    def scene(self, label: str, snap: dict) -> list:
        """Ассеты ОДНОЙ сцены (все виды) → список ссылок {path, sha256, size, kind}; недостающие — на приёмнике. Сбой — исключение (вызывающий считает)."""
        key = self._key(snap)
        self.stat['scenes'] += 1
        hit = self.cache.get(key) if self.use_cache else None
        if hit and hit.get('refs'):
            refs = hit['refs']
            miss = self.push.missing(refs)
            if not miss and hasattr(self.ex, 'prep_has') and not self.ex.prep_has(snap):
                self.log(f'  {label}: ассеты в кэше сборки, но подготовленной сцены нет — собираю (T-24/10)')
            elif not miss:
                hit['t'] = self.now()
                self.stat['cached'] += 1
                return refs
            if miss:
                self.log(f'  {label}: в кэше сборки, но на приёмнике нет {len(miss)} — собираю заново')
        import render_exec as RX
        pr = RX.preset()
        job = self.ex._job_dir('gjob-h-', snap)
        shutil.rmtree(job, ignore_errors=True)
        os.makedirs(job)
        try:
            t = time.time()
            timing: dict = {}
            with self.ex._slot('showcase-' + snap['scene_hash'][:8], pr, self.prio):
                self.ex._prepare(snap, job, os.path.join(job, 'run.log'), pr, lambda s: None, timing)
            self.stat['export_s'] += time.time() - t
            small, assets, src = self.ex._split_assets(self.ex._bundle_files(job))
            refs = [a for a in assets if a['kind'] not in ('code', 'data')]
            size = {a['sha256']: a['size'] for a in refs}
            miss = self.push.missing(refs)
            if miss and not self.dry:
                self.push.push(miss, src, size)
            self.stat['built'] += 1
        finally:
            shutil.rmtree(job, ignore_errors=True)
        self.cache[key] = {'t': self.now(), 'refs': refs, 'label': label}
        return refs

    def run(self, scenes, max_mb: float = DEFAULT_MAX_MB) -> dict:
        """`scenes` — [(метка, снимок)] в порядке важности. → отчёт и горячий список (в `hot`), без записи на приёмник."""
        hot: list = []
        seen: set = set()
        total = 0
        fixed, fsrc = self.fixed_refs()
        miss = self.push.missing(fixed)
        if miss and not self.dry:
            self.push.push(miss, fsrc, {a['sha256']: a['size'] for a in fixed})
        for a in fixed:                                          # программа рендера — первой: она нужна ЛЮБОМУ заказу
            if a['sha256'] not in seen:
                seen.add(a['sha256'])
                hot.append({'sha256': a['sha256'], 'size': a['size']})
                total += a['size']
        cut = 0
        for label, snap in scenes:
            if total >= max_mb * 2 ** 20:
                cut += 1
                self.stat['skipped'] += 1
                continue
            try:
                t1, sent0, built0 = time.time(), self.push.sent_mb, self.stat['built']
                refs = self.scene(label, snap)
                self.log(f"  {label}: {len(refs)} ассетов, {'собрана' if self.stat['built'] > built0 else 'из кэша'}, отправлено {self.push.sent_mb - sent0:.1f} МБ, {time.time() - t1:.0f} с")
            except Exception as e:  # noqa: BLE001 — одна сцена не должна ронять проход: считаем и идём дальше
                self.stat['failed'] += 1
                self.log(f'  {label}: НЕ ВЫШЛО — {type(e).__name__}: {str(e)[:160]}')
                continue
            new = [r for r in refs if r['sha256'] not in seen]
            add = sum(r['size'] for r in new)
            if total + add > max_mb * 2 ** 20 and hot:           # сцена целиком не влезла — не горячая (половина варианта подогрева не даёт)
                self.stat['skipped'] += 1
                cut += 1
                continue
            for r in new:
                seen.add(r['sha256'])
                hot.append({'sha256': r['sha256'], 'size': r['size']})
            total += add
        return {'hot': hot, 'mb': round(total / 2 ** 20, 1), 'cut': cut, **self.stat,
                'sent_mb': round(self.push.sent_mb, 1), 'sent_n': self.push.sent_n, 'sent_s': round(self.push.sent_s, 1)}

    def write_hot(self, hot: list, note: str = '') -> dict:
        obj = JP.new_hot(hot, now=self.now(), note=note)
        if not self.dry:
            self.sink.put(JP.HOT_REL, json.dumps(obj, ensure_ascii=False).encode())
        return obj


def snaps_of(data: dict, source: str, label: str, log=print) -> list:
    """Снимки ВСЕХ вариантов данных (как заказ без своей расстановки: предметы и ракурсы варианта). Вариант, который контракт снимка не принял, пропускаем со строкой."""
    import render_snapshot as RS
    out = []
    for v in data.get('variants') or []:
        vid = v.get('id')
        if not vid:
            continue
        try:
            out.append((f'{label}/{vid}', RS.canonicalize(data, {'v': RS.SNAPSHOT_VERSION, 'variant_id': vid}, source)))
        except RS.SnapshotError as e:
            log(f'  {label}/{vid}: снимок не принят ({e.code}) — не горячий')
    return out


def build_scenes(demo_path: str, tours_root: str, max_tours: int | None, demo_only: bool, log=print) -> list:
    scenes = []
    try:
        scenes += snaps_of(json.load(open(demo_path, encoding='utf-8')), 'demo', 'demo', log)
    except (OSError, ValueError) as e:
        log(f'нет данных витрины /demo ({demo_path}): {e}')
    if not demo_only:
        for label, path in tour_sources(tours_root, max_tours):
            try:
                scenes += snaps_of(json.load(open(path, encoding='utf-8')), 'trial', label, log)
            except (OSError, ValueError) as e:
                log(f'  {label}: данные не читаются ({e})')
    return scenes


def main(argv=None, ex=None, sink=None) -> int:
    ap = argparse.ArgumentParser(description='Залить ассеты витрины (/demo и туры) на приёмник и записать горячий список')
    ap.add_argument('--dry', action='store_true', help='ничего не слать и не записывать: только посчитать')
    ap.add_argument('--demo-only', action='store_true')
    ap.add_argument('--tours', type=int, default=None, help='сколько свежих туров брать (по умолчанию все)')
    ap.add_argument('--max-mb', type=float, default=None, help=f'потолок горячего списка, МБ (по умолчанию правило или {DEFAULT_MAX_MB:g})')
    ap.add_argument('--no-cache', action='store_true')
    ap.add_argument('--par', type=int, default=None)
    ap.add_argument('--prio', type=int, default=0, choices=(0, 1, 2), help='класс в очереди тяжёлых прогонов: 0 — фон (по умолчанию, уступает заказам), 1 — как заказ человека')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    import render_exec as RX
    ex = ex or RX.SaladGpuExecutor(env=dict(os.environ))
    try:
        sink = sink or ex.sink()
    except Exception as e:  # noqa: BLE001
        print(f'showcase_assets: нет приёмника ({e})')
        return 2
    try:
        rules = ex.machine().rules()
    except Exception:  # noqa: BLE001
        rules = {}
    exr = (rules.get('executor') or {}) if isinstance(rules, dict) else {}
    max_mb = a.max_mb or float(exr.get('hot_max_mb') or DEFAULT_MAX_MB)
    par = a.par or int(exr.get('upload_par') or 4)
    t0 = time.time()
    scenes = build_scenes(DEMO_DATA, REISSUE_ROOT, a.tours, a.demo_only, print)
    print(f'showcase_assets: сцен {len(scenes)}, потолок {max_mb:g} МБ' + (' (проба: ничего не шлём)' if a.dry else ''), flush=True)
    cache = load_cache()
    sc = Showcase(ex, sink, print, par, cache, not a.no_cache, a.dry, prio=a.prio)
    rep = sc.run(scenes, max_mb)
    if not a.dry:
        save_cache(cache)
    hot = rep.pop('hot')
    ok_scenes = rep['cached'] + rep['built']
    if not ok_scenes:
        print(f'showcase_assets: ни одной сцены не собралось ({rep}) — список не пишу')
        return 2
    obj = sc.write_hot(hot, note=f"demo+tours {time.strftime('%Y-%m-%d %H:%M', time.gmtime())}Z")
    print(f"showcase_assets: готово за {time.time() - t0:.0f} с — горячих ассетов {obj['n']} ({obj['mb']} МБ); сцен {rep['scenes']}: из кэша {rep['cached']}, собрано "
          f"{rep['built']} (сборка {rep['export_s']:.0f} с), не вышло {rep['failed']}, не влезло в потолок {rep['skipped']}; на приёмник отправлено {rep['sent_n']} шт., "
          f"{rep['sent_mb']} МБ за {rep['sent_s']} с" + (' [проба]' if a.dry else ''), flush=True)
    return 1 if rep['failed'] else 0


# ——— самопроверка: приёмник и исполнитель подменены, ничего не считается
def _selftest() -> int:
    import tempfile
    bad = []

    def ok(n, c):
        print(('OK   ' if c else 'FAIL ') + n)
        if not c:
            bad.append(n)

    h = lambda c: c * 64  # noqa: E731

    class Sink:
        def __init__(self, have=()):
            self.files, self.puts, self.asks = set(have), [], []

        def have_assets(self, items):
            self.asks.append([i['sha256'] for i in items])
            return [i['sha256'] for i in items if i['sha256'] not in self.files]

        def put_asset(self, sha, path):
            self.puts.append((sha, path))
            self.files.add(sha)

        def put(self, rel, data):
            self.puts.append((rel, json.loads(data)))

    class Ex:
        """Исполнитель-заглушка: сцена `s<N>` даёт ассеты по таблице; считает, сколько раз собирали."""
        work = tempfile.mkdtemp()

        def __init__(self, table, fixed):
            self.table, self.fixed, self.built = table, fixed, []

        def versions(self):
            return {'export_scene': 'e1', 'dump': 'd1', 'scene_export': '1'}

        def _job_dir(self, prefix, snap):
            return os.path.join(self.work, prefix + snap['scene_hash'][:8])

        def _slot(self, label, pr, prio=1):
            import contextlib
            return contextlib.nullcontext({})

        def _prepare(self, snap, job, log, pr, progress, timing):
            self.built.append(snap['scene_hash'])

        def _bundle_files(self, job):
            return {'job': job}

        def _split_assets(self, files):
            job = files['job']
            if not job.startswith(os.path.join(self.work, 'gjob-h-')) or job.endswith('empty'):
                refs, src = list(self.fixed), {a['sha256']: '/dev/null' for a in self.fixed}
            else:
                name = os.path.basename(job)[len('gjob-h-'):]
                refs = list(self.table[name]) + list(self.fixed)
                src = {a['sha256']: '/dev/null' for a in refs}
            return {}, refs, src

    ref = lambda c, size, kind='tex': {'path': f'scene/tex/{c}.png', 'sha256': h(c), 'size': size, 'kind': kind}  # noqa: E731
    code = ref('f', 100, 'code')
    table = {'aaaaaaaa': [ref('1', 10 * 2 ** 20), ref('2', 5 * 2 ** 20)], 'bbbbbbbb': [ref('2', 5 * 2 ** 20), ref('3', 20 * 2 ** 20)]}
    snaps = [('v1', {'scene_hash': 'aaaaaaaa' + '0' * 56}), ('v2', {'scene_hash': 'bbbbbbbb' + '0' * 56})]

    import render_exec as RX
    pr_orig = RX.preset
    RX.preset = lambda: {}
    try:
        sink, ex = Sink(), Ex(table, [code])
        sc = Showcase(ex, sink, lambda *a: None, 2, {}, True, False, now=lambda: 1000.0)
        rep = sc.run(snaps, 900)
        ok('первый проход: обе сцены собраны, общий ассет (2) один раз', rep['built'] == 2 and rep['cached'] == 0 and len(ex.built) == 2 and sorted(s for s, _ in sink.puts) == sorted([h('1'), h('2'), h('3'), h('f')]))
        ok('горячий список: программа рендера первой, без повторов, размер по сумме', [a['sha256'] for a in rep['hot']] == [h('f'), h('1'), h('2'), h('3')] and rep['mb'] == 35.0)
        obj = sc.write_hot(rep['hot'], 'x')
        ok('запись списка: путь и состав годны для parse_hot', sink.puts[-1][0] == JP.HOT_REL and len(JP.parse_hot(obj)) == 4)
        # второй проход с тем же кэшем: ничего не собираем и не шлём
        sink2, ex2 = Sink(have=[h('1'), h('2'), h('3'), h('f')]), Ex(table, [code])
        sc2 = Showcase(ex2, sink2, lambda *a: None, 2, sc.cache, True, False)
        rep2 = sc2.run(snaps, 900)
        ok('второй проход: из кэша, сборки 0, отправлено 0', rep2['cached'] == 2 and rep2['built'] == 0 and ex2.built == [] and rep2['sent_n'] == 0)
        # на приёмнике убрали ассет — сцена собирается заново и досылается
        sink3, ex3 = Sink(have=[h('1'), h('f')]), Ex(table, [code])
        sc3 = Showcase(ex3, sink3, lambda *a: None, 2, sc.cache, True, False)
        rep3 = sc3.run(snaps, 900)
        ok('нет ассета на приёмнике — пересборка и досылка только недостающего', rep3['built'] >= 1 and sorted(s for s, _ in sink3.puts) == sorted([h('2'), h('3')]))
        # потолок: сцена целиком не влезла — пропущена
        sink4, ex4 = Sink(), Ex(table, [code])
        sc4 = Showcase(ex4, sink4, lambda *a: None, 2, {}, True, False)
        rep4 = sc4.run(snaps, 20)
        ok('потолок 20 МБ: первая (15 МБ) вошла, вторая (+20) — нет', len(rep4['hot']) == 3 and rep4['skipped'] == 1 and rep4['cut'] == 1)
        # --dry: ничего не уходит
        sink5, ex5 = Sink(), Ex(table, [code])
        sc5 = Showcase(ex5, sink5, lambda *a: None, 2, {}, True, True)
        sc5.run(snaps, 900)
        sc5.write_hot([], 'x')
        ok('--dry: ни PUT ассетов, ни списка', sink5.puts == [])
        # сбой сборки одной сцены не роняет проход
        class Bad(Ex):
            def _prepare(self, snap, *a):
                if snap['scene_hash'].startswith('aaaaaaaa'):
                    raise RuntimeError('boom')
                super()._prepare(snap, *a)
        sc6 = Showcase(Bad(table, [code]), Sink(), lambda *a: None, 2, {}, True, False)
        rep6 = sc6.run(snaps, 900)
        ok('сбой одной сцены: считается, вторая собрана', rep6['failed'] == 1 and rep6['built'] == 1)
    finally:
        RX.preset = pr_orig
        shutil.rmtree(Ex.work, ignore_errors=True)
    # список туров: самая свежая версия каждого тура
    d = tempfile.mkdtemp()
    try:
        for run, tour, mt in (('p1', 'T' * 22, 100), ('p2', 'T' * 22, 200), ('p1', 'U' * 22, 300)):
            p = os.path.join(d, run, tour)
            os.makedirs(p)
            open(os.path.join(p, 'bundle-new.json'), 'w').write('{}')
            os.utime(os.path.join(p, 'bundle-new.json'), (mt, mt))
        ts = tour_sources(d)
        ok('туры: по одному, самый свежий файл вперёд', [t[0] for t in ts] == ['tour:UUUUUUUU', 'tour:TTTTTTTT'] and ts[1][1].split('/')[-3] == 'p2')
        ok('туры: потолок числа', len(tour_sources(d, 1)) == 1)
        cp = os.path.join(d, 'c.json')
        save_cache({f'k{i}': {'t': i, 'refs': []} for i in range(CACHE_KEEP + 5)}, cp)
        c = load_cache(cp)
        ok('кэш: больше потолка — давние вперёд', len(c) == CACHE_KEEP and 'k0' not in c and f'k{CACHE_KEEP + 4}' in c)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # горячий список: разбор и защита от мусора
    ok('parse_hot: годные записи, дубль, плохой хеш, размер 0 и bool — отброшены',
       JP.parse_hot({'v': 1, 'assets': [{'sha256': h('a'), 'size': 5}, {'sha256': h('a'), 'size': 5}, {'sha256': 'zz', 'size': 5}, {'sha256': h('b'), 'size': 0},
                                         {'sha256': h('c'), 'size': True}, 'x', {'sha256': h('d'), 'size': 7}]}) == [(h('a'), 5), (h('d'), 7)])
    ok('parse_hot: чужая версия/не словарь — пусто', JP.parse_hot({'v': 2, 'assets': []}) == [] and JP.parse_hot([]) == [] and JP.parse_hot(None) == [])
    ok('new_hot: порядок и размер', JP.new_hot([{'sha256': h('a'), 'size': 2 ** 20}, {'sha256': h('a'), 'size': 1}], now=5)['mb'] == 1.0)
    print('ИТОГ:', 'ок' if not bad else f'{len(bad)} не прошло')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
