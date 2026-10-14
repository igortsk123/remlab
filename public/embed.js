/* RemLab — встраивание демо квартиры на сайт застройщика (план b2b-07). Подключение:
     <div data-remlab-partner="demo" data-remlab-flat="flat215" data-remlab-lang="ru"></div>
     <script src="https://remont-lab.online/embed.js" async></script>
   Создаёт рамку, подстраивает её высоту, пересылает события как CustomEvent «remlab» на этом div
   (detail.name: open | 3d | save | contact). Сообщения принимаются ТОЛЬКО от remont-lab.online и только от своей рамки. */
(function () {
  var ORIGIN = "https://remont-lab.online";
  var ID = /^[a-z0-9-]{2,40}$/;
  var EVENTS = { open: 1, "3d": 1, save: 1, contact: 1 };
  function mount(el) {
    if (el.__remlab) return;
    var partner = el.getAttribute("data-remlab-partner"), flat = el.getAttribute("data-remlab-flat");
    if (!ID.test(partner || "") || !ID.test(flat || "")) return;
    var q = new URLSearchParams();
    if (el.getAttribute("data-remlab-lang") === "en") q.set("lang", "en");
    new URLSearchParams(location.search).forEach(function (v, k) { if (/^utm_/.test(k)) q.set(k, v.slice(0, 100)); });
    var f = document.createElement("iframe");
    f.src = ORIGIN + "/embed/" + partner + "/" + flat + (q.toString() ? "?" + q : "");
    f.title = "RemLab";
    f.loading = "lazy";
    f.style.cssText = "width:100%;border:0;min-height:600px;display:block";
    f.setAttribute("allow", "clipboard-write; fullscreen");
    el.appendChild(f);
    el.__remlab = f;
  }
  window.addEventListener("message", function (e) {
    if (e.origin !== ORIGIN || !e.data || typeof e.data !== "object") return;
    var els = document.querySelectorAll("[data-remlab-flat]");
    for (var i = 0; i < els.length; i++) {
      var f = els[i].__remlab;
      if (!f || e.source !== f.contentWindow) continue;
      if (e.data.type === "remlab:height" && typeof e.data.h === "number" && e.data.h > 200 && e.data.h < 20000) f.style.height = Math.round(e.data.h) + "px";
      if (e.data.type === "remlab:event" && EVENTS[e.data.name]) els[i].dispatchEvent(new CustomEvent("remlab", { detail: { name: e.data.name } }));
    }
  });
  function scan() { var els = document.querySelectorAll("[data-remlab-flat]"); for (var i = 0; i < els.length; i++) mount(els[i]); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scan); else scan();
})();
