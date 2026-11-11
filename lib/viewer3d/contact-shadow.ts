import * as THREE from "three";
import { HorizontalBlurShader } from "three/examples/jsm/shaders/HorizontalBlurShader.js";
import { VerticalBlurShader } from "three/examples/jsm/shaders/VerticalBlurShader.js";

/**
 * ЗАПЕЧЁННАЯ ТЕНЬ ОТ МЕБЕЛИ НА ПОЛУ (T-20261111-22, владелец TG 1604 «красиво, как на фото»; совет Codex — сначала контактные
 * тени). Приём three `webgl_shadow_contact`: камера снизу вверх видит только мебель в слое 0…1 м от пола, глубина → чёрное с
 * прозрачностью, два прохода размытия, картинка ложится на пол прозрачной плоскостью. Рисуется ОДИН РАЗ на расстановку в простое
 * браузера (а не каждый кадр, как в примере three): цена кадра — одна прозрачная плоскость, первый кадр запекания не ждёт.
 * Замер прототипа (`tools/design/mock/light3d/`): на процессоре 370–780 мс первое запекание (сборка шейдеров), дальше единицы мс.
 */

/** Что запеканию нужно от рендерера (в тестах — подделка без WebGL). */
export type BakeRenderer = Pick<THREE.WebGLRenderer, "getRenderTarget" | "setRenderTarget" | "getClearAlpha" | "setClearAlpha" | "clear" | "render"> & {
  shadowMap: { autoUpdate: boolean };
};

/** Прямоугольник квартиры на плане, см. */
export interface BoundsCm { x0: number; y0: number; x1: number; y1: number }

export interface ContactShadowOptions {
  /** Сторона картинки тени, пикселей (компьютер 512, телефон 256). */
  res: number;
  opacity?: number;
  /** Насколько тёмная тень у самого пола. */
  darkness?: number;
  /** Размытие, пикселей картинки 256. */
  blur?: number;
  /** Выше этого (м) предмет тени на пол почти не даёт. */
  heightM?: number;
}

/** Отложить работу на простой; возвращает отмену. */
export type IdleScheduler = (cb: () => void) => () => void;

const CM = 0.01;
/** Плоскость тени — над ворсом ковра (до 3 см, `kits/bedroom.ts:buildRug`): тень ложится и на ковёр. */
const LIFT_M = 0.032;

const idleDefault: IdleScheduler = (cb) => {
  const g = globalThis as { requestIdleCallback?: (f: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (id: number) => void };
  if (g.requestIdleCallback) {
    const id = g.requestIdleCallback(cb, { timeout: 400 });
    return () => g.cancelIdleCallback?.(id);
  }
  const t = setTimeout(cb, 0);
  return () => clearTimeout(t);
};

export class ContactShadow {
  readonly plane: THREE.Mesh;
  /** Сколько раз запекли и сколько заняло последнее (мс) — для замеров. */
  bakes = 0;
  lastMs = 0;
  private readonly rt: THREE.WebGLRenderTarget;
  private readonly rtBlur: THREE.WebGLRenderTarget;
  private readonly blurMesh: THREE.Mesh;
  private readonly cam: THREE.OrthographicCamera;
  private readonly depthMat: THREE.MeshDepthMaterial;
  private readonly hBlur: THREE.ShaderMaterial;
  private readonly vBlur: THREE.ShaderMaterial;
  private readonly blurPx: number;
  private cancel: (() => void) | null = null;
  private disposed = false;

  constructor(private readonly renderer: BakeRenderer, private readonly scene: THREE.Scene, b: BoundsCm, opts: ContactShadowOptions,
    private readonly idle: IdleScheduler = idleDefault) {
    const w = Math.max(0.1, (b.x1 - b.x0) * CM), d = Math.max(0.1, (b.y1 - b.y0) * CM);
    const cx = ((b.x0 + b.x1) / 2) * CM, cz = ((b.y0 + b.y1) / 2) * CM, h = opts.heightM ?? 1.0;
    const rw = Math.max(16, Math.round(opts.res * Math.min(1, w / d))), rh = Math.max(16, Math.round(opts.res * Math.min(1, d / w)));
    this.rt = new THREE.WebGLRenderTarget(rw, rh);
    this.rtBlur = new THREE.WebGLRenderTarget(rw, rh);
    this.rt.texture.generateMipmaps = false;
    this.rtBlur.texture.generateMipmaps = false;
    this.blurPx = opts.blur ?? 3;
    const geo = new THREE.PlaneGeometry(w, d).rotateX(Math.PI / 2);
    const mat = new THREE.MeshBasicMaterial({ map: this.rt.texture, transparent: true, depthWrite: false, opacity: opts.opacity ?? 0.8, toneMapped: false });
    this.plane = new THREE.Mesh(geo, mat);
    this.plane.name = "contact-shadow";
    this.plane.scale.y = -1;
    this.plane.renderOrder = 1;
    this.plane.position.set(cx, LIFT_M, cz);
    this.plane.visible = false;                         // до первого запекания — пустая картинка не рисуется
    this.plane.raycast = () => undefined;               // не мешает выбору предметов и шагу по полу
    this.blurMesh = new THREE.Mesh(geo);                // вне сцены: рисуется только в проходах размытия
    this.blurMesh.position.set(cx, h / 2, cz);          // внутри объёма камеры тени (у пола его отсекает near)
    this.cam = new THREE.OrthographicCamera(-w / 2, w / 2, d / 2, -d / 2, 0.004, h);
    this.cam.rotation.x = Math.PI / 2;
    this.cam.position.set(cx, 0, cz);
    this.cam.updateMatrixWorld(true);
    // спад по высоте ЛИНЕЙНЫЙ, слой 1 м (как в примере three; снимки T-22/2): с квадратом и слоем 55–60 см тень давали только
    // части у самого пола, а они скрыты под предметом — стулья и журнальный столик «висели», когда солнце бросает их тень
    // за них, на стену; так сиденье и столешница дают мягкое пятно под собой
    const darkness = { value: opts.darkness ?? 1.3 };
    // обе стороны и проверка глубины: у многих моделей низ открыт (тумба-опора журнального столика) — камера снизу видела только
    // столешницу, и тень выходила кольцом, а у опоры на полу её не было; с глубиной побеждает ближняя к полу поверхность, а не
    // последняя нарисованная (снимки T-22/2)
    this.depthMat = new THREE.MeshDepthMaterial({ side: THREE.DoubleSide });
    this.depthMat.onBeforeCompile = (sh) => {
      sh.uniforms.darkness = darkness;
      sh.fragmentShader = "uniform float darkness;\n" + sh.fragmentShader.replace(
        "gl_FragColor = vec4( vec3( 1.0 - fragCoordZ ), opacity );",
        "gl_FragColor = vec4( vec3( 0.0 ), clamp( ( 1.0 - fragCoordZ ) * darkness, 0.0, 1.0 ) );");
    };
    // свои копии форм шейдера: общий объект из three делили бы все сцены страницы
    this.hBlur = new THREE.ShaderMaterial({ ...HorizontalBlurShader, uniforms: THREE.UniformsUtils.clone(HorizontalBlurShader.uniforms), depthTest: false });
    this.vBlur = new THREE.ShaderMaterial({ ...VerticalBlurShader, uniforms: THREE.UniformsUtils.clone(VerticalBlurShader.uniforms), depthTest: false });
    scene.add(this.plane);
  }

  /** Запечь в простое; повторный вызов до запекания заменяет прежний (быстрые правки — одно запекание). */
  schedule(casters: () => THREE.Object3D[]): void {
    if (this.disposed) return;
    this.cancel?.();
    this.cancel = this.idle(() => {
      this.cancel = null;
      if (!this.disposed) this.bake(casters());
    });
  }

  /** Запечь сейчас. `casters` — группы мебели прямо в сцене; всё остальное (стены, пол, ковры, след переноса) тени не даёт. */
  bake(casters: THREE.Object3D[]): void {
    if (this.disposed) return;
    const t0 = performance.now();
    const r = this.renderer, s = this.scene;
    const keep = new Set(casters), hidden: THREE.Object3D[] = [];
    for (const o of s.children) if (o.visible && !keep.has(o)) { hidden.push(o); o.visible = false; }
    const bg = s.background, prevTarget = r.getRenderTarget(), alpha = r.getClearAlpha(), autoShadow = r.shadowMap.autoUpdate;
    try {
      s.background = null;
      s.overrideMaterial = this.depthMat;
      r.shadowMap.autoUpdate = false;                   // карту теней солнца ради запекания не пересчитываем
      r.setClearAlpha(0);
      r.setRenderTarget(this.rt);
      r.clear();
      r.render(s, this.cam);
    } finally {
      s.overrideMaterial = null;
      for (const o of hidden) o.visible = true;
    }
    this.blur(this.blurPx);
    this.blur(this.blurPx * 0.5);
    r.setRenderTarget(prevTarget);
    r.setClearAlpha(alpha);
    s.background = bg;
    r.shadowMap.autoUpdate = autoShadow;
    this.plane.visible = true;
    this.bakes += 1;
    this.lastMs = performance.now() - t0;
  }

  private blur(px: number): void {
    const r = this.renderer;
    this.blurMesh.material = this.hBlur;
    this.hBlur.uniforms.tDiffuse!.value = this.rt.texture;
    this.hBlur.uniforms.h!.value = px / 256;
    r.setRenderTarget(this.rtBlur);
    r.render(this.blurMesh, this.cam);
    this.blurMesh.material = this.vBlur;
    this.vBlur.uniforms.tDiffuse!.value = this.rtBlur.texture;
    this.vBlur.uniforms.v!.value = px / 256;
    r.setRenderTarget(this.rt);
    r.render(this.blurMesh, this.cam);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.cancel?.();
    this.cancel = null;
    this.scene.remove(this.plane);
    this.plane.geometry.dispose();                      // общая с плоскостью размытия
    (this.plane.material as THREE.Material).dispose();
    this.depthMat.dispose();
    this.hBlur.dispose();
    this.vBlur.dispose();
    this.rt.dispose();
    this.rtBlur.dispose();
  }
}

/** Прямоугольник всех комнат квартиры, см. */
export function roomsBounds(rooms: readonly { x: number; y: number; w: number; d: number }[]): BoundsCm | null {
  if (!rooms.length) return null;
  return {
    x0: Math.min(...rooms.map((r) => r.x)), y0: Math.min(...rooms.map((r) => r.y)),
    x1: Math.max(...rooms.map((r) => r.x + r.w)), y1: Math.max(...rooms.map((r) => r.y + r.d)),
  };
}
