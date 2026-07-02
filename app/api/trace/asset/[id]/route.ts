// Отдача картинки-ассета трейса по id (байты с диска). За admin-гардом (фото пользователей).

import { promises as fs } from "node:fs";
import { traceStore } from "@/lib/trace/store";
import { assetFullPath } from "@/lib/trace/assets";
import { traceAdminOk } from "@/lib/trace/admin";
import { verifyAssetSig } from "@/lib/trace/sign";

export const runtime = "nodejs";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Доступ: либо валидная подписанная ссылка (браузер владельца, без раскрытия токена), либо admin-гард.
  const url = new URL(req.url);
  const signed = verifyAssetSig(id, url.searchParams.get("exp"), url.searchParams.get("sig"), Date.now());
  if (!signed && !traceAdminOk(req)) return new Response("forbidden", { status: 403 });
  const asset = await traceStore().getAssetById(id);
  if (!asset) return new Response("not found", { status: 404 });
  try {
    const buf = await fs.readFile(assetFullPath(asset.storageKey));
    return new Response(new Uint8Array(buf), {
      headers: { "content-type": asset.mimeType, "cache-control": "private, max-age=3600" },
    });
  } catch {
    return new Response("gone", { status: 410 });
  }
}
