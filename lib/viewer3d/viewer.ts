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
import { findRoom, roomAt, roomCentre } from "@/contracts/apartment";
import type { Catalogue, Material } from "@/contracts/configurator";
import type { ResolvedScene } from "@/lib/configurator/resolve";
import { type ObjectSpec, planObjects, surfacesByRoom } from "@/lib/viewer3d/build-scene";
import { buildKitchen } from "@/lib/viewer3d/kits/kitchen";
import { buildBathroom } from "@/lib/viewer3d/kits/bathroom";
import { buildBed, buildRug, buildWardrobe } from "@/lib/viewer3d/kits/bedroom";
import type { KitCtx } from "@/lib/viewer3d/kits/common";
import { createMaterialCtx, disposeMaterialCtx, type MaterialCtx } from "@/lib/viewer3d/materials";
import { MeshLibrary, disposeObject, placeMesh, stubBox } from "@/lib/viewer3d/meshes";
import { buildRoom, buildSurroundings } from "@/lib/viewer3d/rooms";
import { canStand, nearestStandable, stepWithSlide, walkArea, type WalkArea } from "@/lib/viewer3d/walk";

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
}

interface Placed {
  spec: ObjectSpec;
  group: THREE.Group;
  signature: string;
}

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
  private moveTarget: THREE.Vector2 | null = null;
  private currentRoom: string | null = null;
  /**
   * Режим камеры: прогулка или «кукольный дом» — вид сверху под углом (владелец 29.09).
   * Сверху удобно понять планировку и расстановку целиком, а ходить — чтобы «пожить» в комнате.
   */
  private viewMode: "walk" | "top" = "walk";
  private topTarget = new THREE.Vector2();   // точка, вокруг которой крутится вид сверху
  private topDistanceCm = 620;
  private topPitch = -52;
  /** Последняя разрешённая сцена — по ней догружаем комнату, в которую вошли. */
  private lastScene: ResolvedScene | null = null;
  private syncing = false;

  constructor(
    canvas: HTMLCanvasElement,
    apartment: Apartment,
    catalogue: Catalogue,
    quality: QualityProfile,
    events: ViewerEvents = {},
  ) {
    this.apartment = apartment;
    this.catalogue = catalogue;
    this.quality = quality;
    this.events = events;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: quality.name === "desktop", powerPreference: "high-performance" });
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
    this.renderer.toneMappingExposure = 1.05;
    if (quality.shadows) {
      this.renderer.shadowMap.enabled = true;
      this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    }

    this.camera = new THREE.PerspectiveCamera(quality.fov, 1, 0.05, 80);
    this.scene.background = new THREE.Color(0xd9e4ec);

    this.matCtx = createMaterialCtx(quality.anisotropy, true);
    this.matCtx.extraMaps = quality.extraMaps;
    const byId = (id: string): Material | undefined => catalogue.materials.find((m) => m.id === id);
    this.kitCtx = {
      materials: this.matCtx,
      byId,
      fallback: byId("paint-white") ?? catalogue.materials[0]!,
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
      this.scene.environmentIntensity = 0.55;
      env.dispose?.();
      pmrem.dispose();
    } catch {
      /* старый GPU/программный рендер — живём без окружения */
    }
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xb6b0a6, 1.05));
    const sun = new THREE.DirectionalLight(0xfff3e2, 1.25);
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
    }
    this.scene.add(sun);
    // мягкая подсветка снизу, чтобы мебель не проваливалась в чёрное на телефоне
    const fill = new THREE.DirectionalLight(0xdfe7ee, 0.35);
    fill.position.set(5, 3, 6);
    this.scene.add(fill);
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
      // прихожая: южная стена — вход в квартиру, там полотно закрыто
      const entranceWall = room.kind === "hall" ? "south" : undefined;
      const { group, floor } = buildRoom(this.matCtx, room, floorMat, wallMat, { entranceWall });
      group.userData.roomId = room.id;
      floor.userData.roomId = room.id;
      this.scene.add(group);
      this.roomGroups.set(room.id, group);
      this.floors.push(floor);
    }
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
    this.totalCount = specs.length;

    for (const [slotId, p] of [...this.placed]) {
      const next = wanted.get(slotId);
      if (!next || signatureOf(next) !== p.signature) {
        this.scene.remove(p.group);
        disposeObject(p.group);
        this.placed.delete(slotId);
      }
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

    if (spec.kind === "mesh") {
      const stub = stubBox(
        { xCm: p.x, yCm: p.y, rotDeg: p.rot, wCm: p.wCm, dCm: p.dCm, hCm: p.hCm, elevCm: p.elevCm },
        true,
      );
      stub.userData = { slotId: spec.slotId, roomId: spec.roomId, title: spec.titleRu };
      this.scene.add(stub);
      this.placed.set(spec.slotId, { spec, group: stub, signature: signatureOf(spec) });

      try {
        this.pendingUrls.add(spec.url);
        const source = await this.meshes.load(spec.url);
        if (this.disposed) return;
        const real = placeMesh(source, {
          xCm: p.x,
          yCm: p.y,
          rotDeg: p.rot,
          wCm: p.wCm,
          dCm: p.dCm,
          hCm: p.hCm,
          elevCm: p.elevCm,
          yawDeg: spec.yawDeg,
          tintRgb: spec.tintRgb,
        });
        real.userData = { slotId: spec.slotId, roomId: spec.roomId, title: spec.titleRu };
        const cur = this.placed.get(spec.slotId);
        if (cur && cur.group === stub) {
          this.scene.remove(stub);
          disposeObject(stub);
          this.scene.add(real);
          this.placed.set(spec.slotId, { spec, group: real, signature: signatureOf(spec) });
        }
      } catch {
        // модель не пришла — остаётся честная серая коробка, как в демо
      } finally {
        this.pendingUrls.delete(spec.url);
        this.loadedCount += 1;
        this.events.onProgress?.(this.loadedCount, this.totalCount);
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

    group.position.set(p.x * CM, (p.elevCm ?? 0) * CM, p.y * CM);
    group.rotation.y = (p.rot * Math.PI) / 180;
    group.userData = { slotId: spec.slotId, roomId: spec.roomId, title: spec.titleRu };
    this.scene.add(group);
    this.placed.set(spec.slotId, { spec, group, signature: signatureOf(spec) });
    this.loadedCount += 1;
    this.events.onProgress?.(this.loadedCount, this.totalCount);
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

  /** Переключение вида: прогулка ↔ сверху. Потолки в виде сверху прячем, иначе видно только их. */
  setViewMode(mode: "walk" | "top"): void {
    if (this.viewMode === mode) return;
    this.viewMode = mode;
    this.scene.traverse((o) => {
      if (o.name.startsWith("ceiling:")) o.visible = mode !== "top";
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

  get mode(): "walk" | "top" {
    return this.viewMode;
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
    if (this.viewMode === "top") {
      // сверху мышь крутит сцену вокруг точки и меняет наклон, а не «голову»
      this.heading = (this.heading + dxPx * 0.25 + 360) % 360;
      this.topPitch = Math.max(-85, Math.min(-22, this.topPitch - dyPx * 0.2));
      return;
    }
    this.heading = (this.heading + dxPx * 0.22 + 360) % 360;
    this.pitch = Math.max(-55, Math.min(45, this.pitch - dyPx * 0.18));
  }

  /** Тап по полу — «иди сюда» (мобильный сценарий из ТЗ). */
  goTo(xCm: number, yCm: number): void {
    const target = nearestStandable(this.area, xCm, yCm);
    if (!target) return;
    this.moveTarget = new THREE.Vector2(target.x, target.y);
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
    const candidates = [
      { x: room.x + room.w * 0.18, y: room.y + room.d * 0.18 },
      { x: room.x + room.w * 0.82, y: room.y + room.d * 0.18 },
      { x: room.x + room.w * 0.18, y: room.y + room.d * 0.82 },
      { x: room.x + room.w * 0.82, y: room.y + room.d * 0.82 },
      { x: c.x, y: c.y },
    ];
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
    const obstacles = [...this.placed.values()]
      .filter((p) => p.spec.roomId === roomId)
      .map((p) => p.spec.placement);
    // Расстояние до ПРЯМОУГОЛЬНИКА предмета, а не до круга вокруг него: кухонная линия
    // 340×60 «кругом» занимала всю комнату, и любая точка считалась занятой (кадр 29.09).
    const clearance = (x: number, y: number): number => {
      let min = 1e9;
      for (const o of obstacles) {
        const a = (-o.rot * Math.PI) / 180;
        const dx = x - o.x;
        const dy = y - o.y;
        const lx = dx * Math.cos(a) - dy * Math.sin(a);
        const ly = dx * Math.sin(a) + dy * Math.cos(a);
        const ox = Math.max(Math.abs(lx) - o.wCm / 2, 0);
        const oy = Math.max(Math.abs(ly) - o.dCm / 2, 0);
        min = Math.min(min, Math.hypot(ox, oy));
      }
      return min;
    };

    let best: { x: number; y: number } | null = null;
    let bestScore = -1e9;
    for (const cand of candidates) {
      const spot = nearestStandable(this.area, cand.x, cand.y, 8, 6);
      if (!spot) continue;
      const free = clearance(spot.x, spot.y);
      const door = isDoorSpot(cand);
      // от двери можно стоять ближе к мебели: мы смотрим В комнату, а не упираемся в шкаф
      if (free < (door ? 20 : 45)) continue;
      // подальше от центра (видно больше комнаты), свобода вокруг, и заметный плюс двери
      const score = Math.hypot(spot.x - c.x, spot.y - c.y) + Math.min(free, 150) + (door ? 220 : 0);
      if (score > bestScore) {
        bestScore = score;
        best = spot;
      }
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
    const dx = c.x - best.x;
    const dy = c.y - best.y;
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
    const hit = hits[0];
    if (hit) {
      let o: THREE.Object3D | null = hit.object;
      while (o && !o.userData?.slotId) o = o.parent;
      if (o?.userData?.slotId) return { slotId: String(o.userData.slotId) };
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
      const mat = new THREE.LineBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.9,
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
    const bb = this._bb.setFromObject(placed.group);
    const size = bb.getSize(new THREE.Vector3());
    const centre = bb.getCenter(new THREE.Vector3());
    this.outline.scale.set(Math.max(size.x, 0.05) * 1.04, Math.max(size.y, 0.05) * 1.04, Math.max(size.z, 0.05) * 1.04);
    this.outline.position.copy(centre);
    this.outline.visible = true;
  }

  highlight(slotId: string | null): void {
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
            x.emissive.setHex(0x2a3550);
            x.emissiveIntensity = 0.35;
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
    this.roomChanged(roomAt(this.apartment, this.pos.x, this.pos.y)?.id ?? null);
  }

  private tick = (): void => {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.tick);
    const dt = Math.min(0.05, this.clock.getDelta());

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
      const rad = (this.heading * Math.PI) / 180;
      const dirX = Math.sin(rad);
      const dirY = Math.cos(rad);
      const len = Math.hypot(fx, fy) || 1;
      const mx = ((dirX * fy + dirY * fx) / len) * speed;
      const my = ((dirY * fy - dirX * fx) / len) * speed;
      const next = stepWithSlide(this.area, { x: this.pos.x, y: this.pos.y }, mx, my);
      this.pos.set(next.x, next.y);
      this.updateRoom();
    } else if (this.moveTarget) {
      const dx = this.moveTarget.x - this.pos.x;
      const dy = this.moveTarget.y - this.pos.y;
      const dist = Math.hypot(dx, dy);
      if (dist < 6) {
        this.moveTarget = null;
      } else {
        const step = Math.min(dist, 260 * dt);
        const next = stepWithSlide(this.area, { x: this.pos.x, y: this.pos.y }, (dx / dist) * step, (dy / dist) * step);
        if (next.x === this.pos.x && next.y === this.pos.y) this.moveTarget = null;
        this.pos.set(next.x, next.y);
        const targetHeading = (Math.atan2(dx, dy) * 180) / Math.PI;
        const diff = ((targetHeading - this.heading + 540) % 360) - 180;
        this.heading = (this.heading + diff * Math.min(1, dt * 4) + 360) % 360;
        this.updateRoom();
      }
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
    this.camera.position.set(this.pos.x * CM, EYE_CM * CM, this.pos.y * CM);
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

  /** Кадр «здесь и сейчас» — для превью и для e2e-проверки, что сцена реально нарисовалась. */
  snapshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/png");
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
  projectSlot(slotId: string): { x: number; y: number; visible: boolean } | null {
    const placed = this.placed.get(slotId);
    if (!placed) return null;
    const bb = new THREE.Box3().setFromObject(placed.group);
    const centre = new THREE.Vector3((bb.min.x + bb.max.x) / 2, (bb.min.y + bb.max.y) / 2, (bb.min.z + bb.max.z) / 2);
    const v = centre.project(this.camera);
    const el = this.renderer.domElement;
    const w = el.clientWidth || el.width;
    const h = el.clientHeight || el.height;
    return {
      x: (v.x * 0.5 + 0.5) * w,
      y: (-v.y * 0.5 + 0.5) * h,
      visible: v.z < 1 && Math.abs(v.x) < 1 && Math.abs(v.y) < 1,
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
    for (const p of this.placed.values()) disposeObject(p.group);
    this.placed.clear();
    for (const g of this.roomGroups.values()) disposeObject(g);
    this.roomGroups.clear();
    this.meshes.dispose();
    disposeMaterialCtx(this.matCtx);
    this.renderer.dispose();
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

function signatureOf(spec: ObjectSpec): string {
  const p = spec.placement;
  const geom = `${p.x}|${p.y}|${p.rot}|${p.wCm}|${p.dCm}|${p.hCm}`;
  if (spec.kind === "mesh") return `mesh|${spec.meshId}|${spec.yawDeg}|${(spec.tintRgb ?? []).join(",")}|${geom}`;
  if (spec.kind === "kitchen") {
    return `kitchen|${spec.level}|${spec.features.join(",")}|${spec.doorMaterialId}|${spec.worktopMaterialId}|${spec.splashbackMaterialId}|${geom}`;
  }
  if (spec.kind === "bathroom") return `bath|${spec.level}|${spec.features.join(",")}|${spec.vanityMaterialId}|${geom}`;
  return `${spec.kind}|${spec.level}|${spec.features.join(",")}|${spec.materialId}|${geom}`;
}
