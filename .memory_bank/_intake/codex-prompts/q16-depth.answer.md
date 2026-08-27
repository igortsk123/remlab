## Вывод

Дополнительно отправлять depth/segmentation/normals в текущий production-запрос я не рекомендую. Для `gpt-image-2` это будет не управляющий канал, а обычный третий референс. Публичных доказательств, что такая depth-картинка улучшает сохранение геометрии GPT Image, нет.

Практический приоритет:

1. Оставить clay + номера + товарные эталоны как основной путь.
2. Проверить depth только контролируемым A/B.
3. Не добавлять одновременно depth, normals и segmentation.
4. Если геометрия должна гарантироваться, использовать путь «фотореалистичная пустая комната → детерминированная вставка товаров → локальная гармонизация», а не ждать гарантии от глобального GPT-edit.

Уверенность в рекомендации — средне-высокая. Уверенность в том, что depth обязательно ухудшит результат, — низкая: это ещё не измерено.

## Что известно про GPT Image

Официальная документация OpenAI подтверждает:

- `/v1/images/edits` принимает несколько изображений-референсов.
- У `gpt-image-2` нельзя менять `input_fidelity`: все входы автоматически обрабатываются с высокой точностью.
- `quality=low` управляет качеством/стоимостью выхода, а не «силой» привязки к референсу.
- Специальных полей для depth, normals, segmentation, ControlNet scale или spatial-conditioning нет.
- Даже штатная edit-mask является prompt-based guidance и не гарантирует точное соблюдение формы.
- OpenAI прямо называет precise composition/layout-sensitive placement ограничением GPT Image. [Официальное руководство Image Generation](https://developers.openai.com/api/docs/guides/image-generation)

Следовательно, дополнительная depth-карта не получит того же смысла, что в ControlNet. Модель может понять её как схему, альтернативный вид, стилистический референс или изображение, которое требуется воспроизвести.

OpenAI рекомендует для нескольких входов явно задавать их индексы и роли. Cookbook также показывает drawing→photorealistic workflow с формулировкой «preserve exact layout, proportions and perspective», но не приводит depth-conditioned экспериментов. [GPT Image Prompting Guide](https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide)

Публикации по ControlNet этого пробела не закрывают. Depth, edges, segmentation и normals работают там потому, что модель имеет специально обученный conditioning pathway. Авторы отдельно отмечают, что depth-to-image обычно требует end-to-end обучения; простой дополнительный RGB-вход не эквивалентен ControlNet. [ControlNet paper](https://arxiv.org/abs/2302.05543)

## Что уже делает текущий clay

`compile_scene` выдаёт depth, instance masks и semantic map, а мебель растеризуется ролевыми прокси-формами, а не голыми кубами: [scene.py](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:325).

Сам clay уже объединяет почти все предлагаемые сигналы:

- цвет по семантике;
- яркостное затенение по depth;
- отдельные тона экземпляров;
- контуры на границах instance masks;
- корректную окклюзию;
- форму, масштаб и ориентацию объёмов.

Это видно непосредственно в [clay_render](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:541). Поэтому отдельный depth будет в основном повторять информацию, уже визуально представленную в более понятной модели форме.

В `draft_render.py` depth-карта действительно строится, но в GPT-путь не передаётся: [collage](/home/pakar/igor/remlab/tools/scout/draft_render.py:145) возвращает `dmap`, затем `_sheet_gpt` отбрасывает её как `_d`, а запрос получает только marked clay и identity sheet: [draft_render.py](/home/pakar/igor/remlab/tools/scout/draft_render.py:950), [список `imgs`](/home/pakar/igor/remlab/tools/scout/draft_render.py:1070).

Есть и неточность комментария: блок около строки 420 обещает четыре входа, но фактически отправляются два изображения и JSON внутри prompt. Неразмеченный clay-лист сохраняется на диск, но не отправляется.

## Почему опыт SDXL-ControlNet нельзя переносить

`shell_make.py` использует специализированный API:

- отдельные `depth_image_url`, `normal_image_url`, `segmentation_image_url`;
- `*_preprocess=False`;
- явный `controlnet_conditioning_scale=0.85`.

См. [shell_make.py](/home/pakar/igor/remlab/tools/scout/shell_make.py:69). Именно эти архитектурные входы и дают пространственное управление.

ADR-0063 фиксирует успех 9/10 для пустой комнаты с SDXL-ControlNet, но это другой endpoint, другая модель и другая задача: [ADR-0063](/home/pakar/igor/remlab/.memory_bank/decisions.md:966). Этот опыт доказывает полезность карт для ControlNet, но ничего не доказывает про generic reference input GPT Image.

Комментарий в `draft_render.py` утверждает, что голая depth-карта уже давала «висящие в пустоте» предметы: [draft_render.py](/home/pakar/igor/remlab/tools/scout/draft_render.py:158). Но в git-истории нет воспроизводимого A/B именно `gpt-image-2: clay` против `clay+depth`; это следует считать наблюдением, а не достаточным экспериментом.

## Сравнение сигналов

| Вход | Возможная польза | Основной риск | Вердикт |
|---|---|---|---|
| Marked clay | Геометрия, семантика, окклюзия, привязка №→SKU в одном понятном кадре | Подписи могут перекрывать детали или просочиться в выход | Основной и лучший сигнал |
| Контуры поверх clay | Делают силуэты и границы заметнее | Уже присутствуют; чрезмерные линии могут остаться в результате | Возможна небольшая локальная доработка, отдельный лист не нужен |
| Отдельный grayscale depth | Может усилить крупные плоскости и порядок близко/далеко | Нет обученного decoder-контракта; буквальная интерпретация, конфликт входов, дополнительные tokens | Только A/B |
| Role-coded segmentation | Явно отделяет экземпляры | Произвольные цвета ничего не значат без легенды; color leakage; семантика дублирует номера | Ниже depth |
| Normals | Теоретически помогают поверхностям и освещению | Фиолетово-зелёная карта похожа на стиль/материал; текущие normals приблизительные, из градиента depth | Не отправлять |

Set-of-Mark имеет опубликованные положительные результаты для visual grounding мультимодальных моделей: [SoM paper](https://arxiv.org/abs/2310.11441). Это не прямой тест image generation, но логически ближе к задаче №→объект, чем неизвестная интерпретация depth. В репо номера дополнительно соединяются с точками внутри масок и несут габариты: [viz_marks.py](/home/pakar/igor/remlab/tools/scout/viz_marks.py:297).

## Если всё же тестировать depth

Подавать её следует отдельным третьим изображением, не смешивая с товарным листом:

1. `Image 1` — marked clay, авторитетный источник композиции.
2. `Image 2` — товарные фотографии.
3. `Image 3` — пиксельно выровненный depth-sheet той же структуры и размеров, включая два вида и маджента-разделитель.

Предпочтительный формат — трёхканальный grayscale PNG без heatmap-палитры. Белое — близко, чёрное — далеко. Но это лишь выбранный вами контракт, не контракт OpenAI.

Текущая `dmap` не метрическая: она min-max нормализуется отдельно для каждого кадра в 8 бит. Поэтому называть её «exact depth in centimeters» нельзя; это relative depth/occlusion guide. Текущий uploader также перекодирует все входы в JPEG: [gpt_edit](/home/pakar/igor/remlab/tools/scout/draft_render.py:640). Для карт лучше lossless PNG, иначе на резких границах появится ringing.

Формулировка для эксперимента:

> Image 1 is the authoritative marked 3D layout. Preserve its camera, room boundaries, object footprints, orientations and occlusions exactly.  
> Image 2 contains product appearance references mapped by number.  
> Image 3 is a pixel-aligned relative-depth guide for Image 1 only: white pixels are nearer to the camera and black pixels are farther away. Use it only to preserve perspective, depth ordering and occlusions. Do not reproduce its grayscale appearance, do not treat it as another view, and do not move any object to match Image 2.

Не добавлять в тот же тест normals или segmentation: иначе будет невозможно понять, какой сигнал помог.

## Состояние внутренних доказательств

Внутренние цифры пока нельзя считать подтверждением текущего рецепта:

- Плейбук сообщает `13–14/14` для `gpt-image-2 medium`, но одновременно требует каждый товар отдельным референсом: [playbook](/home/pakar/igor/remlab/.memory_bank/domain/viz-fidelity-playbook.md:31).
- Текущий код использует `low` и один общий identity-sheet.
- Плейбук сам предупреждает, что описывает старую ветку.
- ADR-0123 фиксирует, что после полной перерисовки координаты сцены переставали совпадать с готовым фото; на одном прогоне `gpt-image-2 medium` подтвердил только три товарных якоря: [ADR-0123](/home/pakar/igor/remlab/.memory_bank/decisions.md:2296). Это тревожный сигнал, но он смешивает ошибки геометрии, узнавания SKU и верификатора.

То есть сохранение геометрии нынешним one-shot pipeline ещё не измерено отдельно от product fidelity.

## Как провести честный замер

Минимальный пилот: 12 сложных сцен × 3 повтора × 2 варианта = 72 запроса:

- A: текущий marked clay + identity sheet;
- B: A + aligned grayscale depth.

Для решения о production — минимум 30 разнообразных сцен × 3 повтора на вариант: 180 запросов для A/B. Если сравнивать ещё contours и segmentation — 360 запросов. Два вида одного листа считать зависимыми; статистическая единица — сцена.

Сцены стратифицировать по плотности, окклюзиям, количеству предметов, угловой мебели, коврам, окнам/дверям, предметам у края и разворотам 90°.

Основные метрики:

- Recall предметов, лишние предметы и дубли.
- Ошибка нижней опорной точки/центра относительно instance mask.
- Масштаб projected bbox/footprint.
- Правильность ориентации и попарных отношений left/right/front/behind/on-top-of.
- Окклюзионный порядок.
- IoU окна и двери, положение стыка стен/пола.
- Отдельно: SKU identity, цвет/материал и слепая оценка фотореализма.
- Артефакты: grayscale/color leakage, линии, номера, потеря маджента-полосы, смешение двух видов.

Monocular-depth error результата можно считать только вторичной метрикой: собственный depth estimator также ошибается и может предпочитать «правдоподобную», но неверную сцену.

Критерий принятия следует зафиксировать до просмотра результатов. Например:

- не менее +5 процентных пунктов к доле полностью геометрически корректных сцен либо ≥15% снижения медианной positional error;
- нижняя граница 95% paired cluster-bootstrap CI выше нуля;
- падение SKU-fidelity и realism не более 3 п.п.;
- без роста пропусков, дублей и лишней мебели.

Стоит также добавить контроль `baseline medium` или `single-view low`: официальное руководство советует сравнивать medium/high для identity-sensitive edits. Возможно, увеличение output budget или упрощение двухпанельной композиции даст больше, чем depth.

## Что изменило бы вывод

Рекомендация сменится на «добавлять depth», если:

- A/B на текущем snapshot и текущих сценах даст устойчивое улучшение геометрии без потери SKU и реализма;
- OpenAI опубликует специализированный structural/depth-control input;
- появится подтверждение, что конкретный `gpt-image-2` обучен понимать depth conventions как отдельную модальность.

Для воспроизводимости лучше закрепить snapshot `gpt-image-2-2026-04-21`, если Vercel Gateway его пропускает; текущий код использует плавающий alias. [Страница модели GPT‑Image‑2](https://developers.openai.com/api/docs/models/gpt-image-2)

Файлы я не изменял. Ревью выполнено по текущему рабочему дереву, где `draft_render.py` уже имел незакоммиченные изменения до проверки.