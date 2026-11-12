// T-20261112-64 (план living-full-01, Т1 шаг 2 «наблюдение», совет Codex § 7): ФАКТЫ «в цене ↔ в 3D» по живым данным витрины —
// тем же кодом, что строит сцену страницы. Только чтение, ничего не публикует.
//
// ЦЕНА — правило страницы (`tools/scout/flat215-demo/index.html`): `productsOf` = предметы с `sku.name` (один товар — одна строка,
// ключ `prodKey`: sid, иначе ссылка+название; количество `buys` = ceil(мест / упаковку)) + декор с `sku.name` (по штуке);
// варианты — не больше `MAXV` = 6 на комнату (`catalogVariants`); вариант отказанной комнаты тура страница опустошает (`varRefused`).
// 3D — путь живой сцены: декор в сцену без мягкого и «только в списке» (`liveDecor`: `rules.soft_roles`, `list_only`) →
// `demo-scene.ts:liveApartment` (мост `fromDemoVariant`) → `resolve.ts:resolveScene` (ваза без опоры, лишняя картина — `unplaced`) →
// `build-scene.ts:planObjects` (что рисуется). Телевизор над тумбой — производный объект сцены, не товар: в цене его нет.
//
// Сборка и запуск (node 20, без tsx): esbuild из корня репо, `@/` — по tsconfig, пакеты — NODE_PATH:
//   NODE_PATH=<repo>/node_modules <repo>/node_modules/.bin/esbuild tools/scout/priced_vs_3d_scene.ts --bundle --platform=node
//     --format=esm --outfile=<tmp>/scene.mjs && node <tmp>/scene.mjs <demo-data.json> [...] > facts.json
// Вывод — JSON {файл: {variants: [{id, room_id, style, rows: [...]}]}}; разбор причин и итоги — `priced_vs_3d.py`.

import { readFileSync } from "node:fs";
import { fromDemoVariant, isCeilingDecor, isWallArtDecor, isWallPlane, stableSlotIds, wallArtItems } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { planObjects } from "@/lib/viewer3d/build-scene";

type Sku = { name?: string; price?: number; sid?: string; url?: string; msid?: string; pack?: number; w?: number; d?: number; h?: number };
type Entry = { role?: string; sku?: Sku; w?: number; d?: number; h?: number; strategy?: string; list_only?: boolean };
type Variant = { id?: string; room_id?: string; room?: unknown; style?: string; items?: Entry[]; decor?: Entry[]; furniture_state?: string };
type Data = { room?: object; rooms_geo?: Record<string, object>; variants?: Variant[]; rules?: { soft_roles?: string[] };
  trial?: { goods?: unknown }; apartment_rooms?: { id?: string; furniture_outcome?: string; furniture_code?: string; furniture_state?: string }[] };

const MAXV = 6;
const SOFT_DEF = ["плед", "подушка", "покрывало", "полка", "шторы"];
const CTX = { apartmentId: "demo-live", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "https://x/demo/" };
// исход комнаты тура → отказ (копия таблицы страницы `TR_OUT`/`TR_NONE`, только «отказные» коды)
const TR_OUT: Record<string, string> = { refused: "no_products", failed: "no_products", no_products: "no_products", scale_unverified: "no_products",
  no_window: "no_products", not_readable: "not_readable", no_entry: "not_readable", no_space: "no_space", no_space_walkthrough: "no_space",
  not_furnished: "not_furnished", none: "not_furnished", largest_living_only: "not_furnished", room_kind_not_furnished: "not_furnished",
  one_living_furnished: "not_furnished", size_unverified: "awaiting", awaiting_check: "awaiting" };

const base = (r?: string): string => String(r ?? "").replace(/\s+\d+$/, "").trim();
const roomIdOf = (v: Variant): string => String(v.room_id || (typeof v.room === "string" ? v.room : "") || "living");
const prodKey = (p: Sku): string => (p.sid ? `sid:${p.sid}` : `${p.url ?? ""}|${p.name ?? ""}`);
const packOf = (p: Sku): number => (p.pack && +p.pack > 0 ? +p.pack : 1);
const isRug = (e: Entry): boolean => base(e.role).startsWith("ковёр");

function refused(D: Data, v: Variant): boolean {
  if (!D.trial) return false;
  const r = (D.apartment_rooms ?? []).find((x) => x?.id === roomIdOf(v));
  const o = r ? TR_OUT[r.furniture_outcome ?? ""] ?? TR_OUT[r.furniture_code ?? ""] ?? TR_OUT[r.furniture_state ?? ""] : undefined;
  return /^(no_products|no_space|not_readable|not_furnished|awaiting)$/.test(o ?? "")
    || (/^(failed|none|no_products|not_furnished|refused)$/.test(v.furniture_state ?? "") && !(v.items ?? []).length);
}

/** Слоты сцены для каждого исходного предмета/декора — та же нумерация, что у моста (`fromDemo.ts:roomPart`). */
function slotMap(items: Entry[], live: Entry[]): { items: string[][]; decor: Map<number, string> } {
  const out: string[][] = items.map(() => []);
  const placeable = items.map((it, i) => ({ it, i })).filter(({ it }) => it.w && it.d && it.h && it.sku?.msid && !isWallPlane(it));
  stableSlotIds(placeable.map(({ it }) => it)).forEach((id, k) => out[placeable[k]!.i]!.push(id));
  items.map((it, i) => ({ it, i })).filter(({ it }) => isRug(it) && it.w && it.d).forEach(({ i }, k) => out[i]!.push(`ковёр#${k}`));
  const planesI = items.map((it, i) => ({ it, i })).filter(({ it }) => isWallPlane(it));
  const art = live.map((x, k) => ({ x, k })).filter(({ x }) => isWallArtDecor(x));
  const artItems = wallArtItems(art.map(({ x }) => x));
  const planeIds = stableSlotIds([...planesI.map(({ it }) => it), ...artItems]);
  planesI.forEach(({ i }, j) => out[i]!.push(planeIds[j]!));
  const decor = new Map<number, string>();
  art.forEach(({ k }, j) => decor.set(k, planeIds[planesI.length + j]!));
  const tab = live.map((x, k) => ({ x, k }))
    .filter(({ x }) => !x.list_only && !isWallArtDecor(x) && !isCeilingDecor(x) && x.sku?.msid && x.sku.w && x.sku.d && x.sku.h);
  stableSlotIds(tab.map(({ x }) => ({ role: x.role ?? "декор" }))).forEach((id, j) => decor.set(tab[j]!.k, `decor:${id}`));
  // люстра — слот на потолке (`fromDemo.ts` «ЛЮСТРА ИЗ ДЕКОРА ВАРИАНТА», T-20261112-66)
  const lights = live.map((x, k) => ({ x, k })).filter(({ x }) => isCeilingDecor(x));
  stableSlotIds(lights.map(({ x }) => ({ role: x.role ?? "люстра" }))).forEach((id, j) => decor.set(lights[j]!.k, `ceiling:${id}`));
  return { items: out, decor };
}

function variantFacts(D: Data, v: Variant) {
  const soft = new Set(D.rules?.soft_roles ?? SOFT_DEF);
  const isSoft = (r?: string): boolean => soft.has(base(r));
  const isRefused = refused(D, v);
  const items = isRefused ? [] : v.items ?? [];
  const decorAll = isRefused ? [] : (v.decor ?? []).map((x, i) => ({ x, i })).filter(({ x }) => x.sku?.name);
  const liveIdx = decorAll.filter(({ x }) => !isSoft(x.role) && !x.list_only);
  const live = liveIdx.map(({ x }) => x);
  const room = (D.rooms_geo ?? {})[roomIdOf(v)] ?? (roomIdOf(v) === "living" || !D.rooms_geo ? D.room : undefined) ?? D.room;
  let rendered = new Set<string>(), unplaced = new Set<string>(), error = "";
  try {
    const built = fromDemoVariant({ room, variants: [{ id: "live", items, decor: live }] } as never, "live", CTX);
    if (built) {
      const sc = resolveScene(built.apartment, built.catalogue, defaultConfiguration(built.apartment, built.catalogue));
      unplaced = new Set(sc.items.filter((i) => i.unplaced).map((i) => i.slotId));
      rendered = new Set(planObjects(built.apartment, built.catalogue, sc).map((o) => o.slotId));
    } else error = "мост не собрал квартиру (нет предметов с моделью)";
  } catch (e) {
    error = `сцена упала: ${(e as Error).message}`.slice(0, 300);
  }
  const map = slotMap(items, live);
  const rows: object[] = [];
  // предметы — группой по товару, как строка списка страницы
  const groups = new Map<string, { sku: Sku; role?: string; idx: number[] }>();
  items.forEach((it, i) => {
    if (!it.sku?.name) return;
    const k = prodKey(it.sku);
    if (!groups.has(k)) groups.set(k, { sku: it.sku, role: it.role, idx: [] });
    groups.get(k)!.idx.push(i);
  });
  for (const g of groups.values()) {
    const slots = g.idx.map((i) => map.items[i]!);
    const shown = g.idx.filter((_, j) => slots[j]!.some((s) => rendered.has(s))).length;
    const it0 = items[g.idx[0]!]!;
    rows.push({ src: "item", role: g.role, name: g.sku.name, sid: g.sku.sid ?? null, price: g.sku.price ?? 0,
      qty: Math.ceil(g.idx.length / packOf(g.sku)), pack: packOf(g.sku), slots: g.idx.length, shown,
      qty_shown: Math.ceil(shown / packOf(g.sku)), has_msid: !!g.sku.msid, dims_ok: !!(it0.w && it0.d && it0.h),
      rug: isRug(it0), wall_plane: isWallPlane(it0), strategy: it0.strategy ?? null,
      unplaced: slots.flat().some((s) => unplaced.has(s)), slot_ids: slots.flat() });
  }
  const liveSet = new Set(liveIdx.map(({ i }) => i));
  decorAll.forEach(({ x, i }) => {
    const k = liveIdx.findIndex((y) => y.i === i);
    const slot = k >= 0 ? map.decor.get(k) : undefined;
    rows.push({ src: "decor", role: x.role, name: x.sku!.name, sid: x.sku!.sid ?? null, price: x.sku!.price ?? 0, qty: 1, slots: 1,
      shown: slot && rendered.has(slot) ? 1 : 0, has_msid: !!x.sku!.msid, dims_ok: !!(x.sku!.w && x.sku!.d && x.sku!.h),
      soft: isSoft(x.role), list_only: !!x.list_only, in_scene_input: liveSet.has(i), wall_art: isWallArtDecor(x),
      strategy: x.strategy ?? null, unplaced: !!slot && unplaced.has(slot), slot_ids: slot ? [slot] : [] });
  });
  return { id: v.id, room_id: roomIdOf(v), style: v.style ?? null, refused: isRefused, error, rows };
}

const out: Record<string, object> = {};
for (const f of process.argv.slice(2)) {
  const D = JSON.parse(readFileSync(f, "utf8")) as Data;
  const per = new Map<string, number>();
  const vs = (D.variants ?? []).filter((v) => {
    const r = roomIdOf(v);
    per.set(r, (per.get(r) ?? 0) + 1);
    return per.get(r)! <= MAXV;
  });
  out[f] = { trial: !!D.trial, goods: !!D.trial?.goods, hidden_over_maxv: (D.variants ?? []).length - vs.length,
    variants: vs.map((v) => variantFacts(D, v)) };
}
process.stdout.write(JSON.stringify(out));
