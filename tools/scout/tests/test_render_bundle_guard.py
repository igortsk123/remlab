"""Сторож пакета задания GPU (T-20261118-03/4, пробел найден директором 18.11): `render_cycles.py` крутится на ЧУЖОЙ машине только из пакета
`render_exec._bundle_files`. Всё, что программа рендера импортирует из репозитория (и что импортируют они), и все `data/**/*.json`, которые эти
модули открывают по пути, обязаны лежать в пакете — иначе Blender на машине упадёт на import / на чтении правил, а локально всё зелёное.
Тест читает код статически (ast), поэтому новый import или новый файл данных без строки в `_bundle_files` сразу делает его красным.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_render_bundle_guard.py -q"""
import ast
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
PROBE = os.path.join(SCOUT, 'cycles_probe')
REPO = os.path.abspath(os.path.join(SCOUT, '..', '..'))
sys.path.insert(0, SCOUT)
sys.path.append(os.path.join(HERE, '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_render_bundle_guard')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
import render_exec as RE  # noqa: E402

ENTRY = os.path.join(PROBE, 'render_cycles.py')
SEARCH = (PROBE, SCOUT)     # куда `render_cycles.py` добавляет sys.path (своя папка и `tools/scout`)


def bundle_keys() -> set:
    """Пути в архиве, которые берёт заказ (пустой каталог задания: сцена и дамп приходят отдельно)."""
    stub = types.SimpleNamespace(public='/нет-такой-папки')
    with tempfile.TemporaryDirectory() as job:
        return set(RE.SaladGpuExecutor._bundle_files(stub, job))


def _local_file(mod: str):
    for d in SEARCH:
        p = os.path.join(d, mod + '.py')
        if os.path.isfile(p):
            return p
    return None


def _imports(path: str):
    tree = ast.parse(open(path, encoding='utf-8').read())
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name.split('.')[0]
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            yield n.module.split('.')[0]


def closure(entry: str) -> list:
    """Локальные модули, нужные программе рендера: сама программа и всё, что она (и они) импортируют из `cycles_probe/` и `tools/scout/`."""
    seen, stack = [], [entry]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.append(p)
        for m in _imports(p):
            lp = _local_file(m)
            if lp:
                stack.append(lp)
    return seen


def data_files(path: str) -> set:
    """Файлы данных, которые модуль открывает по пути из репозитория: `os.path.join(…, 'data', …, '<имя>.json')` (хвост из строк-констант)."""
    out = set()
    for n in ast.walk(ast.parse(open(path, encoding='utf-8').read())):
        if isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == 'join':
            parts = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if 'data' in parts and parts[-1].endswith('.json'):
                out.add('/'.join(parts[parts.index('data'):]))
    return out


def rel(p: str) -> str:
    return os.path.relpath(p, REPO).replace(os.sep, '/')


def test_guard_sees_the_known_dependencies():
    """Сам сторож не пустой: видит сторож кадров, правило картин и три файла данных (иначе «красного» не будет никогда)."""
    mods = {rel(p) for p in closure(ENTRY)}
    assert {'tools/scout/cycles_probe/render_cycles.py', 'tools/scout/cycles_probe/frame_qa.py', 'tools/scout/wall_art.py'} <= mods, mods
    data = set().union(*[data_files(p) for p in closure(ENTRY)])
    assert {'data/flat3d/frame-qa-rules.json', 'data/flat3d/textile.json', 'data/flat3d/wall-art.json'} <= data, data


def test_every_local_import_of_render_cycles_is_in_the_bundle():
    keys = bundle_keys()
    missing = [rel(p) for p in closure(ENTRY) if rel(p) not in keys]
    assert not missing, f'программа рендера импортирует, а пакет задания GPU не везёт: {missing} — добавь в render_exec._bundle_files'


def test_every_data_json_they_open_is_in_the_bundle():
    keys = bundle_keys()
    need = set().union(*[data_files(p) for p in closure(ENTRY)])
    missing = sorted(d for d in need if d not in keys)
    assert not missing, f'эти модули открывают файлы данных, которых нет в пакете: {missing} — добавь в render_exec._bundle_files'
    for d in need:
        assert os.path.isfile(os.path.join(REPO, d)), d


def dump_reads(path: str) -> set:
    """Имена файлов, которые модуль читает из папки дампа: `os.path.join(<…dump_dir>, '<имя>')`."""
    out = set()
    for n in ast.walk(ast.parse(open(path, encoding='utf-8').read())):
        if isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == 'join' and len(n.args) == 2:
            a0, a1 = n.args
            nm = a0.id if isinstance(a0, ast.Name) else a0.attr if isinstance(a0, ast.Attribute) else ''
            if nm.endswith('dump_dir') and isinstance(a1, ast.Constant) and isinstance(a1.value, str):
                out.add(a1.value)
    return out


def test_dump_files_the_guard_reads_are_in_the_bundle():
    """Сторож кадров на машине читает файлы дампа (`scene_info.json`, `demo_nodes*`, `dump_keys.json`) из пакета: нет файла — предпроверка слепа
    («нет scene_info.json»), и проверять кадр на машине нечем. Пропуск нашёл тест 18.11 (scene_info.json не ехал)."""
    keys = bundle_keys()
    reads = dump_reads(os.path.join(PROBE, 'frame_qa.py'))
    assert {'scene_info.json', 'demo_nodes.glb', 'demo_nodes_uuids.json', 'dump_keys.json'} <= reads, reads
    missing = sorted(n for n in reads if 'dump/' + n not in keys)
    assert not missing, f'сторож читает из дампа, а пакет не везёт: {missing} — добавь в render_exec._bundle_files'


def test_bundle_sources_exist_on_disk():
    stub = types.SimpleNamespace(public='/нет-такой-папки')
    with tempfile.TemporaryDirectory() as job:
        files = RE.SaladGpuExecutor._bundle_files(stub, job)
    gone = [k for k, v in files.items() if k.startswith(('tools/', 'data/')) and not os.path.isfile(v)]
    assert not gone, gone
