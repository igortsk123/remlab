import { trialListingIn } from "@/contracts/trial";
import { foreignOrigin } from "@/lib/http/origin";
import { guard } from "@/lib/ratelimit/http";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { askListing } from "@/lib/trial/repo-listing";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// «Размеры своими словами» (план agent-trial-08, Р2-текст): агент со своей ссылкой (`k`) присылает размеры комнат свободным текстом — со
// страницы ожидания (уже на v1) или с плана тура. 202 — принят (или тот же `request_id`, или заменил ещё не взятый текст), 403 — нет права,
// 409 — `not_ready` / `source_gone` (исходного листа уже нет — загрузить заново) / `busy`, 429 — лимит в сутки, 400/413 — пусто или длинно.
// Текст не журналируется и не возвращается. Вторая ручка `/api/*`, которую пропускает песочница тура (`lib/trial/tour-page.ts`).
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  if (foreignOrigin(req)) return fail(403, "forbidden");
  const limited = await guard(req, "trialRead");
  if (limited) return limited;
  const { id } = await ctx.params;
  if (!validId(id)) return fail(404, "not_found");
  const body = await parseBody(req, trialListingIn, 16 * 1024);
  if (body instanceof Response) return body;
  const r = await askListing(id, body);
  if (!r.ok) return fail(r.status, r.error);
  return trialJson({ ok: true, repeated: r.repeated, replaced: r.replaced, listing: r.listing }, 202);
}
