import { chromium } from "@playwright/test";
const OUT=process.argv[2]; const BASE="https://remont-lab.online"; const b=await chromium.launch(); const L=(...a)=>console.log(a.join(" "));
for (const vid of ["set1","set5","set9","set11","set18"]) { try {
  const pg=await (await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"})).newPage(); const errs=[]; pg.on("pageerror",e=>errs.push(String(e).slice(0,100)));
  const r=await pg.goto(`${BASE}/flat?demo=${vid}&flat=flat215`,{waitUntil:"domcontentloaded",timeout:60000}); if (r.status()!==200) { L(vid,"HTTP",r.status()); await pg.context().close(); continue; }
  await pg.waitForSelector("canvas",{timeout:90000}); await pg.waitForTimeout(12000); await pg.screenshot({path:`${OUT}/${vid}-start.png`}); await pg.waitForTimeout(15000); await pg.screenshot({path:`${OUT}/${vid}-start27.png`});
  // каркасные коробки: ищем прозрачные/wireframe меши через сцену недоступно — судим по экрану; идём вперёд 4 с к дивану
  const cv=pg.locator("canvas").first(); const bb=await cv.boundingBox(); await pg.mouse.click(bb.x+bb.width/2,bb.y+bb.height/2);
  await pg.keyboard.down("KeyW"); await pg.waitForTimeout(4000); await pg.keyboard.up("KeyW"); await pg.waitForTimeout(1500); await pg.screenshot({path:`${OUT}/${vid}-walk.png`});
  await pg.keyboard.down("KeyA"); await pg.waitForTimeout(900); await pg.keyboard.up("KeyA"); await pg.keyboard.down("KeyW"); await pg.waitForTimeout(4000); await pg.keyboard.up("KeyW"); await pg.waitForTimeout(1500); await pg.screenshot({path:`${OUT}/${vid}-walk2.png`});
  L(vid,"ошибки:",errs.length); await pg.context().close();
} catch(e) { L(vid,"сбой:",String(e).split("\n")[0].slice(0,120)); } }
await b.close();
