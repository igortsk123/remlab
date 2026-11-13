import * as THREE from "three";
import type { Placement } from "@/contracts/apartment";
import { disposeObject } from "./meshes";

// ЗАМЕНА ТОВАРА БЕЗ ПУСТОТЫ (T-20261112-109, владелец TG 1270: «в какой-то момент пустота, пока он меняется»). Раньше
// `syncObjects` убирал старую модель сразу, а новая грузилась секунды — на месте предмета было пусто. Теперь прежний предмет
// остаётся на месте, пока грузится новый; новая пришла — прежний гаснет за FADE_MS, новая подрастает за APPEAR_MS. Новая не пришла
// — прежний возвращается целиком. Одно правило на все замены (Заменить, кружок цвета, отмена/повтор, смена стиля/набора; /demo и
// туры) — всё идёт через `syncObjects`.
//
// СВЕТЛЫЙ СИЛУЭТ, А НЕ ПОЛУПРОЗРАЧНЫЙ ПРИЗРАК (T-20261113-19, владелец TG 1566–1567: «5 секунд ждёт, страшно, так черно выглядит»).
// Полупрозрачный прежний диван показывал сквозь себя стену, тёмный низ модели и запечённую тень на полу — читалось как поломка.
// Теперь прежний предмет — НЕПРОЗРАЧНЫЙ светлый силуэт своей формы, мягко «дышит» светом (без мигания) — «обновляется, ждём».
// Тень под ним пересчитывает `viewer` сразу (силуэт тени не даёт); тень новой — вместе с готовой моделью. Вещи, стоящие НА
// заменяемой (подушки, плед, лампа на комоде — `standsOn`), ждут её и появляются вместе (`follow` → `lead`).
// Цвет силуэта — НЕ мебельный (директор T-19/2: белый читался как настоящий белый диван / «молочная» кровать из списка): тон
// заглушки, которого нет у товаров, + сверху вниз бежит светлая полоса — с первого взгляда «грузится».

export const GHOST_PERIOD_MS = 1200;
export const FADE_MS = 250;
export const APPEAR_MS = 250;
/** Цвет силуэта — холодный серо-голубой: выбивается из тёплых комнат демо, читается
 *  «технической» заглушкой. Вариант «разбелённая терракота» (#dcae98, T-19/2) читался как персиковый велюр. */
export const SILHOUETTE_RGB = 0xb4c4d8;

/** Свечение силуэта: «дыхание» светлее↔темнее 0.15…0.75 за GHOST_PERIOD_MS, плавно (синус, без вспышек), без прозрачности. */
export function ghostGlow(ms: number): number {
  return 0.45 + 0.3 * Math.sin((2 * Math.PI * ms) / GHOST_PERIOD_MS);
}

/** Бегущий блик: доля пути полосы сверху вниз 0…1 за GHOST_PERIOD_MS. */
export function sweepPhase(ms: number): number {
  const t = ms / GHOST_PERIOD_MS;
  return t - Math.floor(t);
}

/** Блик по высоте предмета: полоса светлее идёт сверху вниз (мир. Y между верхом и низом предмета). Только шейдер — модель не трогаем. */
function addSweep(mat: THREE.MeshStandardMaterial, u: SweepUniforms): void {
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uSweep = u.uSweep;
    sh.uniforms.uY0 = u.uY0;
    sh.uniforms.uY1 = u.uY1;
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying float vSwY;")
      .replace("#include <project_vertex>", "#include <project_vertex>\nvSwY = (modelMatrix * vec4(transformed, 1.0)).y;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying float vSwY;\nuniform float uSweep;\nuniform float uY0;\nuniform float uY1;")
      .replace(
        "#include <emissivemap_fragment>",
        "#include <emissivemap_fragment>\nfloat swT = (uY1 - vSwY) / max(uY1 - uY0, 1e-3);\n" +
          "float swB = 1.0 - smoothstep(0.0, 0.22, abs(swT - (uSweep * 1.5 - 0.25)));\ntotalEmissiveRadiance += vec3(0.45 * swB);",
      );
  };
  mat.customProgramCacheKey = () => "swap-sweep";
}
interface SweepUniforms { uSweep: { value: number }; uY0: { value: number }; uY1: { value: number } }

/** Масштаб появления новой модели: 0.94 → 1, плавное торможение к концу. */
export function appearScale(ms: number): number {
  const t = Math.min(1, Math.max(0, ms / APPEAR_MS));
  return 0.94 + 0.06 * (1 - (1 - t) ** 3);
}

/** Запас по высоте, см: вещь, лежащая на верху носителя (лампа на комоде), — его вещь. */
const ON_TOP_CM = 2;

/** Стоит ли вещь `dep` НА носителе `car`: поднята над полом, не выше его верха и центром над его следом (с поворотом).
 *  Картина над диваном выше его верха — не его; подушки на сиденье, плед на подлокотнике, лампа на комоде, ТВ на тумбе — его. */
export function standsOn(dep: Placement, car: Placement): boolean {
  const lift = dep.elevCm ?? 0;
  if (lift <= 0 || lift > (car.elevCm ?? 0) + car.hCm + ON_TOP_CM) return false;
  const a = (-(car.rot ?? 0) * Math.PI) / 180;
  const dx = dep.x - car.x;
  const dy = dep.y - car.y;
  const lx = dx * Math.cos(a) - dy * Math.sin(a);
  const ly = dx * Math.sin(a) + dy * Math.cos(a);
  return Math.abs(lx) <= car.wCm / 2 && Math.abs(ly) <= car.dCm / 2;
}

type Mat = THREE.Material | THREE.Material[];
interface Ghost<P> {
  prev: P;
  group: THREE.Object3D;
  /** Исходные материалы — силуэт рисуется своим материалом, общий материал модели не трогаем. */
  orig: Map<THREE.Mesh, Mat>;
  /** Один материал силуэта на весь предмет. */
  mat: THREE.MeshStandardMaterial;
  /** Бегущий блик: фаза и высота предмета (низ/верх в мире). */
  sweep: SweepUniforms;
  t0: number;
  fadeAt: number | null;
}

/** Силуэты заменяемых предметов по слоту, подрастающие новые модели и вещи, ждущие свой носитель. Ход рисует `tick` каждого кадра. */
export class SwapGhosts<P extends { group: THREE.Object3D }> {
  private ghosts = new Map<string, Ghost<P>>();
  private growing = new Map<THREE.Object3D, number>();
  /** Носитель (слот), чья модель грузится, → вещи на нём, спрятанные до её прихода. */
  private followers = new Map<string, Set<THREE.Object3D>>();

  constructor(private scene: THREE.Scene) {}

  /** Слот меняет модель: прежний предмет остаётся светлым силуэтом. Силуэт уже есть (быстрые клики) — промежуточный убираем:
   *  на экране остаётся то, что человек видел последним, и никогда — две модели сразу. */
  hold(slotId: string, prev: P, visible: boolean, now: number): void {
    const had = this.ghosts.get(slotId);
    // спрятанная вещь (ждала носитель и сама не показывалась) силуэтом не становится — её никто не видел
    if (!visible || !prev.group.visible || (had && had.fadeAt === null)) { this.discard(prev.group); return; }
    if (had) this.drop(slotId);
    const mat = new THREE.MeshStandardMaterial({ color: SILHOUETTE_RGB, emissive: SILHOUETTE_RGB, emissiveIntensity: ghostGlow(0), roughness: 1, metalness: 0 });
    const box = new THREE.Box3().setFromObject(prev.group);
    const sweep: SweepUniforms = { uSweep: { value: 0 }, uY0: { value: box.isEmpty() ? 0 : box.min.y }, uY1: { value: box.isEmpty() ? 1 : box.max.y } };
    addSweep(mat, sweep);
    const orig = new Map<THREE.Mesh, Mat>();
    prev.group.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      orig.set(m, m.material);
      m.material = mat;
    });
    this.ghosts.set(slotId, { prev, group: prev.group, orig, mat, sweep, t0: now, fadeAt: null });
  }

  has(slotId: string): boolean {
    return this.ghosts.has(slotId);
  }

  /** Новая модель на месте: силуэт гаснет, новая подрастает. */
  release(slotId: string, fresh: THREE.Object3D | null, now: number): void {
    const g = this.ghosts.get(slotId);
    if (g && g.fadeAt === null) {
      g.fadeAt = now;
      g.mat.transparent = true;   // гаснуть — единственный момент, когда силуэт прозрачен (поверх подрастающей новой)
      g.mat.needsUpdate = true;
    }
    if (fresh && g) this.grow(fresh, now);
  }

  /** Новая не пришла: прежний предмет — целиком, со своими материалами, без свечения. */
  restore(slotId: string): P | null {
    const g = this.ghosts.get(slotId);
    if (!g) return null;
    this.ghosts.delete(slotId);
    this.unclone(g);
    return g.prev;
  }

  /** Слот исчез из расстановки — силуэт не нужен. */
  drop(slotId: string): void {
    const g = this.ghosts.get(slotId);
    if (!g) return;
    this.ghosts.delete(slotId);
    this.unclone(g);
    this.discard(g.group);
  }

  /** Модель носителя `carrier` начала грузиться: вещи на нём (`follow`) ждут её. */
  expect(carrier: string): void {
    if (!this.followers.has(carrier)) this.followers.set(carrier, new Set());
  }

  /** Вещь стоит на грузящемся носителе — прячем до его прихода. Носитель не грузится — ничего не делаем (false). */
  follow(carrier: string, obj: THREE.Object3D): boolean {
    const set = this.followers.get(carrier);
    if (!set) return false;
    obj.visible = false;
    set.add(obj);
    return true;
  }

  /** Носитель пришёл (`grow` — подрастают вместе с ним) или не пришёл (прежний на месте) — его вещи показываем. */
  lead(carrier: string, now: number, grow = true): void {
    const set = this.followers.get(carrier);
    if (!set) return;
    this.followers.delete(carrier);
    for (const obj of set) {
      obj.visible = true;
      if (grow) this.grow(obj, now);
    }
  }

  /** Носители, чья загрузка больше не идёт (новая расстановка их не грузит), — их вещи показываем сразу, без ожидания. */
  leadAllExcept(keep: ReadonlySet<string>, now: number): void {
    for (const carrier of [...this.followers.keys()]) if (!keep.has(carrier)) this.lead(carrier, now, false);
  }

  tick(now: number): void {
    for (const [slotId, g] of this.ghosts) {
      const k = g.fadeAt === null ? 1 : 1 - (now - g.fadeAt) / FADE_MS;
      if (k <= 0) { this.drop(slotId); continue; }
      g.mat.emissiveIntensity = ghostGlow(now - g.t0);
      g.sweep.uSweep.value = sweepPhase(now - g.t0);
      if (g.fadeAt !== null) g.mat.opacity = k;
    }
    for (const [obj, t0] of this.growing) {
      obj.scale.setScalar(appearScale(now - t0));
      if (now - t0 >= APPEAR_MS) { obj.scale.setScalar(1); this.growing.delete(obj); }
    }
  }

  /** Расчёт по ПОЛНОМУ размеру подрастающей модели (рамка выделения не должна остаться на 6 % меньше предмета). */
  atFullSize<T>(obj: THREE.Object3D, fn: () => T): T {
    if (!this.growing.has(obj)) return fn();
    const k = obj.scale.x;
    obj.scale.setScalar(1);
    try { return fn(); } finally { obj.scale.setScalar(k); obj.updateMatrixWorld(true); }
  }

  /** Перед сохранённым кадром: гаснущие силуэты — сразу прочь, подрастающие модели — в полный размер. */
  settle(): void {
    for (const [id, g] of [...this.ghosts]) if (g.fadeAt !== null) this.drop(id);
    for (const obj of this.growing.keys()) obj.scale.setScalar(1);
    this.growing.clear();
  }

  disposeAll(): void {
    for (const id of [...this.ghosts.keys()]) this.drop(id);
    this.growing.clear();
    for (const set of this.followers.values()) for (const obj of set) obj.visible = true;
    this.followers.clear();
  }

  private grow(obj: THREE.Object3D, now: number): void {
    obj.scale.setScalar(appearScale(0));
    this.growing.set(obj, now);
  }

  private unclone(g: Ghost<P>): void {
    for (const [m, mat] of g.orig) m.material = mat;
    g.mat.dispose();
  }

  private discard(obj: THREE.Object3D): void {
    this.scene.remove(obj);
    disposeObject(obj);
    this.growing.delete(obj);
  }
}
