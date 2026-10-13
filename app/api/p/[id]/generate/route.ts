import { NextResponse } from "next/server";
import { runGenerate } from "@/modules/generation-job";
import { track, captureError } from "@/lib/analytics";
import { guard } from "@/lib/ratelimit/http";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const limited = await guard(req, "generate"); // платно: Gemini (план b2b-01)
  if (limited) return limited;
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
