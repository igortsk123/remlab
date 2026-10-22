Итог: диагноз верен частично. Главная причина — не отсутствие стеллажа в весах, а то, что покрытие сейчас мягкое и проигрывает гейтам/эстетике. Телефонный `cover` — отдельная вторая причина потери предмета только в превью.

## 1. Почему шкаф/стеллаж пропадает

Ваш пункт (а) неточен:

- `стеллаж` уже есть в `CAM_CORE` с весом `1`, а его запасная высота — `180`, не `80` см: [index.html:1518](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1518), [index.html:1560](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1560).
- `80` см получают только неизвестные роли. Они же получают минимальный вес `0.25`: [index.html:1520](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1520), [index.html:1747](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1747).
- Если `it.h` присутствует, он уже имеет приоритет над таблицей ролей. В фикстуре минимализма стеллаж имеет `h=102`, поэтому не считается высоким ≥120 см.

Реальные причины:

- `camSeen` означает не «целиком»: достаточно 70% ширины, видимого верха и только 25% незаслонённых пикселей: [index.html:2008](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2008).
- `camTallCut` разрешает высокому предмету быть целиком вне кадра. Запрещён только частичный срез: [index.html:1632](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1632). Оптимизатору иногда выгоднее совсем выбросить стеллаж.
- Покрытие — сумма весов плюс стены и окно, а не обязательство: [index.html:1849](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1849).
- Сначала минимизируется нарушение гейтов, и лишь потом максимизируется охват: [index.html:1870](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1870), [index.html:1882](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1882).
- C1 заранее урезается до кандидатов с максимальными `key`/`keyVis`, затем C2 — до десяти дешёвых дополнений: [index.html:1836](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1836), [index.html:1857](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1857). Это уничтожает гарантию существования лучшей пары.
- `camAtWindow` запрещает только позицию камеры в полосе 40 см от окна плюс 40 см по бокам: [index.html:1748](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1748). Шкаф он прямо не исключает, но в тесной комнате может удалить единственную полезную точку рядом с окном.
- Камера всегда зажата внутри комнаты; позиции в дверном проёме/снаружи не рассматриваются: [index.html:1782](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1782).
- Маска считает почти всю мебель непрозрачными коробками. Для открытого стеллажа это завышает заслонение: [index.html:1935](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1935), [index.html:1945](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1945).

На фикстуре 17.10 текущая пара минимализма действительно не покрывает ТВ-тумбу и стеллаж. При этом пара с текущим мягким критерием 70% существует даже для строгого C1 — её теряет отбор/ранжирование. Буквальная пара с `90% в кадре + 90% незаслонённости` там уже не нашлась.

Пункт (б) верен для окна телефона: там `object-fit:cover`, а фокус считается только по `CAM_CORE`, причём диван получает ×4 и меняется лишь горизонтальный `object-position`: [index.html:4969](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4969), [index.html:5177](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5177). Полноэкранный просмотр показывает файл целиком.

Для карточек причина другая: источник 2048×1489 имеет аспект 1.375, а карточка 3:2 — она режет главным образом верх/низ, не левый/правый край: [index.html:229](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:229).

Есть ещё расхождение: CAMFIT и маска считают 3:2, тогда как фактический кадр 2048×1489; рендер использует настоящий аспект: [index.html:1529](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1529), [index.html:5668](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5668), [viewer.ts:1430](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:1430). По горизонтали это шкаф не теряет, но вертикальные метрики и crop надо считать в 2048/1489.

## 2. Алгоритм пары

Не ставил бы покрытие раньше физических ограничений. Предлагаемый порядок:

1. Жёстко отсеять невозможные точки: столкновение, окно/штора, дверной наличник, стена перед объективом, ТВ со спины.
2. Для оставшихся камер вычислить по каждому предмету отдельно:
   - `inFrame`: доля силуэта внутри кадра;
   - `visible`: видимые пиксели / пиксели без заслонения.
3. Обязательная мебель считается покрытой, если хотя бы в одном виде `inFrame ≥ 0.90 && visible ≥ 0.90`.
4. Пару выбирать лексикографически:

```text
mandatoryMissing
mandatoryVisibilityDeficit
optionalMissing
gatePenalty
worstFrameQuality
emptyWall / foreground / floor / ceiling
-diversity
```

Шкаф, стеллаж, диван, тумба, столы и кресла должны быть обязательными. Ковёр и настольный декор — нет. Простое число предметов опасно: три стула могут «перевесить» один потерянный шкаф.

FOV нужно перебирать стадиями, а не штрафом `−0.3`, как сейчас:

1. 72° + 72°.
2. 72° + 78°.
3. 78° + 78°.
4. Точка в дверном проёме.
5. Если всё ещё невозможно — C3 либо явный отчёт о недоборе. Ослаблять сначала декор/пуф, но не шкаф.

В текущей комнате получилось 197 позиций × 16 yaw × 2 FOV = 6304 сырых кандидата. После жёстких фильтров остаётся 932–1578. Это 0.43–1.24 млн пар — дешёвый OR битовых масок. На текущей машине существующий подбор занял 114–248 мс на вариант; расчёт точной маски для всех 932 кандидатов — около 1.16 с. Для сборки это нормально, тем более вызову уже дан таймаут 300 с: [flat215_demo.py:1516](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1516).

Нормы здесь скорее практические рекомендации, не стандарт:

- 135 см — нормальная высота: Zillow рекомендует уровень груди, а для 3D-съёмки указывает 4–5 футов, то есть 122–152 см. [Zillow](https://www.zillow.com/learn/real-estate-photography-tips/), [Zillow 3D Home](https://www.zillow.com/3d-home/360-camera-guide/)
- Горизонтальный кадр, широкий объектив и отсутствие крупного предмета у объектива — также рекомендации Zillow.
- Realtor.com советует снимать из двери/угла и при необходимости из противоположных углов; для гостиной — 2–4 снимка. [Гайд Realtor.com, стр. 5](https://www.realtor.com/marketing/wp-content/uploads/2024/08/realtor.com_How-to-improve-your-photography-skills-for-real-estate-listing-photos.pdf)
- 72° ≈ 25 мм, 78° ≈ 22 мм в эквиваленте full-frame: широкий, но ещё не fish-eye.
- Общепринятой нормы «пол X%, потолок Y%» нет. Ваши пределы `floor≤35%, ceil≤30%` — разумные продуктовые эвристики, но не отраслевой стандарт: [index.html:1722](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1722).

## 3. Окно превью

Хранить crop в `v.cams[i]` разумно, например:

```json
{
  "crop_v": 1,
  "source_aspect": 1.3754,
  "crop": {
    "1.500": {"x": 0.08, "y": 0.04, "w": 0.84, "h": 0.56, "keep": ["item-0", "item-8"]},
    "1.416": {"x": 0.04, "y": 0.02, "w": 0.92, "h": 0.65},
    "0.750": {"x": 0.31, "y": 0.00, "w": 0.55, "h": 1.00}
  }
}
```

Координаты — доли исходного кадра, от левого верхнего угла. Нужны ID предметов, не роли: стульев может быть несколько. Тип сейчас crop не пропускает: [fromDemo.ts:114](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:114), [fromDemo.ts:379](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:379).

Правила crop:

- обязательная мебель внутри с запасом 3–5%;
- граница по возможности проходит между предметами, не через них;
- затем минимум `emptyRun` и пустой стены;
- главный предмет/центр массы — в центральной трети; правило третей только tie-break;
- для телефона хранить несколько аспектов или считать точный crop из сохранённых item-boxes: высота шторки и safe-area меняются.

`object-position` годится, если crop уже имеет ровно аспект контейнера. Процент надо вычислять как `x/(1-w)`, а не просто брать центр. `object-view-box` для iPhone пока непригоден: Safari его не поддерживает. [MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/object-view-box)

Для статических карточек надёжнее серверные WebP/AVIF-деривативы: точный crop, меньше загрузка и декодирование. Для интерактивного окна нужен полный 2048×1489, иначе панорамировать будет нечего.

Важно: GPT может немного сдвигать мебель. Геометрия 3D гарантирует crop исходного кадра, но не «90%» на ответе модели. Нужен запас 5–8% и проверка на уже сохранённых GPT-фото; без новых платных генераций доказать поведение будущих ответов нельзя.

Для пользовательских перестановок crop следует замораживать в записи снимка вместе с `s.cams`, а не брать только из `v.cams`: сейчас фото хранит камеры [index.html:3804](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3804), но `vwPhotoFocus` использует текущие глобальные `items`.

## 4. Пан на iPhone SE

Лучший вариант — нативный `overflow-x:auto` без `scroll-snap`:

- картинка `height:100%; width:auto; max-width:none`;
- контейнер `overflow-x:auto; overflow-y:hidden; touch-action:pan-x`;
- стартовый `scrollLeft` из сохранённого crop;
- браузер сам даёт инерцию и упор по краям. На iOS overflow-прокрутку обслуживает `UIScrollView`. [WebKit](https://trac.webkit.org/wiki/Scrolling)

`transform:translate3d` лучше `object-position`, если нужна полностью собственная физика; transform обычно остаётся на стадии композиции. Но придётся самим писать rAF, скорость, инерцию и резинку. [MDN](https://developer.mozilla.org/en-US/docs/Web/Performance/Guides/Animation_performance_and_frame_rate)

Текущий обработчик надо снять: он знает только `pointerdown/up`, не обрабатывает move/cancel и переключает вид после 50 px: [index.html:5501](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5501). Горизонтальное переключение есть ещё и в `vwZoom`: [index.html:5153](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5153). Если ракурсы только кнопками, убрать оба пути и показать кнопки также во fullscreen.

Тап во весь экран: считать тапом только движение <8 px и отсутствие изменения `scrollLeft`; после scroll/inertia подавлять click. Шторка уже слушает только собственную шапку, поэтому с фото напрямую не конфликтует: [index.html:5311](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5311). `touch-action` также требует корректно обрабатывать `pointercancel`. [MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/touch-action)

## 5. Порядок внедрения

1. Ввести `inFrame/visible`, обязательные роли и отчёт `covered/missing/reason`.
2. Переделать выбор пары без `TOPK` до проверки полного покрытия.
3. Считать crop из той же маски и фактического аспекта 2048/1489.
4. Добавить серверные превью; полный файл оставить мобильному пану.
5. Заменить свайп ракурсов нативным горизонтальным паном.
6. Добавить регрессии на угловой стеллаж, шкаф у окна и пустую C2 лофта.

Бесплатная проверка:

- ID-render/маска реальных 3D-мешей, а не только коробок;
- поверх кадра рисовать контуры предметов и crop;
- требовать для каждого обязательного item `max(C1,C2) ≥ 0.90`;
- Playwright: 320×568, 375×667, 390×844; стартовый crop, пан до обоих краёв, вертикальная шторка, тап, кнопки C1/C2;
- усилить текущий тест: сейчас он требует лишь 70% количества предметов: [demo-cams-pair.test.ts:47](/home/pakar/igor/remlab/tests/unit/demo-cams-pair.test.ts:47).

И ещё обязательная деталь: смена `CAMS_VER` инвалидирует только сохранённые позиции камер, но `stateId` камеры не включает, а готовые фото фильтруются по одному `stateId`: [index.html:2083](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2083), [index.html:4694](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4694), [index.html:5544](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5544). Нужно добавить версию/хеш камер в идентичность фото, иначе после исправления могут продолжить показываться старые плохие ракурсы.