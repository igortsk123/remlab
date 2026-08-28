"""Оригинал фото товара со страницы магазина: в фиде Гдеслона всегда 450 px по ширине,
а у магазина лежит 1200-1920. Для тонких деталей (проволока, ножки) это решающая разница.

Совпадение проверяем по картинке, а не по вёрстке: берём кандидатов со страницы, оставляем
те, что похожи на фидовое фото (сравнение уменьшенных до 64x64 в оттенках серого) — иначе
в набор попадают баннеры и «похожие товары».
"""
import io
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
SCOUT = '/home/pakar/igor/remlab/tools/scout'
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}


def get(u, t=30):
    if u.startswith('//'):
        u = 'https:' + u
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read()


def sig(img):
    """Подпись картинки: 64x64 в сером, с вычтенным средним — устойчиво к масштабу и качеству."""
    a = np.asarray(img.convert('L').resize((64, 64), Image.LANCZOS), dtype=np.float32)
    return a - a.mean()


def similar(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float((a * b).sum() / (na * nb)) if na and nb else 0.0


def best_big(item, ref_sig, min_side=700):
    html = get(item['url'], 40).decode('utf-8', 'ignore')
    cands = {u for u in re.findall(r'https?://[^"\'\\ <>)]+?\.(?:jpg|jpeg|webp|png)', html)}
    # divan.ru шифрует исходник в base64-хвосте пути; повышаем запрошенный размер прямо в URL
    grown = set()
    for u in cands:
        if 'cdn0.divan.ru/img/' in u:
            grown.add(re.sub(r'rs:fit:\d+:\d+', 'rs:fit:2000:2000', u))
    cands |= grown
    best = None
    for u in sorted(cands, key=len, reverse=True)[:40]:
        try:
            im = Image.open(io.BytesIO(get(u, 25))).convert('RGB')
        except Exception:                      # noqa: BLE001 — битые/чужие ссылки на странице
            continue
        if min(im.size) < min_side:
            continue
        if similar(sig(im), ref_sig) < 0.45:   # не тот товар / баннер / интерьерный кадр
            continue
        if not best or im.size[0] * im.size[1] > best.size[0] * best.size[1]:
            best = im
    return best


def main():
    items = json.load(open(os.path.join(ROOT, 'set.json')))
    idx = json.load(open(os.path.join(SCOUT, 'candidates-index.json')))['items']
    url_by_eid = {v['eid']: v['url'] for v in idx.values()}
    os.makedirs(os.path.join(ROOT, 'src_big'), exist_ok=True)
    stat = {'ok': 0, 'small': 0, 'fail': 0}
    errs = []

    def work(it):
        dst = os.path.join(ROOT, 'src_big', it['id'] + '.jpg')
        if os.path.exists(dst):
            return 'ok', None
        eid = next((e for e in url_by_eid if e.startswith(it['id'].split('-')[-1])), None)
        if not eid:
            return 'fail', f'{it["id"]}: не нашёл eid'
        ref = sig(Image.open(os.path.join(ROOT, 'src', it['id'] + '.jpg')))
        try:
            big = best_big({'url': url_by_eid[eid]}, ref)
        except Exception as e:                 # noqa: BLE001 — считаем, не глотаем
            return 'fail', f'{it["id"]}: {type(e).__name__}: {str(e)[:90]}'
        if big is None:
            return 'small', None
        big.save(dst, quality=95)
        return 'ok', None

    with ThreadPoolExecutor(max_workers=6) as ex:
        for st, err in ex.map(work, items):
            stat[st] += 1
            if err:
                errs.append(err)
    print(f'оригиналы: ok={stat["ok"]} нет крупного={stat["small"]} ошибок={stat["fail"]}')
    for e in errs[:10]:
        print('   ✗', e)
    for f in sorted(os.listdir(os.path.join(ROOT, 'src_big'))):
        s = Image.open(os.path.join(ROOT, 'src_big', f)).size
        print(f'   {f[:34]:36} {s[0]}x{s[1]}')


if __name__ == '__main__':
    main()
