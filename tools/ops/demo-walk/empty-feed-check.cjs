// ПУСТАЯ ЛЕНТА ЗАМЕНЫ ВСЕГДА С ПОДСКАЗКОЙ (T-20261118-61/8/1, живая проверка директора 18.11: торшер + «Эконом»/«Премиум» + «по размеру + стиль» →
// 0 карточек и пустая шторка без подсказки; у шкафа подсказка «Снимите ограничения» есть). Правило общее: роль × ступень цены × «по размеру» × «стиль»
// — если карточек нет, в ленте есть подсказка и кнопка «Сбросить фильтры»; ни одного сочетания «0 карточек и пусто».
//   node tools/ops/demo-walk/empty-feed-check.cjs <база, напр. http://127.0.0.1:8791> <папка-снимков|-> [роль,роль…] [lang=ru|en]
// База — `stage-proxy.mjs` над папкой сборки (`make-stage.py`) либо прод. Снимки (если папка задана): 375×667 и 1280×800, RU/EN, торшер «Эконом»/«Премиум» и шкаф.
const path = require("path"), fs = require("fs");
const { demoUrl } = require("../demo-url.cjs");
const pw = require(path.resolve("node_modules/.pnpm/playwright@1.51.1/node_modules/playwright"));
const BASE = process.argv[2] || "http://127.0.0.1:8791", OUT = process.argv[3] && process.argv[3] !== "-" ? process.argv[3] : null;
const ONLY = (process.argv[4] || "").split(",").filter(Boolean), LANGS = (process.argv[5] || "ru,en").split(",");
if (OUT) fs.mkdirSync(OUT, { recursive: true });
const R = []; let bad = 0;
const ok = (n, c, i) => { if (!c) bad++; R.push((c ? "OK  " : "FAIL") + " " + n + (i !== undefined ? " — " + i : "")); console.log(R[R.length - 1]); };
async function open(b, vp, lang) {
  const ctx = await b.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 1, isMobile: vp.phone, hasTouch: vp.phone, locale: lang === "en" ? "en-GB" : "ru-RU" });
  const p = await ctx.newPage(); p.errs = []; p.on("pageerror", (e) => p.errs.push(String(e).slice(0, 200)));
  await p.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));
  await p.goto(demoUrl(BASE + "/demo/?lang=" + lang), { waitUntil: "load", timeout: 120000 });
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&allVariants().length>0&&typeof homeModel==='function'&&homeModel().styles.length>0", null, { timeout: 90000 });
  await p.waitForTimeout(1500);
  return p;
}
// один набор фильтров на одной роли: что видно в ленте после `grid()`
const probe = (p, role, f) => p.evaluate(([role, f]) => {
  const k = items.findIndex((i) => i.role.replace(/\s+\d+$/, "") === role); if (k < 0) return null;
  openPicker(items[k]); Object.assign(F, f); filters(); grid();
  const g = document.getElementById("grid");
  const cards = g.querySelectorAll(".card").length, cols = g.querySelectorAll(".colchip").length, hints = [...g.querySelectorAll(".hint")].map((h) => h.textContent.trim());
  const bt = g.querySelector("button.reset"), btn = !!bt;
  return { cards, cols, hints, btn, btnTxt: bt ? bt.textContent : "", title: document.getElementById("sh-title").textContent, ai: !!(sel && sel.sku && sel.sku.name) };
}, [role, f]);
(async () => {
  const b = await pw.chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  try {
    for (const lang of LANGS) {
      const p = await open(b, { w: 1280, h: 800, phone: false }, lang);
      const roles = await p.evaluate(() => [...new Set(items.map((i) => i.role.replace(/\s+\d+$/, "")))]);
      const use = ONLY.length ? roles.filter((r) => ONLY.includes(r)) : roles;
      console.log(lang, "роли:", use.join(", "));
      const segs = await p.evaluate(() => [null, "lo", "mid", "hi"]);
      let n = 0, empty = 0, emp = 0;
      for (const role of use) for (const price of segs) for (const fitOnly of [true, false]) for (const anyStyle of [true, false]) {
        const r = await probe(p, role, { price, fitOnly, anyStyle }); if (!r) continue; n++;
        // нет карточек других моделей — обязательна подсказка (цвета текущей модели лентой не считаются); при включённом ограничении — и кнопка сброса
        const need = r.cards === 0, active = !!(price || fitOnly || !anyStyle);
        if (need) { emp++; if (!r.hints.length || (active && !r.btn)) { empty++; ok(`[${lang}] ${role} цена=${price} размер=${fitOnly} стиль=${!anyStyle}: пустая лента без подсказки/кнопки`, false, JSON.stringify(r)); } }
        if (need && lang === "ru" && /[A-Za-z]{4,} [a-z]{3,}/.test(r.hints.join(" "))) ok(`${role}: латиница в RU-подсказке`, false, r.hints.join("|"));
        if (need && lang === "en" && /[А-Яа-яЁё]/.test(r.hints.join(" ") + r.btnTxt)) ok(`${role}: кириллица в EN-подсказке`, false, r.hints.join("|") + r.btnTxt);
      }
      ok(`[${lang}] сочетаний проверено ${n}; без карточек ${emp}; из них без подсказки/кнопки ${empty}`, empty === 0 && emp > 0);
      ok(`[${lang}] ошибок страницы нет`, p.errs.length === 0, p.errs.join(" | "));
      await p.context().close();
    }
  } finally { await b.close(); }
  console.log(bad ? "ИТОГО: провалов " + bad : "ИТОГО: всё в норме");
  process.exit(bad ? 1 : 0);
})();
