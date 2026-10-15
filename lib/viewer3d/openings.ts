// Окна и двери: рама, стекло, подоконник, откосы, дверное полотно с наличником.
//
// ЗАЧЕМ ОТДЕЛЬНО: до этого проём был просто дыркой в стене — окно читалось как синий
// прямоугольник, дверь как пустой вырез (владелец 29.09: «вставь вид из окон и окна нормально
// чтоб было; двери и окна визуально должны выглядеть стандартно но хорошо»).
//
// СИСТЕМА КООРДИНАТ: всё строится в ЛОКАЛЬНЫХ осях стены — группа ставится в начало стены и
// поворачивается так, что локальный X идёт вдоль стены (как отступ `offsetCm`), Y — вверх,
// Z — ВНУТРЬ комнаты. Поэтому здесь нет ни одной тригонометрии: размеры пишутся как на чертеже.

import * as THREE from "three";

import type { Opening } from "@/contracts/apartment";
import { openingIR, viewRooms, type IrBackdrop, type OpeningIR, type OpeningMaterial } from "@/lib/viewer3d/opening-ir";
import { WINDOW_VIEWS, windowView } from "@/lib/viewer3d/window-views";

const CM = 0.01;

const WHITE_FRAME = new THREE.MeshStandardMaterial({ color: 0xf4f3f0, roughness: 0.55 });
const REVEAL = new THREE.MeshStandardMaterial({ color: 0xeceae5, roughness: 0.9 });
// Стекло: почти прозрачное. При opacity 0.22 окно читалось белой панелью и закрывало вид
// (кадр 29.09) — стекло должно показывать улицу, а не заменять её.
const GLASS = new THREE.MeshPhysicalMaterial({
  color: 0xeaf2f6,
  roughness: 0.04,
  metalness: 0,
  transparent: true,
  opacity: 0.07,
  depthWrite: false,
  side: THREE.DoubleSide,
});
const DOOR_LEAF = new THREE.MeshStandardMaterial({ color: 0xf2f0ec, roughness: 0.6 });
const DOOR_PANEL = new THREE.MeshStandardMaterial({ color: 0xe8e5e0, roughness: 0.65 });
const HANDLE = new THREE.MeshStandardMaterial({ color: 0xb9bdc2, roughness: 0.25, metalness: 0.85 });

function box(
  w: number,
  h: number,
  d: number,
  x: number,
  y: number,
  z: number,
  material: THREE.Material,
): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w * CM, h * CM, d * CM), material);
  m.position.set(x * CM, y * CM, z * CM);
  m.castShadow = false;
  m.receiveShadow = true;
  return m;
}

// обжитая коробка (demo-04 п.6, `fixtures-ir.ts`): плинтус в тон стены, графитовый карниз, белый плафон
const SKIRTING = new THREE.MeshStandardMaterial({ color: 0xf4f2ee, roughness: 0.6 });
const CORNICE = new THREE.MeshStandardMaterial({ color: 0x3d3d3d, roughness: 0.45, metalness: 0.3 });
const LAMP = new THREE.MeshStandardMaterial({ color: 0xfbfaf7, roughness: 0.8, emissive: 0xfff8ec, emissiveIntensity: 0.6 });

const MATERIAL: Record<OpeningMaterial, THREE.Material> = {
  frame: WHITE_FRAME,
  reveal: REVEAL,
  glass: GLASS,
  leaf: DOOR_LEAF,
  panel: DOOR_PANEL,
  handle: HANDLE,
  skirting: SKIRTING,
  cornice: CORNICE,
  lamp: LAMP,
};

/** Меши набора коробок (плинтус, карниз, светильник — `fixtures-ir.ts`); координаты — в осях того, кто их ставит. */
export function meshesFromBoxes(boxes: { w: number; h: number; d: number; x: number; y: number; z: number; material: OpeningMaterial;
  role: string }[]): THREE.Group {
  const g = new THREE.Group();
  for (const x of boxes) {
    const m = box(x.w, x.h, x.d, x.x, x.y, x.z, MATERIAL[x.material]);
    m.userData.part = x.role;
    g.add(m);
  }
  return g;
}

const viewTextures = new Map<string, THREE.Texture>();

/** Картинка вида — одна на id для всей сцены; без браузера (тесты) — плоскость без картинки. */
function viewMaterial(assetId: string): THREE.MeshBasicMaterial {
  const mat = new THREE.MeshBasicMaterial({ color: 0xc9dae8, toneMapped: false, fog: false });
  const url = WINDOW_VIEWS[assetId]?.url;
  if (!url || typeof document === "undefined") return mat;
  let tex = viewTextures.get(url);
  if (!tex) {
    tex = new THREE.TextureLoader().load(url);
    tex.colorSpace = THREE.SRGBColorSpace;
    viewTextures.set(url, tex);
  }
  mat.map = tex;
  mat.color.set(0xffffff);
  return mat;
}

/** Плоскость вида за окном (`IrBackdrop`): своя часть картинки, лицом в комнату, на `back` см за стеной. */
function backdropMesh(bd: IrBackdrop): THREE.Mesh {
  const geo = new THREE.PlaneGeometry((bd.u1 - bd.u0) * CM, (bd.top - bd.bottom) * CM);
  const uv = geo.attributes.uv as THREE.BufferAttribute;
  for (let i = 0; i < uv.count; i++) {
    uv.setXY(i, bd.uv.u0 + uv.getX(i) * (bd.uv.u1 - bd.uv.u0), bd.uv.v0 + uv.getY(i) * (bd.uv.v1 - bd.uv.v0));
  }
  const m = new THREE.Mesh(geo, viewMaterial(bd.assetId));
  m.position.set(((bd.u0 + bd.u1) / 2) * CM, ((bd.bottom + bd.top) / 2) * CM, -bd.back * CM);
  m.name = "window-view";
  return m;
}

/** Меши проёма из его описания (`opening-ir.ts`) — те же коробки, что получает серверный кадр. */
export function meshesFromIR(ir: OpeningIR): THREE.Group {
  const g = new THREE.Group();
  if (ir.backdrop) g.add(backdropMesh(ir.backdrop));
  const groups = new Map<string, THREE.Group>();
  for (const [name, gr] of Object.entries(ir.groups)) {
    const sub = new THREE.Group();
    sub.position.set(gr.x * CM, gr.y * CM, gr.z * CM);
    sub.rotation.y = (gr.rotYDeg * Math.PI) / 180;
    groups.set(name, sub);
    g.add(sub);
  }
  ir.boxes.forEach((x, i) => {
    const m = box(x.w, x.h, x.d, x.x, x.y, x.z, MATERIAL[x.material]);
    m.userData.part = x.role;
    m.userData.irIndex = i; // номер коробки в описании — по нему тест сверяет деталь с серверным кадром
    (x.group ? groups.get(x.group) ?? g : g).add(m);
  });
  return g;
}

export interface OpeningVisualOpts {
  /** Входная дверь квартиры: полотно закрыто. */
  entranceWall?: string;
  /** Все полотна закрыты (квартира из одной комнаты — двери ведут в несуществующее). */
  doorsClosed?: boolean;
  heightCm: number;
  /** Вид из окна по карточке квартиры (id нашего набора, `window-views.ts`); нет — вид по умолчанию. */
  windowView?: string;
  /** Длина стены — плоскость вида не выходит за её концы. */
  lengthCm?: number;
}

/** Все проёмы одной стены. `openings` уже в координатах «вдоль стены от её начала». */
export function buildOpenings(openings: Opening[], side: string, opts: OpeningVisualOpts): THREE.Group {
  const g = new THREE.Group();
  const { id, view } = windowView(opts.windowView);
  const rooms = viewRooms(openings, opts.lengthCm ?? 1e6);
  openings.forEach((o, i) => g.add(meshesFromIR(openingIR(o, {
    wallHeightCm: opts.heightCm, entrance: !!opts.doorsClosed || opts.entranceWall === side,
    view: { assetId: id, horizon01: view.horizon01, aspect: view.aspect }, viewRoomLo: rooms[i]!.lo, viewRoomHi: rooms[i]!.hi,
  }))));
  return g;
}
