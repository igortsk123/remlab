import { guard } from "@/lib/ratelimit/http";
import { apiOpen } from "@/lib/trial/buyer-gate";
import { fail, trialJson, validId } from "@/lib/trial/http";
import { bundleInfo } from "@/lib/trial/repo-bundle";
import { tourPhotos } from "@/lib/trial/repo-photo-done";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Готовые фото тура (T-20261112-115 Ф1): страница тура (`index.html:loadShots`) после перезагрузки берёт снятое отсюда. Ворота — как у
// данных тура (`buyer-gate.ts:apiOpen`): до «Подтвердить планировку» — только ключ агента `?k=` (или воркер), после — всем по ссылке.
// Только `done`: адреса файлов внутри тура (`/try/<id>/tour/photos/…`, те же ворота), комната, вариант, номер состояния, позы, кто снял.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  const info = validId(id) ? await bundleInfo(id) : undefined;
  if (!info) return fail(404, "not_found");
  if (info === "expired") return fail(410, "expired");
  if (!(await apiOpen(req, id))) return fail(403, "not_active");
  return trialJson({ ok: true, shots: info === "not_ready" ? [] : await tourPhotos(id) });
}
