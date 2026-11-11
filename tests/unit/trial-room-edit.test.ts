import { describe, expect, it } from "vitest";

import { trialRoomEditIn } from "@/contracts/trial";
import { nextDims, roomNow, sameAsBuilt } from "@/lib/trial/repo-room-edit";
import { roomKindOf } from "@/lib/trial/room-kind";
import { injectTour, roomEditPath } from "@/lib/trial/tour-page";

// Правка комнаты в туре (T-20261110-36): форма тела, вид по имени, комната страницы → панель/id/центр, порог 10 см, песочница тура.

const ok = { k: "A".repeat(22), request_id: "edit-0000001", base_version: 3, room: "bedroom-1", name: "Спальня", w_cm: 350, d_cm: 300 };
const box = (x: number, w = 400, d = 300) => ({ x, y: 0, w, d });
const bundle = { apartment_rooms: [{ id: "bedroom-1", titleRu: "Спальня 1" }], trial: { panels: [
  { id: "p1", rooms: [{ id: "living", src_id: "r1", name: "LIVING", kind: "living", bbox: box(0) },
    { id: "bedroom-1", src_id: "r2", name: "BEDROOM 1", kind: "bedroom", bbox: box(400), edited: { w: 420, d: 310 } }] }] } };

describe("правка комнаты: контракт и правила", () => {
  it("тело: все поля; имя обрезается; габариты 50…5000 см; лишний ключ и чужая комната не проходят", () => {
    expect(trialRoomEditIn.parse({ ...ok, name: "  Кабинет  " }).name).toBe("Кабинет");
    for (const bad of [{ name: "" }, { name: "x".repeat(61) }, { w_cm: 49 }, { d_cm: 5001 }, { room: "Bedroom 1" }, { base_version: 0 },
      { k: "short" }, { w_cm: Number.NaN }]) {
      expect(trialRoomEditIn.safeParse({ ...ok, ...bad }).success).toBe(false);
    }
    const { w_cm: _w, ...noW } = ok;
    expect(trialRoomEditIn.safeParse(noW).success).toBe(false);
  });

  it("вид по имени: русские и английские; «Кухня-гостиная» — гостиная; непонятное — other", () => {
    expect(["Гостиная", "Спальня 2", "Детская", "Кухня", "Ванная", "Туалет", "Санузел", "Коридор", "Прихожая", "Кладовая", "Кухня-гостиная",
      "Master bedroom", "WC", "Hallway"].map(roomKindOf))
      .toEqual(["living", "bedroom", "bedroom", "kitchen", "bathroom", "bathroom", "bathroom", "hall", "hall", "other", "living", "bedroom",
        "bathroom", "hall"]);
  });

  it("комната страницы → панель, id плана, подпись, текущие габариты (правка важнее прочитанного), центр в долях охвата панели", () => {
    expect(roomNow(bundle, "bedroom-1")).toEqual({ panel: "p1", srcId: "r2", name: "BEDROOM 1", title: "Спальня 1", kind: "bedroom",
      orig: box(400), w: 420, d: 310, anchor: { x: 0.75, y: 0.5 } });
    expect(roomNow(bundle, "living")).toMatchObject({ w: 400, d: 300, anchor: { x: 0.25, y: 0.5 } });
    expect(roomNow(bundle, "kitchen-1")).toBeNull();
    expect(roomNow({}, "living")).toBeNull();
  });

  it("порог 10 см по каждой оси от построенной; вернули к прочитанному — правки размера нет", () => {
    const now = roomNow(bundle, "bedroom-1")!;
    expect(nextDims(now, 429, 301)).toEqual({ w: 420, d: 310 });       // < 10 — как построено (прошлая правка)
    expect(nextDims(now, 430, 305)).toEqual({ w: 430, d: 310 });
    expect(nextDims(now, 400, 300)).toBeNull();
    expect(nextDims(now, 380.4, 290)).toEqual({ w: 380, d: 290 });
  });

  it("«как построено» до целого см: дробный прочитанный охват (350.7 × 518.6) узнаётся по целым, что шлёт окошко (T-19/2)", () => {
    const frac = { trial: { panels: [{ id: "p0", rooms: [{ id: "bedroom-1", src_id: "r2", name: "B1", kind: "bedroom",
      bbox: { x: 0, y: 0, w: 350.7, d: 518.6 } }] }] } };
    const now = roomNow(frac, "bedroom-1")!;
    expect(sameAsBuilt(now, nextDims(now, 351, 519))).toBe(true);
    expect(sameAsBuilt(now, nextDims(now, 401, 519))).toBe(false);
    const edited = roomNow(bundle, "bedroom-1")!;                       // правка 420 × 310 поверх прочитанного 400 × 300
    expect(sameAsBuilt(edited, nextDims(edited, 425, 312))).toBe(true);
    expect(sameAsBuilt(edited, nextDims(edited, 400, 300))).toBe(false); // вернуть к прочитанному — это изменение
  });

  it("песочница тура пропускает ручку правки ЭТОГО задания и только её", () => {
    const id = "a".repeat(22);
    const html = injectTour("<html><head></head><body></body></html>", id, 1);
    expect(html).toContain(JSON.stringify(roomEditPath(id)));
    expect(html).not.toContain(`/api/trial/${"b".repeat(22)}/room-edit`);
  });
});
