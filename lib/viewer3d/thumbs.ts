// МИНИАТЮРЫ ПРЕДМЕТОВ ИЗ СЦЕНЫ (T-20261109-35/2, тур пробы): в туре нет фото товаров (ссылки и картинки магазинов вычищены,
// `trial_bundle.py:assert_public`), а строка списка в /demo — с картинкой слева. Картинка — НАША 3D-модель предмета из уже
// загруженной сцены: копия группы предмета (геометрия и материалы общие, на видеокарту ничего не грузится заново) на белом фоне,
// своя маленькая камера в три четверти спереди. Все миниатюры — одним листом за одну смену размера холста (как `frameBlob`):
// отрисовали → копия в 2D-холст в той же задаче → размер холста возвращает вызывающий.
import * as THREE from "three";

/** Объектив миниатюры: узкий — меньше перспективных искажений, предмет читается «как на фото товара». */
export const THUMB_FOV = 26;
/** Ракурс: три четверти справа (градусы от фронта) и немного сверху. */
const AZ_DEG = 30;
const EL_DEG = 16;

/**
 * Откуда смотреть на предмет: фронт модели в осях группы — +z (поворот расстановки 0 → лицо к +y плана = +z сцены, `transform.ts`).
 * Расстояние — чтобы описанная сфера коробки целиком вошла в квадратный кадр с полем ~6 %.
 */
export function thumbView(box: THREE.Box3, fovDeg = THUMB_FOV): { eye: THREE.Vector3; target: THREE.Vector3; near: number; far: number } {
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const r = Math.max(sphere.radius, 1e-3);
  const dist = (r / Math.sin(((fovDeg / 2) * Math.PI) / 180)) * 1.06;
  const az = (AZ_DEG * Math.PI) / 180, el = (EL_DEG * Math.PI) / 180;
  const dir = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el));
  return { eye: sphere.center.clone().addScaledVector(dir, dist), target: sphere.center.clone(), near: Math.max(dist - r * 1.5, 1e-3), far: dist + r * 1.5 };
}

/** Свет миниатюры — тот же характер, что в комнате (`viewer.addLights`), без теней. */
function thumbScene(env: THREE.Texture | null, envIntensity: number): THREE.Scene {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);
  scene.environment = env;
  scene.environmentIntensity = envIntensity;
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb6b0a6, 1.05));
  const key = new THREE.DirectionalLight(0xfff3e2, 1.15);
  key.position.set(-2, 4, 3);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xdfe7ee, 0.4);
  fill.position.set(3, 2, 4);
  scene.add(fill);
  return scene;
}

/**
 * Лист миниатюр `size`×`size` (px) в холсте рендерера: модель → data URL (JPEG), нет модели — null. Размер холста и вид экрана
 * вызывающий возвращает сам (`viewer.thumbs`), здесь — только отрисовка и копия, пока буфер WebGL цел.
 */
export function renderThumbs(renderer: THREE.WebGLRenderer, models: (THREE.Object3D | null)[], size: number,
  env: THREE.Texture | null, envIntensity: number): (string | null)[] {
  const n = models.length;
  const sheet = document.createElement("canvas");
  sheet.width = size * n;
  sheet.height = size;
  const ctx = sheet.getContext("2d");
  if (!ctx || !n) return models.map(() => null);
  const scene = thumbScene(env, envIntensity);
  const cam = new THREE.PerspectiveCamera(THUMB_FOV, 1, 0.01, 100);
  const drawn = models.map(() => false);
  renderer.setPixelRatio(1);
  renderer.setSize(size * n, size, false);
  renderer.setScissorTest(true);
  try {
    models.forEach((m, k) => {
      if (!m) return;
      const c = m.clone(true);
      c.position.set(0, 0, 0);
      c.rotation.set(0, 0, 0);
      c.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(c);
      if (box.isEmpty()) return;
      const v = thumbView(box);
      cam.position.copy(v.eye);
      cam.near = v.near;
      cam.far = v.far;
      cam.lookAt(v.target);
      cam.updateProjectionMatrix();
      renderer.setViewport(k * size, 0, size, size);
      renderer.setScissor(k * size, 0, size, size);
      scene.add(c);
      try { renderer.render(scene, cam); } finally { scene.remove(c); }
      drawn[k] = true;
    });
    ctx.drawImage(renderer.domElement, 0, 0);   // та же задача, что и отрисовка: буфер ещё цел
  } finally {
    renderer.setScissorTest(false);
  }
  const one = document.createElement("canvas");
  one.width = size;
  one.height = size;
  const c1 = one.getContext("2d");
  return drawn.map((ok, k) => {
    if (!ok || !c1) return null;
    c1.clearRect(0, 0, size, size);
    c1.drawImage(sheet, k * size, 0, size, size, 0, 0, size, size);
    return one.toDataURL("image/jpeg", 0.88);
  });
}
