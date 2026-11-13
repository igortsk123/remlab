import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ДВЕРИ ПЛАНА ТУРА (T-20261112-48/2, П1.9): чертёж «3D-планировки» тура рисует створки по тому же правилу, что 3D
// (`tools/scout/trial_room.py:_place_opening`): дверь шире 120 или с парой дуг на листе (`leaves: 2`) — две створки по половине проёма,
// створка не шире 100; внутренняя шире 120 без факта дуги — проём 90 без створок; проход без дуги шире 110 — проём без границы.
// Функции берём прямо из страницы (блоки TROPEN и TRLEAF).
type Pt = [number, number];
type Op = { kind: string; c: Pt; widthCm: number; exterior?: boolean; arc?: boolean; leaves?: number };
type Room = { id: string; kind?: string; areaM2?: number; bbox: { x: number; y: number; w: number; d: number } };
type Out = { kind: string; pts: Pt[]; leaves?: number };
type Api = {
  trOpeningsOf: (p: { openings: Op[] }, rs: Room[]) => Out[];
  trLeaves: (o: Out) => [Pt, Pt, Pt][];
  trInDoor: (c: Pt, o: Out, pad: number) => boolean;
};
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const cut = (n: string) => {
  const a = html.indexOf(`// ${n} START`), b = html.indexOf(`// ${n} END`);
  if (a < 0 || b < a) throw new Error(`в странице нет блока ${n}`);
  return html.slice(a, b);
};
const api = new Function(`${cut("TRLEAF")}\n${cut("TROPEN")}\nreturn {trOpeningsOf, trLeaves, trInDoor};`)() as Api;

// две комнаты по обе стороны стены y = 400: сверху столовая 4×4 м, снизу гостиная 4×3 м; дверь — в середине стены
const RS: Room[] = [
  { id: "dining", kind: "living", areaM2: 16, bbox: { x: 0, y: 0, w: 400, d: 400 } },
  { id: "living", kind: "living", areaM2: 12, bbox: { x: 0, y: 400, w: 400, d: 300 } },
];
const door = (o: Partial<Op>) => api.trOpeningsOf({ openings: [{ kind: "door", c: [200, 400], widthCm: 80, arc: true, ...o }] }, RS);
const len = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);

describe("двери плана тура — створки как в 3D", () => {
  it("обычная дверь 80 — одна створка на всю ширину", () => {
    const [o] = door({ widthCm: 80 });
    expect(o.kind).toBe("door");
    const L = api.trLeaves(o);
    expect(L).toHaveLength(1);
    expect(len(L[0][0], L[0][1])).toBeCloseTo(80, 5);
  });

  it("внутренняя 150 с дугой (пара 2×75 в 3D) — две створки по 75 с петлями у обоих концов, открываются в одну сторону", () => {
    const [o] = door({ widthCm: 150 });
    expect(o.kind).toBe("door");
    expect(o.leaves).toBe(2);
    const L = api.trLeaves(o);
    expect(L).toHaveLength(2);
    L.forEach(([H, T, F]) => { expect(len(H, T)).toBeCloseTo(75, 5); expect(len(H, F)).toBeCloseTo(75, 5); });
    expect(L.map(([H]) => H[0]).sort((a, b) => a - b)).toEqual([125, 275]);
    expect(Math.sign(L[0][1][1] - 400)).toBe(Math.sign(L[1][1][1] - 400));
    // свободные концы сходятся в середине проёма
    expect(len(L[0][2], L[1][2])).toBeCloseTo(0, 5);
  });

  it("пара дуг на листе (`leaves: 2`) у двери 119 — две створки по 59,5, хотя уже 120", () => {
    const [o] = door({ widthCm: 119, exterior: true, leaves: 2 });
    const L = api.trLeaves(o);
    expect(L).toHaveLength(2);
    expect(len(L[0][0], L[0][1])).toBeCloseTo(59.5, 5);
  });

  it("створка не шире 100: дверь 110 — одна створка 100; дверь 240 — две по 100", () => {
    expect(len(...(api.trLeaves(door({ widthCm: 110 })[0])[0].slice(0, 2) as [Pt, Pt]))).toBeCloseTo(100, 5);
    const L = api.trLeaves(door({ widthCm: 240 })[0]);
    expect(L).toHaveLength(2);
    L.forEach(([H, T]) => expect(len(H, T)).toBeCloseTo(100, 5));
  });

  it("внутренняя шире 120 без факта дуги — проём 90 без створок; проход без дуги шире 110 — проём без створок", () => {
    const [w] = door({ widthCm: 160, arc: undefined });
    expect(w.kind).toBe("gap");
    expect(len(w.pts[0], w.pts[1])).toBeCloseTo(90, 5);
    const [p] = door({ widthCm: 150, arc: false });
    expect(p.kind).toBe("gap");
    expect(len(p.pts[0], p.pts[1])).toBeCloseTo(150, 5);
  });

  it("сектор открывания двустворчатой — под обеими створками (подпись комнаты туда не ставится)", () => {
    const [o] = door({ widthCm: 150 });
    const s = Math.sign(api.trLeaves(o)[0][1][1] - 400);
    expect(api.trInDoor([140, 400 + s * 30], o, 0)).toBe(true);
    expect(api.trInDoor([260, 400 + s * 30], o, 0)).toBe(true);
    expect(api.trInDoor([200, 400 - s * 30], o, 0)).toBe(false);
  });
});
