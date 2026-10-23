const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// «ЗАМЕНИТЬ · В МАГАЗИН» В ОДНУ СТРОКУ (demo-26 Г, снимок владельца 23.10, iPhone SE): в списке окна варианта (мебель, декор, мягкое —
// одна разметка; избранное открывает то же окно) пара действий стоит одной строкой, внутри ряда, не наезжает на цену и название —
// и с ценами в 6–7 знаков (999 999 ₽, 1 249 990 ₽; подставляются в строки списка), на RU и EN. Платного нет, на сервер ничего не пишется.
//   BASE=http://127.0.0.1:8790/demo/ OUT=<папка/> [V=2] [TAG=after] node tools/ops/demo-walk/row-acts-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').tmpdir()+'/').replace(/\/?$/,'/');
const V=+(process.env.V||2), TAG=process.env.TAG||'run'; fs.mkdirSync(OUT,{recursive:true});
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i===undefined?'':' '+(typeof i==='string'?i:JSON.stringify(i))));
const BIG={ru:['999 999 ₽','1 249 990 ₽'], en:['£999,999','£1,249,990']};
// по строке списка: действия в одну строку (верх «В магазин» — на линии кнопки), внутри ряда; цена и название не пересекаются с действиями
const MEASURE=`(()=>[...document.querySelectorAll('#shotbody .pinlist .row')].map(row=>{const q=s=>row.querySelector(s), r=e=>e?e.getBoundingClientRect():null;
  const a=q('.acts'), btn=a&&a.querySelector('button'), link=a&&a.querySelector('a'), pr=r(q('.p')), nm=r(q('.t b')), rr=r(row), ar=r(a);
  const kids=[btn,link].filter(Boolean).map(r);
  // одна строка — по самому тексту (низ букв «Заменить» и «В магазин» на одной линии ±3 px): коробка кнопки выше текста (44 px)
  const txt=e=>{const g=document.createRange(); g.selectNodeContents(e); return g.getBoundingClientRect();}, tb=[btn,link].filter(Boolean).map(txt);
  const oneLine=tb.length<2||Math.abs(tb[0].bottom-tb[1].bottom)<=3;
  const inside=kids.every(k=>k.right<=rr.right+0.5&&k.left>=rr.left-0.5), cross=(x,y)=>!!x&&!!y&&x.left<y.right&&y.left<x.right&&x.top<y.bottom&&y.top<x.bottom;
  return {name:(q('.t b')||{}).innerText, price:(q('.p')||{}).innerText, n:kids.length, oneLine, inside, overPrice:kids.some(k=>cross(k,pr)), overName:kids.some(k=>cross(k,nm)),
    priceIn:!!pr&&pr.right<=rr.right+0.5, actsH:ar?Math.round(ar.height):0, rowH:Math.round(rr.height), w:kids.map(k=>Math.round(k.width))};}))()`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const errs=[];
  for(const lang of ['ru','en']){
    const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:lang==='en'?'en-GB':'ru-RU'});
    const p=await ctx.newPage(); p.on('pageerror',e=>errs.push(lang+': '+String(e)));
    await p.addInitScript(()=>{try{localStorage.setItem('remlab-sheet-hint-v1','1')}catch(e){}});
    await p.goto(BASE+'?lang='+lang+'&live=0',{waitUntil:'load',timeout:120000});
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(1500);
    await p.evaluate(v=>vwOpenVariant(v),V);
    await p.waitForFunction(()=>document.querySelectorAll('#shotbody .pinlist .row').length>2,null,{timeout:60000}); await p.waitForTimeout(1200);
    // шторка — раскрыта, как на снимке владельца
    await p.evaluate(()=>{const x=[...document.querySelectorAll('#shot button')].find(e=>/Мебель и|Furniture/.test(e.innerText)); if(x)x.click();}); await p.waitForTimeout(1200);
    const shot=async n=>{for(let i=0;i<4;i++){try{await p.screenshot({path:`${OUT}${TAG}-${W}-${lang}-${n}.png`,timeout:20000,animations:'disabled'});return;}catch(e){await p.waitForTimeout(1500);}}};
    const check=async(label)=>{const m=await p.evaluate(MEASURE), bad=m.filter(x=>x.n&&(!x.oneLine||!x.inside||x.overPrice||x.overName||!x.priceIn));
      ok(`${lang} ${label}: «Заменить · В магазин» в одну строку, внутри ряда, без наезда на цену и название (${m.length} строк)`,m.length>0&&!bad.length,bad.length?bad:m.map(x=>x.price).join(' | '));
      return m;};
    const real=await check('цены как есть');
    await p.evaluate(()=>{const x=[...document.querySelectorAll('#shotbody .pinlist .row')].find(r=>/Риббл|Ribble/i.test(r.innerText))||document.querySelector('#shotbody .pinlist .row'); x.scrollIntoView({block:'center'});});
    await p.waitForTimeout(400); await shot('real');
    // цены 6–7 знаков — по очереди в каждой строке
    await p.evaluate(big=>document.querySelectorAll('#shotbody .pinlist .row .p').forEach((e,i)=>{e.textContent=big[i%2];}),BIG[lang]);
    await p.waitForTimeout(300);
    const big=await check('цены 999 999 и 1 249 990');
    // декор и мягкое — те же строки (`data-rep` декора), отдельный снимок конца списка
    await shot('big');
    await p.evaluate(()=>{const rows=document.querySelectorAll('#shotbody .pinlist .row'); rows[rows.length-1].scrollIntoView({block:'center'});}); await p.waitForTimeout(400);
    await shot('big-end');
    R.push(`ИНФО ${lang}: высота ряда ${[...new Set(big.map(x=>x.rowH))].join('/')} px, строки действий ${[...new Set(big.map(x=>x.actsH))].join('/')} px; ширины пары ${JSON.stringify(real[0]&&real[0].w)}`);
    await ctx.close();}
  ok('ошибок на странице нет',!errs.length,errs);
  console.log(R.join('\n')); fs.writeFileSync(`${OUT}${TAG}-${W}.log`,R.join('\n')+'\n'); await b.close();
  process.exit(R.some(x=>x.startsWith('FAIL'))?1:0);})().catch(e=>{console.error(e);process.exit(2);});
