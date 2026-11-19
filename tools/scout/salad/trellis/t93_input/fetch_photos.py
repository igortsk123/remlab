#!/usr/bin/env python3
"""T-93 п.1: размеры фото товара из каждого источника (7 товаров, по одному запросу на файл, пауза 1 с, без входа и без массовых выкачек).
Источники: A) feed/API `picture` (imgng, то, что берёт make_inputs сейчас), B) `original_picture` = products.image_url_hd, C) thumbnail,
D) карточка магазина (direct_url без erid): og:image и картинки галереи, найденные в HTML.
Файлы — ~/remlab-logs/t93-1119/photos/<ключ>/<источник>.<расш>; таблица — photos_table.json (+ вывод на экран)."""
import io
import json
import os
import re
import sys
import time
import urllib.request

from PIL import Image

ROOT = '/home/pakar/remlab-logs/t93-1119'
DB = json.load(open(ROOT + '/db_photos.json', encoding='utf-8'))
SEVEN = ['112923:13224664101879413845', '114667:11634594969038554503', '114082:10587794773481498560', '112923:7957884067802792858',
         '112923:1167444740116678789', '99272:10280649775260801227', '99272:607007941975253599']
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
TBL = []


def get(url, timeout=40):
    if url.startswith('//'):
        url = 'https:' + url
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'ru,en;q=0.8'})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return f.read(), f.headers.get('Content-Type', ''), f.geturl()


def save_img(sku, label, url):
    d = os.path.join(ROOT, 'photos', sku.replace(':', '_'))
    os.makedirs(d, exist_ok=True)
    row = {'sku': sku, 'src': label, 'url': url}
    try:
        data, ct, final = get(url)
        im = Image.open(io.BytesIO(data))
        ext = (im.format or 'img').lower().replace('jpeg', 'jpg')
        p = os.path.join(d, '%s.%s' % (label, ext))
        open(p, 'wb').write(data)
        row.update(ok=True, w=im.size[0], h=im.size[1], fmt=im.format, mode=im.mode, bytes=len(data), ctype=ct, path=p, final=final if final != url else None)
    except Exception as e:  # noqa: BLE001
        row.update(ok=False, err=str(e)[:160])
    TBL.append(row)
    print(sku, label, '→', ('%dx%d %s %d КБ' % (row['w'], row['h'], row['fmt'], row['bytes'] // 1024)) if row['ok'] else 'ОШИБКА ' + row['err'], flush=True)
    time.sleep(1.0)
    return row


def page_images(sku, url):
    """Карточка магазина: og:image + <img>/ссылки на картинки в HTML (без исполнения JS). Возвращает список уникальных адресов."""
    d = os.path.join(ROOT, 'photos', sku.replace(':', '_'))
    os.makedirs(d, exist_ok=True)
    try:
        data, ct, final = get(url, 60)
    except Exception as e:  # noqa: BLE001
        print(sku, 'карточка: ОШИБКА', str(e)[:120])
        return [], {'err': str(e)[:160]}
    html = data.decode('utf-8', 'replace')
    open(os.path.join(d, 'card.html'), 'w', encoding='utf-8').write(html)
    base = final
    urls = []
    for m in re.finditer(r'''(?:og:image["'][^>]*content=["']|content=["']([^"']+)["'][^>]*property=["']og:image)([^"']*)''', html):
        urls.append(m.group(1) or m.group(2))
    for m in re.finditer(r'''["'(=\s](https?:)?(//[^"'\s)<>]+?\.(?:jpe?g|png|webp)(?:\?[^"'\s)<>]*)?|/[^"'\s)<>]+?\.(?:jpe?g|png|webp))''', html, re.I):
        u = (m.group(1) or '') + m.group(2) if m.group(2).startswith('//') else m.group(2)
        urls.append(u)
    for m in re.finditer(r'https?://cdn\d*\.divan\.ru/img/v1/[^"\'\s)<>]+', html):
        urls.append(m.group(0))
    out, seen = [], set()
    for u in urls:
        if not u:
            continue
        if u.startswith('//'):
            u = 'https:' + u
        elif u.startswith('/'):
            u = urllib.request.urljoin(base, u)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out, {'final': final, 'html_bytes': len(html)}


def main():
    do_cards = '--cards' in sys.argv
    for sku in SEVEN:
        x = DB[sku]
        save_img(sku, 'A_feed_picture', x['image_url'])
        save_img(sku, 'B_original_picture', x['image_url_hd'])
        if do_cards:
            lst, meta = page_images(sku, (x.get('direct_url') or '').split('?erid')[0])
            json.dump({'sku': sku, 'meta': meta, 'images': lst}, open(os.path.join(ROOT, 'photos', sku.replace(':', '_'), 'card_images.json'), 'w'), ensure_ascii=False, indent=1)
            print(sku, 'карточка:', meta, 'картинок в HTML:', len(lst), flush=True)
            time.sleep(1.0)
    json.dump(TBL, open(ROOT + ('/photos_table_cards.json' if do_cards else '/photos_table.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


main()
