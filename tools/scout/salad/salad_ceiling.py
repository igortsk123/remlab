#!/usr/bin/env python3
"""ВОРОТА ПРЕДЕЛА ЖИВЫХ МАШИН SALAD — одно место для всех, кто создаёт или стартует группу (владелец TG 1754/2626: ≤10 машин, только low).

ЗАЧЕМ. 24.11 20:08 на Salad было 12 живых машин при пределе 10: предел проверял только `tools/assets/loop5.py` и один раз при старте прогона;
`kit_driver`/`stage_trial` при создании группы его не смотрели, три прогона в одно окно каждый видели «свободно». Теперь перед КАЖДЫМ созданием
(и стартом) группы — `admit`: под общим замком читаем живые машины ВСЕХ групп аккаунта (свои тёплые тоже считаются) и то, что другие процессы
уже заняли, но Salad ещё не показывает (резерв). Выйдет больше предела — отказ, группа не создаётся. Не прочитали список (503, обрыв) — тоже отказ.

ЧИСЛА. Предел — `salad_ceiling` из `tools/scout/rules/loop5.json` (одно правило), срок резерва — `salad_reserve_ttl_s` оттуда же. В коде чисел нет.
ЗАМОК И РЕЗЕРВ — файлы в `$SALAD_CEILING_DIR` (по умолчанию `~/remlab-logs/warm-nodes/`): `salad-ceiling.lock` (flock) и `salad-ceiling-reserved.json`
{группа: {need, ts}}. Резерв живёт, пока группа не погашена (`release` в stop_and_verify) или не истёк срок; группу, уже видимую в списке, считаем
по большему из «видно» и «зарезервировано» (create → pending 1 машина, а нужно replicas). Замок и резерв локальны для машины; общий для всех — список Salad.
Сети здесь нет: список групп приходит через `MG.api('')` вызывающего (тесты подставляют поддельный).

СТОП СЕРИИ (T-20261124-58/3, ночь 24.11: повтор B р.5 погашен штатно, а драйверы серии жили до своего timeout и САМИ пересоздали группы `…m` — 12 живых при пределе 10).
Серия — ключ (`--series`, у loop5 — его run-id; без него — `SALAD_SERIES` из окружения). Штатный стоп серии (`salad_ceiling.py --stop-series КЛЮЧ`, `stage_trial.py --stop-series КЛЮЧ`)
пишет МЕТКУ — файл `series-stop/<ключ>.json` рядом с замком. Ворота `admit` читают её перед КАЖДЫМ созданием/стартом группы, драйвер — ещё и на каждом шаге цикла заданий:
метка есть → группа не создаётся, драйвер гасит свои группы с проверкой «0 нод» и выходит САМ (ни kill, ни pkill).
Метка действует только на процессы, запущенные ДО неё (`ts ≥ момент старта процесса`): новая серия с тем же ключом стартует позже — метку не видит, удалять её не надо (удаление сняло бы стоп с ещё живых старых драйверов).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.normpath(os.path.join(HERE, '..', 'rules', 'loop5.json'))
DEFAULT_DIR = '~/remlab-logs/warm-nodes'
LOCK_WAIT_S = 120
REFUSED = 429                                   # псевдокод отказа ворот в (код, ответ, повторы) api_retry; настоящий 429 у Salad тут не используем


_T0 = time.time()                               # старт процесса: метка серии старше него — не про нас
_BOUND: dict = {'key': '', 'since': 0.0}
SERIES_SUBDIR = 'series-stop'


def ceiling_dir(d: str | None = None) -> str:
    return os.path.expanduser(d or os.environ.get('SALAD_CEILING_DIR') or DEFAULT_DIR)


def _test_process(d: str | None) -> bool:
    """Тесты репозитория гоняют драйвер на подставных группах (их MG не умеет отдавать список групп) — ворота им не нужны и в настоящую папку замка писать нельзя.
    Папка задана явно (`d` или SALAD_CEILING_DIR) — это тест самих ворот, они работают."""
    if d or os.environ.get('SALAD_CEILING_DIR'):
        return False
    return os.path.basename(sys.argv[0] or '').startswith(('tests_', 'test_'))


def bind_series(key: str, now: float | None = None) -> None:
    """Драйвер объявляет свою серию (`--series`): с этого момента ворота этого процесса видят метку стопа серии. Пустой ключ — серия не задана (метки не читаются)."""
    _BOUND['key'], _BOUND['since'] = str(key or ''), (time.time() if now is None else float(now))


def series_key() -> str:
    return _BOUND['key'] or os.environ.get('SALAD_SERIES', '')


def _series_path(key: str, d: str | None) -> str:
    return os.path.join(ceiling_dir(d), SERIES_SUBDIR, re.sub(r'[^A-Za-z0-9._-]', '_', str(key))[:80] + '.json')


def series_stop(key: str, d: str | None = None, reason: str = '', now: float | None = None) -> str:
    """Штатный стоп серии: записать метку. Возвращает путь файла. Драйверы серии сами погасят свои группы и выйдут."""
    p = _series_path(key, d)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f'{p}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'key': str(key), 'ts': time.time() if now is None else float(now), 'reason': reason, 'by_pid': os.getpid()}, f, ensure_ascii=False)
    os.replace(tmp, p)
    return p


def series_stopped(key: str | None = None, since: float | None = None, d: str | None = None) -> str:
    """Причина стопа, если серия `key` (по умолчанию — серия процесса) остановлена ПОСЛЕ старта этого процесса; иначе пустая строка. Не читается метка — «не стоп» (не бросает)."""
    key = key or series_key()
    if not key or _test_process(d):
        return ''
    if since is None:
        since = _BOUND['since'] if _BOUND['key'] == key else _T0
    try:
        with open(_series_path(key, d), encoding='utf-8') as f:
            m = json.load(f)
        if float(m.get('ts', 0)) >= float(since):
            return f'серия {key} остановлена командой стопа серии ({m.get("reason") or "без причины"})'
    except (OSError, ValueError, TypeError):
        pass
    return ''


def series_clear(key: str, d: str | None = None) -> bool:
    """Убрать метку (ручная уборка; новой серии с тем же ключом это не нужно — она старше метки не бывает)."""
    try:
        os.remove(_series_path(key, d))
        return True
    except OSError:
        return False


def load_rules(path: str | None = None) -> dict:
    with open(path or RULES, encoding='utf-8') as f:
        return json.load(f)


def ceiling(rules: dict | None = None) -> int:
    return int((rules or load_rules()).get('salad_ceiling', 10))


def live_by_group(items) -> dict[str, int]:
    """{группа: живых машин} — всё, что не stopped/failed (подъём считается занятым: платная машина уже есть). Как `~/remlab-logs/router-r4/salad_live.sh`."""
    out: dict[str, int] = {}
    for x in items or []:
        cs = x.get('current_state') or {}
        ic = cs.get('instance_status_counts') or {}
        run = sum(int(ic.get(k) or 0) for k in ('allocating_count', 'creating_count', 'running_count'))
        n = max(run, 1 if cs.get('status') in ('running', 'deploying', 'pending') else 0)
        if n:
            out[str(x.get('name'))] = n
    return out


START_GRACE_S = 300


def _read_reserved(path: str, now: float, ttl: float, grace: float = START_GRACE_S) -> dict[str, dict]:
    """Живые резервы. Резерв, по которому уже ушёл /start (`started`), через `grace` с забывается: дальше группу видно в списке Salad, а остановленная НЕ через драйвер (batch_window down,
    ssh_run, submit …) не должна держать место до конца срока."""
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict) and now - float(v.get('ts', 0)) <= ttl
            and not (v.get('started') and now - float(v['started']) > grace)}


def _write_reserved(path: str, data: dict) -> None:
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


class _Lock:
    def __init__(self, d: str, wait_s: float = LOCK_WAIT_S):
        os.makedirs(d, exist_ok=True)
        self.fd = os.open(os.path.join(d, 'salad-ceiling.lock'), os.O_CREAT | os.O_RDWR, 0o644)
        end = time.time() + wait_s
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.time() > end:
                    os.close(self.fd)
                    raise TimeoutError(f'замок предела Salad занят больше {wait_s:.0f} с')
                time.sleep(0.05)

    def release(self) -> None:
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


def admit(MG, name: str, need: int | None = None, d: str | None = None, rules: dict | None = None, clock=time.time, series: str | None = None) -> tuple[bool, str]:
    """Можно ли создать/стартовать группу `name` с `need` машинами (None — взять из резерва или из GET группы). → (да/нет, строка для журнала).
    Да — резерв записан (до погашения/срока). Нет — группа не создаётся; строка: «Salad: живо N, предел P — жди или останови свои»."""
    if _test_process(d):
        return True, 'ворота выключены в тестовом процессе'
    why_stop = series_stopped(series, None, d)                                 # T-58/3: серия остановлена — ни создание, ни пересоздание `…m`, ни старт
    if why_stop:
        return False, f'Salad: {why_stop} — группу {name} не создаю'
    try:
        rules = rules or load_rules()
        limit = ceiling(rules)
        ttl = float(rules.get('salad_reserve_ttl_s', 3600))
        folder = ceiling_dir(d)
        lock = _Lock(folder)
    except (OSError, ValueError, TimeoutError) as e:
        return False, f'Salad: ворота предела не открылись ({type(e).__name__}: {str(e)[:100]}) — группу не создаю'
    try:
        try:
            code, resp = MG.api('')
        except Exception as e:  # noqa: BLE001 — любой сбой чтения списка = «не знаю», а «не знаю» на деньгах = отказ
            return False, f'Salad: список групп не прочитан ({type(e).__name__}: {str(e)[:100]}) — группу не создаю (предел {limit})'
        if code != 200 or not isinstance(resp, dict) or not isinstance(resp.get('items'), list):
            return False, f'Salad: список групп не прочитан (HTTP {code}) — группу не создаю (предел {limit})'
        now = clock()
        rpath = os.path.join(folder, 'salad-ceiling-reserved.json')
        grace = float(rules.get('salad_start_grace_s', START_GRACE_S))
        reserved = _read_reserved(rpath, now, ttl, grace)
        live = live_by_group(resp['items'])
        is_start = need is None
        if need is None:
            if name in reserved:
                need = int(reserved[name].get('need', 1))
            else:
                try:
                    gc, g = MG.api(f'/{name}')
                    need = int((g or {}).get('replicas')) if gc == 200 else None
                except Exception:  # noqa: BLE001
                    need = None
                if need is None:
                    return False, f'Salad: число машин группы {name} не прочитано — старт не даю (предел {limit})'
        need = max(1, int(need))
        eff = {n: max(live.get(n, 0), int(reserved.get(n, {}).get('need', 0))) for n in set(live) | set(reserved)}
        others = sum(v for n, v in eff.items() if n != name)
        mine = max(eff.get(name, 0), need)
        total_now = others + eff.get(name, 0)
        if others + mine > limit:
            return False, (f'Salad: живо {total_now}, предел {limit} — жди или останови свои (группа {name} добавит {mine - eff.get(name, 0)}; '
                           f'резерв других процессов {sum(int(v.get("need", 0)) for n, v in reserved.items() if n != name and n not in live)})')
        reserved[name] = {'need': mine, 'ts': now, **({'started': now} if is_start else {})}
        try:
            _write_reserved(rpath, reserved)
        except OSError as e:
            return False, f'Salad: резерв не записан ({e}) — группу не создаю'
        return True, f'Salad: живо {total_now}, после {name} будет {others + mine} из {limit}'
    finally:
        lock.release()


def release(name: str, d: str | None = None, rules: dict | None = None) -> bool:
    """Снять резерв (группа погашена с проверкой «0 нод» или не создалась). Не бросает: ошибка = строка и False, резерв сам истечёт по сроку."""
    if _test_process(d):
        return False
    try:
        folder = ceiling_dir(d)
        lock = _Lock(folder, 30)
    except (OSError, TimeoutError):
        return False
    try:
        rpath = os.path.join(folder, 'salad-ceiling-reserved.json')
        try:
            ttl = float((rules or load_rules()).get('salad_reserve_ttl_s', 3600))
        except (OSError, ValueError):
            ttl = 3600.0
        reserved = _read_reserved(rpath, time.time(), ttl)
        if name not in reserved:
            return False
        del reserved[name]
        _write_reserved(rpath, reserved)
        return True
    except OSError:
        return False
    finally:
        lock.release()


class DefaultMG:
    """Минимальный клиент API групп для скриптов, у которых своего нет (`batch_show`, `cutout_redo`, `grey_probe`, `batch_window.sh`): `api(path, method, body) → (код, словарь)`.
    Ключ — `SALAD_API_KEY` из окружения (скрипты его и так берут оттуда); нет ключа — исключение, ворота скажут «не прочитан» → отказ."""
    API = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'

    def api(self, path: str = '', method: str = 'GET', body: dict | None = None) -> tuple[int, dict]:
        import urllib.error
        import urllib.request
        data = json.dumps(body).encode() if body is not None else (b'' if method == 'POST' else None)
        req = urllib.request.Request(f'{self.API}{path}', data=data, method=method,
                                     headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {'detail': raw[:200].decode(errors='replace')}


def admit_start(name: str, MG=None) -> tuple[bool, str]:
    """Ворота перед `/start` УЖЕ созданной группы (число машин — из резерва или GET группы). Для скриптов со своим HTTP: `ok, why = admit_start(g)`; нет → не стартовать, `why` — в журнал."""
    return admit(MG or DefaultMG(), name, None)


def main(argv: list[str] | None = None) -> int:
    """Для shell (`batch_window.sh`): `salad_ceiling.py --admit ГРУППА` → код 0 можно (строка на stdout), 1 нельзя (причина на stdout); `--release ГРУППА` — снять резерв."""
    import argparse
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument('--admit', metavar='ГРУППА')
    ap.add_argument('--release', metavar='ГРУППА')
    ap.add_argument('--stop-series', metavar='КЛЮЧ', help='штатный стоп серии: записать метку; драйверы серии гасят свои группы и выходят сами (ни kill, ни pkill)')
    ap.add_argument('--reason', default='', help='с --stop-series: причина в метке')
    ap.add_argument('--series-status', metavar='КЛЮЧ', help='есть ли метка стопа серии (код 0 — есть, 1 — нет)')
    a = ap.parse_args(argv)
    if a.stop_series:
        print(f'стоп серии {a.stop_series}: метка {series_stop(a.stop_series, reason=a.reason)}')
        return 0
    if a.series_status:
        why = series_stopped(a.series_status, 0.0)
        print(why or f'серия {a.series_status}: метки стопа нет')
        return 0 if why else 1
    if a.admit:
        try:
            ok, why = admit_start(a.admit)
        except Exception as e:  # noqa: BLE001 — сбой ворот = отказ
            ok, why = False, f'Salad: ворота предела упали ({type(e).__name__}: {str(e)[:100]}) — группу не стартую'
        print(why)
        return 0 if ok else 1
    if a.release:
        release(a.release)
        return 0
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
