#!/usr/bin/env python3
"""НАБОР SALAD — ДРАЙВЕР ПЛАТНЫХ ПРОБ (T-20261121-178/2). Всё, что уроки пула мешей и проб Salad (724, 734, 737, 740, 748, 754, 755…) требуют от драйвера, — в ОДНОМ месте.
Новая проба пишет только функцию модели (`Spec`: тело группы, что послать, как проверить результат); охрана денег, ожидание образа, сторожа и гашение — отсюда.

ЧТО ДАЁТ (урок → функция):
  • 755 «создано = 201 + группа видна», повтор 502/503/504 ................ `api_retry`, `create_and_start` (старт на большой образ → HTTP 400 → ждём бесплатно до `wait_s`, e022e305)
  • ADR-0137 образ только по digest + сжатый размер ≤ 30 ГиБ до /start .... `check_image` (манифест реестра, бесплатно)
  • 737 деньги по ЖИВОЙ цене, потолок пробы и общий ......................... `gpu_class`, `cost_usd`, `Watch` (`money`/`probe_cap`)
  • 724/754 «running, started=false, 503»: ждать started, не running ........ `Watch` (`no_start` от running, `no_health` от started)
  • 734/740 докачка весов стоит .............................................. `weights_slow`/`weights_stalled` (`download_stalled`)
  • 748/755 молчащая платная нода .............................................. журнал раз в минуту (`say`), `not_ready`, `time`, `no_machine`
  • 578/700 стоп с проверкой «0 нод», в `finally` ................................ `stop_and_verify`
  • правило р.5 («--no-slot») платное только под `heavy-slot --prio 2` ....... `require_slot`
  • расход каждой пробы — строка в общий учёт ............................... `ledger_append` (`SALAD_PROBE_LEDGER`)
Сторож набора: `tests_kit.py` — каждый драйвер проб в tools/scout обязан импортировать этот модуль, каждый воркер — идти через `kit_worker` (или свой сокет `::`).
"""
from __future__ import annotations

import base64  # noqa: F401 — модели удобно иметь под рукой
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

UA = 'remlab-mesh/1.0'                  # без User-Agent API Salad и Cloudflare отвечают 403 (урок 748)
MAX_IMAGE_GIB = 30.0                    # сжатый размер образа: больше — Salad держит pending слишком долго (р.5: 22 ГиБ ≈ 25 мин; ADR-0137)
DIGEST_RE = re.compile(r'^[A-Za-z0-9._\-/:]+@sha256:[0-9a-f]{64}$')
DEFAULT_API_RULES = {'retries': 4, 'status_codes': [502, 503, 504], 'pauses_s': [5, 15, 30, 60]}
SLOT_PRIO = 2                           # платные пробы — heavy-slot --prio 2 (P-038)
SAFE_PREFIXES = ('mesh-', 'render-', 'trial-')       # чужие боевые группы не трогаем и не считаем «посторонними»


def say(*a) -> None:
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ---------------------------------------------------------------- деньги
def cost_usd(running_s: float, price: float, reserve_s: float = 60.0) -> float:
    """Начисления по времени `running` + запас на отставание счёта (платим с момента running)."""
    return max(0.0, running_s + (reserve_s if running_s > 0 else 0.0)) / 3600.0 * price


def effective_cap(first_done: bool, probe_cap: float, cap: float) -> float:
    """До первого готового задания действует потолок пробы, после — общий."""
    return cap if first_done else min(probe_cap, cap)


def _get_json(url: str, headers: dict | None = None, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={'User-Agent': UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def gpu_class(MG, name: str, tier: str, fetch: Callable[[str, dict], dict] | None = None) -> tuple[str | None, float | None]:
    """Класс карты по имени → (id, ЖИВАЯ цена $/ч на тарифе). Снимок цен в rules/ устаревает (19.11: 4090 high $0,44 против $0,33). Нет класса/ответа — (None, None)."""
    try:
        url = MG.API.split('/projects/')[0] + '/gpu-classes'
        d = (fetch or (lambda u, h: _get_json(u, h)))(url, {'Salad-Api-Key': os.environ['SALAD_API_KEY']})
        for c in d.get('items') or []:
            if c.get('name') == name and c.get('id'):
                price = None
                for x in c.get('prices') or []:
                    if str(x.get('priority')).lower() == tier:
                        price = float(x['price'])
                return c['id'], price
    except Exception:  # noqa: BLE001 — нет сети/ключа/формата: класс не найден, группу не создаём
        pass
    return None, None


# ---------------------------------------------------------------- образ: digest и размер из манифеста
class ImageRefused(RuntimeError):
    pass


def split_image(image: str) -> tuple[str, str, str]:
    """`ghcr.io/owner/name@sha256:…` → (реестр, репозиторий, ссылка). Не digest — ImageRefused (ADR-0137: тег может уехать, образ по тегу не воспроизводится)."""
    if not DIGEST_RE.match(image or ''):
        raise ImageRefused(f'образ «{image}» не по digest (нужно имя@sha256:<64 hex>; ADR-0137)')
    name, _, digest = image.partition('@')
    first, _, rest = name.partition('/')
    if '.' in first or ':' in first:
        host, repo = first, rest
    else:
        host, repo = 'docker.io', name
    repo = repo.split(':')[0] if '@' not in repo else repo
    return host, repo, digest


def manifest_bytes(get: Callable[[str, dict], dict], repo: str, ref: str, arch: str = 'amd64') -> int:
    """Сжатый размер образа по манифесту: config + слои. Индекс (мультиархитектура) → берём linux/<arch>. `get(путь, заголовки)` → JSON (подставляется в тестах)."""
    accept = ', '.join(['application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json',
                        'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'])
    m = get(f'/v2/{repo}/manifests/{ref}', {'Accept': accept})
    if m.get('manifests'):
        pick = next((x for x in m['manifests'] if (x.get('platform') or {}).get('os') == 'linux' and (x.get('platform') or {}).get('architecture') == arch), None)
        if pick is None:
            raise ImageRefused(f'в индексе образа нет linux/{arch}')
        m = get(f'/v2/{repo}/manifests/{pick["digest"]}', {'Accept': accept})
    layers = m.get('layers') or []
    if not layers:
        raise ImageRefused('манифест без слоёв — размер не определить')
    return int((m.get('config') or {}).get('size') or 0) + sum(int(x.get('size') or 0) for x in layers)


def registry_getter(host: str, repo: str, auth: dict | None) -> Callable[[str, dict], dict]:
    """Читатель манифестов реестра (бесплатно): токен по Basic из `registry_authentication` группы (для ghcr.io — /token), дальше Bearer."""
    basic = (auth or {}).get('basic') or {}
    state = {'tok': None}

    def token() -> str | None:
        if host != 'ghcr.io':
            return None
        hdr = {}
        if basic.get('username'):
            hdr['Authorization'] = 'Basic ' + base64.b64encode(f'{basic["username"]}:{basic["password"]}'.encode()).decode()
        return _get_json(f'https://ghcr.io/token?service=ghcr.io&scope=repository:{repo}:pull', hdr).get('token')

    def get(path: str, headers: dict) -> dict:
        if state['tok'] is None:
            state['tok'] = token() or ''
        h = dict(headers)
        if state['tok']:
            h['Authorization'] = f'Bearer {state["tok"]}'
        return _get_json(f'https://{host}{path}', h)
    return get


def check_image(image: str, auth: dict | None = None, max_gib: float = MAX_IMAGE_GIB, getter: Callable | None = None) -> tuple[bool, str, float | None]:
    """ДО /start: образ по digest и сжатый размер ≤ max_gib. Возвращает (годится, пояснение, ГиБ). Не смогли прочитать манифест — НЕ годится (платное без проверки не запускаем)."""
    try:
        host, repo, ref = split_image(image)
        n = manifest_bytes(getter or registry_getter(host, repo, auth), repo, ref)
    except ImageRefused as exc:
        return False, str(exc), None
    except Exception as exc:  # noqa: BLE001
        return False, f'манифест образа не прочитан ({type(exc).__name__}: {str(exc)[:100]}) — без проверки размера не запускаю', None
    gib = n / 2 ** 30
    if gib > max_gib:
        return False, f'сжатый образ {gib:.1f} ГиБ больше {max_gib:.0f} ГиБ — Salad будет держать pending слишком долго; сперва вынести веса/слои', round(gib, 2)
    return True, f'образ по digest, сжатый {gib:.2f} ГиБ (≤ {max_gib:.0f})', round(gib, 2)


# ---------------------------------------------------------------- платное только под heavy-slot --prio 2
class SlotRefused(RuntimeError):
    pass


def require_slot(prio: int = SLOT_PRIO, env=None, proc_root: str = '/proc') -> None:
    """Платная проба идёт ТОЛЬКО под `heavy-slot --prio 2` (P-038; урок р.5 с `--no-slot`). heavy-slot кладёт в окружение ребёнка `HEAVY_SLOT_HELD=<pid>`; по
    pid читаем командную строку держателя и сверяем `--prio`. Нет слота, `HEAVY_SLOT_NOSLOT` или другой приоритет — SlotRefused (деньги не тратим)."""
    env = os.environ if env is None else env
    if env.get('HEAVY_SLOT_NOSLOT'):
        raise SlotRefused('heavy-slot запущен с --no-slot (мимо очереди) — платное так не запускаем')
    pid = (env.get('HEAVY_SLOT_HELD') or '').strip()
    if not pid.isdigit():
        raise SlotRefused('нет heavy-slot (HEAVY_SLOT_HELD пуст): запускать `heavy-slot.sh <метка> --prio 2 -- …`')
    try:
        cmd = open(f'{proc_root}/{pid}/cmdline', 'rb').read().split(b'\0')
    except OSError:
        raise SlotRefused(f'держатель слота pid {pid} не найден — окружение чужое')
    args = [c.decode('utf-8', 'replace') for c in cmd]
    got = None
    for i, c in enumerate(args):
        if c == '--prio' and i + 1 < len(args):
            got = args[i + 1]
        elif c.startswith('--prio='):
            got = c.split('=', 1)[1]
    if got is None or not got.isdigit() or int(got) != prio:
        raise SlotRefused(f'heavy-slot с приоритетом {got!r}, нужен --prio {prio}')


# ---------------------------------------------------------------- Salad API
def api_retry(MG, path: str, method: str, body, name: str, say_fn=say, sleep=time.sleep, rules: dict | None = None):
    """Запрос к API групп с повтором при 502/503/504. Перед повтором смотрим группу: создание — группа уже есть (200) → считаем созданной; старт — состояние не «stopped» → уже стартовала.
    Возвращает (код, ответ, число_повторов). `rules` — {'retries','status_codes','pauses_s'}."""
    r = rules or DEFAULT_API_RULES
    pauses = r['pauses_s']
    call = (lambda: MG.api(path, method, body)) if body is not None else (lambda: MG.api(path, method))
    code, resp = call()
    for attempt in range(r['retries']):
        if code not in r['status_codes']:
            return code, resp, attempt
        sleep(float(pauses[min(attempt, len(pauses) - 1)]))
        c2, g = MG.api(f'/{name}')
        state = ((g or {}).get('current_state') or {}).get('status') if c2 == 200 else None
        if c2 == 200 and (method == 'POST' and path == '' or state not in (None, 'stopped')):
            say_fn(f'{method} {path or "создание"}: ответ {code}, но группа уже есть (состояние {state}) — считаю выполненным')
            return 201 if path == '' else 202, resp, attempt + 1
        say_fn(f'{method} {path or "создание"}: краткий сбой Salad API {code} — повтор {attempt + 1}/{r["retries"]}')
        code, resp = call()
    return code, resp, r['retries']


def create_and_start(MG, BR, name: str, body: dict, say_fn=say, sleep=time.sleep, clock=time.time, wait_s: float = 2400, rules: dict | None = None) -> tuple[bool, float, str]:
    """Создать группу (201 + видна в списке), ЖДАТЬ образ бесплатно (состояние stopped), стартовать. `/start` раньше времени на большой образ — HTTP 400 (р.5 e022e305; образ 22 ГиБ ≈ 25 мин):
    повторяем до `wait_s`, пока не 202. Возвращает (ок, время /start, причина отказа)."""
    code, resp, _ = api_retry(MG, '', 'POST', body, name, say_fn, sleep, rules)
    say_fn('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        return False, 0.0, f'create_http_{code}'
    t_wait = clock()
    seen = False
    while clock() - t_wait < wait_s:
        c, g = MG.api(f'/{name}')
        if c == 200:
            seen = True
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
        sleep(5)
    else:
        return False, 0.0, 'create_wait_timeout' if seen else 'group_not_listed'
    t_start = clock()
    while True:
        code, resp, _ = api_retry(MG, f'/{name}/start', 'POST', None, name, say_fn, sleep, rules)
        if code < 300:
            say_fn('start HTTP', code)
            return True, t_start, ''
        if code == 400 and clock() - t_wait < wait_s:
            say_fn('start HTTP 400 — образ ещё готовится (бесплатно), жду 30 с')
            sleep(30)
            continue
        say_fn('start HTTP', code, str(resp)[:200])
        return False, t_start, f'start_http_{code}'


def stop_and_verify(BR, name: str) -> bool:
    """Остановить группу и убедиться, что нод 0 (урок 578: pending = кэш образа, /stop не нужен, но 0 нод проверяем всегда)."""
    return bool(BR.stop_and_verify(name))


class Gateway:
    """HTTP к ноде через шлюз группы (`https://<dns>`) с ключом Salad; без падения на сетевых сбоях (код -1)."""

    def __init__(self, base: str, key: str):
        self.base, self.key = base.rstrip('/'), key

    def call(self, method: str, path: str, body: dict | None = None, timeout: int = 60, raw: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        h = {'Salad-Api-Key': self.key, 'User-Agent': UA}
        if data is not None:
            h['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return r.status, (b if raw else (json.loads(b) if b else {}))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return -1, {}


def head(url: str, token: str = '') -> int:
    h = {'User-Agent': UA}
    if token:
        h['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, method='HEAD', headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return -1


def probes(port: int, path: str = '/health') -> tuple[dict, dict]:
    """Пробы готовности и старта на `/health` (200, пока процесс жив; в теле — фаза и ход докачки). API Salad: failure_threshold ≤ 20 (иначе HTTP 400, урок 724)."""
    http = {'path': path, 'port': port, 'scheme': 'http', 'headers': []}
    return ({'http': http, 'initial_delay_seconds': 30, 'period_seconds': 10, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 3},
            {'http': http, 'initial_delay_seconds': 10, 'period_seconds': 60, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 20})


def group_body(name: str, image: str, tier: str, class_id: str, port: int, env: dict, resources: dict, auth: dict, command: list | None = None) -> dict:
    """Тело временной группы пробы: 1 нода, без автостарта и перезапуска, шлюз с ключом, пробы на /health. Модель задаёт только `env`, `resources`, `command`."""
    readiness, startup = probes(port)
    container = {'image': image, **({'command': command} if command else {}),
                 'resources': {**resources, 'gpu_classes': [class_id]}, 'priority': tier, 'environment_variables': env, 'image_caching': True,
                 'registry_authentication': auth}
    return {'name': name, 'display_name': name, 'container': container, 'autostart_policy': False, 'restart_policy': 'never', 'replicas': 1, 'priority': tier,
            'country_codes': [],
            'networking': {'protocol': 'http', 'port': port, 'auth': True, 'load_balancer': 'round_robin', 'single_connection_limit': False,
                           'client_request_timeout': 100000, 'server_response_timeout': 100000},
            'readiness_probe': readiness, 'startup_probe': startup}


def safe_print(body: dict, z_keys: tuple = ()) -> None:
    """Тело группы в печать без секретов (TOKEN/KEY/SECRET/PASS) и без кода воркера (только длина)."""
    b = json.loads(json.dumps(body))
    b['container'].pop('registry_authentication', None)
    env = b['container'].get('environment_variables', {})
    for k in list(env):
        if k in z_keys or k.endswith('_Z'):
            env[k] = f'<код воркера, {len(env[k])} знаков>'
        elif any(s in k for s in ('TOKEN', 'KEY', 'SECRET', 'PASS')):
            env[k] = '<скрыто>'
    print(json.dumps(b, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- докачка весов
def weights_slow(hist: list, window_s: float, min_gb_min: float) -> float | None:
    """Скорость докачки весов за последние window_s секунд, если она ниже min_gb_min ГБ/мин (иначе None). hist — [(время_с, ГБ)] по возрастанию; нужна выборка, покрывающая всё окно."""
    if len(hist) < 2:
        return None
    t1, g1 = hist[-1]
    old = [(t, g) for t, g in hist if t <= t1 - window_s]
    if not old:
        return None                                             # окно ещё не набралось
    t0, g0 = old[-1]
    rate = (g1 - g0) / ((t1 - t0) / 60)
    return rate if rate < min_gb_min else None


def weights_stalled(hist: list[tuple[float, float]], window_s: float, min_gb: float) -> bool:
    """Докачка стоит: за последние `window_s` секунд папка выросла меньше чем на `min_gb` ГБ. То же, что `weights_slow` с порогом min_gb за окно."""
    return weights_slow(hist, window_s, min_gb * 60.0 / window_s) is not None


# ---------------------------------------------------------------- сторож пробы (чистое решение, тестируется без сети)
@dataclass
class Watch:
    """Сторож платной ноды. Ничего не делает сам: на каждом шаге получает время, экземпляры Salad, ответ /health и цену — возвращает причину стопа или None.
    Исходы: probe_cap, money, time, no_machine, no_start, no_health, download_stalled, warm_failed, not_ready (+ done/fail_streak/first_failed ставит драйвер)."""
    t_start: float
    price: float
    probe_cap: float
    cap: float
    max_min: float = 120
    running_min: float = 30
    start_min: float = 20
    health_min: float = 8
    ready_min: float = 30
    stall_min: float = 5
    stall_gb: float = 0.05
    run_since: float | None = None
    started_since: float | None = None
    ready_at: float | None = None
    ever_ok: bool = False
    first_done: bool = False
    gb_hist: list = field(default_factory=list)
    events: list = field(default_factory=list)       # (ключ, значение) для итога: to_first_running_s, to_container_started_s, to_ready_s, weights_gb…

    def running_s(self, t: float) -> float:
        return (t - self.run_since) if self.run_since is not None else 0.0

    def cost(self, t: float) -> float:
        return cost_usd(self.running_s(t), self.price)

    def cap_now(self) -> float:
        return effective_cap(self.first_done, self.probe_cap, self.cap)

    def money_time(self, t: float, ins: list) -> tuple[str | None, str]:
        """Деньги/время/нет машины. Отмечает первый running и started."""
        if self.run_since is None and any(i.get('state') == 'running' for i in ins):
            self.run_since = t
            self.events.append(('to_first_running_s', round(t - self.t_start, 1), f'первый running: t+{t - self.t_start:.0f} с от /start'))
        if self.run_since is not None and self.started_since is None and any(i.get('started') for i in ins):
            self.started_since = t
            self.events.append(('to_container_started_s', round(t - self.run_since, 1), f'контейнер запущен: через {t - self.run_since:.0f} с после running'))
        if self.cost(t) >= self.cap_now():
            return ('money' if self.first_done else 'probe_cap'), f'≈${self.cost(t):.3f}, потолок ${self.cap_now()}'
        if self.run_since is not None and self.running_s(t) > self.max_min * 60:
            return 'time', f'{self.max_min} мин с running'
        if self.run_since is None and (t - self.t_start) > self.running_min * 60:
            return 'no_machine', f'{self.running_min} мин нода не выдана'
        return None, ''

    def health(self, t: float, ins: list, code: int | None, body: dict | None) -> tuple[str | None, str]:
        """Шаг по ответу /health (code None — не спрашивали). Порядок как у проверенных пробок: докачка → сломан → готов → no_start → no_health → not_ready."""
        h = body if isinstance(body, dict) else {}
        if code == 200:
            self.ever_ok = True
            if h.get('phase') == 'weights' and h.get('root_gb') is not None:
                self.gb_hist.append((t, float(h['root_gb'])))
                self.events.append(('weights_gb', h['root_gb'], ''))
                if weights_stalled(self.gb_hist, self.stall_min * 60, self.stall_gb):
                    return 'download_stalled', f'докачка весов не растёт {self.stall_min} мин (папка {h["root_gb"]} ГБ)'
            if h.get('phase') == 'broken' or h.get('error'):
                self.events.append(('warm_error', h.get('error'), ''))
                return 'warm_failed', f'воркер сломан: {h.get("error")} (фаза {h.get("phase")})'
            if h.get('phase') == 'ready' and self.ready_at is None:
                self.ready_at = t
                self.events.append(('to_ready_s', round(t - self.t_start, 1), f'нода готова: t+{t - self.t_start:.0f} с от /start'))
                return None, 'ready'
        if self.run_since is not None and not self.ever_ok and self.started_since is None and self.running_s(t) > self.start_min * 60:
            return 'no_start', f'{self.start_min} мин после running контейнер так и не запустился (started=False)'
        if self.started_since is not None and not self.ever_ok and t - self.started_since > self.health_min * 60:
            return 'no_health', f'{self.health_min} мин после запуска контейнера воркер не отвечает'
        if self.run_since is not None and self.ready_at is None and self.running_s(t) > self.ready_min * 60:
            return 'not_ready', f'{self.ready_min} мин после running модель не прогрелась'
        return None, ''


# ---------------------------------------------------------------- общий учёт денег проб
def ledger_path() -> str:
    return os.environ.get('SALAD_PROBE_LEDGER') or os.path.expanduser('~/scout-scenes/salad-probe-spend.jsonl')


def ledger_append(rec: dict, path: str | None = None) -> str | None:
    """ОДНА строка на пробу в общий учёт (как у мешей `pool_ledger`/`money_guard`: чтобы пробы не жили вне счёта). Ошибку записи не глотаем молча — возвращаем текст."""
    p = path or ledger_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **rec}, ensure_ascii=False, default=str) + '\n')
        return None
    except OSError as exc:
        return f'учёт не записан: {exc}'


def ledger_total(since: str = '', path: str | None = None) -> float:
    """Сумма `cost_usd_est` по учёту проб (с метки `since` вида 2026-11-21, включительно)."""
    p = path or ledger_path()
    total = 0.0
    try:
        for line in open(p, encoding='utf-8'):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if str(r.get('ts', '')) >= since:
                total += float(r.get('cost_usd_est') or 0)
    except OSError:
        pass
    return round(total, 4)


def ledger_window(seconds: float = 86400, path: str | None = None, now: float | None = None) -> tuple[int, float]:
    """(число проб, сумма `cost_usd_est`) за последние `seconds` секунд — для общего отчёта денег (`money_guard.heartbeat`)."""
    p = path or ledger_path()
    since = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime((now if now is not None else time.time()) - seconds))
    n, total = 0, 0.0
    try:
        for line in open(p, encoding='utf-8'):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if str(r.get('ts', '')) >= since:
                n += 1
                total += float(r.get('cost_usd_est') or 0)
    except OSError:
        pass
    return n, round(total, 2)


def ledger_line(seconds: float = 86400, path: str | None = None, now: float | None = None) -> str:
    """Одна строка для отчёта: «пробы Salad за сутки: N, ≈$X» (счёт проб отдельный, итог читает общий отчёт)."""
    n, usd = ledger_window(seconds, path, now)
    return f'пробы Salad за сутки: {n} шт ≈ ${usd:.2f}'


# ---------------------------------------------------------------- общий цикл пробы
@dataclass
class Spec:
    """Что знает о пробе только модель. Всё остальное делает `run_probe`."""
    prefix: str                                                    # имя группы: <prefix>-<метка>
    card: str                                                      # «RTX 5090 (32 GB)»
    model: str                                                     # для учёта денег
    jobs: list[str]
    build_body: Callable[[str, str, dict], dict]                   # (имя, class_id, auth) → тело группы
    submit: Callable[[Gateway, str, float], tuple[dict | None, dict]]    # (шлюз, ключ, t) → (cur с 'key','id','t0' или None, пояснение отказа)
    poll: Callable[[Gateway, dict, float], tuple[str, dict]]       # (шлюз, cur, t) → ('running'|'done'|'failed', запись о задании)
    preflight: Callable[[], tuple[bool, str]] | None = None        # бесплатные проверки до создания группы (допуск к весам, входные файлы)
    health_keys: tuple = ('phase', 'root_gb', 'weights', 'cuda', 'error')
    ready_keys: tuple = ('version',)
    z_keys: tuple = ()


def run_probe(a, MG, BR, spec: Spec, gw_factory=Gateway, sleep=time.sleep, clock=time.time, slot_check=require_slot,
              image_check=check_image, ledger=ledger_append, wait_s: float = 2400) -> int:
    """Платная проба на Salad по общему образцу. `a`: image, suffix, tier, apply, cap, probe_cap, max_min, running_min, start_min, health_min, ready_min, stall_min, stall_gb,
    job_min, out. Без `--apply` — только разбор (тело без секретов, группа НЕ создаётся)."""
    name = f'{spec.prefix}-{a.suffix}'
    MG.env_from_file()
    class_id, price = gpu_class(MG, spec.card, a.tier)
    if class_id is None:
        say(f'класс карты «{spec.card}» не найден у Salad — стоп, денег не потрачено')
        return 3
    body = spec.build_body(name, class_id, MG.ghcr_auth())
    say('группа', name, spec.card, 'тариф', a.tier, 'цена $/ч', price, 'задания', spec.jobs, f'потолок пробы ${a.probe_cap}, общий ${a.cap}')
    if not a.apply:
        safe_print(body, spec.z_keys)
        ok, why, _g = image_check(a.image, MG.ghcr_auth())
        say('образ:', why if ok else f'НЕ ГОДИТСЯ — {why}')
        return 0
    try:
        slot_check()
    except SlotRefused as exc:
        say(f'ОТКАЗ: {exc}')
        return 4
    if price is None:
        say('цены класса нет — стоп (деньги без цены не считаем)')
        return 2
    ok, why, image_gib = image_check(a.image, MG.ghcr_auth())
    say('образ:', why)
    if not ok:
        return 3
    if spec.preflight:
        ok, why = spec.preflight()
        say('проверки до создания (бесплатно):', why)
        if not ok:
            say('группу НЕ создаю, денег не потрачено')
            return 3
    code, d = MG.api('')
    live = [g['name'] for g in d.get('items', []) if (g.get('current_state') or {}).get('status') not in ('stopped', 'failed', None) and not g['name'].startswith(SAFE_PREFIXES)]
    if live:
        say(f'живые чужие группы {live} — стоп')
        return 2
    code, g = MG.api(f'/{name}')
    if code == 200:
        say(f'группа {name} уже есть — не пересоздаю молча (другая --suffix)')
        return 2
    os.makedirs(a.out, exist_ok=True)
    summary = {'group': name, 'image': a.image, 'image_gib': image_gib, 'tier': a.tier, 'price_usd_h': price, 'cap_usd': a.cap, 'probe_cap_usd': a.probe_cap,
               'jobs': {}, 'failed': 0, 'stop_verified': False, 'stopped_by': None}
    ok_create, t_start, refuse = create_and_start(MG, BR, name, body, say, sleep, clock, wait_s)
    if not ok_create:
        summary['stopped_by'] = refuse
        ok_stop = stop_and_verify(BR, name) if refuse.startswith(('start_http', 'create_wait')) else True
        summary['stop_verified'] = ok_stop
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1, default=str)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified')}, ensure_ascii=False))
        return 1
    w = Watch(t_start, price, a.probe_cap, a.cap, a.max_min, a.running_min, a.start_min, a.health_min, a.ready_min, a.stall_min, a.stall_gb)
    gw = None
    streak = 0
    pending = list(spec.jobs)
    cur = None
    last_say = 0.0
    last_ins: list = []
    last_h: tuple = (None, {})
    seen_ev = 0
    try:
        while True:
            t = clock()
            _, st, _cnt = BR.group_state(name)
            _, ins = BR.instances(name)
            last_ins = ins
            why, detail = w.money_time(t, ins)
            summary['cost_usd_est'] = round(w.cost(t), 3)
            if why:
                say(f'!! стоп по причине «{why}» ({detail}) — гашу')
                summary['stopped_by'] = why
                break
            if t - last_say >= 60:
                last_say = t
                i0 = ins[0] if ins else {}
                hc, hb = last_h
                hs = {k: hb.get(k) for k in spec.health_keys if isinstance(hb, dict) and k in hb}
                say(f'мин: группа {st} · экземпляр {i0.get("state")} started={i0.get("started")} ready={i0.get("ready")} · ≈${summary["cost_usd_est"]:.2f} из ${w.cap_now()} · /health {hc} {json.dumps(hs, ensure_ascii=False)[:300]}')
            if w.run_since is not None and gw is None:
                dns = ((MG.api(f'/{name}')[1].get('networking') or {}).get('dns') or '')
                if dns:
                    gw = gw_factory(f'https://{dns}', os.environ['SALAD_API_KEY'])
                    summary['gateway'] = dns
                    say('шлюз группы получен')
            if gw is not None and w.ready_at is None:
                c, h = gw.call('GET', '/health', timeout=20)
                last_h = (c, h)
                why, detail = w.health(t, ins, c, h)
                if why:
                    say(f'!! {detail} — гашу')
                    summary['stopped_by'] = why
                    break
                if w.ready_at is not None:
                    summary['health'] = {k: h.get(k) for k in spec.ready_keys + ('offload', 'sparse') if k in h}
                    say(f'нода готова: t+{t - t_start:.0f} с от /start', summary['health'])
            elif gw is None or w.ready_at is None:
                why, detail = w.health(t, ins, None, None)
                if why:
                    say(f'!! {detail} — гашу')
                    summary['stopped_by'] = why
                    break
            for k, v, msg in w.events[seen_ev:]:
                summary[k] = v
                if msg and msg != 'ready':
                    say(msg)
            seen_ev = len(w.events)
            if w.ready_at is not None:
                if cur is None and pending:
                    k = pending.pop(0)
                    cur, info = spec.submit(gw, k, t)
                    if cur is None:
                        streak += 1
                        summary['jobs'][k] = {'status': 'not_accepted', **info}
                        say(f'задание {k}: не принято', str(info)[:160])
                elif cur is not None:
                    status, info = spec.poll(gw, cur, t)
                    if status == 'running' and t - cur['t0'] > a.job_min * 60:
                        status, info = 'failed', {'status': 'timeout'}
                        say(f'задание {cur["key"]}: дольше {a.job_min} мин — снимаю')
                    if status == 'done':
                        summary['jobs'][cur['key']] = {'status': 'done', 'wall_s': round(t - cur['t0'], 1), **info}
                        say(f'задание {cur["key"]}: ГОТОВО за {t - cur["t0"]:.0f} с', json.dumps(info.get('metrics') or {}, ensure_ascii=False)[:400])
                        w.first_done = True
                        streak = 0
                        cur = None
                    elif status == 'failed':
                        streak += 1
                        summary['jobs'][cur['key']] = {'status': info.get('status', 'failed'), **{k: v for k, v in info.items() if k != 'status'}}
                        if info.get('status') != 'timeout':
                            say(f'задание {cur["key"]}: ОШИБКА', info.get('error') or info.get('status'))
                        cur = None
                summary['failed'] = sum(1 for v in summary['jobs'].values() if v.get('status') != 'done')
                if streak >= 2:
                    summary['stopped_by'] = 'fail_streak'
                    say('!! 2 задания подряд не удались — гашу (чинить в коде)')
                    break
                if cur is None and not pending:
                    summary['stopped_by'] = 'done' if w.first_done and summary['failed'] == 0 else ('first_failed' if not w.first_done else 'done_with_failures')
                    break
            sleep(10)
    finally:
        summary['stop_verified'] = stop_and_verify(BR, name)
        summary['last_instances'] = last_ins
        summary['last_health'] = {'http': last_h[0], 'body': {k: v for k, v in (last_h[1] or {}).items() if k != 'weights'} if isinstance(last_h[1], dict) else None}
        summary['running_s'] = round((clock() - w.run_since), 1) if w.run_since is not None else 0.0
        summary['cost_usd_est'] = round(cost_usd(summary['running_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1, default=str)
        warn = ledger({'group': name, 'model': spec.model, 'card': spec.card, 'tier': a.tier, 'image': a.image, 'running_s': summary['running_s'], 'price_usd_h': price,
                       'cost_usd_est': summary['cost_usd_est'], 'stopped_by': summary['stopped_by'], 'stop_verified': summary['stop_verified'],
                       'jobs_done': sum(1 for v in summary['jobs'].values() if v.get('status') == 'done'), 'jobs_failed': summary['failed'], 'driver': 'kit_driver'})
        if warn:
            say('!!', warn)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'failed', 'running_s', 'cost_usd_est')}, ensure_ascii=False))
    return 0 if summary['stop_verified'] and summary['stopped_by'] == 'done' else 1
