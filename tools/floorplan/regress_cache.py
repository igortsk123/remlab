#!/usr/bin/env python3
"""Общий кэш разбора листов для `regress.py run` (T-20261111-18): одна и та же база (main) у 2–3 помощников разбиралась
каждым заново — по ~1–2 мин процессора на лист. Здесь результат листа берётся готовым, если совпал отпечаток ВСЕХ входов разбора.

Ключ (`case_key`) — sha256 от:
  • кода разбора (`code_files`): все `tools/floorplan/*.py` и `gold/*.json` + замыкание импортов от `pipeline.py` по
    `tools/{floorplan,ops,scout}` (статически, AST, ленивые импорты внутри функций тоже; имя, найденное в нескольких папках, —
    все совпадения): сейчас это `ops/heavy_slot.py`, `scout/llm_gateway.py`, `scout/env_keys.py`, `scout/remlab_tmp.py`,
    `scout/openai_budget.py` и т. д.; отсутствующий файл — тоже часть ключа;
  • окружения прогона (`env_part`): все `--env`, значения переменных, чьи имена встречаются строками в коде разбора, переменные
    питона/потоков (PYTHONPATH, PYTHONHASHSEED, OMP_*, OPENCV_* …); значения — только в хеше, на диск не пишутся;
  • интерпретатора (`interp_part`): версия и путь питона, sys.path, ВСЕ установленные пакеты с версиями, `pdftoppm -v`;
  • листа: команда прогона (пути кода и папки заменены метками, лист и объявление — хешами содержимого), расширение листа;
  • ответов VLM (`dir_sha` — все файлы папки рекурсивно): папка VLM строки `--cases` известна сразу; у загрузки (`pipeline.py
    job`) она = `<vlm-cache>/<sha256 sheet.png>[:32]` и узнаётся после первого разбора → двухступенчато (как manifest у ccache):
    `idx/<k1>.json` хранит, какие папки VLM читались, полный ключ k2 = k1 + хеши этих папок СЕЙЧАС → `obj/<k2>/`.

Кэш не берётся (и не пишется) при `--no-cache` и когда прогон пишет побочные файлы или читает лишние входы: `--env` с
FP_REDRAW / FP_STATE / FP_DUMP / FP_DEBUG_ENV / FP_CACHE или со значением-путём. В кэш идут только rc 0 (result.json) и rc 3
(error.json задания, напр. source_gone); сбой кода (rc 1), таймаут, убийство памятью — нет.

Запись атомарная: папка собирается в `tmp/` и переименовывается в `obj/<k2>` одним `rename` (второй помощник с тем же ключом
проиграл гонку — его копия убирается, файл победителя тот же по построению); `idx` — temp + `os.replace`. Хит копирует папку листа
целиком (result.json, gold.json, bench/ с картинками) и журнал прогона; `<лист>.log` начинается строкой «regress-cache: из кэша».
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from functools import lru_cache
from pathlib import Path

CACHE_DIR = Path(os.path.expanduser('~/remlab-logs/regress-cache'))
FORMAT = 'regress-cache/1'          # меняется при смене устройства ключа — старые записи просто не находятся
SEARCH = ('floorplan', 'ops', 'scout')
ENTRY = 'pipeline.py'               # вход разбора: `pipeline.py job` и `import pipeline` (regress.RUN_DIRECT)
NO_CACHE_ENV = ('FP_REDRAW', 'FP_STATE', 'FP_DUMP', 'FP_DEBUG_ENV', 'FP_CACHE')
RUNTIME_ENV = ('PYTHONPATH', 'PYTHONHASHSEED', 'PYTHONSAFEPATH', 'PYTHONNOUSERSITE', 'PYTHONUSERBASE', 'PYTHONHOME',
               'PYTHONOPTIMIZE', 'PYTHONWARNINGS', 'PYTHONUTF8', 'PYTHONIOENCODING', 'LC_ALL', 'LC_NUMERIC', 'LANG')
RUNTIME_PREFIX = ('FP_', 'OMP_', 'OPENBLAS_', 'MKL_', 'NUMEXPR_', 'OPENCV_', 'GOTO_', 'VECLIB_', 'BLIS_')
CACHED_RC = (0, 3)
_ENV_NAME = re.compile(r'^[A-Z][A-Z0-9_]+$')


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_sha(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def dir_sha(d) -> str:
    """Все файлы папки рекурсивно (путь + содержимое); нет папки — 'absent'. Ответы VLM: смена/появление любого файла — новый ключ."""
    d = Path(d)
    if not d.is_dir():
        return 'absent'
    h = hashlib.sha256()
    for p in sorted(d.rglob('*')):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode() + b'\0' + file_sha(p).encode() + b'\0')
    return h.hexdigest()


# ───────────────────────── код разбора ─────────────────────────

def _imports(path: Path) -> set[str]:
    """Имена модулей верхнего уровня из `import x` / `from x import …` по всему файлу (в т. ч. внутри функций)."""
    try:
        tree = ast.parse(path.read_bytes(), str(path))
    except SyntaxError:
        return set()            # файл всё равно в ключе по содержимому; разбор такого кода упадёт и в кэш не попадёт
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(n.module.split('.')[0])
    return out


def _resolve(tools: Path, name: str) -> list[Path]:
    out = []
    for d in SEARCH:
        f = tools / d / f'{name}.py'
        if f.is_file():
            out.append(f)
        pkg = tools / d / name
        if (pkg / '__init__.py').is_file():
            out += sorted(pkg.rglob('*.py'))
    return out


def code_files(code) -> dict[str, Path | None]:
    """{путь от корня кода: файл | None (импорт был найден в эталоне, но файла нет — тоже часть ключа)}.
    Все `tools/floorplan/*.py` + `gold/*.json`, плюс замыкание импортов от `pipeline.py` по tools/{floorplan,ops,scout}.
    Чужие модули (stdlib, пакеты) — в `interp_part` версиями."""
    code = Path(code)
    tools = code / 'tools'
    fp = tools / 'floorplan'
    files = {p for p in fp.glob('*.py')} | {p for p in (fp / 'gold').glob('*.json')}
    seen, todo, missing = set(), [fp / ENTRY], set()
    while todo:
        f = todo.pop()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        files.add(f)
        for name in _imports(f):
            todo += _resolve(tools, name)
    for name in ('llm_gateway', 'env_keys'):        # известные внешние зависимости: нет файла (старый снимок) — видно в ключе
        if not _resolve(tools, name):
            missing.add(f'tools/scout/{name}.py')
    out = {str(p.relative_to(code)): p for p in files}
    out.update({m: None for m in missing if m not in out})
    return dict(sorted(out.items()))


def code_part(code) -> tuple[str, list[str]]:
    """→ (хеш кода, имена переменных окружения, встречающиеся строками в этом коде)."""
    h = hashlib.sha256()
    names = set()
    for rel, p in code_files(code).items():
        if p is None:
            h.update(rel.encode() + b'\0MISSING\0')
            continue
        b = p.read_bytes()
        h.update(rel.encode() + b'\0' + _sha(b).encode() + b'\0')
        if p.suffix == '.py':
            try:
                for n in ast.walk(ast.parse(b)):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and _ENV_NAME.match(n.value):
                        names.add(n.value)
            except SyntaxError:
                pass
    return h.hexdigest(), sorted(names)


def env_part(env: dict, names, extra: dict) -> str:
    """Окружение прогона → хеш: все `--env`, переменные с именами из кода, переменные питона и потоков. Значения — только в хеше."""
    keys = set(names) | set(RUNTIME_ENV) | {k for k in env if k.startswith(RUNTIME_PREFIX)}
    view = {k: env.get(k) for k in sorted(keys)}
    return _sha(json.dumps({'env': view, 'extra': dict(sorted((extra or {}).items()))}, sort_keys=True).encode())


INTERP = r'''
import importlib.metadata as m, json, os, platform, sys
d = sorted({(x.metadata['Name'] or '?').lower() + '==' + (x.version or '?') for x in m.distributions()})
print(json.dumps({'v': sys.version, 'exe': os.path.realpath(sys.executable), 'prefix': sys.prefix, 'path': sys.path,
                  'plat': platform.platform(), 'mach': platform.machine(), 'dists': d}))
'''


@lru_cache(maxsize=8)
def _interp(py: str, env_items: tuple) -> str:
    env = dict(env_items)
    r = subprocess.run([py, '-c', INTERP], capture_output=True, text=True, env=env, cwd='/', timeout=120, check=True)
    pdf = shutil.which('pdftoppm', path=env.get('PATH'))
    try:
        pv = subprocess.run([pdf, '-v'], capture_output=True, text=True, timeout=30).stderr.strip() if pdf else 'нет'
    except (OSError, subprocess.SubprocessError):
        pv = 'сбой'
    return _sha((r.stdout + '\0' + str(pdf and os.path.realpath(pdf)) + '\0' + pv).encode())


def interp_part(py: str, env: dict) -> str:
    """Питон прогона: версия, путь, sys.path, все пакеты с версиями (numpy, opencv, shapely, scipy, Pillow …) + pdftoppm."""
    return _interp(str(py), tuple(sorted(env.items())))


def bypass_reason(extra: dict | None) -> str | None:
    """Почему этот прогон кэшем пользоваться не может (побочные файлы или лишние входы), иначе None."""
    for k, v in (extra or {}).items():
        if k in NO_CACHE_ENV:
            return f'--env {k}'
        if '/' in str(v) or str(v).startswith('~'):
            return f'--env {k}=<путь>'
    return None


class Fingerprint:
    """Общая для всех листов прогона часть ключа (код + окружение + интерпретатор)."""

    def __init__(self, code, py: str, env: dict, extra: dict | None):
        self.code = Path(code).resolve()
        c, names = code_part(self.code)
        self.parts = {'format': FORMAT, 'code': c, 'env': env_part(env, names, extra or {}), 'interp': interp_part(py, env)}
        self.digest = _sha(json.dumps(self.parts, sort_keys=True).encode())


def case_key(fpr: Fingerprint, cmd: list[str], case: dict, wd: Path) -> str:
    """Первая ступень ключа листа: общая часть + команда (код и папка листа — метками, лист и объявление — хешами)."""
    code, wd = str(fpr.code), str(wd)
    subst = {}
    for k in ('image', 'listing'):
        if case.get(k):
            subst[str(case[k])] = f'<{k}:{file_sha(case[k])}>'
    # папка VLM строки `--cases` остаётся в ключе путём: idx/<k1> хранит, какую папку хешировать, — у двух папок с разным
    # содержимым при одном листе k1 обязан различаться (иначе второй лист сверили бы по чужой папке)
    norm = []
    for a in cmd:
        a = subst.get(a, a)
        norm.append(a.replace(wd, '<WD>').replace(code, '<CODE>'))
    norm[0] = '<PY>'                                         # питон — в interp_part
    return _sha(json.dumps({'fp': fpr.digest, 'cmd': norm, 'suffix': Path(case['image']).suffix.lower()}).encode())


# ───────────────────────── хранилище ─────────────────────────

class Store:
    def __init__(self, root=CACHE_DIR):
        self.root = Path(root)

    def _idx(self, k1: str) -> Path:
        return self.root / 'idx' / k1[:2] / f'{k1}.json'

    def _obj(self, k2: str) -> Path:
        return self.root / 'obj' / k2[:2] / k2

    @staticmethod
    def full_key(k1: str, deps: list[str]) -> str:
        return _sha(json.dumps({'k1': k1, 'deps': {d: dir_sha(d) for d in sorted(deps)}}, sort_keys=True).encode())

    def get(self, k1: str) -> tuple[str, Path] | None:
        """→ (k2, папка записи) или None. Запись видна только целиком (rename)."""
        f = self._idx(k1)
        try:
            deps = json.loads(f.read_text())['deps']
        except (OSError, ValueError, KeyError):
            return None
        k2 = self.full_key(k1, deps)
        o = self._obj(k2)
        return (k2, o) if (o / 'entry.json').is_file() else None

    def restore(self, o: Path, wd: Path, log: Path, k2: str) -> dict:
        e = json.loads((o / 'entry.json').read_text())
        if (o / 'wd').is_dir():
            shutil.copytree(o / 'wd', wd, symlinks=True)
        else:
            wd.mkdir(parents=True)
        src = o / 'run.log'
        head = (f"regress-cache: из кэша {k2[:16]} (разобрано {e.get('created')}, код {e.get('rev')}, "
                f"{e.get('sec')} с)\n").encode()
        log.write_bytes(head + (src.read_bytes() if src.is_file() else b''))
        return e

    def put(self, k1: str, deps: list[str], wd: Path, log: Path, meta: dict) -> str | None:
        """Папка листа + журнал → obj/<k2>; idx/<k1> — какие папки VLM читались. Гонку проигравший убирает только свою копию."""
        k2 = self.full_key(k1, deps)
        o = self._obj(k2)
        if (o / 'entry.json').is_file():
            self._write_idx(k1, deps)
            return k2
        tmp = self.root / 'tmp' / f'{k2[:16]}.{os.getpid()}.{uuid.uuid4().hex[:8]}'
        try:
            tmp.mkdir(parents=True)
            if wd.is_dir():
                shutil.copytree(wd, tmp / 'wd', symlinks=True)
            if log.is_file():
                shutil.copyfile(log, tmp / 'run.log')
            (tmp / 'entry.json').write_text(json.dumps(dict(meta, k1=k1, k2=k2, deps=deps,
                                                            created=time.strftime('%Y-%m-%d %H:%M:%S')),
                                                       ensure_ascii=False, indent=1))
            o.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(tmp, o)
            except OSError:
                if not (o / 'entry.json').is_file():
                    raise
                shutil.rmtree(tmp, ignore_errors=True)        # своя временная копия: другой помощник записал тот же ключ раньше
        except OSError as e:
            print(f'regress-cache: не записал {k2[:16]}: {type(e).__name__}: {e}', file=sys.stderr)
            shutil.rmtree(tmp, ignore_errors=True)
            return None
        self._write_idx(k1, deps)
        return k2

    def _write_idx(self, k1: str, deps: list[str]) -> None:
        f = self._idx(k1)
        f.parent.mkdir(parents=True, exist_ok=True)
        t = f.with_name(f'.{f.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp')
        t.write_text(json.dumps({'deps': sorted(deps)}))
        os.replace(t, f)


def vlm_deps(case: dict, wd: Path, vlm_root: Path) -> list[str]:
    """Папки ответов VLM, которые читал разбор листа: `--cases` с папкой — она; загрузка — `<vlm_root>/<sha256 sheet.png>[:32]`
    (как `pipeline.run`). Нет sheet.png (лист не растрировался) — VLM не читался."""
    if case.get('vlm_dir'):
        return [str(Path(case['vlm_dir']).resolve())]
    sheet = wd / 'sheet.png'
    return [str(Path(vlm_root).resolve() / file_sha(sheet)[:32])] if sheet.is_file() else []


def main(argv=None) -> int:
    """`regress_cache.py files <код>` — какие файлы входят в отпечаток кода (проверка глазами)."""
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) == 2 and a[0] == 'files':
        for rel, p in code_files(a[1]).items():
            print(('НЕТ  ' if p is None else '     ') + rel)
        print('код', code_part(a[1])[0][:16], '· имён переменных', len(code_part(a[1])[1]))
        return 0
    print(main.__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
