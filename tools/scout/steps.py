#!/usr/bin/env python3
"""Журнал конвейера: что на каждом шаге ОТПРАВИЛИ и что ПОЛУЧИЛИ.

Владелец проверяет визуально и хочет видеть весь путь по ссылке: шаг 1 — отправили то-то в такую-то
модель, шаг 2 — получили это, шаг 3 — сделали локально. Журнал пишется рядом со сценой
(`{prefix}-steps.json`) и разворачивается в страницу `process_report.py`.
"""
import json
import os
import time

MAX_PROMPT = 4000


def log(prefix: str, title: str, *, model: str = 'локально, без нейросети',
        prompt: str = '', params: dict | None = None,
        inputs: list[str] | None = None, outputs: list[str] | None = None,
        note: str = '') -> None:
    """Добавляет шаг в журнал сцены. Пути — как есть, картинки подтянет отчёт."""
    path = f'{prefix}-steps.json'
    steps = []
    if os.path.exists(path):
        try:
            steps = json.load(open(path))
        except (OSError, ValueError):
            steps = []
    steps.append({
        'n': len(steps) + 1,
        'title': title,
        'model': model,
        'prompt': (prompt or '')[:MAX_PROMPT],
        'params': params or {},
        'inputs': [p for p in (inputs or []) if p and os.path.exists(p)],
        'outputs': [p for p in (outputs or []) if p and os.path.exists(p)],
        'note': note,
        'ts': time.strftime('%H:%M:%S'),
    })
    json.dump(steps, open(path, 'w'), ensure_ascii=False, indent=1)


def reset(prefix: str) -> None:
    """Начать журнал заново (перед новым прогоном комплекта)."""
    path = f'{prefix}-steps.json'
    if os.path.exists(path):
        os.remove(path)
