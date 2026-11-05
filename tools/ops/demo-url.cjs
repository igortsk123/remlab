// Адрес демо для скриптов-обходов: `quiz=0` — без опроса-знакомства, прежняя главная (ADR-0330 п.5, план onb-03). Свой `quiz=`
// не трогается, `#фрагмент` остаётся в конце. Та же функция для живых проверок — `e2e/live/browser.ts:demoUrl` (сверяет
// `tests/unit/demo-url.test.ts`).
exports.demoUrl = function demoUrl(path) {
  const i = path.indexOf("#"), base = i < 0 ? path : path.slice(0, i), frag = i < 0 ? "" : path.slice(i);
  if (/[?&]quiz=/.test(base)) return path;
  return base + (base.includes("?") ? (/[?&]$/.test(base) ? "" : "&") : "?") + "quiz=0" + frag;
};
