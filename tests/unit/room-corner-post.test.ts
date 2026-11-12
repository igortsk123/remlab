// T-20261112-51/2 (владелец TG 855, «Этажи»: светлые щели на стыке стен у кухни-гостиной). Ядро и пристройка — отдельные коробки со
// стенами, вдвинутыми на 1 см (`rooms.ts:INSET_CM`); на вогнутом углу стыка между ними был просвет 1×1 см на всю высоту — сквозь него
// небо и земля. Угловая стойка (`rooms.ts:cornerPosts`) его закрывает; луч из комнаты в угол обязан упереться в стену или стойку.
import { describe, expect, it } from "vitest";
import * as THREE from "three";

import { room as roomSchema, type Room } from "@/contracts/apartment";
import type { Material } from "@/contracts/configurator";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { buildRoom, cornerPosts } from "@/lib/viewer3d/rooms";

const CTX = { apartmentId: "trial", partnerId: "demo", currency: "RUB" as const, basePrice: 0 };
const MAT = { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as unknown as Material;
// кухня-гостиная тура «Этажи» (aOv8…, перевыпуск 12.11 12:58): ядро 335×380, хвост 255×265 за стыком 80…335 на севере, портал 90 в
// западной стене хвоста и кусок прохода за ним
const GEO = {
  w: 335, d: 380, height_cm: 310,
  openings: [{ wall: "south", offset_cm: 41.4, width_cm: 174, kind: "window", sill_cm: 85, height_cm: 150 },
             { kind: "opening", wall: "north", offset_cm: 80, width_cm: 255, junction: true }],
  annexes: [
    { x: 80, y: 380, w: 255, d: 265, junction: "north", openings: [
      { kind: "opening", wall: "south", offset_cm: 0, width_cm: 255, junction: true },
      { wall: "west", offset_cm: 18.6, width_cm: 90, kind: "opening" }] },
    { x: -40, y: 398.6, w: 120, d: 90, stub: true, openings: [{ kind: "opening", wall: "east", offset_cm: 0, width_cm: 90, junction: true }] },
  ],
};

function living(geo: Record<string, unknown>): Room {
  const ap = fromDemoVariant({ rooms_geo: { living: geo }, variants: [{ id: "v1", style: "сканди", items: [] }] }, "v1", CTX)!.apartment;
  return roomSchema.parse(ap.rooms[0]);
}

/** Луч на высоте `hCm` из точки `from` (см плана) в точку `to`: что он встречает первым — с учётом односторонних стен. */
function firstHit(group: THREE.Object3D, from: [number, number], to: [number, number], hCm = 150): THREE.Intersection | null {
  group.updateMatrixWorld(true);
  const o = new THREE.Vector3(from[0] / 100, hCm / 100, from[1] / 100);
  const d = new THREE.Vector3((to[0] - from[0]) / 100, 0, (to[1] - from[1]) / 100).normalize();
  const rc = new THREE.Raycaster(o, d, 0, 50);
  const hits = rc.intersectObject(group, true).filter((h) => /^(wall|corner):/.test(h.object.name));
  return hits[0] ?? null;
}

describe("угол стыка ядра и пристройки — без просвета (T-20261112-51/2)", () => {
  it("стойка — только у края стыка посреди стены; стык до конца стены — без стойки", () => {
    const j = (offsetCm: number, widthCm: number) => ({ kind: "opening" as const, wall: "north" as const, offsetCm, widthCm, junction: true });
    expect(cornerPosts(335, [j(0, 255)])).toEqual([[254, 255]]);             // северная стена ядра «Этажей» (отступ уже зеркальный)
    expect(cornerPosts(335, [j(80, 255)])).toEqual([[80, 81]]);
    expect(cornerPosts(255, [j(0, 255)])).toEqual([]);                       // стык на всю стену — углы выпуклые или на одной линии
    expect(cornerPosts(335, [{ ...j(80, 90), junction: false }])).toEqual([]);   // обычный портал: края закрывает наличник
  });

  it("кухня-гостиная «Этажей»: одна стойка ровно в просвете угла (80, 380)", () => {
    const { group } = buildRoom(createMaterialCtx(1, false), living(GEO), MAT, MAT);
    group.updateMatrixWorld(true);
    const posts: THREE.Object3D[] = [];
    group.traverse((o) => { if (o.name.startsWith("corner:")) posts.push(o); });
    expect(posts.map((p) => p.name)).toEqual(["corner:living:north"]);
    const b = new THREE.Box3().setFromObject(posts[0]!);
    expect(b.min.x).toBeCloseTo(0.8, 3);
    expect(b.max.x).toBeCloseTo(0.81, 3);
    expect(b.min.z).toBeCloseTo(3.79, 3);
    expect(b.max.z).toBeCloseTo(3.8, 3);
    expect(b.max.y).toBeCloseTo(3.1, 3);
  });

  it("лучи в угол из ядра и из хвоста упираются в стену или стойку, не уходят на улицу", () => {
    const { group } = buildRoom(createMaterialCtx(1, false), living(GEO), MAT, MAT);
    const target: [number, number][] = [];
    for (const fx of [0.1, 0.5, 0.9]) for (const fy of [0.1, 0.5, 0.9]) target.push([80 + fx, 379 + fy]);   // точки просвета
    const from: [number, number][] = [[200, 200], [150, 300], [300, 370], [250, 500], [200, 600], [120, 360]];
    let open = 0;
    for (const a of from) for (const t of target) for (const h of [10, 150, 300]) {
      const hit = firstHit(group, a, t, h);
      const dist = Math.hypot(t[0] - a[0], t[1] - a[1]) / 100;
      if (!hit || hit.distance > dist + 0.02) open++;
    }
    expect(open).toBe(0);
  });

  it("без стойки просвет есть (проверка видит щель)", () => {
    const { group } = buildRoom(createMaterialCtx(1, false), living(GEO), MAT, MAT);
    const posts: THREE.Object3D[] = [];
    group.traverse((o) => { if (o.name.startsWith("corner:")) posts.push(o); });
    posts.forEach((p) => p.parent?.remove(p));
    const hit = firstHit(group, [200, 200], [80.5, 379.5]);
    const dist = Math.hypot(80.5 - 200, 379.5 - 200) / 100;
    expect(!hit || hit.distance > dist + 0.02).toBe(true);
  });
});
