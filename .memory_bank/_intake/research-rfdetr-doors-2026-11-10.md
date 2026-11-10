---
source: external:web (исследование субагента 10.11)
updated: 2026-11-10
---

# Своя модель дверей/окон на RF-DETR Medium — исследование (10.11.2026)

Контекст: проба T-35 (`~/remlab-logs/t35/1522/eval-2/table.md` на pakardev, эталон `tools/floorplan/trials/gold-doors/` на ветке
`worktree-doors-eval`, коммит `297e2cd2`, 7 листов): `OsamaMo/2dplan2strct` — F1 дверей 0,93 против нашего 0,79; на CPU
0,3–0,7 с на лист, пик памяти ~1,4 ГБ. Веса — только некоммерческие. Ниже — что известно о ней и как сделать свою.
Всё ниже — факты с источниками; оценки помечены «оценка».

## 1. Как именно обучали `OsamaMo/2dplan2strct` (главное)

Источники: карточка https://huggingface.co/OsamaMo/2dplan2strct (README, 7 версий в истории коммитов), `config.json`,
`inference.py`, `USAGE_TERMS.md`, API `https://huggingface.co/api/models/OsamaMo/2dplan2strct`, сам файл весов (служебная часть
pickle разобрана без исполнения кода).

| Что | Факт | Где сказано |
|---|---|---|
| Автор | Osama Mohamed (HF `OsamaMo`); кроме этой модели у него только Text-to-SQL на Qwen и один статический Space; датасетов на HF нет, статей нет; GitHub `OsamaMo` пустой (0 репо) | `api/users/OsamaMo/overview`, `api/models?author=OsamaMo`, `api.github.com/users/OsamaMo` |
| Дата | опубликована 23.09.2026, 7 коммитов за 1,5 часа; первое имя репо — `floorplan-architecture-rfdetr-medium` | история коммитов HF |
| Архитектура | RF-DETR Medium (класс `RFDETRMedium`), чекпойнт PyTorch, `rfdetr>=1.10,<1.11` | README «Model details», `config.json`, `requirements.txt` |
| Разрешение | 576 (родное для Medium) | `config.json`: `"resolution": 576` |
| Классы | 4: `wall`, `room`, `door`, `window`; стены и комнаты — рамками, не масками | `config.json`, README |
| Внутри весов | только `model` (510 тензоров) и `args` = `class_names`, `num_queries: 300`, `group_detr: 13` — параметры обучения (путь к данным, эпохи, батч, lr, аугментации) автор вычистил | разбор `checkpoint_best_ema.pth/data.pkl` (копия на pakardev `~/models/fp-trial/2dplan2strct/`) |
| Видеокарта и время | «NVIDIA T4 GPU with 16 GB»; «reported training duration was 16 hours» (строка добавлена последним коммитом) | README «Training setup» |
| Эпохи | опубликован «best EMA checkpoint after epoch 13»; сколько эпох всего — не сказано | README «Evaluation» |
| Батч, lr, аугментации | не указаны нигде (ни в карточке, ни в весах) | — |
| Датасет | **не назван** ни в одной версии карточки; известен только размер проверки: **2 964 отложенных листа** | README «Evaluation» |
| Метрики (на своей проверке, не на независимом тесте) | mAP@0.5 94,52 %; mAP@0.5:0.95 82,58 %; F1 91,86 %; P 93,53 %; R 90,26 % (по всем 4 классам вместе) | README |
| Приёмы при выводе | никаких: картинка целиком → `model.predict(image, threshold=0.35)`; резки листа на куски нет, NMS/постобработки своей нет; порог по умолчанию 0,35 (в первой версии тоже 0,35) | `inference.py` |
| CPU | Xeon Platinum 8488C, 2 потока, fp32, лист 1206×1013, 123 объекта: медиана 457,63 мс, p95 654,66 мс | README «Inference speed» |
| Лицензия | `license: other`, `non-commercial-research-only`; текст: «available for non-commercial research and evaluation only. No commercial-use rights are granted. Redistribution must preserve these terms. Contact the publisher for any other use.» Про выходы модели ничего не сказано | `USAGE_TERMS.md` |

Выводы по разделу:
- Рецепт у автора — **штатное дообучение `rfdetr` без хитростей**: Medium, 576, 4 класса, имя файла `checkpoint_best_ema.pth` —
  стандартный выход `model.train()` (раздел 2). Сила модели — в данных, не в приёмах.
- Масштаб данных (оценка): проверка 2 964 листа; при обычной доле проверки 10–20 % всего ~15–30 тыс. размеченных листов.
  16 ч на T4 при лучшей эпохе 13 → порядка 1 ч на эпоху, т. е. ~4–8 картинок/с на T4 при 576 (оценка, не замер).
- Откуда данные — неизвестно. Ни один из проверенных открытых наборов не даёт ровно 2 964 листа в проверке (CubiCasa5k — 400,
  ResPlan — 1 632, см. раздел 3). Пример в карточке (`images/before_rec_2.jpeg`) — американский рекламный план с подписью
  «Plans are illustrative only» — это пример вывода, о составе обучения он не говорит. Если в данных был CubiCasa5k (CC BY-NC-SA) или
  листы с сайтов недвижимости — это объясняет некоммерческую лицензию; это догадка, не факт.
- Хорошо работает на 576 и плохо на 1152 (T-35: F1 на A 0,97 → 0,83) — модель училась на сжатых до 576 листах.

## 2. RF-DETR: лицензия, дообучение, вывод

**Лицензия** (https://github.com/roboflow/rf-detr, файл `LICENSE` — Apache License 2.0, SPDX `Apache-2.0` по GitHub API; README
раздел License):
- Код пакета `rfdetr` — Apache 2.0. README: «RF-DETR Nano, Small, Medium and Large detection, every RF-DETR-Seg size (Nano through
  2XLarge), and RF-DETR Keypoint are released under the Apache 2.0 license, so they're commercially usable out of the box: you can
  ship them in closed-source, commercial products, including self-hosted deployments, without paying a license fee».
- **Веса Nano/Small/Medium/Large (детекция) — Apache 2.0.** Atto/Femto/Pico/XL/2XL и модели NAS платформы — PML 1.0 (`rfdetr[plus]`):
  коммерция только на Roboflow, свой хостинг — платный Enterprise. `pip install rfdetr` ставит только Apache-часть.
- Основа: LW-DETR (Apache 2.0) и DINOv2 (`facebookresearch/dinov2` — Apache 2.0 по GitHub API). Базовые веса обучены на COCO
  (`docs/learn/pretrained.md`).

**Цифры моделей** (README, T4 + TensorRT FP16, батч 1):

| Модель | COCO AP50:95 | RF100-VL AP50 | задержка | параметры | разрешение |
|---|---|---|---|---|---|
| Nano | 48,4 | 85,0 | 2,3 мс | 30,5 M | 384 |
| Small | 53,0 | 86,7 | 3,5 мс | 32,1 M | 512 |
| Medium | 54,7 | 87,4 | 4,4 мс | 33,7 M | 576 |
| Large | 56,5 | 88,2 | 6,8 мс | 33,9 M | 704 |

**Дообучение** (`docs/learn/train/index.md`, `training-parameters.md`, `dataset-formats.md`, `faq.md` в репо):
- `pip install "rfdetr[train]"`; `RFDETRMedium().train(dataset_dir=..., epochs=100, batch_size="auto", lr=1e-4, output_dir=...)`.
- Формат определяется сам: COCO (`train/_annotations.coco.json`, `valid/…`, `test/…`) или YOLO (`data.yaml` + `train/images`,
  `train/labels`). Число классов берётся из разметки; классы COCO не сохраняются.
- Разрешение — параметр `resolution`, кратно 32 для детекции (типовые 384/512/576/704; можно выше, дороже по памяти).
- Ориентиры батча (эффективный 16): T4 16 ГБ — `batch_size=4, grad_accum_steps=4`; RTX 3090/4090 24 ГБ — 8×2; A100 — 16×1.
  По умолчанию `grad_accum_steps=1`.
- Есть EMA, ранняя остановка (`early_stopping`, `patience` 10), `skip_best_epochs` при дообучении, `resume` с чекпойнта
  (полный `.ckpt` восстанавливает оптимизатор) — это важно для прерываемых машин; `checkpoint_interval` 10 эпох.
- Лимит объектов на картинку — `num_queries` 300 (у 2dplan2strct столько же); на лист с ~120 объектами хватает.
- Сколько картинок нужно: у Roboflow точного числа нет. Ориентиры практиков: убывающая отдача около 150–500 примеров на класс
  (Shahinfar et al. 2020 по пересказу), «менее ~100 на класс — редко хватает»; считать надо **объекты**, а не листы
  (поиск: форум Roboflow и обзоры, см. ссылки в разделе 7). Набор RF100-VL — 100 наборов из Roboflow Universe, по нему RF-DETR
  и проверяли на «чужих доменах» (arXiv 2505.20612, 2511.09554).

**Вывод и экспорт:**
- CPU: замер автора 2dplan2strct — 0,46 с на лист (2 потока); наш T-35 — 0,3–0,7 с, пик RSS 1 374 МБ на pakardev (PyTorch).
- Экспорт: `model.export(format="onnx")` (нужен `rfdetr[onnx]`), запуск — `RFDETRInference("…/inference_model.onnx")` или
  onnxruntime напрямую; есть OpenVINO, TensorRT, TFLite (`docs/exports/onnx.md`, `faq.md`). Грабля из доков: выходы ONNX
  сопоставлять по имени (`dets`/`labels`), не по форме.

## 3. Открытые наборы планов — лицензии и годность для коммерческого обучения

| Набор | Размер | Похож на наши UK-рекламные? | Разметка | Лицензия | Коммерческое обучение |
|---|---|---|---|---|---|
| CubiCasa5k | 5 000 листов, 80+ категорий, сплит 4200/400/400 | **да, ближе всех** (финские планы для продажи жилья) | полигоны SVG (двери, окна, стены, комнаты) | GitHub `LICENSE`: CC BY-NC 4.0; Zenodo 2613548: CC BY-NC-SA 4.0 | **нет** |
| ResPlan (2025) | 17 000 планов, сплит 13 053/1 632/1 632 | геометрия из реальных объявлений, но **картинок нет** — только векторы | векторы стен/дверей/окон/комнат + граф | данные CC BY 4.0, код MIT; права на исходные картинки не передаются; есть процедура снятия | **да, с указанием авторства**; картинки надо рисовать самим |
| Swiss Dwellings (Archilyse, Zenodo 7788422, v3.0.0) | 45 176 квартир, ~3 100 зданий, ~715 тыс. проёмов (двери, окна) | нет (CAD-векторы швейцарских домов) | WKT-геометрия: `entity_type` area/separator/opening/feature | CC BY 4.0 | **да, с указанием авторства**; рендер сами |
| MSD (Modified Swiss Dwellings, 4TU DOI 10.4121/e1d89cb5…) | 5,3 тыс. планов, 18,9 тыс. квартир | нет (производная от Swiss Dwellings, графы) | графы/маски | CC BY 4.0 (DataCite) | да, с авторством |
| FloorPlanCAD | 15 663 CAD-чертежа | нет (строительные CAD) | SVG + PNG + COCO | CC BY-NC 4.0 (сайт floorplancad.github.io; копии на HF с тегом CC BY-SA — это теги перезаливщиков, не авторов) | **нет** |
| WAFFLE | ~20 тыс. картинок с Wikimedia Commons | частично (много исторических/общественных зданий) | метаданные, тексты; рамок дверей нет | на странице не указана; код — «Wikimedia Commons license»; у каждой картинки своя лицензия Commons | неясно, по картинке |
| R2V / FloorplanTransformation | ~870 размеченных (LIFULL HOME'S, Япония) | частично | векторы стен/дверей/иконок; **картинки не раздаются** («We don't have the permission to share the rasterized images») | код MIT; картинки LIFULL — по договору NII, исследования | **нет** (без картинок) |
| ROBIN | ~510 планов (ICDAR 2017) | нет (схематичные) | классы планов для поиска | репо GPL-3.0, лицензия данных отдельно не указана | неясно → считать нет |
| CVC-FP | 122 скана | нет | стены, двери, окна, комнаты | CC BY-NC 4.0 (dag.cvc.uab.es) | **нет** |
| Rent3D | 215 квартир Лондона (объявления аренды) | **да по стилю**, но мало | планы + фото | лицензия не указана; исходные картинки — сайта аренды | **нет** (права неясны) |

Roboflow Universe (страницы закрыты Cloudflare для автоматического чтения; данные — по выдаче поиска, перепроверить руками):
- «Floor Plan Walls» (`floorplan-mbkj7/floor-plan-walls-ohio3`) — 3 395 картинок, CC BY 4.0, классы не подтверждены.
- «floorplan-3xara» (`floorplan-hudg2`, форки `invlm`, `yassmen`, `data-collection-shygp`) — у форка ~12 488 картинок, CC BY 4.0.
- «Floor Plans 500» (`university-y9nbi`) — 402 картинки, двери/окна/зоны, CC BY 4.0.
- «Segmentation(wall,door,window)» (`houses-khykk`) — 405 картинок, CC BY 4.0.
- «Wall-Window-Door detection» (`floorplan-model`) — CC BY 4.0, размер не виден.
- «CVC-FP-Floorplan» (`sandy-s-workspace`) — перезалив CVC-FP; оригинал CC BY-NC.

Важно про Universe: лицензию ставит загрузивший. Многие наборы — перезаливы CubiCasa5k/CVC-FP/чужих сайтов с меткой CC BY 4.0;
метка не снимает исходный запрет. Брать только те, где видно происхождение картинок. Это вопрос к юристу, не к нам.

**Где лицензия разрешает коммерческое обучение:** ResPlan, Swiss Dwellings, MSD (все CC BY 4.0, но это векторы без картинок —
рисовать листы самим) и наборы Universe с CC BY 4.0 при чистом происхождении. CubiCasa5k, FloorPlanCAD, CVC-FP — нет.

## 4. Своя разметка

- Сколько (оценка по ориентирам раздела 2): на UK-листе 6–60 дверей (наш эталон: 7 листов ≈ 120 дверей). 100–150 листов дают
  ~1 000–1 500 дверей и столько же окон — это выше порога «несколько сотен примеров на класс». Разумно: 150 листов на обучение +
  отдельно 40–50 на проверку (нынешний эталон в 7 листов слишком мал, чтобы различать 0,90 и 0,93).
- Разнообразие важнее количества: разные агентства и стили (Rightmove-скриншоты, водяные знаки, мебель-иконки, тёмные стены,
  тонкие линии, многоэтажные листы).
- Синтетика (бесплатно по лицензии): рисовать листы из векторов ResPlan/Swiss Dwellings в 5–10 «агентских» стилях → десятки тысяч
  листов с точной разметкой; затем дообучить на своих 150 реальных. Это оценка подхода, не проверено.
- Инструменты: CVAT (MIT, `cvat-ai/cvat`) — свой сервер, импорт предразметки в COCO, авто-разметка своей моделью; Label Studio
  Community (Apache 2.0, `HumanSignal/label-studio`) — импорт предразметки. Roboflow Free: проекты закрыты, пока не опубликуешь;
  10 кредитов в месяц, ИИ-разметка тратит кредиты; «New workspaces allow data licensing and model training on private projects
  by default» — опцию надо выключить в настройках, иначе наши листы могут пойти в данные Roboflow (roboflow.com/pricing).
- Ускорение: наши кандидаты дверей из `tools/floorplan/fpcore.py` → COCO-предразметка → человек правит (так же устроен DoorDet,
  arXiv 2508.07714: детектор → LLM-классификация → проверка человеком; цифр экономии в аннотации нет). Наша модель первой
  итерации потом размечает следующие листы.
- **Юридический риск (не решаем):** брать выходы 2dplan2strct как предразметку для обучения своей модели — спорно. Условия
  запрещают коммерческое использование модели и молчат про выходы; использование её выходов для коммерческого продукта может
  считаться коммерческим использованием. Нужен юрист или письменное разрешение автора («Contact the publisher for any other use»).
  Чистый путь — предразметка нашими правилами и своей моделью.

## 5. Видеокарта и деньги

- Цены (за час GPU): Salad — RTX 3090 $0,09–0,20, RTX 4090 $0,16–0,44, 4060 Ti 16 ГБ $0,08–0,14 по уровням приоритета
  (salad.com/pricing); RunPod Community — RTX 3090 $0,22, 4090 $0,34, A5000 $0,16, L4 $0,44, A100 80 ГБ $1,19; посекундно
  (runpod.io/pricing). Vast.ai — не проверял.
- Сколько часов (оценка от скорости автора 2dplan2strct ~4–8 карт/с на T4): 150–500 листов × 50–100 эпох = 7,5–50 тыс. проходов →
  0,5–3 ч на T4, в 2–3 раза быстрее на 3090/4090. С синтетикой 20 тыс. листов × 15 эпох ≈ 300 тыс. проходов → ~10–20 ч T4 или
  ~4–8 ч на 4090. С подбором (5–10 прогонов) — 20–60 ч GPU.
- Деньги (оценка): дообучение на своих листах — **$1–5**; с синтетикой и подбором — **$10–40** на 4090 (Salad/RunPod).
- Salad годится с оговорками: контейнеры прерываемые (Medium/Low/Lowest вытесняются; High — «never preempted», но узел может
  отвалиться), диска мало, оплата за работу контейнера. Salad сам описывает дообучение с сохранением состояния и продолжением после
  прерывания (docs.salad.com, учебник LLM fine-tuning; блог про SDXL с чекпойнтом каждые 10 %). У нас уже есть пул и стопоры
  (`core/mesh-pool.md`), но для разовых коротких прогонов проще RunPod: SSH, том для данных, без вытеснения.

## 6. Итог: рекомендуемый путь (решать ведущему и владельцу)

1. Эталон: расширить `gold-doors` до 40–50 листов разных агентств (2–3 дня глазами; без этого прирост не измерить).
2. Данные: 150 своих листов — предразметка нашими кандидатами → правка в CVAT (оценка 3–5 мин на лист → 10–15 ч человека);
   классы как у 2dplan2strct (`door`, `window`, при желании `wall`, `room`) плюс, возможно, `door_double`/`opening`.
3. По желанию — синтетика из ResPlan/Swiss Dwellings (CC BY 4.0, указать авторство) в нескольких стилях: 2–4 дня кода.
4. Обучение: `RFDETRMedium`, сначала 576 как у автора, затем 704/768 (двери на листе 2000 px при 576 становятся ~15–20 px);
   COCO-формат; RunPod или Salad 4090; $1–40.
5. Проверка: `doors_eval.py` на расширенном эталоне, сравнение с нашим 0,79 и с 2dplan2strct 0,93 (её — только как мерку, внутри).
6. Встраивание: ONNX + onnxruntime на CPU как второе мнение к правилам (T-35 уже показал пользу: подтверждённая вторым мнением
   дверь верна 78 %, неподтверждённая — 10 %).

Объём: ~1,5–3 недели работы исполнителя + 10–15 ч разметки; деньги на GPU — десятки долларов.

Риски: (а) 150 листов может не хватить до 0,93 — у автора порядка 15–30 тыс.; лечится синтетикой и наращиванием; (б) лицензии
наборов Universe с неясным происхождением; (в) соблазн псевдо-разметки 2dplan2strct — юридический риск; (г) маленький эталон даёт
шум в сравнении; (д) права на сами листы объявлений (Rightmove/агентства) для обучения — отдельный юридический вопрос (аналог —
ResPlan, который снимает права на исходные картинки и публикует только геометрию); (е) RF-DETR в плохих сценах (скриншот,
водяной знак) может давать ложные — нужна постпроверка нашими правилами.

## 7. Источники

- Карточка и файлы модели: https://huggingface.co/OsamaMo/2dplan2strct ; условия: https://huggingface.co/OsamaMo/2dplan2strct/blob/main/USAGE_TERMS.md ;
  метаданные: https://huggingface.co/api/models/OsamaMo/2dplan2strct ; автор: https://huggingface.co/OsamaMo
- RF-DETR: https://github.com/roboflow/rf-detr (README, LICENSE), доки https://rfdetr.roboflow.com (обучение, параметры,
  форматы, FAQ, экспорт ONNX); статья https://arxiv.org/abs/2511.09554 ; RF100-VL https://arxiv.org/abs/2505.20612 ;
  DINOv2 https://github.com/facebookresearch/dinov2 ; LW-DETR https://github.com/Atten4Vis/LW-DETR
- CubiCasa5k: https://github.com/CubiCasa/CubiCasa5k , https://zenodo.org/record/2613548
- ResPlan: https://github.com/m-agour/ResPlan (LICENSE, README)
- Swiss Dwellings: https://zenodo.org/records/7788422 ; MSD: https://doi.org/10.4121/e1d89cb5-6872-48fc-be63-aadd687ee6f9 ,
  https://github.com/caspervanengelenburg/msd
- FloorPlanCAD: https://floorplancad.github.io/ ; WAFFLE: https://tau-vailab.github.io/WAFFLE/ , https://github.com/TAU-VAILab/WAFFLE
- R2V: https://github.com/art-programmer/FloorplanTransformation ; ROBIN: https://github.com/gesstalt/ROBIN ;
  CVC-FP: https://dag.cvc.uab.es/dataset/cvc-fp-database-for-structural-floor-plan-analysis/ ;
  Rent3D: https://www.cs.utoronto.ca/~fidler/projects/rent3D.html
- Roboflow Universe: https://universe.roboflow.com/floorplan-mbkj7/floor-plan-walls-ohio3 ,
  https://universe.roboflow.com/floorplan-hudg2/floorplan-3xara , https://universe.roboflow.com/university-y9nbi/floor-plans-500 ,
  https://universe.roboflow.com/houses-khykk/segmentation-wall-door-window ,
  https://universe.roboflow.com/floorplan-model/wall-window-door-detection-9ofgh
- Разметка: https://github.com/cvat-ai/cvat , https://github.com/HumanSignal/label-studio , https://roboflow.com/pricing ;
  DoorDet https://arxiv.org/abs/2508.07714 ; сколько картинок — https://changsin.medium.com/how-many-images-do-you-need-for-object-detection-d33185629843 ,
  https://discuss.roboflow.com/t/roboflow-3-0-and-yolo-8-11-transfer-learning-advice-needed/10152
- GPU: https://salad.com/pricing , https://www.runpod.io/pricing ,
  https://docs.salad.com/container-engine/tutorials/machine-learning/llm-fine-tuning
