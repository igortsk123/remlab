"""Стенд паритета гостиной (room-pipeline-01 Б-3, T-20261105-41): нормализация и шум, подмешанное различие видно,
устаревший эталон — отказ, сторож процессов (запись вне стенда — отказ, жёсткая ссылка не портит замороженный файл,
запись и воспроизведение сети). Без базы и сети.
    ~/venvs/scout/bin/python tools/scout/tests/test_parity_living.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import parity_living  # noqa: E402

sys.exit(parity_living.selftest())
