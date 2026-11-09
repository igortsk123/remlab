// `/try/<id>/tour/…` — та же страница `/demo` для загруженного плана (план agent-trial-08). Вся логика и проверки — `lib/trial/tour.ts`.
import { jobView } from "@/lib/trial/repo-public";
import { tourResponse } from "@/lib/trial/tour";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string; path?: string[] }> }): Promise<Response> {
  const { id, path } = await ctx.params;
  return tourResponse(id, path ?? [], { view: jobView });
}
