// РЕНДЕР «СДЕЛАТЬ ФОТО» ИЗ ТУРА (T-20261117-19/1, план `photo-render-first-01` шаг 4). Бесплатный рендер Blender тех же двух ракурсов: право — то же,
// что у фото нейросети (комната с `photo_ok` в ПОСЛЕДНЕЙ версии данных задания, размеры страницы = данным, срок не вышел), но БЕЗ брони строки
// `trial_photos` и без квоты фото нейросети — у рендера свои пределы по адресу, туру и очереди (сервис кадров: `tools/scout/render_jobs.py`,
// отказ — до постановки с кодом и сроком повтора). Данные тура страница не присылает: приложение само вырезает из последней версии данных вариант
// и товары снимка и передаёт сервису кадров с внутренним ключом (`x-internal-token`) — сервис сверяет заказ с ними (`render_snapshot.py`).
// «Улучшить» — не здесь: это обычный заказ фото нейросети (`askPhoto`) с `render_key` из готового рендера.

import type { TrialRenderIn } from "@/contracts/trial";
import { trialDraftUrl } from "@/lib/trial/config";
import { photoRoomProblem, type DraftReply } from "@/lib/trial/repo-photo";
import { latestBundle, type LatestBundle } from "@/lib/trial/repo-bundle";
import { trialDir } from "@/lib/trial/config";

export type RenderAsk =
  | { ok: true; status: 200; body: Record<string, unknown> }
  | { ok: false; status: number; error: string; message?: string; messageEn?: string; retryAfter?: number };
export type RenderSend = (payload: Record<string, unknown>, ip: string) => Promise<DraftReply & { retryAfter?: number }>;

type Dict = Record<string, unknown>;
const isDict = (v: unknown): v is Dict => typeof v === "object" && v !== null && !Array.isArray(v);

/** Карточка товара — словарь с `name` и ключом: `sid` (/demo) или `msid` (тур: `sid` в публичных данных нет). Как `render_snapshot.sku_index` / `msid_index`. */
const hasSid = (v: Dict) => v.sid !== undefined && v.sid !== null;
const isCard = (v: Dict) => typeof v.name === "string" && (hasSid(v) || "msid" in v);   // `msid: null` — заглушка без модели (ковёр, обеденный стол): ключ один `name`
/** Ключ карточки: `s:<sid>` или `m:<msid>\u0000<name>` — пара (msid, name) (тур) ни с каким sid не смешивается. */
const cardKey = (v: Dict) => (hasSid(v) ? `s:${String(v.sid)}` : `m:${String(v.msid ?? "")}\u0000${String(v.name)}`);

/** Все карточки товаров внутри значения. Карточки без `sid` с одной парой (msid, name), но РАЗНЫМ содержимым не склеиваются (сервер должен увидеть
 *  двусмысленность и отказать); одинаковые — один раз. Карточки с `sid` — первое вхождение побеждает, как на сервере. */
function collectSkus(v: unknown, into: Map<string, Dict[]>): void {
  if (Array.isArray(v)) { for (const x of v) collectSkus(x, into); return; }
  if (!isDict(v)) return;
  if (isCard(v)) {
    const k = cardKey(v), cur = into.get(k);
    if (!cur) into.set(k, [v]);
    else if (!hasSid(v) && !cur.some((c) => JSON.stringify(c) === JSON.stringify(v))) cur.push(v);
  }
  for (const x of Object.values(v)) collectSkus(x, into);
}

/** Данные для сервиса кадров: ОДИН вариант задания, его комната, правила мягкого и только те товары, на которые ссылается заказ (или сам вариант).
 *  Нет такого варианта — null (наружу 404 `unknown_variant`). Размер — единицы КБ, а не вся версия данных. */
export function reduceSource(json: string, inp: Pick<TrialRenderIn, "variant_id" | "room_id" | "items">): Dict | null {
  let b: Dict;
  try { b = JSON.parse(json) as Dict; } catch { return null; }
  const variants = Array.isArray(b.variants) ? b.variants.filter(isDict) : [];
  const variant = variants.find((v) => v.id === inp.variant_id);
  if (!variant) return null;
  const all = new Map<string, Dict[]>();
  collectSkus(b, all);
  const wanted = new Map<string, Dict[]>();
  collectSkus(variant, wanted);
  for (const it of inp.items ?? []) {
    const k = it.sid !== undefined ? `s:${it.sid}` : `m:${it.msid ?? ""}\u0000${it.name}`;
    const cards = all.get(k);
    if (cards) wanted.set(k, cards);
  }
  const rid = String(variant.room_id ?? inp.room_id);
  const geo = isDict(b.rooms_geo) && isDict((b.rooms_geo as Dict)[rid]) ? (b.rooms_geo as Dict)[rid] : b.room;
  const rules = isDict(b.rules) && Array.isArray(b.rules.soft_roles) ? { soft_roles: b.rules.soft_roles } : {};
  // роли для проверки заказа — по всем вариантам: лёгкие копии вариантов без предметов (роль и товар), сами предметы чужих вариантов не нужны
  const roleStubs = variants.filter((v) => v !== variant).map((v) => ({ id: v.id, room_id: v.room_id, items: (Array.isArray(v.items) ? v.items : []).filter(isDict).map((i) => ({ role: i.role })) }));
  return { apartment_id: b.apartment_id, build: b.build, room: b.room, rooms_geo: { [rid]: geo }, rules, variants: [variant, ...roleStubs], _skus: [...wanted.values()].flat() };
}

/** Тело заказа сервису кадров: контракт снимка + номер тура + срезанные данные (только с внутренним ключом сервис им верит). */
export function renderPayload(id: string, inp: TrialRenderIn, source: Dict, prio = 0): Dict {
  const { mode: _mode, ...snap } = inp;
  void _mode;
  return { ...snap, trial: id, source_data: source, ...(prio ? { prio } : {}) };
}

/** Заказ рендера в сервис кадров с сервера приложения (внутренний ключ обязателен: без него сервис тур не принимает). */
export const sendToRender: RenderSend = async (payload, ip) => {
  const key = process.env.INTERNAL_API_TOKEN;
  if (!key) return { status: 503, body: null };
  try {
    const r = await fetch(`${trialDraftUrl()}/render/cycles`, {
      method: "POST", headers: { "content-type": "application/json", "x-internal-token": key, ...(ip ? { "x-forwarded-for": ip } : {}) },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(25_000),
    });
    const body = (await r.json().catch(() => null)) as Dict | null;
    const ra = Number(r.headers.get("retry-after"));
    return { status: r.status, body, ...(Number.isFinite(ra) && ra > 0 ? { retryAfter: ra } : {}) };
  } catch {
    return { status: 503, body: null };
  }
};

const gone = (status: number, error: string, message?: string, messageEn?: string): RenderAsk => ({ ok: false, status, error, ...(message ? { message } : {}), ...(messageEn ? { messageEn } : {}) });

/** Заказ рендера из тура. Проверки — до сервиса кадров (комната, версия, срок, вариант); дальше его отказы приходят как есть, с кодом и сроком повтора. */
export async function askRender(id: string, inp: TrialRenderIn, ip: string, send: RenderSend = sendToRender,
  load: (id: string, dir: string) => Promise<LatestBundle> = latestBundle, dir = trialDir()): Promise<RenderAsk> {
  const latest = await load(id, dir);
  if (latest === "expired") return gone(410, "expired");
  if (latest === "not_ready") return gone(409, "not_ready");
  const problem = photoRoomProblem(latest.json, inp.room_id, inp.room);
  if (problem) return gone(problem === "stale" ? 409 : 403, problem);
  const source = reduceSource(latest.json, inp);
  if (!source) return gone(404, "unknown_variant", "Такого варианта в туре нет. Обновите страницу.", "This variant is not in the tour. Reload the page.");
  const r = await send(renderPayload(id, inp, source), ip);
  const b = r.body;
  if (r.status === 200 && b && typeof b.job === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(b.job)) return { ok: true, status: 200, body: b };
  if (inp.check && r.status === 200 && b && typeof b.scene_hash === "string" && /^[0-9a-f]{64}$/.test(b.scene_hash)) return { ok: true, status: 200, body: b };   // проверка хеша: задания нет
  const code = typeof b?.code === "string" ? b.code : "render_unavailable";
  const msg = typeof b?.error === "string" ? b.error.slice(0, 300) : "Рендер сейчас недоступен. Попробуйте позже.";
  const en = typeof b?.error_en === "string" ? b.error_en.slice(0, 300) : "Rendering is unavailable right now. Try again later.";
  return { ok: false, status: r.status >= 400 && r.status < 600 ? r.status : 503, error: code, message: msg, messageEn: en,
    ...(r.retryAfter ? { retryAfter: r.retryAfter } : typeof b?.retry_after === "number" ? { retryAfter: b.retry_after } : {}) };
}
