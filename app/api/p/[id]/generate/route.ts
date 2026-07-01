import { NextResponse } from "next/server";
import { runPreview } from "@/modules/generation-job";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await runPreview(id);
  if (!project) return NextResponse.json({ ok: false }, { status: 404 });
  return NextResponse.json({ ok: true, status: project.status });
}
