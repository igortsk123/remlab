"""РЕФЕРАЛЬНАЯ ССЫЛКА → ПРЯМАЯ КАРТОЧКА ТОВАРА.

Вынесено из `load3.py` (26.08): загрузчик — скрипт без `if __name__ == '__main__'`, и любой
`from load3 import direct` запускал весь конвейер фидов как побочный эффект. Логика ссылки
нужна и загрузчику, и резолверу медиа (`catalog_media.py`), поэтому живёт отдельным модулем.

ССЫЛКУ БОЛЬШЕ НЕ РЕЖЕМ (01.09.2026, ADR-0144). С 26.08 по 01.09 для mnogomebeli путь обрезался
до раздела: считалось, что «и карточка, и её родитель дают 404, живёт только страница серии».
Замеры 01.09 показали обратное — 404 отдаёт РОДИТЕЛЬ (серия без `/!вариант/`), а сама карточка
жива (200 + `schema.org/InStock`), и с меткой `?erid=` тоже. Правило вывели из одного
наблюдения и приняли за свойство магазина. Цена ошибки: ссылка вела в раздел вместо товара,
а `stock_check` проверял этот раздел — он всегда 200, поэтому мёртвый товар нельзя было снять
автоматикой ни при каких условиях (в выборке 30 карточек мертвы были 11).

Функция ИДЕМПОТЕНТНА: `direct(direct(u)) == direct(u)`. Это не украшение — `catalog_media.py`
применяет её к уже готовому `direct_url`, и прежняя обрезка на втором проходе съедала ещё
один уровень пути (в банке ссылки были на уровень выше, чем в БД).

  reflink.py --selftest
"""
import re
import sys
import urllib.parse


def direct(url):
    """Партнёрская ссылка (или уже прямая) → прямой адрес карточки товара."""
    m = re.search(r'goto=(.+)$', url or '')
    u = urllib.parse.unquote(m.group(1)) if m else (url or '')
    u = u.replace(':443/', '/')
    # РАЗДЕЛИТЕЛЬ ПАРАМЕТРА erid (26.08, находка владельца): партнёрка отдаёт ссылку вида
    # `.../путь/&erid=XXX` — без «?». nonton.ru на такой URL отвечает 404, divan.ru — 502, то есть
    # РЕФЕРАЛЬНАЯ ссылка (наш заработок) вела в никуда у двух крупнейших магазинов. Чиним при
    # загрузке: первый параметр обязан идти через «?».
    if '?' not in u and '&' in u:
        u = u.replace('&', '?', 1)
    return u


# --- селфтест: таблица случаев вместо «проверим на живом каталоге» ---------------------------
def _selftest() -> int:
    GS = 'https://xf.gdeslon.ru/cm/d96529b09e/?mid=114667&goto='
    CARD = ('https://mnogomebeli.com/divany/boss/boss-sleep-160-velyur-royal/'
            '!divan-boss-sleep-160-velyur-royal-topaz/')
    cases = [
        # (что на входе, что ждём на выходе, зачем этот случай)
        (GS + urllib.parse.quote(CARD, safe='') + '&erid=2SDnjdmrh3C',
         CARD + '?erid=2SDnjdmrh3C',
         'карточка mnogomebeli доезжает ЦЕЛИКОМ, с `/!вариантом` и меткой erid'),
        ('https://xf.gdeslon.ru/cm/x/?mid=1&goto=https%3A%2F%2Fwww.divan.ru%2Fproduct%2Fkreslo'
         '&erid=2SDnjeSGLnX',
         'https://www.divan.ru/product/kreslo?erid=2SDnjeSGLnX',
         'у остальных магазинов поведение не изменилось'),
        ('https://xf.gdeslon.ru/cm/x/?mid=1&goto=https%3A%2F%2Fshop.ru%3A443%2Fa%2Fb%2F',
         'https://shop.ru/a/b/',
         'порт :443 из фида убираем'),
        ('https://shop.ru/a/b/?erid=X', 'https://shop.ru/a/b/?erid=X',
         'готовую прямую ссылку не трогаем'),
        ('', '', 'пустая строка не роняет'),
    ]
    bad = 0
    for src, want, why in cases:
        got = direct(src)
        if got != want:
            bad += 1
            print(f'  FAIL {why}\n    получили {got!r}\n    ждали    {want!r}')
    # ИДЕМПОТЕНТНОСТЬ — та самая двойная обрезка: `catalog_media` зовёт direct() второй раз.
    for src, _want, why in cases:
        once = direct(src)
        if direct(once) != once:
            bad += 1
            print(f'  FAIL идемпотентность ({why}): {once!r} → {direct(once)!r}')
    # И отдельно — то, чего быть не должно: путь карточки укорочен до раздела.
    if direct(GS + urllib.parse.quote(CARD, safe='')).count('/') < CARD.count('/'):
        bad += 1
        print('  FAIL путь карточки укорочен — обрезка вернулась')
    print(f'reflink selftest: случаев {len(cases) * 2 + 1}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
