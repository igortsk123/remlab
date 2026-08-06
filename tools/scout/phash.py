#!/usr/bin/env python3
"""Отпечаток самой картинки: изменилось ли фото товара на самом деле.

Магазин регулярно меняет URL картинки, не меняя саму картинку (перезалил на новый CDN, добавил
параметр). Сравнение ссылок это не ловит — и мы платим за повторный анализ того же изображения.
Поэтому у товара есть перцептивный хеш: он считается по пикселям, устойчив к пережатию и ресайзу.

Важное ограничение (техническая ревизия, 2026-08-05): один перцептивный хеш НЕ доказывает, что
это тот же товар. Один и тот же диван в бежевом и сером даёт близкие хеши — форма и раскладка
кадра совпадают. Поэтому хеш здесь — ТРИГГЕР, а подтверждение — визуальный эмбеддинг (CLIP,
локально, бесплатно), который различает цвет и фактуру.

  ~/venvs/scout/bin/python phash.py --from-cache        # проставить хеши по кэшу миниатюр
  ~/venvs/scout/bin/python phash.py --check 116933 3036041517751486277 <url>
"""
import io
import os
import re
import subprocess
import sys
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
THUMBS = os.path.join(HERE, 'thumbs')
REFS = os.path.join(HERE, 'refs')
IMGCACHE = os.path.join(HERE, 'imgcache')   # главный кэш обогащения, ключ файла = image_url
EMB_PATH = os.path.join(HERE, 'embeddings.npz')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

HAM_SAME = 6        # ≤ этого расстояния картинку считаем той же (обычная практика для 64 бит)
HAM_CLOSE = 14      # между SAME и CLOSE — спорно: решают эмбеддинг И цвет
COS_SAME = 0.985    # косинус выше — та же вещь; 0.93 склеивал ткани одной модели (см. ниже)
RGB_SAME = 14.0     # среднее отличие цвета по сетке 8×8, 0–255

# Порог косинуса поднят по результату проверки 2026-08-05: «Диван Босс Лофт Рогожка Мальмо серый»
# и тот же диван в велюре давали 0.983 — CLIP на 224 px не различает фактуру ткани, и старый порог
# 0.93 объявлял их одной картинкой. Ошибка «то же» дорогая: за товаром остаётся чужое обогащение.
# Ошибка «изменилось» стоит один дешёвый пересчёт. Поэтому при сомнении отвечаем «изменилось».


def _prep(im: Image.Image, side: int) -> np.ndarray:
    return np.asarray(im.convert('L').resize((side, side), Image.LANCZOS), dtype=np.float32)


def dhash(im: Image.Image) -> int:
    """Горизонтальный градиент 8×9 — устойчив к яркости и лёгкому кропу."""
    a = np.asarray(im.convert('L').resize((9, 8), Image.LANCZOS), dtype=np.float32)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int(''.join('1' if b else '0' for b in bits), 2)


def phash(im: Image.Image) -> int:
    """Классический DCT-хеш: низкие частоты 8×8, порог — медиана."""
    a = _prep(im, 32)
    # DCT-II через матрицу косинусов: заводить scipy ради одного преобразования незачем
    n = 32
    k = np.arange(n)
    c = np.cos(np.pi * (2 * k[:, None] + 1) * k[None, :] / (2 * n))
    c[:, 0] *= 1 / np.sqrt(2)
    d = c.T @ a @ c
    low = d[:8, :8]
    med = np.median(low[1:, 1:])          # без DC-компоненты, она тянет медиану
    bits = (low > med).flatten()
    return int(''.join('1' if b else '0' for b in bits), 2)


def fingerprint(data: bytes) -> str:
    """Отпечаток картинки: dHash и pHash вместе, 32 hex-символа."""
    im = Image.open(io.BytesIO(data))
    return f'{dhash(im):016x}{phash(im):016x}'


def fingerprint_file(path: str) -> str | None:
    try:
        with open(path, 'rb') as f:
            return fingerprint(f.read())
    except Exception:  # noqa: BLE001 — битый файл в кэше не должен ронять прогон
        return None


def hamming(a: str, b: str) -> int:
    """Расстояние по обоим хешам сразу (0–128)."""
    if not a or not b or len(a) != len(b):
        return 999
    return bin(int(a, 16) ^ int(b, 16)).count('1')


def _embed(paths: list[str]) -> list[np.ndarray]:
    from fastembed import ImageEmbedding
    # кэш моделей — на диск: /tmp здесь tmpfs и модель в него не влезает
    m = ImageEmbedding('Qdrant/clip-ViT-B-32-vision', cache_dir=os.path.expanduser('~/.cache/fastembed'))
    out = []
    for v in m.embed(paths, batch_size=8):
        v = np.asarray(v, dtype=np.float32)
        out.append(v / (np.linalg.norm(v) + 1e-8))
    return out


def colour_sig(path: str) -> np.ndarray | None:
    """Цветовая подпись: сетка 8×8 в RGB. Отпечаток и CLIP видят форму, а не оттенок ткани."""
    try:
        im = Image.open(path).convert('RGB').resize((8, 8), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        return None
    return np.asarray(im, dtype=np.float32)


def colour_diff(path_a: str, path_b: str) -> float:
    a, b = colour_sig(path_a), colour_sig(path_b)
    if a is None or b is None:
        return 999.0
    return float(np.abs(a - b).mean())


def same_image(path_a: str, path_b: str) -> tuple[bool, str]:
    """Та же картинка или другая. Возвращает (то же ли, чем решили).

    При сомнении отвечаем «другая»: лишний дешёвый пересчёт безопаснее, чем чужое обогащение,
    оставшееся за товаром.
    """
    fa, fb = fingerprint_file(path_a), fingerprint_file(path_b)
    if not fa or not fb:
        return False, 'нет отпечатка — считаем изменением'
    dist = hamming(fa, fb)
    dc = colour_diff(path_a, path_b)
    if dist <= HAM_SAME and dc <= RGB_SAME:
        return True, f'отпечаток совпал (расстояние {dist}, цвет {dc:.1f})'
    if dist <= HAM_SAME:
        return False, f'форма та же (расстояние {dist}), но цвет другой ({dc:.1f}) — другой вариант'
    if dist > HAM_CLOSE:
        return False, f'отпечаток далёк (расстояние {dist})'
    if dc > RGB_SAME:
        return False, f'спорный отпечаток ({dist}) и цвет другой ({dc:.1f}) — другое'
    va, vb = _embed([path_a, path_b])
    cos = float(va @ vb)
    same = cos >= COS_SAME
    return same, (f'спорный отпечаток ({dist}), цвет {dc:.1f}, эмбеддинг {cos:.3f} → '
                  f'{"то же" if same else "другое"}')


def _rows(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:400])
        sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]


def _key(mid, eid) -> str:
    return f"{mid}-{re.sub(r'[^A-Za-z0-9]', '_', str(eid))[:40]}"


def _from_imgcache() -> list[tuple[int, str, str]]:
    """(mid, eid, fp) для товаров БЕЗ отпечатка, чей файл уже лежит в imgcache.

    Имя файла — тот же ключ, что у `golden_label._image_b64`: не-алфавитные символы URL → '_',
    последние 90 символов, расширение .jpg. Соответствие товар→файл точное (по image_url).
    """
    if not os.path.isdir(IMGCACHE):
        return []
    rows = _rows("select e.shop_mid, e.external_id, p.image_url from product_enrichment e "
                 "join products p using (shop_mid, external_id) "
                 "where e.perceptual_hash is null and p.image_url is not null "
                 "and p.image_url<>''")
    out = []
    for mid, eid, url in rows:
        path = os.path.join(IMGCACHE, re.sub(r'[^A-Za-z0-9]', '_', url)[-90:] + '.jpg')
        if not os.path.exists(path):
            continue
        fp = fingerprint_file(path)
        if fp:
            out.append((int(mid), eid, fp))
    return out


def from_cache() -> None:
    """Проставить перцептивный хеш всем товарам, чья картинка уже лежит в кэше.

    Ни одной новой закачки: работаем по тому, что скачано ради миниатюр и эталонов, плюс
    главный кэш обогащения `imgcache/` (24.9k картинок 448px) — раньше он не сканировался,
    и отпечаток был лишь у 17% пула (аудит 06.08, волна А1).
    """
    done = 0
    updates = []
    for folder, ext in ((THUMBS, '.png'), (REFS, '.jpg')):
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if not fn.endswith(ext):
                continue
            m = re.match(r'(\d+)-(.+)' + re.escape(ext) + r'$', fn)
            if not m:
                continue
            fp = fingerprint_file(os.path.join(folder, fn))
            if not fp:
                continue
            updates.append((int(m.group(1)), m.group(2), fp))
            done += 1
    imgcache_updates = _from_imgcache()
    done += len(imgcache_updates)
    if not updates and not imgcache_updates:
        print('в кэше нечего хешировать')
        return
    if imgcache_updates:
        # точное соответствие товар→файл (ключ = image_url), префиксные like не нужны
        for chunk_start in range(0, len(imgcache_updates), 2000):
            chunk = imgcache_updates[chunk_start:chunk_start + 2000]
            vals = ','.join(f"({mid},'{eid}','{fp}')" for mid, eid, fp in chunk)
            _rows(f"""
              update product_enrichment e set perceptual_hash=v.fp, updated_at=now()
                from (values {vals}) as v(mid, eid, fp)
               where e.shop_mid=v.mid and e.external_id=v.eid
                 and e.perceptual_hash is distinct from v.fp;""")
        print(f'imgcache: отпечатков посчитано {len(imgcache_updates)}')
    if not updates:
        print(_rows("select 'с отпечатком: '||count(*) from product_enrichment "
                    "where perceptual_hash is not null")[0][0])
        return
    # ключ в кэше — усечённый external_id, поэтому обновляем по префиксу
    vals = ','.join(f"({mid},'{eid}','{fp}')" for mid, eid, fp in updates)
    _rows(f"""
      update product_enrichment e set perceptual_hash=v.fp, updated_at=now()
        from (values {vals}) as v(mid, eid_key, fp)
       where e.shop_mid=v.mid
         and regexp_replace(e.external_id,'[^A-Za-z0-9]','_','g') like v.eid_key||'%';
      select 'с отпечатком: '||count(*) from product_enrichment where perceptual_hash is not null;
    """)
    print(f'посчитано отпечатков: {done}')
    print(_rows("select 'с отпечатком: '||count(*) from product_enrichment "
                "where perceptual_hash is not null")[0][0])


def check(mid: int, eid: str, url: str) -> None:
    """Скачать картинку по новому URL и сказать, изменилась ли она на самом деле."""
    row = _rows(f"select coalesce(perceptual_hash,'') from product_enrichment "
                f"where shop_mid={mid} and external_id='{eid}'")
    old = row[0][0] if row else ''
    u = 'https:' + url if url.startswith('//') else url
    req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        data = urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:  # noqa: BLE001 — CDN отдаёт 404/502 регулярно; это не повод падать
        print(f'картинка не скачалась ({str(e)[:50]}) — отпечаток не меняем, товар на перепроверку')
        return
    new = fingerprint(data)
    dist = hamming(old, new)
    if not old:
        print(f'старого отпечатка нет — нужен анализ. новый {new}')
    elif dist <= HAM_SAME:
        print(f'картинка ТА ЖЕ (расстояние {dist}) — повторный анализ не нужен')
    elif dist > HAM_CLOSE:
        print(f'картинка ДРУГАЯ (расстояние {dist}) — нужен повторный анализ')
    else:
        print(f'спорно (расстояние {dist}) — решает эмбеддинг, см. same_image()')


def main() -> None:
    if '--from-cache' in sys.argv:
        from_cache()
    elif '--check' in sys.argv:
        i = sys.argv.index('--check')
        check(int(sys.argv[i + 1]), sys.argv[i + 2], sys.argv[i + 3])
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
