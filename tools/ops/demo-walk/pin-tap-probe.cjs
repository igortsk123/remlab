/* eslint-disable @typescript-eslint/no-require-imports -- сценарий Node */
// T-20261112-111/1 (разбор, без правок): ценники в 3D на живом /demo. Для каждого видимого ценника — что лежит сверху в его середине
// (elementFromPoint), настоящий тап/клик по нему → выбран ли предмет и видна ли карточка; то же — тапом по самому предмету (точка,
// где `scene.pick` = его номер). Плюс: стоит ли ценник над СВОЕЙ рамкой или над чужой, у какого декора в 3D ценника нет (ваза на столике).
// НИЧЕГО НЕ ПИШЕТСЯ: не-GET и /api/(events|render|job) — 204 здесь.
// T-20261112-111/2: чей ценник — расстояние от ценника до своей рамки и до чужих (ни одна чужая не ближе, своя ≤ ряда).
// T-20261112-111/3: точки тапа по предмету — по сетке кадра, где `scene.itemAt` (тот же путь, что у тапа в 3D) = его номер, и не ближе
// M px (телефон 12, компьютер 2) к видимому ценнику: палец рядом с ценником браузер отдаёт ценнику (touch adjustment) — это тап по
// соседу, а не промах сцены. Перед тапом точка перепроверяется (камера вернулась, ценники разложились). Расхождения pick/itemAt — в mism.
//   SIZE=375x667|1280x800 LANG_UI=en|ru OUT=… VARS=2 CAMS=0,1 [ALLROOMS=1] [TAPS=0|PINTAPS=0] [NEW=1 SCENE_DIR=… WT=…] node pin-tap-probe.cjs
//   сводки: pin-tap-owner-summary.py <папка> (чей ценник), pin-tap-item-summary.py <папка> (тап по предмету)
//   тяжёлое: tools/ops/heavy-slot.sh <метка> --min-gb 3 --cores 9 -- … (один браузер с программной графикой ест ~9 ядер)
const fs = require("fs");
const { demoUrl } = require("/home/pakar/igor/remlab/tools/ops/demo-url.cjs");
const PNPM = "/home/pakar/igor/remlab/node_modules/.pnpm/";
const pw = require(PNPM + fs.readdirSync(PNPM).find((d) => d.startsWith("playwright-core@")) + "/node_modules/playwright-core");
const OUT = process.env.OUT.replace(/\/?$/, "/"); fs.mkdirSync(OUT, { recursive: true });
const [W, H] = (process.env.SIZE || "375x667").split("x").map(Number);
const LANG = process.env.LANG_UI || "en", PHONE = W <= 700, NV = +(process.env.VARS || 3);
const NEW = process.env.NEW === "1", SCENE_DIR = process.env.SCENE_DIR, WT = process.env.WT || "/home/pakar/igor/remlab/.claude/worktrees/price-tags-1112";
const CAMS = (process.env.CAMS || "0,1").split(",").map(Number);
const TAG = `${NEW ? "stalo" : "bylo"}-${W}-${LANG}`;
const path = require("path");
const SOFT = "return/swiftshader|llvmpipe|software|microsoft basic/i.test(";
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), TAG, ...a);
const res = { size: TAG, variants: [] };

(async () => {
  const b = await pw.chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const ctx = PHONE ? await b.newContext({ ...pw.devices["iPhone 13"], viewport: { width: W, height: H }, locale: LANG === "en" ? "en-GB" : "ru-RU" })
    : await b.newContext({ viewport: { width: W, height: H }, locale: LANG === "en" ? "en-GB" : "ru-RU" });
  const p = await ctx.newPage(); const errs = [];
  p.on("pageerror", (e) => errs.push(String(e.stack || e).slice(0, 400)));
  const man = NEW ? JSON.parse(fs.readFileSync(path.join(SCENE_DIR, "scene.json"), "utf8")) : null;
  await p.route("**/*", async (r) => {
    const q = r.request(), u = q.url();
    if (q.method() !== "GET" || /\/api\/(events|render|job)/.test(u)) return r.fulfill({ status: 204, body: "" });
    if (NEW && q.resourceType() === "document" && /\/demo\/(\?|$)/.test(u))
      return r.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: fs.readFileSync(WT + "/tools/scout/flat215-demo/index.html", "utf8") });
    if (NEW && /\/demo\/lib\/scene\.json/.test(u)) { const res = await r.fetch(); const j = await res.json();
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...j, file: man.file, build: man.build }) }); }
    if (/\/scene\.[0-9a-f]{12}\.js/.test(u)) {
      let body = NEW && u.includes(man.file) ? fs.readFileSync(path.join(SCENE_DIR, man.file), "utf8") : null;
      if (body === null) { const res = await r.fetch(); body = await res.text(); }
      if (!PHONE) body = body.replace(SOFT, "return!globalThis.__FULL3D&&/swiftshader|llvmpipe|software|microsoft basic/i.test(");
      return r.fulfill({ status: 200, contentType: "text/javascript", body });
    }
    return r.continue();
  });
  // цены на телефоне по умолчанию скрыты (T-117) — показываем, как владелец кнопкой «Показать цены»
  await p.addInitScript(() => { window.__FULL3D = true; try { localStorage.setItem("remlab-sheet-hint-v1", "1"); sessionStorage.setItem("remlab-prices-off", "0"); } catch { /* приватное окно — без хранилища */ } });
  await p.goto(demoUrl("https://remont-lab.online/demo/?lang=" + LANG + "&quiz=0&live=force"), { waitUntil: "load", timeout: 300000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D", null, { timeout: 300000 });
  await p.evaluate(() => Promise.all([sceneModule(), rtMeshes()]));
  // гостиная и спальня, по NV вариантов разных стилей в каждой
  const living = await p.evaluate(([nv, allRooms]) => { const by = {}; allVariants().forEach((v, i) => { const room = String(roomIdOf(v) || "living"), k = allRooms ? room : /bed|спал/i.test(room) ? "bed" : /^living|гост/i.test(room) ? "living" : "";
    if (!k) return; const g = (by[k] = by[k] || []); if (g.length < nv && !g.some((x) => x.style === v.style)) g.push({ i, style: v.style }); });
    return Object.values(by).flat().map((x) => x.i); }, [NV, !!process.env.ALLROOMS]);
  log("варианты:", JSON.stringify(living));
  const tap = async (x, y) => { if (PHONE) await p.touchscreen.tap(x, y); else await p.mouse.click(x, y); };
  const state = async (want) => {
    const t0 = Date.now();
    await p.waitForFunction((i) => VW.sel === i && PINS.rot && PINS.rot._for === i && !PINS.rot.hidden, want, { timeout: 10000 }).catch(() => {});
    return p.evaluate(([i, ms]) => { const c = document.querySelector("#vpins .vacts"); const r = c && !c.hidden ? c.getBoundingClientRect() : null;
      const exp = vwItemAt(i) ? vwCardInfo(vwItemAt(i)).name : "", got = (document.querySelector("#vpins .vacts .vcnm") || {}).textContent || "";
      const q = LIVE.scene.pins().find((z) => z.index === i);
      return { sel: VW.sel, card: !!(r && r.width > 0) && got === exp, cardName: got, want: exp, ms, pricesOff: PRICES_OFF, vis: !!(q && q.visible) }; }, [want, Date.now() - t0]); };

  for (const vi of living) {
    await p.evaluate((i) => { pickVariant(i); VW.collapse = true; vwOpenVariant(i); if (VW.mode !== "walk") vwMode("walk"); if (PRICES_OFF) vwPricesToggle(); }, vi);
    await p.waitForFunction("LIVE.ok===false||(LIVE.scene&&LIVE.state==='ready')", null, { timeout: 240000 }).catch(() => {});
    for (const cam of CAMS) {
      await p.evaluate((k) => { vwSelect(null); vwCamGo(k); if (PRICES_OFF) vwPricesToggle(); }, cam); await p.waitForTimeout(8000);
      const V = { variant: vi, cam, pins: [], items: [] };
      // ценники: середина, кто сверху, своя рамка / чужие рамки под ценником
      V.pins = await p.evaluate(() => {
        const all = LIVE.scene.pins(), fr = document.getElementById("vpins").getBoundingClientRect();
        // ЧЕЙ ЦЕННИК (T-111/2): расстояние от прямоугольника ценника до своей рамки и до ближайшей чужой рамки мебели/предмета на ней
        // (фон — картины, ткань, ковёр, люстра — не считаем); оба 0 — ближе та, что меньше. Своя прошла — ownWins
        const dec = (i) => { const it = vwItemAt(i); return it && it.dec !== undefined ? ((allVariants()[cur] || {}).decor || [])[it.dec] : null; };
        const backdrop = (i) => { const x = dec(i); return !!x && (isWallArt(x) || isCloth3d(x) || x.strategy === "ceiling_over"); };
        const rect = (q) => ({ left: fr.left + q.box[0], right: fr.left + q.box[2], top: fr.top + q.box[1], bottom: fr.top + q.box[3] });
        const gap = (a, b) => Math.hypot(Math.max(0, b.left - a.right, a.left - b.right), Math.max(0, b.top - a.bottom, a.top - b.bottom));
        const area = (q) => (q.right - q.left) * (q.bottom - q.top);
        const owner = (r, i) => { const own = all.find((q) => q.index === i && q.box); if (!own || backdrop(i)) return { backdrop: backdrop(i) };
          const R = rect(own), d = gap(r, R); let best = null;
          all.filter((q) => q.index !== i && q.visible && q.box && !backdrop(q.index)).forEach((q) => { const Q = rect(q), e = gap(r, Q);
            const closer = e < d || (e === d && d === 0 && area(Q) <= area(R)); if (closer && (!best || e < best.gap)) best = { name: name(q.index), gap: Math.round(e) }; });
          return { gapOwn: Math.round(d), closerOther: best, ownWins: !best }; };
        const name = (i) => { const it = vwItemAt(i); return it ? String(baseRole(it.role) || "") + " · " + String(((skuOf(it) || {}).name) || "").slice(0, 34) : "?"; };
        return [...document.querySelectorAll("#vpins .vpin")].filter((n) => !n.hidden && n.getBoundingClientRect().width > 0).map((n) => {
          const r = n.getBoundingClientRect(), i = +n.dataset.pi, cx = r.left + r.width / 2, cy = r.top + r.height / 2;
          const top = document.elementFromPoint(cx, cy), own = all.find((q) => q.index === i);
          const ob = own && own.box ? { l: fr.left + own.box[0], r: fr.left + own.box[2], t: fr.top + own.box[1], b: fr.top + own.box[3] } : null;
          // под ценником — чья рамка (кроме своей); центр ценника над своей рамкой по горизонтали?
          const over = all.filter((q) => q.index !== i && q.visible && q.box).filter((q) => cx > fr.left + q.box[0] && cx < fr.left + q.box[2] && cy > fr.top + q.box[1] && cy < fr.top + q.box[3]).map((q) => name(q.index));
          return { i, name: name(i), text: n.textContent, x: Math.round(cx), y: Math.round(cy),
            topEl: top ? (top === n ? "сам ценник" : (top.id ? "#" + top.id : top.tagName.toLowerCase() + "." + String(top.className).split(" ")[0])) : "ничего",
            overOwnX: ob ? cx >= ob.l && cx <= ob.r : null, aboveOwn: ob ? cy <= ob.t + 4 : null, overOthers: over,
            // расстояние: низ ценника → верх своей рамки (+ — над, − — залез на предмет), середина ценника → середина рамки по горизонтали
            ...owner(r, i),
            dy: ob ? Math.round(ob.t - r.bottom) : null, dx: ob ? Math.round(cx - (ob.l + ob.r) / 2) : null, boxW: ob ? Math.round(ob.r - ob.l) : null };
        });
      });
      // видимый в кадре товар с ценой, у которого ценника нет (ценник спрятан правилом раскладки)
      V.noPin = await p.evaluate(() => LIVE.scene.pins().filter((q) => q.visible && q.box && vwItemAt(q.index) && (skuOf(vwItemAt(q.index)) || {}).price)
        .filter((q) => { const n = document.querySelector(`#vpins .vpin[data-pi="${q.index}"]`); return !n || n.hidden; })
        .map((q) => ({ i: q.index, name: String(baseRole(vwItemAt(q.index).role) || "") + " · " + String((skuOf(vwItemAt(q.index)) || {}).name || "").slice(0, 30),
          inFrame: q.box[2] > 0 && q.box[0] < LIVE.canvas.clientWidth && q.box[3] > 0 && q.box[1] < LIVE.canvas.clientHeight })));
      await p.screenshot({ path: `${OUT}${TAG}-v${vi}-c${cam}-0-cenniki.png`, timeout: 120000 }).catch(() => {});
      // тап по каждому ценнику
      for (const pin of (process.env.TAPS === "0" || process.env.PINTAPS === "0" ? [] : V.pins)) {
        await p.evaluate(() => vwSelect(null)); await p.waitForTimeout(600);
        await p.waitForFunction((i) => { const n = document.querySelector(`#vpins .vpin[data-pi="${i}"]`); return !!n && !n.hidden; }, pin.i, { timeout: 6000 }).catch(() => {});
        // без GPU кадр идёт секундами: после снятия выбора ценники ещё стоят по старой раскладке (карточка открыта) — ждём, пока место
        // ценника не перестанет меняться два кадра подряд, и что под серединой — он сам
        const fresh = await p.evaluate((i) => new Promise((res) => { let prev = null, same = 0, n0 = 0;
          const step = () => { const n = document.querySelector(`#vpins .vpin[data-pi="${i}"]`); if (!n || n.hidden) return res(null);
            const r = n.getBoundingClientRect(), q = { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
            same = prev && prev.x === q.x && prev.y === q.y ? same + 1 : 0; prev = q;
            const el = document.elementFromPoint(q.x, q.y), own = !!(el && el.closest && el.closest(`.vpin[data-pi="${i}"]`));
            if ((same >= 2 && own) || ++n0 > 40) return res({ ...q, own, frames: n0 }); requestAnimationFrame(step); };
          requestAnimationFrame(step); }), pin.i);
        if (!fresh) { pin.tap = "ценник пропал перед тапом"; continue; }
        await tap(fresh.x, fresh.y);
        pin.tap = await state(pin.i); pin.tapAt = fresh;
        if (pin.tap.sel !== pin.i || !pin.tap.card) await p.screenshot({ path: `${OUT}${TAG}-v${vi}-c${cam}-pin-${pin.i}-net.png`, timeout: 120000 }).catch(() => {});
      }
      // тап по самому предмету: точка сетки, где pick = номер, ближе всего к середине его попаданий
      await p.evaluate(() => vwSelect(null)); await p.waitForTimeout(600);
      // T-111/3: точка — по тому же лучу, что сам тап (`itemAt` = walkAim), и не ближе пальца к ценнику: телефон «притягивает» тап
      // к ссылке рядом (ценник соседа в 4–6 px — его товар, так и должно быть); расхождения pick/itemAt по сетке — отдельно
      const ITEMS = process.env.TAPS === "0" ? { items: [], mism: [] } : await p.evaluate((M) => {
        const r = LIVE.canvas.getBoundingClientRect(), hits = new Map(), mism = [];
        const pinR = [...document.querySelectorAll("#vpins .vpin")].filter((e) => !e.hidden).map((e) => e.getBoundingClientRect()).filter((q) => q.width > 0);
        const busy = [...document.querySelectorAll("#shot .vmodes, #shot .vprice, #shot .vhist, #vside, #vsum, #shot .vcams, #shot .vslots, #vpins .vpin")].map((e) => e.getBoundingClientRect()).filter((q) => q.width > 0);
        for (let fy = 0.06; fy < 0.94; fy += 0.02) for (let fx = 0.03; fx <= 0.97; fx += 0.02) {
          const x = r.left + fx * r.width, y = r.top + fy * r.height;
          if (busy.some((q) => x > q.left - M && x < q.right + M && y > q.top - M && y < q.bottom + M)) continue;   // у кнопки палец уходит к ней
          if (document.elementFromPoint(x, y) !== LIVE.canvas) continue;
          const pk = LIVE.scene.pick(x, y), i = LIVE.scene.itemAt ? LIVE.scene.itemAt(x, y) : pk;
          if (pk !== i && (pk >= 0 || i >= 0)) mism.push([Math.round(x), Math.round(y), pk, i]);
          if (i < 0 || pinR.some((q) => x > q.left - M && x < q.right + M && y > q.top - M && y < q.bottom + M)) continue; (hits.get(i) || hits.set(i, []).get(i)).push([x, y]);
        }
        return { mism, items: [...hits].map(([i, pts]) => { const mx = pts.reduce((s, q) => s + q[0], 0) / pts.length, my = pts.reduce((s, q) => s + q[1], 0) / pts.length;
          const srt = pts.slice().sort((a, c) => Math.hypot(a[0] - mx, a[1] - my) - Math.hypot(c[0] - mx, c[1] - my)), best = srt[0];
          const it = vwItemAt(i); return { i, name: it ? String(baseRole(it.role) || "") + " · " + String(((skuOf(it) || {}).name) || "").slice(0, 34) : "?", price: !!(it && (skuOf(it) || {}).price), n: pts.length, x: Math.round(best[0]), y: Math.round(best[1]), edge: best[0] < r.left + 0.2 * r.width || best[0] > r.left + 0.8 * r.width, pts: srt.slice(0, 60).map((q) => [Math.round(q[0]), Math.round(q[1])]) }; }) };
      }, PHONE ? 12 : 2);
      V.items = ITEMS.items; V.mism = ITEMS.mism;
      for (const it of (process.env.TAPS === "0" ? [] : V.items)) {
        await p.evaluate(() => vwSelect(null)); await p.waitForTimeout(600);
        const pt = await p.waitForFunction(([i, pts, M]) => { const pr = [...document.querySelectorAll("#vpins .vpin")].filter((e) => !e.hidden).map((e) => e.getBoundingClientRect()).filter((q) => q.width > 0);
          return pts.find(([x, y]) => document.elementFromPoint(x, y) === LIVE.canvas && LIVE.scene.itemAt(x, y) === i && !pr.some((q) => x > q.left - M && x < q.right + M && y > q.top - M && y < q.bottom + M)) || false; },
          [it.i, it.pts, PHONE ? 12 : 2], { timeout: 8000, polling: 100 }).then((h) => h.jsonValue()).catch(() => null);
        it.tapAt = pt || [it.x, it.y]; it.fresh = !!pt;
        await tap(it.tapAt[0], it.tapAt[1]);
        it.tap = await state(it.i);
        if (it.tap.sel !== it.i || !it.tap.card) await p.screenshot({ path: `${OUT}${TAG}-v${vi}-c${cam}-item-${it.i}-net.png`, timeout: 120000 }).catch(() => {});
        // тап в «3D» по полу/предмету может увести камеру (шаг) — вернуть ракурс
        await p.evaluate((k) => { vwSelect(null); vwCamGo(k); }, cam); await p.waitForTimeout(1500);
      }
      // ПУСТОЕ У КРАЯ (директор 00:12): тап в крайних 20 % по стене/полу — поворот взгляда, как было; ПОЛ на телефоне — шторка не поднимается (TG 1175)
      await p.evaluate((k) => { vwSelect(null); vwCamGo(k); }, cam); await p.waitForTimeout(2500);
      if (process.env.TAPS !== "0") V.empty = await p.evaluate(() => { const r = LIVE.canvas.getBoundingClientRect(), out = {};
        const empty = (x, y) => document.elementFromPoint(x, y) === LIVE.canvas && LIVE.scene.pick(x, y) < 0 && !(LIVE.scene.itemAt && LIVE.scene.itemAt(x, y) >= 0);
        for (const [k, a, b] of [["left", 0.04, 0.16], ["right", 0.84, 0.96]]) for (let fy = 0.35; fy < 0.9 && !out[k]; fy += 0.05) for (let fx = a; fx <= b && !out[k]; fx += 0.04) {
          const x = r.left + fx * r.width, y = r.top + fy * r.height; if (empty(x, y)) out[k] = [Math.round(x), Math.round(y)]; }
        for (let fy = 0.85; fy > 0.45 && !out.floor; fy -= 0.04) for (let fx = 0.3; fx <= 0.7 && !out.floor; fx += 0.05) {
          const x = r.left + fx * r.width, y = r.top + fy * r.height; if (empty(x, y)) out.floor = [Math.round(x), Math.round(y)]; }
        return out; });
      const look = () => p.evaluate(() => { const q = LIVE.scene.pose() || {}; return JSON.stringify(q); });
      const sheet = () => p.evaluate(() => { const sd = document.getElementById("vside"); return { pos: sd ? sd.dataset.pos || "" : "", vis: Math.round(VW.sheetVis || 0) }; });
      for (const k of (V.empty ? ["left", "right", "floor"] : [])) { const pt = V.empty[k]; if (!pt) { V.empty[k] = "нет пустой точки"; continue; }
        const a = await look(), s0 = await sheet(); await tap(pt[0], pt[1]); await p.waitForTimeout(2500); const b = await look(), s1 = await sheet();
        V.empty[k] = { pt, turned: a !== b, sel: await p.evaluate(() => VW.sel), sheet0: s0, sheet1: s1 };
        await p.evaluate((c) => { vwSelect(null); vwCamGo(c); }, cam); await p.waitForTimeout(2000); }
      log(`вариант ${vi}: пустое у края/пол`, JSON.stringify(V.empty));
      // декор в 3D без ценника (ваза на столике и т. п.)
      V.decorNoPin = await p.evaluate(() => { const ds = (allVariants()[cur] || {}).decor || [], out = [];
        ds.forEach((x, j) => { const k = vwDecIndex(j), it = k >= 0 ? vwItemAt(k) : null; out.push({ j, role: x.role || (x.sku || {}).role || "", name: String(((x.sku || {}).name) || "").slice(0, 40), in3d: k >= 0, strategy: x.strategy || "", price: !!(x.sku && x.sku.price), itPrice: !!(it && (skuOf(it) || {}).price), pin: k >= 0 && !!document.querySelector(`#vpins .vpin[data-pi="${k}"]`) }); });
        return out; });
      res.variants.push(V);
      const bad = V.pins.filter((q) => typeof q.tap !== "object" || q.tap.sel !== q.i || !q.tap.card), badI = V.items.filter((q) => q.tap.sel !== q.i || !q.tap.card);
      log(`вариант ${vi} ракурс ${cam}: ценников ${V.pins.length}, тап по ценнику без карточки ${bad.length}`, JSON.stringify(bad.map((q) => [q.name, q.topEl, q.tap])),
        `· предметов ${V.items.length}, тап по предмету без карточки ${badI.length}`, JSON.stringify(badI.map((q) => [q.name, q.n, q.edge ? "край" : "середина", q.tap])),
        `· ценник над чужим:`, JSON.stringify(V.pins.filter((q) => q.overOthers.length).map((q) => [q.name, q.text, q.overOthers, q.overOwnX])));
    }
  }
  res.errs = errs;
  fs.writeFileSync(`${OUT}${TAG}-pins.json`, JSON.stringify(res, null, 1));
  log("ошибки страницы:", errs.length, errs[0] || "");
  await b.close();
})().catch((e) => { console.log("СБОЙ", TAG, String(e).slice(0, 400)); process.exit(1); });
