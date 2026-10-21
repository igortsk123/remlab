#!/usr/bin/env python3
"""Хеш текущего фото товара — ЕДИНСТВЕННЫЙ писатель `product_photo_current` (план mesh-14, 21.10).

ЗАЧЕМ. Хеш писали двое по разным воротам: `cutout_sync` — только для пула подбора (качество ≥ 0.65), `hd_backfill` —
только при смене байтов; а меш нужен по воротам `mesh_bind.mark_required` без качества. На 21.10 у 405 представителей
`mesh_required` хеша не было: готовые меши навсегда висели в stale (`mesh_bind.enforce_ready_invariant` без хеша не
пускает в ready), хотя у всех 176 stale скачанное фото давало тот же sha, что у поколения. Теперь «кого хешировать» =
пул подбора ∪ представители `mesh_required`, mesh-товары stale/none — первыми; запись — только здесь.

Хеш — sha256 байтов по адресу `coalesce(image_url_hd, image_url)` (HD в приоритете, тот же адрес качает генератор,
ADR-0182), полной строкой: ревизии сравнивают по префиксу (`mesh_bind.py`: `like sha16||'%'`).

  ~/venvs/scout/bin/python photo_hash.py --limit 1000            # ночной шаг (зовёт cutout_sync)
  ~/venvs/scout/bin/python photo_hash.py --only-mesh --dry        # кто без хеша среди mesh_required, скачать без записи
  ~/venvs/scout/bin/python photo_hash.py --stats                  # без хеша сейчас и возраст старейшего
  python3 photo_hash.py --selftest
"""
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pool_gate as PG  # noqa: E402

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab',
        '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),   # одноразовая база --dbtest, как у mesh_queue/mesh_bind
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
UA = {'User-Agent': 'remlab-cutout/1.0'}
SHA_MAX_AGE_DAYS = int(os.environ.get('SHA_MAX_AGE_DAYS', '30'))   # магазин подменяет картинку под тем же адресом
# С КАКОГО ВРЕМЕНИ товар без хеша (для сторожа `pipeline_map`): в базе такой отметки нет, держим рядом с состоянием
MISSING = os.path.expanduser(os.environ.get('PHOTO_HASH_MISSING', '~/scout-scenes/photo-hash-missing.json'))
SKU = "p.shop_mid||':'||p.external_id"
URL = 'coalesce(p.image_url_hd, p.image_url)'
REP = f'coalesce(p.mesh_family_rep, {SKU}) = {SKU}'      # вариант семейства получает меш и статус от представителя


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def q(v) -> str:
    return 'null' if v is None else "'" + str(v).replace("'", "''") + "'"


def fetch(url: str, timeout: int = 40) -> bytes:
    if url.startswith('//'):
        url = 'https:' + url
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def upsert_sql(sku: str, url: str, sha: str) -> str:
    """ЕДИНСТВЕННАЯ запись в `product_photo_current` во всём репо (тест `--selftest` следит)."""
    return ("insert into product_photo_current (sku, image_url, source_sha, observed_at) "
            f"values ({q(sku)}, {q(url)}, {q(sha)}, now()) "
            "on conflict (sku) do update set image_url=excluded.image_url, "
            "source_sha=excluded.source_sha, observed_at=now();")


def targets_sql(limit: int, only_mesh: bool = False) -> str:
    """Кого хешировать: представители `mesh_required` (БЕЗ условия качества — меш им нужен и так; stale/none первыми) ∪
    пул подбора. Пропускаем тех, у кого свежий хеш по ТОМУ ЖЕ адресу."""
    mesh = (f"select {SKU} as sku, {URL} as url, "
            "case when coalesce(p.mesh_status, 'none') in ('stale', 'none') then 0 else 1 end as ord "
            f"from products p where p.mesh_required and {REP} and {URL} is not null")
    pool = f"select {SKU} as sku, {URL} as url, 2 as ord {PG.POOL_SQL}"
    src = mesh if only_mesh else f'{mesh} union all {pool}'
    return (f"select t.sku, t.url from (select sku, url, min(ord) as ord from ({src}) u group by sku, url) t "
            "where not exists (select 1 from product_photo_current c where c.sku = t.sku and c.image_url = t.url "
            "  and coalesce(c.source_sha, '') <> '' "
            f"  and c.observed_at > now() - interval '{SHA_MAX_AGE_DAYS} days') "
            f"order by t.ord, t.sku limit {int(limit)}")


def missing_sql() -> str:
    """Представители `mesh_required` без хеша фото — то, что сторож обязан видеть нулём."""
    return (f"select {SKU} from products p where p.mesh_required and {REP} and not exists "
            f"(select 1 from product_photo_current c where c.sku = {SKU} and coalesce(c.source_sha, '') <> '')")


def track_missing(prev: dict, missing: set, now: float) -> dict:
    """{sku: с какого времени без хеша}. Захешированные уходят, новые получают `now`. Чистая функция."""
    return {s: float(prev.get(s, now)) for s in sorted(missing)}


def _load_missing() -> dict:
    try:
        return json.load(open(MISSING, encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f'  !! {MISSING} не читается ({type(e).__name__}) — возраст «без хеша» считаю заново', flush=True)
        return {}


def _save_missing(d: dict) -> None:
    os.makedirs(os.path.dirname(MISSING), exist_ok=True)
    tmp = MISSING + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f)
    os.replace(tmp, MISSING)


def oldest_hours(missing: set, since: dict, now: float) -> float:
    """Часов у старейшего без хеша — по отметке `MISSING`; товар без отметки (появился после ночного хеширования)
    считаем свежим. Чистая функция."""
    return max((now - float(since[s]) for s in missing if s in since), default=0.0) / 3600


def missing_stats(now: float | None = None) -> tuple[int, float]:
    """(сколько представителей `mesh_required` без хеша, часов у старейшего)."""
    miss = {r[0] for r in db(missing_sql()) if r}
    return len(miss), oldest_hours(miss, _load_missing(), now or time.time())


def _hash_rows(rows: list[list[str]], dry: bool) -> dict:
    """Скачивание параллельно (CDN держат 8 потоков), запись последовательно (psql через docker exec).
    Отказ скачивания не валит прогон, но считается и печатается с классом ошибки."""
    def one(r):
        sku, url = r
        try:
            return sku, url, hashlib.sha256(fetch(url)).hexdigest(), None
        except Exception as e:  # noqa: BLE001 — мёртвое фото не валит прогон, но не молчит
            return sku, url, None, f'{type(e).__name__}: {str(e)[:70]}'

    st = {'targets': len(rows), 'hashed': 0, 'failed': 0}
    errs: collections.Counter = collections.Counter()
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sku, url, sha, err in ex.map(one, rows):
            if err:
                st['failed'] += 1
                errs[re.sub(r'\d{3}', 'NNN', err.split(':')[0] + ':' + err.split(':', 1)[1][:30])] += 1
                print(f'  хеш {sku}: {err}', flush=True)
                continue
            st['hashed'] += 1
            if not dry:
                db(upsert_sql(sku, url, sha))
    if errs:
        print('  отказы скачивания по классам: ' + ', '.join(f'{k} ×{n}' for k, n in errs.most_common(5)), flush=True)
    return st


def sync(limit: int, only_mesh: bool = False, dry: bool = False) -> dict:
    """Досчитать хеши тем, кого надо хешировать (`targets_sql`), и обновить отметку «без хеша с …»."""
    st = _hash_rows([r for r in db(targets_sql(limit, only_mesh)) if len(r) == 2], dry)
    if not dry:
        _save_missing(track_missing(_load_missing(), {r[0] for r in db(missing_sql()) if r}, time.time()))
    return st


def hash_skus(skus: list[str], dry: bool = False) -> dict:
    """Досчитать хеш заданным товарам (спрос мешей — `mesh_queue.ingest`) по тому же адресу HD→SD, что и `sync`."""
    if not skus:
        return {'targets': 0, 'hashed': 0, 'failed': 0}
    lst = ','.join(q(s) for s in skus)
    return _hash_rows([r for r in db(f"select {SKU}, {URL} from products p where {SKU} in ({lst}) and {URL} is not null")
                       if len(r) == 2], dry)


# ------------------------------------------------------------------ самопроверка

def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    # 1) единственный писатель: ни один файл, кроме этого, не пишет в product_photo_current
    root = os.path.abspath(os.path.join(HERE, '..', '..'))
    rx = re.compile(r'(insert\s+into|update)\s+product_photo_current\b', re.I)
    writers = []
    for base in ('tools', 'lib', 'app', 'scripts', 'infra'):
        for dp, dn, fn in os.walk(os.path.join(root, base)):
            dn[:] = [d for d in dn if d not in ('node_modules', '.next', 'tests', '__pycache__')]
            for f in fn:
                if f.endswith(('.py', '.sh', '.ts', '.tsx', '.mjs', '.sql')):
                    p = os.path.join(dp, f)
                    try:
                        if rx.search(open(p, encoding='utf-8', errors='ignore').read()):
                            writers.append(os.path.relpath(p, root))
                    except OSError:
                        pass
    ok(f'единственный писатель product_photo_current — photo_hash.py (нашлось: {writers})',
       writers == ['tools/scout/photo_hash.py'])
    # 2) кого хешировать: mesh_required — без условия качества, пул — с границей включительно, stale/none первыми
    sql = targets_sql(10)
    mesh_part = sql.split(' union all ')[0]
    ok('ветка mesh_required без условия качества', 'mesh_required' in mesh_part and 'quality' not in mesh_part)
    ok('пул подбора — через pool_gate (граница 0.65 включительно)', PG.quality_ok('e.quality') in sql)
    ok('mesh-товары stale/none идут первыми (ord 0), пул последним (ord 2)',
       "in ('stale', 'none') then 0" in mesh_part and '2 as ord' in sql and sql.rstrip().endswith('limit 10')
       and 'order by t.ord' in sql)
    ok('--only-mesh не берёт пул', 'product_enrichment' not in targets_sql(10, only_mesh=True))
    ok('вариант семейства не хешируется отдельно (только представитель)', REP in mesh_part and REP in missing_sql())
    # 3) отметка «без хеша с …»: захешированные уходят, новые — с now, старые сохраняют дату
    t = track_missing({'a': 100.0, 'b': 200.0}, {'b', 'c'}, 1000.0)
    ok('track_missing: a захеширован — ушёл; b — прежняя дата; c — новая', t == {'b': 200.0, 'c': 1000.0})
    ok('возраст: старейший из ещё без хеша, без отметки — свежий',
       oldest_hours({'b', 'c', 'z'}, {'a': 0.0, 'b': 3600.0, 'c': 7200.0}, 3600.0 * 30) == 29.0
       and oldest_hours(set(), {'a': 0.0}, 99.0) == 0.0)
    up = upsert_sql("1:x'y", '//u', 'ab')
    ok('upsert экранирует кавычки и обновляет observed_at', "'1:x''y'" in up and 'observed_at=now()' in up)
    print(f'photo_hash selftest: ошибок {bad}')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    if '--stats' in sys.argv:
        n, h = missing_stats()
        print(f'представителей mesh_required без хеша фото: {n}; старейший без хеша: {h:.1f} ч')
        return 0
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 1000
    only_mesh, dry = '--only-mesh' in sys.argv, '--dry' in sys.argv
    st = sync(limit, only_mesh=only_mesh, dry=dry)
    print(f"хеш фото{' (СУХО, без записи)' if dry else ''}: к хешированию {st['targets']}, посчитано {st['hashed']}, "
          f"не скачалось {st['failed']}", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
