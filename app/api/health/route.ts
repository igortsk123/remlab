import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({
    ok: true,
    service: "remlab",
    version: process.env.APP_VERSION ?? "dev",
    ts: new Date().toISOString(),
  });
}
