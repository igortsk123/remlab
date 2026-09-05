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
"""
import fcntl
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.expanduser('~/scout-scenes/mesh-audit/posters')
LOCK = os.path.expanduser('~/scout-scenes/mesh-audit/posters.lock')
REMOTE = 'root@89.167.127.0:/opt/remlab/test/mesh-audit/posters/'
CHUNK = int(os.environ.get('POSTER_CHUNK', '20'))
SIZE = 320
YAW, PITCH = 35.0, 12.0   # три четверти: видны фронт и бок — то, по чему владелец судит форму


def poster_name(generation_key: str) -> str:
    """Имя файла постера из ключа поколения: `|` и `:` в имени файла и URL ни к чему."""
    return generation_key.replace('|', '_').replace(':', '-') + '.jpg'


def _todo() -> list[tuple[str, str]]:
    """(generation_key, каталог) поколений без постера — по порядку регистрации."""
    from mesh_queue import db
    rows = db("select generation_key, path from mesh_generations order by generated_at, generation_key")
    return [(r[0], r[1]) for r in rows if len(r) == 2 and not os.path.exists(os.path.join(OUT, poster_name(r[0])))]


def render_one(generation_key: str, path: str) -> bool:
    from PIL import Image

    from mesh_render import load_parts, render
    glb = os.path.join(path, 'model.glb')
    if not os.path.exists(glb):
        return False
    im = render(load_parts(glb), YAW, PITCH, size=(SIZE, SIZE))
    bg = Image.new('RGB', im.size, (244, 244, 242))
    bg.paste(im, (0, 0), im)
    dst = os.path.join(OUT, poster_name(generation_key))
    tmp = dst + '.tmp'
    bg.save(tmp, 'JPEG', quality=85)
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


def main() -> int:
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
    t0, total = time.time(), 0
    while time.time() - t0 < budget:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), '--child', str(CHUNK)],
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
    print(f'постеры: отрисовано {total}, всего файлов {len(os.listdir(OUT))}, '
          f'{(time.time() - t0) / 60:.1f} мин', flush=True)
    if '--publish' in sys.argv and total:
        publish()
    return 0


if __name__ == '__main__':
    sys.exit(main())
