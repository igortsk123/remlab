## 1. Вывод

Наиболее вероятная причина — не dtype и не повреждённый GLB, а сочетание:

1. **≈75%: реальный пик VRAM при `low_vram=False`, проявившийся как сбой VMM-allocator PyTorch с `expandable_segments=True`.**  
   Последовательность практически сигнатурная:

   - первая нехватка/ошибка отображения памяти → `CUDA driver error: device not ready`;
   - allocator остаётся с активным, но не отображённым handle;
   - следующая аллокация в том же процессе → `!handles_.at(i)`.

   В PyTorch описан ровно такой сценарий, включая ту же пару сообщений и рекомендацию `expandable_segments:False`. После первого сбоя процесс считается необратимо повреждённым. [PyTorch issue #188008](https://github.com/pytorch/pytorch/issues/188008#issuecomment-3312931917)

2. **≈15%: асинхронный дефект kernel FlexGEMM**, который проявился только на последующей `tensor.type()`. Без `CUDA_LAUNCH_BLOCKING=1` traceback первого задания не устанавливает истинный kernel.

3. **≈7%: патологически много активных dual-grid voxels** из-за сложной/внутренней геометрии. Это усиливает VRAM-пик, но число треугольников само по себе не определяет sparse-размер.

4. **≈3%: reset/сбой арендованной GPU или драйвера Salad.**

Второй traceback почти не свидетельствует против FlexGEMM: это, скорее всего, последствие первого сбоя, потому что worker продолжает принимать задания после CUDA exception: [worker_trellis.py:980](/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119/tools/scout/salad/trellis/worker_trellis.py:980), [worker_trellis.py:1033](/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119/tools/scout/salad/trellis/worker_trellis.py:1033).

## 2. Доказательства

- Worker принудительно включает expandable allocator, затем держит **все** модели на GPU:

  - allocator: [worker_trellis.py:714](/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119/tools/scout/salad/trellis/worker_trellis.py:714);
  - `low_vram=False`: [worker_trellis.py:751](/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119/tools/scout/salad/trellis/worker_trellis.py:751);
  - `pipe.cuda()` и DINO `.cuda()`: [worker_trellis.py:756](/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119/tools/scout/salad/trellis/worker_trellis.py:756).

- Более того, upstream `inference.py` безусловно снова пишет `expandable_segments:True`: [inference.py:11](/home/pakar/ext-src/pixal3d-1911/repo/inference.py:11). Одной переменной контейнера недостаточно, если эта строка не исправлена.

- Upstream рекомендует для ≤24 ГБ поэтапную загрузку моделей: [inference.py:84](/home/pakar/ext-src/pixal3d-1911/repo/inference.py:84). `get_proj_cond_shape` сам переносит DINO на GPU и обратно при `low_vram=True`: [pixal3d_image_to_3d.py:255](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/pipelines/pixal3d_image_to_3d.py:255).

- `encode_shape_slat` строит sparse grid разрешения 1024 и передаёт весь набор активных узлов encoder’у: [trellis2_texturing.py:201](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/pipelines/trellis2_texturing.py:201), [trellis2_texturing.py:219](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/pipelines/trellis2_texturing.py:219).

- FP16 настроен правильно. Encoder имеет FP16 torso, но LayerNorm намеренно создаёт FP32 temporary через `tensor.type(dtype)`:

  - encoder dtype: [sparse_unet_vae.py:316](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/models/sc_vaes/sparse_unet_vae.py:316);
  - переход в torso: [sparse_unet_vae.py:373](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/models/sc_vaes/sparse_unet_vae.py:373);
  - штатный cast: [utils.py:68](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/modules/utils.py:68).

  Поэтому падение на `.type()` хорошо согласуется с крупной аллокацией, а не с неправильным dtype.

- FlexGEMM использует hashmap ratio 2 и masked implicit GEMM: [config.py:2](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/modules/sparse/conv/config.py:2), [conv_flex_gemm.py:37](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/modules/sparse/conv/conv_flex_gemm.py:37).

- Обучающие данные ограничивались одним миллионом active voxels: [flexi_dual_grid.py:67](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/datasets/flexi_dual_grid.py:67). Это полезный диагностический порог.

- Входной TRELLIS GLB уже должен быть декомпозирован примерно до 500k faces: [worker_trellis.py:170](/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119/tools/scout/salad/trellis/worker_trellis.py:170). ComfyUI перед texturing автоматически mesh не упрощает; simplifier — отдельный node.

## 3. Что изменить перед одним последним запуском

### Обязательно

До импорта torch:

```text
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False
CUDA_LAUNCH_BLOCKING=1
TORCH_SHOW_CPP_STACKTRACES=1
```

И дополнительно:

- заменить безусловный `expandable_segments:True` в `/opt/Pixal3D/inference.py`; лучше `setdefault`, чтобы значение контейнера `False` победило;
- после `import inference` снова проверить/установить `expandable_segments:False` до первой CUDA-аллокации;
- не включать `PYTORCH_NO_CUDA_MEMORY_CACHING`: это излишне ухудшит производительность и память.

В `PixalTexBackend.load`:

- `pipe.low_vram=True`;
- не переносить все `pipe.models` на GPU;
- не делать постоянный `image_cond_model_tex_1024.cuda()`;
- загрузить NAF на CPU, как upstream low-VRAM;
- shape encoder, DINO, flow и decoder должны поочерёдно заходить на GPU штатными ветками `low_vram`.

После вычисления камеры MoGe убрать с GPU. Между этапами порядок должен быть:

```text
delete/offload model → torch.cuda.synchronize() → gc.collect() → empty_cache()
```

Особенно добавить очистку сразу после `encode_shape_slat`: сейчас encoder уже закончил работу, но его cached workspace остаётся до более позднего этапа.

Использовать `torch.inference_mode()`, а не только `no_grad()`.

### Разрешение и mesh

- Полный texture run оставить **1024**. Именно этот tex checkpoint официально поддерживается; upstream Pixal3D допускает pipeline 1024/1536: [pixal3d_image_to_3d.py:642](/home/pakar/ext-src/pixal3d-1911/repo/pixal3d/pipelines/pixal3d_image_to_3d.py:642). Полная покраска на 512 была бы недостоверным экспериментом.
- Не упрощать автоматически уже 500k GLB: face decimation почти не меняет число surface voxels при той же поверхности.
- Перед переносом на GPU обязательно вывести:

  - faces/vertices/components/watertight;
  - `len(voxel_indices)`, диапазон и unique координат;
  - число `intersected`;
  - CUDA free/total, allocated/reserved перед encoder и после него.

- Если active voxels **>1,000,000**, использовать упрощённую копию только для shape encoding, например 200–250k faces, а запекать на исходный mesh. Обязательно записать Hausdorff proxy/original. Но это условный fallback, не основная правка.

### Как объединить в один запуск

1. Свежий процесс, один align-вариант, один job.
2. Classic allocator + low-VRAM + `CUDA_LAUNCH_BLOCKING=1`.
3. Actual resolution 1024 с указанными метриками и sync после каждого крупного этапа.
4. При любом `device not ready`, illegal access или allocator assert — записать диагностику и завершить child; никаких следующих jobs в этом CUDA-контексте.
5. Если получится обычный `torch.cuda.OutOfMemoryError`, контекст ещё пригоден: очистить модели и сделать только encode-тест того же mesh на 512. Успех 512 при OOM 1024 однозначно подтвердит масштаб active voxels/VRAM.

## 4. Риски

- `CUDA_LAUNCH_BLOCKING=1` замедлит весь run, но даст истинную строку сбоя.
- Classic allocator может сильнее фрагментироваться, зато вернёт нормальный OOM вместо разрушения allocator.
- Low-VRAM увеличит CPU RAM и время PCIe-переносов.
- Encoding proxy может ослабить мелкий рельеф в условии текстуры, хотя финальная геометрия останется исходной.
- `empty_cache()` не следует вызывать до `synchronize()` и пока остаются живые ссылки на GPU-модель.

## 5. Что изменит вывод

- Прямой `illegal memory access` внутри FlexGEMM при `CUDA_LAUNCH_BLOCKING=1` и свободной VRAM → основной виновник FlexGEMM.
- Обычный OOM при свободной памяти около нуля → чистая нехватка VRAM; allocator был лишь маскирующим дефектом.
- Active voxels существенно выше 1 млн и успех 512 → патологическая sparse-нагрузка mesh/1024.
- Сбой простого mesh на свежем процессе при тех же настройках → несовместимость сборки FlexGEMM/torch/CUDA.
- Xid/reset в host logs или исчезновение GPU из `nvidia-smi` → инфраструктура Salad.
- Успех с `expandable_segments=False` и low-VRAM практически подтвердит основной вывод.