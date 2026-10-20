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
  2) если в комплекте есть `model.glb` — его каталог записан в реестр поколений
     `mesh_generations` (пишет `ingest_registry.py`; оттуда же `mesh_bind` ставит ссылку в
     карточку); если модели нет (гейт завернул форму) — достаточно локальной копии: это
     диагностика, в карточку она и не должна попадать;
  3) комплект старше RETAIN_H часов — свежие оставляем, чтобы жил кэш «уже сделано» на
     приёмнике: повтор из спула и волна лечения тогда возвращаются мгновенно, не тратя GPU.
Когда тесно (`sink_health.tight` — та же мера, что у ворот, и раньше них) условие 3 снимается —
диск важнее кэша.

ПОЧЕМУ РЕЕСТР, А НЕ `mesh_status='ready'` (20.10, mesh-12). До 20.10 условие 2 требовало метку
«ready» в карточке. Но `mesh_bind` после привязки переводит товар в `stale` (фото сменилось) или
`quarantine` (ревизия выведена) — и такой комплект, уже скачанный, записанный и привязанный,
лежал на приёмнике вечно: 17–20.10 там стояли 39 таких (32 stale, 7 quarantine) и ни одного
другого. «Записано в базу» по правилу владельца — это запись в реестре, а не текущая оценка меша.

КОМПЛЕКТ С МОДЕЛЬЮ, НО НЕ В РЕЕСТРЕ старше ORPHAN_H: реестр обходит локальные копии каждые 15 минут,
так что это уже не «не успел», а сбой записи — печатаем `WARN:sink_unregistered` со списком.
Удаляем такие только явно (`--apply --orphans`): локальная копия есть (условие 1), с приёмника
теряется лишь кэш, но причину сбоя должен увидеть человек.

  ~/venvs/scout/bin/python receiver_purge.py                     # показать, что удалил бы
  ~/venvs/scout/bin/python receiver_purge.py --apply             # удалить
  ~/venvs/scout/bin/python receiver_purge.py --apply --orphans   # + не записанные в реестр
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.environ.get('MESH_SRV', 'root@89.167.127.0')
PORT = os.environ.get('MESH_SSH_PORT', '22222')
REMOTE = os.environ.get('MESH_ROOT_REMOTE', '/opt/remlab/meshes')
LOCAL = os.path.expanduser(os.environ.get('MESH_LOCAL', '~/scout-scenes/meshes-hunyuan'))
RETAIN_H = float(os.environ.get('MESH_RECV_RETAIN_H', '6'))
# ПОРОГ «ТЕСНО» — НЕ ЗДЕСЬ (20.10, mesh-12). До 20.10 тут жили свои 6 ГБ по сумме `du` комплектов,
# а ворота (`sink_health`) судили по счётчику приёмника. 17.10 счётчик показывал 7.1 ГБ при 0.6 ГБ
# комплектов — ворота закрыты, чистка «не тесно», пул стоял. Теперь и порог, и мера — из
# `sink_health` (лестница там). Здесь — только сторож расхождения: счётчик приёмника больше
# настоящего объёма каталога на DRIFT_WARN_GB → `WARN:sink_counter_drift` (лечение — перезапуск
# приёмника, он пересчитывает каталог при старте).
DRIFT_WARN_GB = float(os.environ.get('MESH_RECV_DRIFT_WARN_GB', '0.5'))
ORPHAN_H = float(os.environ.get('MESH_RECV_ORPHAN_H', '48'))
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


def sink_delete(prefixes: list) -> tuple[int, int]:
    """Удаляет префиксы ЧЕРЕЗ API приёмника. Возвращает (удалено, не смогли).

    ПОЧЕМУ НЕ `rm -rf` ПО SSH (04.09, подтверждено замером). Приёмник считает размер каталога
    инкрементально (`receiver._SIZE`) и вычитает байты ТОЛЬКО в своём `DELETE /prefix/...`.
    Удаление мимо API освобождает диск, но счётчик не трогает — он умеет только расти. К
    18:00 04.09 приёмник докладывал 7.37 ГБ при реальных 5.13 ГБ; `sink_health` краснеет уже
    на 7 ГБ, поэтому сторож погасил пул, хотя места было полно. Лечилось только перезапуском
    контейнера (счётчик пересчитывается при старте) — то есть вручную.
    """
    import sink_health  # noqa: PLC0415 — только ради токена, кругового импорта нет
    tok = sink_health.sink_token()
    if not tok:
        print('нет токена приёмника — удалить через API не могу, НИЧЕГО не удаляю')
        return 0, len(prefixes)
    base = sink_health.SINK_URL
    done, failed = 0, 0
    for d in prefixes:
        rel = d.strip('/')
        req = urllib.request.Request(f'{base}/prefix/{urllib.parse.quote(rel)}', method='DELETE',
                                     headers={'Authorization': f'Bearer {tok}',
                                              'User-Agent': 'remlab-purge'})
        try:
            urllib.request.urlopen(req, timeout=60).read()
            done += 1
        except urllib.error.HTTPError as e:
            # 404 — уже нет: считаем успехом, счётчику вычитать нечего
            if e.code == 404:
                done += 1
            else:
                failed += 1
                if failed <= 3:
                    print(f'  не удалил {rel}: HTTP {e.code}')
        except Exception as e:  # noqa: BLE001
            failed += 1
            if failed <= 3:
                print(f'  не удалил {rel}: {type(e).__name__}: {str(e)[:60]}')
    return done, failed


def remote_bytes() -> int:
    """Настоящий объём ВСЕГО каталога приёмника (`du`) — только для сторожа расхождения со счётчиком;
    решения принимаются по мере `sink_health.measure()`."""
    return int(ssh(f"du -sb {REMOTE} | cut -f1").strip())


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
        done, failed = sink_delete(doomed)
        if failed:
            print(f'.staging: не удалось убрать {failed}')
        return done
    return 0


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


def registered_dirs() -> set:
    """Каталоги комплектов (относительно LOCAL), записанные в реестр поколений."""
    r = subprocess.run(PSQL, input='select path from mesh_generations;', capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'psql: {r.stderr[:200]}')
    root = LOCAL.rstrip('/') + '/'
    return {p.strip()[len(root):] for p in r.stdout.splitlines() if p.strip().startswith(root)}


def local_bytes(d: str) -> int:
    p = os.path.join(LOCAL, d)
    if not os.path.isdir(p):
        return -1
    return sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(p) for f in fs)


def has_model(d: str) -> bool:
    return os.path.exists(os.path.join(LOCAL, d, 'model.glb'))


def decide(sets: list, registered: set, tight: bool, local_bytes_of=None, model_in=None) -> tuple:
    """Что удалить. → (к удалению, {причина: сколько оставлено}, не в реестре старше ORPHAN_H).
    Чистая функция: стенд (`tests_sink_gate.py`) подаёт свои комплекты и локальные объёмы."""
    local_bytes_of = local_bytes_of or local_bytes
    model_in = model_in or has_model
    purge, orphans = [], []
    keep = {'молодые': 0, 'нет локально': 0, 'объём меньше': 0, 'нет в реестре': 0}
    for d, size, age_h in sets:
        loc = local_bytes_of(d)
        if loc < 0:
            keep['нет локально'] += 1
            continue
        if loc < size:
            keep['объём меньше'] += 1
            continue
        if model_in(d) and d not in registered:
            keep['нет в реестре'] += 1
            if age_h >= ORPHAN_H:
                orphans.append(d)
            continue
        if age_h < RETAIN_H and not tight:
            keep['молодые'] += 1
            continue
        purge.append(d)
    return purge, keep, orphans


def main() -> None:
    apply = '--apply' in sys.argv
    with_orphans = '--orphans' in sys.argv
    try:
        sets = remote_sets()
    except Exception as e:  # noqa: BLE001 — приёмник недоступен: это не авария конвейера
        print(f'приёмник недоступен ({type(e).__name__}: {str(e)[:80]}) — очистку пропускаю')
        return
    try:
        sweep_staging(apply)
    except Exception as e:  # noqa: BLE001 — уборка остатков не должна ломать основную чистку
        print(f'.staging: не разобрал ({type(e).__name__}: {str(e)[:80]})')
    import sink_health as SH  # noqa: PLC0415 — рядом лежит, кругового импорта нет
    warns = []
    try:
        m = SH.measure()
    except Exception as e:  # noqa: BLE001 — /health молчит: удалить через API всё равно не выйдет
        m = None
        print(f'приёмник не ответил на /health ({type(e).__name__}) — меры нет, срок хранения соблюдаю')
    why = SH.tight(m) if m else ''
    if m:
        try:
            real = remote_bytes() / 2 ** 30
            if m['dir_gb'] - real > DRIFT_WARN_GB:
                warns.append(f'WARN:sink_counter_drift: приёмник считает каталог {m["dir_gb"]:.2f} ГБ, на диске '
                             f'{real:.2f} ГБ — счётчик завышен на {m["dir_gb"] - real:.1f} ГБ, ворота закроются раньше '
                             f'времени; лечит перезапуск приёмника (пересчёт при старте)')
        except Exception as e:  # noqa: BLE001 — сторож расхождения не должен ломать чистку
            print(f'настоящий объём каталога не измерил ({type(e).__name__}: {str(e)[:60]})')
    if not sets:
        print('на приёмнике пусто')
        for w in warns:
            print(w)
        return
    purge, keep, orphans = decide(sets, registered_dirs(), bool(why))
    kits_gb = sum(s[1] for s in sets) / 2 ** 30
    print(f'на приёмнике комплектов: {len(sets)} ({kits_gb:.1f} ГБ)'
          + (f'; приёмник: каталог {m["dir_gb"]:.1f} ГБ, свободно {m["free_gb"]:.1f} ГБ' if m else '')
          + (f' — тесно: {why}, срок хранения не соблюдаю' if why else ''))
    print(f'к удалению: {len(purge)}; оставляю: '
          + ', '.join(f'{k} {v}' for k, v in keep.items() if v))
    if orphans:
        warns.append(f'WARN:sink_unregistered: {len(orphans)} комплектов с моделью старше {ORPHAN_H:.0f} ч не записаны '
                     f'в реестр (пример: {orphans[0]}) — удаляю только с --orphans')
        if with_orphans:
            purge += orphans
    try:
        if not purge:
            return
        if not apply:
            print('это разбор без действий. Удалить: --apply' + (' (+ --orphans)' if orphans else ''))
            return
        done, failed = sink_delete(purge)
        after = ''
        try:
            a = SH.measure()
            after = f'; приёмник: каталог {a["dir_gb"]:.1f} ГБ, свободно {a["free_gb"]:.1f} ГБ'
        except Exception:  # noqa: BLE001 — итог печатаем и без «после»
            pass
        print(f'удалено комплектов: {done}; не удалось: {failed}{after}')
        if failed:
            # Молчаливый успех при неудалении — как раз то, из-за чего таймер докладывал бы «ок»,
            # а приёмник копился. Пусть вызывающий видит отказ.
            sys.exit(1)
    finally:
        # Предупреждения — ПОСЛЕДНИМИ строками: сторож приёмника пишет в журнал хвост вывода.
        for w in warns:
            print(w)


if __name__ == '__main__':
    main()
