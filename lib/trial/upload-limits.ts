// Лимиты загрузки плана на пробу с одного адреса — одно место для лимитера (`lib/ratelimit/index.ts:PRESETS.trialUpload`) и
// текста формы (`lib/trial/steps.ts:uploadErrorText`): форма различает «подряд» и «на сегодня» по Retry-After ответа 429 —
// короткое окно отвечает не дольше `burst.windowSec`, суточное — до конца суток UTC (окна фиксированные). Без серверных
// зависимостей: модуль тянет клиентская форма. T-20261110-15.

export const TRIAL_UPLOAD_LIMITS = {
  burst: { limit: 3, windowSec: 600 },
  day: { limit: 10, windowSec: 86_400 },
} as const;
