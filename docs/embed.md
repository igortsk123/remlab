# Встраивание демо RemLab на сайт застройщика / Embedding the RemLab demo

## Русский

**Что получится.** На странице квартиры на вашем сайте появляется наше демо: расстановка мебели по стилям, цены,
сохранение подборки, переход в 3D (в новой вкладке) и связь с менеджером. Наша страница к вам не копируется — она
показывается рамкой с нашего сайта.

**Шаги.**
1. Пришлите нам: домены сайта, где будет демо (например `https://zhk-primer.ru`), планировки квартир, цены и
   условия сертификата, кому слать заявки (Telegram менеджеров или почту).
2. Мы заводим квартиры в реестре и разрешаем ваш домен (без этого браузер не покажет рамку на вашем сайте).
3. Вставьте на страницу квартиры:
   ```html
   <div data-remlab-partner="ВАШ_ID" data-remlab-flat="ID_КВАРТИРЫ" data-remlab-lang="ru"></div>
   <script src="https://remont-lab.online/embed.js" async></script>
   ```
   Высота рамки подстраивается сама. Метки `utm_*` из адреса вашей страницы передаются в демо.
4. (Необязательно) События для вашей аналитики:
   ```js
   document.querySelector('[data-remlab-flat]').addEventListener('remlab', e => console.log(e.detail.name));
   // open — демо открыто; 3d — переход в 3D; save — сохранена подборка; contact — нажата связь с менеджером
   ```
   Личных данных в событиях нет.

**Проверка «подключилось».** Откройте страницу: рамка видна, по нажатию «Сохранить подборку» в журнале событий
приходит `save`. Пример страницы: https://remont-lab.online/test/embed-sample/

## English

Add the two lines from step 3 to your apartment page (`data-remlab-lang="en"` for English). We must allow-list
your domain first (send it to us together with floor plans, prices and where to send leads). The frame resizes
itself; `utm_*` parameters are passed through; events `open | 3d | save | contact` are dispatched as a `remlab`
CustomEvent on the container and carry no personal data. Sample page: https://remont-lab.online/test/embed-sample/
