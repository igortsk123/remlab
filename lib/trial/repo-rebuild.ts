// «Обустроить» / «Обустроить всё» — постановка пересборки (план agent-trial-08, Р1; `db/init/024-trial-rebuilds.sql`). Всё решается под
// блокировкой строки задания (`for update`): ключ → повтор `request_id` (та же строка, без второй работы) → задание готово →
// `base_version` = текущей версии данных (иначе `stale`) → нет активной → суточный лимит → комнаты действительно ждут проверки
// (по той версии, которую видит агент) → вставка. Два одновременных нажатия упираются в один замок; второе видит первое.

import { sql, type SQL } from "drizzle-orm";
import type { TrialRebuildIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { readBundle } from "@/lib/trial/bundle";
import { trialDir, trialRebuildDaily } from "@/lib/trial/config";
import { editKeyMatches } from "@/lib/trial/edit-key";

export type RebuildAsk =
  | { ok: true; repeated: boolean; rebuild: { id: string; status: string } }
  | { ok: false; status: number; error: string; version?: number };

type JobRow = { status: string; edit_key_hash: string | null; bundle_version: number; past_term: boolean };
type Tx = Parameters<Parameters<ReturnType<typeof db>["transaction"]>[0]>[0];
const no = (status: number, error: string, version?: number): RebuildAsk => ({ ok: false, status, error, ...(version !== undefined ? { version } : {}) });
const q = async <T>(tx: Tx, query: SQL): Promise<T[]> => (await tx.execute(query)) as unknown as T[];

/** Комнаты страницы, которые в версии `version` ждут проверки размера (`furniture_state: awaiting_check`). */
export async function awaitingRooms(id: string, version: number, dir = trialDir()): Promise<string[] | null> {
  const text = await readBundle(dir, id, version);
  if (text === null) return null;
  try {
    const rooms = (JSON.parse(text) as { apartment_rooms?: { id?: unknown; furniture_state?: unknown }[] }).apartment_rooms ?? [];
    return rooms.filter((r) => r.furniture_state === "awaiting_check" && typeof r.id === "string").map((r) => r.id as string);
  } catch {
    return null;
  }
}

export async function askRebuild(id: string, inp: TrialRebuildIn, dir = trialDir(), env = process.env): Promise<RebuildAsk> {
  return db().transaction(async (tx) => {
    const [job] = await q<JobRow>(tx, sql`select status, edit_key_hash, bundle_version,
        coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${id} for update`);
    if (!job) return no(404, "not_found");
    if (job.status === "expired" || job.past_term) return no(410, "expired");
    if (!editKeyMatches(inp.k, job.edit_key_hash)) return no(403, "forbidden");
    const [same] = await q<{ id: string; status: string }>(tx, sql`select id, status from trial_rebuilds
        where job_id = ${id} and request_id = ${inp.request_id}`);
    if (same) return { ok: true, repeated: true, rebuild: same };
    if (job.status !== "done") return no(409, "not_ready");
    if (job.bundle_version !== inp.base_version) return no(409, "stale", job.bundle_version);
    const [active] = await q<{ id: string }>(tx, sql`select id from trial_rebuilds where job_id = ${id} and status in ('queued', 'running')`);
    if (active) return no(409, "busy");
    const [day] = await q<{ n: number }>(tx, sql`select count(*)::int as n from trial_rebuilds
        where job_id = ${id} and created_at > now() - interval '24 hours'`);
    if ((day?.n ?? 0) >= trialRebuildDaily(env)) return no(429, "rebuild_limit");
    const waiting = await awaitingRooms(id, job.bundle_version, dir);
    if (waiting === null) return no(409, "not_ready");
    const rooms = inp.rooms === "all" ? ["*"] : [...new Set(inp.rooms)];
    if (inp.rooms === "all" ? waiting.length === 0 : rooms.some((r) => !waiting.includes(r))) {
      return no(inp.rooms === "all" ? 409 : 422, inp.rooms === "all" ? "nothing_to_furnish" : "bad_rooms");
    }
    const rid = randomToken();
    await tx.execute(sql`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version)
        values (${rid}, ${id}, ${inp.request_id}, ${JSON.stringify(rooms)}::jsonb, ${inp.base_version})`);
    return { ok: true, repeated: false, rebuild: { id: rid, status: "queued" } };
  });
}
