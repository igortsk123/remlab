// Контракт пробы для агентов UK (план agent-trial-01-upload-grey-tour, T-A): статусы задания, вид для страницы
// `/try/<id>`, результат стенда `floorplanResult` и тела ручек воркера DEV. Один и тот же JSON результата проверяет
// прод (`safeParse` при приёме) и тест Python стенда (выгрузка `z.toJSONSchema` → `tests/fixtures/trial-result.schema.json`).
// Координаты результата — сантиметры, x вправо, y вниз по листу (= «вглубь» сцены, как `lib/viewer3d/rooms.ts`).

import { z } from "zod";

export const trialStatus = z.enum(["queued", "running", "done", "failed", "cancelled", "expired"]);
export const trialStage = z.enum(["queued", "raster", "labels", "walls", "repair", "export", "done"]);
/** Коды ошибок, которые видит страница (закрытый список; подробности — только в `error_detail` базы). */
export const trialErrorCode = z.enum([
  "pdf_unreadable", "unsupported", "too_large", "no_plan", "budget", "vlm_error", "pipeline_error", "timeout",
  "lease_lost", "stale", "internal",
]);
/** Коды, которые может прислать воркер: публичные + «вернуть задание, DEV занят» (попытку не тратит). */
export const trialFailCode = z.enum([...trialErrorCode.options, "waiting_capacity"]);

export type TrialStatus = z.infer<typeof trialStatus>;
export type TrialStage = z.infer<typeof trialStage>;
export type TrialErrorCode = z.infer<typeof trialErrorCode>;

/** Что видит страница. Ни пути файла, ни текста объявления, ни аренды, ни воркера, ни деталей ошибки. */
export const trialJobView = z.object({
  id: z.string(),
  status: trialStatus,
  stage: trialStage,
  stages: z.array(z.object({ stage: trialStage, at: z.string() })),
  createdAt: z.string(),
  finishedAt: z.string().nullable(),
  elapsedSec: z.number().int().nonnegative(),
  /** Сколько заданий заберут раньше этого (то же условие и порядок, что у claim); null — не в очереди. */
  queueAhead: z.number().int().nonnegative().nullable(),
  workerAlive: z.boolean(),
  errorCode: trialErrorCode.nullable(),
  resultVersion: z.number().int().nonnegative(),
  /** Опубликованная версия данных страницы (`/api/trial/<id>/bundle`, ETag `"v<N>"`); 0 — ещё нет. */
  bundleVersion: z.number().int().nonnegative(),
  /** Последняя пересборка «Обустроить» (план agent-trial-08, Р1): ждёт / идёт / не удалась; null — нет или завершена. Ключа здесь нет. */
  rebuild: z.enum(["queued", "running", "failed"]).nullable().default(null),
  rebuildError: z.enum(["stale", "lease_lost", "timeout", "pipeline_error", "internal"]).nullable().default(null),
  /** «Размеры своими словами» (Р2-текст): размеров нет (`scale` ∈ not_verified/area) или есть комнаты, ждущие проверки, — звать агента
   *  написать размеры. Считается по последней версии данных страницы (`lib/trial/size-ask.ts`). */
  askSizes: z.boolean().default(false),
  /** Последний текст агента: принят и ждёт сборки / применяется / применён / не удался. Самого текста здесь нет. */
  listing: z.enum(["accepted", "applying", "done", "failed"]).nullable().default(null),
  listingError: z.enum(["source_gone", "no_match", "stale", "lease_lost", "timeout", "pipeline_error", "internal"]).nullable().default(null),
  /** Правка комнаты (T-20261110-36): пересобирается / готово (новая версия пришла) / не удалась. */
  roomEdit: z.enum(["applying", "done", "failed"]).nullable().default(null),
  roomEditError: z.enum(["stale", "lease_lost", "timeout", "pipeline_error", "internal"]).nullable().default(null),
  /** «Перечитать планировку» оператором (T-20261111-02): тур обновляется — нейтрально, без кода ошибки (не удалась — тур прежний). */
  tourUpdate: z.enum(["applying"]).nullable().default(null),
});
export type TrialJobView = z.infer<typeof trialJobView>;

// ── «Обустроить» / «Обустроить всё» (план agent-trial-08, Р1; `db/init/024-trial-rebuilds.sql`) ─────────────────
/** id комнаты страницы (`living`, `bedroom-1`, `living-2`) — как `trial_bundle.py` и `variant.room_id`. */
export const trialPageRoomId = z.string().regex(/^[a-z0-9-]{1,40}$/);
/** Тело кнопки: `k` — ключ правки из ссылки агента, `request_id` — повтор нажатия даёт ту же пересборку, `base_version` — версия данных,
 *  которую видит страница (устарела — 409 `stale`), `rooms` — комнаты страницы или "all" (все, что ждут проверки). */
export const trialRebuildIn = z.object({
  k: z.string().regex(/^[A-Za-z0-9_-]{22}$/),
  request_id: z.string().regex(/^[A-Za-z0-9_-]{8,64}$/),
  base_version: z.number().int().positive(),
  rooms: z.union([z.array(trialPageRoomId).min(1).max(40), z.literal("all")]),
});
export type TrialRebuildIn = z.infer<typeof trialRebuildIn>;

/** Заказ фото нейросети из тура (T-20261109-34): заказ страницы как у `/demo` (`payload()` + `views`). Обязательны комната страницы,
 *  ДВА кадра из 3D браузера (имена — sha256 загруженных `/api/render/frame`; без 3D фото нет, серверной сцены для тура нет), размеры
 *  комнаты (сверяются с данными задания) и предметы. Остальные поля заказа проходят как есть — их форму проверяет сервис кадров. */
export const trialPhotoIn = z.looseObject({
  room_id: trialPageRoomId,
  views: z.array(z.object({ camera: z.string().regex(/^C[1-4]$/), id: z.string().regex(/^[0-9a-f]{64}$/) })).length(2),
  room: z.looseObject({ w: z.number().finite().positive(), d: z.number().finite().positive() }),
  items: z.array(z.looseObject({ role: z.string().min(1).max(60) })).min(1).max(200),
});
export type TrialPhotoIn = z.infer<typeof trialPhotoIn>;
/** Коды сбоя пересборки от воркера (наружу — `trialJobView.rebuildError` / `listingError`); `source_gone` — исходного листа (или
 *  кэша чтения плана) уже нет; `no_match` — текст агента ни к одной комнате плана не подошёл (страница остаётся как была).
 *  Только у «перечитать планировку» (`reparse`, T-20261111-02; наружу не выходят — тур прежний): `cache_miss` — кэша чтения плана нет
 *  (платно не читаем), `edits_conflict` — правка агента не нашла однозначной пары, `regress` — сторож регресса нашёл потери. */
export const trialRebuildFailCode = z.enum([
  "stale", "timeout", "pipeline_error", "internal", "waiting_capacity", "nothing_to_furnish", "source_gone", "no_match",
  "cache_miss", "edits_conflict", "regress",
]);

// ── «Размеры своими словами» (план agent-trial-08, Р2-текст; `db/init/025-trial-listing-text.sql`) ─────────────────
export const TRIAL_SIZES_TEXT_MAX = 2000; // знаков (= проверка базы `trial_rebuilds_text_len`)
export const TRIAL_SIZES_TEXT_MAX_BYTES = 6000; // UTF-8: 2000 знаков кириллицы — 4000 байт
/** Текст агента: принимается уже на v1 (задание ещё идёт); `request_id` — повтор отправки не даёт второй работы. */
export const trialListingIn = z.object({
  k: z.string().regex(/^[A-Za-z0-9_-]{22}$/),
  request_id: z.string().regex(/^[A-Za-z0-9_-]{8,64}$/),
  text: z.string().trim().min(1).max(TRIAL_SIZES_TEXT_MAX)
    .refine((t) => new TextEncoder().encode(t).length <= TRIAL_SIZES_TEXT_MAX_BYTES, { message: "too many bytes" }),
});
export type TrialListingIn = z.infer<typeof trialListingIn>;

// ── Правка комнаты в туре (план trial-room-edit-01, Е3; `db/init/028-trial-room-edits.sql`) ─────────────────
export const TRIAL_ROOM_NAME_MAX = 60;
export const TRIAL_ROOM_CM_MIN = 50;
export const TRIAL_ROOM_CM_MAX = 5000;
/** Правка одной комнаты страницы: имя и габариты (охват по осям листа, см) — окошко шлёт все поля; площадь окошко переводит в габариты
 *  по пропорциям. `base_version` — версия данных, которую видит страница (по ней сервер считает «изменилось ли» и порог 10 см). */
export const trialRoomEditIn = z.object({
  k: z.string().regex(/^[A-Za-z0-9_-]{22}$/),
  request_id: z.string().regex(/^[A-Za-z0-9_-]{8,64}$/),
  base_version: z.number().int().positive(),
  room: trialPageRoomId,
  name: z.string().trim().min(1).max(TRIAL_ROOM_NAME_MAX),
  w_cm: z.number().finite().min(TRIAL_ROOM_CM_MIN).max(TRIAL_ROOM_CM_MAX),
  d_cm: z.number().finite().min(TRIAL_ROOM_CM_MIN).max(TRIAL_ROOM_CM_MAX),
  /** true — черновик (T-20261111-16): правка сохраняется без пересборки, в сборку идёт по «Подтвердить планировку» (`confirm`).
   *  Новая страница шлёт всегда; без поля (старая страница) — как раньше: правка подтверждена и сразу ставит пересборку `edit`. */
  draft: z.boolean().optional(),
});
export type TrialRoomEditIn = z.infer<typeof trialRoomEditIn>;
/** Правка, как её получает воркер при claim любой пересборки (накладывает на копию `result` перед сборкой). */
export type TrialRoomEdit = {
  panel: string; srcId: string; anchor: { x: number; y: number }; name: string; kind: string; wCm: number | null; dCm: number | null;
  built: boolean;
  /** «размеры верны» в окне подтверждения (T-20261111-16): сборка ставит комнате `user_dims` и без правки размера */
  dimsOk: boolean;
};

// ── Окна и двери агента на плане тура (план trial-room-edit-01, Е4; `db/init/029-trial-opening-edits.sql`) ─────────────────
export const TRIAL_OPENING_CM_MIN = 30;
export const TRIAL_OPENING_CM_MAX = 600;
export const TRIAL_OPENING_OPS_MAX = 30;
/** Одна правка проёма: `key` — `s<номер>` (распознанный, как его отдала страница) или `u<токен>` (новый, токен даёт страница);
 *  `c` — центр на стене, `w_cm` — ширина, см листа (`trial.panels[]`); `removed` — снять. */
export const trialOpeningOpIn = z.object({
  key: z.string().regex(/^(s\d{1,3}|u[A-Za-z0-9_-]{6,32})$/),
  kind: z.enum(["door", "window"]),
  c: z.tuple([z.number().finite(), z.number().finite()]),
  w_cm: z.number().finite().min(TRIAL_OPENING_CM_MIN).max(TRIAL_OPENING_CM_MAX),
  removed: z.boolean(),
});
/** «Сохранить» режима «Окна и двери»: все правки одной панели плана разом (`base_version` — версия данных, которую видит страница). */
export const trialOpeningEditIn = z.object({
  k: z.string().regex(/^[A-Za-z0-9_-]{22}$/),
  request_id: z.string().regex(/^[A-Za-z0-9_-]{8,64}$/),
  base_version: z.number().int().positive(),
  panel: z.string().min(1).max(40),
  ops: z.array(trialOpeningOpIn).min(1).max(TRIAL_OPENING_OPS_MAX),
  /** true — черновик (как у `trialRoomEditIn.draft`): без пересборки до «Подтвердить планировку». */
  draft: z.boolean().optional(),
});
export type TrialOpeningEditIn = z.infer<typeof trialOpeningEditIn>;
/** Правка проёма, как её получает воркер при claim любой пересборки (`tools/floorplan/opening_edits.py`). */
export type TrialOpeningEdit = {
  panel: string; key: string; srcIdx: number | null; srcC: [number, number] | null; kind: "door" | "window"; c: [number, number];
  widthCm: number; removed: boolean; built: boolean;
};

// ── «Подтвердить планировку» (план trial-confirm-plan-01; `db/init/032-trial-plan-confirm.sql`; T-20261111-16) ─────────────────
/** Кнопка: все черновики правок → подтверждены, ОДНА пересборка `edit` (и без черновиков). `rooms_ok` — комнаты страницы с галочкой
 *  «размеры верны» (их сборка получает `user_dims`: проверка размера снята, фото можно); комнаты без галочки — без этого флага
 *  (правка размера агентом — `user_dims` всегда). `request_id` — повтор нажатия даёт тот же ответ. */
export const trialConfirmIn = z.object({
  k: z.string().regex(/^[A-Za-z0-9_-]{22}$/),
  request_id: z.string().regex(/^[A-Za-z0-9_-]{8,64}$/),
  base_version: z.number().int().positive(),
  rooms_ok: z.array(trialPageRoomId).max(40),
});
export type TrialConfirmIn = z.infer<typeof trialConfirmIn>;
/** Состояние комнаты страницы в пересборке: ждёт / считается / посчитана (видна — с итоговой версией). */
export const trialRoomStatus = z.enum(["queued", "building", "ready"]);
export type TrialRoomStatus = z.infer<typeof trialRoomStatus>;
/** Ход пересборки от воркера (пульс аренды `…/rebuild/heartbeat`): состояния правленых комнат страницы и «N из M». */
export const trialRebuildProgressIn = z.object({
  rooms: z.record(trialPageRoomId, trialRoomStatus).refine((r) => Object.keys(r).length <= 60, { message: "too many rooms" }),
  done: z.number().int().nonnegative().max(60),
  total: z.number().int().nonnegative().max(60),
});
export type TrialRebuildProgressIn = z.infer<typeof trialRebuildProgressIn>;
/** Что отдаёт `GET /api/trial/<id>/rebuild-status?k=`: последняя пересборка тура (null — не было). Обратный отсчёт страница ведёт сама:
 *  от `elapsedS` (секунд с постановки на момент ответа) к `etaS` (оценка всего пересчёта; по комнате — `roomEtaS`). */
export type TrialRebuildStatus = {
  ok: true; version: number;
  rebuild: null | {
    id: string; kind: string; status: "queued" | "running" | "done" | "failed"; error: string | null;
    createdAt: string; startedAt: string | null; finishedAt: string | null; elapsedS: number;
    rooms: Record<string, TrialRoomStatus>; done: number; total: number; etaS: number | null; roomEtaS: Record<string, number>;
  };
};
/** Что отдаёт `GET /api/trial/<id>/edits?k=`: черновики правок (рисуются поверх плана с пометкой «не подтверждено»), комнаты с
 *  галочкой «размеры верны» и время последнего подтверждения. `room` — id комнаты страницы в текущей версии (null — не нашлась). */
/** Черновик, снятый при «Перечитать планировку» (T-20261111-16/2): `key` — id комнаты прочитанного плана или ключ проёма, `name` — имя
 *  комнаты из черновика или вид проёма (`door`/`window`); `code`: `gone` — комнаты или проёма в перечитанном плане нет (`why` — почему),
 *  `late` — правка пришла, пока план перечитывали. */
export type TrialDroppedDraft = { kind: "room" | "opening"; panel: string; key: string; name: string; code: "gone" | "late"; why: string };

export type TrialEditsView = {
  ok: true; version: number; drafts: number; confirmedAt: string | null; roomsOk: string[];
  /** Черновики, снятые перечитыванием плана после последнего подтверждения (пусто — ничего не снято). */
  dropped: TrialDroppedDraft[];
  rooms: { room: string | null; panel: string; srcId: string; name: string; kind: string; w_cm: number | null; d_cm: number | null }[];
  openings: { panel: string; key: string; kind: "door" | "window"; c: [number, number]; w_cm: number; removed: boolean }[];
};

const num = z.number().finite();
const pt = z.tuple([num, num]);
const ring = z.array(pt).min(3).max(4000);
const flags = z.array(z.string().max(60)).max(30);

const room = z.object({
  id: z.string().min(1).max(40),
  name: z.string().max(80),
  /** балкон / лоджия / терраса — `other` + флаг `outdoor` (за наружной стеной по тонким линиям листа — ещё `outdoor_outline`,
   *  `tools/floorplan/outdoor.py`, T-20261111-20): не обставляется, в масштаб квартиры не входит */
  kind: z.enum(["living", "bedroom", "kitchen", "bathroom", "hall", "other"]),
  contour: ring,
  bbox: z.object({ x: num, y: num, w: num.positive(), d: num.positive() }),
  /** площадь для показа: напечатанная на листе, если есть и годна (флаг `area_from_label`), иначе по контуру */
  areaM2: num.nonnegative(),
  /** площадь по контуру, когда показана подпись листа (`tools/floorplan/pipeline.py:area_shown`, T-20261111-12) */
  areaContourM2: num.nonnegative().optional(),
  dims: z.object({ w: num.positive(), d: num.positive(), src: z.enum(["plan", "listing"]) }).optional(),
  flags,
}).refine((r) => {
  // bbox — проекция контура (как `contracts/apartment.ts:room`): T5 возьмёт комнату без пересчёта
  const xs = r.contour.map((p) => p[0]), ys = r.contour.map((p) => p[1]);
  return Math.abs(Math.min(...xs) - r.bbox.x) < 1 && Math.abs(Math.min(...ys) - r.bbox.y) < 1 &&
    Math.abs(Math.max(...xs) - (r.bbox.x + r.bbox.w)) < 1 && Math.abs(Math.max(...ys) - (r.bbox.y + r.bbox.d)) < 1;
}, { message: "bbox must be the projection of contour" });

const panel = z.object({
  id: z.string().min(1).max(40),
  title: z.string().max(120),
  rooms: z.array(room).max(80),
  walls: z.array(z.object({ z0: num, z1: num, polys: z.array(z.object({ outer: ring, holes: z.array(ring).max(200) })).max(400) })).max(20),
  openings: z.array(z.object({ kind: z.enum(["door", "window", "opening"]), c: pt, widthCm: num.positive(), exterior: z.boolean() })).max(400),
});

export const floorplanResult = z.object({
  version: z.literal(1),
  units: z.literal("cm"),
  source: z.object({
    mime: z.enum(["image/jpeg", "image/png", "image/webp", "image/avif", "application/pdf"]),
    pages: z.number().int().min(1),
    usedPages: z.number().int().min(1),
    imageW: z.number().int().positive(),
    imageH: z.number().int().positive(),
  }),
  scale: z.object({
    /** опоры по порядку: подписи плана → размеры текстом → общая площадь (`area`, размеры примерные) → толщина стены */
    status: z.enum(["verified", "listing", "area", "not_verified"]),
    ppm: num.positive().nullable(),
    inliers: z.number().int().nonnegative(),
    n: z.number().int().nonnegative(),
    /** общая площадь, если найдена (у `area` — опора масштаба, иначе сверка): м² и откуда — текст, лист или оба */
    areaM2: num.positive().optional(),
    areaSrc: z.enum(["text", "sheet", "both"]).optional(),
  }),
  panels: z.array(panel).min(1).max(6),   // T-27/2: 4 → 6 (Nethercote: дом, постройки, 1-й, 2-й этаж, подвал)
  /** высота потолков из текста объявления, см (T-20261110-38: «Высота потолков 3,1 м»); нет — тур берёт 270 */
  ceilingCm: num.min(220).max(500).optional(),
  flags,
  timings: z.record(z.string().max(40), num.nonnegative()),
  costUsd: num.nonnegative(),
});
export type FloorplanResult = z.infer<typeof floorplanResult>;

// ── Тела ручек воркера DEV (Bearer TRIAL_WORKER_TOKEN) ─────────────────────────────────────────────
const workerId = z.string().regex(/^[A-Za-z0-9_.:-]{1,64}$/);
const lease = { id: z.string(), attempt: z.number().int().positive(), leaseToken: z.string().min(16).max(64) };
const spent = z.number().nonnegative().max(100).optional();

export const trialClaimIn = z.object({
  workerId,
  version: z.string().max(64).optional(),
  /** true — воркер сам себя притормозил: только отметиться «жив», задание не брать. */
  paused: z.boolean().optional(),
  /** true — воркер умеет пересборки «Обустроить» (`rebuild` в ответе); старый воркер их не получает. */
  rebuilds: z.boolean().optional(),
  /** true — воркер умеет и пересборки по тексту агента (`kind: "listing"`); без этого такие строки ему не отдаются. */
  listing: z.boolean().optional(),
  /** true — воркер умеет правки комнат (`kind: "edit"` и `edits` в каждой пересборке); без этого строки `edit` ему не отдаются. */
  edit: z.boolean().optional(),
  /** true — воркер умеет «перечитать планировку» (`kind: "reparse"`, оператор; T-20261111-02); без этого такие строки ему не отдаются. */
  reparse: z.boolean().optional(),
});
/** Аренда пересборки: `id` — id строки `trial_rebuilds` (не задания). */
export const trialRebuildLeaseIn = z.object({ ...lease, spentUsd: spent, progress: trialRebuildProgressIn.optional() });
export const trialRebuildFailIn = z.object({
  ...lease, code: trialRebuildFailCode, retryable: z.boolean(), detail: z.string().max(2000).optional(), spentUsd: spent,
});
export type TrialRebuildLease = Pick<z.infer<typeof trialRebuildLeaseIn>, "id" | "attempt" | "leaseToken">;
export type TrialRebuildFailIn = z.infer<typeof trialRebuildFailIn>;

/** Что получает воркер при claim пересборки: `rooms` — накопленные снятые комнаты задания вместе с этой пересборкой ("*" — все),
 *  `result` — сохранённый результат стен из Postgres (рабочие папки DEV чистятся по сроку). */
export type TrialRebuildClaimed = {
  id: string; jobId: string; attempt: number; leaseToken: string; leaseUntil: string; rooms: string[]; baseVersion: number;
  result: unknown;
  /** `listing` — пересборка по тексту агента: `listingText` — его текст (только воркеру), `baseVersion` — версия данных на момент claim. */
  kind: "furnish" | "listing" | "edit" | "reparse"; listingText?: string; inputMime?: string;
  /** `reparse` (оператор, T-20261111-02): `listingText` — ИСХОДНЫЙ текст объявления задания (может быть пустым), `bundle` — точные байты
   *  текущей версии данных страницы (`baseVersion`): сторож регресса сравнивает с ней новую страницу. */
  bundle?: string;
  /** Правки комнат задания (только воркеру, умеющему `edit`): накладываются на копию `result` перед любой сборкой. */
  edits?: TrialRoomEdit[];
  /** Окна и двери агента (тому же воркеру): накладываются после правок комнат. */
  openingEdits?: TrialOpeningEdit[];
  /** Только `reparse` (T-20261111-16/2): черновики, ни разу не подтверждённые, — в сборку не идут, их только переводят на новые номера. */
  draftEdits?: TrialRoomEdit[];
  draftOpeningEdits?: TrialOpeningEdit[];
  /** `edit` от «Подтвердить планировку» (T-20261111-16): пересобрать и без правленых комнат (пересчёт фото-права), не `no_match`. */
  confirm?: boolean;
};
export const trialHeartbeatIn = z.object({ ...lease, stage: trialStage, spentUsd: spent });
export const trialResultIn = z.object({ ...lease, result: z.unknown(), spentUsd: spent });
export const trialFailIn = z.object({
  ...lease, code: trialFailCode, retryable: z.boolean(), detail: z.string().max(2000).optional(), spentUsd: spent,
  /** Через сколько секунд снова отдавать задание (для `retryable`); по умолчанию 30. */
  retryAfterSec: z.number().int().min(1).max(3600).optional(),
});
export type TrialHeartbeatIn = z.infer<typeof trialHeartbeatIn>;
export type TrialFailIn = z.infer<typeof trialFailIn>;

/** Что получает воркер при claim. */
export type TrialClaimed = {
  id: string; kind: string; attempt: number; leaseToken: string; leaseUntil: string;
  inputMime: string; inputBytes: number; inputHash: string | null; listingText: string | null; budgetUsd: number;
};
