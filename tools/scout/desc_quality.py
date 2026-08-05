#!/usr/bin/env python3
"""Годность описания как источника: не всякий текст в поле description что-то говорит о товаре.

Замер по пулу гостиной (2026-08-05): описание есть у 7 813 товаров из 26 147, но уникальных
текстов среди них 3 551. Один и тот же абзац стоит у 969 диванов («Идеальное сочетание красоты,
комфорта и надёжности в вашем доме!»), у 352 шкафов — инструкция по креплению к стене.

Такой текст не источник признаков, а шум: он занимает место в промпте, стоит денег и создаёт
ложное ощущение, что карточка информативна. Классифицируем описание ДО обращения к модели:

  useful      — уникальный содержательный текст, отдаём модели;
  duplicate   — тот же текст у многих товаров (маркетинговый шаблон магазина);
  boilerplate — про доставку, сборку, гарантию, крепёж: не про сам предмет;
  short       — короче 60 символов, признаков не несёт;
  none        — описания нет.

  ~/venvs/scout/bin/python desc_quality.py            # замер по каталогу
  ~/venvs/scout/bin/python desc_quality.py --show 8   # примеры каждого класса
"""
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

DUP_LIMIT = 3        # один текст более чем у трёх товаров — шаблон магазина, не описание
MIN_LEN = 60

BOILER = re.compile(
    r'рекомендуется закрепить|крепеж в комплект|крепёж в комплект|сборка не универсальн|'
    r'доставка|самовывоз|гаранти\w+ \d|в комплект не входит|уточняйте у менеджер|'
    r'цвет на фото может|возможны незначительные отличия|товар сертифицирован|'
    r'идеальное сочетание|отличное решение для|подарит вам|создаст уют|станет украшением',
    re.I)

_DUPS: set[str] | None = None


def _h(text: str) -> str:
    return hashlib.sha1(re.sub(r'\s+', ' ', (text or '').strip().lower()).encode()).hexdigest()[:16]


def load_dups() -> set[str]:
    """Хеши текстов, встречающихся у нескольких товаров. Считается по ВСЕМУ каталогу."""
    global _DUPS
    if _DUPS is not None:
        return _DUPS
    r = subprocess.run(PSQL, capture_output=True, text=True, input=f"""
        select md5(regexp_replace(lower(trim(description)),'\\s+',' ','g')), count(*)
          from products where description is not null and description<>''
         group by 1 having count(*) > {DUP_LIMIT}
    """)
    # md5 из БД и sha1 из питона несравнимы — берём тексты и хешируем одинаково
    r2 = subprocess.run(PSQL, capture_output=True, text=True, input=f"""
        select left(regexp_replace(lower(trim(description)),'\\s+',' ','g'), 400)
          from products where description is not null and description<>''
         group by regexp_replace(lower(trim(description)),'\\s+',' ','g')
        having count(*) > {DUP_LIMIT}
    """)
    _DUPS = {_h(l) for l in r2.stdout.split('\n') if l.strip()}
    return _DUPS


def classify(desc: str | None) -> str:
    if not desc or not desc.strip():
        return 'none'
    text = re.sub(r'\s+', ' ', desc.strip())
    if len(text) < MIN_LEN:
        return 'short'
    if BOILER.search(text):
        return 'boilerplate'
    if _h(text[:400]) in load_dups():
        return 'duplicate'
    return 'useful'


def trusted(desc: str | None) -> bool:
    """Отдавать ли этот текст модели."""
    return classify(desc) == 'useful'


def main() -> None:
    r = subprocess.run(PSQL, capture_output=True, text=True, input="""
        select coalesce(p.description,''), l.role
          from lr_roles l join products p using (shop_mid, external_id)
         where l.role is not null
    """)
    rows = [l.split('\x1f') for l in r.stdout.split('\n') if l]
    counts: dict[str, int] = {}
    samples: dict[str, list] = {}
    for desc, role in rows:
        c = classify(desc)
        counts[c] = counts.get(c, 0) + 1
        samples.setdefault(c, []).append((role, desc[:110]))
    total = sum(counts.values())
    print(f'пул гостиной: {total} товаров\n')
    for c in ('useful', 'duplicate', 'boilerplate', 'short', 'none'):
        n = counts.get(c, 0)
        print(f'  {c:12s} {n:>6}  {n / total * 100:5.1f}%')
    print(f'\nописание можно использовать как источник: {counts.get("useful", 0)} '
          f'({counts.get("useful", 0) / total * 100:.1f}%)')
    if '--show' in sys.argv:
        k = int(sys.argv[sys.argv.index('--show') + 1])
        for c in ('duplicate', 'boilerplate', 'short', 'useful'):
            print(f'\n--- {c} ---')
            for role, d in samples.get(c, [])[:k]:
                print(f'  [{role}] {d}')


if __name__ == '__main__':
    main()
