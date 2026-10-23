// Геометрия квартиры для 3D-конфигуратора (план apartment-3d-configurator, ADR-0211).
//
// КАНОН КООРДИНАТ — тот же, что у планировщика и серверного рендера
// (`services/planner-solver/planner/models.py:1-8`, `tools/scout/scene_mesh.py:61-83`):
//   сантиметры; x — вправо, y — вглубь; x/y предмета = ЦЕНТР footprint;
//   rot — градусы ПО ЧАСОВОЙ, 0 → лицом в +y.
// Отличие от демо: координаты общие по КВАРТИРЕ, а не по одной комнате. Комната — прямоугольник
// (x,y) = её юго-западный угол. Перевод в комнатные координаты для фото-конвейера — `toRoomLocal`.

import { z } from "zod";

export const roomKind = z.enum(["living", "kitchen", "bathroom", "bedroom", "hall"]);
export type RoomKind = z.infer<typeof roomKind>;

export const wallSide = z.enum(["north", "south", "east", "west"]);
export type WallSide = z.infer<typeof wallSide>;

/** Проём в стене комнаты: offsetCm — от начала стены (запад→восток / юг→север). */
export const opening = z.object({
  // balcony — балконная дверь (остеклённая, до пола); один набор видов с `planner/models.py:Opening` (demo-04)
  kind: z.enum(["door", "window", "opening", "balcony"]),
  wall: wallSide,
  offsetCm: z.number().nonnegative(),
  widthCm: z.number().positive(),
  sillCm: z.number().nonnegative().optional(), // подоконник; у двери нет
  heightCm: z.number().positive().optional(),
  swingCm: z.number().nonnegative().optional(), // глубина зоны открывания внутрь комнаты; 0 — дверь открывается наружу
  hinge: z.enum(["left", "right"]).optional(), // петли у начала отступа (left, по умолчанию) или у конца — как у расстановщика
});
export type Opening = z.infer<typeof opening>;

/**
 * Высота потолка по умолчанию, см — одно число для 3D-комнаты, камеры и гейта подвеса люстры (проход 210 → вылет ≤ 60;
 * зеркала вне TS: `tools/scout/compose_gates.py:CEILING_CM`, `tools/scout/flat215-demo/index.html:camRoomH`). Было 245 — его
 * не читал никто: квартира 3D (`data/flat3d/apartment.json`, британская) пишет 245 у комнат сама, демо — 270 (T-20261023-04/3).
 */
export const DEFAULT_CEILING_CM = 270;

export const room = z.object({
  id: z.string(),
  kind: roomKind,
  titleRu: z.string(),
  titleEn: z.string(),
  x: z.number(), // юго-западный угол в координатах квартиры, см
  y: z.number(),
  w: z.number().positive(),
  d: z.number().positive(),
  heightCm: z.number().positive().default(DEFAULT_CEILING_CM),
  openings: z.array(opening).default([]),
  /** Паспорт отделки (`lib/viewer3d/finish-passport.ts`): стены, пол, потолок, плинтус — id и цвет; нет — набор по умолчанию. */
  finish: z.object({
    wall: z.object({ id: z.string(), colorHex: z.string() }).partial(),
    floor: z.object({ id: z.string(), colorHex: z.string() }).partial(),
    ceiling: z.object({ id: z.string(), colorHex: z.string() }).partial(),
    skirting: z.object({ id: z.string(), colorHex: z.string() }).partial(),
  }).partial().optional(),
  /** Вид из окон комнаты — id нашего набора (`lib/viewer3d/window-views.ts`), из карточки квартиры застройщика; нет — по умолчанию. */
  windowView: z.string().regex(/^[a-z0-9-]{1,32}$/).optional(),
  /**
   * Настоящий контур комнаты, если она не прямоугольник ([x,y] в см, координаты квартиры). Сейчас его
   * НЕ читают ни солвер, ни 3D — прямоугольник (x,y,w,d) остаётся рамкой контура; поле нужно, чтобы
   * планировки застройщиков заводить честно уже сейчас (b2b-06 → b2b-10/13 подхватят без миграции).
   */
  contour: z.array(z.tuple([z.number(), z.number()])).min(3).optional(),
}).refine((r) => !r.contour || (
  Math.abs(Math.min(...r.contour.map((p) => p[0])) - r.x) < 1 && Math.abs(Math.min(...r.contour.map((p) => p[1])) - r.y) < 1 &&
  Math.abs(Math.max(...r.contour.map((p) => p[0])) - (r.x + r.w)) < 1 && Math.abs(Math.max(...r.contour.map((p) => p[1])) - (r.y + r.d)) < 1
), "рамка контура должна совпадать с x, y, w, d комнаты");
export type Room = z.infer<typeof room>;

/** Категории апгрейдов. Порядок = порядок показа в панели комнаты. */
export const slotCategory = z.enum([
  "flooring",
  "kitchen",
  "appliances",
  "bathroom",
  "walls",
  "furniture",
  "storage",
  "lighting",
]);
export type SlotCategory = z.infer<typeof slotCategory>;

/** Место предмета: центр + поворот + габарит (см). */
export const placement = z.object({
  x: z.number(),
  y: z.number(),
  rot: z.number().default(0),
  wCm: z.number().positive(),
  dCm: z.number().positive(),
  hCm: z.number().positive(),
  elevCm: z.number().nonnegative().default(0), // навесное: высота низа над полом
  /** Г-диван: оттоманка слева (как `corner_left` расстановщика); нет поля — не Г-диван (demo-03 14.10). */
  cornerLeft: z.boolean().optional(),
});
export type Placement = z.infer<typeof placement>;

/**
 * Слот — «что тут можно выбрать». Три вида:
 *  - surface  — покрытие (пол, стены, фартук, столешница): вариант меняет материал;
 *  - builtin  — встроенное (кухня, санузел, шкаф): вариант меняет параметрический комплект;
 *  - furniture— отдельно стоящее: вариант меняет модель (меш).
 */
export const slot = z.object({
  id: z.string(),
  roomId: z.string(),
  category: slotCategory,
  kind: z.enum(["surface", "builtin", "furniture"]),
  titleRu: z.string(),
  titleEn: z.string(),
  surface: z.enum(["floor", "wall", "splashback", "worktop"]).optional(),
  placement: placement.optional(),
  defaultOptionId: z.string(),
  /** Пусто = «все опции своей категории, подходящие типу комнаты». */
  optionIds: z.array(z.string()).default([]),
  /** Роль для фото-конвейера (протокол логики — по-русски, ADR демо). */
  photoRole: z.string().optional(),
  /**
   * Группа совместной замены: выбрал вариант на одном стуле — меняются ВСЕ стулья комнаты
   * (владелец 30.09: «стул меняем все вместе»). Разные стулья за одним столом никто не ставит.
   */
  selectionGroup: z.string().optional(),
  /**
   * Настольный декор (ваза): место считается от опоры — журнальный столик, иначе обеденный стол — тем же правилом, что на
   * серверном кадре (`resolve.placeTabletop` → `scene-extras.decorLayout`); покупатель его не двигает (владелец 08.09).
   */
  tabletop: z.boolean().optional(),
});
export type Slot = z.infer<typeof slot>;

export const cropWindow = z.object({
  x: z.number(),
  y: z.number(),
  w: z.number().positive(),
  h: z.number().positive(),
  keep: z.array(z.string()).optional(),
});
export type CropWindow = z.infer<typeof cropWindow>;

/** Готовая точка съёмки для photo-режима: см и градусы, как ждёт `/api/render`. */
export const cameraPreset = z.object({
  id: z.string(),
  roomId: z.string(),
  titleRu: z.string(),
  x: z.number(),
  y: z.number(),
  rot: z.number(),
  fov: z.number().default(72),
  /** Версия позы съёмки (`viewer.PhotoPose.pose`): 2 — глаз 135, горизонтально, сдвиг объектива (ракурсы окна демо). */
  pose: z.number().optional(),
  /** Сдвиг вертикального кадра телефона (`viewer.PhotoPose.pshift`, demo-12). */
  pshift: z.number().optional(),
  /**
   * Окно превью по пропорции окна («1.500», «0.673»…): доли кадра 2048×1489 (y — сверху) и id мебели, что в нём целиком.
   * Считает сборка демо по 3D-модели расстановки (`camCrop` в блоке CAMFIT, demo-22).
   */
  crop: z.record(z.string(), cropWindow).optional(),
});
export type CameraPreset = z.infer<typeof cameraPreset>;

export const apartment = z.object({
  id: z.string(),
  titleRu: z.string(),
  titleEn: z.string(),
  areaM2: z.number().positive(),
  developerId: z.string(),
  /** Базовая цена квартиры в валюте каталога — от неё считается «квартира + выбор». Берётся из
   *  реестра застройщиков (`data/partners`), а не из файла 3D (b2b-06). */
  basePrice: z.number().nonnegative().default(0),
  /** Исходный набор мебели витрины, из которого собрана квартира (`?demo=`), и его стиль для кадра. */
  baseVariant: z.string().optional(),
  style: z.string().optional(),
  rooms: z.array(room).min(1),
  slots: z.array(slot),
  cameras: z.array(cameraPreset).default([]),
  /** Точка старта прогулки (см, в координатах квартиры) и направление взгляда, градусы. */
  spawn: z.object({ x: z.number(), y: z.number(), rot: z.number().default(0) }),
});
export type Apartment = z.infer<typeof apartment>;

/** Комната по id — единственная точка, где допускается «не нашли». */
export function findRoom(a: Apartment, roomId: string): Room | undefined {
  return a.rooms.find((r) => r.id === roomId);
}

/** Слоты комнаты в порядке категорий каталога. */
export function slotsOfRoom(a: Apartment, roomId: string): Slot[] {
  return a.slots.filter((s) => s.roomId === roomId);
}

/**
 * Перевод координат квартиры в координаты ОДНОЙ комнаты (0..w, 0..d) — формат, на котором
 * говорит фото-конвейер (`draft_service.py` ждёт room+items одной комнаты).
 */
export function toRoomLocal(r: Room, x: number, y: number): { x: number; y: number } {
  return { x: x - r.x, y: y - r.y };
}

/** Центр комнаты в координатах квартиры — цель для камеры и старта прогулки. */
export function roomCentre(r: Room): { x: number; y: number } {
  return { x: r.x + r.w / 2, y: r.y + r.d / 2 };
}

/** Точка внутри комнаты (по её прямоугольнику). */
export function isInsideRoom(r: Room, x: number, y: number): boolean {
  return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.d;
}

/** Комната, в которой находится точка; null — коридор/за пределами. */
export function roomAt(a: Apartment, x: number, y: number): Room | null {
  return a.rooms.find((r) => isInsideRoom(r, x, y)) ?? null;
}
