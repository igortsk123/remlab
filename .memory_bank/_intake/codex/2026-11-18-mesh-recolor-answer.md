## Вывод

Для вашей задачи я бы не менял Hunyuan3D Paint на другой генеративный texturing-модель. Почти все перечисленные TEXTure / Paint3D / SyncMVD / MV-Adapter / TEXGen / IP-Adapter-подходы генерируют текстуру заново. Они умеют делать правдоподобный материал, но не гарантируют:

- колориметрически точный оттенок;
- сохранение существующей древесной текстуры, плетения и принта;
- отсутствие новых артефактов и швов.

Наиболее надёжный и дешёвый путь — детерминированная постобработка готового GLB:

1. Оценить камеру исходной фотографии.
2. Получить соответствие пиксель фото → поверхность → UV.
3. Отделить низкочастотный цвет baseColor от высокочастотной детали.
4. Корректировать только низкочастотный компонент, а detail residual перенести в результат без изменений.
5. Проверять результат в том же ракурсе по ΔE00 и отдельно контролировать сохранность высоких частот.

Это не «global multiply»: локальный контраст и спектр дерева/ткани сохраняются конструктивно.

Для новых моделей параллельно имеет смысл закончить эксперимент `_mv_cal`: коррекция multiview до bake потенциально дешевле постпроцесса. Но она не решает уже готовые GLB и пока не доказала сохранность деталей.

---

## Что из существующих методов действительно подходит

| Метод | Что происходит с текущей текстурой | Практический вердикт |
|---|---|---|
| Низкочастотная коррекция + фиксированный detail residual | Высокочастотная часть сохраняется буквально | **Основной вариант** |
| Differentiable rendering низкочастотного поля | Сохраняется, если residual заморожен | Хорошее усложнение второго этапа |
| Reinhard / histogram / sliced OT | Без декомпозиции меняет и контраст деталей | Только по материалам и только для low-pass |
| Hunyuan `_mv_cal` до bake | Не регенерирует структуру multiview, но меняет её яркость до переноса в UV | Перспективно для новых мешей |
| Hunyuan3D Paint повторно | Генерирует новую текстуру | Только когда исходная текстура уже непригодна |
| TEXTure / Text2Tex / SyncMVD / Paint3D / MVPaint | Перерисовывают материал | Не годятся для гарантированного сохранения grain/weave |
| TEXGen | Генерирует UV-текстуру по image/text condition | Качественный генератор, но не корректор |
| MV-Adapter | Генерирует новые согласованные виды/текстуру | Reference similarity, а не точная калибровка |
| IP-Adapter-подобный repaint | Перерисовывает внешний вид по embedding | Слабая гарантия точного цвета и деталей |
| SUPRA-Tex | Восстанавливает/дополняет PBR по референсному виду | Перспективный резерв, но слишком новый |

По конкретным работам:

- [Hunyuan3D 2.1 Paint](https://github.com/tencent-hunyuan/hunyuan3d-2.1/blob/main/hy3dpaint/README.md) уже принимает существующий mesh и изображение и строит PBR-текстуру через multiview. Повторный запуск может дать лучший результат, но это опять генерация, а не сохранение текущей фактуры.
- [Paint3D](https://github.com/OpenTexture/Paint3D) строит новую lighting-less 2K-текстуру через генерацию видов, UV-inpainting и refinement. Это хороший генератор, не инструмент оттеночной калибровки.
- [TEXGen](https://github.com/CVMI-Lab/TEXGen) генерирует UV напрямую, в том числе по одному изображению. Он про synthesis/completion, не про сохранение старой текстуры.
- [SyncMVD](https://github.com/LIU-Yuxin/SyncMVD), [TEXTure](https://texturepaper.github.io/TEXTurePaper/), [Text2Tex](https://github.com/daveredrum/Text2Tex) и [MVPaint](https://openaccess.thecvf.com/content/CVPR2025/html/Cheng_MVPaint_Synchronized_Multi-View_Diffusion_for_Painting_Anything_3D_CVPR_2025_paper.html) в основном text-guided и регенерируют поверхность.
- [MV-Adapter](https://github.com/huanngzh/MV-Adapter) умеет image+geometry-conditioned multiview и texture generation, но также создаёт новые пиксели. Для восстановления отсутствующего материала он интересен; для сохранения существующего weave — нет.
- [EASI-Tex](https://sairajk.github.io/easi-tex/) сочетает ControlNet/IP-Adapter и image inversion. По идее близок к задаче reference-guided texturing, но опубликованный GitHub фактически содержит сайт проекта, а не готовый производственный пайплайн.
- Показательный отрицательный результат: [IP-ConTex](https://link.springer.com/article/10.1186/s42492-026-00232-2) использует image prompt, IP-Adapter и согласование видов, но авторы сами отмечают проблемы с повторяющимися высокочастотными деталями — полосами, клеткой, логотипами и вышивкой.
- [SUPRA-Tex](https://github.com/Supra-3D/SUPRA-Tex) конца 2026 года наиболее интересен как следующий кандидат: он использует surface-aligned anchors из референсного вида и восстанавливает PBR. Но это свежий препринт, модель дополняет/генерирует материал и не гарантирует сохранение текущих texels.

Моя оценка: генеративные методы доказали способность создавать визуально убедительные текстуры. Их применение как «точного recolor без изменения фактуры» пока в значительной степени hype. Метрики этих работ обычно оценивают perceptual similarity, CLIP/FID и пользовательские предпочтения, а не ΔE00 и идентичность исходного high-pass residual.

---

## Рекомендуемый пайплайн

### 1. Подготовить фотографию

- Применить ICC-профиль, если он есть.
- Перевести sRGB в linear RGB.
- Использовать известную маску товара.
- Не применять grey-world по самому товару: серый диван или тёплое дерево разрушат такую оценку white balance.
- Если фон каталога достоверно нейтральный белый/серый и не клиппирован — использовать его для грубой WB/экспозиции.
- Исключить глубокие тени, блики, пересвеченные области и узкую кайму силуэта.

Абсолютный albedo из единственного RGB-изображения математически не идентифицируется: более тёмный материал под сильным светом может выглядеть как более светлый под слабым. Поэтому результат корректнее называть «соответствие референсной фотографии при нормализованном освещении», а не физически истинным albedo.

### 2. Оценить камеру

В репозитории уже есть хорошая начальная точка: [`best_pose`](/home/pakar/igor/remlab/tools/scout/salad/color_steps.py:115) перебирает yaw/pitch по silhouette IoU.

Его следует расширить:

- yaw, pitch, roll;
- focal length либо orthographic scale;
- 2D translation;
- несколько стартовых гипотез;
- loss по silhouette IoU плюс signed-distance/chamfer между границами.

Камеру надо подбирать только по геометрии и маске, не по цвету. Иначе неверный оттенок начнёт компенсироваться неверной позой.

После fit отрендерить:

- UV coordinates;
- material/primitive ID;
- depth;
- normals;
- visibility;
- желательно surface/connected-component ID.

Текущий [`texel_map`](/home/pakar/igor/remlab/tools/scout/salad/color_o2.py:171) уже реализует ключевую часть соответствия экранного пикселя UV-текселю. Bbox alignment из текущего прототипа слишком слаб для кресел и перспективных ракурсов.

Если silhouette IoU ниже примерно 0.6–0.65 или несколько камер дают почти одинаковый score, автоматическую коррекцию лучше не применять.

### 3. Разделить цвет и деталь

Для исходной baseColor-текстуры \(T_0\), в linear RGB:

\[
B_0 = \operatorname{edgeAwareLowPass}(T_0)
\]

\[
D = \log(T_0+\epsilon)-\log(B_0+\epsilon)
\]

Здесь:

- \(B_0\) — плавный цвет/тон материала;
- \(D\) — высокочастотный multiplicative residual: волокна, weave, мелкий принт, поры.

Оптимизируется только \(B_0\). Результат:

\[
T_1=\exp(\log(B_1+\epsilon)+D)
\]

Альтернатива — Laplacian pyramid: изменять только 1–2 самых грубых уровня, а мелкие уровни копировать побитно.

Лучше использовать edge-aware decomposition: guided/bilateral/domain-transform filter или маски сохранения крупных границ. Иначе широкий узор либо крупный сучок попадёт в low-pass и будет перекрашен.

Для цветовой оптимизации практичнее OKLab или Lab, но декомпозицию и recomposition лучше делать в linear RGB/log-reflectance, а не в gamma-encoded sRGB.

### 4. Подбирать низкочастотную коррекцию

Первый производственный вариант не требует нейросети или differentiable renderer:

- отдельная коррекция для каждого материала/цветового региона;
- плавное поле \(L,a,b\) по поверхности или coarse UV-grid;
- robust median/Huber loss по соответствующим пикселям;
- дополнительный loss по распределению цветов внутри региона;
- TV/Laplacian regularization;
- штраф за отклонение от identity.

Например:

\[
\mathcal L =
\lambda_1 \rho(\Delta E_{00}(R(B_1), A_{\text{photo}}))
+\lambda_2 W_{\text{sliced}}(R(B_1), A_{\text{photo}})
+\lambda_3 TV(B_1-B_0)
+\lambda_4\|B_1-B_0\|^2
\]

Где \(A_{\text{photo}}\) — оценённый photo albedo, а \(R\) — unlit/emissive render в найденной камере.

Pixelwise loss следует использовать только в центральных, хорошо совпавших областях. При несовершенной геометрии sliced-Wasserstein/гистограммное сравнение внутри одного материала устойчивее.

Классические [Reinhard color transfer](https://home.cis.rit.edu/~cnspci/references/dip/color_transfer/reinhard2001.pdf) и [итеративный N-D transfer Питье](https://www.cs.jhu.edu/~misha/ReadingSeminar/Papers/Pitie07.pdf) пригодны лишь как часть этой схемы — на low-pass и отдельно по материалам. На полном атласе они закономерно меняют древесные прожилки, контраст и отношения разных материалов.

### 5. Когда нужен differentiable rendering

Если piecewise/per-material коррекции недостаточно, следующий шаг — оптимизировать coarse surface field через:

- [nvdiffrast](https://github.com/NVlabs/nvdiffrast) — самый лёгкий вариант для differentiable rasterization;
- [PyTorch3D renderer](https://pytorch3d.org/docs/renderer) — удобнее для камер и прототипирования;
- [Mitsuba 3 inverse rendering](https://mitsuba.readthedocs.io/en/latest/src/inverse_rendering/gradient_based_opt.html) — если нужно совместно оценивать PBR, освещение и material parameters.

Для обычной мебели я бы начинал без Mitsuba. Полный inverse rendering увеличивает число неоднозначностей: коррекция baseColor начинает компенсироваться светом и roughness.

Поле лучше задавать на coarse surface graph/per-vertex basis, а потом bake в существующую UV. Это автоматически уменьшает UV seam artifacts. Упрощённая версия — coarse UV grid с seam constraints.

---

## Отделение albedo от света

### Практический базовый вариант

Для диффузных тканей и дерева:

1. Удалить 5–10% самых ярких и тёмных значений региона.
2. Удалить низкосатурированные локальные блики.
3. Не использовать boundary pixels.
4. Оценить плавную shading-карту Retinex-подобным фильтром.
5. Использовать trimmed median albedo в каждом материальном регионе.
6. При наличии normals совместно подобрать низкопорядковое сферически-гармоническое освещение и coarse albedo.

Последний пункт более контролируем, чем слепо доверять intrinsic-модели.

### Модели intrinsic decomposition

Наиболее практичный кандидат — [Marigold](https://github.com/prs-eth/Marigold): новые IID-модели предсказывают albedo, diffuse shading и non-diffuse residual; appearance-вариант также оценивает roughness/metallic.

Дополнительные исследовательские кандидаты:

- [IntrinsicDiffusion](https://github.com/JundanLuo/IntrinsicDiffusion) — albedo/shading/normals;
- [Colorful Diffuse Intrinsic Image Decomposition](https://github.com/compphoto/Intrinsic) — отдельно diffuse albedo, цветное shading и specular residual;
- [Intrinsic Image Diffusion](https://openaccess.thecvf.com/content/CVPR2024/html/Kocsis_Intrinsic_Image_Diffusion_for_Indoor_Single-view_Material_Estimation_CVPR_2024_paper.html) — indoor albedo/roughness/metallic, но домен целых комнат отличается от каталожных cutout-фотографий.

Я бы использовал IID только как proposal:

- сравнить Marigold, простой Retinex и robust raw-photo estimate;
- если оценки отличаются более чем на заданный ΔE/ΔL, отправить модель в manual review;
- не обучать корректор принимать output IID за ground truth.

Для металла, лака и стекла видимый цвет сильно определяется окружением. Автоматическую diffuse recolor для таких частей лучше отключать. В предельном случае нужен PBR inverse rendering и известное/ограниченное освещение.

---

## Работа с несколькими материалами

Нельзя переносить общую гистограмму фотографии на весь атлас.

Иерархия должна быть такой:

1. GLB material/primitive ID.
2. Connected surface components.
3. Кластеры исходного baseColor.
4. Photo superpixels/segments внутри соответствующей проекции.
5. Soft matching между близкими кластерами.

Для частей, не видимых на фотографии:

- переносить коррекцию только если они уверенно относятся к тому же материалу;
- иначе оставить исходный цвет;
- не генерировать «догадку» на обороте автоматически.

Особенно опасны:

- один atlas image, используемый несколькими GLB material;
- overlapping/reused UV;
- разные `baseColorFactor` поверх одной картинки;
- дерево и ткань близкого среднего цвета, но разного материала.

---

## Acceptance check

Текущий guard полезен как поиск аномалий, но его пороги слишком широки для приёмки shade correction.

### Цвет

Считать на eroded product/material masks в найденной камере:

- median ΔE00;
- p90 и p95 ΔE00;
- median \(|\Delta L^*|\);
- отдельно chroma и hue error;
- долю площади с ΔE00 выше порога.

Начальные, ещё не откалиброванные пороги для диффузных материалов:

- median ΔE00 ≤ 4–5;
- p90 ΔE00 ≤ 8–10;
- median \(|\Delta L^*|\) ≤ 3–5.

Их надо откалибровать на blind pairwise оценках владельца. Фото само по себе содержит WB, тональную кривую и shading, поэтому требовать ΔE00 < 2 почти наверняка будет ложной точностью.

### Сохранение деталей

На исходной и новой текстуре:

- SSIM/correlation high-pass log-luminance residual;
- отношение high-pass energy;
- gradient/edge correlation;
- при цветном принте — те же показатели отдельно для chroma residual.

Разумные стартовые ограничения:

- residual SSIM или correlation ≥ 0.98;
- high-pass energy ratio 0.9–1.1;
- отсутствие существенного падения локального RMS-контраста.

В предложенной схеме residual заморожен, поэтому показатели должны быть почти единичными. Если нет — произошёл clipping, gamut compression, ошибка фильтра или resampling.

Дополнительно:

- проверка нового ΔE через пары UV seam;
- процент clipped pixels;
- geometry/UV неизменны;
- изображения MR/roughness/metallic побитно неизменны;
- neutral-light renders с нескольких ракурсов;
- blind A/B владельца.

Текущий [`surface_colour`](/home/pakar/igor/remlab/tools/scout/mesh_color_check.py:333) измеряет baseColor по UV и площади граней; его можно переиспользовать, но расширить до ΔE00, matched-view masks и detail metrics. [`mesh_render.py`](/home/pakar/igor/remlab/tools/scout/mesh_render.py:207) уже имеет точный unlit-режим.

---

## Куда встроить в репозитории

Диагностика в плане убедительна: в 12/12 проверенных случаев основное изменение возникает на стадии multiview, а последующий bake добавляет мало. Это зафиксировано в [`mesh-color-03.md`](/home/pakar/igor/remlab/.memory_bank/plans/mesh-color-03.md) и согласуется с тем, что изменение яркости входной фотографии не даёт линейного управления выходом.

### Предпочтительное место

Для готовых GLB — отдельный post-process после paint и после удаления alien debris:

- paint сохраняется в [`_save_painted`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:551);
- затем вызывается `cut_alien_debris` в paint-only и full ветках;
- после этого геометрия уже финальная, а значит silhouette/camera fit не устареют.

Такой этап должен:

1. Читать только baseColor.
2. Строить matched-view correspondences.
3. Создавать исправленную baseColor-текстуру.
4. Хирургически заменять только соответствующий GLB image/blob.
5. Оставлять geometry, UV, material factors, normal и MR неизменными.

Для записи лучше переиспользовать аккуратную работу с GLB buffers/data URIs из [`texture_fix.py`](/home/pakar/igor/remlab/tools/scout/salad/texture_fix.py:192), а не [`color_o2.write_glb`](/home/pakar/igor/remlab/tools/scout/salad/color_o2.py:390), который повторно экспортирует сцену через trimesh и может менять не относящиеся к цвету части файла.

### Что уже можно переиспользовать

- Camera initialization: [`color_steps.best_pose`](/home/pakar/igor/remlab/tools/scout/salad/color_steps.py:115).
- Screen→UV mapping: [`color_o2.texel_map`](/home/pakar/igor/remlab/tools/scout/salad/color_o2.py:171).
- Metal/pattern/region эвристики: [`color_o2.py`](/home/pakar/igor/remlab/tools/scout/salad/color_o2.py:306).
- Unlit rendering: [`mesh_render.py`](/home/pakar/igor/remlab/tools/scout/mesh_render.py:207).
- Lab и photo/product measurements: [`mesh_color_check.py`](/home/pakar/igor/remlab/tools/scout/mesh_color_check.py:333).
- Безопасная замена baseColor внутри GLB: [`texture_fix.py`](/home/pakar/igor/remlab/tools/scout/salad/texture_fix.py:192).

### Вариант до bake

Текущий hook [`_Knobs._cal_hook`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:774) применяет `_mv_cal` к шести albedo views до super-resolution и bake. [`mv_color_cal.py`](/home/pakar/igor/remlab/tools/scout/salad/mv_color_cal.py:217) уже имеет region LUT, проверку соответствия chroma и support masks.

Это подходящее место для будущих моделей, если текущий T52 покажет:

- стабильное снижение ΔE00;
- отсутствие потери detail residual;
- отсутствие дополнительных seam/bake artifacts.

Но `_mv_cal` сейчас ограничен коррекцией L и приближённым bbox/silhouette alignment. Он не заменяет camera-aware postprocess готовых GLB.

---

## Основные риски

- Неверная камера или геометрия: цвет одного элемента переносится на другой.
- Несколько материалов в одном атласе.
- Цветной свет или автоматическая тональная обработка фотографии.
- Ошибка маски: фон начинает задавать target shade.
- Лакированная/металлическая поверхность, где visible RGB не равен baseColor.
- Крупный узор попадает в low-frequency слой и перекрашивается.
- Текущая высокочастотная деталь сама неверна: её строгое сохранение тогда нежелательно.
- Часть текстуры уже содержит baked highlights/shadows; фиксированный residual сохранит мелкие из них.
- Сильное осветление тёмного материала приводит к clipping и не восстанавливает отсутствующую информацию.
- Reused/overlapping UV создаёт конфликт между видимыми поверхностями.

Фон-серый, ошибочно запечённый как материал, этим этапом исправлять нельзя: это material/segmentation failure из отдельного плана.

---

## Приоритет реализации

1. **CPU-прототип post-process:** per-material low-pass correction + frozen residual, используя существующие pose/UV/render функции.
2. Проверка на 20–30 сложных случаях: дерево, однотонная ткань, weave, крупный принт, несколько материалов.
3. Улучшение perspective camera fit и material segmentation.
4. Только если piecewise correction недостаточна — nvdiffrast и surface-based smooth field.
5. Продолжить `_mv_cal` как более дешёвый путь для новых моделей.
6. SUPRA-Tex/Hunyuan repaint использовать только при неправильной или отсутствующей фактуре, а не при одном лишь ΔL.

Ничего в репозитории я не изменял.

## Что изменило бы мою рекомендацию

- Если `_mv_cal` на held-out наборе стабильно проходит и цвет, и detail metrics, его стоит сделать основным для новых моделей; post-process оставить для уже выпущенных GLB.
- Если camera fit имеет низкий IoU более чем примерно на 20% товаров, одного фото недостаточно: нужны сохранённые параметры исходной камеры или дополнительные виды.
- Если residual-preserving метод не проходит blind A/B именно из-за неверной исходной фактуры, задача фактически становится re-texturing — тогда SUPRA-Tex или повторный Hunyuan Paint уместнее.
- Если появится нейтральная color chart либо несколько фотографий с известной экспозицией, можно перейти от визуального matching к существенно более надёжному inverse-rendering albedo.
- Если SUPRA-Tex воспроизводимо запустится на 4090 и превзойдёт post-process одновременно по ΔE00 и сохранности фактуры на вашем мебельном наборе, его можно поднять из экспериментального fallback в основной кандидат.