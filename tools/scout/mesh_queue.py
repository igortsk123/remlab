#!/usr/bin/env python3
"""Автоочередь мешей: «что отдавать на генерацию» считается само (ADR-0131).

Методика отбора зафиксирована владельцем 28.08: роли слотов сетов × ворота пригодности
подбора (in_stock + живое фото + enrichment quality ≥ 0.65). Спрос (demand) шире, чем
«кто стоит в сетах», иначе жёсткое правило «сеты только с мешами» голодает — новые
кандидаты замены никогда не получат меш:
  1) товары, СТОЯЩИЕ в сетах (sets3.json) — приоритет 1;
  2) top-K кандидатов каждой корзины candidates-index (после ВСЕХ немешевых ворот
     compose2: конверт, подтип, качество) — приоритет 2;
  3) резерв направленных ролей из БД по тем же воротам — приоритет 3.

Истина состояния — dev-Postgres (control plane, Codex q25), а не файл: файл очереди —
только ЭКСПОРТ батча в формате заданий mesh_pilot (совместим с salad/submit.py).
Идентичность входа — SHA-256 БАЙТОВ фото (source ingest), не URL и не phash: URL живёт
дольше содержимого и наоборот (TOCTOU). Байты не храним (диск DEV-VM мал) — воркер Salad
скачивает сам и сверяет хеш; разошёлся → вход устарел, задание не выполняется.

  ~/venvs/scout/bin/python mesh_queue.py --run              # пересчёт demand + ingest + постановка
  ~/venvs/scout/bin/python mesh_queue.py --export batch.json  # экспорт queued-заданий
  ~/venvs/scout/bin/python mesh_queue.py --report           # состояние конвейера
Повторный --run без изменений каталога обязан дать 0 новых заданий (гейт плана).
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = os.path.join(HERE, 'sets3.json')
CAND = os.path.join(HERE, 'candidates-index.json')
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

# Мягкий декор рисует модель по фото (viz_paste.SOFT), плоское — варп; мешей им не надо.
MESH_EXCLUDE = {'подушка', 'плед', 'ковёр', 'шторы', 'картина', 'зеркало', 'часы', 'полка'}
# Направленные роли (фронт обязателен) — ADR-0131; банкетка решается ПРИЗНАКОМ спинки.
DIRECTED = {'диван', 'кресло', 'стул', 'тв-тумба', 'стеллаж', 'комод', 'стенка',
            'витрина', 'камин'}
TOP_K_PER_BUCKET = int(os.environ.get('MESH_TOPK', '5'))
RESERVE_PER_ROLE = int(os.environ.get('MESH_RESERVE', '30'))
INGEST_MAX = int(os.environ.get('MESH_INGEST_MAX', '200'))   # скачиваний фото за прогон
PIPELINE_VERSION = os.environ.get('PIPELINE_VERSION', 'v1')

SCHEMA = """
create table if not exists mesh_demand (
  sku text primary key,
  role text not null,
  priority int not null,            -- 1 в сете, 2 кандидат слота, 3 резерв
  status text not null default 'wanted',   -- wanted|not_required|superseded
  image_url text,
  source_sha text,                  -- SHA-256 байтов фото; null = ingest ещё не был
  sha_at timestamptz,               -- когда хеш посчитан (для периодической перепроверки)
  dims jsonb,
  name text,
  first_seen timestamptz default now(),
  last_seen timestamptz default now()
);
create table if not exists mesh_jobs (
  job_key text primary key,         -- sku|source_sha|pipeline_version
  sku text not null,
  status text not null default 'queued',   -- queued|submitted|running|retry_wait|failed_terminal|completed
  batch_id text,
  attempts int not null default 0,
  created timestamptz default now(),
  updated timestamptz default now()
);
create table if not exists asset_revisions (
  revision_key text primary key,    -- sku|source_sha|pipeline_version (ключ генерации)
  sku text not null,
  glb_sha text,
  status text not null default 'generated',  -- generated|acceptance_pending|accepted|rejected|superseded
  origin text,                      -- salad|legacy-local
  manifest jsonb,
  created timestamptz default now(),
  updated timestamptz default now()
);
create table if not exists orientation_state (
  revision_key text primary key,
  sku text not null,
  status text not null default 'pending',
  -- not_required|pending|auto_resolved|vlm_pending|review_pending|human_resolved
  resolution jsonb,                 -- raw_to_canonical quaternion + версии + evidence
  updated timestamptz default now()
);
-- Догоняющие правки: таблицы создаются через `if not exists`, поэтому новые колонки на живой
-- базе появляются только так. Каждая строка идемпотентна — блок гоняется каждым запуском.
alter table mesh_demand add column if not exists sha_at timestamptz;
"""


def db(sql: str, quiet: bool = True) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def q(s: str | None) -> str:
    return "'" + str(s or '').replace("'", "''") + "'"


def base_role(slot: str) -> str:
    """Слот «кресло 3» → роль «кресло»; «стол обеденный» НЕ резать (грабля q25)."""
    parts = slot.split(' ')
    return slot if not parts[-1].isdigit() else ' '.join(parts[:-1])


def directed(role: str, name: str, subtype: str | None) -> bool:
    if role in DIRECTED:
        return True
    if role in ('пуф', 'банкетка'):
        t = f'{name} {subtype or ""}'.lower()
        return 'спинк' in t          # банкетка со спинкой направлена (q25)
    return False


# ---------------------------------------------------------------- источники спроса

def demand_from_sets() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in json.load(open(SETS)):
        for slot, it in (s.get('items') or {}).items():
            role = base_role(slot)
            if not it or role in MESH_EXCLUDE:
                continue
            sku = f"{it.get('mid')}:{it.get('eid')}"
            if ':' not in sku or sku.startswith('None'):
                continue
            out.setdefault(sku, {
                'role': role, 'priority': 1, 'image_url': it.get('img'),
                'name': it.get('name'),
                'dims': {'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
                         'dia': it.get('dia')}})
    return out


def demand_from_candidates() -> dict[str, dict]:
    """top-K каждой корзины индекса кандидатов: это уже «после немешевых ворот»."""
    ci = json.load(open(CAND))
    items, out = ci.get('items', {}), {}
    for bucket, skus in (ci.get('index') or {}).items():
        role = bucket.split('|')[0]
        if role in MESH_EXCLUDE:
            continue
        for sku in skus[:TOP_K_PER_BUCKET]:
            it = items.get(sku)
            if not it or not it.get('img'):
                continue
            out.setdefault(sku, {
                'role': role, 'priority': 2, 'image_url': it['img'], 'name': it.get('name'),
                'dims': {'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
                         'dia': it.get('dia')}})
    return out


def demand_reserve() -> dict[str, dict]:
    """Резерв направленных ролей прямо из БД — ворота методики (ADR-0131)."""
    roles = ','.join(q(r) for r in sorted(DIRECTED))
    rows = db(f"""
      select p.shop_mid||':'||p.external_id, p.cat_role, p.image_url,
             regexp_replace(coalesce(p.name,''), E'[\\n\\r\\x1f]', ' ', 'g')
        from products p
        join product_enrichment e using (shop_mid, external_id)
       where p.cat_role in ({roles}) and p.in_stock and p.image_url is not null
         and e.status='active' and e.payload is not null and e.quality >= 0.65
       order by p.cat_role, e.quality desc, p.shop_mid, p.external_id
    """)
    out, per_role = {}, {}
    for row in rows:
        if len(row) != 4:
            continue                  # имя с переводом строки порвало строку вывода psql
        sku, role, img, name = row
        if per_role.get(role, 0) >= RESERVE_PER_ROLE:
            continue
        per_role[role] = per_role.get(role, 0) + 1
        out[sku] = {'role': role, 'priority': 3, 'image_url': img, 'name': name, 'dims': None}
    return out


# ---------------------------------------------------------------- ingest и постановка

SHA_MAX_AGE_DAYS = int(os.environ.get('MESH_SHA_MAX_AGE_DAYS', '30'))


def ingest(limit: int) -> int:
    """SHA-256 байтов фото для demand-строк без него. Байты выбрасываем — хеш остаётся.

    Перехешируем не только новые строки, но и те, чей хеш старше `SHA_MAX_AGE_DAYS`: магазин
    может подменить картинку под ТЕМ ЖЕ адресом, и тогда смену не поймать ни по URL, ни по
    расписанию фида. Без этого меш от старого фото молча числится свежим.
    """
    rows = db("select sku, image_url from mesh_demand "
              "where status='wanted' and image_url is not null "
              "  and (source_sha is null "
              f"       or sha_at is null or sha_at < now() - interval '{SHA_MAX_AGE_DAYS} days') "
              f"order by (source_sha is not null), priority, sku limit {limit}")
    n = 0
    for sku, url in rows:
        try:
            if url.startswith('//'):
                url = 'https:' + url          # фид отдаёт протокол-относительные URL
            with urllib.request.urlopen(url, timeout=30) as r:
                sha = hashlib.sha256(r.read()).hexdigest()
            db(f"update mesh_demand set source_sha={q(sha)}, sha_at=now() where sku={q(sku)}")
            n += 1
        except Exception as e:  # noqa: BLE001 — мёртвое фото не валит прогон, строка ждёт
            print(f'  ingest {sku}: {str(e)[:80]}', flush=True)
    return n


def reconcile_legacy() -> int:
    """Bootstrap: старые локальные меши → asset_revisions, чтобы дифф «сделано» их видел.
    Канонический кэш по товарам — ~/scout-scenes/meshes/<mid>_<eid>[-generator].manifest.json."""
    import glob
    import re
    n = 0
    for man in glob.glob(os.path.join(SCENE_DIR, 'meshes', '*.manifest.json')):
        base = os.path.basename(man)[:-len('.manifest.json')]
        m = re.match(r'(\d+)_(\d+)(?:-(.+))?$', base)
        if not m:
            continue
        sku, gen = f'{m.group(1)}:{m.group(2)}', m.group(3) or 'trellis'
        try:
            v = json.load(open(man))
        except Exception:  # noqa: BLE001 — битый манифест не валит прогон
            continue
        rk = f'{sku}|legacy|{gen}'
        # Legacy (fal/Trellis) НЕ закрывает спрос: владелец 28.08 — генерация только
        # Hunyuan 2.1 на Salad. Ревизия фиксируется для истории как superseded.
        st = 'superseded'
        _ = v.get('status')
        db(f"""insert into asset_revisions (revision_key, sku, glb_sha, status, origin, manifest)
               values ({q(rk)}, {q(sku)}, {q(v.get('glb_sha'))}, {q(st)}, 'legacy-local',
                       {q(json.dumps(v, ensure_ascii=False))}::jsonb)
               on conflict (revision_key) do nothing""")
        n += 1
    return n


def run() -> None:
    db(SCHEMA)
    want = demand_from_sets()
    for sku, v in demand_from_candidates().items():
        want.setdefault(sku, v)
    for sku, v in demand_reserve().items():
        want.setdefault(sku, v)

    for sku, v in want.items():
        db(f"""insert into mesh_demand (sku, role, priority, image_url, dims, name)
               values ({q(sku)}, {q(v['role'])}, {v['priority']}, {q(v['image_url'])},
                       {q(json.dumps(v['dims'], ensure_ascii=False))}::jsonb, {q(v['name'])})
               on conflict (sku) do update set
                 -- Приоритет ПЕРЕСЧИТЫВАЕТСЯ, а не берётся минимумом: least() делал его липким,
                 -- и товар, однажды побывавший в сете, навсегда оставался приоритетом 1 даже
                 -- уйдя в резерв — очередь генерации выстраивалась по прошлому, а не по спросу.
                 priority=excluded.priority,
                 image_url=excluded.image_url, last_seen=now(),
                 -- Смена картинки под тем же URL обязана сбросить хеш: `ingest()` считает его
                 -- только там, где он null, поэтому без сброса новые байты остаются незамеченными
                 -- и меш от старого фото продолжает числиться свежим.
                 source_sha=case when mesh_demand.image_url is distinct from excluded.image_url
                                 then null else mesh_demand.source_sha end,
                 status=case when mesh_demand.status='not_required' then 'wanted'
                             else mesh_demand.status end""")
    # выпавшие из спроса (нет в сетах/кандидатах/резерве) — не гоняем, но и не трогаем сделанное
    skus = ','.join(q(s) for s in want) or "''"
    db(f"update mesh_demand set status='not_required' "
       f"where status='wanted' and sku not in ({skus})")

    got = ingest(INGEST_MAX)
    legacy = reconcile_legacy()

    # постановка: спрос с хешом, ещё не сгенерированный этим ключом и без активного задания
    new = db(f"""
      insert into mesh_jobs (job_key, sku)
      select d.sku||'|'||d.source_sha||'|'||{q(PIPELINE_VERSION)}, d.sku
        from mesh_demand d
       where d.status='wanted' and d.source_sha is not null
         and not exists (select 1 from asset_revisions r
                          where r.sku=d.sku and r.status='accepted')
         and not exists (select 1 from mesh_jobs j
                          where j.job_key = d.sku||'|'||d.source_sha||'|'||{q(PIPELINE_VERSION)})
      on conflict (job_key) do nothing
      returning job_key""")
    print(f'[mesh_queue] спрос {len(want)} | ingest +{got} | legacy-ревизий {legacy} | '
          f'новых заданий {len(new)}', flush=True)


def export(path: str) -> None:
    rows = db("""select j.job_key, d.sku, d.role, d.image_url, d.dims, d.name
                   from mesh_jobs j join mesh_demand d using (sku)
                  where j.status='queued' order by d.priority, d.sku""")
    jobs = []
    for jk, sku, role, img, dims, name in rows:
        jobs.append({'sku': sku, 'mid': int(sku.split(':')[0]), 'eid': sku.split(':')[1],
                     'role': role, 'name': name, 'image_url': img,
                     'dims_cm': json.loads(dims) if dims and dims != '\\N' else None,
                     'source_sha': jk.split('|')[1], 'seeds': [0]})
    json.dump({'source': 'mesh_queue', 'pipeline': PIPELINE_VERSION,
               'skus': len(jobs), 'jobs': jobs},
              open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'[mesh_queue] экспорт {len(jobs)} заданий → {path}', flush=True)


def report() -> None:
    db(SCHEMA)
    for t, sql in (('спрос', 'select status, count(*) from mesh_demand group by 1'),
                   ('задания', 'select status, count(*) from mesh_jobs group by 1'),
                   ('ревизии', 'select status, count(*) from asset_revisions group by 1'),
                   ('ориентация', 'select status, count(*) from orientation_state group by 1')):
        rows = db(sql)
        print(f'{t}: ' + (', '.join(f'{a}={b}' for a, b in rows) or 'пусто'), flush=True)


if __name__ == '__main__':
    if '--run' in sys.argv:
        run()
    elif '--export' in sys.argv:
        export(sys.argv[sys.argv.index('--export') + 1])
    elif '--report' in sys.argv:
        report()
    else:
        print(__doc__)
