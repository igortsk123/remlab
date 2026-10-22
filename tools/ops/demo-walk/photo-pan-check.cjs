const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ФОТО ПАЛЬЦЕМ И РАКУРС КНОПКАМИ (demo-22 п.2–3, T-20261022-12/1). Телефон: в «Фото» картинка во всю высоту области и шире её,
// двигается нативной прокруткой (`.vpan`, без обработчиков движения), старт — окно превью вида (`crop` ближайшей пропорции к
// фактической области); свайп ракурс не листает; тап — во весь экран, там ракурс — кнопками. Компьютер — фото целиком, как было.
// Замер: фактическая пропорция области фото и какое окно превью выбрано. Платного нет: заказ фото и коллекции подменены.
//   DATA=<demo-data.json с crop> FROZEN=1 BASE=https://remont-lab.online/demo/ OUT=<папка/> node tools/ops/demo-walk/photo-pan-check.cjs 375x667
// DATA — подменить данные витрины; FROZEN=1 — дописать окна превью из DATA в записи реестра кадров (как сохранит сервер)
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const DATA=process.env.DATA?JSON.parse(fs.readFileSync(process.env.DATA,'utf8')):null;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i===undefined?'':typeof i==='string'?i:JSON.stringify(i)));
const PAN=`(()=>{const p=document.querySelector('#shot .vpan'), im=p&&p.querySelector('img.vmain'); if(!p||!im)return null;
  const r=p.getBoundingClientRect(), ir=im.getBoundingClientRect(), s=shots[shotAt]||{}, cs=getComputedStyle(p);
  return {w:Math.round(r.width), h:Math.round(r.height), aspect:+(r.width/r.height).toFixed(3), imgW:Math.round(ir.width), imgH:Math.round(ir.height),
    sl:Math.round(p.scrollLeft), max:p.scrollWidth-p.clientWidth, crop:p.dataset.crop||'', ovx:cs.overflowX, ta:cs.touchAction,
    fc:p._fc==null?null:+p._fc.toFixed(3), cam:s.camera||'C1', frozen:!!((s.cams||[]).find(c=>c&&c.name===(s.camera||'C1')&&c.crop)),
    fit:getComputedStyle(im).objectFit, photo:VW.photo, mode:VW.mode, zoom:!!(document.getElementById('vzoom')||{classList:{contains:()=>false}}).classList.contains('on')};})()`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
  const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/warm/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now(),id:'f'+Date.now()})}));
  await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:60})}));
  // избранное — без записи на сервер: коллекция живёт в пробе
  const COLL=new Map();
  const J=(r,o,st)=>r.fulfill({status:st||200,contentType:'application/json',body:JSON.stringify(o)});
  await p.route(/\/api\/collections/,async r=>{const q=r.request(), m=q.method(), u=new URL(q.url()), id=(u.pathname.match(/collections\/([^/?]+)/)||[])[1];
    if(m==='POST'){const snap=JSON.parse(q.postData()||'{}'), nid='probe'+(COLL.size+1); COLL.set(nid,{...snap,id:nid,editToken:'t'});
      return J(r,{ok:true,id:nid,editToken:'t',url:'/c/'+nid});}
    if(m==='PATCH'){const c=COLL.get(id)||{}; Object.assign(c,JSON.parse(q.postData()||'{}')); return J(r,{ok:true,collection:c});}
    if(m==='DELETE'){COLL.delete(id); return J(r,{ok:true});}
    if(!id){const ids=(u.searchParams.get('ids')||'').split(',').filter(Boolean); return J(r,{ok:true,collections:ids.map(i=>COLL.get(i)).filter(Boolean)});}
    return COLL.has(id)?J(r,{ok:true,collection:COLL.get(id)}):J(r,{ok:false,error:'нет'},404);});
  if(DATA)await p.route(u=>new URL(u).pathname.endsWith('/demo/demo-data.json'),r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(DATA)}));
  if(DATA&&process.env.FROZEN)await p.route(/\/test\/share\/shots\.json/,async r=>{const res=await r.fetch(); const j=await res.json();
    const near=(a,c)=>Math.abs(a.x-c.x)<=2&&Math.abs(a.y-c.y)<=2;
    j.forEach(rec=>(rec.cams||[]).forEach(c=>{for(const v of DATA.variants){const d=(v.cams||[]).find(x=>x.name===c.name&&near(x,c)&&x.crop); if(d){c.crop=d.crop; break;}}}));
    await r.fulfill({response:res,body:JSON.stringify(j),headers:{...res.headers(),'content-type':'application/json'}});});
  await p.goto(BASE+'?lang=ru&live=0',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&SHOTS_LOADED",null,{timeout:90000}).catch(()=>{});
  await p.waitForTimeout(1500);
  if(!PHONE){await p.screenshot({path:OUT+`pan-${W}-0-home.png`});
    const t=await p.evaluate(()=>{const e=document.querySelector('.hm-rooms, .hm-room'); return e?Math.round(e.getBoundingClientRect().top+scrollY-80):600;});
    await p.evaluate(y=>scrollTo(0,y),t); await p.waitForTimeout(800); await p.screenshot({path:OUT+`pan-${W}-0-home-cards.png`}); await p.evaluate(()=>scrollTo(0,0));}
  // окно варианта с фото: первый вариант, у которого есть реалистичные кадры ЭТОЙ расстановки
  const vi=await p.evaluate(async()=>{for(let i=0;i<allVariants().length;i++){await vwOpenVariant(i); await new Promise(r=>setTimeout(r,700));
      if(vwRealShots().length>1){vwMode('photo'); return i;}} return -1;});
  ok('есть вариант с двумя фото',vi>=0,vi);
  await p.waitForFunction(()=>{const im=document.querySelector('#shot .vpan img.vmain'); return im&&im.complete&&im.naturalWidth>0;},null,{timeout:60000}).catch(()=>{});
  await p.waitForTimeout(1200);
  const g0=await p.evaluate(PAN); ok('0 фото на месте',!!g0,g0);
  if(PHONE){
    ok('0 область фото — фактическая пропорция',!!g0&&g0.aspect>0.4&&g0.aspect<0.8,g0&&{w:g0.w,h:g0.h,aspect:g0.aspect});
    ok('0 фото во всю высоту и шире области (есть что двигать)',!!g0&&g0.imgH===g0.h&&g0.max>50,g0&&{imgW:g0.imgW,imgH:g0.imgH,max:g0.max});
    ok('0 нативная прокрутка по горизонтали',!!g0&&g0.ovx==='auto'&&/pan-x/.test(g0.ta),g0&&{ovx:g0.ovx,ta:g0.ta});
    // окно превью — ближайшей пропорции к области; старт — середина окна
    const exp=await p.evaluate(()=>{const pn=document.querySelector('#shot .vpan'), s=shots[shotAt], a=pn.clientWidth/pn.clientHeight, cr=vwCropOf(s,a);
      const Ws=pn.scrollWidth; return cr?{key:cr.key, x:cr.x, w:cr.w, want:Math.round(Math.max(0,Math.min(pn.scrollWidth-pn.clientWidth,(cr.x+cr.w/2)*Ws-pn.clientWidth/2)))}:null;});
    ok('0 старт — из окна превью вида',!!exp&&g0.crop===exp.key&&Math.abs(g0.sl-exp.want)<=2,{exp,sl:g0.sl,crop:g0.crop,frozen:g0.frozen});
    if(process.env.FROZEN)ok('0 окно превью — из записи кадра (сервер)',g0.frozen);
    // порядок источников окна: запись кадра → нынешняя точка того же имени → нет
    const src=await p.evaluate(()=>{const s=shots[shotAt], c0=(cams||[]).find(c=>c.name===(s.camera||'C1'));
      const fake={camera:s.camera, cams:[{...c0, crop:{'0.531':{x:0.01,y:0,w:0.3,h:1}}}]};
      const {crop:_c,...c1}=c0, old={camera:s.camera, cams:[{...c1, x:c1.x+50}]};
      return {own:(vwCropOf(fake,0.55)||{}).x, cur:!!vwCropOf({camera:s.camera,cams:[{...c0}]},0.55), other:vwCropOf(old,0.55)};});
    ok('0 окно: запись кадра важнее, кадр с другой точки — без окна',src.own===0.01&&src.other===null,src);
    // прослушки движения на полосе нет — двигает браузер (плавность не зависит от скрипта)
    const cdp=await ctx.newCDPSession(p);
    const {result}=await cdp.send('Runtime.evaluate',{expression:"document.querySelector('#shot .vpan')"});
    const {listeners}=await cdp.send('DOMDebugger.getEventListeners',{objectId:result.objectId});
    const types=listeners.map(l=>l.type);
    ok('0 на полосе нет обработчиков движения',!types.some(t=>/move|touchstart|wheel/.test(t)),types);
    await p.screenshot({path:OUT+`pan-${W}-1-start.png`});
    // свайп пальцем: сенсорные события CDP — как палец (прокрутка браузера, инерция)
    const swipe=async(x0,x1,y)=>{await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:x0,y}]});
      for(let k=1;k<=12;k++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x0+(x1-x0)*k/12,y}]}); await p.waitForTimeout(16);}
      await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]}); await p.waitForTimeout(900);};
    const yM=Math.round(g0.h/2);
    await swipe(300,120,yM); const g1=await p.evaluate(PAN);
    ok('1 свайп влево двигает фото, ракурс тот же, полный экран не открылся',g1.sl>g0.sl+20&&g1.photo===g0.photo&&g1.cam===g0.cam&&!g1.zoom,{from:g0.sl,to:g1.sl,photo:g1.photo,zoom:g1.zoom});
    await p.evaluate(()=>{const pn=document.querySelector('#shot .vpan'); pn.scrollLeft=Math.round((pn.scrollWidth-pn.clientWidth)/2);}); await p.waitForTimeout(400);
    await p.screenshot({path:OUT+`pan-${W}-2-middle.png`});
    for(let k=0;k<4;k++)await swipe(330,40,yM);
    const g2=await p.evaluate(PAN); ok('2 у правого края — упор',g2.sl>=g2.max-1&&g2.photo===g0.photo,{sl:g2.sl,max:g2.max});
    await p.screenshot({path:OUT+`pan-${W}-3-end.png`});
    for(let k=0;k<4;k++)await swipe(40,330,yM);
    const g3=await p.evaluate(PAN); ok('3 у левого края — упор, ракурс тот же',g3.sl<=1&&g3.photo===g0.photo,{sl:g3.sl});
    await p.screenshot({path:OUT+`pan-${W}-4-left.png`});
    // поворот/смена размера держит то же место фото
    const fc=g3.fc; await p.setViewportSize({width:W,height:H-40}); await p.waitForTimeout(600); const g4=await p.evaluate(PAN);
    ok('4 смена размера области — то же место фото',g4.fc!=null&&Math.abs(g4.fc-fc)<0.03,{before:fc,after:g4.fc});
    await p.setViewportSize({width:W,height:H}); await p.waitForTimeout(600);
    // тап — во весь экран; ракурс — кнопками
    await p.touchscreen.tap(Math.round(W/2),yM); await p.waitForTimeout(700);
  }else{
    ok('0 компьютер: фото целиком, полоса без прокрутки',g0.fit==='contain'&&g0.max<=1&&g0.ovx==='hidden',{fit:g0.fit,max:g0.max,ovx:g0.ovx});
    await p.screenshot({path:OUT+`pan-${W}-1-window.png`});
    const box=await p.evaluate(()=>{const r=document.querySelector('#shot .vpan').getBoundingClientRect(); return [r.left+r.width/2,r.top+r.height/2];});
    await p.mouse.move(box[0],box[1]); await p.mouse.down(); await p.mouse.move(box[0]-200,box[1],{steps:8}); await p.mouse.up(); await p.waitForTimeout(500);
    const g1=await p.evaluate(PAN); ok('1 протяжка мышью — ракурс тот же, полный экран не открылся',g1.photo===g0.photo&&!g1.zoom,{photo:g1.photo,zoom:g1.zoom});
    await p.mouse.click(box[0],box[1]); await p.waitForTimeout(700);
  }
  const z=await p.evaluate(()=>{const z=document.getElementById('vzoom'); return z&&{on:z.classList.contains('on'), at:z.dataset.at,
    btn:[...z.querySelectorAll('.vzcams button')].map(b=>({t:b.textContent,on:b.classList.contains('on'),r:(r=>[r.left,r.top,r.right,r.bottom].map(Math.round))(b.getBoundingClientRect())}))};});
  ok('5 тап — во весь экран, снизу кнопки ракурсов с подписями',!!z&&z.on&&z.btn.length===2&&z.btn.every(x=>x.t&&x.r[2]<=W&&x.r[0]>=0&&x.r[3]<=H),z);
  await p.evaluate(()=>{const h=document.querySelector('#vzoom .vzh'); if(h)h.remove();});
  await p.screenshot({path:OUT+`pan-${W}-5-full.png`});
  // свайп вбок во весь экран — ракурс не меняется
  if(PHONE){const yz=Math.round(H/2); await p.evaluate(([x0,x1,y])=>{const z=document.getElementById('vzoom'), ev=(t,x)=>z.dispatchEvent(new PointerEvent(t,{pointerId:7,clientX:x,clientY:y,bubbles:true,pointerType:'touch',isPrimary:true}));
      ev('pointerdown',x0); for(let k=1;k<=8;k++)ev('pointermove',x0+(x1-x0)*k/8); ev('pointerup',x1);},[320,40,yz]); await p.waitForTimeout(700);
    ok('5 свайп вбок во весь экран — ракурс тот же',await p.evaluate(at=>document.getElementById('vzoom').dataset.at===at,z.at));}
  const other=z&&z.btn.findIndex(x=>!x.on);
  if(other>=0){const src0=await p.evaluate(()=>document.querySelector('#vzoom img').src);
    await p.click(`#vzoom .vzcams button[data-zi="${other}"]`); await p.waitForTimeout(900);
    const z2=await p.evaluate(()=>({at:document.getElementById('vzoom').dataset.at, src:document.querySelector('#vzoom img').src}));
    ok('6 кнопка второго ракурса во весь экран — другой снимок',z2.at===String(other)&&z2.src!==src0,z2);
    await p.screenshot({path:OUT+`pan-${W}-6-full-other.png`});
    await p.click('#vzoom .vzx'); await p.waitForTimeout(900);
    const g5=await p.evaluate(PAN); ok('6 закрыл — окно на том же ракурсе',!!g5&&g5.photo===other&&g5.mode==='photo',g5&&{photo:g5.photo,cam:g5.cam});}
  // кнопки ракурсов в окне
  const before=await p.evaluate(()=>VW.photo);
  await p.click(`#vCams [data-cam="${before?0:1}"]`); await p.waitForTimeout(1200);
  const g6=await p.evaluate(PAN); ok('7 кнопка ракурса в окне — другой снимок',!!g6&&g6.photo!==before,g6&&{photo:g6.photo,cam:g6.cam,crop:g6.crop,sl:g6.sl});
  await p.screenshot({path:OUT+`pan-${W}-7-cam-button.png`});
  // избранное: карточка — превью кадра (без записи на сервер)
  const fav=await p.evaluate(async()=>{try{if(!window.__fav)return 'нет __fav'; document.getElementById('vFav').click(); await new Promise(r=>setTimeout(r,500));
      const okb=document.getElementById('favOk'); if(okb)okb.click(); await new Promise(r=>setTimeout(r,1500)); return window.__fav.list().length;}catch(e){return String(e);}});
  ok('8 избранное сохранено (подмена)',fav===1,fav);
  await p.evaluate(()=>{const x=document.getElementById('shotx'); if(x)x.click();}); await p.waitForTimeout(800);
  await p.evaluate(()=>{if(window.__basket)window.__basket.open(); const h=document.getElementById('favHead'); if(h)h.scrollIntoView({block:'start'});}); await p.waitForTimeout(1500);
  await p.screenshot({path:OUT+`pan-${W}-8-fav.png`});
  ok('ошибок страницы нет',!errs.length,errs.slice(0,3));
  fs.writeFileSync(OUT+`pan-${W}.log`,R.join('\n')+'\n'); console.log(R.join('\n')); await b.close();
})().catch(e=>{console.log('CRASH',e); fs.writeFileSync(OUT+`pan-${W}.log`,R.join('\n')+'\nCRASH '+e+'\n'); process.exit(1);});
