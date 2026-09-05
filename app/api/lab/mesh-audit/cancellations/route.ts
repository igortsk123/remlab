import { NextResponse } from "next/server";
import { machineOk } from "@/lib/mesh-review/auth";
import { listCancellations } from "@/lib/mesh-audit/repo-decisions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// GET ?after_id=N — конвейер забирает отмены курсором (свой курсор, отдельно от решений).
export async function GET(req: Request): Promise<Response> {
  if (!(await machineOk())) return NextResponse.json({ error: "нет доступа" }, { status: 401 });
  const after = Number(new URL(req.url).searchParams.get("after_id") ?? "0");
  const cancellations = await listCancellations(Number.isFinite(after) ? after : 0);
  return NextResponse.json({ cancellations });
}
