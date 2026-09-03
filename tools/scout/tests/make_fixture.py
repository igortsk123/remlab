#!/usr/bin/env python3
"""Собирает фикстуру фида для селфтестов загрузки (план catalog-load-hardening, П0.3).

Берёт из ЖИВЫХ выгрузок `feeds2/*.xml.zip` по одному-два оффера на каждый тест-кейс и складывает их в один
YML-файл `fixtures/feed-mini.xml.zip` (заголовок магазина, дерево категорий только нужных веток, офферы).
Рядом пишет `feed-mini.manifest.json` (какой оффер зачем взят) и срезы `category-roles-mini.json` /
`unit-priors-mini.json` из живых карт — чтобы селфтесты в CI не зависели от данных вне git.

Зачем генератор, а не ручной файл: фикстуру можно пересобрать после смены формата фида одной командой
и увидеть в diff, что именно поменял Гдеслон.

  ~/venvs/scout/bin/python tools/scout/tests/make_fixture.py        # пересобрать
"""
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
FEEDS = os.path.join(SCOUT, 'feeds2')
OUT = os.path.join(HERE, 'fixtures')

# магазин → хеш выгрузки (постоянные ссылки кабинета Гдеслона, см. refresh_daily.sh)
FEED = {
    112923: '1b9f77d20e11b89864c73ac9551ff57be0bff818',   # divan.ru
    99272: 'a5bb9dc9178031fc6c3b165c3df9c20bfcc55e18',    # tvoydom.ru
    114667: 'a5906abd53d7d2efaff63c5021bd1cd4fb337a45',   # mnogomebeli.com
    114082: 'f7633bdd943d41c718c12dc88e7a61f2b88b55c6',   # divanboss.ru
    96431: 'ec02cfec770831e51450542cf9e6fc0ee53657e4',    # mdm-complect.ru
    112098: 'c0021e3fe460caf057f3d7823043b14adf6acb0c',   # gipfel.ru
}

OFFER_RE = re.compile(r'<offer\b[^>]*>.*?</offer>', re.S)


def load(mid):
    z = zipfile.ZipFile(os.path.join(FEEDS, FEED[mid] + '.xml.zip'))
    raw = z.open(z.namelist()[0]).read().decode('utf-8', 'ignore')
    cats = re.findall(r'<category\s+id="(\d+)"(?:\s+parent_id="(\d+)")?\s*>(.*?)</category>', raw, re.S)
    return raw, {c[0]: c for c in cats}, OFFER_RE.findall(raw)


def field(o, tag):
    m = re.search(rf'<{tag}>(.*?)</{tag}>', o, re.S)
    return m.group(1).strip() if m else ''


def text(s):
    return re.sub(r'<!\[CDATA\[|\]\]>', '', s).strip()


def params(o):
    return {k: text(v) for k, v in re.findall(r'<param name="([^"]+)">(.*?)</param>', o, re.S)}


def attr(o, name):
    m = re.search(rf'\b{name}="([^"]*)"', o)
    return m.group(1) if m else ''


# (магазин, метка кейса, предикат, сколько взять)
CASES = [
    (112923, 'divan: original_picture+article+описание, роль по категории',
     lambda o, p: field(o, 'categoryId') == '176' and text(field(o, 'description')), 2),
    (112923, 'divan: «Распродажа» (cid 334) — кресло, роль по названию',
     lambda o, p: field(o, 'categoryId') == '334' and text(field(o, 'name')).startswith('Кресло'), 1),
    (112923, 'divan: «Распродажа» (cid 334) — не гостиная, DENY по названию',
     lambda o, p: field(o, 'categoryId') == '334' and re.search(r'^(Матрас|Подушка|Наматрасник|Чехол)', text(field(o, 'name'))), 1),
    (99272, 'tvoydom: стул с «Длина/Ширина/Высота» (Длина = глубина) и «ШхГхВ см» в названии',
     lambda o, p: 'Длина' in p and 'Ширина' in p and 'Высота' in p and re.search(r'\d{2,3}х\d{2,3}х\d{2,3}\s*см', text(field(o, 'name'))) and text(field(o, 'name')).startswith('Стул'), 1),
    (99272, 'tvoydom: шторы с «Размер штор» и без размеров в параметрах',
     lambda o, p: 'Размер штор' in p and 'Ширина' not in p, 1),
    (99272, 'tvoydom: светильник с «Габариты (Д*Ш*В)»',
     lambda o, p: 'Габариты (Д*Ш*В)' in p and re.search(r'х', p['Габариты (Д*Ш*В)']) and re.match(r'(Люстра|Бра)', text(field(o, 'name'))), 1),
    (99272, 'tvoydom: пустое описание + размеры только в названии «57х60х85 см»',
     lambda o, p: not text(field(o, 'description')) and re.match(r'Кресло .*\d{2}х\d{2}х\d{2} см', text(field(o, 'name'))), 1),
    (99272, 'tvoydom: светильник с «Глубина» (обычный путь осей, не мебель — Длина→d не применяется)',
     lambda o, p: 'Глубина' in p and 'Ширина' in p and re.match(r'(Спот|Светильник)', text(field(o, 'name'))), 1),
    (114667, 'mnogomebeli: диван без глубины, с «Изображение с размерами»',
     lambda o, p: 'Изображение с размерами' in p and 'Глубина' not in p and text(field(o, 'name')).startswith('Угловой диван'), 1),
    (114082, 'divanboss: original_picture с «:443» (НЕ нормализовать)',
     lambda o, p: ':443' in field(o, 'original_picture'), 1),
    (96431, 'mdm: «Пантографы» (cid 1476) — фурнитура, override → без роли',
     lambda o, p: field(o, 'categoryId') == '1476', 1),
    (96431, 'mdm: «Гардеробная система HOME SPACE» (cid 1482)',
     lambda o, p: field(o, 'categoryId') == '1482', 1),
    (112098, 'gipfel: декор в мм (приор единиц)',
     lambda o, p: 'Высота' in p and re.search(r'^\d{3,4}$', p.get('Высота', '')) and re.search(r'^(Ваза|Кашпо|Статуэтка)', text(field(o, 'name'))), 1),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    picked, manifest, cat_need = [], [], {}
    cache = {}
    for mid, label, pred, n in CASES:
        if mid not in cache:
            cache[mid] = load(mid)
        raw, cats, offers = cache[mid]
        got = 0
        for o in offers:
            if got >= n:
                break
            if o in picked:
                continue
            try:
                ok = pred(o, params(o))
            except Exception:  # noqa: BLE001 — предикат на сыром XML, пропускаем странный оффер
                ok = False
            if ok:
                picked.append(o); got += 1
                cid = field(o, 'categoryId')
                manifest.append({'mid': mid, 'id': attr(o, 'id'), 'article': attr(o, 'article'),
                                 'cid': cid, 'name': text(field(o, 'name'))[:80], 'case': label})
                # дерево категорий: сама категория и все родители
                c = cid
                while c in cats:
                    cat_need[(mid, c)] = cats[c]; c = cats[c][1]
        if got < n:
            print(f'НЕ НАЙДЕНО: {label} (взято {got} из {n})', file=sys.stderr)
    # синтетический кейс: два оффера с одной картинкой (в живых фидах дублей нет — делаем копию с другим id)
    src = next(o for o in picked if attr(o, 'merchant_id') == '112923')
    clone = re.sub(r'\bid="(\d+)"', lambda m: f'id="{m.group(1)[:-1]}9"', src, count=1)
    clone = re.sub(r'<name>.*?</name>', '<name><![CDATA[' + text(field(src, 'name')) + ' (вариант цвета)]]></name>', clone, count=1, flags=re.S)
    picked.append(clone)
    manifest.append({'mid': 112923, 'id': attr(clone, 'id'), 'article': attr(clone, 'article'), 'cid': field(clone, 'categoryId'),
                     'name': text(field(clone, 'name'))[:80], 'case': 'СИНТЕТИКА: второй оффер с той же картинкой (вариант)'})

    cats_xml = ''.join(
        f'<category id="{c[0]}"' + (f' parent_id="{c[1]}"' if c[1] else '') + f'>{c[2]}</category>'
        for (mid, cid), c in sorted(cat_need.items()))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<yml_catalog date="2026-09-03 12:35"><shop><name>GdeSlon.ru</name>'
           '<url>https://www.gdeslon.ru</url><currencies><currency id="RUR" rate="1"/></currencies>'
           f'<categories>{cats_xml}</categories><offers>' + ''.join(picked) + '</offers></shop></yml_catalog>')
    with zipfile.ZipFile(os.path.join(OUT, 'feed-mini.xml.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('feed-mini.xml', xml)
    json.dump(manifest, open(os.path.join(OUT, 'feed-mini.manifest.json'), 'w'), ensure_ascii=False, indent=1)

    # срезы карт: роли категорий и приоры единиц только для попавших магазинов/категорий
    roles = json.load(open(os.path.join(SCOUT, 'category-roles.json')))
    mini_roles = {k: v for k, v in roles.items() if any(k == f'{mid}:{cid}' for (mid, cid) in cat_need)}
    json.dump(mini_roles, open(os.path.join(OUT, 'category-roles-mini.json'), 'w'), ensure_ascii=False, indent=1)
    pri_path = os.path.join(SCOUT, 'unit-priors.json')
    if os.path.exists(pri_path):
        pri = json.load(open(pri_path))
        mids = {str(m['mid']) for m in manifest}
        mini_pri = {k: v for k, v in pri.items() if k.split(':')[0] in mids}
        json.dump(mini_pri, open(os.path.join(OUT, 'unit-priors-mini.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'офферов: {len(picked)}, категорий: {len(cat_need)}, ролей: {len(mini_roles)} → {OUT}')
    for m in manifest:
        print(f"  {m['mid']} {m['id']} cid={m['cid']:>5} | {m['case'][:60]} | {m['name'][:50]}")


if __name__ == '__main__':
    main()
