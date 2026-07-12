// Чистые функции площадей калькулятора (К1). Проёмы и исключаемые зоны вычитаются; net ≥ 0.
// Покрыто golden-тестом tests/unit/calc-geometry.test.ts.

import type { CalcKind, Floor, Room, Surface } from "@/contracts/calc";

const round2 = (n: number) => Math.round(n * 100) / 100;

export function surfaceGross(s: Surface): number {
  return s.lengthM * s.heightM;
}

export function surfaceOpeningsArea(s: Surface): number {
  return s.openings.reduce((sum, o) => sum + o.widthM * o.heightM * o.count, 0);
}

export function surfaceNet(s: Surface): number {
  return round2(Math.max(0, surfaceGross(s) - surfaceOpeningsArea(s)));
}

export function floorGross(f: Floor): number {
  return f.lengthM * f.widthM + f.extraZones.reduce((s, z) => s + z.lengthM * z.widthM, 0);
}

export function floorExcluded(f: Floor): number {
  return f.excludedZones.reduce((s, z) => s + z.lengthM * z.widthM, 0);
}

export function floorNet(f: Floor): number {
  return round2(Math.max(0, floorGross(f) - floorExcluded(f)));
}

export type RoomAreas = { grossM2: number; netM2: number };

// Площади комнаты по виду: ламинат — по полу; обои/плитка/краска — сумма поверхностей.
export function roomAreas(room: Room, kind: CalcKind): RoomAreas {
  if (kind === "laminat") {
    const f = room.floor;
    if (!f) return { grossM2: 0, netM2: 0 };
    return { grossM2: round2(floorGross(f)), netM2: floorNet(f) };
  }
  let gross = 0;
  let net = 0;
  for (const s of room.surfaces) {
    gross += surfaceGross(s);
    net += surfaceNet(s);
  }
  return { grossM2: round2(gross), netM2: round2(net) };
}
