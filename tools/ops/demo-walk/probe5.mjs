import { chromium } from "@playwright/test";
const BASE="https://remont-lab.online"; const b=await chromium.launch(); const pg=await (await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"})).newPage();
let renders=0, bundle=""; pg.on("request",r=>{ if(r.url().includes("/api/render")) renders++; if(/scene\.[^/]*\.js/.test(r.url())) bundle=r.url(); });
await pg.goto(BASE+"/demo/",{waitUntil:"networkidle",timeout:60000});
await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(4000);
console.log("bundle:",bundle||"(не грузился)"); console.log("canvas в окне:", await pg.locator("#shot canvas").count(), "| webgl canvas на странице:", await pg.locator("canvas").count());
const before=renders; await pg.locator("#shotbody [data-rep]").first().click(); await pg.waitForTimeout(800); await pg.locator("#sheet .mini:has-text('Заменить')").nth(1).click(); await pg.waitForTimeout(3000);
console.log("POST /api/render при замене:", renders-before, "| полоса:", JSON.stringify((await pg.locator("#shot").innerText()).replace(/\s+/g," ").slice(0,160)));
await pg.screenshot({path:process.argv[2]+"/P5-live-scene.png"}); await b.close();
