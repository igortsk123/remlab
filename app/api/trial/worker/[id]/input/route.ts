import { leasedInputResponse } from "@/lib/trial/input-response";
import { leasedInput } from "@/lib/trial/repo-worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Исходный файл задания — ТОЛЬКО воркеру с текущей арендой (заголовки X-Trial-Attempt, X-Trial-Lease; в адрес токен не
// кладём — адреса пишет журнал Caddy). Кроме воркера файл видит только агент по своей ссылке (`lib/trial/tour-source.ts`). 409 — аренды нет; 410 — файл удалён по сроку.
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await ctx.params;
  return leasedInputResponse(req, id, leasedInput);
}
