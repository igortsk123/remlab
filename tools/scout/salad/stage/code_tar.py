#!/usr/bin/env python3
"""СРЕЗ КОДА ПО SHA ДЛЯ ЗАДАНИЯ SALAD (T-193/1/1): `code.tar` = то, что этап реально импортирует, ровно как в коммите. Драйвер кладёт его во вход КАЖДОГО задания; воркер (`worker_stage.py`) сверяет sha256,
распаковывает в `<задание>/code` и запускает команду оттуда. Образ — только среда (python, numpy, trimesh, opencv): новый код этапа едет без пересборки образа.

Состав среза (путь от корня репозитория): `tools/scout/salad/trellis/**` и `tools/scout/rules/**` целиком (там код этапов и их правила — числа в правилах, не в коде) + замыкание импортов точек входа
(`worker_stage.COMMANDS`): наши модули вне этих папок (paint_stage, recolor_lp, mesh_render …), которые этап импортирует. Правило замыкания — как в проверенном списке образа (`stage_files.txt`): в файлах
из FULL (точки входа, trellis/**, перечисленные в FULL_EXTRA) учитываются ВСЕ импорты, включая отложенные внутри функций; в остальных — только верхнего уровня (иначе в срез тянется пол-репозитория).
Срез ДЕТЕРМИНИРОВАН: `git archive` одного SHA с одним списком путей → побайтно один tar → один sha256 (его пишет воркер в ответ и в `_code.json`).
Неполный срез (импорт этапа не находится в нём) ловится ДО платной группы: `selfcheck()` распаковывает tar в чистую папку и импортирует точки входа тем же `python -I`.
Запуск (проверка среза SHA, бесплатно):  python code_tar.py <SHA|ветка> [--repo <корень>] [--out <файл.tar>]   → путь, размер, sha256, число файлов."""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, HERE)
import worker_stage as WS  # noqa: E402  (whitelist команд — единственный источник: что можно запускать из кода задания)

SLICES = ('tools/scout/salad/trellis', 'tools/scout/rules')              # берутся целиком
ASSETS = 'tools/assets'                                                   # части граней (материал/ножки): tex_fill ленивo импортирует их из tools/assets (sys.path.insert внутри функции) — T-193/3
DIRS = tuple(WS.CODE_DIRS) + (ASSETS,)                                    # где искать наши модули по имени (как sys.path этапа + tools/assets)
FULL_EXTRA = ('tools/scout/paint_stage.py', 'tools/scout/salad/recolor_lp.py',
              'tools/assets/material_parts.py', 'tools/assets/parts_refine.py', 'tools/assets/parts_vote.py')   # кроме точек входа и trellis/**: учитываем и отложенные импорты (parts_refine: `from parts_vote import` внутри функции)
DATA_FILES = ('data/flat3d/material-part-rules.json', 'data/flat3d/parts-sam-rules.json')   # правила модулей tools/assets (их RULES_PATH = ROOT/data/flat3d/…); едут в срезе вместе с модулями
MUST = ('06', '07')                                                       # точки входа, без которых срез не годится (ref_zone/render_unlit — если есть в коммите)
SHA_RE = re.compile(r'^[0-9a-f]{40}$')


class CodeTarError(Exception):
    pass


def git(repo: str, *args: str, text: bool = True):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True)
    if r.returncode != 0:
        raise CodeTarError(f'git {" ".join(args[:3])}: {r.stderr.decode("utf-8", "replace").strip()[:300]}')
    return r.stdout.decode('utf-8') if text else r.stdout


def resolve_sha(repo: str, ref: str) -> str:
    sha = git(repo, 'rev-parse', '--verify', f'{ref}^{{commit}}').strip()
    if not SHA_RE.match(sha):
        raise CodeTarError(f'не SHA коммита: {ref!r} → {sha!r}')
    return sha


def tree_files(repo: str, sha: str) -> list[str]:
    return [x for x in git(repo, 'ls-tree', '-r', '--name-only', sha, '--', 'tools/scout', ASSETS, 'data/flat3d').split('\n') if x]


def imports(src: str, deep: bool) -> set[str]:
    t = ast.parse(src)
    out: set[str] = set()

    def add(n):
        if isinstance(n, ast.Import):
            out.update(a.name.split('.')[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split('.')[0])

    for n in (ast.walk(t) if deep else t.body):
        add(n)
        if not deep and isinstance(n, (ast.Try, ast.If)):
            for m in ast.walk(n):
                add(m)
    return out


def closure(repo: str, sha: str, files: set[str]) -> tuple[list[str], list[str]]:
    """(файлы вне SLICES, которые импортирует этап; точки входа, найденные в коммите). Нет обязательной точки входа — CodeTarError."""
    entries = []
    for st, c in WS.COMMANDS.items():
        if c['script'] in files:
            entries.append(c['script'])
        elif st in MUST:
            raise CodeTarError(f'в коммите {sha[:8]} нет скрипта этапа {st}: {c["script"]}')
    full = set(entries) | set(FULL_EXTRA) | {f for f in files if f.startswith(SLICES[0] + '/') and f.endswith('.py')}
    seen: set[str] = set()
    todo = list(entries) + [f for f in FULL_EXTRA if f in files]
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        src = git(repo, 'show', f'{sha}:{f}')
        for m in imports(src, f in full):
            for d in DIRS:
                p = f'{d}/{m}.py'
                if p in files:
                    if p not in seen:
                        todo.append(p)
                    break
    outside = sorted(f for f in seen if not any(f.startswith(s + '/') for s in SLICES))
    return outside, entries


DATA_PREFIX = 'tools/assets/_data/'                                       # воркер (в образе) распаковывает только `tools/…` → правила `data/flat3d/x.json` едут как `tools/assets/_data/flat3d/x.json` (те же байты)


def packed_name(path: str) -> str:
    """`data/flat3d/x.json` → `tools/assets/_data/flat3d/x.json` (путь в срезе кода; ищет его `tex_fill.load_part_modules`, если по `ROOT/data/…` файла нет)."""
    return DATA_PREFIX + path[len('data/'):]


def add_data(tar: bytes, extra: list[tuple[str, bytes]]) -> bytes:
    """Детерминированно дописывает файлы в tar `git archive` (mtime/режим — как у первого файла среза, имена по порядку)."""
    out = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(tar)) as src, tarfile.open(fileobj=out, mode='w', format=tarfile.PAX_FORMAT) as dst:
        mtime = 0
        for m in src.getmembers():
            if m.isdir() or m.isreg():
                mtime = mtime or m.mtime
                dst.addfile(m, src.extractfile(m) if m.isreg() else None)
        for name, data in sorted(extra):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode = len(data), mtime, 0o644
            dst.addfile(ti, io.BytesIO(data))
    return out.getvalue()


def build(repo: str, ref: str) -> dict:
    """{sha, tar (bytes), tar_sha256, files (список), outside (модули вне срезов), entries}. Детерминированно: одинаковый SHA → одинаковые байты."""
    sha = resolve_sha(repo, ref)
    files = set(tree_files(repo, sha))
    outside, entries = closure(repo, sha, files)
    data: list[str] = []
    if any(f.startswith(ASSETS + '/') for f in outside):          # модули частей в срезе — значит и их правила обязаны быть (иначе на ноде «частей нет», T-193/3)
        data = list(DATA_FILES)
        absent = [d for d in data if d not in files]
        if absent:
            raise CodeTarError(f'в коммите {sha[:8]} нет правил модулей частей: {absent}')
    paths = list(SLICES) + outside
    tar = git(repo, 'archive', '--format=tar', sha, '--', *paths, text=False)
    if data:
        tar = add_data(tar, [(packed_name(d), git(repo, 'show', f'{sha}:{d}', text=False)) for d in data])
        outside = outside + [packed_name(d) for d in data]
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        names = sorted(m.name for m in tf.getmembers() if m.isreg())
    if not names:
        raise CodeTarError(f'срез пуст: {paths}')
    return {'sha': sha, 'tar': tar, 'tar_sha256': hashlib.sha256(tar).hexdigest(), 'files': names, 'outside': outside, 'entries': entries}


def selfcheck(tar: bytes, entries: list[str], python: str = sys.executable) -> str:
    """'' если точки входа импортируются из ЧИСТОЙ распаковки среза (`python -I`, как на ноде); иначе — причина. Нужны библиотеки этапов (numpy, trimesh …) в этом python."""
    with tempfile.TemporaryDirectory(prefix='code-tar-chk-') as d:
        try:
            WS.safe_untar(tar, d)
        except ValueError as exc:
            return f'срез не проходит проверку воркера: {exc}'
        mods = [os.path.splitext(os.path.basename(e))[0] for e in entries]
        code = ('import sys,os\nroot=sys.argv[1]\n'
                f'for d in reversed({tuple(DIRS)!r}): sys.path.insert(0, os.path.join(root, d))\n'
                f'import importlib\nfor m in {mods!r}: importlib.import_module(m)\n'
                "T = sys.modules.get('tex_fill')\n"
                "if T is not None and hasattr(T, 'load_part_modules'): T.load_part_modules()   # модули частей и их правила — из ЧИСТОЙ распаковки (T-193/3: раньше их в срезе не было)\n"
                'print("ok")\n')
        r = subprocess.run([python, '-I', '-c', code, d], capture_output=True, timeout=300)
        return '' if r.returncode == 0 else (r.stderr.decode('utf-8', 'replace').strip().splitlines() or ['сбой импорта'])[-1][:300]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ref')
    ap.add_argument('--repo', default=ROOT)
    ap.add_argument('--out', default='')
    ap.add_argument('--check', action='store_true', help='ещё и импортировать точки входа из чистой распаковки (нужны numpy/trimesh/…)')
    a = ap.parse_args()
    r = build(a.repo, a.ref)
    print(f'sha {r["sha"]}\ntar {len(r["tar"]) / 1024:.0f} КБ, файлов {len(r["files"])}, sha256 {r["tar_sha256"]}\nточки входа: {r["entries"]}\nвне срезов: {r["outside"]}')
    if a.out:
        open(a.out, 'wb').write(r['tar'])
    if a.check:
        why = selfcheck(r['tar'], r['entries'])
        print('импорт точек входа: ' + ('ок' if not why else 'ОТКАЗ — ' + why))
        return 0 if not why else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
