1. **Что происходит сейчас и почему ниша недоступна**

   В 3D-окне варианта перетаскивание мышью или пальцем вращает взгляд; движение менее 8 px считается тапом. Тап по предмету выбирает предмет, по полу на компьютере запускает маршрут. Тапы в крайних 20% кадра поворачивают взгляд на 30°. Это обработано в `tools/scout/flat215-demo/index.html:11237` и `tools/scout/flat215-demo/index.html:11250`. **На телефоне ходьба тапом сейчас намеренно выключена**: сцену создают с `walk:!isTouchUI()` в `tools/scout/flat215-demo/index.html:11197`, а `walkTap` при `walk === false` прекращает обработку в `lib/viewer3d/demo-scene.ts:365`. Свайп там — осмотр, не шаг вперёд.

   Сам движок умеет больше: `goTo` ищет допустимую точку и маршрут вокруг мебели (`lib/viewer3d/viewer.ts:1051`); `followRoute` ведёт камеру по нему со скоростью 260 см/с и плавно поворачивает взгляд (`lib/viewer3d/viewer.ts:1556`). WASD/стрелки и Shift реализованы в движке (`lib/viewer3d/viewer.ts:1026`, `lib/viewer3d/viewer.ts:1530`), **но страница не передаёт эти клавиши движку**: её обработчик клавиатуры обслуживает выбор и перенос мебели (`tools/scout/flat215-demo/index.html:10225`). Курсора *назначения прогулки* на полу нет; существующий цветной след относится к переносу мебели (`lib/viewer3d/viewer.ts:1307`).

   **Главная найденная причина для ниши-пристройки — расхождение рисунка и навигации.** `annexes` уже превращаются в отдельные коробки с полом (`lib/viewer3d/rooms.ts:187`), но `buildRoom` возвращает только пол основной комнаты (`lib/viewer3d/rooms.ts:201`), и `FlatViewer` регистрирует для raycast только его (`lib/viewer3d/viewer.ts:435`). Одновременно `walkArea` проверяет только прямоугольники `apartment.rooms`, игнорируя `annexes` (`lib/viewer3d/walk.ts:87`, `lib/viewer3d/walk.ts:111`). Поэтому видимый пол закутка не становится ни целью клика, ни разрешённым местом для камеры. Дополнительно проход могут сузить отступ **28 см от стены** и **30 см от мебели** (`lib/viewer3d/walk.ts:53`, `lib/viewer3d/walk.ts:85`, `lib/viewer3d/walk.ts:117`); мебельная зона строится в `lib/viewer3d/viewer.ts:482`. Без данных конкретного тура нельзя утверждать, задевает ли двустворчатую дверь ещё и мебель, но игнорирование пристройки в этих двух местах подтверждено кодом.

2. **Какую подсказку выбрать**

   | Вариант | Польза | Ограничение |
   |---|---|---|
   | **Тонкое пульсирующее кольцо под указателем**; на тапе — краткая точка назначения | Прямо отвечает «можно встать здесь?», не загромождает интерьер. **Мой выбор** для покупателя | Нужны исправная зона ходьбы и проверка видимости пола |
   | Постоянная «призрачная» точка в доступной нише | Обнаруживается и без наведения, особенно на телефоне | Постоянный маркер может выглядеть как часть интерьера; нужна привязка к достижимой точке |
   | 1–2 шеврона к проходу или мягкая подсветка проёма | Помогает заметить закуток **за углом**, когда его пол ещё не виден | Шевроны не должны обещать проход, пока маршрут не проверен |
   | Курсор «нельзя» на стене/мебели | Ясный отрицательный ответ | Не показывает, *куда именно* идти; применять лишь как дополнение |

   Сравнение важно не принимать за копирование конкретной анимации. Matterport документирует **круги на полу** как точки перехода в VR, но это не подтверждение именно пульса под мышью в браузере — пульс здесь предлагаем как собственное оформление. Zillow описывает навигационные стрелки между 360°-видами; Kuula предлагает анимируемые hotspot-значки, в том числе расположенные на полу, и режим перехода по направлению клика. Это примеры понятных *сигналов перехода*, а не готовый алгоритм свободной ходьбы для нашей геометрии. IKEA Kreativ в первую очередь даёт сканировать и обставлять комнату, поэтому не стоит выдавать его за образец такой навигации. ([support.matterport.com](https://support.matterport.com/s/article/Exploring-Matterport-Spaces-in-VR?ardId=kA05d000001DX0q&language=en_US&utm_source=openai))

   Рекомендация: **сначала открыть настоящую проходимость ниши**, затем добавить кольцо. У проёма ниши можно один раз показать ненавязчивую стрелку «Пройти сюда»; после первого действия её убрать. На телефоне наведения нет: при тапе показать кольцо примерно на **180 мс до начала движения**, а при первом входе — подсказку «Коснитесь пола, чтобы пройти; проведите пальцем, чтобы осмотреться». Удержание можно использовать для предварительного просмотра точки, но не делать обязательным жестом.

3. **Готовый код для внедрения** — без новой зависимости и без телепортации камеры.

   Сначала расширить единую область ходьбы в `lib/viewer3d/walk.ts:87`. Индекс берётся от исходной пристройки, чтобы совпадать с идентификатором в `buildRoom`; уличный балкон в область квартиры не добавляется:

   ```ts
   export function walkArea(
     apartment: Apartment,
     marginCm = 28,
     obstacles: Obstacle[] = [],
     bodyCm = BODY_CM,
   ): WalkArea {
     const rooms: Room[] = apartment.rooms.flatMap((room) => [
       room,
       ...(room.annexes ?? []).flatMap((part, index): Room[] =>
         part.outdoor ? [] : [{
           ...room,
           id: `${room.id}~${index}`,
           x: room.x + part.x,
           y: room.y + part.y,
           w: part.w,
           d: part.d,
           openings: part.openings,
           annexes: undefined,
         }],
       ),
     ]);

     return {
       rooms,
       passages: passages({ ...apartment, rooms }),
       marginCm,
       obstacles,
       bodyCm,
     };
   }
   ```

   В `lib/viewer3d/viewer.ts:435` заменить регистрацию одного `floor` регистрацией всех полов построенной группы — основной комнаты и внутренних пристроек:

   ```ts
   const { group } = buildRoom(
     this.matCtx, room, floorMat, wallMat,
     { entranceWall, doorsClosed, ...(accent ? { accent } : {}) },
   );
   group.userData.roomId = room.id;
   group.traverse((object) => {
     if (object instanceof THREE.Mesh && object.name.startsWith("floor:")) {
       object.userData.roomId = room.id;
       this.floors.push(object);
     }
   });
   // Удалить прежние floor.userData.roomId = ... и this.floors.push(floor).
   ```

   Затем добавить в `FlatViewer` курсор. Здесь размеры Three.js — **метры**, поэтому кольцо имеет радиус 19–25,5 см; `canStand` — та же проверка, которой пользуется реальное движение. Проверка ближних пересечений не даёт рисовать его *сквозь* стену или мебель; плоские предметы вроде ковра не блокируют точку. `RingGeometry`, raycast и `polygonOffset` поддерживаются самим Three.js. ([threejs.org](https://threejs.org/docs/pages/RingGeometry.html?utm_source=openai))

   ```ts
   private walkMarker: THREE.Mesh<
     THREE.RingGeometry, THREE.MeshBasicMaterial
   > | null = null;

   hideWalkTarget(): void {
     if (this.walkMarker) this.walkMarker.visible = false;
   }

   showWalkTarget(
     clientX: number, clientY: number, rect: DOMRect,
   ): { x: number; y: number } | null {
     if (this.viewMode === "top" || !rect.width || !rect.height) {
       this.hideWalkTarget();
       return null;
     }

     const ndc = new THREE.Vector2(
       ((clientX - rect.left) / rect.width) * 2 - 1,
       -((clientY - rect.top) / rect.height) * 2 + 1,
     );
     this.raycaster.setFromCamera(ndc, this.camera);
     const floorHit = this.raycaster.intersectObjects(this.floors, false)[0];
     if (!floorHit) {
       this.hideWalkTarget();
       return null;
     }

     const point = { x: floorHit.point.x / CM, y: floorHit.point.z / CM };
     if (!canStand(this.area, point.x, point.y)) {
       this.hideWalkTarget();
       return null;
     }

     const blockers: THREE.Object3D[] = [
       ...this.roomGroups.values(),
       ...[...this.placed.values()]
         .filter((placed) => !isFlatOnSurface(placed.spec))
         .map((placed) => placed.group),
     ];
     const hidden = this.raycaster.intersectObjects(blockers, true).some(
       (hit) => hit.distance < floorHit.distance - 0.005 &&
         !this.floors.includes(hit.object as THREE.Mesh),
     );
     if (hidden) {
       this.hideWalkTarget();
       return null;
     }

     if (!this.walkMarker) {
       this.walkMarker = new THREE.Mesh(
         new THREE.RingGeometry(0.19, 0.255, 32),
         new THREE.MeshBasicMaterial({
           color: 0xc8805c,
           transparent: true,
           opacity: 0.7,
           depthTest: true,
           depthWrite: false,
           side: THREE.DoubleSide,
           polygonOffset: true,
           polygonOffsetFactor: -2,
           polygonOffsetUnits: -2,
         }),
       );
       this.walkMarker.rotation.x = -Math.PI / 2;
       this.scene.add(this.walkMarker);
     }
     this.walkMarker.position.set(
       floorHit.point.x, floorHit.point.y + 0.04, floorHit.point.z,
     );
     this.walkMarker.visible = true;
     return point;
   }
   ```

   В начале `tick` (`lib/viewer3d/viewer.ts:1525`), **до ранних `return`**, добавить пульс; в ветке `if (r.done)` (`lib/viewer3d/viewer.ts:1569`) скрывать маркер, а при `dispose` (`lib/viewer3d/viewer.ts:1972`) освобождать его геометрию и материал:

   ```ts
   if (this.walkMarker?.visible) {
     const phase = (performance.now() % 1200) / 1200 * Math.PI * 2;
     const scale = 1 + 0.08 * Math.sin(phase);
     this.walkMarker.scale.setScalar(scale);
     this.walkMarker.material.opacity = 0.65 + 0.15 * Math.sin(phase);
   }
   ```

   Подключение жестов: добавить в интерфейс и возвращаемый объект `DemoScene` метод `previewWalk(x, y)`, вызывающий `viewer.showWalkTarget(x, y, canvas.getBoundingClientRect())`, и метод скрытия через `viewer.hideWalkTarget()` (`lib/viewer3d/demo-scene.ts:123`, `lib/viewer3d/demo-scene.ts:363`). В `liveWire` (`tools/scout/flat215-demo/index.html:11239`) вызывать preview на `pointermove` **только для мыши, когда `!p0 && !VW.mv && VW.mode==='walk'`**; на начале перетаскивания и `pointerleave` скрывать. В `walkTap` после проверки попадания по предмету брать точку через `showWalkTarget`, а не через `floorPoint`: последний при промахе по мешу пересекает бесконечную плоскость (`lib/viewer3d/viewer.ts:1411`). На телефоне заменить `walk:!isTouchUI()` на `walk:true`; после валидного тапа вызвать `goTo(point.x, point.y)` с задержкой 180 мс, отменяя таймер при закрытии/смене сцены. **Не писать второй алгоритм движения:** существующий `goTo → planRoute → followRoute` уже плавно перемещает камеру и обходит мебель (`lib/viewer3d/viewer.ts:1052`, `lib/viewer3d/viewer.ts:1556`). При смене режима также скрывать маркер.

4. **Что проверить перед выпуском**

   - **Ниша:** доступны ли точки *внутри* и непрерывен ли проход через портал; при ширине менее 56 см отступы от обеих стен уже могут исключить стояние. Прогнать сценарий с мебелью у двустворчатой двери (`lib/viewer3d/walk.ts:53`, `lib/viewer3d/viewer.ts:485`).
   - **Слабые телефоны:** один меш создаётся однократно; не выполнять обход всех мешей и поиск A* на каждом кадре. Raycast делать по событиям указателя, при необходимости ограничить до ~20–30 проверок/с. Предложенный hover проверяет допустимость точки; если возможны изолированные участки, **достижимость маршрута** проверять отдельно при тапе, иначе кольцо может обещать недостижимую цель.
   - **Мерцание и перекрытие:** подъём кольца на 4 см — выше отмеченного в коде ворса ковра до 3 см; оставить `depthTest:true`, `depthWrite:false` и небольшой `polygonOffset`, не делать `depthTest:false`, как у контура выделения (`lib/viewer3d/viewer.ts:1318`, `lib/viewer3d/viewer.ts:1438`).
   - **Приоритет действий:** перенос мебели и вращение взгляда отменяют preview; выбор мебели обрабатывается раньше навигации (`tools/scout/flat215-demo/index.html:11241`, `lib/viewer3d/demo-scene.ts:365`). Для будущего действия «нажать окно → подойти к окну» дать кликабельному окну приоритет над полом и отдельную ближайшую допустимую цель: сейчас подтверждённого обработчика такого клика в этой 3D-сцене я не нашёл.

Папка read-only: это интеграционный код и указания, **файлы не изменены и тесты не запускались**.