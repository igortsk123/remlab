// АВТОФОТО ТУРА — ИСПОЛНИТЕЛЬ НА DEV (план `.memory_bank/plans/tour-auto-photos-01.md`, Ф3; T-20261112-115/3). СЕЙЧАС — ТОЛЬКО СУХОЙ
// РЕЖИМ: открывает тур покупательским адресом (`?live=force`, служебный Bearer воркера — как `tools/scout/trial_cards.mjs`), по одной
// комнате строит её 3D и снимает два ракурса функциями самой страницы (общий модуль `lib/live-shoot.mjs`, тот же путь, что у ночной
// досъёмки витрины), кладёт кадры JPEG в папку прогона и пишет `result.json`. НИЧЕГО НЕ ЗАКАЗЫВАЕТ: место заказа — `orderPhoto`
// (заглушка, TODO Ф3 после Ф1 и Ф2). Кадры на сервер не грузит (сухой ход).
//
//   node tools/ops/tour-auto-photos.mjs --job задание.json [--out папка]   # задание — см. `parseJob`
//   node tools/ops/tour-auto-photos.mjs --tour <id22> --rooms bedroom-1[:вариант][,living…] [--out папка]
//   node tools/ops/tour-auto-photos.mjs --selftest                         # на заглушках страницы — без браузера, сети и денег
// Сам встаёт в общую очередь тяжёлых прогонов (`heavy-slot.sh --cores 6 --min-gb 3`: 3D рисует процессор); одна комната за раз.
// Ключ воркера — из окружения (`TRIAL_WORKER_TOKEN`, как у `tools/floorplan/cards.py`), не печатается и не пишется в файлы; без него
// откроется только тур, подтверждённый агентом (до подтверждения тур без ключа закрыт — `lib/trial/buyer-gate.ts`).
// Выход: 0 — сняты все комнаты задания; 3 — хоть одна не снята (причина — в `result.json` и строке `ROOM`); 2 — неверный вызов.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { PAGE_READY, captureViews, launchLive, openLivePage, routeTourBearer } from "./lib/live-shoot.mjs";

const ID_RE = /^[A-Za-z0-9_-]{22}$/, ROOM_RE = /^[a-z0-9-]{1,40}$/;
/** Больше комнат за один тур не снимаем (владелец 12.11 TG 1318: «5 помещений максимум»). */
export const MAX_ROOMS = 5;

/**
 * Задание: {tour, base?, rooms:[{room_id, variant?, state_id?, poses?}]}. `variant` — id варианта (активный стиль комнаты отдаст Ф2);
 * нет — первый вариант комнаты с мебелью в порядке страницы. `state_id` — номер состояния, для которого заказано (Ф2 фиксирует его
 * вместе с версией сборки): страница насчитала другой — комнату НЕ снимаем (тур успели пересобрать). `poses` — пара точек
 * [{name:"C1",x,y,rot,fov}, {name:"C2",…}] вместо пары страницы. Неверное — громкий отказ, а не молчаливая правка.
 */
export function parseJob(j) {
  if (!j || typeof j !== "object") throw new Error("задание: не объект");
  if (!ID_RE.test(String(j.tour ?? ""))) throw new Error(`задание: tour — 22 знака [A-Za-z0-9_-], пришло ${JSON.stringify(j.tour)}`);
  const base = String(j.base ?? "https://remont-lab.online").replace(/\/+$/, "");
  if (!/^https?:\/\/[^/]+$/.test(base)) throw new Error(`задание: base — только сервер, без пути (${base})`);
  if (!Array.isArray(j.rooms) || !j.rooms.length) throw new Error("задание: rooms — непустой список");
  if (j.rooms.length > MAX_ROOMS) throw new Error(`задание: комнат ${j.rooms.length} — больше ${MAX_ROOMS}`);
  const seen = new Set();
  const rooms = j.rooms.map((r, k) => {
    const id = String(r?.room_id ?? "");
    if (!ROOM_RE.test(id)) throw new Error(`задание: rooms[${k}].room_id ${JSON.stringify(r?.room_id)}`);
    if (seen.has(id)) throw new Error(`задание: комната ${id} дважды`);
    seen.add(id);
    const poses = r.poses ?? null;
    if (poses !== null && !(Array.isArray(poses) && poses.length === 2
      && poses.every((c, n) => c && c.name === `C${n + 1}` && [c.x, c.y].every(Number.isFinite) && (c.rot == null || Number.isFinite(c.rot))
        && (c.fov == null || (Number.isFinite(c.fov) && c.fov > 0 && c.fov < 180)))))
      throw new Error(`задание: rooms[${k}].poses — ровно две точки C1, C2 с числами x, y (rot, fov)`);
    return { room_id: id, variant: r.variant ? String(r.variant) : "", state_id: r.state_id ? String(r.state_id) : "", poses };
  });
  return { tour: String(j.tour), base, rooms };
}

/** `--rooms bedroom-1:вариант,living` → список комнат задания. */
export function roomsArg(s) {
  return String(s ?? "").split(",").map((x) => x.trim()).filter(Boolean).map((x) => {
    const [room_id, variant = ""] = x.split(":");
    return { room_id, variant };
  });
}

/**
 * Покупательский адрес тура для съёмки: 3D даже на программном рендере, без опроса, русский. Косая в конце `/tour/` ОБЯЗАТЕЛЬНА
 * (как `tools/floorplan/cards.py:tour_url`): данные страница берёт относительным `demo-data.json` — без косой он уходит на
 * `/try/<id>/demo-data.json` (404) и страница не оживает (проба 13.11 00:27: ожидание данных 90 с — таймаут).
 */
export function tourUrl(job) {
  return `${job.base}/try/${job.tour}/tour/?live=force&quiz=0&lang=ru`;
}

/** Готовность страницы ТУРА: общие данные + это именно тур (`TRIAL()`), а не витрина. */
export const TOUR_READY = `${PAGE_READY} && typeof TRIAL === 'function' && TRIAL()`;

/** Номер варианта на странице для комнаты задания: свой `variant` или первый с мебелью, без ожидания и отказа. → индекс | -1 */
export function pickIndex(list, room) {
  const mine = list.filter((v) => v.room === room.room_id);
  const v = room.variant ? mine.find((x) => x.id === room.variant) : mine.find((x) => x.items > 0 && !x.pending && !x.refused);
  return v ? v.i : -1;
}

/** Имя файла кадра: комната, вариант, ракурс — только безопасные знаки. */
export function frameName(roomId, variant, k) {
  const safe = (s) => String(s).replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 60);
  return `${safe(roomId)}-${safe(variant)}-C${k + 1}.jpg`;
}

/**
 * МЕСТО ЗАКАЗА — ЗАГЛУШКА (TODO Ф3, план tour-auto-photos-01 § «Критика Codex»): боевой путь — резерв в БД с UNIQUE (тур, комната,
 * вариант/stateId, подпись обеих поз с fov, качество) ДО запуска Chromium (Ф2), загрузка кадров (`vwUploadViews`), заказ класса `auto`
 * по Bearer воркера через `/api/trial/<id>/photo`, завершение `POST /api/trial/worker/<id>/photo` (Ф1), потолки 50 ₽/тур и
 * 500 ₽/сутки. Пока любой вызов — отказ: денег этот скрипт не тратит.
 */
export function orderPhoto() {
  throw new Error("заказ фото тура ещё не подключён (Ф3 после Ф1/Ф2, план tour-auto-photos-01) — только сухой ход");
}

/**
 * ЯДРО (чистое; deps — страница или заглушки самопроверки): комнаты строго по одной. Для каждой: вариант на странице → номер
 * состояния (не тот, что в задании, — пропуск без съёмки) → кадры (`deps.capture`) → файлы (`deps.save`). Сухой ход — заказ не зовётся.
 * deps: list() → [{i,id,room,items,pending,refused}]; stateOf(i) → stateId; capture(i, poses) → итог `pageCapture` с `jpgs`;
 *       save(name, b64) → путь. → {rooms:[{room_id, ok, why?, variant, stateId, poses, files, sec, readyMs, captureMs}], ok, failed}
 */
export async function runTour(job, deps) {
  const list = await deps.list();
  const out = { rooms: [], ok: 0, failed: 0 };
  for (const room of job.rooms) {
    const t0 = Date.now(), rec = { room_id: room.room_id, ok: false, variant: room.variant, stateId: "", files: [] };
    const i = pickIndex(list, room);
    try {
      if (i < 0) throw new Error(room.variant ? `варианта ${room.variant} в комнате нет` : "в комнате нет варианта с мебелью");
      rec.variant = list.find((v) => v.i === i).id;
      const st = await deps.stateOf(i);
      rec.stateId = st;
      if (room.state_id && st !== room.state_id) throw new Error(`состояние комнаты ${st} ≠ заданного ${room.state_id} — тур пересобран, не снимаю`);
      const cap = await deps.capture(i, room.poses);
      if (!cap?.ok) throw new Error(`${cap?.error ?? "кадры не сняты"}${cap?.live ? ` (3D: ${cap.live})` : ""}`);
      if (cap.roomId !== room.room_id) throw new Error(`кадры комнаты ${cap.roomId}, ждали ${room.room_id}`);
      if (cap.stateId !== st) throw new Error(`пока снимали, состояние сменилось: ${cap.stateId} ≠ ${st}`);
      if (!Array.isArray(cap.jpgs) || cap.jpgs.length < 2) throw new Error(`кадров ${cap.jpgs?.length ?? 0}, нужно 2`);
      rec.poses = (cap.poses ?? []).map((p, k) => ({ name: `C${k + 1}`, ...p }));
      rec.size = cap.size; rec.readyMs = cap.readyMs; rec.captureMs = cap.ms?.capture ?? null; rec.roomSig = cap.room;
      for (let k = 0; k < cap.jpgs.length; k++) rec.files.push(await deps.save(frameName(room.room_id, rec.variant, k), cap.jpgs[k]));
      rec.ok = true; out.ok += 1;
    } catch (e) {
      rec.why = String(e?.message ?? e).slice(0, 300); out.failed += 1;
    }
    rec.sec = Math.round((Date.now() - t0) / 100) / 10;
    out.rooms.push(rec);
    deps.log?.(`ROOM ${room.room_id} ${rec.variant || "?"}: ${rec.ok ? `снято ${rec.files.length} кадра` : "НЕ СНЯТО — " + rec.why}, ${rec.sec} с`);
  }
  return out;
}

/** Очередь тяжёлых прогонов: вне слота → [heavy-slot.sh, аргументы] перезапуска себя; в слоте (HEAVY_SLOT_HELD) или TOUR_NO_SLOT=1 → null. */
export function underSlot(env, argv, node, self) {
  if (env.HEAVY_SLOT_HELD || env.TOUR_NO_SLOT === "1") return null;
  return [fileURLToPath(new URL("./heavy-slot.sh", import.meta.url)),
    ["tour-photos", "--min-gb", "3", "--cores", "6", "--timeout", env.TOUR_SLOT_WAIT_S ?? "3600", "--", node, self, ...argv]];
}

const arg = (k) => { const i = process.argv.indexOf(k); return i >= 0 ? process.argv[i + 1] : undefined; };

/** Вызов проверяется ДО очереди тяжёлых прогонов (неверное задание не занимает билет на 6 ядер): `--go` и плохое задание — код 2. */
function jobOrExit() {
  if (process.argv.includes("--go")) { console.error(orderPhoto.name + ": " + (() => { try { orderPhoto(); } catch (e) { return e.message; } })()); process.exit(2); }
  try {
    return parseJob(arg("--job") ? JSON.parse(readFileSync(arg("--job"), "utf8")) : { tour: arg("--tour"), base: arg("--base"), rooms: roomsArg(arg("--rooms")) });
  } catch (e) { console.error(String(e.message ?? e)); process.exit(2); }
}

async function main() {
  const job = jobOrExit();
  const hm = new Date().toTimeString().slice(0, 5).replace(":", "");
  const out = arg("--out") ?? join(homedir(), "remlab-logs", "t115-1112", hm);
  mkdirSync(out, { recursive: true });
  const { chromium } = await import("@playwright/test");
  const browser = await launchLive(chromium, true);
  const t0 = Date.now();
  let res;
  const errs = [];
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" });
    await ctx.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));   // это не посетитель
    const bearer = await routeTourBearer(ctx, `${job.base}/try/${job.tour}/tour`, process.env.TRIAL_WORKER_TOKEN || "");
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
    await openLivePage(page, tourUrl(job), { gl: true, ready: TOUR_READY });
    const pageMs = Date.now() - t0;
    console.log(`тур ${job.tour}: страница готова за ${(pageMs / 1000).toFixed(1)} с; ключ воркера: ${bearer ? "есть" : "нет (только подтверждённый тур)"}; папка ${out}`);
    res = await runTour(job, {
      list: () => page.evaluate(() => allVariants().map((v, i) => ({ i, id: String(v.id || ""), room: roomIdOf(v), items: (v.items || []).length,
        pending: typeof varPending === "function" && varPending(v), refused: typeof varRefused === "function" && varRefused(v) }))),
      stateOf: (i) => page.evaluate((k) => { pickVariant(k); return curStateId(); }, i),
      capture: (i, poses) => captureViews(page, i, { noUpload: true, b64: true, poses }),
      save: (name, b64) => { const p = join(out, name); writeFileSync(p, Buffer.from(b64, "base64")); return p; },
      log: (l) => console.log(l),
    });
    res.pageMs = pageMs; res.pageErrors = errs.slice(0, 5);
  } catch (e) {
    // страница тура не открылась (данные, доступ, 3D) — ни одна комната не снята; громко, с причиной, без падения без итога
    const why = `страница тура не готова: ${String(e?.message ?? e).split("\n")[0].slice(0, 200)}`;
    console.log(`ТУР ${job.tour}: НЕ СНЯТ — ${why}`);
    res = { rooms: job.rooms.map((r) => ({ room_id: r.room_id, ok: false, why, files: [] })), ok: 0, failed: job.rooms.length, pageErrors: errs.slice(0, 5) };
  } finally { await browser.close(); }
  res.tour = job.tour; res.dry = true; res.totalSec = Math.round((Date.now() - t0) / 100) / 10;
  writeFileSync(join(out, "result.json"), JSON.stringify(res, null, 1));
  console.log(`итого: снято комнат ${res.ok}, не снято ${res.failed}, ${res.totalSec} с; заказов 0 (сухой ход) → ${join(out, "result.json")}`);
  process.exit(res.failed ? 3 : 0);
}

async function selftest() {
  const res = [];
  const check = (ok, msg, got) => { res.push(!!ok); console.log(ok ? `OK   ${msg}` : `FAIL ${msg}: ${JSON.stringify(got)}`); };
  const T = "aRQVC9nJ1g1WqBTXeA6VqA";
  const bad = (j) => { try { parseJob(j); return ""; } catch (e) { return e.message; } };
  check(parseJob({ tour: T, rooms: [{ room_id: "bedroom-1" }] }).base === "https://remont-lab.online", "задание: сервер по умолчанию — прод", null);
  check(/tour/.test(bad({ tour: "x", rooms: [{ room_id: "a" }] })) && /больше 5/.test(bad({ tour: T, rooms: [1, 2, 3, 4, 5, 6].map((n) => ({ room_id: `r${n}` })) }))
    && /дважды/.test(bad({ tour: T, rooms: [{ room_id: "a" }, { room_id: "a" }] })) && /room_id/.test(bad({ tour: T, rooms: [{ room_id: "../x" }] }))
    && /без пути/.test(bad({ tour: T, base: "https://x.ru/try", rooms: [{ room_id: "a" }] })),
  "задание: чужой id, больше 5 комнат, дубль, плохое имя комнаты, адрес с путём — громкий отказ", null);
  check(/две точки/.test(bad({ tour: T, rooms: [{ room_id: "a", poses: [{ name: "C1", x: 1, y: 1 }] }] }))
    && /две точки/.test(bad({ tour: T, rooms: [{ room_id: "a", poses: [{ name: "C1", x: 1, y: 1 }, { name: "C2", x: "1", y: 1 }] }] }))
    && !bad({ tour: T, rooms: [{ room_id: "a", poses: [{ name: "C1", x: 1, y: 2, rot: 45, fov: 72 }, { name: "C2", x: 3, y: 4 }] }] }),
  "задание: пара поз — ровно C1, C2 с числами", null);
  check(JSON.stringify(roomsArg("bedroom-1:bedroom-1-loft, living")) === '[{"room_id":"bedroom-1","variant":"bedroom-1-loft"},{"room_id":"living","variant":""}]',
    "--rooms: комната[:вариант] через запятую", roomsArg("bedroom-1:bedroom-1-loft, living"));
  check(tourUrl(parseJob({ tour: T, rooms: [{ room_id: "a" }] })) === `https://remont-lab.online/try/${T}/tour/?live=force&quiz=0&lang=ru`
    && TOUR_READY.includes("TRIAL()"), "адрес тура: покупательский, с косой /tour/ (данные — относительно), 3D принудительно, без опроса; ждём именно тур", null);
  const L = [{ i: 0, id: "b1-s", room: "bedroom-1", items: 0 }, { i: 1, id: "b1-m", room: "bedroom-1", items: 4, pending: true },
    { i: 2, id: "b1-l", room: "bedroom-1", items: 5 }, { i: 3, id: "lv", room: "living", items: 7 }];
  check(pickIndex(L, { room_id: "bedroom-1" }) === 2 && pickIndex(L, { room_id: "bedroom-1", variant: "b1-s" }) === 0 && pickIndex(L, { room_id: "kitchen" }) === -1
    && pickIndex(L, { room_id: "living", variant: "b1-l" }) === -1, "вариант: заданный — этой комнаты; иначе первый с мебелью, не ждущий", null);
  check(frameName("bedroom-1", "b1/../x", 1) === "bedroom-1-b1_x-C2.jpg", "имя кадра — безопасные знаки", frameName("bedroom-1", "b1/../x", 1));
  const sNo = underSlot({}, ["--tour", T], "/n", "/s.mjs");
  check(sNo[0].endsWith("/heavy-slot.sh") && sNo[1].join(" ") === `tour-photos --min-gb 3 --cores 6 --timeout 3600 -- /n /s.mjs --tour ${T}`
    && underSlot({ HEAVY_SLOT_HELD: "1" }, [], "/n", "/s") === null && underSlot({ TOUR_NO_SLOT: "1" }, [], "/n", "/s") === null,
  "очередь: 6 ядер, 3 ГБ (3D процессором); в слоте — без", sNo);
  let threw = "";
  try { orderPhoto(); } catch (e) { threw = e.message; }
  check(/Ф3/.test(threw), "заказ — заглушка: любой вызов — отказ, денег нет", threw);

  // ЯДРО НА ЗАГЛУШКАХ СТРАНИЦЫ: настоящий `pageCapture` из общего модуля на `globalThis` — комнаты по одной, кадры своей комнаты
  const { pageCapture } = await import("./lib/live-shoot.mjs");
  const g = globalThis, picks = [];
  let room = "", state = {};
  const V = [{ id: "b1-l", room_id: "bedroom-1", items: [1] }, { id: "lv", room_id: "living", items: [1] }, { id: "b2-l", room_id: "bedroom-2", items: [1] }];
  Object.assign(g, { cur: 0, cams: null, VW: { mode: "walk" }, LIVE: { ok: true, scene: {}, state: "ready" },
    allVariants: () => V, roomIdOf: (v) => v.room_id, pickVariant: (i) => { picks.push(i); g.cur = i; g.cams = null; room = V[i].room_id; },   // как `index.html:load` — cams=null
    curStateId: () => state[V[g.cur].room_id] ?? "s-" + V[g.cur].id, openLiveWindow: () => {}, vwMode: () => {},
    liveHere: () => ({}), camPoseOf: (c) => ({ x: c.x, y: c.y, rot: c.rot || 0, fov: c.fov || 72 }), loadCams: () => [{ x: 1, y: 1 }, { x: 2, y: 2 }],
    vwCaptureViews: async () => { return room === "bedroom-2" ? null
      : { blobs: [new Blob([`${room}-1`]), new Blob([`${room}-2`])], size: "2048×1489", ms: { capture: 5 }, room: room + "-sig" }; } });
  const saved = {}, logs = [];
  const fdeps = {
    list: async () => V.map((v, i) => ({ i, id: v.id, room: v.room_id, items: v.items.length })),
    stateOf: async (i) => { g.pickVariant(i); return g.curStateId(); },
    capture: (i, poses) => pageCapture({ i, noUpload: true, b64: true, poses, waitTicks: 2 }),
    save: async (name, b64) => { saved[name] = Buffer.from(b64, "base64").toString(); return "/out/" + name; },
    log: (l) => logs.push(l),
  };
  const P = [{ name: "C1", x: 10, y: 20, rot: 45, fov: 70 }, { name: "C2", x: 30, y: 40 }];
  let r = await runTour(parseJob({ tour: T, rooms: [{ room_id: "living", poses: P }, { room_id: "bedroom-1", state_id: "s-b1-l" }, { room_id: "bedroom-2" }] }), fdeps);
  check(r.ok === 2 && r.failed === 1 && saved["living-lv-C1.jpg"] === "living-1" && saved["living-lv-C2.jpg"] === "living-2" && saved["bedroom-1-b1-l-C2.jpg"] === "bedroom-1-2"
    && r.rooms[0].poses[0].name === "C1" && r.rooms[0].poses[0].x === 10 && /кадры из браузера не сняты/.test(r.rooms[2].why) && logs.length === 3,
  "комнаты по одной: кадры каждой — из её сцены, файлы по комнате и варианту; не снялось — причина, остальные идут", { r, saved: Object.keys(saved) });
  check(r.rooms[0].poses[1].x === 30 && r.rooms[1].poses[0].x === 1, "пара поз задания уходит в съёмку; без неё — пара страницы", r.rooms.map((x) => x.poses));
  state = { "bedroom-1": "s-новое" };
  const nCap = picks.length;
  r = await runTour(parseJob({ tour: T, rooms: [{ room_id: "bedroom-1", state_id: "s-b1-l" }] }), fdeps);
  check(r.failed === 1 && /тур пересобран/.test(r.rooms[0].why) && picks.length === nCap + 1,
    "состояние не то, что в задании, — комната не снимается (только выбор варианта, без съёмки)", r.rooms[0]);
  state = {};
  r = await runTour(parseJob({ tour: T, rooms: [{ room_id: "kitchen" }, { room_id: "living", variant: "нет-такого" }] }), fdeps);
  check(r.failed === 2 && /нет варианта/.test(r.rooms[0].why) && /нет-такого/.test(r.rooms[1].why), "нет варианта в комнате — отказ с причиной, без съёмки", r.rooms);
  // ключ воркера — только к адресам этого тура и нигде не печатается
  const routes = [];
  const ctx = { route: async (m, h) => routes.push({ m, h }) };
  const okB = await routeTourBearer(ctx, `https://remont-lab.online/try/${T}/tour`, "секрет-123");
  const m = routes[0]?.m;
  check(okB && m(new URL(`https://remont-lab.online/try/${T}/tour/demo-data.json`)) && !m(new URL(`https://remont-lab.online/api/render/frame`))
    && !m(new URL(`https://evil.example/try/${T}/tour`)) && !(await routeTourBearer({ route: async () => {} }, "https://remont-lab.online/demo/", "k"))
    && !JSON.stringify(r).includes("секрет") && !logs.join("\n").includes("секрет"),
  "Bearer — только адреса этого тура на том же сервере; не тур — без ключа; в итоге и журнале ключа нет", null);
  process.exit(res.every(Boolean) ? 0 : 1);
}

if (process.argv.includes("--selftest")) await selftest();
else if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const slot = underSlot(process.env, process.argv.slice(2), process.execPath, process.argv[1]);
  jobOrExit();
  if (!slot) await main();
  else {
    const { spawnSync } = await import("node:child_process");
    const r = spawnSync("bash", [slot[0], ...slot[1]], { stdio: "inherit" });
    process.exit(r.status ?? 1);
  }
}
