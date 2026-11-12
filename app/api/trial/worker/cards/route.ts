import { CARDS_PER_POST, CARD_MAX_BYTES, trialCardsIn } from "@/contracts/trial-cards";
import { workerGuard } from "@/lib/trial/auth";
import { trialDir } from "@/lib/trial/config";
import { fail, parseBody, trialJson, validId } from "@/lib/trial/http";
import { writeCards } from "@/lib/trial/tour-cards";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Готовые снимки карточек комнат тура (T-20261112-29): Bearer воркера, задание с папкой на томе, только JPEG. Аренда не нужна —
// снимки снимаются после публикации версии (и перевыпуском), файл — по содержимому, повтор безвреден. Новой версии данных нет:
// карта уходит в страницу при следующем открытии (`lib/trial/tour.ts`).
const BODY_MAX = Math.ceil((CARD_MAX_BYTES * 4) / 3) * CARDS_PER_POST + 16 * 1024;

export async function POST(req: Request): Promise<Response> {
  const denied = workerGuard(req);
  if (denied) return denied;
  const body = await parseBody(req, trialCardsIn, BODY_MAX);
  if (body instanceof Response) return body;
  if (!validId(body.id)) return fail(404, "not_found");
  const cards = body.cards.map((c) => ({ key: c.key, jpg: Buffer.from(c.jpg, "base64") }));
  if (cards.some((c) => c.jpg.length > CARD_MAX_BYTES)) return fail(413, "too_large");
  const r = await writeCards(trialDir(), body.id, cards);
  if (!r.ok) return fail(r.error === "not_found" ? 404 : 422, r.error);
  return trialJson({ ok: true, written: r.written, index: r.index });
}
