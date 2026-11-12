const {demoUrl}=require('../demo-url.cjs');
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// КРАЙ КОВРА ПРИ ДВИЖЕНИИ КАМЕРЫ (T-20261112-33, владелец 12.11: «когда двигаю — полоска белая мерцает под ковром»). Живое окно 3D
// гостиной демо: камера стоит у переднего края ковра и медленно сдвигается (по 1 см и 0,2°) — кадры подряд; мерцание видно как
// «рваная» полоса у края, меняющаяся от кадра к кадру. Бесплатно, нейросеть не зовётся.
//   OUT=<папка> node tools/ops/demo-walk/rug-edge-check.cjs 375x667            — прод как есть («до»)
//   OUT=<папка> ENGINE=<папка со scene.json и scene.*.js> node … 375x667          — движок из своей сборки поверх прода («после»)
//   URL=https://remont-lab.online/try/<id>/tour/ — тур пробы вместо демо
//   VARIANT=<n> — один вариант (по умолчанию все, где есть ковёр); BROWSER=webkit — WebKit вместо Chromium
const OUT=(process.env.OUT||require('os').tmpdir())+'/', ENGINE=process.env.ENGINE; const [W,H]=(process.argv[2]||'375x667').split('x').map(Number);
const PHONE=W<700, STEPS=+(process.env.STEPS||6), BACK=+(process.env.BACK||60);   // BACK — см от края ковра до камеры
fs.mkdirSync(OUT,{recursive:true});
(async()=>{const kind=process.env.BROWSER==='webkit'?pw.webkit:pw.chromium;
const b=await kind.launch(kind===pw.chromium?{args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']}:{});
const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE&&kind===pw.chromium,hasTouch:PHONE,locale:'ru-RU'});
const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
if(ENGINE){const man=JSON.parse(fs.readFileSync(ENGINE+'/scene.json','utf8'));
  await p.route(/\/lib\/scene\.json/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(man)}));
  await p.route(new RegExp('/lib/'+man.file.replace(/\./g,'\\.')),r=>r.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(ENGINE+'/'+man.file,'utf8')}));
  console.log('движок', man.file);}
// URL=<адрес тура пробы> — тот же обход в туре (`/try/<id>/tour/`): страница та же, движок тот же
await p.goto(demoUrl((process.env.URL||'https://remont-lab.online/demo/')+'?live=force&lang=ru&v='+Date.now()),{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&typeof allVariants==='function'&&allVariants().length>0",null,{timeout:90000});
const n=await p.evaluate('allVariants().length'); const only=process.env.VARIANT!=null?[+process.env.VARIANT]:[...Array(n).keys()];
for(const i of only){
  const r=await p.evaluate(async([i,BACK])=>{pickVariant(i); openLiveWindow(); if(VW.mode!=='walk')vwMode('walk');
    for(let k=0;k<600&&!(LIVE.scene&&LIVE.state==='ready');k++)await new Promise(ok=>setTimeout(ok,300));
    if(!LIVE.scene)return {error:'3D не открылась'};
    const rug=items.find(it=>String(it.role||'').startsWith('ковёр')); if(!rug)return {skip:'нет ковра'};
    // камера — на линии «точка съёмки → центр ковра», в 60 см перед его краем: край ковра крупно в нижней половине кадра
    const c=loadCams()[0], base=camPoseOf(c), dx=rug.x-c.x, dy=rug.y-c.y, L=Math.hypot(dx,dy)||1, half=Math.max(rug.w,rug.d)/2;
    const back=Math.min(L, half+BACK); const x0=rug.x-dx/L*back, y0=rug.y-dy/L*back;
    return {rug:{x:rug.x,y:rug.y,w:rug.w,d:rug.d,rot:rug.rot,msid:rug.sku&&rug.sku.msid,title:rug.title||rug.name}, pose:{...base,x:x0,y:y0}, cam:[c.x,c.y,c.rot]};
  },[i,BACK]);
  if(r.error||r.skip){console.log(`вариант ${i}:`,r.error||r.skip); continue;}
  console.log(`вариант ${i}: ковёр`,JSON.stringify(r.rug),'поза',JSON.stringify(r.pose));
  for(let k=0;k<STEPS;k++){
    const pose={...r.pose,x:r.pose.x+k*1.0,y:r.pose.y+k*0.6,rot:r.pose.rot+k*0.2};
    await p.evaluate((pose)=>{LIVE.scene.goToPose(pose);},pose); await p.waitForTimeout(1500);
    await p.screenshot({path:`${OUT}v${i}-${W}-k${k}.png`});
  }
  // тот же край в снимке движка (`capture`, полный кадр с тенями — как карточка/коллекция)
  const shots=await p.evaluate(async(pose)=>{const out=[]; const blob2url=(bl)=>new Promise(ok=>{const fr=new FileReader(); fr.onload=()=>ok(fr.result); fr.readAsDataURL(bl);});
    for(let k=0;k<3;k++){const res=await LIVE.scene.capture([{...pose,x:pose.x+k*1.0,y:pose.y+k*0.6,rot:pose.rot+k*0.2}],1280,800); out.push(await blob2url(res.frames[0]));}
    return out;},r.pose);
  shots.forEach((u,k)=>fs.writeFileSync(`${OUT}v${i}-${W}-cap${k}.jpg`,Buffer.from(u.split(',')[1],'base64')));
}
console.log('errs',errs.slice(0,3)); await b.close();})().catch(e=>{console.error(e);process.exit(1);});
