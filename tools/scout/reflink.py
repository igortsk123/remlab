"""РЕФЕРАЛЬНАЯ ССЫЛКА → ПРЯМАЯ КАРТОЧКА ТОВАРА.

Вынесено из `load3.py` (26.08): загрузчик — скрипт без `if __name__ == '__main__'`, и любой
`from load3 import direct` запускал весь конвейер фидов как побочный эффект. Логика ссылки
нужна и загрузчику, и резолверу медиа (`catalog_media.py`), поэтому живёт отдельным модулем.
"""
import re
import urllib.parse

SPA_CUT = re.compile(r'/!.*$')  # mnogomebeli/divanboss: вариант после /! — серверу неизвестен


def direct(url):
    m = re.search(r'goto=(.+)$', url or '')
    u = urllib.parse.unquote(m.group(1)) if m else (url or '')
    u = u.replace(':443/', '/')
    # РАЗДЕЛИТЕЛЬ ПАРАМЕТРА erid (26.08, находка владельца): партнёрка отдаёт ссылку вида
    # `.../путь/&erid=XXX` — без «?». nonton.ru на такой URL отвечает 404, divan.ru — 502, то есть
    # РЕФЕРАЛЬНАЯ ссылка (наш заработок) вела в никуда у двух крупнейших магазинов. Чиним при
    # загрузке: первый параметр обязан идти через «?».
    if '?' not in u and '&' in u:
        u = u.replace('&', '?', 1)
    host = urllib.parse.urlparse(u).netloc.lower()
    if 'mnogomebeli' in host or 'divanboss' in host:
        u = SPA_CUT.sub('/', u)
        u = re.sub(r'/[^/]+/$', '/', u)  # карточка 404 → родитель (серия) жив
    return u
