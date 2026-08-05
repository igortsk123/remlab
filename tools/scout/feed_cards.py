#!/usr/bin/env python3
"""Полная карточка товара ИЗ ФИДА: всё, что там есть, а не наш урезанный слепок.

Зачем. В сеты попадал сокращённый набор полей (дерево/металл/ткань/цвет-класс), и у половины
товаров он пустой — модель рисовала тканевый пуф кожаным, потому что про материал ей не сказали.
А в самом фиде у этого пуфа есть `<param name="Материал">Ткань</param>` и `Цвет: Бежевый`
(владелец, 2026-08-05: «зайди в сам фид, всё по максимуму выгружай»).

Что берём с каждого оффера:
  * `<name>`, `<vendor>`, `<model>`, `article` — как товар называется и кто его делает;
  * `<description>` — подробное описание (есть у 30% офферов);
  * ВСЕ `<param>` — Материал, Цвет, Тип товара, Коллекция/серия, Особенности, Материал корпуса…;
  * `<original_picture>` — фото магазина в исходном размере (1080 px против 450 у витринного).

Пишет `feed-cards.json`: ключ `mid-eid` → карточка. Читается `viz_objects.product`.

  ~/venvs/scout/bin/python feed_cards.py            # по товарам из sets3.json
  ~/venvs/scout/bin/python feed_cards.py --all      # по всем офферам фидов
"""
import glob
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FEEDS = os.path.join(HERE, 'feeds2')
DST = os.path.join(HERE, 'feed-cards.json')

TAG = {
    'name': re.compile(r'<name><!\[CDATA\[(.*?)\]\]></name>', re.S),
    'vendor': re.compile(r'<vendor><!\[CDATA\[(.*?)\]\]></vendor>', re.S),
    'model': re.compile(r'<model><!\[CDATA\[(.*?)\]\]></model>', re.S),
    'description': re.compile(r'<description><!\[CDATA\[(.*?)\]\]></description>', re.S),
    'original_picture': re.compile(r'<original_picture>(.*?)</original_picture>', re.S),
    'picture': re.compile(r'<picture>(.*?)</picture>', re.S),
}
RE_OFFER = re.compile(r'<offer\b[^>]*>.*?</offer>', re.S)
RE_ID = re.compile(r'<offer\b[^>]*\bid="([^"]+)"')
RE_MID = re.compile(r'merchant_id="(\d+)"')
RE_ART = re.compile(r'article="([^"]*)"')
RE_PARAM = re.compile(r'<param name="([^"]+)"><!\[CDATA\[(.*?)\]\]></param>', re.S)


def clean(text: str) -> str:
    """Описание из фида приходит с html-разметкой — оставляем читаемый текст."""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def card(offer: str) -> dict:
    out = {}
    for key, rx in TAG.items():
        m = rx.search(offer)
        if m and m.group(1).strip():
            out[key] = clean(m.group(1)) if key == 'description' else m.group(1).strip()
    art = RE_ART.search(offer)
    if art and art.group(1):
        out['article'] = art.group(1)
    params = {k: clean(v) for k, v in RE_PARAM.findall(offer) if v.strip()}
    if params:
        out['params'] = params
    return out


def main() -> None:
    want = None
    if '--all' not in sys.argv:
        sets = json.load(open(os.path.join(HERE, 'sets3.json')))
        want = {f"{it['mid']}-{it['eid']}" for s in sets for it in s['items'].values()}
        print(f'товаров в сетах: {len(want)}')
    cards, seen = {}, 0
    for z in sorted(glob.glob(os.path.join(FEEDS, '*.xml.zip'))):
        with zipfile.ZipFile(z) as zf:
            data = zf.open(zf.namelist()[0]).read().decode('utf-8', 'ignore')
        for m in RE_OFFER.finditer(data):
            offer = m.group(0)
            seen += 1
            oid = RE_ID.search(offer)
            mid = RE_MID.search(offer)
            if not oid or not mid:
                continue
            key = f'{mid.group(1)}-{oid.group(1)}'
            if want is not None and key not in want:
                continue
            cards[key] = card(offer)
    json.dump(cards, open(DST, 'w'), ensure_ascii=False, indent=1)
    with_mat = sum(1 for c in cards.values() if (c.get('params') or {}).get('Материал'))
    with_col = sum(1 for c in cards.values() if (c.get('params') or {}).get('Цвет'))
    with_desc = sum(1 for c in cards.values() if c.get('description'))
    with_orig = sum(1 for c in cards.values() if c.get('original_picture'))
    print(f'офферов просмотрено: {seen}; карточек собрано: {len(cards)}')
    print(f'  материал: {with_mat}  цвет: {with_col}  описание: {with_desc}  '
          f'оригинальное фото: {with_orig}')
    print(DST)


if __name__ == '__main__':
    main()
