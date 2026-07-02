// Разбор прогона по «номеру генерации» (seq): прогон + шаги + ассеты (с URL картинок). JSON.
// За admin-гардом. Используется скиллом /trace и для ручной диагностики.

import { traceStore } from "@/lib/trace/store";
import { traceAdminOk, signedAssetUrl } from "@/lib/trace/admin";

export const runtime = "nodejs";

export async function GET(req: Request, { params }: { params: Promise<{ seq: string }> }) {
  if (!traceAdminOk(req)) return new Response("forbidden", { status: 403 });
  const { seq } = await params;
  const n = Number(seq);
  if (!Number.isInteger(n)) return Response.json({ error: "bad seq" }, { status: 400 });

  const store = traceStore();
  const run = await store.getRunBySeq(n);
  if (!run) return Response.json({ error: "not found", seq: n }, { status: 404 });

  const steps = await store.getStepsByRun(run.id);
  const assets = await store.getAssetsByRun(run.id);
  const now = Date.now();
  const withUrls = assets.map((a) => ({
    id: a.id, stepId: a.stepId, role: a.role, mimeType: a.mimeType,
    sizeBytes: a.sizeBytes, url: signedAssetUrl(a.id, req, now),
  }));

  return Response.json({ run, steps, assets: withUrls });
}
