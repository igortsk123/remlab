// Коробка комнаты: пол, стены с проёмами, потолок.
//
// ЕДИНИЦЫ: данные — сантиметры, сцена — метры (делим на 100).
// ОСИ: план x → сцена X, план y (вглубь) → сцена Z, вверх → Y. Это ровно то отображение,
// на котором работает серверный рендер (`tools/scout/scene_mesh.py`), поэтому 3D и фото
// показывают одну и ту же комнату.
//
// Стены — ОДНОСТОРОННИЕ плоскости, повёрнутые внутрь комнаты, и вдвинуты на 1 см. Так две
// соседние комнаты не дерутся за одни и те же пиксели (общая стена рисуется дважды, но
// каждая половина видна только из своей комнаты) — и не нужен CSG ради дверных проёмов.

import * as THREE from "three";

import type { Opening, Room, WallSide } from "@/contracts/apartment";
import type { Material } from "@/contracts/configurator";
import { type MaterialCtx, tiled } from "@/lib/viewer3d/materials";
import { finishPassport } from "@/lib/viewer3d/finish-passport";
import { jointStrips } from "@/lib/viewer3d/joints";
import { ceilingLampIR, wallFixturesIR } from "@/lib/viewer3d/fixtures-ir";
import { buildOpenings, meshesFromBoxes } from "@/lib/viewer3d/openings";
import { openingIR, wallRects } from "@/lib/viewer3d/opening-ir";

const CM = 0.01;
const INSET_CM = 1;

// куски стены вокруг проёмов считает общий модуль без three.js — его же зовёт ночная сборка (`tools/flat3d/opening-ir.mjs`)
export { wallRects } from "@/lib/viewer3d/opening-ir";

interface WallFrame {
  /** Точка начала стены (u=0) в координатах квартиры, см. */
  ox: number;
  oy: number;
  /** Направление роста u. */
  dx: number;
  dy: number;
  /** Поворот плоскости вокруг Y, чтобы лицо смотрело внутрь комнаты. */
  rotY: number;
  lengthCm: number;
}

function frameOf(room: Room, side: WallSide): WallFrame {
  const inset = INSET_CM;
  switch (side) {
    case "south":
      return { ox: room.x, oy: room.y + inset, dx: 1, dy: 0, rotY: 0, lengthCm: room.w };
    case "north":
      return { ox: room.x + room.w, oy: room.y + room.d - inset, dx: -1, dy: 0, rotY: Math.PI, lengthCm: room.w };
    case "west":
      return { ox: room.x + inset, oy: room.y + room.d, dx: 0, dy: -1, rotY: Math.PI / 2, lengthCm: room.d };
    case "east":
      return { ox: room.x + room.w - inset, oy: room.y, dx: 0, dy: 1, rotY: -Math.PI / 2, lengthCm: room.d };
  }
}

/** Проёмы стены в координатах «вдоль стены от её начала». */
function openingsOnSide(room: Room, side: WallSide): Opening[] {
  const list = room.openings.filter((o) => o.wall === side);
  if (side === "north" || side === "west") {
    // у этих стен u растёт в обратную сторону от того, как задан offset (запад→восток /
    // юг→север), поэтому зеркалим отступ относительно длины стены
    const len = side === "north" ? room.w : room.d;
    // петли по данным — у начала отступа (`hinge` left, как у расстановщика); после зеркала это другой конец
    return list.map((o) => ({ ...o, offsetCm: len - o.offsetCm - o.widthCm, hinge: o.hinge === "right" ? "left" : "right" }));
  }
  return list;
}

export interface RoomVisual {
  group: THREE.Group;
  /** Плоскость пола — по ней ходит «point-and-go» и считается попадание курсора. */
  floor: THREE.Mesh;
}

/** Столярка проёмов одной стены, уже поставленная на место в квартире. Отдельно — чтобы тест сверял её с серверным кадром
 *  (`tests/unit/opening-ir.test.ts`, эталон `tools/assets/opening_golden.py`) без материалов стен. */
export function joineryOf(
  room: Room,
  side: WallSide,
  opts: { entranceWall?: string; doorsClosed?: boolean } = {},
): THREE.Group | null {
  const wallOpenings = openingsOnSide(room, side);
  if (wallOpenings.length === 0) return null;
  const f = frameOf(room, side);
  const joinery = buildOpenings(wallOpenings, side, {
    heightCm: room.heightCm,
    entranceWall: opts.entranceWall,
    doorsClosed: opts.doorsClosed,
    windowView: room.windowView,
    lengthCm: f.lengthCm,
  });
  joinery.position.set(f.ox * CM, 0, f.oy * CM);
  joinery.rotation.y = f.rotY;
  joinery.name = `joinery:${room.id}:${side}`;
  return joinery;
}

export function buildRoom(
  ctx: MaterialCtx,
  room: Room,
  floorMat: Material,
  wallMat: Material,
  opts: { ceiling?: boolean; entranceWall?: string; doorsClosed?: boolean; accent?: { side: WallSide; material: Material } } = {},
): RoomVisual {
  const group = new THREE.Group();
  group.name = `room:${room.id}`;
  const fp = finishPassport(room.finish); // паспорт отделки: потолок и плинтус (стены и пол — материалами каталога)

  const floorGeo = new THREE.PlaneGeometry(room.w * CM, room.d * CM);
  const floor = new THREE.Mesh(floorGeo, tiled(ctx, floorMat, room.w, room.d));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set((room.x + room.w / 2) * CM, 0, (room.y + room.d / 2) * CM);
  floor.name = `floor:${room.id}`;
  floor.receiveShadow = true;
  group.add(floor);

  for (const side of ["south", "north", "west", "east"] as WallSide[]) {
    const f = frameOf(room, side);
    const wallOpenings = openingsOnSide(room, side);

    // СТОЛЯРКА ПРОЁМОВ (рама, стекло, подоконник, полотно) строится в локальных осях стены:
    // группа стоит в начале стены, её X идёт вдоль стены, Z — внутрь комнаты. Это ровно та же
    // система, в которой заданы `offsetCm`, поэтому размеры пишутся как на чертеже.
    const joinery = joineryOf(room, side, opts);
    if (joinery) group.add(joinery);

    const rects = wallRects(f.lengthCm, room.heightCm, wallOpenings);
    // мягкая тень у стыков пол/потолок/угол — в осях стены, как столярка (`joints.ts`, demo-04 п.4)
    const joints = jointStrips(f.lengthCm, room.heightCm, rects);
    joints.position.set(f.ox * CM, 0, f.oy * CM);
    joints.rotation.y = f.rotY;
    joints.name = `joints:${room.id}:${side}`;
    group.add(joints);
    // плинтус по кускам стены и карниз над окнами — то же описание получает серверный кадр (`fixtures-ir.ts`, demo-04 п.6)
    const wins = wallOpenings.filter((o) => o.kind === "window" || o.kind === "balcony")
      .map((o) => openingIR(o, { wallHeightCm: room.heightCm }).cut);
    const fixtures = meshesFromBoxes(wallFixturesIR(rects, wins, room.heightCm), { skirting: fp.skirting.colorHex });
    fixtures.position.set(f.ox * CM, 0, f.oy * CM);
    fixtures.rotation.y = f.rotY;
    fixtures.name = `fixtures:${room.id}:${side}`;
    group.add(fixtures);
    for (const r of rects) {
      const wCm = r.u1 - r.u0;
      const hCm = r.v1 - r.v0;
      const geo = new THREE.PlaneGeometry(wCm * CM, hCm * CM);
      // акцентная стена (demo-07) — своим материалом, остальные — базовым
      const mat = tiled(ctx, opts.accent?.side === side ? opts.accent.material : wallMat, wCm, hCm, 0, [r.u0, r.v0]);
      mat.side = THREE.FrontSide;
      const mesh = new THREE.Mesh(geo, mat);
      const uMid = r.u0 + wCm / 2;
      mesh.position.set(
        (f.ox + f.dx * uMid) * CM,
        (r.v0 + hCm / 2) * CM,
        (f.oy + f.dy * uMid) * CM,
      );
      mesh.rotation.y = f.rotY;
      mesh.name = `wall:${room.id}:${side}`;
      mesh.receiveShadow = true;
      group.add(mesh);
    }
  }

  if (opts.ceiling !== false) {
    const ceil = new THREE.Mesh(
      new THREE.PlaneGeometry(room.w * CM, room.d * CM),
      // потолок светится отражённым светом: верхний источник до него не достаёт, а нижняя часть общего света серая —
      // без собственного свечения он выходил тёмно-серым (прогон d8 14.10, demo-04 п.4)
      new THREE.MeshStandardMaterial({ color: fp.ceiling.colorHex, roughness: 1, emissive: fp.ceiling.colorHex, emissiveIntensity: 0.32 }),
    );
    ceil.rotation.x = Math.PI / 2;
    ceil.position.set((room.x + room.w / 2) * CM, room.heightCm * CM, (room.y + room.d / 2) * CM);
    ceil.name = `ceiling:${room.id}`;
    group.add(ceil);
    const lamp = meshesFromBoxes(ceilingLampIR(room.w, room.d, room.heightCm));
    lamp.position.set(room.x * CM, 0, room.y * CM);
    lamp.name = `ceiling:${room.id}:lamp`;   // имя с «ceiling:» — прячется вместе с потолком в виде сверху
    group.add(lamp);
  }

  return { group, floor };
}

/**
 * Что видно за окнами. Плоская синяя заливка читалась как «дырка» (владелец 29.09), поэтому
 * вокруг дома стоит сфера с панорамой: небо, город в дымке, деревья, земля
 * (`tools/assets/material_pipeline.py outside`). Панорама — 27 КБ, грузится один раз.
 */
export function buildSurroundings(rooms: Room[], panoramaUrl = "/flat3d/env/outside.webp"): THREE.Group {
  const g = new THREE.Group();
  const minX = Math.min(...rooms.map((r) => r.x));
  const maxX = Math.max(...rooms.map((r) => r.x + r.w));
  const minY = Math.min(...rooms.map((r) => r.y));
  const maxY = Math.max(...rooms.map((r) => r.y + r.d));
  const cx = ((minX + maxX) / 2) * CM;
  const cz = ((minY + maxY) / 2) * CM;
  const size = Math.max(maxX - minX, maxY - minY) * CM * 6;

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(size, size),
    new THREE.MeshStandardMaterial({ color: 0x7e8a6c, roughness: 1 }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(cx, -0.04, cz);
  g.add(ground);

  const skyMat = new THREE.MeshBasicMaterial({ color: 0xc9dae8, side: THREE.BackSide, fog: false });
  const sky = new THREE.Mesh(new THREE.SphereGeometry(size / 2, 40, 24), skyMat);
  // горизонт панорамы приходится на середину картинки, поэтому сферу поднимаем на уровень
  // глаз: иначе город оказывается «под ногами»
  sky.position.set(cx, 1.6, cz);
  g.add(sky);

  const tex = new THREE.TextureLoader().load(
    panoramaUrl,
    () => {
      skyMat.map = tex;
      skyMat.color.set(0xffffff);
      skyMat.needsUpdate = true;
    },
    undefined,
    () => {
      /* панорамы нет — остаётся ровный светлый цвет, сцена не ломается */
    },
  );
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  return g;
}
