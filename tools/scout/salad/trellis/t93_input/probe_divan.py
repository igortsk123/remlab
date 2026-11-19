#!/usr/bin/env python3
"""T-93: у divan.ru original_picture ограничен 800×600 (imgproxy: rs:fit:800:600, подпись в адресе). Проверка: что в адресе закодировано,
пускает ли CDN другой размер (3 запроса к открытому CDN, без перебора)."""
import base64
import io
import json
import re
import urllib.request

from PIL import Image

DB = json.load(open('/home/pakar/remlab-logs/t93-1119/db_photos.json', encoding='utf-8'))
u = DB['112923:13224664101879413845']['image_url_hd']
print('URL:', u)
m = re.match(r'(https://cdn\d*\.divan\.ru/img/v1/)([^/]+)/(.+)/([^/]+)\.jpg$', u)
sig, opts, enc = m.group(2), m.group(3), m.group(4)
print('подпись:', sig, '| опции:', opts)
pad = enc + '=' * (-len(enc) % 4)
print('источник (base64):', base64.urlsafe_b64decode(pad))
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0'}


def probe(url, label):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as f:
            data = f.read()
        im = Image.open(io.BytesIO(data))
        print(label, '→ 200', im.size, len(data) // 1024, 'КБ')
    except Exception as e:  # noqa: BLE001
        print(label, '→', str(e)[:100])


probe(u, 'как есть            ')
probe(u.replace('rs:fit:800:600', 'rs:fit:2000:1500'), 'rs:fit:2000:1500 подпись как была')
probe(u.replace('rs:fit:800:600', 'rs:fit:1600:1200'), 'rs:fit:1600:1200 подпись как была')
