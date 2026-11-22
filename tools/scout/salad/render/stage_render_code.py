#!/usr/bin/env python3
"""Контекст сборки образа кадров форм (T-184/1, очередь 3): копирует файлы из `render_files.txt` в `<ctx>/code/…` с теми же путями (без копий «на глаз»).
  python stage_render_code.py <корень репозитория> <папка-назначения>
Отказ, если файла нет или папка назначения уже не пуста. Используется в CI (`build-render-trial.yml`) и локально; общую логику копирования берём у камеры (`stage_pose_code.stage`)."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'pose'))
import stage_pose_code as SPC  # noqa: E402

LIST = os.path.join(HERE, 'render_files.txt')


def read_list(path: str = LIST) -> list[str]:
    return [ln.strip() for ln in open(path, encoding='utf-8') if ln.strip() and not ln.lstrip().startswith('#')]


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    done = SPC.stage(sys.argv[1], sys.argv[2], read_list())
    print(f'скопировано файлов: {len(done)} → {sys.argv[2]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
