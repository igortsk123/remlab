import { chromium } from "@playwright/test";
const OUT=process.argv[2]; const BASE="https://remont-lab.online"; const b=await chromium.launch(); const pg=await (await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"})).newPage();
const vid=(await (await fetch(BASE+"/demo/demo-data.json")).json()).variants[0].id; console.log("variant:",vid); await pg.goto(BASE+"/flat?demo="+vid+"&flat=flat215",{waitUntil:"domcontentloaded",timeout:60000}); await pg.waitForSelector("canvas",{timeout:90000}); await pg.waitForTimeout(12000); await pg.screenshot({path:`${OUT}/flat-start.png`});
await pg.locator("button:has-text('Сверху')").first().click(); await pg.waitForTimeout(5000); await pg.screenshot({path:`${OUT}/flat-top.png`});
await pg.locator("button:has-text('Бродилка')").first().click(); await pg.waitForTimeout(3000); await pg.keyboard.down("KeyD"); await pg.waitForTimeout(1100); await pg.keyboard.up("KeyD"); await pg.waitForTimeout(2500); await pg.screenshot({path:`${OUT}/flat-turn-right.png`});
// серверный кадр: второй вид
const p2=await (await b.newContext({viewport:{width:1280,height:900},locale:"ru-RU"})).newPage(); await p2.goto(BASE+"/demo/",{waitUntil:"networkidle",timeout:60000}); await p2.locator("button[data-swap]").first().click(); await p2.waitForTimeout(3000);
await p2.locator("#shotbody [data-rep], #shot [data-rep]").first().click(); await p2.waitForTimeout(800); await p2.locator("#sheet .mini:has-text('Заменить')").nth(1).click();
await p2.waitForFunction(()=>{const s=document.querySelector("#shot");const img=s&&s.querySelector(".shotwrap img");return img&&img.naturalWidth>300&&!/Собираем|очереди|Считаем/i.test(s.innerText);},null,{timeout:240000}).catch(()=>{});
await p2.locator("#shot button:has-text('Ракурс 2')").first().click(); await p2.waitForTimeout(2500); await p2.screenshot({path:`${OUT}/server-view-b.png`});
console.log("кадры:", JSON.stringify(await p2.evaluate(()=>[...document.querySelectorAll("#shot img")].map(i=>i.getAttribute("src")).filter(s=>/frames|scene3d/.test(s||"")).slice(0,3))));
await b.close();
