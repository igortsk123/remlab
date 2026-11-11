/* eslint-disable react/display-name -- вставка в страницу через Playwright, не компоненты React */
/* ПРОТОТИП СВЕТА 3D-ВИДА (T-20261111-22, владелец TG 1604 «красиво, как на фото»). НЕ ДЛЯ ПРОДА: вставка в страницу демо через
   Playwright (`shoot.cjs`), движок — сборка `build.mjs` с точкой входа `globalThis.__light3d(viewer)` сразу после `addLights()`.
   Варианты (`window.__L3D.variant`):
     v0 — как сейчас (ничего не меняем, только отдаём сцену для замеров);
     v1 — «свет»: калибровка ИМЕЮЩИХСЯ источников (небо/солнце/заполняющий/окружение, без новых): солнце — за окном, тёплый отскок
          от пола, мягче и светлее тени, экспозиция. Цена кадра = 0;
     v2 — v1 + «пятна» контактной тени: плоскость по следу каждого предмета с ОДНОЙ общей градиентной текстурой (совет Codex 11.11);
     v3 — v1 + запечённые контактные тени по силуэту (рендер сверху один раз на расстановку, размытие) + шторы у окна;
     v4 — v3 + мягкий источник в проёме окна (RectAreaLight, только компьютер) + GTAO постобработкой на каждый кадр — дорогой, для цены.
   Поправку цвета на модель владелец 11.11 (TG 1614) отложил отдельным планом — здесь её нет; замер цвета показывает, что даёт один свет.
   Замеры: `__L3D_measure()` — кадр, маска предметов (уникальный цвет на предмет) и альбедо (без света) для сравнения с фото товара. */
(function () {
  const CFG = (window.__L3D = window.__L3D || { variant: "v0" });
  const STAT = (window.__L3D_STAT = { bakeMs: [], hookMs: 0, syncs: 0, composer: false });
  const V = () => CFG.variant || "v0";
  const on = (...vs) => vs.includes(V());

  window.__light3d = function (viewer) {
    window.__L3D_VIEWER = viewer;
    const T = window.RemlabScene && window.RemlabScene.L3D;
    if (!T) { console.warn("L3D: нет классов three в бандле"); return; }
    const t0 = performance.now();
    if (V() !== "v0") relight(viewer, T);
    const sync = viewer.syncObjects.bind(viewer);
    viewer.syncObjects = async (sc) => {
      await sync(sc);
      STAT.syncs++;
      if (V() !== "v0") aimSun(viewer, T);
      if (on("v2")) blobs(viewer, T);
      if (on("v3", "v4")) {
        curtains(viewer, T);
        // запекание — в простое ПОСЛЕ готовой сцены: первый кадр не ждёт компиляции шейдеров тени (на телефоне это сотни мс)
        const job = viewer.__l3dJob = (viewer.__l3dJob || 0) + 1;
        (window.requestIdleCallback || setTimeout)(() => { if (job === viewer.__l3dJob && !viewer.disposed) bakeContact(viewer, T); }, { timeout: 400 });
      }
    };
    if (on("v4")) composer(viewer, T);
    STAT.hookMs = performance.now() - t0;
  };

  // ── геометрия комнаты ─────────────────────────────────────────────────────────────────────────────────────────────────────
  const CM = 0.01;
  function roomsOf(viewer) { return (viewer.apartment && viewer.apartment.rooms) || []; }
  function bounds(viewer) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, h = 260;
    for (const r of roomsOf(viewer)) { x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y); x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.d); h = r.heightCm || h; }
    return { x0, y0, x1, y1, h, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
  }
  /** Окна в метрах сцены: центр проёма на плоскости стены, нормаль внутрь комнаты, ширина/низ/верх. offset — от room.x (юг/север) или room.y (запад/восток). */
  function windows(viewer) {
    const out = [];
    for (const r of roomsOf(viewer)) for (const o of r.openings || []) {
      if (o.kind !== "window" && o.kind !== "balcony") continue;
      const off = (o.offsetCm || 0) + (o.widthCm || 0) / 2, sill = o.sillCm ?? (o.kind === "balcony" ? 0 : 85), top = sill + (o.heightCm || 150);
      let px, pz, nx, nz;
      if (o.wall === "south") { px = r.x + off; pz = r.y; nx = 0; nz = 1; }
      else if (o.wall === "north") { px = r.x + off; pz = r.y + r.d; nx = 0; nz = -1; }
      else if (o.wall === "west") { px = r.x; pz = r.y + off; nx = 1; nz = 0; }
      else { px = r.x + r.w; pz = r.y + off; nx = -1; nz = 0; }
      out.push({ x: px * CM, z: pz * CM, nx, nz, w: (o.widthCm || 100) * CM, sill: sill * CM, top: top * CM, roomH: (r.heightCm || 270) * CM });
    }
    return out;
  }

  // ── v1: свет ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
  // Эталоны (Планктон, TG 1451): светлая «высокая» картинка, тени мягкие и светло-серые, нет тёмных углов; тёплый отскок от пола.
  // Тонмаппинг остаётся Neutral (урок 445: ACES съедает товарный цвет) — меняем только свет и экспозицию.
  function relight(viewer, T) {
    const r = viewer.renderer, s = viewer.scene;
    r.toneMappingExposure = CFG.exposure ?? 1.08;
    s.environmentIntensity = CFG.env ?? 0.5;
    s.background = new T.Color(0xeef2f5);
    // цвета: CFG.sky / CFG.ground / CFG.sunC — строкой "#rrggbb" (прогон «нейтральный» — белые стены как в эталоне, без кремового сдвига)
    for (const o of s.children) {
      if (o.isHemisphereLight) { o.color.set(CFG.sky ?? 0xfffaf3); o.groundColor.set(CFG.ground ?? 0xd9c7ad); o.intensity = CFG.hemi ?? 0.85; }
      else if (o.isDirectionalLight && o.castShadow !== undefined && o.color.getHex() === 0xfff3e2) { o.userData.l3dSun = true; o.color.set(CFG.sunC ?? 0xfff0dc); o.intensity = CFG.sun ?? 2.2; }
      else if (o.isDirectionalLight) { o.userData.l3dFill = true; o.color.set(0xf3f1ec); o.intensity = CFG.fill ?? 0.25; }
    }
    if (viewer.quality && viewer.quality.shadows) {
      // тень солнца — мягче и светлее: в эталоне от мебели не чёрное пятно, а лёгкая серая полутень
      for (const o of s.children) if (o.userData.l3dSun) { o.shadow.radius = 6; o.shadow.blurSamples = 12; o.shadow.intensity = CFG.shadowK ?? 0.5; }
    }
  }
  /** Солнце — снаружи окна, сверху под ~40°, светит в центр комнаты (сейчас — с фиксированной стороны (-6, 9, -4), и окно не при чём). */
  function aimSun(viewer, T) {
    const w = windows(viewer)[0]; if (!w) return;
    const b = bounds(viewer);
    for (const o of viewer.scene.children) {
      if (o.userData.l3dSun) {
        const cx = b.cx * CM, cz = b.cy * CM;
        o.target.position.set(cx, 0, cz); o.target.updateMatrixWorld();
        // сбоку от нормали на 35° — тени не ровно «от окна», а чуть наискосок, как в эталоне
        const a = 0.6, dx = w.nx * Math.cos(a) - w.nz * Math.sin(a), dz = w.nz * Math.cos(a) + w.nx * Math.sin(a);
        o.position.set(cx - dx * 6, 6.5, cz - dz * 6);
        if (o.shadow && o.shadow.camera) {
          const half = Math.max(b.x1 - b.x0, b.y1 - b.y0) * CM * 0.8 + 1;
          Object.assign(o.shadow.camera, { left: -half, right: half, top: half, bottom: -half, near: 1, far: 20 });
          o.shadow.camera.updateProjectionMatrix();
        }
      } else if (o.userData.l3dFill) {
        // заполняющий — со стороны комнаты к окну (отражённый от стен свет), без теней
        o.position.set(b.cx * CM + w.nx * 5, 2.5, b.cy * CM + w.nz * 5);
      }
    }
    if (!viewer.__l3dWin) {
      // «свет из окна» — мягкий прямоугольный источник в проёме (только для полного профиля: на телефоне он дорогой — каждый пиксель
      // считает LTC). На телефоне его роль играет солнце + небо
      if (viewer.quality && viewer.quality.name === "desktop" && on("v4")) {
        T.RectAreaLightUniformsLib.init();
        for (const x of windows(viewer)) {
          const L = new T.RectAreaLight(0xfff6ea, CFG.rectK ?? 2.2, x.w, x.top - x.sill);
          L.position.set(x.x + x.nx * 0.05, (x.sill + x.top) / 2, x.z + x.nz * 0.05);
          L.lookAt(x.x + x.nx * 2, (x.sill + x.top) / 2 - 0.4, x.z + x.nz * 2);
          viewer.scene.add(L);
        }
      }
      viewer.__l3dWin = true;
    }
  }

  // ── v3: запечённые контактные тени (приём three `webgl_shadow_contact`, но рендер — один раз на расстановку, а не каждый кадр) ──
  const FLAT_KINDS = new Set(["rug", "wall-plane"]);
  function furniture(viewer) {
    const out = [];
    for (const [, p] of viewer.placed || []) {
      if (!p || !p.group || FLAT_KINDS.has(p.spec && p.spec.kind)) continue;
      if (p.spec && p.spec.kind === "tv" && p.spec.hung) continue;
      out.push(p.group);
    }
    return out;
  }
  // состояние — НА СЦЕНУ: демо пересоздаёт сцену при каждом открытии (liveDrop → liveEngine), общий объект ссылался бы на старую
  function bakeContact(viewer, T) {
    const t0 = performance.now();
    const r = viewer.renderer, s = viewer.scene, b = bounds(viewer);
    const W = (b.x1 - b.x0) * CM, D = (b.y1 - b.y0) * CM;
    const lite = !(viewer.quality && viewer.quality.name === "desktop");
    const RES = lite ? 256 : 512, rw = Math.round(RES * Math.min(1, W / D)) || RES, rh = Math.round(RES * Math.min(1, D / W)) || RES;
    const H = CFG.csHeight ?? 0.55;   // выше 55 см от пола предмет тени на пол почти не даёт
    let CS = viewer.__l3dCS;
    if (!CS) {
      const rt = new T.WebGLRenderTarget(rw, rh); rt.texture.generateMipmaps = false;
      const rtb = new T.WebGLRenderTarget(rw, rh); rtb.texture.generateMipmaps = false;
      const geo = new T.PlaneGeometry(W, D).rotateX(Math.PI / 2);
      const mat = new T.MeshBasicMaterial({ map: rt.texture, transparent: true, depthWrite: false, opacity: CFG.csOpacity ?? 0.9, toneMapped: false });
      const plane = new T.Mesh(geo, mat); plane.scale.y = -1; plane.renderOrder = 1; plane.name = "l3d:contact";
      plane.position.set(b.cx * CM, 0.032, b.cy * CM);   // над ковром (ворс до 3 см, `kits/bedroom.ts:buildRug`): тень и на ковре
      plane.raycast = () => {};                          // не мешает выбору предметов и шагу по полу
      const blur = new T.Mesh(geo); blur.visible = false;
      blur.position.set(b.cx * CM, H / 2, b.cy * CM);   // внутри объёма камеры тени (у пола её отсекает near)
      const cam = new T.OrthographicCamera(-W / 2, W / 2, D / 2, -D / 2, 0.004, H);
      cam.rotation.x = Math.PI / 2; cam.position.set(b.cx * CM, 0, b.cy * CM);
      const dm = new T.MeshDepthMaterial(); dm.userData.darkness = { value: CFG.csDark ?? 2.0 };
      dm.onBeforeCompile = (sh) => {
        sh.uniforms.darkness = dm.userData.darkness;
        sh.fragmentShader = "uniform float darkness;\n" + sh.fragmentShader.replace(
          "gl_FragColor = vec4( vec3( 1.0 - fragCoordZ ), opacity );",
          "gl_FragColor = vec4( vec3( 0.0 ), clamp( ( 1.0 - fragCoordZ ) * ( 1.0 - fragCoordZ ) * darkness, 0.0, 1.0 ) );");
      };
      dm.depthTest = false; dm.depthWrite = false;
      const hb = new T.ShaderMaterial(T.HorizontalBlurShader); hb.depthTest = false;
      const vb = new T.ShaderMaterial(T.VerticalBlurShader); vb.depthTest = false;
      CS = viewer.__l3dCS = { rt, rtb, plane, blur, cam, dm, hb, vb, rw, rh };
      s.add(plane); s.add(blur);
    }
    const { rt, rtb, plane, blur, cam, dm, hb, vb } = CS;
    cam.updateMatrixWorld(true);
    // видна только мебель: стены, пол, ковры, шторы — не отбрасывают
    const keep = new Set(furniture(viewer)), hidden = [];
    for (const o of s.children) if (o.visible && !keep.has(o)) { hidden.push(o); o.visible = false; }
    const bg = s.background, prevT = r.getRenderTarget(), alpha = r.getClearAlpha(), sm = r.shadowMap.autoUpdate;
    s.background = null; s.overrideMaterial = dm; r.shadowMap.autoUpdate = false;
    r.setClearAlpha(0); r.setRenderTarget(rt); r.clear(); r.render(s, cam);
    s.overrideMaterial = null;
    for (const o of hidden) o.visible = true;
    const pass = (amount) => {
      blur.visible = true;
      blur.material = hb; hb.uniforms.tDiffuse.value = rt.texture; hb.uniforms.h.value = amount / 256;
      r.setRenderTarget(rtb); r.render(blur, cam);
      blur.material = vb; vb.uniforms.tDiffuse.value = rtb.texture; vb.uniforms.v.value = amount / 256;
      r.setRenderTarget(rt); r.render(blur, cam);
      blur.visible = false;
    };
    pass(CFG.csBlur ?? 3); pass((CFG.csBlur ?? 3) * 0.5);
    r.setRenderTarget(prevT); r.setClearAlpha(alpha); s.background = bg; r.shadowMap.autoUpdate = sm;
    plane.visible = true;
    STAT.bakeMs.push(+(performance.now() - t0).toFixed(1));
  }

  // ── v3: шторы (декоративные, лён) — две панели по краям окна, от карниза до пола, со складками ──
  function curtains(viewer, T) {
    if (viewer.__l3dCurt || CFG.curtains === false) return;
    viewer.__l3dCurt = true;
    const mat = new T.MeshStandardMaterial({ color: 0xd8c4a6, roughness: 0.95, side: T.DoubleSide });
    for (const w of windows(viewer)) {
      const top = Math.min(w.roomH - 0.04, w.top + 0.14), h = top - 0.01, pw = 0.55;
      const geo = new T.PlaneGeometry(pw, h, 28, 1);
      const pos = geo.attributes.position;
      for (let i = 0; i < pos.count; i++) pos.setZ(i, 0.03 * Math.sin((pos.getX(i) / pw + 0.5) * Math.PI * 9));
      geo.computeVertexNormals();
      for (const side of [-1, 1]) {
        const m = new T.Mesh(geo, mat); m.name = "l3d:curtain";
        const along = side * (w.w / 2 + pw / 2 - 0.12);           // слегка заходит на проём, как в эталоне
        // ось «вдоль стены» = нормаль, повёрнутая на 90°
        const ax = -w.nz, az = w.nx;
        m.position.set(w.x + ax * along + w.nx * 0.09, 0.01 + h / 2, w.z + az * along + w.nz * 0.09);
        m.rotation.y = Math.atan2(w.nx, w.nz);
        m.raycast = () => {};
        viewer.scene.add(m);
      }
    }
  }

  // ── v4: GTAO постобработкой (каждый кадр) ──
  let COMP = null, inComp = false;
  function composer(viewer, T) {
    const r = viewer.renderer, orig = r.render.bind(r);
    const size = new T.Vector2();
    r.render = (s, c) => {
      if (COMP && !inComp && !CFG.bypass && s === viewer.scene && c === viewer.camera && r.getRenderTarget() === null) {
        inComp = true;
        try {
          r.getDrawingBufferSize(size);
          if (size.x !== COMP.w || size.y !== COMP.h) { COMP.c.setPixelRatio(1); COMP.c.setSize(size.x, size.y); COMP.w = size.x; COMP.h = size.y; }
          COMP.c.render();
        } finally { inComp = false; }
        return;
      }
      return orig(s, c);
    };
    r.getDrawingBufferSize(size);
    const rt = new T.WebGLRenderTarget(size.x || 896, size.y || 597, { type: T.HalfFloatType, samples: viewer.quality.name === "desktop" ? 4 : 0 });
    const c = new T.EffectComposer(r, rt);
    c.addPass(new T.RenderPass(viewer.scene, viewer.camera));
    const ao = new T.GTAOPass(viewer.scene, viewer.camera, size.x || 896, size.y || 597);
    ao.updateGtaoMaterial({ radius: 0.35, distanceExponent: 1.5, thickness: 1, scale: 1, samples: viewer.quality.name === "desktop" ? 16 : 8 });
    ao.blendIntensity = CFG.aoK ?? 0.85;
    c.addPass(ao);
    c.addPass(new T.OutputPass());
    COMP = { c, w: 0, h: 0 };
    STAT.composer = true;
  }

  // ── v2: пятна контактной тени по следу (одна текстура-градиент на все, плоскость на предмет) ──
  function blobTex(T) {
    const n = 64, cv = document.createElement("canvas"); cv.width = cv.height = n;
    const g = cv.getContext("2d"), img = g.createImageData(n, n);
    // скруглённый прямоугольник с мягким краем: плотно в середине следа, к краю — в ноль (как тень «под» предметом, не круг)
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const u = Math.abs((x + 0.5) / n * 2 - 1), v = Math.abs((y + 0.5) / n * 2 - 1);
      const d = Math.pow(Math.pow(u, 4) + Math.pow(v, 4), 0.25);   // «суперэллипс»
      const a = Math.max(0, Math.min(1, (1 - d) / 0.42));
      const i = (y * n + x) * 4; img.data[i] = img.data[i + 1] = img.data[i + 2] = 0; img.data[i + 3] = Math.round(255 * a * a);
    }
    g.putImageData(img, 0, 0);
    const tex = new T.CanvasTexture(cv);
    return tex;
  }
  function blobs(viewer, T) {
    const t0 = performance.now();
    const BLOB = viewer.__l3dBlob || (viewer.__l3dBlob = { tex: blobTex(T), list: [] });
    for (const m of BLOB.list) { viewer.scene.remove(m); m.geometry.dispose(); }
    BLOB.list = [];
    const mat = BLOB.mat || (BLOB.mat = new T.MeshBasicMaterial({ map: BLOB.tex, transparent: true, depthWrite: false, opacity: CFG.blobK ?? 0.6,
      toneMapped: false, color: 0x000000, polygonOffset: true, polygonOffsetFactor: -2 }));
    for (const [, p] of viewer.placed || []) {
      const sp = p.spec; if (!sp || FLAT_KINDS.has(sp.kind) || (sp.kind === "tv" && sp.hung)) continue;
      const pl = sp.placement; if (!pl || (pl.elevCm || 0) > 20) continue;
      const pad = 1.18 + Math.min(0.25, 12 / Math.max(20, Math.min(pl.wCm, pl.dCm)));   // тень чуть шире следа
      const geo = new T.PlaneGeometry(pl.wCm * CM * pad, pl.dCm * CM * pad).rotateX(-Math.PI / 2);
      const m = new T.Mesh(geo, mat); m.name = "l3d:blob"; m.renderOrder = 1; m.raycast = () => {};
      m.position.set(pl.x * CM, 0.032, pl.y * CM); m.rotation.y = (pl.rot || 0) * Math.PI / 180;   // как `placeGroup`
      viewer.scene.add(m); BLOB.list.push(m);
    }
    STAT.bakeMs.push(+(performance.now() - t0).toFixed(1));
  }

  window.__L3D_debug = function () {
    const v = window.__L3D_VIEWER; if (!v) return null;
    const CS = v.__l3dCS, BLOB = v.__l3dBlob;
    const o = { keep: furniture(v).length, placed: v.placed ? v.placed.size : 0, cs: !!CS, blobs: BLOB ? BLOB.list.length : 0,
      shadowsOn: v.renderer.shadowMap.enabled, exposure: v.renderer.toneMappingExposure, envK: v.scene.environmentIntensity,
      lights: v.scene.children.filter((x) => x.isLight).map((x) => ({ t: x.type, k: +x.intensity.toFixed(2), c: x.color.getHexString(), cast: !!x.castShadow,
        map: !!(x.shadow && x.shadow.map), pos: x.position.toArray().map((n) => +n.toFixed(2)), sun: !!x.userData.l3dSun })) };
    let rs = 0, cs = 0, nm = 0; v.scene.traverse((x) => { if (x.isMesh) { nm++; if (x.receiveShadow) rs++; if (x.castShadow) cs++; } });
    Object.assign(o, { meshes: nm, receive: rs, cast: cs });
    if (CS) {
      const px = new Uint8Array(CS.rw * CS.rh * 4);
      v.renderer.readRenderTargetPixels(CS.rt, 0, 0, CS.rw, CS.rh, px);
      let n = 0, mx = 0; for (let i = 3; i < px.length; i += 4) { if (px[i] > 8) n++; if (px[i] > mx) mx = px[i]; }
      Object.assign(o, { rw: CS.rw, rh: CS.rh, alphaPx: n, alphaMax: mx, planeVis: CS.plane.visible, planePos: CS.plane.position.toArray(), inScene: !!CS.plane.parent });
    }
    return o;
  };

  // ── замеры цвета: кадр / маска предметов / альбедо ──
  const IDS = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0], [255, 0, 255], [0, 255, 255], [255, 128, 0], [128, 0, 255],
    [0, 128, 255], [255, 0, 128], [128, 255, 0], [0, 255, 128], [128, 128, 255], [255, 128, 128]];
  function grab(r) {
    const gl = r.getContext(), w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, px = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
    const ctx = cv.getContext("2d"), img = ctx.createImageData(w, h);
    for (let y = 0; y < h; y++) img.data.set(px.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);   // GL снизу вверх
    for (let i = 3; i < img.data.length; i += 4) img.data[i] = 255;
    ctx.putImageData(img, 0, 0);
    return cv.toDataURL("image/png");
  }
  window.__L3D_measure = function () {
    const v = window.__L3D_VIEWER, T = window.RemlabScene.L3D; if (!v) return null;
    const r = v.renderer, s = v.scene, cam = v.camera;
    const legend = [], owner = new Map();
    let i = 0;
    for (const [slot, p] of v.placed || []) {
      if (!p.group || (p.spec && FLAT_KINDS.has(p.spec.kind) && p.spec.kind === "wall-plane")) continue;
      const id = IDS[i % IDS.length]; i++;
      legend.push({ slot, id, kind: p.spec && p.spec.kind, meshId: p.spec && p.spec.meshId, url: p.spec && p.spec.url, title: p.spec && p.spec.titleRu, k: p.group.userData.l3dK || 1 });
      p.group.traverse((o) => { if (o.isMesh) owner.set(o, { id, idx: legend.length - 1 }); });
    }
    const saved = new Map(), black = new T.MeshBasicMaterial({ color: 0x000000, toneMapped: false });
    const swap = (mk) => s.traverse((o) => {
      if (!(o.isMesh || o.isLine || o.isPoints || o.isSprite)) return;
      if (!saved.has(o)) saved.set(o, { m: o.material, v: o.visible });
      const own = owner.get(o);
      if (!o.isMesh) { o.visible = false; return; }
      if (o.name === "l3d:contact") { o.visible = false; return; }
      o.material = mk(own, saved.get(o).m);
    });
    CFG.bypass = true;
    const bg = s.background, out = { w: 0, h: 0, legend };
    try {
      r.render(s, cam); out.beauty = grab(r);
      CFG.bypass = true;
      s.background = new T.Color(0, 0, 0);
      const cache = new Map();
      swap((own) => {
        if (!own) return black;
        const key = own.id.join(",");
        if (!cache.has(key)) cache.set(key, new T.MeshBasicMaterial({ color: new T.Color().setRGB(own.id[0] / 255, own.id[1] / 255, own.id[2] / 255, T.SRGBColorSpace), toneMapped: false }));
        return cache.get(key);
      });
      r.render(s, cam); out.ids = grab(r);
      swap((own, m0) => {
        if (!own) return black;
        const m = Array.isArray(m0) ? m0[0] : m0;
        return new T.MeshBasicMaterial({ map: m && m.map || null, color: m && m.color ? m.color.clone() : new T.Color(1, 1, 1), vertexColors: !!(m && m.vertexColors), toneMapped: false, side: m ? m.side : 0 });
      });
      r.render(s, cam); out.albedo = grab(r);
    } finally {
      for (const [o, x] of saved) { o.material = x.m; o.visible = x.v; }
      s.background = bg; CFG.bypass = false;
      r.render(s, cam);
    }
    const gl = r.getContext(); out.w = gl.drawingBufferWidth; out.h = gl.drawingBufferHeight;
    return out;
  };
})();
