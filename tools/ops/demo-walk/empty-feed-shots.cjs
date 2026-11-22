// СНИМКИ ПУСТОЙ ЛЕНТЫ ЗАМЕНЫ (T-20261118-61/8/1): шторка «Выбрать <роль>» при ступени цены + «по размеру + стиль»; 375×667 и 1280×800, RU и EN.
// Кроме снимков — проверка кнопки: нажали «Сбросить фильтры» — в ленте появились карточки, чипы «по размеру/стиль/цена» сняты.
//   node tools/ops/demo-walk/empty-feed-shots.cjs <база> <папка-снимков> [роль:ступень,…=торшер:lo,торшер:hi,стул:lo,диван:-]
const path = require("path"), fs = require("fs");
const { demoUrl } = require("../demo-url.cjs");
const pw = require(path.resolve("node_modules/.pnpm/playwright@1.51.1/node_modules/playwright"));
const BASE = process.argv[2], OUT = process.argv[3];
const CASES = (process.argv[4] || "торшер:lo,торшер:mid,торшер:hi,стул:lo,диван:-").split(",").map((s) => s.split(":"));
fs.mkdirSync(OUT, { recursive: true });
let bad = 0;
const ok = (n, c, i) => { if (!c) bad++; console.log((c ? "OK  " : "FAIL") + " " + n + (i !== undefined ? " — " + i : "")); };
(async () => {
  const b = await pw.chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  try {
    for (const lang of ["ru", "en"]) for (const vp of [{ w: 375, h: 667, phone: true }, { w: 1280, h: 800, phone: false }]) {
      const ctx = await b.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 1, isMobile: vp.phone, hasTouch: vp.phone, locale: lang === "en" ? "en-GB" : "ru-RU" });
      const p = await ctx.newPage(); p.errs = []; p.on("pageerror", (e) => p.errs.push(String(e).slice(0, 200)));
      await p.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
      await p.goto(demoUrl(BASE + "/demo/?lang=" + lang), { waitUntil: "load", timeout: 120000 });
      await p.waitForFunction("typeof D!=='undefined'&&!!D&&allVariants().length>0&&typeof homeModel==='function'&&homeModel().styles.length>0", null, { timeout: 90000 });
      await p.waitForTimeout(1500);
      for (const [role, seg] of CASES) {
        const tag = `${lang}-${vp.w}-${role.replace(/\s+/g, "_")}-${seg === "-" ? "default" : seg}`;
        const r = await p.evaluate(([role, seg]) => {
          const k = items.findIndex((i) => i.role.replace(/\s+\d+$/, "") === role); if (k < 0) return null;
          openPicker(items[k]); if (seg !== "-") { F.price = seg; filters(); grid(); }
          const g = document.getElementById("grid");
          return { cards: g.querySelectorAll(".card").length, hint: [...g.querySelectorAll(".hint")].map((h) => h.textContent.trim()).join(" | "), btn: !!g.querySelector("button.reset") };
        }, [role, seg]);
        if (!r) { console.log("нет роли", role); continue; }
        await p.waitForTimeout(500);
        await p.screenshot({ path: path.join(OUT, tag + ".png") });
        console.log(tag, JSON.stringify(r));
        if (r.cards === 0) {
          ok(`${tag}: подсказка и кнопка есть`, !!r.hint && r.btn);
          await p.click("#grid button.reset"); await p.waitForTimeout(400);
          const a = await p.evaluate(() => ({ cards: document.querySelectorAll("#grid .card").length, price: F.price, fit: F.fitOnly, any: F.anyStyle, title: document.getElementById("sh-title").textContent }));
          ok(`${tag}: после «Сбросить» карточки появились, ограничения сняты`, a.cards > 0 && !a.price && !a.fit && a.any, JSON.stringify(a));
          await p.screenshot({ path: path.join(OUT, tag + "-after-reset.png") });
        }
        await p.evaluate(() => { try { closePicker(); } catch (e) {} });
      }
      ok(`[${lang} ${vp.w}] ошибок страницы нет`, p.errs.length === 0, p.errs.join(" | "));
      await ctx.close();
    }
  } finally { await b.close(); }
  console.log(bad ? "ИТОГО: провалов " + bad : "ИТОГО: всё в норме");
  process.exit(bad ? 1 : 0);
})();
