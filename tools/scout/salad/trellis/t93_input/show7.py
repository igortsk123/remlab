#!/usr/bin/env python3
"""T-93: 7 товаров для сверки — полный вид полей из db_photos.json (без описаний)."""
import json

SEVEN = ['112923:13224664101879413845', '114667:11634594969038554503', '114082:10587794773481498560', '112923:7957884067802792858',
         '112923:1167444740116678789', '99272:10280649775260801227', '99272:607007941975253599']
d = json.load(open('/home/pakar/remlab-logs/t93-1119/db_photos.json', encoding='utf-8'))
for s in SEVEN:
    x = d[s]
    print('=====', s, x['name'], '|', x['shop'])
    for k in ('image_url', 'image_url_hd', 'url', 'direct_url', 'photo_bg', 'photo_collage', 'mesh_from_collage', 'photo_alive'):
        print('  ', k, '=', x.get(k))
    print('   param_keys:', x.get('param_keys'))
    print('   param_pics:', json.dumps(x.get('param_pics'), ensure_ascii=False)[:400])
    print('   product_photo_current:', json.dumps(x.get('product_photo_current'), ensure_ascii=False)[:300])
    print('   api_offers:', json.dumps(x.get('api_offers'), ensure_ascii=False)[:700])
