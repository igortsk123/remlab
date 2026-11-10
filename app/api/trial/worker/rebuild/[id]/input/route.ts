import { leasedInputResponse } from "@/lib/trial/input-response";
import { leasedRebuildInput } from "@/lib/trial/repo-rebuild-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Исходный лист задания — пересборке по тексту агента (Р2-текст; `id` — id пересборки) ТОЛЬКО с её текущей арендой.
// 410 — файл удалён по сроку: воркер закрывает пересборку кодом `source_gone` («загрузите план заново»).
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  return leasedInputResponse(req, id, leasedRebuildInput);
}
