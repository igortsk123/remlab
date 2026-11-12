// Рантайм-слой 3D: сцена, свет, прогулка, ленивая подгрузка комнат, попадание курсора.
//
// Это единственный файл, который знает про WebGL. UI (React) им ТОЛЬКО управляет: даёт
// разрешённую конфигурацию и команды («в эту комнату», «выдели этот слот»), получает события.
// Императивный класс выбран сознательно (ADR-0210): его можно завести в тесте и в любой
// обёртке, он не завязан на реконсилер React.
//
// Размер файла оправдан: это движок одной сцены, дробить его на «компоненты по 100 строк»
// дороже для чтения, чем держать цикл кадра рядом с его состоянием.

import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

import type { Apartment, Placement, Room } from "@/contracts/apartment";
import { entranceOf, findRoom, isIsolatedRoom, roomAt, roomCentre } from "@/contracts/apartment";
import { material as materialSchema, type Catalogue, type Material } from "@/contracts/configurator";
import type { ResolvedScene } from "@/lib/configurator/resolve";
import { isExtra, isFlatOnSurface, type ObjectSpec, planObjects, surfacesByRoom } from "@/lib/viewer3d/build-scene";
import { buildKitchen } from "@/lib/viewer3d/kits/kitchen";
import { buildBathroom } from "@/lib/viewer3d/kits/bathroom";
import { buildBed, buildRug, buildWardrobe } from "@/lib/viewer3d/kits/bedroom";
import { buildTv } from "@/lib/viewer3d/kits/tv";
import { buildWallPlane } from "@/lib/viewer3d/kits/wall-plane";
import type { KitCtx } from "@/lib/viewer3d/kits/common";
import { createMaterialCtx, disposeMaterialCtx, type MaterialCtx } from "@/lib/viewer3d/materials";
import { ContactShadow, roomsBounds } from "@/lib/viewer3d/contact-shadow";
import { fadeForMove, floorFootprint } from "@/lib/viewer3d/footprint";
import { buildCurtains, LIGHT, sunPose } from "@/lib/viewer3d/window-light";
import { MeshLibrary, chaiseSide, disposeObject, placeMesh, stubBox } from "@/lib/viewer3d/meshes";
import { outlineFrame } from "@/lib/viewer3d/outline";
import { renderThumbs } from "@/lib/viewer3d/thumbs";
import { buildRoom, buildSurroundings } from "@/lib/viewer3d/rooms";
import { boxPoints, livePitchDeg, liveSpot, lookPitchRange, LIVE_EYE_CM, type LiveBand, type LivePoint } from "@/lib/viewer3d/live-eye";
import { canStand, frameSpot, inRooms, nearestStandable, obstacleDistanceCm, walkArea, walkRoomAt, type WalkArea } from "@/lib/viewer3d/walk";
import { followRoute, newRoute, planRoute, slideStep, type RouteState, type SlideMemo } from "@/lib/viewer3d/walk-motion";
import { chooseAim, type WalkHits } from "@/lib/viewer3d/walk-aim";
import { createWalkMarker, placeWalkMarker, pulseWalkMarker, type WalkMarker } from "@/lib/viewer3d/walk-marker";
import { windowAtPoint, windowGap, windowSpot } from "@/lib/viewer3d/window-walk";

// ВХОД БЕЗ ФЛАГА (T-20261106-72): прихожая без проёма `isEntrance` — вход угадан стеной; говорим об этом один раз на комнату
const entranceWarned = new Set<string>();
function warnEntranceOnce(roomId: string, wall: string): void {
  if (entranceWarned.has(roomId)) return;
  entranceWarned.add(roomId);
  console.warn(`прихожая ${roomId}: нет проёма с isEntrance — вход угадан по стене ${wall}`);
}

const CM = 0.01;
// пределы «кукольного дома»: ближе 2,4 м камера влезает в мебель, дальше 30 м квартира — точка
const TOP_MIN_CM = 240;
const TOP_MAX_CM = 3000;

/** Рисует ли браузер силами процессора (SwiftShader, llvmpipe, программный ANGLE). */
function isSoftwareRenderer(renderer: THREE.WebGLRenderer): boolean {
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const name = String(
      ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
    );
    return /swiftshader|llvmpipe|software|microsoft basic/i.test(name);
  } catch {
    return false;
  }
}
const EYE_CM = 162;

export interface QualityProfile {
  name: "desktop" | "lite";
  pixelRatio: number;
  shadows: boolean;
  anisotropy: number;
  extraMaps: boolean;
  /** Сколько комнат вокруг текущей грузим сразу (0 — только текущую). */
  preloadRooms: number;
  fov: number;
}

export const DESKTOP_QUALITY: QualityProfile = {
  name: "desktop",
  pixelRatio: 2,
  shadows: true,
  anisotropy: 8,
  extraMaps: true,
  preloadRooms: 2,
  fov: 62,
};

/** «3D Lite» для телефона: без теней, меньше пикселей, только цветовые карты. */
export const LITE_QUALITY: QualityProfile = {
  name: "lite",
  pixelRatio: 1.4,
  shadows: false,
  anisotropy: 2,
  extraMaps: false,
  preloadRooms: 0,
  fov: 70,
};

export interface ViewerEvents {
  onPick?: (slotId: string | null) => void;
  onRoomChange?: (roomId: string | null) => void;
  onProgress?: (loaded: number, total: number) => void;
  /** Видеоконтекст потерян (мало памяти GPU, вкладка в фоне на телефоне) — обёртка переходит на запасной путь. */
  onContextLost?: () => void;
}

export interface ViewerOptions {
  /** Декоративные шторы у окон (T-20261111-22). Нет — `CURTAINS_DEFAULT`. */
  curtains?: boolean;
}

/** Шторы по умолчанию ВКЛ (владелец TG 1643 «Шторы ставь»). Откат — `false` здесь или `?curtains=0` в адресе демо. */
export const CURTAINS_DEFAULT = true;

/**
 * ФОТО-ПОЗА — ТА ЖЕ КАМЕРА, ЧТО У СЕРВЕРНОГО КАДРА (план demo-01 п.3, урок 414): точка на плане (см), `rot` — как у
 * точки съёмки демо и `draft_render.cams_from_request`: взгляд (sin rot, −cos rot) по плану, глаз 165 см, цель —
 * 105 см в 4 м перед глазом, `fov` — ГОРИЗОНТАЛЬНЫЙ угол (`planner/scene.py:Camera`). У прогулки другая конвенция
 * (heading 0 = +y), поэтому позу нельзя передавать прогулке «как угол».
 */
export interface PhotoPose {
  x: number;
  y: number;
  rot: number;
  fov?: number;
  /** Версия позы (`draft_render.photo_pose_heights`): 1 — глаз 165 и наклон к 105 в 4 м; 2 — глаз 135, камера
   *  горизонтальна, кадр опущен сдвигом объектива (вертикали прямые, demo-02 14.10); 3 — глаз 150, взгляд вниз на 8°, сдвиг
   *  как у 2 (T-73/6). Нет — 1, как у старых кадров. */
  pose?: number;
  /** Сдвиг объектива ВЕРТИКАЛЬНОГО кадра (телефон), доля высоты: пол и потолок поровну, мебель — в средней трети (demo-12,
   *  подбор `camPortraitShift` в блоке CAMFIT демо). Есть — вертикальный кадр не наклоняется к мебели, вертикали прямые. */
  pshift?: number;
  /** Нижний предел наклона «3D» глазами стоящего, градусы (вниз — минус): зона комнаты задаёт свой (`CAM_ZONES.hall.livePitchMin`,
   *  T-20261107-05/8 — в узком коридоре при −40° низкая мебель у входа в метре от глаза попадала в угол кадра). Нет — `LIVE_PITCH_MIN`. */
  pitchMin?: number;
}
export const PHOTO_EYE_CM = 165;
export const PHOTO_TARGET_CM = 105;
export const PHOTO_AIM_CM = 400;
export const PHOTO_POSE_VER = 3;
const POSE_V2 = { eye: 135, target: 135, shift: -0.1 };
/** v3 (T-20261108-73/6, владелец TG 690 «камера чуть выше и слегка вниз»): глаз 150, взгляд вниз на 8° (цель — на `PHOTO_AIM_CM`
 *  впереди, ниже глаза), сдвиг объектива — как у v2. При горизонтальном взгляде с 135 см низ кровати и дивана уходил под кадр.
 *  Те же числа — `draft_render.PHOTO_POSE_V3` и `CAM_POSE` в блоке CAMFIT демо (мера подбора ракурсов). */
export const POSE_V3_PITCH = 8;
const POSE_V3 = { eye: 150, target: 150 - PHOTO_AIM_CM * Math.tan((POSE_V3_PITCH * Math.PI) / 180), shift: -0.1 };
const poseOf = (p: PhotoPose) => ((p.pose ?? 1) >= 3 ? POSE_V3 : (p.pose ?? 1) >= 2 ? POSE_V2 : null);

/** Точки глаза и цели фото-позы в сантиметрах (x — вправо, y — вверх, z — вглубь плана). Общая для теста и рендера. */
export function photoRay(p: PhotoPose): { eye: [number, number, number]; target: [number, number, number] } {
  const a = (p.rot * Math.PI) / 180;
  const q = poseOf(p);
  return {
    eye: [p.x, q ? q.eye : PHOTO_EYE_CM, p.y],
    target: [p.x + PHOTO_AIM_CM * Math.sin(a), q ? q.target : PHOTO_TARGET_CM, p.y - PHOTO_AIM_CM * Math.cos(a)],
  };
}

/** Сдвиг объектива позы, доля высоты кадра (как `planner/scene.py:Camera.shift_y`: минус — кадр ниже, видно больше пола).
 *  Вертикальный кадр (`aspect` < 1) с подобранным `pshift` — свой сдвиг (demo-12). */
export function photoShift(p: PhotoPose, aspect = 1.5): number {
  if (aspect < 1 && typeof p.pshift === "number") return p.pshift;
  const base = poseOf(p)?.shift ?? 0;
  // КАДР КОМПЬЮТЕРА ВО ВСЮ ОБЛАСТЬ (demo-15, fable-lead 18.10: поля над и под полосой 3:2 — пустое место). Область уже 3:2,
  // но не вертикальная: верхний край — как у кадра 3:2 (потолка не больше, прогон d8 14.10), вся добавочная высота — в пол.
  // В долях −1…1 сдвиг верхнего края — `2·shift`; при 3:2 формула даёт ровно `base`.
  if (aspect >= 1 && aspect < 1.5) {
    const t = Math.tan(((p.fov ?? 72) * Math.PI) / 360), top = (t / 1.5) * (1 + 2 * base), half = t / aspect;
    return (top / half - 1) / 2;
  }
  return base;
}

/** Сдвиг объектива на камере three.js: окно проекции опускается на долю высоты, вертикали остаются параллельными.
 *  Задан долей, а не пикселями, — переживает смену размера холста и экспорт кадра. */
export function applyPhotoShift(cam: THREE.PerspectiveCamera, shift: number): void {
  // `setViewOffset` переписывает aspect = fullWidth / fullHeight — поэтому «полный кадр» задаём в пропорциях камеры
  if (shift) cam.setViewOffset(cam.aspect, 1, 0, -shift, cam.aspect, 1);
  else if (cam.view) cam.clearViewOffset();
}

/** Вертикальный угол three.js из горизонтального угла кадра и соотношения сторон. */
export function verticalFov(hfovDeg: number, aspect: number): number {
  const t = Math.tan((hfovDeg * Math.PI) / 360) / Math.max(aspect, 1e-3);
  return (Math.atan(t) * 360) / Math.PI;
}


interface Placed {
  spec: ObjectSpec;
  /** Внешняя группа: позиция и поворот предмета. Внутри — модель, отцентрованная в начале координат. */
  group: THREE.Group;
  /** Что требует пересоздать объект (модель, размеры, подкраска); место и поворот сюда не входят. */
  signature: string;
  /** Модель пришла / осталась честной коробкой / ещё грузится (demo-10: коробка уходит в кадр нейросети как «clay»). */
  status: "loaded" | "stub" | "pending";
}

/** Нейтральная белая краска — когда в каталоге нет ни одного материала. */
const NEUTRAL_WALL: Material = materialSchema.parse({ id: "neutral-white", titleRu: "Белый", titleEn: "White", colorHex: "#f2f0ec", roughness: 0.95 });

export class FlatViewer {
  readonly scene = new THREE.Scene();
  private renderer: THREE.WebGLRenderer;
  private camera: THREE.PerspectiveCamera;
  private raycaster = new THREE.Raycaster();
  private clock = new THREE.Clock();
  private raf = 0;
  private disposed = false;

  private apartment: Apartment;
  private catalogue: Catalogue;
  private quality: QualityProfile;
  private events: ViewerEvents;

  private matCtx: MaterialCtx;
  private kitCtx: KitCtx;
  private meshes: MeshLibrary;

  private roomGroups = new Map<string, THREE.Group>();
  private floors: THREE.Mesh[] = [];
  private placed = new Map<string, Placed>();
  private pendingUrls = new Set<string>();
  private loadedCount = 0;
  private totalCount = 0;

  private area: WalkArea;
  private pos = new THREE.Vector2(); // см, координаты квартиры
  private heading = 0; // градусы, 0 = смотрим в +y
  private pitch = 0;
  private keys = new Set<string>();
  /** Путь «иди сюда» (тап по полу): точки поворота в обход мебели и счётчик упора (`walk-motion.ts:followRoute`). */
  private moveTarget: RouteState | null = null;
  /** Куда повернуться, дойдя до окна (`walkToWindow`): курс и наклон; взгляд рукой, тап по полу, клавиши, ракурс — снимают. */
  private faceAt: { heading: number; pitch: number } | null = null;
  /** Кольцо «сюда пойдём» (T-20261112-36, `walk-marker.ts`): `hover` — под мышью, `route` — цель идущего пути, гаснет, дойдя. */
  private walkMarker: WalkMarker | null = null;
  private markerMode: "hover" | "route" | null = null;
  /** Сторона обхода «почти в лоб» при ходьбе клавишами — липкая, чтобы обход не метался (`walk-motion.ts:slideStep`). */
  private slideMemo: SlideMemo = { side: 0, free: 0 };
  /** Плавный вход в прогулку из точки ракурса (T-20261111-14): с какого угла обзора, высоты глаз и сдвига камера доезжает до своих. */
  private walkBlend: { t0: number; ms: number; fov: number; eye: number; dx: number; dy: number } | null = null;
  private currentRoom: string | null = null;
  /**
   * Режим камеры: прогулка или «кукольный дом» — вид сверху под углом (владелец 29.09).
   * Сверху удобно понять планировку и расстановку целиком, а ходить — чтобы «пожить» в комнате.
   */
  private viewMode: "walk" | "top" | "photo" = "walk";
  private photo: PhotoPose | null = null;
  /**
   * 3D ИЗ ТОЧКИ СЪЁМКИ (demo-09, владелец 17.10): «3D» окна стоит в позе ракурса — тот же кадр, что снимет «Сделать
   * реалистичнее», — и перетаскиванием поворачивает взгляд вокруг этой точки (`photoLook`, градусы). Переход между позами
   * C1/C2 — плавный (`poseAnim`: разница «откуда − куда» гаснет за `ms`).
   */
  private photoLook = { yaw: 0, pitch: 0 };
  /** Портрет телефона (приёмка d8 17.10): в позе взгляд наклонён к мебели, иначе верх кадра — потолок. Снимок сервера — без наклона. */
  private tilt = false;
  /**
   * «3D» глазами стоящего (demo-27, `live-eye.ts`): есть — живая фото-поза берёт глаз `eyeCm` вместо высоты кадра нейросети, без
   * сдвига объектива, с наклоном вниз, при котором мебель — в видимой полосе холста `band`. Кадры нейросети (`capturePhoto`) — как были.
   */
  private liveEye: { eyeCm: number; band: LiveBand } | null = null;
  /** Поза ракурса как пришла: `photo` из неё при «3D» глазами стоящего — с глазом не ближе 50 см к стенам (`liveSpot`). */
  private photoRaw: PhotoPose | null = null;
  private poseAnim: { dx: number; dy: number; yaw: number; pitch: number; t0: number; ms: number } | null = null;
  /** Кэш точки ценника над предметом: `Box3` по группе — дорого на каждый кадр (Codex 17.10, ценники в прогулке). */
  private anchors = new Map<string, { g: THREE.Object3D; px: number; pz: number; ry: number; t: number; c: THREE.Vector3; bb: THREE.Box3 }>();
  private topTarget = new THREE.Vector2();   // точка, вокруг которой крутится вид сверху
  private topDistanceCm = 620;
  private topPitch = -52;
  /** Последняя разрешённая сцена — по ней догружаем комнату, в которую вошли. */
  private lastScene: ResolvedScene | null = null;
  private syncing = false;
  private options: ViewerOptions;
  /** Солнце и заполняющий — их ставит `aimLights` по окну комнаты. */
  private sun: THREE.DirectionalLight | null = null;
  private fill: THREE.DirectionalLight | null = null;
  /** Запечённая тень мебели на полу (`contact-shadow.ts`); пересоздаётся с оболочкой. */
  private contact: ContactShadow | null = null;
  private curtains: THREE.Group | null = null;

  constructor(
    canvas: HTMLCanvasElement,
    apartment: Apartment,
    catalogue: Catalogue,
    quality: QualityProfile,
    events: ViewerEvents = {},
    options: ViewerOptions = {},
  ) {
    this.apartment = apartment;
    this.catalogue = catalogue;
    this.quality = quality;
    this.events = events;
    this.options = options;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: quality.name === "desktop", powerPreference: "high-performance" });
    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      // освобождённая сцена своё «контекст потерян» не сообщает (T-20261106-77/3): демо пересоздаёт сцену при смене комнаты,
      // и браузер, закрывая старый контекст, выключал 3D у новой
      if (!this.disposed) this.events.onContextLost?.();
    });
    // Без видеокарты (виртуалки, старые офисные машины, CI) браузер рисует силами процессора.
    // Полноэкранная сцена с тенями там не тянет — вкладка падает. Переходим на облегчённый
    // профиль: человек увидит квартиру, пусть и проще, вместо «страница не отвечает».
    if (isSoftwareRenderer(this.renderer)) {
      this.quality = { ...LITE_QUALITY, fov: quality.fov, preloadRooms: quality.preloadRooms };
      quality = this.quality;
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, quality.pixelRatio));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    // ТОВАРНЫЙ тонмаппинг (Khronos PBR Neutral), а не кинематографический ACES: ACES уводит
    // насыщенные тона к белому тем сильнее, чем светлее место — жёлтый диван у окна выцветал
    // до бежевого (замер 29.09: насыщенность 74 из 255 при цели 151). Здесь человек выбирает
    // товар по цвету, поэтому цвет важнее «киношной» картинки.
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    // калибровка по эталону — `window-light.ts:LIGHT` (T-20261111-22/2); при 1.05+ белый шкаф терял рельеф дверей
    this.renderer.toneMappingExposure = LIGHT.exposure;
    if (quality.shadows) {
      this.renderer.shadowMap.enabled = true;
      this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    }

    this.camera = new THREE.PerspectiveCamera(quality.fov, 1, 0.05, 80);
    this.scene.background = new THREE.Color(0xeef2f5);

    this.matCtx = createMaterialCtx(quality.anisotropy, true);
    this.matCtx.extraMaps = quality.extraMaps;
    const byId = (id: string): Material | undefined => catalogue.materials.find((m) => m.id === id);
    this.kitCtx = {
      materials: this.matCtx,
      byId,
      // У набора из витрины (`?demo=`) своих материалов нет вовсе — без встроенного запасного
      // сцена падала на первой же стене (13.10, белый экран «Application error»).
      fallback: byId("paint-white") ?? catalogue.materials[0] ?? NEUTRAL_WALL,
    };
    this.meshes = new MeshLibrary({ ktx2Path: "/vendor/basis/", renderer: this.renderer });

    this.area = walkArea(apartment);
    this.pos.set(apartment.spawn.x, apartment.spawn.y);
    this.heading = apartment.spawn.rot;

    this.addLights();
    this.scene.add(buildSurroundings(apartment.rooms));
  }

  private addLights(): void {
    // ОКРУЖЕНИЕ (environment): без него PBR-материалы выглядят плоско — у них нечего отражать
    // (замечание Codex 28.09). `RoomEnvironment` — процедурная комната из three, файлов не тянет.
    try {
      const pmrem = new THREE.PMREMGenerator(this.renderer);
      const env = new RoomEnvironment();
      this.scene.environment = pmrem.fromScene(env, 0.04).texture;
      this.scene.environmentIntensity = LIGHT.env;
      env.dispose?.();
      pmrem.dispose();
    } catch {
      /* старый GPU/программный рендер — живём без окружения */
    }
    // КАЛИБРОВКА T-20261111-22 («нейтральная», прототип `tools/design/mock/light3d/`): белое небо и светлый отскок от пола —
    // стены белые, как в эталоне владельца (тёплые оттенки делали их кремовыми и сдвигали цвет товара, Δab 2 → 6); солнце бьёт
    // из окна (`aimLights`), его тень мягкая и светлая — серая полутень, не чёрное пятно; числа — `window-light.ts:LIGHT`
    this.scene.add(new THREE.HemisphereLight(LIGHT.hemiSky, LIGHT.hemiGround, LIGHT.hemi));
    const sun = new THREE.DirectionalLight(LIGHT.sunColor, LIGHT.sun);
    sun.position.set(-6, 9, -4);
    if (this.quality.shadows) {
      sun.castShadow = true;
      sun.shadow.mapSize.set(1024, 1024);
      sun.shadow.camera.near = 1;
      sun.shadow.camera.far = 40;
      const s = 9;
      sun.shadow.camera.left = -s;
      sun.shadow.camera.right = s;
      sun.shadow.camera.top = s;
      sun.shadow.camera.bottom = -s;
      sun.shadow.bias = -0.0008;
      sun.shadow.radius = 6;
      sun.shadow.intensity = 0.5;
    }
    this.scene.add(sun);
    // мягкая подсветка с комнатной стороны (отражённый от стен свет), чтобы мебель не проваливалась в чёрное на телефоне
    const fill = new THREE.DirectionalLight(0xf3f1ec, LIGHT.fill);
    fill.position.set(5, 3, 6);
    this.scene.add(fill);
    this.sun = sun;
    this.fill = fill;
  }

  /** Солнце — за окном комнаты, светит в её середину; заполняющий — с другой стороны (`window-light.ts:sunPose`). Окон нет — как было. */
  private aimLights(): void {
    const pose = sunPose(this.apartment.rooms);
    if (!pose || !this.sun || !this.fill) return;
    this.sun.position.set(...pose.sun);
    this.sun.target.position.set(...pose.target);
    this.sun.target.updateMatrixWorld();
    this.fill.position.set(...pose.fill);
    if (this.sun.castShadow) {
      const c = this.sun.shadow.camera;
      Object.assign(c, { left: -pose.half, right: pose.half, top: pose.half, bottom: -pose.half, near: 1, far: 20 });
      c.updateProjectionMatrix();
    }
  }

  /** Мебель, что даёт тень на пол: без ковров и плоского на стене, без ТВ на стене и без предмета «в руке» (его место — след переноса). */
  private shadowCasters(): THREE.Object3D[] {
    const inHand = this.moving?.slotId;
    return [...this.placed.values()]
      .filter((p) => p.spec.slotId !== inHand && !isFlatOnSurface(p.spec) && !(p.spec.kind === "tv" && p.spec.hung))
      .map((p) => p.group);
  }

  /** Запечь тень мебели в простое браузера (повторные вызовы до запекания сливаются в одно). */
  private bakeContact(): void {
    this.contact?.schedule(() => this.shadowCasters());
  }

  // ── сцена ────────────────────────────────────────────────────────────────

  /** Полная пересборка коробки квартиры (пол/стены/потолок) под текущие материалы. */
  buildShell(resolved: ResolvedScene): void {
    const surfaces = surfacesByRoom(resolved);
    for (const [, g] of this.roomGroups) {
      this.scene.remove(g);
      disposeObject(g);
    }
    this.roomGroups.clear();
    this.floors = [];

    for (const room of this.apartment.rooms) {
      const s = surfaces.get(room.id) ?? {};
      const floorMat = s.floor?.material ?? this.kitCtx.fallback;
      const wallMat = s.wall?.material ?? this.kitCtx.fallback;
      // вход в квартиру — проём с `isEntrance` (данные экземпляра, T-20261106-72), его полотно закрыто; флага нет — у прихожей
      // прежняя эвристика «южная стена» с предупреждением (`entranceOf`). Комната без соседей (живая сцена демо, комнаты варианта
      // витрины в /flat — ряд с зазором, onb-11): двери ведут в несуществующее — полотно закрыто, как на интерьерном снимке и на
      // серверном кадре (`tools/flat3d/opening-ir.mjs`); распахнутое у угла закрывало четверть кадра (demo-04, 14.10)
      const ent = entranceOf(room);
      if (!ent.flagged && ent.fallbackWall) warnEntranceOnce(room.id, ent.fallbackWall);
      const entranceWall = ent.fallbackWall;
      const doorsClosed = isIsolatedRoom(this.apartment, room);
      const accent = s.wall?.accent;
      const { group, floors } = buildRoom(this.matCtx, room, floorMat, wallMat, { entranceWall, doorsClosed, ...(accent ? { accent } : {}) });
      group.userData.roomId = room.id;
      for (const f of floors) f.userData.roomId = room.id;   // пол пристройки — пол её комнаты (T-20261112-36)
      if (this.viewMode === "top") group.traverse((o) => { if (o.name === "window-view:skirt") o.visible = false; });
      this.scene.add(group);
      this.roomGroups.set(room.id, group);
      this.floors.push(...floors);
    }
    this.aimLights();
    this.shellExtras();
  }

  /** Тень мебели на полу и шторы — по комнатам квартиры; пересоздаются с оболочкой (комнаты могли смениться). */
  private shellExtras(): void {
    this.contact?.dispose();
    this.contact = null;
    const b = roomsBounds(this.apartment.rooms);
    if (b) this.contact = new ContactShadow(this.renderer, this.scene, b, { res: this.quality.name === "lite" ? 256 : 512 });
    if (this.curtains) {
      this.scene.remove(this.curtains);
      disposeObject(this.curtains);
      this.curtains = null;
    }
    if (this.options.curtains ?? CURTAINS_DEFAULT) {
      this.curtains = buildCurtains(this.apartment.rooms);
      this.scene.add(this.curtains);
    }
    if (this.placed.size) this.bakeContact();   // смена отделки при готовой мебели; первую тень запечёт `syncObjects`
  }

  /**
   * Обновление предметов: пересобираем только изменившееся.
   *
   * ЛЕНИВО ПО КОМНАТАМ: в лёгком режиме (телефон) грузим только текущую комнату и её соседей
   * по списку — требование ТЗ «сначала текущая/ближайшая». На десктопе тянем всё сразу,
   * порядком «где человек стоит → ближайшие».
   */
  async syncObjects(resolved: ResolvedScene): Promise<void> {
    this.lastScene = resolved;
    const lite = this.quality.name === "lite";
    const all = planObjects(this.apartment, this.catalogue, resolved, { lite });
    const order = this.roomOrder();
    const allowedRooms = new Set(
      this.quality.preloadRooms > 0 ? order.slice(0, this.quality.preloadRooms + 1) : order.slice(0, 1),
    );
    const specs = all.filter((s) => allowedRooms.has(s.roomId));
    const wanted = new Map(all.map((s) => [s.slotId, s]));
    // ПРОГУЛКА НЕ СКВОЗЬ МЕБЕЛЬ (demo-05 п.5): следы всех предметов, кроме ковра и плоского, — препятствия зоны прогулки;
    // набор санузла описан коробкой на всю комнату (сантехника внутри расставляется кодом) — его след не препятствие;
    // производное (ТВ над тумбой) стоит на тумбе или висит на стене — препятствие уже тумба
    this.area = walkArea(this.apartment, 28, all
      .filter((sp) => !isFlatOnSurface(sp) && sp.kind !== "bathroom" && !isExtra(sp.slotId) && sp.placement.hCm > 10)
      .map((sp) => ({ x: sp.placement.x, y: sp.placement.y, w: sp.placement.wCm, d: sp.placement.dCm, rot: sp.placement.rot, h: sp.placement.hCm })));
    // счётчик считаем ЗАНОВО на каждой синхронизации: раньше он копился между вызовами и
    // «загружено» обгоняло «всего» — процент прыгал выше 100 (находка советника 30.09)
    this.totalCount = specs.length;
    this.loadedCount = specs.filter((sp) => this.placed.get(sp.slotId)?.signature === signatureOf(sp)).length;
    this.events.onProgress?.(Math.min(this.loadedCount, this.totalCount), this.totalCount);

    for (const [slotId, p] of [...this.placed]) {
      const next = wanted.get(slotId);
      if (!next || signatureOf(next) !== p.signature) {
        this.scene.remove(p.group);
        disposeObject(p.group);
        this.placed.delete(slotId);
      } else {
        // ДВИЖЕНИЕ БЕЗ ПЕРЕСОЗДАНИЯ (demo-01 п.4): сменились только место/поворот — двигаем внешнюю группу; модель,
        // её загрузка и материалы остаются. Раньше координаты входили в подпись, и каждый сдвиг удалял объект.
        placeGroup(p.group, next.placement);
        p.spec = next;
      }
      this.refreshSelection(slotId);
    }

    const sorted = [...specs].sort((a, b) => order.indexOf(a.roomId) - order.indexOf(b.roomId));
    const queue = sorted.filter((s) => !this.placed.has(s.slotId));
    // Грузим ПАРАЛЛЕЛЬНО, но не больше четырёх сразу: последовательная загрузка растягивала
    // наполнение комнаты на десяток секунд, а без ограничения телефон захлёбывается на старте.
    const CONCURRENCY = this.quality.name === "lite" ? 2 : 4;
    let cursor = 0;
    const worker = async (): Promise<void> => {
      while (cursor < queue.length && !this.disposed) {
        const spec = queue[cursor];
        cursor += 1;
        if (!spec) return;
        await this.addObject(spec);
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker));
    // тень — по ГОТОВОЙ расстановке (модели пришли, места новые): в простое, первый кадр её не ждёт
    if (!this.disposed) this.bakeContact();
  }

  /** Порядок загрузки: текущая комната, потом соседние — «сначала то, где человек стоит». */
  private roomOrder(): string[] {
    const cur = this.currentRoom ?? roomAt(this.apartment, this.pos.x, this.pos.y)?.id ?? this.apartment.rooms[0]!.id;
    const rest = this.apartment.rooms.map((r) => r.id).filter((id) => id !== cur);
    const centre = roomCentre(findRoom(this.apartment, cur)!);
    rest.sort((a, b) => {
      const ca = roomCentre(findRoom(this.apartment, a)!);
      const cb = roomCentre(findRoom(this.apartment, b)!);
      return Math.hypot(ca.x - centre.x, ca.y - centre.y) - Math.hypot(cb.x - centre.x, cb.y - centre.y);
    });
    return [cur, ...rest];
  }

  private async addObject(spec: ObjectSpec): Promise<void> {
    const p = spec.placement;
    let group: THREE.Group;
    // ДВЕ СИНХРОНИЗАЦИИ ПОДРЯД (demo-05 п.5, прогон d8 15.10): в /flat обе видели «предмета нет» и ставили его дважды —
    // карта помнила второй, а первый оставался в сцене пустой каркасной коробкой вокруг загруженной модели. Тот же
    // предмет уже ставится — второй раз не ставим; другой — прежний убираем из сцены
    const prev = this.placed.get(spec.slotId);
    if (prev) {
      if (prev.signature === signatureOf(spec)) return;
      this.scene.remove(prev.group);
      disposeObject(prev.group);
      this.placed.delete(spec.slotId);
    }

    if (spec.kind === "mesh") {
      // ВНЕШНЯЯ ГРУППА = МЕСТО И ПОВОРОТ, ВНУТРИ — МОДЕЛЬ В НАЧАЛЕ КООРДИНАТ (demo-01 п.4). Посадка та же, что у
      // `placeMesh` с местом (поворот вокруг центра следа не сдвигает центр и низ), но сдвиг/поворот предмета —
      // это одна запись в трансформ, без новой модели.
      const outer = new THREE.Group();
      const local = { xCm: 0, yCm: 0, rotDeg: 0, wCm: p.wCm, dCm: p.dCm, hCm: p.hCm, elevCm: 0 };
      const stub = stubBox(local, true);
      // ЗАГЛУШКА НЕ ВИДНА, ПОКА МОДЕЛЬ ГРУЗИТСЯ (прогон d8 15.10: на старте /flat серые каркасные коробки читались как
      // поломка): ход загрузки показывает счётчик. Коробка появляется, только если модель не пришла или грузится дольше
      // STUB_SHOW_MS — тогда честное «здесь предмет» лучше пустого места
      stub.visible = false;
      const showStub = setTimeout(() => { stub.visible = true; }, STUB_SHOW_MS);
      outer.add(stub);
      placeGroup(outer, p);
      outer.userData = { slotId: spec.slotId, roomId: spec.roomId, title: spec.titleRu };
      this.scene.add(outer);
      this.placed.set(spec.slotId, { spec, group: outer, signature: signatureOf(spec), status: "pending" });
      this.refreshSelection(spec.slotId);

      try {
        this.pendingUrls.add(spec.url);
        const source = await this.meshes.load(spec.url);
        if (this.disposed) return;
        // Г-ДИВАН: оттоманка — с той стороны, что выбрал расстановщик (владелец 14.10: «столик наезжает на диван»)
        let mirror = false;
        if (p.cornerLeft !== undefined) {
          const side = chaiseSide(source, spec.yawDeg);
          mirror = side !== null && side !== (p.cornerLeft ? "left" : "right");
        }
        const real = placeMesh(source, { ...local, yawDeg: spec.yawDeg, tintRgb: spec.tintRgb, mirror });
        const cur = this.placed.get(spec.slotId);
        if (cur && cur.group === outer) {
          outer.remove(stub);
          disposeObject(stub);
          outer.add(real);
          cur.status = "loaded";
          this.refreshSelection(spec.slotId);
        } else {
          // пока грузилась, предмет заменили или убрали: эта группа больше не нужна — не оставляем её в сцене
          this.scene.remove(outer);
          disposeObject(outer);
        }
      } catch {
        // модель не пришла — остаётся честная серая коробка, как в демо
        stub.visible = true;
        const cur = this.placed.get(spec.slotId);
        if (cur && cur.group === outer) cur.status = "stub";
      } finally {
        clearTimeout(showStub);
        this.pendingUrls.delete(spec.url);
        this.loadedCount += 1;
        this.events.onProgress?.(Math.min(this.loadedCount, this.totalCount), this.totalCount);
      }
      return;
    }

    if (spec.kind === "kitchen") {
      const kitchenRoom = findRoom(this.apartment, spec.roomId);
      group = buildKitchen(this.kitCtx, {
        level: spec.level,
        features: spec.features,
        doorMaterialId: spec.doorMaterialId,
        worktopMaterialId: spec.worktopMaterialId,
        splashbackMaterialId: spec.splashbackMaterialId,
        widthCm: p.wCm,
        depthCm: p.dCm,
        roomDepthCm: kitchenRoom ? Math.min(kitchenRoom.w, kitchenRoom.d) : undefined,
        columnsAt: kitchenRoom ? farFromDoor(kitchenRoom, p) : undefined,
      });
    } else if (spec.kind === "bathroom") {
      group = buildBathroom(this.kitCtx, {
        level: spec.level,
        features: spec.features,
        widthCm: p.wCm,
        depthCm: p.dCm,
        vanityMaterialId: spec.vanityMaterialId,
      });
    } else if (spec.kind === "tv") {
      group = buildTv(this.kitCtx, { widthCm: p.wCm, heightCm: p.hCm, depthCm: p.dCm, hung: spec.hung });
    } else if (spec.kind === "wall-plane") {
      group = buildWallPlane(this.kitCtx, { widthCm: p.wCm, heightCm: p.hCm, depthCm: p.dCm, mirror: spec.mirror, materialId: spec.materialId });
    } else if (spec.kind === "rug") {
      group = buildRug(this.kitCtx, {
        materialId: spec.materialId,
        widthCm: p.wCm,
        depthCm: p.dCm,
        pile: spec.features.includes("soft") ? "soft" : "flat",
      });
    } else if (spec.kind === "bed") {
      group = buildBed(this.kitCtx, {
        level: spec.level,
        features: spec.features,
        bodyMaterialId: spec.materialId,
        widthCm: p.wCm,
        depthCm: p.dCm,
      });
    } else {
      group = buildWardrobe(this.kitCtx, {
        level: spec.level,
        features: spec.features,
        doorMaterialId: spec.materialId,
        widthCm: p.wCm,
        depthCm: p.dCm,
        heightCm: p.hCm,
      });
    }

    placeGroup(group, p);
    group.userData = { slotId: spec.slotId, roomId: spec.roomId, title: spec.titleRu };
    this.scene.add(group);
    this.placed.set(spec.slotId, { spec, group, signature: signatureOf(spec), status: "loaded" });
    this.refreshSelection(spec.slotId);
    this.loadedCount += 1;
    this.events.onProgress?.(Math.min(this.loadedCount, this.totalCount), this.totalCount);
  }

  // ── управление ───────────────────────────────────────────────────────────

  setSize(width: number, height: number): void {
    // Потолок по числу пикселей кадра. На весь экран (тем более 4K и при dpr 2) сцена иначе
    // рисует до 8 мегапикселей: на слабой видеокарте это провал кадров, а на программном
    // рендере — падение вкладки (ловили на тестах 29.09). 2,3 Мп хватает для чёткой картинки.
    const dpr = Math.min(window.devicePixelRatio || 1, this.quality.pixelRatio);
    const wanted = width * height * dpr * dpr;
    const cap = 2_300_000;
    const ratio = wanted > cap ? dpr * Math.sqrt(cap / wanted) : dpr;
    // менять плотность ТОЛЬКО когда она правда другая: каждый вызов заново выделяет буферы
    // кадра, а размер приходит потоком от наблюдателя за канвасом — так можно исчерпать память
    // видеоконтекста (ловили на тестах 29.09: «context lost» вместо картинки)
    if (Math.abs(this.renderer.getPixelRatio() - ratio) > 0.01) this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
    if (this.viewMode === "top") this.fitTop(this.currentRoom);
  }

  /** Переключение вида: прогулка ↔ сверху. Потолки в виде сверху прячем, иначе видно только их; кайму вида за окнами — тоже. */
  setViewMode(mode: "walk" | "top"): void {
    if (this.viewMode === mode) return;
    this.viewMode = mode;
    this.walkBlend = null;
    this.photo = null;
    applyPhotoShift(this.camera, 0); // сдвиг объектива — только у фото-позы
    this.scene.traverse((o) => {
      if (o.name.startsWith("ceiling:") || o.name === "window-view:skirt") o.visible = mode !== "top";
    });
    if (mode === "top") {
      // по умолчанию показываем ВСЮ квартиру («кукольный дом»), а выбор комнаты приближает к ней
      this.camera.fov = 48;
      this.camera.updateProjectionMatrix();
      this.heading = this.bestTopHeading(null);
      this.fitTop(null);
    } else {
      this.camera.fov = this.quality.fov;
      this.camera.updateProjectionMatrix();
      if (this.currentRoom) this.goToRoom(this.currentRoom);
    }
  }

  /**
   * Прогулка из точки съёмки (demo-02, прогон d8 14.10: «3D» стартовал у пола и в стене — у квартиры из одной комнаты
   * `setViewMode` не знал комнату и оставлял камеру где была). Встаём туда, где стоит камера ракурса (её подбор уже
   * обходит помехи, `index.html:camFit`), и смотрим на середину мебели комнаты на высоте предметов (урок 420).
   */
  walkFrom(pose: PhotoPose): void {
    this.setViewMode("walk");
    this.walkBlend = null;
    if (Math.abs(this.camera.fov - this.quality.fov) > 0.01) { this.camera.fov = this.quality.fov; this.camera.updateProjectionMatrix(); }
    const spot = nearestStandable(this.area, pose.x, pose.y, 8, 12) ?? { x: pose.x, y: pose.y };
    this.pos.set(spot.x, spot.y);
    const room = roomAt(this.apartment, spot.x, spot.y);
    const own = this.framed(room?.id).map((p) => p.spec.placement);
    const c = own.length > 0
      ? { x: own.reduce((a, o) => a + o.x, 0) / own.length, y: own.reduce((a, o) => a + o.y, 0) / own.length }
      : room ? roomCentre(room) : { x: spot.x, y: spot.y + 100 };
    const dx = c.x - spot.x;
    const dy = c.y - spot.y;
    const dist = Math.hypot(dx, dy);
    // без мебели — по взгляду ракурса: (sin rot, −cos rot) на плане, у прогулки heading 0 = +y
    this.heading = dist > 15 ? ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360 : (540 - pose.rot) % 360;
    this.pitch = Math.max(-25, (Math.atan2(110 - EYE_CM, Math.max(dist, 60)) * 180) / Math.PI);
    this.moveTarget = null;
    if (room) this.roomChanged(room.id);
  }

  get mode(): "walk" | "top" | "photo" {
    return this.viewMode;
  }

  /** Неподвижная камера фото-кадра (см. `PhotoPose`). Выход — `setViewMode`. */
  setPhotoPose(pose: PhotoPose): void {
    this.photoRaw = { ...pose };
    this.photo = this.livePlaced(pose);
    this.photoLook = { yaw: 0, pitch: this.basePitch(this.photo) };
    this.poseAnim = null;
    if (this.viewMode === "top") {
      this.scene.traverse((o) => {
        if (o.name.startsWith("ceiling:") || o.name === "window-view:skirt") o.visible = true;
      });
    }
    this.viewMode = "photo";
    this.walkBlend = null;
  }

  setTilt(on: boolean): void {
    this.tilt = on;
  }

  /** «3D» глазами стоящего: глаз (см) и видимая полоса холста (доли высоты); null — живая поза как кадр нейросети. */
  setLiveEye(v: { eyeCm?: number; band?: Partial<LiveBand> } | null): void {
    this.liveEye = v ? { eyeCm: v.eyeCm ?? LIVE_EYE_CM, band: { top: v.band?.top ?? 0, bottom: v.band?.bottom ?? 1 } } : null;
    if (this.photoRaw && this.photo) {
      const p = this.livePlaced(this.photoRaw);
      this.photo = { ...this.photo, x: p.x, y: p.y };
    }
  }

  /** Поза для живой сцены: «3D» глазами стоящего — глаз внутри комнаты, не ближе `LIVE_WALL_CM` к стенам; иначе как есть. */
  private livePlaced(pose: PhotoPose): PhotoPose {
    return this.liveEye ? { ...pose, ...liveSpot(pose, this.apartment.rooms) } : { ...pose };
  }

  /** Наклон взгляда в текущей позе заново — по мебели, что уже в сцене (после загрузки расстановки: до неё мебели нет). */
  aimLive(): void {
    if (this.viewMode === "photo" && this.photo && !this.poseAnim) this.photoLook.pitch = this.basePitch(this.photo);
  }

  /** Наклон позы по умолчанию: «3D» глазами стоящего — по мебели (`livePitch`); иначе портрет — `tiltFor`; иначе прямо. */
  private basePitch(pose: PhotoPose): number {
    return this.liveEye ? this.livePitch(pose) : this.tilt ? this.tiltFor(pose) : 0;
  }

  /**
   * Предметы комнаты (все — без комнаты), по которым строится ракурс: взгляд, наклон, рамка. Настенные плоскости (картина, зеркало)
   * не входят — картина над кроватью не задирает и не уводит взгляд, ракурс тот же, что без неё (T-20261112-26/2).
   */
  private framed(roomId: string | undefined): Placed[] {
    return [...this.placed.values()].filter((p) => (!roomId || p.spec.roomId === roomId) && p.spec.kind !== "wall-plane");
  }

  /** Наклон, при котором мебель комнаты позы — в видимой полосе холста (`live-eye.ts`). */
  private livePitch(pose: PhotoPose): number {
    const room = roomAt(this.apartment, pose.x, pose.y);
    const pts: LivePoint[] = [];
    for (const p of this.framed(room?.id)) {
      const bb = this.anchorOf(p.spec.slotId)?.bb;
      if (!bb || bb.isEmpty()) continue;
      pts.push(...boxPoints({ x: bb.min.x / CM, y: bb.min.z / CM, h: bb.min.y / CM }, { x: bb.max.x / CM, y: bb.max.z / CM, h: bb.max.y / CM }));
    }
    return livePitchDeg(pose, pts, this.camera.aspect, this.liveEye?.band ?? { top: 0, bottom: 1 }, this.liveEye?.eyeCm, pose.pitchMin);
  }

  /** Глаз и цель позы (см) для ЖИВОЙ сцены: «3D» глазами стоящего — глаз `liveEye`, взгляд горизонтален (наклон — `photoLook`). */
  private liveRay(p: PhotoPose): { eye: [number, number, number]; target: [number, number, number] } {
    const r = photoRay(p);
    if (this.liveEye) { r.eye[1] = this.liveEye.eyeCm; r.target[1] = this.liveEye.eyeCm; }
    return r;
  }

  /** Сдвиг объектива живой позы: «3D» глазами стоящего — без сдвига (кадр опускает наклон), иначе — как у кадра. */
  private liveShift(p: PhotoPose): number {
    return this.liveEye ? 0 : photoShift(p, this.camera.aspect);
  }

  /** Наклон взгляда из позы к середине мебели комнаты на высоте сидений: 70 % от прямого угла, не круче 18°. */
  private tiltFor(pose: PhotoPose): number {
    if (typeof pose.pshift === "number") return 0;   // вертикальный кадр уже выставлен сдвигом объектива (demo-12)
    const room = roomAt(this.apartment, pose.x, pose.y);
    const own = this.framed(room?.id).map((p) => p.spec.placement);
    if (!own.length) return 0;
    const cx = own.reduce((a, o) => a + o.x, 0) / own.length, cy = own.reduce((a, o) => a + o.y, 0) / own.length;
    const eye = photoRay(pose).eye[1];
    const deg = (Math.atan2(eye - 60, Math.max(100, Math.hypot(cx - pose.x, cy - pose.y))) * 180) / Math.PI;
    return -Math.min(18, Math.max(0, deg * 0.7));
  }

  /** Действующая поза кадра: поза ракурса + поворот взгляда + незаконченный переход. */
  private livePose(now = performance.now()): { x: number; y: number; rot: number; pitch: number } | null {
    if (!this.photo) return null;
    const a = this.poseAnim;
    let k = 1;
    if (a) {
      const t = Math.min(1, (now - a.t0) / Math.max(1, a.ms));
      k = 1 - Math.pow(1 - t, 3);
      if (t >= 1) this.poseAnim = null;
    }
    const left = a ? 1 - k : 0;
    return {
      x: this.photo.x + (a ? a.dx * left : 0),
      y: this.photo.y + (a ? a.dy * left : 0),
      rot: this.photo.rot + this.photoLook.yaw + (a ? a.yaw * left : 0),
      pitch: this.photoLook.pitch + (a ? a.pitch * left : 0),
    };
  }

  /**
   * Плавно перейти к позе ракурса (стрелки «‹ ›» в 3D, demo-09): из фото-позы — по разнице поз, из прогулки — от точки,
   * где стоит человек. Поворот взгляда сбрасывается: в конце перехода кадр = кадр будущего реалистичного фото.
   */
  goToPose(pose: PhotoPose, ms = 650, pitch?: number): void {
    const now = performance.now();
    const cur = this.viewMode === "photo" ? this.livePose(now)
      : { x: this.pos.x, y: this.pos.y, rot: (540 - this.heading) % 360, pitch: this.pitch };
    this.faceAt = null;
    this.setPhotoPose(pose);
    if (pitch !== undefined) this.photoLook.pitch = this.clampLook(pitch);   // наклон к предмету (`frameItem`)
    if (!cur) return;
    const yaw = ((cur.rot - pose.rot + 540) % 360) - 180;
    const to = this.photo ?? pose;   // глаз «3D» мог отойти от стены (`livePlaced`) — переход к нему, не к точке кадра
    this.poseAnim = { dx: cur.x - to.x, dy: cur.y - to.y, yaw, pitch: cur.pitch - this.photoLook.pitch, t0: now, ms };
  }

  /** Из фото-позы — в прогулку с той же точки и тем же взглядом (тап по полу в 3D: «иди сюда»). */
  photoToWalk(): void {
    const p = this.viewMode === "photo" ? this.livePose() : null;
    if (!p) return;
    // ПЛАВНЫЙ ВХОД (T-20261111-14): у ракурса угол обзора уже (72° по горизонтали), глаз ниже (152 против 162 см), а точка может
    // стоять ближе к мебели, чем пускает прогулка. Раньше всё это менялось одним кадром — первый шаг дёргал экран. Теперь
    // камера доезжает до прогулочных за 0,5 с (`tick`)
    const eye0 = this.photo ? this.liveRay(this.photo).eye[1] : EYE_CM;
    const fov0 = this.camera.fov;
    this.viewMode = "walk";
    this.photo = null;
    this.poseAnim = null;
    applyPhotoShift(this.camera, 0);
    this.camera.updateProjectionMatrix();
    const spot = nearestStandable(this.area, p.x, p.y, 8, 12) ?? { x: p.x, y: p.y };
    this.pos.set(spot.x, spot.y);
    this.walkBlend = { t0: performance.now(), ms: 500, fov: fov0, eye: eye0, dx: p.x - spot.x, dy: p.y - spot.y };
    this.heading = (540 - p.rot) % 360;
    this.pitch = this.clampLook(p.pitch);
    this.moveTarget = null;
  }

  /** Где камера и куда смотрит (heading: 0 = +y), в любой из поз — живые проверки поворота и шага. */
  viewPose(): { x: number; y: number; yaw: number; pitch: number } {
    const p = this.viewMode === "photo" ? this.livePose() : null;
    const r1 = (v: number): number => Math.round(v * 10) / 10;   // наклон — живая проверка «ракурс тот же, что без картины» (T-26/2)
    if (p) return { x: Math.round(p.x), y: Math.round(p.y), yaw: Math.round((((540 - p.rot) % 360) + 360) % 360), pitch: r1(p.pitch) };
    return { x: Math.round(this.pos.x), y: Math.round(this.pos.y), yaw: Math.round(this.heading), pitch: r1(this.pitch) };
  }

  /** Рисует ли браузер силами процессора — обёртка демо в этом случае берёт серверный эскиз. */
  get softwareRenderer(): boolean {
    return isSoftwareRenderer(this.renderer);
  }

  /**
   * Новая расстановка той же квартиры (демо: замена товара, перестановка). Рендерер, загруженные модели и стены
   * остаются; дальше вызывающий зовёт `syncObjects` — сдвинутое двигается, заменённое перегружается.
   */
  setApartment(apartment: Apartment, catalogue: Catalogue): void {
    this.apartment = apartment;
    this.catalogue = catalogue;
    const byId = (id: string): Material | undefined => catalogue.materials.find((m) => m.id === id);
    this.kitCtx = { ...this.kitCtx, byId, fallback: byId("paint-white") ?? catalogue.materials[0] ?? NEUTRAL_WALL };
    this.area = walkArea(apartment);
  }

  /** Поставить камеру вида сверху по текущим точке интереса, повороту и расстоянию. */
  private placeTopCamera(): void {
    const pitchRad = (this.topPitch * Math.PI) / 180;
    const rad = (this.heading * Math.PI) / 180;
    const d = this.topDistanceCm * CM;
    const tx = this.topTarget.x * CM;
    const tz = this.topTarget.y * CM;
    this.camera.position.set(
      tx - Math.sin(rad) * Math.cos(pitchRad) * d,
      Math.max(1.2, -Math.sin(pitchRad) * d),
      tz - Math.cos(rad) * Math.cos(pitchRad) * d,
    );
    this.camera.lookAt(tx, 0.4, tz);
    this.camera.updateMatrixWorld();
  }

  /** Углы коробки (пол + стены) комнаты или всей квартиры — по ним и кадрируем. */
  private topCorners(roomId: string | null): { corners: THREE.Vector3[]; cx: number; cy: number } {
    const room = roomId ? findRoom(this.apartment, roomId) : null;
    const x0 = room ? room.x : Math.min(...this.apartment.rooms.map((r) => r.x));
    const x1 = room ? room.x + room.w : Math.max(...this.apartment.rooms.map((r) => r.x + r.w));
    const y0 = room ? room.y : Math.min(...this.apartment.rooms.map((r) => r.y));
    const y1 = room ? room.y + room.d : Math.max(...this.apartment.rooms.map((r) => r.y + r.d));
    const top = Math.max(...this.apartment.rooms.map((r) => r.heightCm ?? 250));
    const corners: THREE.Vector3[] = [];
    for (const x of [x0, x1]) for (const y of [y0, y1]) for (const h of [0, top]) {
      corners.push(new THREE.Vector3(x * CM, h * CM, y * CM));
    }
    return { corners, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
  }

  /**
   * Самое близкое расстояние, при котором все углы ещё в кадре, — ДЕЛЕНИЕМ ОТРЕЗКА ПОПОЛАМ.
   *
   * Подгонять «умножением на промах» нельзя: камера наклонная, и при сближении крайний угол
   * убегает быстрее, чем растёт множитель — подгонка расходилась и упиралась в минимум
   * (поймано кадром 29.09). Деление пополам монотонно: дальше — всё влезает, ближе — нет.
   */
  private fitDistance(corners: THREE.Vector3[]): number {
    const inside = (d: number): boolean => {
      this.topDistanceCm = d;
      this.placeTopCamera();
      let worst = 0;
      for (const c of corners) {
        const ndc = c.clone().project(this.camera);
        worst = Math.max(worst, Math.abs(ndc.x), Math.abs(ndc.y));
      }
      return Number.isFinite(worst) && worst <= 0.97;
    };
    let lo = TOP_MIN_CM;
    let hi = TOP_MAX_CM;
    if (!inside(hi)) return hi;
    for (let i = 0; i < 18; i += 1) {
      const mid = (lo + hi) / 2;
      if (inside(mid)) hi = mid;
      else lo = mid;
    }
    return hi;
  }

  /** Вписать в кадр комнату (или всю квартиру, если roomId не задан). */
  private fitTop(roomId: string | null): void {
    const { corners, cx, cy } = this.topCorners(roomId);
    this.topTarget.set(cx, cy);
    this.topDistanceCm = this.fitDistance(corners);
  }

  /**
   * Развернуть «кукольный дом» так, чтобы квартира заняла кадр целиком: пробуем четыре стороны
   * и берём ту, с которой камера подходит ближе всего. Экран широкий, квартира вытянутая —
   * при неудачном развороте она занимала треть кадра, при удачном в полтора раза крупнее.
   */
  private bestTopHeading(roomId: string | null): number {
    const { corners, cx, cy } = this.topCorners(roomId);
    this.topTarget.set(cx, cy);
    const keepHeading = this.heading;
    const keepDistance = this.topDistanceCm;
    let best = keepHeading;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const h of [0, 90, 180, 270]) {
      this.heading = h;
      const d = this.fitDistance(corners);
      if (d < bestDistance - 1) {
        bestDistance = d;
        best = h;
      }
    }
    this.heading = keepHeading;
    this.topDistanceCm = keepDistance;
    return best;
  }

  /**
   * Вид сверху не выпускаем за пределы квартиры больше чем на метр: иначе человек «улетает»
   * в пустое поле и не понимает, что показывать (вопрос владельца 29.09 — решено так).
   */
  private clampTopTarget(): void {
    const minX = Math.min(...this.apartment.rooms.map((r) => r.x)) - 100;
    const maxX = Math.max(...this.apartment.rooms.map((r) => r.x + r.w)) + 100;
    const minY = Math.min(...this.apartment.rooms.map((r) => r.y)) - 100;
    const maxY = Math.max(...this.apartment.rooms.map((r) => r.y + r.d)) + 100;
    this.topTarget.set(
      Math.min(Math.max(this.topTarget.x, minX), maxX),
      Math.min(Math.max(this.topTarget.y, minY), maxY),
    );
  }

  /** Приблизить/отдалить вид сверху (колесо мыши, щипок). */
  zoom(deltaCm: number): void {
    if (this.viewMode !== "top") return;
    this.topDistanceCm = Math.min(TOP_MAX_CM, Math.max(TOP_MIN_CM, this.topDistanceCm + deltaCm));
  }

  keyDown(code: string): void {
    this.keys.add(code);
  }

  keyUp(code: string): void {
    this.keys.delete(code);
  }

  look(dxPx: number, dyPx: number): void {
    this.faceAt = null;
    if (this.viewMode === "top") {
      // сверху мышь крутит сцену вокруг точки и меняет наклон, а не «голову»
      this.heading = (this.heading + dxPx * 0.25 + 360) % 360;
      this.topPitch = Math.max(-85, Math.min(-22, this.topPitch - dyPx * 0.2));
      return;
    }
    if (this.viewMode === "photo" && this.photo) {
      // взгляд из точки съёмки: та же чувствительность, что у прогулки (у позы угол растёт в другую сторону)
      this.photoLook.yaw -= dxPx * 0.22;
      this.photoLook.pitch = this.clampLook(this.photoLook.pitch - dyPx * 0.18);
      return;
    }
    this.heading = (this.heading + dxPx * 0.22 + 360) % 360;
    this.pitch = this.clampLook(this.pitch - dyPx * 0.18);
  }

  /** Наклон взгляда в пределах: середина видимой полосы холста — ±60° вверх и вниз (`live-eye.ts:lookPitchRange`), фото-поза и прогулка. */
  private clampLook(pitch: number): number {
    const vfov = this.viewMode === "photo" && this.photo ? verticalFov(this.photo.fov ?? 72, this.camera.aspect) : this.camera.fov;
    const [lo, hi] = lookPitchRange(this.liveEye?.band, vfov);
    return Math.max(lo, Math.min(hi, pitch));
  }

  /**
   * Тап по полу — «иди сюда» (мобильный сценарий из ТЗ). Ответ — где встанем: цель недостижима (за мебелью, отрезана) — путь
   * ведёт к ближайшей достижимой точке (`planRoute`), там и кольцо «сюда пойдём» (T-20261112-36); рядом с собой — null, стоим.
   */
  goTo(xCm: number, yCm: number): { x: number; y: number } | null {
    const target = nearestStandable(this.area, xCm, yCm);
    if (!target) return null;
    this.faceAt = null;
    // путь в обход мебели (T-20261111-14): прежде шаг к цели огибал предмет сам и метался «вбок — назад» у косяков и мебели
    const from = { x: this.pos.x, y: this.pos.y };
    const pts = planRoute(this.area, from, target) ?? [target];
    this.moveTarget = newRoute(pts);
    const end = pts.at(-1) ?? target;
    if (Math.hypot(end.x - from.x, end.y - from.y) < 20) {
      this.hideWalkTarget(true);
      return null;
    }
    this.markWalk(end.x, end.y, "route");
    return end;
  }

  /** Кольцо на полу в точке плана (см): `hover` — под мышью, `route` — цель пути (гаснет, когда путь кончился, — `tick`). */
  private markWalk(xCm: number, yCm: number, mode: "hover" | "route"): void {
    if (!this.walkMarker) {
      this.walkMarker = createWalkMarker();
      this.scene.add(this.walkMarker);
    }
    placeWalkMarker(this.walkMarker, xCm, yCm);
    this.markerMode = mode;
  }

  /** Убрать кольцо: по умолчанию только «под мышью» (мышь ушла, начали поворот); `all` — и цель пути. */
  hideWalkTarget(all = false): void {
    if (!this.walkMarker || (!all && this.markerMode !== "hover")) return;
    this.walkMarker.visible = false;
    this.markerMode = null;
  }

  /**
   * ЧТО ПОД ТОЧКОЙ ЭКРАНА В ПРОГУЛКЕ (T-20261112-36): по лучу ближайшее — окно, предмет (`selectable`: страница выбирает не всё,
   * ковёр и картину — нет), пол комнаты или её пристройки; стена, дверь или невыбираемый предмет ближе — ничего (`walk-aim.ts`).
   * У пола — точка, где можно встать (до 50 см от курсора, `nearestStandable`), иначе ничего.
   */
  walkAim(clientX: number, clientY: number, rect: DOMRect, selectable: (slotId: string) => boolean = (id) => !isExtra(id)):
    { kind: "window" } | { kind: "item"; slotId: string } | { kind: "floor"; x: number; y: number } | { kind: "none" } {
    if (this.viewMode === "top" || !rect.width || !rect.height) return { kind: "none" };
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const shown = (o: THREE.Object3D | null): boolean => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
    const hits: WalkHits = {};
    let slotId = "";
    for (const h of this.raycaster.intersectObjects([...this.placed.values()].map((p) => p.group), true)) {
      if (!shown(h.object)) continue;
      let o: THREE.Object3D | null = h.object;
      while (o && !o.userData?.slotId) o = o.parent;
      const id = o?.userData?.slotId ? String(o.userData.slotId) : "";
      const spec = this.placed.get(id)?.spec;
      if (id && selectable(id) && !isExtra(id)) { hits.item = h.distance; slotId = id; break; }
      if (spec && !isFlatOnSurface(spec) && hits.block === undefined) hits.block = h.distance;   // ТВ над тумбой закрывает пол за ним
    }
    let floorAt: THREE.Vector3 | null = null;
    const shell = this.raycaster.intersectObjects([...this.roomGroups.values()], true).find((h) => shown(h.object));
    if (shell && this.floors.includes(shell.object as THREE.Mesh)) {
      hits.floor = shell.distance;
      floorAt = shell.point;
    } else if (shell && windowAtPoint(this.apartment.rooms, shell.point.x / CM, shell.point.z / CM, shell.point.y / CM)) {
      hits.window = shell.distance;
    } else if (shell) hits.block = Math.min(hits.block ?? Infinity, shell.distance);
    const kind = chooseAim(hits);
    if (kind === "item") return { kind, slotId };
    if (kind === "window") return { kind };
    if (kind !== "floor" || !floorAt) return { kind: "none" };
    const spot = nearestStandable(this.area, floorAt.x / CM, floorAt.z / CM, 10, 5);
    return spot ? { kind, x: spot.x, y: spot.y } : { kind: "none" };
  }

  /** Мышь над сценой (T-20261112-36): над полом — кольцо там, куда пойдём; над предметом, окном, стеной — без кольца. Пока идём к
   *  цели — её кольцо остаётся. Ответ — что под курсором. */
  previewWalk(clientX: number, clientY: number, rect: DOMRect, selectable?: (slotId: string) => boolean): "window" | "item" | "floor" | "none" {
    if (this.moveTarget && this.markerMode === "route") return "none";
    const aim = this.walkAim(clientX, clientY, rect, selectable);
    if (aim.kind === "floor") this.markWalk(aim.x, aim.y, "hover");
    else this.hideWalkTarget();
    return aim.kind;
  }

  /**
   * ПОДОЙТИ К ОКНУ (T-20261112-30, владелец TG 1731): луч из точки экрана упёрся в оболочку комнаты в вырезе окна (стекло, рама,
   * подоконник, откос) — идём к окну тем же путём в обход мебели, что и по тапу в пол, и, дойдя, поворачиваемся к нему: курс —
   * наружу по нормали, наклон — середина видимой полосы на середину окна (`window-walk.ts`). Не окно или негде встать — false.
   */
  walkToWindow(clientX: number, clientY: number, rect: DOMRect): boolean {
    if (this.viewMode === "top") return false;
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const shown = (o: THREE.Object3D | null): boolean => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
    const hit = this.raycaster.intersectObjects([...this.roomGroups.values()], true).find((h) => shown(h.object));
    if (!hit) return false;
    const w = windowAtPoint(this.apartment.rooms, hit.point.x / CM, hit.point.z / CM, hit.point.y / CM);
    // расстояние — по углу обзора прогулки по горизонтали: окно целиком и полоса стены по бокам (T-30/2: на телефоне в 70 см — одно небо)
    const hfov = (2 * Math.atan(Math.tan((this.quality.fov * Math.PI) / 360) * this.camera.aspect) * 180) / Math.PI;
    const spot = w ? windowSpot(this.area, w, windowGap(w, hfov), hfov) : null;
    if (!w || !spot) return false;
    if (this.viewMode === "photo") this.photoToWalk();   // 3D из точки съёмки — уже прогулка, как шаг по полу
    const from = { x: this.pos.x, y: this.pos.y };
    this.moveTarget = newRoute(planRoute(this.area, from, spot) ?? [spot]);
    this.markWalk(spot.x, spot.y, "route");   // кольцо «сюда пойдём» — и у окна (T-20261112-36)
    // середина видимой полосы (у телефона она выше середины холста — `lookPitchRange` с пределом 0 даёт сдвиг) — на середину окна;
    // наклон камеры в конце — 0…−5° (ведущий, T-30/2): почти прямо, рама и подоконник в кадре, не пол и не потолок
    const aim = (Math.atan2((w.sill + w.top) / 2 - EYE_CM, spot.gapCm) * 180) / Math.PI;
    const [off] = lookPitchRange(this.liveEye?.band, this.quality.fov, 0);
    this.faceAt = { heading: spot.heading, pitch: this.clampLook(Math.max(-5, Math.min(0, aim + off))) };
    return true;
  }

  /**
   * Телепорт в комнату. Встаём НЕ в центр, а в дальний угол и смотрим в центр — как снимают
   * комнату риелторы. Из центра человек упирался взглядом в ближнюю стену или в окно
   * (проверено кадром 28.09: при спавне в гостиной в кадре было одно небо).
   */
  goToRoom(roomId: string): void {
    const room = findRoom(this.apartment, roomId);
    if (!room) return;
    if (this.viewMode === "top") {
      this.fitTop(roomId);
      this.roomChanged(roomId);
      return;
    }
    const c = roomCentre(room);
    // КАНДИДАТЫ — СЕТКА 5×5 ПО КОМНАТЕ: углы (дальше от центра) по-прежнему в приоритете счёта, а промежуточные точки нужны,
    // когда углы заняты мебелью или видом на ТВ сбоку (прогон d8 15.10, современный и минимализм)
    const FR = [0.18, 0.35, 0.5, 0.65, 0.82];
    const candidates = FR.flatMap((fx) => FR.map((fy) => ({ x: room.x + room.w * fx, y: room.y + room.d * fy })));
    // ТЕСНАЯ КОМНАТА — СМОТРИМ ОТ ДВЕРИ. В кухне 3,6×1,8 м из любого угла кадр упирается в
    // шкаф (кадр 29.09): в жизни такие комнаты и снимают из проёма. Добавляем к кандидатам
    // точки в дверных проёмах комнаты — стоять там разрешено, и оттуда видно всю комнату.
    const doorSpots: { x: number; y: number }[] = [];
    if ((room.w * room.d) / 10_000 < 13) {
      for (const o of room.openings) {
        if (o.kind === "window") continue;
        const mid = o.offsetCm + o.widthCm / 2;
        if (o.wall === "south") doorSpots.push({ x: room.x + mid, y: room.y - 30 });
        else if (o.wall === "north") doorSpots.push({ x: room.x + mid, y: room.y + room.d + 30 });
        else if (o.wall === "west") doorSpots.push({ x: room.x - 30, y: room.y + mid });
        else doorSpots.push({ x: room.x + room.w + 30, y: room.y + mid });
      }
      candidates.push(...doorSpots);
    }
    const isDoorSpot = (p: { x: number; y: number }): boolean =>
      doorSpots.some((d) => Math.hypot(d.x - p.x, d.y - p.y) < 60);
    // Мебель комнаты: вставать В НЕЁ нельзя — кадр упрётся в спинку дивана или в кровать
    // (поймано кадрами 28.09: в спальне полкадра занимала кровать в упор).
    // (16.10: выбор по плану сцены вместо загруженного уронил e2e «правая панель состава» — откатан до разбора; старт сканди
    // может зависеть от порядка загрузки моделей — см. план demo-05 п.5)
    const inRoom = [...this.placed.values()].filter((p) => p.spec.roomId === roomId);
    // ковёр и плоское — пол, а не препятствие (как у прогулки): с ковром из витрины в /flat (demo-05 п.9) середина комнаты и
    // середины стен считались «занятыми», и старт оставался у торца ТВ-тумбы
    const obstacles = inRoom.filter((p) => !isFlatOnSurface(p.spec) && p.spec.placement.hCm > 10).map((p) => p.spec.placement);
    // Расстояние до ПРЯМОУГОЛЬНИКА предмета, а не до круга вокруг него: кухонная линия
    // 340×60 «кругом» занимала всю комнату, и любая точка считалась занятой (кадр 29.09).
    // ВЫСОКОЕ — ДАЛЬШЕ (demo-05 п.5: /flat стартовал вплотную к торшеру, абажур на уровне глаз закрывал треть кадра): от
    // предметов выше 120 см держим ещё 35 см — запас считается как будто их след шире
    const TALL_CM = 120;
    const TALL_EXTRA = 35;
    const clearance = (x: number, y: number): number => {
      let min = 1e9;
      for (const o of obstacles) {
        // высота — по ВЕРХУ предмета: телевизор 68 см на тумбе 62 см — это 130 см у глаз, а не «низкий» (прогон d8 15.10)
        const extra = (o.elevCm ?? 0) + o.hCm >= TALL_CM ? TALL_EXTRA : 0;
        const a = (-o.rot * Math.PI) / 180;
        const dx = x - o.x;
        const dy = y - o.y;
        const lx = dx * Math.cos(a) - dy * Math.sin(a);
        const ly = dx * Math.sin(a) + dy * Math.cos(a);
        const ox = Math.max(Math.abs(lx) - o.wCm / 2, 0);
        const oy = Math.max(Math.abs(ly) - o.dCm / 2, 0);
        min = Math.min(min, Math.hypot(ox, oy) - extra);
      }
      return min;
    };

    // ТЕЛЕВИЗОР НЕ БОКОМ И НЕ СПИНОЙ У КРАЯ КАДРА (demo-05 п.2/п.5, прогон d8 15.10: у современного старт был у торца
    // ТВ-тумбы — чёрный торец экрана занимал левую треть кадра). Точка ближе 2,2 м к экрану и вне его «конуса» ±53° — штраф
    const tvs = inRoom.filter((p) => p.spec.kind === "tv").map((p) => p.spec.placement);
    const tvSide = (x: number, y: number): boolean => tvs.some((t) => {
      const r = (t.rot * Math.PI) / 180;
      const dx = x - t.x;
      const dy = y - t.y;
      const d = Math.hypot(dx, dy);
      // ближе 1,5 м к экрану — тоже плохо (прогон d8 16.10: у современного экран в упор занимал четверть кадра), как в
      // правилах камер окна
      return d < 150 || (d < 220 && (dx * Math.sin(r) + dy * Math.cos(r)) / Math.max(d, 1) < 0.6);
    });
    // «БЛИЖЕ 80 СМ НИЧЕГО» (правило камер окна, прогон d8 16.10: торец тумбы вплотную у края кадра) — мягко: каждый
    // недостающий до 80 см сантиметр стоит 3 очка, жёсткий отказ остаётся 45/35 см ниже
    const near = (free: number): number => Math.max(0, 80 - free) * 3;

    let best: { x: number; y: number } | null = null;
    let bestScore = -1e9;
    let lookAt: { x: number; y: number } = c;
    // ЖЁСТКО (решение d8 16.10): «ближе 80 см ничего» и «до экрана ТВ ≥ 1,5 м»; «ТВ спереди» — мягко (штраф). У минимализма
    // единственная точка «ТВ спереди» стояла в 47 см от столика и с экраном в упор на треть кадра — хуже торца тумбы
    const tvDist = (x: number, y: number): number => Math.min(1e9, ...tvs.map((t) => {
      const a = (-t.rot * Math.PI) / 180;
      const dx = x - t.x;
      const dy = y - t.y;
      const lx = dx * Math.cos(a) - dy * Math.sin(a);
      const ly = dx * Math.sin(a) + dy * Math.cos(a);
      return Math.hypot(Math.max(Math.abs(lx) - t.wCm / 2, 0), Math.max(Math.abs(ly) - t.dCm / 2, 0));
    }));
    for (const cand of candidates) {
      const spot = nearestStandable(this.area, cand.x, cand.y, 8, 6);
      if (!spot) continue;
      const free = clearance(spot.x, spot.y);
      const door = isDoorSpot(cand);
      if (free < (door ? 20 : 80) || tvDist(spot.x, spot.y) < 150) continue;
      const score = Math.hypot(spot.x - c.x, spot.y - c.y) + Math.min(free, 150) + (door ? 220 : 0) - (tvSide(spot.x, spot.y) ? 400 : 0);
      if (score > bestScore) {
        bestScore = score;
        best = spot;
      }
    }
    // НИ ОДНА ТОЧКА НЕ ПРОШЛА — СТАРТ ОТ ДВЕРИ С ВИДОМ НА ДИВАН (решение d8 16.10; ТВ пусть будет не в кадре, как ступень 1 у
    // окна): в 60 см от входа внутрь комнаты, взгляд — на диван (нет дивана — в центр)
    if (!best) {
      const d0 = room.openings.find((o) => o.kind === "door");
      if (d0) {
        const mid = d0.offsetCm + d0.widthCm / 2;
        const inward = d0.wall === "south" ? { x: room.x + mid, y: room.y + 60 } : d0.wall === "north" ? { x: room.x + mid, y: room.y + room.d - 60 }
          : d0.wall === "west" ? { x: room.x + 60, y: room.y + mid } : { x: room.x + room.w - 60, y: room.y + mid };
        const spot = nearestStandable(this.area, inward.x, inward.y, 8, 6);
        const sofa = inRoom.find((p) => p.spec.slotId.startsWith("диван"))?.spec.placement;
        const dining = inRoom.find((p) => p.spec.slotId.startsWith("стол обеденный"))?.spec.placement;
        if (spot && clearance(spot.x, spot.y) >= 20) {
          best = spot;
          // взгляд — на середину между диваном и обеденной группой (решение d8 16.10): в кадр входят ≥ 3 предмета ядра
          lookAt = sofa && dining ? { x: (sofa.x + dining.x) / 2, y: (sofa.y + dining.y) / 2 } : sofa ? { x: sofa.x, y: sofa.y } : c;
        }
      }
    }
    // и только если двери нет — прежние мягкие проходы (45/35 см, вид на ТВ сбоку — штраф)
    for (const minFree of best ? [] : [45, 35]) {
      for (const cand of candidates) {
        const spot = nearestStandable(this.area, cand.x, cand.y, 8, 6);
        if (!spot) continue;
        const free = clearance(spot.x, spot.y);
        const door = isDoorSpot(cand);
        if (free < (door ? 20 : minFree)) continue;
        const score = Math.hypot(spot.x - c.x, spot.y - c.y) + Math.min(free, 150) + (door ? 220 : 0) - (tvSide(spot.x, spot.y) ? 400 : 0)
          - (door ? 0 : near(free));
        if (score > bestScore) {
          bestScore = score;
          best = spot;
        }
      }
      if (best && !tvSide(best.x, best.y)) break;
    }
    if (!best) {
      // всё занято мебелью — встаём в самое свободное место из кандидатов
      for (const cand of candidates) {
        const spot = nearestStandable(this.area, cand.x, cand.y, 8, 6);
        if (!spot) continue;
        const free = clearance(spot.x, spot.y);
        if (free > bestScore) {
          bestScore = free;
          best = spot;
        }
      }
    }
    if (!best) return;
    this.pos.set(best.x, best.y);
    const dx = lookAt.x - best.x;
    const dy = lookAt.y - best.y;
    const dist = Math.hypot(dx, dy);
    if (dist > 15) this.heading = ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
    // целимся в точку на высоте мебели в центре комнаты: иначе половину кадра занимает потолок
    const aimY = 110;
    this.pitch = Math.max(-25, (Math.atan2(aimY - EYE_CM, Math.max(dist, 60)) * 180) / Math.PI);
    // тесная комната — шире угол: в санузле 2,8×2,2 м обычные 62° показывают один угол стены
    const areaM2 = (room.w * room.d) / 10_000;
    this.camera.fov = areaM2 < 9 ? 82 : areaM2 < 14 ? 72 : this.quality.fov;
    this.camera.updateProjectionMatrix();
    this.moveTarget = null;
    // ВАЖНО: комната остаётся ТОЙ, которую выбрал человек, даже если смотрим из дверного проёма.
    // Проём физически принадлежит соседней комнате, и авто-определение тут же возвращало выбор
    // назад — кнопка комнаты не работала вовсе (поймано 29.09). Через `roomChanged`, чтобы
    // заодно догрузилась обстановка выбранной комнаты.
    this.roomChanged(roomId);
  }

  /** Луч из точки экрана: возвращает slotId предмета или id комнаты по полу. */
  pick(clientX: number, clientY: number, rect: DOMRect): { slotId?: string; roomId?: string; point?: { x: number; y: number } } {
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.camera);
    const objects = [...this.placed.values()].map((p) => p.group);
    const hits = this.raycaster.intersectObjects(objects, true);
    // производное (ТВ над тумбой) не выбирается: своего слота у него нет — клик проходит к тому, что за ним
    for (const hit of hits) {
      let o: THREE.Object3D | null = hit.object;
      while (o && !o.userData?.slotId) o = o.parent;
      if (o?.userData?.slotId && !isExtra(String(o.userData.slotId))) return { slotId: String(o.userData.slotId) };
    }
    const floorHit = this.raycaster.intersectObjects(this.floors, false)[0];
    if (floorHit) {
      return {
        roomId: String(floorHit.object.userData.roomId ?? ""),
        point: { x: floorHit.point.x / CM, y: floorHit.point.z / CM },
      };
    }
    return {};
  }

  // ── ПЕРЕМЕЩЕНИЕ И ПОВОРОТ ПРЕДМЕТА ──────────────────────────────────────────
  // Во время перетаскивания React-состояние НЕ трогаем: подпись объекта включает координаты,
  // и каждое движение пальца пересоздавало бы модель (загрузка GLB заново). Двигаем уже
  // загруженную группу, а в подбор пишем один раз — на отпускании.
  private moving: {
    slotId: string;
    from: { x: number; y: number; rot: number };
    now: { x: number; y: number; rot: number };
    /** Исходное положение группы в сцене — двигаем и вращаем ОТ него, без пересборки объекта. */
    base: { posX: number; posZ: number; rotY: number };
  } | null = null;
  private ghost: THREE.Mesh | null = null;

  /** Начать перемещение предмета. Возвращает исходное место — на случай отмены. */
  beginMove(slotId: string): { x: number; y: number; rot: number } | null {
    const p = this.placed.get(slotId);
    if (!p) return null;
    const pl = p.spec.placement;
    const from = { x: pl.x, y: pl.y, rot: pl.rot };
    const base = { posX: p.group.position.x, posZ: p.group.position.z, rotY: p.group.rotation.y };
    this.moving = { slotId, from, now: { ...from }, base };
    this.ensureGhost(p.group, pl.wCm, pl.dCm);
    this.fadeModel(p.group);
    this.applyMove(true);
    // тень предмета «в руке» снимаем: на старом месте она висела бы пятном, под ним самим — след переноса
    this.bakeContact();
    return from;
  }

  /** Вернуть модели переносимого предмета её материалы (`fadeModel`). */
  private moveFade: (() => void)[] = [];

  /**
   * Предмет «в руке» — полупрозрачный (T-20261111-05/8, владелец TG 1588–1591: как в Sims 2): след на полу под ним виден целиком.
   * Материалы КОПИРУЕМ на время переноса: одна модель в сцене бывает дважды (два одинаковых стула) с общими материалами — второй
   * не должен бледнеть. Глубину модель не пишет: след (`ensureGhost`, рисуется ПОСЛЕ неё) не прячется за сиденьем.
   */
  private fadeModel(group: THREE.Object3D): void {
    this.unfadeModel();
    this.moveFade.push(fadeForMove(group, MOVE_MODEL_ALPHA, MOVE_GHOST_ORDER - 1));
  }

  private unfadeModel(): void {
    this.moveFade.forEach((f) => f());
    this.moveFade = [];
  }

  /**
   * Подсветка места под предметом: зелёная — можно ставить, красная — нельзя. Форма — СЛЕД САМОЙ МОДЕЛИ на полу
   * (`footprint.floorFootprint`, T-20261111-05/5): прямоугольник габарита у Г-дивана наполовину лежал на пустом полу.
   * Нет треугольников — прямоугольник габарита, как раньше. Геометрия — в осях предмета; место и поворот берёт у группы.
   */
  private ensureGhost(group: THREE.Object3D, wCm: number, dCm: number): void {
    if (this.ghost) {
      this.scene.remove(this.ghost);
      this.ghost.geometry.dispose();
    }
    const geo = floorFootprint(group) ?? new THREE.PlaneGeometry(wCm * CM, dCm * CM).rotateX(-Math.PI / 2);
    // СЛЕД — НА ПОЛУ (T-20261111-05/8, владелец TG 1588: «зелёное лежит на высоте и проступает сквозь сиденья»): прежде он рисовался
    // поверх всего (`depthTest: false`) и читался пятном на сиденье. Теперь он проверяет глубину, как пол: стены и соседняя мебель его
    // закрывают, а свой предмет — нет (тот полупрозрачный и глубину не пишет, `fadeModel`). Над полом и ковром (ворс до 3 см) — на
    // `GHOST_LIFT_CM`, плюс сдвиг глубины: без мерцания стыка с полом.
    // Рисуется ПОСЛЕ предмета (T-05/10: предмет плотнее, `MOVE_MODEL_ALPHA` 0,8): нарисованный до него, след проступал сквозь плотную
    // модель на 20 % и цвет «влезает / нет» почти не читался. Глубину проверяет по-прежнему: стены и соседняя мебель его закрывают
    const mat = new THREE.MeshBasicMaterial({
      color: 0x3aa55c, transparent: true, opacity: 0.55, depthWrite: false, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.renderOrder = MOVE_GHOST_ORDER;
    this.ghost = mesh;
    this.scene.add(mesh);
  }

  /** Перенести черновик в новую точку. `ok` решает вызывающая сторона (проверка места). */
  moveDraftTo(x: number, y: number, ok: boolean, rot?: number): void {
    if (!this.moving) return;
    this.moving.now.x = x;
    this.moving.now.y = y;
    if (rot !== undefined && Number.isFinite(rot)) this.moving.now.rot = ((rot % 360) + 360) % 360;
    this.applyMove(ok);
  }

  /** Повернуть черновик на шаг. */
  rotateDraftBy(deltaDeg: number, ok: boolean): void {
    if (!this.moving) return;
    this.moving.now.rot = (this.moving.now.rot + deltaDeg + 360) % 360;
    this.applyMove(ok);
  }

  private applyMove(ok: boolean): void {
    if (!this.moving) return;
    const p = this.placed.get(this.moving.slotId);
    const { x, y, rot } = this.moving.now;
    const { from, base } = this.moving;
    if (p) {
      // сдвиг и поворот СЧИТАЕМ ОТ ИСХОДНОГО положения группы: так отмена возвращает предмет
      // ровно туда, где он стоял, без накопления ошибки за время перетаскивания
      p.group.position.x = base.posX + (x - from.x) * CM;
      p.group.position.z = base.posZ + (y - from.y) * CM;
      // тот же знак, что у постановки предмета (`placeGroup`: rotation.y = rot): поставленный после переноса предмет не прыгает
      p.group.rotation.y = base.rotY + ((rot - from.rot) * Math.PI) / 180;
    }
    if (this.ghost && p) {
      // след — там же, где группа предмета, и повёрнут, как она: модель и след опираются на одно место
      this.ghost.position.set(p.group.position.x, GHOST_LIFT_CM * CM, p.group.position.z);
      this.ghost.rotation.y = p.group.rotation.y;
      (this.ghost.material as THREE.MeshBasicMaterial).color.set(ok ? 0x3aa55c : 0xc0392b);
    }
    // рамку на время переноса прячем: предмет «в руке» показан полупрозрачной моделью и следом на полу (как в Sims, TG 1588)
    if (this.outline) this.outline.visible = false;
  }

  /** Текущее положение черновика. */
  moveDraft(): { x: number; y: number; rot: number } | null {
    return this.moving ? { ...this.moving.now } : null;
  }

  /** Завершить перемещение: вернуть куда встало (вызывающая сторона запишет в подбор). */
  endMove(): { slotId: string; x: number; y: number; rot: number } | null {
    if (!this.moving) return null;
    const out = { slotId: this.moving.slotId, ...this.moving.now };
    this.clearMove();
    this.showOutline(out.slotId);
    this.bakeContact();   // тень — на новом месте (страница затем пересоберёт расстановку — запекание сольётся в одно)
    return out;
  }

  /** Отменить перемещение — предмет возвращается ровно туда, где стоял. */
  cancelMove(): void {
    if (!this.moving) return;
    const { slotId, from } = this.moving;
    this.moving.now = { ...from };
    this.applyMove(true);
    this.clearMove();
    this.showOutline(slotId);
    this.bakeContact();   // предмет вернулся — тень тоже
  }

  private clearMove(): void {
    this.moving = null;
    this.unfadeModel();
    if (this.ghost) {
      this.scene.remove(this.ghost);
      this.ghost.geometry.dispose();
      (this.ghost.material as THREE.Material).dispose();
      this.ghost = null;
    }
  }

  /** Точка на полу под курсором — куда тянут предмет. */
  floorPoint(clientX: number, clientY: number, rect: DOMRect): { x: number; y: number } | null {
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.floors, false)[0];
    if (hit) return { x: hit.point.x / CM, y: hit.point.z / CM };
    // мимо пола — считаем пересечение с горизонтальной плоскостью на уровне пола
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const pt = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(plane, pt) ? { x: pt.x / CM, y: pt.z / CM } : null;
  }

  /**
   * Контур вокруг выбранного предмета. Синий круг на полу владелец забраковал (29.09): у
   * широких вещей вроде кухни он превращался в дугу через весь экран. Контур по габариту
   * читается сразу и ничего не загораживает.
   */
  private outline: THREE.LineSegments | null = null;
  /** переиспользуемая коробка: контур пересчитывается на каждом выделении */
  private readonly _bb = new THREE.Box3();

  private showOutline(slotId: string | null): void {
    if (!this.outline) {
      const geo = new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1));
      // тёплая терракота бренда (#b06a4a), а не белая «техническая» рамка (владелец 16.10: «выделять красиво»)
      const mat = new THREE.LineBasicMaterial({
        color: 0xc8805c,
        transparent: true,
        opacity: 0.95,
        depthTest: false,
      });
      this.outline = new THREE.LineSegments(geo, mat);
      this.outline.renderOrder = 999;
      this.scene.add(this.outline);
    }
    const placed = slotId ? this.placed.get(slotId) : undefined;
    if (!placed) {
      this.outline.visible = false;
      return;
    }
    const { size, centre, yaw } = outlineFrame(placed.group, this._bb);
    this.outline.scale.copy(size);
    this.outline.position.copy(centre);
    this.outline.rotation.y = yaw;
    (this.outline.material as THREE.LineBasicMaterial).color.setHex(this.outlineWarn ? 0xd2453a : 0xc8805c);
    this.outline.visible = true;
  }

  /** Рамка-предупреждение (T-20261111-05 п.7): повёрнутый предмет задевает соседний — рамка красная, сам поворот не отменяется. */
  private outlineWarn = false;

  setOutlineWarn(on: boolean): void {
    if (this.outlineWarn === on) return;
    this.outlineWarn = on;
    if (this.outline) (this.outline.material as THREE.LineBasicMaterial).color.setHex(on ? 0xd2453a : 0xc8805c);
    this.start();
  }

  /** Выбранное место — его рамку и подсветку пересчитываем, когда объект места пересобран или сдвинут. */
  private selectedSlot: string | null = null;

  /**
   * Объект места пересобран, сдвинут или убран (замена товара, догрузка модели). Если место выбрано — рамка и подсветка
   * строятся заново по НОВОМУ объекту: раньше рамка считалась один раз при выборе, и после замены ковра на другой
   * размер оставалась по прежней плите (T-20261019-02).
   */
  private refreshSelection(slotId: string): void {
    if (slotId === this.selectedSlot) this.highlight(slotId);
  }

  highlight(slotId: string | null): void {
    this.selectedSlot = slotId;
    this.showOutline(slotId);
    for (const [id, p] of this.placed) {
      p.group.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        const mat = m.material as THREE.MeshStandardMaterial | THREE.MeshStandardMaterial[];
        const list = Array.isArray(mat) ? mat : [mat];
        for (const x of list) {
          if (!x || !("emissive" in x)) continue;
          if (id === slotId) {
            x.userData.prevEmissive ??= x.emissive.getHex();
            x.emissive.setHex(0x4a2614);   // мягкая тёплая подсветка выбранного предмета
            x.emissiveIntensity = 0.32;
          } else if (x.userData.prevEmissive !== undefined) {
            x.emissive.setHex(Number(x.userData.prevEmissive));
            delete x.userData.prevEmissive;
          }
        }
      });
    }
  }

  /** Комната сменилась: сообщить наружу и догрузить её обстановку (ленивый режим). */
  private roomChanged(id: string | null): void {
    if (id === this.currentRoom) return;
    this.currentRoom = id;
    this.events.onRoomChange?.(id);
    if (this.lastScene && !this.syncing) {
      this.syncing = true;
      void this.syncObjects(this.lastScene).finally(() => {
        this.syncing = false;
      });
    }
  }

  /** Комната по положению человека — работает при ХОДЬБЕ. */
  private updateRoom(): void {
    // в пристройке (закуток за порталом) — её комната, не «нигде» (T-20261112-36)
    this.roomChanged(walkRoomAt(this.apartment, this.pos.x, this.pos.y));
  }

  private tick = (): void => {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.tick);
    const dt = Math.min(0.05, this.clock.getDelta());
    // кольцо «сюда пойдём» (T-20261112-36): пульс; цель пути гаснет, когда путь кончился (дошли, клавиши, ракурс), в виде сверху — нет
    if (this.walkMarker?.visible) {
      if (this.viewMode === "top" || (this.markerMode === "route" && !this.moveTarget)) this.hideWalkTarget(true);
      else pulseWalkMarker(this.walkMarker, performance.now());
    }

    const speed = (this.keys.has("ShiftLeft") ? 420 : 240) * dt; // см/с
    let fx = 0;
    let fy = 0;
    if (this.keys.has("KeyW") || this.keys.has("ArrowUp")) fy += 1;
    if (this.keys.has("KeyS") || this.keys.has("ArrowDown")) fy -= 1;
    if (this.keys.has("KeyA") || this.keys.has("ArrowLeft")) fx -= 1;
    if (this.keys.has("KeyD") || this.keys.has("ArrowRight")) fx += 1;

    if ((fx || fy) && this.viewMode === "top") {
      const radT = (this.heading * Math.PI) / 180;
      const step = speed * 1.6;
      this.topTarget.x += (Math.sin(radT) * fy + Math.cos(radT) * fx) * step;
      this.topTarget.y += (Math.cos(radT) * fy - Math.sin(radT) * fx) * step;
      this.clampTopTarget();
    } else if (fx || fy) {
      this.moveTarget = null;
      this.faceAt = null;
      const rad = (this.heading * Math.PI) / 180;
      const dirX = Math.sin(rad);
      const dirY = Math.cos(rad);
      const len = Math.hypot(fx, fy) || 1;
      const mx = ((dirX * fy + dirY * fx) / len) * speed;
      const my = ((dirY * fy - dirX * fx) / len) * speed;
      // упор в стену, косяк, мебель — скольжение вдоль преграды, без шага назад (T-20261111-14, `walk-motion.ts:slideStep`)
      const next = slideStep(this.area, { x: this.pos.x, y: this.pos.y }, mx, my, this.slideMemo);
      this.pos.set(next.x, next.y);
      this.updateRoom();
    } else if (this.moveTarget) {
      // ДРОЖЬ У СТЕНЫ И МЕБЕЛИ (demo-20 Б6; T-20261111-14): идём по пути в обход мебели (`goTo` → `planRoute`), взгляд плавно
      // поворачивается к точке в 60 см впереди по пути — на изломах курс не дёргается; упор 9 кадров подряд — стоп
      const r = followRoute(this.area, { x: this.pos.x, y: this.pos.y }, this.moveTarget, 260 * dt);
      this.pos.set(r.pos.x, r.pos.y);
      if (r.aim) {
        const dx = r.aim.x - this.pos.x;
        const dy = r.aim.y - this.pos.y;
        if (Math.hypot(dx, dy) > 15) {
          const diff = (((Math.atan2(dx, dy) * 180) / Math.PI - this.heading + 540) % 360) - 180;
          this.heading = (this.heading + diff * Math.min(1, dt * 4) + 360) % 360;
        }
      }
      // идём к окну — взгляд сразу плавно поднимается на окно, не смотрит в пол по дороге (T-30/2)
      if (this.faceAt) this.pitch += (this.faceAt.pitch - this.pitch) * Math.min(1, dt * 3);
      if (r.done) this.moveTarget = null;
      this.updateRoom();
    } else if (this.faceAt && this.viewMode === "walk") {
      // дошёл до окна (`walkToWindow`) — плавно поворачиваемся к нему и смотрим на середину окна
      const k = Math.min(1, dt * 4), f = this.faceAt;
      const dh = (((f.heading - this.heading + 540) % 360) - 180), dp = f.pitch - this.pitch;
      this.heading = (this.heading + dh * k + 360) % 360;
      this.pitch += dp * k;
      if (Math.abs(dh) < 0.3 && Math.abs(dp) < 0.3) this.faceAt = null;
    }

    if (this.viewMode === "photo" && this.photo) {
      const lp = this.livePose();
      const { eye, target } = this.liveRay(lp ? { ...this.photo, x: lp.x, y: lp.y, rot: lp.rot } : this.photo);
      if (lp && lp.pitch) target[1] += Math.tan((lp.pitch * Math.PI) / 180) * PHOTO_AIM_CM;   // поворот взгляда вверх-вниз
      const vfov = verticalFov(this.photo.fov ?? 72, this.camera.aspect);
      const shift = this.liveShift(this.photo);
      if (Math.abs(this.camera.fov - vfov) > 0.01 || (this.camera.view?.offsetY ?? 0) !== -shift) {
        this.camera.fov = vfov;
        applyPhotoShift(this.camera, shift);
        this.camera.updateProjectionMatrix();
      }
      this.camera.position.set(eye[0] * CM, eye[1] * CM, eye[2] * CM);
      this.camera.lookAt(target[0] * CM, target[1] * CM, target[2] * CM);
      this.renderer.render(this.scene, this.camera);
      return;
    }
    const rad = (this.heading * Math.PI) / 180;
    if (this.viewMode === "top") {
      // вид сверху: камера на дуге вокруг точки интереса
      const pitchRad = (this.topPitch * Math.PI) / 180;
      const d = this.topDistanceCm * CM;
      const tx = this.topTarget.x * CM;
      const tz = this.topTarget.y * CM;
      this.camera.position.set(
        tx - Math.sin(rad) * Math.cos(pitchRad) * d,
        Math.max(1.2, -Math.sin(pitchRad) * d),
        tz - Math.cos(rad) * Math.cos(pitchRad) * d,
      );
      this.camera.lookAt(tx, 0.4, tz);
      this.renderer.render(this.scene, this.camera);
      return;
    }
    const pitchRad = (this.pitch * Math.PI) / 180;
    let eye = EYE_CM;
    let ox = 0;
    let oy = 0;
    const wb = this.walkBlend;
    if (wb) {
      const t = Math.min(1, (performance.now() - wb.t0) / wb.ms);
      const left = Math.pow(1 - t, 3); // как у перехода ракурсов (`livePose`)
      eye = EYE_CM + (wb.eye - EYE_CM) * left;
      ox = wb.dx * left;
      oy = wb.dy * left;
      this.camera.fov = this.quality.fov + (wb.fov - this.quality.fov) * left;
      this.camera.updateProjectionMatrix();
      if (t >= 1) this.walkBlend = null;
    }
    this.camera.position.set((this.pos.x + ox) * CM, eye * CM, (this.pos.y + oy) * CM);
    const look = new THREE.Vector3(
      this.camera.position.x + Math.sin(rad) * Math.cos(pitchRad),
      this.camera.position.y + Math.sin(pitchRad),
      this.camera.position.z + Math.cos(rad) * Math.cos(pitchRad),
    );
    this.camera.lookAt(look);
    this.renderer.render(this.scene, this.camera);
  };

  start(): void {
    if (!this.raf) this.tick();
  }

  /** Загрузить модель в кэш заранее (кандидат ленты замен); ошибка — молча: при замене будет честная коробка. */
  preloadMesh(url: string): void {
    this.meshes.load(url).catch(() => undefined);
  }

  /** Остановить цикл кадров (холст скрыт — не жечь батарею); `start()` продолжает. */
  stop(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  /**
   * Пробные кадры (demo-01 п.7): время N отрисовок текущей сцены с ожиданием видеокарты (`readPixels` одного пикселя
   * дожидается конца кадра). Первые 2 кадра — разогрев (компиляция шейдеров), в счёт не идут. Возвращает p95, мс.
   */
  measureFrameMs(frames = 10): number {
    const gl = this.renderer.getContext();
    const px = new Uint8Array(4);
    const times: number[] = [];
    for (let i = 0; i < frames + 2; i++) {
      const t = performance.now();
      this.renderer.render(this.scene, this.camera);
      gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
      if (i >= 2) times.push(performance.now() - t);
    }
    times.sort((a, b) => a - b);
    return times[Math.min(times.length - 1, Math.floor(times.length * 0.95))] ?? 0;
  }

  /** Статус предметов по месту (demo-10): `stub` — честная коробка вместо модели, `pending` — модель ещё грузится. */
  slotStatus(): Record<string, "loaded" | "stub" | "pending"> {
    return Object.fromEntries([...this.placed].map(([id, p]) => [id, p.status]));
  }

  /**
   * КАДР ДЛЯ НЕЙРОСЕТИ ИЗ ПОЗЫ РАКУРСА (demo-10, Codex 17.10: атомарно, не `goToPose` + `exportFrame`). Отдельная камера ровно
   * в позе (без наклона телефона и поворота взгляда), экранная камера не трогается; выделение и призрак расстановки скрыты,
   * честные коробки — непрозрачные (как серверный clay); ждём догрузки моделей (до 20 с). Всё возвращается в `finally`.
   */
  async capturePhoto(pose: PhotoPose, width: number, height: number, quality = 0.85, opts: { tilt?: boolean } = {}): Promise<Blob> {
    const t0 = performance.now();
    // и картинок материалов (ковёр, картина, пол): `ready` сцены ждёт только модели, а текстура, не пришедшая к кадру, — чёрная
    // (ковёр на карточке тура, T-20261111-05, TG 1453). Не пришла совсем — `materials.ts:dropTexture` вернёт ровный цвет
    while ((this.pendingUrls.size || this.matCtx.loading.size) && performance.now() - t0 < 20000) await new Promise((ok) => setTimeout(ok, 100));
    const cam = new THREE.PerspectiveCamera(verticalFov(pose.fov ?? 72, width / height), width / height, this.camera.near, this.camera.far);
    applyPhotoShift(cam, photoShift(pose, width / height));
    cam.updateProjectionMatrix();
    const { eye, target } = photoRay(pose);
    // вертикальный кадр телефона — с тем же наклоном к мебели, что видит человек в 3D (иначе полкадра потолок, demo-10)
    if (opts.tilt) target[1] += Math.tan((this.tiltFor(pose) * Math.PI) / 180) * PHOTO_AIM_CM;
    cam.position.set(eye[0] * CM, eye[1] * CM, eye[2] * CM);
    cam.lookAt(target[0] * CM, target[1] * CM, target[2] * CM);
    const undo: (() => void)[] = [];
    for (const p of this.placed.values()) {
      if (p.status !== "stub") continue;
      p.group.traverse((o) => {
        const m = o as THREE.Mesh;
        const mat = m.isMesh ? (m.material as THREE.MeshStandardMaterial) : null;
        if (!mat || !mat.transparent) return;
        const op = mat.opacity;
        mat.transparent = false; mat.opacity = 1; mat.needsUpdate = true;
        undo.push(() => { mat.transparent = true; mat.opacity = op; mat.needsUpdate = true; });
      });
    }
    // рамка выбора, след переноса и кольцо «сюда пойдём» (T-36) — подсказки глазу, не в кадр нейросети
    for (const o of [this.outline, this.ghost, this.walkMarker]) if (o && o.visible) { o.visible = false; undo.push(() => { o.visible = true; }); }
    // кайма вида за окном — только для глаза «3D» (`openings.ts:skirtMesh`); кадр нейросети — как у сервера, по плоскости вида
    this.scene.traverse((o) => { if (o.name === "window-view:skirt" && o.visible) { o.visible = false; undo.push(() => { o.visible = true; }); } });
    // тёплая подсветка выбранного — не в кадр нейросети; снимаем и возвращаем в той же задаче, что и кадр (T-20261109-32/2:
    // прежде её гасил `demo-scene.capture` на всю съёмку — выбранный предмет в 3D «тух» на секунды)
    const sel = this.selectedSlot;
    if (sel) { this.highlight(null); undo.push(() => this.highlight(sel)); }
    return this.frameBlob(width, height, "image/jpeg", quality, () => {
      try { this.renderer.render(this.scene, cam); } finally { undo.forEach((f) => f()); }
    });
  }

  /**
   * КАДР В ЧУЖОМ РАЗМЕРЕ БЕЗ МИГАНИЯ ОКНА (T-20261109-32/2). Холст один: кадр рисуется в нём в своём размере. Прежде холст ждал
   * `toBlob` в этом размере — между тем браузер показывал окно 3D в чужом разрешении и мог показать сам кадр другой камеры (проба
   * `photo-views-check flicker`: 8 кадров анимации из 41 в размере 2048×1489). Теперь в ОДНОЙ задаче, до показа: нарисовали → копия
   * в свой 2D-холст → размер вернули → видимый вид перерисован. Сжатие (`toBlob`) — уже копии, асинхронно; пиксели кадра те же.
   */
  private async frameBlob(width: number, height: number, type: string, quality: number, draw: () => void): Promise<Blob> {
    const canvas = this.renderer.domElement;
    const prev = new THREE.Vector2();
    this.renderer.getSize(prev);
    const prevRatio = this.renderer.getPixelRatio();
    const copy = document.createElement("canvas");
    copy.width = width;
    copy.height = height;
    const ctx = copy.getContext("2d");
    if (!ctx) throw new Error("кадр не собрался");
    try {
      this.renderer.setPixelRatio(1);
      this.renderer.setSize(width, height, false);
      draw();
      ctx.drawImage(canvas, 0, 0);   // буфер WebGL ещё цел: та же задача, что и отрисовка
    } finally {
      this.renderer.setPixelRatio(prevRatio);
      this.renderer.setSize(prev.x, prev.y, false);
      this.renderer.render(this.scene, this.camera);   // `setSize` очистил холст — видимый вид на место до показа
    }
    const blob = await new Promise<Blob | null>((ok) => copy.toBlob(ok, type, quality));
    if (!blob) throw new Error("кадр не собрался");
    return blob;
  }

  /** Кадр «здесь и сейчас» — для превью и для e2e-проверки, что сцена реально нарисовалась. */
  snapshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
  }

  /**
   * Миниатюры предметов для списка (T-20261109-35/2, `thumbs.ts`): место → JPEG data URL; модель ещё не пришла (коробка, загрузка) или
   * места нет — null, страница спросит позже. Подсветка выбранного на время листа снята; размер холста и вид экрана — на место.
   */
  thumbs(slotIds: string[], size = 128): (string | null)[] {
    const models = slotIds.map((id) => {
      const p = this.placed.get(id);
      return p && p.status === "loaded" ? p.group : null;
    });
    if (!models.some(Boolean) || this.disposed) return models.map(() => null);
    const prev = new THREE.Vector2();
    this.renderer.getSize(prev);
    const prevRatio = this.renderer.getPixelRatio();
    const sel = this.selectedSlot;
    if (sel) this.highlight(null);
    try {
      return renderThumbs(this.renderer, models, size, this.scene.environment, this.scene.environmentIntensity);
    } finally {
      this.renderer.setPixelRatio(prevRatio);
      this.renderer.setSize(prev.x, prev.y, false);
      if (sel) this.highlight(sel);
      this.renderer.render(this.scene, this.camera);   // `setSize` очистил холст — видимый вид на место до показа
    }
  }

  /**
   * Сохранённый кадр заданного размера (demo-01 п.3): JPEG/WebP асинхронно (`toBlob`), только по действию человека —
   * не на каждое движение. Холст временно перерисовывается в нужном размере и возвращается обратно.
   */
  async exportFrame(width: number, height: number, type = "image/jpeg", quality = 0.9): Promise<Blob> {
    const prevAspect = this.camera.aspect;
    const prevFov = this.camera.fov;
    const ring = this.walkMarker?.visible ? this.walkMarker : null;   // кольцо «сюда пойдём» — не в сохранённый кадр (T-36)
    return this.frameBlob(width, height, type, quality, () => {
      try {
        if (ring) ring.visible = false;
        this.camera.aspect = width / height;
        if (this.photo) this.camera.fov = verticalFov(this.photo.fov ?? 72, this.camera.aspect);
        this.camera.updateProjectionMatrix();
        this.renderer.render(this.scene, this.camera);
      } finally {
        if (ring) ring.visible = true;
        this.camera.aspect = prevAspect;
        this.camera.fov = prevFov;
        this.camera.updateProjectionMatrix();
      }
    });
  }

  get position(): { x: number; y: number; heading: number } {
    return { x: this.pos.x, y: this.pos.y, heading: this.heading };
  }

  get room(): string | null {
    return this.currentRoom;
  }

  /**
   * Экранная точка предмета «здесь и сейчас» — для проверок и для наведения на предмет.
   * Тот же расчёт, что у карточки, но по запросу.
   */
  /** Габаритная коробка предмета и её центр — из кэша, пока группа та же и не сдвинута (и не старше 1 с: модель могла смениться с коробки). */
  private anchorOf(slotId: string) {
    const placed = this.placed.get(slotId);
    if (!placed) return null;
    const g = placed.group, now = performance.now();
    let a = this.anchors.get(slotId);
    if (!a || a.g !== g || a.px !== g.position.x || a.pz !== g.position.z || a.ry !== g.rotation.y || now - a.t > 1000) {
      const bb = new THREE.Box3().setFromObject(g);
      // ЧТО СТОИТ НА ПРЕДМЕТЕ — В ЕГО РАМКЕ (demo-27 В): телевизор на тумбе, ваза на столике — объекты сцены (`@extra:`), а не
      // предметы; без них ценник тумбы ложился на экран телевизора. Своё — центр на плане внутри следа предмета, низ не ниже его низа
      if (!isExtra(slotId) && !bb.isEmpty()) {
        const own = bb.clone();
        for (const [id2, p2] of this.placed) {
          if (!isExtra(id2)) continue;
          const b2 = new THREE.Box3().setFromObject(p2.group);
          if (b2.isEmpty()) continue;
          const cx = (b2.min.x + b2.max.x) / 2, cz = (b2.min.z + b2.max.z) / 2;
          if (cx >= own.min.x && cx <= own.max.x && cz >= own.min.z && cz <= own.max.z && b2.min.y >= own.min.y) bb.union(b2);
        }
      }
      a = { g, px: g.position.x, pz: g.position.z, ry: g.rotation.y, t: now, bb,
        c: new THREE.Vector3((bb.min.x + bb.max.x) / 2, (bb.min.y + bb.max.y) / 2, (bb.min.z + bb.max.z) / 2) };
      this.anchors.set(slotId, a);
    }
    return a;
  }

  /**
   * Точка предмета на холсте (px) и его РАМКА — проекция габаритной коробки `[left, top, right, bottom]` (demo-27 В: ценник ставится
   * над рамкой, а не на середину предмета — у дальнего стола он закрывал столешницу). Угол коробки за камерой — рамки нет.
   */
  projectSlot(slotId: string): { x: number; y: number; visible: boolean; distM: number; box: [number, number, number, number] | null } | null {
    const a = this.anchorOf(slotId);
    if (!a) return null;
    const centre = a.c.clone();
    const distM = this.camera.position.distanceTo(centre);
    const v = centre.project(this.camera);
    const el = this.renderer.domElement;
    const w = el.clientWidth || el.width;
    const h = el.clientHeight || el.height;
    let box: [number, number, number, number] | null = [Infinity, Infinity, -Infinity, -Infinity];
    const q = new THREE.Vector3();
    for (const x of [a.bb.min.x, a.bb.max.x]) for (const y of [a.bb.min.y, a.bb.max.y]) for (const z of [a.bb.min.z, a.bb.max.z]) {
      if (!box) break;
      q.set(x, y, z).applyMatrix4(this.camera.matrixWorldInverse);
      if (q.z > -this.camera.near) { box = null; break; }        // угол за камерой — проекция неверна
      q.applyMatrix4(this.camera.projectionMatrix);
      const sx = (q.x * 0.5 + 0.5) * w, sy = (-q.y * 0.5 + 0.5) * h;
      box = [Math.min(box[0], sx), Math.min(box[1], sy), Math.max(box[2], sx), Math.max(box[3], sy)];
    }
    return {
      x: (v.x * 0.5 + 0.5) * w,
      y: (-v.y * 0.5 + 0.5) * h,
      visible: v.z < 1 && Math.abs(v.x) < 1 && Math.abs(v.y) < 1,
      distM,
      box,
    };
  }

  /** Состояние сцены для диагностики: что реально добавлено и куда смотрит камера. */
  /**
   * Доля почти чёрных точек кадра — сторож против «дыр» в картинке: незагруженная текстура
   * рисуется ЧЁРНЫМ (так пропадала дверь шкафа, 29.09).
   *
   * Читаем НЕ с экрана, а из отдельного буфера: без `preserveDrawingBuffer` экранный буфер к
   * моменту чтения уже очищен, а со сглаживанием разные движки браузера отдают его по-разному
   * (в одном режиме кадр читался, в другом — сплошной ноль).
   */
  debugDarkShare(w = 128, h = 80): number {
    const rt = new THREE.WebGLRenderTarget(w, h);
    const prev = this.renderer.getRenderTarget();
    this.renderer.setRenderTarget(rt);
    this.renderer.render(this.scene, this.camera);
    const buf = new Uint8Array(w * h * 4);
    this.renderer.readRenderTargetPixels(rt, 0, 0, w, h, buf);
    this.renderer.setRenderTarget(prev);
    rt.dispose();
    let dark = 0;
    for (let i = 0; i < w * h; i += 1) {
      const o = i * 4;
      if (buf[o]! + buf[o + 1]! + buf[o + 2]! < 12) dark += 1;
    }
    return dark / (w * h);
  }

  debugState(): Record<string, unknown> {
    let meshes = 0;
    this.scene.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) meshes += 1;
    });
    return {
      sceneChildren: this.scene.children.length,
      meshes,
      rooms: this.roomGroups.size,
      placed: this.placed.size,
      floors: this.floors.length,
      camera: this.camera.position.toArray().map((v) => Number(v.toFixed(2))),
      heading: Math.round(this.heading),
      room: this.currentRoom,
      canvas: [this.renderer.domElement.width, this.renderer.domElement.height],
    };
  }

  /** Что стоит на каждом месте (подпись модели) — живая проверка «замена дошла до сцены» (demo-02, приёмка 16.10 п.1). */
  placedSignatures(): Record<string, string> {
    return Object.fromEntries([...this.placed].map(([id, p]) => [id, p.signature]));
  }

  /** Повернуться в прогулке лицом к точке квартиры (см): живая проверка «4 с хода к предмету» (demo-05 п.1д). */
  faceToward(x: number, y: number): void {
    if (this.viewMode === "photo" && this.photo) {
      // взгляд из точки съёмки: направление позы на плане — (sin rot, −cos rot)
      const want = (Math.atan2(x - this.photo.x, -(y - this.photo.y)) * 180) / Math.PI;
      this.photoLook.yaw = ((want - this.photo.rot + 540) % 360) - 180;
      this.photoLook.pitch = this.basePitch(this.photo);
      return;
    }
    this.heading = ((Math.atan2(x - this.pos.x, y - this.pos.y) * 180) / Math.PI + 360) % 360;
  }

  /**
   * НАВЕСТИСЬ НА ПРЕДМЕТ (demo-15, критика Codex п.5): после замены покупатель видит новый предмет. Прямой полёт камеры прошёл бы
   * сквозь стену или мебель, поэтому: текущая точка годится (до следа предмета ≥ `FRAME_MIN_CM`, взгляд не закрыт высоким) — только
   * плавный поворот; иначе — точки кольца 1–1.8 м вокруг следа, где можно стоять, видно предмет и прямой путь от текущей проходим,
   * ближайшая к текущей — плавный переход; подходящей нет — только поворот. Расстояние — по размеру предмета (`frameDistCm`,
   * demo-20 Б5), взгляд наклонён к середине предмета по высоте (низкая тумба не уходит под нижний край). Ответ — что сделано.
   */
  frameItem(at: { x: number; y: number }, ms = 600): "turn" | "move" | "none" {
    const cur = this.viewMode === "photo" ? this.livePose()
      : { x: this.pos.x, y: this.pos.y, rot: (540 - this.heading) % 360, pitch: this.pitch };
    if (!cur) return "none";
    const base = this.photo ?? { x: cur.x, y: cur.y, rot: cur.rot, fov: 72, pose: PHOTO_POSE_VER };
    const spot = frameSpot(this.area, cur, at, base.fov ?? 72);
    // сдвиг вертикального кадра подобран для точки съёмки — на новой точке он не годится
    const keep = spot.kind !== "move" && typeof base.pshift === "number";
    const pose: PhotoPose = { x: spot.x, y: spot.y, rot: spot.rot, fov: base.fov ?? 72, pose: base.pose ?? PHOTO_POSE_VER, ...(keep ? { pshift: base.pshift } : {}) };
    this.goToPose(pose, spot.kind === "move" ? Math.max(ms, Math.min(1400, Math.hypot(spot.x - cur.x, spot.y - cur.y) * 4)) : ms,
      this.pitchToward(pose, spot.item));
    return spot.kind;
  }

  /**
   * Наклон взгляда позы, при котором середина предмета по высоте — в середине кадра (градусы, вниз — минус; вверх не смотрим).
   * Учитывает сдвиг объектива позы: опущенный кадр уже смотрит ниже оси камеры. Предел ±35° — в `goToPose`.
   */
  private pitchToward(pose: PhotoPose, it: { x: number; y: number; w: number; d: number; rot: number; h?: number }): number {
    const dist = Math.max(30, Math.hypot(it.x - pose.x, it.y - pose.y));
    const toItem = Math.atan2((it.h ?? 60) / 2 - this.liveRay(pose).eye[1], dist);
    const vhalf = (verticalFov(pose.fov ?? 72, this.camera.aspect) * Math.PI) / 360;
    const lens = Math.atan(2 * this.liveShift(pose) * Math.tan(vhalf));   // минус — кадр опущен
    return Math.min(0, ((toItem - lens) * 180) / Math.PI);
  }

  /** Где стоит человек в прогулке и сколько до ближайшей мебели — метрика живой проверки (прогон d8 15.10). */
  debugWalk(): { x: number; y: number; heading: number; inRoom: boolean; nearestCm: number | null; loading: boolean } {
    const { x, y } = this.pos;
    const d = this.area.obstacles.map((o) => obstacleDistanceCm(o, x, y));
    return { x: Math.round(x), y: Math.round(y), heading: Math.round(this.heading), inRoom: inRooms(this.area, x, y),
      nearestCm: d.length ? Math.round(Math.min(...d)) : null,
      // модели ещё грузятся — старт выбран по неполной расстановке и будет выбран заново после загрузки (под заставкой)
      loading: this.loadedCount < this.totalCount };
  }

  canStandAt(x: number, y: number): boolean {
    return canStand(this.area, x, y);
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    if (this.outline) {
      this.outline.geometry.dispose();
      (this.outline.material as THREE.Material).dispose();
    }
    if (this.walkMarker) {
      this.walkMarker.geometry.dispose();
      this.walkMarker.material.dispose();
    }
    for (const p of this.placed.values()) disposeObject(p.group);
    this.placed.clear();
    for (const g of this.roomGroups.values()) disposeObject(g);
    this.roomGroups.clear();
    this.contact?.dispose();
    this.contact = null;
    if (this.curtains) disposeObject(this.curtains);
    this.curtains = null;
    this.meshes.dispose();
    disposeMaterialCtx(this.matCtx);
    this.renderer.dispose();
    // контекст отдаём браузеру сразу, а не ждём сборщика мусора: у вкладки их не больше 16, после — гаснет самый старый
    // (демо пересоздаёт сцену при смене комнаты — без этого 16-й переход выключал 3D, проба T-20261106-77/3)
    this.renderer.forceContextLoss();
  }
}

/**
 * С какой стороны линии ставить колонны: подальше от двери. Дверь переводим в локальную ось
 * предмета (вдоль линии) и смотрим, к какому её концу она ближе.
 */
function farFromDoor(room: Room, p: Placement): "start" | "end" {
  const door = room.openings.find((o) => o.kind === "door" || o.kind === "opening");
  if (!door) return "start";
  const mid = door.offsetCm + door.widthCm / 2;
  const dx =
    door.wall === "south" || door.wall === "north" ? room.x + mid - p.x : (door.wall === "west" ? room.x : room.x + room.w) - p.x;
  const dy =
    door.wall === "west" || door.wall === "east" ? room.y + mid - p.y : (door.wall === "south" ? room.y : room.y + room.d) - p.y;
  const a = (-p.rot * Math.PI) / 180;
  const local = dx * Math.cos(a) - dy * Math.sin(a); // координата двери вдоль линии
  return local < 0 ? "end" : "start";
}

/** Место и поворот предмета — во внешнюю группу (центр следа на плане, низ на полу + подъём). */
/** Сколько ждать модель, прежде чем показать на её месте серую коробку. */
const STUB_SHOW_MS = 15_000;
/** Непрозрачность предмета «в руке» при переносе (T-20261111-05/8: 0,3; T-05/10 — плотнее, видно, что несёшь, как в Sims). */
const MOVE_MODEL_ALPHA = 0.8;
/** Порядок отрисовки следа переноса: после предмета «в руке» (у того на 1 меньше) — след виден и сквозь плотную модель. */
const MOVE_GHOST_ORDER = 1000;
/** След переноса над полом, см: выше ворса ковра (до 3 см, `kits` ковра), чтобы ковёр его не закрывал. */
const GHOST_LIFT_CM = 3.5;

function placeGroup(g: THREE.Object3D, p: Placement): void {
  g.position.set(p.x * CM, (p.elevCm ?? 0) * CM, p.y * CM);
  g.rotation.y = (p.rot * Math.PI) / 180;
}

/** Подпись объекта: что требует пересоздать его (модель, размеры, материалы). Место/поворот — не сюда (demo-01 п.4). */
function signatureOf(spec: ObjectSpec): string {
  const p = spec.placement;
  const geom = `${p.wCm}|${p.dCm}|${p.hCm}`;
  if (spec.kind === "mesh") return `mesh|${spec.meshId}|${spec.yawDeg}|${(spec.tintRgb ?? []).join(",")}|${geom}|${p.cornerLeft ?? "-"}`;
  // Наборы (кухня, санузел, кровать, шкаф, ковёр) собираются кодом от места: кухня выбирает сторону колонн по двери
  // (`farFromDoor`). Их сдвиг — пересборка, как до demo-01 (verify 14.10: колонны оставались на старой стороне).
  const at = `${p.x}|${p.y}|${p.rot}`;
  if (spec.kind === "kitchen") {
    return `kitchen|${spec.level}|${spec.features.join(",")}|${spec.doorMaterialId}|${spec.worktopMaterialId}|${spec.splashbackMaterialId}|${geom}|${at}`;
  }
  if (spec.kind === "bathroom") return `bath|${spec.level}|${spec.features.join(",")}|${spec.vanityMaterialId}|${geom}|${at}`;
  if (spec.kind === "tv") return `tv|${spec.hung}|${geom}`;
  if (spec.kind === "wall-plane") return `plane|${spec.mirror}|${spec.materialId}|${geom}`;
  return `${spec.kind}|${spec.level}|${spec.features.join(",")}|${spec.materialId}|${geom}|${at}`;
}
