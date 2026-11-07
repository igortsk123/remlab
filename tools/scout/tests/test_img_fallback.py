"""Фото предмета не скачалось — подхват с опубликованной главной, иначе плашка «нет фото» без запроса `…/null` (T-20261106-65). Без сети.

Проверяет:
  1) `published_img` берёт только ответ 200 с типом image/*, ≥ 500 байт и открывающийся как картинка: страница ошибки,
     HTML, обрезок и 404 — не берутся; плитка ужимается до 400 px, крупная `-l.jpg` — по возможности;
  2) пустой адрес главной — подхват выключен, сети нет;
  3) страница демо: каждое `<img src=…img>`, `href:…img` и `url('…img')` предмета под проверкой «фото есть» — иначе
     пустое фото даёт `src="null"`, запрос `…/null` и 404 в консоли (дефект из пустой папки T-59/2).
    ~/venvs/scout/bin/python tools/scout/tests/test_img_fallback.py"""
import io
import os
import re
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_img_fallback')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


def jpeg(w=800, h=600):
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (w, h), (180, 120, 90)).save(b, 'JPEG', quality=80)
    return b.getvalue()


def fake(table):
    """fetch-подмена: адрес → (код, тип, тело); чего нет — 404. Запоминает запрошенные адреса."""
    seen = []

    def fetch(url):
        seen.append(url)
        return table.get(url, (404, 'text/html', b'<html>not found</html>'))
    fetch.seen = seen
    return fetch


def main():
    import flat215_demo as F
    from PIL import Image
    base = 'https://example.test/demo/'
    name = '0123456789abcdef.jpg'
    tile_url, big_url = base + 'img/' + name, base + 'img/0123456789abcdef-l.jpg'
    with tempfile.TemporaryDirectory() as d:
        def paths(tag):
            dd = os.path.join(d, tag)
            os.makedirs(dd)
            dst = os.path.join(dd, name)
            return dst, dst[:-4] + '-l.jpg'

        dst, big = paths('ok')
        f = fake({tile_url: (200, 'image/jpeg', jpeg()), big_url: (200, 'image/jpeg', jpeg(1600, 1200))})
        r = F.published_img(name, dst, big, base=base, fetch=f)
        check('200 + image/jpeg → плитка записана', r and os.path.exists(dst))
        check('плитка ужата до 400 px', r and max(Image.open(dst).size) <= 400, str(r and Image.open(dst).size))
        check('крупная -l.jpg записана, ≤ 1200 px', os.path.exists(big) and max(Image.open(big).size) <= 1200)
        check('временных файлов не осталось', not [x for x in os.listdir(os.path.dirname(dst)) if x.endswith('.tmp')])

        dst, big = paths('nobig')
        r = F.published_img(name, dst, big, base=base, fetch=fake({tile_url: (200, 'image/jpeg', jpeg())}))
        check('крупной нет (404) — плитка всё равно берётся', r and os.path.exists(dst) and not os.path.exists(big))

        for tag, resp in (('html', (200, 'text/html; charset=utf-8', b'<html>' + b'x' * 2000 + b'</html>')),
                          ('404', (404, 'image/jpeg', jpeg())),
                          ('small', (200, 'image/jpeg', b'\xff\xd8' + b'0' * 100)),
                          ('broken', (200, 'image/jpeg', b'\xff\xd8\xff\xe0' + b'garbage' * 200)),
                          ('neterr', (0, '', b'')),
                          ('tiny', (200, 'image/png', None))):
            if tag == 'tiny':
                b = io.BytesIO()
                Image.new('RGB', (8, 8)).save(b, 'PNG')
                raw = b.getvalue() + b'\0' * 600          # проходит по размеру, но 8×8 — не фото товара
                resp = (200, 'image/png', raw)
            dst, big = paths(tag)
            r = F.published_img(name, dst, big, base=base, fetch=fake({tile_url: resp}))
            check(f'{tag}: не берётся, файла нет', r is False and not os.path.exists(dst))

        dst, big = paths('off')
        f = fake({tile_url: (200, 'image/jpeg', jpeg())})
        r = F.published_img(name, dst, big, base='', fetch=f)
        check('адрес главной пустой — подхват выключен, запросов нет', r is False and not f.seen)

        dst, big = paths('have')
        Image.new('RGB', (400, 300)).save(dst, 'JPEG')
        f = fake({big_url: (200, 'image/jpeg', jpeg(1600, 1200))})
        r = F.published_img(name, dst, big, base=base, fetch=f)
        check('плитка уже есть — не перекачивается, докачивается крупная', r and tile_url not in f.seen and os.path.exists(big))

    # 2б) весь шаг фото сборки (`cache_images`): магазин не отдаёт (порт 9 закрыт) → повтор → копия главной; нет и там —
    # предмет остаётся без фото, счётчики в `_img_cached`
    import hashlib
    import types
    dead1, dead2 = 'http://127.0.0.1:9/a.jpg', 'http://127.0.0.1:9/b.jpg'
    n1 = hashlib.md5(dead1.encode()).hexdigest()[:16]
    keep = (F.OUT, F.time, F._http_get, F.IMG_FALLBACK)
    calls = []
    try:
        with tempfile.TemporaryDirectory() as d:
            F.OUT = d
            F.time = types.SimpleNamespace(sleep=lambda s: calls.append(s), time=keep[1].time)
            F.IMG_FALLBACK = base
            F._http_get = fake({base + 'img/' + n1 + '.jpg': (200, 'image/jpeg', jpeg())})
            data = {'feeds': {}, 'sets': [], 'variants': [{'id': 'setX', 'items': [
                {'role': 'диван', 'sku': {'name': 'Диван А', 'img': dead1}},
                {'role': 'торшер', 'sku': {'name': 'Торшер Б', 'img': dead2}}]}]}
            out = F.cache_images(data)
            a, b = (it['sku'] for it in out['variants'][0]['items'])
            st = out['_img_cached']
            check('сборка: не скачалось → взято с главной', a.get('img') == f'img/{n1}.jpg' and os.path.exists(os.path.join(d, 'img', n1 + '.jpg')),
                  str(a.get('img')))
            check('сборка: нет и на главной → предмет остаётся, img пустой', b.get('img') is None and len(out['variants'][0]['items']) == 2)
            check('сборка: счётчики — с главной 1, без фото 1', st.get('from_published') == 1 and st.get('variant_items_no_photo') == 1, str(st))
            check('сборка: перед подхватом — пауза и повтор', 5 in calls, str(calls))
    finally:
        F.OUT, F.time, F._http_get, F.IMG_FALLBACK = keep

    # 3) страница: фото предмета без проверки не рисуем
    page = open(os.path.join(HERE, '..', 'flat215-demo', 'index.html'), encoding='utf-8').read()
    bad = []
    pats = [r'src="\$\{(\w+)\.img\}"', r"src=\"'\+esc\((\w+)\.img\)\+'\"", r'href:(\w+)\.img\b',
            r"url\('\$\{escHtml\((\w+)\.img\)\}'\)"]
    for pat in pats:
        for m in re.finditer(pat, page):
            v = m.group(1)
            before = page[max(0, m.start() - 400):m.start()]
            if not re.search(rf'\b{v}\.img\s*\?|\b{v}\s*&&\s*{v}\.img|if\s*\(\s*{v}\.img\)', before):
                bad.append(f'стр. {page.count(chr(10), 0, m.start()) + 1}: {m.group(0)}')
    check('страница: каждое фото предмета — под проверкой «фото есть»', not bad, '; '.join(bad))
    check('страница: плашка «нет фото» в ленте замены и всплывашке плана',
          '#grid .card .noimg{' in page and '#peek .noimg{' in page and '.noimg-dot' in page)

    print(f'\n{"FAIL" if fails else "OK"}: {fails} провалов')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
