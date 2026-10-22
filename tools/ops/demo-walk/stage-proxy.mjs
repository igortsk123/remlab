// ЛОКАЛЬНАЯ СБОРКА ДЕМО ПОД АДРЕСОМ ПРОДА — без публикации (demo-23 шаг 3, T-20261022-19/1). Страница, данные витрины и модули
// (`/demo/`, `/demo/index.html`, `/demo/demo-data.json`, `/demo/lib/*`) — из папки сборки; всё остальное (API, картинки, кадры, реестр)
// проксируется на прод. Любая проба (`BASE=http://127.0.0.1:<порт>/demo/`) и живая проверка (`playwright.live.config.ts` с
// `BASE_URL`) смотрят на НОВУЮ страницу до выкладки. `UK_OPTIONS_IN_PACKAGE=1` — в ответе карточки британской квартиры опции
// застройщика идут в пакет (`settlement: allowance`), как после выкладки данных `data/partners/demo-uk.json` шага 3.
//   STAGE=<папка сборки> PORT=8790 [UK_OPTIONS_IN_PACKAGE=1] node tools/ops/demo-walk/stage-proxy.mjs
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const STAGE = process.env.STAGE ?? "", PORT = Number(process.env.PORT ?? 8790), UP = process.env.UPSTREAM ?? "https://remont-lab.online";
const UK_OPT = process.env.UK_OPTIONS_IN_PACKAGE === "1";
if (!STAGE) { console.error("нужен STAGE=<папка сборки>"); process.exit(2); }
const TYPES = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".js": "text/javascript" };

// путь страницы → файл сборки; null — на прод
function local(path) {
  if (path === "/demo/" || path === "/demo/index.html") return "index.html";
  if (path === "/demo/demo-data.json") return "demo-data.json";
  if (path.startsWith("/demo/lib/")) { const f = normalize(path.slice("/demo/".length)); return f.startsWith("lib/") ? f : null; }
  return null;
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", UP);
  const file = local(url.pathname);
  try {
    if (file) {
      const body = await readFile(join(STAGE, file)), mtime = (await stat(join(STAGE, file))).mtime;
      // дата файла — как у Caddy: живая проверка 1.1 по ней судит о свежести витрины
      res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream", "cache-control": "no-store", "last-modified": mtime.toUTCString() });
      res.end(body);
      return;
    }
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const headers = { ...req.headers };
    delete headers.host; delete headers["accept-encoding"]; delete headers.connection;
    // сервер принимает запись только со своего адреса — источник и ссылку переписываем на прод
    if (headers.origin) headers.origin = UP;
    if (typeof headers.referer === "string") headers.referer = headers.referer.replace(/^https?:\/\/[^/]+/, UP);
    const up = await fetch(url, { method: req.method, headers, body: chunks.length ? Buffer.concat(chunks) : undefined, redirect: "manual" });
    let body = Buffer.from(await up.arrayBuffer());
    if (UK_OPT && url.pathname.startsWith("/api/apartments/") && up.ok) {
      const j = JSON.parse(body.toString("utf8"));
      if (j?.card?.market === "uk") for (const o of j.card.options ?? []) if (o.settlement === "property_price") o.settlement = "allowance";
      body = Buffer.from(JSON.stringify(j));
    }
    // полные адреса прода в ответах API (кадры задания) — на адрес прокси: иначе картинка с `crossOrigin` чужая для страницы
    if (url.pathname.startsWith("/api/") && /json/.test(up.headers.get("content-type") ?? "") && req.headers.host)
      body = Buffer.from(body.toString("utf8").replaceAll(UP + "/", `http://${req.headers.host}/`));
    const out = {};
    up.headers.forEach((v, k) => { if (!["content-encoding", "content-length", "transfer-encoding", "connection"].includes(k)) out[k] = v; });
    res.writeHead(up.status, out);
    res.end(body);
  } catch (e) {
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(`прокси: ${String(e)}`);
  }
});
server.listen(PORT, "127.0.0.1", () => console.log(`сборка ${STAGE} → http://127.0.0.1:${PORT}/demo/ (остальное — ${UP})`));
