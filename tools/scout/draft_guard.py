"""Защита сервиса кадров (`draft_service.py`, план b2b-01): CORS, частота с адреса, безопасные
ссылки в страницах подборок и передача контакта в базу. Отдельным модулем — чтобы проверять
без тяжёлого рендера: `python tools/scout/draft_guard.py --selftest`."""
import json
import os
import sys
import threading
import time

# CORS — ТОЛЬКО СВОИ АДРЕСА (план b2b-01). Было `*`: любой сайт мог гонять наш платный рендер из
# браузера посетителя. Страницы демо ходят сюда с того же домена через Caddy, им CORS не нужен
# вовсе; список — для локальной отладки и будущих доменов застройщиков.
ALLOWED_ORIGINS = {o.strip().rstrip('/') for o in os.environ.get(
    'DRAFT_ALLOWED_ORIGINS', 'https://remont-lab.online').split(',') if o.strip()}
# Контакт «отправить себе» уходит в базу через приложение (ADR-0248): в файлы под веб-корнем —
# никогда. Адрес внутренний (сеть remlab-net), снаружи Caddy отвечает на него 404.
SHARE_SINK_URL = os.environ.get('SHARE_SINK_URL', 'http://remlab-app:3000/api/internal/share-request')
INTERNAL_TOKEN = os.environ.get('INTERNAL_API_TOKEN', '')
# Частота с одного адреса: рендер и подборки бесплатны для человека, но не для нас. Потолок с
# запасом: менеджеры застройщика в одном офисе выходят в сеть с ОДНОГО адреса и показывают демо
# нескольким покупателям сразу — лимит ловит скрипт-перебор, а не живой показ. Деньги держит HOURLY_CAP.
IP_LIMITS = {'render': (120, 600), 'share': (20, 600)}   # (сколько, за сколько секунд)
_IP_HITS: dict = {}
_IP_LOCK = threading.Lock()


def safe_url(u) -> str:
    """Ссылка в странице подборки — только http(s) или путь от корня сайта (ADR-0248).

    `html.escape` экранирует кавычки, но пропускает `javascript:alert(1)` — такая ссылка
    из присланного JSON стала бы чужим скриптом на нашем домене."""
    s = str(u or '').strip()
    if '\\' in s or any(ord(c) < 32 for c in s):          # «/\evil.com», переводы строк
        return ''
    if s.lower().startswith(('https://', 'http://')):
        return s
    if s.startswith('/') and not s.startswith('//'):
        return s
    return ''


def ip_allowed(ip: str, kind: str, now: float | None = None) -> bool:
    """Скользящее окно в памяти процесса: сервис один, перезапуск сбрасывает счёт — это приемлемо,
    дневной потолок денег держат `HOURLY_CAP` и лимиты приложения."""
    limit, win = IP_LIMITS[kind]
    now = time.time() if now is None else now
    with _IP_LOCK:
        if len(_IP_HITS) > 5000:                    # не копим адреса бесконечно
            for k in [k for k, v in _IP_HITS.items() if not v or now - v[-1] > 3600]:
                _IP_HITS.pop(k, None)
        hits = [t for t in _IP_HITS.get((kind, ip), []) if now - t < win]
        if len(hits) >= limit:
            _IP_HITS[(kind, ip)] = hits
            return False
        hits.append(now)
        _IP_HITS[(kind, ip)] = hits
        return True


def save_share_request(body: dict) -> bool:
    """Отдать заявку приложению (`app/api/internal/share-request`). Ошибка — False и строка в лог
    БЕЗ контакта; файл-запаска не пишется никогда: лучше потерять заявку, чем раскрыть контакт."""
    if not INTERNAL_TOKEN:
        print('заявка «отправить себе» не сохранена: нет INTERNAL_API_TOKEN', flush=True)
        return False
    body = {k: v for k, v in body.items() if v is not None}
    try:
        import urllib.request as _u
        req = _u.Request(SHARE_SINK_URL, data=json.dumps(body).encode(), method='POST',
                         headers={'Content-Type': 'application/json', 'x-internal-token': INTERNAL_TOKEN})
        with _u.urlopen(req, timeout=10) as r:
            return bool(json.loads(r.read()).get('ok'))
    except Exception as e:  # noqa: BLE001
        print(f'заявка «отправить себе» {body.get("shareId")} не сохранена: {str(e)[:120]}', flush=True)
        return False


_DEFAULT_SEC = {'draft': 25.0, 'realistic': 180.0}


def queue_eta(position: int, quality: str, durs: dict, slots: int = 2) -> int:
    """Оценка «через сколько секунд будет кадр» для места `position` в очереди сервиса кадров (1 — следующий; b2b-08
    п.3). Среднее последних замеров по качеству, без замеров — типичное время; `slots` кадров считаются разом."""
    d = durs.get(quality) or []
    avg = sum(d) / len(d) if d else _DEFAULT_SEC.get(quality, 30.0)
    rounds = (max(position, 1) - 1) // max(slots, 1) + 1
    return int(round(avg * rounds))


REGISTRY_MAX = 120


def registry_trim(data: list, cap: int = REGISTRY_MAX) -> list:
    """Реестр кадров не растёт бесконечно, но свежайший кадр КАЖДОГО стиля остаётся: иначе кадры покупателей вытесняют
    прогретые кадры карточек (b2b-08, verify 14.10). Порядок записей сохраняется."""
    if len(data) <= cap:
        return data
    keep = set()
    seen = set()
    for i in range(len(data) - 1, -1, -1):
        st = data[i].get('style') or ''
        if st and st not in seen:
            seen.add(st)
            keep.add(i)
    rest = [i for i in range(len(data) - 1, -1, -1) if i not in keep][:max(0, cap - len(keep))]
    return [data[i] for i in sorted(keep | set(rest))]


def _selftest() -> int:
    bad = 0

    def ok(cond: bool, name: str) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    ok(safe_url('https://shop.ru/x') == 'https://shop.ru/x', 'https-ссылка проходит')
    ok(safe_url('/test/share/a.png') == '/test/share/a.png', 'путь от корня проходит')
    ok(safe_url('javascript:alert(1)') == '', 'javascript: режется')
    ok(safe_url(' JaVaScRiPt:alert(1)') == '', 'javascript: в любом регистре режется')
    ok(safe_url('//evil.com/x') == '', 'протокол-относительная ссылка режется')
    ok(safe_url('data:text/html,<script>') == '', 'data: режется')
    ok(safe_url(None) == '', 'пусто → пусто')
    ok(safe_url('/\\evil.com') == '', 'обратная косая после / режется')
    ok(safe_url('https://a.ru/\nx') == '', 'управляющие символы режутся')
    t0 = 1_000_000.0
    lim, win = IP_LIMITS['share']
    res = [ip_allowed('9.9.9.9', 'share', t0 + i) for i in range(lim + 1)]
    ok(all(res[:lim]) and not res[lim], f'share: {lim} проходят, {lim + 1}-й — нет')
    ok(ip_allowed('8.8.8.8', 'share', t0 + 1), 'другой адрес считается отдельно')
    ok(ip_allowed('9.9.9.9', 'share', t0 + win + 1), 'после окна снова можно')
    ok(queue_eta(1, 'draft', {}) == 25, 'очередь: без замеров — типичное время черновика')
    ok(queue_eta(2, 'draft', {'draft': [10, 20]}) == 15, 'очередь: второй идёт в том же круге (два кадра разом)')
    ok(queue_eta(3, 'draft', {'draft': [10, 20]}) == 30, 'очередь: третий ждёт круг')
    ok(queue_eta(1, 'realistic', {}) == 180, 'очередь: фото — минуты')
    old = [{'style': 'лофт', 'ts': 0}] + [{'style': 'сканди', 'ts': i} for i in range(1, 200)]
    tr = registry_trim(old, 50)
    ok(len(tr) == 50 and tr[0]['style'] == 'лофт', 'реестр кадров: не больше предела, старый кадр редкого стиля сохранён')
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
