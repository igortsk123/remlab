#!/usr/bin/env python3
"""СТОРОЖ РЕНДЕР-МАШИНЫ (T-20261117-24/1, план render-machine-01 п.5). Крон на сервере, как `salad-deadman.py` для мешей, но ТОЛЬКО `render-*`.

Правило: контроллер (`tools/scout/render_gpu/render_machine.py tick`, DEV) раз в минуту кладёт отметку `controller.json` на приёмник; не отмечался
дольше `RENDER_GUARD_STALE_MIN` (10) минут — контроллер умер, а машина (платная) может работать вхолостую → гасим живые `render-*` группы и пишем
владельцу. Меш-группы НЕ трогаем (их ведёт `salad-deadman.py`), VPN-нода вне Salad.

Крон (строку ставит директор): `* * * * *  root  /usr/bin/python3 /opt/remlab/scripts/render-guard.py >> /var/log/render-guard.log 2>&1`
Сухо: `RENDER_GUARD_DRY=1 python3 render-guard.py` (ничего не гасит и не шлёт). Отключить на время ручной работы: файл `RENDER_GUARD_OFF` с временем UNIX,
до которого сторож молчит. Селфтест без сети: `python3 render-guard.py --selftest`.
Стоп-запрос — POST `/stop`, итог проверяется повторным чтением списка на следующей минуте (крон) — тут только одна попытка и громкий журнал."""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'
KEY_FILE = os.environ.get('SALAD_KEY_FILE', '/etc/remlab/salad.key')
BEAT = os.environ.get('RENDER_CONTROLLER_BEAT', '/opt/remlab/meshes/rendermachine/.staging/controller.json')
OFF = os.environ.get('RENDER_GUARD_OFF', '/opt/remlab/render-guard-off-until')
TG_ENV = '/opt/remlab/catalog-watchdog/.env'
STALE_S = int(os.environ.get('RENDER_GUARD_STALE_MIN', '10')) * 60
PREFIXES = tuple(p.strip() for p in os.environ.get('RENDER_GUARD_PREFIXES', 'render-').split(',') if p.strip())
DOWN = ('stopped', 'failed')
PAID = ('allocating', 'creating', 'running', 'stopping')


def machines(state: dict):
    counts = state.get('instance_status_counts')
    if not isinstance(counts, dict):
        return None
    got = [counts.get(f'{k}_count', counts.get(k)) for k in PAID]
    if all(v is None for v in got):
        return None
    return sum(int(v or 0) for v in got)


def is_live(status, n) -> bool:
    """Платим: группа не в stopped/failed и есть машины; `pending` (создаётся) без машин — не платим."""
    return status not in DOWN and (n is None or n > 0) and status != 'pending'


def guarded(name: str) -> bool:
    return name.startswith(PREFIXES)


def decide(groups: dict, beat_age_s, off_until, now: float):
    """groups — {имя: (статус, машин|None)} ТОЛЬКО render-*. → (решение, группы к остановке). Чистая функция.
    idle — живых нет; inhibited — ручное отключение; controller_alive — отметка свежая; stop — отметки нет/старая, гасим живые."""
    live = sorted(g for g, (st, n) in groups.items() if guarded(g) and is_live(st, n))
    if not live:
        return 'idle', []
    if off_until and off_until > now:
        return 'inhibited', []
    if beat_age_s is not None and beat_age_s < STALE_S:
        return 'controller_alive', []
    return 'stop', live


def _req(path: str, key: str, method: str = 'GET') -> dict:
    r = urllib.request.Request(API + path, data=b'' if method == 'POST' else None, method=method,
                               headers={'Salad-Api-Key': key, 'User-Agent': 'remlab-render-guard/1.0'})
    with urllib.request.urlopen(r, timeout=30) as f:
        body = f.read()
    return json.loads(body) if body else {}


def groups(key: str) -> dict:
    out = {}
    for i in _req('', key).get('items', []):
        if guarded(i['name']):
            st = i.get('current_state') or {}
            out[i['name']] = (st.get('status'), machines(st))
    return out


def tg(text: str) -> None:
    env = {}
    try:
        for ln in open(TG_ENV, encoding='utf-8'):
            if '=' in ln and not ln.startswith('#'):
                k, v = ln.strip().split('=', 1)
                env[k] = v.strip().strip('"').strip("'")
        data = urllib.parse.urlencode({'chat_id': env['TG_CHAT_ID'], 'text': text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{env['TG_BOT_TOKEN']}/sendMessage", data=data, timeout=20).read()
    except Exception as e:  # noqa: BLE001 — недоставка не отменяет остановку
        print(f'TG FAIL: {type(e).__name__}', flush=True)


def main() -> int:
    now = time.time()
    dry = bool(os.environ.get('RENDER_GUARD_DRY'))
    key = open(KEY_FILE, encoding='utf-8').read().strip()
    gs = groups(key)
    age = now - os.path.getmtime(BEAT) if os.path.exists(BEAT) else None
    try:
        off = float(open(OFF, encoding='utf-8').read().strip()) if os.path.exists(OFF) else None
    except ValueError:
        off = None
    verdict, to_stop = decide(gs, age, off, now)
    stamp = time.strftime('%F %T', time.localtime(now))
    txt = ', '.join(f"{g} {st}/{'?' if n is None else n}" for g, (st, n) in sorted(gs.items())) or 'нет'
    print(f"{stamp} render-группы: {txt}; отметка контроллера: {'нет файла' if age is None else f'{age / 60:.1f} мин назад'}; решение: {verdict}", flush=True)
    if verdict != 'stop':
        return 0
    if dry:
        print('СУХО: погасил бы', to_stop, flush=True)
        return 0
    done = []
    for g in to_stop:
        try:
            _req(f'/{urllib.parse.quote(g)}/stop', key, 'POST')
            done.append(g)
            print(f'{stamp} STOP {g}', flush=True)
        except Exception as e:  # noqa: BLE001
            print(f'{stamp} НЕ УДАЛОСЬ погасить {g}: {type(e).__name__} {str(e)[:100]}', flush=True)
    tg(f"❗ Сторож рендер-машины: контроллер не отмечался больше {STALE_S // 60} мин — погасил {', '.join(done) or 'ничего (не вышло)'}. "
       f"Если машина нужна — /render_on (контроллер проверить: render_machine.py tick на DEV).")
    return 0 if len(done) == len(to_stop) else 1


def _selftest() -> int:
    bad = []

    def ok(name, cond):
        print(('OK   ' if cond else 'FAIL ') + name)
        if not cond:
            bad.append(name)
    now = 1_000_000.0
    run = {'render-3090': ('running', 1)}
    ok('отметка свежая → не гасим', decide(run, 60, None, now) == ('controller_alive', []))
    ok('отметка старая → гасим', decide(run, 11 * 60, None, now) == ('stop', ['render-3090']))
    ok('отметки нет → гасим', decide(run, None, None, now) == ('stop', ['render-3090']))
    ok('граница 10 мин → гасим', decide(run, 600, None, now) == ('stop', ['render-3090']))
    ok('ручное отключение → молчим', decide(run, None, now + 100, now) == ('inhibited', []))
    ok('отключение истекло → гасим', decide(run, None, now - 1, now) == ('stop', ['render-3090']))
    ok('группа остановлена → ничего', decide({'render-3090': ('stopped', 0)}, None, None, now) == ('idle', []))
    ok('pending без машин → не платим', decide({'render-3090': ('pending', 0)}, None, None, now) == ('idle', []))
    ok('deploying с машиной → платим, гасим', decide({'render-3090': ('deploying', 1)}, None, None, now) == ('stop', ['render-3090']))
    # главное: меш-группы сторож не трогает ни при каком раскладе
    mesh = {'mesh-q-low-1': ('running', 3), 'mesh-batch-7': ('deploying', 1)}
    ok('меш-группы живые, отметки нет → НЕ трогаем', decide(mesh, None, None, now) == ('idle', []))
    ok('смесь: гасим только render-*', decide({**mesh, 'render-3090': ('running', 1)}, None, None, now) == ('stop', ['render-3090']))
    ok('guarded: префикс', guarded('render-3090') and guarded('render-bench-4090') and not guarded('mesh-render-1') and not guarded('remnanode'))
    ok('machines: счётчики', machines({'instance_status_counts': {'running_count': 1, 'creating_count': 0}}) == 1 and machines({}) is None)
    print('итог:', 'чисто' if not bad else f'ПРОВАЛЕНО {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())
