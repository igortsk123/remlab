import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { buildRug } from "@/lib/viewer3d/kits/bedroom";
import { createMaterialCtx } from "@/lib/viewer3d/materials";

// ПОЛОСА ПО КРАЮ КОВРА МЕРЦАЛА (T-20261112-33, владелец 12.11 «когда двигаю — полоска белая мерцает под ковром»): рамка лежала
// на плите с фото, их верхние и боковые грани совпадали — глубина равная, и при движении камеры пиксель доставался то одной, то
// другой коробке. Проверка без WebGL: ни одна пара коробок ковра не делит площадь ни сверху, ни сбоку, габарит — прежний.

const data = {
  room: { w: 439, d: 325, title: "Гостиная", height_cm: 270, openings: [] },
  variants: [{ id: "v", title: "Сканди", style: "сканди", items: [
    { role: "ковёр", x: 200, y: 200, rot: 0, w: 230, d: 160, sku: { name: "Ковёр", price: 9291, sid: "r0", img: "img/r0.jpg" } },
  ] }],
};
const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 9_578_200 };

function boxes(g: THREE.Group): THREE.Box3[] {
  g.updateMatrixWorld(true);
  return g.children.map((c) => new THREE.Box3().setFromObject(c));
}

/** Площадь общего куска двух коробок в плоскости, где они соприкасаются гранью (0 — касаются по ребру или не касаются). */
function sharedFace(a: THREE.Box3, b: THREE.Box3): number {
  const ov = (lo1: number, hi1: number, lo2: number, hi2: number): number => Math.max(0, Math.min(hi1, hi2) - Math.max(lo1, lo2));
  const ox = ov(a.min.x, a.max.x, b.min.x, b.max.x), oy = ov(a.min.y, a.max.y, b.min.y, b.max.y), oz = ov(a.min.z, a.max.z, b.min.z, b.max.z);
  const eps = 1e-6;   // 1 мкм: координаты коробок — float32
  // объёмы пересекаются — значит, видимые грани одной лежат внутри/в плоскости другой
  if (ox > eps && oy > eps && oz > eps) return ox * oz + ox * oy + oy * oz;
  // наружные грани в одной плоскости и смотрят в одну сторону: верх ↔ верх, бок ↔ бок
  let s = 0;
  if (Math.abs(a.max.y - b.max.y) < eps && ox > eps && oz > eps && !(oy > eps)) s += ox * oz;
  for (const [amin, amax, bmin, bmax, o1, o2] of [
    [a.min.x, a.max.x, b.min.x, b.max.x, oy, oz], [a.min.z, a.max.z, b.min.z, b.max.z, ox, oy]] as const) {
    if ((Math.abs(amax - bmax) < eps || Math.abs(amin - bmin) < eps) && o1 > eps && o2 > eps) s += o1 * o2;
  }
  return s;
}

describe("ковёр — рамка вокруг полотна (T-20261112-33)", () => {
  const r = fromDemoVariant(data, "v", CTX)!;
  const ctx = { materials: createMaterialCtx(1, false), byId: (id: string) => r.catalogue.materials.find((m) => m.id === id),
    fallback: r.catalogue.materials[0]! };
  const matId = r.catalogue.materials.find((m) => m.surfaces?.includes("rug"))?.id;

  for (const pile of ["flat", "soft"] as const) {
    for (const [w, d] of [[230, 160], [200, 140], [12, 10]] as const) {
      it(`${pile} ${w}×${d}: коробки не делят граней, габарит и высота прежние`, () => {
        const g = buildRug(ctx, { materialId: matId, widthCm: w, depthCm: d, pile });
        const bs = boxes(g);
        for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) expect(sharedFace(bs[i]!, bs[j]!), `${i}↔${j}`).toBe(0);
        const all = bs.reduce((u, b) => u.union(b), new THREE.Box3());
        expect(all.max.x - all.min.x).toBeCloseTo(w * 0.01, 6);
        expect(all.max.z - all.min.z).toBeCloseTo(d * 0.01, 6);
        expect(all.max.y).toBeCloseTo((pile === "soft" ? 3 : 1.5) * 0.01, 6);
        // бока ковра — рамка: полотно (первая коробка) не выходит к краю ни с одной стороны
        const body = bs[0]!;
        expect(body.min.x).toBeGreaterThan(all.min.x);
        expect(body.max.x).toBeLessThan(all.max.x);
        expect(body.min.z).toBeGreaterThan(all.min.z);
        expect(body.max.z).toBeLessThan(all.max.z);
      });
    }
  }
});
