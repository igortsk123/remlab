// Правка комнаты в туре пробы (план trial-room-edit-01, Е3; `db/init/028-trial-room-edits.sql`; T-20261110-36). Под блокировкой строки
// задания (`for update`), как «Обустроить» (`repo-rebuild.ts`): ключ → повтор `request_id` → задание готово → версия данных та, что видит
// страница (иначе `stale`) → комната есть в этой версии → порог 10 см по каждой оси от ПОСЛЕДНЕЙ построенной геометрии (меньше — ось как
// была; ничего не изменилось — `unchanged`, без работы) → правка в таблицу (одна на комнату, новая заменяет) → пересборка `edit`: ждущая
// правка уже стоит — новая едет с ней (без второй работы и без счёта), другая активная — `busy` → суточный лимит правок → вставка.

import { sql } from "drizzle-orm";
import type { TrialRoomEditIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { readBundle } from "@/lib/trial/bundle";
import { trialDir } from "@/lib/trial/config";
import { editKeyMatches } from "@/lib/trial/edit-key";
import { q, type Tx } from "@/lib/trial/repo-rebuild";
import { roomKindOf } from "@/lib/trial/room-kind";
import { TRIAL_ROOM_EDIT_LIMITS } from "@/lib/trial/upload-limits";

export const EDIT_THRESHOLD_CM = 10;

export type RoomEditAsk =
  | { ok: true; repeated: boolean; unchanged: boolean; edit: { id: string; status: string } | null }
  | { ok: false; status: number; error: string; version?: number };

type Box = { x: number; y: number; w: number; d: number };
type PlanRoom = { id: string; src_id: unknown; name?: string | null; kind: string; bbox: Box; edited?: { w: number; d: number } | null };
export type RoomNow = {
  panel: string; srcId: string; name: string; title: string; kind: string; orig: Box; w: number; d: number; anchor: { x: number; y: number };
};
type Bundle = { trial?: { panels?: { id: string; rooms?: PlanRoom[] }[] }; apartment_rooms?: { id?: string; titleRu?: string }[] };
type JobRow = { status: string; edit_key_hash: string | null; bundle_version: number; past_term: boolean };
const no = (status: number, error: string, version?: number): RoomEditAsk => ({ ok: false, status, error, ...(version !== undefined ? { version } : {}) });
const r1 = (v: number) => Math.round(v);

/** Комната страницы в версии данных → панель, id прочитанного плана, текущие имя и габариты (правка или как прочитано) и центр в долях
 *  охвата панели (по нему правка находит комнату, если перечитывание плана сменило id). */
export function roomNow(bundle: unknown, room: string): RoomNow | null {
  const b = bundle as Bundle;
  const panels = b?.trial?.panels ?? [];
  const title = String(b?.apartment_rooms?.find((x) => x.id === room)?.titleRu ?? "");
  for (const p of panels) {
    const rooms = p.rooms ?? [];
    const r = rooms.find((x) => x.id === room);
    if (!r || !r.bbox || r.src_id === undefined || r.src_id === null) continue;
    const bs = rooms.filter((x) => x.bbox).map((x) => x.bbox);
    const x0 = Math.min(...bs.map((b) => b.x)), y0 = Math.min(...bs.map((b) => b.y));
    const sx = Math.max(...bs.map((b) => b.x + b.w)) - x0 || 1, sy = Math.max(...bs.map((b) => b.y + b.d)) - y0 || 1;
    const c = { x: (r.bbox.x + r.bbox.w / 2 - x0) / sx, y: (r.bbox.y + r.bbox.d / 2 - y0) / sy };
    return { panel: p.id, srcId: String(r.src_id), name: String(r.name ?? ""), title, kind: r.kind, orig: r.bbox,
      w: r.edited?.w ?? r.bbox.w, d: r.edited?.d ?? r.bbox.d, anchor: { x: +c.x.toFixed(4), y: +c.y.toFixed(4) } };
  }
  return null;
}

/** Порог 10 см по каждой оси: меньше — ось остаётся как построена. → итоговые габариты; null — как прочитано (правки размера нет). */
export function nextDims(now: RoomNow, w: number, d: number): { w: number; d: number } | null {
  const nw = Math.abs(w - now.w) < EDIT_THRESHOLD_CM ? now.w : w, nd = Math.abs(d - now.d) < EDIT_THRESHOLD_CM ? now.d : d;
  return Math.abs(nw - now.orig.w) < 1 && Math.abs(nd - now.orig.d) < 1 ? null : { w: r1(nw), d: r1(nd) };
}

export async function askRoomEdit(id: string, inp: TrialRoomEditIn, dir = trialDir()): Promise<RoomEditAsk> {
  return db().transaction(async (tx) => {
    const [job] = await q<JobRow>(tx, sql`select status, edit_key_hash, bundle_version,
        coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${id} for update`);
    if (!job) return no(404, "not_found");
    if (job.status === "expired" || job.past_term) return no(410, "expired");
    if (!editKeyMatches(inp.k, job.edit_key_hash)) return no(403, "forbidden");
    const [same] = await q<{ one: number }>(tx, sql`select 1 as one from trial_room_edits where job_id = ${id} and request_id = ${inp.request_id}`);
    if (same) {
      const [last] = await q<{ id: string; status: string }>(tx, sql`select id, status from trial_rebuilds where job_id = ${id} and kind = 'edit'
          order by created_at desc, id desc limit 1`);
      return { ok: true, repeated: true, unchanged: false, edit: last ?? null };
    }
    if (job.status !== "done") return no(409, "not_ready");
    if (job.bundle_version !== inp.base_version) return no(409, "stale", job.bundle_version);
    const text = await readBundle(dir, id, job.bundle_version);
    let now: RoomNow | null = null;
    try { now = text === null ? null : roomNow(JSON.parse(text), inp.room); } catch { now = null; }
    if (!now) return no(422, "bad_room");
    const dims = nextDims(now, inp.w_cm, inp.d_cm);
    const sameDims = (dims?.w ?? now.orig.w) === r1(now.w) && (dims?.d ?? now.orig.d) === r1(now.d);
    // окошко показывает подпись страницы (`titleRu`), сборщик хранит подпись плана (`name`) — любое из них = имя не меняли
    const sameName = inp.name === now.name || inp.name === now.title;
    if (sameName && sameDims) return { ok: true, repeated: false, unchanged: true, edit: null };
    const gate = await editGate(tx, id);
    if (!gate.ok) return gate;
    const kind = sameName ? now.kind : roomKindOf(inp.name);
    const name = (sameName ? now.name || now.title : inp.name).slice(0, 60) || inp.name;
    await tx.execute(sql`insert into trial_room_edits (job_id, room_key, panel, src_id, anchor, name, kind, w_cm, d_cm, built, request_id)
        values (${id}, ${`${now.panel}|${now.srcId}`}, ${now.panel}, ${now.srcId}, ${JSON.stringify(now.anchor)}::jsonb, ${name}, ${kind},
          ${dims?.w ?? null}, ${dims?.d ?? null}, false, ${inp.request_id})
        on conflict (job_id, room_key) do update set name = excluded.name, kind = excluded.kind, w_cm = excluded.w_cm, d_cm = excluded.d_cm,
          anchor = excluded.anchor, built = false, request_id = excluded.request_id, updated_at = now()`);
    return { ok: true, repeated: false, unchanged: false, edit: await queueEdit(tx, id, inp.request_id, job.bundle_version, gate.active) };
  });
}

/** Можно ли поставить правку (комнаты или проёма, T-20261110-39 — та же пересборка `edit`): ждущая правка уже стоит — новая едет с ней
 *  (без второй работы и без счёта), другая активная — `busy`, суточный лимит пересборок `edit`. */
export async function editGate(tx: Tx, id: string): Promise<{ ok: true; active: { id: string } | null } | { ok: false; status: number; error: string }> {
  const [active] = await q<{ id: string; kind: string; status: string }>(tx, sql`select id, kind, status from trial_rebuilds
      where job_id = ${id} and status in ('queued', 'running')`);
  if (active && !(active.kind === "edit" && active.status === "queued")) return { ok: false, status: 409, error: "busy" };
  if (!active) {
    const [day] = await q<{ n: number }>(tx, sql`select count(*)::int as n from trial_rebuilds
        where job_id = ${id} and kind = 'edit' and created_at > now() - interval '24 hours'`);
    if ((day?.n ?? 0) >= TRIAL_ROOM_EDIT_LIMITS.day) return { ok: false, status: 429, error: "edit_limit" };
  }
  return { ok: true, active: active ? { id: active.id } : null };
}

/** Пересборка `edit` под принятую правку: ждущая (`editGate`) — она и есть, иначе новая строка. */
export async function queueEdit(tx: Tx, id: string, requestId: string, version: number, active: { id: string } | null): Promise<{ id: string; status: string }> {
  if (active) return { id: active.id, status: "queued" };
  const rid = randomToken();
  await tx.execute(sql`insert into trial_rebuilds (id, job_id, request_id, rooms, base_version, kind)
      values (${rid}, ${id}, ${requestId}, '[]'::jsonb, ${version}, 'edit')`);
  return { id: rid, status: "queued" };
}
