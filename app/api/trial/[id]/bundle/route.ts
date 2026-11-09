import { guard } from "@/lib/ratelimit/http";
import { bundleResponse } from "@/lib/trial/bundle-http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Текущая опубликованная версия данных страницы задания (`demo-data.json`, план agent-trial-08): работает и пока задание идёт.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  return bundleResponse(req, id);
}
