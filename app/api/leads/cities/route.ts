import { NextResponse } from "next/server";
import { searchCities } from "@/lib/leads/cities";

export const runtime = "nodejs";

// Автокомплит города для модалки «найдём дешевле» (П7): ?q=моск → до 8 подсказок.
export async function GET(req: Request): Promise<Response> {
  const q = new URL(req.url).searchParams.get("q") ?? "";
  return NextResponse.json({ cities: searchCities(q).map((c) => ({ name: c.n, region: c.r })) });
}
