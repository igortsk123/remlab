// Загрузка GLB товаров и посадка их в сцену по паспорту.
//
// ПОРЯДОК ПРЕОБРАЗОВАНИЙ (переносится дословно из рабочей сцены демо и серверного рендера
// `tools/scout/scene_mesh.py:61-83`; каждый шаг — след конкретного дефекта):
//   1) канонический разворот меша: `obj.rotation.y = -yaw` (калибровка orient.json);
//   2) НЕРАВНОМЕРНЫЙ масштаб по трём осям — на ОБЁРТКЕ, не на объекте: матрица обёртки даёт
//      R·S, а не S·R, иначе повёрнутый предмет перекашивает;
//   3) поворот расстановки `rot`;
//   4) посадка по Box3: центр по XZ в точке предмета, низ — на пол.
//
// ЗНАК `rot`: канон (`planner/models.py`, `scene_mesh.py`) — rot ПО ЧАСОВОЙ, 0 → +y, и
// three.js `rotation.y = +rot` даёт ровно это (ry(270°): +Z → −X = запад, как в каноне).
// В отладочном блоке демо (`flat215-demo/index.html:3135`) стоит минус — там же лежит и
// ошибка «угол вместо центра»; канону верим больше, проверено кадром.

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { KTX2Loader } from "three/examples/jsm/loaders/KTX2Loader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

const CM = 0.01;

export interface MeshPlacement {
  xCm: number;
  yCm: number;
  rotDeg: number;
  wCm: number;
  dCm: number;
  hCm: number;
  elevCm?: number;
  yawDeg?: number;
}

export interface MeshLoaderOptions {
  /** Путь к транскодеру Basis для KTX2-текстур (лежит в public/vendor/basis/). */
  ktx2Path?: string;
  renderer?: THREE.WebGLRenderer;
}

export class MeshLibrary {
  private loader: GLTFLoader;
  private cache = new Map<string, Promise<THREE.Object3D>>();
  private ktx2: KTX2Loader | null = null;

  constructor(opts: MeshLoaderOptions = {}) {
    this.loader = new GLTFLoader();
    this.loader.setMeshoptDecoder(MeshoptDecoder);
    if (opts.ktx2Path && opts.renderer) {
      this.ktx2 = new KTX2Loader().setTranscoderPath(opts.ktx2Path).detectSupport(opts.renderer);
      this.loader.setKTX2Loader(this.ktx2);
    }
  }

  /** Загрузка с кэшем по URL: один товар может стоять в комнате несколько раз. */
  load(url: string): Promise<THREE.Object3D> {
    const hit = this.cache.get(url);
    if (hit) return hit;
    const p = new Promise<THREE.Object3D>((resolve, reject) => {
      this.loader.load(
        url,
        (gltf) => resolve(gltf.scene),
        undefined,
        (err) => reject(err instanceof Error ? err : new Error(String(err))),
      );
    });
    this.cache.set(url, p);
    return p;
  }

  dispose(): void {
    this.ktx2?.dispose();
    this.cache.clear();
  }
}

/** Посадка модели: возвращает готовую к добавлению в сцену группу. */
export function placeMesh(source: THREE.Object3D, p: MeshPlacement): THREE.Group {
  const obj = source.clone(true);
  obj.rotation.y = -(((p.yawDeg ?? 0) * Math.PI) / 180);

  const wrap = new THREE.Group();
  wrap.add(obj);
  const bb = new THREE.Box3().setFromObject(wrap);
  const size = new THREE.Vector3();
  bb.getSize(size);
  wrap.scale.set(
    (p.wCm * CM) / Math.max(size.x, 1e-4),
    (p.hCm * CM) / Math.max(size.y, 1e-4),
    (p.dCm * CM) / Math.max(size.z, 1e-4),
  );
  wrap.rotation.y = (p.rotDeg * Math.PI) / 180;
  wrap.updateMatrixWorld(true);

  const bb2 = new THREE.Box3().setFromObject(wrap);
  const centre = new THREE.Vector3();
  bb2.getCenter(centre);
  wrap.position.set(
    p.xCm * CM - centre.x,
    (p.elevCm ?? 0) * CM - bb2.min.y,
    p.yCm * CM - centre.z,
  );
  wrap.traverse((o) => {
    if ((o as THREE.Mesh).isMesh) {
      o.castShadow = true;
      o.receiveShadow = true;
    }
  });
  return wrap;
}

/** Заглушка, когда модель ещё грузится или не пришла: та же коробка, что в демо. */
export function stubBox(p: MeshPlacement, loading: boolean): THREE.Group {
  const g = new THREE.Group();
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(p.wCm * CM, p.hCm * CM, p.dCm * CM),
    new THREE.MeshStandardMaterial({
      color: loading ? 0xc9ccd2 : 0xb9bcc4,
      transparent: true,
      opacity: loading ? 0.35 : 0.55,
      roughness: 0.9,
    }),
  );
  mesh.position.set(0, (p.hCm / 2) * CM, 0);
  g.add(mesh);
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({ color: 0x8a8f99 }),
  );
  edges.position.copy(mesh.position);
  g.add(edges);
  g.position.set(p.xCm * CM, (p.elevCm ?? 0) * CM, p.yCm * CM);
  g.rotation.y = (p.rotDeg * Math.PI) / 180;
  return g;
}

/** Освобождение геометрии/материалов поддерева — иначе вкладка течёт при смене вариантов. */
export function disposeObject(obj: THREE.Object3D): void {
  obj.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    m.geometry?.dispose();
    const mat = m.material;
    if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
    else mat?.dispose();
  });
}
