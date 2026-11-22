# StableGen на нашей готовой форме — проба (T-20261119-90/5, этап 1)

Идея: форму и развёртку берём наши (HD-форма t94, UV не меняется), текстуру рисует **StableGen** (аддон Blender, GPL-3, v0.5.0) через ComfyUI с Qwen-Image-Edit по HD-вырезке t93 как «внешнему стилю».
Blender с аддоном работает у нас без окна, ComfyUI — на Salad (4090). **ПРОБА, не боевой шаг**: ничего из этого не подключено к конвейеру мешей.

## Что здесь
| Файл | Роль |
|---|---|
| `sg_drive.py` | драйвер ВНУТРИ Blender: импорт GLB (UV-слой → `BakeUV`) → пресет → камеры (`add_cameras`, `EXEC_DEFAULT`) → генерация → запекание в нашу UV (`bake_textures`, `EXEC_DEFAULT`, `try_unwrap=none`) → экспорт GLB |
| `sg_run.sh` | запуск Blender 4.5.9 под xvfb (`SG_HOME`, `SG_THREADS`, по умолчанию 4 потока) |
| `fake_comfy.py` | поддельный ComfyUI на том же протоколе — бесплатная проверка без видеокарты |
| `worker_sg.py` | воркер в образе: порт сразу, докачка весов, ComfyUI, пропуск HTTP+WebSocket к нему |
| `sg_relay.py` | локальный мост http/ws → https/wss + ключ Salad (аддон другого не умеет) |
| `sg_salad.py` | драйвер Salad: группа, проверки, потолок денег, мост, прогоны по очереди, стоп с подтверждением |
| `Dockerfile.sg-comfy` | тонкий слой поверх образа р.4: узел ComfyUI-GGUF (коммит `6ea2651e…`) |
| `tests_sg.py` | тесты чистых частей |

## Окружение на pakardev (`SG_HOME=~/remlab-logs/t90-1119/sg`)
- `addon/` + `stablegen.zip` — аддон из `~/ext-src/stablegen-1911/repo/stablegen`; ставится в изолированную папку `home/` (`BLENDER_USER_RESOURCES=$SG_HOME/home`), расширение `bl_ext.user_default.stablegen`.
- `deps/` — колёса для Python 3.11 Blender'а (`pip install --target deps --python-version 3.11 --only-binary=:all: --platform manylinux2014_x86_64 pillow opencv-python-headless trimesh imageio websocket-client websockets fast-simplification`); в Blender передаётся `PYTHONPATH` + `--python-use-system-env`.
- `fake-deps/` — aiohttp/numpy/pillow для поддельного сервера, воркера и моста под системный `python3`.

## Что проверено бесплатно (pakardev, 19.11)
- Полный проход комода (HD, 486 тыс. граней): 8 камер, 8 видов, запекание 2048² в нашу UV (CPU Cycles ≈ 156 с), экспорт GLB ≈ 70 с — на поддельном сервере.
- Цепочка Blender → мост → воркер → поддельный ComfyUI (HTTP, загрузки, WebSocket, бинарные кадры).
- Все 15 типов узлов из заданий пресета «Qwen Precise» есть в ComfyUI v0.46.0; нет только `UnetLoaderGGUF` (его добавляет образ).
- Все 8 адресов весов на Hugging Face публичны (HEAD 200).

## Грабли (чтобы не наступать снова)
- `add_cameras`/`bake_textures` с `INVOKE_DEFAULT` только открывают окно настроек — из скрипта вызывать `EXEC_DEFAULT`; `add_cameras` — ещё `review_placement=False` и контекст окна с 3D-видом (`temp_override`).
- В фоне (`-b`) модальные операторы не тикают — отсюда Blender в xvfb и драйвер на таймере.
- Нужны `preferences.system.use_online_access = True` и `output_dir` в настройках аддона, иначе `poll` оператора отказывает.
- Относительный `PYTHONPATH` ломается у дочернего процесса с другим `cwd` — только абсолютный.
