// Оценка времени пересчёта для таймера страницы (владелец TG 1479/1480; T-20261111-16): на плитке правленой комнаты, внутри открытой
// комнаты и возле плана. Сервер даёт только оценку (`eta_s` всего пересчёта и `room_eta_s` по комнате) — обратный отсчёт страница ведёт
// сама. Источник — замеры стадий прошлых пересборок (`trial_rebuilds.progress.timings`, их шлёт воркер при публикации:
// `tools/floorplan/conveyor.py:Rebuild.publish`): сперва этого тура (последнее ненулевое), нет — среднее по всем турам, нет и его — запас.
// Модель конвейера `EditRebuild`: версия стен (`v1_s`) → гостиная (`living_s`, если правлена) → спальни (`bedrooms_s`, если правлена
// хоть одна) → итоговая версия с ракурсами и отправка (`tail` = `publish_s` − предыдущие). Очередь к воркеру в оценку не входит.

import { sql } from "drizzle-orm";
import { q, type Tx } from "@/lib/trial/repo-rebuild";

export type StageEst = { v1: number; living: number; bedrooms: number; tail: number };
/** Запас, пока замеров нет нигде (≈ 2 мин на правку одной спальни — как обещано агенту в плане). */
export const ETA_DEFAULT: StageEst = { v1: 15, living: 60, bedrooms: 60, tail: 40 };
type Timings = Record<string, number>;

const pos = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);
const tailOf = (t: Timings): number | null => {
  const p = pos(t.publish_s);
  return p === null ? null : Math.max(0, p - (t.v1_s ?? 0) - (t.living_s ?? 0) - (t.bedrooms_s ?? 0));
};
const KEYS: [keyof StageEst, (t: Timings) => number | null][] = [
  ["v1", (t) => pos(t.v1_s)], ["living", (t) => pos(t.living_s)], ["bedrooms", (t) => pos(t.bedrooms_s)], ["tail", tailOf],
];

/** Замеры этого тура (новые первыми) и всех туров → оценка стадий. Нулевой замер (стадию не запускали — прежняя сцена) не в счёт. */
export function stageEst(own: Timings[], all: Timings[]): StageEst {
  const out = { ...ETA_DEFAULT };
  for (const [k, get] of KEYS) {
    const mine = own.map(get).find((v) => v !== null);
    const vals = all.map(get).filter((v): v is number => v !== null);
    out[k] = mine ?? (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : ETA_DEFAULT[k]);
  }
  return out;
}

/** Оценка пересчёта задетых комнат: всего и по каждой (гостиная готова после своей стадии, спальни — после стадии спален, прочие — к итогу). */
export function etaOf(est: StageEst, rooms: { id: string; kind: string }[]): { eta_s: number; room_eta_s: Record<string, number> } {
  const living = rooms.some((r) => r.kind === "living"), bedroom = rooms.some((r) => r.kind === "bedroom");
  const total = est.v1 + (living ? est.living : 0) + (bedroom ? est.bedrooms : 0) + est.tail;
  const room = (kind: string) => kind === "living" ? est.v1 + est.living
    : kind === "bedroom" ? est.v1 + (living ? est.living : 0) + est.bedrooms : total;
  return { eta_s: Math.round(total), room_eta_s: Object.fromEntries(rooms.map((r) => [r.id, Math.round(room(r.kind))])) };
}

/** Замеры из базы: до 10 последних пересборок этого тура и до 200 последних всех туров (виды со стадиями мебели — `edit`, `furnish`). */
export async function stageEstimate(tx: Tx, jobId: string): Promise<StageEst> {
  const pick = (own: boolean, n: number) => q<{ t: Timings }>(tx, sql`select progress->'timings' as t from trial_rebuilds
      where status = 'done' and kind in ('edit', 'furnish') and jsonb_typeof(progress->'timings') = 'object'
        ${own ? sql`and job_id = ${jobId}` : sql``}
      order by finished_at desc nulls last limit ${n}`);
  return stageEst((await pick(true, 10)).map((r) => r.t), (await pick(false, 200)).map((r) => r.t));
}
