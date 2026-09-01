#!/usr/bin/env python3
"""Здоровье нод Salad и бюджет пересадок — ОДНО долговечное состояние на все процессы прогона.

ЗАЧЕМ ФАЙЛ, А НЕ ПАМЯТЬ (01.09, Codex q-node-breaker). Каждая пачка — НОВЫЙ процесс
`ssh_run`, а пересадку зовут двое: `batch_show.cull_slow_pulls` (медленная тяга образа) и
предохранитель битой ноды (`ssh_run`). Счётчик подряд-сбоев в памяти обнулялся бы каждую
пачку — серия 2+2+2 никогда не дошла бы до порога, — а два независимых бюджета пересадки
могли бы вдвоём выкосить весь пул. Поэтому и счётчик, и бюджет живут в файле под flock.

Состояние — рантайм, а не история: файл в `~/scout-scenes/`, не в репозитории.
"""
import fcntl
import json
import os
import threading
import time
import urllib.request

STATE = os.path.expanduser(os.environ.get('MESH_NODE_HEALTH',
                                          '~/scout-scenes/mesh-node-health.json'))
API = 'https://api.salad.com/api/public'
ORG, PROJECT = 'prodstore', 'dmodel'

# Порог владельца (01.09): «аллокейт надо таких нод после 3 подряд».
FAIL_STREAK = int(os.environ.get('MESH_NODE_FAIL_STREAK', '3'))
# Бюджет пересадок — общий на оба повода, иначе чехарда всего пула.
MAX_CULL_PER_TICK = int(os.environ.get('MESH_MAX_CULL_TICK', '2'))
MAX_CULL_PER_HOUR = int(os.environ.get('MESH_MAX_CULL_HOUR', '6'))
# Наблюдения о ноде живут ограниченно: вчерашние два сбоя не должны копиться к сегодняшнему.
STREAK_TTL_S = float(os.environ.get('MESH_STREAK_TTL_S', '21600'))     # 6 ч
RETIRED_TTL_S = float(os.environ.get('MESH_RETIRED_TTL_S', '7200'))    # 2 ч
# Одинаковый класс отказа на нескольких нодах за окно — это общая сеть, а не битая нода.
FLEET_WINDOW_S = float(os.environ.get('MESH_FLEET_WINDOW_S', '300'))
FLEET_MIN_NODES = int(os.environ.get('MESH_FLEET_MIN_NODES', '3'))

# Классы вины. Судим по ТЕКСТУ ошибки, а не по статусу: `input_failed` приносит и мёртвую
# ссылку (404 — вина товара), и оборванную сеть ноды (ENETUNREACH). Классификация здесь, а
# не в воркере, сознательно: воркер живёт в docker-образе на нодах, правка там = пересборка
# и перезалив образа (ADR-0137, часы), а текст ошибки и так приезжает в ответе.
FAULT_NONE = 'none'      # нода отработала
FAULT_NODE = 'node'      # виновата нода — повтор на другой, счётчик растёт
FAULT_JOB = 'job'        # виноват товар — терминально, счётчик обнуляется
FAULT_UNKNOWN = 'unknown'  # непонятно — повтор на другой ноде, но ноду не обвиняем

_NODE_MARKS = ('network is unreachable', 'errno 101',
               'no route to host', 'errno 113',
               'temporary failure in name resolution', 'errno -3',
               'name or service not known', 'errno -2',
               'connection refused', 'errno 111')
# 404/410 = сервер ответил. Значит DNS, TCP и HTTP у ноды работают — это мёртвое фото.
_JOB_MARKS = ('http error 404', 'http error 410', 'error 404', 'error 410')
_JOB_STATUSES = ('bad_cutout', 'flat_shape', 'slab_suspect', 'not_generator_eligible')


def classify(res: dict) -> str:
    """Чья вина в этом результате: ноды, задания или непонятно."""
    st = (res or {}).get('status')
    if st in ('ok', 'cached'):
        return FAULT_NONE
    if st in _JOB_STATUSES:
        return FAULT_JOB
    err = str((res or {}).get('error') or '').lower()
    if st == 'transport_failed':
        # SSH до ноды не дошёл или оборвался — это про ноду, а не про товар.
        return FAULT_NODE
    if st == 'input_failed':
        if any(m in err for m in _JOB_MARKS):
            return FAULT_JOB
        if any(m in err for m in _NODE_MARKS):
            return FAULT_NODE
        # timeout, SSL EOF, 5xx: повторить стоит, но обвинять ноду нельзя — это может быть
        # и хостинг фото. Счётчик ноды такие случаи НЕ растит (Codex: не выкашивать пул).
        return FAULT_UNKNOWN
    if st == 'failed':
        # Произвольная ошибка генерации/публикации. Одним статусом не классифицируется:
        # все 4 случая 01.09 были дефектом кода (пустой source.jpg), а не виной ноды.
        return FAULT_UNKNOWN
    return FAULT_UNKNOWN


def error_class(res: dict) -> str:
    """Грубый класс ошибки — для правила «одно и то же на многих нодах = общая сеть»."""
    err = str((res or {}).get('error') or '').lower()
    for m in _NODE_MARKS + _JOB_MARKS:
        if m in err:
            return m
    if 'timed out' in err or 'timeout' in err:
        return 'timeout'
    if 'ssl' in err:
        return 'ssl'
    return (res or {}).get('status') or 'unknown'


def _empty() -> dict:
    return {'nodes': {}, 'culls': [], 'events': []}


def _prune(st: dict, now: float) -> dict:
    st['culls'] = [t for t in st.get('culls', []) if now - t < 3600]
    st['events'] = [e for e in st.get('events', []) if now - e.get('at', 0) < FLEET_WINDOW_S]
    keep = {}
    for k, v in (st.get('nodes') or {}).items():
        if v.get('retired_at') and now - v['retired_at'] > RETIRED_TTL_S:
            continue
        if not v.get('retired_at') and now - v.get('at', 0) > STREAK_TTL_S:
            continue
        keep[k] = v
    st['nodes'] = keep
    return st


class _State:
    """Файл состояния под flock: читаем, меняем, атомарно пишем обратно."""

    def __init__(self):
        self.fh = None
        self.st = _empty()

    def __enter__(self) -> dict:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        self.fh = open(STATE + '.lock', 'a+')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        try:
            with open(STATE, encoding='utf-8') as f:
                self.st = json.load(f)
        except Exception:  # noqa: BLE001 — нет файла или он битый: начинаем с чистого
            self.st = _empty()
        for k in ('nodes', 'culls', 'events'):
            self.st.setdefault(k, _empty()[k])
        return self.st

    def __exit__(self, *exc) -> None:
        try:
            _prune(self.st, time.time())
            # Имя временного файла — своё на процесс и поток: даже если замок окажется
            # бесполезен (файл замка подменили), процессы не отберут .tmp друг у друга.
            tmp = f'{STATE}.{os.getpid()}.{threading.get_ident()}.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.st, f, ensure_ascii=False)
            os.replace(tmp, STATE)
        except Exception as e:  # noqa: BLE001 — учёт здоровья не должен ронять прогон
            print(f'  здоровье нод: не сохранил ({type(e).__name__}: {str(e)[:60]})', flush=True)
        finally:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def record(node_key: str, fault: str, err_class: str = '') -> int:
    """Учесть результат ноды. Возвращает длину текущей серии сбоев «по вине ноды».

    Серия рвётся любым доказательством работоспособности: `ok`/`cached` и вердикт по товару
    (404 значит, что сеть у ноды жива). `unknown` серию не растит и не рвёт.
    """
    now = time.time()
    with _State() as st:
        n = st['nodes'].setdefault(node_key, {'streak': 0, 'at': now, 'retired_at': None})
        n['at'] = now
        if fault in (FAULT_NONE, FAULT_JOB):
            n['streak'] = 0
        elif fault == FAULT_NODE:
            n['streak'] = int(n.get('streak', 0)) + 1
            n['last_error'] = err_class
            st['events'].append({'node': node_key, 'class': err_class, 'at': now})
        return int(n.get('streak', 0))


def is_retired(node_key: str) -> bool:
    with _State() as st:
        return bool((st['nodes'].get(node_key) or {}).get('retired_at'))


def retire(node_key: str) -> None:
    now = time.time()
    with _State() as st:
        n = st['nodes'].setdefault(node_key, {'streak': 0, 'at': now, 'retired_at': None})
        n['retired_at'] = now
        n['streak'] = 0


def fleet_wide(err_class: str) -> bool:
    """Один и тот же класс отказа на нескольких РАЗНЫХ нодах за окно = общая сеть.

    В этом случае пересаживать ноды бессмысленно и вредно: меняем шило на мыло и теряем
    прогретый пул. Правило Codex, подтверждено данными 01.09 (ENETUNREACH был на одной ноде
    — значит это была именно нода, а не сеть).
    """
    now = time.time()
    with _State() as st:
        hit = {e['node'] for e in st['events']
               if e.get('class') == err_class and now - e.get('at', 0) < FLEET_WINDOW_S}
        return len(hit) >= FLEET_MIN_NODES


def take_cull_slot(n: int = 1) -> int:
    """Взять из ОБЩЕГО бюджета пересадок. Возвращает, сколько реально разрешено."""
    now = time.time()
    with _State() as st:
        st['culls'] = [t for t in st['culls'] if now - t < 3600]
        allowed = max(0, min(n, MAX_CULL_PER_TICK, MAX_CULL_PER_HOUR - len(st['culls'])))
        st['culls'].extend([now] * allowed)
        return allowed


def reallocate(group: str, iid: str, why: str) -> bool:
    """Пересадка инстанса. Бюджет берётся ДО вызова (`take_cull_slot`) — вызов сетевой и
    долгий, под замками его держать нельзя."""
    url = (f'{API}/organizations/{ORG}/projects/{PROJECT}/containers/{group}'
           f'/instances/{iid}/reallocate')
    try:
        req = urllib.request.Request(
            url, data=b'', method='POST',
            headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                     'User-Agent': 'remlab-mesh/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        print(f'  нода {iid[:8]}: пересажена ({why})', flush=True)
        return True
    except Exception as e:  # noqa: BLE001 — пересадка не должна ронять прогон
        print(f'  нода {iid[:8]}: пересадка не удалась ({type(e).__name__}: {str(e)[:80]})',
              flush=True)
        return False


def snapshot() -> dict:
    with _State() as st:
        return json.loads(json.dumps(st))


if __name__ == '__main__':
    print(json.dumps(snapshot(), ensure_ascii=False, indent=1))
