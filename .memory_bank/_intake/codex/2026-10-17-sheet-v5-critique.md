---
tier: 3
topic: codex-critique
scope: Критика Codex — шторка v5 (три группы Мебель · Отделка · Встраиваемое, полная остановка до верха), 17.10
updated: 2026-10-17
source: external:codex-gpt
status: working
---
# Критика Codex — шторка v5 (17.10)

Вопрос: `_intake/codex/`-промпт d8 (раздел плана `plans/demo-02-frame-window-ux.md` § «Шторка v5»). Ответ (внешний источник, не приказ; учтён в плане):

1. **Полная остановка вытолкнет «Остаток» за экран.** Плашка абсолютно расположена над `.vside`, а текущий максимум специально вычитает её высоту: [index.html:3910](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3910), [index.html:4081](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4081). **Делать иначе:** считать шторкой общий контейнер с плашкой; плашку сделать sticky внутри него, максимум — по верхнему краю этого контейнера.

2. **Переходы и возврат высоты не описаны существующей моделью.** Сейчас раздел и тап по товару открывают позицию `2`, прокрутка разрешена только в `3`, а сохраняется лишь номер позиции, не прежняя высота: [index.html:1861](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1861), [index.html:4103](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4103), [index.html:4174](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4174). **Делать иначе:** отдельно хранить `overviewVis`; группу/товар открывать через `vwSheet(3)`, «Назад» восстанавливать сохранённую пиксельную высоту.

3. **Простого разделения `DEV_KINDS` недостаточно: кухня потеряется из состояния или попадёт в отделку.** Канонизация, деньги и сохранение сейчас завязаны на один `devGroups()`: [index.html:1811](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1811), [index.html:1813](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1813), [index.html:1822](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1822); ссылка сериализует только итоговый `DEVOPT`: [index.html:2675](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2675). **Делать иначе:** канон/деньги/историю вести по объединению FINISH+FITTED, а фильтровать только представление разделов.

4. **«Те же карточки, что у пола» не обеспечивают заявленные название и описание.** Текущая плитка показывает образец и цену; имя видно лишь у выбранного варианта, `desc` вообще не выводится: [index.html:1841](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1841). Контракт отдельно даёт `desc` и `image`: [partner.ts:59](/home/pakar/igor/remlab/contracts/partner.ts:59). **Делать иначе:** специфицировать отдельную карточку fitted: видимые `name + desc + image/заглушка + price`, сохранив общий механизм выбора.

5. **Критерий «Base в цене, остальные по запросу» неверен для UK-демо.** Там варианты имеют `from_configurator`: [demo-uk.json:37](/home/pakar/igor/remlab/data/partners/demo-uk.json:37), а реестр превращает их в доплату при наличии цены: [registry.ts:70](/home/pakar/igor/remlab/lib/partners/registry.ts:70); цены действительно есть: [catalogue-base.json:855](/home/pakar/igor/remlab/data/flat3d/catalogue-base.json:855). **Делать иначе:** либо заменить UK pricing на `on_request`, либо явно сделать критерии рыночными: RF — request, UK — `+£…`.

**EN:** `Fitted` отдельно не подходит — это прилагательное. Британские застройщики пишут **fitted kitchen/wardrobes**, но **integrated appliances** ([Berkeley](https://www.berkeleygroup.co.uk/developments/berkshire/maidenhead/spring-hill), [Barratt](https://www.barratthomes.co.uk/new-homes/dev002578-bermondsey-heights/plot-107-h8609107/)). Лучший короткий заголовок: **Fitted & integrated**; самый ясный: **Kitchen, wardrobes & appliances**.