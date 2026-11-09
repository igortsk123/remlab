---
source: external:web (обзор фонового помощника ведущего common, 09.11.2026; первоисточники — ссылки ниже)
topic: floorplan-ready-solutions
updated: 2026-11-09
---
# Готовые решения «картинка плана → стены/комнаты → 3D» — обзор 09.11.2026 (по слову владельца TG 223–225)

Итог: готового сервиса, чью геометрию можно свободно встроить в продукт по открытой цене, нет. Ближе всех Sketch2Space (формат ответа)
и Planner 5D (самый зрелый); оба для встраивания — только письменным договором. РФ ни у кого не подтверждена. Открытых моделей с
коммерческими весами нет (всё упирается в лицензии данных). Цифры точности/скорости — заявления компаний, не замеры.

## Коммерческие
| Решение | Тип | Выход | Цена | Права на результат | UK/РФ | Проба | Вердикт |
|---|---|---|---|---|---|---|---|
| Sketch2Space | API на всех тарифах (https://sketch2space.com/docs/developer-api/) | JSON в метрах: стены (ось, толщина, наружная), проёмы на стене (`hostWallId`, позиция, ширина, подоконник), полигоны комнат, привязка к картинке; .DAE | вне аккаунта не видна | Terms 05.11.26 (https://sketch2space.com/terms.html): модель наша; перепродажа/«перепаковка» — по письменному договору; загрузки идут в обучение (opt-out); право Израиля | не проверено | бесплатный аккаунт, ключ в меню | №1 |
| Planner 5D | API-ключ из профиля при PRO (https://planner5d.com/reference/public-api); B2B — продажи | `POST /recognition` → `GET /projects/{hash}/document`; экспорт DXF/DWG/PDF | PRO-проба 7 дней = 3 распознавания; B2B-проба €99 = 10 планов (https://planner5d.com/business/api-integrations) | B2B-условия 20.08.26 §8.4: «технические файлы» с координатами не передаются; запрет конкурирующего продукта | Литва; санкционные территории запрещены | PRO-проба | №2 — проба да, продукт — договор |
| Polycam digitizer | UI; API — Enterprise | DWG/DXF со слоями стен/дверей/окон/комнат (https://poly.cam/tools/floor-plan-digitizer) | Free 1 план просмотр; Basic $30/мес (https://poly.cam/pricing) | Terms не прочитаны (404) | — | бесплатно без экспорта | №3 — эталон качества через DXF |
| Floor Plan API (Space Pixel) | API | маска стен + полигоны комнат в px + рамки дверей/окон; без масштаба (https://floorplanapi.com/docs) | Free 20; €99/200; €399/1000 | Terms: исходник и результат наши | — | лист ожидания | следить |
| Archilogic | сервис + Space API | GeoJSON/IFC/glTF/DXF | $329/план конверсия (https://www.archilogic.com/pricing) | конверсия руками; запрет точных замеров (Codex 14.10) | — | — | нет |
| CubiCasa | только свои сканы | — | — | РФ нет | — | — | нет |
| RoomSketcher AI Convert | UI | их редактор, DXF/API нет | 1 бесплатно | — | — | — | нет |
| RasterScan | RapidAPI/Docker | JSON | — | — | — | сайт 402, похоже свернулись | нет |
| Getfloorplan | рендеры/туры | картинки | $20–69/план | — | — | — | нет |
Без публичного API распознавания: Homestyler, Coohom/Kujiale, Magicplan, Floorplanner, Rayon, Planoplan, Remplanner. Replicate ton731 — лицензия не указана.

## Открытые модели
DeepFloorplan/TF2DeepFloorplan — GPL-3.0, данные R2V/LIFULL (академические) → нет; FloorplanToBlender3d — GPL-3.0, правила OpenCV
без весов → можно как базовую пробу на своём сервере; FloorplanTransformation, Raster-to-Graph — LIFULL → нет; HEAT — некоммерческая;
RoomFormer — облако точек, Structured3D некоммерческий; PolyRoom — без лицензии; Raster2Seq — веса CC BY-NC; xmarva — CubiCasa5K.
**Данные для своего обучения:** Swiss Dwellings v3 (https://zenodo.org/records/7788422) — CC BY 4.0, 45 тыс. квартир в векторе
(растр рисовать самим) — единственный чистый для коммерции набор.

## Пути пробы (ничего не загружено; аккаунты не создавались)
Sketch2Space — бесплатный аккаунт → ключ → `POST /projects` → `POST /projects/{id}/sketch` → `GET /projects/{id}/model` (до загрузки
отключить обучение на наших файлах). Planner 5D — PRO-проба (карта, вероятно). Polycam — 1 план бесплатно глазами; DXF с Basic $30.
Не проверено: цены Sketch2Space/Planner 5D PRO, Terms Polycam, доступ из РФ, данные обучения Sketch2Space/Floor Plan API, точность на наших планах.
