// Превью чертежа агента (T-20261112-52): воркер DEV режет лист разбора по панелям (`tools/floorplan/source_preview.py`) и шлёт сюда WEBP
// (`tools/floorplan/worker.py:send_source`). Раскладка вырезов — в результате (`contracts/trial.ts`, `source.preview`).

import { z } from "zod";

/** Потолок превью (1600 px по длинной стороне, WEBP 82 — сотни КБ); = `lib/trial/storage.ts:PREVIEW_MAX_BYTES`. */
export const SOURCE_PREVIEW_MAX = 3 * 1024 * 1024;

export const trialSourceIn = z.object({
  id: z.string().min(1).max(64),
  // base64 без префикса data:
  webp: z.string().min(16).max(Math.ceil((SOURCE_PREVIEW_MAX * 4) / 3) + 4).regex(/^[A-Za-z0-9+/]+={0,2}$/),
});
export type TrialSourceIn = z.infer<typeof trialSourceIn>;
