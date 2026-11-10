// «Размеры своими словами» — приём текста агента (план agent-trial-08, Р2-текст; `db/init/025-trial-listing-text.sql`). Всё под блокировкой
// строки задания (`for update`), как «Обустроить» (`repo-rebuild.ts`): ключ → повтор `request_id` (та же строка, без второй работы) →
// есть первая версия данных (v1; задание может ещё идти — тогда «принято, применим после сборки») → исходный лист на месте →
// активная пересборка: ждущий ТЕКСТ заменяем новым (не склеиваем, новой работы нет), любая другая — `busy` → суточный лимит Р1 → вставка.
// Точную версию данных НЕ сверяем: штатный переход v1→v3 до `done` — не отказ; поколение сверяет claim/публикация воркера.
// Текст не попадает ни в журнал, ни в ответ, ни в статус.

import { sql } from "drizzle-orm";
import type { TrialListingIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { trialRebuildDaily } from "@/lib/trial/config";
import { editKeyMatches } from "@/lib/trial/edit-key";
import { q } from "@/lib/trial/repo-rebuild";

export type ListingAsk =
  | { ok: true; repeated: boolean; replaced: boolean; listing: { id: string; status: string } }
  | { ok: false; status: number; error: string };

type JobRow = { status: string; edit_key_hash: string | null; bundle_version: number; past_term: boolean; has_source: boolean };
const no = (status: number, error: string): ListingAsk => ({ ok: false, status, error });
// управляющие символы (кроме перевода строки и табуляции) — пробелом: NUL Postgres не примет, остальное — мусор для разбора
const clean = (t: string): string => t.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, " ");

export async function askListing(id: string, inp: TrialListingIn, env = process.env): Promise<ListingAsk> {
  const text = clean(inp.text);
  return db().transaction(async (tx) => {
    const [job] = await q<JobRow>(tx, sql`select status, edit_key_hash, bundle_version, input_path is not null as has_source,
        coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${id} for update`);
    if (!job) return no(404, "not_found");
    if (job.status === "expired" || job.past_term) return no(410, "expired");
    if (!editKeyMatches(inp.k, job.edit_key_hash)) return no(403, "forbidden");
    const [same] = await q<{ id: string; status: string }>(tx, sql`select id, status from trial_rebuilds
        where job_id = ${id} and request_id = ${inp.request_id}`);
    if (same) return { ok: true, repeated: true, replaced: false, listing: same };
    // нужен результат чтения: опубликованная версия данных (v1, задание может ещё идти) или готовый результат (`done`)
    if (job.status !== "done" && (job.status !== "running" || job.bundle_version < 1)) return no(409, "not_ready");
    if (!job.has_source) return no(409, "source_gone");
    const [active] = await q<{ id: string; kind: string; status: string }>(tx, sql`select id, kind, status from trial_rebuilds
        where job_id = ${id} and status in ('queued', 'running')`);
    if (active?.kind === "listing" && active.status === "queued") {
      await tx.execute(sql`update trial_rebuilds set listing_text = ${text}, request_id = ${inp.request_id} where id = ${active.id}`);
      return { ok: true, repeated: false, replaced: true, listing: { id: active.id, status: "queued" } };
    }
    if (active) return no(409, "busy");
    const [day] = await q<{ n: number }>(tx, sql`select count(*)::int as n from trial_rebuilds
        where job_id = ${id} and kind <> 'edit' and created_at > now() - interval '24 hours'`);  // правки — свой счёт
    if ((day?.n ?? 0) >= trialRebuildDaily(env)) return no(429, "rebuild_limit");
    const rid = randomToken();
    await tx.execute(sql`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, listing_text)
        values (${rid}, ${id}, ${inp.request_id}, '[]'::jsonb, ${job.bundle_version}, 'listing', ${text})`);
    return { ok: true, repeated: false, replaced: false, listing: { id: rid, status: "queued" } };
  });
}
