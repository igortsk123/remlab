# Встраивание демо RemLab на сайт застройщика / Embedding the RemLab demo

## Русский

**Что получится.** На странице квартиры на вашем сайте появляется наше демо: расстановка мебели по стилям, цены,
сохранение подборки, переход в 3D (в новой вкладке). Наша страница к вам не копируется — она показывается рамкой
с нашего сайта. Заявку на консультацию собирает **ваш** сайт: демо сообщает вам, что покупатель нажал
«Получить консультацию» (событие `contact`), и вы открываете свою форму.

**Шаги.**
1. Пришлите нам на почту проекта: домены, где будет демо — все варианты (`https://zhk-primer.ru`,
   `https://www.zhk-primer.ru`, тестовый стенд; только https, `localhost` не поддерживается), планировки квартир
   (лучше DXF или PDF), цены и условия сертификата.
2. Мы заводим квартиры и выдаём вам `ID_ПАРТНЁРА` и `ID_КВАРТИРЫ` (наши, латиница; список — таблицей «ваша квартира →
   наш ID»), разрешаем ваши домены и пишем, что готово. Без разрешения домена браузер покажет пустую рамку.
3. Вставьте на страницу квартиры (скрипт — один раз на страницу, контейнеров может быть несколько):
   ```html
   <div data-remlab-partner="ID_ПАРТНЁРА" data-remlab-flat="ID_КВАРТИРЫ" data-remlab-lang="ru"></div>
   <script src="https://remont-lab.online/embed.js" async></script>
   ```
   `data-remlab-lang` — `ru` (по умолчанию) или `en`. Высота рамки подстраивается сама. Метки `utm_*` из адреса
   вашей страницы передаются в адрес рамки. Сайт на React/Vue добавил контейнер позже — вызовите
   `window.RemLabEmbed.scan()`.
4. События (подписывайтесь сразу после контейнера — до загрузки скрипта, тогда `open` не потеряется):
   ```js
   document.querySelectorAll('[data-remlab-flat]').forEach(el => el.addEventListener('remlab', e => {
     // e.detail.name: open — демо открыто; 3d — переход в 3D; save — сохранена подборка;
     // contact — покупатель хочет консультацию: откройте свою форму заявки
     if (e.detail.name === 'contact') openMyLeadForm(el.dataset.remlabFlat);
   }));
   ```
   В событии только `name`, личных данных нет; квартиру берите из своего контейнера (`data-remlab-flat`).

**Без скрипта** (если на сайт нельзя добавить JS) — рамка фиксированной высоты; язык — `?lang=en` в адресе:
```html
<iframe src="https://remont-lab.online/embed/ID_ПАРТНЁРА/ID_КВАРТИРЫ" style="width:100%;height:1900px;border:0" title="RemLab"></iframe>
```
Ограничения: высота не подстраивается (на телефоне будет прокрутка внутри рамки), событий нет — кнопку заявки
разместите рядом с рамкой сами, `utm_*` не передаются.

**Если на вашем сайте включена политика безопасности (CSP)** — разрешите `https://remont-lab.online` в `script-src`
(скрипт) и `frame-src` (рамка).

**Проверка «подключилось».** Откройте страницу: рамка с демо видна; с обработчиком из шага 4 в консоли браузера
(`console.log(e.detail.name)`) при открытии приходит `open`, после «Сохранить коллекцию» — `save`. Пример:
https://remont-lab.online/test/embed-sample/ (журнал событий — над рамкой).

**Что значит, если не работает.** Пустая рамка — домен не разрешён (напишите нам точный адрес страницы); «not found» в
рамке — неверный ID партнёра или квартиры; «demo unavailable» — демо обновляется, повторите через минуту.

**Данные и согласия.** Рамка не ставит рекламных куки и не подключает счётчики посещений; в хранилище браузера
(localStorage, на нашем домене) запоминаются только выбор покупателя: язык, его подборки, выбор кухни. Переход в 3D
открывает новую вкладку по нажатию — блокировщики всплывающих окон его не трогают.

## English

1. Send us your domains (all variants, https only), floor plans (DXF/PDF preferred), prices. 2. We issue your
`PARTNER_ID` and `FLAT_ID`s and allow-list your domains. 3. Paste the `<div data-remlab-partner=… data-remlab-flat=…
data-remlab-lang="en">` + `<script src="https://remont-lab.online/embed.js" async>` (one script per page, several containers
are fine; call `window.RemLabEmbed.scan()` after adding containers dynamically). 4. Listen for the `remlab` CustomEvent:
`e.detail.name` is `open | 3d | save | contact`; on `contact` open your own enquiry form (the demo does not collect
leads). No personal data in events. Without JS: `<iframe src="https://remont-lab.online/embed/PARTNER_ID/FLAT_ID?lang=en"
style="width:100%;height:1900px;border:0" title="RemLab">` — fixed height, no events. If your site has a CSP, allow
`https://remont-lab.online` in `script-src` and `frame-src`. Empty frame = domain not allowed; "not found" = wrong IDs.
The frame sets no advertising cookies; localStorage on our domain keeps only the buyer's choices.
Sample page: https://remont-lab.online/test/embed-sample/
