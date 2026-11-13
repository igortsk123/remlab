// ЗАПРЕТ МАСШТАБА СТРАНИЦЫ НА ТЕЛЕФОНЕ (T-20261113-15, П1.58; владелец TG 1466–1479: «запретить менять масштаб — на телефоне —
// везде»; страницу случайно увеличили щипком в окне комнаты, и вернуть было нельзя). Отменяет «зум разрешён» аудита 01.09 (Б1).
// ОДНО ПРАВИЛО НА ВСЕ СТРАНИЦЫ: сайт (`app/layout.tsx`), заглушки тура (`lib/trial/tour-stub.ts`) берут его отсюда; статическая
// витрина /demo и туры (`tools/scout/flat215-demo/index.html`, туры — её копия) несут тот же блок между метками `no-zoom:start/end`,
// сверка побайтно — `tests/unit/no-zoom.test.ts` (правишь здесь — перенеси вывод `noZoomHead("viewport-fit=cover")` в
// index.html; расхождение тест покажет строкой).
// Три слоя, потому что ни один браузер не слушается всего:
//  1. viewport `maximum-scale=1, user-scalable=no` — Android Chrome и прочие (кроме режима доступности «принудительный зум»);
//  2. iOS Safari (с iOS 10 viewport игнорирует): `gesturestart/gesturechange` → preventDefault, и двухпальцевый `touchmove`
//     с `scale ≠ 1` → preventDefault. Свои жесты (щипок 3D-камеры, зум фото `#vzoom`) идут pointer-событиями и `touch-action:none`
//     — их это не трогает;
//  3. двойной тап — `touch-action: manipulation` у корня: прокрутка и клики как были, увеличения по двойному тапу нет.
// Поля ввода не увеличивают страницу при фокусе: iOS увеличивает при шрифте < 16 px — на сенсорном экране поле не мельче 16 px.

export const NO_ZOOM_VIEWPORT = "width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no";

export const NO_ZOOM_CSS =
  "html{touch-action:manipulation;-webkit-text-size-adjust:100%;text-size-adjust:100%}" +
  "@media (pointer:coarse){input,textarea,select{font-size:max(16px,1em)!important}}";

export const NO_ZOOM_JS =
  "(function(){if(window.__noZoom)return;window.__noZoom=1;var d=document,o={passive:false},s=function(e){e.preventDefault();};" +
  "['gesturestart','gesturechange','gestureend'].forEach(function(t){d.addEventListener(t,s,o);});" +
  "d.addEventListener('touchmove',function(e){if(e.touches&&e.touches.length>1||typeof e.scale==='number'&&e.scale!==1)e.preventDefault();},o);})();";

/** Блок для статических страниц (витрина /demo, туры, заглушки): `<meta viewport>` + стиль + скрипт, метки для сверки. Каждый
 *  тег — с начала строки: сборщик витрины (`tools/scout/page_build.mjs`, тест `page-build.test.ts`) считает блоки по началу строки. */
export function noZoomHead(extraViewport = ""): string {
  return [
    "<!-- no-zoom:start (lib/page/no-zoom.ts) -->",
    `<meta name="viewport" content="${NO_ZOOM_VIEWPORT}${extraViewport ? `,${extraViewport}` : ""}">`,
    `<style>${NO_ZOOM_CSS}</style>`,
    `<script>${NO_ZOOM_JS}</script>`,
    "<!-- no-zoom:end -->",
  ].join("\n");
}
