#!/usr/bin/env python3
"""ПЕРЕЕЗД ПУЛА НА НОВЫЙ ОБРАЗ ОДНИМ ЗАПУСКОМ: снести старые группы, поднять новые, включить конвейер.

ЗАЧЕМ (владелец 04.09: «смысл тянуть если все равно все ноды стояли — удаляй старое, новое деплой»).
План предполагал переезд по одной группе в окно 15:00, чтобы не ронять выработку. Но пул и так стоит
с 12:36 (кончились кредиты Salad), и осторожность потеряла смысл: качать образ заново всё равно всем.

ЧТО ДЕЛАЕТ:
  1. Читает боевую спеку с живой группы `mesh-low-4` (она уже на новом образе) — ресурсы, переменные,
     карты, сеть. Не собирает конфиг из головы: имя — не контракт, спека берётся с факта.
  2. Создаёт `mesh-low-5` (тариф low, 20 реплик) и `mesh-batch-3` (batch, 20 реплик, окно 09–15 UTC).
     С `mesh-low-4` (10 реплик) выходит ровно 50 — вся квота, 30 на low и 20 на batch.
     Одна batch-группа вместо двух: 04.09 у `mesh-batch-2` было 8 мешей на двух нодах — на таком
     выборке сравнивать тарифы нельзя, а одна группа даёт чистый замер в окне.
  3. Гасит и удаляет старые: `mesh-batch-1`, `mesh-batch-2`, `mesh-low-2`, `mesh-low-3`.
     Образ у живой группы подменить нельзя — PATCH проходит молча (ADR-0154), только пересоздание.
  4. Правит `rules/salad-groups.json` и `~/scout-scenes/salad.env` под новый состав.
  5. Снимает запрет сторожа, если он стоит (пул гасился при нехватке кредитов — тишина тогда была
     не поломкой пула, а отсутствием групп; дефект сторожа правится отдельно).
  6. Поднимает конвейер, если его нет.

    ~/venvs/scout/bin/python tools/scout/salad/migrate_groups.py          # разбор без действий
    ~/venvs/scout/bin/python tools/scout/salad/migrate_groups.py --apply  # выполнить
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'
IMAGE = ('ghcr.io/igortsk123/mesh-hunyuan@sha256:'
         'f9a9ad6d0d859a24102416632d730f59dda2ec6e9a699d85664917ddc8a656cb')   # localpaint2
DONOR = 'mesh-low-4'                       # живая группа-образец: уже на новом образе
DROP = ('mesh-batch-1', 'mesh-batch-2', 'mesh-low-2', 'mesh-low-3')
NEW = (
    {'name': 'mesh-low-5', 'tier': 'low', 'replicas': 20, 'window': None},
    {'name': 'mesh-batch-3', 'tier': 'batch', 'replicas': 20, 'window': [9, 15]},
)
KEEP = {'mesh-low-4': {'tier': 'low', 'replicas': 10, 'window': None}}
RULES = os.path.join(HERE, '..', 'rules', 'salad-groups.json')
ENVF = os.path.expanduser('~/scout-scenes/salad.env')
HALT = os.path.expanduser('~/scout-scenes/mesh-group-halt.json')
LOG = os.path.expanduser('~/igor/remlab/.memory_bank/_intake/batch-hardened.log')


def env_from_file() -> None:
    """Ключ Salad живёт в ~/scout-scenes/salad.env (вне git) — подхватываем, если не задан."""
    if os.environ.get('SALAD_API_KEY'):
        return
    with open(ENVF, encoding='utf-8') as f:
        for line in f:
            k, _, v = line.strip().partition('=')
            if k and v and not k.startswith('#'):
                os.environ.setdefault(k, v)


def api(path: str, method: str = 'GET', body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else (b'' if method == 'POST' else None)
    req = urllib.request.Request(f'{API}{path}', data=data, method=method,
                                 headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                                          'User-Agent': 'remlab-mesh/1.0',
                                          'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {'detail': raw[:200].decode(errors='replace')}


def ghcr_auth() -> dict:
    """Доступ к приватному реестру: без него группа создаётся и падает в `failed: Auth Required`."""
    a = json.load(open(os.path.expanduser('~/.docker/config.json')))['auths']['ghcr.io']['auth']
    user, _, pw = base64.b64decode(a).decode().partition(':')
    return {'basic': {'username': user, 'password': pw}}


def build_body(donor: dict, spec: dict) -> dict:
    c = donor['container']
    env = dict(c.get('environment_variables') or {})
    env['DEPLOYMENT_EPOCH'] = f'20260904-{spec["name"]}'
    body = {
        'name': spec['name'], 'display_name': spec['name'],
        'container': {
            'image': IMAGE,
            'resources': {k: v for k, v in c['resources'].items()
                          if k in ('cpu', 'memory', 'gpu_classes', 'storage_amount')},
            'command': c.get('command') or [],
            'priority': spec['tier'],
            'environment_variables': env,
            'image_caching': True,
            'registry_authentication': ghcr_auth(),
        },
        'autostart_policy': True,
        'restart_policy': donor.get('restart_policy', 'always'),
        'replicas': spec['replicas'],
        'priority': spec['tier'],
        'networking': donor.get('networking'),
        'readiness_probe': donor.get('readiness_probe'),
        'startup_probe': donor.get('startup_probe'),
        'liveness_probe': donor.get('liveness_probe'),
        'queue_autoscaler': donor.get('queue_autoscaler'),
    }
    return {k: v for k, v in body.items() if v is not None}


def main() -> int:
    apply = '--apply' in sys.argv
    env_from_file()
    if not os.environ.get('SALAD_API_KEY'):
        return print(f'нет SALAD_API_KEY (ни в окружении, ни в {ENVF})') or 2

    code, donor = api(f'/{DONOR}')
    if code != 200 or 'container' not in donor:
        return print(f'группа-образец {DONOR} не прочитана: HTTP {code} {str(donor)[:150]}') or 1
    r = donor['container']['resources']
    print(f'образец {DONOR}: RAM {r.get("memory")}, CPU {r.get("cpu")}, диск {r.get("storage_amount")}, '
          f'GPU-классов {len(r.get("gpu_classes") or [])}, реплик {donor.get("replicas")}')
    print(f'создам: ' + ', '.join(f'{s["name"]} ({s["tier"]}, {s["replicas"]})' for s in NEW))
    print(f'снесу:  {", ".join(DROP)}')
    total = sum(s['replicas'] for s in NEW) + sum(v['replicas'] for v in KEEP.values())
    print(f'итого реплик после переезда: {total} (квота 50)')
    if not apply:
        print('\nэто разбор без действий. Выполнить: --apply')
        return 0

    # 1) СНАЧАЛА СНОСИМ СТАРЫЕ — освобождаем квоту, иначе новые не создать (50 реплик — потолок)
    for g in DROP:
        st, _ = api(f'/{g}/stop', 'POST')
        print(f'  стоп {g}: HTTP {st}')
    time.sleep(15)
    for g in DROP:
        st, _ = api(f'/{g}', 'DELETE')
        print(f'  удаление {g}: HTTP {st}')
    time.sleep(20)

    # 2) новые группы
    made = []
    for spec in NEW:
        st, resp = api('', 'POST', build_body(donor, spec))
        if st == 201:
            made.append(spec)
            print(f'  создана {spec["name"]}: тариф {resp.get("priority")}, реплик {resp.get("replicas")}')
        else:
            print(f'  !! {spec["name"]} НЕ создана: HTTP {st} {str(resp)[:160]}')

    # 3) правила и окружение — под фактический состав
    groups = {**KEEP, **{s['name']: s for s in made}}
    rules = json.load(open(RULES, encoding='utf-8'))
    rules['groups'] = {n: ({'tier': v['tier'], 'window_utc': v['window']} if v['window']
                           else {'tier': v['tier']}) for n, v in groups.items()}
    with open(RULES, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'  rules/salad-groups.json: {", ".join(rules["groups"])}')

    lines = [ln for ln in open(ENVF, encoding='utf-8').read().splitlines()
             if not ln.startswith('SALAD_GROUP=')]
    lines.insert(0, 'SALAD_GROUP=' + ','.join(groups))
    with open(ENVF, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'  SALAD_GROUP={",".join(groups)}')

    # 4) запрет сторожа: он записан во время нехватки кредитов — гасить было нечего
    if os.path.exists(HALT):
        why = json.load(open(HALT, encoding='utf-8')).get('why')
        os.remove(HALT)
        print(f'  снят запрет сторожа ({why})')

    # 5) конвейер
    alive = subprocess.run(['pgrep', '-f', '[b]atch_show.py'], capture_output=True).returncode == 0
    if alive:
        print('  конвейер уже работает — перезапусти его сам, чтобы подхватил новый состав групп:\n'
              '    touch ~/scout-scenes/mesh-draining   # выйдет на границе пачки, группы не погасит')
    else:
        env = {**os.environ,
               'MESH_SAMPLE': os.path.expanduser('~/igor/remlab/tools/scout/mesh-queue-v1.json'),
               'MESH_MAX_JOBS': '12000', 'MESH_RETRY_GRACE_S': '45', 'MESH_POST_EVERY_S': '900',
               'SALAD_GROUP': ','.join(groups)}
        with open(LOG, 'a') as out:
            subprocess.Popen([sys.executable, '-u', os.path.join(HERE, 'batch_show.py'),
                              '--batch', '200'], cwd=HERE, env=env, stdout=out, stderr=out,
                             start_new_session=True)
        print(f'  конвейер запущен, лог: {LOG}')
    print('\nГотово. Машины качают образ ~час; сторож денег подхватит новый состав при следующем '
          'своём перезапуске (или перезапусти его так же).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
