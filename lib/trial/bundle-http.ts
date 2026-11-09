// Отдача данных страницы задания: общая для `/api/trial/<id>/bundle` и будущего `tour/demo-data.json`. Только текущая версия из манифеста;
// заголовки как у всей пробы + noindex. ETag `"v<N>"`: опрос с If-None-Match получает 304 без чтения файла. Снято по сроку — 410.

import { TRIAL_HEADERS } from "@/lib/trial/config";
import { fail, validId } from "@/lib/trial/http";
import { bundleInfo, latestBundle } from "@/lib/trial/repo-bundle";

const NOINDEX = { "X-Robots-Tag": "noindex, nofollow" } as const;

export async function bundleResponse(req: Request, id: string): Promise<Response> {
  const info = validId(id) ? await bundleInfo(id) : undefined;
  if (!info) return fail(404, "not_found", NOINDEX);
  if (info === "expired") return fail(410, "expired", NOINDEX);
  if (info === "not_ready") return fail(404, "not_ready", NOINDEX);
  const seen = req.headers.get("if-none-match");
  if (seen === `"v${info.version}"`) return new Response(null, { status: 304, headers: { ...TRIAL_HEADERS, ...NOINDEX, ETag: seen } });
  const b = await latestBundle(id);
  if (b === "expired") return fail(410, "expired", NOINDEX);
  if (b === "not_ready") return fail(404, "not_ready", NOINDEX);
  return new Response(b.json, {
    status: 200,
    headers: { ...TRIAL_HEADERS, ...NOINDEX, "Content-Type": "application/json; charset=utf-8", ETag: `"v${b.version}"` },
  });
}
