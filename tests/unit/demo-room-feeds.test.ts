import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { roomFeedKey } from "@/lib/configurator/demo-feeds";

// ЛЕНТЫ И ПОЛОСЫ ПО КЛЮЧУ КОМНАТЫ (T-20261106-77, Codex): общая роль (ковёр) гостиной и спальни — разные ленты; гостиная — голая роль.
// Окно (`index.html` ROOMKEY), /flat (`demo-feeds.ts:roomFeedKey`) и сборка (`demo_bedroom.room_key`) ищут одинаково
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const roomIdSrc = html.slice(html.indexOf("function roomIdOf("), html.indexOf("\n", html.indexOf("function roomIdOf(")));
const block = html.slice(html.indexOf("// ROOMKEY START"), html.indexOf("// ROOMKEY END"));
type V = { room_id?: string };
const page = new Function(`${roomIdSrc}\n${block};return {roomKeysOf,byRoomOf};`)() as {
  roomKeysOf: (v: V, base: string) => string[];
  byRoomOf: (v: V, dict: Record<string, unknown> | undefined, base: string) => unknown;
};

const feeds = { "ковёр": ["ковёр гостиной"], "bedroom:ковёр": ["ковёр спальни"], "bedroom:кровать": ["кровать"] };
const bands = { "ковёр": { lo: 160 }, "bedroom-1:кровать": { lo: 160 }, "bedroom-2:кровать": { lo: 90 } };

describe("ленты по комнате: окно", () => {
  it("гостиная и спальня с ролью «ковёр» — разные ленты; гостиная — по голой роли", () => {
    expect(page.byRoomOf({}, feeds, "ковёр")).toEqual(["ковёр гостиной"]);
    expect(page.byRoomOf({ room_id: "living" }, feeds, "ковёр")).toEqual(["ковёр гостиной"]);
    expect(page.byRoomOf({ room_id: "bedroom-1" }, feeds, "ковёр")).toEqual(["ковёр спальни"]);
    expect(page.byRoomOf({ room_id: "bedroom-2" }, feeds, "ковёр")).toEqual(["ковёр спальни"]);
  });

  it("спальня без своей ленты роли — пусто, а не лента гостиной", () => {
    expect(page.byRoomOf({ room_id: "bedroom-1" }, { "ковёр": ["ковёр гостиной"] }, "ковёр")).toBeNull();
    expect(page.byRoomOf({}, feeds, "кровать")).toBeNull();
  });

  it("полоса — своя у каждой спальни (назначение), затем по типу комнаты", () => {
    expect(page.byRoomOf({ room_id: "bedroom-1" }, bands, "кровать")).toEqual({ lo: 160 });
    expect(page.byRoomOf({ room_id: "bedroom-2" }, bands, "кровать")).toEqual({ lo: 90 });
    expect(page.roomKeysOf({ room_id: "bedroom-2" }, "тумба")).toEqual(["bedroom-2:тумба", "bedroom:тумба"]);
  });
});

describe("ленты по комнате: /flat", () => {
  it("ключ — как у окна и сборки", () => {
    expect(roomFeedKey("living", "ковёр")).toBe("ковёр");
    expect(roomFeedKey(undefined, "ковёр")).toBe("ковёр");
    expect(roomFeedKey("bedroom-2", "ковёр")).toBe("bedroom:ковёр");
    expect(roomFeedKey("bedroom-1", "ковёр")).toBe(page.roomKeysOf({ room_id: "bedroom-1" }, "ковёр")[1]);
  });
});
