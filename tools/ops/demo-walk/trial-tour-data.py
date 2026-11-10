"""Данные тура пробы для браузерных проб из фикстуры живого `/demo` (`tests/fixtures/trial-tour-furnished.json`, T-20261109-35/3):
та же квартира и расстановка, но предметы — как их отдаёт сборка тура `trial_bundle.py`: нейтральные имена по роли, без названий,
магазинов, ссылок, цен и картинок, декора нет, ленты замен — только товары вариантов (`_feeds`).
    python tools/ops/demo-walk/trial-tour-data.py <выход.json> [--old]
`--old` — имена, как до T-35/3 (у всех диванов «Диван»): так проба воспроизводит прежнюю ошибку «Заменить»."""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import trial_bundle as TB  # noqa: E402


def tour_item(it: dict) -> dict:
    sku = it.get('sku') or {}
    base = TB._base_role(it['role'])
    ru, en = TB.neutral_names(base)
    colour = TB.clean_colour(sku.get('colour_en')) if sku.get('colour_en') else TB.colour_en(sku.get('name'), base)
    new = {'name': ru, 'name_en': en, 'colour_en': colour, 'msid': sku.get('msid'), 'w': sku.get('w', it.get('w')),
           'd': sku.get('d', it.get('d')), 'h': sku.get('h', it.get('h'))}
    if sku.get('sleep_w'):
        new['sleep_w'] = sku['sleep_w']
    return TB.public_item({**it, 'sku': new})


def main() -> int:
    out, old = sys.argv[1], '--old' in sys.argv
    d = json.load(open(os.path.join(ROOT, 'tests', 'fixtures', 'trial-tour-furnished.json'), encoding='utf-8'))
    for v in d['variants']:
        v['items'] = [tour_item(it) for it in v.get('items') or []]
        v['decor'] = []
    if not old:
        TB.name_items(d['variants'])
    feeds = TB._feeds(d['variants'], room_keys=not old)
    d.update(feeds=feeds, sofa_feed=feeds.get('диван', []), sets=[])
    TB.assert_public({'variants': d['variants'], 'feeds': feeds}, [])
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)
    rows = {k: len(v) for k, v in feeds.items()}
    print(json.dumps({'ok': True, 'old': old, 'variants': len(d['variants']), 'feeds': rows}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
