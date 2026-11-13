// Какие комнаты тура снимать автофото (T-20261112-115 Ф2, план tour-auto-photos-01 § Скоуп п.2; владелец 12.11 TG 1318/1355). Чистая функция
// по данным тура (bundle): комната с правом на фото (`photo_ok`, ready), с мебелью; гостиная первой, затем спальни по площади; не больше
// `max_rooms`; в комнате — АКТИВНЫЙ вариант так же, как его выбирает тур без выбора человека (`index.html:homeModel` → `mixShown`: первый стиль
// по порядку появления, точный вариант комнаты → карта замен `room_style_fallback`), два ракурса из `v.cams`. Не подошло — код отказа.
// Подпись варианта — то, от чего зависит кадр (размер и проёмы комнаты, предметы и декор): та же подпись при повторном подтверждении — та же
// задача (UNIQUE в `036`), снимать нечего.

import { createHash } from "node:crypto";
import { camsSigOf, photoCams, type PhotoCam } from "@/contracts/trial-photos";
import RULES from "@/tools/scout/rules/tour-auto-photos.json";

export type AutoRules = { max_rooms: number; shots_per_room: number; kind_order: string[]; quality: "realistic" | "draft";
  reserve_rub: number; tour_cap_rub: number; daily_cap_rub: number; daily_warn_rub: number; lease_s: number;
  retry_s: number; max_releases: number; urgent_window_s: number; max_tries: number };
export const AUTO_RULES = RULES as AutoRules;

export type AutoPick = { roomId: string; variantId: string; style: string; areaM2: number | null; ord: number; variantSig: string;
  cams: PhotoCam[]; camsSig: string };
export type AutoRefusal = { room: string; code: "no_active_variant" | "no_furniture" | "no_cams" | "max_rooms" | "bad_bundle" };

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const rnd = (v: unknown) => Math.round(Number(v) || 0) || 0;
const styleOf = (v: Obj) => str(v.style_id) || str(v.style);

/** Подпись расстановки варианта: комната (размер, проёмы), предметы (роль без номера, модель, товар, место, поворот, размеры, подъём, угол,
 *  секция, подвес), декор — порядок предметов не важен. Камеры не входят (у задачи своя подпись поз). */
export function variantSig(v: Obj, geo: Obj): string {
  const base = (s: unknown) => str(s).replace(/\s+\d+$/, "");
  const ent = arr(v.items).map((x) => { const it = obj(x), k = obj(it.sku);
    return JSON.stringify([base(it.role), str(k.msid) || str(k.sid), str(k.sid), rnd(it.x), rnd(it.y), ((rnd(it.rot) % 360) + 360) % 360,
      rnd(it.w), rnd(it.d), rnd(it.h), rnd(it.elev), it.corner ? 1 : 0, rnd(it.section), k.hung ? 1 : 0]); })
    .concat(arr(v.decor).map((x) => { const d = obj(x), k = obj(d.sku), w = obj(k.wall_at);
      return JSON.stringify(["декор", base(d.role), str(k.sid), str(w.wall), rnd(w.along), rnd(w.elev)]); }))
    .sort();
  const size = obj(v.room_size);
  const ops = arr(geo.openings).map((x) => { const o = obj(x);
    return JSON.stringify([str(o.kind), str(o.wall), rnd(o.offset_cm), rnd(o.width_cm), rnd(o.sill_cm), rnd(o.height_cm)]); }).sort();
  const canon = JSON.stringify(["auto1", [rnd(geo.w ?? size.w), rnd(geo.d ?? size.d)], ops, ent]);
  return `v1-${createHash("sha256").update(canon).digest("hex").slice(0, 32)}`;
}

/** Активный вариант комнаты без выбора человека: первый стиль тура → точный вариант → карта замен сборки. */
function activeVariant(variants: Obj[], fb: Obj, roomId: string, style0: string): Obj | undefined {
  const find = (s: string) => variants.find((v) => str(v.room_id) === roomId && styleOf(v) === s);
  return find(style0) ?? arr(obj(fb[roomId])[style0]).map(str).map(find).find(Boolean);
}

export function pickAutoRooms(bundle: unknown, rules: AutoRules = AUTO_RULES): { picks: AutoPick[]; refused: AutoRefusal[] } {
  const b = obj(bundle), geo = obj(b.rooms_geo), fb = obj(b.room_style_fallback);
  const variants = arr(b.variants).map(obj).filter((v) => !v.mine && !v.cid && styleOf(v) && geo[str(v.room_id)]);
  const style0 = variants.length ? styleOf(variants[0]!) : "";
  const area = new Map<string, number>();
  for (const p of arr(obj(b.trial).panels)) for (const r of arr(obj(p).rooms)) {
    const o = obj(r);
    if (typeof o.areaM2 === "number") area.set(str(o.id), o.areaM2);
  }
  const rooms = arr(b.apartment_rooms).map(obj)
    .filter((r) => r.photo_ok === true && r.furniture_state === "ready" && rules.kind_order.includes(str(r.kind)))
    .map((r, i) => ({ id: str(r.id), kind: str(r.kind), area: area.get(str(r.id)) ?? null, i }))
    .sort((a, b2) => rules.kind_order.indexOf(a.kind) - rules.kind_order.indexOf(b2.kind) || (b2.area ?? 0) - (a.area ?? 0) || a.i - b2.i);
  const picks: AutoPick[] = [], refused: AutoRefusal[] = [];
  for (const r of rooms) {
    const v = activeVariant(variants, fb, r.id, style0);
    if (!v) { refused.push({ room: r.id, code: "no_active_variant" }); continue; }
    if (!arr(v.items).length) { refused.push({ room: r.id, code: "no_furniture" }); continue; }
    const cams = photoCams.safeParse(arr(v.cams).slice(0, rules.shots_per_room));
    if (!cams.success || cams.data.length < rules.shots_per_room) { refused.push({ room: r.id, code: "no_cams" }); continue; }
    if (picks.length >= rules.max_rooms) { refused.push({ room: r.id, code: "max_rooms" }); continue; }
    picks.push({ roomId: r.id, variantId: str(v.id), style: styleOf(v), areaM2: r.area, ord: picks.length, variantSig: variantSig(v, obj(geo[r.id])),
      cams: cams.data, camsSig: camsSigOf(cams.data) });
  }
  return { picks, refused };
}
