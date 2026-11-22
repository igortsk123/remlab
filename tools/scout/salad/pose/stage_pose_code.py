#!/usr/bin/env python3
"""Собрать папку с кодом цепочки pose_fit по списку `pose_files.txt` (пути от корня репозитория сохраняются: `<dest>/tools/scout/...`).
Использование: stage_pose_code.py <корень репозитория> <папка назначения>. Это и контекст сборки образа `worker-pose` (CI), и «код как в образе» для локальной сверки.
Нет файла из списка — отказ (код 2): образ без части цепочки не собираем. Ничего не удаляет; папка назначения должна быть пустой или новой."""
from __future__ import annotations

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, 'pose_files.txt')


def read_list(path: str = LIST) -> list[str]:
    return [ln.strip() for ln in open(path, encoding='utf-8') if ln.strip() and not ln.lstrip().startswith('#')]


def stage(root: str, dest: str, files: list[str] | None = None) -> list[str]:
    """Копирует файлы; возвращает список скопированных. Не нашёл — FileNotFoundError со всем списком пропавших."""
    files = files if files is not None else read_list()
    missing = [f for f in files if not os.path.isfile(os.path.join(root, f))]
    if missing:
        raise FileNotFoundError(f'нет файлов из pose_files.txt: {missing}')
    if os.path.isdir(dest) and os.listdir(dest):
        raise FileExistsError(f'папка назначения не пуста: {dest}')
    for f in files:
        to = os.path.join(dest, f)
        os.makedirs(os.path.dirname(to), exist_ok=True)
        shutil.copy2(os.path.join(root, f), to)
    return files


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    try:
        done = stage(sys.argv[1], sys.argv[2])
    except (FileNotFoundError, FileExistsError) as exc:
        print('ОТКАЗ:', exc)
        return 2
    print(f'скопировано файлов: {len(done)} → {sys.argv[2]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
