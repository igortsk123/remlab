import { autoTaskIn } from "@/contracts/trial-auto-photos";
import { workerGuard } from "@/lib/trial/auth";
import { markAutoTask } from "@/lib/trial/auto-photos-lease";
import { fail, parseBody, trialJson } from "@/lib/trial/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Отметка задачи автофото (T-20261112-115 Ф2) под арендой партии; продлевает аренду. 409 `lease_lost` — партию забрали или закрыли
// (исполнитель бросает её, ничего не заказывает); 409 `bad_transition` — задача уже заказана/закрыта; 404 — нет такой задачи в партии.
export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, autoTaskIn);
  if (body instanceof Response) return body;
  const r = await markAutoTask(body);
  if (!r.ok) return fail(r.error === "not_found" ? 404 : 409, r.error);
  return trialJson({ ok: true, status: r.status, leaseUntil: r.leaseUntil });
}
