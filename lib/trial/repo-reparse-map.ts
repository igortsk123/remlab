// «Перечитать планировку» (план trial-reparse-01; T-20261111-02): после перечитывания у комнат и проёмов плана могут смениться номера
// (`trial_bundle.py` нумерует по порядку комнат). Правки агента хранятся по номерам ПРОЧИТАННОГО плана (`028`/`029`), поэтому публикация
// `reparse` той же транзакцией переписывает их на новые номера по карте воркера (однозначные геометрические пары, `tools/floorplan/
// conveyor.py:Reparse`): иначе следующая «Обустроить» положила бы правку по старому номеру на чужую комнату. Переименование — в два шага
// (сперва во временный ключ `~…`): ключ строки — первичный, обмен номерами двух правок иначе упёрся бы в него посреди обновления.
//
// Черновики (T-20261111-16/2): строки без подтверждения едут той же картой (`map.drafts`, их перевёл воркер теми же `translate`);
// не легшие (комнаты или проёма в перечитанном плане нет) и пришедшие во время перечитывания (их воркер не видел) снимаются, а причина
// уходит в `trial_rebuilds.progress.dropped_drafts` этой пересборки: страница показывает её из `GET edits` (`repo-plan-status.ts`).
// У подтверждённой строки с черновиком (`draft`) центр комнаты и проёма в черновике переводится вместе со строкой.

import { sql } from "drizzle-orm";
import type { TrialReparseMap } from "@/contracts/trial-bundle";
import type { TrialDroppedDraft } from "@/contracts/trial";
import { q, type Tx } from "@/lib/trial/repo-rebuild";

const LATE = "план перечитан, пока правка ждала подтверждения";

/** Снять строки-черновики, которых нет в карте черновиков: не легли (`dropped`, причина воркера) или пришли во время перечитывания. */
async function dropDrafts(tx: Tx, jobId: string, map: TrialReparseMap): Promise<TrialDroppedDraft[]> {
  const d = map.drafts;
  if (!d) return [];                     // карта старого воркера (без черновиков): строки переписываются по ключу, как до T-16/2
  const why = new Map(d.dropped.map((x) => [`${x.kind}:${x.panel}|${x.key}`, x.why]));
  const keepRooms = new Set(d.rooms.map((m) => `${m.panel}|${m.from}`));
  const keepOps = new Set(d.openings.map((m) => `${m.panel}|${m.key}`));
  const out: TrialDroppedDraft[] = [];
  const rooms = await q<{ room_key: string; panel: string; src_id: string; name: string }>(tx, sql`select room_key, panel, src_id, name
      from trial_room_edits where job_id = ${jobId} and confirmed_at is null order by created_at, room_key for update`);
  for (const r of rooms.filter((x) => !keepRooms.has(x.room_key))) {
    await tx.execute(sql`delete from trial_room_edits where job_id = ${jobId} and room_key = ${r.room_key}`);
    const w = why.get(`room:${r.room_key}`);
    out.push({ kind: "room", panel: r.panel, key: r.src_id, name: r.name, code: w ? "gone" : "late", why: w ?? LATE });
  }
  const ops = await q<{ op_key: string; panel: string; kind: string }>(tx, sql`select op_key, panel, kind from trial_opening_edits
      where job_id = ${jobId} and confirmed_at is null order by created_at, op_key for update`);
  for (const o of ops.filter((x) => !keepOps.has(x.op_key))) {
    await tx.execute(sql`delete from trial_opening_edits where job_id = ${jobId} and op_key = ${o.op_key}`);
    const w = why.get(`opening:${o.op_key}`);
    out.push({ kind: "opening", panel: o.panel, key: o.op_key.slice(o.panel.length + 1), name: o.kind, code: w ? "gone" : "late",
      why: w ?? LATE });
  }
  return out;
}

/** → снятые черновики с причиной (пусто — все легли). */
export async function applyReparseMap(tx: Tx, jobId: string, map: TrialReparseMap): Promise<TrialDroppedDraft[]> {
  const dropped = await dropDrafts(tx, jobId, map);
  const allRooms = [...map.rooms, ...(map.drafts?.rooms ?? [])];   // ключи подтверждённых и черновиков не пересекаются (первичный ключ)
  for (const m of allRooms.filter((x) => x.from !== x.to)) {
    await tx.execute(sql`update trial_room_edits set room_key = ${`~${m.panel}|${m.from}`}
      where job_id = ${jobId} and room_key = ${`${m.panel}|${m.from}`}`);
  }
  for (const m of allRooms) {
    const key = m.from === m.to ? `${m.panel}|${m.from}` : `~${m.panel}|${m.from}`;
    const anchor = JSON.stringify(m.anchor);
    await tx.execute(sql`update trial_room_edits set room_key = ${`${m.panel}|${m.to}`}, src_id = ${m.to}, anchor = ${anchor}::jsonb,
        draft = case when draft ? 'anchor' then jsonb_set(draft, '{anchor}', ${anchor}::jsonb) else draft end, updated_at = now()
      where job_id = ${jobId} and room_key = ${key}`);
  }
  const allOps = [...map.openings, ...(map.drafts?.openings ?? [])];
  for (const m of allOps.filter((x) => x.key !== x.to)) {
    await tx.execute(sql`update trial_opening_edits set op_key = ${`~${m.panel}|${m.key}`}
      where job_id = ${jobId} and op_key = ${`${m.panel}|${m.key}`}`);
  }
  const k = map.k ?? null;
  for (const m of allOps) {
    const key = m.key === m.to ? `${m.panel}|${m.key}` : `~${m.panel}|${m.key}`;
    // центр в черновике подтверждённой строки — в масштабе перечитанного плана (как `opening_edits._scaled`)
    await tx.execute(sql`update trial_opening_edits set op_key = ${`${m.panel}|${m.to}`}, src_idx = ${m.srcIdx},
        src_c = ${m.srcC ? JSON.stringify(m.srcC) : null}::jsonb, c = ${JSON.stringify(m.c)}::jsonb,
        draft = case when ${k}::float8 is not null and draft ? 'c' then jsonb_set(draft, '{c}', jsonb_build_array(
          round(((draft->'c'->>0)::float8 * ${k}::float8)::numeric, 1), round(((draft->'c'->>1)::float8 * ${k}::float8)::numeric, 1)))
          else draft end, updated_at = now()
      where job_id = ${jobId} and op_key = ${key}`);
  }
  return dropped;
}
