import { workerGuard } from "@/lib/trial/auth";
import { fail, trialJson } from "@/lib/trial/http";
import { reparseSource } from "@/lib/trial/repo-reparse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Исходник «перечитать планировку» для пробного прогона оператора (`reissue.py --reparse --dry-run`; T-20261111-02): результат, точные
// байты последней версии, правки агента, исходный текст объявления и вид листа. Самого листа здесь нет — он только воркеру под арендой.
// 404 нет тура · 410 срок вышел · 409 `not_ready` / `busy` / `no_bundle` — как у перевыпуска (`reissue/[id]`).
const STATUS = { not_found: 404, expired: 410, not_ready: 409, busy: 409, no_bundle: 409 } as const;

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const { id } = await ctx.params;
  const src = await reparseSource(id);
  if (typeof src === "string") return fail(STATUS[src], src);
  return trialJson({ ok: true, ...src });
}
