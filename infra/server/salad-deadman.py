#!/usr/bin/env python3
"""Мёртвая рука Salad на СЕРВЕРЕ (план conv-11, ADR-0274): DEV пропал посреди волны — группы гасит сервер.

ЗАЧЕМ. Конвейер мешей и его сторожа (idle_guard, money_guard) живут на домашнем компьютере. Выключили его посреди
волны — группы Salad крутятся и платятся, гасить некому (найдено 13.10, `domain/deployment-details.md` § «без DEV»).

КАК. Пока конвейер держит свой замок, DEV раз в 3 минуты ставит отметку `/opt/remlab/mesh/heartbeat`
(`tools/scout/salad/heartbeat.sh`). Сторож (таймер `remlab-salad-deadman`, раз в 10 мин): есть группы проекта не в
`stopped`, а отметке больше 30 минут → `/stop` каждой, ждём `stopped` (до 4 мин), сообщение в Telegram. Ручная работа на
Salad без конвейера — файл `/opt/remlab/mesh/deadman-off-until` с датой-временем окончания (ISO) — сторож молчит.
Ключ — отдельного участника команды Salad, `/etc/remlab/salad.key` (root, 600), не общий `.env`.

  /opt/remlab/scripts/salad-deadman.py            # обычный заход
  DRY=1 /opt/remlab/scripts/salad-deadman.py      # решение без /stop и без Telegram
  python3 salad-deadman.py --selftest
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

API = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'
KEY_FILE = os.environ.get('SALAD_KEY_FILE', '/etc/remlab/salad.key')
HB = os.environ.get('MESH_HEARTBEAT', '/opt/remlab/mesh/heartbeat')
INHIBIT = os.environ.get('MESH_DEADMAN_OFF', '/opt/remlab/mesh/deadman-off-until')
STATE = os.environ.get('MESH_DEADMAN_STATE', '/opt/remlab/mesh/deadman-state.json')
TG_ENV = '/opt/remlab/catalog-watchdog/.env'
STALE_S = int(os.environ.get('MESH_DEADMAN_STALE_MIN', '30')) * 60
DOWN = ('stopped', 'failed')


def decide(groups: dict, hb_age_s: float | None, inhibit_until: float | None, now: float) -> tuple[str, list]:
    """→ (решение, группы к остановке). Чистая функция: проверяется селфтестом."""
    live = sorted(g for g, st in groups.items() if st not in DOWN)
    if not live:
        return 'idle', []
    if inhibit_until and inhibit_until > now:
        return 'inhibited', []
    if hb_age_s is not None and hb_age_s < STALE_S:
        return 'conveyor_alive', []
    return 'stop', live


def _req(path: str, key: str, method: str = 'GET') -> dict:
    r = urllib.request.Request(API + path, data=b'' if method == 'POST' else None, method=method,
                               headers={'Salad-Api-Key': key, 'User-Agent': 'remlab-deadman/1.0'})
    with urllib.request.urlopen(r, timeout=30) as f:
        body = f.read()
    return json.loads(body) if body else {}


def groups(key: str) -> dict:
    return {i['name']: (i.get('current_state') or {}).get('status') for i in _req('', key).get('items', [])}


def tg(text: str) -> None:
    env = {}
    try:
        for ln in open(TG_ENV, encoding='utf-8'):
            if '=' in ln and not ln.startswith('#'):
                k, v = ln.strip().split('=', 1)
                env[k] = v.strip().strip('"').strip("'")
        data = urllib.parse.urlencode({'chat_id': env['TG_CHAT_ID'], 'text': text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{env['TG_BOT_TOKEN']}/sendMessage", data=data, timeout=20).read()
    except Exception as e:  # noqa: BLE001 — недоставка не отменяет остановку, но видна в журнале
        print(f'TG FAIL: {type(e).__name__}', flush=True)


def main() -> int:
    import urllib.parse  # noqa: F401 — tg() кодирует форму
    now = time.time()
    key = open(KEY_FILE, encoding='utf-8').read().strip()
    gs = groups(key)
    hb_age = now - os.path.getmtime(HB) if os.path.exists(HB) else None
    inh = None
    if os.path.exists(INHIBIT):
        try:
            inh = datetime.fromisoformat(open(INHIBIT, encoding='utf-8').read().strip()).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            inh = None
    verdict, todo = decide(gs, hb_age, inh, now)
    hb_txt = 'нет отметки' if hb_age is None else f'{hb_age / 60:.0f} мин назад'
    print(f'{datetime.now(timezone.utc):%F %T} группы {gs}; конвейер: {hb_txt}; решение: {verdict}', flush=True)
    if verdict != 'stop' or os.environ.get('DRY'):
        return 0
    for g in todo:
        try:
            _req(f'/{g}/stop', key, 'POST')
        except Exception as e:  # noqa: BLE001
            print(f'stop {g}: {type(e).__name__} {str(e)[:80]}', flush=True)
    left = list(todo)
    for _ in range(16):                                   # до 4 минут ждём stopped
        time.sleep(15)
        cur = groups(key)
        left = [g for g in todo if cur.get(g) != 'stopped']
        if not left:
            break
    ok = not left
    tg(('⚠️ Меши: домашний компьютер не отвечает (' + hb_txt + '), а на Salad работали группы ' + ', '.join(todo) +
        ' — сервер их ' + ('остановил, остановка подтверждена.' if ok else 'пытался остановить, НЕ остановились: ' + ', '.join(left) +
                           ' — идёт оплата, проверьте портал Salad.')))
    json.dump({'at': now, 'stopped': todo, 'left': left}, open(STATE, 'w'))
    return 0 if ok else 1


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    now = 1_000_000.0
    ok('всё остановлено — делать нечего', decide({'a': 'stopped', 'b': 'failed'}, None, None, now) == ('idle', []))
    ok('группа работает, конвейер жив (отметка 5 мин) — не трогаем', decide({'a': 'running'}, 300, None, now)[0] == 'conveyor_alive')
    ok('группа работает, отметке 40 мин — гасим', decide({'a': 'running', 'b': 'stopped'}, 2400, None, now) == ('stop', ['a']))
    ok('группа работает, отметки нет вовсе — гасим', decide({'a': 'deploying'}, None, None, now) == ('stop', ['a']))
    ok('ручная работа (отсрочка) — молчим', decide({'a': 'running'}, None, now + 600, now)[0] == 'inhibited')
    ok('просроченная отсрочка не мешает', decide({'a': 'running'}, None, now - 1, now)[0] == 'stop')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())
