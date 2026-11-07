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


def registry_room_fields(payload: dict) -> dict:
    """Комната и вариант кадра для записи реестра (onb-12): страница шлёт `room_id`/`variant_id` (`index.html:payload`); пришли —
    пишем строкой до 64 знаков, нет (старая страница) — полей нет вовсе, запись читается как гостиная, как весь реестр до onb-12."""
    out = {}
    for k in ('room_id', 'variant_id'):
        v = str(payload.get(k) or '').strip()
        if v and len(v) <= 64:
            out[k] = v
    return out


# ЗАЩИТА ФОТО ОПУБЛИКОВАННЫХ СОСТОЯНИЙ (T-20261107-17). Реестр полон (120), а прежнее правило держало только свежайшую запись пары
# (комната, стиль): ночной черновик того же стиля снимал защиту с фото нейросети, и при полном реестре оно уходило как старое —
# главная (`index.html:pubShot`) показала бы черновик вместо фото. Какие записи показывает главная, знает только код страницы
# (номер состояния `pubStateOf`, точка `shotCamOk`, сверка варианта `regOf`), поэтому сервер формулу не повторяет: ночной прогрев
# (`tools/ops/demo-warm.mjs`) тем же кодом выбирает для каждого опубликованного варианта последнее годное фото нейросети, а нет его —
# последнюю годную запись, и кладёт их ключи файлом `pub-shots.json` рядом с реестром. Нет файла, битый, большой или старше 3 суток —
# защита только прежняя (статус виден в `shots-trim.json` и в сводке ночи).
PUB_FILE = 'pub-shots.json'
PUB_MAX_KEYS = 400            # больше вариантов на главной не бывает; битый файл не раздует обязательное сверх разумного
PUB_MAX_BYTES = 256 * 1024
PUB_MAX_AGE_SEC = 3 * 86400


def shot_key(r: dict) -> str:
    """Ключ записи реестра: `id` (с 2026-10 у всех новых), у старых без него — комната|стиль|время. Тот же ключ строит прогрев."""
    return str(r.get('id') or f"{r.get('room_id') or 'living'}|{r.get('style') or ''}|{r.get('ts') or 0}")


def load_pub(path: str, now: float | None = None) -> tuple[set | None, str]:
    """Ключи защищённых записей из `pub-shots.json` и статус: ok | missing | bad | big | stale. Возраст — по mtime файла на
    сервере (часы DEV могут расходиться), не по полю `ts` внутри."""
    try:
        st = os.stat(path)
    except OSError:
        return None, 'missing'
    if st.st_size > PUB_MAX_BYTES:
        return None, 'big'
    if (now if now is not None else time.time()) - st.st_mtime > PUB_MAX_AGE_SEC:
        return None, 'stale'
    try:
        with open(path, encoding='utf-8') as f:
            keys = json.load(f).get('keys')
    except (OSError, ValueError, AttributeError):
        return None, 'bad'
    if not isinstance(keys, list) or not all(isinstance(k, str) and 0 < len(k) <= 200 for k in keys):
        return None, 'bad'
    if len(keys) > PUB_MAX_KEYS:
        return None, 'big'
    return set(keys), 'ok'


TRIM_STATS_FILE = 'shots-trim.json'


def trim_stats_update(prev, st: dict, pub_status: str, now: float) -> dict:
    """Счётчики обрезки реестра (`shots-trim.json`, пишет только сервер): итоги растут монотонно с `epoch` (новый — если файла нет
    или он битый), «за ночь» считает сам ночной прогон разницей со своей прошлой отметкой — второго писателя у файла нет.
    `protected_current` — сколько записей реестра сейчас под защитой списка прогрева (а не прибавка)."""
    base = prev if isinstance(prev, dict) and prev.get('epoch') and isinstance(prev.get('dropped_total'), int) else None
    if base is None:
        import uuid
        base = {'epoch': uuid.uuid4().hex[:12], 'since': int(now * 1000), 'trim_events_total': 0, 'dropped_total': 0,
                'dropped_realistic_total': 0, 'overflow_events_total': 0}
    out = dict(base)
    if st.get('dropped'):
        out['trim_events_total'] = int(out.get('trim_events_total', 0)) + 1
    out['dropped_total'] = int(out.get('dropped_total', 0)) + int(st.get('dropped', 0))
    out['dropped_realistic_total'] = int(out.get('dropped_realistic_total', 0)) + int(st.get('dropped_realistic', 0))
    if st.get('overflow'):
        out['overflow_events_total'] = int(out.get('overflow_events_total', 0)) + 1
    out.update(protected_current=int(st.get('protected', 0)), overflow_current=int(st.get('overflow', 0)), pub_status=pub_status,
               updated=int(now * 1000))
    return out


def registry_trim(data: list, cap: int = REGISTRY_MAX, pub: set | None = None, stats: dict | None = None) -> list:
    """Реестр не длиннее `cap`. Обязательно остаются: свежайшая запись каждой пары (комната, стиль) — как раньше (иначе кадры
    покупателей вытесняют прогретые кадры карточек, b2b-08; кадры спальни — кадр гостиной того же стиля, onb-12; запись без
    `room_id` — гостиная) — и записи из `pub`
    (кадры, которые сейчас показывает главная). Остальное место — сперва фото нейросети, затем прочее, свежие первыми; уходят старые
    черновики и старые состояния. Обязательных больше `cap` — остаются все (переполнение — в `stats['overflow']`). Порядок записей
    сохраняется. `stats` (если дан) получает dropped / dropped_realistic / protected / overflow."""
    pub = pub or set()
    if stats is not None:
        stats.update(dropped=0, dropped_realistic=0, overflow=0, protected=sum(1 for r in data if shot_key(r) in pub))
    if len(data) <= cap:
        return data
    keep = set()
    seen = set()
    for i in range(len(data) - 1, -1, -1):
        st = data[i].get('style') or ''
        key = (data[i].get('room_id') or 'living', st)
        if st and key not in seen:
            seen.add(key)
            keep.add(i)
    keep |= {i for i, r in enumerate(data) if shot_key(r) in pub}
    newest = [i for i in range(len(data) - 1, -1, -1) if i not in keep]
    rest = [i for i in newest if data[i].get('quality') == 'realistic'] + [i for i in newest if data[i].get('quality') != 'realistic']
    out_i = keep | set(rest[:max(0, cap - len(keep))])
    if stats is not None:
        gone = [r for i, r in enumerate(data) if i not in out_i]
        stats.update(dropped=len(gone), dropped_realistic=sum(1 for r in gone if r.get('quality') == 'realistic'),
                     overflow=max(0, len(keep) - cap))
    return [data[i] for i in sorted(out_i)]


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
    # onb-12: свежий кадр — по паре (комната, стиль); запись без комнаты — гостиная, старые записи читаются
    mix = ([{'style': 'сканди', 'ts': 0}, {'style': 'сканди', 'room_id': 'bedroom', 'variant_id': 'bed1', 'ts': 1}]
           + [{'style': 'сканди', 'room_id': 'living', 'ts': i} for i in range(2, 200)])
    tr = registry_trim(mix, 50)
    ok(len(tr) == 50 and tr[0] == mix[1] and tr[-1] == mix[-1],
       'реестр кадров: старый кадр спальни не вытесняют кадры гостиной того же стиля')
    ok(mix[0] not in tr, 'реестр кадров: запись без комнаты — гостиная (её вытесняет свежий кадр гостиной того же стиля)')
    tr = registry_trim([{'style': 'лофт', 'ts': 0}] + [{'style': 'сканди', 'ts': i} for i in range(1, 60)], 10)
    ok(len(tr) == 10 and tr[0]['style'] == 'лофт', 'реестр кадров: старые записи без комнаты — как раньше, по стилю')
    # T-17: фото нейросети из списка прогрева не уходит под 10 свежими черновиками того же стиля; без списка — уходит
    reg = [{'id': 'p', 'style': 'сканди', 'quality': 'realistic', 'ts': 0}] + [{'id': f'd{i}', 'style': 'сканди', 'ts': i} for i in range(1, 11)]
    st: dict = {}
    tr = registry_trim(reg, 3, pub={'p'}, stats=st)
    ok(tr[0]['id'] == 'p' and len(tr) == 3 and st['protected'] == 1 and st['dropped'] == 8 and st['dropped_realistic'] == 0,
       'реестр кадров: фото из списка прогрева остаётся при свежих черновиках, счётчики точны')
    ok(registry_trim([dict(r, quality='draft') if r['id'] == 'p' else r for r in reg], 3)[0]['id'] == 'd8',
       'реестр кадров: без списка и без фото нейросети — по свежести, как раньше')
    ok(len(registry_trim(reg, 2, pub={'p', 'd1', 'd2'})) == 4, 'реестр кадров: обязательных больше предела — остаются все')
    ok(shot_key({'style': 'x', 'ts': 5}) == 'living|x|5' and shot_key({'id': 'a'}) == 'a', 'ключ записи: id, иначе комната|стиль|время')
    ok(registry_room_fields({'room_id': 'bedroom', 'variant_id': 'bed1', 'style': 'x'}) =={'room_id': 'bedroom', 'variant_id': 'bed1'},
       'запись реестра: комната и вариант сохраняются, если пришли')
    ok(registry_room_fields({'style': 'x'}) == {} and registry_room_fields({'room_id': '', 'variant_id': 'v' * 65}) == {},
       'запись реестра: не пришли (старая страница) или мусор — полей нет, запись — гостиная')
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
