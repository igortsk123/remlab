import { chromium } from "@playwright/test";
const OUT=process.argv[2]; const BASE="https://remont-lab.online"; const b=await chromium.launch(); const L=(...a)=>console.log(a.join(" "));
const snap=async(pg,n)=>{await pg.screenshot({path:`${OUT}/${n}.png`}); L("экран",n);};
const btn=(pg,t)=>pg.locator(`#shot button:text-is("${t}")`).first();
// живая сцена: сканди (окно крупно на ракурсе 1 у сканди/джапанди? берём 0 и 4), 3D с взглядом вверх
for (const [idx,tag] of [[0,"set1"],[4,"japandi"]]) {
  const ctx=await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"}); const pg=await ctx.newPage();
  await pg.goto(BASE+"/demo/?live=force",{waitUntil:"networkidle",timeout:60000}); await pg.locator("button[data-swap]").nth(idx).click(); await pg.waitForTimeout(10000); await snap(pg,`live-${tag}-a1`);
  await btn(pg,"Ракурс 2").click(); await pg.waitForTimeout(7000); await snap(pg,`live-${tag}-a2`);
  await btn(pg,"3D").click(); await pg.waitForTimeout(6000); await snap(pg,`live-${tag}-3d`);
  const cv=pg.locator("#shot canvas").first(); const bb=await cv.boundingBox(); if (bb) { await pg.mouse.move(bb.x+bb.width/2,bb.y+bb.height/2); await pg.mouse.down(); await pg.mouse.move(bb.x+bb.width/2,bb.y+bb.height/2+260,{steps:12}); await pg.mouse.up(); await pg.waitForTimeout(5000); await snap(pg,`live-${tag}-3d-up`); await pg.mouse.move(bb.x+bb.width/2,bb.y+bb.height/2); await pg.mouse.down(); await pg.mouse.move(bb.x+bb.width/2+420,bb.y+bb.height/2-200,{steps:12}); await pg.mouse.up(); await pg.waitForTimeout(5000); await snap(pg,`live-${tag}-3d-turn`); }
  await ctx.close();
}
// серверный кадр
{ const ctx=await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"}); const pg=await ctx.newPage(); await pg.goto(BASE+"/demo/?live=0",{waitUntil:"networkidle",timeout:60000}); await pg.locator("button[data-swap]").first().click(); await pg.waitForTimeout(3000); await pg.locator("#shotbody [data-rep], #shot [data-rep]").first().click(); await pg.waitForTimeout(800); await pg.locator("#sheet .mini:has-text('Заменить')").nth(1).click();
  await pg.waitForFunction(()=>{const s=document.querySelector("#shot");const img=s&&s.querySelector(".shotwrap img");return img&&img.naturalWidth>300&&!/Собираем|очереди|Считаем/i.test(s.innerText);},null,{timeout:240000}).catch(()=>L("эскиз не дождался")); await snap(pg,"server-a1"); await btn(pg,"Ракурс 2").click(); await pg.waitForTimeout(45000); await snap(pg,"server-a2"); L("кадры:",JSON.stringify(await pg.evaluate(()=>[...document.querySelectorAll("#shot img")].map(i=>i.getAttribute("src")).filter(s=>/frames/.test(s||"")).slice(0,3)))); await ctx.close(); }
// /flat
{ const ctx=await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"}); const pg=await ctx.newPage(); const vid=(await (await fetch(BASE+"/demo/demo-data.json")).json()).variants[0].id; await pg.goto(BASE+"/flat?demo="+vid+"&flat=flat215",{waitUntil:"domcontentloaded",timeout:60000}); await pg.waitForSelector("canvas",{timeout:90000}); await pg.waitForTimeout(12000); await snap(pg,"flat-start"); const cv=pg.locator("canvas").first(); const bb=await cv.boundingBox(); await pg.mouse.move(bb.x+bb.width/2,bb.y+bb.height/2); await pg.mouse.down(); await pg.mouse.move(bb.x+bb.width/2,bb.y+bb.height/2+250,{steps:10}); await pg.mouse.up(); await pg.waitForTimeout(4000); await snap(pg,"flat-up"); await ctx.close(); }
await b.close();
