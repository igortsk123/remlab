import { NextResponse } from "next/server";
import { runGenerate } from "@/modules/generation-job";
import { track, captureError } from "@/lib/analytics";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    const project = await runGenerate(id);
    if (!project) return NextResponse.json({ ok: false }, { status: 404 });
    await track("preview_ready", project.sessionId, { projectId: id });
    return NextResponse.json({ ok: true, status: project.status });
  } catch (e) {
    await captureError(e, { where: "generate", projectId: id });
    return NextResponse.json({ ok: false }, { status: 500 });
  }
}
