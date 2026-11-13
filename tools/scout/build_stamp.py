"""МЕТКА СБОРКИ ДАННЫХ (T-20261112-92): одно поле `build` в данных /demo (`flat215_demo.py`) и тура (`trial_bundle.py`,
`trial_reissue.py`) — «<git>.<правила>». Страница его не читает; по нему проверка «демо = туры» (`tools/ops/tour-reissue.sh`)
видит, что тур и витрина собраны одними правилами сборщика.

  git     — короткий хеш HEAD копии, из которой собрано (справка: коммиты одной памяти его двигают, сравнивать не по нему);
  правила — sha256 ВСЕХ файлов правил сборщика, с подпапками: `services/planner-solver/rules/**/*.json` (в т.ч. шаблоны комнат
            `room-templates/`), `tools/scout/rules/**/*.json` (в т.ч. профили `profiles/`) — путь от корня репо + содержимое,
            в порядке пути. До T-20261112-121 (план conveyor-guards-01 шаг 5) брался только верхний уровень: правка шаблона
            комнаты метку не двигала, и витрина «на старом шаблоне» выглядела сверенной.
Сбой git — `nogit`, правил нет — `norules`: метка не валит сборку.

ПУБЛИКАТОР СВЕРЯЕТ (шаг 5): `publish_demo.sh` зовёт `build_stamp.py --check-data <сборка>/demo-data.json` и не выкладывает сборку,
у которой нет метки или правила метки ≠ правилам копии, из которой публикуют (собрано по другим правилам — пересобрать
`flat215_demo.py`). Самопроверка — `python tools/scout/build_stamp.py --selftest`.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RULE_GLOBS = ('services/planner-solver/rules/**/*.json', 'tools/scout/rules/**/*.json')


def rule_files(root: str = ROOT) -> list[str]:
    """→ пути файлов правил от корня, по порядку (одна копия правил — один порядок на любой машине)."""
    out = set()
    for g in RULE_GLOBS:
        for p in glob.glob(os.path.join(root, g), recursive=True):
            if os.path.isfile(p):
                out.add(os.path.relpath(p, root).replace(os.sep, '/'))
    return sorted(out)


def rules_hash(root: str = ROOT) -> str:
    h, n = hashlib.sha256(), 0
    for rel in rule_files(root):
        with open(os.path.join(root, rel), 'rb') as f:
            h.update(rel.encode('utf-8') + b'\0' + f.read() + b'\0')
        n += 1
    return h.hexdigest()[:10] if n else 'norules'


def git_head(root: str = ROOT) -> str:
    try:
        r = subprocess.run(['git', '-C', root, 'rev-parse', '--short=10', 'HEAD'], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else 'nogit'
    except (OSError, subprocess.TimeoutExpired):
        return 'nogit'


def stamp(root: str = ROOT) -> str:
    """→ «<git>.<правила>»."""
    return f'{git_head(root)}.{rules_hash(root)}'


def rules_of(build: str | None) -> str:
    """Часть «правила» метки (то, что сравнивает проверка); нет метки — ''."""
    return str(build or '').rsplit('.', 1)[-1] if build and '.' in str(build) else ''


def check_data(path: str, root: str = ROOT) -> str:
    """Сборка `path` (demo-data.json) собрана по правилам копии `root`? → '' (да) или причина отказа."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return f'данные сборки не прочитаны ({type(e).__name__}: {path})'
    got = rules_of(data.get('build') if isinstance(data, dict) else None)
    if not got:
        return f'у сборки нет метки правил (`build` в {path}) — собрана до T-92 или не flat215_demo.py'
    want = rules_hash(root)
    if got != want:
        return f'сборка собрана по другим правилам: метка {got}, правила этой копии {want}'
    return ''


def _selftest() -> int:
    import tempfile
    bad = []

    def ok(c, m):
        print(('OK  ' if c else 'BAD ') + m)
        if not c:
            bad.append(m)

    with tempfile.TemporaryDirectory(prefix='build-stamp-') as d:
        def put(rel, text):
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(text)

        ok(rules_hash(d) == 'norules', 'нет правил — norules')
        put('services/planner-solver/rules/a.json', '{"a": 1}')
        put('tools/scout/rules/b.json', '{"b": 1}')
        h0 = rules_hash(d)
        put('services/planner-solver/rules/room-templates/living.json', '{"w": 1}')
        h1 = rules_hash(d)
        ok(h1 != h0, 'новый шаблон комнаты в подпапке двигает метку')
        put('services/planner-solver/rules/room-templates/living.json', '{"w": 2}')
        h2 = rules_hash(d)
        ok(h2 != h1, 'правка шаблона комнаты двигает метку')
        put('tools/scout/rules/profiles/x/deep.json', '{}')
        ok(rules_hash(d) != h2, 'файл на любой глубине подпапок — в метке')
        put('tools/scout/rules/notes.md', 'не правило')
        h3 = rules_hash(d)
        ok(rules_hash(d) == h3 and 'tools/scout/rules/notes.md' not in rule_files(d), 'не-json в метку не идёт')
        ok(rule_files(d) == sorted(rule_files(d)), 'порядок — по пути')
        put('out/good.json', json.dumps({'build': f'abc.{rules_hash(d)}'}))
        put('out/stale.json', json.dumps({'build': 'abc.0123456789'}))
        put('out/nostamp.json', json.dumps({'v': 1}))
        put('out/broken.json', '{')
        ok(check_data(os.path.join(d, 'out/good.json'), d) == '', 'сборка по этим правилам — пропуск')
        ok('другим правилам' in check_data(os.path.join(d, 'out/stale.json'), d), 'другие правила — отказ')
        ok('нет метки' in check_data(os.path.join(d, 'out/nostamp.json'), d), 'нет метки — отказ')
        ok('не прочитаны' in check_data(os.path.join(d, 'out/broken.json'), d), 'битый файл — отказ')
        ok('не прочитаны' in check_data(os.path.join(d, 'out/none.json'), d), 'нет файла — отказ')
    ok(any('/room-templates/' in p for p in rule_files()), 'в репо шаблоны комнат входят в метку')
    print('итог:', 'OK' if not bad else f'FAIL ({len(bad)})')
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ['--selftest']:
        return _selftest()
    if len(argv) == 2 and argv[0] == '--check-data':
        why = check_data(argv[1])
        if why:
            print(f'отказ: {why}. Пересоберите витрину (`tools/scout/flat215_demo.py`) из этой копии и публикуйте снова.')
            return 1
        print(f'метка правил сборки сверена: {rules_hash()}')
        return 0
    if not argv:
        print(stamp())
        return 0
    print('ключи: --check-data <demo-data.json> | --selftest | (без ключей — метка этой копии)', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
