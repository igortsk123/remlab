// Комнаты квартиры витрины для `/flat` (onb-11, ADR-0330 п.3): какой вариант в какой комнате и где комната стоит в 3D.
//
// ЗАЧЕМ. Раньше мост собирал одну гостиную (`roomId: "living"` жёстко), и спальни/кухня витрины в 3D не попадали. Теперь
// комната — это `room_id` варианта; комната без вариантов в данных не появляется (честно: «скоро» показывает витрина).
//
// ГЕОМЕТРИЯ — `rooms_geo[room_id]` сборки витрины (onb-07); у гостиной — `room` (её псевдоним, байт-в-байт прежний путь).
// Нет своей геометрии — нынешняя геометрия гостиной: комната видна и считается, размеры уточнит сборка.
//
// РАССТАНОВКА КОМНАТ — лесенкой: следующая комната правее И дальше предыдущей на зазор. Настоящего плана квартиры №215 у нас
// нет (схема — с чертежа №180, размеры не совпадают с замерами комнат), а наложение комнат ломало бы прогулку. В простой ряд
// нельзя: вид за окном — плоскость на 30 см за стеной шириной на 10 м в стороны (`openings.ts:skirtMesh`), в ряду она проходила
// сквозь соседнюю комнату (живая проверка 05.11 — улица на месте стены гостиной). Лесенкой плоскость любого окна лежит между
// комнатами. Гостиная всегда в (0,0) — её координаты прежние.

import { roomKind, type RoomKind } from "@/contracts/apartment";

export const LIVING = "living";
/** Зазор между комнатами лесенки по обеим осям, см: больше отступа вида за окном (`opening-ir.ts:VIEW_BACK_CM` + кайма). */
export const ROOM_GAP_CM = 100;

export type RoomGeo = {
  w?: number;
  d?: number;
  title?: string;
  height_cm?: number;
  window_view?: string;
  finish?: Record<string, { id?: string; colorHex?: string }>;
  openings?: {
    kind?: string; wall?: string; offset_cm?: number; width_cm?: number; sill_cm?: number; height_cm?: number;
    swing_cm?: number; hinge?: string; into?: boolean;
  }[];
};
type Variant = { id?: string; style?: string; room_id?: string; room_type?: string };
type RoomMeta = { id?: string; kind?: string; ordinal?: number; titleRu?: string; titleEn?: string };
type Data<V> = { room?: RoomGeo; rooms_geo?: Record<string, RoomGeo>; apartment_rooms?: RoomMeta[]; variants?: V[] };

/** Комната варианта (ADR-0330 п.3): `room_id`; у старой сборки поля нет — гостиная (как `index.html:roomOfV`). */
export const roomIdOf = (v: { room_id?: string }): string => v.room_id || LIVING;

/** Где комната в квартире и чем её обставить. `prefix` — к id мест и опций: у гостиной пусто, сохранённые подборы не сдвигаются. */
export type RoomAt<V> = {
  id: string;
  kind: RoomKind;
  titleRu: string;
  titleEn: string;
  geo: RoomGeo & { w: number; d: number };
  /** Юго-западный угол комнаты в квартире, см: к нему прибавляются места, ракурсы и старт прогулки. */
  ox: number;
  oy: number;
  prefix: string;
  variant: V;
};

const kindOf = (...xs: (string | undefined)[]): RoomKind => {
  for (const x of xs) {
    const k = roomKind.safeParse(x);
    if (k.success) return k.data;
  }
  return "living";
};

/**
 * Комнаты квартиры по вариантам витрины: в комнате открытого варианта — он сам, в остальных — вариант того же стиля, нет —
 * первый. Порядок: гостиная, дальше по `apartment_rooms[].ordinal`. `fits` — пригоден ли вариант (есть ли что поставить):
 * комната с пустым вариантом не появляется.
 */
export function planRooms<V extends Variant>(data: Data<V>, open: V, fits: (v: V) => boolean): RoomAt<V>[] {
  const vs = data.variants ?? [];
  const meta = new Map((data.apartment_rooms ?? []).filter((r) => r.id).map((r) => [r.id!, r]));
  const order = (id: string): number => (id === LIVING ? -1 : meta.get(id)?.ordinal ?? Number.MAX_SAFE_INTEGER);
  const ids = [...new Set([roomIdOf(open), ...vs.map(roomIdOf)])].map((id, i) => ({ id, i }))
    .sort((a, b) => order(a.id) - order(b.id) || a.i - b.i).map((x) => x.id);
  const out: RoomAt<V>[] = [];
  let ox = 0, oy = 0;
  for (const id of ids) {
    const mine = vs.filter((v) => roomIdOf(v) === id);
    const variant = id === roomIdOf(open) ? open : mine.find((v) => v.style === open.style && fits(v)) ?? mine.find(fits);
    if (!variant || !fits(variant)) continue;
    const own = id === LIVING ? data.room ?? data.rooms_geo?.[LIVING] : data.rooms_geo?.[id];
    const geo = own ?? data.room;
    if (!geo?.w || !geo?.d) continue;
    const m = meta.get(id);
    out.push({
      id,
      kind: id === LIVING ? "living" : kindOf(m?.kind, variant.room_type, id.replace(/-\d+$/, "")),
      // заголовок гостиной — прежний (`room.title`); чужая геометрия-заглушка свой заголовок комнате не даёт
      titleRu: id === LIVING ? geo.title ?? "Гостиная" : (own?.title ?? m?.titleRu ?? id),
      titleEn: id === LIVING ? "Living room" : m?.titleEn ?? id,
      geo: geo as RoomGeo & { w: number; d: number },
      ox,
      oy,
      prefix: id === LIVING ? "" : `${id}/`,
      variant,
    });
    ox += geo.w + ROOM_GAP_CM;
    oy += geo.d + ROOM_GAP_CM;
  }
  return out;
}
