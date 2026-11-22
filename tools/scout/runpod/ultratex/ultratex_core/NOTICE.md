# Чужой код в этой папке (T-20261119-90/2)

`render.py`, `prep.py`, `bake.py` — копия из **ComfyUI-UltraTex** (https://github.com/visualbruno/ComfyUI-UltraTex), коммит
`1f2392308e7d08374cb1c3844afe7e3ee2fadbe0` (24.10.2026), каталог `ultratex_core/`. Лицензия MIT, © 2026 Yibo Zhang (текст — `LICENSE.upstream`).
Копия нужна как есть: рендер 6 видов (moderngl), подготовка, запекание видов в UV. ComfyUI им не нужен (все импорты ComfyUI — в необязательных ветках с запасным путём).

Наши правки (всё остальное — как у источника, файлы не пересобираем руками, а сверяем с источником diff-ом):
1. `render.py::_context` — сначала EGL (в контейнере без экрана), при отказе — прежний путь.

Модель (сэмплирование) из ComfyUI-UltraTex НЕ берём: оно завязано на ComfyUI; вместо него — код авторов UltraTex
(https://github.com/yiboz2001/UltraTex, MIT, коммит a726678f3f3631fe2c5e3d1fb4597114784c7a8b, `train_flux2.inference`).
