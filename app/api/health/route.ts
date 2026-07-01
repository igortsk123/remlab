import { NextResponse } from "next/server";
import { buildHealth } from "@/lib/health";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(buildHealth());
}
