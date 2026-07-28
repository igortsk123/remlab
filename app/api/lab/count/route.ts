import { NextResponse } from "next/server";
import { readSessionId } from "@/lib/session";
import { estimateRepo } from "@/modules/estimate/repository";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Счётчик сохранённых расчётов сессии — для бейджа «Моя лаборатория» (шапка/плитка главной).
// Отдельный динамический роут, чтобы страницы оставались статическими (SSG), а бейдж грузился с клиента.
export async function GET(): Promise<Response> {
  const sid = await readSessionId();
  const count = sid ? (await estimateRepo().listBySession(sid)).length : 0;
  return NextResponse.json({ count });
}
