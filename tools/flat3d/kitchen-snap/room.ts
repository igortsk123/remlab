// КОМНАТА ДЛЯ СНИМКА КУХНИ НА КВАРТИРЕ (T-20261105-33, план onb-09 Т4): пол, четыре стены с проёмами окна и двери,
// набор по посадке солвера (`data/partners/kitchen-fit/*.json`: центр и поворот как у предметов — `lib/viewer3d/viewer.ts`
// `g.rotation.y = rot`), отдельный холодильник и стол простыми коробками. Оси плана: x → X, y (вглубь) → Z, см → `CM`.

import * as THREE from "three";

import { CM } from "@/lib/viewer3d/kits/common";

export type Wall = "north" | "south" | "west" | "east";
export interface SnapOpening { kind: string; wall: Wall; offset_cm: number; width_cm: number; sill_cm?: number; height_cm?: number }
export interface SnapBox { wall: Wall | null; x: number; y: number; w: number; d: number; h: number; color: number }
export interface SnapRoom {
  w: number;
  d: number;
  openings: SnapOpening[];
  pose: { x: number; y: number; rot: number };
  boxes: SnapBox[];
  /** top — сверху (юг вверху, как на чертеже); entry — из двери; kit/counter — два вида посадки (eye/target, см). */
  camera: { kind: "top" } | { kind: "eye"; eye: { x: number; y: number; h: number }; target: { x: number; y: number; h: number } };
}

const H = 270;
const T = 8;
const WALL = new THREE.MeshStandardMaterial({ color: 0xf1efea, roughness: 0.9 });
const FLOOR = new THREE.MeshStandardMaterial({ color: 0xc8b89a, roughness: 0.8 });
const GLASS = new THREE.MeshStandardMaterial({ color: 0xbfd9ee, roughness: 0.1, transparent: true, opacity: 0.35 });

/** Кусок стены `wall` от `a` до `b` (см вдоль стены) по высоте от `z0` до `z1`. */
function piece(room: SnapRoom, wall: Wall, a: number, b: number, z0: number, z1: number, mat = WALL): THREE.Mesh {
  const len = b - a;
  const along = wall === "south" || wall === "north";
  const geo = along ? new THREE.BoxGeometry(len * CM, (z1 - z0) * CM, T * CM) : new THREE.BoxGeometry(T * CM, (z1 - z0) * CM, len * CM);
  const m = new THREE.Mesh(geo, mat);
  const mid = (a + b) / 2;
  const y = (z0 + z1) / 2;
  if (wall === "south") m.position.set(mid * CM, y * CM, -T / 2 * CM);
  if (wall === "north") m.position.set(mid * CM, y * CM, (room.d + T / 2) * CM);
  if (wall === "west") m.position.set(-T / 2 * CM, y * CM, mid * CM);
  if (wall === "east") m.position.set((room.w + T / 2) * CM, y * CM, mid * CM);
  m.receiveShadow = true;
  return m;
}

export function roomShell(room: SnapRoom): THREE.Group {
  const g = new THREE.Group();
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(room.w * CM, room.d * CM), FLOOR);
  floor.rotation.x = -Math.PI / 2;
  floor.position.set((room.w / 2) * CM, 0, (room.d / 2) * CM);
  floor.receiveShadow = true;
  g.add(floor);
  for (const wall of ["south", "north", "west", "east"] as Wall[]) {
    const len = wall === "south" || wall === "north" ? room.w : room.d;
    const ops = room.openings.filter((o) => o.wall === wall).sort((p, q) => p.offset_cm - q.offset_cm);
    let at = -T;
    for (const o of ops) {
      g.add(piece(room, wall, at, o.offset_cm, 0, H));
      const a = o.offset_cm;
      const b = o.offset_cm + o.width_cm;
      if (o.kind === "window") {
        const sill = o.sill_cm ?? 90;
        const top = sill + (o.height_cm ?? 150);
        g.add(piece(room, wall, a, b, 0, sill), piece(room, wall, a, b, top, H), piece(room, wall, a, b, sill, top, GLASS));
      } else {
        g.add(piece(room, wall, a, b, 210, H));
      }
      at = b;
    }
    g.add(piece(room, wall, at, len + T, 0, H));
  }
  for (const b of room.boxes) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(b.w * CM, b.h * CM, b.d * CM), new THREE.MeshStandardMaterial({ color: b.color, roughness: 0.5 }));
    m.position.set(b.x * CM, (b.h / 2) * CM, b.y * CM);
    m.castShadow = true;
    g.add(m);
  }
  return g;
}

/** Набор кухни на место посадки: центр следа и поворот лицом в комнату. */
export function placeKit(kit: THREE.Object3D, room: SnapRoom): void {
  kit.position.set(room.pose.x * CM, 0, room.pose.y * CM);
  kit.rotation.y = (room.pose.rot * Math.PI) / 180;
}

export function roomCamera(room: SnapRoom, aspect: number): THREE.Camera {
  const c = room.camera;
  if (c.kind === "top") {
    // план сверху — ортографический (стены не заваливаются), комната с полями по 40 см
    const halfW = Math.max(room.w + 80, (room.d + 80) * aspect) / 2;
    const halfH = halfW / aspect;
    const cam = new THREE.OrthographicCamera(-halfW * CM, halfW * CM, halfH * CM, -halfH * CM, 0.05, 20);
    cam.position.set((room.w / 2) * CM, 6, (room.d / 2) * CM);
    cam.up.set(0, 0, -1); // юг (y = 0, наружная стена) — вверху кадра, как на чертеже
    cam.lookAt((room.w / 2) * CM, 0, (room.d / 2) * CM);
    return cam;
  }
  const cam = new THREE.PerspectiveCamera(aspect < 1 ? 75 : 62, aspect, 0.05, 60);
  cam.position.set(c.eye.x * CM, c.eye.h * CM, c.eye.y * CM);
  cam.lookAt(c.target.x * CM, c.target.h * CM, c.target.y * CM);
  return cam;
}
