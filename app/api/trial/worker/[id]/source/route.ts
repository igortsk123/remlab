import { SOURCE_PREVIEW_MAX, trialSourceIn } from "@/contracts/trial-source";
import { workerGuard } from "@/lib/trial/auth";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { savePreview } from "@/lib/trial/repo-source";
import { sniffMime } from "@/lib/trial/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Превью чертежа агента (T-20261112-52): Bearer воркера, только WEBP по первым байтам, задание с живым туром. Аренда не нужна, как у
// снимков карточек (`../../cards/route.ts`): воркер шлёт превью и после пересборки «перечитать планировку», когда аренда уже снята.
// Повтор безвреден — тот же файл `<id>.src.webp`. Отдаётся только агенту по ключу его ссылки (`lib/trial/tour-source.ts`).
const BODY_MAX = Math.ceil((SOURCE_PREVIEW_MAX * 4) / 3) + 16 * 1024;

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const body = await parseBody(req, trialSourceIn, BODY_MAX);
  if (body instanceof Response) return body;
  if (!validId(id) || body.id !== id) return fail(404, "not_found");
  const webp = Buffer.from(body.webp, "base64");
  if (webp.length > SOURCE_PREVIEW_MAX) return fail(413, "too_large");
  if (sniffMime(webp.subarray(0, 16)) !== "image/webp") return fail(415, "not_webp");
  const r = await savePreview(id, webp);
  if (!r.ok) return fail(r.error === "not_found" ? 404 : 410, r.error);
  return trialJson({ ok: true });
}
