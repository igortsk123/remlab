// Данные страницы задания `demo-data.json` (план agent-trial-08, задача А; собирает `tools/scout/trial_bundle.py`): то, без чего `index.html`
// падает при загрузке. Форма — схема; связи между полями — `bundleProblem` (бизнес-правила не в Zod). Остальные поля проходят как есть.

import { z } from "zod";

const num = z.number().finite();
const wall = z.enum(["north", "south", "east", "west"]);
const geo = z.looseObject({
  w: num.positive(), d: num.positive(), title: z.string().max(200),
  openings: z.array(z.looseObject({ kind: z.enum(["door", "window", "opening"]), wall, offset_cm: num, width_cm: num.positive() })).max(200),
  radiators: z.array(z.unknown()).max(50),
});
const variant = z.looseObject({
  id: z.string().min(1).max(80), room_id: z.string().regex(/^[a-z0-9-]{1,40}$/), style: z.string().min(1).max(40),
  items: z.array(z.looseObject({ role: z.string().min(1), x: num, y: num })).max(200), pending: z.boolean(), furniture_state: z.string().max(20),
});

export const trialBundle = z.looseObject({
  trial: z.looseObject({ job_id: z.string() }),
  room: geo,
  rooms_geo: z.record(z.string(), geo),
  /** По каждой комнате исход мебели: готово / подбирается / отказ (`furniture_text` — текст для покупателя). */
  apartment_rooms: z.array(z.looseObject({
    id: z.string().min(1).max(40), furniture_state: z.enum(["ready", "pending", "refused"]), furniture_text: z.string().max(300).nullable(),
  })).max(200),
  variants: z.array(variant).min(1).max(200),
  feeds: z.record(z.string(), z.array(z.unknown())),
  rules: z.looseObject({}),
});
export type TrialBundle = z.infer<typeof trialBundle>;

/** Первое нарушение связей (код для ответа воркеру) или null. Задание чужое, id повторяются, комнаты варианта нет — страница открыла бы не то. */
export function bundleProblem(b: TrialBundle, jobId: string): string | null {
  if (b.trial.job_id !== jobId) return "wrong_job";
  const vars = b.variants.map((v) => v.id);
  if (new Set(vars).size !== vars.length) return "variant_id_repeated";
  const rooms = b.apartment_rooms.map((r) => r.id);
  if (new Set(rooms).size !== rooms.length) return "room_id_repeated";
  if (b.variants.some((v) => !(v.room_id in b.rooms_geo))) return "variant_without_room";
  if (b.variants.some((v) => v.pending && v.items.length > 0)) return "pending_with_items";
  if (b.apartment_rooms.some((r) => r.furniture_state === "refused" && !r.furniture_text?.trim())) return "refused_without_text";
  const furnished = new Set(b.variants.filter((v) => v.items.length > 0).map((v) => v.room_id));
  if (b.apartment_rooms.some((r) => r.furniture_state === "ready" && !furnished.has(r.id))) return "ready_without_items";
  return null;
}

const lease = { id: z.string(), attempt: z.number().int().positive(), leaseToken: z.string().min(16).max(64) };

/** Тело публикации: `bundle` — ТОЧНЫЕ байты файла строкой, `sha256` — их хеш у воркера (проверяется до записи; сверка с тем, что собрали). */
export const trialBundleIn = z.object({
  ...lease, bundle: z.string().min(2), sha256: z.string().regex(/^[0-9a-f]{64}$/), spentUsd: z.number().nonnegative().max(100).optional(),
});
export type TrialBundleIn = z.infer<typeof trialBundleIn>;
