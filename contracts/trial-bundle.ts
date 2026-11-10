// Данные страницы задания `demo-data.json` (план agent-trial-08, задача А; собирает `tools/scout/trial_bundle.py`): то, без чего `index.html`
// падает при загрузке. Форма — схема; связи между полями — `bundleProblem` (бизнес-правила не в Zod). Остальные поля проходят как есть.

import { z } from "zod";

const num = z.number().finite();
const wall = z.enum(["north", "south", "east", "west"]);
// подпись комнаты: `title` — по-русски (как в живом `/demo`), `title_ru`/`title_en` — оба языка, `approx` — ядро заметно меньше контура
const geo = z.looseObject({
  w: num.positive(), d: num.positive(), title: z.string().max(200),
  title_ru: z.string().max(200).optional(), title_en: z.string().max(200).optional(), approx: z.boolean().optional(),
  openings: z.array(z.looseObject({ kind: z.enum(["door", "window", "opening"]), wall, offset_cm: num, width_cm: num.positive() })).max(200),
  radiators: z.array(z.unknown()).max(50),
});
const variant = z.looseObject({
  id: z.string().min(1).max(80), room_id: z.string().regex(/^[a-z0-9-]{1,40}$/), style: z.string().min(1).max(40),
  items: z.array(z.looseObject({ role: z.string().min(1), x: num, y: num })).max(200), pending: z.boolean(), furniture_state: z.string().max(20),
});

export const trialBundle = z.looseObject({
  /** `complete` — ни одной комнаты-цели (гостиные, спальни) в «подбирается»: только тогда задание может стать `done`. */
  trial: z.looseObject({ job_id: z.string(), complete: z.boolean().optional() }),
  room: geo,
  rooms_geo: z.record(z.string(), geo),
  /** По каждой комнате исход мебели: подбирается / готово / отказ / не обставляется (кухня, санузел, прихожая) / ждёт проверки размера
   *  (`awaiting_check`: распознавание пометило «размер не сошёлся» — автоматически не обставляем, агент поправит размер и нажмёт
   *  «Обустроить»; `done` не держит); `furniture_text` — текст покупателю (у отказа, «не обставляется» и «ждёт проверки» обязателен),
   *  `furniture_text_en` — он же по-английски. */
  apartment_rooms: z.array(z.looseObject({
    id: z.string().min(1).max(40), furniture_state: z.enum(["ready", "pending", "refused", "not_furnished", "awaiting_check"]),
    furniture_text: z.string().max(300).nullable(), furniture_text_en: z.string().max(300).nullable().optional(),
    /** код для надписи на любом языке: furnished / pending / no_products / no_space / no_space_walkthrough (товары были, места под
     *  диван и ТВ нет; «проходная» — две двери и больше, T-20261110-09) / not_readable / scale_unverified / no_window /
     *  largest_living_only / not_furnished / failed / size_unverified */
    furniture_outcome: z.string().max(40).optional(),
    titleRu: z.string().max(120).optional(), titleEn: z.string().max(120).optional(),
    /** Размерам комнаты можно верить для фото нейросети (`trial_bundle.photo_ok`, T-20261109-34): нет поля — фото нет. */
    photo_ok: z.boolean().optional(),
  })).max(200),
  variants: z.array(variant).min(1).max(200),
  feeds: z.record(z.string(), z.array(z.unknown())),
  rules: z.looseObject({}),
  /** Правило опроса (`rules/quiz.json`): без `questions` ссылка покупателя `?quiz=1` опрос не откроет. */
  quiz: z.looseObject({ questions: z.array(z.unknown()).min(1) }),
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
  const textual = new Set(["refused", "not_furnished", "awaiting_check"]);
  if (b.apartment_rooms.some((r) => textual.has(r.furniture_state) && !r.furniture_text?.trim())) return "refused_without_text";
  const furnished = new Set(b.variants.filter((v) => v.items.length > 0).map((v) => v.room_id));
  if (b.apartment_rooms.some((r) => r.furniture_state === "ready" && !furnished.has(r.id))) return "ready_without_items";
  if (b.apartment_rooms.some((r) => r.furniture_state !== "ready" && furnished.has(r.id))) return "items_in_unfurnished_room";
  if (b.trial.complete && b.apartment_rooms.some((r) => r.furniture_state === "pending")) return "complete_with_pending";
  if (b.apartment_rooms.some((r) => r.titleEn && CYRILLIC.test(r.titleEn))) return "cyrillic_in_english_title";
  if (hasShopField(b)) return "shop_field";
  return null;
}

const CYRILLIC = /[Ѐ-ԯ]/;
// второй замок к очистке сборщика (`trial_bundle.assert_public`): у товаров вариантов и лент нет полей магазина
const SHOP_FIELDS = new Set(["url", "url_direct", "shop", "img", "img_hd", "price", "brand"]);
function hasShopField(b: TrialBundle): boolean {
  const bad = (o: unknown): boolean => !!o && typeof o === "object" && Object.keys(o).some((k) => SHOP_FIELDS.has(k) || k.endsWith("_url"));
  const items = b.variants.flatMap((v) => v.items);
  const rows = Object.values(b.feeds).flat();
  return items.some((it) => bad(it) || bad((it as { sku?: unknown }).sku)) || rows.some(bad);
}

const lease = { id: z.string(), attempt: z.number().int().positive(), leaseToken: z.string().min(16).max(64) };

/** Тело публикации: `bundle` — ТОЧНЫЕ байты файла строкой, `sha256` — их хеш у воркера (проверяется до записи; сверка с тем, что собрали). */
export const trialBundleIn = z.object({
  ...lease, bundle: z.string().min(2), sha256: z.string().regex(/^[0-9a-f]{64}$/), spentUsd: z.number().nonnegative().max(100).optional(),
});
export type TrialBundleIn = z.infer<typeof trialBundleIn>;

/** Пересборка готового тура «как есть» (оператор, T-20261110-05): от какой версии собрано и точные байты новой. */
export const trialReissueIn = z.object({
  baseVersion: z.number().int().positive(), bundle: z.string().min(2), sha256: z.string().regex(/^[0-9a-f]{64}$/),
});

/** Итог пересборки «Обустроить» (план agent-trial-08, Р1): `id` — id пересборки (её аренда), `jobId` — задание, чья это версия.
 *  `result` — только у пересборки по тексту агента (Р2-текст): план перечитан с размерами из текста, новый `floorplanResult` задания. */
export const trialRebuildPublishIn = z.object({
  ...lease, jobId: z.string().regex(/^[A-Za-z0-9_-]{22}$/), bundle: z.string().min(2), sha256: z.string().regex(/^[0-9a-f]{64}$/),
  spentUsd: z.number().nonnegative().max(100).optional(), result: z.unknown().optional(),
});
