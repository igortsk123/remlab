import { chromium } from "@playwright/test";
const BASE="https://remont-lab.online"; const b=await chromium.launch({args:["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"]}); const pg=await (await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"})).newPage();
const reqs=[]; let renders=0; pg.on("request",r=>{ const u=r.url(); if(u.includes("/api/render")) renders++; if(/\.js(\?|$)|\.glb|\/rt\//.test(u)) reqs.push(u.replace(BASE,"").slice(0,70)); });
pg.on("console",m=>{ if(m.type()==="error"||/scene|сцен/i.test(m.text())) console.log("console:",m.type(),m.text().slice(0,160)); });
await pg.goto(BASE+"/demo/",{waitUntil:"networkidle",timeout:60000});
await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(2000);
await pg.locator("#shotbody [data-rep]").first().click(); await pg.waitForTimeout(800); await pg.locator("#sheet .mini:has-text('Заменить')").nth(1).click();
for (const t of [3000,5000,7000]) { await pg.waitForTimeout(t); console.log(`+${t}мс canvas в окне:`, await pg.locator("#shot canvas").count(), "| полоса:", JSON.stringify((await pg.locator("#shot").innerText()).replace(/\s+/g," ").slice(0,90))); }
console.log("POST /api/render:", renders); console.log("js/glb/rt запросы:", reqs.filter(u=>/scene|rt\/|glb/.test(u)).slice(0,12).join(" | ")||"(нет)");
console.log("webgl:", await pg.evaluate(()=>{ const c=document.createElement("canvas"); const gl=c.getContext("webgl2")||c.getContext("webgl"); if(!gl) return "нет"; const e=gl.getExtension("WEBGL_debug_renderer_info"); return e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):"есть, без имени"; }));
await pg.screenshot({path:process.argv[2]+"/P6-live-scene.png"}); await b.close();
