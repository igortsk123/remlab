// Ручки исполнителя автофото тура (T-20261112-115 Ф2; `db/init/036-trial-auto-photos.sql`): партия под аренду, отметки задач, закрытие.
// Только Bearer воркера DEV (`lib/trial/auth.ts:workerGuard`).

import { z } from "zod";
import type { PhotoCam } from "@/contracts/trial-photos";

const tok = z.string().regex(/^[A-Za-z0-9_-]{8,64}$/);
const code = z.string().regex(/^[a-z_]{1,40}$/);

export const autoClaimIn = z.object({ workerId: z.string().regex(/^[A-Za-z0-9_.:-]{1,80}$/) });
export const autoLeaseIn = z.object({ batchId: tok, leaseToken: tok });
export type AutoLease = z.infer<typeof autoLeaseIn>;

/** Отметка задачи: `shooting` — взял комнату в работу; `skipped` / `failed` — без заказа (резерв возвращается), код обязателен; `spent_rub` —
 *  факт заказа (после готовности фото), идёт в потолки вместо резерва. Переход в `ordered` делает только заказ (`/api/trial/<id>/photo`). */
export const autoTaskIn = autoLeaseIn.extend({
  taskId: tok,
  status: z.enum(["shooting", "skipped", "failed"]).optional(),
  code: code.optional(),
  spent_rub: z.number().finite().min(0).max(100).optional(),
}).refine((x) => x.status !== undefined || x.spent_rub !== undefined, { message: "status or spent_rub" })
  .refine((x) => x.status === undefined || x.status === "shooting" || x.code !== undefined, { message: "code required" });
export type AutoTaskIn = z.infer<typeof autoTaskIn>;

export const autoFinishIn = autoLeaseIn.extend({ note: z.string().max(400).optional() });
export type AutoFinishIn = z.infer<typeof autoFinishIn>;
/** Тур ещё не готов к съёмке (съёмщик: exit 3 / TOUR_READY) — вернуть партию в очередь, не сбой. */
export const autoReleaseIn = autoLeaseIn.extend({ code: code.default("tour_not_ready") });
export type AutoReleaseIn = z.infer<typeof autoReleaseIn>;

export type AutoTaskStatus = "reserved" | "shooting" | "ordered" | "done" | "failed" | "skipped";
export type AutoTaskView = { id: string; roomId: string; variantId: string; style: string; ord: number; cams: PhotoCam[]; camsSig: string;
  variantSig: string; status: AutoTaskStatus };
/** Партия исполнителю: тур открывать покупательским адресом `tourPath` с Bearer воркера; снимать только версию `bundleVersion`.
 *  `urgency`: `urgent` — сразу после подтверждения (heavy-slot `--prio 1`, ≤ 2 ядер, `--short`), `catchup` — догон, обычный приоритет. */
export type AutoBatchClaimed = { batchId: string; leaseToken: string; leaseUntil: string; attempt: number; jobId: string; bundleVersion: number;
  tourPath: string; urgency: "urgent" | "catchup"; tasks: AutoTaskView[] };
