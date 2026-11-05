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
  ~/venvs/scout/bin/python photo_hash.py --limit 1000 --rooms-limit 5000   # + товары комнат после гостиной (T-46)
  ~/venvs/scout/bin/python photo_hash.py --stats                  # без хеша сейчас и возраст старейшего; счёт по комнатам
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


def sync(limit: int, only_mesh: bool = False, dry: bool = False, rooms_limit: int | None = None) -> dict:
    """Досчитать хеши тем, кого надо хешировать (`targets_sql`), и обновить отметку «без хеша с …».

    Потом — товары комнат (`rooms_targets`) СВОИМ лимитом (`rooms_limit`, по умолчанию `PHOTO_ROOMS_LIMIT`, 0 = не трогать):
    гостиная идёт первой и тем же списком, комнаты её ночь не удлиняют."""
    st = _hash_rows([r for r in db(targets_sql(limit, only_mesh)) if len(r) == 2], dry)
    if not dry:
        _save_missing(track_missing(_load_missing(), {r[0] for r in db(missing_sql()) if r}, time.time()))
    rl = ROOMS_LIMIT if rooms_limit is None else rooms_limit
    st['rooms'] = {'targets': 0, 'hashed': 0, 'failed': 0}
    if rl > 0 and not only_mesh:
        rows, skip = rooms_targets(rl)
        print(f'  комнаты: к хешированию {len(rows)} (лимит {rl}); пропуск — {_skip_line(skip)}', flush=True)
        st['rooms'] = _hash_rows(rows, dry)
    return st


def hash_skus(skus: list[str], dry: bool = False) -> dict:
    """Досчитать хеш заданным товарам (спрос мешей — `mesh_queue.ingest`) по тому же адресу HD→SD, что и `sync`."""
    if not skus:
        return {'targets': 0, 'hashed': 0, 'failed': 0}
    lst = ','.join(q(s) for s in skus)
    return _hash_rows([r for r in db(f"select {SKU}, {URL} from products p where {SKU} in ({lst}) and {URL} is not null")
                       if len(r) == 2], dry)


# ------------------------------------------------------------------ второй источник: товары комнат (room-pipeline-01 В-2, T-46)
# ЗАЧЕМ. Вырезка — вход генератора 3D и проверка «годится ли фото», а цели брались только из `products` (гостиная). Товары
# спальни и прихожей живут в `room_catalog` (ADR-0330) и хеша/вырезки не получали. Ключи таблиц уже нейтральные
# (`product_photo_current.sku = mid:eid`, `photo_assessment.source_sha`) — таблицы не меняются, добавляется только источник.
# ПОРЯДОК: гостиная — первой и тем же SQL (`targets_sql` не тронут), комнаты — после, СВОИМ лимитом (`--rooms-limit`,
# `PHOTO_ROOMS_LIMIT`; по умолчанию 0 = ночь гостиной та же, пока интегратор не включит).
# КТО ВХОДИТ: товары `room_catalog`, которых нет в `products` (те ведёт гостиная — тот же ключ `sku`, второй раз не качаем).
# ОДИН ТОВАР — ОДНА ЦЕЛЬ: в `room_catalog` ключ (mid, eid, room), роль одна на комнату; товар в нескольких комнатах
# берёт строку с наименьшей парой (room, role) по алфавиту — детерминированно, от порядка строк в базе не зависит.
# АДРЕС: тот же приоритет HD, что у гостиной (`image_url_hd`, иначе `image_url`); пустая строка = нет адреса → пропуск
# с причиной «нет адреса фото» (у гостиной пустых адресов нет; в комнатах есть null — 73 на 05.11).
ROOMS_LIMIT = int(os.environ.get('PHOTO_ROOMS_LIMIT', '0'))
RSKU = "r.shop_mid||':'||r.external_id"
RURL = "coalesce(nullif(r.image_url_hd, ''), nullif(r.image_url, ''))"
SKIP_IN_PRODUCTS = 'есть в products — ведёт гостиная'
SKIP_NO_URL = 'нет адреса фото'


def rooms_rows_sql(assessor: str = '') -> str:
    """Все строки `room_catalog` со всем, что нужно чистому `pick_rooms`: hd, sd, комната, роль, есть ли в products, хеш по ЭТОМУ
    адресу (sha, свежий ли) и вердикт вырезки текущей версии оценщика (`assessor`; пусто — не смотрим)."""
    return (f"select {RSKU}, coalesce(r.image_url_hd, ''), coalesce(r.image_url, ''), r.room, r.role, "
            "exists (select 1 from products p where p.shop_mid = r.shop_mid and p.external_id = r.external_id), "
            "coalesce(c.source_sha, ''), "
            f"coalesce(c.observed_at > now() - interval '{SHA_MAX_AGE_DAYS} days', false), "
            "coalesce(a.verdict, case when a.source_sha is not null then '?' end, ''), '.' "
            "from room_catalog r "
            f"left join product_photo_current c on c.sku = {RSKU} and c.image_url = {RURL} "
            f"left join photo_assessment a on a.source_sha = c.source_sha and a.assessor_version = {q(assessor)} "
            "order by 1, 4, 5")


def parse_room_rows(rows: list[list[str]]) -> list[dict]:
    """Последний столбец — заглушка '.': `db()` режет вывод `strip()`, а `\\x1f` для Python — пробел, и у последней строки
    пропадало пустое поле вердикта (товар терялся молча). Строка не той длины — ошибка, не пропуск."""
    out = []
    for r in rows:
        if len(r) != 10 or r[9] != '.':
            raise RuntimeError(f'room_catalog: строка не той формы ({len(r)} полей): {r[:2]}')
        out.append({'sku': r[0], 'hd': r[1], 'sd': r[2], 'room': r[3], 'role': r[4], 'in_products': r[5] == 't',
                    'sha': r[6], 'fresh': r[7] == 't' and bool(r[6]), 'verdict': r[8]})
    return out


def pick_rooms(rows: list[dict]) -> tuple[list[dict], dict[str, collections.Counter]]:
    """Одна цель на товар комнат. Чистая функция (её и тестирует `--selftest`).

    Возвращает (цели по порядку room → sku, с полями url/room/role/sha/fresh/verdict; пропуски {причина: Counter(room)}).
    Товар есть в products → весь пропуск (по комнате выбранной строки); в нескольких комнатах — строка с min (room, role);
    адрес — hd, иначе sd; оба пусты → пропуск «нет адреса фото»."""
    best: dict[str, dict] = {}
    for r in rows:
        b = best.get(r['sku'])
        if b is None or (r['room'], r['role']) < (b['room'], b['role']):
            best[r['sku']] = r
    out, skip = [], {SKIP_IN_PRODUCTS: collections.Counter(), SKIP_NO_URL: collections.Counter()}
    for sku in sorted(best, key=lambda s: (best[s]['room'], s)):
        r = best[sku]
        if r['in_products']:
            skip[SKIP_IN_PRODUCTS][r['room']] += 1
            continue
        url = r['hd'] or r['sd']
        if not url:
            skip[SKIP_NO_URL][r['room']] += 1
            continue
        out.append({**r, 'url': url})
    return out, skip


def rooms_targets(limit: int) -> tuple[list[list[str]], dict[str, collections.Counter]]:
    """[sku, url] товаров комнат без свежего хеша по их адресу — после гостиной, своим лимитом; плюс пропуски с причиной."""
    picked, skip = pick_rooms(parse_room_rows(db(rooms_rows_sql())))
    return [[t['sku'], t['url']] for t in picked if not t['fresh']][:max(int(limit), 0)], skip


def room_cutout_jobs(picked: list[dict], skip_shas: set, limit: int) -> list[tuple[str, str, str, str]]:
    """(sku, role, url, sha) товаров комнат к вырезке: хеш по текущему адресу есть, вырезки текущей версии нет. Ключ
    вырезки — sha байтов, поэтому sha, уже стоящий в работе у гостиной (`skip_shas`) или у другого товара комнат, второй
    раз не режем. Порядок — как у `pick_rooms` (комната, sku). Чистая функция."""
    out, seen = [], set(skip_shas)
    for t in picked:
        if not t['sha'] or t['verdict'] or t['sha'] in seen:
            continue
        seen.add(t['sha'])
        out.append((t['sku'], t['role'], t['url'], t['sha']))
    return out[:max(int(limit), 0)]


def _skip_line(skip: dict[str, collections.Counter]) -> str:
    return '; '.join(f"{why}: " + ', '.join(f'{room} ×{n}' for room, n in sorted(c.items()))
                     for why, c in skip.items() if c) or 'нет'


def rooms_stats(assessor: str) -> dict[str, dict]:
    """По комнатам (комната выбранной строки товара): целей, с хешем (по текущему адресу), с вырезкой версии `assessor`,
    ждёт вырезки (хеш есть, вырезки нет), брак маски (вердикт не ok), без хеша, пропуски по причинам."""
    picked, skip = pick_rooms(parse_room_rows(db(rooms_rows_sql(assessor))))
    st: dict[str, dict] = collections.defaultdict(lambda: collections.Counter())
    for t in picked:
        s = st[t['room']]
        s['целей'] += 1
        if t['sha']:
            s['с хешем'] += 1
            if t['verdict']:
                s['с вырезкой'] += 1
                if t['verdict'] != 'ok':
                    s['брак маски'] += 1
            else:
                s['ждёт вырезки'] += 1
        else:
            s['без хеша'] += 1
    for why, c in skip.items():
        for room, n in c.items():
            st[room][why] += n
    return {room: dict(c) for room, c in sorted(st.items())}


def print_rooms_stats(assessor: str) -> None:
    keys = ('целей', 'с хешем', 'с вырезкой', 'ждёт вырезки', 'брак маски', 'без хеша', SKIP_NO_URL, SKIP_IN_PRODUCTS)
    st = rooms_stats(assessor)
    print(f'товары комнат (room_catalog, оценщик {assessor or "—"}):')
    for room in sorted(set(st) | {'bedroom', 'hall'}):
        s = st.get(room, {})
        print(f'  {room:8} ' + ' · '.join(f'{k} {s.get(k, 0)}' for k in keys))


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
    # 4) второй источник — товары комнат (T-46): один товар — одна цель, products впереди, пустой адрес — с причиной
    def row(sku, room, role, hd='', sd='', in_products=False, sha='', fresh=False, verdict=''):
        return {'sku': sku, 'hd': hd, 'sd': sd, 'room': room, 'role': role, 'in_products': in_products,
                'sha': sha, 'fresh': fresh and bool(sha), 'verdict': verdict}
    picked, skip = pick_rooms([
        row('1:a', 'bedroom', 'кровать', hd='//a', in_products=True),            # есть в products → ведёт гостиная
        row('1:b', 'hall', 'обувница', sd='//b-hall'),                            # в двух комнатах → одна строка
        row('1:b', 'bedroom', 'комод', hd='//b-hd', sd='//b-sd'),
        row('1:c', 'bedroom', 'шкаф'),                                            # нет адреса → пропуск с причиной
        row('1:d', 'hall', 'зеркало', sd='//d'),
        row('1:e', 'bedroom', 'тумба прикроватная', hd='//e', sha='s', fresh=True)])
    ok('товар и в products, и в room_catalog — целью комнат не становится, пропуск с причиной',
       '1:a' not in [t['sku'] for t in picked] and skip[SKIP_IN_PRODUCTS] == {'bedroom': 1})
    ok('товар в двух комнатах — одна цель: min(room, role) = bedroom/комод, адрес HD',
       [(t['room'], t['role'], t['url']) for t in picked if t['sku'] == '1:b'] == [('bedroom', 'комод', '//b-hd')])
    rev, _ = pick_rooms(list(reversed([row('1:b', 'hall', 'обувница', sd='//x'), row('1:b', 'bedroom', 'комод', sd='//y')])))
    ok('выбор строки не зависит от порядка строк базы', [(t['room'], t['url']) for t in rev] == [('bedroom', '//y')])
    ok('пустой адрес — пропуск «нет адреса фото», не цель', '1:c' not in [t['sku'] for t in picked]
       and skip[SKIP_NO_URL] == {'bedroom': 1})
    ok('порядок целей — комната, потом sku; без HD берётся обычный адрес',
       [t['sku'] for t in picked] == ['1:b', '1:e', '1:d'] and picked[-1]['url'] == '//d')
    ok('адрес комнат — тот же приоритет HD, пустая строка = нет адреса',
       RURL == "coalesce(nullif(r.image_url_hd, ''), nullif(r.image_url, ''))" and RURL in rooms_rows_sql())
    ok('хеш и вырезка комнат — по адресу и sha выбранной строки', f'c.image_url = {RURL}' in rooms_rows_sql()
       and "a.assessor_version = 'a1'" in rooms_rows_sql('a1'))
    ok('лимит комнат по умолчанию 0 (ночь гостиной та же, пока не включат)',
       ROOMS_LIMIT == int(os.environ.get('PHOTO_ROOMS_LIMIT', '0')) and 'room_catalog' not in targets_sql(10))
    jobs = room_cutout_jobs([
        {**row('2:a', 'bedroom', 'кровать', sha='s1'), 'url': '//a'},
        {**row('2:b', 'bedroom', 'шкаф', sha='s1'), 'url': '//b'},                 # тот же sha — второй раз не режем
        {**row('2:c', 'bedroom', 'комод', sha='s2', verdict='ok'), 'url': '//c'},  # уже вырезан
        {**row('2:d', 'bedroom', 'комод'), 'url': '//d'},                          # хеша нет — ждёт хеша
        {**row('2:e', 'hall', 'обувница', sha='s3'), 'url': '//e'},                # sha уже в работе у гостиной
        {**row('2:f', 'hall', 'зеркало', sha='s4'), 'url': '//f'}], {'s3'}, 10)
    ok('вырезка комнат: один sha — одна работа, без хеша и с вырезкой — мимо, sha гостиной не дублируем',
       jobs == [('2:a', 'кровать', '//a', 's1'), ('2:f', 'зеркало', '//f', 's4')])
    ok('вырезка комнат: лимит 0 — ничего', room_cutout_jobs([{**row('2:a', 'bedroom', 'кровать', sha='s1'), 'url': '//a'}],
                                                             set(), 0) == [])
    good = parse_room_rows([['3:a', '', '//sd', 'bedroom', 'кровать', 'f', '', 'f', '', '.']])
    try:
        parse_room_rows([['3:a', '', '//sd', 'bedroom', 'кровать', 'f', '', 'f']])   # хвост срезан strip() — не молчим
        cut = False
    except RuntimeError:
        cut = True
    ok('разбор строк: пустой вердикт цел, срезанная строка — ошибка, не тихий пропуск',
       good[0]['verdict'] == '' and good[0]['fresh'] is False and cut)
    print(f'photo_hash selftest: ошибок {bad}')
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    if '--stats' in sys.argv:
        n, h = missing_stats()
        print(f'представителей mesh_required без хеша фото: {n}; старейший без хеша: {h:.1f} ч')
        print_rooms_stats(_assessor_version())
        return 0
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 1000
    rooms_limit = int(sys.argv[sys.argv.index('--rooms-limit') + 1]) if '--rooms-limit' in sys.argv else None
    only_mesh, dry = '--only-mesh' in sys.argv, '--dry' in sys.argv
    st = sync(limit, only_mesh=only_mesh, dry=dry, rooms_limit=rooms_limit)
    rs = st['rooms']
    print(f"хеш фото{' (СУХО, без записи)' if dry else ''}: к хешированию {st['targets']}, посчитано {st['hashed']}, "
          f"не скачалось {st['failed']}; комнаты — к хешированию {rs['targets']}, посчитано {rs['hashed']}, "
          f"не скачалось {rs['failed']}", flush=True)
    return 0


def _assessor_version() -> str:
    """Версия оценщика вырезки для счёта «с вырезкой» — из `salad/preprocess.py` текстом: модуль тянет torch, а `--stats` —
    сторожевой и должен быть лёгким. Не нашлась — счёт вырезки пустой, а не падение."""
    try:
        m = re.search(r"^ASSESSOR_VERSION\s*=\s*'([^']+)'", open(os.path.join(HERE, 'salad', 'preprocess.py'),
                                                                   encoding='utf-8').read(), re.M)
        return m.group(1) if m else ''
    except OSError:
        return ''


if __name__ == '__main__':
    sys.exit(main())
