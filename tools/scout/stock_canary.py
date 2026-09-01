#!/usr/bin/env python3
"""КАНАРЕЙКА ПОСЛЕ СМЕНЫ СХЕМЫ ССЫЛОК (01.09.2026, требование Codex перед массовым применением).

Два одинаковых 404 доказывают, что ОТВЕТ стабилен, но не что мы стучимся ПО ПРАВИЛЬНОМУ адресу.
Испорченное преобразование ссылки даёт стабильный 404 на весь каталог — и автоматика снимет
живые товары, дважды «подтвердив» собственную ошибку. Поэтому сверяем не ответ, а АДРЕС:

  1) хост ссылки совпадает с магазином товара;
  2) в пути есть след названия товара — значит это карточка ЭТОГО товара, а не соседнего;
  3) доля отрицательных не выглядит как «умерло всё» (это поломка, а не ассортимент).

Работает по СЫРЫМ наблюдениям прогона (`product_page_observation`), а не по применённым
статусам: наблюдения появляются сразу после обхода, до подтверждающего прохода, — то есть
проверить схему можно ДО того, как снятие дойдёт до наличия. Сети не трогает.

  stock_canary.py --shop mnogomebeli.com [--run <run_id>] [--sample 20]
"""
import os
import re
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
ALARM_NEGATIVE_SHARE = 0.60      # тот же аварийный порог, что у гейта (stock_truth.GATE_SHARE_FIRST_RUN)
SLUG_MISS_LIMIT = 0.30           # доля выборки, где след названия не найден, — выше уже подозрительно
# в слаге магазины пишут латиницей; сверяем по транслиту значимых слов названия
TRANSLIT = {'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh',
            'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
            'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
            'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
            'я': 'ya'}


def translit(s: str) -> str:
    return ''.join(TRANSLIT.get(c, c) for c in (s or '').lower())


def db(sql: str) -> list:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip('\n').split('\n') if ln]


def q(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def slug_hit(name: str, url: str):
    """Есть ли в адресе след названия товара → True / False / None («по слагу не судить»).

    Достаточно ДВУХ значимых слов: магазины переставляют и сокращают слова, но не выдумывают
    их с нуля. НО адрес бывает и по числовому ID (`tvoydom.ru/catalog/1002738503/`,
    `gipfel.ru/catalog/43161/`, mdm) — там слага нет вовсе, и «не совпало» означало бы
    «непонятно», а не «чужая ссылка». Такие адреса честно отдаём как None: проверка слагом
    к ним неприменима (иначе канарейка кричит на 100% каталога трёх магазинов — поймано 01.09).
    """
    path_raw = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    segs = [s for s in path_raw.split('/') if s]
    if segs and re.fullmatch(r'\d{3,}', segs[-1]):
        return None
    path = translit(path_raw).replace('-', ' ')
    words = [translit(w) for w in re.findall(r'[а-яёa-z0-9]{4,}', (name or '').lower())]
    return sum(1 for w in words if w[:5] in path) >= 2


def main() -> int:
    shop = sys.argv[sys.argv.index('--shop') + 1] if '--shop' in sys.argv else ''
    n = int(sys.argv[sys.argv.index('--sample') + 1]) if '--sample' in sys.argv else 20
    run = sys.argv[sys.argv.index('--run') + 1] if '--run' in sys.argv else ''
    if not run:
        r = db(f"""select o.run_id from product_page_observation o join products p
                     on p.shop_mid = o.shop_mid and p.external_id = o.external_id
                    where p.shop = {q(shop)} and o.probe_kind = 'explore'
                    order by o.observed_at desc limit 1;""")
        if not r:
            print(f'наблюдений по магазину {shop} нет — проверять нечего')
            return 1
        run = r[0][0]
    rows = db(f"""
    select o.verdict, p.name, o.url, p.shop, coalesce(o.reason, '')
      from product_page_observation o join products p
        on p.shop_mid = o.shop_mid and p.external_id = o.external_id
     where o.run_id = {q(run)} and p.shop = {q(shop)};""")
    if not rows:
        print(f'в прогоне {run} нет наблюдений магазина {shop}')
        return 1
    per = {}
    for v, *_ in rows:
        per[v] = per.get(v, 0) + 1
    total = len(rows)
    neg = per.get('gone', 0) + per.get('oos', 0)
    print(f'прогон {run} · {shop}: наблюдений {total} — '
          + ', '.join(f'{k} {v}' for k, v in sorted(per.items())))
    print(f'доля отрицательных: {neg / total:.0%} (аварийный порог {ALARM_NEGATIVE_SHARE:.0%})')
    bad = 0
    for verdict in ('gone', 'oos', 'alive'):
        sample = [r for r in rows if r[0] == verdict][:n]
        if not sample:
            continue
        checked = [r for r in sample if slug_hit(r[1], r[2]) is not None]
        by_id = len(sample) - len(checked)
        miss = [r for r in checked if slug_hit(r[1], r[2]) is False]
        host_bad = [r for r in sample
                    if (urllib.parse.urlsplit(r[2]).hostname or '').replace('www.', '') != r[3]]
        print(f'  {verdict}: выборка {len(sample)} (адрес по ID, слагом не судим: {by_id}), '
              f'не похож на карточку товара {len(miss)}, чужой хост {len(host_bad)}')
        for r in miss[:3]:
            print(f'     ? {r[1][:50]} → {r[2][:95]}')
        if (checked and len(miss) > len(checked) * SLUG_MISS_LIMIT) or host_bad:
            bad += 1
    if neg / total > ALARM_NEGATIVE_SHARE:
        print('ТРЕВОГА: отрицательных больше порога — это похоже на поломку схемы ссылок, '
              'а не на ассортимент магазина')
        bad += 1
    print('канарейка: ' + ('ЧИСТО — применение вердиктов обосновано'
                           if not bad else 'ЕСТЬ ЗАМЕЧАНИЯ — разобрать ДО применения'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
