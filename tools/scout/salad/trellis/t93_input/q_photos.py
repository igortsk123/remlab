#!/usr/bin/env python3
"""T-93: какие картинки товара есть в БД (только чтение). Для 30 товаров пробы: image_url, image_url_hd, params с адресами, api_offers.picture,
product_photo_current, product_enrichment (hash). Вывод — JSON в ~/remlab-logs/t93-1119/db_photos.json и краткая таблица."""
import json
import subprocess
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/.claude/worktrees/trellis-trial/tools/scout')
import catalog_media as CM

OUT = '/home/pakar/remlab-logs/t93-1119/db_photos.json'
SKUS = list(json.load(open('/home/pakar/remlab-logs/mesh-models-1118/trellis/inputs30/inputs.json', encoding='utf-8')))


def q(sql):
    r = subprocess.run(CM.PSQL + [sql], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('psql rc=%s %s' % (r.returncode, r.stderr[:300]))
    return r.stdout


res = {}
for sku in SKUS:
    mid, eid = sku.split(':', 1)
    row = q("select json_build_object('name',name,'shop',shop,'image_url',image_url,'image_url_hd',image_url_hd,'url',url,'direct_url',direct_url,"
            "'photo_bg',photo_bg,'photo_collage',photo_collage,'mesh_from_collage',mesh_from_collage,'photo_alive',photo_alive,"
            "'param_keys',(select coalesce(json_agg(k),'[]'::json) from jsonb_object_keys(coalesce(params,'{}'::jsonb)) k),"
            "'param_pics',(select coalesce(json_object_agg(k,v),'{}'::json) from jsonb_each_text(coalesce(params,'{}'::jsonb)) as t(k,v) "
            "where v ~* '(\\.jpe?g|\\.png|\\.webp|imgng|picture|photo)' or k ~* '(pict|photo|image|img|фото|картин)'))"
            " from products where shop_mid=%s and external_id='%s'" % (int(mid), eid.replace("'", ''))).strip()
    d = json.loads(row) if row else {}
    pc = q("select coalesce(json_agg(t),'[]'::json) from (select * from product_photo_current where sku='%s') t" % sku.replace("'", '')).strip()
    ao = q("select coalesce(json_agg(t),'[]'::json) from (select picture,image_url_hd,url,direct_url,available,seen_at from api_offers where shop_mid=%s and external_id='%s') t" % (int(mid), eid.replace("'", ''))).strip()
    for key, raw in (('product_photo_current', pc), ('api_offers', ao)):
        try:
            d[key] = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            d[key] = 'err %s %s' % (e, raw[:200])
    res[sku] = d
json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for sku, d in res.items():
    print(sku, '|', (d.get('name') or '')[:40], '| img:', d.get('image_url'), '| hd:', d.get('image_url_hd'), '| bg:', d.get('photo_bg'), 'collage:', d.get('photo_collage'))
