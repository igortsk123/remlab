#!/usr/bin/env python3
"""Сборка коллажа с самопроверкой: фото по умолчанию, 3D — только куда без него никак.

Порядок (весь — локально и бесплатно, кроме шага 3):
  1. Собрать коллаж на ФОТОГРАФИЯХ товаров. Фотография — настоящий вид вещи, и подменять её
     рендером незачем (владелец, 2026-08-05: «для всего остального вставлять как есть»).
  2. Прогнать приёмку `collage_audit`: она числами сверяет каждый предмет с его местом в кадре.
  3. Только тем, кто приёмку НЕ прошёл, собрать 3D-модель товара (≈1,6 ₽ разово, кэш по товару)
     и подставить рендер под углом камеры. Подвесное (люстра, бра) не моделим никогда, а модель,
     не совпавшая со своей карточкой, отбраковывается автоматически.
  4. Пересобрать коллаж и прогнать приёмку заново. Что осталось — честно показывается.

Так «нужна ли модель» решает не список ролей и не человек, а сама проверка кадра.

  ~/venvs/scout/bin/python viz_build.py 21 --cams C1,C2
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
PY = sys.executable


def ensure_shell(n: int, cams: list[str]) -> bool:
    """Фотореал-оболочка пустой комнаты (ADR-0063, дефолт с А4): ~2 ₽/камера, кэш по комнате.

    Оболочка строится по НАШЕЙ карте глубины (ControlNet), поэтому геометрия совпадает с clay —
    возражение «мебель повисает» относилось к оболочкам без depth-условия (2026-08-04).
    Не собралась — честный фолбэк на clay."""
    if os.environ.get('VIZ_BASE', 'shell') == 'clay':
        return False
    missing = [c for c in cams
               if not os.path.exists(os.path.join(SCENE_DIR, f'scene{n}-{c}-shell.jpg'))]
    if missing:
        r = subprocess.run([PY, os.path.join(HERE, 'shell_make.py'), str(n),
                            '--cams', ','.join(missing)], cwd=HERE, capture_output=True, text=True)
        if r.returncode != 0:
            print(f'   оболочка не собралась ({(r.stderr or r.stdout)[-120:].strip()}) — база clay')
            return False
    return all(os.path.exists(os.path.join(SCENE_DIR, f'scene{n}-{c}-shell.jpg')) for c in cams)


def paste(n: int, cam: str, mesh_roles: list[str], shell: bool = False) -> None:
    cmd = [PY, os.path.join(HERE, 'viz_paste.py'), str(n), '--cam', cam]
    if shell:
        cmd += ['--base', 'shell']
    if mesh_roles:
        cmd += ['--mesh-roles', ','.join(mesh_roles)]
    subprocess.run(cmd, cwd=HERE, check=True, capture_output=True)


def audit(n: int, cams: list[str]) -> list[dict]:
    subprocess.run([PY, os.path.join(HERE, 'collage_audit.py'), str(n), '--cams', ','.join(cams)],
                   cwd=HERE, capture_output=True)
    return json.load(open(os.path.join(SCENE_DIR, f'scene{n}-audit.json')))


def failing(rows: list[dict]) -> list[str]:
    return sorted({r['role'] for r in rows if r['bad']})


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])

    shell = ensure_shell(n, cams)
    print(f'1. коллаж на фотографиях товаров (база: {"shell" if shell else "clay"})')
    for c in cams:
        paste(n, c, [], shell)
    rows = audit(n, cams)
    bad = failing(rows)
    total = len([r for r in rows if r['status'] not in ('рисует модель', 'частично закрыт')])
    print(f'2. приёмка: без замечаний {total - len(bad)} из {total}'
          + (f'; не прошли — {", ".join(bad)}' if bad else ''))
    if not bad:
        print('коллаж принят, 3D не понадобилось')
        return

    print('3. собираю 3D непрошедшим и сильно развёрнутым')
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))
    from mesh_make import ensure_mesh, mesh_trusted
    from viz_base import fal_key
    from viz_objects import product
    from mesh_need import on_floor
    from scene_build import load_scene
    _, placements = load_scene(n)
    by = {p.role: p for p in placements}
    # Кандидаты: провалившие приёмку И сильно развёрнутые к камере (порог владельца — 45°).
    # Список развёрнутых берём у `mesh_need.analyse` — там уже отфильтровано по тому, что реально
    # ВИДНО в кадре. Своя копия расчёта дала диван, которого во втором виде нет вообще, и зря
    # собрала для него модель (2026-08-05).
    from mesh_need import analyse
    turned = sorted({r['role'] for r in analyse(n, cams) if r['need']})
    if turned:
        print(f'   сильно развёрнуты: {", ".join(turned)}')
    key, use = fal_key(), []
    for role in sorted(set(bad) | set(turned)):
        p = by.get(role)
        if p is None:
            continue
        if not on_floor(p):
            print(f'   {role}: не напольное — модель не делаем, остаётся фото')
            continue
        try:
            path = ensure_mesh(n, role, key)
        except Exception as e:  # noqa: BLE001 — сбой генератора не должен ронять сборку
            print(f'   {role}: модель не собралась ({str(e)[:60]}) — остаётся фото')
            path = None
        if path and mesh_trusted(path, product(n, role)[1]):
            use.append(role)
            continue
        # Вторая попытка другим генератором (А6): 39% Trellis-мешей браковала самопроверка,
        # и хвост (столик/кашпо/стеллаж) оставался «рисует модель по эталону».
        fb = os.environ.get('MESH_FALLBACK', 'fal-ai/hunyuan3d/v2')
        try:
            path2 = ensure_mesh(n, role, key, model=fb) if fb else None
        except Exception as e:  # noqa: BLE001
            print(f'   {role}: фолбэк-модель не собралась ({str(e)[:60]})')
            path2 = None
        if path2 and mesh_trusted(path2, product(n, role)[1]):
            # рендер ищет меш по каноничному пути — доверенный фолбэк становится канонм
            import shutil
            from mesh_make import mesh_path
            shutil.copyfile(path2, mesh_path(product(n, role)[0]))
            print(f'   {role}: прошла модель фолбэка ({fb})')
            use.append(role)
        else:
            print(f'   {role}: обе модели не прошли самопроверку — остаётся фото')
    if not use:
        print('годных моделей нет — коллаж остаётся на фотографиях, приёмка НЕ пройдена')
        json.dump({'mesh_roles': [], 'still_bad': bad},
                  open(os.path.join(SCENE_DIR, f'scene{n}-build.json'), 'w'), ensure_ascii=False)
        sys.exit(1)   # раньше выходили нулём, и батч считал сцену чистой (А4)

    print(f'4. пересобираю с моделями: {", ".join(use)}')
    for c in cams:
        paste(n, c, use, shell)
    rows = audit(n, cams)
    bad2 = failing(rows)
    total2 = len([r for r in rows if r['status'] not in ('рисует модель', 'частично закрыт')])
    print(f'   приёмка после 3D: без замечаний {total2 - len(bad2)} из {total2}'
          + (f'; осталось — {", ".join(bad2)}' if bad2 else ''))
    json.dump({'mesh_roles': use, 'still_bad': bad2},
              open(os.path.join(SCENE_DIR, f'scene{n}-build.json'), 'w'), ensure_ascii=False)
    sys.exit(1 if bad2 else 0)


if __name__ == '__main__':
    main()
