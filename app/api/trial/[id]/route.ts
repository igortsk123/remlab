import { guard } from "@/lib/ratelimit/http";
import { fail, trialJson, validId } from "@/lib/trial/http";
import { jobView } from "@/lib/trial/repo-public";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Статус задания для страницы `/try/<id>` (опрос раз в 1,5 с): шаги, время, очередь, жив ли воркер. Кривой и
// неизвестный ключ неразличимы — 404; результат снят по сроку — 410.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  const v = validId(id) ? await jobView(id) : undefined;
  if (!v) return fail(404, "not_found");
  if (v === "expired") return fail(410, "expired");
  return trialJson({ ok: true, job: v });
}
