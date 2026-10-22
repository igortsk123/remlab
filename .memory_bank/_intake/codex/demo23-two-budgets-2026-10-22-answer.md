Короткий вывод: идея двух бюджетов верная, сегментированная одна полоса — лучший компромисс. Но `fitout = 0` не эквивалентно «опции вне пакета», а `settlement` нельзя превращать в признак мебель/отделка. Нужны две независимые оси: куда выставляется счёт и из какого бюджета он покрывается.

## 1. Проверка рыночных цифр

### UK

- £250 тыс. — уже заниженный ориентир для «среднего жилья»: официальная средняя цена по UK в августе 2026 года — £273 тыс.; для Англии — £294 тыс. Данные по новостройкам особенно шумные из-за малого числа сделок. [ONS, October 2026](https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/privaterentandhousepricesuk/october2026)
- 5% — не единый размер рыночного пакета, а распространённый ипотечный предел. Например, Nationwide принимает совокупные финансовые incentives не более 5% цены/оценки; UK Finance требует раскрывать incentives кредитору. [Nationwide](https://www.nationwide-intermediary.co.uk/lending-criteria/new-build), [UK Finance](https://lendershandbook.ukfinance.org.uk/disclosure-form)
- Состав назван верно: deposit/cashback, vouchers, part exchange, stamp duty/legal fees, white goods, fitted/free-standing furniture, upgrades. Santander прямо разделяет эти категории; CMA подтверждает практику бесплатных kitchen upgrades и ипотечных субсидий. [Santander](https://www.santanderforintermediaries.co.uk/products/new-build-lender), [CMA](https://assets.publishing.service.gov.uk/media/65d8baed6efa83001ddcc5cd/Housebuilding_market_study_final_report.pdf)
- £12 500 = 5% от £250 тыс.; треть — £4 166,67; округление вверх до £500 действительно даёт £4 500, остаток — £8 000. Арифметика верна.
- Но деление «треть на мебель» не нашлось как рыночный стандарт. Это разумная внутренняя продуктовая политика конкретного застройщика, не «UK classic». Кроме того, fitted upgrades и отдельно стоящая мебель могут по-разному учитываться кредиторами.

Итого: 5% — хороший верхний ориентир для моделирования, но не дефолт-обещание продукта. Текущие 4% в UK-демо тоже правдоподобны: [data/partners/demo-uk.json:10](/home/pakar/igor/remlab/data/partners/demo-uk.json:10).

### РФ

- 10 млн ₽ близко к рынку: средняя стоимость проданной квартиры в российской новостройке за 2025 год — 9,32 млн ₽. [РБК/DataFlat](https://realty.rbc.ru/amp/news/69735a7f9a794737e3ebf9a9)
- 600 тыс. ₽ = 6% — арифметически верно, но данных, что 6% является типичным именно пакетом мебели/отделки, нет.
- Практика гораздо шире: встречаются 50 тыс. ₽ на мебель, 400–500 тыс. ₽ на меблировку или отделку, предложения до 800 тыс. ₽. [GloraX/Hoff 50 тыс.](https://erzrf.ru/news/article/Kvartira-s-bonusom-na-interyer-v-Oktyabrskom-daryat-sertifikaty-Hoff), [«Полис» 400–500 тыс.](https://erzrf.ru/news/gk-polis-darit-500-000-rubley-za-pokupku-kvartiry-v-zhk-polis-lavriki)
- Средний дисконт московских новостроек в 2025 году оценивался примерно в 5%, но скидка на квартиру — не то же самое, что целевой пакет на интерьер. Их нельзя смешивать в одной метрике. [РБК](https://realty.rbc.ru/news/694a739b9a7947613ede8276)

Вывод: цифры владельца годятся как продуктовые сценарии, но не как рыночные дефолты. Пакет должен полностью задаваться партнёром.

## 2. Модель данных

### Разделить две оси

Сохранить нынешний `settlement`:

- `allowance` — может покрываться incentive-пакетом;
- `developer_surcharge` — отдельная оплата застройщику;
- `property_price` — входит/добавляется в цену квартиры.

И добавить только для `allowance`:

```ts
type BudgetBucket = "furniture" | "fitout";
```

То есть строка расчёта получает `{ settlement, budgetBucket }`. Сейчас `SettlementLine` имеет только первую ось: [lib/configurator/settlement.ts:6](/home/pakar/igor/remlab/lib/configurator/settlement.ts:6).

Это важно потому, что «пол вне пакета» и «пол относится к fitout, но лимит исчерпан» — разные договорные ситуации.

### Политика пакета

Вместо плохо читаемого `pooled: boolean` советую enum:

```ts
incentive: {
  mode: "pooled" | "split";
  limits: {
    furniture: number;
    fitout: number;
  };
}
```

Публичная `ApartmentCard` должна всегда отдавать уже рассчитанные абсолютные суммы. В реестре можно дополнительно разрешить формулы: фиксированная сумма либо доля цены с правилом округления. Для британского шаблона — 5% total, мебель 1/3 с `ceil` до £500, fitout как остаток.

Политику разрешать на уровнях partner → complex → apartment, но ближайшее значение должно заменять политику целиком, без глубокого merge. Сейчас сертификат живёт только на партнёре как `certificateShare`: [contracts/partner.ts:181](/home/pakar/igor/remlab/contracts/partner.ts:181), а сумма считается здесь: [lib/partners/registry.ts:51](/home/pakar/igor/remlab/lib/partners/registry.ts:51).

Для совместимости:

- если нового `incentive` нет, преобразовать старый `certificateShare` в `mode:"pooled"`, `furniture=currentAmount`, `fitout=0`;
- оставить `certificateShare` на один переходный релиз;
- старое поведение опций продолжает определяться `settlementOf`, поэтому пол/стены не начнут внезапно расходовать пакет.

Именно поэтому тезис «вне пакета = fitout 0» неверен:

- при `mode:"pooled"` fitout с нулевым собственным лимитом всё равно может расходовать общий остаток;
- действительно внешняя опция должна иметь `developer_surcharge` либо `property_price`;
- `fitout=0` означает только нулевое покрытие в режиме `split`.

### Назначение позиции

Не использовать свободный `role`: он русскоязычный и предназначен для фото-конвейера [contracts/apartment.ts:109](/home/pakar/igor/remlab/contracts/apartment.ts:109).

Центральная чистая функция должна классифицировать по стабильной таксономии:

- shop item или `slot.kind === "furniture"` → `furniture`;
- `surface`/`builtin`, kitchen, wardrobe, bathroom, flooring, walls → `fitout`;
- appliances → `furniture`, согласно текущей договорённости;
- допустим типизированный override на уровне категории программы, но не списки SKU/названий.

Основания уже есть: `slot.kind` и `slot.category` в [contracts/apartment.ts:64](/home/pakar/igor/remlab/contracts/apartment.ts:64), `optionGroup.kind` в [contracts/partner.ts:83](/home/pakar/igor/remlab/contracts/partner.ts:83).

### Расчёт

`settle(lines, allowanceLimit)` заменить совместимым ядром, принимающим `ResolvedIncentive` и возвращающим:

```ts
package: {
  eligible: { furniture, fitout, total };
  covered:  { furniture, fitout, total };
  overage:  { furniture, fitout, total };
}
developerSurcharge;
propertyPriceDelta;
onRequest;
```

Правила:

- `pooled`: `covered.total = min(allEligible, furnitureLimit + fitoutLimit)`; остатки переносятся автоматически;
- `split`: расчёт `min(spend, limit)` отдельно для каждого бюджета; перенос запрещён;
- превышение — доплата покупателя, а не отказ включить;
- неизвестная цена остаётся `onRequest`; до её появления нельзя обещать размер покрытия;
- отрицательные суммы и перенос «в долг» запрещены.

Сейчас низкоуровневый `settle` уже считает overage, но корзина затем запрещает включение при превышении: [lib/basket/basket.ts:198](/home/pakar/igor/remlab/lib/basket/basket.ts:198). Это надо заменить на `included_with_topup` с явным подтверждением пользователя.

### Где менять

- Контракт партнёра и `ApartmentCard`: [contracts/partner.ts:181](/home/pakar/igor/remlab/contracts/partner.ts:181), [contracts/partner.ts:215](/home/pakar/igor/remlab/contracts/partner.ts:215).
- Наследование и расчёт абсолютных лимитов: [lib/partners/registry.ts:51](/home/pakar/igor/remlab/lib/partners/registry.ts:51).
- Денежное ядро: [lib/configurator/settlement.ts:16](/home/pakar/igor/remlab/lib/configurator/settlement.ts:16).
- `/flat`: добавить bucket в `ResolvedItem`/`ResolvedSurface` и `totals.byBudget`; сейчас есть только `bySettlement`: [lib/configurator/resolve.ts:59](/home/pakar/igor/remlab/lib/configurator/resolve.ts:59).
- Quote: строки сейчас теряют и settlement, и bucket при сборке: [lib/configurator/quote.ts:12](/home/pakar/igor/remlab/lib/configurator/quote.ts:12), [lib/configurator/repo.ts:13](/home/pakar/igor/remlab/lib/configurator/repo.ts:13).
- Отдельный текущий дефект: `upgradeQuote` не возвращает даже существующий `raw.bySettlement`, хотя тип его объявляет: [lib/configurator/repo.ts:29](/home/pakar/igor/remlab/lib/configurator/repo.ts:29), [lib/configurator/repo.ts:35](/home/pakar/igor/remlab/lib/configurator/repo.ts:35). Это стоит исправить до миграции.
- Корзина: добавить bucket в `quoteLine`, поднять localStorage-схему до v3; старые allowance-строки читать как furniture и затем пересчитывать по текущим данным: [lib/basket/basket.ts:19](/home/pakar/igor/remlab/lib/basket/basket.ts:19).
- Коллекции хранят выбор, а не финансовое обещание, поэтому `CollectionIn` можно не повышать только ради бюджета: [contracts/collection.ts:40](/home/pakar/igor/remlab/contracts/collection.ts:40). Но кэш `FavoriteRef.quote` требует миграции.
- Страница менеджера сейчас отправляет только `apartmentId`: [app/api/manager/sends/route.ts:12](/home/pakar/igor/remlab/app/api/manager/sends/route.ts:12). На первом этапе показывать рассчитанный пакет read-only. Если менеджер сможет менять его для конкретного клиента, обязательно сохранять snapshot в `Send`; иначе уже отправленная ссылка изменится вслед за реестром.

## 3. Одна полоса

Рекомендую:

- `pooled` — нынешняя обычная полоса;
- `split` и оба лимита больше нуля — один трек, внутри два пропорциональных сегмента, каждый заполняется независимо;
- если один лимит равен нулю — показывать обычную одночастную полосу с названием активного бюджета, а в `i`: «Мебель не входит в пакет».

Подписи:

- pooled: `Выбрано 420 000 из 600 000 ₽`;
- split без превышения: та же строка, но сегментированный трек;
- split с превышением: `Выбрано 650 000 ₽ · доплата 50 000 ₽`, справа/в `i` — пакет 600 000 ₽;
- пузырь:

  - `Мебель: 230 000 из 200 000 ₽ · доплата 30 000 ₽`;
  - `Отделка и встроенное: 370 000 из 400 000 ₽ · осталось 30 000 ₽`;
  - `Перенос между бюджетами недоступен`.

На 375 px не ставить длинные названия под сегментами: только различимые оттенки/разделитель, детали по `i`. Нельзя кодировать смысл только цветом. Для screen reader это должны быть `role="group"` и два именованных progress/meter, а не один progressbar с двумя визуальными значениями. У текущей полосы уже нет обязательного accessible name: [tools/scout/flat215-demo/index.html:1189](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1189); требование имени подтверждает [MDN](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/progressbar_role).

Альтернативы:

- две полосы — наиболее понятны, но слишком высоки для липкой области;
- маленький второй маркер — годится только для pooled/advisory split, не показывает две независимые заполненности;
- переключатель — скрывает перерасход второго бюджета;
- только стек в `i` — сохраняет чистоту, но пользователь не видит проблему до открытия;
- сегментированная полоса — единственный вариант, одновременно сохраняющий один компонент и обе границы.

Бюджетные продукты обычно дают каждой непересекающейся категории отдельный progress bar; YNAB показывает прогресс по категориям, Wallet рекомендует не пересекать бюджеты. То есть наш сегментированный трек — осознанное компактное исключение, а не распространённый стандарт. [YNAB](https://support.ynab.com/how-to-use-targets-rk5kkI9ks), [Wallet](https://support.budgetbakers.com/hc/en-us/articles/7076953735314-Setup-Budgets)

Текущую единую функцию `certScale` действительно стоит сохранить как точку рендера для главной и окна: [tools/scout/flat215-demo/index.html:1186](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1186).

## 4. Безопасный порядок внедрения

1. Новый ADR, явно уточняющий ADR-0297/0298; старые правила не удалять.
2. Добавить типы, resolver политики и классификатор bucket без изменения UI. Старые данные должны давать прежние 470 000 ₽/£11 400.
3. Расширить `settle` и unit-тесты:

   - pooled: 500/0 при лимитах 400/200 → overage 0;
   - split с теми же числами → overage 100, неиспользовано 200;
   - нулевые бюджеты;
   - точная граница и оба перерасхода;
   - UK-округление £4 500 + £8 000;
   - `on_request`;
   - `developer_surcharge`/`property_price` не расходуют пакет.

4. Обновить Quote и миграции старых quote/basket. Отдельно проверить, что сохранённая коллекция открывается, выбор не теряется, а цены и политика пересчитываются.
5. Отдать новую структуру в `ApartmentCard`; менеджеру сначала только read-only.
6. Под feature flag включить новую полосу для отдельной тестовой квартиры; текущее demo оставить старым до прохождения проверок.
7. Прогнать главную, окно варианта, избранное и `/flat` в состояниях pooled/split/zero/overage/on-request, RU/EN.
8. Снимки 375×667 и 1440×900, включая открытый `i`, крупный шрифт и экстремальное соотношение 5/95. Уже подходящие основы: [tools/ops/demo-walk/basket-check.cjs:8](/home/pakar/igor/remlab/tools/ops/demo-walk/basket-check.cjs:8) и [tools/ops/demo-walk/probe19.cjs:6](/home/pakar/igor/remlab/tools/ops/demo-walk/probe19.cjs:6).

Главная продуктовая правка к предварительному выводу: два бюджета — да; одна сегментированная полоса — да; но «вне пакета» должно оставаться явным способом расчёта, а не выводиться из нулевого лимита. Репозиторий не изменял.