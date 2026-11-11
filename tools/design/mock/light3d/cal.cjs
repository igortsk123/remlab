/* eslint-disable @typescript-eslint/no-require-imports -- сценарий Node */
// T-20261111-22/2 правки (владелец TG 1666): калибровка яркости по эталону Планктона. Чистые кадры холста (без кнопок страницы)
// спальни и гостиной для набора настроек света, подставленных на лету в живую сцену: одна загрузка — много вариантов.
//   OUT=<папка> SIZE=1280x800 VAR=6 MODE=stalo|bylo CFG=.t22-cal-cfg.json node .t22-cal.cjs
const fs = require("fs"), path = require("path");
const { demoUrl } = require(path.join(process.cwd(), "tools/ops/demo-url.cjs"));
const pw = require(process.cwd() + "/node_modules/.pnpm/" + fs.readdirSync("node_modules/.pnpm").find((d) => d.startsWith("playwright-core@")) + "/node_modules/playwright-core");
const NEW = JSON.parse(fs.readFileSync(".t22-out/s2/scene.json", "utf8"));
const [W, H] = (process.env.SIZE || "1280x800").split("x").map(Number), PHONE = W <= 700;
const VI = +(process.env.VAR || 6), MODE = process.env.MODE || "stalo", OUT = (process.env.OUT || "/tmp/cal/").replace(/\/?$/, "/");
const CFGS = MODE === "bylo" ? [{ name: "bylo" }] : JSON.parse(fs.readFileSync(process.env.CFG || ".t22-cal-cfg.json", "utf8"));
const CAMS = String(process.env.CAMS || "0,1").split(",").map(Number);
fs.mkdirSync(OUT, { recursive: true });
const SOFT = "return/swiftshader|llvmpipe|software|microsoft basic/i.test(";
const HOOK = "this.addLights(),";
const patch = (js, win) => {
  if (!js.includes(HOOK)) throw new Error("нет addLights в сборке");
  let out = js.replace(HOOK, HOOK + "globalThis.__V=this,");
  if (!PHONE) out = out.replace(SOFT, "return!1&&/x/i.test(");
  if (win) {   // свет окон в сборке ветки выключен (win:0) — для подбора включаем, сила задаётся на лету
    if (!/win:0,/.test(out)) throw new Error("нет LIGHT.win в сборке");
    out = out.replace(/win:0,/, "win:1,");
  }
  return out;
};

(async () => {
  const b = await pw.chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const p = await (await b.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: PHONE ? 2 : 1, isMobile: PHONE, hasTouch: PHONE, locale: "ru-RU" })).newPage();
  p.on("pageerror", (e) => console.log("ОШИБКА", String(e.stack || e).slice(0, 500)));
  const HDRI = (process.env.HDRI || require("os").homedir() + "/remlab-logs/t22-1111/hdri").replace(/\/?$/, "/");
  await p.route("**/*", async (r) => {
    const q = r.request(), u = q.url();
    if (q.method() !== "GET" || /\/api\/(events|render|job)/.test(u)) return r.fulfill({ status: 204, body: "" });
    const hm = /\/t22-env\/([\w-]+\.hdr)$/.exec(u);   // HDRI пробы — с диска (Poly Haven, CC0), на прод не выкладываются
    if (hm) return r.fulfill({ status: 200, contentType: "application/octet-stream", body: fs.readFileSync(HDRI + hm[1]) });
    if (MODE !== "bylo") {
      if (/\/demo\/lib\/scene\.json/.test(u)) return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(NEW) });
      if (u.includes("/demo/lib/" + NEW.file)) return r.fulfill({ status: 200, contentType: "text/javascript", body: patch(fs.readFileSync(".t22-out/s2/" + NEW.file, "utf8"), true) });
      if (NEW.basket && u.includes("/demo/lib/" + NEW.basket.file)) return r.fulfill({ status: 200, contentType: "text/javascript", body: fs.readFileSync(".t22-out/s2/" + NEW.basket.file, "utf8") });
    } else if (/\/demo\/lib\/scene\.[0-9a-f]{12}\.js/.test(u)) {
      const res = await r.fetch();
      return r.fulfill({ response: res, body: patch(await res.text(), false) });
    }
    return r.continue();
  });
  await p.goto(demoUrl("https://remont-lab.online/demo/?live=force"), { waitUntil: "load", timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT", null, { timeout: 90000 });
  await p.evaluate(async (i) => {
    pickVariant(i); VW.collapse = true; vwOpenVariant(i); if (VW.mode !== "walk") vwMode("walk");
    for (let k = 0; k < 2400 && !LIVE.scene && LIVE.ok !== false; k++) await new Promise((r) => setTimeout(r, 25));
  }, VI);
  const info = await p.evaluate(() => ({ quality: __V.quality.name, win: (__V.windowLights || []).length, sun: !!__V.sun }));
  console.log(MODE, W, "v" + VI, JSON.stringify(info));
  const envMs = {};
  // настройки — внешним циклом: HDRI меняет окружение насовсем (варианты с ним в списке последними)
  for (const c of CFGS) {
    for (const cam of CAMS) {
      if (CAMS.length > 1 || c === CFGS[0]) { await p.evaluate((k) => vwCamGo(k), cam); await p.waitForTimeout(CAMS.length > 1 ? 2500 : 3000); }
      if (c.hdr && (await p.evaluate(() => globalThis.__ENV)) !== c.hdr) {
        const res = await p.evaluate(async (n) => { const r = await globalThis.__V.loadEnvironment(location.origin + "/t22-env/" + n + ".hdr"); globalThis.__ENV = n; return r; }, c.hdr);
        envMs[c.hdr] = res;
        console.log("окружение", c.hdr, JSON.stringify(res));
      }
      const url = await p.evaluate((c) => {
        const v = globalThis.__V, s = v.scene, r = v.renderer;
        // пол нейтральнее (ориентир Codex: медиана #bcb6ac) — множитель цвета текстуры только в пробе; сам пол — задача T-24/2
        for (const f of v.floors || []) { const m = f.material; if (m && m.color) m.color.setRGB(...(c.floorTint || [1, 1, 1])); }
        if (c.exposure != null) r.toneMappingExposure = c.exposure;
        if (c.env != null) s.environmentIntensity = c.env;
        s.traverse((o) => { if (o.isHemisphereLight) { if (c.hemi != null) o.intensity = c.hemi; if (c.hemiGround) o.groundColor.set(c.hemiGround); } });
        if (v.sun && c.sun != null) v.sun.intensity = c.sun;
        if (v.sun && c.sunColor) v.sun.color.set(c.sunColor);
        if (v.sun && c.shInt != null && v.sun.shadow) v.sun.shadow.intensity = c.shInt;
        if (v.fill && c.fill != null) v.fill.intensity = c.fill;
        for (const l of v.windowLights || []) {
          if (c.win != null) l.intensity = c.win;
          if (c.winDecay != null) l.decay = c.winDecay;
          if (c.winDist != null) l.distance = c.winDist;
          if (c.winColor) l.color.set(c.winColor);
        }
        r.render(s, v.camera);
        return r.domElement.toDataURL("image/png");
      }, c);
      fs.writeFileSync(`${OUT}${MODE}-v${VI}-${W}-c${cam}-${c.name}.png`, Buffer.from(url.split(",")[1], "base64"));
    }
  }
  await b.close();
  console.log("готово", CFGS.length * CAMS.length, "кадров");
})().catch((e) => { console.error(e); process.exit(2); });
