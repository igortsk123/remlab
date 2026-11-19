"""`tools/scout/pattern_metric.py` — метрика узора `pattern_grad_ncc` (T-20261119-04/1): самопроверка модуля как тест CI (нужны numpy, opencv).
    python tools/scout/tests/test_pattern_metric.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import pattern_metric  # noqa: E402

sys.exit(pattern_metric.selftest())
