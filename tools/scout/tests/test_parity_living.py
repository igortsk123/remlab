"""Стенд паритета комнат (room-pipeline-01 Б-3, T-20261105-41 гостиная, T-54 спальня/прихожая): нормализация и шум, подмешанное различие видно,
шаги комнат и сборщик по профилю, ключи .env* не попадают в стенд,
устаревший эталон — отказ, сторож процессов (запись вне стенда — отказ, жёсткая ссылка не портит замороженный файл,
запись и воспроизведение сети). Без базы и сети.
    ~/venvs/scout/bin/python tools/scout/tests/test_parity_living.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import parity_living  # noqa: E402

sys.exit(parity_living.selftest())
