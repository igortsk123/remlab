#!/usr/bin/env python3
"""Что за группа Salad: тариф, цена, окно подъёма — ОДИН источник для всех стартёров и отчётов.

ЗАЧЕМ (04.09). Тариф и окно жили в именах групп и в трёх разных местах кода (`tier_compare.TIER`,
`pool_hours.TIER`, `batch_window.sh`), а `SALAD_GROUP` разбирался в семи местах с разными
умолчаниями (`mesh-run3`, `mesh-run10`). Итог ночи 03.09: конвейер поднял batch-группы, которые
крон погасил в 15:00 UTC, — 57 машин прогрелось, 0 мешей, 134 ₽ впустую. Правило «группу вне окна
не поднимает никто» может работать только там, где окно записано ровно один раз.

    import salad_groups as SG
    SG.allowed_now('mesh-batch-1')      # False вечером — поднимать нельзя
    SG.price('mesh-low-2')              # 0.143 $/ч
    SG.groups_from_env()                # ['mesh-batch-1', ...] из SALAD_GROUP, без умолчания

УДАЛЁННЫЕ В SALAD ГРУППЫ (T-20261106-86). Запись группы в правилах не стираем — по ней считаются цена и тариф старых
нодо-минут (книга сторожа денег, `tier_compare`). Удалённую помечаем `"deleted": "<дата>"` (+ `_deleted_why`): её не отдают
`windowed()` (расписание `batch_window.sh`), `allowed_now()` и `--can-start`. Ложная тревога 06.11 15:00 «НЕ УДАЛОСЬ
погасить mesh-batch-6 (HTTP 404)» — группы в Salad не было с пересборки, а расписание гасило её по списку правил.
Сверка «правила ↔ Salad» — `reconcile()` (чистая, селфтест без сети) и `--check-live` (одним GET списка групп).

    python3 salad/salad_groups.py --selftest     # без сети: удалённые, окно, сверка, живые правила
    set -a; . ~/scout-scenes/salad.env; set +a; python3 salad/salad_groups.py --check-live   # 0 — сходится, 1 — расхождение
"""
from __future__ import annotations

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.environ.get('MESH_GROUPS_RULES') or os.path.join(HERE, '..', 'rules', 'salad-groups.json')
# ЗАПРЕТ ЦЕНЫ ПО ГРУППЕ (план mesh-15): сторож денег кладёт сюда группу, у которой меш дороже потолка, ДО её остановки —
# иначе конвейер (`batch_show.ensure_group_started`) или расписание (`batch_window.sh up`) поднимут её обратно. Общий
# стоп-файл `mesh-group-halt.json` гасит весь пул; этот — одну группу. Снимает человек (удалить группу из файла).
PRICE_HALT = os.environ.get('MESH_PRICE_HALT') or os.path.expanduser('~/scout-scenes/mesh-price-halt.json')
_CACHE: dict | None = None


def load() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(RULES, encoding='utf-8') as f:
            _CACHE = json.load(f)
    return _CACHE


def info(group: str) -> dict:
    return (load().get('groups') or {}).get(group) or {}


def tier(group: str) -> str:
    """Тариф группы или '?' — неизвестную группу не считаем ничьей молча: отчёты печатают '?'."""
    return info(group).get('tier') or '?'


def price(group: str) -> float | None:
    """$/ч машины группы. По классу карты (`price_class` → `prices_by_class_usd_h`, прайс Salad — цена класса полная,
    CPU и ОЗУ включены; T-20261024-01), иначе — по тарифу (`prices_usd_h`, цена RTX 3090 на 03.09: для 4060 Ti она
    на 43 % выше прайса, ночь 23→24.10 считалась 716 ₽ вместо ≈ 501 ₽)."""
    cls = info(group).get('price_class')
    by_cls = ((load().get('prices_by_class_usd_h') or {}).get(cls) or {}) if cls else {}
    if tier(group) in by_cls:
        return by_cls[tier(group)]
    return (load().get('prices_usd_h') or {}).get(tier(group))


def queue_of(group: str) -> str:
    """Очередь Salad, к которой группа подключена при создании (`queue` в правилах, план mesh-18); '' — группа без очереди
    (задания ей возят по SSH). Связь задаётся только при создании группы — правило лишь описывает факт (`queue_setup.py`)."""
    return str(info(group).get('queue') or '')


def usd_rub() -> float:
    return float(load().get('usd_rub') or 0)


def price_ceiling() -> dict:
    """Потолок цены меша и правила суда (`price_ceiling` в rules/salad-groups.json); нет блока — пусто (сторож молчит)."""
    return load().get('price_ceiling') or {}


def node_min_ram_gb() -> float:
    """Сколько ОЗУ должно быть у машины, чтобы брать задания (`node_ram.min_gb`, T-20261022-10); 0 — не проверяем."""
    return float((load().get('node_ram') or {}).get('min_gb') or 0)


def price_halted(group: str) -> str:
    """Причина запрета подъёма группы по цене меша; '' — запрета нет. Битый файл — запрета нет, но громко."""
    try:
        with open(PRICE_HALT, encoding='utf-8') as f:
            d = json.load(f)
    except FileNotFoundError:
        return ''
    except (OSError, ValueError) as e:
        print(f'!! {PRICE_HALT} не читается ({type(e).__name__}) — запрет цены не учтён', flush=True)
        return ''
    return str((d.get(group) or {}).get('why') or '') if isinstance(d, dict) else ''


def deleted(group: str) -> str:
    """Дата удаления группы в Salad (`deleted` в правилах); '' — группа живая."""
    return str(info(group).get('deleted') or '')


def allowed_now(group: str, now: float | None = None) -> bool:
    """Можно ли ПОДНИМАТЬ группу сейчас. Нет окна — всегда (low работает круглосуточно). Запрет цены — никогда.

    Окно — [с, до) по часам UTC. Разбор журнала 01–03.09: доля закрытых заданий на `batch`
    09–14ч 51–81%, 15–19ч 0–9% — вечером хозяева забирают домашние компьютеры, задание рвётся.
    """
    if price_halted(group):
        return False
    if deleted(group):                  # группы нет в Salad — поднимать нечего (T-20261106-86)
        return False
    if info(group).get('disabled'):
        # ВЫКЛЮЧЕНА В ПРАВИЛАХ (mesh-18 этап 2): новая группа заведена заранее и ждёт слова владельца — не поднимает никто,
        # даже если её имя попало в SALAD_GROUP; включение — снять `disabled` (человек)
        return False
    win = info(group).get('window_utc')
    if not win:
        return True
    h = time.gmtime(now if now is not None else time.time()).tm_hour
    a, b = int(win[0]), int(win[1])
    return a <= h < b if a <= b else (h >= a or h < b)


def groups_from_env() -> list[str]:
    """Группы из `SALAD_GROUP` (через запятую). БЕЗ УМОЛЧАНИЯ: тихий `mesh-run3` из старого кода
    однажды заставил бы конвейер работать с давно удалённой группой."""
    raw = os.environ.get('SALAD_GROUP', '')
    gs = [g.strip() for g in raw.split(',') if g.strip()]
    if not gs:
        raise SystemExit('нет SALAD_GROUP — задай в ~/scout-scenes/salad.env (через запятую)')
    return gs


def groups_or_empty() -> list[str]:
    """То же, но без отказа: для чтения при импорте модуля (стенд `tests_pool` импортирует
    `ssh_run` без окружения). Проверка на пустоту — в точке входа `main()`."""
    return [g.strip() for g in os.environ.get('SALAD_GROUP', '').split(',') if g.strip()]


def windowed() -> list[str]:
    """Группы с окном (их поднимает и гасит расписание `batch_window.sh`); удалённые в Salad — нет."""
    return [g for g, i in (load().get('groups') or {}).items() if i.get('window_utc') and not i.get('deleted')]


def reconcile(rules_groups: dict, salad: list) -> dict:
    """Сверка правил с составом групп в Salad. Чистая. → {'gone': в правилах живая, в Salad нет — пометить `deleted`;
    'zombie': помечена удалённой, а в Salad есть — снять пометку; 'unknown': в Salad есть, в правилах нет — тариф и цена
    неизвестны}. Пустые списки — сходится."""
    have = set(salad)
    live = {g for g, i in rules_groups.items() if not (i or {}).get('deleted')}
    dead = set(rules_groups) - live
    return {'gone': sorted(live - have), 'zombie': sorted(dead & have), 'unknown': sorted(have - set(rules_groups))}


def salad_names(base: str = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers') -> list:
    """Имена групп проекта в Salad — одним GET списка (бесплатно). Через curl: WAF Salad режет python-UA (ADR-0137).
    Не вышло — исключение (молча пустой список дал бы «все группы удалены»)."""
    import subprocess  # noqa: PLC0415
    r = subprocess.run(['curl', '-sS', '--fail', '--max-time', '30', '-H', f"Salad-Api-Key: {os.environ['SALAD_API_KEY']}", base],
                       capture_output=True, text=True, timeout=45)
    if r.returncode != 0:
        raise RuntimeError(f'список групп Salad не получен: curl rc={r.returncode} {r.stderr.strip()[:120]}')
    return [str(x.get('name')) for x in (json.loads(r.stdout).get('items') or [])]


def reconcile_text(R: dict) -> list:
    out = []
    if R['gone']:
        out.append('в правилах живые, в Salad их нет — пометить "deleted": ' + ', '.join(R['gone']))
    if R['zombie']:
        out.append('помечены удалёнными, а в Salad есть — снять "deleted": ' + ', '.join(R['zombie']))
    if R['unknown']:
        out.append('в Salad есть, в правилах нет (тариф и цена неизвестны): ' + ', '.join(R['unknown']))
    return out


def _selftest() -> int:
    import tempfile  # noqa: PLC0415
    global RULES, _CACHE, PRICE_HALT
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1
    keep = (RULES, _CACHE, PRICE_HALT)
    tmp = tempfile.mkdtemp(prefix='sg-selftest-')
    try:
        RULES, _CACHE, PRICE_HALT = os.path.join(tmp, 'r.json'), None, os.path.join(tmp, 'нет-запрета.json')
        json.dump({'groups': {'b-live': {'tier': 'batch', 'window_utc': [0, 24]}, 'b-dead': {'tier': 'batch', 'window_utc': [0, 24],
                                                                                         'deleted': '2026-10-23'},
                              'l-live': {'tier': 'low'}, 'l-dead': {'tier': 'low', 'deleted': '2026-10-23'}},
                   'prices_usd_h': {'batch': 0.1, 'low': 0.2}}, open(RULES, 'w', encoding='utf-8'))
        ok('окно: удалённая в Salad группа не отдаётся расписанию', windowed() == ['b-live'])
        ok('поднимать удалённую нельзя, живую — можно', not allowed_now('b-dead') and not allowed_now('l-dead')
           and allowed_now('b-live') and allowed_now('l-live'))
        ok('цена и тариф удалённой остаются (книга старых нодо-минут)', price('l-dead') == 0.2 and tier('b-dead') == 'batch')
        R = reconcile(load()['groups'], ['b-live', 'l-live'])
        ok('сверка: правила = Salad (удалённых там нет) — расхождений нет', R == {'gone': [], 'zombie': [], 'unknown': []}
           and reconcile_text(R) == [])
        R = reconcile(load()['groups'], ['b-live', 'l-dead', 'x-new'])
        ok('сверка: живая пропала → gone; удалённая есть → zombie; чужая → unknown',
           R == {'gone': ['l-live'], 'zombie': ['l-dead'], 'unknown': ['x-new']} and len(reconcile_text(R)) == 3)
        env = dict(os.environ, MESH_GROUPS_RULES=RULES, MESH_PRICE_HALT=PRICE_HALT)
        import subprocess  # noqa: PLC0415
        import sys  # noqa: PLC0415
        me = os.path.abspath(__file__)
        r = subprocess.run([sys.executable, me, '--can-start', 'b-dead'], env=env, capture_output=True, text=True)
        w = subprocess.run([sys.executable, me, '--windowed'], env=env, capture_output=True, text=True)
        ok('--can-start удалённой: 1 с причиной; --windowed без неё', r.returncode == 1 and 'удалена в Salad' in r.stdout
           and w.stdout.split() == ['b-live'])
        # живые правила репозитория: у каждой группы тариф и цена; дата удаления — ГГГГ-ММ-ДД
        RULES, _CACHE = keep[0], None
        G = load().get('groups') or {}
        ok('правила репо: у каждой группы тариф с ценой', all(price(g) is not None for g in G))
        ok('правила репо: deleted — дата ГГГГ-ММ-ДД', all(len(deleted(g)) == 10 and deleted(g)[4] == '-' for g in G if deleted(g)))
    finally:
        RULES, _CACHE, PRICE_HALT = keep
    print(f'salad_groups selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    import sys
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    elif '--check-live' in sys.argv:           # сверка правил с Salad (сеть, GET списка); 0 — сходится, 1 — расхождение
        _R = reconcile(load().get('groups') or {}, salad_names())
        _t = reconcile_text(_R)
        print('\n'.join(_t) if _t else 'правила групп = Salad')
        sys.exit(1 if _t else 0)
    elif '--windowed' in sys.argv:
        print(' '.join(windowed()))
    elif '--can-start' in sys.argv:          # batch_window.sh up: 0 — можно поднимать, 1 — запрет цены или disabled (окно — cron)
        _g = sys.argv[sys.argv.index('--can-start') + 1]
        _why = (price_halted(_g) or (f'удалена в Salad {deleted(_g)} (rules: deleted)' if deleted(_g) else '')
                or ('выключена в rules (disabled)' if info(_g).get('disabled') else ''))
        if _why:
            print(_why if _why.startswith(('удалена', 'выключена')) else f'запрет цены: {_why}')
        sys.exit(1 if _why else 0)
    else:
        for g, i in (load().get('groups') or {}).items():
            print(f"{g:14s} {i.get('tier'):6s} {price(g)} $/ч  окно {i.get('window_utc') or '—'}  "
                  f"сейчас {'можно' if allowed_now(g) else 'НЕЛЬЗЯ'}" + (f'  УДАЛЕНА в Salad {deleted(g)}' if deleted(g) else ''))
