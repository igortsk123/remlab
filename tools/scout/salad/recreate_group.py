#!/usr/bin/env python3
"""ПЕРЕСОЗДАТЬ ОДНУ ГРУППУ SALAD ПОД ТЕМ ЖЕ ИМЕНЕМ — с новыми ресурсами, тем же образом (T-20261020-17).

ЗАЧЕМ (20.10). Память группы надо поднять до 24 ГБ (сбои 3090 = нехватка ОЗУ машины, решение
владельца). PATCH `resources` создаёт у группы новую версию: обещанное документацией «реплики на
подходящих машинах остаются» не выполнилось — нода оборвалась посреди задания, а инстансы версии 2
пришли БЕЗ `ssh_port`, и пул (`ssh_run.instances`) их не видит, хотя Salad за них берёт деньги.
Группы, созданные POST'ом (`migrate_groups.py`, 04.09), SSH получили — поэтому пересоздание.

ПОЧЕМУ ТО ЖЕ ИМЯ. Живой конвейер читает список групп ОДИН раз при старте (`ssh_run.GROUPS` из
`SALAD_GROUP`), сторожа и окно batch — из `salad.env` и `rules/salad-groups.json`. Новое имя
потребовало бы перезапуска волны и правки трёх мест; старое — ничего.

ЧТО ДЕЛАЕТ: GET образца (по умолчанию сама группа) → тело как у `migrate_groups.build_body` (тот же
digest образа, ADR-0154; env, сеть, пробы — с факта) + новая память → stop → DELETE → дождаться 404 →
POST → GET-сверка. Без --apply печатает тело без секретов и ничего не меняет.

    ~/venvs/scout/bin/python recreate_group.py mesh-low-4 --memory 24576                 # разбор
    ~/venvs/scout/bin/python recreate_group.py mesh-low-4 --memory 24576 --apply
    ~/venvs/scout/bin/python recreate_group.py mesh-batch-3 --memory 24576 --no-autostart --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import migrate_groups as MG
import salad_groups as SG


def wait(pred, timeout_s: float, every_s: float = 5.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return True
        time.sleep(every_s)
    return False


def summary(body: dict) -> str:
    c = body['container']
    r = c['resources']
    return (f"имя {body['name']}, образ …{c['image'][-12:]}, тариф {body.get('priority')}, реплик {body['replicas']}, "
            f"autostart {body.get('autostart_policy')}, cpu {r.get('cpu')}, memory {r.get('memory')}, "
            f"диск {r.get('storage_amount')}, GPU-классов {len(r.get('gpu_classes') or [])}, "
            f"env {sorted(k for k in c['environment_variables'] if 'TOKEN' not in k and 'KEY' not in k)}, "
            f"сеть {'да' if body.get('networking') else 'нет'}, пробы "
            f"{[k for k in ('readiness_probe', 'startup_probe', 'liveness_probe') if body.get(k)]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('group')
    ap.add_argument('--memory', type=int, required=True)
    ap.add_argument('--donor', default=None)
    ap.add_argument('--replicas', type=int, default=None)
    ap.add_argument('--no-autostart', action='store_true', help='не стартовать после создания (batch вне окна)')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--create-only', action='store_true', help='группа уже удалена (прошлый запуск упёрся в name_conflict)')
    a = ap.parse_args()
    if not a.group.startswith('mesh-') or not 1024 <= a.memory <= 61440:
        return print('группа не mesh-* или память вне 1024–61440 МБ') or 2
    MG.env_from_file()
    code, donor = MG.api(f'/{a.donor or a.group}')
    if code != 200 or 'container' not in donor:
        return print(f'образец не прочитан: HTTP {code} {str(donor)[:150]}') or 1
    if donor['container'].get('image') != MG.IMAGE:
        print(f'!! образ образца {donor["container"].get("image")} ≠ боевого {MG.IMAGE} — беру боевой (ADR-0154)')
    tier = SG.tier(a.group)
    if tier == '?':
        return print(f'{a.group}: нет тарифа в rules/salad-groups.json — не пересоздаю') or 2
    body = MG.build_body(donor, {'name': a.group, 'tier': tier, 'replicas': a.replicas or donor.get('replicas') or 1})
    body['container']['resources']['memory'] = a.memory
    body['container']['environment_variables']['DEPLOYMENT_EPOCH'] = f'{time.strftime("%Y%m%d")}-{a.group}'
    body['autostart_policy'] = not a.no_autostart
    print('создам:', summary(body))
    if not a.apply:
        return print('\nэто разбор без действий. Выполнить: --apply') or 0

    if a.create_only:
        if MG.api(f'/{a.group}')[0] != 404:
            return print(f'{a.group} существует — --create-only только для уже удалённой') or 2
    else:
        st, _ = MG.api(f'/{a.group}/stop', 'POST')
        print(f'стоп {a.group}: HTTP {st}')
        wait(lambda: (MG.api(f'/{a.group}')[1].get('current_state') or {}).get('status') in ('stopped', None), 180)
        st, _ = MG.api(f'/{a.group}', 'DELETE')
        print(f'удаление {a.group}: HTTP {st}')
        if not wait(lambda: MG.api(f'/{a.group}')[0] == 404, 180):
            return print('!! группа не исчезла за 3 мин — не создаю, разбери руками') or 1
    # имя освобождается не мгновенно: 20.10 после 404 ещё ≥3 мин отвечал name_conflict
    for attempt in range(1, 41):
        st, resp = MG.api('', 'POST', body)
        if st == 201:
            break
        print(f'  создание, попытка {attempt}: HTTP {st} {str(resp)[:100]}', flush=True)
        time.sleep(30)
    else:
        return print(f'!! {a.group} НЕ создана — пул без группы, верни руками') or 1
    code, got = MG.api(f'/{a.group}')
    r = (got.get('container') or {}).get('resources') or {}
    ok = (code == 200 and r.get('memory') == a.memory and (got.get('container') or {}).get('image') == MG.IMAGE)
    print(f'создана {a.group}: HTTP {code}, memory {r.get("memory")}, образ …{(got.get("container") or {}).get("image", "")[-12:]}, '
          f'реплик {got.get("replicas")}, autostart {got.get("autostart_policy")}, версия {got.get("version")}, '
          f'статус {(got.get("current_state") or {}).get("status")}')
    return 0 if ok else 3


if __name__ == '__main__':
    sys.exit(main())
