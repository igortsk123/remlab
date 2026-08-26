#!/usr/bin/env python3
"""ГДЕСЛОН API — доступность партнёрок и запасной источник товаров.

Зачем (26.08): ссылка на выгрузку nonton (mid 116933, 11 595 товаров) отдавала 404 с 11 августа,
и мы две недели показывали товары магазина, которого у нас больше нет. Ссылки выгрузок в кабинете
статичные, списка выгрузок в API нет — но есть СПИСОК РЕКЛАМОДАТЕЛЕЙ (`/api/users/shops.xml`),
и он и есть источник правды: магазина нет в списке → программа недоступна → его товары нельзя
ни продать, ни монетизировать, и в банке им не место.

  gdeslon_api.py --check            # какие магазины каталога больше не доступны (только отчёт)
  gdeslon_api.py --retire           # снять с продажи товары недоступных магазинов
  gdeslon_api.py --search 112923 диван 20   # запасной источник: товары магазина через XML-поиск

Ключ — `GDESLON_API_TOKEN` в `.env.local` (значение в памяти не хранится).
"""
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SHOPS_URL = 'https://www.gdeslon.ru/api/users/shops.xml?api_token={tok}'
# ВАЖНО: www.gdeslon.ru отвечает 301 на api.gdeslon.ru — без follow параметры `m`/`_gs_at`
# теряются, и поиск молча отдаёт «всё подряд». Поэтому ходим сразу на api-хост.
SEARCH_URL = ('https://api.gdeslon.ru/api/search.xml?q={q}&m={mid}&l={l}&p={p}&_gs_at={tok}')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-tAc']


def token() -> str:
    t = os.environ.get('GDESLON_API_TOKEN')
    if t:
        return t.strip()
    for p in (os.path.join(HERE, '..', '..', '.env.local'), os.path.join(HERE, '..', '..', '.env')):
        try:
            for line in open(p, encoding='utf-8'):
                if line.startswith('GDESLON_API_TOKEN'):
                    return line.split('=', 1)[1].strip().strip('"\'')
        except Exception:
            continue
    raise SystemExit('нет GDESLON_API_TOKEN (.env.local)')


def _get(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'remlab/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return f.read().decode('utf-8', 'replace')


def shops() -> dict:
    """mid → название магазина, доступного нашему аккаунту сейчас."""
    x = _get(SHOPS_URL.format(tok=token()))
    out = {}
    for b in re.findall(r'<shop>(.*?)</shop>', x, re.S):
        i = re.search(r'<id><!\[CDATA\[(\d+)\]\]></id>', b)
        n = re.search(r'<name><!\[CDATA\[(.*?)\]\]></name>', b, re.S)
        if i:
            out[int(i.group(1))] = (n.group(1).strip() if n else '')
    return out


def _sql(q: str) -> str:
    return subprocess.run(PSQL + [q], capture_output=True, text=True).stdout.strip()


def check() -> list:
    live = shops()
    rows = _sql("select shop_mid||'~'||shop||'~'||cnt from (select shop_mid, shop, count(*) cnt "
                "from products where in_stock group by 1,2 order by 3 desc) t").splitlines()
    gone = []
    for r in rows:
        p = r.split('~')
        if len(p) < 3:
            continue
        mid, shop, cnt = int(p[0]), p[1], int(p[2])
        mark = 'доступен' if mid in live else 'НЕДОСТУПЕН — программы нет в кабинете'
        print(f'  mid {mid:7d}  {shop:20s} товаров {cnt:6d}  {mark}')
        if mid not in live:
            gone.append((mid, shop, cnt))
    print(f'магазинов у Гдеслона сейчас: {len(live)}; недоступных у нас: {len(gone)}')
    return gone


def retire() -> None:
    gone = check()
    if not gone:
        print('снимать нечего')
        return
    for mid, shop, cnt in gone:
        _sql(f"update products set in_stock=false, status='archived' where shop_mid={mid}")
        print(f'снято с продажи: {shop} (mid {mid}) — {cnt} товаров')
    print('дальше замену сделает контракт слота: sets_incremental.py --enforce-contracts --apply')


def search(mid: int, q: str, limit: int = 100, page: int = 1) -> list:
    """Запасной источник, когда выгрузка магазина умерла: те же офферы через XML-поиск."""
    x = _get(SEARCH_URL.format(q=urllib.parse.quote(q), mid=mid, l=min(limit, 100), p=page,
                               tok=token()))
    offers = re.findall(r'<offer\b(.*?)</offer>', x, re.S)
    return offers


if __name__ == '__main__':
    import urllib.parse
    if '--retire' in sys.argv:
        retire()
    elif '--search' in sys.argv:
        i = sys.argv.index('--search')
        print(len(search(int(sys.argv[i + 1]), sys.argv[i + 2],
                         int(sys.argv[i + 3]) if len(sys.argv) > i + 3 else 20)), 'офферов')
    else:
        check()
