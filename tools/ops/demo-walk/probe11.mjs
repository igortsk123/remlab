import { chromium } from "@playwright/test";
const OUT=process.argv[2]; const BASE="https://remont-lab.online"; const b=await chromium.launch();
for (const [view,tag] of [[{width:1280,height:900},"desk"],[{width:390,height:844},"phone"]]) {
  for (let i=0;i<5;i++) {
    const ctx=await b.newContext({viewport:view,locale:"ru-RU",isMobile:view.width<500,hasTouch:view.width<500}); const pg=await ctx.newPage();
    await pg.goto(BASE+"/demo/?live=force",{waitUntil:"networkidle",timeout:60000}); const cards=pg.locator("button[data-swap]"); if (await cards.count()<=i) { await ctx.close(); continue; }
    await cards.nth(i).click(); await pg.waitForTimeout(9000); await pg.screenshot({path:`${OUT}/${tag}-${i}-a1.png`}); console.log("экран",`${tag}-${i}-a1`); await ctx.close();
  }
}
await b.close();
