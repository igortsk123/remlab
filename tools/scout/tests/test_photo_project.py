"""`tools/scout/salad/photo_project.py` — проекция фото на UV (T-20261119-04/1): самопроверка модуля как тест CI (синтетический ящик, без внешних файлов и сети;
нужны numpy, opencv, scipy, trimesh, pygltflib). Временные файлы — в `tempfile`, убираются ОС; артефактов в репо нет.
    python tools/scout/tests/test_photo_project.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))
sys.path.insert(0, os.path.join(HERE, '..'))
import photo_project  # noqa: E402

sys.exit(photo_project.selftest())
