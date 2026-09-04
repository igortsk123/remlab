#!/usr/bin/env python3
"""Очистка приёмника — ТОЛЬКО того, что уже скачано, сверено и записано в базу.

ЗАЧЕМ (владелец 01.09: «чтоб узким местом приёмник не был, надо периодически триггером
запускать копирование, запись в базу, сверку и очистку»). exit-fi работает транзитом: 38 ГБ
на весь сервер, там же сайт и база с ночными снимками. 01.09 приёмник дорос до 7.8 ГБ и
свободного места осталось 4.7 ГБ — конвейер копил, а чистил только в самом конце прогона.

ПОРЯДОК ВЛАДЕЛЬЦА СОБЛЮДЁН БУКВАЛЬНО: копирование (`drain.sh --keep`) и запись в базу
(`ingest_registry.py`, `mesh_bind.py`) делает конвейер ДО этого шага, здесь — сверка и только
потом удаление. Прежний `drain.sh` без `--keep` удалял сразу после проверки локальной копии,
то есть ДО записи в базу: комплект мог исчезнуть с сервера, не оставив следа в карточке.

ЧТО СЧИТАЕТСЯ «МОЖНО УДАЛЯТЬ» — три условия разом:
  1) локальная копия есть и её объём не меньше серверного (не оборванный rsync);
  2) если в комплекте есть `model.glb` — товар отмечен `mesh_status='ready'` в базе;
     если модели нет (гейт завернул форму) — достаточно локальной копии: это диагностика,
     в карточку она и не должна попадать;
  3) комплект старше RETAIN_H часов — свежие оставляем, чтобы жил кэш «уже сделано» на
     приёмнике: повтор из спула и волна лечения тогда возвращаются мгновенно, не тратя GPU.
При нехватке места (свободно меньше FREE_MIN_GB) условие 3 снимается — диск важнее кэша.

  ~/venvs/scout/bin/python receiver_purge.py            # показать, что удалил бы
  ~/venvs/scout/bin/python receiver_purge.py --apply    # удалить
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.environ.get('MESH_SRV', 'root@89.167.127.0')
PORT = os.environ.get('MESH_SSH_PORT', '22222')
REMOTE = os.environ.get('MESH_ROOT_REMOTE', '/opt/remlab/meshes')
LOCAL = os.path.expanduser(os.environ.get('MESH_LOCAL', '~/scout-scenes/meshes-hunyuan'))
RETAIN_H = float(os.environ.get('MESH_RECV_RETAIN_H', '6'))
FREE_MIN_GB = float(os.environ.get('MESH_RECV_FREE_MIN_GB', '8'))
# ПОРОГ ПО ОБЪЁМУ КАТАЛОГА (04.09). Приёмник отказывает (507) при `dir_gb > 8`, а пред-проверка
# конвейера (`sink_health`) — при `> 7`. При 70–100 мешах в час кэш на 6 часов дорастает до 6 ГБ и
# упирается в эти пороги при ПУСТОМ диске. Поэтому срок хранения снимаем не только когда мало места
# на диске, но и когда каталог сам вырос: лестница purge 6 → пред-проверка 7 → приёмник 8.
DIR_TIGHT_GB = float(os.environ.get('MESH_RECV_DIR_TIGHT_GB', '6'))
# Остатки `.staging`: приёмник переносит файлы в постоянный каталог по /complete и только тогда
# сносит staging. Если нода упала посреди комплекта (или приёмник ответил 507 на N-й файл, а первые
# уже легли), `.staging` остаётся навсегда — ни drain, ни эта чистка его не видели (искали только
# complete.json). Судим не по mtime каталога (он не движется при долгой записи ОДНОГО файла), а по
# двум последовательным наблюдениям неизменного размера + возраст ≥ RETAIN_H.
STAGING_SEEN = os.path.expanduser(os.environ.get('MESH_STAGING_SEEN', '~/scout-scenes/.staging-seen.json'))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-t', '-A']


def ssh(cmd: str, timeout: int = 300) -> str:
    r = subprocess.run(['ssh', '-p', PORT, '-o', 'BatchMode=yes', SRV, cmd],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f'ssh: {r.stderr[:200]}')
    return r.stdout


def free_gb() -> float:
    """Свободно на КОРНЕ сервера — намеренно тот же диск, по которому судит приёмник
    (`statvfs(ROOT)`): иначе их вердикты разойдутся. Образы докера и прочее на этом же корне чистит
    серверный watchdog, а не мы — мы освобождаем только меши."""
    out = ssh("df -Pk / | tail -1").split()
    return int(out[3]) / 1024 / 1024


def sweep_staging(apply: bool) -> int:
    """Удаляет `.staging`, которые не менялись между двумя прогонами и старше RETAIN_H. Возвращает,
    сколько убрано. Состояние — файл `{путь: [размер, когда_впервые_увидели]}`."""
    out = ssh("cd %s && find . -type d -name .staging -printf '%%p\\t%%T@\\n' 2>/dev/null "
              "| while IFS=$'\\t' read -r d t; do printf '%%s\\t%%s\\t%%s\\n' \"$d\" \"$t\" "
              "\"$(du -sb \"$d\" | cut -f1)\"; done" % REMOTE)
    now = time.time()
    seen: dict = {}
    try:
        seen = json.load(open(STAGING_SEEN, encoding='utf-8'))
    except Exception:  # noqa: BLE001 — нет файла или битый: начинаем заново
        seen = {}
    cur, doomed = {}, []
    for ln in out.strip().split('\n'):
        if not ln.strip():
            continue
        d, mt, size = ln.split('\t')
        size = int(size)
        prev = seen.get(d)
        first = prev[1] if prev and prev[0] == size else now
        cur[d] = [size, first]
        age_h = (now - float(mt)) / 3600
        if prev and prev[0] == size and age_h >= RETAIN_H and (now - first) >= 900:
            doomed.append(d)
    with open(STAGING_SEEN, 'w', encoding='utf-8') as f:
        json.dump(cur, f)
    if cur:
        print(f'.staging на приёмнике: {len(cur)}, к удалению (не менялись 2 прогона и старше '
              f'{RETAIN_H:.0f} ч): {len(doomed)}')
    if doomed and apply:
        ssh('cd %s && rm -rf %s && find . -mindepth 1 -type d -empty -delete' % (
            REMOTE, ' '.join(f"'{d}'" for d in doomed)), timeout=600)
    return len(doomed) if apply else 0


def remote_sets() -> list[tuple[str, int, float]]:
    """(каталог, суммарный размер, возраст в часах) для завершённых комплектов."""
    out = ssh("cd %s && find . -name complete.json -printf '%%h\\t%%T@\\n'" % REMOTE)
    res = []
    now = time.time()
    for ln in out.strip().split('\n'):
        if not ln.strip():
            continue
        d, ts = ln.split('\t')
        d = d[2:] if d.startswith('./') else d
        res.append((d, 0, (now - float(ts)) / 3600))
    if not res:
        return []
    # размеры считаем одним заходом, а не по каталогу на ssh-сессию
    sizes = ssh("cd %s && du -sb $(find . -name complete.json -printf '%%h\\n' | tr '\\n' ' ')"
                % REMOTE)
    by_dir = {}
    for ln in sizes.strip().split('\n'):
        if '\t' not in ln:
            continue
        sz, d = ln.split('\t', 1)
        by_dir[d[2:] if d.startswith('./') else d] = int(sz)
    return [(d, by_dir.get(d, 0), age) for d, _, age in res]


def ready_skus() -> set:
    q = "select shop_mid||':'||external_id from products where mesh_status='ready';"
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'psql: {r.stderr[:200]}')
    return {s.strip() for s in r.stdout.split() if s.strip()}


def local_bytes(d: str) -> int:
    p = os.path.join(LOCAL, d)
    if not os.path.isdir(p):
        return -1
    return sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(p) for f in fs)


def has_model(d: str) -> bool:
    return os.path.exists(os.path.join(LOCAL, d, 'model.glb'))


def sku_of(d: str) -> str | None:
    """`meshes/hunyuan21/v2/<mid>_<eid>/<jid>` → `<mid>:<eid>`."""
    parts = d.strip('/').split('/')
    return parts[-2].replace('_', ':', 1) if len(parts) >= 2 else None


def main() -> None:
    apply = '--apply' in sys.argv
    try:
        sets = remote_sets()
    except Exception as e:  # noqa: BLE001 — приёмник недоступен: это не авария конвейера
        print(f'приёмник недоступен ({type(e).__name__}: {str(e)[:80]}) — очистку пропускаю')
        return
    try:
        sweep_staging(apply)
    except Exception as e:  # noqa: BLE001 — уборка остатков не должна ломать основную чистку
        print(f'.staging: не разобрал ({type(e).__name__}: {str(e)[:80]})')
    if not sets:
        print('на приёмнике пусто')
        return
    ready = ready_skus()
    free = free_gb()
    dir_gb = sum(s[1] for s in sets) / 2 ** 30
    tight = free < FREE_MIN_GB or dir_gb > DIR_TIGHT_GB
    print(f'на приёмнике комплектов: {len(sets)} ({dir_gb:.1f} ГБ); свободно на сервере {free:.1f} ГБ'
          + (f' — {"меньше %.0f ГБ" % FREE_MIN_GB if free < FREE_MIN_GB else "каталог больше %.0f ГБ" % DIR_TIGHT_GB}'
             f', срок хранения не соблюдаю' if tight else ''))

    purge, keep = [], {'молодые': 0, 'нет локально': 0, 'объём меньше': 0, 'нет в базе': 0}
    for d, size, age_h in sets:
        loc = local_bytes(d)
        if loc < 0:
            keep['нет локально'] += 1
            continue
        if loc < size:
            keep['объём меньше'] += 1
            continue
        if has_model(d) and sku_of(d) not in ready:
            keep['нет в базе'] += 1
            continue
        if age_h < RETAIN_H and not tight:
            keep['молодые'] += 1
            continue
        purge.append(d)

    print(f'к удалению: {len(purge)}; оставляю: '
          + ', '.join(f'{k} {v}' for k, v in keep.items() if v))
    if not purge:
        return
    if not apply:
        print('это разбор без действий. Удалить: --apply')
        return
    # удаляем пачками, чтобы не открывать ssh-сессию на каждый каталог
    for i in range(0, len(purge), 100):
        chunk = purge[i:i + 100]
        ssh('cd %s && rm -rf %s' % (REMOTE, ' '.join(f"'{d}'" for d in chunk)), timeout=600)
    print(f'удалено комплектов: {len(purge)}; свободно стало {free_gb():.1f} ГБ')


if __name__ == '__main__':
    main()
