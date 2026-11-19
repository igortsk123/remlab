#!/usr/bin/env python3
"""T-93 п.1: что отдаёт API Гдеслона по товару — ВСЕ теги <offer> (в т.ч. повторяющиеся <picture>, <param>, original_picture).
Клиент и ключ — готовый модуль tools/scout/gdeslon_api.py (ключ читает он сам, здесь не показывается и не пишется).
Поиск по названию товара внутри магазина (mid), берём оффер, чьё имя совпадает точнее всего; сырой XML оффера (без ключа) — в t93-1119/gdeslon_raw/."""
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

sys.path.insert(0, '/home/pakar/igor/remlab/tools/scout')
import gdeslon_api as G

OUT = '/home/pakar/remlab-logs/t93-1119/gdeslon_raw'
os.makedirs(OUT, exist_ok=True)
DB = json.load(open('/home/pakar/remlab-logs/t93-1119/db_photos.json', encoding='utf-8'))
SKUS = sys.argv[1:]
res = {}
for sku in SKUS:
    mid, eid = sku.split(':', 1)
    name = DB[sku]['name']
    q = ' '.join(name.split()[:4])
    raw = G._get(G.SEARCH_URL.format(q=urllib.parse.quote(q), mid=int(mid), l=100, p=1, tok=G.token()))
    root = ET.fromstring(raw)
    offers = list(root.iter('offer'))
    best, bs = None, -1
    for o in offers:
        n = (o.findtext('name') or '')
        s = 1000 if n.strip() == name.strip() else len(set(n.lower().split()) & set(name.lower().split()))
        if s > bs:
            best, bs = o, s
    info = {'query': q, 'offers_in_page': len(offers), 'match_score': bs}
    if best is not None:
        tags = {}
        for c in best:
            tags.setdefault(c.tag, []).append((c.text or '').strip()[:300] if c.tag not in ('description',) else '<%d симв.>' % len((c.text or '')))
        info['attrib'] = {k: v for k, v in best.attrib.items()}
        info['name'] = best.findtext('name')
        info['tags'] = {k: v for k, v in tags.items() if k != 'param'}
        info['param_count'] = len(tags.get('param', []))
        info['picture_like_tags'] = {k: v for k, v in tags.items() if re.search('pic|img|image|photo', k, re.I)}
        open(os.path.join(OUT, sku.replace(':', '_') + '.offer.xml'), 'w', encoding='utf-8').write(ET.tostring(best, encoding='unicode'))
    res[sku] = info
    print(sku, '|', info.get('name'), '| score', bs, '| pic-теги:', json.dumps(info.get('picture_like_tags'), ensure_ascii=False)[:600])
json.dump(res, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
