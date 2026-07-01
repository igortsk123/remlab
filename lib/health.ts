// Чистая логика health-ответа — тестируется unit-тестом (regression-net §12.1).

export type Health = {
  ok: true;
  service: "remlab";
  version: string;
  ts: string;
};

export function buildHealth(now: Date = new Date()): Health {
  return {
    ok: true,
    service: "remlab",
    version: process.env.APP_VERSION ?? "dev",
    ts: now.toISOString(),
  };
}
