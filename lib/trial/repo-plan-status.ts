// Чтение для страницы тура агента (план trial-confirm-plan-01, пп. 2 и 4; T-20261111-16), право — ключом правки `k`:
// `edits` — черновики правок (страница рисует их поверх плана с пометкой «не подтверждено», переживают перезагрузку), галочки
// «размеры верны» и время последнего подтверждения; `rebuild-status` — ход последней пересборки (комнаты «в очереди / считаем / готово»,
// «N из M», оценка времени и сколько прошло). Только чтение, без замков.

import { sql } from "drizzle-orm";
import type { TrialDroppedDraft, TrialEditsView, TrialRebuildStatus, TrialRoomStatus } from "@/contracts/trial";
import { readBundle } from "@/lib/trial/bundle";
import { trialDir } from "@/lib/trial/config";
import { editKeyMatches } from "@/lib/trial/edit-key";
import { pageRooms, roomByKey } from "@/lib/trial/plan-rooms";
import { PENDING } from "@/lib/trial/repo-draft";
import { iso, jsonOf, rows } from "@/lib/trial/sql";

type Denied = { ok: false; status: number; error: string };
type JobRow = { status: string; edit_key_hash: string | null; bundle_version: number; past_term: boolean };

async function jobFor(id: string, k: string): Promise<JobRow | Denied> {
  const [job] = await rows<JobRow>(sql`select status, edit_key_hash, bundle_version, coalesce(result_expires_at < now(), false) as past_term
      from trial_jobs where id = ${id}`);
  if (!job) return { ok: false, status: 404, error: "not_found" };
  if (job.status === "expired" || job.past_term) return { ok: false, status: 410, error: "expired" };
  if (!editKeyMatches(k, job.edit_key_hash)) return { ok: false, status: 403, error: "forbidden" };
  return job;
}

type RoomRow = { room_key: string; panel: string; src_id: string; name: string; kind: string; w_cm: number | null; d_cm: number | null;
  draft: Record<string, unknown> | null; pending: boolean; dims_ok: boolean };
type OpRow = { op_key: string; panel: string; kind: "door" | "window"; c: unknown; width_cm: number; removed: boolean;
  draft: Record<string, unknown> | null };

export async function editsView(id: string, k: string, dir = trialDir()): Promise<TrialEditsView | Denied> {
  const job = await jobFor(id, k);
  if ("ok" in job) return job;
  const text = job.bundle_version > 0 ? await readBundle(dir, id, job.bundle_version) : null;
  let rooms: ReturnType<typeof pageRooms> = [];
  try { rooms = text === null ? [] : pageRooms(JSON.parse(text)); } catch { rooms = []; }
  const rr = await rows<RoomRow>(sql`select room_key, panel, src_id, name, kind, w_cm, d_cm, draft, ${PENDING} as pending, dims_ok
      from trial_room_edits where job_id = ${id} order by created_at, room_key`);
  const or = await rows<OpRow>(sql`select op_key, panel, kind, c, width_cm, removed, draft from trial_opening_edits
      where job_id = ${id} and ${PENDING} order by created_at, op_key`);
  const [last] = await rows<{ at: string | null }>(sql`select ${iso(sql`max(created_at)`)} as at from trial_rebuilds
      where job_id = ${id} and kind = 'edit' and (progress->>'confirm')::boolean`);
  // черновики, снятые перечитыванием плана (`repo-reparse-map.ts`) после последнего подтверждения: страница говорит агенту, что и почему
  const gone = await rows<{ d: unknown }>(sql`select progress->'dropped_drafts' as d from trial_rebuilds
      where job_id = ${id} and kind = 'reparse' and status = 'done' and jsonb_typeof(progress->'dropped_drafts') = 'array'
        and finished_at > coalesce((select max(created_at) from trial_rebuilds where job_id = ${id} and kind = 'edit'
          and (progress->>'confirm')::boolean), '-infinity'::timestamptz)
      order by finished_at`);
  const pend = rr.filter((r) => r.pending);
  return {
    ok: true, version: job.bundle_version, drafts: pend.length + or.length, confirmedAt: last?.at ?? null,
    dropped: gone.flatMap((g) => jsonOf<TrialDroppedDraft[]>(g.d)),
    roomsOk: rr.filter((r) => r.dims_ok).flatMap((r) => roomByKey(rooms, r.room_key)?.id ?? []),
    rooms: pend.map((r) => {
      const d = r.draft ? jsonOf<Record<string, unknown>>(r.draft) : null;
      return { room: roomByKey(rooms, r.room_key)?.id ?? null, panel: r.panel, srcId: r.src_id, name: d ? String(d.name) : r.name,
        kind: d ? String(d.kind) : r.kind, w_cm: d ? (d.w_cm as number | null) : r.w_cm, d_cm: d ? (d.d_cm as number | null) : r.d_cm };
    }),
    openings: or.map((o) => {
      const d = o.draft ? jsonOf<Record<string, unknown>>(o.draft) : null;
      return { panel: o.panel, key: o.op_key.slice(o.panel.length + 1), kind: d ? (d.kind as "door" | "window") : o.kind,
        c: jsonOf<[number, number]>(d ? d.c : o.c), w_cm: d ? Number(d.width_cm) : o.width_cm, removed: d ? d.removed === true : o.removed };
    }),
  };
}

type StatusRow = { id: string; kind: string; status: "queued" | "running" | "done" | "failed"; error_code: string | null; created_at: string;
  started_at: string | null; finished_at: string | null; elapsed: number; progress: unknown };
type Progress = { rooms?: Record<string, TrialRoomStatus>; done?: number; total?: number; eta_s?: number; room_eta_s?: Record<string, number> };

export async function rebuildStatus(id: string, k: string): Promise<TrialRebuildStatus | Denied> {
  const job = await jobFor(id, k);
  if ("ok" in job) return job;
  const [r] = await rows<StatusRow>(sql`select id, kind, status, error_code, ${iso(sql`created_at`)} as created_at,
      ${iso(sql`started_at`)} as started_at, ${iso(sql`finished_at`)} as finished_at,
      greatest(0, extract(epoch from (coalesce(finished_at, now()) - created_at)))::int as elapsed, progress
    from trial_rebuilds where job_id = ${id} order by created_at desc, id desc limit 1`);
  if (!r) return { ok: true, version: job.bundle_version, rebuild: null };
  const p = (r.progress === null ? {} : jsonOf<Progress>(r.progress)) ?? {};
  return {
    ok: true, version: job.bundle_version,
    rebuild: { id: r.id, kind: r.kind, status: r.status, error: r.status === "failed" ? r.error_code : null, createdAt: r.created_at,
      startedAt: r.started_at, finishedAt: r.finished_at, elapsedS: r.elapsed, rooms: p.rooms ?? {}, done: p.done ?? 0, total: p.total ?? 0,
      etaS: typeof p.eta_s === "number" ? p.eta_s : null, roomEtaS: p.room_eta_s ?? {} },
  };
}
