"""МЕДИА ТОВАРА — ПРОИЗВОДНЫЕ ДАННЫЕ (26.08, владелец: «миниатюра вообще не такая, что на сайте»).

Диагноз: банк `sets3.json` хранил замороженные `img`/`url`. Сверка с каталогом по ключу
(shop_mid, external_id) показала: 1490 позиций из 3086 несли КАРТИНКУ ДРУГОГО ТОВАРА той же
роли (кресло Дольче с фото кресла Ретро, стол Ориндж с фото стола Jasmin), при этом в БД
image_url уникален для каждого из 32343 товаров. Значит картинку нельзя хранить в банке —
её надо резолвить из каталога в момент использования: тогда «фото не от того товара» и
«товар исчез из фида» ловятся автоматически, без ручных чисток.

ДОСТУПНОСТЬ ≠ «НЕТ В ТАБЛИЦЕ» (26.08, разбор Codex): `load3` строки не удаляет — исчезнувший
товар уходит в `missing → archived`, и наличие пересчитывает `stock_truth`. Плюс источник с битым фидом стоит
в карантине (`feed-freshness.json`), и про его товары нельзя утверждать НИЧЕГО: их просто никто
не проверял. Поэтому `media()` отдаёт запись со статусом: `available` (жив в свежем прогоне),
`gone` (подтверждённо ушёл) и `unknown` (магазин в карантине).

Использование:
    from catalog_media import media, sync_bank
    m = media(mid, eid)      # {'img','url','price','name','state'} или None — ключа нет в каталоге
"""
import subprocess
import json
import os

from reflink import direct as _direct     # ссылка в магазин строится ТЕМ ЖЕ кодом, что при
                                         # загрузке (раскрытие goto= + починка разделителя erid)

PSQL = ["docker", "exec", "-i", "remlab-devdb", "psql", "-U", "remlab", "-d", "remlab",
        "-q", "-v", "ON_ERROR_STOP=1", "-tAc"]
_CACHE = None


def _quarantined_mids() -> set:
    """Магазины, чей фид сейчас не принят (broken/stale/empty): их товары не проверялись."""
    out = set()
    try:
        fr = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         'feed-freshness.json'), encoding='utf-8'))
    except Exception:
        return out
    for f in fr.values():
        if (f.get('state') or '') in ('broken', 'stale', 'empty'):
            out.update(int(x) for x in (f.get('mids') or []) + (f.get('mids_quarantine_pending') or []))
    return out


_QUARANTINE = _quarantined_mids()


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    q = ("select p.shop_mid||'\x1f'||p.external_id||'\x1f'||coalesce(p.image_url,'')||'\x1f'"
         "||coalesce(p.direct_url,p.url,'')||'\x1f'||coalesce(p.price_rub,0)||'\x1f'||p.name"
         "||'\x1f'||coalesce(p.status,'active')||'\x1f'||coalesce(p.in_stock::int,0)"
         "||'\x1f'||p.shop||'\x1f'||coalesce(p.w_cm,0)||'\x1f'||coalesce(p.d_cm,0)"
         "||'\x1f'||coalesce(p.h_cm,0)||'\x1f'||coalesce(p.dia_cm,0)"
         "||'\x1f'||coalesce(ps.state,'')||'\x1f'||coalesce(p.url,'')"
         " from products p left join product_page_status ps"
         " on ps.shop_mid=p.shop_mid and ps.external_id=p.external_id")
    out = subprocess.run(PSQL + [q], capture_output=True, text=True).stdout
    m = {}
    for line in out.splitlines():
        p = line.split('\x1f')
        if len(p) >= 8:
            mid = str(p[0])
            # КАРАНТИН ИСТОЧНИКА ЗАЩИЩАЕТ ТОЛЬКО ЖИВОЙ ТОВАР (26.08): если магазин закрыт
            # (программы нет в кабинете Гдеслона) и товар уже архивный — «не проверить» не
            # оправдание, это именно «ушёл».
            active = (p[6] == 'active' and p[7] == '1')
            # ПОДТВЕРЖДЁННО МЁРТВАЯ КАРТОЧКА СИЛЬНЕЕ КАРАНТИНА ФИДА (31.08): «фид не приехал» —
            # это «не знаю про фид», но про товар мы знаем точно — его страницы нет.
            page_dead = len(p) > 13 and p[13] in ('gone', 'oos')
            state = ('available' if active else 'gone' if page_dead else
                     'unknown' if (int(mid) in _QUARANTINE and p[6] == 'active') else 'gone')
            num = lambda v: (float(v) or None) if v else None   # noqa: E731
            # ДВЕ РАЗНЫЕ ССЫЛКИ, И ПУТАТЬ ИХ НЕЛЬЗЯ (01.09, разбор Codex + замер):
            #   url       — ПАРТНЁРСКАЯ (`xf.gdeslon.ru/...goto=...`), её и показываем человеку:
            #               атрибуция клика живёт в редиректе партнёрки (он сам добавляет
            #               `gsaid`/`_gs_ref`/`utm_source=gdeslon` и приводит на ту же карточку).
            #               Прямая ссылка с одним `erid` — это МАРКИРОВКА РЕКЛАМЫ, а не засчитанный
            #               клик: до 01.09 банк хранил именно её, то есть переходы уходили в
            #               магазин мимо партнёрки и комиссия не начислялась (ADR-0016 требует
            #               обратного: внешний переход ВСЕГДА через реф).
            #   probe_url — прямая карточка, СЛУЖЕБНАЯ: проверка наличия и скрейп фото. Стучаться
            #               ботом в партнёрскую ссылку нельзя — это накрутка кликов.
            aff = (p[14] if len(p) > 14 else '') or None
            m[(mid, str(p[1]))] = {'img': p[2] or None,
                                   'url': aff or (_direct(p[3]) if p[3] else None),
                                   'probe_url': _direct(p[3]) if p[3] else None,
                                   'price': int(p[4] or 0), 'name': p[5], 'state': state,
                                   'shop': p[8], 'w': num(p[9]), 'd': num(p[10]),
                                   'h': num(p[11]), 'dia': num(p[12])}
    _CACHE = m
    return m


def media(mid, eid):
    """Текущие фото/ссылки/цена товара; None — товара в каталоге больше нет (ушёл из фида).

    `url` — партнёрская (человеку), `probe_url` — прямая карточка (машине). См. `_load()`.
    """
    return _load().get((str(mid), str(eid)))


def sync_bank(path: str = 'sets3.json', apply: bool = False) -> dict:
    """Привести медиа банка к каталогу. Позиции, которых нет в фиде, помечаются `_gone: true` —
    решение о замене принимает лечение (`sets_incremental.py`), не этот модуль."""
    sets = json.load(open(path, encoding='utf-8'))
    stat = {'ok': 0, 'fixed_img': 0, 'fixed_url': 0, 'gone': 0, 'unknown': 0,
            'fixed_shop': 0, 'fixed_dims': 0, 'dims_unknown': 0}
    for st in sets:
        for role, it in (st.get('items') or {}).items():
            if not it or not it.get('eid'):
                continue
            m = media(it.get('mid'), it['eid'])
            if not m or m['state'] == 'gone':
                stat['gone'] += 1
                it['_gone'] = True
                continue
            it.pop('_gone', None)
            if m['state'] == 'unknown':
                stat['unknown'] += 1     # источник в карантине — медиа не трогаем, но помечаем
                it['_source_quarantined'] = True
                continue
            it.pop('_source_quarantined', None)
            if (it.get('img') or '') != (m['img'] or ''):
                stat['fixed_img'] += 1
                it['img'] = m['img']
            if (it.get('url') or '') != (m['url'] or ''):
                stat['fixed_url'] += 1
                it['url'] = m['url']
            # ГАБАРИТЫ И МАГАЗИН — ТОЖЕ ИЗ КАТАЛОГА (26.08, находка владельца: коврик 90 см
            # стоял в банке как 230×160 и с чужим магазином — размеры остались от предыдущего
            # товара слота). Размер решает, влезет ли предмет в комнату: хранить его отдельно
            # от товара нельзя. Каталог не знает размера — позицию нельзя проверить, помечаем
            # `_dims_unknown`, и контракт слота её заменит. Частичное знание (фид даёт ширину и
            # высоту, но не глубину) — норма: правим то, что каталог знает, остальное оставляем.
            if m.get('shop') and it.get('shop') != m['shop']:
                stat['fixed_shop'] += 1
                it['shop'] = m['shop']
            if not any(m.get(f) for f in ('w', 'd', 'h', 'dia')):
                stat['dims_unknown'] += 1
                it['_dims_unknown'] = True
            else:
                it.pop('_dims_unknown', None)
                for f in ('w', 'd', 'h', 'dia'):
                    if m.get(f) and it.get(f) != m[f]:
                        stat['fixed_dims'] += 1
                        it[f] = m[f]
                        it['_dims_changed'] = True
            stat['ok'] += 1
    if apply:
        bak = path + '.bak-media'
        if not os.path.exists(bak):
            json.dump(json.load(open(path, encoding='utf-8')), open(bak, 'w', encoding='utf-8'),
                      ensure_ascii=False)
        json.dump(sets, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
    return stat


if __name__ == '__main__':
    import sys
    st = sync_bank(apply='--apply' in sys.argv)
    print(f"медиа банка: сверено {st['ok']}, фото исправлено {st['fixed_img']}, "
          f"ссылок исправлено {st['fixed_url']}, габаритов {st['fixed_dims']}, "
          f"магазин исправлен {st['fixed_shop']}, размер неизвестен каталогу {st['dims_unknown']}, "
          f"ушли из каталога {st['gone']}, магазин в карантине {st['unknown']}"
          + ('' if '--apply' in sys.argv else '  (сухой прогон, --apply чтобы записать)'))
