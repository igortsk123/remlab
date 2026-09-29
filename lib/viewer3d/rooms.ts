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
import { buildOpenings } from "@/lib/viewer3d/openings";

const CM = 0.01;
const INSET_CM = 1;

interface Rect {
  u0: number;
  u1: number;
  v0: number;
  v1: number;
}

/** Куски стены, оставшиеся от полотна после вырезания проёмов (координаты вдоль стены, см). */
export function wallRects(lengthCm: number, heightCm: number, openings: Opening[]): Rect[] {
  const sorted = [...openings].sort((a, b) => a.offsetCm - b.offsetCm);
  const out: Rect[] = [];
  let cursor = 0;
  for (const o of sorted) {
    const u0 = Math.max(0, Math.min(lengthCm, o.offsetCm));
    const u1 = Math.max(0, Math.min(lengthCm, o.offsetCm + o.widthCm));
    if (u1 <= u0) continue;
    if (u0 > cursor) out.push({ u0: cursor, u1: u0, v0: 0, v1: heightCm });
    const sill = o.kind === "window" ? (o.sillCm ?? 90) : 0;
    const top = Math.min(heightCm, sill + (o.heightCm ?? (o.kind === "window" ? 140 : 205)));
    if (sill > 0) out.push({ u0, u1, v0: 0, v1: sill });
    if (top < heightCm) out.push({ u0, u1, v0: top, v1: heightCm });
    cursor = Math.max(cursor, u1);
  }
  if (cursor < lengthCm) out.push({ u0: cursor, u1: lengthCm, v0: 0, v1: heightCm });
  return out.filter((r) => r.u1 - r.u0 > 0.5 && r.v1 - r.v0 > 0.5);
}

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
    return list.map((o) => ({ ...o, offsetCm: len - o.offsetCm - o.widthCm }));
  }
  return list;
}

export interface RoomVisual {
  group: THREE.Group;
  /** Плоскость пола — по ней ходит «point-and-go» и считается попадание курсора. */
  floor: THREE.Mesh;
}

export function buildRoom(
  ctx: MaterialCtx,
  room: Room,
  floorMat: Material,
  wallMat: Material,
  opts: { ceiling?: boolean; entranceWall?: string } = {},
): RoomVisual {
  const group = new THREE.Group();
  group.name = `room:${room.id}`;

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
    if (wallOpenings.length > 0) {
      const joinery = buildOpenings(wallOpenings, side, {
        heightCm: room.heightCm,
        entranceWall: opts.entranceWall,
      });
      joinery.position.set(f.ox * CM, 0, f.oy * CM);
      joinery.rotation.y = f.rotY;
      joinery.name = `joinery:${room.id}:${side}`;
      group.add(joinery);
    }

    const rects = wallRects(f.lengthCm, room.heightCm, wallOpenings);
    for (const r of rects) {
      const wCm = r.u1 - r.u0;
      const hCm = r.v1 - r.v0;
      const geo = new THREE.PlaneGeometry(wCm * CM, hCm * CM);
      const mat = tiled(ctx, wallMat, wCm, hCm, 0, [r.u0, r.v0]);
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
      new THREE.MeshStandardMaterial({ color: 0xf6f5f2, roughness: 1 }),
    );
    ceil.rotation.x = Math.PI / 2;
    ceil.position.set((room.x + room.w / 2) * CM, room.heightCm * CM, (room.y + room.d / 2) * CM);
    ceil.name = `ceiling:${room.id}`;
    group.add(ceil);
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
