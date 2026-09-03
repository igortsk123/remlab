#!/usr/bin/env python3
"""Загрузка каталога: свежие фиды Гдеслона (feeds2/*.zip) → upsert в products (+ product_enrichment).

Что делает (план catalog-load-hardening, П2; история — ADR-0068/0107/0141):
- Ключ товара — (merchant_id из АТРИБУТА оффера, id оффера). Раньше mid брался regex-ом из партнёрской
  ссылки; теперь ссылка — только фолбэк с WARN при расхождении.
- Из фида читаются ВСЕ нужные поля: article (артикул магазина — общий ключ с API Гдеслона),
  original_picture (крупное фото 800×600 → image_url_hd; раньше HD шло только через API и покрывало 63 %),
  description (пустое описание фида НЕ затирает уже известное).
- Отпечатки изменений (эффективные, версия HASH_VERSION): коммерческий, текстовый (по ЭФФЕКТИВНОМУ
  описанию), геометрический, картинки (image_url — контракт GPT), HD-картинки, параметров (весь
  канонизированный params). Смена смысла → product_enrichment.enrichment_status='stale' (payload остаётся,
  capabilities продолжает его читать); смена контракта хешей (HASH_VERSION) → baseline без stale.
- Предохранитель «похудевший фид» — ПО МАГАЗИНУ (mid) и против последнего УСПЕШНОГО прогона из
  журнала catalog_import_runs (не против числа строк в БД): похудевший магазин исключается из прогона
  (его строки и статусы не трогаются), остальные грузятся. Обход — FORCE_SHRINK=all|<mid,...>.
- Дедупликация (mid, external_id) до upsert; товары, статусы и хеши пишутся ОДНОЙ транзакцией.
- HD из фида пишется новым товарам и товарам без HD; товар с УЖЕ сгенерированным мешом без HD
  бэкфилл минует (его ведёт hd_backfill.py: сверка байтов, снятие ready, новое задание).
- Товары, исчезнувшие из свежего фида → status missing → archived (3 пропуска). Магазины без свежего
  фида (карантин feed_guard) не трогаем.
- НАЛИЧИЕ ЗДЕСЬ НЕ РЕШАЕТСЯ: `products.in_stock` считает `stock_truth.reconcile()` в конце прогона.

Запуск:  load3.py            — прогон (нужна БД)
         load3.py --selftest — чистый разбор фикстуры tests/fixtures/feed-mini.xml.zip, без БД
Env:     SCOUT_FEEDS_DIR, SCOUT_PSQL_CMD, SCOUT_ROLES_PATH, SCOUT_PRIORS_PATH (см. dim_resolver), FORCE_SHRINK
"""
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FEEDS = os.environ.get('SCOUT_FEEDS_DIR') or os.path.join(HERE, 'feeds2')
ROLES_PATH = os.environ.get('SCOUT_ROLES_PATH') or os.path.join(HERE, 'category-roles.json')
FRESH_PATH = os.path.join(HERE, 'feed-freshness.json')
PSQL = shlex.split(os.environ.get('SCOUT_PSQL_CMD') or '') or [
    "docker", "exec", "-i", "remlab-devdb", "psql", "-U", "remlab", "-d", "remlab", "-q", "-v", "ON_ERROR_STOP=1"]
HASH_VERSION = 2          # 1 — четыре хеша по фидовым полям; 2 — эффективное описание + attrs + hd
SHRINK_RATIO = 0.7
DESC_MAX = 1500

from dim_resolver import resolve as resolve_dims  # noqa: E402 — единицы по свидетельствам (T1)
from reflink import direct  # noqa: E402 — прямая ссылка строится тем же способом, что в catalog_media
import category_map  # noqa: E402 — is_kids, а после П3.5 — MIXED/role_by_name


def sql(q, inp=None):
    r = subprocess.run(PSQL, input=inp if inp is not None else q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:800], flush=True)
        sys.exit(1)
    return r.stdout


def sql_rows(q):
    """SELECT с разделителем \\x1f (без заголовков)."""
    r = subprocess.run(PSQL + ['-t', '-A', '-F', '\x1f'], input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:800], flush=True)
        sys.exit(1)
    return [line.split('\x1f') for line in r.stdout.split('\n') if line]


def esc(v):
    if v is None:
        return r'\N'
    return str(v).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', ' ')


# --- отпечатки ----------------------------------------------------------------------------------
_WS = re.compile(r'\s+')


def _h(*parts):
    s = '\x1f'.join('' if p is None else str(p) for p in parts)
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:20]


def _norm(t):
    return _WS.sub(' ', (t or '').strip().lower())


def commercial_hash(price, oldp, in_stock, url):
    return _h(price, oldp, in_stock, url)


def text_hash(name, desc):
    return _h(_norm(name), _norm(desc))


def geometry_hash(w, d, h, ln, dia):
    # округляем до сантиметра: фид иногда шлёт 60.0 и 60, это не изменение товара
    return _h(*[None if v is None else round(float(v)) for v in (w, d, h, ln, dia)])


def image_hash(url):
    return _h(_norm(url))


_PARAM_ALIAS = {'коллекция': 'коллекция/серия', 'серия': 'коллекция/серия'}


def canon_params(params: dict) -> dict:
    """Канонизация параметров для отпечатка: ключи и значения без лишних пробелов, регистра и «ё»,
    ×/x/* → «х», пустые значения выброшены, алиасы Коллекция/Серия слиты, порядок по ключу."""
    out = {}
    for k, v in (params or {}).items():
        kk = _WS.sub(' ', (k or '').strip().lower()).replace('ё', 'е')
        kk = _PARAM_ALIAS.get(kk, kk)
        vv = _WS.sub(' ', (v or '').strip().lower()).replace('ё', 'е')
        vv = re.sub(r'\s*[×x*]\s*', 'х', vv)
        if not kk or not vv:
            continue
        out[kk] = vv
    return dict(sorted(out.items()))


def attrs_hash(params: dict) -> str:
    return _h(json.dumps(canon_params(params), ensure_ascii=False, separators=(',', ':')))


# --- карты ---------------------------------------------------------------------------------------
def load_roles(path: str = ROLES_PATH) -> tuple[dict, set]:
    """(mid, cid) → роль; множество размеченных категорий (включая осознанный null)."""
    catrole, known = {}, set()
    for c in json.load(open(path, encoding='utf-8')).values():
        key = (int(c['mid']), str(c['id']))
        known.add(key)
        if c.get('role'):
            catrole[key] = c['role']
    return catrole, known


def load_fresh(path: str = FRESH_PATH) -> dict:
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:  # noqa: BLE001 — нет файла/битый JSON: карантина нет, грузим всё
        return {}


# --- разбор оффера (чистая функция, без БД) ---------------------------------------------------------
_MID_URL = re.compile(r'mid(?:=|%3D)(\d+)')


def _text(el, tag):
    return (el.findtext(tag) or '').strip()


def norm_hd(url: str | None) -> str | None:
    """original_picture → абсолютный https. `//host/...` → `https://host/...`; порт `:443` НЕ трогаем
    (divanboss шлёт `https://divanboss.ru:443/...`, и та же строка лежит в api_offers — иначе
    sync_photos сочтёт адрес новым и скачает 11 тыс. файлов заново)."""
    u = (url or '').strip()
    if not u:
        return None
    if u.startswith('//'):
        u = 'https:' + u
    if not u.startswith(('http://', 'https://')):
        return None
    return u


def parse_offer(el, cats: dict) -> dict | None:
    """Оффер фида → плоский словарь полей. Без ролей/размеров/БД. None — нет ключа магазина."""
    url = _text(el, 'url')
    attr_mid = el.get('merchant_id')
    m = _MID_URL.search(url)
    url_mid = int(m.group(1)) if m else None
    mid = int(attr_mid) if attr_mid and attr_mid.isdigit() else url_mid
    if mid is None:
        return None
    pic = _text(el, 'picture') or None
    if pic and '/None/' in pic:
        pic = None   # битый URL из фида — не скачается никогда (А2)
    desc = re.sub(r'<[^>]+>', ' ', el.findtext('description') or '')
    desc = re.sub(r'\s+', ' ', desc).strip()[:DESC_MAX] or None
    price, oldp = _text(el, 'price'), _text(el, 'oldprice')
    cid = _text(el, 'categoryId')
    d_url = direct(url)
    return {
        'mid': mid, 'mid_url': url_mid, 'mid_mismatch': bool(url_mid and url_mid != mid),
        'eid': el.get('id') or '', 'article': (el.get('article') or '').strip() or None,
        'name': _text(el, 'name') or _text(el, 'model'),
        'brand': _text(el, 'vendor') or None, 'url': url, 'direct_url': d_url,
        'shop': urllib.parse.urlparse(d_url).netloc.replace('www.', '') or str(mid),
        'pic': pic, 'pic_hd': norm_hd(_text(el, 'original_picture')),
        'price': int(float(price)) if price else None, 'oldprice': int(float(oldp)) if oldp else None,
        'cid': cid, 'cat_path': cats.get(cid, ''), 'desc': desc,
        'params': {p.get('name'): (p.text or '') for p in el.findall('param')},
    }


def assign(o: dict, catrole: dict, known: set) -> dict:
    """Роль и размеры. accepted=False — категория не нужна гостиной (или детское)."""
    key = (o['mid'], str(o['cid']))
    mixed = getattr(category_map, 'MIXED', set())
    role = None
    if key in catrole:
        role = catrole[key]
    elif f'{o["mid"]}:{o["cid"]}' in mixed and hasattr(category_map, 'role_by_name'):
        role = category_map.role_by_name(o['name'])          # П3.5: смешанная ветка — роль по названию
    accepted = bool(role)                                    # категория нужна гостиной (или MIXED дал роль)
    if role and category_map.is_kids(o['name']):
        role = None       # детское внутри разрешённых категорий: строка грузится, но БЕЗ роли (как и прежде —
                          # иначе 46 товаров divan.ru/tvoydom ушли бы в missing→archived при первом же прогоне)
    o['role'] = role
    o['known'] = key in known
    o['accepted'] = accepted
    if role:
        dims, ev, dsrc = resolve_dims(o['mid'], o['name'], o['params'], role)
        o['dims'], o['dims_evidence'], o['dims_source'] = dims, ev, dsrc
    else:
        o['dims'], o['dims_evidence'], o['dims_source'] = {'w': None, 'd': None, 'h': None, 'len': None, 'dia': None}, None, None
    o['feed_status'] = 'active' if o['price'] else 'out_of_stock'
    return o


def parse_feed(zip_path: str, catrole: dict, known: set):
    """→ (список офферов с полями и ролями, счётчики по mid)."""
    zf = zipfile.ZipFile(zip_path)
    name = zf.namelist()[0]
    cats, offers = {}, []
    raw = {}
    with zf.open(name) as f:
        for _, el in ET.iterparse(f):
            if el.tag == 'category':
                cats[el.get('id')] = el.text or ''
            if el.tag != 'offer':
                continue
            o = parse_offer(el, cats)
            el.clear()
            if o is None:
                continue
            raw[o['mid']] = raw.get(o['mid'], 0) + 1
            offers.append(assign(o, catrole, known))
    return offers, raw


def dedupe(offers: list[dict]) -> tuple[list[dict], dict]:
    """Одна строка на (mid, eid): первая побеждает; счётчик дублей по mid (в staging два одинаковых PK
    роняют `ON CONFLICT DO UPDATE ... cannot affect row a second time`)."""
    seen, out, dups = set(), [], {}
    for o in offers:
        k = (o['mid'], o['eid'])
        if k in seen:
            dups[o['mid']] = dups.get(o['mid'], 0) + 1
            continue
        seen.add(k)
        out.append(o)
    return out, dups


# --- строки для COPY -------------------------------------------------------------------------------
PRODUCT_COLS = ("shop_mid,external_id,shop,category_id,category_path,name,brand,url,image_url,image_url_hd,article,"
                "price_rub,old_price_rub,in_stock,w_cm,d_cm,h_cm,len_cm,dia_cm,dims_source,params,direct_url,"
                "description,cat_role,dims_evidence")
ENRICH_COLS = ("shop_mid,external_id,commercial_hash,text_hash,geometry_hash,image_hash,image_hd_hash,attrs_hash,"
               "hash_version,feed_status")


def product_row(o: dict) -> str:
    d = o['dims']
    return '\t'.join(esc(x) for x in (
        o['mid'], o['eid'], o['shop'], o['cid'], o['cat_path'], o['name'], o['brand'], o['url'], o['pic'], o['pic_hd'],
        o['article'], o['price'], o['oldprice'], 't', d['w'], d['d'], d['h'], d['len'], d['dia'], o['dims_source'],
        json.dumps(o['params'], ensure_ascii=False), o['direct_url'], o['desc'], o['role'],
        json.dumps(o['dims_evidence'], ensure_ascii=False) if o['dims_evidence'] else None))


def enrich_row(o: dict, effective_desc: str | None) -> str:
    d = o['dims']
    return '\t'.join(esc(x) for x in (
        o['mid'], o['eid'],
        commercial_hash(o['price'], o['oldprice'], bool(o['price']), o['direct_url']),
        text_hash(o['name'], effective_desc), geometry_hash(d['w'], d['d'], d['h'], d['len'], d['dia']),
        image_hash(o['pic']), image_hash(o['pic_hd'] or o['pic']), attrs_hash(o['params']),
        HASH_VERSION, o['feed_status']))


# --- схема ---------------------------------------------------------------------------------------
DDL = """
alter table products add column if not exists direct_url text;
alter table products add column if not exists last_seen date;
alter table products add column if not exists description text;
alter table products add column if not exists dims_evidence jsonb;
alter table products add column if not exists image_url_hd text;
alter table products add column if not exists article text;
create index if not exists products_article_idx on products (shop_mid, article) where article is not null;
alter table product_enrichment add column if not exists image_hd_hash text;
alter table product_enrichment add column if not exists attrs_hash text;
alter table product_enrichment add column if not exists hash_version int;
alter table product_enrichment add column if not exists enrichment_status text;  -- current|stale|pending
-- одноразовая миграция состояний: прежний сигнал «сброшенная версия» → pending, остальное — current
update product_enrichment set enrichment_status = case when payload is null or enrichment_version is null
                                                       then 'pending' else 'current' end
 where enrichment_status is null;
create table if not exists catalog_import_runs (
  id bigserial primary key, run_date date not null default current_date, feed_hash text, mid int not null,
  raw_count int not null, accepted_count int not null, dedup_dropped int not null default 0,
  previous_success_count int, verdict text not null, forced boolean not null default false,
  created_at timestamptz not null default now());
"""


# --- прогон --------------------------------------------------------------------------------------
def main() -> int:
    sql(DDL)
    catrole, known = load_roles()
    if not catrole:
        print('СТОП: карта категорий пуста — прогон отменён', flush=True)
        return 1
    print(f'карта категорий: {len(catrole)} нужных категорий', flush=True)
    fresh = load_fresh()
    mixed = getattr(category_map, 'MIXED', set())

    offers, raw_by_mid, feed_of_mid = [], {}, {}
    for z in sorted(glob.glob(os.path.join(FEEDS, '*.zip'))):
        fh = os.path.basename(z).split('.')[0]
        fst = (fresh.get(fh) or {}).get('state')
        if fst in ('broken', 'stale', 'empty') or not zipfile.is_zipfile(z):
            # карантин источника: старый архив каждый день ставил бы свежий last_seen товарам
            # исчезнувшего магазина (Codex 16.08)
            print(f'ФИД {fh[:12]} ПРОПУЩЕН: {fst or "не zip"} — товары магазина остаются как есть (карантин источника)', flush=True)
            continue
        offs, raw = parse_feed(z, catrole, known)
        offers.extend(offs)
        for mid, n in raw.items():
            raw_by_mid[mid] = raw_by_mid.get(mid, 0) + n
            feed_of_mid.setdefault(mid, fh)

    accepted = [o for o in offers if o['accepted']]
    mismatch = sum(1 for o in offers if o['mid_mismatch'])
    if mismatch:
        print(f'WARN:mid_mismatch: у {mismatch} офферов merchant_id не совпадает с mid в ссылке (взят атрибут)', flush=True)
    no_hd = sum(1 for o in accepted if not o['pic_hd'])
    if accepted and no_hd / len(accepted) > 0.01:
        print(f'WARN:no_original_picture: у {no_hd} из {len(accepted)} офферов нет original_picture — формат фида изменился?', flush=True)
    dropped_unknown, dropped_known = {}, {}
    for o in offers:
        if o['accepted']:
            continue
        if not o['known'] and f'{o["mid"]}:{o["cid"]}' not in mixed:
            dropped_unknown[o['mid']] = dropped_unknown.get(o['mid'], 0) + 1
        else:
            k = (o['mid'], o['cat_path'] or o['cid'])
            dropped_known[k] = dropped_known.get(k, 0) + 1
    accepted, dups = dedupe(accepted)
    per_shop = {}
    for o in accepted:
        per_shop[o['shop']] = per_shop.get(o['shop'], 0) + 1
    print('офферов в свежих фидах:', len(accepted), per_shop, flush=True)
    print('строк с description:', sum(1 for o in accepted if o['desc']), flush=True)
    for mid, n in dups.items():
        print(f'WARN:dedupe: mid={mid} повторов (mid, id) в фиде: {n} — взята первая строка', flush=True)
    if dropped_unknown:
        for m, n in sorted(dropped_unknown.items(), key=lambda kv: -kv[1]):
            print(f'БЕЗ РОЛИ: mid={m} выброшено {n} офферов (категории нет в карте)', flush=True)
    if dropped_known:
        top = sorted(dropped_known.items(), key=lambda kv: -kv[1])[:5]
        print('выброшено по известным null-категориям (топ-5): ' + '; '.join(f'mid={m} «{p[:60]}» {n}' for (m, p), n in top), flush=True)

    # --- предохранитель «похудевший фид» — ПО МАГАЗИНУ, против последнего успешного прогона --------
    acc_by_mid = {}
    for o in accepted:
        acc_by_mid[o['mid']] = acc_by_mid.get(o['mid'], 0) + 1
    mids = set(acc_by_mid) | set(raw_by_mid)
    if not mids:
        print('СТОП: ни одного оффера ни в одном свежем фиде', flush=True)
        return 2
    baseline = {int(r[0]): int(r[1]) for r in sql_rows(
        "select distinct on (mid) mid, accepted_count from catalog_import_runs "
        "where verdict in ('ok','forced') order by mid, created_at desc") if len(r) == 2}
    db_prev = {int(r[0]): int(r[1]) for r in sql_rows(
        "select shop_mid, count(*) from product_enrichment where status<>'archived' group by 1") if len(r) == 2}
    force_env = os.environ.get('FORCE_SHRINK', '')
    forced_all = force_env == 'all'
    forced_mids = {int(x) for x in re.findall(r'\d+', force_env)} if not forced_all else set()
    shrunk, ledger = set(), []
    for mid in sorted(mids):
        acc = acc_by_mid.get(mid, 0)
        prev = baseline.get(mid, db_prev.get(mid, 0))
        forced = forced_all or mid in forced_mids
        if prev and acc < SHRINK_RATIO * prev and not forced:
            shrunk.add(mid)
            verdict = 'shrunk'
            print(f'WARN:shrink: mid={mid} офферов сегодня {acc} < {int(SHRINK_RATIO*100)}% от последнего успешного {prev} — '
                  f'магазин пропущен, статусы не трогаю (осознанно — FORCE_SHRINK={mid})', flush=True)
        else:
            verdict = 'forced' if (forced and prev and acc < SHRINK_RATIO * prev) else 'ok'
        ledger.append((feed_of_mid.get(mid), mid, raw_by_mid.get(mid, 0), acc, dups.get(mid, 0), prev, verdict, forced))
    if shrunk:
        accepted = [o for o in accepted if o['mid'] not in shrunk]
        mids -= shrunk
    if not mids or not accepted:
        print('СТОП: после предохранителя не осталось магазинов для загрузки', flush=True)
        return 2
    mlist = ','.join(map(str, sorted(mids)))

    # --- эффективное описание: пустое в фиде не затирает известное, и отпечаток считаем от него ----
    old_desc = {(int(r[0]), r[1]): r[2] for r in sql_rows(
        f"select shop_mid, external_id, description from products where shop_mid in ({mlist}) "
        "and coalesce(description,'') <> ''") if len(r) == 3}
    rows = [product_row(o) for o in accepted]
    erows = [enrich_row(o, o['desc'] or old_desc.get((o['mid'], o['eid']))) for o in accepted]
    ledger_vals = ','.join(
        "(" + ','.join(['NULL' if fh is None else f"'{fh}'", str(mid), str(rawn), str(acc), str(dd), 'NULL' if prev is None else str(prev), f"'{v}'",
                        'true' if f else 'false']) + ")" for fh, mid, rawn, acc, dd, prev, v, f in ledger)

    # --- одна транзакция: товары + отпечатки/статусы + журнал ------------------------------------
    script = f"""
begin;
create temp table products_new (like products including defaults) on commit drop;
copy products_new({PRODUCT_COLS}) from stdin;
{chr(10).join(rows)}
\\.
create temp table enrich_new (shop_mid int, external_id text, commercial_hash text, text_hash text,
  geometry_hash text, image_hash text, image_hd_hash text, attrs_hash text, hash_version int, feed_status text) on commit drop;
copy enrich_new({ENRICH_COLS}) from stdin;
{chr(10).join(erows)}
\\.
create temp table delta on commit drop as
select n.shop_mid, n.external_id,
       (e.shop_mid is null) as is_new,
       (e.shop_mid is not null and e.hash_version is distinct from n.hash_version) as is_baseline,
       (e.text_hash is distinct from n.text_hash) as ch_text,
       (e.geometry_hash is distinct from n.geometry_hash) as ch_geom,
       (e.image_hash is distinct from n.image_hash) as ch_img,
       (e.image_hd_hash is distinct from n.image_hd_hash) as ch_hd,
       (e.attrs_hash is distinct from n.attrs_hash) as ch_attrs,
       (e.commercial_hash is distinct from n.commercial_hash) as ch_comm
  from enrich_new n left join product_enrichment e using (shop_mid, external_id);
insert into products as p ({PRODUCT_COLS},last_seen)
select {PRODUCT_COLS},current_date from products_new
on conflict (shop_mid,external_id) do update set
  name=excluded.name,url=excluded.url,image_url=excluded.image_url,price_rub=excluded.price_rub,
  old_price_rub=excluded.old_price_rub,direct_url=excluded.direct_url,last_seen=current_date,
  article=coalesce(excluded.article,p.article),
  -- HD из фида: новым и тем, у кого HD нет; товар с ревизией меша без HD ведёт hd_backfill.py
  image_url_hd=case when p.image_url_hd is not null then p.image_url_hd
                    when exists (select 1 from asset_revisions r where r.sku = p.shop_mid||':'||p.external_id) then p.image_url_hd
                    else excluded.image_url_hd end,
  -- пустое описание фида не затирает известное
  description=coalesce(nullif(excluded.description,''), p.description),
  -- authority сильнее свежести: scrape/manual фид не затирает; остальное — resolver каждый прогон
  w_cm   =case when p.dims_source in ('scrape','manual') then p.w_cm    else excluded.w_cm    end,
  d_cm   =case when p.dims_source in ('scrape','manual') then p.d_cm    else excluded.d_cm    end,
  h_cm   =case when p.dims_source in ('scrape','manual') then p.h_cm    else excluded.h_cm    end,
  len_cm =case when p.dims_source in ('scrape','manual') then p.len_cm  else excluded.len_cm  end,
  dia_cm =case when p.dims_source in ('scrape','manual') then p.dia_cm  else excluded.dia_cm  end,
  dims_source  =case when p.dims_source in ('scrape','manual') then p.dims_source   else excluded.dims_source   end,
  dims_evidence=case when p.dims_source in ('scrape','manual') then p.dims_evidence else excluded.dims_evidence end,
  params=excluded.params, cat_role=excluded.cat_role,
  category_id=excluded.category_id, category_path=excluded.category_path;
insert into product_enrichment as e (shop_mid,external_id,commercial_hash,text_hash,geometry_hash,image_hash,
       image_hd_hash,attrs_hash,hash_version,status,enrichment_status,missing_runs,missing_since,last_seen)
select shop_mid,external_id,commercial_hash,text_hash,geometry_hash,image_hash,image_hd_hash,attrs_hash,hash_version,
       feed_status,'pending',0,null,current_date
from enrich_new
on conflict (shop_mid,external_id) do update set
  commercial_hash=excluded.commercial_hash, text_hash=excluded.text_hash, geometry_hash=excluded.geometry_hash,
  image_hash=excluded.image_hash, image_hd_hash=excluded.image_hd_hash, attrs_hash=excluded.attrs_hash,
  hash_version=excluded.hash_version,
  status=excluded.status, missing_runs=0, missing_since=null,
  -- смена контракта хешей → baseline (статус не трогаем); смена смысла (текст/размеры/картинка GPT/
  -- параметры) → stale: payload остаётся читаемым, todo() возьмёт товар в переобогащение
  enrichment_status=case
      when e.hash_version is distinct from excluded.hash_version then coalesce(e.enrichment_status,'current')
      when e.payload is null then 'pending'
      when e.text_hash is distinct from excluded.text_hash
        or e.geometry_hash is distinct from excluded.geometry_hash
        or e.image_hash is distinct from excluded.image_hash
        or e.attrs_hash is distinct from excluded.attrs_hash then 'stale'
      else coalesce(e.enrichment_status,'current') end,
  last_seen=current_date, updated_at=now();
-- пропал из свежего фида своего магазина: помечаем; три пропуска подряд → архив. Считаем ДНИ, а не
-- прогоны: второй прогон за день (--force, @reboot) раньше добавлял второй пропуск (03.09: 97 товаров
-- ушли в архив на день раньше срока)
update product_enrichment e set missing_runs=e.missing_runs+1,
       missing_since=coalesce(e.missing_since,current_date),
       status=case when e.missing_runs+1>=3 then 'archived' else 'missing' end,
       updated_at=now()
 where e.shop_mid in ({mlist})
   and e.status <> 'archived'
   and (e.status <> 'missing' or e.updated_at::date < current_date)
   and not exists (select 1 from enrich_new n where n.shop_mid=e.shop_mid and n.external_id=e.external_id);
update products p set status=e.status
  from product_enrichment e
 where p.shop_mid=e.shop_mid and p.external_id=e.external_id and p.shop_mid in ({mlist})
   and p.status is distinct from e.status;
insert into catalog_import_runs (feed_hash, mid, raw_count, accepted_count, dedup_dropped, previous_success_count, verdict, forced)
values {ledger_vals};
select 'ДЕЛЬТА новых: '||count(*) filter (where is_new)
     ||'; baseline(смена контракта хешей): '||count(*) filter (where is_baseline)
     ||'; сменили текст: '||count(*) filter (where ch_text and not is_new and not is_baseline)
     ||'; размеры: '||count(*) filter (where ch_geom and not is_new and not is_baseline)
     ||'; картинку: '||count(*) filter (where ch_img and not is_new and not is_baseline)
     ||'; HD: '||count(*) filter (where ch_hd and not is_new and not is_baseline)
     ||'; параметры: '||count(*) filter (where ch_attrs and not is_new and not is_baseline)
     ||'; только цена/наличие: '||count(*) filter (where ch_comm and not is_new and not is_baseline
           and not ch_text and not ch_geom and not ch_img and not ch_attrs)
  from delta;
commit;
"""
    out = subprocess.run(PSQL + ['-t', '-A'], input=script, capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr[:1200], flush=True)
        print('СТОП: транзакция загрузки откатилась — товары и статусы не изменены', flush=True)
        return 1
    for line in out.stdout.split('\n'):
        if line.startswith('ДЕЛЬТА'):
            print(line, flush=True)
    print(sql("select shop, count(*) filter (where in_stock) live, count(*) filter (where not in_stock) dead "
              "from products group by 1 order by 2 desc;"))
    print('СТАТУСЫ', ' '.join(f'{r[0]}:{r[1]}' for r in sql_rows(
        "select status, count(*) from product_enrichment group by status order by count(*) desc")), flush=True)
    print('ОБОГАЩЕНИЕ', ' '.join(f'{r[0]}:{r[1]}' for r in sql_rows(
        "select coalesce(enrichment_status,'?'), count(*) from product_enrichment group by 1 order by 2 desc")), flush=True)

    # ---------- наличие: одно место, где оно вычисляется ------------------------------------------
    from stock_truth import audit as stock_audit, reconcile as stock_reconcile  # noqa: E402
    stock_reconcile()
    if stock_audit():
        print('ВНИМАНИЕ: наличие расходится с формулой — см. stock_truth.py --audit', flush=True)
    return 0


# --- селфтест: чистый разбор фикстуры, без БД ---------------------------------------------------
def selftest() -> int:
    fx = os.path.join(HERE, 'tests', 'fixtures')
    os.environ.setdefault('SCOUT_PRIORS_PATH', os.path.join(fx, 'unit-priors-mini.json'))
    catrole, known = load_roles(os.path.join(fx, 'category-roles-mini.json'))
    offers, raw = parse_feed(os.path.join(fx, 'feed-mini.xml.zip'), catrole, known)
    by_id = {o['eid']: o for o in offers}
    bad = 0

    def check(name, cond, detail=''):
        nonlocal bad
        if not cond:
            bad += 1
            print(f'  FAIL {name} {detail}')

    manifest = json.load(open(os.path.join(fx, 'feed-mini.manifest.json'), encoding='utf-8'))
    check('все офферы фикстуры разобраны', len(offers) == len(manifest), f'{len(offers)} != {len(manifest)}')
    for m in manifest:
        o = by_id.get(m['id'])
        check(f'оффер {m["id"]} найден', o is not None)
        if not o:
            continue
        check(f'{m["id"]}: mid из атрибута', o['mid'] == m['mid'] and not o['mid_mismatch'])
        check(f'{m["id"]}: article из атрибута', o['article'] == (m['article'] or None), o['article'])
        c = m['case']
        if 'original_picture' in c or 'divan:' in c:
            check(f'{m["id"]}: HD абсолютный https', (o['pic_hd'] or '').startswith('https://'), o['pic_hd'])
        if ':443' in c:
            check(f'{m["id"]}: порт :443 сохранён', ':443' in (o['pic_hd'] or ''), o['pic_hd'])
        if 'роль по категории' in c:
            check(f'{m["id"]}: роль диван', o['role'] == 'диван' and o['accepted'], o['role'])
            check(f'{m["id"]}: описание непустое', bool(o['desc']))
        if 'Распродажа' in c:
            # до П3.5 (MIXED) ветка выбрасывается целиком; категория карте ИЗВЕСТНА (осознанный null)
            expect_role = 'кресло' if hasattr(category_map, 'MIXED') and 'кресло' in c else None
            check(f'{m["id"]}: Распродажа → роль {expect_role}', o['role'] == expect_role, o['role'])
            check(f'{m["id"]}: категория известна карте', o['known'])
        if 'стул' in c:
            check(f'{m["id"]}: высота стула 87', o['dims']['h'] == 87, o['dims'])
        if 'пустое описание' in c:
            check(f'{m["id"]}: описание None', o['desc'] is None, o['desc'])
        if 'Пантографы' in c:
            expect = None if getattr(category_map, 'OVERRIDES', None) else 'шкаф'
            check(f'{m["id"]}: пантограф → роль {expect}', o['role'] == expect, o['role'])
        if 'gipfel' in c:
            check(f'{m["id"]}: высота статуэтки в см (165 мм → 16.5)', o['dims']['h'] is not None and 10 < o['dims']['h'] < 20, o['dims'])
    # синтетика: два оффера с одной картинкой — оба приняты, у них разные id
    same = [o for o in offers if o['pic'] and sum(1 for x in offers if x['pic'] == o['pic']) > 1]
    check('две записи с одной картинкой обе приняты', len(same) == 2 and same[0]['eid'] != same[1]['eid'], len(same))
    # дедуп по (mid, eid)
    d, dups = dedupe(offers + [offers[0]])
    check('дедуп (mid,eid): одна строка, счётчик 1', len(d) == len(offers) and dups.get(offers[0]['mid']) == 1, dups)
    # канонизация параметров
    check('attrs: пробелы/регистр', attrs_hash({'Цвет': ' Серый '}) == attrs_hash({'цвет': 'серый'}))
    check('attrs: ё и ×', attrs_hash({'Размер': '120 × 60'}) == attrs_hash({'Размер': '120x60'}) == attrs_hash({'размер': '120Х60'.lower()}))
    check('attrs: алиас Коллекция/Серия', attrs_hash({'Коллекция': 'Босс'}) == attrs_hash({'Серия': 'босс'}))
    check('attrs: пустое значение = отсутствие', attrs_hash({'Цвет': '', 'Материал': 'дуб'}) == attrs_hash({'Материал': 'дуб'}))
    check('attrs: порядок ключей', attrs_hash({'a': '1', 'b': '2'}) == attrs_hash({'b': '2', 'a': '1'}))
    check('text_hash: эффективное описание', text_hash('x', 'old') != text_hash('x', None))
    check('accepted ⊇ role: строка с ролью всегда принята', all(o['accepted'] for o in offers if o['role']))
    check('norm_hd: // → https', norm_hd('//cdn.shop.ru/a.jpg') == 'https://cdn.shop.ru/a.jpg')
    check('norm_hd: не URL → None', norm_hd('картинка.jpg') is None and norm_hd('') is None)
    # строки COPY собираются без исключений и с нужным числом колонок
    for o in offers:
        check(f'{o["eid"]}: product_row колонок', product_row(o).count('\t') == PRODUCT_COLS.count(','))
        check(f'{o["eid"]}: enrich_row колонок', enrich_row(o, o['desc']).count('\t') == ENRICH_COLS.count(','))
    print(f'load3 selftest: офферов {len(offers)}, магазинов {len(raw)}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
