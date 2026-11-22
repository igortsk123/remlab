#!/usr/bin/env python3
"""Контекст сборки образа этапов 06/07 (T-189/1): копирует файлы из `stage_files.txt` в `<ctx>/code/…` с теми же путями (без копий «на глаз»).
  python stage_stage_code.py <корень репозитория> <папка-назначения>
Отказ, если файла нет или папка назначения уже не пуста. Используется в CI (`build-stage-trial.yml`) и локально. Кэши `__pycache__` и `.pyc` не копируются."""
from __future__ import annotations

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, 'stage_files.txt')


def read_list(path: str = LIST) -> list[str]:
    return [ln.strip() for ln in open(path, encoding='utf-8') if ln.strip() and not ln.lstrip().startswith('#')]


def stage(root: str, dest: str, files: list[str]) -> list[str]:
    if os.path.isdir(dest) and os.listdir(dest):
        raise SystemExit(f'папка назначения не пуста: {dest}')
    miss = [f for f in files if not os.path.isfile(os.path.join(root, f))]
    if miss:
        raise SystemExit(f'нет файлов из списка: {miss}')
    for f in files:
        p = os.path.join(dest, f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        shutil.copyfile(os.path.join(root, f), p)
    return files


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    done = stage(sys.argv[1], sys.argv[2], read_list())
    print(f'скопировано файлов: {len(done)} → {sys.argv[2]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
