import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { room as roomSchema } from "@/contracts/apartment";
import { ContactShadow, roomsBounds, type BakeRenderer } from "@/lib/viewer3d/contact-shadow";
import { curtainsFromUrl } from "@/lib/viewer3d/demo-scene";
import { CURTAINS_DEFAULT } from "@/lib/viewer3d/viewer";
import { buildCurtains, roomWindows, sunPose } from "@/lib/viewer3d/window-light";

// ЗАПЕЧЁННАЯ ТЕНЬ МЕБЕЛИ И СВЕТ ОТ ОКНА (T-20261111-22/2). Без WebGL: рендерер — подделка, которая запоминает, что было видно
// в момент рисования, а «простой браузера» — ручная очередь.

function fakeRenderer(): BakeRenderer & { renders: { target: unknown; visible: string[] }[]; scene?: THREE.Scene } {
  let target: unknown = null, alpha = 1;
  const r = {
    renders: [] as { target: unknown; visible: string[] }[],
    shadowMap: { autoUpdate: true },
    getRenderTarget: () => target,
    setRenderTarget: (t: unknown) => { target = t; },
    getClearAlpha: () => alpha,
    setClearAlpha: (a: number) => { alpha = a; },
    clear: () => undefined,
    render: (obj: THREE.Object3D) => {
      const visible = obj instanceof THREE.Scene ? obj.children.filter((c) => c.visible).map((c) => c.name) : ["blur"];
      r.renders.push({ target, visible });
    },
  };
  return r as unknown as ReturnType<typeof fakeRenderer>;
}

function manualIdle(): { idle: (cb: () => void) => () => void; run: () => void; size: () => number } {
  const q = new Map<number, () => void>();
  let n = 0;
  return {
    idle: (cb) => { const id = ++n; q.set(id, cb); return () => q.delete(id); },
    run: () => { const all = [...q.values()]; q.clear(); all.forEach((f) => f()); },
    size: () => q.size,
  };
}

const named = (name: string): THREE.Group => Object.assign(new THREE.Group(), { name });
const BOUNDS = { x0: 0, y0: 0, x1: 400, y1: 300 };

describe("запечённая тень мебели", () => {
  it("рисует только мебель, остальное прячет на время запекания и возвращает; рендерер — как был", () => {
    const scene = new THREE.Scene();
    const bed = named("bed"), wall = named("wall"), rug = named("rug"), hiddenAlready = named("ghost");
    hiddenAlready.visible = false;
    scene.add(bed, wall, rug, hiddenAlready);
    const r = fakeRenderer();
    const cs = new ContactShadow(r, scene, BOUNDS, { res: 256 }, manualIdle().idle);
    expect(cs.plane.visible).toBe(false);                 // до запекания пустая картинка не рисуется
    cs.bake([bed]);
    expect(r.renders[0]!.visible).toEqual(["bed"]);       // стены, ковёр и сама плоскость тени — не в кадре тени
    expect(r.renders.length).toBe(5);                     // сцена + два прохода размытия по два шага
    expect([wall.visible, rug.visible, hiddenAlready.visible, cs.plane.visible]).toEqual([true, true, false, true]);
    expect(r.getRenderTarget()).toBeNull();
    expect(r.getClearAlpha()).toBe(1);
    expect(r.shadowMap.autoUpdate).toBe(true);
    expect(scene.overrideMaterial).toBeNull();
    expect(cs.bakes).toBe(1);
  });

  it("в простое: несколько вызовов подряд — одно запекание по последней мебели", () => {
    const scene = new THREE.Scene();
    const a = named("a"), b = named("b");
    scene.add(a, b);
    const r = fakeRenderer(), q = manualIdle();
    const cs = new ContactShadow(r, scene, BOUNDS, { res: 256 }, q.idle);
    cs.schedule(() => [a]);
    cs.schedule(() => [a, b]);
    expect(q.size()).toBe(1);
    expect(r.renders.length).toBe(0);                     // сразу не рисуем — первый кадр не ждёт
    q.run();
    expect(cs.bakes).toBe(1);
    expect(r.renders[0]!.visible).toEqual(["a", "b"]);
    cs.schedule(() => [b]);                               // повтор после переноса
    q.run();
    expect(cs.bakes).toBe(2);
    expect(r.renders[5]!.visible).toEqual(["b"]);
  });

  it("dispose: плоскость уходит из сцены, отложенное запекание не срабатывает, всё освобождено", () => {
    const scene = new THREE.Scene();
    scene.add(named("bed"));
    const r = fakeRenderer(), q = manualIdle();
    const cs = new ContactShadow(r, scene, BOUNDS, { res: 512 }, q.idle);
    const freed: string[] = [];
    const watch = (o: unknown, n: string): void =>
      (o as THREE.EventDispatcher<{ dispose: object }>).addEventListener("dispose", () => freed.push(n));
    const inner = cs as unknown as { rt: THREE.WebGLRenderTarget; rtBlur: THREE.WebGLRenderTarget; depthMat: THREE.Material;
      hBlur: THREE.Material; vBlur: THREE.Material };
    watch(cs.plane.geometry, "geo");
    watch(cs.plane.material as THREE.Material, "mat");
    watch(inner.rt, "rt");
    watch(inner.rtBlur, "rtBlur");
    watch(inner.depthMat, "depth");
    watch(inner.hBlur, "h");
    watch(inner.vBlur, "v");
    cs.schedule(() => scene.children);
    expect(scene.children).toContain(cs.plane);
    cs.dispose();
    expect(q.size()).toBe(0);                             // отложенное снято
    q.run();
    expect(r.renders.length).toBe(0);
    expect(scene.children).not.toContain(cs.plane);
    expect(freed.sort()).toEqual(["depth", "geo", "h", "mat", "rt", "rtBlur", "v"]);
    cs.dispose();                                         // повторный — без ошибок
    cs.schedule(() => scene.children);
    expect(q.size()).toBe(0);
  });

  it("плоскость тени — по всей квартире, над ворсом ковра; картинка — по пропорции квартиры", () => {
    const cs = new ContactShadow(fakeRenderer(), new THREE.Scene(), { x0: 100, y0: 50, x1: 500, y1: 250 }, { res: 512 });
    expect(cs.plane.position.x).toBeCloseTo(3, 6);
    expect(cs.plane.position.z).toBeCloseTo(1.5, 6);
    expect(cs.plane.position.y).toBeGreaterThan(0.03);
    const rt = (cs as unknown as { rt: THREE.WebGLRenderTarget }).rt;
    expect([rt.width, rt.height]).toEqual([512, 256]);
    expect(roomsBounds([{ x: 0, y: 0, w: 300, d: 200 }, { x: 300, y: -50, w: 100, d: 100 }])).toEqual({ x0: 0, y0: -50, x1: 400, y1: 200 });
    expect(roomsBounds([])).toBeNull();
  });
});

describe("свет от окна", () => {
  const room = (openings: unknown[]) => roomSchema.parse({ id: "r", kind: "bedroom", titleRu: "С", titleEn: "B", x: 0, y: 0, w: 400, d: 300, openings });

  it("солнце — снаружи окна и выше комнаты, светит в её середину; заполняющий — с комнатной стороны", () => {
    const east = room([{ id: "w", kind: "window", wall: "east", offsetCm: 100, widthCm: 120 }]);
    const p = sunPose([east])!;
    expect(p.target).toEqual([2, 0, 1.5]);
    expect(p.sun[0]).toBeGreaterThan(4);                  // за восточной стеной (x = 4 м)
    expect(p.sun[1]).toBeGreaterThan(east.heightCm / 100);
    expect(p.fill[0]).toBeLessThan(0);                    // с запада, напротив окна
    expect(sunPose([room([])])).toBeNull();               // окон нет — солнце как было
  });

  it("окна по сторонам стен; шторы — два полотна на окно у его краёв", () => {
    const r = room([
      { id: "a", kind: "window", wall: "south", offsetCm: 100, widthCm: 150 },
      { id: "b", kind: "balcony", wall: "north", offsetCm: 20, widthCm: 80 },
      { id: "d", kind: "door", wall: "west", offsetCm: 20, widthCm: 80 },
    ]);
    const wins = roomWindows([r]);
    expect(wins.map((w) => [w.x, w.z, w.nx, w.nz])).toEqual([[1.75, 0, 0, 1], [0.6, 3, 0, -1]]);
    expect(wins[1]!.sill).toBe(0);                        // балконный блок — до пола
    const g = buildCurtains([r]);
    expect(g.children.length).toBe(4);
    const xs = g.children.slice(0, 2).map((m) => m.position.x).sort((a, b) => a - b);
    expect(xs[0]).toBeLessThan(1.75 - 0.75 + 0.2);        // левое полотно — у левого края окна
    expect(xs[1]).toBeGreaterThan(1.75 + 0.75 - 0.2);
    expect(buildCurtains([room([])]).children.length).toBe(0);
  });

  it("шторы по умолчанию вкл., выключатель в адресе — откат без выкладки (владелец TG 1643)", () => {
    expect(CURTAINS_DEFAULT).toBe(true);
    expect(curtainsFromUrl("")).toBeUndefined();               // решает движок — вкл.
    expect(curtainsFromUrl("?live=force&curtains=0")).toBe(false);
    expect(curtainsFromUrl("?curtains=1&quiz=0")).toBe(true);
    expect(curtainsFromUrl("?curtains=01")).toBeUndefined();   // мусор — не выключатель
  });
});
