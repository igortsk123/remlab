// «Перечитать планировку» готового тура (план trial-reparse-01; T-20261111-02) — ставит ОПЕРАТОР скриптом `tools/floorplan/reissue.py
// --reparse` (ключ воркера), не агент. Это строка очереди `trial_rebuilds` вида `reparse` (`db/init/031-trial-reparse.sql`): воркер DEV
// перечитывает исходный лист с исходным текстом объявления (кэш VLM, 0 $), подбирает мебель заново и публикует ОДНУ версию вместе с новым
// `result` — только если сторож регресса не нашёл потерь. Постановка — под замком строки задания, как «Обустроить» (`repo-rebuild.ts`):
// повтор `request_id` → та же строка; задание готово, исходный лист на месте, нет активной пересборки (`busy`). Суточных лимитов агента
// не тратит. `base_version` переписывает claim (перевыпуск между постановкой и claim — не отказ), сверяет публикация (`stale`).

import { sql } from "drizzle-orm";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { trialDir } from "@/lib/trial/config";
import { validId } from "@/lib/trial/http";
import { q } from "@/lib/trial/repo-rebuild";
import { reissueSource, type ReissueSource } from "@/lib/trial/repo-reissue";
import { jsonOf, rows } from "@/lib/trial/sql";

export type ReparseAsk =
  | { ok: true; repeated: boolean; rebuild: { id: string; status: string } }
  | { ok: false; status: number; error: string };

type JobRow = { status: string; bundle_version: number; past_term: boolean; has_source: boolean };
const no = (status: number, error: string): ReparseAsk => ({ ok: false, status, error });

export async function askReparse(jobId: string, requestId: string): Promise<ReparseAsk> {
  if (!validId(jobId)) return no(404, "not_found");
  return db().transaction(async (tx) => {
    const [job] = await q<JobRow>(tx, sql`select status, bundle_version, input_path is not null as has_source,
        coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${jobId} for update`);
    if (!job) return no(404, "not_found");
    if (job.status === "expired" || job.past_term) return no(410, "expired");
    const [same] = await q<{ id: string; status: string }>(tx, sql`select id, status from trial_rebuilds
        where job_id = ${jobId} and request_id = ${requestId}`);
    if (same) return { ok: true, repeated: true, rebuild: same };
    if (job.status !== "done" || job.bundle_version < 1) return no(409, "not_ready");
    if (!job.has_source) return no(410, "source_gone");
    const [active] = await q<{ id: string }>(tx, sql`select id from trial_rebuilds where job_id = ${jobId} and status in ('queued', 'running')`);
    if (active) return no(409, "busy");
    const rid = randomToken();
    await tx.execute(sql`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind)
        values (${rid}, ${jobId}, ${requestId}, '[]'::jsonb, ${job.bundle_version}, 'reparse')`);
    return { ok: true, repeated: false, rebuild: { id: rid, status: "queued" } };
  });
}

export type ReparseState = { id: string; jobId: string; status: string; error: string | null; detail: string | null;
  version: number | null; baseVersion: number };

/** Исход пересборки `reparse` для оператора (ждёт его скрипт): статус, код и разбор сторожа (`error_detail` — только по ключу воркера). */
export async function reparseState(id: string): Promise<ReparseState | undefined> {
  if (!validId(id)) return undefined;
  const [r] = await rows<{ id: string; job_id: string; status: string; error_code: string | null; error_detail: string | null;
    result_version: number | null; base_version: number }>(sql`select id, job_id, status, error_code, error_detail, result_version,
    base_version from trial_rebuilds where id = ${id} and kind = 'reparse'`);
  return r ? { id: r.id, jobId: r.job_id, status: r.status, error: r.error_code, detail: r.error_detail, version: r.result_version,
    baseVersion: r.base_version } : undefined;
}

type Refused = Exclude<Awaited<ReturnType<typeof reissueSource>>, ReissueSource>;
export type ReparseSource = ReissueSource & { listingText: string; inputMime: string; hasSource: boolean; released: string[] };

/** Исходник для пробного прогона оператора (`reissue.py --reparse --dry-run`): то же, что у перевыпуска (результат, точные байты версии,
 *  правки), плюс ИСХОДНЫЙ текст объявления, вид листа и снятые агентом комнаты. Сам лист этой ручкой не отдаётся (только воркеру под арендой). */
export async function reparseSource(jobId: string, dir = trialDir()): Promise<ReparseSource | Refused> {
  const src = await reissueSource(jobId, dir);
  if (typeof src === "string") return src;
  const [j] = await rows<{ listing_text: string | null; input_mime: string; has_source: boolean; released_rooms: unknown }>(sql`select
      listing_text, input_mime, input_path is not null as has_source, released_rooms from trial_jobs where id = ${jobId}`);
  const rel = jsonOf<unknown>(j?.released_rooms ?? []);
  return { ...src, listingText: j?.listing_text ?? "", inputMime: j?.input_mime ?? "", hasSource: j?.has_source ?? false,
    released: Array.isArray(rel) ? rel.map(String) : [] };
}
