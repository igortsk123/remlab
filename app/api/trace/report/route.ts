// Пользовательская жалоба на генерацию: помечает прогон (meta.reported) и шлёт событие в аналитику.
// По номеру потом делаем разбор (скилл /trace). Данные уже в трейсе — тут только флаг + комментарий.

import { z } from "zod";
import { traceStore } from "@/lib/trace/store";
import { track } from "@/lib/analytics";

export const runtime = "nodejs";

const bodySchema = z.object({
  seq: z.number().int(),
  comment: z.string().max(1000).optional(),
});

export async function POST(req: Request) {
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return Response.json({ ok: false, error: "bad body" }, { status: 400 });
  const { seq, comment } = parsed.data;

  const run = await traceStore().getRunBySeq(seq);
  if (!run) return Response.json({ ok: false, error: "not found" }, { status: 404 });

  await traceStore().annotateRun(run.id, {
    reported: true,
    reportComment: comment ?? "",
    reportedAtIso: new Date().toISOString(),
  }).catch(() => {});
  await track("problem_reported", run.sessionId ?? "anon", { seq, runId: run.id, comment: comment ?? "" });

  return Response.json({ ok: true });
}
