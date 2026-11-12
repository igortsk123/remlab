import * as THREE from "three";
import { disposeObject } from "./meshes";

// ЗАМЕНА ТОВАРА БЕЗ ПУСТОТЫ (T-20261112-109, владелец TG 1270: «в какой-то момент пустота, пока он меняется»). Раньше
// `syncObjects` убирал старую модель сразу, а новая грузилась секунды — на месте предмета было пусто. Теперь старая
// остаётся «призраком»: полупрозрачная, мягко мерцает, пока грузится новая; новая пришла — призрак гаснет за FADE_MS,
// новая подрастает за APPEAR_MS. Новая не пришла — старая возвращается целиком, без мерцания. Одно правило на все
// замены (Заменить, кружок цвета, отмена/повтор; /demo и туры) — всё идёт через `syncObjects`.

export const GHOST_PERIOD_MS = 1400;
export const FADE_MS = 250;
export const APPEAR_MS = 250;

/** Прозрачность призрака: спокойный пульс 0.35…0.75 (без «колеса»). */
export function ghostOpacity(ms: number): number {
  return 0.55 + 0.2 * Math.sin((2 * Math.PI * ms) / GHOST_PERIOD_MS);
}

/** Масштаб появления новой модели: 0.94 → 1, плавное торможение к концу. */
export function appearScale(ms: number): number {
  const t = Math.min(1, Math.max(0, ms / APPEAR_MS));
  return 0.94 + 0.06 * (1 - (1 - t) ** 3);
}

type Mat = THREE.Material | THREE.Material[];
interface Ghost<P> {
  prev: P;
  group: THREE.Object3D;
  /** Исходные материалы — призрак рисуется копиями, иначе прозрачность уехала бы во все копии модели. */
  orig: Map<THREE.Mesh, Mat>;
  t0: number;
  fadeAt: number | null;
}

/** Призраки заменяемых предметов по слоту и подрастающие новые модели. Рисует ход в `tick` каждого кадра. */
export class SwapGhosts<P extends { group: THREE.Object3D }> {
  private ghosts = new Map<string, Ghost<P>>();
  private growing = new Map<THREE.Object3D, number>();

  constructor(private scene: THREE.Scene) {}

  /** Слот меняет модель: прежний предмет остаётся призраком. Призрак уже есть (быстрые клики) — промежуточный убираем:
   *  на экране остаётся то, что человек видел последним, и никогда — две модели сразу. */
  hold(slotId: string, prev: P, visible: boolean, now: number): void {
    const had = this.ghosts.get(slotId);
    if (!visible || (had && had.fadeAt === null)) { this.discard(prev.group); return; }
    if (had) this.drop(slotId);
    const orig = new Map<THREE.Mesh, Mat>();
    prev.group.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      orig.set(m, m.material);
      const copy = (x: THREE.Material): THREE.Material => {
        const c = x.clone();
        c.transparent = true;
        c.depthWrite = false;
        return c;
      };
      m.material = Array.isArray(m.material) ? m.material.map(copy) : copy(m.material);
    });
    this.ghosts.set(slotId, { prev, group: prev.group, orig, t0: now, fadeAt: null });
  }

  has(slotId: string): boolean {
    return this.ghosts.has(slotId);
  }

  /** Новая модель на месте: призрак гаснет, новая подрастает. */
  release(slotId: string, fresh: THREE.Object3D | null, now: number): void {
    const g = this.ghosts.get(slotId);
    if (g && g.fadeAt === null) g.fadeAt = now;
    if (fresh && g) { fresh.scale.setScalar(appearScale(0)); this.growing.set(fresh, now); }
  }

  /** Новая не пришла: прежний предмет — целиком, со своими материалами, без мерцания. */
  restore(slotId: string): P | null {
    const g = this.ghosts.get(slotId);
    if (!g) return null;
    this.ghosts.delete(slotId);
    this.unclone(g);
    return g.prev;
  }

  /** Слот исчез из расстановки — призрак не нужен. */
  drop(slotId: string): void {
    const g = this.ghosts.get(slotId);
    if (!g) return;
    this.ghosts.delete(slotId);
    this.unclone(g);
    this.discard(g.group);
  }

  tick(now: number): void {
    for (const [slotId, g] of this.ghosts) {
      const k = g.fadeAt === null ? 1 : 1 - (now - g.fadeAt) / FADE_MS;
      if (k <= 0) { this.drop(slotId); continue; }
      const a = ghostOpacity(now - g.t0) * k;
      for (const m of g.orig.keys()) for (const x of Array.isArray(m.material) ? m.material : [m.material]) x.opacity = a;
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

  /** Перед сохранённым кадром: гаснущие призраки — сразу прочь, подрастающие модели — в полный размер. */
  settle(): void {
    for (const [id, g] of [...this.ghosts]) if (g.fadeAt !== null) this.drop(id);
    for (const obj of this.growing.keys()) obj.scale.setScalar(1);
    this.growing.clear();
  }

  disposeAll(): void {
    for (const id of [...this.ghosts.keys()]) this.drop(id);
    this.growing.clear();
  }

  private unclone(g: Ghost<P>): void {
    for (const [m, mat] of g.orig) {
      for (const x of Array.isArray(m.material) ? m.material : [m.material]) x.dispose();
      m.material = mat;
    }
  }

  private discard(obj: THREE.Object3D): void {
    this.scene.remove(obj);
    disposeObject(obj);
    this.growing.delete(obj);
  }
}
