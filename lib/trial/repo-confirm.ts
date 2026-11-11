// «Подтвердить планировку» (план trial-confirm-plan-01, пп. 3 и 5; T-20261111-16). Под блокировкой строки задания: ключ → повтор
// `request_id` (тот же ответ, и у пустого подтверждения) → задание готово → версия та, что видит страница (иначе `stale`) → никакой
// активной пересборки (иначе `busy`) и суточный лимит пересборок `edit` (`editGate`) → галочки «размеры верны» — комнаты этой версии →
// ОДНА пересборка `edit` ВСЕГДА (и без черновиков: пересчитает фото-право, неправленое берётся готовым) → черновики подтверждены под неё
// (`repo-draft.ts:confirmDrafts`) → галочки в строки правок (`dims_ok`) → ход: задетые комнаты «в очереди» и оценка времени (`rebuild-eta.ts`).

import { sql } from "drizzle-orm";
import type { TrialConfirmIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { readBundle } from "@/lib/trial/bundle";
import { trialDir } from "@/lib/trial/config";
import { editKeyMatches } from "@/lib/trial/edit-key";
import { pageRooms, roomByKey, roomsAtOpening, type PageRoom } from "@/lib/trial/plan-rooms";
import { etaOf, stageEstimate } from "@/lib/trial/rebuild-eta";
import { confirmDrafts } from "@/lib/trial/repo-draft";
import { q, type Tx } from "@/lib/trial/repo-rebuild";
import { editGate, roomNow } from "@/lib/trial/repo-room-edit";

type Counts = { rooms: number; openings: number };
export type ConfirmAsk =
  | { ok: true; repeated: boolean; rebuild: { id: string; status: string }; confirmed: Counts }
  | { ok: false; status: number; error: string; version?: number };
type JobRow = { status: string; edit_key_hash: string | null; bundle_version: number; past_term: boolean };
const no = (status: number, error: string, version?: number): ConfirmAsk => ({ ok: false, status, error, ...(version !== undefined ? { version } : {}) });
/** Галочка меняет сборку только у гостиной/спальни без права на фото в этой версии; у прочих — запоминается без пересчёта комнаты. */
const dimsMatter = (r: PageRoom): boolean => (r.kind === "living" || r.kind === "bedroom") && !r.photoOk;

export async function askConfirm(id: string, inp: TrialConfirmIn, dir = trialDir()): Promise<ConfirmAsk> {
  return db().transaction(async (tx): Promise<ConfirmAsk> => {
    const [job] = await q<JobRow>(tx, sql`select status, edit_key_hash, bundle_version,
        coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${id} for update`);
    if (!job) return no(404, "not_found");
    if (job.status === "expired" || job.past_term) return no(410, "expired");
    if (!editKeyMatches(inp.k, job.edit_key_hash)) return no(403, "forbidden");
    const [same] = await q<{ id: string; status: string; counts: Counts | null }>(tx, sql`select id, status, progress->'counts' as counts
        from trial_rebuilds where job_id = ${id} and request_id = ${inp.request_id}`);
    if (same) return { ok: true, repeated: true, rebuild: { id: same.id, status: same.status }, confirmed: same.counts ?? { rooms: 0, openings: 0 } };
    if (job.status !== "done") return no(409, "not_ready");
    if (job.bundle_version !== inp.base_version) return no(409, "stale", job.bundle_version);
    const gate = await editGate(tx, id);
    if (!gate.ok) return gate;
    if (gate.active) return no(409, "busy");                    // ждущая правка старой страницы или другое подтверждение
    const text = await readBundle(dir, id, job.bundle_version);
    let bundle: unknown = null;
    try { bundle = text === null ? null : JSON.parse(text); } catch { bundle = null; }
    if (bundle === null) return no(409, "not_ready");
    const rooms = pageRooms(bundle);
    const ok = new Set(inp.rooms_ok);
    if ([...ok].some((r) => !rooms.some((x) => x.id === r))) return no(422, "bad_rooms");
    const rid = randomToken();
    await tx.execute(sql`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind, progress)
        values (${rid}, ${id}, ${inp.request_id}, '[]'::jsonb, ${job.bundle_version}, 'edit', '{"confirm": true}'::jsonb)`);
    const counts = await confirmDrafts(tx, id, rid);
    await markDims(tx, id, rid, bundle, rooms, ok, inp.request_id);
    const touched = await touchedRooms(tx, id, rid, rooms);
    const eta = etaOf(await stageEstimate(tx, id), touched);
    const progress = { confirm: true, counts, rooms: Object.fromEntries(touched.map((r) => [r.id, "queued"])), done: 0, total: touched.length, ...eta };
    await tx.execute(sql`update trial_rebuilds set progress = ${JSON.stringify(progress)}::jsonb where id = ${rid}`);
    return { ok: true, repeated: false, rebuild: { id: rid, status: "queued" }, confirmed: counts };
  });
}

/** Галочки «размеры верны» → `dims_ok` строк правок комнат этой версии (нет строки — новая, без смены имени и размеров). Изменение,
 *  которое меняет сборку (`dimsMatter`, снятие галочки), — правка этой пересборки (`built = false`, `rebuild_id`). */
async function markDims(tx: Tx, id: string, rid: string, bundle: unknown, rooms: PageRoom[], ok: Set<string>, requestId: string): Promise<void> {
  const rows = await q<{ room_key: string; dims_ok: boolean }>(tx, sql`select room_key, dims_ok from trial_room_edits where job_id = ${id}`);
  for (const r of rooms) {
    const key = `${r.panel}|${r.srcId}`, row = rows.find((x) => x.room_key === key), want = ok.has(r.id);
    if ((row?.dims_ok ?? false) === want) continue;
    const dirty = !want || dimsMatter(r);
    if (row) {
      await tx.execute(sql`update trial_room_edits set dims_ok = ${want}, updated_at = now()
          ${dirty ? sql`, built = false, rebuild_id = ${rid}, confirmed_at = now()` : sql``} where job_id = ${id} and room_key = ${key}`);
      continue;
    }
    const now = roomNow(bundle, r.id);
    if (!now) continue;
    const name = (now.name || now.title || r.id).slice(0, 60);
    await tx.execute(sql`insert into trial_room_edits (job_id, room_key, panel, src_id, anchor, name, kind, built, request_id, confirmed_at,
          rebuild_id, dims_ok)
        values (${id}, ${key}, ${now.panel}, ${now.srcId}, ${JSON.stringify(now.anchor)}::jsonb, ${name}, ${now.kind}, ${!dirty}, ${requestId},
          now(), ${rid}, true)`);
  }
}

/** Комнаты страницы, которые пересчёт задевает: правки комнат этой пересборки и комнаты у стен её проёмов (оценка; точный список
 *  воркер присылает в ходе). */
async function touchedRooms(tx: Tx, id: string, rid: string, rooms: PageRoom[]): Promise<PageRoom[]> {
  const re = await q<{ room_key: string }>(tx, sql`select room_key from trial_room_edits where job_id = ${id} and rebuild_id = ${rid}
      and not built`);
  const op = await q<{ panel: string; c: [number, number] }>(tx, sql`select panel, c from trial_opening_edits where job_id = ${id}
      and rebuild_id = ${rid} and not built`);
  const hit = new Map<string, PageRoom>();
  for (const r of re) { const p = roomByKey(rooms, r.room_key); if (p) hit.set(p.id, p); }
  for (const o of op) for (const p of roomsAtOpening(rooms, o.panel, o.c)) hit.set(p.id, p);
  return [...hit.values()];
}
