"""МЕДИА ТОВАРА — ПРОИЗВОДНЫЕ ДАННЫЕ (26.08, владелец: «миниатюра вообще не такая, что на сайте»).

Диагноз: банк `sets3.json` хранил замороженные `img`/`url`. Сверка с каталогом по ключу
(shop_mid, external_id) показала: 1490 позиций из 3086 несли КАРТИНКУ ДРУГОГО ТОВАРА той же
роли (кресло Дольче с фото кресла Ретро, стол Ориндж с фото стола Jasmin), при этом в БД
image_url уникален для каждого из 32343 товаров. Значит картинку нельзя хранить в банке —
её надо резолвить из каталога в момент использования: тогда «фото не от того товара» и
«товар исчез из фида» ловятся автоматически, без ручных чисток.

ДОСТУПНОСТЬ ≠ «НЕТ В ТАБЛИЦЕ» (26.08, разбор Codex): `load3` строки не удаляет — исчезнувший
товар получает `in_stock=false`, затем `missing → archived`. Плюс источник с битым фидом стоит
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
    q = ("select shop_mid||'\x1f'||external_id||'\x1f'||coalesce(image_url,'')||'\x1f'"
         "||coalesce(direct_url,url,'')||'\x1f'||coalesce(price_rub,0)||'\x1f'||name"
         "||'\x1f'||coalesce(status,'active')||'\x1f'||coalesce(in_stock::int,0) from products")
    out = subprocess.run(PSQL + [q], capture_output=True, text=True).stdout
    m = {}
    for line in out.splitlines():
        p = line.split('\x1f')
        if len(p) >= 8:
            mid = str(p[0])
            state = ('unknown' if int(mid) in _QUARANTINE else
                     'available' if (p[6] == 'active' and p[7] == '1') else 'gone')
            m[(mid, str(p[1]))] = {'img': p[2] or None,
                                   'url': _direct(p[3]) if p[3] else None,
                                   'price': int(p[4] or 0), 'name': p[5], 'state': state}
    _CACHE = m
    return m


def media(mid, eid):
    """Текущие фото/ссылка/цена товара; None — товара в каталоге больше нет (ушёл из фида)."""
    return _load().get((str(mid), str(eid)))


def sync_bank(path: str = 'sets3.json', apply: bool = False) -> dict:
    """Привести медиа банка к каталогу. Позиции, которых нет в фиде, помечаются `_gone: true` —
    решение о замене принимает лечение (`sets_incremental.py`), не этот модуль."""
    sets = json.load(open(path, encoding='utf-8'))
    stat = {'ok': 0, 'fixed_img': 0, 'fixed_url': 0, 'gone': 0, 'unknown': 0}
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
          f"ссылок исправлено {st['fixed_url']}, ушли из каталога {st['gone']}, "
          f"магазин в карантине (не проверить) {st['unknown']}"
          + ('' if '--apply' in sys.argv else '  (сухой прогон, --apply чтобы записать)'))
