## Вывод

На 18 ноября 2026 года я рекомендую тест из шести систем:

1. **Hunyuan3D 2.1** — текущий контроль.
2. **Hi3D 3.0 API, `2048quality`** — главный претендент по геометрии.
3. **Meshy 7.1 API** — наиболее сбалансированный кандидат для production.
4. **Tripo H3.1 API** — сильная геометрия, быстрее и дешевле Hi3D.
5. **TRELLIS.2-4B self-hosted** — лучший практичный open-weight кандидат с полным PBR.
6. **Pixal3D self-hosted** — отдельная гипотеза на точное соответствие фотографии и multi-view.

Сначала следует сделать пилот **3 товара × 6 моделей = 18 GLB**, с жёстким потолком около `$25`, включая холодные старты. Если минимум две альтернативы выигрывают у Hunyuan одновременно по форме и цвету, расширять до 20 товаров.

Не стоит включать в первый общий рейтинг TripoSG, Hi3DGen, Direct3D-S2 и Hi3D v1.0/Sparc3D: это преимущественно geometry-only модели или рефайнеры. Они требуют отдельного painter и отвечают на другую задачу.

Файлы я не изменял.

## Что говорит внешний leaderboard

Присланные владельцем числа относятся к Rapidata/benchmark.ai. Текущий снимок от **18.11.2026** немного сдвинулся:

- Hi3D 3.0 — `1366 ±18`;
- Meshy 7.1 — `1299 ±18`;
- Tripo H3.1 — `1260 ±17`;
- Hunyuan3D 3.1 Pro — `1144`;
- TRELLIS.2 — `1003`;
- Pixal3D — `756`;
- Hunyuan3D 2.1 — `750`.

Это самый полезный из общедоступных рейтингов: 357 фиксированных single-image входов, одинаковые turntable-рендеры, 61 354 парных сравнения, 306 670 ответов, отдельные clay/geometry и textured/appearance оценки, Bradley–Terry/Elo и доверительные интервалы. [Rapidata Image-to-3D, обновлено 18.11.2026](https://www.benchmark.ai/image-to-3d).

Но для remlab он только prior:

- выборка не мебельная;
- нет ΔE, веса GLB, полигональности и web-load;
- оценка «похоже» может предпочитать красивый baked light правильному albedo;
- не проверяется held-out задняя фотография;
- не смешивает multi-view и single-view, что правильно, но не отвечает на второй сценарий remlab.

[Top3D live arena](https://www.top3d.ai/leaderboard) полезен как sanity check: сейчас там Tripo 3.1 впереди Meshy 7.1 и Hi3D 3.0. Но это непрерывно меняющийся community Elo, с разными режимами моделей, меньшими выборками и настройками вроде 4K geometry/8K texture. Решение о production-модели на нём основывать не следует.

## A. Open weights для Salad

В таблице `н/п` означает «производитель не публикует надёжное типичное число». Я сознательно не подставляю community-оценки за VRAM, время или размер файла.

Текущие сохранённые Salad batch-тарифы: RTX 3090 `$0.09/h`, RTX 4090 `$0.16/h`, то есть `$0.0015` и `$0.00267` за GPU-минуту соответственно — [submit.py](/home/pakar/igor/remlab/tools/scout/salad/submit.py:41). Холодный старт и простой обычно важнее чистого inference.

| Модель | Лицензия и вход | Текстура / геометрия | Ресурс и время | Выход, стоимость, мебельные риски |
|---|---|---|---|---|
| **Hunyuan3D 2.1**, 13.06.2025, текущий baseline | Tencent Community; single image. Коммерческое использование возможно только в Territory; лицензия прямо исключает EU, UK, South Korea и требует отдельного разрешения при >1M MAU. [Лицензия](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE) | Полный PBR; shape 3.3B + paint 2B. Официально 10 GB shape, 21 GB paint, 29 GB вместе. [README](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) | В remlab стадии разнесены, поэтому работает на 16–24 GB. Локально примерно 5–8 мин/ассет; paint около 42% задания. | Фиксированного polycount нет. Локальный storage estimate — около 4 MB на комплект, но надо пересчитать по фактической выборке. Реальная цена remlab ≈ `$0.013/mesh` — [конфиг](/home/pakar/igor/remlab/tools/scout/rules/salad-groups.json:247). Слабости уже известны: тонкие ножки/ручки, серые верха, пустой back, drift светлоты. |
| **TRELLIS.2-4B**, current main | MIT; официальный inference — single image. | Нативный full PBR: BaseColor, Roughness, Metallic, Opacity; поддерживает open surfaces, internal structures, non-manifold topology. | ≥24 GB; проверен авторами на A100/H100. H100: 3/17/60 с для 512³/1024³/1536³. На 3090/4090 требуется замер. [Официальный repo](https://github.com/microsoft/TRELLIS.2) | Polycount/MB не фиксированы; вероятен тяжёлый dense GLB. Цена — `$0.0015 × GPU-минуты` на 3090 плюс прогрев. Хорошая гипотеза на тонкие поверхности и PBR, но back всё равно галлюцинация; обязательны LOD/decimation тесты. |
| **Pixal3D main**, Trellis.2-based от 05.2026; multi-view от 09.2026 | MIT core; single и multi-image. Для multi-view нужны `transforms.json`, camera-to-world и FOV. Аудит third-party NOTICE обязателен. | Pixel-aligned lifting даёт прямое соответствие пикселей поверхности; full PBR. Это лучшая open-гипотеза на цвет фасада. [Repo, обновления 05/09.2026](https://github.com/TencentARC/Pixal3D) | Стандарт 1536, low-VRAM 1024; точные VRAM/time не опубликованы. Практически планировать 24 GB и отдельный Salad probe. | Dense GLB, poly/MB н/п. Rapidata почти на уровне Hunyuan 2.1, поэтому обещание pixel alignment пока не означает сильную общую геометрию. Shop-фото без известных камер осложняют multi-view. |
| **Step1X-3D**, weights 13.05.2025 | Apache-2.0; пользовательский вход single image. | 1.3B geometry + 3.5B texture, watertight TSDF, sharp-edge sampling, согласованная multi-view texture. Полный metallic/roughness PBR в документации не заявлен. | Официально 27–29 GB и 152 с/50 steps. [Repo](https://github.com/stepfun-ai/Step1X-3D) | Нужна 32 GB карта, например Salad 5090. При `$0.25/h` чистый inference ≈ `$0.011`, без прогрева. Полигональность и MB н/п. Интересен как запасной self-hosted textured кандидат, но архитектура и release уже заметно старее TRELLIS.2. |
| **TripoSG 1.5B**, 03.2025 | MIT; single image. Bundled RMBG можно обойти, подавая готовую remlab-вырезку. | Сильная sharp geometry, но **без штатной production-текстуры/PBR**. | ≥8 GB; время официально не закреплено. [Repo](https://github.com/VAST-AI-Research/TripoSG) | Есть параметр face limit и GLB. Дёшев на 16 GB, но нужен отдельный painter. Для общего textured рейтинга непригоден. **TripoSF** — вообще не I2-3D генератор: это VAE-реконструктор point cloud/mesh, ≥12 GB. [TripoSF](https://github.com/VAST-AI-Research/TripoSF) |
| **Direct3D-S2 v1.1.0**, 30.05.2025 | MIT; single image. v1.2 лишь анонсирован, публичного release нет. | Geometry-only OBJ, сильные high-res SDF shapes. | 512³ ≥10 GB, рекомендуемые 1024³ ≈24 GB; время н/п. [Repo](https://github.com/DreamTechAI/Direct3D-S2) | Опциональный remesh снижает triangles. Нет цвета/PBR; thin legs могут исчезнуть на remesh. Нужен отдельный painter и OBJ→GLB. |
| **Hi3DGen / Stable3DGen**, 2025 | MIT; single image, multi-image в UI всё ещё не реализован. | Normal-bridged high-detail geometry; штатной texture stage нет. | Официальные VRAM/time не указаны; feasibility на 24 GB надо проверять. [Repo](https://github.com/Stable-X/Stable3DGen) | Тяжёлая геометрия и дополнительный UV/paint этап. Полезен только как geometry arm, не как готовая замена `model.glb`. Не путать с коммерческим Hi3D 3.0. |
| **Hi3D v1.0 / Sparc3D refiner**, 23.10.2026 | Custom Hi3D Open License; commercial разрешён, но при >200k MAU или `$1M/month` нужен отдельный договор и для интеграции требуется `Powered by Hi3D 1.0`. | **Не standalone генератор**: image + coarse mesh → refined geometry 512/1024/1536; без текстуры и цвета. | 1536 проверен только на H20 96 GB; возможность на меньших GPU не установлена. [Model card](https://huggingface.co/hi3d-official/Hi3Dv1.0) | Coarse errors сохраняются, back — plausible completion. В текущем Salad-пуле реалистичен только отдельный эксперимент 512/1024, после первичного генератора. |
| **SPAR3D**, 08.01.2025 | Stability Community License: commercial бесплатно при aggregate revenue < `$1M/year`, с регистрацией/атрибуцией; выше — enterprise. Single image. | Textured UV GLB и editable point cloud; point conditioning специально улучшает back. Не заявляет такой же полный PBR набор, как TRELLIS.2. | Официально 0.7 с; 10.5 GB default, около 7 GB low-VRAM. [Stability](https://stability.ai/news-updates/stable-point-aware-3d), [repo](https://github.com/Stability-AI/stable-point-aware-3d) | Есть rough target face count/remesh. Очень дешёвый speed baseline, но ожидаемая detail/color fidelity ниже современных 4B/API моделей. |

Новые open weights Hunyuan 3.0/3.1 не опубликованы: в официальном Tencent GitHub последней полноценной I2-3D open моделью остаётся 2.1; версии 3.x доступны через API.

## B. Коммерческие API

Для API «коммерческая лицензия» — это права на output по плану и Terms, а не лицензия весов. Перед production отдельно проверяются хранение входных фото, private output, DPA и право встраивать результаты в customer-facing продукт.

| Модель | Вход и качество | Время / размер | Цена на 18.11.2026 | Риски на мебели |
|---|---|---|---|---|
| **Hi3D 3.0**, выпущен 19.08.2026 | Single или 2–4 views; полный PBR; 2048³ quality/master. [Changelog](https://docs.hi3d.ai/en/api/getting-started/changelog) | Рекомендовано 2M faces для quality, 5M для master; типичный MB не опубликован. [FAQ](https://docs.hi3d.ai/en/api/getting-started/faq) | Текущая live-таблица: quality `$0.90`, master `$2.90`. [Pricing](https://docs.hi3d.ai/en/api/getting-started/pricing) | Лидер Rapidata, но очень тяжёлый для web. Master не нужен в первом круге. Back остаётся реконструкцией, а не знанием товара. |
| **Meshy 7.1**, 18.09.2026 | Single/multi; PBR, 2K/4K/8K textures; standard/2K/4K geometry. Можно отключить `image_enhancement`, PBR включается отдельно. [API](https://docs.meshy.ai/en/api/image-to-3d), [changelog](https://docs.meshy.ai/en/api/changelog) | Raw poly н/п; remesh target 100–300k. Внешний Top3D full-quality прогон около 6.6 мин, но это не SLA. | Textured 2K/4K — 30 credits; эффективная цена `$0.60` Pro, `$0.40` Premium, `$0.375` Ultra, если месячные credits использованы полностью. Ultra geometry +5 credits. [Credits](https://help.meshy.ai/en/articles/16815622-how-many-credits-does-each-meshy-api-task-cost), [plans, 27.08.2026](https://help.meshy.ai/en/articles/12062933-which-meshy-plan-is-right-for-you-free-vs-pro-vs-premium-vs-ultra) | Нельзя включать remesh в raw arm: он может съесть ручки/ножки. `image_enhancement=false`, иначе вход уже не идентичен остальным. Paid plans дают private/commercial output. |
| **Tripo H3.1**, snapshot `v3.1-20260211` | Single/multiview, native PBR; current texture snapshot `v3.5-20260815`. | Официально ~40 с без texture, ~120 с с texture; standard до 1.5M, detailed до 2M faces; smart low-poly 500–20k. | Standard texture ¥2.10, detailed ¥2.80, 8K ¥3.50; detailed geometry ещё +¥1.40. [Документация](https://developers.tripo3d.com/en/models/v3-1) | В raw arm выключить smart-low-poly/quad. Paid outputs разрешены коммерчески, но текущие Terms требуют отдельной проверки, если сам generator фактически предоставляется third parties. API-ассеты с 01.12.2026 хранятся только 7 дней. |
| **Hunyuan3D 3.1 Pro API** | Single и до 8 именованных дополнительных видов; PBR; 3k–1.5M faces, default 500k. [API, обновлено 27.05.2026](https://intl.cloud.tencent.com/ind/document/api/1284/75540) | Время и типичный MB н/п. | Normal textured 25 credits + PBR 10. При postpaid `$0.02/credit`: `$0.70` single PBR, `$0.90` multiview PBR. Prepaid дешевле. [Billing](https://intl.cloud.tencent.com/pt/document/product/1284/75281) | Хороший второй круг: проверит, исправила ли 3.1 характерные ошибки 2.1. Но Rapidata заметно ниже тройки лидеров. |
| **Rodin Gen-2.5 / Agent-Ready**, 05–09.2026 | 1–5 images; PBR/basecolor/metallic/normal/roughness; 20k–2M target, Extreme High даёт дополнительный raw до 10M. | Geometry tiers рекламируются как 4/9/20/40/80 с плюс texture time. Typical MB н/п. | Base 0.5 credits, Extreme High +0.5, extreme-high texture +2; доллар за credit зависит от плана. [API](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5) | Default geometry mode `creative`, а experimental `faithful` сам vendor не рекомендует для production. Rapidata High = 956, поэтому второй круг. API payload/output удаляется из active systems через 7 дней и не используется для обучения — [policy, 03.08.2026](https://docs.hyper3d.ai/en/legal/data-retention-policy). |
| **Seed3D 2.0**, 23.04.2026 | Single-image object generation; coarse-to-fine geometry специально улучшает sharp edges/thin walls; unified PBR albedo + metallic/roughness. [Официальный релиз](https://seed.bytedance.com/en/seed3d_2_0) | VRAM/poly/MB/time публично не раскрыты. | API существует в Volcano Engine, но прозрачной глобальной first-party цены не найдено. | Технически релевантен для тонких деталей, но reproducibility, availability и цена слишком непрозрачны для первой партии. Rapidata = 1097. |

## Рекомендуемый shortlist и настройки

Первая партия:

| Система | Параметры первого честного прогона |
|---|---|
| Hunyuan3D 2.1 | Текущий production config, фиксированный seed; сохранить raw и current recolor как два результата. |
| Hi3D 3.0 | `2048quality`, PBR, рекомендуемые 2M faces. Не master. |
| Meshy 7.1 | Standard geometry, `should_remesh=false`, PBR, 4K texture, `image_enhancement=false`; сохранить pre-remesh/raw. |
| Tripo H3.1 | `v3.1-20260211`, standard geometry/PBR, `texture_version=v3.5-20260815`, без smart-low-poly и quad. |
| TRELLIS.2 | 1024³ feasibility, затем 1536³ для тех же pilot SKU, если помещается и укладывается в budget. |
| Pixal3D | main, 1536 single-image. Multi-view только отдельным треком. |

Rodin 2.5, Hunyuan 3.1 Pro и Seed3D 2.0 — резерв второго круга. SPAR3D можно прогнать как дешёвый speed floor, но не занимать им один из шести главных слотов.

## Протокол 20 товаров

### Выборка

- 3 дивана: простой коробчатый; ткань/капитоне; серый с плоским верхом и тонкими ножками.
- 3 стула/кресла: монолитный; шпиндельная спинка; тонкие ножки/подлокотники и сильная окклюзия.
- 3 шкафа: простой; тонкие ручки; зеркало/стекло или sliding doors.
- 3 стола: четыре обычные ножки; pedestal; hairpin/thin legs и glossy top.
- 2 лампы: абажур; тонкая стойка/несколько рожков.
- 2 кровати: простая; мягкое изголовье и видимое пространство снизу.
- 2 комода: простой; сложные ручки/ножки и плоская серая крышка.
- 2 вазы: матовая простая; стеклянная/глянцевая или с ручками.

Внутри должны присутствовать белые, серые, тёмные и насыщенные цвета; дерево, ткань, металл, стекло; минимум восемь hard cases.

### Входы

Основной single-image track использует один и тот же RGBA/crop, полученный существующим [hybrid_mask.py](/home/pakar/igor/remlab/tools/scout/salad/hybrid_mask.py:1). Это важно: текущий hybrid сохраняет 95% деталей толщиной 1–2 px против 79% BiRefNet, то есть именно ножки и ручки.

- Если API принимает alpha — отправлять этот PNG.
- Если не принимает — один и тот же заранее определённый neutral composite.
- Выключить vendor image enhancement и повторное background removal, где возможно.
- Хешировать фактический отправленный файл.
- Main photo используется для generation.
- Дополнительные product photos остаются held-out и используются для оценки side/back.

Multi-view — отдельная таблица результатов для 6–8 товаров. Нельзя смешивать её с single-image Elo. Для Pixal3D нужны реальные/оценённые extrinsics и FOV; просто назвать случайные магазинные фотографии `front/right/back` недостаточно.

### Два уровня результата

1. **Native-quality:** только orientation, axis, scale и camera alignment; без recolor, repair, retopo и decimation.
2. **Deployment-quality:** общий target, например 100k triangles, максимум 2K textures, meshopt/Draco по вашей web-цепочке.

Для цвета публикуются отдельно:

- raw generator;
- raw + одинаковая общая recolor-процедура.

Нельзя сравнивать recolored Hunyuan с raw Meshy.

### Автоматические метрики

1. **Надёжность:** success rate, timeout, retries, wall time, GPU paid time/API credits.

2. **Silhouette IoU:**
   - front IoU после оптимизации yaw/pitch/FOV/scale;
   - held-out side/back IoU;
   - среднее по всем видам и худший вид.
   
   Один front IoU опасен: billboard-подобная модель может выглядеть идеально спереди и быть пустой сзади.

3. **Цвет:** unlit BaseColor render → Lab → ΔE00 median и p90, плюс отдельно `ΔL*` и chroma error. Камеру сначала совмещать по силуэту; считать только пересечение foreground masks и отдельно опорную часть фасада. Освещённый Cycles-кадр для ΔE использовать нельзя.

   В репозитории это уже обосновано: [mesh_render.py](/home/pakar/igor/remlab/tools/scout/mesh_render.py:207) при `UNLIT=1` выводит чистый baseColor. На 191 текущей модели основная ошибка — светлота, а не hue; `|ΔL|>40` у 26% — [mesh-color.md](/home/pakar/igor/remlab/.memory_bank/core/mesh-color.md:13).

4. **Empty/back guard финального GLB:**
   - alpha occupancy каждого из 8–10 видов;
   - largest connected component;
   - backside texture coverage и entropy;
   - доля neutral gray/однотонных texels;
   - пустые UV islands.
   
   Существующий [view_guard.py](/home/pakar/igor/remlab/tools/scout/salad/view_guard.py:40) проверяет внутренние Hunyuan paint-views, а не финальный GLB, поэтому его идею надо перенести на итоговый turntable.

5. **Thin-part survival:** skeleton/medial-axis recall на маске фасада плюс заранее размеченные anchors: ножки, ручки, рожки лампы, рейки спинки.

6. **Mesh health:** triangles, vertices, components, degenerate/non-manifold/boundary edges, watertightness, flipped normals, bbox ratios после масштаба по известным размерам.

7. **PBR:** наличие и разрешение BaseColor/Normal/Roughness/Metallic/Opacity, variance карт, корректный color space, количество материалов и draw calls.

8. **Web:** raw и compressed GLB size, texture bytes, GPU texture memory, decode time, first-frame time. Типичные MB почти никто из vendors не публикует — это надо измерить, а не оценивать по рекламному voxel resolution.

### Рендеры

Для автоматики использовать текущий software renderer и unlit pass.

Для owner sheet нужен отдельный object-turntable adapter:

- yaw `0, 45, …, 315°`;
- pitch около `15°`;
- дополнительный top `+55°` и underside `−20°`;
- textured/PBR и neutral-clay pass;
- одинаковые camera/FOV, ground plane, area lights и 18% neutral world;
- Cycles GPU, 64 samples, OIDN;
- фиксированная версия Blender;
- одинаковые AgX/look/exposure для визуальной части.

Найденный [render_cycles.py](/home/pakar/igor/remlab/tools/scout/cycles_probe/render_cycles.py:132) уже задаёт Cycles и поддерживает GPU, AgX и подмену runtime GLB через `--orig` — [параметры](/home/pakar/igor/remlab/tools/scout/cycles_probe/render_cycles.py:55). Но это renderer полной комнатной сцены, а [run.sh](/home/pakar/igor/remlab/tools/scout/cycles_probe/run.sh:1) запускает один комнатный кадр. Его настройки стоит переиспользовать, но не считать готовым turntable-бенчем.

Текущий owner poster [mesh_audit_posters.py](/home/pakar/igor/remlab/tools/scout/mesh_audit_posters.py:105) показывает один software-render ракурс; для выбора генератора этого недостаточно.

### Owner sheet и итоговый score

На листе:

- слева input и held-out photos;
- далее анонимные коды A–F в случайном порядке;
- 4 крупных обязательных вида: front, ¾, back, top;
- ссылка на полный 10-view sheet и интерактивный GLB;
- отдельные оценки 0–3: форма, цвет/material, thin parts, backside, «можно использовать сейчас»;
- hard reject: empty back, missing leg/handle, gray top, collapsed silhouette, явно неверный цвет.

Сначала зафиксировать голоса, затем раскрывать названия. Парные A/B сравнения дают более устойчивый результат, чем субъективные «8 из 10».

Форма и цвет должны быть gates, а не взаимозаменяемыми баллами. После прохождения gates можно считать:

- geometry/held-out silhouette — 35%;
- color — 25%;
- completeness/back/thin parts — 15%;
- PBR — 10%;
- web weight/performance — 10%;
- cost/time — 5%.

Итоги считать парно по одним и тем же товарам, с bootstrap 95% CI, отдельно по ролям и easy/hard. Абсолютные пороги ΔE/IoU лучше зафиксировать после пилота относительно распределения Hunyuan, а не выдумывать заранее.

### Budget guard

Пилотные товары:

1. серый комод или шкаф с плоским верхом;
2. стул с тонкими ножками/рейками;
3. цветной тканевый диван.

Прямые API-затраты на 3 товара ориентировочно:

- Hi3D quality: `$2.70`;
- Meshy: `$1.13–1.80`, в зависимости от плана;
- Tripo standard texture: `¥6.30`;
- self-hosted inference — центы, но cold start может стоить больше.

Практический hard cap: `$25`. На одном hard SKU можно добавить второй seed для всех моделей. Полная партия запускается только после прохождения пилота; ориентир API-бюджета для 20 товаров — порядка `$35–50`, плюс подписки, холодные Salad-ноды и повторы.

## Изменения интеграции в `tools/scout/salad/`

### Общий слой

Сейчас worker и manifest жёстко Hunyuan-специфичны:

- POST `/generate` принимает один `image_url` — [worker.py](/home/pakar/igor/remlab/tools/scout/salad/worker.py:210);
- preprocessing уже выдаёт одинаковые shape/paint/cutout — [worker.py](/home/pakar/igor/remlab/tools/scout/salad/worker.py:232);
- production contract публикует `model.glb` — [worker.py](/home/pakar/igor/remlab/tools/scout/salad/worker.py:325);
- prefix жёстко `meshes/hunyuan21/...` — [manifest.py](/home/pakar/igor/remlab/tools/scout/salad/manifest.py:51);
- generator metadata жёстко Hunyuan — [manifest.py](/home/pakar/igor/remlab/tools/scout/salad/manifest.py:63).

Для нескольких генераторов нужен один тонкий adapter contract:

```text
generate(inputs[], params, workdir)
  -> raw_artifacts
  -> normalized self-contained model.glb
  -> timings, cost, provider_request_id, model_snapshot
```

`job_id` должен включать provider/model snapshot, параметры, seed и хеш каждого view. Manifest — хранить raw/native и normalized результаты отдельно. Любой результат валидируется через Blender/glTF parser: axes, units, bottom origin, textures, PBR channels и отсутствие внешних файлов.

Не следует собирать все open models в один Docker image: текущий образ уже содержит CUDA extensions и weights, а Salad ограничивает compressed image 35 GB — [Dockerfile](/home/pakar/igor/remlab/tools/scout/salad/Dockerfile:22).

### По кандидатам

- **TRELLIS.2:** отдельный CUDA 12.4 image, FlashAttention/O-Voxel/cuMesh extensions, baked 4B weights. Reuse `hybrid_mask`, storage, job id и output validator. Выход уже GLB, затем normalization и отдельный LOD stage.

- **Pixal3D:** отдельный image, близкий к TRELLIS.2, но со своими weights/dependencies. Для MV расширить job до `views[] + transforms.json`; хранить исходную camera convention.

- **Step1X-3D:** 32 GB Salad pool; отдельный image с geometry и SDXL texture stages. Привести GLB/material к общему contract.

- **SPAR3D/TripoSG/Direct3D-S2/Hi3DGen:** лёгкие отдельные images. Для geometry-only моделей output должен иметь `mode=geometry_only` и не публиковаться как production `model.glb`, пока не прошёл общий painter.

- **Hi3D v1.0/Sparc3D:** цепочка `coarse generator → refiner → painter`; сохранять coarse и refined. Это минимум три независимых версии в manifest и высокая integration cost.

- **Hi3D/Meshy/Tripo/Rodin/Hunyuan API:** GPU Docker не нужен. Нужен маленький CPU worker: upload/base64, submit, async poll/webhook, `429 Retry-After`, deadline, download URL до expiry, GLB validation, публикация как `model.glb`. В manifest сохранять consumed credits, provider task ID и точный snapshot.

- **Meshy:** pin `meshy-7.1`, `image_enhancement=false`, `should_remesh=false`, `target_formats=["glb"]`.

- **Tripo:** pin `v3.1-20260211` и `texture_version=v3.5-20260815`; сразу скачивать результат — с 01.12.2026 retention семь дней.

- **Hi3D:** pin `hi3dv3.0/2048quality`; контролировать 2M-face выход и отдельно делать web LOD.

## Основные риски

1. **Юридический:** лицензия текущего Hunyuan 2.1 запрещает использование не только weights, но и outputs вне Territory, исключая EU, UK и South Korea. Для международного web planner это требует немедленного legal review.

2. **API Terms:** paid-output commercial rights есть не всегда автоматически для любого способа перепродажи/предоставления сервиса. Нужна проверка Hi3D, Tripo, Rodin и Tencent договоров до production.

3. **Benchmark leakage:** leaderboard конфиги могут быть не теми, которые будут вызваны через API. Пиновать snapshots и сохранять request JSON.

4. **Color metric:** shop photo содержит свет и тени, а albedo — нет. Поэтому ΔE считать unlit, с ΔL/chroma decomposition и опорными частями, а не по lit Cycles render.

5. **Hidden surfaces:** никакая single-image модель не может восстановить реальную заднюю стенку товара; она лишь правдоподобно её дорисует. Held-out фото — единственный сильный контроль.

6. **Heavy outputs:** 2–5M faces и 8K/12K textures могут красиво выиграть owner sheet, но проиграть room planner. Native и deployment arms должны оцениваться отдельно.

7. **Multi-view cameras:** Pixal3D требует известной геометрии камер; произвольные shop angles могут ухудшить результат сильнее, чем помочь.

8. **Cold start и container size:** чистый GPU inference стоит центы, но загрузка большого image/weights и простой Salad-ноды могут доминировать.

9. **Transitive licenses:** MIT основного repo не гарантирует MIT всех background-removal, encoder и rasterizer weights. Подача уже подготовленного RGBA позволяет убрать как минимум bundled RMBG из runtime path.

## Неопределённости

- Для Pixal3D, Hi3DGen и части geometry-only моделей нет официальных стабильных VRAM/time/polycount данных на consumer RTX.
- Почти никто не публикует типичный размер GLB; voxel resolution не переводится напрямую в triangles или MB.
- Rodin публикует credits, но долларовая цена зависит от аккаунта.
- Seed3D 2.0 доступен через Volcano Engine, однако публичные global price/version guarantees непрозрачны.
- API цены и live leaderboards могут меняться; приведённые значения проверены на **18.11.2026**.
