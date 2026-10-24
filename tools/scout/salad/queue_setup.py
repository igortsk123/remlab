#!/usr/bin/env python3
"""ОЧЕРЕДЬ SALAD И ГРУППА, ПОДКЛЮЧЁННАЯ К НЕЙ ПРИ СОЗДАНИИ (план mesh-18 п.1, T-20261024-03). Группа создаётся ОСТАНОВЛЕННОЙ.

ЗАЧЕМ. 28.08 очередь привязывали PATCH'ем к живой группе (`submit.py`): PATCH ответил 200, у очереди `container_groups`
остался пуст, задания висели `pending`. По документации Salad связь группы с очередью (`queue_connection`) задаётся
ТОЛЬКО при создании группы и потом не меняется (Codex § 2, docs «Creating a Job Queue»). Поэтому — новая группа.

ЧТО ДЕЛАЕТ (без --apply — только печатает тело без секретов):
  1. очередь `--queue` (POST /queues), если её нет;
  2. группу `--group` по образцу `--donor`: тот же образ (`migrate_groups.IMAGE`, сверяется с образцом), те же ресурсы
     (cpu, память, диск, shm, классы GPU) и переменные, тариф из `rules/salad-groups.json`; `autostart_policy=false`,
     реплик `--replicas`; без публичного шлюза (задания приходят изнутри, через очередь);
     `queue_connection` → порт `--port`, путь `/generate`; проба готовности `/ready` (200 только после прогрева, `worker.py`);
     `command` = `bash -c <queue_entry.sh> qw [<queue_proxy.py>]` — воркер генерации + закреплённый воркер очереди со
     сверкой SHA-256; при `--port 8001` (по умолчанию) ещё и посредник, который дописывает в ответ машину (этап 2);
     `--port 8000` — без посредника, как канарейка 24.10 (`mesh-q-canary`);
  3. GET-сверка: `queue_connection` записана, статус группы `stopped`. `container_groups` очереди НЕ мерило: канарейка
     24.10 — пуст и у работающей группы, задание при этом ушло в работу (T-20261024-04).
  --test-job: положить одно тестовое задание (без фото: воркер ответит 400 до вырезки и GPU) — без машин оно обязано
  остаться `pending`. Перед платной канарейкой его снять: `queue_run.py --cancel <очередь> <id>`.

Группу НЕ стартует никогда; существующую не трогает (отказ). Боевая группа (не `*-canary`) в rules обязана быть
выключенной (`disabled`) — её поднимет только раздатчик после того, как человек снимет `disabled` (`salad_groups.allowed_now`).

    ~/venvs/scout/bin/python queue_setup.py --queue mesh-q --group mesh-q-canary --donor mesh-low-10             # разбор
    ~/venvs/scout/bin/python queue_setup.py --queue mesh-q --group mesh-q-canary --donor mesh-low-10 --apply
    ~/venvs/scout/bin/python queue_setup.py --queue mesh-q --group mesh-q-canary --check [--test-job]
    ~/venvs/scout/bin/python queue_setup.py --queue mesh-q-low --group mesh-q-low-1 --donor mesh-low-10 --replicas 30 --apply
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import migrate_groups as MG  # noqa: E402 — API контейнеров, доступ к реестру, боевой образ
import queue_run as QR       # noqa: E402 — API очереди
import salad_groups as SG    # noqa: E402

ENTRY = os.path.join(HERE, 'queue_entry.sh')
PROXY = os.path.join(HERE, 'queue_proxy.py')
PROXY_PORT = 8001
MAX_REPLICAS = 30            # как у боевой low (квота проекта 50: low 30 + batch 20)
CMD_ITEM_MAX = 1000          # лимит Salad на элемент `container.command` (схема CreateContainer)
READINESS = {'http': {'path': '/ready', 'port': 8000, 'scheme': 'http', 'headers': []},
             'initial_delay_seconds': 60, 'period_seconds': 10, 'timeout_seconds': 5,
             'success_threshold': 1, 'failure_threshold': 3}


def entry_command(path: str = ENTRY) -> list[str]:
    """`command` группы: текст `queue_entry.sh` без строк-комментариев и пустых строк (лимит 1000 знаков на элемент)."""
    lines = [ln.strip() for ln in open(path, encoding='utf-8').read().splitlines()]
    body = '\n'.join(ln for ln in lines if ln and not ln.startswith('#'))
    if len(body) > CMD_ITEM_MAX:
        raise SystemExit(f'queue_entry.sh без комментариев — {len(body)} знаков > {CMD_ITEM_MAX} (лимит Salad)')
    return ['bash', '-c', body]


def proxy_code(path: str = PROXY) -> str:
    """Код посредника для `command`: без строк-комментариев и пустых строк, отступы сохраняются (это Python)."""
    lines = open(path, encoding='utf-8').read().splitlines()
    body = '\n'.join(ln.rstrip() for ln in lines if ln.strip() and not ln.lstrip().startswith('#'))
    if len(body) > CMD_ITEM_MAX:
        raise SystemExit(f'queue_proxy.py без комментариев — {len(body)} знаков > {CMD_ITEM_MAX} (лимит Salad)')
    return body


def command(port: int) -> list[str]:
    """8001 — с посредником (ответ с машиной), 8000 — прямо на генерацию."""
    if port == PROXY_PORT:
        return entry_command() + ['qw', proxy_code()]
    if port == 8000:
        return entry_command()
    raise SystemExit(f'порт {port}: только {PROXY_PORT} (с посредником) или 8000 (без)')


def build(donor: dict, group: str, queue: str, replicas: int, port: int = PROXY_PORT) -> dict:
    tier = SG.tier(group)
    if tier == '?':
        raise SystemExit(f'{group}: нет тарифа в rules/salad-groups.json — не создаю')
    if SG.queue_of(group) != queue:
        raise SystemExit(f'{group}: в rules/salad-groups.json очередь {SG.queue_of(group)!r}, а не {queue!r} — не создаю')
    if not group.endswith('-canary') and not SG.info(group).get('disabled'):
        raise SystemExit(f'{group}: боевая группа должна быть в rules выключенной (`disabled`) до слова владельца — не создаю')
    if donor['container'].get('image') != MG.IMAGE:
        raise SystemExit(f'образ образца …{donor["container"].get("image", "")[-12:]} ≠ боевого …{MG.IMAGE[-12:]} — не создаю')
    body = MG.build_body(donor, {'name': group, 'tier': tier, 'replicas': replicas})
    c = body['container']
    c['resources'] = {k: v for k, v in donor['container']['resources'].items()
                      if k in ('cpu', 'memory', 'gpu_classes', 'storage_amount', 'shm_size')}
    c['environment_variables']['DEPLOYMENT_EPOCH'] = f'{time.strftime("%Y%m%d")}-{group}'
    c['command'] = command(port)
    body['autostart_policy'] = False
    body['queue_connection'] = {'path': '/generate', 'port': port, 'queue_name': queue}
    body['readiness_probe'] = READINESS
    for k in ('networking', 'startup_probe', 'liveness_probe', 'queue_autoscaler'):
        body.pop(k, None)
    return body


def summary(body: dict) -> str:
    c = body['container']
    r = c['resources']
    return (f"имя {body['name']}, образ …{c['image'][-12:]}, тариф {body.get('priority')}, реплик {body['replicas']}, "
            f"autostart {body['autostart_policy']}, cpu {r.get('cpu')}, memory {r.get('memory')}, диск {r.get('storage_amount')}, "
            f"shm {r.get('shm_size')}, GPU-классов {len(r.get('gpu_classes') or [])}, "
            f"env {sorted(k for k in c['environment_variables'] if 'TOKEN' not in k and 'KEY' not in k)}, "
            f"queue_connection {body.get('queue_connection')}, readiness {body['readiness_probe']['http']['path']}, "
            f"сеть {'да' if body.get('networking') else 'нет'}, command {c['command'][:2]} + {len(c['command'][2])} знаков"
            + (f" + посредник {len(c['command'][4])} знаков" if len(c['command']) > 3 else ''))


def check(group: str, queue: str) -> int:
    """GET группы и очереди: связь записана с обеих сторон, группа остановлена."""
    code, g = MG.api(f'/{group}')
    st = (g.get('current_state') or {}).get('status')
    qc = g.get('queue_connection')
    print(f'группа {group}: HTTP {code}, статус {st}, autostart {g.get("autostart_policy")}, реплик {g.get("replicas")}, '
          f'версия {g.get("version")}, queue_connection {qc}, readiness {(g.get("readiness_probe") or {}).get("http")}, '
          f'command {(g.get("container") or {}).get("command", [])[:2]}')
    qcode, q = QR.req('GET', f'/queues/{queue}')
    names = [x.get('name') for x in q.get('container_groups') or []]
    print(f'очередь {queue}: HTTP {qcode}, id {q.get("id")}, групп {names}, длина {q.get("current_queue_length")}')
    # container_groups очереди — не мерило (пуст и у работающей группы, канарейка 24.10): судим по стороне группы
    ok = code == 200 and st == 'stopped' and (qc or {}).get('queue_name') == queue and qcode == 200
    print('СВЯЗЬ ЗАПИСАНА: группа ссылается на очередь, группа остановлена' if ok else '!! связи нет или группа не остановлена')
    return 0 if ok else 3


def test_job(queue: str) -> int:
    """Тестовое задание: без фото воркер откажет 400 ДО вырезки и GPU; без машин оно обязано остаться `pending`."""
    job = {'sku': None, 'image_url': None, 'probe': 'mesh-18: проверка, что задание ждёт без машин — не генерировать'}
    qid, why = QR.submit(queue, job, {'probe': 'mesh-18', 'by': 'queue_setup'})
    if not qid:
        return print(f'!! задание не положено: {why}') or 1
    QR.ledger_write({'ev': 'probe', 'qid': qid, 'queue': queue})
    time.sleep(20)
    code, d = QR.get(queue, qid)
    print(f'тестовое задание {qid}: HTTP {code}, статус {d.get("status")}, события '
          f'{[(e.get("action"), e.get("time")) for e in d.get("events") or []]}')
    return 0 if d.get('status') == 'pending' else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--queue', required=True)
    ap.add_argument('--group', required=True)
    ap.add_argument('--donor', default=None)
    ap.add_argument('--replicas', type=int, default=1)
    ap.add_argument('--port', type=int, default=PROXY_PORT, help='8001 — с посредником (машина в ответе), 8000 — без')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--test-job', action='store_true')
    a = ap.parse_args()
    cap = 2 if a.group.endswith('-canary') else MAX_REPLICAS
    if not a.group.startswith('mesh-q-') or not 1 <= a.replicas <= cap:
        return print(f'группа не mesh-q-* или реплик вне 1–{cap}') or 2
    MG.env_from_file()
    if a.check or a.test_job:
        rc = check(a.group, a.queue) if a.check else 0
        return rc or (test_job(a.queue) if a.test_job else 0)
    if not a.donor:
        return print('нужен --donor (группа-образец)') or 2
    code, donor = MG.api(f'/{a.donor}')
    if code != 200 or 'container' not in donor:
        return print(f'образец не прочитан: HTTP {code} {str(donor)[:150]}') or 1
    body = build(donor, a.group, a.queue, a.replicas, a.port)
    print('создам:', summary(body))
    if not a.apply:
        return print('\nэто разбор без действий. Выполнить: --apply') or 0

    if MG.api(f'/{a.group}')[0] != 404:
        return print(f'{a.group} уже существует — не трогаю') or 2
    qcode, q = QR.req('GET', f'/queues/{a.queue}')
    if qcode == 404:
        qcode, q = QR.req('POST', '/queues', {'name': a.queue, 'display_name': a.queue,
                                             'description': 'mesh-18: задания генерации мешей без SSH'})
        print(f'очередь {a.queue}: создана HTTP {qcode}, id {q.get("id")}')
        if qcode != 201:
            return print(f'!! очередь не создана: {str(q)[:200]}') or 1
    elif qcode == 200:
        print(f'очередь {a.queue}: уже есть, id {q.get("id")}, групп {[x.get("name") for x in q.get("container_groups") or []]}')
    else:
        return print(f'!! очередь не прочитана: HTTP {qcode} {str(q)[:150]}') or 1
    st, resp = MG.api('', 'POST', body)
    print(f'группа {a.group}: создание HTTP {st} {"" if st == 201 else str(resp)[:300]}')
    if st != 201:
        return 1
    time.sleep(10)
    return check(a.group, a.queue)


if __name__ == '__main__':
    sys.exit(main())
