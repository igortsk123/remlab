#!/usr/bin/env python3
"""Контекст сборки образа `Dockerfile.ocr` (T-176/ocr-salad): файлы по списку `ocr_files.txt` → <ctx>/code/<имя> (words_on_sheet.py, words_rules.json) и <ctx>/requirements-ocr.txt, плюс Dockerfile.ocr.
Перед копированием СВЕРЯЕТ каждый файл кода с `frozen/SHA256SUMS` (= SHA256SUMS снимка 20261126-2234): правленый файл → отказ (код 2), образ не собираем.
Использование: stage_ocr_code.py <корень репозитория> <папка контекста>. Папка контекста — пустая или новая; ничего не удаляет."""
from __future__ import annotations

import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, 'ocr_files.txt')
SUMS = os.path.join(HERE, 'frozen', 'SHA256SUMS')
REPO_DIR = 'tools/scout/salad/ocr'


def read_list(path: str = LIST) -> list[str]:
    return [ln.strip() for ln in open(path, encoding='utf-8') if ln.strip() and not ln.lstrip().startswith('#')]


def read_sums(path: str = SUMS) -> dict[str, str]:
    out = {}
    for ln in open(path, encoding='utf-8'):
        if ln.strip():
            h, name = ln.split(None, 1)
            out[name.strip()] = h
    return out


def sha(path: str) -> str:
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def frozen_problems(root: str, files: list[str], sums: dict[str, str]) -> list[str]:
    """Файлы из frozen/ должны совпасть с SHA256SUMS снимка побайтно; в frozen/ нет файла из списка/сумм — тоже проблема."""
    bad = []
    for f in files:
        if '/frozen/' not in f:
            continue
        name = os.path.basename(f)
        p = os.path.join(root, f)
        if name not in sums:
            bad.append(f'{name}: нет в frozen/SHA256SUMS')
        elif not os.path.isfile(p):
            bad.append(f'{f}: нет файла')
        elif sha(p) != sums[name]:
            bad.append(f'{name}: sha256 {sha(p)[:12]} ≠ снимок {sums[name][:12]}')
    for name in sums:
        if not any(os.path.basename(f) == name and '/frozen/' in f for f in files):
            bad.append(f'{name}: есть в SHA256SUMS, но нет в ocr_files.txt')
    return bad


def stage(root: str, dest: str, files: list[str] | None = None) -> list[str]:
    files = files if files is not None else read_list()
    missing = [f for f in files if not os.path.isfile(os.path.join(root, f))]
    if missing:
        raise FileNotFoundError(f'нет файлов из ocr_files.txt: {missing}')
    bad = frozen_problems(root, files, read_sums(os.path.join(root, REPO_DIR, 'frozen', 'SHA256SUMS')))
    if bad:
        raise ValueError('замороженный код не совпал со снимком: ' + '; '.join(bad))
    if os.path.isdir(dest) and os.listdir(dest):
        raise FileExistsError(f'папка назначения не пуста: {dest}')
    for f in files:
        to = os.path.join(dest, 'requirements-ocr.txt') if os.path.basename(f) == 'requirements-ocr.txt' else os.path.join(dest, 'code', os.path.basename(f))
        os.makedirs(os.path.dirname(to), exist_ok=True)
        shutil.copy2(os.path.join(root, f), to)
    shutil.copy2(os.path.join(root, REPO_DIR, 'Dockerfile.ocr'), os.path.join(dest, 'Dockerfile.ocr'))
    return files


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    try:
        done = stage(sys.argv[1], sys.argv[2])
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f'ОТКАЗ: {exc}', file=sys.stderr)
        return 2
    print(f'контекст готов: {len(done)} файлов + Dockerfile.ocr → {sys.argv[2]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
