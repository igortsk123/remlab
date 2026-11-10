// Лимиты загрузки плана на пробу с одного адреса — одно место для лимитера (`lib/ratelimit/index.ts:PRESETS.trialUpload`) и
// текста формы (`lib/trial/steps.ts:uploadErrorText`): форма различает «подряд» и «на сегодня» по Retry-After ответа 429 —
// короткое окно отвечает не дольше `burst.windowSec`, суточное — до конца суток UTC (окна фиксированные). Без серверных
// зависимостей: модуль тянет клиентская форма. T-20261110-15; числа — владелец 10.11, TG 744 (T-20261110-24): 10 в час, 30 в сутки.
// Наши машины — без лимита (`lib/trial/own-key.ts`).

export const TRIAL_UPLOAD_LIMITS = {
  burst: { limit: 10, windowSec: 3600 },
  day: { limit: 30, windowSec: 86_400 },
} as const;
