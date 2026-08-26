#!/usr/bin/env python3
"""ДЕМО «интерактив» по квартире 215 (гостиная): экспорт данных для страницы.

Архитектура — по решению владельца 26.08: НИЧЕГО не считаем на лету. Здесь офлайн собираем
`demo-data.json` (комната + предпосчитанные варианты + лента диванов из каталога + числа правил),
а страница только показывает и даёт двигать. Правила для советчика берутся из ТЕХ ЖЕ файлов,
что читает движок, чтобы подсказки не разошлись с каноном.

  ~/venvs/scout/bin/python flat215_demo.py [--publish]      # → /test/flat215-demo/
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules')
OUT = os.path.expanduser('~/scout-scenes/flat215-demo')
# ВАРИАНТЫ РАССТАНОВКИ и КОМПЛЕКТЫ ТОВАРОВ — РАЗНЫЕ СУЩНОСТИ (владелец 26.08):
# «шаблоны не называть стилями, а просто варианты; далее под любой из шаблонов показываем наши
# сеты; люди могут смешать разные товары из разных стилей». Поэтому: вариант = геометрия
# расстановки, комплект = набор товаров, который на неё накладывается; отдельный предмет можно
# заменить товаром из любого комплекта.
VARIANTS = [(1, 'Вариант 1'), (4, 'Вариант 2'), (7, 'Вариант 3'),
            (10, 'Вариант 4'), (13, 'Вариант 5'), (16, 'Вариант 6')]
SET_BANKS = [1, 4, 7, 10, 13, 16]        # комплекты товаров (по одному на стиль банка)
SHOW_ROLES = ('диван', 'диван 2', 'кресло', 'кресло 2', 'столик', 'ковёр', 'тв-тумба', 'стенка',
              'торшер', 'пуф', 'стеллаж', 'комод', 'витрина', 'кашпо', 'камин', 'банкетка',
              'стол обеденный', 'стул', 'стул 2', 'приставной')


def _rules() -> dict:
    occ = json.load(open(os.path.join(RULES, 'occupancy.json'), encoding='utf-8'))
    zn = json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))
    d = occ.get('distances_cm') or {}
    dyn = occ.get('dynamic') or {}
    return {
        'main_route': zn.get('main_route') or {'quality_min_cm': 75, 'acceptance_floor_cm': 70,
                                               'target_cm': 91},
        'sofa_table_hard': d.get('sofa_coffee_table_hard') or [32, 50],
        'sofa_table_pref': d.get('sofa_coffee_table') or [36, 46],
        'sofa_tv_cm': d.get('sofa_tv_cm') or [180, 300],
        'corner_sofa_tv_min_cm': 150,          # угловой смотрит по диагонали — ближе допустимо
        'corner_sofa_table_min_cm': 0,         # столик внутри «Г» стоит вплотную к плечу
        '_corner_why': 'исключения для Г-дивана — те же, что в движке (solver_run: lo_eff=150; '
                       'validate: нижней границы столика у углового нет)',
        'passage_secondary_cm': d.get('sofa_to_wall_passage') or 76,
        'rug_front_legs_cm': (dyn.get('rug_rules') or {}).get('front_legs_on_rug_cm') or 25,
        'radiator_min_cm': ((dyn.get('radiator') or {}).get('hard_min_clearance_cm') or [15, 20])[0],
        '_provenance': 'services/planner-solver/rules/{occupancy,zones}.json — те же файлы, что у движка',
    }


def _sku(items: dict, role: str) -> dict | None:
    it = items.get(role)
    if not it:
        return None
    return {'name': it.get('name'), 'price': it.get('price'), 'img': it.get('img'),
            'url': it.get('url'), 'shop': it.get('shop'),
            'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h')}


def build() -> dict:
    flat = json.load(open(os.path.join(HERE, 'flat215.json'), encoding='utf-8'))
    liv = flat['rooms'][0]
    sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
    variants = []
    for n, style in VARIANTS:
        fs = glob.glob(os.path.join(HERE, f'v3set{n}-layout.json'))
        if not fs:
            continue
        art = json.load(open(fs[0], encoding='utf-8'))
        items = sets[n - 1].get('items') or {}
        objs = []
        for role, v in art.items():
            if role.startswith('_') or not isinstance(v, dict) or 'x' not in v:
                continue
            if role.split(' ')[0] not in [r.split(' ')[0] for r in SHOW_ROLES]:
                continue
            objs.append({'role': role, 'x': round(v['x'], 1), 'y': round(v['z'], 1),
                         'rot': int(v.get('rot') or 0), 'w': v.get('w'), 'd': v.get('d'),
                         'h': v.get('h'), 'sku': _sku(items, role),
                         # Г-диван: у него ДРУГИЕ пороги (столик может стоять вплотную внутри «Г»,
                         # ТВ ближе — 150 см), иначе советчик выдаёт ложные предупреждения на
                         # плане, который движок считает валидным (26.08)
                         'corner': bool(v.get('corner')),
                         'corner_left': bool(v.get('corner_left')),
                         'section': v.get('section') or v.get('corner_section_cm')})
        variants.append({'id': f'set{n}', 'title': style, 'fill_pct': art.get('_fill_pct'),
                         'items': objs})
    # ЛЕНТЫ ТОВАРОВ ПО РОЛЯМ (владелец 26.08: «чтоб фотки можно было назначать»): для каждой роли
    # собираем живые SKU с фото; границы — конверт слота той же комнаты, чтобы примерка не
    # предлагала заведомо негодный габарит (диван 260 см в 14 м²).
    ENV = {'диван': (144, 198), 'кресло': (60, 100), 'столик': (70, 132), 'ковёр': (180, 300),
           'тв-тумба': (90, 176), 'стеллаж': (60, 110), 'комод': (80, 140), 'торшер': (20, 60),
           'пуф': (35, 90), 'кашпо': (20, 60), 'витрина': (50, 100), 'банкетка': (90, 150),
           'стол обеденный': (70, 160), 'стул': (35, 60), 'приставной': (30, 70)}
    feeds, seen = {}, set()
    for s in sets:
        for role, it in (s.get('items') or {}).items():
            base = role.split(' ')[0]
            if base not in ENV or not it or not it.get('img'):
                continue
            key = (base, it.get('mid'), it.get('eid'))
            if key in seen:
                continue
            lo, hi = ENV[base]
            side = max(it.get('w') or 0, it.get('d') or 0) if base == 'ковёр' else (it.get('w') or 0)
            if not (lo <= side <= hi):
                continue
            seen.add(key)
            feeds.setdefault(base, []).append(
                {'name': it.get('name'), 'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
                 'price': it.get('price'), 'img': it.get('img'), 'url': it.get('url'),
                 'shop': it.get('shop'), 'style': s.get('style')})
    for k in feeds:
        feeds[k].sort(key=lambda x: x['price'] or 0)
        feeds[k] = feeds[k][:24]
    feed = feeds.get('диван', [])
    # КОМПЛЕКТЫ: набор товаров по ролям, который накладывается на ЛЮБОЙ вариант расстановки
    product_sets = []
    for n in SET_BANKS:
        items = (sets[n - 1].get('items') or {})
        roles = {}
        for role, it in items.items():
            base = role.split(' ')[0]
            if base not in ENV or not it or not it.get('img'):
                continue
            roles[role] = {'name': it.get('name'), 'w': it.get('w'), 'd': it.get('d'),
                           'h': it.get('h'), 'price': it.get('price'), 'img': it.get('img'),
                           'url': it.get('url'), 'shop': it.get('shop')}
        if roles:
            product_sets.append({'id': f'kit{n}', 'title': f'Комплект {SET_BANKS.index(n) + 1}',
                                 'roles': roles,
                                 'sum': sum((v.get('price') or 0) for v in roles.values())})
    return {'room': {'w': liv['w'], 'd': liv['d'], 'title': liv['title'],
                     'openings': liv['openings'], 'radiators': liv.get('radiators') or []},
            'variants': variants, 'sets': product_sets, 'sofa_feed': feed, 'feeds': feeds,
            'rules': _rules(),
            '_note': flat.get('_scale_note')}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    data = build()
    json.dump(data, open(os.path.join(OUT, 'demo-data.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"OK: вариантов {len(data['variants'])}; ленты: "
          + ', '.join(f"{k} {len(v)}" for k, v in sorted(data['feeds'].items()))
          + f"; комплектов {len(data['sets'])}")
    if '--publish' in sys.argv:
        subprocess.run(f"cd {os.path.dirname(OUT)} && tar czf /tmp/f215demo.tgz flat215-demo && "
                       "scp -q -P 22222 /tmp/f215demo.tgz root@89.167.127.0:/tmp/ && "
                       "ssh -p 22222 root@89.167.127.0 'cd /tmp && rm -rf flat215-demo && "
                       "tar xzf f215demo.tgz && rm -rf /opt/remlab/test/flat215-demo && "
                       "mv flat215-demo /opt/remlab/test/flat215-demo && rm f215demo.tgz' && "
                       "rm -f /tmp/f215demo.tgz", shell=True, check=True)
        print('опубликовано: /test/flat215-demo/')


if __name__ == '__main__':
    main()
