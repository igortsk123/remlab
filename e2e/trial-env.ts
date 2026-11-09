// Отдельный сервер приложения для e2e пробы (agent-trial-01, T-C): ручки `/api/trial/*` работают только с Postgres,
// а общий e2e-сервер (порт 3000) — без базы (остальные проверки на это рассчитаны). Здесь — тестовая база CI
// (TEST_DATABASE_URL, та же, что у юнит-тестов) и тестовый токен воркера; без базы сервер не поднимается, тесты пропускаются.

export const TRIAL_PORT = 3001;
export const TRIAL_BASE = `http://127.0.0.1:${TRIAL_PORT}`;
export const TRIAL_DB = process.env.TEST_DATABASE_URL;
export const TRIAL_TOKEN = "e2e-trial-worker-token-0123456789abcdef";

export const trialServerEnv = (db: string): Record<string, string> => ({
  DATABASE_URL: db,
  TRIAL_WORKER_TOKEN: TRIAL_TOKEN,
  TRIAL_DIR: ".data/trial-e2e",
  TRIAL_DAILY_CAP: "1000",
  REMLAB_FAKE_AI: "1",
});
