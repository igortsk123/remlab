// Контракт пробы для агентов UK (план agent-trial-01-upload-grey-tour, T-A): статусы задания, вид для страницы
// `/try/<id>`, результат стенда `floorplanResult` и тела ручек воркера DEV. Один и тот же JSON результата проверяет
// прод (`safeParse` при приёме) и тест Python стенда (выгрузка `z.toJSONSchema` → `tests/fixtures/trial-result.schema.json`).
// Координаты результата — сантиметры, x вправо, y вниз по листу (= «вглубь» сцены, как `lib/viewer3d/rooms.ts`).

import { z } from "zod";

export const trialStatus = z.enum(["queued", "running", "done", "failed", "cancelled", "expired"]);
export const trialStage = z.enum(["queued", "raster", "labels", "walls", "repair", "export", "done"]);
/** Коды ошибок, которые видит страница (закрытый список; подробности — только в `error_detail` базы). */
export const trialErrorCode = z.enum([
  "pdf_unreadable", "unsupported", "too_large", "no_plan", "budget", "vlm_error", "pipeline_error", "timeout",
  "lease_lost", "stale", "internal",
]);
/** Коды, которые может прислать воркер: публичные + «вернуть задание, DEV занят» (попытку не тратит). */
export const trialFailCode = z.enum([...trialErrorCode.options, "waiting_capacity"]);

export type TrialStatus = z.infer<typeof trialStatus>;
export type TrialStage = z.infer<typeof trialStage>;
export type TrialErrorCode = z.infer<typeof trialErrorCode>;

/** Что видит страница. Ни пути файла, ни текста объявления, ни аренды, ни воркера, ни деталей ошибки. */
export const trialJobView = z.object({
  id: z.string(),
  status: trialStatus,
  stage: trialStage,
  stages: z.array(z.object({ stage: trialStage, at: z.string() })),
  createdAt: z.string(),
  finishedAt: z.string().nullable(),
  elapsedSec: z.number().int().nonnegative(),
  /** Сколько заданий заберут раньше этого (то же условие и порядок, что у claim); null — не в очереди. */
  queueAhead: z.number().int().nonnegative().nullable(),
  workerAlive: z.boolean(),
  errorCode: trialErrorCode.nullable(),
  resultVersion: z.number().int().nonnegative(),
});
export type TrialJobView = z.infer<typeof trialJobView>;

const num = z.number().finite();
const pt = z.tuple([num, num]);
const ring = z.array(pt).min(3).max(4000);
const flags = z.array(z.string().max(60)).max(30);

const room = z.object({
  id: z.string().min(1).max(40),
  name: z.string().max(80),
  kind: z.enum(["living", "bedroom", "kitchen", "bathroom", "hall", "other"]),
  contour: ring,
  bbox: z.object({ x: num, y: num, w: num.positive(), d: num.positive() }),
  areaM2: num.nonnegative(),
  dims: z.object({ w: num.positive(), d: num.positive(), src: z.enum(["plan", "listing"]) }).optional(),
  flags,
}).refine((r) => {
  // bbox — проекция контура (как `contracts/apartment.ts:room`): T5 возьмёт комнату без пересчёта
  const xs = r.contour.map((p) => p[0]), ys = r.contour.map((p) => p[1]);
  return Math.abs(Math.min(...xs) - r.bbox.x) < 1 && Math.abs(Math.min(...ys) - r.bbox.y) < 1 &&
    Math.abs(Math.max(...xs) - (r.bbox.x + r.bbox.w)) < 1 && Math.abs(Math.max(...ys) - (r.bbox.y + r.bbox.d)) < 1;
}, { message: "bbox must be the projection of contour" });

const panel = z.object({
  id: z.string().min(1).max(40),
  title: z.string().max(120),
  rooms: z.array(room).max(80),
  walls: z.array(z.object({ z0: num, z1: num, polys: z.array(z.object({ outer: ring, holes: z.array(ring).max(200) })).max(400) })).max(20),
  openings: z.array(z.object({ kind: z.enum(["door", "window", "opening"]), c: pt, widthCm: num.positive(), exterior: z.boolean() })).max(400),
});

export const floorplanResult = z.object({
  version: z.literal(1),
  units: z.literal("cm"),
  source: z.object({
    mime: z.enum(["image/jpeg", "image/png", "image/webp", "application/pdf"]),
    pages: z.number().int().min(1),
    usedPages: z.number().int().min(1),
    imageW: z.number().int().positive(),
    imageH: z.number().int().positive(),
  }),
  scale: z.object({
    status: z.enum(["verified", "listing", "not_verified"]),
    ppm: num.positive().nullable(),
    inliers: z.number().int().nonnegative(),
    n: z.number().int().nonnegative(),
  }),
  panels: z.array(panel).min(1).max(4),
  flags,
  timings: z.record(z.string().max(40), num.nonnegative()),
  costUsd: num.nonnegative(),
});
export type FloorplanResult = z.infer<typeof floorplanResult>;

// ── Тела ручек воркера DEV (Bearer TRIAL_WORKER_TOKEN) ─────────────────────────────────────────────
const workerId = z.string().regex(/^[A-Za-z0-9_.:-]{1,64}$/);
const lease = { id: z.string(), attempt: z.number().int().positive(), leaseToken: z.string().min(16).max(64) };
const spent = z.number().nonnegative().max(100).optional();

export const trialClaimIn = z.object({
  workerId,
  version: z.string().max(64).optional(),
  /** true — воркер сам себя притормозил: только отметиться «жив», задание не брать. */
  paused: z.boolean().optional(),
});
export const trialHeartbeatIn = z.object({ ...lease, stage: trialStage, spentUsd: spent });
export const trialResultIn = z.object({ ...lease, result: z.unknown(), spentUsd: spent });
export const trialFailIn = z.object({
  ...lease, code: trialFailCode, retryable: z.boolean(), detail: z.string().max(2000).optional(), spentUsd: spent,
  /** Через сколько секунд снова отдавать задание (для `retryable`); по умолчанию 30. */
  retryAfterSec: z.number().int().min(1).max(3600).optional(),
});
export type TrialHeartbeatIn = z.infer<typeof trialHeartbeatIn>;
export type TrialFailIn = z.infer<typeof trialFailIn>;

/** Что получает воркер при claim. */
export type TrialClaimed = {
  id: string; kind: string; attempt: number; leaseToken: string; leaseUntil: string;
  inputMime: string; inputBytes: number; inputHash: string | null; listingText: string | null; budgetUsd: number;
};
