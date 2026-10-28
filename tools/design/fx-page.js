// ПОМОЩНИК В СТРАНИЦЕ ДЛЯ ВЫГРУЗКИ В ФИГМУ (design-01-figma-export): подключается capture.mjs через addInitScript.
// Ничего в странице не меняет, кроме временных data-fx* меток на время снимка (снимаются сразу).
// window.__fx.snapshot()   → статичный HTML всей страницы «как на экране» (без скриптов, абсолютные адреса, липкое и прокрутка заморожены)
// window.__fx.grab(sel,o)  → образец компонента: outerHTML + цепочка предков + размеры + замер стилей (для кита и figma-spec)
// window.__fx.texts()      → текстовые стили видимых элементов (кегль/вес/межстрочный)
// window.__fx.tokenProbe() → значения токенов :root в том виде, как их отдаёт getComputedStyle (для сопоставления)
(() => {
  if (window.__fx) return;
  const ABS = (u) => { try { return u && !/^(data:|blob:|#|javascript:|mailto:|tel:)/.test(u) ? new URL(u, location.href).href : u; } catch (e) { return u; } };
  const absStyle = (s) => s && s.replace(/url\((['"]?)([^'")]+)\1\)/g, (m, q, u) => `url("${ABS(u)}")`);
  let cvN = 0;
  // метки на живых узлах: холсты (3D) — node снимет их скриншотом; blob-картинки — заменим на data:
  async function blobToData(u) { try { const b = await (await fetch(u)).blob(); return await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(b); }); } catch (e) { return ""; } }
  function markCanvases(root) {
    const out = [];
    root.querySelectorAll("canvas").forEach((c) => { const r = c.getBoundingClientRect(); if (r.width < 4 || r.height < 4) return;
      if (!c.dataset.fxcv) c.dataset.fxcv = "cv" + (++cvN); out.push({ id: c.dataset.fxcv, w: Math.round(r.width), h: Math.round(r.height) }); });
    if (root.tagName === "CANVAS") { const c = root; if (!c.dataset.fxcv) c.dataset.fxcv = "cv" + (++cvN); out.push({ id: c.dataset.fxcv }); }
    return out;
  }
  async function cleanClone(clone, live) {
    // адреса — абсолютные; ленивые картинки — сразу; скрипты и предзагрузки — прочь (в конце: списки живых и копий идут по одному индексу)
    const lives = live ? [live, ...live.querySelectorAll("*")] : null; const clones = [clone, ...clone.querySelectorAll("*")];
    for (let i = 0; i < clones.length; i++) {
      const e = clones[i], L = lives && lives[i];
      if (e.tagName === "IMG") {
        const src = L ? (L.currentSrc || L.src) : e.getAttribute("src");
        if (src && src.startsWith("blob:")) e.setAttribute("src", await blobToData(src)); else if (src) e.setAttribute("src", ABS(src));
        if (e.getAttribute("srcset")) e.setAttribute("srcset", e.getAttribute("srcset").split(",").map((p) => { const [u, d] = p.trim().split(/\s+/); return ABS(u) + (d ? " " + d : ""); }).join(", "));
        e.removeAttribute("loading");
      }
      if (e.tagName === "A" && e.getAttribute("href")) e.setAttribute("href", ABS(e.getAttribute("href")));
      if ((e.tagName === "image" || e.tagName === "use") && e.getAttribute) for (const a of ["href", "xlink:href"]) { const v = e.getAttribute(a); if (v && !v.startsWith("#")) e.setAttribute(a, ABS(v)); }
      if (e.tagName === "LINK" && e.getAttribute("href")) e.setAttribute("href", ABS(e.getAttribute("href")));
      if (e.tagName === "SOURCE" && e.getAttribute("src")) e.setAttribute("src", ABS(e.getAttribute("src")));
      if (e.getAttribute && e.getAttribute("style")) e.setAttribute("style", absStyle(e.getAttribute("style")));
      if (L && (e.tagName === "INPUT" || e.tagName === "TEXTAREA")) { if (L.type === "checkbox" || L.type === "radio") { if (L.checked) e.setAttribute("checked", ""); else e.removeAttribute("checked"); } else e.setAttribute("value", L.value); }
      if (L && e.tagName === "CANVAS") { const r = L.getBoundingClientRect(); const im = document.createElement("img"); im.setAttribute("data-fxcv-src", L.dataset.fxcv || "");
        im.setAttribute("alt", "3D"); im.className = L.className; if (L.getAttribute("style")) im.setAttribute("style", L.getAttribute("style"));
        // правила страницы для <img> внутри кадра (видимость/позиция фото) не должны прятать снимок холста — вычисленное холста, inline !important
        const cs = getComputedStyle(L); for (const k of ["position", "top", "left", "right", "bottom", "z-index", "border-radius", "opacity", "display", "transform"]) im.style.setProperty(k, cs.getPropertyValue(k), "important");
        im.style.setProperty("visibility", "visible", "important"); im.style.setProperty("width", r.width + "px", "important"); im.style.setProperty("height", r.height + "px", "important"); im.style.setProperty("object-fit", "cover", "important"); im.style.setProperty("max-width", "none", "important");
        e.replaceWith(im); }
      // обработчики событий из атрибутов (onclick=…) — это тоже скрипт
      if (e.attributes) [...e.attributes].forEach((a) => { if (/^on/i.test(a.name)) e.removeAttribute(a.name); });
    }
    clone.querySelectorAll("style").forEach((s) => { s.textContent = absStyle(s.textContent); });
    clone.querySelectorAll("script,noscript,link[rel=modulepreload],link[rel=preload],link[rel=prefetch],base").forEach((e) => e.remove());
    if (clone.matches && clone.matches("script")) return document.createComment("script");
    return clone;
  }
  const isFixed = (e) => { for (let x = e; x && x !== document.documentElement; x = x.parentElement) { const p = getComputedStyle(x).position; if (p === "fixed") return true; } return false; };
  async function snapshot(meta) {
    const live = document.documentElement; const sy = scrollY;
    const cvs = markCanvases(document.body);
    // липкие, которые сейчас прилипли, и прокрученные внутри области
    const stick = [], scr = [];
    document.querySelectorAll("body *").forEach((e) => {
      const cs = getComputedStyle(e); if (cs.display === "none") return;
      if (cs.position === "sticky") { const r = e.getBoundingClientRect(), t = parseFloat(cs.top); const par = e.parentElement;
        // в прокрутке страницы (не внутри своей прокручиваемой области) и сидит на своём top
        if (sy > 0 && !isFixed(e) && !isNaN(t) && Math.abs(r.top - t) < 1.5 && r.bottom > 0) { e.dataset.fxstick = stick.length; stick.push({ top: r.top, left: r.left, w: r.width, h: r.height, mt: cs.marginTop, mb: cs.marginBottom }); } }
      if (e.scrollTop > 0 && /auto|scroll|hidden|clip/.test(cs.overflowY) && e.scrollHeight > e.clientHeight) { e.dataset.fxscroll = e.scrollTop; scr.push(e.scrollTop); }
      if (e.scrollLeft > 0 && /auto|scroll|hidden|clip/.test(cs.overflowX) && e.scrollWidth > e.clientWidth) { e.dataset.fxscrollx = e.scrollLeft; }
    });
    const clone = live.cloneNode(true);
    await cleanClone(clone, live);
    // замораживаем: тело сдвинуто на прокрутку (как делает сама страница при открытом окне — lockPage), липкие — fixed на своих местах
    const body = clone.querySelector("body");
    const bodyFixed = getComputedStyle(document.body).position === "fixed";
    if (sy > 0 && !bodyFixed) { body.style.position = "fixed"; body.style.top = -sy + "px"; body.style.left = "0"; body.style.right = "0"; }
    clone.querySelectorAll("[data-fxstick]").forEach((e) => { const s = stick[+e.dataset.fxstick];
      const ph = document.createElement("div"); ph.setAttribute("aria-hidden", "true"); ph.style.cssText = `height:${s.h}px;margin-top:${s.mt};margin-bottom:${s.mb};visibility:hidden`;
      e.before(ph); e.style.position = "fixed"; e.style.top = s.top + "px"; e.style.left = s.left + "px"; e.style.width = s.w + "px"; e.style.margin = "0"; e.style.boxSizing = "border-box"; e.removeAttribute("data-fxstick"); });
    clone.querySelectorAll("[data-fxscroll]").forEach((e) => { const k = e.firstElementChild; e.style.overflowY = "hidden"; if (k) k.style.marginTop = `-${e.dataset.fxscroll}px`; e.removeAttribute("data-fxscroll"); });
    clone.querySelectorAll("[data-fxscrollx]").forEach((e) => { const k = e.firstElementChild; e.style.overflowX = "hidden"; if (k) k.style.marginLeft = `-${e.dataset.fxscrollx}px`; e.removeAttribute("data-fxscrollx"); });
    document.querySelectorAll("[data-fxstick],[data-fxscroll],[data-fxscrollx]").forEach((e) => { delete e.dataset.fxstick; delete e.dataset.fxscroll; delete e.dataset.fxscrollx; });
    const head = clone.querySelector("head");
    const m = document.createElement("meta"); m.name = "fx-snapshot"; m.content = JSON.stringify({ ...(meta || {}), url: location.href, viewport: [innerWidth, innerHeight], scrollY: sy, at: new Date().toISOString() });
    head.prepend(m);
    const c = document.createComment(" Статичный снимок /demo для импорта в Фигму (html.to.design): без скриптов, адреса абсолютные, прокрутка и липкие элементы заморожены. Продукт: remont-lab.online/demo/ ");
    head.prepend(c);
    return { html: "<!doctype html>\n" + clone.outerHTML, canvases: cvs };
  }
  // ——— замер стилей узла (только не-умолчания, чтобы JSON был коротким) ———
  const PICK = ["display", "position", "flexDirection", "flexWrap", "justifyContent", "alignItems", "alignSelf", "flexGrow", "flexShrink", "flexBasis", "rowGap", "columnGap",
    "gridTemplateColumns", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "backgroundColor", "backgroundImage", "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
    "borderTopStyle", "borderTopColor", "borderRightColor", "borderBottomColor", "borderLeftColor", "borderTopLeftRadius", "borderTopRightRadius", "borderBottomRightRadius", "borderBottomLeftRadius", "boxShadow", "opacity",
    "color", "fontSize", "fontWeight", "lineHeight", "fontFamily", "letterSpacing", "textAlign", "textTransform", "textDecorationLine", "whiteSpace", "textOverflow", "overflowX", "overflowY", "backdropFilter", "zIndex", "objectFit", "aspectRatio", "transform", "minHeight", "minWidth", "maxWidth"];
  const DEF = { display: "block", position: "static", flexDirection: "row", flexWrap: "nowrap", justifyContent: "normal", alignItems: "normal", alignSelf: "auto", flexGrow: "0", flexShrink: "1", flexBasis: "auto",
    rowGap: "normal", columnGap: "normal", gridTemplateColumns: "none", paddingTop: "0px", paddingRight: "0px", paddingBottom: "0px", paddingLeft: "0px", backgroundColor: "rgba(0, 0, 0, 0)", backgroundImage: "none",
    borderTopWidth: "0px", borderRightWidth: "0px", borderBottomWidth: "0px", borderLeftWidth: "0px", borderTopStyle: "none", boxShadow: "none", opacity: "1", letterSpacing: "normal", textAlign: "start", textTransform: "none",
    textDecorationLine: "none", whiteSpace: "normal", textOverflow: "clip", overflowX: "visible", overflowY: "visible", backdropFilter: "none", zIndex: "auto", objectFit: "fill", aspectRatio: "auto", transform: "none", minHeight: "auto", minWidth: "auto", maxWidth: "none",
    borderTopLeftRadius: "0px", borderTopRightRadius: "0px", borderBottomRightRadius: "0px", borderBottomLeftRadius: "0px" };
  const nm = (e) => e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + (typeof e.className === "string" && e.className.trim() ? "." + e.className.trim().split(/\s+/).join(".") : "");
  function styleOf(e, parentCs) {
    const cs = getComputedStyle(e), o = {};
    for (const k of PICK) { const v = cs[k]; if (v === undefined) continue;
      if (/^border(Top|Right|Bottom|Left)Color$/.test(k)) { const w = cs[k.replace("Color", "Width")]; if (w === "0px") continue; }
      if (k === "borderTopStyle" && cs.borderTopWidth === "0px") continue;
      // наследуемые — только если отличаются от родителя
      if (["color", "fontSize", "fontWeight", "lineHeight", "fontFamily", "letterSpacing", "textAlign", "textTransform", "whiteSpace"].includes(k)) { if (parentCs && parentCs[k] === v) continue; }
      else if (DEF[k] === v) continue;
      o[k] = v; }
    return o;
  }
  const ownText = (e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").replace(/\s+/g, " ").trim();
  // ——— дерево для Фигмы (п.5 плана): без обрезки глубины; текст — с рамкой самого текста и числом строк; значки — svg целиком
  // (цвета из вычисленных стилей); фото — полный адрес; холст и встроенные картинки — меткой, снимок делает capture.mjs ———
  const SVG_PROPS = ["fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "opacity", "fill-opacity", "stroke-opacity", "fill-rule"];
  function svgText(e) {
    const c = e.cloneNode(true); const L = [e, ...e.querySelectorAll("*")], C = [c, ...c.querySelectorAll("*")];
    for (let i = 0; i < C.length; i++) { const cs = getComputedStyle(L[i]); for (const p of SVG_PROPS) { const v = cs.getPropertyValue(p); if (v) C[i].setAttribute(p, v); } C[i].removeAttribute("class"); C[i].removeAttribute("style"); }
    const r = e.getBoundingClientRect(); c.setAttribute("width", r.width); c.setAttribute("height", r.height); c.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    return c.outerHTML;
  }
  // строчные обёртки (inline-flex/inline-block без фона/рамки, напр. «Доплата …» внутри абзаца) — тоже часть сплошного текста
  const BLOCKY = (cs) => !/^inline(-flex|-block)?$/.test(cs.display) || cs.backgroundColor !== "rgba(0, 0, 0, 0)" || cs.borderTopWidth !== "0px" || cs.position !== "static" || cs.backgroundImage !== "none";
  // элемент — «сплошной текст»: внутри только текст и строчные теги без рамок/фона (b, span, a…) → один текстовый слой с кусками стиля
  function richOnly(e) { for (const k of e.querySelectorAll("*")) { if (/^(IMG|SVG|svg|CANVAS|INPUT|BUTTON|BR)$/.test(k.tagName) || BLOCKY(getComputedStyle(k))) return false; } return true; }
  function textBox(nodes) {
    const rg = document.createRange(); let L = 1e9, T = 1e9, Rr = -1e9, B = -1e9; const tops = new Set();
    for (const t of nodes) { rg.selectNodeContents(t); for (const q of rg.getClientRects()) { if (q.width < 0.5) continue; L = Math.min(L, q.left); T = Math.min(T, q.top); Rr = Math.max(Rr, q.right); B = Math.max(B, q.bottom); tops.add(Math.round(q.top / 4)); } }
    return Rr < L ? null : { l: L, t: T, w: Rr - L, h: B - T, lines: tops.size };
  }
  const textNodes = (e) => { const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); const o = []; let t; while ((t = w.nextNode())) if (t.textContent.trim()) o.push(t); return o; };
  let imN = 0;
  function tree(root, maxDepth = 99, maxNodes = 1500) {
    const R = root.getBoundingClientRect(); let n = 0;
    const box = (r) => ({ x: Math.round(r.left - R.left), y: Math.round(r.top - R.top), w: Math.round(r.width), h: Math.round(r.height) });
    const walk = (e, d, pcs) => {
      const cs = getComputedStyle(e); if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") return null; const r = e.getBoundingClientRect();
      if (d > 0 && (r.width < 1 || r.height < 1) && !e.children.length) return null;
      n++; const node = { el: nm(e).slice(0, 90), ...box(r), st: styleOf(e, d === 0 ? null : pcs) };
      if (d === 0) { node.st.fontFamily = cs.fontFamily; node.st.fontSize = cs.fontSize; node.st.fontWeight = cs.fontWeight; node.st.lineHeight = cs.lineHeight; node.st.color = cs.color; }
      if (e.tagName === "IMG") { const s = e.currentSrc || e.src || ""; if (/^https?:/.test(s)) node.img = s; else { e.dataset.fximg = "im" + (++imN); node.img = "shot:" + e.dataset.fximg; } }
      const bgu = /url\("?([^")]+)"?\)/.exec(cs.backgroundImage || ""); if (bgu && /^https?:/.test(bgu[1])) node.bgimg = bgu[1];
      if (e.tagName === "svg" || e.tagName === "SVG") { node.svg = svgText(e); return node; }
      if (e.tagName === "CANVAS") { node.canvas = true; node.cv = e.dataset.fxcv || ""; return node; }
      const pse = []; for (const p of ["::before", "::after"]) { const ps = getComputedStyle(e, p); if (ps.content && ps.content !== "none" && ps.content !== "normal" && (ps.backgroundColor !== "rgba(0, 0, 0, 0)" || ps.width !== "auto")) pse.push({ p, content: ps.content, w: ps.width, h: ps.height, bg: ps.backgroundColor, radius: ps.borderTopLeftRadius, pos: [ps.top, ps.left] }); }
      if (pse.length) node.pseudo = pse;
      const tn = textNodes(e);
      if (tn.length && e.children.length && richOnly(e)) {
        // один слой: полный текст + куски с другим весом/цветом/кеглем
        const tb = textBox(tn); node.text = e.innerText.replace(/[ \t]+/g, " ").trim(); node.runs = [];
        // сверка кусков — по тексту с обычными пробелами (innerText хранит неразрывный пробел «680 000», а \s+ его заменяет)
        const hay = node.text.replace(/ /g, " ");
        let pos = 0; for (const t of tn) { const s = t.textContent.replace(/\s+/g, " "); const k = hay.indexOf(s.trim(), pos); if (k < 0) continue; const ps = getComputedStyle(t.parentElement);
          if (t.parentElement !== e) node.runs.push({ s: k, e: k + s.trim().length, fw: ps.fontWeight, color: ps.color, fs: ps.fontSize }); pos = k + s.trim().length; }
        if (!node.runs.length) delete node.runs;
        if (tb) { node.tb = { ...box({ left: tb.l, top: tb.t, width: tb.w, height: tb.h }) }; node.lines = tb.lines; }
        return node;
      }
      const kids = [];
      for (const c of e.childNodes) {
        if (n >= maxNodes) { node.truncated = true; break; }
        if (c.nodeType === 3) { if (!c.textContent.trim()) continue; const tb = textBox([c]); if (!tb) continue; n++;
          // свой текст элемента — отдельный слой со своей рамкой (раньше весь «свой текст» клеился в одну строку и налезал на соседей)
          if (!e.children.length) { node.text = c.textContent.replace(/\s+/g, " ").trim(); node.tb = box({ left: tb.l, top: tb.t, width: tb.w, height: tb.h }); node.lines = tb.lines; continue; }
          kids.push({ el: "#text", ...box({ left: tb.l, top: tb.t, width: tb.w, height: tb.h }), text: c.textContent.replace(/\s+/g, " ").trim(), lines: tb.lines, st: {} }); continue; }
        if (c.nodeType !== 1 || d >= maxDepth) continue;
        const k = walk(c, d + 1, cs); if (k) kids.push(k);
      }
      if (kids.length) node.children = kids;
      return node; };
    return walk(root, 0, null);
  }
  function chain(e) { const out = []; for (let x = e.parentElement; x && x !== document.body && x !== document.documentElement; x = x.parentElement) out.unshift({ tag: x.tagName.toLowerCase(), id: x.id || "", cls: typeof x.className === "string" ? x.className : "", attrs: ["data-pos", "role"].filter((a) => x.hasAttribute(a)).map((a) => [a, x.getAttribute(a)]) }); return out; }
  const visible = (e) => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 1 && r.height > 1 && cs.visibility !== "hidden" && cs.display !== "none"; };
  async function grab(sel, o = {}) {
    let list = [...document.querySelectorAll(sel)].filter(visible);
    if (o.pick === "last") list = list.reverse();
    if (typeof o.index === "number") list = list.slice(o.index);
    const e = list[0]; if (!e) return null;
    const r = e.getBoundingClientRect(); const par = e.parentElement; const pr = par.getBoundingClientRect(); const pcs = getComputedStyle(par);
    const parentW = Math.round(pr.width - parseFloat(pcs.paddingLeft) - parseFloat(pcs.paddingRight) - parseFloat(pcs.borderLeftWidth) - parseFloat(pcs.borderRightWidth));
    const cvs = markCanvases(e);
    const t = tree(e);   // до клона: дерево ставит метки data-fximg встроенным картинкам
    const clone = await cleanClone(e.cloneNode(true), e);
    // ширина/высота во «вьюпортных» единицах — заморозить на образце (кит смотрят в другом окне)
    const fixed = isFixed(e);
    return { html: clone.outerHTML, chain: chain(e), parentW, w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top), fixed, canvases: cvs,
      parentDisplay: pcs.display, parentFlexDir: pcs.flexDirection, tree: t, bodyCls: document.body.className };
  }
  function texts() {
    const out = []; const seen = new Set();
    document.querySelectorAll("body *").forEach((e) => { if (!visible(e)) return; const t = ownText(e); if (!t || t.length < 2) return;
      const r = e.getBoundingClientRect(); if (r.bottom < 0 || r.top > innerHeight) return;
      const cs = getComputedStyle(e); const k = nm(e).slice(0, 60) + "|" + cs.fontSize + "|" + cs.fontWeight; if (seen.has(k)) return; seen.add(k);
      out.push({ sel: nm(e).slice(0, 60), fs: cs.fontSize, fw: cs.fontWeight, lh: cs.lineHeight, color: cs.color }); });
    return out;
  }
  function tokenProbe() {
    const root = getComputedStyle(document.documentElement); const names = [];
    for (const s of document.styleSheets) { try { for (const r of s.cssRules) if (r.selectorText === ":root") for (const p of r.style) if (p.startsWith("--") && !names.includes(p)) names.push(p); } catch (e) {} }
    const probe = document.createElement("div"); document.body.appendChild(probe); const out = { raw: {}, color: {}, shadow: {}, length: {} };
    for (const n of names) {
      const raw = root.getPropertyValue(n).trim(); out.raw[n] = raw;
      probe.style.cssText = `color:var(${n});box-shadow:var(${n});width:var(${n})`;
      const cs = getComputedStyle(probe);
      if (cs.color && probe.style.color) out.color[n] = cs.color;
      if (cs.boxShadow && cs.boxShadow !== "none") out.shadow[n] = cs.boxShadow;
      if (/px$/.test(cs.width) && /^-?[\d.]+px$/.test(raw)) out.length[n] = cs.width;
    }
    probe.remove(); return out;
  }
  window.__fx = { snapshot, grab, texts, tokenProbe };
})();
