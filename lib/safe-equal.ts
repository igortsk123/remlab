// Сравнение секретов за постоянное время: обычное `===` выдаёт длину совпавшего префикса по времени.

import { timingSafeEqual } from "node:crypto";

export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}
