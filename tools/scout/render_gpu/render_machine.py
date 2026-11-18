#!/usr/bin/env python3
"""КОНТРОЛЛЕР МАШИНЫ РЕНДЕРА (T-20261117-24/1, план render-machine-01 § «Решение» п.1, 4, 5). Один держатель желаемого состояния.

    render_machine.py on     [--by <кто>] [--lang ru|en]   # включить (идемпотентно: живую не перезапускает, второй группы не создаёт)
    render_machine.py off    [--by <кто>] [--lang ru|en]   # выключить: /stop и проверка `stopped`
    render_machine.py status [--lang ru|en] [--json]        # одна строка: выключена / включается / прогрелась / расход
    render_machine.py pulse  [--by <кто>]                   # «работа идёт»: воркер/маршрутизатор зовёт при старте и конце КАЖДОЙ пары (сбрасывает автостоп)
    render_machine.py tick                                  # раз в минуту по крону: прогрелась? автостоп? потолок $? сообщения; отметка для сторожа

ГДЕ ЖИВЁТ: на DEV (pakardev) — там ключ Salad (`migrate_groups.api`), `alert.sh` с настроенным TG и доступ ssh к серверу. Боты на других машинах
зовут его через `r '<команда>'` (README). Состояние — `~/remlab-logs/render-machine/state.json` (вне репо), все команды под одной блокировкой
(`flock`): двойное нажатие кнопки не плодит групп.

ЧТО РЕШАЕТ ЧИСТАЯ ФУНКЦИЯ `plan(state, obs, rules, now)` → (новое состояние, действия) — без сети, под тестами (`tests_render_machine.py`).
Действия: start / stop(причина) / notify(ключ). Исполнитель `execute()` делает их через Salad API и `alert.sh`.

ПРЕДОХРАНИТЕЛИ (независимые, числа — в `rules/salad-groups.json` → `render_machine`):
  • автостоп `idle_stop_min` после последней отметки работы (`pulse`) или после `on` без заказов;
  • максимум непрерывной работы `max_run_min`;
  • дневной потолок `day_cap_usd` (по Лондону): превысили = стоп + сообщение; пока потолок исчерпан, `on` отказывает;
  • не прогрелась за `warmup_max_min` = стоп + сообщение;
  • сторож на сервере (`infra/server/render-guard.py`): контроллер не отмечался > `guard_stale_min` → гасит ТОЛЬКО `render-*`.

СООБЩЕНИЯ владельцу (через готовый `tools/scout/alert.sh`, токены не читаем): «прогрелась» — ОДНО за запуск; деградация — отдельное, одно на
эпизод (без спама); стоп по предохранителю — одно. Каждая надпись — пара RU/EN (`T`)."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))

# статусы ГРУППЫ в Salad: pending (создаётся, /start даёт 400), deploying (машина выделяется/качает образ), running, stopping, stopped, failed
LIVE = ('deploying', 'running')
PAID = LIVE + ('stopping',)
STATE_DIR = os.path.expanduser(os.environ.get('RENDER_MACHINE_DIR', '~/remlab-logs/render-machine'))
RULES = os.environ.get('MESH_GROUPS_RULES') or os.path.join(HERE, '..', 'rules', 'salad-groups.json')
SERVER = ['ssh', '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', '-p', '22222', 'root@89.167.127.0']
SINK_ROOT = '/opt/remlab/meshes'

# ───────────────────────── надписи: пара RU/EN ─────────────────────────
T = {
    'on_started': ('Включаю машину рендера — прогреется за 2–4 минуты, я напишу.', 'Starting the render machine — about 2–4 minutes, I will message you.'),
    'on_already': ('Машина уже включена ({st}) — второй не запускаю.', 'The machine is already on ({st}) — not starting another.'),
    'on_refused_cap': ('Не включаю: дневной потолок ${cap:.2f} исчерпан (потрачено ${spent:.2f}). Завтра — или поднять потолок в правилах.',
                       'Not starting: the daily ${cap:.2f} cap is used up (spent ${spent:.2f}).'),
    'on_refused_image': ('Не включаю: в Salad группа «{g}» с другим образом, чем в правилах. Для нового образа — новая группа (имя в правилах).',
                         'Not starting: Salad group "{g}" has a different image than the rules. A new image needs a new group name.'),
    'on_error': ('Не получилось включить: {why}.', 'Could not start: {why}.'),
    'off_done': ('Машина рендера выключена (остановка подтверждена). Сегодня потрачено ${spent:.2f}.', 'Render machine is off (stop confirmed). Spent today ${spent:.2f}.'),
    'off_already': ('Машина рендера уже выключена. Сегодня потрачено ${spent:.2f}.', 'Render machine is already off. Spent today ${spent:.2f}.'),
    'off_unconfirmed': ('❗ Выключаю, но остановку Salad пока не подтвердил — проверю на ближайшей отметке.', '❗ Stopping, but Salad has not confirmed yet — will re-check.'),
    'st_off': ('Машина рендера выключена. Сегодня потрачено ${spent:.2f} из ${cap:.2f}. Включить — /render_on.',
               'Render machine is off. Spent today ${spent:.2f} of ${cap:.2f}. Turn on: /render_on.'),
    'st_starting': ('Машина включается ({st}), уже {age} мин. Потрачено сегодня ${spent:.2f}.', 'Machine is starting ({st}), {age} min so far. Spent today ${spent:.2f}.'),
    'st_ready': ('Машина прогрелась и работает ({age} мин), фото считается ~15–30 с. До автостопа {left} мин простоя. Сегодня ${spent:.2f} из ${cap:.2f}. Выключить — /render_off.',
                 'Machine is ready ({age} min), a photo takes ~15–30 s. {left} min of idle left before auto-stop. Today ${spent:.2f} of ${cap:.2f}. Turn off: /render_off.'),
    'st_stray': ('Машина по команде выключена, но на Salad она ещё «{st}» (не наша команда на этой группе или остановка идёт). Ближайший tick её погасит. Сегодня ${spent:.2f}.',
                 'The machine is switched off by command, but Salad still shows it as "{st}" (not started by this controller, or stopping). The next tick will stop it. Spent today ${spent:.2f}.'),
    'st_degraded': ('❗ Машина включена, но не отвечает ({age} мин). Сегодня ${spent:.2f}.', '❗ Machine is on but not responding ({age} min). Spent today ${spent:.2f}.'),
    'warm': ('✅ Машина рендера готова, фото считается ~15–30 с (запуск занял {min} мин). Выключить — /render_off.',
             '✅ Render machine is ready, a photo takes ~15–30 s (started in {min} min). Turn off: /render_off.'),
    'degraded': ('❗ Машина рендера перестала отвечать ({why}). Рендер идёт на запасном CPU. Жду до {min} мин, потом выключу.',
                 '❗ Render machine stopped responding ({why}). Rendering falls back to CPU. Waiting up to {min} min, then stopping.'),
    'recovered_stop': ('Машина рендера не ожила за {min} мин — выключаю.', 'Render machine did not recover in {min} min — stopping.'),
    'lost': ('❗ Машина рендера пропала (статус Salad: {st}). Пробую включить заново ({n} из {max}).', '❗ Render machine disappeared (Salad status: {st}). Restarting ({n} of {max}).'),
    'gave_up': ('❗ Машина рендера пропала и не поднялась за {max} попытки — выключаю, рендер идёт на запасном CPU.',
                '❗ Render machine disappeared and did not come back after {max} tries — switching off, CPU fallback.'),
    'stop_idle': ('Машина рендера выключена: {min} мин без заказов (автостоп). Сегодня потрачено ${spent:.2f}.', 'Render machine stopped: {min} min idle (auto-stop). Spent today ${spent:.2f}.'),
    'stop_maxrun': ('Машина рендера выключена: проработала подряд {min} мин (предел). Включить снова — /render_on.', 'Render machine stopped: {min} min of continuous run (limit).'),
    'stop_cap': ('❗ Машина рендера выключена: дневной потолок ${cap:.2f} (потрачено ${spent:.2f}).', '❗ Render machine stopped: daily cap ${cap:.2f} reached (spent ${spent:.2f}).'),
    'stop_warmup': ('❗ Машина рендера не прогрелась за {min} мин — выключаю, чтобы не платить зря. Рендер идёт на CPU.',
                    '❗ Render machine did not warm up in {min} min — stopping to avoid cost. CPU fallback.'),
}


def tr(key: str, lang: str = 'ru', **kw) -> str:
    ru, en = T[key]
    return (en if lang == 'en' else ru).format(**kw)


# ───────────────────────── правила ─────────────────────────
DEFAULT_RULES = {
    'group': 'render-4090', 'card': '4090', 'idle_stop_min': 20, 'max_run_min': 240, 'day_cap_usd': 2.0, 'warmup_max_min': 15,
    'ready_stale_s': 120, 'degraded_stop_min': 10, 'guard_stale_min': 10, 'restart_max': 2, 'start_retry_s': 45, 'sink_prefix': 'rendermachine',
    'cpu': 8, 'memory_mb': 16384, 'storage_gb': 10, 'price_class': 'RTX 4090 (24 GB)', 'tier': 'high',
    'gpu_class_id': 'ed563892-aacd-40f5-80b7-90c9be6c759b', 'controller_stale_s': 300,
    # исполнитель (render_exec.SaladGpuExecutor): ждать взятия задания, потолок пары, опрос результата, «занято» на время ожидания
    'executor': {'pickup_s': 90, 'pair_max_s': 900, 'poll_s': 3, 'busy_s': 90, 'bundle_max_mb': 95},
    'alert_sh': '/home/pakar/igor/remlab/tools/scout/alert.sh', 'donor_group': 'mesh-q-low-1',
}


def load_rules() -> dict:
    r = dict(DEFAULT_RULES)
    try:
        r.update(json.load(open(RULES, encoding='utf-8')).get('render_machine') or {})
    except (OSError, ValueError):
        pass
    if os.environ.get('RENDER_MACHINE_OVERRIDE'):         # только для проверок вживую: '{"idle_stop_min": 3}'
        r.update(json.loads(os.environ['RENDER_MACHINE_OVERRIDE']))
    return r


def price_usd_h(rules: dict) -> float:
    try:
        d = json.load(open(RULES, encoding='utf-8'))
        return float(d['prices_by_class_usd_h'][rules['price_class']][rules['tier']])
    except (OSError, ValueError, KeyError):
        return 0.17


def london_date(now: float) -> str:
    os.environ.setdefault('TZ', 'UTC')
    import datetime
    import zoneinfo
    return datetime.datetime.fromtimestamp(now, zoneinfo.ZoneInfo('Europe/London')).strftime('%Y-%m-%d')


# ───────────────────────── состояние ─────────────────────────
def new_state() -> dict:
    return {'desired': 'off', 'gen': 0, 'by': None, 'at': 0, 'on_at': 0, 'running_since': 0, 'last_activity': 0, 'busy_until': 0, 'last_tick': 0, 'last_start_try': 0,
            'accrued_ts': 0, 'spent_date': '', 'spent_usd': 0.0, 'warm_gen': 0, 'degraded_since': 0, 'restarts': 0, 'stop_reason': '', 'stop_notified_gen': 0}


def _acc(s: dict, now: float, paying: bool, price: float) -> None:
    """Расход: время между отметками, пока машина оплачивается (deploying/running/stopping — Salad берёт деньги за running, но
    выделение считаем с запасом: потолок честнее), × цена класса. Сутки — по Лондону; новые сутки — счёт с нуля."""
    d = london_date(now)
    if s['spent_date'] != d:
        s['spent_date'], s['spent_usd'] = d, 0.0
    if paying and s['accrued_ts'] and now > s['accrued_ts']:
        s['spent_usd'] = round(s['spent_usd'] + (min(now, s['accrued_ts'] + 600) - s['accrued_ts']) / 3600 * price, 5)
    s['accrued_ts'] = now if paying else 0


def plan(state: dict, obs: dict, rules: dict, now: float) -> tuple[dict, list]:
    """obs: {'status': str|None (статус группы Salad; None — группы нет), 'running': int, 'ready': dict|None (ready.json), 'price': float}.
    Возвращает (новое состояние, [(действие, аргументы)]). Действия: ('start',), ('stop', причина), ('notify', ключ, {поля})."""
    s = json.loads(json.dumps(state))
    acts: list = []
    st = obs.get('status')
    live = st in LIVE
    _acc(s, now, st in PAID, obs['price'])
    s['last_tick'] = now

    if s['desired'] != 'on':
        if live:
            acts.append(('stop', 'desired-off'))        # желаемое «выключено», а машина жива (ручной /start мимо контроллера, сбой стопа)
        return s, acts

    # ── желаемое «включено» ──
    age_min = (now - s['on_at']) / 60
    if st == 'running' and not s['running_since']:
        s['running_since'] = now
    ready = obs.get('ready') or {}
    fresh = bool(ready) and now - float(ready.get('ts', 0)) <= rules['ready_stale_s'] and float(ready.get('ts', 0)) >= s['on_at'] - 5
    is_ready = st == 'running' and fresh and bool(ready.get('ready'))

    # предохранители — по порядку важности
    if s['spent_usd'] >= rules['day_cap_usd']:
        return _stop(s, acts, 'cap', 'stop_cap', cap=rules['day_cap_usd'], spent=s['spent_usd'])
    if s['running_since'] and (now - s['running_since']) / 60 >= rules['max_run_min']:
        return _stop(s, acts, 'maxrun', 'stop_maxrun', min=rules['max_run_min'])
    # автостоп — от ПОСЛЕДНЕГО события (заказ в очередь ИЛИ готовая пара: оба зовут pulse), и НИКОГДА, пока есть задание в очереди/в работе:
    # исполнитель, ждущий пару, продлевает `busy_until` (pulse --busy) каждые ~15 с; умер исполнитель — метка истекает сама, остаются потолки
    idle_ref = max(s['last_activity'], s['on_at'])
    if is_ready and now >= s.get('busy_until', 0) and (now - idle_ref) / 60 >= rules['idle_stop_min']:
        return _stop(s, acts, 'idle', 'stop_idle', min=rules['idle_stop_min'], spent=s['spent_usd'])
    if s['warm_gen'] != s['gen'] and age_min >= rules['warmup_max_min']:
        return _stop(s, acts, 'warmup', 'stop_warmup', min=rules['warmup_max_min'])

    # потеря машины: группа остановлена/упала, а мы хотим «включено»
    if st in ('stopped', 'failed') and now - s['on_at'] > 20:
        if now - s['last_start_try'] >= rules['start_retry_s']:
            if s['running_since'] or s['restarts']:      # была запущена (или уже перезапускали) и снова остановилась — это потеря, не «ещё создаётся»
                if s['restarts'] >= rules['restart_max']:
                    return _stop(s, acts, 'lost', 'gave_up', max=rules['restart_max'])
                s['restarts'] += 1
                acts.append(('notify', 'lost', {'st': st, 'n': s['restarts'], 'max': rules['restart_max']}))
                s['running_since'] = 0
            s['last_start_try'] = now
            acts.append(('start',))
        return s, acts
    if st is None and now - s['last_start_try'] >= rules['start_retry_s']:
        s['last_start_try'] = now
        acts.append(('start',))                          # группы ещё нет (создаётся) — исполнитель создаст/запустит

    # прогрелась / деградация
    if is_ready:
        s['degraded_since'] = 0
        if s['warm_gen'] != s['gen']:
            s['warm_gen'] = s['gen']
            acts.append(('notify', 'warm', {'min': max(1, round(age_min))}))
    elif s['warm_gen'] == s['gen'] and st == 'running':  # была готова, теперь нет свежего ready.json или он ready:false
        if not s['degraded_since']:
            s['degraded_since'] = now
            why = 'GPU не виден' if ready and not ready.get('ready') else 'нет свежей отметки от машины'
            acts.append(('notify', 'degraded', {'why': why, 'min': rules['degraded_stop_min']}))
        elif (now - s['degraded_since']) / 60 >= rules['degraded_stop_min']:
            return _stop(s, acts, 'degraded', 'recovered_stop', min=rules['degraded_stop_min'])
    return s, acts


def _stop(s: dict, acts: list, reason: str, key: str, **kw) -> tuple[dict, list]:
    s['desired'] = 'off'
    s['stop_reason'] = reason
    s['running_since'] = 0
    acts.append(('stop', reason))
    if s['stop_notified_gen'] != s['gen']:               # одно сообщение о стопе на запуск
        s['stop_notified_gen'] = s['gen']
        acts.append(('notify', key, kw))
    return s, acts


# ───────────────────────── ввод-вывод ─────────────────────────
def say(*a):
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, file=sys.stderr, flush=True)


class Box:
    """Блокировка + чтение/запись состояния. Всё под одним flock: два нажатия кнопки идут по очереди."""

    def __enter__(self):
        os.makedirs(STATE_DIR, exist_ok=True)
        self.lock = open(os.path.join(STATE_DIR, 'lock'), 'w')
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.path = os.path.join(STATE_DIR, 'state.json')
        try:
            self.state = json.load(open(self.path, encoding='utf-8'))
        except (OSError, ValueError):
            self.state = new_state()
        for k, v in new_state().items():
            self.state.setdefault(k, v)
        return self

    def save(self):
        tmp = self.path + '.tmp'
        json.dump(self.state, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def __exit__(self, *a):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


class Salad:
    def __init__(self, rules: dict):
        import migrate_groups as MG
        MG.env_from_file()
        self.MG, self.r = MG, rules

    def group(self):
        code, g = self.MG.api(f"/{self.r['group']}")
        if code == 404:
            return None, None, {}
        if code != 200:
            raise RuntimeError(f'Salad GET HTTP {code}')
        cs = g.get('current_state') or {}
        return g, cs.get('status'), cs.get('instance_status_counts') or {}

    def running_count(self, cnt) -> int:
        return int(cnt.get('running_count', 0) or 0)

    def create(self, image: str) -> None:
        code, donor = self.MG.api(f"/{self.r['donor_group']}")
        if code != 200:
            raise RuntimeError(f"образец {self.r['donor_group']}: HTTP {code}")
        denv = (donor.get('container') or {}).get('environment_variables') or {}
        body = {
            'name': self.r['group'], 'display_name': self.r['group'],
            'container': {
                'image': image,
                'resources': {'cpu': self.r['cpu'], 'memory': self.r['memory_mb'], 'gpu_classes': [self.r['gpu_class_id']],
                              'storage_amount': self.r['storage_gb'] * 2 ** 30, 'shm_size': 256},
                'priority': self.r['tier'],
                'environment_variables': {'MESH_SINK_URL': denv['MESH_SINK_URL'], 'MESH_SINK_TOKEN': denv['MESH_SINK_TOKEN'],
                                          'AGENT_PREFIX': self.r['sink_prefix'], 'NVIDIA_DRIVER_CAPABILITIES': 'all',
                                          'DEPLOYMENT_EPOCH': time.strftime('%Y%m%d', time.gmtime())},
                'image_caching': True,
                'registry_authentication': self.MG.ghcr_auth(),
            },
            'autostart_policy': False, 'restart_policy': 'never', 'replicas': 1, 'priority': self.r['tier'],
        }
        code, d = self.MG.api('', 'POST', body)
        if code not in (200, 201):
            raise RuntimeError(f'создание группы HTTP {code} {str(d)[:120]}')

    def start(self) -> int:
        return self.MG.api(f"/{self.r['group']}/start", 'POST')[0]

    def stop(self) -> int:
        return self.MG.api(f"/{self.r['group']}/stop", 'POST')[0]


def read_ready(rules: dict) -> dict | None:
    """ready.json от машины. Свежесть — по времени файла НА СЕРВЕРЕ (`ts` кладём из mtime): часы контейнера не участвуют."""
    p = f"{SINK_ROOT}/{rules['sink_prefix']}/.staging/ready.json"
    try:
        r = subprocess.run(SERVER + [f'stat -c %Y {p} 2>/dev/null && cat {p}'], capture_output=True, text=True, timeout=40)
        first, _, body = r.stdout.partition('\n')
        d = json.loads(body)
        d['ts'] = float(first)
        return d
    except (subprocess.SubprocessError, ValueError):
        return None


def beat_server(rules: dict, now: float) -> bool:
    """Отметка для сторожа на сервере: файл `controller.json` (время — по mtime)."""
    d = f"{SINK_ROOT}/{rules['sink_prefix']}/.staging"
    try:
        r = subprocess.run(SERVER + [f"mkdir -p {d} && echo '{{\"ts\": {now:.0f}}}' > {d}/controller.json"], capture_output=True, text=True, timeout=40)
        return r.returncode == 0
    except subprocess.SubprocessError:
        return False


def alert(rules: dict, text: str) -> bool:
    if os.environ.get('RENDER_MACHINE_DRY'):
        print('[сухо, сообщение владельцу]', text, flush=True)
        return True
    try:
        return subprocess.run(['bash', rules['alert_sh'], text], timeout=300).returncode == 0
    except subprocess.SubprocessError:
        return False


def stop_and_verify(sal: Salad, timeout_s: int = 240) -> bool:
    code = sal.stop()
    say('stop HTTP', code)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            _, st, cnt = sal.group()
        except RuntimeError:
            st, cnt = None, {}
        n = sum(int(cnt.get(k, 0) or 0) for k in ('allocating_count', 'creating_count', 'running_count', 'stopping_count'))
        if st in ('stopped', None) and n == 0:
            return True
        time.sleep(8)
    return False


def observe(sal: Salad, rules: dict, with_ready: bool = True) -> dict:
    g, st, cnt = sal.group()
    return {'status': st if g else None, 'running': sal.running_count(cnt), 'exists': g is not None, 'group': g,
            'ready': read_ready(rules) if (with_ready and st == 'running') else None, 'price': price_usd_h(rules)}


def image_of(rules: dict) -> str:
    img = rules.get('image') or ''
    if not img:
        raise RuntimeError('в rules/salad-groups.json → render_machine.image не задан образ (digest)')
    return img


def start_or_create(sal: Salad, rules: dict, obs: dict) -> str:
    """Возвращает пустую строку при успехе или причину отказа. Образ существующей группы должен совпадать с правилами."""
    img = image_of(rules)
    if not obs['exists']:
        sal.create(img)
        return ''                                         # создаётся (бывает pending до 10 мин) — /start доберёт tick
    cur = (obs['group'].get('container') or {}).get('image')
    if cur and cur != img:
        return 'image'
    if obs['status'] in ('stopped', 'failed', None):
        code = sal.start()
        say('start HTTP', code)
        if code >= 400:
            return ''                                     # создаётся — повтор на ближайшей отметке
    return ''


def execute(sal: Salad, rules: dict, acts: list, lang: str, spent: float) -> list:
    out = []
    for a in acts:
        if a[0] == 'notify':
            txt = tr(a[1], lang, **{'spent': spent, 'cap': rules['day_cap_usd'], **a[2]})
            alert(rules, txt)
            out.append(txt)
        elif a[0] == 'stop':
            ok = stop_and_verify(sal)
            say('остановка', a[1], 'подтверждена' if ok else 'НЕ подтверждена')
        elif a[0] == 'start':
            try:
                start_or_create(sal, rules, observe(sal, rules, with_ready=False))
            except Exception as e:  # noqa: BLE001 — не роняем отметку; повтор на следующей минуте
                say('start ОШИБКА', type(e).__name__, str(e)[:160])
    return out


# ───────────────────────── команды ─────────────────────────
def cmd_on(a, rules) -> str:
    sal = Salad(rules)
    with Box() as b:
        s = b.state
        now = time.time()
        obs = observe(sal, rules, with_ready=False)
        _acc(s, now, obs['status'] in PAID, obs['price'])
        if s['spent_usd'] >= rules['day_cap_usd']:
            b.save()
            return tr('on_refused_cap', a.lang, cap=rules['day_cap_usd'], spent=s['spent_usd'])
        if s['desired'] == 'on' and obs['status'] in PAID:
            b.save()
            return tr('on_already', a.lang, st=obs['status'])
        if obs['status'] in LIVE:                         # жива мимо контроллера — берём под управление без перезапуска
            s.update(desired='on', gen=s['gen'] + 1, by=a.by, at=now, on_at=now, last_activity=now, running_since=0, warm_gen=0,
                     degraded_since=0, restarts=0, stop_reason='')
            b.save()
            return tr('on_already', a.lang, st=obs['status'])
        try:
            why = start_or_create(sal, rules, obs)
        except Exception as e:  # noqa: BLE001
            return tr('on_error', a.lang, why=f'{type(e).__name__}: {str(e)[:120]}')
        if why == 'image':
            return tr('on_refused_image', a.lang, g=rules['group'])
        s.update(desired='on', gen=s['gen'] + 1, by=a.by, at=now, on_at=now, last_activity=now, running_since=0, warm_gen=0, degraded_since=0,
                 restarts=0, stop_reason='', last_start_try=now, accrued_ts=now)
        b.save()
        beat_server(rules, now)
        return tr('on_started', a.lang)


def cmd_off(a, rules) -> str:
    sal = Salad(rules)
    with Box() as b:
        s = b.state
        now = time.time()
        obs = observe(sal, rules, with_ready=False)
        _acc(s, now, obs['status'] in PAID, obs['price'])
        was_live = obs['status'] in PAID
        s.update(desired='off', by=a.by, at=now, running_since=0)
        if was_live:
            s['stop_reason'] = 'manual'
        if not was_live:
            b.save()
            return tr('off_already', a.lang, spent=s['spent_usd'])
        ok = stop_and_verify(sal)
        _, st, _ = sal.group()
        _acc(s, time.time(), False, obs['price'])
        b.save()
        return tr('off_done' if ok else 'off_unconfirmed', a.lang, spent=s['spent_usd'])


def cmd_status(a, rules) -> str:
    sal = Salad(rules)
    with Box() as b:
        s = b.state
        now = time.time()
        obs = observe(sal, rules)
        d = london_date(now)
        spent = s['spent_usd'] if s['spent_date'] == d else 0.0
        if a.json:
            return json.dumps({'desired': s['desired'], 'gen': s['gen'], 'status': obs['status'], 'spent_usd': spent, 'by': s['by']}, ensure_ascii=False)
        if s['desired'] != 'on':
            # желаемое «выключено»: пока Salad её не остановил (или её запустил кто-то мимо контроллера) — это не «не отвечает»: возраст `on_at` тут ни при чём
            if obs['status'] not in PAID:
                return tr('st_off', a.lang, spent=spent, cap=rules['day_cap_usd'])
            return tr('st_stray', a.lang, st=obs['status'], spent=spent)
        age = round((now - s['on_at']) / 60)
        ready = obs.get('ready') or {}
        fresh = bool(ready) and now - float(ready.get('ts', 0)) <= rules['ready_stale_s']
        if s['warm_gen'] == s['gen'] and obs['status'] == 'running' and fresh and ready.get('ready'):
            left = max(0, round(rules['idle_stop_min'] - (now - max(s['last_activity'], s['on_at'])) / 60))
            return tr('st_ready', a.lang, age=age, left=left, spent=spent, cap=rules['day_cap_usd'])
        if s['warm_gen'] == s['gen']:
            return tr('st_degraded', a.lang, age=age, spent=spent)
        return tr('st_starting', a.lang, st=obs['status'] or 'создаётся', age=age, spent=spent)


def pulse(busy_s: float = 0.0, now: float | None = None) -> None:
    """Событие по заказу: последняя активность = сейчас. busy_s>0 — «задание в работе»: автостоп не сработает, пока не истекут busy_s секунд
    (ждущий исполнитель обновляет метку); busy_s=0 — задание кончилось, метка сброшена, отсчёт простоя идёт с этого момента."""
    now = time.time() if now is None else now
    with Box() as b:
        b.state['last_activity'] = now
        b.state['busy_until'] = now + busy_s if busy_s > 0 else 0
        b.save()


def cmd_pulse(a, rules) -> str:
    pulse(a.busy)
    return 'ok'


def cmd_tick(a, rules) -> str:
    with Box() as b:
        now = time.time()
        beat_server(rules, now)                           # отметка для сторожа — первой: контроллер жив, даже если Salad не ответил
        try:
            sal = Salad(rules)
            obs = observe(sal, rules)
        except Exception as e:  # noqa: BLE001
            return f'tick: Salad недоступен ({type(e).__name__}) — состояние не менял'
        s, acts = plan(b.state, obs, rules, now)
        b.state = s
        b.save()
        execute(sal, rules, acts, 'ru', s['spent_usd'])
        if any(x[0] == 'stop' for x in acts):
            _, st, _ = sal.group()
            if st in ('stopped', None):                   # подтверждённый стоп закрывает расход
                _acc(b.state, time.time(), False, obs['price'])
        b.save()
        return f"tick: желаемое={s['desired']} статус={obs['status']} действия={[x[0] for x in acts]} потрачено=${s['spent_usd']:.3f}"


def main() -> int:
    ap = argparse.ArgumentParser(description='Контроллер машины рендера на Salad (см. docstring)')
    ap.add_argument('cmd', choices=['on', 'off', 'status', 'pulse', 'tick'])
    ap.add_argument('--by', default='cli')
    ap.add_argument('--lang', default='ru', choices=['ru', 'en'])
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--busy', type=float, default=0.0, help='pulse: секунд «задание в работе» (автостоп не сработает)')
    a = ap.parse_args()
    rules = load_rules()
    try:
        print({'on': cmd_on, 'off': cmd_off, 'status': cmd_status, 'pulse': cmd_pulse, 'tick': cmd_tick}[a.cmd](a, rules))
    except Exception as e:  # noqa: BLE001 — кнопке бота нужна одна понятная строка, а не трассировка
        print(tr('on_error', a.lang, why=f'{type(e).__name__}: {str(e)[:160]}'))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
