// `/try/<id>/tour/…` — та же страница `/demo` для загруженного плана (план agent-trial-08). Вся логика и проверки — `lib/trial/tour.ts`;
// данные — последняя опубликованная версия задания (`latestBundle`), запасной — `demo-data.json`. Тур не открывается — человеку
// страница-заглушка на его языке (`?lang=`, иначе язык браузера) со ссылкой на страницу задания (T-20261110-07). Ссылка покупателя
// до «Подтвердить планировку» агента — заглушка «Ссылка не активирована» (`lib/trial/buyer-gate.ts`, T-20261112-40).
import { requestGate } from "@/lib/trial/buyer-gate";
import { langFromAccept, parseLang } from "@/lib/trial/i18n";
import { latestBundle } from "@/lib/trial/repo-bundle";
import { jobView } from "@/lib/trial/repo-public";
import { tourResponse } from "@/lib/trial/tour";
import { ensureJobRelease } from "@/lib/trial/tour-bundle";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request, ctx: { params: Promise<{ id: string; path?: string[] }> }): Promise<Response> {
  const { id, path } = await ctx.params;
  const q = new URL(req.url).searchParams;
  const lang = parseLang(q.get("lang")) ?? langFromAccept(req.headers.get("accept-language"));
  return tourResponse(id, path ?? [], { view: jobView, latest: latestBundle, pin: ensureJobRelease, stub: { lang, k: q.get("k") },
    gate: requestGate(req), ifNoneMatch: req.headers.get("if-none-match"), keyed: q.has("k"), acceptEncoding: req.headers.get("accept-encoding") });
}
