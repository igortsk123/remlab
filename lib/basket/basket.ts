// КОРЗИНА СЕРТИФИКАТА (план demo-16 шаг 2, «Решения владельца 18.10», критика Codex 18.10). Избранное покупателя — глобальное
// между стилями, но своё у каждой квартиры (`remlab-basket:v2:<apartmentId>`). Сертификат считается ТОЛЬКО по тому, что
// включено: у комнаты ровно один включённый вариант (`includedByRoom`), остальные лежат в избранном без пометки.
// Чистые функции без DOM и сети: страница демо получает их отдельным маленьким модулем (`lib/basket/basket-bundle.ts`),
// деньги — тем же ядром `settle`, что окно и /flat. Цены — текущие: строки комнаты (`quote`) — только кэш со статусом свежести,
// страница обновляет их по коллекции с сервера (ADR-0254 п.6), неизвестная цена — «неполный итог», не ноль.
// `zod/mini` с именованными импортами: полный zod в стартовом модуле страницы весил бы ~330 КБ (замер Codex 18.10), этот — ~10 КБ.

import {
  array, boolean, enum as zenum, literal, maxLength, minimum, nullable, number, object, optional, record, refine, regex,
  safeParse, string, type infer as Infer,
} from "zod/mini";

import { budgetBucket } from "@/lib/configurator/budget";
import { settle, type BudgetPolicy, type Settlement, type SettlementLine, type SettlementTotals } from "@/lib/configurator/settlement";

const TOKEN = /^[A-Za-z0-9_-]{22}$/;
const ROOM = /^[a-z0-9-]{2,40}$/;

export const quoteLine = object({
  /** Уникален в комнате: `shop:<sid>` (одинаковые товары — одной покупкой с учётом упаковки), `dev:<группа>`. */
  chargeKey: string().check(maxLength(120)),
  roomId: string().check(regex(ROOM)),
  label: string().check(maxLength(200)),
  settlement: zenum(["allowance", "developer_surcharge", "property_price"]),
  /** В валюте карточки квартиры; `null` — цена неизвестна. */
  amount: nullable(number().check(minimum(0))),
  priceStatus: zenum(["known", "on_request", "unavailable"]),
  source: zenum(["shop", "developer"]),
  /** Бюджет пакета (demo-23) — для `allowance`; нет поля (кэш до demo-23) — мебель, пересчёт строк комнаты его проставит. */
  budgetBucket: optional(zenum(["furniture", "fitout"])),
});
export type QuoteLine = Infer<typeof quoteLine>;

/** Строки комнаты — кэш: `fresh` — посчитано по текущим ценам, `pending` — ещё не досчитано (миграция, сеть), `unavailable` —
 *  коллекция не открылась. Пустой `fresh` — комната без покупок; пустой `pending` — НЕ ноль (Codex 18.10 п.2). */
export const roomQuote = object({
  status: zenum(["fresh", "pending", "unavailable"]),
  currency: string().check(maxLength(3)),
  /** Курс показа рублёвых цен (у британского двойника): другой курс — суммы кэша неверны. */
  fx: optional(string().check(maxLength(40))),
  at: number(),
  lines: array(quoteLine).check(maxLength(200)),
});
export type RoomQuote = Infer<typeof roomQuote>;

export const favoriteRef = object({
  /** Номер коллекции на сервере (`/api/collections/<id>`): он же id избранного. */
  favoriteId: string().check(regex(TOKEN)),
  editToken: optional(nullable(string().check(regex(TOKEN)))),
  roomId: string().check(regex(ROOM)),
  roomKind: zenum(["kitchen", "bathroom", "bedroom", "living", "hall"]),
  styleId: string().check(maxLength(20)),
  stateId: string().check(maxLength(40)),
  sourceVariantId: string().check(maxLength(40)),
  displayName: string().check(maxLength(80)),
  /** Имя дано автоматически («Гостиная #2») — при миграции и переименовании комнаты его можно переписать; своё — нет. */
  autoName: boolean(),
  createdAt: number(),
  shot: optional(string().check(maxLength(200))),
  quote: roomQuote,
});
export type FavoriteRef = Infer<typeof favoriteRef>;

export const basketV2 = object({
  v: literal(2),
  apartmentId: string().check(regex(ROOM)),
  favorites: array(favoriteRef).check(maxLength(200)),
  /** Единственный источник выбора сертификата (Codex п.3): комната → включённый вариант. */
  includedByRoom: record(string().check(regex(ROOM)), string().check(regex(TOKEN))),
}).check(refine((b) => {
  const ids = new Set(b.favorites.map((f) => f.favoriteId));
  if (ids.size !== b.favorites.length) return false;
  // включённый вариант — избранное ЭТОЙ комнаты этой корзины
  return Object.entries(b.includedByRoom).every(([room, id]) => b.favorites.some((f) => f.favoriteId === id && f.roomId === room));
}, "избранное повторяется или включён вариант другой комнаты"));
export type BasketV2 = Infer<typeof basketV2>;

export const emptyBasket = (apartmentId: string): BasketV2 => ({ v: 2, apartmentId, favorites: [], includedByRoom: {} });

/**
 * Корзина из хранилища браузера. Битое не роняет страницу и не обнуляет всё: годные записи остаются, повторы и чужие
 * включения снимаются, корзина другой квартиры — пустая этой.
 */
export function loadBasket(raw: unknown, ctx: { apartmentId: string; currency: string; fx?: string }): BasketV2 {
  const ok = safeParse(basketV2, raw);
  const b = ok.success ? ok.data : repair(raw, ctx.apartmentId);
  if (b.apartmentId !== ctx.apartmentId) return emptyBasket(ctx.apartmentId);
  // валюта или курс карточки сменились — числа кэша в другой валюте: сбрасываем, досчитаем заново (не показываем £100 000 вместо ₽, Codex 18.10)
  const same = (q: RoomQuote) => q.currency === ctx.currency && (q.fx ?? "") === (ctx.fx ?? "");
  return { ...b, favorites: b.favorites.map((f) => same(f.quote) ? f : { ...f, quote: { status: "pending" as const, currency: ctx.currency, at: 0, lines: [] } }) };
}

function repair(raw: unknown, apartmentId: string): BasketV2 {
  const r = (raw && typeof raw === "object" ? raw : {}) as { apartmentId?: unknown; favorites?: unknown; includedByRoom?: unknown };
  if (r.apartmentId !== apartmentId) return emptyBasket(apartmentId);
  const favs: FavoriteRef[] = [];
  for (const f of Array.isArray(r.favorites) ? r.favorites : []) {
    const p = safeParse(favoriteRef, f);
    if (p.success && !favs.some((x) => x.favoriteId === p.data.favoriteId)) favs.push(p.data);
  }
  favs.splice(200);                                    // сперва обрезка, потом включения — не ссылаемся на отрезанное (Codex 18.10)
  const inc: Record<string, string> = {};
  const src = r.includedByRoom && typeof r.includedByRoom === "object" ? (r.includedByRoom as Record<string, unknown>) : {};
  for (const [room, id] of Object.entries(src)) if (favs.some((f) => f.favoriteId === id && f.roomId === room)) inc[room] = id as string;
  return { v: 2, apartmentId, favorites: favs, includedByRoom: inc };
}

// ——— строки комнаты

export type QuoteSku = { sid?: string; name?: string; price?: number; pack?: number; unavailable?: boolean };
export type QuoteOption = {
  id: string; roomKind: string; roomId: string | null; title: string; settlement: Settlement; defaultVariantId: string;
  /** Вид группы (`optionGroup.kind`) — из него бюджет пакета (demo-23); нет — мебель, как до двух бюджетов. */
  kind?: string;
  variants: { id: string; name?: string; price: { type: string; amount: number | null } }[];
};

/**
 * Строки комнаты из её состава: товары (мебель и декор) — одной строкой на товар, сколько упаковок купить (как список
 * мебели страницы); опции застройщика — только группы ЭТОЙ комнаты (`roomId`, у старых данных — по типу комнаты). Цена
 * товара — в рублях витрины, `toCard` переводит в валюту карточки. Пропавший товар и исчезнувший вариант опции — `unavailable`.
 */
export function quoteRoom(p: {
  roomId: string; roomKind: string; currency: string; at: number; fx?: string;
  items: { role: string; sku?: QuoteSku }[]; decor: { role: string; sku?: QuoteSku }[];
  developerOptions: Record<string, string>; options: QuoteOption[]; toCard: (rub: number) => number;
}): RoomQuote {
  const lines: QuoteLine[] = [];
  const bySku = new Map<string, { sku: QuoteSku; slots: number; role: string }>();
  for (const it of [...p.items, ...p.decor]) {
    const s = it.sku; if (!s || !(s.sid || s.name)) continue;
    const k = s.sid ? `shop:${s.sid}` : `shop:name:${String(s.name).slice(0, 100)}`;
    const g = bySku.get(k) ?? { sku: s, slots: 0, role: it.role };
    g.slots += 1; bySku.set(k, g);
  }
  for (const [k, g] of bySku) {
    const pack = g.sku.pack && g.sku.pack > 0 ? g.sku.pack : 1, buys = Math.ceil(g.slots / pack);
    const known = !g.sku.unavailable && typeof g.sku.price === "number" && g.sku.price > 0;
    lines.push({ chargeKey: k, roomId: p.roomId, label: String(g.sku.name ?? g.role).slice(0, 200), settlement: "allowance",
      amount: known ? Math.round(p.toCard(g.sku.price! * buys)) : null, priceStatus: known ? "known" : "unavailable", source: "shop",
      budgetBucket: budgetBucket({ source: "shop" }) });
  }
  for (const g of p.options) {
    if (g.roomId ? g.roomId !== p.roomId : g.roomKind !== p.roomKind) continue;
    const vid = p.developerOptions[g.id] ?? g.defaultVariantId, v = g.variants.find((x) => x.id === vid);
    const base = { chargeKey: `dev:${g.id}`, roomId: p.roomId, label: g.title.slice(0, 200), settlement: g.settlement, source: "developer" as const,
      ...(g.settlement === "allowance" ? { budgetBucket: g.kind ? budgetBucket({ groupKind: g.kind }) : "furniture" as const } : {}) };
    if (!v) { lines.push({ ...base, amount: null, priceStatus: "unavailable" }); continue; }   // вариант исчез — не молча «по умолчанию»
    if (v.price.type === "included") continue;
    if (v.price.type === "surcharge" && typeof v.price.amount === "number") lines.push({ ...base, amount: Math.round(v.price.amount), priceStatus: "known" });
    else lines.push({ ...base, amount: null, priceStatus: "on_request" });
  }
  return { status: "fresh", currency: p.currency, at: p.at, lines, ...(p.fx ? { fx: p.fx } : {}) };
}

// ——— итоги

export type BasketTotals = SettlementTotals & {
  /** Все строки сертификата известны — можно сравнивать с лимитом. */
  allowanceComplete: boolean;
  /** Известны все строки, включая доплаты застройщику. */
  complete: boolean;
  /** Комнаты, у которых строки не досчитаны (кэш устарел или пуст). */
  pendingRooms: string[];
  rooms: number;
};

/** Пакет: политика двух бюджетов (demo-23) или число — прежний контракт (одна сумма, всё в мебели, перерасход — отказ). */
export type Limit = number | BudgetPolicy;

function totalsOf(quotes: { roomId: string; quote: RoomQuote }[], limit: Limit): BasketTotals {
  const lines: SettlementLine[] = [];
  let allowanceComplete = true, complete = true;
  const pendingRooms: string[] = [];
  for (const { roomId, quote } of quotes) {
    if (quote.status !== "fresh") { pendingRooms.push(roomId); allowanceComplete = false; complete = false; }
    for (const l of quote.lines) {
      const unknown = l.priceStatus !== "known" || l.amount == null;
      if (unknown) { complete = false; if (l.settlement === "allowance") allowanceComplete = false; }
      lines.push({ amount: l.amount ?? 0, settlement: l.settlement, onRequest: unknown, label: l.label,
        ...(l.budgetBucket ? { budgetBucket: l.budgetBucket } : {}) });
    }
  }
  return { ...settle(lines, limit), allowanceComplete, complete, pendingRooms, rooms: quotes.length };
}

const included = (b: BasketV2, exceptRoom?: string) => Object.entries(b.includedByRoom)
  .filter(([room]) => room !== exceptRoom)
  .map(([roomId, id]) => ({ roomId, quote: b.favorites.find((f) => f.favoriteId === id)!.quote }));

/** Сумма сертификата по корзине: только включённые варианты комнат. */
export const basketTotals = (b: BasketV2, limit: Limit): BasketTotals => totalsOf(included(b), limit);

/** Плашка окна: корзина без этой комнаты и она же с черновиком окна вместо комнаты («с этой гостиной»). Замена, не сложение. */
export function preview(b: BasketV2, roomId: string, draft: RoomQuote, limit: Limit): { base: BasketTotals; with: BasketTotals } {
  const rest = included(b, roomId);
  return { base: totalsOf(rest, limit), with: totalsOf([...rest, { roomId, quote: draft }], limit) };
}

// ——— решения (ворота лимита — только здесь, UI `includedByRoom` руками не меняет; Codex п.4)

/** Доплата покупателя сверх пакета: всего и по бюджетам (в `split` перенос запрещён — доплата может быть при остатке в другом). */
export type Topup = { overBy: number; furniture: number; fitout: number };

export type Decision =
  | { kind: "included" }
  /** Место в комнате занято; `topup` — с этим вариантом пакет будет превышен (demo-23: включить можно, с подтверждением доплаты). */
  | { kind: "ask_replace"; currentId: string; topup?: Topup }
  /** demo-23: перерасход — не отказ, а доплата покупателя; включается только с его явным подтверждением (`include(…, {confirmTopup})`). */
  | { kind: "included_with_topup"; overBy: number; topup: Topup }
  /** Прежний контракт (лимит числом — страница до шага 3 demo-23): сверх сертификата не включаем. */
  | { kind: "over_limit"; overBy: number }
  | { kind: "price_pending" };

/** Что будет, если включить этот вариант комнаты: сперва цена и лимит, потом — пусто ли место (Codex п.5). */
export function evaluate(b: BasketV2, roomId: string, candidate: RoomQuote, limit: Limit): Decision {
  const t = preview(b, roomId, candidate, limit).with;
  if (candidate.status !== "fresh" || !candidate.lines.every((l) => l.settlement !== "allowance" || l.priceStatus === "known")) return { kind: "price_pending" };
  const cur = b.includedByRoom[roomId];
  if (t.allowanceOverage > 0) {
    if (typeof limit === "number") return { kind: "over_limit", overBy: t.allowanceOverage };
    const topup = { overBy: t.budget.overage.total, furniture: t.budget.overage.furniture, fitout: t.budget.overage.fitout };
    return cur ? { kind: "ask_replace", currentId: cur, topup } : { kind: "included_with_topup", overBy: topup.overBy, topup };
  }
  return cur ? { kind: "ask_replace", currentId: cur } : { kind: "included" };
}

export const MAX_FAVORITES = 200;

/** Новое — первым. Сверх 200 уходит самое старое НЕвключённое: включённые в сертификат не теряются (Codex 18.10). */
export function addFavorite(b: BasketV2, f: FavoriteRef): BasketV2 {
  const list = [f, ...b.favorites.filter((x) => x.favoriteId !== f.favoriteId)];
  const inc = new Set(Object.values(b.includedByRoom));
  while (list.length > MAX_FAVORITES) {
    let k = -1;
    for (let i = list.length - 1; i > 0; i--) if (!inc.has(list[i]!.favoriteId) && (k < 0 || list[i]!.createdAt < list[k]!.createdAt)) k = i;
    if (k < 0) break;
    list.splice(k, 1);
  }
  return { ...b, favorites: list };
}

export type IncludeResult = { basket: BasketV2; result: "included" | "included_with_topup" | "topup_unconfirmed" | "over_limit" | "price_pending";
  overBy?: number; topup?: Topup };

/**
 * Включить вариант в пакет: единственные ворота лимита. Цена не досчитана — корзина не меняется. Сверх пакета: с политикой
 * (demo-23) — включается только с `confirmTopup` (иначе `topup_unconfirmed`, корзина та же); с лимитом числом — отказ, как раньше.
 */
export function include(b: BasketV2, favoriteId: string, limit: Limit, opts: { confirmTopup?: boolean } = {}): IncludeResult {
  const f = b.favorites.find((x) => x.favoriteId === favoriteId);
  if (!f) return { basket: b, result: "price_pending" };
  const d = evaluate(b, f.roomId, f.quote, limit);
  if (d.kind === "price_pending") return { basket: b, result: d.kind };
  if (d.kind === "over_limit") return { basket: b, result: d.kind, overBy: d.overBy };
  const topup = d.kind === "included_with_topup" || d.kind === "ask_replace" ? d.topup : undefined;
  if (topup && !opts.confirmTopup) return { basket: b, result: "topup_unconfirmed", overBy: topup.overBy, topup };
  const basket = { ...b, includedByRoom: { ...b.includedByRoom, [f.roomId]: favoriteId } };
  return topup ? { basket, result: "included_with_topup", overBy: topup.overBy, topup } : { basket, result: "included" };
}

/** Снять комнату из расчёта (вариант остаётся в избранном). */
export function exclude(b: BasketV2, roomId: string): BasketV2 {
  const { [roomId]: _gone, ...rest } = b.includedByRoom;
  return { ...b, includedByRoom: rest };
}

/** Убрать из избранного. Был включён — включается СТАРЕЙШИЙ оставшийся вариант комнаты, если влезает; нет — комната пустая
 *  (к следующему молча не перескакиваем, Codex п.6). */
export function removeFavorite(b: BasketV2, favoriteId: string, limit: Limit): BasketV2 {
  const f = b.favorites.find((x) => x.favoriteId === favoriteId);
  if (!f) return b;
  const wasIncluded = b.includedByRoom[f.roomId] === favoriteId;
  let next: BasketV2 = { ...b, favorites: b.favorites.filter((x) => x.favoriteId !== favoriteId) };
  if (!wasIncluded) return next;
  next = exclude(next, f.roomId);
  const oldest = next.favorites.filter((x) => x.roomId === f.roomId).sort((a, c) => a.createdAt - c.createdAt)[0];
  return oldest ? include(next, oldest.favoriteId, limit).basket : next;
}

export function updateQuote(b: BasketV2, favoriteId: string, quote: RoomQuote): BasketV2 {
  return { ...b, favorites: b.favorites.map((f) => f.favoriteId === favoriteId ? { ...f, quote } : f) };
}

export function rename(b: BasketV2, favoriteId: string, name: string): BasketV2 {
  const n = name.trim().slice(0, 80);
  return n ? { ...b, favorites: b.favorites.map((f) => f.favoriteId === favoriteId ? { ...f, displayName: n, autoName: false } : f) } : b;
}

/** «Гостиная #N»: N — наибольший занятый номер этой комнаты + 1 (после удаления «#2» новый не повторит «#3»). */
export function nextName(b: BasketV2, roomId: string, title: string): string {
  let n = 0;
  for (const f of b.favorites) {
    if (f.roomId !== roomId || !f.displayName.startsWith(title + " #")) continue;
    const k = Number(f.displayName.slice(title.length + 2));
    if (Number.isInteger(k) && k > n) n = k;
  }
  return `${title} #${n + 1}`;
}

// ——— перенос избранного demo-15 (один глобальный список `remlab-favorites`, все — гостиные)

export type FavoriteV1 = { collectionId: string; editToken?: string | null; displayName?: string; style?: string; stateId?: string | null;
  sourceVariantId?: string | null; createdAt?: number; shot?: string };

/**
 * Старые записи одной квартиры → корзина. Квартиру каждой записи страница узнаёт по коллекции с сервера (у старого списка её
 * нет). Автоимя — эвристика: «<Стиль> #N» с известным стилем считается автоматическим и переписывается в «<Комната> #k» по
 * порядку создания; совпавшее по форме своё имя неотличимо (зафиксировано тестом). Ничего не включаем — «0 на старте».
 */
export function migrateV1(b: BasketV2, list: (FavoriteV1 & { styleId: string })[], room: { id: string; kind: FavoriteRef["roomKind"]; title: string },
  styleTitles: string[], currency: string): BasketV2 {
  const auto = (nm: string) => styleTitles.some((t) => new RegExp(`^${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} #\\d+$`, "i").test(nm.trim()));
  let next = b;
  for (const o of [...list].sort((x, y) => (x.createdAt ?? 0) - (y.createdAt ?? 0))) {
    if (!TOKEN.test(o.collectionId) || next.favorites.some((f) => f.favoriteId === o.collectionId)) continue;
    const nm = String(o.displayName ?? "").trim(), isAuto = !nm || auto(nm);
    next = addFavorite(next, {
      favoriteId: o.collectionId, editToken: o.editToken && TOKEN.test(o.editToken) ? o.editToken : null, roomId: room.id, roomKind: room.kind,
      styleId: o.styleId.slice(0, 20), stateId: String(o.stateId ?? "").slice(0, 40), sourceVariantId: String(o.sourceVariantId ?? "").slice(0, 40),
      displayName: isAuto ? nextName(next, room.id, room.title) : nm.slice(0, 80), autoName: isAuto, createdAt: o.createdAt ?? 0,
      ...(o.shot ? { shot: o.shot.slice(0, 200) } : {}),
      quote: { status: "pending", currency, at: 0, lines: [] },
    });
  }
  return next;
}

