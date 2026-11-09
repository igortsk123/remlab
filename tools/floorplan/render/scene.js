// Серое 3D из model-<plan>-<i>.json (T-20261109-02): полосы стен по высоте (подоконник/проём/перемычка) выдавливаются,
// пол — многоугольники комнат. Координаты модели: метры, x вправо, y вниз по листу → в сцене X = x, Z = y, Y — вверх.
import * as THREE from "/three/three.module.js";

const W = 1200, H = 900;
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setSize(W, H);
renderer.setPixelRatio(1);
renderer.shadowMap.enabled = true;
document.body.appendChild(renderer.domElement);

const wallMat = new THREE.MeshStandardMaterial({ color: 0x9a9a9a, roughness: 0.9 });
const floorMat = new THREE.MeshStandardMaterial({ color: 0xc8c8c8, roughness: 1.0, side: THREE.DoubleSide });
const edgeMat = new THREE.LineBasicMaterial({ color: 0x555555 });

function shapeOf(poly) {
  const s = new THREE.Shape(poly.outer.map(([x, y]) => new THREE.Vector2(x, -y)));
  for (const h of poly.holes || []) s.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, -y))));
  return s;
}

function build(model, shadows = true) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a8a, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.castShadow = shadows;
  sun.shadow.mapSize.set(2048, 2048);
  scene.add(sun);
  const box = new THREE.Box3();
  for (const band of model.bands) {
    for (const p of band.polys) {
      if (p.outer.length < 3) continue;
      const g = new THREE.ExtrudeGeometry(shapeOf(p), { depth: band.z1 - band.z0, bevelEnabled: false });
      g.rotateX(-Math.PI / 2);
      g.translate(0, band.z0, 0);
      const m = new THREE.Mesh(g, wallMat);
      m.castShadow = m.receiveShadow = true;
      scene.add(m);
      scene.add(new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), edgeMat));
      g.computeBoundingBox();
      box.union(g.boundingBox);
    }
  }
  for (const p of model.floors) {
    if (p.outer.length < 3) continue;
    const g = new THREE.ShapeGeometry(shapeOf(p));
    g.rotateX(-Math.PI / 2);
    g.translate(0, 0.005, 0);
    const m = new THREE.Mesh(g, floorMat);
    m.receiveShadow = true;
    scene.add(m);
  }
  const c = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  sun.position.set(c.x - size.x * 0.4, 12, c.z + size.z * 0.9);
  sun.target.position.copy(c);
  scene.add(sun.target);
  const R = Math.max(size.x, size.z);
  Object.assign(sun.shadow.camera, { left: -R, right: R, top: R, bottom: -R, near: 0.1, far: 60 });
  sun.shadow.camera.updateProjectionMatrix();
  return { scene, c, size };
}

function polyArea(pts) {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a / 2);
}

function inside(pts, x, y) {
  let r = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) r = !r;
  }
  return r;
}

window.renderView = (model, view) => {
  const { scene, c, size } = build(model, view !== "top");
  const aspect = W / H;
  let cam;
  if (view === "top") {
    // почти ортогонально сверху: малый угол обзора, далеко — пропорции как на листе
    cam = new THREE.PerspectiveCamera(8, aspect, 1, 2000);
    const fit = Math.max(size.x / aspect, size.z) * 1.08;
    const dist = fit / 2 / Math.tan((8 * Math.PI) / 360);
    cam.position.set(c.x, dist, c.z + 0.001);
    cam.up.set(0, 0, -1);
    cam.lookAt(c.x, 0, c.z);
  } else if (view === "oblique") {
    cam = new THREE.PerspectiveCamera(35, aspect, 0.1, 500);
    const R = Math.max(size.x / aspect, size.z) * 1.25;
    const d = R / Math.tan((35 * Math.PI) / 360);
    cam.position.set(c.x - d * 0.25, d * 0.75, c.z + d * 0.62);
    cam.lookAt(c.x, 0.4, c.z);
  } else {
    // вид изнутри самой большой комнаты: из дальнего угла на центр, высота глаз 1,5 м
    let best = null;
    for (const f of model.floors) if (!best || polyArea(f.outer) > polyArea(best.outer)) best = f;
    const pts = best.outer;
    const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
    let far = pts[0], fd = -1;
    for (const p of pts) { const d = (p[0] - cx) ** 2 + (p[1] - cy) ** 2; if (d > fd) { fd = d; far = p; } }
    let ex = cx + (far[0] - cx) * 0.8, ey = cy + (far[1] - cy) * 0.8;
    for (let k = 0.8; k > 0.1 && !inside(pts, ex, ey); k -= 0.1) { ex = cx + (far[0] - cx) * k; ey = cy + (far[1] - cy) * k; }
    cam = new THREE.PerspectiveCamera(75, aspect, 0.05, 200);
    cam.position.set(ex, 1.5, ey);
    cam.lookAt(cx - (far[0] - cx) * 0.5, 1.2, cy - (far[1] - cy) * 0.5);
    scene.add(new THREE.PointLight(0xffffff, 2, 0, 1.5).translateX(cx).translateY(2.4).translateZ(cy));
  }
  renderer.render(scene, cam);
  return renderer.domElement.toDataURL("image/png");
};
window.ready = true;
