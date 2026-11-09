// Страница тура пробы (план agent-trial-08): тот же HTML, что `/demo`, плюс «песочница» первым скриптом в `<head>` —
// выполняется ДО любого кода страницы (первый скрипт читает адрес, `?s=` и хранилище раньше, чем придут данные).
// Режим показа включается полем данных `D.trial`; здесь — только то, что должно действовать всегда и с первого байта.

import { TOKEN_RE } from "@/lib/token";

/** Что нельзя делать со страницы пробы никогда: любые ручки `/api/*` (кадры, заявка менеджеру, коллекции, счётчики) и реестр кадров. */
const BLOCK = String.raw`/^\/(?:api|test\/share)(?:\/|$)/`;

/** Две ссылки задания: агент смотрит без опроса, покупатель начинает с опроса. Ключ правки `k` (Р1) — только в ссылке агента
 *  покупатель его никогда не получает. Копируются только на странице ожидания `/try/<id>` — в самом туре блока ссылок нет (T-20261109-35). */
export const tourLinks = (id: string, k?: string | null): { agent: string; buyer: string } => ({
  agent: `/try/${id}/tour/?quiz=0${k && TOKEN_RE.test(k) ? `&k=${k}` : ""}`,
  buyer: `/try/${id}/tour/?quiz=1`,
});

/** Единственная ручка `/api/*`, которую песочница пропускает, — «Обустроить» ЭТОГО задания и только через fetch (право — ключом на сервере). */
export const rebuildPath = (id: string): string => `/api/trial/${id}/rebuild`;

/** `version` — номер результата на момент отдачи HTML: страница опрашивает `version.json` и обновляется, когда он вырастет. */
export function injectTour(html: string, id: string, version = 0): string {
  if (!TOKEN_RE.test(id)) throw new Error("bad id");
  const m = html.match(/<head[^>]*>/i);
  if (!m || m.index === undefined) throw new Error("no head");
  const prefix = `trial:${id}:`;
  const boot = `<script>(function(){
window.__TOUR_VER=${Number.isInteger(version) ? version : 0};
var PRE=${JSON.stringify(prefix)};
if(!/\\/$/.test(location.pathname))history.replaceState(history.state,'',location.pathname+'/'+location.search+location.hash);
var P=Storage.prototype,G=P.getItem,S=P.setItem,R=P.removeItem,K=P.key,L=Object.getOwnPropertyDescriptor(P,'length');
function own(s){var o=[],n=L.get.call(s),i,k;for(i=0;i<n;i++){k=K.call(s,i);if(k&&k.indexOf(PRE)===0)o.push(k);}return o;}
P.getItem=function(k){return G.call(this,PRE+k);};
P.setItem=function(k,v){return S.call(this,PRE+k,v);};
P.removeItem=function(k){return R.call(this,PRE+k);};
P.key=function(i){var k=own(this)[i];return k==null?null:k.slice(PRE.length);};
P.clear=function(){own(this).forEach(function(k){R.call(this,k);},this);};
Object.defineProperty(P,'length',{configurable:true,enumerable:true,get:function(){return own(this).length;}});
var BLOCK=${BLOCK};
var OK=${JSON.stringify(rebuildPath(id))};
function bad(u,ok){try{var x=new URL(String(u),document.baseURI);return x.origin===location.origin&&BLOCK.test(x.pathname)&&!(ok&&x.pathname===OK&&!x.search);}catch(e){return false;}}
var F=window.fetch;
window.fetch=function(i,o){if(bad(i&&i.url||i,1))return Promise.resolve(new Response('{"ok":false,"error":"trial"}',{status:403,headers:{'content-type':'application/json'}}));return F.call(window,i,o);};
if(navigator.sendBeacon){var B=navigator.sendBeacon.bind(navigator);navigator.sendBeacon=function(u,d){return bad(u)?true:B(u,d);};}
})();</script>`;
  const at = m.index + m[0].length;
  return html.slice(0, at) + boot + html.slice(at);
}
