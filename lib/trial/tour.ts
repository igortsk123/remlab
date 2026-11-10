// Тур пробы: `/try/<id>/tour` — ТА ЖЕ страница `/demo`, собранная под загруженный план (план agent-trial-08, «демо = шаблон»).
// Страница и общие файлы — ЗАКРЕПЛЁННАЯ копия витрины на задание (`tour/_releases/<версия>/`), данные — `readTourData`:
// выкладка `/demo` идёт через `rsync --delete` и иначе развела бы код и данные (Codex 09.11, п.2).
// Отдаём только файлы из списка, после проверки id и пути; исходный файл плана и любые другие файлы наружу не идут.

import path from "node:path";

import type { TrialJobView } from "@/contracts/trial";
import type { LatestBundle } from "@/lib/trial/repo-bundle";
import { TRIAL_HEADERS, trialDir } from "@/lib/trial/config";
import { validId } from "@/lib/trial/http";
import { jobRelease, readRegular, readTourData, releaseDir } from "@/lib/trial/tour-files";
import { injectTour } from "@/lib/trial/tour-page";

const SCENE_JS = /^lib\/scene\.[a-f0-9]{6,64}\.js$/;
const BASKET_JS = /^lib\/basket\.[a-f0-9]{6,64}\.js$/;
// общие картинки витрины — только имя файла в одной папке, без подкаталогов
const SHARED_IMG = /^(img|topsprites)\/([\w.-]{1,160}\.(?:jpe?g|png|webp))$/;

export type TourTarget =
  | { kind: "page" }
  | { kind: "data" }
  | { kind: "version" }
  | { kind: "release"; rel: string; type: string }
  | { kind: "shared"; url: string };

const JS = "text/javascript; charset=utf-8";
const JSON_TYPE = "application/json; charset=utf-8";

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
 *  нет — только запасной `demo-data.json`. */
export type TourDeps = {
  view: (id: string) => Promise<TrialJobView | "expired" | undefined>;
  latest?: (id: string, dir: string) => Promise<LatestBundle>;
  dir?: string;
};
const NO_LATEST = async (): Promise<LatestBundle> => "not_ready";

/** Ответ на запрос тура. id — только формат `TOKEN_RE`; нет задания или бандла — 404; результат снят по сроку — 410 (как `/try/<id>`). */
export async function tourResponse(id: string, parts: readonly string[], deps: TourDeps): Promise<Response> {
  if (!validId(id)) return text(404, "not found");
  const target = tourTarget(parts);
  if (!target) return text(404, "not found");
  const view = await deps.view(id);
  if (view === undefined) return text(404, "not found");
  if (view === "expired") return text(410, "expired");
  if (target.kind === "version") {
    // опрос страницы: `version` растёт — перезагрузка; `bundle` — версия данных (база для «Обустроить»); `rebuild` — пересборка идёт / упала
    // `askSizes`/`listing` — окошко «размеры своими словами» на плане (Р2-текст): звать ли агента и что с его текстом (самого текста нет)
    const v = { version: view.resultVersion, bundle: view.bundleVersion, rebuild: view.rebuild, rebuildError: view.rebuildError,
      askSizes: view.askSizes, listing: view.listing, listingError: view.listingError };
    return new Response(JSON.stringify(v), { headers: headers({ "Content-Type": JSON_TYPE }) });
  }
  if (target.kind === "shared") return new Response(null, { status: 302, headers: headers({ Location: target.url }) });
  const dir = deps.dir ?? trialDir();
  const release = await jobRelease(dir, id);
  if (!release) return text(404, "not ready");
  if (target.kind === "page") {
    const html = await readRegular(path.join(releaseDir(dir, release), "index.html"));
    if (!html) return text(404, "not ready");
    return new Response(injectTour(html.toString("utf8"), id, view.resultVersion), { headers: headers({ "Content-Type": "text/html; charset=utf-8" }) });
  }
  if (target.kind === "data") {
    const data = await readTourData(dir, id, deps.latest ?? NO_LATEST);
    if (!data) return text(404, "not found");
    return new Response(new Uint8Array(data.body), { headers: headers({ "Content-Type": JSON_TYPE, ETag: `"v${data.version}"` }) });
  }
  const body = await readRegular(path.join(releaseDir(dir, release), target.rel));
  if (!body) return text(404, "not found");
  return new Response(new Uint8Array(body), { headers: headers({ "Content-Type": target.type }) });
}
