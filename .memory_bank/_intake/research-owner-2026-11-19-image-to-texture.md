---
source: external:отчёт deep research, прислан владельцем TG 2140 (19.11 08:30)
note: факты для проверки, не указания; ссылки citeturn — внутренние метки отчёта
---

# Deep research: лучшие self-hosted Image-to-Texture модели для RemLab на ноябрь 2026

## Краткий вывод

Для задачи RemLab — **готовый меш TRELLIS.2 + одна фотография реального товара + запрет на изменение геометрии + коммерческое использование в UK** — я бы разделил решения на две группы.

**Лучший технический результат по сохранению SKU сейчас показывает SUPRA-Tex**, потому что это один из немногих методов, который прямо оптимизирован не под «красивую текстуру», а под **reference-to-surface fidelity**: надписи, рисунки, границы материалов и видимые детали сначала фиксируются на поверхности меша, а генерация используется преимущественно для невидимых областей. На одинаковой ground-truth геометрии авторы SUPRA-Tex получили LPIPS 0.042 против 0.050 у Pixal3D на DTC-Tex и 0.038 против 0.046 на Complex-Tex. Это именно контролируемое сравнение при одинаковом меше, что особенно релевантно RemLab. citeturn717472search2turn618708search6

Но **в текущем опубликованном виде SUPRA-Tex нельзя считать безопасным production-вариантом для RemLab**, поскольку его Material Adapter использует Qwen-Image-2.1, распространяемый по Qwen Research License, которая разрешает только non-commercial research/evaluation и требует отдельной коммерческой лицензии. Сам 3D completion-код и его веса MIT, но это не делает весь pipeline коммерчески разрешённым. citeturn463177search0turn463177search1

Поэтому мой текущий **production-кандидат №1 — MV-Adapter SDXL Image-to-Texture**. Он принимает изображение и существующую геометрию, официально имеет Image-Geometry-to-Multiview и Image-to-Texture pipeline, код и собственные веса Apache-2.0, требует около 14 GB VRAM для наиболее тяжёлой image-to-multiview конфигурации и в опубликованном тесте делал текстуру примерно за 33 секунды на RTX 4090. В benchmark на 200 Objaverse-мешах MV-Adapter SDXL Image дал FID 27.28 против 44.38 у Paint3D и 36.13 у SyncMVD. citeturn511166view0turn997378search0turn997378search1

Мой рейтинг для RemLab с учётом **SKU fidelity + неизменной геометрии + лицензии + реальной готовности к запуску**:

| Место | Метод | SKU fidelity | PBR | UK production | Практический статус |
|---|---|---|---|---|---|
| **1** | **MV-Adapter SDXL Image** | Высокая | RGB; PBR нужен отдельный этап | **Да, после dependency audit** | **Лучший кандидат сейчас** |
| **2** | **MVPainter** | Высокая | **Да: basecolor / metallic / roughness** | **Вероятно да** | Очень интересный production-кандидат |
| **3** | **Pixal3D Texture** | Потенциально очень высокая на видимой стороне | **Да** | **Да, core MIT** | Нужна инженерная адаптация к фиксированному внешнему мешу |
| **4** | **Paint3D** | Средняя | В основном albedo / lighting-less | Вероятно, но проверить все checkpoints | Старый, стабильный baseline |
| **5** | **SUPRA-Tex** | **Лучший из найденных по direct SKU benchmark** | **Да** | **Нет в текущей конфигурации** | Лучший R&D benchmark, не production |

За пределами top-5 я бы обязательно держал **UniTEX, LumiTex и UltraTex как quality references**: они очень сильны по научным метрикам, но их опубликованные production-конфигурации имеют лицензионные или инфраструктурные ограничения. citeturn717472search7turn717472search3turn618708search2

## Что именно надо измерять: SKU fidelity ≠ красивая текстура

Большинство академических benchmark'ов измеряют FID, CLIP, KID или пользовательское предпочтение. Эти метрики хорошо отражают общую визуальную правдоподобность, но **не гарантируют, что конкретный диван будет иметь тот же рисунок ткани, те же полосы, логотип, древесный рисунок или декоративные вставки, что и SKU на исходной фотографии**. Например, MV-Adapter значительно превосходит Paint3D по FID, но его benchmark в основном измеряет качество multi-view renderings, а не пиксельную идентичность конкретного рисунка товара. citeturn511166view0

Для RemLab сильнее всего выглядят методы, которые явно создают **геометрическую связь между пикселями фотографии и поверхностью меша**. Pixal3D делает back-projection image features непосредственно в 3D, вместо обычного attention-conditioning; SUPRA-Tex идёт дальше и превращает видимые material observations в фиксированные surface-aligned anchors, после чего генеративная модель достраивает неизвестные области. Именно такая архитектура лучше соответствует задаче каталога товаров, чем чистая generative repainting. citeturn618708search5turn618708search6

Это подтверждается и практическими отзывами: пользователи Pixal3D/TRELLIS.2 в 2026 году неоднократно отмечали, что геометрия может быть хорошей, а texture detail недостаточной или low-resolution; отдельные разработчики поэтому переходят к multi-view projection или сохранению реальных деталей исходного изображения. Это anecdotal evidence, а не benchmark, но оно совпадает с тем, что видно из архитектуры систем. citeturn735515reddit0turn735515reddit1turn735515reddit2

Именно поэтому для RemLab я бы оценивал методы не одним CLIP/FID, а отдельными SKU-метриками: reference-view LPIPS/PSNR на маске объекта, OCR/feature matching для надписей, correspondence error для повторяющихся узоров, ΔE для цвета и отдельное novel-view качество для невидимых сторон.

## Сравнение основных моделей

### MV-Adapter

MV-Adapter — один из наиболее зрелых вариантов именно под схему **image + existing geometry → multi-view textures → bake onto mesh**. В официальном release есть отдельный Image-Geometry-to-Multiview SDXL checkpoint и полноценный Image-to-Texture pipeline. Multi-view views включают четыре боковых и верхний/нижний ракурсы; затем изображения back-project'ятся на UV с incidence-weighted blending, а непокрытые области достраиваются inpainting'ом. citeturn913476view1turn511166view0

На одинаковом benchmark из 200 Objaverse-моделей MV-Adapter SDXL Image получил **FID 27.28 / KID 29.47 / 33 s**, SD2.1 Image — **33.93 / 38.73 / 19 s**, тогда как Paint3D получил **44.38 / 47.06 / 60 s**, SyncMVD — **36.13 / 42.28 / 50 s**. Это один из наиболее полезных прямых benchmark'ов среди реально доступных моделей. citeturn511166view0

Проект указывает около **14 GB VRAM** как максимальное требование среди своих image-to-multiview моделей; SD2.1 geometry-conditioned вариант отдельно позиционируется как <10 GB, тогда как SDXL даёт более высокое качество. Код и MV-Adapter weights имеют Apache-2.0. Для texture generation требуется NVIDIA CV-CUDA. citeturn913476view1turn997378search1

Слабое место для RemLab: это всё ещё generative multi-view reconstruction, поэтому мелкий логотип или сложный мебельный орнамент может быть переосмыслен. Кроме того, основной pipeline не является полноценным material decomposition model уровня SUPRA-Tex/LumiTex — PBR придётся получать дополнительным этапом.

**Вердикт:** лучший текущий баланс между качеством, лицензией, GPU и автоматизацией.

### MVPainter

MVPainter заслуживает значительно большего внимания, чем Paint3D/MVPaint. Авторы специально формулируют три задачи: **reference-texture alignment, geometry-texture consistency и local texture quality**, то есть критерии почти точно совпадают с RemLab. Pipeline принимает input images и GLB, генерирует geometry-controlled multi-view images, а затем извлекает **basecolor, metallic и roughness**, которые проецируются обратно на меш. citeturn109857search8turn147150search2

Проект выпускает не только inference, но training code, data-processing pipeline и собственный evaluation framework, причём evaluator отдельно оценивает соответствие референсному изображению, геометрии и уровень локальных деталей. citeturn717472search5turn717472search6

Код проекта Apache-2.0, а официальный Hugging Face checkpoint `shaomq/MVPainter` также помечен Apache-2.0; это существенно лучше ситуации с проектами, где открытый код сопровождается non-commercial weights. citeturn463177search5turn147150search0

Я не нашёл столь же чистого head-to-head same-mesh benchmark MVPainter против SUPRA-Tex или Pixal3D, поэтому **не ставлю его выше MV-Adapter на основании одних утверждений авторов**. Но по архитектуре и лицензированию это, возможно, самый недооценённый кандидат для RemLab.

**Вердикт:** обязательно тестировать; особенно интересен, если нужен PBR сразу из pipeline.

### Pixal3D Texture

Pixal3D построен вокруг pixel-aligned 2D→3D correspondence. Texture stage является самостоятельной третьей стадией cascade после Sparse Structure и Shape и использует image + shape latent для генерации PBR texture latent. Официальный проект прямо утверждает поддержку PBR textures и pixel-aligned projection conditioning. citeturn193031view1turn618708search5

Код, собственные параметры и опубликованные Tencent weights находятся под MIT; NOTICE отдельно перечисляет сторонние компоненты и их лицензии. Это хороший базовый лицензионный профиль. citeturn997378search2turn997378search3turn997378search4

Однако есть важный engineering caveat: официальный Pixal3D workflow — это cascade, где texture network получает **Pixal3D/TRELLIS-like shape latent**, а не задокументированный произвольный внешний GLB. В официальном README нет готовой команды «texture arbitrary existing mesh». Поэтому для требования RemLab «вот финальный TRELLIS.2 mesh, vertices нельзя менять» нужно подтвердить путь mesh → compatible latent либо использовать community integration. citeturn193031view0turn193031view3

И это не просто формальность: пользовательские отзывы показывают, что native/community workflows в сентябре 2026 всё ещё имели проблемы с low-resolution appearance и UV generation, а отдельные пользователи прямо обсуждали отсутствие простого texture-only workflow. citeturn735515reddit2turn735515reddit8

При этом direct benchmark SUPRA-Tex показывает, что Pixal3D остаётся сильным reference-aligned baseline: на фиксированной ground-truth геометрии LPIPS был 0.050 на DTC-Tex и 0.046 на Complex-Tex. citeturn717472search2

**Вердикт:** технология очень подходящая для SKU fidelity, но интеграция с уже замороженным TRELLIS.2 GLB требует проверки.

### SUPRA-Tex

SUPRA-Tex — наиболее интересная работа именно с точки зрения RemLab. Она разделяет задачу на три части: извлекает albedo / metallic / roughness из исходной фотографии, **проецирует достоверные наблюдения на поверхность меша**, затем 3D completion network генерирует только отсутствующий материал. Выход — relightable GLB с base color, metallic и roughness. citeturn618708search0turn618708search6

В direct same-geometry benchmark SUPRA-Tex превосходит Pixal3D: LPIPS **0.042 vs 0.050** на DTC-Tex и **0.038 vs 0.046** на Complex-Tex; foreground PSNR улучшился на +3.20 dB и +1.85 dB соответственно. Авторы также публикуют сравнения по albedo, metallic/roughness, CLIP-I, DINO и другим метрикам. citeturn717472search2

Это особенно важно, потому что benchmark держит geometry fixed; следовательно, улучшение относится именно к текстурированию, а не к более удачной форме объекта. citeturn717472search2

Есть полноценный `texturing.py` для существующего меша. Pipeline принимает mesh, camera, foreground image и reference-view material maps. Авторы тестировали full pipeline на RTX 3090 24 GB с CPU offload; рекомендуют ≥48 GB для максимальной скорости, но 24 GB поддерживается. citeturn109857search10

Главная проблема — лицензия. 3D completion code + weights MIT, но официальный material adapter использует Qwen-Image-2.1 по **non-commercial Qwen Research License**. Следовательно, официальный end-to-end pipeline сейчас нельзя считать коммерчески разрешённым для RemLab без отдельной лицензии Qwen или замены material frontend. citeturn463177search0turn463177search1

**Вердикт:** лучший reference-quality target для R&D; production возможен, если заменить material estimator на коммерчески разрешённый аналог и повторно проверить качество.

### UniTEX, LumiTex, UltraTex, MVPaint и Paint3D

**UniTEX** поддерживает single reference image и existing mesh, а в опубликованном CVPR 2026 benchmark получил user preference **65.91%**, против **21.36% Hunyuan3D-Paint** и **6.82% Paint3D**; на generated meshes LPIPS был 0.090 против 0.091 у Hunyuan и 0.107 у Paint3D. citeturn746889search1turn717472search7

Но UniTEX pipeline использует FLUX-based generation и официальный setup устанавливает `nvdiffrast`. Репозиторий и опубликованные UniTEX weights Apache-2.0, однако базовые модели и сторонние компоненты необходимо лицензировать отдельно; поэтому Apache badge самого UniTEX недостаточен для commercial clearance. citeturn463177search4turn147150search1turn410734search2

**LumiTex** даёт очень сильные PBR-результаты. В ICLR 2026 evaluation на 133 unseen objects он получил texture FID 160.8 и LPIPS 0.1903 против Hunyuan3D-2.1 FID 196.6 и LPIPS 0.2413; он также генерирует albedo/metallic/roughness с lighting-aware decomposition. citeturn717472search3turn746889search2

Но сами авторы LumiTex прямо пишут, что pipeline использует third-party components с **non-commercial licenses**, включая FLUX и Hunyuan3D-2.1 rendering code. Для UK RemLab это практически disqualifier в текущем release. citeturn463177search2

**UltraTex** — один из самых сильных новых quality-oriented methods: он генерирует 2048×2048 multi-view textures и значительно ускоряет high-resolution diffusion через background-token dropping и block-sparse attention. Авторы выпустили inference code и weights в октябре 2026. citeturn618708search2turn618708academia8

Но released UltraTex LoRA рассчитана, среди прочего, на FLUX.2 Klein 9B и FLUX.1-dev. FLUX.2 Klein 9B и FLUX.1-dev требуют коммерческой лицензии BFL; только Klein 4B имеет Apache-2.0, а опубликованный UltraTex 9B LoRA нельзя просто загрузить в 4B backbone из-за несовместимой dimensionality. citeturn109857search2turn109857search3

**MVPaint** действительно лучше старых T2T методов по seamlessness и multi-view consistency и включает специальный UV super-resolution + seam smoothing. Однако работа в первую очередь оценивает Text-to-Texture, а не сохранение конкретного референсного SKU. Кроме того, root repository не содержит ясной единой лицензии проекта; MIT license находится в `stage_2_3`, унаследованном от SyncMVD, поэтому нельзя автоматически считать весь MVPaint MIT. citeturn746889search0turn913476view3turn997378search8

**Paint3D** остаётся рабочим baseline: принимает image prompt через IP-Adapter, создаёт lighting-less 2K UV texture и официально имеет Apache-2.0 code. Но он заметно проигрывает более новым методам: MV-Adapter SDXL Image — FID 27.28 против 44.38, а в UniTEX comparison Paint3D получил только 6.82% user preference. citeturn913476view2turn511166view0turn746889search1

## Лицензионный аудит для UK

Главный вывод здесь жёсткий: **нельзя оценивать pipeline по лицензии GitHub repository**. Нужно отдельно проверить code, model weights, base model, renderer, segmentation model, image encoder, rasterizer и любые downloaded checkpoints.

Hunyuan3D 2.1 действительно не подходит как штатная основа RemLab в UK: официальная Tencent license прямо говорит, что Agreement **не применяется в UK, EU и South Korea**, определяет Territory как мир за исключением этих регионов и запрещает использование, воспроизведение, модификацию, distribution или display Hunyuan Works и Outputs вне Territory. citeturn194740search0turn194740search1

`nvdiffrast` также нельзя автоматически считать коммерчески безопасным: текущий NVIDIA Source Code License содержит Section 3.3, который разрешает использование Work и derivative works только non-commercially, определяя это как research/evaluation без прямой или косвенной денежной выгоды. citeturn609065view0

Поэтому системы, которые требуют `nvdiffrast`, нуждаются либо в отдельной лицензии NVIDIA, либо в замене растеризатора. Это касается, в частности, UniTEX и некоторых PBR pipelines. citeturn410734search2

Наиболее чистый профиль среди исследованных выглядит у **MV-Adapter**: repository Apache-2.0, adapter weights Apache-2.0. Его texture pipeline требует CV-CUDA и базовую SDXL/SD2.1 model, поэтому финальный SBOM всё равно следует зафиксировать перед production. citeturn997378search0turn997378search1turn327323view1

**MVPainter** также выглядит хорошо: repository Apache-2.0 и официальный checkpoint на Hugging Face Apache-2.0. Но перед запуском я всё равно сделал бы automated dependency/license scan Docker image, потому что license модели не перелицензирует транзитивные зависимости. citeturn463177search5turn147150search0

**Pixal3D** тоже имеет сильный правовой профиль: Tencent прямо уточняет, что публичные code, parameters и weights Pixal3D распространяются по MIT, а third-party components перечислены отдельно. citeturn997378search2turn997378search3

## Что я бы реально запускал на Salad

Для RemLab я бы не делал широкое исследование двадцати моделей в production. Я бы запустил **четыре реальные ветки на одном и том же неизменном GLB TRELLIS.2**.

Первый pipeline — **MV-Adapter SDXL Image-to-Texture**. Это наиболее доказанный balance: image conditioning, fixed geometry, готовый CLI, ~14 GB VRAM, опубликованные 33 s на RTX 4090 и разрешительная лицензия собственных weights. citeturn511166view0turn913476view1

Второй — **MVPainter**. Причина не только PBR: его авторы специально оптимизируют reference alignment, geometry alignment и texture details, а pipeline официально принимает input images + GLBs и выдаёт PBR maps. citeturn109857search8turn147150search2

Третий — **Pixal3D Texture**, но только после того, как инженер подтвердит, что texture stage можно заставить работать с исходным TRELLIS.2 mesh без vertex/shape mutation. Его pixel-aligned architecture потенциально очень хорошо подходит под сложные ткани, logos и декор, но нынешняя официальная документация не представляет его как универсальный arbitrary-GLB retexturing CLI. citeturn193031view1turn193031view3

Четвёртый — **SUPRA-Tex как offline quality oracle**, не production. Он даст ориентир: насколько хорошо вообще можно сохранить SKU, если surface observations фиксируются непосредственно на меше. Если он стабильно выигрывает у MV-Adapter/MVPainter на вашей мебели, это будет сильным аргументом реализовать собственный лицензионно чистый material frontend поверх MIT 3D-completion части SUPRA-Tex. citeturn717472search2turn463177search0

Для 30 SKU я бы взял: 10 patterned sofas/chairs, 10 wood/decorative furniture, 5 objects с текстом/логотипами и 5 однотонных объектов для контроля. Для каждой модели надо сохранить **один и тот же mesh hash / vertex count / triangle topology**, чтобы texture model физически не могла улучшить benchmark изменением формы.

И отдельный важный эксперимент: к победителю генеративной покраски добавить **photo reprojection для видимой стороны**. Это технически отличается от генеративного Image-to-Texture: оригинальные пиксели SKU становятся жёстким observation layer, а AI отвечает только за невидимые поверхности и seam repair. Архитектурно именно в эту сторону уже движется SUPRA-Tex — фиксированные surface observations плюс generative completion. citeturn618708search6

## Итоговый выбор

Если нужно выбрать **один вариант сегодня для коммерческого прототипа RemLab**, я выбрал бы **MV-Adapter SDXL Image-to-Texture**.

Если нужны **PBR maps сразу**, я бы параллельно тестировал **MVPainter**; он может оказаться более удобным production pipeline именно для Three.js/каталога мебели. citeturn109857search8turn147150search0

Если вопрос звучит **«какая технология сегодня наиболее убедительно сохраняет конкретный SKU?»**, ответ другой: **SUPRA-Tex**. Он специально построен вокруг surface-aligned observations и уже имеет controlled same-geometry comparison против Pixal3D. Но его Qwen material frontend в текущем виде исключает его из коммерческого UK production без отдельной лицензии. citeturn717472search2turn463177search0

**Pixal3D** я бы не исключал: его MIT-license и pixel-aligned conditioning очень привлекательны, но сначала надо доказать, что его Texture stage можно использовать как чистый re-texturer готового TRELLIS.2 mesh без изменения геометрии. citeturn997378search4turn193031view1

**Paint3D и MVPaint уже не выглядят стратегическими ставками**: они полезны как baseline, но существенно более новые MV-Adapter, MVPainter, UniTEX, LumiTex, UltraTex и SUPRA-Tex показывают, насколько быстро рынок ушёл вперёд. citeturn511166view0turn717472search7turn717472search3turn618708search2

Практический shortlist RemLab на ноябрь 2026: **MV-Adapter → MVPainter → Pixal3D Texture → SUPRA-Tex benchmark**, а следующий инженерный шаг — проверить их **на одном и том же замороженном TRELLIS.2 GLB с мебельными SKU**, а не доверять общим FID/CLIP рейтингам.