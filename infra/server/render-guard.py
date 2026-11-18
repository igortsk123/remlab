#!/usr/bin/env python3
"""СТОРОЖ РЕНДЕР-МАШИНЫ (T-20261117-24/1, план render-machine-01 п.5). Крон на сервере, как `salad-deadman.py` для мешей, но ТОЛЬКО `render-*`.

Правило: контроллер (`tools/scout/render_gpu/render_machine.py tick`, DEV) раз в минуту кладёт отметку `controller.json` на приёмник; не отмечался
дольше `RENDER_GUARD_STALE_MIN` (10) минут — контроллер умер, а машина (платная) может работать вхолостую → гасим живые `render-*` группы и пишем
владельцу. Меш-группы НЕ трогаем (их ведёт `salad-deadman.py`), VPN-нода вне Salad.

Крон (строку ставит директор): `* * * * *  root  /usr/bin/python3 /opt/remlab/scripts/render-guard.py >> /var/log/render-guard.log 2>&1`
Сухо: `RENDER_GUARD_DRY=1 python3 render-guard.py` (ничего не гасит и не шлёт). Отключить на время ручной работы: файл `RENDER_GUARD_OFF` с временем UNIX,
до которого сторож молчит. Селфтест без сети: `python3 render-guard.py --selftest`.
ГРУППА БЕЗ ХОЗЯИНА (T-20261118-09/6, 18.11: после смены группы в правилах прежняя m7 осталась работать, пока контроллер вёл m11 и сам был жив): контроллер на каждой отметке
кладёт ещё `controller-<группа>.json` — «эту группу веду я». Живая `render-*` группа, у которой такой отметки нет свежее `RENDER_GUARD_OWNER_MIN` (3) минут, пока ОБЩАЯ отметка жива, —
«сирота»; сирота подряд дольше `RENDER_GUARD_ORPHAN_MIN` (3) минут гасится (время первого наблюдения — файл `RENDER_GUARD_ORPHANS`). Отметок по группам нет вовсе (контроллер
старый) — сирот не ищем. Опытная группа, которую ведёт другой экземпляр контроллера (свой каталог состояния), отмечается так же и сиротой не считается; вручную включённую
`render-*` на опыты — отключить сторожа файлом `RENDER_GUARD_OFF`.
Стоп-запрос — POST `/stop`, итог проверяется повторным чтением списка на следующей минуте (крон) — тут только одна попытка и громкий журнал."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

API = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'
KEY_FILE = os.environ.get('SALAD_KEY_FILE', '/etc/remlab/salad.key')
BEAT = os.environ.get('RENDER_CONTROLLER_BEAT', '/opt/remlab/meshes/rendermachine/.staging/controller.json')
OFF = os.environ.get('RENDER_GUARD_OFF', '/opt/remlab/render-guard-off-until')
BEAT_DIR = os.path.dirname(BEAT)
ORPHANS = os.environ.get('RENDER_GUARD_ORPHANS', '/opt/remlab/render-guard-orphans.json')
OWNER_S = int(os.environ.get('RENDER_GUARD_OWNER_MIN', '3')) * 60
ORPHAN_S = int(os.environ.get('RENDER_GUARD_ORPHAN_MIN', '3')) * 60
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


def decide_orphans(groups: dict, owner_age: dict, beat_age_s, first_seen: dict, off_until, now: float):
    """Группы без хозяина. groups — {имя: (статус, машин|None)}; owner_age — {группа: возраст отметки «веду я», с} (пусто — отметок по группам нет вовсе);
    first_seen — {группа: время, когда впервые увидели сиротой}. → (к остановке, новые first_seen). Чистая функция.
    Сирота: живая guarded-группа без свежей своей отметки, при ЖИВОЙ общей отметке контроллера (мёртвый контроллер — дело `decide`) и при непустом owner_age."""
    live = sorted(g for g, (st, n) in groups.items() if guarded(g) and is_live(st, n))
    if not owner_age or beat_age_s is None or beat_age_s >= STALE_S or (off_until and off_until > now):
        return [], {}
    orphans = [g for g in live if owner_age.get(g) is None or owner_age[g] >= OWNER_S]
    seen = {g: first_seen.get(g, now) for g in orphans}            # не сирота (больше) — выпадает из списка
    return [g for g in orphans if now - seen[g] >= ORPHAN_S], seen


def owner_ages() -> dict:
    """{группа: возраст отметки controller-<группа>.json, с} (по mtime)."""
    out = {}
    try:
        names = os.listdir(BEAT_DIR)
    except OSError:
        return out
    now = time.time()
    for n in names:
        if n.startswith('controller-') and n.endswith('.json'):
            try:
                out[n[len('controller-'):-len('.json')]] = now - os.path.getmtime(os.path.join(BEAT_DIR, n))
            except OSError:
                pass
    return out


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
        return orphan_pass(gs, age, off, now, key, dry, stamp)
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


def orphan_pass(gs: dict, age, off, now: float, key: str, dry: bool, stamp: str) -> int:
    try:
        seen0 = json.load(open(ORPHANS, encoding='utf-8'))
    except (OSError, ValueError):
        seen0 = {}
    oa = owner_ages()
    to_stop, seen = decide_orphans(gs, oa, age, seen0 if isinstance(seen0, dict) else {}, off, now)
    if not dry:
        try:
            json.dump(seen, open(ORPHANS, 'w', encoding='utf-8'))
        except OSError as e:
            print(f'{stamp} не записал {ORPHANS}: {e}', flush=True)
    if seen:
        print(f"{stamp} без хозяина: {', '.join(f'{g} {int(now - t)} с' for g, t in sorted(seen.items()))}; хозяева: {', '.join(f'{g} {int(a)} с' for g, a in sorted(oa.items())) or 'нет'}", flush=True)
    if not to_stop:
        return 0
    if dry:
        print('СУХО: погасил бы группы без хозяина', to_stop, flush=True)
        return 0
    done = []
    for g in to_stop:
        try:
            _req(f'/{urllib.parse.quote(g)}/stop', key, 'POST')
            done.append(g)
            print(f'{stamp} STOP (без хозяина) {g}', flush=True)
        except Exception as e:  # noqa: BLE001
            print(f'{stamp} НЕ УДАЛОСЬ погасить {g}: {type(e).__name__} {str(e)[:100]}', flush=True)
    tg(f"❗ Сторож рендер-машины: группа без хозяина (контроллер её не ведёт, платная) — погасил {', '.join(done) or 'ничего (не вышло)'}. "
       f"Если это опыты вручную — файл отключения сторожа; смену группы в правилах контроллер гасит сам.")
    return 0 if len(done) == len(to_stop) else 1


def _selftest() -> int:
    bad = []

    def ok(name, cond):
        print(('OK   ' if cond else 'FAIL ') + name)
        if not cond:
            bad.append(name)
    now = 1_000_000.0
    run = {'render-x1': ('running', 1)}
    ok('отметка свежая → не гасим', decide(run, 60, None, now) == ('controller_alive', []))
    ok('отметка старая → гасим', decide(run, 11 * 60, None, now) == ('stop', ['render-x1']))
    ok('отметки нет → гасим', decide(run, None, None, now) == ('stop', ['render-x1']))
    ok('граница 10 мин → гасим', decide(run, 600, None, now) == ('stop', ['render-x1']))
    ok('ручное отключение → молчим', decide(run, None, now + 100, now) == ('inhibited', []))
    ok('отключение истекло → гасим', decide(run, None, now - 1, now) == ('stop', ['render-x1']))
    ok('группа остановлена → ничего', decide({'render-x1': ('stopped', 0)}, None, None, now) == ('idle', []))
    ok('pending без машин → не платим', decide({'render-x1': ('pending', 0)}, None, None, now) == ('idle', []))
    ok('deploying с машиной → платим, гасим', decide({'render-x1': ('deploying', 1)}, None, None, now) == ('stop', ['render-x1']))
    # главное: меш-группы сторож не трогает ни при каком раскладе
    mesh = {'mesh-q-low-1': ('running', 3), 'mesh-batch-7': ('deploying', 1)}
    ok('меш-группы живые, отметки нет → НЕ трогаем', decide(mesh, None, None, now) == ('idle', []))
    ok('смесь: гасим только render-*', decide({**mesh, 'render-x1': ('running', 1)}, None, None, now) == ('stop', ['render-x1']))
    ok('guarded: префикс', guarded('render-x1') and guarded('render-bench-4090') and not guarded('mesh-render-1') and not guarded('remnanode'))
    ok('machines: счётчики', machines({'instance_status_counts': {'running_count': 1, 'creating_count': 0}}) == 1 and machines({}) is None)
    # группа без хозяина (T-20261118-09/6)
    m7, m11 = ('running', 1), ('running', 1)
    gs2 = {'render-4090m7': m7, 'render-4090m11': m11}
    own = {'render-4090m11': 30.0, 'render-4090m7': 4000.0}
    st1, seen1 = decide_orphans(gs2, own, 30, {}, None, now)
    ok('сирота (m7 без свежей отметки, контроллер жив) замечена, сразу не гасим (срок 3 мин)', st1 == [] and list(seen1) == ['render-4090m7'] and seen1['render-4090m7'] == now)
    st2, seen2 = decide_orphans(gs2, own, 30, seen1, None, now + 200)
    ok('сирота подряд дольше 3 мин → гасим только её, хозяйскую m11 не трогаем', st2 == ['render-4090m7'])
    st3, seen3 = decide_orphans(gs2, {'render-4090m11': 30.0, 'render-4090m7': 20.0}, 30, seen1, None, now + 200)
    ok('у m7 снова свежая отметка (её ведёт другой экземпляр контроллера) — не сирота, счётчик сброшен', st3 == [] and seen3 == {})
    ok('отметок по группам нет вовсе (старый контроллер) — сирот не ищем', decide_orphans(gs2, {}, 30, {}, None, now) == ([], {}))
    ok('общая отметка старая — это дело decide (мёртвый контроллер), сирот не считаем', decide_orphans(gs2, own, 11 * 60, {}, None, now) == ([], {}))
    ok('ручное отключение — молчим', decide_orphans(gs2, own, 30, {'render-4090m7': now - 999}, now + 100, now) == ([], {}))
    ok('остановленная и pending без машин — не сирота', decide_orphans({'render-4090m7': ('stopped', 0), 'render-x': ('pending', 0)}, own, 30, {}, None, now) == ([], {}))
    ok('меш-группы сиротой не считаются', decide_orphans({'mesh-q-low-1': ('running', 3)}, own, 30, {}, None, now) == ([], {}))
    # разбор аргументов: --help и --selftest не трогают ключ и сеть
    ok('аргументы: без них — не selftest; --selftest — selftest', parse_args([]).selftest is False and parse_args(['--selftest']).selftest is True)
    for argv, code in ((['--help'], 0), (['--нет-такого'], 2)):
        try:
            parse_args(argv)
            rc = None
        except SystemExit as e:
            rc = e.code
        ok(f'аргументы: {argv[0]} → выход {code}', rc == code)
    env = {k: v for k, v in os.environ.items() if k != 'SALAD_KEY_FILE'} | {'SALAD_KEY_FILE': '/нет/такого/ключа'}
    r = subprocess.run([sys.executable, os.path.abspath(__file__), '--help'], capture_output=True, text=True, env=env, timeout=30)
    ok('процесс: --help → код 0, справка, без traceback, ключ не читается', r.returncode == 0 and 'usage:' in r.stdout and 'Traceback' not in r.stderr)
    print('итог:', 'чисто' if not bad else f'ПРОВАЛЕНО {len(bad)}')
    return 1 if bad else 0


def parse_args(argv: list) -> 'argparse.Namespace':
    """Разбор аргументов (T-20261118-10/9: `--help` раньше шёл в main() и падал на чтении ключа). Крон зовёт без аргументов — поведение прежнее."""
    ap = argparse.ArgumentParser(prog='render-guard.py', description=(__doc__ or '').split('\n')[0],
                                 epilog='Сухо: RENDER_GUARD_DRY=1; отключить сторожа: файл RENDER_GUARD_OFF (время UNIX). Без аргументов — один проход (как из крона).')
    ap.add_argument('--selftest', action='store_true', help='проверки без сети и без ключа')
    return ap.parse_args(argv)


if __name__ == '__main__':
    sys.exit(_selftest() if parse_args(sys.argv[1:]).selftest else main())
