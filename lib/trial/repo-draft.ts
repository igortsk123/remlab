// Черновики правок тура (план trial-confirm-plan-01, п. 1; `db/init/032-trial-plan-confirm.sql`; T-20261111-16). Правка с `draft: true`
// пересборку не ставит: строка без `confirmed_at` (новая правка) или `draft` у подтверждённой строки (изменение уже построенной правки —
// подтверждённые значения остаются в основных колонках, сборка до кнопки берёт их). «Подтвердить планировку» (`repo-confirm.ts`)
// переносит черновики в подтверждённые одной транзакцией с постановкой пересборки. Все функции — внутри транзакции под замком задания.

import { sql } from "drizzle-orm";
import { q, type Tx } from "@/lib/trial/repo-rebuild";
import { TRIAL_ROOM_EDIT_LIMITS } from "@/lib/trial/upload-limits";
import type { OpeningRow } from "@/lib/trial/repo-opening-edit";

/** Строка с черновиком: не подтверждена или у подтверждённой есть неподтверждённое изменение. */
export const PENDING = sql`(confirmed_at is null or draft is not null)`;

export type RoomDraft = {
  roomKey: string; panel: string; srcId: string; anchor: { x: number; y: number }; name: string; kind: string;
  w: number | null; d: number | null; requestId: string;
};

/** Был ли уже такой `request_id` у правки (подтверждённой или черновика) этого задания. */
export async function seenRequest(tx: Tx, table: "room" | "opening", id: string, requestId: string): Promise<boolean> {
  const t = table === "room" ? sql`trial_room_edits` : sql`trial_opening_edits`;
  const [hit] = await q<{ one: number }>(tx, sql`select 1 as one from ${t} where job_id = ${id}
      and (request_id = ${requestId} or draft->>'request_id' = ${requestId}) limit 1`);
  return !!hit;
}

/** Черновик правки комнаты: новой — строка без `confirmed_at`, неподтверждённой — новые значения, подтверждённой — `draft`. */
export async function writeRoomDraft(tx: Tx, id: string, d: RoomDraft): Promise<void> {
  const [row] = await q<{ confirmed: boolean }>(tx, sql`select confirmed_at is not null as confirmed from trial_room_edits
      where job_id = ${id} and room_key = ${d.roomKey} for update`);
  const anchor = JSON.stringify(d.anchor);
  if (!row) {
    await tx.execute(sql`insert into trial_room_edits (job_id, room_key, panel, src_id, anchor, name, kind, w_cm, d_cm, built, request_id)
        values (${id}, ${d.roomKey}, ${d.panel}, ${d.srcId}, ${anchor}::jsonb, ${d.name}, ${d.kind}, ${d.w}, ${d.d}, false, ${d.requestId})`);
  } else if (!row.confirmed) {
    await tx.execute(sql`update trial_room_edits set anchor = ${anchor}::jsonb, name = ${d.name}, kind = ${d.kind}, w_cm = ${d.w}, d_cm = ${d.d},
        request_id = ${d.requestId}, updated_at = now() where job_id = ${id} and room_key = ${d.roomKey}`);
  } else {
    const draft = JSON.stringify({ name: d.name, kind: d.kind, w_cm: d.w, d_cm: d.d, anchor: d.anchor, request_id: d.requestId });
    await tx.execute(sql`update trial_room_edits set draft = ${draft}::jsonb, updated_at = now() where job_id = ${id} and room_key = ${d.roomKey}`);
  }
}

/** Агент вернул комнату к построенному: черновик снимается (новая правка — строка целиком, у подтверждённой — только `draft`). */
export async function dropRoomDraft(tx: Tx, id: string, roomKey: string): Promise<void> {
  await tx.execute(sql`delete from trial_room_edits where job_id = ${id} and room_key = ${roomKey} and confirmed_at is null`);
  await tx.execute(sql`update trial_room_edits set draft = null, updated_at = now() where job_id = ${id} and room_key = ${roomKey}
      and draft is not null`);
}

/** Черновик правки проёма (порядок — как у комнаты). */
export async function writeOpeningDraft(tx: Tx, id: string, panel: string, r: OpeningRow, requestId: string): Promise<void> {
  const key = `${panel}|${r.key}`;
  const [row] = await q<{ confirmed: boolean }>(tx, sql`select confirmed_at is not null as confirmed from trial_opening_edits
      where job_id = ${id} and op_key = ${key} for update`);
  const c = JSON.stringify(r.c);
  if (!row) {
    await tx.execute(sql`insert into trial_opening_edits (job_id, op_key, panel, src_idx, src_c, kind, c, width_cm, removed, built, request_id)
        values (${id}, ${key}, ${panel}, ${r.srcIdx}, ${r.srcC ? JSON.stringify(r.srcC) : null}::jsonb, ${r.kind}, ${c}::jsonb, ${r.w},
          ${r.removed}, false, ${requestId})`);
  } else if (!row.confirmed) {
    await tx.execute(sql`update trial_opening_edits set kind = ${r.kind}, c = ${c}::jsonb, width_cm = ${r.w}, removed = ${r.removed},
        request_id = ${requestId}, updated_at = now() where job_id = ${id} and op_key = ${key}`);
  } else {
    const draft = JSON.stringify({ kind: r.kind, c: r.c, width_cm: r.w, removed: r.removed, request_id: requestId });
    await tx.execute(sql`update trial_opening_edits set draft = ${draft}::jsonb, updated_at = now() where job_id = ${id} and op_key = ${key}`);
  }
}

/** Проём вернули к построенному (или свой новый сняли до подтверждения): черновик снимается. */
export async function dropOpeningDraft(tx: Tx, id: string, panel: string, key: string): Promise<void> {
  const k = `${panel}|${key}`;
  await tx.execute(sql`delete from trial_opening_edits where job_id = ${id} and op_key = ${k} and confirmed_at is null`);
  await tx.execute(sql`update trial_opening_edits set draft = null, updated_at = now() where job_id = ${id} and op_key = ${k}
      and draft is not null`);
}

/** Черновиков задания (комнаты + проёмы; перезапись той же комнаты или проёма — та же строка, не считается дважды). */
export async function draftCount(tx: Tx, id: string): Promise<number> {
  const [n] = await q<{ n: number }>(tx, sql`select (select count(*) from trial_room_edits where job_id = ${id} and ${PENDING})::int
      + (select count(*) from trial_opening_edits where job_id = ${id} and ${PENDING})::int as n`);
  return n?.n ?? 0;
}

/** Сверх лимита черновиков — откат всей транзакции (строки уже записаны). */
export class DraftLimit extends Error {}
export async function checkDraftLimit(tx: Tx, id: string): Promise<void> {
  if ((await draftCount(tx, id)) > TRIAL_ROOM_EDIT_LIMITS.drafts) throw new DraftLimit();
}

/** Подтвердить все черновики задания под пересборку `rid`: значения `draft` → в основные колонки, `confirmed_at`, `rebuild_id`,
 *  `built = false`. → сколько строк комнат и проёмов подтверждено. */
export async function confirmDrafts(tx: Tx, id: string, rid: string): Promise<{ rooms: number; openings: number }> {
  const rooms = await q<{ k: string }>(tx, sql`update trial_room_edits set
      name = coalesce(draft->>'name', name), kind = coalesce(draft->>'kind', kind),
      w_cm = case when draft is null then w_cm else (draft->>'w_cm')::int end,
      d_cm = case when draft is null then d_cm else (draft->>'d_cm')::int end,
      anchor = coalesce(draft->'anchor', anchor), request_id = coalesce(draft->>'request_id', request_id),
      draft = null, confirmed_at = now(), rebuild_id = ${rid}, built = false, updated_at = now()
    where job_id = ${id} and ${PENDING} returning room_key as k`);
  const ops = await q<{ k: string }>(tx, sql`update trial_opening_edits set
      kind = coalesce(draft->>'kind', kind), c = coalesce(draft->'c', c),
      width_cm = coalesce((draft->>'width_cm')::int, width_cm), removed = coalesce((draft->>'removed')::boolean, removed),
      request_id = coalesce(draft->>'request_id', request_id),
      draft = null, confirmed_at = now(), rebuild_id = ${rid}, built = false, updated_at = now()
    where job_id = ${id} and ${PENDING} returning op_key as k`);
  return { rooms: rooms.length, openings: ops.length };
}
