#!/usr/bin/env python3
"""T-93: самые крупные варианты главного фото комода из HTML карточки divan.ru (адреса подписаны магазином, берём ровно те, что он сам отдаёт)."""
import io
import time
import urllib.request

from PIL import Image

B = 'https://cdn.servicecdn.ru/@wmp-core/img/v1/'
E = 'czM6Ly9kaXZhbi9wcm9kdWN0LzQzOTcyNzIucG5n'
U = [B + 'rs:fit:1200:630:1:1:ce:0:0/g:ce:0:0/bg:f5f3f1/q:85/' + E + '.jpg',
     B + 't:0::0:0/pd:123:160:123:160/rs:fit:948:594:0:1:ce:0:0/g:ce:0:0/bg:f5f3f1/q:85/' + E + '.jpg',
     B + 't:0::0:0/pd:58:76:58:76/rs:fit:449:281:0:1:ce:0:0/g:ce:0:0/bg:f5f3f1/q:85/' + E + '.jpg']
for u in U:
    try:
        d = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0'}), timeout=30).read()
        im = Image.open(io.BytesIO(d))
        open('/home/pakar/remlab-logs/t93-1119/photos/112923_13224664101879413845/card_%dx%d.jpg' % im.size, 'wb').write(d)
        print(u.split('/v1/')[1][:60], '→', im.size, len(d) // 1024, 'КБ')
    except Exception as e:  # noqa: BLE001
        print(u[-40:], '→', str(e)[:80])
    time.sleep(1)
