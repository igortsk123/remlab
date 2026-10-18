---
tier: 3
topic: codex-critique
scope: Критика Codex — план demo-16 (главная: стили → комнаты, избранное-корзина, липкая шапка), 18.10
updated: 2026-10-18
source: external:codex-gpt
status: working
---
# Критика Codex — demo-16 (18.10)

Вопрос: план demo-16 + (а) модель корзины, (б) первый экран до сгиба, (в) конфликты с demo-15. Ответ (внешний источник, не приказ; учтён в плане):

## 5 главных рисков

1. **План опирается на несуществующий источник комнат в `/api/apartments`.** В `ApartmentRef` и `ApartmentCard` комнат нет: [contracts/partner.ts:110](/home/pakar/igor/remlab/contracts/partner.ts:110), [contracts/partner.ts:175](/home/pakar/igor/remlab/contracts/partner.ts:175). Сейчас их отдельно и эвристически собирает генератор `demo-data.json`: [flat215_demo.py:930](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:930).  
   **Делать иначе:** добавить в контракт и API упорядоченные `rooms: {id, kind, ordinal, title, areaM2, contentState}[]`. Не определять комнаты из заголовков и DOM; простое добавление поля в `demo.json` без изменения Zod/API не поможет.

2. **Текущая модель — плоский список вариантов одной гостиной, а не «стиль → комнаты».** Генератор всегда берёт `flat['rooms'][0]`: [flat215_demo.py:690](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:690), `allVariants()` возвращает один плоский массив: [index.html:985](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:985), а активное состояние глобально — `cur/items`: [index.html:880](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:880). При простой перестановке вкладок состояние комнаты начнёт протекать между стилями.  
   **Делать иначе:** нормализовать данные в `styles[]`, `rooms[]`, `roomVariants[{styleId, roomId,…}]`; активный ключ — `(styleId, roomId, variantId)`. Заглушка комнаты — отдельный `contentState`, не фиктивный вариант гостиной.

3. **Demo-15 не содержит идентичности корзины и не способен обеспечить «один вариант на комнату».** Локальный `FavoriteRef` не хранит `apartmentId`, `roomId` и выбор сертификата: [index.html:5457](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5457). Поиск идёт глобально только по `stateId`: [index.html:5482](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5482). Хотя серверный контракт имеет `roomId`, снимок его не отправляет и получает дефолт `living`: [collection.ts:42](/home/pakar/igor/remlab/contracts/collection.ts:42), [index.html:5448](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5448).  
   **Делать иначе:** ввести версионированный `BasketV2`; выбор сертификата хранить отдельной картой `includedByRoom`, а не булевым флагом внутри карточки.

4. **Нынешний денежный путь даст неверный сертификат по нескольким комнатам.** `totalsOf` молча превращает неизвестную цену в ноль: [index.html:974](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:974). `devLines()` собирает опции всех комнат, а не текущей: [index.html:2173](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2173). Более того, `roomId`, разрешённый исходным контрактом, теряется в публичной карточке: [contracts/partner.ts:84](/home/pakar/igor/remlab/contracts/partner.ts:84), [registry.ts:91](/home/pakar/igor/remlab/lib/partners/registry.ts:91).  
   **Делать иначе:** оставить `settle()` чистой функцией над строками: [settlement.ts:44](/home/pakar/igor/remlab/lib/configurator/settlement.ts:44). Перед ней строить проверенный `BasketQuote` только из включённых комнат, с `roomId`, уникальным `chargeKey`, статусом цены и источником. «По запросу»/недоступно — неполный итог, не ноль.

5. **Требование «Перейти → Назад в то же состояние» конфликтует с текущей навигацией.** Страница пишет только hash через `replaceState(null,…)`: [index.html:1068](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1068), понимает лишь `#v/#c/#plan`: [index.html:1090](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1090), а история расстановки хранится только в памяти: [index.html:4071](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4071). Тост сейчас вообще текстовый: [index.html:2353](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2353).  
   **Делать иначе:** URL хранит стабильные `style`, `room`, `variant/collection`, сохраняя существующие `lang` и `s`; `history.state` — `overlay`, ракурс, положение шторки и scroll. Открытие избранного — `pushState`, изменения внутри окна — `replaceState`, `popstate` восстанавливает снимок.

## (а) Модель корзины

```ts
BasketV2 {
  schemaVersion: 2
  apartmentId: string
  favorites: Record<favoriteId, {
    favoriteId: string
    collectionId?: string
    roomId: string       // bedroom-1, bedroom-2 — разные
    roomKind: string
    styleId: string
    stateId: string
    sourceVariantId: string
    displayName: string
    createdAt: number
    shot?: string
  }>
  includedByRoom: Record<roomId, favoriteId>
}
```

Хранить под `remlab-basket:v2:<apartmentId>`: «глобально» означает между стилями, но не между квартирами. `includedByRoom` — единственный источник выбора сертификата. Первый вариант комнаты выбирается автоматически; при удалении выбранного детерминированно выбирается оставшийся старейший.

Расчёт:

- берём только `includedByRoom`;
- для каждой комнаты получаем актуальные серверные строки коллекции;
- `остаток = max(0, certificate − allowanceEligible)`;
- превышение и `developerSurcharge/propertyPriceDelta` показываем отдельно;
- комнаты без контента и без избранного дают ноль, их дефолтные опции не подмешиваются;
- превью окна заменяет комнату: `корзина без roomId + текущий draft`, а не прибавляет draft поверх уже выбранной гостиной.

## (б) Первый экран 375×667 / 390×844

Целевой бюджет до начала фото — около 260–300 px:

- 44 px: квартира · цена · ♡;
- 20–24 px: ЖК · сдача · этаж;
- 44 px: две короткие кнопки «Ипотека» / «Консультация»;
- 40–42 px: сертификат и полоса;
- максимум две строки, 38–40 px: вводный текст;
- 44–46 px: горизонтальные вкладки;
- остальное — небольшие отступы.

Сжать нужно текущие полноширинные мобильные CTA, которые сейчас складываются столбцом: [index.html:119](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:119). «Оплата 100 %» и пояснение убрать в поповер цены; длинный текст сертификата и его CTA не выводить над фото. Название комнаты лучше наложить на фото, не создавать ещё один заголовочный блок.

После прокрутки оставлять ровно две строки: 44 px квартира/цена/избранное + 44 px вкладки, суммарно до 96 px. Проверять не «карточка появилась», а видимую часть изображения:

`visiblePhotoHeight >= 120 px`.

## (в) Конфликты с demo-15

- **Имя:** заменить генератор `<Стиль> #N` на `<Комната> #N`; нумерация отдельно по `(apartmentId, roomId)`. При миграции менять только автоматически распознанные старые имена, пользовательские не переписывать.
- **Раздел:** вынести «Избранное» из `#screen-room` — сейчас оно находится внутри комнатного экрана: [index.html:771](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:771). Не добавлять избранные коллекции обратно в `allVariants`; каталог и корзина должны быть разными хранилищами.
- **Остаток:** глобальная шапка показывает корзину. Окно показывает сценарий «С этой гостиной»: заменяет выбранный вариант той же комнаты. Сердечко означает сохранение, а отдельный radio/переключатель — включение в сертификат; эти состояния нельзя связывать автоматически.