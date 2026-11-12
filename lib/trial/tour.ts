// Тур пробы: `/try/<id>/tour` — ТА ЖЕ страница `/demo`, собранная под загруженный план (план agent-trial-08, «демо = шаблон»).
// Страница и общие файлы — ЗАКРЕПЛЁННАЯ копия витрины на задание (`tour/_releases/<версия>/`), данные — `readTourData`:
// выкладка `/demo` идёт через `rsync --delete` и иначе развела бы код и данные (Codex 09.11, п.2).
// Отдаём только файлы из списка, после проверки id и пути; исходный файл плана и любые другие файлы наружу не идут.

import path from "node:path";

import type { TrialJobView } from "@/contracts/trial";
import type { LatestBundle } from "@/lib/trial/repo-bundle";
import { gateCheck, keyCookie, OPEN, type TourGate } from "@/lib/trial/buyer-gate";
import { TRIAL_HEADERS, trialDemoDir, trialDir } from "@/lib/trial/config";
import { validId } from "@/lib/trial/http";
import { acceptsBrotli, brotliPage } from "@/lib/trial/tour-brotli";
import { contentTag, encodedTag, IMMUTABLE, REVALIDATE, tagMatches } from "@/lib/trial/tour-cache";
import { MARKET_LANG, tourHref } from "@/lib/trial/i18n";
import { pageCards, readCard } from "@/lib/trial/tour-cards";
import { jobRelease, readRegular, readTourData, releaseDir } from "@/lib/trial/tour-files";
import { injectTour } from "@/lib/trial/tour-page";
import { stubHtml, type StubKind, type StubOpts } from "@/lib/trial/tour-stub";

const SCENE_JS = /^lib\/scene\.[a-f0-9]{6,64}\.js$/;
const BASKET_JS = /^lib\/basket\.[a-f0-9]{6,64}\.js$/;
// общие картинки витрины — только имя файла в одной папке, без подкаталогов
const SHARED_IMG = /^(img|topsprites)\/([\w.-]{1,160}\.(?:jpe?g|png|webp))$/;
// готовый снимок карточки комнаты этого задания (T-20261112-29, `tour-cards.ts`): имя — хеш содержимого
const CARD_IMG = /^cards\/([a-f0-9]{16}\.jpg)$/;

export type TourTarget =
  | { kind: "page" }
  | { kind: "data" }
  | { kind: "version" }
  | { kind: "release"; rel: string; type: string }
  | { kind: "shared"; url: string }
  | { kind: "card"; file: string };

const JS = "text/javascript; charset=utf-8";
const JSON_TYPE = "application/json; charset=utf-8";
const HTML = "text/html; charset=utf-8";

/** Адрес внутри тура → что отдать. Всё, что не в списке, — null (404): обход `..`, чужие расширения и папки не проходят. */
export function tourTarget(parts: readonly string[]): TourTarget | null {
  if (parts.length === 0) return { kind: "page" };
  if (parts.some((p) => p === "" || p === "." || p === ".." || p.includes("\\") || p.includes("\0"))) return null;
  const rel = parts.join("/");
  if (rel === "demo-data.json") return { kind: "data" };
  if (rel === "version.json") return { kind: "version" };
  if (rel === "lib/scene.json" || rel === "rt-meshes.json") return { kind: "release", rel, type: JSON_TYPE };
  if (SCENE_JS.test(rel) || BASKET_JS.test(rel)) return { kind: "release", rel, type: JS };
  if (SHARED_IMG.test(rel)) return { kind: "shared", url: `/demo/${rel}` }; // картинки товаров общие (103 МБ на витрине), личного в них нет
  const card = CARD_IMG.exec(rel);
  if (card) return { kind: "card", file: card[1]! };
  return null;
}

const headers = (extra: Record<string, string> = {}): Record<string, string> => ({
  ...TRIAL_HEADERS,
  "X-Robots-Tag": "noindex, nofollow",
  "X-Content-Type-Options": "nosniff",
  ...extra,
});
const text = (status: number, body: string, extra: Record<string, string> = {}): Response =>
  new Response(body, { status, headers: headers({ "Content-Type": "text/plain; charset=utf-8", ...extra }) });

/** `latest` — чтение последней версии данных (`repo-bundle.ts:latestBundle`; передаёт маршрут — здесь импорт дал бы круг модулей);
 *  нет — только запасной `demo-data.json`. `pin` — закрепить страницу (`tour-bundle.ts:ensureJobRelease`, тот же круг): версия
 *  данных есть, а закрепления нет (сбой при публикации) — закрепляем при первом открытии. `stub` — язык и ключ для страницы-заглушки. */
export type TourDeps = {
  view: (id: string) => Promise<TrialJobView | "expired" | undefined>;
  latest?: (id: string, dir: string) => Promise<LatestBundle>;
  pin?: (id: string, dir: string) => Promise<unknown>;
  dir?: string;
  stub?: StubOpts;
  /** Сверка кэша (T-20261110-43): If-None-Match запроса; `keyed` — в адресе страницы ключ агента `k` (такая страница не хранится). */
  ifNoneMatch?: string | null;
  keyed?: boolean;
  /** Accept-Encoding запроса: страница — brotli, если клиент просит (`tour-brotli.ts`). */
  acceptEncoding?: string | null;
  /** Папка витрины (`trialDemoDir`): из её таблицы лёгких копий тур добирает модели, которых нет в закреплённой (T-23). */
  demoDir?: string;
  /** Ворота ссылки покупателя (`buyer-gate.ts`, T-20261112-40): страница, данные и снимки — только агенту, пока не подтверждено.
   *  Нет — открыто (юнит-тесты прочих веток); маршрут передаёт всегда. */
  gate?: TourGate;
};
const NO_LATEST = async (): Promise<LatestBundle> => "not_ready";

const RT_TABLE = "rt-meshes.json";

/**
 * ЛЁГКИЕ КОПИИ, ПОЯВИВШИЕСЯ ПОСЛЕ ЗАКРЕПЛЕНИЯ ТУРА (T-20261111-23): таблица `rt-meshes.json` закреплена с витриной на день публикации
 * тура, а мебель тура подбирается из банков пробы, не из вариантов /demo, — копий её моделей в таблице могло не быть (тур aOv8:
 * 4 модели гостиной — исходники по 3,4–3,9 МБ вместо копий 0,2 МБ). Записи закреплённой таблицы не меняем (пересобранная копия
 * другого отпечатка — та же модель), а моделям, которых в ней нет, добавляем записи текущей таблицы витрины: её публикация
 * выкладывает файлы на `/rt/` до таблицы (`tools/assets/publish_rt.sh`), поэтому запись в ней = файл уже отдаётся.
 * Витрины нет или таблица битая — закреплённая как есть.
 */
async function withNewCopies(pinned: Buffer, demoDir: string): Promise<Buffer> {
  const cur = await readRegular(path.join(demoDir, RT_TABLE));
  if (!cur) return pinned;
  try {
    const a = JSON.parse(pinned.toString("utf8")) as { meshes?: Record<string, unknown> };
    const b = JSON.parse(cur.toString("utf8")) as { meshes?: Record<string, unknown> };
    if (!a || typeof a !== "object" || !b?.meshes || typeof b.meshes !== "object") return pinned;
    const meshes = { ...(a.meshes ?? {}) };
    let added = 0;
    for (const [id, e] of Object.entries(b.meshes)) {
      if (!(id in meshes)) {
        meshes[id] = e;
        added += 1;
      }
    }
    return added ? Buffer.from(JSON.stringify({ ...a, meshes })) : pinned;
  } catch {
    return pinned;
  }
}

/** Ответ, который браузер хранит со сверкой (`tour-cache.ts`): метка совпала — 304 без тела с теми же заголовками, нет — тело. */
function cached(body: Uint8Array | string, tag: string, type: string, deps: TourDeps, cacheControl = REVALIDATE): Response {
  const h = headers({ "Content-Type": type, "Cache-Control": cacheControl, ETag: tag });
  if (tagMatches(deps.ifNoneMatch, tag)) return new Response(null, { status: 304, headers: h });
  return new Response(typeof body === "string" ? body : new Uint8Array(body), { headers: h });
}

/** Страница тура: метка по телу; brotli, если клиент просит; с ключом `k` — не хранится (как раньше), без ключа — со сверкой. */
async function pageResponse(out: string, deps: TourDeps, cookie: string | null): Promise<Response> {
  const tag = contentTag(out);
  const br = acceptsBrotli(deps.acceptEncoding);
  const h = headers({ "Content-Type": HTML, Vary: "Accept-Encoding", ...(cookie ? { "Set-Cookie": cookie } : {}) });
  if (!deps.keyed) {
    Object.assign(h, { "Cache-Control": REVALIDATE, ETag: br ? encodedTag(tag, "br") : tag });
    if (tagMatches(deps.ifNoneMatch, tag)) return new Response(null, { status: 304, headers: h });
  }
  if (!br) return new Response(out, { headers: h });
  return new Response(new Uint8Array(await brotliPage(tag, out)), { headers: { ...h, "Content-Encoding": "br" } });
}

/** Тур не открывается: адрес страницы — человеку короткая страница (`tour-stub.ts`), машинным адресам — текст, как раньше. */
function notOpen(page: boolean, status: number, body: string, kind: StubKind, id: string, deps: TourDeps): Response {
  // `TRIAL_HEADERS` — `private, no-store`: та же ссылка скоро откроет тур (готов / подтверждён), заглушка из кэша не покажется
  if (!page) return text(status, body);
  const o = deps.stub ?? { lang: MARKET_LANG };
  return new Response(stubHtml(kind, id, tourHref(id, o.lang, o.k), o),
    { status, headers: headers({ "Content-Type": HTML }) });
}

/** Закрепление страницы тура: есть — его версия; нет, но версия данных опубликована — закрепить сейчас (сбой — null). */
async function releaseOf(dir: string, id: string, view: TrialJobView, pin: TourDeps["pin"]): Promise<string | null> {
  const got = await jobRelease(dir, id);
  if (got || !pin || view.bundleVersion <= 0) return got;
  try {
    await pin(id, dir);
  } catch (e) {
    console.error(`trial ${id}: release_pin_failed (tour) ${e instanceof Error ? e.message : String(e)}`.slice(0, 500));
    return null;
  }
  return jobRelease(dir, id);
}

/** Ответ на запрос тура. id — только формат `TOKEN_RE`; нет задания или бандла — 404; результат снят по сроку — 410 (как `/try/<id>`).
 *  Сама страница в этих случаях — заглушка для человека (T-20261110-07): «готовится» / «не получилось» / «не найден» / «срок истёк». */
export async function tourResponse(id: string, parts: readonly string[], deps: TourDeps): Promise<Response> {
  const page = parts.length === 0;
  if (!validId(id)) return notOpen(page, 404, "not found", "missing", id, deps);
  const target = tourTarget(parts);
  if (!target) return text(404, "not found");
  // общие плитки витрины — переход без запроса к базе (T-20261111-23: 0,2–0,35 с на каждую; новая страница тура берёт их с `/demo/img/`
  // сама, `index.html:trImgAbs`, — переход остаётся для страниц, закреплённых раньше); личного в них нет, задание не нужно
  if (target.kind === "shared") return new Response(null, { status: 302, headers: headers({ Location: target.url }) });
  const view = await deps.view(id);
  if (view === undefined) return notOpen(page, 404, "not found", "missing", id, deps);
  if (view === "expired") return notOpen(page, 410, "expired", "expired", id, deps);
  if (target.kind === "version") {
    // опрос страницы: `version` растёт — перезагрузка; `bundle` — версия данных (база для «Обустроить»); `rebuild` — пересборка идёт / упала
    // `askSizes`/`listing` — окошко «размеры своими словами» на плане (Р2-текст): звать ли агента и что с его текстом (самого текста нет)
    const v = { version: view.resultVersion, bundle: view.bundleVersion, rebuild: view.rebuild, rebuildError: view.rebuildError,
      askSizes: view.askSizes, listing: view.listing, listingError: view.listingError, roomEdit: view.roomEdit, roomEditError: view.roomEditError,
      tourUpdate: view.tourUpdate };
    return new Response(JSON.stringify(v), { headers: headers({ "Content-Type": JSON_TYPE }) });
  }
  // ворота покупателя — до любых данных тура: страница, `demo-data.json`, снимки карточек (код витрины и опрос версии — общие, без личного)
  const personal = target.kind === "page" || target.kind === "data" || target.kind === "card";
  const gate = personal && deps.gate ? await gateCheck(deps.gate, id, page) : OPEN;
  if (!gate.open) return notOpen(page, 403, "not active", "inactive", id, deps);
  const dir = deps.dir ?? trialDir();
  const release = await releaseOf(dir, id, view, deps.pin);
  // задание идёт (или версия есть, а закрепить не вышло) — «готовится»; закрыто без тура — «не получилось»
  const closed = view.bundleVersion <= 0 && ["done", "failed", "cancelled"].includes(view.status);
  if (!release) return notOpen(page, 404, "not ready", closed ? "failed" : "wait", id, deps);
  if (target.kind === "page") {
    const html = await readRegular(path.join(releaseDir(dir, release), "index.html"));
    if (!html) return notOpen(true, 404, "not ready", "wait", id, deps);
    // карта готовых снимков карточек — в саму страницу: карточка с картинкой с первого кадра (T-20261112-29)
    const out = injectTour(html.toString("utf8"), id, view.resultVersion, await pageCards(dir, id));
    return pageResponse(out, deps, gate.pass ? keyCookie(id, gate.pass, deps.gate?.secure ?? false) : null);
  }
  if (target.kind === "data") {
    const data = await readTourData(dir, id, deps.latest ?? NO_LATEST);
    if (!data) return text(404, "not found");
    // версия данных неизменна (`repo-bundle.ts:latestBundle`) — метка `"v<N>"`; запасной файл без версии (v0) — как раньше, не хранится
    if (data.version <= 0) return new Response(new Uint8Array(data.body), { headers: headers({ "Content-Type": JSON_TYPE, ETag: '"v0"' }) });
    return cached(data.body, `"v${data.version}"`, JSON_TYPE, deps);
  }
  if (target.kind === "card") {
    const jpg = await readCard(dir, id, target.file);
    if (!jpg) return text(404, "not found");
    return cached(jpg, contentTag(jpg), "image/jpeg", deps, IMMUTABLE);   // имя = хеш содержимого — не меняется
  }
  const pinned = await readRegular(path.join(releaseDir(dir, release), target.rel));
  if (!pinned) return text(404, "not found");
  const body = target.rel === RT_TABLE ? await withNewCopies(pinned, deps.demoDir ?? trialDemoDir()) : pinned;
  // движок 3D и корзина — хеш содержимого в имени, навсегда; `lib/scene.json` и `rt-meshes.json` — со сверкой (релиз их не меняет)
  const hashed = SCENE_JS.test(target.rel) || BASKET_JS.test(target.rel);
  return cached(body, contentTag(body), target.type, deps, hashed ? IMMUTABLE : REVALIDATE);
}
