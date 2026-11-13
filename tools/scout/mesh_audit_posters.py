#!/usr/bin/env python3
"""Постеры для страницы ручной приёмки мешей (/lab/mesh-audit): рендер 320px на каждое поколение.

Постер — то, что владелец видит СРАЗУ: страница из 20 карточек открывается мгновенно, а
7,6-мегабайтная модель грузится только по клику. Постеры живут постоянно (~40 МБ на весь пул),
поэтому любая страница видна даже вне активной партии моделей.

Рендер — `mesh_render.py` (numpy, без GPU), ~2 с на модель. trimesh не отдаёт память (урок 391),
поэтому родитель БЕЗ trimesh запускает себя дочерними процессами по CHUNK рендеров и останавливается,
когда рендерить нечего или кончился бюджет времени. Дочерний процесс ничего не удаляет.

  ~/venvs/scout/bin/python mesh_audit_posters.py                 # всё, чего нет (бюджет 1 ч)
  ~/venvs/scout/bin/python mesh_audit_posters.py --budget 300    # шаг конвейера: 5 минут
  ~/venvs/scout/bin/python mesh_audit_posters.py --publish       # …и rsync постеров на прод
  ~/venvs/scout/bin/python mesh_audit_posters.py --hd --limit 300 # снимки 1024 px для увеличения (/lab/mesh-check,
                                                                  # T-20261112-118): порция, ночью под heavy-slot --cores 1 --long
  ~/venvs/scout/bin/python mesh_audit_posters.py --hd --part 1/2  # доля 1 из 2 (вторая — --part 2/2, другим ядром; свой замок)
Снимок 1024 (T-20261113-05) — рисуется в 2048 и уменьшается (края без лесенки), jpg 92; первыми — карточки совсем без снимка; новым
карточкам маленький не нужен: страница берёт большой (`MeshCheckCard.tsx`).
Снимок 1024 — тот же ракурс и фон, свой каталог `posters-hd` и свой замок: обычные постеры он не держит. Тот же файл
`poster_name(gk)`, поэтому мост находит пару по ключу поколения (`mesh_audit_sync.current_items` → `posterHdUrl`).
"""
import fcntl
import os
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
HD = '--hd' in sys.argv


def parse_part(argv: list) -> tuple[int, int]:
    """`--part N/M` — доля N из M (два ядра без пересечений); без ключа — 1/1."""
    if '--part' not in argv:
        return 1, 1
    n, m = (int(x) for x in argv[argv.index('--part') + 1].split('/'))
    if not 1 <= n <= m:
        raise SystemExit(f'--part {n}/{m}: нужно 1 ≤ N ≤ M')
    return n, m


PART = parse_part(sys.argv)
OUT_SD = os.path.expanduser('~/scout-scenes/mesh-audit/posters')
OUT_HD = os.path.expanduser('~/scout-scenes/mesh-audit/posters-hd')
OUT = OUT_HD if HD else OUT_SD
LOCK = os.path.expanduser('~/scout-scenes/mesh-audit/posters-hd' if HD else '~/scout-scenes/mesh-audit/posters') \
    + (f'-{PART[0]}of{PART[1]}' if PART != (1, 1) else '') + '.lock'
REMOTE = 'root@89.167.127.0:/opt/remlab/test/mesh-audit/posters-hd/' if HD else 'root@89.167.127.0:/opt/remlab/test/mesh-audit/posters/'
CHUNK = int(os.environ.get('POSTER_CHUNK', '20'))
SIZE = 1024 if HD else 320
# СНИМОК 1024 БЕЗ ЛЕСЕНКИ (T-20261113-05, владелец TG 1420: «при увеличении весь в квадратиках»): рисуем вдвое крупнее и уменьшаем
# (сглаживание краёв — у `mesh_render.render` его нет), jpg 92 без прореживания цвета; 40–90 КБ, ≈ 8,5 с на модель (проба 13.11)
SUPERSAMPLE = 2 if HD else 1
QUALITY = 92 if HD else 85
SUBSAMPLING = 0 if HD else -1   # 0 — 4:4:4; -1 — как по умолчанию у PIL
YAW, PITCH = 35.0, 12.0   # три четверти: видны фронт и бок — то, по чему владелец судит форму


def poster_name(generation_key: str) -> str:
    """Имя файла постера из ключа поколения: `|` и `:` в имени файла и URL ни к чему."""
    return generation_key.replace('|', '_').replace(':', '-') + '.jpg'


# Порядок обхода страницы проверки — как разделы `lib/mesh-audit/sections.ts` (снимки 1024 нужны сперва тем, кого смотрят первыми)
HD_ROLE_ORDER = ['диван', 'кресло', 'стул', 'столик', 'стол обеденный', 'тв-тумба', 'комод', 'шкаф', 'стеллаж', 'витрина',
                 'стенка', 'пуф', 'кашпо', 'ваза', 'торшер', 'лампа', 'люстра', 'камин']


def hd_order(items: list[dict], has_sd=lambda gk: False) -> list[str]:
    """Ключи текущих поколений карточек страницы: сперва карточки совсем без снимка (у них на странице «снимка ещё нет»), затем с
    маленьким; внутри — порядок разделов и карточек. Чистая функция (селфтест)."""
    rank = {r: i for i, r in enumerate(HD_ROLE_ORDER)}
    idx = sorted(range(len(items)), key=lambda i: (bool(has_sd(items[i]['generationKey'])),
                                                   rank.get(items[i].get('role') or '', len(rank)), i))
    return [items[i]['generationKey'] for i in idx]


def in_part(generation_key: str, part: tuple[int, int]) -> bool:
    """Доля по ключу, а не по месту в списке: список сокращается по ходу, а ключ — нет, поэтому доли не пересекаются."""
    return zlib.crc32(generation_key.encode()) % part[1] == part[0] - 1


def _todo_hd() -> list[tuple[str, str]]:
    """Только ТЕКУЩИЕ поколения карточек страницы (старые попытки увеличивать незачем), без снимка — первыми."""
    from mesh_audit_sync import current_items
    from mesh_queue import db
    paths = {r[0]: r[1] for r in db("select generation_key, path from mesh_generations") if len(r) == 2}
    has_sd = lambda gk: os.path.exists(os.path.join(OUT_SD, poster_name(gk)))  # noqa: E731
    return [(gk, paths[gk]) for gk in hd_order(current_items(), has_sd)
            if gk in paths and in_part(gk, PART) and not os.path.exists(os.path.join(OUT, poster_name(gk)))]


def _todo() -> list[tuple[str, str]]:
    """(generation_key, каталог) поколений без постера — по порядку регистрации."""
    from mesh_queue import db
    if HD:
        return _todo_hd()
    rows = db("select generation_key, path from mesh_generations order by generated_at, generation_key")
    return [(r[0], r[1]) for r in rows if len(r) == 2 and not os.path.exists(os.path.join(OUT, poster_name(r[0])))]


def render_one(generation_key: str, path: str) -> bool:
    from PIL import Image

    from mesh_render import load_parts, render
    glb = os.path.join(path, 'model.glb')
    if not os.path.exists(glb):
        return False
    im = render(load_parts(glb), YAW, PITCH, size=(SIZE * SUPERSAMPLE, SIZE * SUPERSAMPLE))
    if SUPERSAMPLE > 1:
        im = im.resize((SIZE, SIZE), Image.LANCZOS)
    bg = Image.new('RGB', im.size, (244, 244, 242))
    bg.paste(im, (0, 0), im)
    dst = os.path.join(OUT, poster_name(generation_key))
    tmp = dst + '.tmp'
    bg.save(tmp, 'JPEG', quality=QUALITY, subsampling=SUBSAMPLING)
    os.replace(tmp, dst)
    return True


def child(n: int) -> int:
    """Дочерний процесс: не больше n рендеров и выход — память возвращается ОС."""
    done = 0
    for key, path in _todo()[:n]:
        try:
            if render_one(key, path):
                done += 1
        except Exception as e:  # noqa: BLE001 — один битый GLB не должен останавливать остальные
            print(f'  постер {key}: {type(e).__name__}: {str(e)[:80]}', flush=True)
    print(f'POSTERS_DONE {done}', flush=True)
    return 0


def publish() -> None:
    r = subprocess.run(['rsync', '-a', '--info=stats1', '-e', 'ssh -p 22222 -o BatchMode=yes',
                        OUT + '/', REMOTE], capture_output=True, text=True, timeout=1800)
    print('публикация постеров: ' + ('ok' if r.returncode == 0 else 'СБОЙ ' + r.stderr[-200:]), flush=True)


def _selftest() -> int:
    items = [{'generationKey': 'a', 'role': 'кашпо'}, {'generationKey': 'b', 'role': None}, {'generationKey': 'c', 'role': 'диван'},
             {'generationKey': 'd', 'role': 'кашпо'}, {'generationKey': 'e', 'role': 'диван'}]
    got = hd_order(items)
    ok = got == ['c', 'e', 'a', 'd', 'b']
    print(f'mesh_audit_posters selftest: порядок снимков 1024 {"ok" if ok else "ОШИБКА " + str(got)}')
    got2 = hd_order(items, lambda gk: gk in ('c', 'a'))
    ok2 = got2 == ['e', 'd', 'b', 'c', 'a']
    print(f'mesh_audit_posters selftest: без снимка — первыми {"ok" if ok2 else "ОШИБКА " + str(got2)}')
    keys = [f'k{i}' for i in range(200)]
    halves = [{k for k in keys if in_part(k, (n, 2))} for n in (1, 2)]
    ok3 = not (halves[0] & halves[1]) and halves[0] | halves[1] == set(keys) and min(map(len, halves)) > 60 \
        and all(in_part(k, (1, 1)) for k in keys) and parse_part(['x', '--part', '2/2']) == (2, 2) and parse_part([]) == (1, 1)
    print(f'mesh_audit_posters selftest: доли 1/2 и 2/2 не пересекаются и покрывают всё {"ok" if ok3 else "ОШИБКА"}')
    return 0 if ok and ok2 and ok3 else 1


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    os.makedirs(OUT, exist_ok=True)
    if '--child' in sys.argv:
        return child(int(sys.argv[sys.argv.index('--child') + 1]))
    lock = open(LOCK, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('постеры уже рендерит другой процесс', flush=True)
        return 75
    budget = float(sys.argv[sys.argv.index('--budget') + 1]) if '--budget' in sys.argv else 3600.0
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None   # порция: не больше N за заход
    t0, total = time.time(), 0
    while time.time() - t0 < budget:
        n_child = CHUNK if limit is None else min(CHUNK, limit - total)
        if n_child <= 0:
            break
        r = subprocess.run([sys.executable, os.path.abspath(__file__), '--child', str(n_child)] + (['--hd'] if HD else [])
                           + (['--part', f'{PART[0]}/{PART[1]}'] if PART != (1, 1) else []),
                           capture_output=True, text=True, timeout=max(60, budget))
        n = 0
        for ln in r.stdout.splitlines():
            if ln.startswith('POSTERS_DONE '):
                n = int(ln.split()[1])
            elif ln.strip():
                print(ln, flush=True)
        total += n
        if n == 0:
            break
    dt = time.time() - t0
    print(f'постеры{" 1024" if HD else ""}: отрисовано {total}, всего файлов {len(os.listdir(OUT))}, '
          f'{dt / 60:.1f} мин' + (f', {dt / total:.1f} с на модель' if total else ''), flush=True)
    if '--publish' in sys.argv and total:
        publish()
    return 0


if __name__ == '__main__':
    sys.exit(main())
