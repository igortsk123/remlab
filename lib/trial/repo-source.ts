// Чертёж агента во вкладке тура «План квартиры» (T-20261112-52; владелец TG 855, 1000, 1002) — данные в базе: превью `<id>.src.webp`
// (кладёт воркер, `app/api/trial/worker/[id]/source/route.ts`) и исходный файл задания. Отдаёт их только агенту — `lib/trial/tour-source.ts`.

import { sql } from "drizzle-orm";
import { trialDir } from "@/lib/trial/config";
import { rows } from "@/lib/trial/sql";
import { writePreview } from "@/lib/trial/storage";

/** Что лежит у задания: превью, исходный файл (имя и тип), снят ли файл по сроку. */
export type SourceRow = { preview: string | null; input: string | null; mime: string; inputGone: boolean };

export async function sourceRow(id: string): Promise<SourceRow | undefined> {
  const [r] = await rows<{ preview_path: string | null; input_path: string | null; input_mime: string; gone: boolean }>(sql`select
      preview_path, input_path, input_mime, input_deleted_at is not null as gone from trial_jobs where id = ${id} and status <> 'expired'`);
  return r ? { preview: r.preview_path, input: r.input_path, mime: r.input_mime, inputGone: r.gone } : undefined;
}

export type PreviewSaved = { ok: true; name: string } | { ok: false; error: "not_found" | "expired" };

/** Превью от воркера: задание есть и тур жив (иначе 404/410) → файл подменой, имя — в строку. Повтор безвреден (то же имя). */
export async function savePreview(id: string, webp: Buffer, dir = trialDir()): Promise<PreviewSaved> {
  const [j] = await rows<{ status: string; alive: boolean }>(sql`select status,
      (result_expires_at is null or result_expires_at > now()) as alive from trial_jobs where id = ${id}`);
  if (!j) return { ok: false, error: "not_found" };
  if (j.status === "expired" || !j.alive) return { ok: false, error: "expired" };
  const name = await writePreview(dir, id, webp);
  // тур успел истечь между проверкой и записью — строку не трогаем; файл без строки снимет уборка сирот (`retention.ts:orphans`)
  await rows(sql`update trial_jobs set preview_path = ${name} where id = ${id} and status <> 'expired'`);
  return { ok: true, name };
}
