#!/usr/bin/env python3
"""Индекс кандидатов: сборщик комплекта не должен читать весь каталог.

Сейчас `compose2` тянет 26 тысяч строк и фильтрует их в памяти на каждый комплект. При 126
комплектах это 126 полных проходов. Индекс раскладывает пул один раз по ключу
«роль × подтип × размерная полка × ценовая ступень × цветовая группа», и подбор роли начинается
с десятков кандидатов, а не с десятков тысяч.

Источник истины — обогащение (`product_enrichment.payload`), а не регексы категории: роль там
проверена моделью, подтип отличает банкетку от пуфа, цвет и материал сверены с текстом.
Товары с качеством ниже порога в индекс не попадают — плохая карточка не должна попасть
в комплект только потому, что подошла по размеру.

  ~/venvs/scout/bin/python candidates.py --build     # собрать и сохранить индекс
  ~/venvs/scout/bin/python candidates.py --funnel столик    # воронка отбора по роли
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, 'candidates-index.json')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
MIN_QUALITY = 0.65

# размерные полки по длинной стороне, см: комплект подбирается под метраж, и полка отсекает
# заведомо чужое до всякого скоринга
BANDS = [(0, 60, 'мини'), (60, 100, 'малый'), (100, 160, 'средний'),
         (160, 230, 'крупный'), (230, 10 ** 4, 'очень крупный')]


def band_of(long_cm: float | None) -> str:
    if not long_cm:
        return 'без размера'
    for lo, hi, name in BANDS:
        if lo <= long_cm < hi:
            return name
    return 'очень крупный'


def rows(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:400])
        sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]


def _photo_ok(url) -> bool:
    try:
        from img_alive import alive as _a
        return _a(url, unknown=True)
    except Exception:
        return True


def build() -> dict:
    data = rows(f"""
      select e.shop_mid, e.external_id, p.name, p.price_rub, p.shop,
             coalesce(p.w_cm,0), coalesce(p.d_cm,0), coalesce(p.h_cm,0), coalesce(p.dia_cm,0),
             p.image_url, coalesce(p.direct_url, p.url),
             e.payload->'model'->>'role', e.payload->'model'->>'functional_subtype',
             e.payload->'model'->>'primary_color', e.payload->'model'->>'materials',
             e.payload->'model'->>'styles', e.payload->'model'->>'style_strength',
             e.payload->'model'->>'visual_mass', e.payload->'model'->>'warmth', e.quality
        from product_enrichment e join products p using (shop_mid, external_id)
       where e.payload is not null and e.status='active' and e.quality >= {MIN_QUALITY}
         and p.price_rub is not null and p.image_url is not null
         and p.in_stock  -- мёртвые карточки (health.py) не должны попадать в комплекты (А2)
    """)
    idx: dict[str, list] = {}
    items: dict[str, dict] = {}
    dead_photo = 0
    for r in data:
        w, d, h, dia = (float(x) for x in r[5:9])
        long_cm = max(w, d, dia) or None
        img, purl = r[9], r[10]                     # 26.08: фото и ПРЯМАЯ ссылка (не редирект
                                                    # партнёрки) — иначе замена ломает контракт ссылки
        role, sub = r[11], r[12]                    # без них лечение не может проверить контракт
        # ФОТО, КОТОРОЕ УЖЕ ПРИЗНАНО МЁРТВЫМ, ВЫБРАСЫВАЕТ ТОВАР ИЗ ПУЛА (владелец 26.08: «товар
        # без фото не должен участвовать в выборке»). Непроверенное пропускаем: обход всего пула
        # идёт ежедневно с бюджетом времени (`img_alive.py --pool`), и решение уточняется само.
        if not _photo_ok(img):
            dead_photo += 1
            continue
        key = f'{role}|{sub}|{band_of(long_cm)}'
        pid = f'{r[0]}:{r[1]}'
        items[pid] = dict(mid=int(r[0]), eid=r[1], name=r[2], price=int(r[3]), shop=r[4],
                          w=w or None, d=d or None, h=h or None, dia=dia or None,
                          role=role, subtype=sub, colour=r[13],
                          img=img, url=purl,
                          materials=json.loads(r[14]) if r[14] else [],
                          styles=json.loads(r[15]) if r[15] else {},
                          strength=r[16], mass=r[17], warmth=r[18], quality=float(r[19]))
        idx.setdefault(key, []).append(pid)
    # ценовые ступени считаем ВНУТРИ роли: «комфортный» торшер и «комфортный» диван — разные деньги
    if dead_photo:
        print(f'выброшено из пула по мёртвому фото: {dead_photo}')
    tiers: dict[str, dict] = {}
    for role in {it['role'] for it in items.values()}:
        ps = sorted(it['price'] for it in items.values() if it['role'] == role)
        if not ps:
            continue

        def pc(p, ps=ps):
            return ps[max(0, min(len(ps) - 1, int(p * len(ps))))]
        tiers[role] = {'эконом': [pc(0.05), pc(0.45)], 'комфорт': [pc(0.35), pc(0.80)],
                       'премиум': [pc(0.70), pc(0.97)]}
    out = {'items': items, 'index': idx, 'tiers': tiers, 'min_quality': MIN_QUALITY}
    json.dump(out, open(INDEX, 'w'), ensure_ascii=False)
    print(f'товаров в индексе: {len(items)}; ключей: {len(idx)}')
    print(f'самые населённые ключи:')
    for k, v in sorted(idx.items(), key=lambda kv: -len(kv[1]))[:8]:
        print(f'  {k:52s} {len(v)}')
    return out


def load() -> dict:
    if not os.path.exists(INDEX):
        return build()
    return json.load(open(INDEX))


def candidates(role: str, tier: str | None = None, bands: list[str] | None = None,
               subtypes: list[str] | None = None, colours: list[str] | None = None,
               style: str | None = None, idx: dict | None = None) -> list[dict]:
    """Кандидаты роли после всех дешёвых отсечений. Порядок фильтров — от самого узкого."""
    idx = idx or load()
    keys = [k for k in idx['index'] if k.split('|')[0] == role
            and (not subtypes or k.split('|')[1] in subtypes)
            and (not bands or k.split('|')[2] in bands)]
    out = [idx['items'][pid] for k in keys for pid in idx['index'][k]]
    if tier and role in idx['tiers']:
        lo, hi = idx['tiers'][role][tier]
        out = [it for it in out if lo <= it['price'] <= hi]
    if colours:
        out = [it for it in out if it['colour'] in colours]
    if style:
        out = [it for it in out if (it['styles'] or {}).get(style) in ('средняя', 'высокая')]
    return out


def funnel(role: str) -> None:
    """Воронка: сколько остаётся после каждого шага. Так видно, где отбор реально сужает."""
    idx = load()
    total = len(idx['items'])
    step1 = candidates(role, idx=idx)
    step2 = candidates(role, tier='комфорт', idx=idx)
    step3 = candidates(role, tier='комфорт', bands=['средний', 'крупный'], idx=idx)
    step4 = candidates(role, tier='комфорт', bands=['средний', 'крупный'], style='сканди', idx=idx)
    print(f'воронка для роли «{role}» (ступень комфорт, стиль сканди):')
    print(f'  весь индекс                 {total:>7}')
    print(f'  → роль                      {len(step1):>7}')
    print(f'  → ценовая ступень           {len(step2):>7}')
    print(f'  → размерная полка           {len(step3):>7}')
    print(f'  → стиль                     {len(step4):>7}')
    if step4:
        best = sorted(step4, key=lambda x: -x['quality'])[:3]
        print('  примеры:')
        for b in best:
            print(f'    {b["name"][:56]:58s} {b["price"]:>7} ₽  {b["subtype"]}')


def main() -> None:
    if '--build' in sys.argv:
        build()
    elif '--funnel' in sys.argv:
        funnel(sys.argv[sys.argv.index('--funnel') + 1])
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
