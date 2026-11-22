#!/usr/bin/env python3
"""НАБОР SALAD — ДРАЙВЕР ПЛАТНЫХ ПРОБ (T-20261121-178/2). Всё, что уроки пула мешей и проб Salad (724, 734, 737, 740, 748, 754, 755…) требуют от драйвера, — в ОДНОМ месте.
Новая проба пишет только функцию модели (`Spec`: тело группы, что послать, как проверить результат); охрана денег, ожидание образа, сторожа и гашение — отсюда.

ЧТО ДАЁТ (урок → функция):
  • 755 «создано = 201 + группа видна», повтор 502/503/504 ................ `api_retry`, `create_and_start` (старт на большой образ → HTTP 400 → ждём бесплатно до `wait_s`, e022e305)
  • ADR-0137 образ только по digest + сжатый размер ≤ 35 ГиБ до /start .... `check_image` (манифест реестра, бесплатно)
  • 737 деньги по ЖИВОЙ цене, потолок пробы и общий ......................... `gpu_class`, `cost_usd`, `Watch` (`money`/`probe_cap`)
  • 724/754 «running, started=false, 503»: ждать started, не running ........ `Watch` (`no_start` от running, `no_health` от started)
  • 734/740 докачка весов стоит .............................................. `weights_slow`/`weights_stalled` (`download_stalled`)
  • 734/357 докачка ОБРАЗА медленная (прогноз >15 мин через 8) → пересадка ... `pull_verdict`, `PullGuard` (общий бюджет `node_health`, ≤3, обе медленные → ждём)
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
MAX_IMAGE_GIB = 35.0                    # сжатый размер образа: предел Salad 35 ГБ (https://docs.salad.com/container-engine/explanation/infrastructure-platform/container-registries, «может измениться») и канон ADR-0137 «веса вшиты, лимит 35»; 30 был строже канона без основания (21.11, решение директора). Медленную докачку большого образа ловит PullGuard (норма от размера)
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


# ---------------------------------------------------------------- сверка архитектуры CUDA образа с картой ДО группы (урок 742)
CARD_ARCH = (('RTX 50', '12.0'), ('RTX 40', '8.9'), ('RTX 30', '8.6'), ('RTX 20', '7.5'), ('GTX 16', '7.5'), ('A100', '8.0'), ('H100', '9.0'))


def card_arch(card: str) -> str | None:
    """Вычислительная архитектура карты по имени класса Salad («RTX 5090 (32 GB)» → '12.0'); незнакомая карта — None (не блокируем, а говорим)."""
    return next((arch for key, arch in CARD_ARCH if key in (card or '')), None)


def arch_refusal(card: str, image_archs) -> str:
    """'' — можно; иначе причина отказа ДО создания группы. `image_archs` — архитектуры, под которые собран образ (``('12.0',)``); пусто — модель не заявила, проверка не делается.
    Урок 742: образ под 8.9 на картах 8.6 и 12.0 — «no kernel image», ≈$0,05 впустую; здесь отказ до денег."""
    if not image_archs:
        return ''
    arch = card_arch(card)
    if arch is None:
        return ''
    if arch not in {str(x) for x in image_archs}:
        return f'образ собран под CUDA-архитектуры {sorted(map(str, image_archs))}, карта «{card}» — {arch}: «no kernel image» (урок 742); группу не создаю'
    return ''


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
    last_note = t_wait
    while clock() - t_wait < wait_s:
        c, g = MG.api(f'/{name}')
        st = None
        if c == 200:
            seen = True
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
        if clock() - last_note >= 60:                              # b2k 21.11: 8 мин тишины, пока Salad готовит образ в кэше (группа pending, $0) — строка раз в минуту, лог живой (п.12 рецепта)
            last_note = clock()
            say_fn(f'ждём образ в кэше Salad (бесплатно): группа {st or "не видна"}, {clock() - t_wait:.0f} с от создания, предел {wait_s:.0f} с')
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


def salad_rules(key: str) -> dict:
    """Раздел `key` из `rules/salad-groups.json` (числа сторожей — в правилах, не в коде); нет файла/раздела — пустой словарь, действуют умолчания в коде."""
    try:
        return json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rules', 'salad-groups.json'), encoding='utf-8')).get(key) or {}
    except (OSError, ValueError):
        return {}


def gateway_post_rules() -> dict:
    """Правила POST задания к шлюзу Salad: `gateway_post` {base_s, per_mb_s, max_s, retry_http}."""
    return salad_rules('gateway_post')


def post_timeout_s(body_chars: int, override: int = 0, rules: dict | None = None) -> int:
    """Таймаут POST задания по размеру тела: base_s + per_mb_s × МБ (base64), не больше max_s — из `gateway_post` (T-178 22.11: шлюз Salad отвечает 76–90+ с на холодной ноде,
    зашитые 90/120 с срывали первое задание). `override` > 0 — явное значение; нет правила — 90 + 30/МБ, ≤ 300."""
    if override and override > 0:
        return int(override)
    g = gateway_post_rules() if rules is None else rules
    base, per_mb, top = float(g.get('base_s', 90)), float(g.get('per_mb_s', 30)), float(g.get('max_s', 300))
    return int(min(top, base + per_mb * body_chars / 2 ** 20))


def post_job(gw, path: str, body: dict, check_path: str, override: int = 0, say_fn=say, rules: dict | None = None) -> tuple[int, dict, dict | None]:
    """ОДИН общий вход «отправить задание» для обоих драйверов (trellis_trial, salad_trial): POST с таймаутом по размеру тела. Нет ответа (код -1) или ошибка ШЛЮЗА
    (код из `gateway_post.retry_http`, по умолчанию 502/503/504 — HTML-страница шлюза, T-178 22.11) — это НЕ отказ воркера: спросить его `GET check_path` (его запись о задании).
    200 → задание принято (вернём 202); иначе вернём исходный код, а повтор — решает вызывающий (один раз, в конец очереди той же ноды; второй раз → «не принято» с кодом в причине).
    Возвращает (код, ответ, сведения или None); сведения (`job_id`, `code`, `timeout_s`, `worker_saw_job`) — для сводки; `worker_saw_job` False = повторять можно."""
    g = gateway_post_rules() if rules is None else rules
    retry_http = {int(x) for x in g.get('retry_http', [502, 503, 504])} | {-1}
    to = post_timeout_s(sum(len(v) for v in body.values() if isinstance(v, str)), override, g)
    c, r = gw.call('POST', path, body, timeout=to)
    if c not in retry_http:
        return c, r, None
    cj, _ = gw.call('GET', check_path, timeout=30)
    info = {'job_id': body.get('job_id'), 'code': c, 'timeout_s': to, 'worker_saw_job': cj == 200}
    if cj == 200:
        say_fn('задание', body.get('job_id'), f'→ POST: нет ответа/код {c} (таймаут {to} с), но воркер задание принял ({check_path} 200) — продолжаю')
        return 202, {}, info
    say_fn('задание', body.get('job_id'), f'→ POST: нет ответа/код {c} (таймаут {to} с), воркер задание не видит')
    return c, r, info


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


STARTUP_PERIOD_S = 10   # рецепт Hunyuan/TRELLIS.2 fast (урок 802): период стартовой пробы 10 с, не 60 — «контейнер запущен» виден за секунды (прогрев 1323 → 195 с). /health отвечает 200, пока процесс жив, поэтому частая проба не перезапускает прогрев


def probes(port: int, path: str = '/health') -> tuple[dict, dict]:
    """Пробы готовности и старта на `/health` (200, пока процесс жив; в теле — фаза и ход докачки). API Salad: failure_threshold ≤ 20 (иначе HTTP 400, урок 724)."""
    http = {'path': path, 'port': port, 'scheme': 'http', 'headers': []}
    return ({'http': http, 'initial_delay_seconds': 30, 'period_seconds': 10, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 3},
            {'http': http, 'initial_delay_seconds': 10, 'period_seconds': STARTUP_PERIOD_S, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 20})


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


# ---------------------------------------------------------------- сторож докачки ОБРАЗА (уроки 734/740/357; владелец 21.11, TG 1069/1070)
# Образ тянется ДО running и не оплачивается, но 21.11 (проба d2) нода «downloading» 30 мин, у соседней пробы было 6,7 мин: драйвер ждал только running и погас по no_machine.
# Здесь общее решение (чистая функция, тестируется без сети) и исполнитель: пересадка через ОБЩИЙ бюджет `node_health` (6/ч на пул мешей и пробы), не копия логики пула.
_PGR = salad_rules('pull_guard')                       # числа — `rules/salad-groups.json` → pull_guard (T-178 22.11: общий сторож и для TRELLIS.2, и для UltraTex)
PULL_AFTER_S = float(_PGR.get('after_s', 480.0))                      # судить не раньше 8-й минуты наблюдений (урок 734)
PULL_HEALTHY_MB_S = float(_PGR.get('healthy_mb_s', 17.5))             # здоровая нода: образ UltraTex 6,87 ГиБ за ≈6,7 мин (проба d1 21.11) ≈ 17,5 МБ/с ≈ 15 % образа в минуту
PULL_SLOW_FACTOR = float(_PGR.get('slow_factor', 2.5))                # ожидаемое время × 2,5 — нода медленная (владелец 21.11); ступени пула мешей (20 мин→5 % для образа 26 ГБ) для малого образа не годятся
PULL_FLOOR_MIN = float(_PGR.get('floor_min', 10.0))                   # не строже 10 минут полной докачки (разброс сети)
PULL_MIN_ETA_MIN = float(_PGR.get('min_eta_min', 3.0))                # осталось меньше — доедет, пересадка с нуля дороже
PULL_WINDOW_S = float(_PGR.get('window_s', 300.0))                    # темп — по последним 5 минутам, не по среднему с начала
PULL_MAX_CULLS = int(_PGR.get('max_culls', 3))                        # пересадок на запуск (общий бюджет node_health — отдельно)


STUCK_MIN = 10.0        # задание «зависло»: шаг не менялся и GPU < STUCK_GPU_PCT непрерывно дольше N мин (урок b1 21.11, P3-SAM: 15 мин молчания). Параметр `--stuck-min`; 0 — выключить
STUCK_GPU_PCT = 5.0


def progress_problems(text: str) -> list[str]:
    """Воркер платной пробы обязан отдавать живой ход задания (шаг, секунды шага, GPU %, последняя строка) в /health: `begin_job` + `step`/`on_step`/`note`.
    Без этого «считает или завис» не отличить (b1: 15 мин молчания). Пусто — хода нет в коде воркера."""
    out = []
    if 'begin_job(' not in text:
        out.append('воркер не открывает ход задания (`state.begin_job(id)`) — /health.job будет пуст')
    if not re.search(r'\.step\(|on_step|\.note\(|set_step\(', text):
        out.append('воркер не сообщает шаги (`state.step(имя)` / `engine.on_step = state.step`) — не видно, где задание')
    return out


def worker_progress_refusal(path: str) -> str:
    """'' — ход в коде воркера есть; иначе причина отказа (проверка ДО создания группы, деньги не тратятся). Нет файла — отказ."""
    try:
        text = open(path, encoding='utf-8').read()
    except OSError as exc:
        return f'код воркера не читается ({path}): {exc}'
    bad = progress_problems(text)
    return '; '.join(bad)


class JobStall:
    """Сторож зависшего задания по ходу из /health (`State.job_view`): шаг тот же и GPU < порога подряд дольше `stuck_min` → причина стопа. Время подаёт вызывающий."""

    def __init__(self, stuck_min: float = STUCK_MIN, gpu_pct: float = STUCK_GPU_PCT):
        self.stuck_s = stuck_min * 60
        self.gpu_pct = gpu_pct
        self.key: tuple | None = None
        self.since: float | None = None

    def step(self, t: float, jv: dict | None) -> str | None:
        if not self.stuck_s or not jv:
            self.key = self.since = None
            return None
        key = (jv.get('id'), jv.get('step'))
        util = jv.get('gpu_util')
        if key != self.key or util is None or util >= self.gpu_pct:
            self.key, self.since = key, (t if util is not None and util < self.gpu_pct else None)
            return None
        if self.since is None:
            self.since = t
        if t - self.since >= self.stuck_s:
            return (f'задание «{jv.get("id")}» зависло: шаг «{jv.get("step")}» не меняется, GPU {util:g} % уже {(t - self.since) / 60:.0f} мин '
                    f'(порог {self.stuck_s / 60:g} мин); последняя строка: {jv.get("line")}')
        return None


def pull_txt(inst: dict) -> str:
    """« 37%» — доля скачанного образа в минутной строке журнала (d2 21.11: «downloading» без процента — не видно, ползёт или стоит)."""
    p = inst.get('pulling_progress')
    return f' {float(p):.0%}' if inst.get('state') == 'downloading' and p is not None else ''


def max_total_for_image(image_gib: float | None, healthy_mb_s: float = PULL_HEALTHY_MB_S, factor: float = PULL_SLOW_FACTOR, floor_min: float = PULL_FLOOR_MIN) -> float:
    """Допустимое полное время докачки образа (мин) = ожидаемое при здоровой скорости × factor, не меньше floor_min. Размер неизвестен — 15 мин.
    Образ 6,87 ГиБ → 16,7 мин; образ 26 ГиБ (меши, ≈3 %/мин) → ≈63 мин."""
    if not image_gib:
        return 15.0
    return max(floor_min, factor * image_gib * 1024.0 / healthy_mb_s / 60.0)


def pull_verdict(obs: list, after_s: float = PULL_AFTER_S, max_total_min: float = 15.0, min_eta_min: float = PULL_MIN_ETA_MIN,
                 window_s: float = PULL_WINDOW_S) -> str | None:
    """Медленная ли докачка образа. obs — [(время_с, доля 0..1)] по возрастанию. max_total_min — из `max_total_for_image`. Причина пересадки или None.
    Догрузившую (≥0,999) не трогаем никогда (05.09: выбросить готовую ноду = заплатить за прогрев дважды)."""
    if len(obs) < 2:
        return None
    t1, p1 = obs[-1]
    if p1 >= 0.999:
        return None
    age = t1 - obs[0][0]
    if age < after_s:
        return None
    ta, pa = next(o for o in obs if t1 - o[0] <= window_s)
    if t1 - ta < 120.0:
        return None
    rate = (p1 - pa) / ((t1 - ta) / 60.0)                   # доля образа в минуту
    eta = (1.0 - p1) / rate if rate > 1e-6 else float('inf')
    if eta < min_eta_min:
        return None
    total = age / 60.0 + eta
    if total > max_total_min:
        eta_txt = 'не растёт' if eta == float('inf') else f'ещё {eta:.0f} мин'
        return f'образ {p1:.0%} за {age / 60:.0f} мин, темп {max(rate, 0):.1%}/мин ({eta_txt}) — прогноз докачки дольше {max_total_min:.0f} мин'
    return None


class PullGuard:
    """Исполнитель сторожа докачки образа. На каждом шаге получает экземпляры Salad (`pulling_progress`, `state`) и при медленной докачке пересаживает ноду.
    Режим ОДНОЙ ноды (у пробы одна реплика; `MIN_WORKING_TO_CULL` пула мешей сюда не применяется). Урок 357: исчерпаны все пересадки, а следующая нода тоже медленная —
    медленен образ или сеть, а не машина: `give_up` (драйвер гасит пробу, $0 — до running не списывается), по кругу не пересаживаем.
    `take_slot()` — общий бюджет пересадок (`node_health.take_cull_slot`), `realloc(group, iid, why)` — `node_health.reallocate`; оба подменяются в тестах."""

    def __init__(self, group: str, max_culls: int = PULL_MAX_CULLS, take_slot: Callable[[], int] | None = None, realloc: Callable[[str, str, str], bool] | None = None,
                 say_fn=say, **verdict_kw):
        self.group, self.max_culls, self.verdict_kw, self.say = group, max_culls, verdict_kw, say_fn
        self.take_slot, self.realloc = take_slot, realloc
        self.hist: dict = {}
        self.slow: set = set()
        self.culls = 0
        self.noted: set = set()
        self.give_up = ''                                        # причина, по которой пересадки закончились при всё ещё медленной ноде (стоп драйвера)

    def configure(self, image_gib: float | None) -> None:
        """Норма от размера образа и здоровой скорости; явный max_total_min (тесты, особый образ) не перекрывается."""
        self.verdict_kw.setdefault('max_total_min', max_total_for_image(image_gib))

    def _nh(self):
        if self.take_slot is None or self.realloc is None:
            import sys
            here = os.path.dirname(os.path.abspath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            import node_health as NH
            self.take_slot = self.take_slot or NH.take_cull_slot
            self.realloc = self.realloc or NH.reallocate

    def _note(self, key: str, msg: str) -> None:
        if key not in self.noted:
            self.noted.add(key)
            self.say(msg)

    def step(self, t: float, ins: list) -> bool:
        """True — ноду пересадили на этом шаге (драйвер сбрасывает отсчёт «нода не выдана»)."""
        for i in ins:
            iid, prog = i.get('id'), i.get('pulling_progress')
            if not iid or i.get('state') != 'downloading' or prog is None:
                continue
            obs = self.hist.setdefault(iid, [])
            if obs and float(prog) < obs[-1][1] - 0.10:         # откат >10 п.п. — загрузка началась заново
                obs.clear()
            obs.append((t, float(prog)))
            if len(obs) > 200:
                del obs[1:len(obs) - 150]                        # первое наблюдение держим (возраст), хвост — для темпа
            why = pull_verdict(obs, **self.verdict_kw)
            if not why:
                continue
            self.slow.add(iid)
            if self.culls >= self.max_culls:
                self.give_up = f'медленно качают все {len(self.slow)} ноды подряд (пересадок {self.culls}) — это образ или сеть, а не машина (урок 357): {why}'
                self._note('max', f'сторож докачки: {self.give_up} — останавливаю пробу')
                continue
            self._nh()
            if not self.take_slot():
                self._note('slot', f'сторож докачки: общий бюджет пересадок на час исчерпан — жду: {why}')
                continue
            self.say(f'сторож докачки: нода {iid[:8]} — {why} → пересаживаю (№{self.culls + 1} из {self.max_culls})')
            if self.realloc(self.group, iid, why):
                self.culls += 1
                self.hist.pop(iid, None)
                return True
        return False


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
    last_cull: float | None = None                   # пересадка ноды при медленной докачке образа: «нода не выдана» считаем заново от неё
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
        if self.run_since is None and (t - max(self.t_start, self.last_cull or 0.0)) > self.running_min * 60:
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
    worker_file: str = ''                                          # код воркера пробы: ОБЯЗАТЕЛЕН — до создания группы проверяем, что он отдаёт ход задания в /health (урок b1); пусто → отказ до группы (код 3)
    allow_no_worker_check: bool = False                            # пропуск проверки хода — ТОЛЬКО для тестов драйвера с поддельным воркером; в боевой пробе не ставить
    before_job: Callable[[str, float, float], str | None] | None = None   # (следующий ключ, деньги сейчас $, потолок сейчас $) → причина планового стопа или None: --max-meshes, файл-стоп,
                                                                           # «по средней длительности не успеет до потолка», первый провал (платное не шлём впустую); стоп = 'planned:<причина>', код 0
    cuda_archs: tuple = ()                                         # архитектуры CUDA образа ('12.0',): пусто — сверка с картой не делается (урок 742)


def run_probe(a, MG, BR, spec: Spec, gw_factory=Gateway, sleep=time.sleep, clock=time.time, slot_check=require_slot,
              image_check=check_image, ledger=ledger_append, wait_s: float = 2400, pull_guard: Callable[[str], PullGuard] | None = None) -> int:
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
    bad_arch = arch_refusal(spec.card, spec.cuda_archs)
    if bad_arch:
        say('ОТКАЗ:', bad_arch)
        say('группу НЕ создаю, денег не потрачено')
        return 3
    if not spec.worker_file and not spec.allow_no_worker_check:
        say('ОТКАЗ: у пробы не указан код воркера (`Spec.worker_file`) — без него не проверить, что воркер отдаёт ход задания (урок b1: 15 мин молчания). Укажи путь к файлу воркера')
        say('группу НЕ создаю, денег не потрачено')
        return 3
    if spec.worker_file:
        bad_prog = worker_progress_refusal(spec.worker_file)
        if bad_prog:
            say('ОТКАЗ: нет живого хода задания в воркере —', bad_prog)
            say('группу НЕ создаю, денег не потрачено')
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
    guard = (pull_guard or PullGuard)(name) if getattr(a, 'pull_guard', True) else None      # --no-pull-guard выключает (a.pull_guard=False)
    if guard is not None:
        guard.configure(image_gib)                                                           # норма докачки — от размера образа (ожидаемое × 2,5), не константы мешей
    gw = None
    streak = 0
    busy_waits = 0
    post_retried: set = set()                                          # ключи, которым уже сделан повтор после POST без ответа (повтор — один)
    last_job_look = 0.0
    stall = JobStall(getattr(a, 'stuck_min', STUCK_MIN))
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
            if guard is not None and w.run_since is None and guard.step(t, ins):       # образ качается слишком медленно → пересадка (бесплатно: до running не списывается)
                w.last_cull = t
                summary['pull_culls'] = guard.culls
            if guard is not None and guard.give_up and w.run_since is None:
                say(f'!! {guard.give_up} — гашу')
                summary['stopped_by'] = 'pull_slow'
                break
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
                say(f'мин: группа {st} · экземпляр {i0.get("state")}{pull_txt(i0)} started={i0.get("started")} ready={i0.get("ready")} · ≈${summary["cost_usd_est"]:.2f} из ${w.cap_now()} · /health {hc} {json.dumps(hs, ensure_ascii=False)[:300]}')
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
                if cur is None and pending and spec.before_job:
                    why_plan = spec.before_job(pending[0], w.cost(t), w.cap_now())
                    if why_plan:
                        say(f'новые задания не отправляю: {why_plan} — гашу')
                        summary['stopped_by'] = 'planned' if not str(why_plan).startswith('!') else str(why_plan)[1:]       # «!причина» — аварийный стоп (код 1), иначе плановый
                        summary['planned_reason'] = str(why_plan)
                        break
                if cur is None and pending:
                    k = pending.pop(0)
                    cur, info = spec.submit(gw, k, t)
                    if cur is None and info.get('http') == 429:
                        # «занят»: нода ещё считает прежнее задание (p4 21.11: Сакура получила 429 и сожгла серию провалов, пока комод считался) — не провал: ключ в начало очереди, ждём
                        pending.insert(0, k)
                        busy_waits += 1
                        if busy_waits in (1, 6) or busy_waits % 30 == 0:
                            say(f'задание {k}: нода занята (429) — жду, не провал (ожидание №{busy_waits})')
                    elif cur is None and (info.get('post') or {}).get('worker_saw_job') is False and k not in post_retried:
                        # POST без ответа/503 шлюза и воркер задание не видит (T-178 22.11): не провал — один повтор в конец очереди той же ноды
                        post_retried.add(k)
                        pending.append(k)
                        summary.setdefault('post_timeouts', []).append({'key': k, **(info.get('post') or {})})
                        say(f'задание {k}: POST без ответа — один повтор в конец очереди')
                    elif cur is None:
                        streak += 1
                        summary['jobs'][k] = {'status': 'not_accepted', **info}
                        say(f'задание {k}: не принято', str(info)[:160])
                elif cur is not None:
                    if t - last_job_look >= 60:                   # ход задания из /health воркера (kit_worker State.job): какой шаг, сколько идёт — видно, считает или завис
                        last_job_look = t
                        hc, hb = gw.call('GET', '/health', timeout=20)
                        jv = (hb or {}).get('job') if hc == 200 else None
                        if jv:
                            say(f'ход задания {cur["key"]}: шаг «{jv.get("step")}» {jv.get("step_s")} с, всего {jv.get("elapsed_s")} с, GPU {jv.get("gpu_util")} % / {jv.get("gpu_mem_mb")} МБ, ядер CPU {jv.get("cores_now")}; '
                                f'строка: {jv.get("line")}; пройдено {jv.get("done")}')
                        elif hc == 200:
                            say(f'ход задания {cur["key"]}: /health.job пуст — воркер не отдаёт ход (урок b1)')
                        why_stuck = stall.step(t, jv)
                        if why_stuck:
                            say(f'!! {why_stuck} — гашу')
                            summary['jobs'][cur['key']] = {'status': 'stuck', 'error': why_stuck}
                            summary['stopped_by'] = 'job_stuck'
                            break
                    status, info = spec.poll(gw, cur, t)
                    if status == 'running' and a.job_min and t - cur['t0'] > a.job_min * 60:       # job_min=0 (по умолчанию) — задание живёт до потолка пробы; срезать только явным --job-min
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
    return 0 if summary['stop_verified'] and summary['stopped_by'] in ('done', 'planned') and not summary['failed'] else 1
