// Общие настройки браузера живых проверок (T-20261018-18). Внимание: файл со своими `launchOptions` (`test.use`) ЗАМЕНЯЕТ ими
// настройки конфига целиком — такой файл добавляет `LIVE_BROWSER_ARGS` к своим аргументам сам, иначе в нём Метрика снова
// считает визиты проверок.
import { LIVE_CHECK_HEADER } from "../../lib/http/live-check";

/** Служебная метка: сервер по ней не пишет счётчики застройщика и события (`lib/http/live-check.ts`). Доходит до всех запросов
 *  страницы — fetch, sendBeacon, keepalive, рамки, воркеры, `request` (проба 18.10). Чужих доменов, кроме Метрики, демо и 3D не
 *  грузят; появится чужой fetch с CORS — метка вызовет у него предзапрос, тогда ставить её через `context.route` только своему домену. */
export const LIVE_CHECK_HEADERS = { [LIVE_CHECK_HEADER]: "1" };

/** Метрика не грузится вовсе: её домены для браузера не существуют — визиты проверок не попадают в отчёты Метрики. */
export const LIVE_BROWSER_ARGS = ["--host-resolver-rules=MAP mc.yandex.ru ~NOTFOUND, MAP mc.yandex.com ~NOTFOUND"];

/** Адрес демо для автоматики: `quiz=0` — без опроса-знакомства, прежняя главная (ADR-0330 п.5, план onb-03). Свой `quiz=` (тесты
 *  опроса — `quiz=1`) не трогается; `#фрагмент` остаётся в конце. */
export function demoUrl(path: string): string {
  const i = path.indexOf("#"), base = i < 0 ? path : path.slice(0, i), frag = i < 0 ? "" : path.slice(i);
  if (/[?&]quiz=/.test(base)) return path;
  return `${base}${base.includes("?") ? (/[?&]$/.test(base) ? "" : "&") : "?"}quiz=0${frag}`;
}
