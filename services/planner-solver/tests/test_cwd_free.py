"""Ф4 (план cwd-free-tooling): скрипты конвейера работают из ЛЮБОЙ папки.

13.08 «не та папка» четырежды ломала/искажала работу (включая тихий показ старого
отчёта как нового). Этот тест запускает ключевые скрипты из КОРНЯ репозитория.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PY = os.path.expanduser('~/venvs/scout/bin/python')
SCOUT = os.path.join(ROOT, 'tools', 'scout')


def _run_from_root(args, timeout=300):
    return subprocess.run([PY] + args, cwd=ROOT, capture_output=True,
                          text=True, timeout=timeout)


def test_rules_audit_from_root():
    r = _run_from_root([os.path.join(SCOUT, 'rules_audit.py')])
    assert r.returncode == 0, r.stderr[-500:]


def test_solver_from_root():
    r = _run_from_root([os.path.join(SCOUT, 'solver_run.py'), '1', '--v3'],
                       timeout=600)
    assert r.returncode == 0, (r.stdout[-300:] + r.stderr[-300:])


def test_run_sh_exists_and_executable():
    p = os.path.join(SCOUT, 'run.sh')
    assert os.path.exists(p) and os.access(p, os.X_OK)
