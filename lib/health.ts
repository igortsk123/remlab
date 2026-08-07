// Чистая логика health-ответа — тестируется unit-тестом (regression-net §12.1).

import { traceWriteFailures } from "@/lib/trace/failures";

export type Health = {
  ok: true;
  service: "remlab";
  version: string;
  ts: string;
  traceWriteFailures: number;
};

export function buildHealth(now: Date = new Date()): Health {
  return {
    ok: true,
    service: "remlab",
    version: process.env.APP_VERSION ?? "dev",
    ts: now.toISOString(),
    traceWriteFailures: traceWriteFailures(),
  };
}
