// Окна и двери агента на плане тура пробы (план trial-room-edit-01, Е4; `db/init/029-trial-opening-edits.sql`; T-20261110-39). Порядок —
// как у правки комнаты (`repo-room-edit.ts`), под блокировкой строки задания: ключ → повтор `request_id` → задание готово → версия
// данных та, что видит страница (иначе `stale`) → панель и проёмы есть в этой версии → что изменилось (меньше 1 см и тот же тип —
// без правки; ничего — `unchanged`, без работы) → пересборка `edit` (`editGate`: ждущая забирает, другая активная — `busy`, лимит суток)
// → строки правок (одна на проём, новая заменяет) → пересборка.

import { sql } from "drizzle-orm";
import type { TrialOpeningEditIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { readBundle } from "@/lib/trial/bundle";
import { trialDir } from "@/lib/trial/config";
import { editKeyMatches } from "@/lib/trial/edit-key";
import { q } from "@/lib/trial/repo-rebuild";
import { editGate, queueEdit, type RoomEditAsk } from "@/lib/trial/repo-room-edit";

/** Проёмов-правок на задание всего (добавленные + правленые распознанные): больше — `too_many`. */
export const OPENING_EDITS_MAX = 120;
/** Центр проёма — не дальше этого от охвата комнат панели (см). */
const BOX_PAD_CM = 100;

type Pt = [number, number];
type PageOpening = { kind?: string; c?: Pt; widthCm?: number; key?: string; srcC?: Pt };
type PlanRoom = { bbox?: { x: number; y: number; w: number; d: number } };
type Bundle = { trial?: { panels?: { id: string; rooms?: PlanRoom[]; openings?: PageOpening[] }[] } };
/** Проём панели в версии данных: ключ страницы, тип, центр, ширина и центр как прочитан (у распознанного). */
export type OpeningNow = { key: string; kind: string; c: Pt; w: number; srcC: Pt | null };
export type PanelNow = { openings: OpeningNow[]; box: { x0: number; y0: number; x1: number; y1: number } };
export type OpeningRow = { key: string; srcIdx: number | null; srcC: Pt | null; kind: "door" | "window"; c: Pt; w: number; removed: boolean };

const no = (status: number, error: string, version?: number): RoomEditAsk => ({ ok: false, status, error, ...(version !== undefined ? { version } : {}) });

/** Панель плана в версии данных → её проёмы с ключами (у сборки без правок проёмов ключа нет — `s<номер>`) и охват комнат. */
export function panelNow(bundle: unknown, panel: string): PanelNow | null {
  const p = (bundle as Bundle)?.trial?.panels?.find((x) => x.id === panel);
  const bs = (p?.rooms ?? []).map((r) => r.bbox).filter((b): b is NonNullable<PlanRoom["bbox"]> => !!b);
  if (!p || !bs.length) return null;
  const openings = (p.openings ?? []).flatMap((o, i): OpeningNow[] => {
    if (!Array.isArray(o.c) || !(Number(o.widthCm) > 0)) return [];
    const key = typeof o.key === "string" ? o.key : `s${i}`;
    return [{ key, kind: String(o.kind), c: [+o.c[0], +o.c[1]], w: +Number(o.widthCm), srcC: key.startsWith("s") ? (o.srcC ?? [+o.c[0], +o.c[1]]) : null }];
  });
  return { openings, box: { x0: Math.min(...bs.map((b) => b.x)), y0: Math.min(...bs.map((b) => b.y)),
    x1: Math.max(...bs.map((b) => b.x + b.w)), y1: Math.max(...bs.map((b) => b.y + b.d)) } };
}

/** Правки страницы → строки таблицы (только изменённые) или ошибка: проёма с таким ключом `s…` нет, центр вне плана. */
export function openingRows(now: PanelNow, ops: TrialOpeningEditIn["ops"]): OpeningRow[] | "bad_opening" {
  const out: OpeningRow[] = [];
  const { x0, y0, x1, y1 } = now.box;
  for (const op of ops) {
    const cur = now.openings.find((o) => o.key === op.key);
    if (op.key.startsWith("s") && !cur) return "bad_opening";
    const [x, y] = op.c;
    if (x < x0 - BOX_PAD_CM || x > x1 + BOX_PAD_CM || y < y0 - BOX_PAD_CM || y > y1 + BOX_PAD_CM) return "bad_opening";
    const c: Pt = [Math.round(x * 10) / 10, Math.round(y * 10) / 10], w = Math.round(op.w_cm);
    if (!cur && op.removed) continue;                                           // свой новый, снятый до сохранения — нечего писать
    if (cur && !op.removed && cur.kind === op.kind && Math.hypot(cur.c[0] - c[0], cur.c[1] - c[1]) < 1 && Math.abs(cur.w - w) < 1) continue;
    const src = op.key.startsWith("s");
    out.push({ key: op.key, srcIdx: src ? Number(op.key.slice(1)) : null, srcC: src ? (cur?.srcC ?? null) : null, kind: op.kind, c, w,
      removed: op.removed });
  }
  return out;
}

export async function askOpeningEdit(id: string, inp: TrialOpeningEditIn, dir = trialDir()): Promise<RoomEditAsk> {
  return db().transaction(async (tx): Promise<RoomEditAsk> => {
    const [job] = await q<{ status: string; edit_key_hash: string | null; bundle_version: number; past_term: boolean }>(tx, sql`select status,
        edit_key_hash, bundle_version, coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${id} for update`);
    if (!job) return no(404, "not_found");
    if (job.status === "expired" || job.past_term) return no(410, "expired");
    if (!editKeyMatches(inp.k, job.edit_key_hash)) return no(403, "forbidden");
    const [same] = await q<{ one: number }>(tx, sql`select 1 as one from trial_opening_edits where job_id = ${id} and request_id = ${inp.request_id} limit 1`);
    if (same) {
      const [last] = await q<{ id: string; status: string }>(tx, sql`select id, status from trial_rebuilds where job_id = ${id} and kind = 'edit'
          order by created_at desc, id desc limit 1`);
      return { ok: true, repeated: true, unchanged: false, edit: last ?? null };
    }
    if (job.status !== "done") return no(409, "not_ready");
    if (job.bundle_version !== inp.base_version) return no(409, "stale", job.bundle_version);
    const text = await readBundle(dir, id, job.bundle_version);
    let now: PanelNow | null = null;
    try { now = text === null ? null : panelNow(JSON.parse(text), inp.panel); } catch { now = null; }
    if (!now) return no(422, "bad_opening");
    const rows = openingRows(now, inp.ops);
    if (rows === "bad_opening") return no(422, "bad_opening");
    if (!rows.length) return { ok: true, repeated: false, unchanged: true, edit: null };
    const gate = await editGate(tx, id);
    if (!gate.ok) return gate;
    for (const r of rows) {
      await tx.execute(sql`insert into trial_opening_edits (job_id, op_key, panel, src_idx, src_c, kind, c, width_cm, removed, built, request_id)
          values (${id}, ${`${inp.panel}|${r.key}`}, ${inp.panel}, ${r.srcIdx}, ${r.srcC ? JSON.stringify(r.srcC) : null}::jsonb, ${r.kind},
            ${JSON.stringify(r.c)}::jsonb, ${r.w}, ${r.removed}, false, ${inp.request_id})
          on conflict (job_id, op_key) do update set kind = excluded.kind, c = excluded.c, width_cm = excluded.width_cm,
            removed = excluded.removed, built = false, request_id = excluded.request_id, updated_at = now()`);
    }
    const [n] = await q<{ n: number }>(tx, sql`select count(*)::int as n from trial_opening_edits where job_id = ${id}`);
    if ((n?.n ?? 0) > OPENING_EDITS_MAX) throw new TooMany();
    return { ok: true, repeated: false, unchanged: false, edit: await queueEdit(tx, id, inp.request_id, job.bundle_version, gate.active) };
  }).catch((e: unknown): RoomEditAsk => {
    if (e instanceof TooMany) return no(422, "too_many");
    throw e;
  });
}

/** Сверх `OPENING_EDITS_MAX` — откат всей транзакции (строки уже вставлены). */
class TooMany extends Error {}
