#!/usr/bin/env python3
"""Прополка болванок формы (`shape.glb`) — промежуточного шага, который копится молча.

ЗАЧЕМ (02.10). Генератор отдаёт два GLB: `shape.glb` — серая болванка формы без текстур, и
`model.glb` — готовый PBR-меш, который и есть продукт. Болванка в среднем в три раза тяжелее
продукта (14 МБ против 4,7 МБ), остаётся на диске навсегда и к 02.10 заняла 32,6 ГБ против
9,3 ГБ у самих мешей — больше трети диска DEV-машины ушло на промежуточный шаг.

ПОЧЕМУ БОЛВАНКУ МОЖНО УБИРАТЬ. Вердикт гейта по форме уже записан рядом в `verdict.json` и
`manifest.json` (`slab_excess`, `gate_reason`) — то есть ВЫВОД сохранён, пересматривать саму
болванку незачем. Реестр поколений, привязка к товару и ориентация читают только `model.glb`
(`ingest_registry.py`, `mesh_bind.py`, `orient_worker.py`).

ЧТО ПРИ ЭТОМ ТЕРЯЕТСЯ — ДВЕ ВЕЩИ, ОБЕ ОСОЗНАННО (уточнено 02.10 по разбору `verify`):
 1. `blocked_page.py:105-113` рисует форму для КАЖДОГО job-каталога запрошенных SKU, без
    оглядки на `model.glb` (фильтра там нет — первая формулировка этого файла врала). Падения
    нет (`:111` проверяет наличие), но у закреплённых SKU, у которых модель есть, колонка
    «что выдал генератор» теперь пустая.
 2. Перепокраска сохранённой формы — рычаг цвета из ADR-0145 (`core/mesh-color.md`): paint =
    42 % стоимости задания, геометрия не меняется. Для прополотых мешей он недоступен — цвет
    лечится полным перегоном. 02.10 за это заплатили 2132 болванками (ADR-0231), и владелец
    выбрал иначе: **болванка живёт, пока меш не принят** (ADR-0233, условие 5). Теперь рычаг
    остаётся ровно там, где нужен: у непросмотренных и забракованных мешей.

ЧТО ЗНАЧИТ «ПРИНЯТ». Кнопки «принять» в приёмке нет — есть «переделать» и «отменить», решения
пишутся только отрицательные. Поэтому принято = владелец ВИДЕЛ карточку и не забраковал:
`seen_at` есть, статус `open` (правило — `lib/mesh-audit/rules.ts:isAccepted`). Признак живёт на
проде, поэтому спрашиваем его у прода (`GET /api/lab/mesh-audit/items?scope=accepted`, тот же
Bearer, что у `mesh_audit_sync.py`), а карту «каталог → поколение» берём из базы DEV
(`mesh_generations.path`, пишет `ingest_registry.py:133`). Новое поколение сбрасывает
«просмотрено» (`repo-items.ts:102`), так что приёмка не протекает на следующую попытку.
Не ответил прод или база — прополка не делает НИЧЕГО, как и при недоступном приёмнике.

ЧТО СЧИТАЕТСЯ «МОЖНО УДАЛЯТЬ» — шесть условий разом:
  1) рядом есть `model.glb` — продукт на месте, болванка больше не единственный результат;
  2) есть `complete.json` — комплект опубликован целиком, а не оборван на середине закачки;
  3) есть `manifest.json` — паспорт с вердиктом гейта и параметрами прогона сохранён;
  4) КОМПЛЕКТА УЖЕ НЕТ НА ПРИЁМНИКЕ (одна ssh-перепись за прогон) — см. ниже, это главное;
  5) МЕШ ПРИНЯТ ВЛАДЕЛЬЦЕМ на `/lab/mesh-audit` (решение владельца 02.10, ADR-0233) — см. ниже;
  6) комплект старше MIN_AGE_H часов — дешёвый пол, если переписи выше пусты по чужой причине.
Проверки в базе здесь НЕТ сознательно: в конвейере шаг стоит после `ingest_registry.py` и
`mesh_bind.py`, а на судьбу болванки запись в базу всё равно не влияет — она про `model.glb`.

ПОЧЕМУ УСЛОВИЕ 4 — САМОЕ ВАЖНОЕ (поймано 02.10 ДО первого запуска). И откачка, и чистка
приёмника сравнивают ОБЪЁМ локальной копии с серверной:
  * `receiver_purge.py:229` — `if loc < size: keep['объём меньше']` — комплект НИКОГДА не
    уедет с приёмника, а приёмник транзитный: дорастёт до порога, ответит 507, и ноды будут
    стоять оплаченными (ровно грабля ADR-0199, 7 нодо-часов);
  * `drain.sh:65-74` — при `локально < на сервере` комплект считается «перевыложенным полнее»
    и качается ЗАНОВО, то есть болванка возвращается, а прополка и откачка начинают пинг-понг.
На 02.10 на приёмнике лежало 195 комплектов, и ВСЕ 195 попали бы под чистку без этой проверки.
Если приёмник недоступен, прополка НИЧЕГО не делает (место подождёт, простой нод — нет);
обойти можно только явным `--no-sink-check`, когда переписал приёмник руками.

ЧЕГО НЕЛЬЗЯ ДЕЛАТЬ НИ ПРИ КАКИХ УСЛОВИЯХ. Болванку БЕЗ `model.glb` (02.10 таких 43) трогать
нельзя: `wave_missing.py:done_inputs()` считает задание сделанным по `model.glb` ИЛИ
`shape.glb`, и без неё волна вернёт этот SKU в очередь и заплатит за GPU второй раз. Поэтому
условие 1 — не удобство, а защита денег.

ЖУРНАЛ. Удалённое пишем строкой в `pruned-shapes.jsonl` рядом с хранилищем: «файла нет» должно
читаться как «убрали тогда-то», а не превращаться в загадку через месяц.

  ~/venvs/scout/bin/python prune_shapes.py            # показать, что удалил бы
  ~/venvs/scout/bin/python prune_shapes.py --apply    # удалить
  ~/venvs/scout/bin/python prune_shapes.py --selftest # самопроверка без диска проекта
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SRC = os.path.expanduser(os.environ.get(
    'PRUNE_SRC', '~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))
JOURNAL = os.path.expanduser(os.environ.get(
    'PRUNE_JOURNAL', '~/scout-scenes/meshes-hunyuan/pruned-shapes.jsonl'))
# Выдержка поверх срока хранения приёмника (`receiver_purge.RETAIN_H`=6): даже если перепись
# приёмника почему-то солгала, свежий комплект прополка не тронет.
MIN_AGE_H = float(os.environ.get('PRUNE_MIN_AGE_H', '48'))
SRV = os.environ.get('MESH_SRV', 'root@89.167.127.0')
PORT = os.environ.get('MESH_SSH_PORT', '22222')
REMOTE = os.environ.get('MESH_ROOT_REMOTE', '/opt/remlab/meshes')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-t', '-A', '-F', '\t']
GB = 1 << 30


def accepted_keys() -> set | None:
    """Поколения, принятые владельцем, — у прода. `None` — прод не ответил."""
    cfg = os.path.expanduser('~/.config/remlab/env')
    if os.path.exists(cfg):
        for ln in open(cfg, encoding='utf-8'):
            if '=' in ln and not ln.strip().startswith('#'):
                k, v = ln.strip().split('=', 1)
                os.environ.setdefault(k, v)
    tok = os.environ.get('MESH_REVIEW_MACHINE_TOKEN', '')
    if not tok:
        print('  нет MESH_REVIEW_MACHINE_TOKEN (см. _secrets/ACCESS.md)', flush=True)
        return None
    url = os.environ.get('MESH_REVIEW_URL', 'https://remont-lab.online').rstrip('/')
    req = urllib.request.Request(f'{url}/api/lab/mesh-audit/items?scope=accepted',
                                 headers={'Authorization': f'Bearer {tok}'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 — свой же прод
            keys = json.loads(r.read()).get('keys')
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f'  приёмка владельца не опрошена ({e})', flush=True)
        return None
    if not isinstance(keys, list):
        print('  приёмка владельца ответила без списка принятых', flush=True)
        return None
    return set(keys)


def generation_of_path() -> dict | None:
    """Карта «job-каталог → ключ поколения» из базы DEV. `None` — база не ответила."""
    try:
        r = subprocess.run(PSQL, input='select path, generation_key from mesh_generations;',
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'  база поколений не опрошена ({e})', flush=True)
        return None
    if r.returncode != 0:
        print(f'  база поколений ответила кодом {r.returncode}: '
              f'{r.stderr.strip()[:200]}', flush=True)
        return None
    out = {}
    for ln in r.stdout.split('\n'):
        if '\t' in ln:
            path, gk = ln.rsplit('\t', 1)
            out[os.path.normpath(path.strip())] = gk.strip()
    return out


def key(job: str) -> str:
    """Ключ комплекта «<sku>/<job_id>» — общий для локального дерева и приёмника."""
    return '/'.join(os.path.normpath(job).split(os.sep)[-2:])


def sink_probe() -> str | None:
    """Сырой ответ приёмника ОДНОЙ ssh-сессией. `None` — не ответил."""
    # МАРКЕР КОРНЯ — не формальность. Пустая перепись и в норме бывает (purge всё убрал), так
    # что «пусто» само по себе разрешает прополку. Значит ошибка в `MESH_ROOT_REMOTE`, указавшая
    # на существующий ЧУЖОЙ каталог, выглядела бы как «приёмник пуст» и пустила бы под нож всё
    # старше выдержки. Поэтому корень обязан предъявить себя: в нём есть `meshes/`.
    cmd = (f"test -d {REMOTE}/meshes && echo __ROOT_OK__; "
           f"find {REMOTE} -name complete.json -printf '%h\\n' 2>/dev/null")
    try:
        r = subprocess.run(['ssh', '-p', PORT, '-o', 'BatchMode=yes',
                            '-o', 'ConnectTimeout=15', SRV, cmd],
                           capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'  приёмник не опрошен ({e})', flush=True)
        return None
    if r.returncode != 0:
        print(f'  приёмник ответил кодом {r.returncode}: {r.stderr.strip()[:200]}', flush=True)
        return None
    return r.stdout


def parse_sink(out: str | None) -> set | None:
    """Разобрать перепись. `None` — приёмника нет или корень себя не предъявил."""
    if out is None:
        return None
    lines = [ln for ln in out.split('\n') if ln.strip()]
    if '__ROOT_OK__' not in lines:
        print(f'  корень приёмника {REMOTE} не предъявил себя (нет {REMOTE}/meshes)', flush=True)
        return None
    return {key(ln) for ln in lines if ln != '__ROOT_OK__'}


def resolve_sink(argv, probe) -> tuple:
    """Решить, с какой переписью работать. Возвращает `(перепись, останавливаться ли)`."""
    if '--no-sink-check' in argv:
        # Обход — только для ручного прогона, когда приёмник переписан глазами. В конвейере
        # флага нет: недоступный приёмник должен останавливать прополку, а не разрешать её.
        print('  перепись приёмника ПРОПУЩЕНА по флагу --no-sink-check', flush=True)
        return set(), False
    sink = parse_sink(probe())
    if sink is None:
        print('  приёмник не переписан — ничего не трогаю (иначе комплект застрянет на нём'
              ' навсегда: receiver_purge.py:229)', flush=True)
        return None, True
    print(f'  на приёмнике комплектов: {len(sink)}', flush=True)
    return sink, False


def classify(job: str, sink: set, now: float, accepted: set, gen_of: dict) -> str:
    """Что делать с болванкой: 'del' | 'keep_no_model' | 'keep_partial' | 'keep_sink'
    | 'keep_unaccepted' | 'keep_young' | 'none'."""
    sg = os.path.join(job, 'shape.glb')
    if not os.path.isfile(sg):
        return 'none'
    if not os.path.isfile(os.path.join(job, 'model.glb')):
        return 'keep_no_model'
    done = os.path.join(job, 'complete.json')
    if not (os.path.isfile(done) and os.path.isfile(os.path.join(job, 'manifest.json'))):
        return 'keep_partial'
    if key(job) in sink:
        return 'keep_sink'
    # ПРИЁМКА ВЛАДЕЛЬЦА (ADR-0233). Поколения нет в карте — значит реестр про этот каталог ещё
    # не знает: тоже «не принято». Так ошибка в карте играет в сторону сохранения болванки.
    if gen_of.get(os.path.normpath(job)) not in accepted:
        return 'keep_unaccepted'
    try:
        age_h = (now - os.path.getmtime(done)) / 3600
    except OSError:
        return 'keep_partial'
    if age_h < MIN_AGE_H:
        return 'keep_young'
    return 'del'


def prune(src: str, journal: str, apply: bool, sink: set,
          accepted: set, gen_of: dict) -> dict:
    """Пройти хранилище и (при `apply`) убрать болванки. Возвращает счётчики."""
    c = {'комплектов': 0, 'удалить': 0, 'байт': 0, 'без model.glb': 0,
         'неполный комплект': 0, 'на приёмнике': 0, 'не принято владельцем': 0,
         'молодые': 0, 'ошибок': 0}
    done = []
    now = time.time()
    for job in sorted(glob.glob(os.path.join(src, '*', '*'))):
        if not os.path.isdir(job):
            continue
        c['комплектов'] += 1
        verdict = classify(job, sink, now, accepted, gen_of)
        if verdict == 'none':
            continue
        if verdict == 'keep_no_model':
            c['без model.glb'] += 1
            continue
        if verdict == 'keep_partial':
            c['неполный комплект'] += 1
            continue
        if verdict == 'keep_sink':
            c['на приёмнике'] += 1
            continue
        if verdict == 'keep_unaccepted':
            c['не принято владельцем'] += 1
            continue
        if verdict == 'keep_young':
            c['молодые'] += 1
            continue
        sg = os.path.join(job, 'shape.glb')
        try:
            size = os.path.getsize(sg)
        except OSError as e:  # размер не прочитался — считаем ошибкой, а не «нечего делать»
            c['ошибок'] += 1
            print(f'  ОШИБКА размера {sg}: {e}', flush=True)
            continue
        c['удалить'] += 1
        c['байт'] += size
        if not apply:
            continue
        try:
            os.remove(sg)
        except FileNotFoundError:
            # ГОНКА, А НЕ АВАРИЯ. Замка у прополки нет и не нужно: ручной прогон рядом с
            # конвейером мог снести этот же файл секунду назад. Исход тот же, что и задуман,
            # поэтому в отказы не пишем — иначе шаг печатал бы «СБОЙ» на безобидной гонке.
            c['удалить'] -= 1
            c['байт'] -= size
            continue
        except OSError as e:
            c['ошибок'] += 1
            c['удалить'] -= 1
            c['байт'] -= size
            print(f'  ОШИБКА удаления {sg}: {e}', flush=True)
            continue
        done.append({'path': os.path.relpath(sg, src), 'bytes': size,
                     'at': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
    if apply and done:
        try:
            os.makedirs(os.path.dirname(journal), exist_ok=True)
            with open(journal, 'a', encoding='utf-8') as fh:
                for row in done:
                    fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        except OSError as e:
            c['ошибок'] += 1
            print(f'  ОШИБКА записи журнала {journal}: {e}', flush=True)
    return c


def _selftest() -> int:
    """Самопроверка на временном дереве: сухой прогон не удаляет, защиты работают."""
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'v2')
        full = ('model.glb', 'shape.glb', 'complete.json', 'manifest.json')
        cases = {
            'ok': full,
            'no_model': ('shape.glb', 'manifest.json'),
            'partial': ('model.glb', 'shape.glb', 'manifest.json'),
            'no_shape': ('model.glb', 'complete.json', 'manifest.json'),
            'on_sink': full,      # комплект ещё лежит на приёмнике — трогать нельзя
            'young': full,        # моложе выдержки
            'unaccepted': full,   # владелец ещё не принял — рычаг перепокраски нужен (ADR-0233)
            'unknown_gen': full,  # каталога нет в реестре поколений — тоже «не принято»
        }
        old = time.time() - (MIN_AGE_H + 24) * 3600
        for name, files in cases.items():
            d = os.path.join(src, f'sku_{name}', 'job')
            os.makedirs(d)
            for f in files:
                with open(os.path.join(d, f), 'wb') as fh:
                    fh.write(b'x' * 100)
            if name != 'young':
                done_p = os.path.join(d, 'complete.json')
                if os.path.exists(done_p):
                    os.utime(done_p, (old, old))
        journal = os.path.join(tmp, 'journal.jsonl')
        sink = {'sku_on_sink/job'}
        # Принято всё, кроме 'unaccepted'; 'unknown_gen' вообще не попал в реестр поколений.
        gen_of, accepted = {}, set()
        for name in cases:
            if name == 'unknown_gen':
                continue
            gk = f'gen-{name}'
            gen_of[os.path.join(src, f'sku_{name}', 'job')] = gk
            if name != 'unaccepted':
                accepted.add(gk)

        dry = prune(src, journal, apply=False, sink=sink, accepted=accepted, gen_of=gen_of)
        if (dry['удалить'] != 1 or dry['без model.glb'] != 1 or dry['неполный комплект'] != 1
                or dry['на приёмнике'] != 1 or dry['молодые'] != 1
                or dry['не принято владельцем'] != 2):
            bad += 1
            print(f'  FAIL раскладка сухого прогона: {dry}')
        if not os.path.exists(os.path.join(src, 'sku_ok', 'job', 'shape.glb')):
            bad += 1
            print('  FAIL сухой прогон УДАЛИЛ файл')
        if os.path.exists(journal):
            bad += 1
            print('  FAIL сухой прогон написал журнал')

        real = prune(src, journal, apply=True, sink=sink, accepted=accepted, gen_of=gen_of)
        if real['удалить'] != 1 or real['ошибок'] != 0:
            bad += 1
            print(f'  FAIL раскладка удаления: {real}')
        if os.path.exists(os.path.join(src, 'sku_ok', 'job', 'shape.glb')):
            bad += 1
            print('  FAIL болванка не удалена там, где можно')
        for name in ('no_model', 'partial', 'on_sink', 'young', 'unaccepted', 'unknown_gen'):
            if not os.path.exists(os.path.join(src, f'sku_{name}', 'job', 'shape.glb')):
                bad += 1
                print(f'  FAIL удалена защищённая болванка: {name}')
        if not os.path.exists(os.path.join(src, 'sku_ok', 'job', 'model.glb')):
            bad += 1
            print('  FAIL задет продукт model.glb')
        try:
            rows = [json.loads(ln) for ln in open(journal, encoding='utf-8') if ln.strip()]
        except OSError as e:
            rows = []
            bad += 1
            print(f'  FAIL журнал не прочитался: {e}')
        if len(rows) != 1 or rows[0]['bytes'] != 100:
            bad += 1
            print(f'  FAIL журнал: {rows}')

        again = prune(src, journal, apply=True, sink=sink, accepted=accepted, gen_of=gen_of)
        if again['удалить'] != 0:
            bad += 1
            print(f'  FAIL повторный прогон не идемпотентен: {again}')
        if key('/a/b/sku_x/job_y') != 'sku_x/job_y':
            bad += 1
            print('  FAIL ключ комплекта считается не по двум последним частям пути')

    # ВЕТКИ «НИЧЕГО НЕ ДЕЛАТЬ» — самые важные и раньше не покрывались (находка verify 02.10):
    # гарантия «приёмник недоступен → прополка стоит» подтверждалась только чтением кода.
    root_ok = '__ROOT_OK__\n/opt/remlab/meshes/meshes/hunyuan21/v2/sku/job\n'
    for name, out, want_stop, want_len in (
            ('приёмник молчит', None, True, None),
            ('корень не предъявил себя', '/opt/x/v2/sku/job\n', True, None),
            ('приёмник пуст, но корень на месте', '__ROOT_OK__\n', False, 0),
            ('приёмник с комплектом', root_ok, False, 1)):
        sink, stop = resolve_sink([], lambda o=out: o)
        if stop != want_stop or (want_len is not None and len(sink) != want_len):
            bad += 1
            print(f'  FAIL ветка «{name}»: stop={stop}, перепись={sink}')
    sink, stop = resolve_sink(['--no-sink-check'], lambda: None)
    if stop or sink != set():
        bad += 1
        print(f'  FAIL --no-sink-check: stop={stop}, перепись={sink}')
    print('самопроверка prune_shapes: ' + ('ОК' if not bad else f'ПРОВАЛОВ {bad}'))
    return bad


def main() -> int:
    if '--selftest' in sys.argv:
        return 1 if _selftest() else 0
    apply = '--apply' in sys.argv
    if not os.path.isdir(SRC):
        print(f'нет хранилища {SRC} — нечего полоть')
        return 0
    print(f'{"УДАЛЯЮ" if apply else "СУХОЙ ПРОГОН (ничего не удаляю)"}: болванки в {SRC}')
    sink, stop = resolve_sink(sys.argv, sink_probe)
    if stop:
        return 0
    accepted = accepted_keys()
    if accepted is None:
        print('  приёмка владельца не переписана — ничего не трогаю: без неё болванка ушла бы'
              ' у непринятого меша и унесла рычаг перепокраски (ADR-0233)')
        return 0
    gen_of = generation_of_path()
    if gen_of is None:
        print('  карты «каталог → поколение» нет — ничего не трогаю: сопоставить приёмку'
              ' с каталогами нечем')
        return 0
    print(f'  принято владельцем поколений: {len(accepted)}; в реестре каталогов: {len(gen_of)}')
    c = prune(SRC, JOURNAL, apply, sink, accepted, gen_of)
    print('  ' + ', '.join(f'{k}: {v}' for k, v in c.items() if k != 'байт')
          + f", объём: {c['байт'] / GB:.2f} ГБ")
    if c['ошибок']:
        print(f'  ОТКАЗОВ {c["ошибок"]} — разобрать, молча не пропускаем')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
