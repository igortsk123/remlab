import { NextResponse } from "next/server";
import { z } from "zod";
import { machineOk, reviewerOk } from "@/lib/mesh-review/auth";
import { listPage, toView, upsertItems, applyAcks } from "@/lib/mesh-audit/repo-items";
import { batchState } from "@/lib/mesh-audit/repo-batches";
import { clampPage, pageCount } from "@/lib/mesh-audit/rules";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// GET ?page=N — страница карточек (кука владельца или Bearer конвейера).
export async function GET(req: Request): Promise<Response> {
  if (!(await reviewerOk()) && !(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const raw = new URL(req.url).searchParams.get("page") ?? undefined;
  const first = await listPage(1);
  const pages = pageCount(first.total);
  const page = clampPage(raw, pages);
  const data = page === 1 ? first : await listPage(page);
  return NextResponse.json({ page, pages, total: data.total, seen: data.seen, items: data.items.map(toView), batch: await batchState() });
}

const ItemIn = z.object({
  sku: z.string().min(1),
  generationKey: z.string().min(1),
  revisionKey: z.string().optional(),
  role: z.string().optional(),
  name: z.string().optional(),
  imageUrl: z.string().optional(),
  posterUrl: z.string().optional(),
  modelPath: z.string().min(1),
  seed: z.number().int().optional(),
  attempt: z.number().int().optional(),
  generatedAt: z.string().optional(),
  photoStale: z.boolean().optional(),
});
const AckIn = z.object({ sku: z.string().min(1), reworkStatus: z.string().min(1), error: z.string().optional() });
const Body = z.object({ items: z.array(ItemIn).max(500).optional(), acks: z.array(AckIn).max(500).optional() });

// POST — DEV пушит текущие поколения (upsert по sku, порядок = порядок карточек) и ACK переделок.
export async function POST(req: Request): Promise<Response> {
  if (!(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "неверный запрос" }, { status: 400 });
  const put = parsed.data.items ? await upsertItems(parsed.data.items) : 0;
  const acked = parsed.data.acks ? await applyAcks(parsed.data.acks) : 0;
  return NextResponse.json({ ok: true, put, acked });
}
