#!/usr/bin/env python3
"""НАБОР SALAD — ДРАЙВЕР ПЛАТНЫХ ПРОБ (T-20261121-178/2). Всё, что уроки пула мешей и проб Salad (724, 734, 737, 740, 748, 754, 755…) требуют от драйвера, — в ОДНОМ месте.
Новая проба пишет только функцию модели (`Spec`: тело группы, что послать, как проверить результат); охрана денег, ожидание образа, сторожа и гашение — отсюда.

ЧТО ДАЁТ (урок → функция):
  • 755 «создано = 201 + группа видна»; 504/обрыв → ищем группу по имени (подхват, не второй create), 502/503 → один повтор, name_conflict после 504 → подхват; счётчики retries_create/adopted_after_504 (T-20261123-03/1; правила — rules/salad-groups.json → api_retry) `api_retry`, `orphan_check`, `create_and_start` (старт на большой образ → HTTP 400 → ждём бесплатно до `wait_s`, e022e305)
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
DEFAULT_API_RULES = {'retries': 1, 'status_codes': [502, 503], 'pauses_s': [20], 'timeout_codes': [504, 599], 'lookup_pauses_s': [5, 15, 30], 'timeout_retries': 1,
                     'conflict_codes': [400, 409], 'conflict_type': 'name_conflict'}     # запасные числа; живые — rules/salad-groups.json → api_retry
API_COUNTERS = {'retries_create': 0, 'retries_start': 0, 'adopted_after_504': 0, 'adopted_after_503': 0, 'orphans_stopped': 0}   # счётчики итога прогона: каждый повтор/подхват — не молча
NO_ANSWER = 599                        # псевдокод «ответа нет» (обрыв, таймаут сокета): MG.api в этих случаях бросает исключение, а код ≥ 300 нужен всем вызывающим
SLOT_PRIO = 2                           # платные пробы — heavy-slot --prio 2 (P-038)
SAFE_PREFIXES = ('mesh-', 'render-', 'trial-')       # чужие боевые группы не трогаем и не считаем «посторонними»
HOLD = 'hold'                                         # before_job вернул HOLD → очередное задание пока не отправляем (нода прогрета и ждёт решения), цикл идёт дальше


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
def api_rules(rules: dict | None = None) -> dict:
    """Правила повтора: запасные в коде ← `rules/salad-groups.json` → api_retry ← явные `rules` вызывающего (у sg_salad свои)."""
    return {**DEFAULT_API_RULES, **salad_rules('api_retry'), **(rules or {})}


def bump(counters: dict | None, key: str, n: int = 1) -> None:
    if counters is not None:
        counters[key] = counters.get(key, 0) + n


def _api_call(MG, path: str, method: str, body):
    """Один запрос к API групп; обрыв/таймаут → (599, ...), а не исключение: драйвер не падает, решение — в api_retry."""
    try:
        return MG.api(path, method, body) if body is not None else MG.api(path, method)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return NO_ANSWER, {'detail': f'нет ответа: {type(e).__name__} {str(e)[:100]}'}


def _group_state(MG, name: str) -> tuple[bool, str | None]:
    """(группа видна по имени, её состояние)."""
    try:
        c, g = MG.api(f'/{name}')
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, None
    return c == 200, (((g or {}).get('current_state') or {}).get('status') if c == 200 else None)


def _is_conflict(r: dict, code: int, resp) -> bool:
    return code in r['conflict_codes'] and r['conflict_type'] in json.dumps(resp, ensure_ascii=False)[:600]


def api_retry(MG, path: str, method: str, body, name: str, say_fn=say, sleep=time.sleep, rules: dict | None = None, counters: dict | None = None):
    """create/start группы Salad с повтором (T-20261123-03/1; правила — `rules/salad-groups.json` → api_retry). Возвращает (код, ответ, число_повторов); обрыв/таймаут → код 599.
      • 504 / нет ответа: Salad мог выполнить действие. НЕ повторяем вслепую: ищем группу по имени (GET, несколько проб — список отстаёт). Создание — группа есть → подхват (`adopted_after_504`), второй create не шлём;
        старт — состояние не «stopped» → уже стартовала. Не нашли — `timeout_retries` повтор (`retries_create`/`retries_start`). Повтор вернул name_conflict → снова ищем и подхватываем (группа от первого вызова).
      • 502/503: `retries` повтор(ов) через `pauses_s`; перед повтором — тот же поиск (`adopted_after_503`). 400/401/прочее — без повторов.
    Каждый повтор и подхват — строка в журнал (`say_fn`) и счётчик в `counters` (словарь итога)."""
    r = api_rules(rules)
    is_create = method == 'POST' and path == ''
    what = path or 'создание'
    rk = 'retries_create' if is_create else 'retries_start'

    def found() -> tuple[bool, str | None]:
        ok_, st = _group_state(MG, name)
        return ok_ and (is_create or st not in (None, 'stopped')), st

    def lookup(pauses) -> tuple[bool, str | None]:
        for i, ps in enumerate(pauses):
            sleep(float(ps))
            hit, st = found()
            if hit:
                return True, st
            say_fn(f'{method} {what}: группы {name} по имени пока не видно (проба {i + 1}/{len(pauses)})')
        return False, None

    def adopt(key: str, code: int, st, n: int, resp):
        bump(counters, key)
        say_fn(f'{method} {what}: ответ {code}, но группа уже есть (состояние {st}) — подхватываю, второй запрос не шлю [{key}]')
        return (201 if is_create else 202), resp, n

    code, resp = _api_call(MG, path, method, body)
    n, left_status, left_timeout, after_timeout = 0, int(r['retries']), int(r['timeout_retries']), False
    while True:
        if code in r['timeout_codes']:
            after_timeout = True
            hit, st = lookup(r['lookup_pauses_s'])
            if hit:
                return adopt('adopted_after_504', code, st, n, resp)
            if left_timeout <= 0:
                break
            left_timeout -= 1
        elif code in r['status_codes']:
            if left_status <= 0:
                break
            left_status -= 1
            ps = r['pauses_s']
            sleep(float(ps[min(n, len(ps) - 1)]))
            hit, st = found()
            if hit:
                return adopt('adopted_after_503', code, st, n, resp)
        elif is_create and after_timeout and _is_conflict(r, code, resp):
            hit, st = lookup(r['lookup_pauses_s'])                       # name_conflict после «504»: группа от первого вызова, список просто отстаёт
            if hit:
                return adopt('adopted_after_504', code, st, n, resp)
            say_fn(f'{method} {what}: {code} {r["conflict_type"]}, а группы {name} не видно — не подхватываю (возможно, чужая/старая); решает вызывающий')
            break
        else:
            break
        n += 1
        bump(counters, rk)
        say_fn(f'{method} {what}: ответ {code} — повтор {n} (retries={r["retries"]}, timeout_retries={r["timeout_retries"]}) [{rk}]')
        code, resp = _api_call(MG, path, method, body)
    return code, resp, n


def orphan_check(MG, BR, name: str, say_fn=say, counters: dict | None = None) -> bool | None:
    """После НЕудачного create: группа могла всё же появиться (504, потерянный ответ). Видна → гасим с проверкой «0 нод» (ничьей машины без присмотра). Возвращает stop_verified или None, если группы нет."""
    hit, st = _group_state(MG, name)
    if not hit:
        return None
    say_fn(f'!! создание отказало, но группа {name} видна (состояние {st}) — гашу с проверкой, сирот не оставляю')
    bump(counters, 'orphans_stopped')
    return bool(BR.stop_and_verify(name))


def create_and_start(MG, BR, name: str, body: dict, say_fn=say, sleep=time.sleep, clock=time.time, wait_s: float = 2400, rules: dict | None = None, counters: dict | None = None) -> tuple[bool, float, str]:
    """Создать группу (201 + видна в списке), ЖДАТЬ образ бесплатно (состояние stopped), стартовать. `/start` раньше времени на большой образ — HTTP 400 (р.5 e022e305; образ 22 ГиБ ≈ 25 мин):
    повторяем до `wait_s`, пока не 202. Возвращает (ок, время /start, причина отказа). `counters` — словарь итога: retries_create/retries_start/adopted_after_504/orphans_stopped;
    отказ create с видимой группой → она гасится здесь (`orphans_stopped`, `orphan_stop_verified`)."""
    code, resp, _ = api_retry(MG, '', 'POST', body, name, say_fn, sleep, rules, counters)
    say_fn('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        v = orphan_check(MG, BR, name, say_fn, counters)
        if v is not None and counters is not None:
            counters['orphan_stop_verified'] = v
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
        code, resp, _ = api_retry(MG, f'/{name}/start', 'POST', None, name, say_fn, sleep, rules, counters)
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


# ---------------------------------------------------------------- профиль ресурсов по типу работы (T-186/1; владелец TG 1456/1457/1470)
class ProfileRefused(RuntimeError):
    """Группу Salad создаём ТОЛЬКО по профилю типа работы (`rules/salad-resources.json`). Нет профиля, свои числа мимо него, запрещённый тариф, карта вне профиля → отказ ДО создания группы (код 3)."""


FORBIDDEN_TIERS = ('batch', 'high')                           # владелец TG 1456/1457: low, нет машин → medium, выше и batch нельзя
PROFILE_REQUIRED = ('card', 'cpu', 'memory_mb', 'storage_gb', 'shm_mb', 'tier', 'tier_fallback', 'expect', 'basis')


def resources_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rules', 'salad-resources.json')


def load_profiles(path: str | None = None) -> dict:
    try:
        return json.load(open(path or resources_path(), encoding='utf-8')).get('profiles') or {}
    except (OSError, ValueError):
        return {}


def profile_problems(prof: dict) -> list[str]:
    """Чем строка профиля негодна (пусто — годна): все поля на месте, тарифы только low/medium, `basis` честный (measured — дата и лог)."""
    out = [f'нет поля «{k}»' for k in PROFILE_REQUIRED if k not in prof]
    for k in ('tier', 'tier_fallback'):
        if prof.get(k) in FORBIDDEN_TIERS or (k in prof and prof[k] not in ('low', 'medium')):
            out.append(f'{k}={prof.get(k)!r}: разрешены только low и medium')
    if prof.get('basis') not in ('measured', 'estimate'):
        out.append('basis: measured или estimate')
    elif prof['basis'] == 'measured':
        m = prof.get('measured') or {}
        if not (m.get('date') and m.get('log')):
            out.append('basis=measured без measured.date и measured.log (откуда числа)')
    elif not prof.get('basis_note'):
        out.append('basis=estimate без basis_note (что именно не мерили)')
    rule = prof.get('card_rule')
    if rule is not None:                                     # правило выбора карты (T-186/1): малая карта для лёгких, большая — для тяжёлых и тех, что упали по памяти
        cards = [prof.get('card'), *(prof.get('card_fallbacks') or [])]
        if rule.get('small') not in cards or not rule.get('large') or any(c not in cards for c in rule['large']):
            out.append('card_rule: small и large — только карты из card/card_fallbacks профиля, large не пуст')
    return out


def resource_profile(work_type: str, path: str | None = None) -> dict:
    """Строка профиля типа работы; нет типа/строки/поля — `ProfileRefused` с понятным текстом."""
    if not work_type:
        raise ProfileRefused('не указан тип работы (`work_type`): группу Salad создаём только по профилю `rules/salad-resources.json`')
    prof = load_profiles(path).get(work_type)
    if not isinstance(prof, dict):
        raise ProfileRefused(f'нет профиля «{work_type}» в rules/salad-resources.json — добавь строку (карта, vCPU, RAM, диск, shm, тариф, basis) и только потом создавай группу')
    bad = profile_problems(prof)
    if bad:
        raise ProfileRefused(f'профиль «{work_type}» негоден: ' + '; '.join(bad))
    return prof


def profile_resources(prof: dict, variant: str = '') -> dict:
    """`resources` тела группы — ТОЛЬКО из профиля (вариант `variants.<имя>` перекрывает отдельные поля, например диск диагностики)."""
    v = {**prof, **((prof.get('variants') or {}).get(variant) or {})} if variant else prof
    return {'cpu': int(v['cpu']), 'memory': int(v['memory_mb']), 'storage_amount': int(v['storage_gb']) * 2 ** 30, 'shm_size': int(v['shm_mb'])}


def tier_refusal(prof: dict, tier: str) -> str | None:
    if tier in FORBIDDEN_TIERS:
        return f'тариф «{tier}» запрещён (владелец TG 1456/1457: low, нет машин — medium, выше и batch нельзя)'
    if tier not in (prof['tier'], prof['tier_fallback']):
        return f'тариф «{tier}» вне профиля: разрешены {prof["tier"]} и (нет машин) {prof["tier_fallback"]}'
    return None


def card_refusal(prof: dict, card: str) -> str | None:
    cards = [prof['card'], *(prof.get('card_fallbacks') or [])]
    return None if card in cards else f'карта «{card}» вне профиля (разрешены: {", ".join(cards)})'


OOM_MARKERS = ('out of memory', 'cudacachingallocator', 'handles_.at', 'cublas_status_alloc_failed', 'cuda error: out of memory')


def is_oom_error(err) -> bool:
    """Задание упало из-за памяти КАРТЫ (а не из-за входа/кода): «CUDA out of memory» или сбой аллокатора CUDA (`INTERNAL ASSERT … CUDACachingAllocator`, замер T-186/1: так падали тяжёлые на 16 ГБ)."""
    t = str(err or '').lower()
    return any(m in t for m in OOM_MARKERS)


def retry_card(prof: dict, card: str) -> str | None:
    """Карта для ОДНОГО повтора задания, упавшего по памяти: у профиля есть `card_rule`, задание шло на его малой карте → первая из `large`; иначе None (повтор не нужен — карта уже большая или правила нет)."""
    rule = prof.get('card_rule') or {}
    large = rule.get('large') or []
    return large[0] if card == rule.get('small') and large and card not in large else None


def body_refusal(prof: dict, body: dict, variant: str = '') -> str | None:
    """Готовое тело группы сверяем с профилем: драйвер, собравший тело мимо `group_body(work_type=…)`, ловится здесь, до создания группы."""
    c = (body or {}).get('container') or {}
    got = {k: (c.get('resources') or {}).get(k) for k in ('cpu', 'memory', 'storage_amount', 'shm_size')}
    want = profile_resources(prof, variant)
    if got != want:
        return f'ресурсы тела группы {got} не равны профилю {want} — числа только из rules/salad-resources.json'
    for k in (c.get('priority'), (body or {}).get('priority')):
        bad = tier_refusal(prof, k)
        if bad:
            return bad
    return None


def basis_text(prof: dict) -> str:
    if prof.get('basis') == 'measured':
        m = prof.get('measured') or {}
        return f'замер {m.get("date")}, {m.get("log")}'
    return 'по оценке'


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


def group_body(name: str, image: str, tier: str, class_id: str, port: int, env: dict, auth: dict, command: list | None = None, *, work_type: str = '', variant: str = '',
               card: str | None = None, resources: dict | None = None) -> dict:
    """Тело временной группы пробы: 1 нода, без автостарта и перезапуска, шлюз с ключом, пробы на /health. Ресурсы — ТОЛЬКО из профиля типа работы (`work_type`,
    `rules/salad-resources.json`): свои `resources` → `ProfileRefused`, как и нет профиля, тариф вне {low, medium} (batch/high — нельзя), карта вне профиля."""
    if resources is not None:
        raise ProfileRefused('ресурсы группы нельзя передавать мимо профиля: правь строку типа работы в rules/salad-resources.json')
    prof = resource_profile(work_type)
    bad = tier_refusal(prof, tier) or (card_refusal(prof, card) if card else None)
    if bad:
        raise ProfileRefused(bad)
    readiness, startup = probes(port)
    container = {'image': image, **({'command': command} if command else {}),
                 'resources': {**profile_resources(prof, variant), 'gpu_classes': [class_id]}, 'priority': tier, 'environment_variables': env, 'image_caching': True,
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
PULL_MIN_GIB_MIN = float(_PGR.get('min_gib_min', 0.0))                # порог скорости докачки образа, ГиБ/мин (0 — выключен): темп по окну ниже → пересадка, даже если укладывается в допуск по времени
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
                 window_s: float = PULL_WINDOW_S, min_rate: float | None = None, image_gib: float | None = None) -> str | None:
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
    if min_rate and rate < min_rate:                           # min_rate — доля образа в минуту (= min_gib_min / размер образа): нода медленнее порога скорости
        gib = f' ({rate * image_gib:.2f} ГиБ/мин)' if image_gib else ''
        return f'образ {p1:.0%} за {age / 60:.0f} мин, темп {max(rate, 0):.1%}/мин{gib} < порога {min_rate:.1%}/мин — нода медленная'
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
        if PULL_MIN_GIB_MIN > 0 and image_gib:
            self.verdict_kw.setdefault('min_rate', PULL_MIN_GIB_MIN / image_gib)
            self.verdict_kw.setdefault('image_gib', image_gib)

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


# ---------------------------------------------------------------- сторож медленного ДИСКА ноды (T-186/1: t178c качал веса 0,95 ГБ/мин при норме 7,5, а run_probe не звал weights_slow)
_DGR = salad_rules('disk_guard')                        # числа — `rules/salad-groups.json` → disk_guard; нижняя скорость профиля `expect.weights_gb_min_min` перекрывает
DISK_WINDOW_S = float(_DGR.get('window_s', 300.0))
DISK_MIN_GB_MIN = float(_DGR.get('min_gb_min', 2.0))
DISK_MAX_RECREATE = int(_DGR.get('max_recreations', 2))


class DiskGuard:
    """Идёт фаза `weights` (воркер отдаёт `root_gb` в /health), а скорость за окно ниже нормы — нода с медленным диском: пересаживаем (≤ max_recreations за пробу), потом `give_up`
    (драйвер гасит: медленно качают все ноды — это образ/сеть/диск группы, а не одна машина). Деньги и число медленных нод идут в сводку (`disk_culls`, `disk_slow_rates`).
    `realloc(group, iid, why)` и `take_slot()` — как у PullGuard (общий бюджет node_health), подменяются в тестах."""

    def __init__(self, group: str, min_gb_min: float = DISK_MIN_GB_MIN, window_s: float = DISK_WINDOW_S, max_recreations: int = DISK_MAX_RECREATE,
                 take_slot: Callable[[], int] | None = None, realloc: Callable[[str, str, str], bool] | None = None, say_fn=say):
        self.group, self.min_gb_min, self.window_s, self.max_recreations, self.say = group, min_gb_min, window_s, max_recreations, say_fn
        self.take_slot, self.realloc = take_slot, realloc
        self.culls = 0
        self.rates: list = []                                   # скорости медленных нод, ГБ/мин — в сводку
        self.give_up = ''

    def _nh(self):
        if self.take_slot is None or self.realloc is None:
            import sys
            here = os.path.dirname(os.path.abspath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            import node_health as NH
            self.take_slot = self.take_slot or NH.take_cull_slot
            self.realloc = self.realloc or NH.reallocate

    def step(self, t: float, hist: list, ins: list) -> bool:
        """True — ноду пересадили (вызывающий чистит `hist`). `hist` = [(время, ГБ папки весов)] текущей ноды."""
        rate = weights_slow(hist, self.window_s, self.min_gb_min)
        if rate is None:
            return False
        iid = next((i.get('id') for i in ins if i.get('id')), None)
        why = f'веса качаются {rate:.2f} ГБ/мин за {self.window_s / 60:.0f} мин (норма от {self.min_gb_min} ГБ/мин) — медленный диск/сеть ноды'
        if self.culls >= self.max_recreations:
            self.give_up = f'{why}; пересадок уже {self.culls} — гашу'
            return False
        if not iid:
            return False
        self._nh()
        if not self.take_slot():
            self.say(f'сторож диска: общий бюджет пересадок на час исчерпан — жду: {why}')
            return False
        self.say(f'сторож диска: нода {str(iid)[:8]} — {why} → пересаживаю (№{self.culls + 1} из {self.max_recreations})')
        if self.realloc(self.group, iid, why):
            self.culls += 1
            self.rates.append(round(rate, 3))
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
    slow_window_s: float = 0                         # сторож медленной сборки весов на running-ноде (0 — выключен): окно, с
    slow_gb_min: float = 2.0                         # …и порог ГБ/мин (здоровая нода ≈7,5, медленная ≈0,95 — замер 22.11)
    banked: float = 0.0                              # деньги, уже потраченные на пересаженные ноды (running_s считается заново на новой)
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
        return self.banked + cost_usd(self.running_s(t), self.price)

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
            if h.get('phase') == 'weights' and self.slow_window_s > 0:
                rate = weights_slow(self.gb_hist, self.slow_window_s, self.slow_gb_min)
                if rate is not None:
                    return 'weights_slow', f'веса собираются {rate:.2f} ГБ/мин < {self.slow_gb_min} за {self.slow_window_s / 60:.0f} мин (папка {h["root_gb"]} ГБ) — нода медленная'
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


class SilenceGuard:
    """Сторож тишины (P-039, T-178 22.11: нода 37 мин без готовых заданий — узнали только на обходе). «Ход» — готовое задание, новая готовность ноды, перезапуск ноды. Нет хода дольше
    `minutes` (до готовности ноды — ×`warm_factor`: подъём ноды законно долог) — `step` возвращает минуты тишины, повтор тревоги — каждые `minutes`. minutes=0 — выключен."""

    def __init__(self, minutes: float, t0: float, warm_factor: float = 2.5):
        self.limit, self.warm, self.last, self.alerts = float(minutes or 0) * 60.0, warm_factor, t0, 0
        self.seen = (0, None, 0)

    def step(self, t: float, n_done: int, ready_at, restarts: int):
        cur = (n_done, ready_at, restarts)
        if cur != self.seen:
            self.seen, self.last, self.alerts = cur, t, 0
            return None
        if self.limit <= 0:
            return None
        lim = self.limit * (self.warm if ready_at is None else 1.0) * (self.alerts + 1)
        if t - self.last > lim:
            self.alerts += 1
            return (t - self.last) / 60.0
        return None


def node_reset(w: 'Watch', t: float) -> None:
    """Нода сменилась (пересадка или Salad перезапустил её сам): потраченное уходит в `banked`, отсчёты «running/started/ответ/готова/веса» — заново на новой ноде."""
    w.banked = w.cost(t)
    w.run_since = w.started_since = w.ready_at = None
    w.ever_ok = False
    w.gb_hist = []
    w.last_cull = t


def node_lost_step(w: 'Watch', t: float, ins: list, lost_obs: int, cur, pending: list, max_restarts: int, restarts: int, need_obs: int = 3):
    """Нода пропала у прогретой группы (22.11, t178a: Salad перезапустил экземпляр — state снова downloading, /health 503 — и 12 заданий подряд получили 503 как «отказы»).
    Возвращает (lost_obs, restarts, action): action None — нода на месте; 'wait' — нет running, наблюдений меньше need_obs (не дёргаться на одном провале запроса);
    'restart' — нода потеряна: прерванное задание вернулось в начало очереди (не отказ), деньги ноды в banked, отсчёты заново; 'stop' — перезапусков больше max_restarts."""
    if w.ready_at is None or any(i.get('state') == 'running' for i in ins):
        return 0, restarts, None
    lost_obs += 1
    if lost_obs < need_obs:
        return lost_obs, restarts, 'wait'
    if restarts >= max_restarts:
        return lost_obs, restarts, 'stop'
    if cur is not None:
        pending.insert(0, cur['key'])
    node_reset(w, t)
    return 0, restarts + 1, 'restart'


def disk_guard_wanted(a) -> bool:
    """DiskGuard (профиль, включён по умолчанию) и сторож `Watch.slow_window_s` (--slow-window-min, T-178/3) делают одно и то же: работает ОДИН. Явное окно сторожа весов выключает DiskGuard; `a.disk_guard=False` выключает его всегда."""
    return bool(getattr(a, 'disk_guard', True)) and not float(getattr(a, 'slow_window_s', 0) or 0) > 0


def weights_cull(w: 'Watch', guard, t: float, ins: list, why: str, say_fn=say) -> bool:
    """Медленная сборка весов на running-ноде: пересадить (тот же бюджет `max_culls`, что у медленной докачки образа). Потраченное на эту ноду уходит в `banked`,
    отсчёты «running/started/ответ/веса» начинаются заново на новой ноде. False — пересаживать нельзя (нет сторожа, бюджет исчерпан, нет running-инстанса): драйвер гасит группу."""
    if guard is None or guard.culls >= guard.max_culls:
        return False
    run = [i for i in ins if i.get('state') == 'running' and i.get('id')]
    if not run:
        return False
    guard._nh()
    if not guard.take_slot():
        say_fn('сторож весов: общий бюджет пересадок на час исчерпан — гашу')
        return False
    iid = run[0]['id']
    say_fn(f'сторож весов: нода {iid[:8]} — {why} → пересаживаю (№{guard.culls + 1} из {guard.max_culls})')
    if not guard.realloc(guard.group, iid, why):
        return False
    guard.culls += 1
    node_reset(w, t)
    return True


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
    work_type: str = ''                                            # тип работы → профиль ресурсов `rules/salad-resources.json` (T-186/1): ОБЯЗАТЕЛЕН, пусто/нет профиля → отказ до группы (код 3)
    variant: str = ''                                              # вариант профиля (`variants.<имя>`, например диск диагностики)


def run_probe(a, MG, BR, spec: Spec, **kw) -> int:
    """Платная проба по профилю типа работы. Тариф `low`; нет машин (`no_machine`, $0 — до running не списывается) → ОДИН раз `tier_fallback` (medium) в ядре, не в драйверах.
    ВАЖНО: `a.tier`/`a.suffix` меняются на месте (замыкания `build_body` драйверов читают `a`). Выше medium и batch — нельзя (`tier_refusal`)."""
    res: dict = {}
    rc = _run_probe_once(a, MG, BR, spec, result=res, **kw)
    try:
        prof = resource_profile(spec.work_type)
    except ProfileRefused:
        return rc
    if (res.get('summary') or {}).get('stopped_by') == 'no_machine' and a.apply and a.tier == prof['tier'] and prof['tier_fallback'] != a.tier and getattr(a, 'tier_fallback', True):
        say(f'нет машин на «{a.tier}» — один раз пробую «{prof["tier_fallback"]}» (профиль {spec.work_type}; выше нельзя)')
        a.tier, a.suffix = prof['tier_fallback'], f'{a.suffix}m'
        return _run_probe_once(a, MG, BR, spec, result={}, **kw)
    return rc


def _run_probe_once(a, MG, BR, spec: Spec, gw_factory=Gateway, sleep=time.sleep, clock=time.time, slot_check=require_slot,
                    image_check=check_image, ledger=ledger_append, wait_s: float = 2400, pull_guard: Callable[[str], PullGuard] | None = None,
                    disk_guard: Callable[[str], DiskGuard] | None = None, result: dict | None = None) -> int:
    """Платная проба на Salad по общему образцу. `a`: image, suffix, tier, apply, cap, probe_cap, max_min, running_min, start_min, health_min, ready_min, stall_min, stall_gb,
    job_min, out. Без `--apply` — только разбор (тело без секретов, группа НЕ создаётся)."""
    name = f'{spec.prefix}-{a.suffix}'
    try:                                                     # профиль ресурсов — ДО всего (в т.ч. до разбора без --apply): нет профиля/чужой тариф/чужая карта → отказ
        prof = resource_profile(spec.work_type)
        refuse = tier_refusal(prof, a.tier) or card_refusal(prof, spec.card)
    except ProfileRefused as exc:
        prof, refuse = None, str(exc)
    if refuse:
        say('ОТКАЗ по профилю ресурсов:', refuse)
        say('группу НЕ создаю, денег не потрачено')
        return 3
    MG.env_from_file()
    class_id, price = gpu_class(MG, spec.card, a.tier)
    if class_id is None:
        say(f'класс карты «{spec.card}» не найден у Salad — стоп, денег не потрачено')
        return 3
    try:
        body = spec.build_body(name, class_id, MG.ghcr_auth())
        refuse = body_refusal(prof, body, spec.variant)
    except ProfileRefused as exc:
        refuse = str(exc)
    if refuse:
        say('ОТКАЗ по профилю ресурсов:', refuse)
        say('группу НЕ создаю, денег не потрачено')
        return 3
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
               'work_type': spec.work_type, 'profile': prof, 'profile_basis': basis_text(prof), 'jobs': {}, 'failed': 0, 'stop_verified': False, 'stopped_by': None,
               **API_COUNTERS}
    if result is not None:
        result['summary'] = summary
    ok_create, t_start, refuse = create_and_start(MG, BR, name, body, say, sleep, clock, wait_s, counters=summary)
    if not ok_create:
        summary['stopped_by'] = refuse
        ok_stop = stop_and_verify(BR, name) if refuse.startswith(('start_http', 'create_wait')) else summary.get('orphan_stop_verified', True)   # create отказал, но группа была видна (504) — её уже погасили в create_and_start
        summary['stop_verified'] = ok_stop
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1, default=str)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', *API_COUNTERS)}, ensure_ascii=False))
        return 1
    w = Watch(t_start, price, a.probe_cap, a.cap, a.max_min, a.running_min, a.start_min, a.health_min, a.ready_min, a.stall_min, a.stall_gb)
    w.slow_window_s = float(getattr(a, 'slow_window_s', 0) or 0)
    w.slow_gb_min = float(getattr(a, 'slow_gb_min', 2.0) or 2.0)
    guard = (pull_guard or PullGuard)(name) if getattr(a, 'pull_guard', True) else None      # --no-pull-guard выключает (a.pull_guard=False)
    dguard = (disk_guard or (lambda n: DiskGuard(n, min_gb_min=float((prof.get('expect') or {}).get('weights_gb_min_min') or DISK_MIN_GB_MIN))))(name) if disk_guard_wanted(a) else None
    if guard is not None:
        guard.configure(image_gib)                                                           # норма докачки — от размера образа (ожидаемое × 2,5), не константы мешей
    gw = None
    streak = 0
    busy_waits = 0
    post_retried: set = set()                                          # ключи, которым уже сделан повтор после POST без ответа (повтор — один)
    last_job_look = 0.0
    stall = JobStall(getattr(a, 'stuck_min', STUCK_MIN))
    lost_obs, node_restarts = 0, 0
    silence = SilenceGuard(float(getattr(a, 'silence_min', 10) or 0), clock())
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
            lost_obs, node_restarts, lost_act = node_lost_step(w, t, ins, lost_obs, cur, pending, int(getattr(a, 'max_node_restarts', 3)), node_restarts)
            if lost_act == 'restart':
                say(f'!! нода пропала у прогретой группы (Salad перезапустил экземпляр, перезапуск №{node_restarts}) — прерванное задание в начало очереди, жду новую ноду')
                if cur is not None:
                    summary['jobs'].pop(cur['key'], None)
                    summary.setdefault('interrupted', []).append(cur['key'])
                cur = None
                gw = None
                last_h = (None, {})
                seen_ev = len(w.events)
                summary['node_restarts'] = node_restarts
            elif lost_act == 'stop':
                say(f'!! нода пропала снова — перезапусков уже {node_restarts} — гашу')
                summary['stopped_by'] = 'node_lost'
                break

            if dguard is not None and w.run_since is not None and w.ready_at is None:           # платная фаза докачки весов: медленный диск → пересадка, потом стоп
                if dguard.step(t, w.gb_hist, ins):
                    w.gb_hist.clear()
                    summary['disk_culls'], summary['disk_slow_rates'] = dguard.culls, dguard.rates
                if dguard.give_up:
                    say(f'!! {dguard.give_up}')
                    summary['stopped_by'] = 'disk_slow'
                    break
            q_min = silence.step(t, sum(1 for v in summary['jobs'].values() if v.get('status') == 'done'), w.ready_at, node_restarts)
            if q_min:
                i0 = ins[0] if ins else {}
                say(f'!! ТИШИНА {q_min:.0f} мин: готовых заданий нет · группа {st} · экземпляр {i0.get("state")}{pull_txt(i0)} started={i0.get("started")} ready={i0.get("ready")} '
                    f'· в очереди {len(pending)} · ≈${w.cost(t):.2f} — разбор (P-039): лог ноды, причина, решение')
                summary['silence_alerts'] = summary.get('silence_alerts', 0) + 1
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
                if why == 'weights_slow' and weights_cull(w, guard, t, ins, detail, say):
                    gw = None                                              # новая нода — новый шлюз, отсчёт заново
                    last_h = (None, {})
                    summary['weights_culls'] = guard.culls
                    why = None                                             # пересадили — дальше обычный шаг цикла (пауза в конце)
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
                held = False                                                     # before_job вернул HOLD: задание пока не шлём (ждём решения, нода прогрета)
                if cur is None and pending and spec.before_job:
                    why_plan = spec.before_job(pending[0], w.cost(t), w.cap_now())
                    held = why_plan == HOLD
                    if why_plan and not held:
                        say(f'новые задания не отправляю: {why_plan} — гашу')
                        summary['stopped_by'] = 'planned' if not str(why_plan).startswith('!') else str(why_plan)[1:]       # «!причина» — аварийный стоп (код 1), иначе плановый
                        summary['planned_reason'] = str(why_plan)
                        break
                if cur is None and pending and not held:
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
                max_streak = int(getattr(a, 'fail_streak', 2) or 2)                # сколько отказов подряд до стопа (по умолчанию 2; пакет — --fail-streak 3)
                if streak >= max_streak:
                    summary['stopped_by'] = 'fail_streak'
                    say(f'!! {max_streak} задания подряд не удались — гашу (чинить в коде)')
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
        summary['cost_usd_est'] = round(w.banked + cost_usd(summary['running_s'], price), 3)       # banked — деньги пересаженных/перезапущенных нод (без них ИТОГ и журнал занижали расход)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1, default=str)
        if dguard is not None:
            summary['disk_culls'], summary['disk_slow_rates'] = dguard.culls, dguard.rates
        warn = ledger({'group': name, 'model': spec.model, 'work_type': spec.work_type, 'profile_basis': basis_text(prof), 'profile': prof, 'card': spec.card, 'tier': a.tier, 'image': a.image, 'running_s': summary['running_s'], 'price_usd_h': price,
                       'cost_usd_est': summary['cost_usd_est'], 'stopped_by': summary['stopped_by'], 'stop_verified': summary['stop_verified'],
                       'jobs_done': sum(1 for v in summary['jobs'].values() if v.get('status') == 'done'), 'jobs_failed': summary['failed'], 'driver': 'kit_driver'})
        if warn:
            say('!!', warn)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'failed', 'running_s', 'cost_usd_est', *API_COUNTERS)}, ensure_ascii=False))
    return 0 if summary['stop_verified'] and summary['stopped_by'] in ('done', 'planned') and not summary['failed'] else 1
