"""МЕТКА СБОРКИ ДАННЫХ (T-20261112-92): одно поле `build` в данных /demo (`flat215_demo.py`) и тура (`trial_bundle.py`,
`trial_reissue.py`) — «<git>.<правила>». Страница его не читает; по нему проверка «демо = туры» (`tools/ops/tour-reissue.sh`)
видит, что тур и витрина собраны одними правилами сборщика.

  git     — короткий хеш HEAD копии, из которой собрано (справка: коммиты одной памяти его двигают, сравнивать не по нему);
  правила — sha256 файлов правил сборщика: `services/planner-solver/rules/*.json`, `tools/scout/rules/*.json` (по имени, содержимое).
Сбой git — `nogit`, правил нет — `norules`: метка не валит сборку.
"""
from __future__ import annotations

import glob
import hashlib
import os
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RULE_GLOBS = ('services/planner-solver/rules/*.json', 'tools/scout/rules/*.json')


def rules_hash(root: str = ROOT) -> str:
    h, n = hashlib.sha256(), 0
    for g in RULE_GLOBS:
        for p in sorted(glob.glob(os.path.join(root, g))):
            with open(p, 'rb') as f:
                h.update(os.path.relpath(p, root).encode('utf-8') + b'\0' + f.read() + b'\0')
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
