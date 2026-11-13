// Заказ автофото через обычную ручку фото тура (T-20261112-115 Ф2). Класс `auto` — только по Bearer воркера (`photo/route.ts:sourceOf`), и
// заказ обязан назвать свою задачу-резерв (`auto_task`): задача этой комнаты и этого варианта, открытая (reserved/shooting), её партия под
// арендой → `ordered` с номером строки фото — под замком строки задания, тем же движением, что и бронь `trial_photos`. Второй заказ той же
// задачи не пройдёт (`auto_task_busy`) — ровно один раз за деньги. Квоту людей (10 в сутки) автофото не трогает: её потолки — у очереди.
// Отказ сервиса кадров — задача failed с его кодом, номер фото снят (денег не ушло, резерв вернулся). Готово/сбой фото — задача следом.

import { sql } from "drizzle-orm";
import type { TrialPhotoIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { q, type Tx } from "@/lib/trial/repo-rebuild";

/** Номер задачи из заказа (поле `auto_task`) или null. */
export function autoTaskOf(inp: TrialPhotoIn): string | null {
  const t = (inp as Record<string, unknown>).auto_task;
  return typeof t === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(t) ? t : null;
}

/** Задача → ordered под этот заказ; false — нет такой открытой задачи (чужая комната/вариант, уже заказана, аренда закрыта). */
export async function takeAutoTask(tx: Tx, a: { jobId: string; taskId: string; roomId: string; variantId: string | null; photoId: string;
  stateId: string | null }): Promise<boolean> {
  const got = await q<{ id: string }>(tx, sql`update trial_photo_tasks t set status = 'ordered', photo_id = ${a.photoId},
      state_id = ${a.stateId}, updated_at = now()
    from trial_photo_batches b where t.id = ${a.taskId} and t.job_id = ${a.jobId} and t.room_id = ${a.roomId}
      and t.variant_id = ${a.variantId ?? ""} and t.status in ('reserved', 'shooting') and b.id = t.batch_id and b.status = 'leased'
    returning t.id`);
  return got.length > 0;
}

/** Сервис кадров заказ не принял — задача failed с его кодом, номер фото снят (резерв не в счёт потолков). */
export async function releaseAutoTask(photoId: string, code: string): Promise<void> {
  await db().execute(sql`update trial_photo_tasks set status = 'failed', fail_code = ${code.slice(0, 40)}, photo_id = null, updated_at = now()
    where photo_id = ${photoId} and status = 'ordered'`);
}

/** Сбой задания сервиса кадров, случившийся ДО платного вызова модели (`draft_render.py`: `NoProductSheet` — лист товаров не собрался,
 *  `paid_gate`; `NoCreditsError` — шлюз отказал из-за денег, HTTP 402): денег не ушло. Проба T-115/5 13.11 — обе спальни тестового тура
 *  `no_product_sheet` уже ПОСЛЕ приёма заказа (асинхронно), задача держала 10 ₽ потолка тура и не ставилась снова. */
export const NO_SPEND_CODES: ReadonlySet<string> = new Set(["no_product_sheet", "no_credits"]);

/** Фото заказа готово или сорвалось (`repo-photo-done.ts`) — задача следом; деньги ушли — `photo_id` остаётся; сорвалось до платного
 *  вызова (`NO_SPEND_CODES`) — номер фото снят, как при отказе на приёме: резерв вернулся, следующее подтверждение поставит задачу снова. */
export async function settleAutoTask(photoId: string, status: "done" | "failed", code?: string): Promise<void> {
  const failCode = status === "failed" ? (code ?? "draft_failed").slice(0, 40) : null;
  const free = failCode !== null && NO_SPEND_CODES.has(failCode);
  await db().execute(sql`update trial_photo_tasks set status = ${status}, fail_code = ${failCode},
    photo_id = ${free ? null : sql`photo_id`}, updated_at = now() where photo_id = ${photoId} and status in ('ordered', 'failed')`);
}
