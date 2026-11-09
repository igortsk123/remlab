import { guard } from "@/lib/ratelimit/http";
import { TRIAL_HEADERS } from "@/lib/trial/config";
import { fail, trialJson, validId } from "@/lib/trial/http";
import { jobResult } from "@/lib/trial/repo-public";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// JSON результата (`contracts/trial.ts:floorplanResult`) для серого тура. ETag = result_version: страница шлёт
// If-None-Match и получает 304 без тела. Кэшам — no-store (ключ ссылки). Не готов — 404 not_ready; снят — 410.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  const r = validId(id) ? await jobResult(id) : undefined;
  if (!r) return fail(404, "not_found");
  if (r === "expired") return fail(410, "expired");
  if (r === "not_ready") return fail(404, "not_ready");
  const etag = `"v${r.version}"`;
  if (req.headers.get("if-none-match") === etag) {
    return new Response(null, { status: 304, headers: { ...TRIAL_HEADERS, ETag: etag } });
  }
  return trialJson({ ok: true, version: r.version, result: r.result }, 200, { ETag: etag });
}
