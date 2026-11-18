#!/usr/bin/env python3
"""Картины по правилу «только с рисунком» на ГОТОВОЙ витрине (T-20261117-18/1) — без полной пересборки и без базы: пул — ленты замен
самой витрины (`feeds['картина']`). У вариантов, чьи картины без рисунка (`wall_art.has_content` ложь), эти строки снимаются и
подбор идёт тем же `wall_art.annotate`, что при сборке (`flat215_demo.wall_art_step`); остальные варианты не трогаются.
Нужно, чтобы посмотреть/отрендерить новые картины, не гоняя весь конвейер. Витрину НЕ правит: пишет копию.
  wall_art_reannotate.py <demo-data.json> <куда-копия.json> [папка-с-img=рядом с demo-data]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wall_art as WA  # noqa: E402


def main(src: str, dst: str, imgroot: str | None = None) -> int:
    imgroot = imgroot or os.path.dirname(os.path.abspath(src))
    data = json.load(open(src, encoding='utf-8'))
    r = WA.rules()
    pool = [dict(p) for p in (data.get('feeds') or {}).get(r['role'], [])]
    blank = set()
    for p in pool:
        try:
            if p.get("img") and not WA.has_content(WA.art_stats(os.path.join(imgroot, p["img"]), p, r), r):
                blank.add(p['img'])
        except OSError:
            pass
    print(f'картин в ленте {len(pool)}, без рисунка {len(blank)}')
    changed = []
    for v in data['variants']:
        arts = [d for d in v.get('decor') or [] if WA.is_art(d, r)]
        if arts and any((d.get('sku') or {}).get('img') in blank for d in arts):
            v['decor'] = [d for d in v['decor'] if not WA.is_art(d, r)]
            changed.append(v['id'])
    got = WA.annotate(data, pool, r, None, blank=blank)
    for vid, sup, names in got:
        print(f'  {vid} над «{sup}»: ' + ('; '.join(names) if names else 'НЕТ товара с рисунком по размеру и стилю'))
    n_crop = WA.annotate_crop(data, imgroot, r)
    print('снято и подобрано заново:', ', '.join(changed) or 'ничего', '| фото без поля', n_crop)
    json.dump(data, open(dst, 'w', encoding='utf-8'), ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:4]))
