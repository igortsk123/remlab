#!/usr/bin/env python3
"""Бэкфилл крупного фото (HD) товарам, у которых УЖЕ есть сгенерированный меш (план catalog-load-hardening П2.3).

Почему отдельно от load3: смена адреса картинки у товара с мешом делает меш «не по текущему фото» —
`cutout_sync` перехеширует байты, `mesh_queue` подхватит новый source_sha, `mesh_ready()` скажет «не готов»,
`mesh_bind` поставит `stale`, планировщик поставит новое задание. Это честно (урок 313: готовность привязана к
версии входа), но делать это надо явно и по списку, а не молчаливым флагом в утреннем цикле.

Что делает для каждого SKU из очереди (in_stock, image_url_hd пуст, есть ревизия меша):
  1. берёт original_picture из свежего фида магазина;
  2. качает текущее фото (по адресу из product_photo_current, иначе image_url) и HD, сравнивает SHA байтов;
  3. байты одинаковые → только записывает адрес HD (перехеширования не будет);
     разные → записывает HD и СРАЗУ обновляет product_photo_current новым SHA (cutout_sync не тратит
     обход на повторную закачку), меш станет stale при ближайшем mesh_bind;
  4. пишет строку в hd_backfill_log.

  hd_backfill.py --dry            # только сравнить и показать
  hd_backfill.py --limit 5        # применить к 5 SKU (по приоритету: сначала товары из опубликованных сетов)
  hd_backfill.py --limit 0        # применить ко всем
"""
import hashlib
import os
import re
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FEEDS = os.environ.get('SCOUT_FEEDS_DIR') or os.path.join(HERE, 'feeds2')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) remlab-catalog/1.0'}

sys.path.insert(0, HERE)
from load3 import norm_hd  # noqa: E402 — одна и та же нормализация HD-адреса


def db(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:600])
    return [line.split('\x1f') for line in r.stdout.split('\n') if line]


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def hd_from_feeds(ids: dict[str, int]) -> dict[str, str]:
    """external_id → original_picture из свежих выгрузок (только для нужных id; регекс без разбора дерева)."""
    want = set(ids)
    out = {}
    for z in sorted(os.listdir(FEEDS)):
        if not z.endswith('.zip'):
            continue
        zf = zipfile.ZipFile(os.path.join(FEEDS, z))
        raw = zf.open(zf.namelist()[0]).read().decode('utf-8', 'ignore')
        for m in re.finditer(r'<offer\b[^>]*\bid="(\d+)"[^>]*>(.*?)</offer>', raw, re.S):
            if m.group(1) in want:
                p = re.search(r'<original_picture>(.*?)</original_picture>', m.group(2), re.S)
                if p:
                    out[m.group(1)] = p.group(1).strip()
    return out


SCHEMA = """
create table if not exists hd_backfill_log (
  sku text primary key, hd_url text, sd_url text, sd_sha text, hd_sha text, same_bytes boolean,
  applied_at timestamptz not null default now());
"""


def queue() -> list[tuple[str, int, str, str]]:
    """(sku, mid, external_id, текущий адрес фото) — сначала товары из опубликованных сетов."""
    rows = db("""
      select p.shop_mid||':'||p.external_id as sku, p.shop_mid, p.external_id,
             coalesce(c.image_url, p.image_url) as cur_url
        from products p
        left join product_photo_current c on c.sku = p.shop_mid||':'||p.external_id
       where p.in_stock and p.image_url_hd is null and p.image_url is not null
         and exists (select 1 from asset_revisions r where r.sku = p.shop_mid||':'||p.external_id)
         and not exists (select 1 from hd_backfill_log l where l.sku = p.shop_mid||':'||p.external_id)
       order by (select count(*) from set_items s where s.sku = p.shop_mid||':'||p.external_id) desc nulls last,
                p.shop_mid, p.external_id""") if _has_table('set_items') else db("""
      select p.shop_mid||':'||p.external_id, p.shop_mid, p.external_id, coalesce(c.image_url, p.image_url)
        from products p
        left join product_photo_current c on c.sku = p.shop_mid||':'||p.external_id
       where p.in_stock and p.image_url_hd is null and p.image_url is not null
         and exists (select 1 from asset_revisions r where r.sku = p.shop_mid||':'||p.external_id)
         and not exists (select 1 from hd_backfill_log l where l.sku = p.shop_mid||':'||p.external_id)
       order by p.shop_mid, p.external_id""")
    return [(r[0], int(r[1]), r[2], r[3]) for r in rows if len(r) == 4]


def _has_table(name: str) -> bool:
    return bool(db(f"select 1 from information_schema.tables where table_name={q(name)}"))


def main() -> int:
    dry = '--dry' in sys.argv
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
    db(SCHEMA)
    items = queue()
    if limit:
        items = items[:limit]
    print(f'очередь HD-бэкфилла (мешовые SKU без HD): {len(items)}' + (' — сухой прогон' if dry else ''), flush=True)
    hd = hd_from_feeds({eid: mid for _, mid, eid, _ in items})
    same = diff = skipped = 0
    for sku, mid, eid, cur_url in items:
        hd_url = norm_hd(hd.get(eid))
        if not hd_url:
            print(f'  {sku}: в фиде нет original_picture — пропуск', flush=True)
            skipped += 1
            continue
        sd_url = cur_url if cur_url.startswith('http') else 'https:' + cur_url
        try:
            sd_sha = hashlib.sha256(fetch(sd_url)).hexdigest()
            hd_sha = hashlib.sha256(fetch(hd_url)).hexdigest()
        except Exception as e:  # noqa: BLE001 — недоступное фото не валит прогон, SKU остаётся в очереди
            print(f'  {sku}: не скачалось ({type(e).__name__}: {str(e)[:60]}) — остаётся в очереди', flush=True)
            skipped += 1
            continue
        is_same = sd_sha == hd_sha
        same += is_same
        diff += (not is_same)
        print(f'  {sku}: байты {"одинаковые" if is_same else "РАЗНЫЕ"} → {"только адрес" if is_same else "HD + новый source_sha, меш → stale"}', flush=True)
        if dry:
            continue
        stmts = [f"update products set image_url_hd={q(hd_url)} where shop_mid={mid} and external_id={q(eid)};"]
        if not is_same:
            stmts.append(f"insert into product_photo_current (sku, image_url, source_sha, observed_at) values ({q(sku)},{q(hd_url)},{q(hd_sha)},now()) "
                         "on conflict (sku) do update set image_url=excluded.image_url, source_sha=excluded.source_sha, observed_at=now();")
        stmts.append(f"insert into hd_backfill_log (sku, hd_url, sd_url, sd_sha, hd_sha, same_bytes) values ({q(sku)},{q(hd_url)},{q(sd_url)},{q(sd_sha)},{q(hd_sha)},{'true' if is_same else 'false'}) "
                     "on conflict (sku) do nothing;")
        db('begin;' + ''.join(stmts) + 'commit;')
    print(f'итог: одинаковых байтов {same}, разных {diff}, пропущено {skipped}' + ('' if dry else '; применено'), flush=True)
    if not dry and diff:
        print('дальше: mesh_bind.py (ready → stale по инварианту), mesh_scheduler.py --dry (партия)', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
