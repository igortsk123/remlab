// АВТОФОТО ТУРА — ИСПОЛНИТЕЛЬ НА DEV (план `.memory_bank/plans/tour-auto-photos-01.md`, Ф3; T-20261112-115/3, /5).
// Берёт из очереди прода партию «снять тур» (её ставит подтверждение планировки агентом — `lib/trial/auto-photos-queue.ts`), открывает
// тур покупательским адресом (`?live=force`, служебный Bearer воркера — как `tools/scout/trial_cards.mjs`), по одной комнате строит её 3D
// и снимает два ракурса функциями самой страницы (общий модуль `lib/live-shoot.mjs`, тот же путь, что у ночной досъёмки витрины), грузит
// кадры (`/api/render/frame`) и заказывает фото нейросети кнопкой страницы (`makePhoto`) классом `auto` по своей задаче (`auto_task`):
// сервер пускает ровно один заказ на задачу, потолки 50 ₽ на тур и 500 ₽ в сутки держит очередь. Готовые фото скачивает в папку прогона.
//
//   node tools/ops/tour-auto-photos.mjs --claim [--dry] [--max-tasks N] [--only <id22>] [--base URL]   # одна партия (юнит DEV — systemd/)
//   node tools/ops/tour-auto-photos.mjs --tour <id22> --rooms bedroom-1[:вариант][,…] [--out папка]   # СУХАЯ съёмка без очереди и заказа
//   node tools/ops/tour-auto-photos.mjs --job задание.json [--out папка]                                # то же заданием (`parseJob`)
//   node tools/ops/tour-auto-photos.mjs --selftest                         # на заглушках страницы и ручек — без браузера, сети и денег
// `--claim`: партия берётся под аренду ДО очереди тяжёлых прогонов (срочная — `--prio 1 --short`, догон — обычная); пока ждём слот, аренда
// продлевается. `--dry` — снять кадры без загрузки и заказа и вернуть партию в очередь (`dry_run`, попытка не тратится). `--max-tasks N` —
// после N комнат вернуть партию (остальные ждут в очереди). Тур не готов (TOUR_READY) или версия не та — партия возвращается (exit 3).
// Ключ воркера — из окружения (`TRIAL_WORKER_TOKEN`, юнит берёт из `~/.config/remlab/env`), не печатается и не пишется в файлы.
// Выход: 0 — партия снята (или очередь пуста); 3 — хоть одна комната не снята / партия возвращена; 2 — неверный вызов; 4 — ручки недоступны.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, hostname } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { DATA_READY, captureViews, launchLive, openLivePage, routeTourBearer } from "./lib/live-shoot.mjs";

const ID_RE = /^[A-Za-z0-9_-]{22}$/, ROOM_RE = /^[a-z0-9-]{1,40}$/;
/** Больше комнат за один тур не снимаем (владелец 12.11 TG 1318: «5 помещений максимум»). */
export const MAX_ROOMS = 5;
const PROD = "https://remont-lab.online";

/**
 * Задание: {tour, base?, rooms:[{room_id, variant?, state_id?, poses?}]}. `variant` — id варианта (у партии — активный стиль из очереди);
 * нет — первый вариант комнаты с мебелью в порядке страницы. `state_id` — номер состояния, для которого заказано: страница насчитала
 * другой — комнату НЕ снимаем (тур успели пересобрать). `poses` — пара точек [{name:"C1",x,y,rot,fov,…}, {name:"C2",…}] вместо пары
 * страницы (у партии — позы задачи `v.cams`). Неверное — громкий отказ, а не молчаливая правка.
 */
export function parseJob(j) {
  if (!j || typeof j !== "object") throw new Error("задание: не объект");
  if (!ID_RE.test(String(j.tour ?? ""))) throw new Error(`задание: tour — 22 знака [A-Za-z0-9_-], пришло ${JSON.stringify(j.tour)}`);
  const base = String(j.base ?? PROD).replace(/\/+$/, "");
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

/** Покупательский адрес тура для съёмки: 3D даже на программном рендере, без опроса, русский (`/tour/` сервер сам ведёт 308 сюда). */
export function tourUrl(job) {
  return `${job.base}/try/${job.tour}/tour?live=force&quiz=0&lang=ru`;
}

/**
 * Готовность страницы ТУРА: данные + это именно тур (`TRIAL()`). Без `FLAT`: карточку квартиры грузит только витрина — с ним тур
 * не дождаться (проба 13.11 00:27: 90 с ожидания, таймаут, ни одного кадра).
 */
export const TOUR_READY = `${DATA_READY} && typeof TRIAL === 'function' && TRIAL()`;

/** Номер варианта на странице для комнаты задания: свой `variant` или первый с мебелью, без ожидания и отказа. → индекс | -1 */
export function pickIndex(list, room) {
  const mine = list.filter((v) => v.room === room.room_id);
  const v = room.variant ? mine.find((x) => x.id === room.variant) : mine.find((x) => x.items > 0 && !x.pending && !x.refused);
  return v ? v.i : -1;
}

/** Имя файла кадра: комната, вариант, ракурс — только безопасные знаки. */
export function frameName(roomId, variant, k, kind = "C") {
  const safe = (s) => String(s).replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 60);
  return `${safe(roomId)}-${safe(variant)}-${kind}${k + 1}.jpg`;
}

/**
 * СУХОЕ ЯДРО (чистое; deps — страница или заглушки самопроверки): комнаты задания строго по одной, без очереди и заказа. Для каждой:
 * вариант на странице → номер состояния (не тот, что в задании, — пропуск без съёмки) → кадры (`deps.capture`) → файлы (`deps.save`).
 * deps: list() → [{i,id,room,items,pending,refused}]; stateOf(i) → stateId; capture(i, poses) → итог `pageCapture` с `jpgs`;
 *       save(name, b64) → путь. → {rooms:[{room_id, ok, why?, variant, stateId, poses, files, sec, readyMs, captureMs}], ok, failed}
 */
export async function runTour(job, deps) {
  const list = await deps.list();
  const out = { rooms: [], ok: 0, failed: 0 };
  for (const room of job.rooms) {
    const t0 = Date.now(), rec = { room_id: room.room_id, ok: false, variant: room.variant, stateId: "", files: [] };
    try {
      await shootRoom(list, room, rec, deps, false);
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

/** Ошибка съёмки с кодом для отметки задачи (`[a-z_]{1,40}`, контракт `autoTaskIn`). */
const fail = (code, msg) => Object.assign(new Error(msg), { code });

/** Одна комната: вариант → состояние → кадры своей комнаты (`upload` — загружены на сервер, есть `views`) → файлы. Бросает с `code`. */
async function shootRoom(list, room, rec, deps, upload) {
  const i = pickIndex(list, room);
  if (i < 0) throw fail("variant_missing", room.variant ? `варианта ${room.variant} в комнате нет` : "в комнате нет варианта с мебелью");
  rec.variant = list.find((v) => v.i === i).id;
  const st = await deps.stateOf(i);
  rec.stateId = st;
  if (room.state_id && st !== room.state_id) throw fail("state_changed", `состояние комнаты ${st} ≠ заданного ${room.state_id} — тур пересобран, не снимаю`);
  const cap = await deps.capture(i, room.poses, upload);
  if (!cap?.ok) throw fail("capture_failed", `${cap?.error ?? "кадры не сняты"}${cap?.live ? ` (3D: ${cap.live})` : ""}`);
  if (cap.roomId !== room.room_id) throw fail("room_mismatch", `кадры комнаты ${cap.roomId}, ждали ${room.room_id}`);
  if (cap.stateId !== st) throw fail("state_changed", `пока снимали, состояние сменилось: ${cap.stateId} ≠ ${st}`);
  if (!Array.isArray(cap.jpgs) || cap.jpgs.length < 2) throw fail("capture_failed", `кадров ${cap.jpgs?.length ?? 0}, нужно 2`);
  if (upload && !(Array.isArray(cap.views) && cap.views.length >= 2)) throw fail("upload_failed", "кадры не загрузились на сервер");
  rec.poses = (cap.poses ?? []).map((p, k) => ({ name: `C${k + 1}`, ...p }));
  rec.size = cap.size; rec.readyMs = cap.readyMs; rec.captureMs = cap.ms?.capture ?? null; rec.uploadMs = cap.ms?.upload ?? null; rec.roomSig = cap.room;
  for (let k = 0; k < cap.jpgs.length; k++) rec.files.push(await deps.save(frameName(room.room_id, rec.variant, k), cap.jpgs[k]));
  return i;
}

/** Код отказа для ручки задачи: только `[a-z_]`, до 40 знаков; пусто — `order_failed`. */
export function codeOf(s, dflt = "order_failed") {
  const c = String(s ?? "").toLowerCase().replace(/[^a-z_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  return c || dflt;
}

/** Отказы сервиса кадров, после которых дальше по партии не заказываем (денег/сервиса нет — следующий заказ откажет так же). */
export const STOP_CODES = new Set(["no_credits", "unavailable", "daily_limit", "auto_daily", "rate_limited"]);

/**
 * ЯДРО ПАРТИИ (чистое; deps — страница и ручки или заглушки самопроверки). Задачи по одной: отметка `shooting` (продлевает аренду) →
 * съёмка (`shootRoom`, в боевом — с загрузкой кадров) → заказ (`deps.order(i, taskId)`, ровно один на задачу; сервер сам переводит
 * задачу в `ordered`, готовое фото — в `done`) → фото скачаны (`deps.fetchPhotos`). Не снялось до заказа — задача `failed` с кодом
 * (резерв вернулся). Отказ сервиса из `STOP_CODES` — дальше не заказываем (остальные ждут в очереди). Аренда потеряна — стоп сразу.
 * `dry` — без загрузки и заказа; `maxTasks` — после N комнат стоп (остальные — `left`).
 * deps: list, stateOf, capture(i, poses, upload), save — как у `runTour`; mark(taskId, status, code?) → {ok, lost?, error?};
 *       order(i, taskId) → {ok, urls?, error?, code?}; fetchPhotos(urls, room, variant) → [{path, bytes, jpeg}]; log.
 * → {rooms:[…], ok, failed, ordered, refusals, left, lost, stop}
 */
export async function runBatch(batch, job, deps, { dry = false, maxTasks = Infinity } = {}) {
  const out = { rooms: [], ok: 0, failed: 0, ordered: 0, refusals: 0, left: 0, lost: false, stop: "" };
  const list = await deps.list();
  let n = 0;
  for (let k = 0; k < batch.tasks.length; k++) {
    const t = batch.tasks[k], room = job.rooms[k];
    if (out.lost || out.stop || n >= maxTasks) { out.left += 1; continue; }
    n += 1;
    const t0 = Date.now(), rec = { task: t.id, room_id: t.roomId, variant: t.variantId, ok: false, stateId: "", files: [], photos: [] };
    let ordered = false;
    try {
      const m = await deps.mark(t.id, "shooting");
      if (m.lost) { out.lost = true; throw fail("lease_lost", "аренда партии потеряна — дальше не снимаю и не заказываю"); }
      if (!m.ok) throw fail("bad_transition", `задача не открыта (${m.error ?? "?"}) — не снимаю`);
      const i = await shootRoom(list, room, rec, deps, !dry);
      if (rec.variant !== t.variantId) throw fail("variant_mismatch", `на странице вариант ${rec.variant}, в задаче ${t.variantId}`);
      if (!dry) {
        const o = await deps.order(i, t.id);
        if (!o?.ok) {
          out.refusals += 1;
          const code = codeOf(o?.code || o?.error);
          if (STOP_CODES.has(code)) out.stop = code;
          throw fail(code, `заказ не принят: ${String(o?.error ?? "?").slice(0, 160)}${o?.code ? ` [${o.code}]` : ""}`);
        }
        ordered = true; out.ordered += 1; rec.ordered = true; rec.orderSec = o.sec ?? null;
        rec.photos = await deps.fetchPhotos(o.urls ?? [], t.roomId, rec.variant);
        if (rec.photos.filter((p) => p.jpeg).length < 2) throw fail("photo_missing", `фото пришло ${rec.photos.length}, JPEG ${rec.photos.filter((p) => p.jpeg).length}, нужно 2`);
      }
      rec.ok = true; out.ok += 1;
    } catch (e) {
      rec.why = String(e?.message ?? e).slice(0, 300); rec.code = e?.code ?? "shoot_error"; out.failed += 1;
      // до заказа — задача failed с кодом (резерв вернулся); после заказа деньги ушли — задачу ведёт сервер (готово/сбой фото)
      if (!ordered && !out.lost && rec.code !== "bad_transition") {
        const r = await deps.mark(t.id, "failed", codeOf(rec.code, "shoot_error"));
        if (r.lost) out.lost = true;
      }
    }
    rec.sec = Math.round((Date.now() - t0) / 100) / 10;
    out.rooms.push(rec);
    deps.log?.(`ROOM ${t.roomId} ${rec.variant || "?"}: ${rec.ok ? (dry ? `снято ${rec.files.length} кадра (сухой ход)` : `фото ${rec.photos.length}`) : `НЕ СНЯТО [${rec.code}] — ${rec.why}`}, ${rec.sec} с`);
  }
  return out;
}

/** Партия очереди → задание съёмки: тур из `tourPath` (тот же, что `jobId`), комнаты по порядку задач, вариант и позы задачи. */
export function batchJob(batch, base) {
  const m = /^\/try\/([A-Za-z0-9_-]{22})\/tour$/.exec(String(batch?.tourPath ?? ""));
  if (!m || m[1] !== batch.jobId) throw new Error(`партия: tourPath ${JSON.stringify(batch?.tourPath)} не тур ${batch?.jobId}`);
  if (!Array.isArray(batch.tasks) || !batch.tasks.length) throw new Error("партия: задач нет");
  return parseJob({ tour: m[1], base, rooms: batch.tasks.map((t) => ({ room_id: t.roomId, variant: t.variantId,
    poses: (t.cams ?? []).slice(0, 2).map((c) => ({ ...c })) })) });
}

/** Ручки исполнителя на проде (`/api/trial/worker/photos/*`, Bearer воркера). Ключ — только в заголовке. → {status, body} */
export function workerApi(base, token, fetchFn = fetch) {
  const post = async (path, body) => {
    try {
      const r = await fetchFn(`${base}/api/trial/worker/photos/${path}`, { method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${token}` }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json().catch(() => null) };
    } catch (e) { return { status: 0, body: { error: `сеть: ${String(e?.message ?? e).slice(0, 120)}` } }; }
  };
  const lease = (b) => ({ batchId: b.batchId, leaseToken: b.leaseToken });
  return {
    claim: (workerId) => post("claim", { workerId }),
    mark: async (b, taskId, status, code) => {
      const r = await post("task", { ...lease(b), taskId, status, ...(code ? { code } : {}) });
      return { ok: r.status === 200, lost: r.body?.error === "lease_lost", error: r.body?.error ?? (r.status === 200 ? "" : `http_${r.status}`) };
    },
    release: (b, code) => post("release", { ...lease(b), code }),
    finish: (b, note) => post("finish", { ...lease(b), ...(note ? { note: note.slice(0, 400) } : {}) }),
  };
}

/** Ядер на съёмку: 3D без видеокарты рисует процессор (замер — в отчёте T-115/5); юнит DEV режет квотой и ставит TOUR_SLOT_CORES. */
export const slotCores = (env) => String(Math.max(1, Math.min(8, Number(env.TOUR_SLOT_CORES) || 6)));

/** Очередь тяжёлых прогонов: вне слота → [heavy-slot.sh, аргументы] перезапуска себя; в слоте (HEAVY_SLOT_HELD) или TOUR_NO_SLOT=1 → null.
 *  `urgency` партии: срочная (сразу после подтверждения) — `--prio 1 --short`, догон — обычная долгая очередь. */
export function underSlot(env, argv, node, self, urgency = "") {
  if (env.HEAVY_SLOT_HELD || env.TOUR_NO_SLOT === "1") return null;
  const prio = urgency === "urgent" ? ["--prio", "1", "--short"] : urgency === "catchup" ? ["--long"] : [];
  return [fileURLToPath(new URL("./heavy-slot.sh", import.meta.url)),
    ["tour-photos", "--min-gb", "3", "--cores", slotCores(env), "--timeout", env.TOUR_SLOT_WAIT_S ?? "3600", ...prio, "--", node, self, ...argv]];
}

const arg = (k) => { const i = process.argv.indexOf(k); return i >= 0 ? process.argv[i + 1] : undefined; };
const stamp = () => { const d = new Date(), p = (x) => String(x).padStart(2, "0"); return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`; };

/** Вызов проверяется ДО очереди тяжёлых прогонов (неверное задание не занимает билет на 6 ядер): плохое задание — код 2. */
function jobOrExit() {
  try {
    return parseJob(arg("--job") ? JSON.parse(readFileSync(arg("--job"), "utf8")) : { tour: arg("--tour"), base: arg("--base"), rooms: roomsArg(arg("--rooms")) });
  } catch (e) { console.error(String(e.message ?? e)); process.exit(2); }
}

/** Браузер + контекст тура: события посетителя — мимо, Bearer — к адресам тура и к его ручке фото (заказ класса `auto`). */
async function openTour(base, tour, token, errs) {
  const { chromium } = await import("@playwright/test");
  const browser = await launchLive(chromium, true);
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "ru-RU" });
  await ctx.route(/\/api\/events/, (r) => r.fulfill({ status: 204, body: "" }));   // это не посетитель
  const bearer = await routeTourBearer(ctx, `${base}/try/${tour}/tour`, token);
  if (bearer) {
    const origin = new URL(base).origin, photo = `/api/trial/${tour}/photo`;
    await ctx.route((x) => x.origin === origin && (x.pathname === photo || x.pathname === photo + "s"),
      (r) => r.continue({ headers: { ...r.request().headers(), authorization: `Bearer ${token}` } }));
  }
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
  return { browser, page, bearer };
}

/** Признаки страницы, когда тур не готов (данные, тур, варианты, 3D) — разбирать без повторной очереди. */
const pageSigns = (page) => page ? page.evaluate(() => [typeof D !== "undefined" && !!D ? "данные есть" : "данных нет",
  typeof TRIAL === "function" && TRIAL() ? "тур" : "не тур", typeof allVariants === "function" ? `вариантов ${allVariants().length}` : "нет allVariants",
  typeof LIVE !== "undefined" ? `3D ${LIVE.ok}/${LIVE.state}` : "нет LIVE"].join(", ")).catch((x) => `признаки не прочитаны: ${String(x?.message ?? x).slice(0, 80)}`)
  : Promise.resolve("страницы нет");

/** Функции страницы для ядер (`runTour`/`runBatch`): список вариантов, номер состояния, кадры. */
const pageDeps = (page, out) => ({
  list: () => page.evaluate(() => allVariants().map((v, i) => ({ i, id: String(v.id || ""), room: roomIdOf(v), items: (v.items || []).length,
    pending: typeof varPending === "function" && varPending(v), refused: typeof varRefused === "function" && varRefused(v) }))),
  stateOf: (i) => page.evaluate((k) => { pickVariant(k); return curStateId(); }, i),
  capture: (i, poses, upload = false) => captureViews(page, i, { noUpload: !upload, b64: true, poses }),
  save: (name, b64) => { const p = join(out, name); writeFileSync(p, Buffer.from(b64, "base64")); return p; },
  log: (l) => console.log(l),
});

/** СУХОЙ ХОД без очереди (`--tour`/`--job`): комнаты задания, кадры в папку, ничего не грузит и не заказывает. */
async function mainDry() {
  const job = jobOrExit();
  const out = arg("--out") ?? join(homedir(), "remlab-logs", "tour-photos", `dry-${stamp()}`);
  mkdirSync(out, { recursive: true });
  const errs = [], t0 = Date.now();
  let res, page = null, browser = null;
  try {
    const o = await openTour(job.base, job.tour, process.env.TRIAL_WORKER_TOKEN || "", errs);
    browser = o.browser; page = o.page;
    await openLivePage(page, tourUrl(job), { gl: true, ready: TOUR_READY });
    const pageMs = Date.now() - t0;
    console.log(`тур ${job.tour}: страница готова за ${(pageMs / 1000).toFixed(1)} с; ключ воркера: ${o.bearer ? "есть" : "нет (только подтверждённый тур)"}; папка ${out}`);
    res = await runTour(job, pageDeps(page, out));
    res.pageMs = pageMs; res.pageErrors = errs.slice(0, 5);
  } catch (e) {
    const why = `страница тура не готова: ${String(e?.message ?? e).split("\n")[0].slice(0, 160)} [${await pageSigns(page)}]`;
    console.log(`ТУР ${job.tour}: НЕ СНЯТ — ${why}`);
    res = { rooms: job.rooms.map((r) => ({ room_id: r.room_id, ok: false, why, files: [] })), ok: 0, failed: job.rooms.length, pageErrors: errs.slice(0, 5) };
  } finally { await browser?.close(); }
  res.tour = job.tour; res.dry = true; res.totalSec = Math.round((Date.now() - t0) / 100) / 10;
  writeFileSync(join(out, "result.json"), JSON.stringify(res, null, 1));
  console.log(`итого: снято комнат ${res.ok}, не снято ${res.failed}, ${res.totalSec} с; заказов 0 (сухой ход) → ${join(out, "result.json")}`);
  process.exit(res.failed ? 3 : 0);
}

/** Заказ фото кнопкой страницы по снятым и загруженным кадрам (`__liveCap`), классом `auto` по задаче. → {ok, urls, sec} | {ok:false, error, code} */
const pageOrder = (page) => async (i, taskId) => {
  const t0 = Date.now();
  const r = await page.evaluate(async ([k, task]) => {
    const c = globalThis.__liveCap;
    if (cur !== k) return { error: `на странице вариант ${cur}, снимали ${k}`, code: "variant_changed" };
    if (!c || !c.views) return { error: "нет загруженных кадров", code: "no_views" };
    const extra = { views: c.views, clay: c.clay, sheet: c.sheet, auto_task: task };
    return await new Promise((ok) => makePhoto("realistic", "", "", { bg: true, extra, progress: () => {},
      fail: (m, code) => ok({ error: String(m), code: code || "" }),
      done: (n0) => ok({ ok: true, urls: shots.slice(n0).map((s) => s.url), frames: (shots[n0] || {}).timing?.frames }) }));
  }, [i, taskId]);
  if (r.ok && r.frames && r.frames !== "browser") return { error: `фото снято не из кадров браузера (${r.frames})`, code: "not_browser_frames", ...r, ok: false };
  return { ...r, sec: Math.round((Date.now() - t0) / 1000) };
};

/** Скачать готовые фото (адреса тура — с Bearer) и проверить, что это JPEG. → [{url, path, bytes, jpeg}] */
const photoFetcher = (base, token, out) => async (urls, roomId, variant) => {
  const got = [];
  for (let k = 0; k < urls.length; k++) {
    const url = new URL(urls[k], base).href, rec = { url: urls[k], path: "", bytes: 0, jpeg: false };
    try {
      const r = await fetch(url, { headers: token ? { authorization: `Bearer ${token}` } : {} });
      const b = Buffer.from(await r.arrayBuffer());
      rec.bytes = b.length; rec.jpeg = r.ok && b.length > 10_000 && b[0] === 0xff && b[1] === 0xd8;
      rec.path = join(out, frameName(roomId, variant, k, "photo-"));
      writeFileSync(rec.path, b);
      if (!r.ok) rec.why = `http ${r.status}`;
    } catch (e) { rec.why = String(e?.message ?? e).slice(0, 120); }
    got.push(rec);
  }
  return got;
};

/**
 * СЪЁМКА ПАРТИИ (в слоте тяжёлых прогонов). Тур не открылся / не тур / версия не та — партия обратно в очередь (`tour_not_ready` /
 * `version_mismatch`, попытка не тратится), exit 3. Иначе — `runBatch`; итог: сухой ход, стоп по отказу сервиса или `--max-tasks` — партия
 * обратно в очередь (взятые и не заказанные задачи снова ждут), всё прошло — партия закрыта (`finish`).
 */
async function shootBatch(batch, out, opt) {
  const token = process.env.TRIAL_WORKER_TOKEN || "", base = opt.base, api = workerApi(base, token);
  writeFileSync(join(out, "started"), new Date().toISOString());   // внешний процесс перестаёт продлевать аренду сам
  const errs = [], t0 = Date.now();
  let res, page = null, browser = null, back = "";
  try {
    const job = batchJob(batch, base);
    const o = await openTour(base, job.tour, token, errs);
    browser = o.browser; page = o.page;
    try { await openLivePage(page, tourUrl(job), { gl: true, ready: TOUR_READY }); }
    catch (e) { back = "tour_not_ready"; throw new Error(`тур не готов: ${String(e?.message ?? e).split("\n")[0].slice(0, 120)} [${await pageSigns(page)}]`); }
    const ver = await page.evaluate(() => window.__TOUR_VER);
    if (ver !== batch.bundleVersion) { back = "version_mismatch"; throw new Error(`версия тура на странице ${ver}, в партии ${batch.bundleVersion}`); }
    const pageMs = Date.now() - t0;
    console.log(`партия ${batch.batchId} тур ${job.tour} v${ver}: страница за ${(pageMs / 1000).toFixed(1)} с, задач ${batch.tasks.length}, ${opt.dry ? "СУХОЙ ХОД" : "с заказом"}; папка ${out}`);
    const deps = { ...pageDeps(page, out), mark: (taskId, status, code) => api.mark(batch, taskId, status, code),
      order: pageOrder(page), fetchPhotos: photoFetcher(base, token, out) };
    res = await runBatch(batch, job, deps, { dry: opt.dry, maxTasks: opt.maxTasks });
    res.pageMs = pageMs;
  } catch (e) {
    const why = String(e?.message ?? e).slice(0, 300);
    console.log(`ПАРТИЯ ${batch.batchId}: НЕ СНЯТА — ${why}`);
    res = { rooms: [], ok: 0, failed: batch.tasks.length, ordered: 0, refusals: 0, left: batch.tasks.length, lost: false, stop: back || "page_error", why };
    back ||= "shooter_error";
  } finally { await browser?.close(); }
  res.pageErrors = errs.slice(0, 5);
  let end;
  if (res.lost) end = { action: "none", why: "lease_lost" };
  else if (back || opt.dry || res.stop || res.left) {
    const code = back || (opt.dry ? "dry_run" : res.stop || "max_tasks");
    end = { action: "release", code, ...(await api.release(batch, code)) };
  } else end = { action: "finish", ...(await api.finish(batch, `ok ${res.ok}, failed ${res.failed}, ordered ${res.ordered}`)) };
  Object.assign(res, { batchId: batch.batchId, jobId: batch.jobId, bundleVersion: batch.bundleVersion, attempt: batch.attempt, urgency: batch.urgency,
    dry: !!opt.dry, end, totalSec: Math.round((Date.now() - t0) / 100) / 10 });
  writeFileSync(join(out, "result.json"), JSON.stringify(res, null, 1));
  console.log(`итого: снято ${res.ok}, не снято ${res.failed}, заказов ${res.ordered}, отказов ${res.refusals}, осталось ${res.left}; партия: ${end.action}${end.code ? " " + end.code : ""} (${end.status ?? "-"}), ${res.totalSec} с → ${join(out, "result.json")}`);
  return res.failed || back || res.left || res.lost || opt.dry ? 3 : 0;
}

/** `--claim`: партия под аренду → съёмка в слоте тяжёлых прогонов (пока ждём слот — продлеваем аренду) → итог. */
async function mainClaim() {
  const token = process.env.TRIAL_WORKER_TOKEN || "";
  const base = String(arg("--base") ?? process.env.TRIAL_API_URL ?? PROD).replace(/\/+$/, "");
  const dry = process.argv.includes("--dry"), maxTasks = arg("--max-tasks") ? Number(arg("--max-tasks")) : Infinity;
  if (!(maxTasks === Infinity || (Number.isInteger(maxTasks) && maxTasks > 0))) { console.error("--max-tasks — целое > 0"); process.exit(2); }
  if (!/^https?:\/\/[^/]+$/.test(base)) { console.error(`--base — только сервер, без пути (${base})`); process.exit(2); }
  if (arg("--only") !== undefined && !ID_RE.test(arg("--only"))) { console.error("--only — id тура, 22 знака"); process.exit(2); }
  const file = arg("--batch-file");
  if (file) {   // внутренний запуск в слоте
    const batch = JSON.parse(readFileSync(file, "utf8"));
    process.exit(await shootBatch(batch, arg("--out"), { base, dry, maxTasks }));
  }
  if (!token) { console.error("нет TRIAL_WORKER_TOKEN в окружении — партию не беру"); process.exit(2); }
  const api = workerApi(base, token);
  const got = await api.claim(`dev-${hostname()}-${process.pid}`.slice(0, 80));
  if (got.status !== 200) { console.error(`очередь: claim ${got.status} ${got.body?.error ?? ""}`); process.exit(4); }
  const batch = got.body?.batch;
  if (!batch) { console.log("очередь автофото пуста"); process.exit(0); }
  if (arg("--only") && batch.jobId !== arg("--only")) {   // проба на своём туре: чужую партию не снимаем — сразу обратно (попытка не тратится)
    const r = await api.release(batch, "not_this_worker");
    console.log(`партия ${batch.batchId} — тур ${batch.jobId}, не ${arg("--only")}: возвращена (${r.status})`); process.exit(0);
  }
  if (!batch.tasks?.length) {   // открытых задач не осталось (всё заказано/закрыто) — партию закрыть, слот не брать
    const r = await api.finish(batch, "no_open_tasks");
    console.log(`партия ${batch.batchId}: открытых задач нет — закрыта (${r.status})`); process.exit(0);
  }
  const out = arg("--out") ?? join(homedir(), "remlab-logs", "tour-photos", `${stamp()}-${batch.batchId.slice(0, 8)}`);
  mkdirSync(out, { recursive: true });
  const bf = join(out, "batch.json");
  writeFileSync(bf, JSON.stringify(batch), { mode: 0o600 });   // аренда партии — только этому запуску
  console.log(`взял партию ${batch.batchId}: тур ${batch.jobId} v${batch.bundleVersion}, задач ${batch.tasks.length}, попытка ${batch.attempt}, ${batch.urgency}`);
  const argv = ["--claim", "--batch-file", bf, "--out", out, "--base", base, ...(dry ? ["--dry"] : []), ...(arg("--max-tasks") ? ["--max-tasks", arg("--max-tasks")] : [])];
  const slot = underSlot(process.env, argv, process.execPath, process.argv[1], batch.urgency);
  if (!slot) process.exit(await shootBatch(batch, out, { base, dry, maxTasks }));
  const { spawn } = await import("node:child_process");
  const first = batch.tasks[0]?.id;
  const beat = setInterval(async () => {   // ждём слот — аренда не должна истечь (каждая отметка продлевает); съёмка начнётся — продлевает сама
    if (existsSync(join(out, "started")) || !first) return;
    const r = await api.mark(batch, first, "shooting");
    if (!r.ok) console.log(`аренда при ожидании слота: ${r.error}`);
  }, 240_000);
  const rc = await new Promise((ok) => spawn("bash", [slot[0], ...slot[1]], { stdio: "inherit" }).on("exit", (c) => ok(c ?? 1)));
  clearInterval(beat);
  if (!existsSync(join(out, "result.json"))) {   // слот не дождались (124) или съёмщик упал без итога — партию вернуть, не держать аренду
    const code = rc === 124 ? "slot_busy" : "shooter_crash", r = await api.release(batch, code);
    console.log(`съёмка не дошла до итога (код ${rc}) — партия возвращена: ${code} → ${r.status} ${r.body?.status ?? r.body?.error ?? ""}`);
    process.exit(3);
  }
  process.exit(rc);
}

async function selftest() {
  const res = [];
  const check = (ok, msg, got) => { res.push(!!ok); console.log(ok ? `OK   ${msg}` : `FAIL ${msg}: ${JSON.stringify(got)}`); };
  const T = "aRQVC9nJ1g1WqBTXeA6VqA";
  const bad = (j) => { try { parseJob(j); return ""; } catch (e) { return e.message; } };
  check(parseJob({ tour: T, rooms: [{ room_id: "bedroom-1" }] }).base === PROD, "задание: сервер по умолчанию — прод", null);
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
  check(tourUrl(parseJob({ tour: T, rooms: [{ room_id: "a" }] })) === `${PROD}/try/${T}/tour?live=force&quiz=0&lang=ru`
    && TOUR_READY.includes("TRIAL()") && !TOUR_READY.includes("FLAT"), "адрес тура: покупательский, 3D принудительно, без опроса; ждём именно тур и без карточки квартиры витрины", null);
  const L = [{ i: 0, id: "b1-s", room: "bedroom-1", items: 0 }, { i: 1, id: "b1-m", room: "bedroom-1", items: 4, pending: true },
    { i: 2, id: "b1-l", room: "bedroom-1", items: 5 }, { i: 3, id: "lv", room: "living", items: 7 }];
  check(pickIndex(L, { room_id: "bedroom-1" }) === 2 && pickIndex(L, { room_id: "bedroom-1", variant: "b1-s" }) === 0 && pickIndex(L, { room_id: "kitchen" }) === -1
    && pickIndex(L, { room_id: "living", variant: "b1-l" }) === -1, "вариант: заданный — этой комнаты; иначе первый с мебелью, не ждущий", null);
  check(frameName("bedroom-1", "b1/../x", 1) === "bedroom-1-b1_x-C2.jpg" && frameName("lv", "v", 0, "photo-") === "lv-v-photo-1.jpg",
    "имя кадра и фото — безопасные знаки", frameName("bedroom-1", "b1/../x", 1));
  const sNo = underSlot({}, ["--tour", T], "/n", "/s.mjs");
  check(sNo[0].endsWith("/heavy-slot.sh") && sNo[1].join(" ") === `tour-photos --min-gb 3 --cores 6 --timeout 3600 -- /n /s.mjs --tour ${T}`
    && underSlot({ HEAVY_SLOT_HELD: "1" }, [], "/n", "/s") === null && underSlot({ TOUR_NO_SLOT: "1" }, [], "/n", "/s") === null,
  "очередь: 6 ядер, 3 ГБ (3D процессором); в слоте — без", sNo);
  const sU = underSlot({ TOUR_SLOT_CORES: "2" }, ["--claim"], "/n", "/s", "urgent")[1].join(" "), sC = underSlot({}, ["--claim"], "/n", "/s", "catchup")[1].join(" ");
  check(sU === "tour-photos --min-gb 3 --cores 2 --timeout 3600 --prio 1 --short -- /n /s --claim" && sC.includes("--cores 6") && sC.includes("--long -- ")
    && !sC.includes("--prio"), "срочная партия — --prio 1 --short (ядра из TOUR_SLOT_CORES юнита); догон — обычная долгая очередь", [sU, sC]);
  check(codeOf("No-Credits!") === "no_credits" && codeOf("") === "order_failed" && codeOf("Кадр не принят", "x") === "x" && codeOf("a".repeat(60)).length === 40,
    "код отказа для ручки — [a-z_] до 40 знаков, иначе запасной", codeOf("No-Credits!"));

  // ЯДРО НА ЗАГЛУШКАХ СТРАНИЦЫ: настоящий `pageCapture` из общего модуля на `globalThis` — комнаты по одной, кадры своей комнаты
  const { pageCapture } = await import("./lib/live-shoot.mjs");
  const g = globalThis, picks = [];
  let room = "", state = {};
  const V = [{ id: "b1-l", room_id: "bedroom-1", items: [1] }, { id: "lv", room_id: "living", items: [1] }, { id: "b2-l", room_id: "bedroom-2", items: [1] }];
  Object.assign(g, { cur: 0, cams: null, VW: { mode: "walk" }, LIVE: { ok: true, scene: {}, state: "ready" },
    allVariants: () => V, roomIdOf: (v) => v.room_id, pickVariant: (i) => { picks.push(i); g.cur = i; g.cams = null; room = V[i].room_id; },   // как `index.html:load` — cams=null
    curStateId: () => state[V[g.cur].room_id] ?? "s-" + V[g.cur].id, openLiveWindow: () => {}, vwMode: () => {},
    liveHere: () => ({}), camPoseOf: (c) => ({ x: c.x, y: c.y, rot: c.rot || 0, fov: c.fov || 72 }), loadCams: () => [{ x: 1, y: 1 }, { x: 2, y: 2 }],
    vwCaptureViews: async (o) => { return room === "bedroom-2" ? null
      : { blobs: [new Blob([`${room}-1`]), new Blob([`${room}-2`])], size: "2048×1489", ms: { capture: 5 }, room: room + "-sig",
        ...(o?.noUpload ? {} : { views: [{ camera: "C1", id: "a" }, { camera: "C2", id: "b" }] }) }; } });
  const saved = {}, logs = [];
  const fdeps = {
    list: async () => V.map((v, i) => ({ i, id: v.id, room: v.room_id, items: v.items.length })),
    stateOf: async (i) => { g.pickVariant(i); return g.curStateId(); },
    capture: (i, poses, upload = false) => pageCapture({ i, noUpload: !upload, b64: true, poses, waitTicks: 2 }),
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

  // ПАРТИЯ ОЧЕРЕДИ НА ЗАГЛУШКАХ РУЧЕК: отметки, заказ ровно один на задачу, отказы с кодом, стоп по отказу сервиса и по аренде
  const B = { batchId: "B".repeat(22), leaseToken: "L".repeat(24), jobId: T, tourPath: `/try/${T}/tour`, bundleVersion: 7, attempt: 1, urgency: "urgent",
    tasks: [["t-living-1", "living", "lv"], ["t-bed1-001", "bedroom-1", "b1-l"], ["t-bed2-001", "bedroom-2", "b2-l"]].map(([id, roomId, variantId], ord) => ({
      id, roomId, variantId, style: "scandi", ord, status: "reserved", cams: [{ name: "C1", x: 5, y: 6, rot: 10, fov: 80, pose: 3 }, { name: "C2", x: 7, y: 8, pose: 3 }] })) };
  const BJ = batchJob(B, PROD);
  check(BJ.tour === T && BJ.rooms.map((x) => `${x.room_id}:${x.variant}`).join(",") === "living:lv,bedroom-1:b1-l,bedroom-2:b2-l" && BJ.rooms[0].poses[0].pose === 3
    && /не тур/.test((() => { try { batchJob({ ...B, tourPath: "/try/x/tour" }, PROD); return ""; } catch (e) { return e.message; } })()),
  "партия → задание: тур из tourPath (= jobId), комнаты по порядку задач, вариант и позы задачи как есть", BJ);
  const mk = (over = {}) => {
    const marks = [], orders = [];
    return { marks, orders, deps: { ...fdeps, log: () => {},
      mark: async (id, st, code) => { marks.push([id, st, code ?? ""]); return over.mark?.(id, st) ?? { ok: true }; },
      order: async (i, id) => { orders.push([i, id]); return over.order?.(i, id) ?? { ok: true, urls: ["/p/1.jpg", "/p/2.jpg"], sec: 30 }; },
      fetchPhotos: async (urls) => urls.map((u) => ({ url: u, path: "/out" + u, bytes: 50_000, jpeg: true })) } };
  };
  let m = mk();
  r = await runBatch(B, BJ, m.deps);
  check(r.ok === 2 && r.failed === 1 && r.ordered === 2 && m.orders.map((o) => o[1]).join() === "t-living-1,t-bed1-001"
    && m.marks.map((x) => x.join(":")).join(" ") === "t-living-1:shooting: t-bed1-001:shooting: t-bed2-001:shooting: t-bed2-001:failed:capture_failed"
    && r.rooms[0].photos.length === 2 && r.rooms[0].poses[0].x === 5,
  "боевой ход: отметка → кадры с позами задачи и загрузкой → один заказ на задачу → 2 фото; не снялось до заказа — failed с кодом, остальные идут", { r, marks: m.marks });
  m = mk();
  r = await runBatch(B, BJ, m.deps, { dry: true });
  check(r.ok === 2 && r.ordered === 0 && m.orders.length === 0 && m.marks.filter((x) => x[1] === "failed").length === 1,
    "сухой ход: кадры сняты, загрузки и заказа нет", { r, marks: m.marks });
  m = mk({ order: (i, id) => id === "t-living-1" ? { error: "Нет средств", code: "no_credits" } : { ok: true, urls: ["/a", "/b"] } });
  r = await runBatch(B, BJ, m.deps);
  check(r.ordered === 0 && r.refusals === 1 && r.stop === "no_credits" && r.left === 2 && m.orders.length === 1
    && m.marks.some((x) => x.join(":") === "t-living-1:failed:no_credits"),
  "отказ сервиса (нет денег) — счётчик отказов, дальше по партии не заказываем, остальные ждут в очереди", { r, marks: m.marks });
  m = mk({ order: () => ({ ok: true, urls: ["/a"] }) });
  r = await runBatch({ ...B, tasks: B.tasks.slice(0, 1) }, { ...BJ, rooms: BJ.rooms.slice(0, 1) }, m.deps);
  check(r.ordered === 1 && r.failed === 1 && r.rooms[0].code === "photo_missing" && !m.marks.some((x) => x[1] === "failed"),
    "после заказа деньги ушли: фото не хватает — громко в итоге, задачу failed не отмечаем (её ведёт сервер)", { r, marks: m.marks });
  m = mk({ mark: (id) => id === "t-bed1-001" ? { ok: false, lost: true, error: "lease_lost" } : { ok: true } });
  r = await runBatch(B, BJ, m.deps);
  check(r.lost && r.ordered === 1 && r.left === 1 && m.orders.length === 1 && m.marks.length === 2,
    "аренда потеряна — стоп сразу: без заказа и без отметок дальше", { r, marks: m.marks });
  m = mk();
  r = await runBatch(B, BJ, m.deps, { maxTasks: 1 });
  check(r.ok === 1 && r.left === 2 && m.orders.length === 1 && m.marks.length === 1, "--max-tasks 1: одна комната, остальные остаются в очереди", r);
  m = mk({ order: () => ({ ok: false, error: "задача уже заказана", code: "auto_task_busy" }) });
  r = await runBatch({ ...B, tasks: B.tasks.slice(0, 1) }, { ...BJ, rooms: BJ.rooms.slice(0, 1) }, m.deps);
  check(r.refusals === 1 && !r.stop && r.rooms[0].code === "auto_task_busy", "второй заказ той же задачи сервер не пускает — отказ с кодом, не стоп партии", r);

  // ручки и ключ: Bearer только в заголовке, адреса ручек, аренда в теле; ключ нигде не печатается
  const calls = [];
  const fakeFetch = async (url, init) => { calls.push({ url, auth: init.headers.authorization, body: JSON.parse(init.body) });
    return { status: url.endsWith("/task") ? 409 : 200, json: async () => (url.endsWith("/task") ? { ok: false, error: "lease_lost" } : { ok: true, batch: null }) }; };
  const api = workerApi(PROD, "секрет-123", fakeFetch);
  const c0 = await api.claim("dev-1"), m0 = await api.mark(B, "t-living-1", "failed", "capture_failed");
  await api.release(B, "dry_run");
  check(c0.status === 200 && c0.body.batch === null && m0.lost && !m0.ok && calls.map((x) => x.url.split("/").pop()).join() === "claim,task,release"
    && calls.every((x) => x.auth === "Bearer секрет-123" && x.url.startsWith(`${PROD}/api/trial/worker/photos/`))
    && calls[1].body.leaseToken === B.leaseToken && calls[1].body.code === "capture_failed" && calls[2].body.code === "dry_run",
  "ручки исполнителя: claim/task/release с Bearer воркера; 409 lease_lost распознан", calls.map((x) => x.url));
  // ключ воркера — только к адресам этого тура и нигде не печатается
  const routes = [];
  const ctx = { route: async (mm, h) => routes.push({ m: mm, h }) };
  const okB = await routeTourBearer(ctx, `${PROD}/try/${T}/tour`, "секрет-123");
  const rm = routes[0]?.m;
  check(okB && rm(new URL(`${PROD}/try/${T}/tour/demo-data.json`)) && !rm(new URL(`${PROD}/api/render/frame`))
    && !rm(new URL(`https://evil.example/try/${T}/tour`)) && !(await routeTourBearer({ route: async () => {} }, `${PROD}/demo/`, "k"))
    && !JSON.stringify(r).includes("секрет") && !logs.join("\n").includes("секрет"),
  "Bearer — только адреса этого тура на том же сервере; не тур — без ключа; в итоге и журнале ключа нет", null);
  process.exit(res.every(Boolean) ? 0 : 1);
}

if (process.argv.includes("--selftest")) await selftest();
else if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  if (process.argv.includes("--claim")) await mainClaim();
  else {
    const slot = underSlot(process.env, process.argv.slice(2), process.execPath, process.argv[1]);
    jobOrExit();
    if (!slot) await mainDry();
    else {
      const { spawnSync } = await import("node:child_process");
      const rs = spawnSync("bash", [slot[0], ...slot[1]], { stdio: "inherit" });
      process.exit(rs.status ?? 1);
    }
  }
}
