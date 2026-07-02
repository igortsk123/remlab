// Ассеты трейса (картинки вход/промежуточные/выход) — байты на диске под TRACE_DIR,
// в БД только ссылка+метаданные (base64 в БД НЕ пишем). Прод: TRACE_DIR=/app/data/traces
// (том → /opt/remlab/data/traces). Dev: ./.data/traces.

import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { traceStore } from "@/lib/trace/store";
import type { RunContext } from "@/lib/trace/context";
import type { AssetRole, AssetRef, AssetRow } from "@/lib/trace/types";

export const TRACE_DIR = process.env.TRACE_DIR || path.join(process.cwd(), ".data", "traces");

const EXT_BY_MIME: Record<string, string> = {
  "image/webp": "webp", "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
};
function extFor(mime: string): string {
  return EXT_BY_MIME[mime] ?? "bin";
}

export function assetFullPath(storageKey: string): string {
  return path.join(TRACE_DIR, storageKey);
}

// Сохранить картинку как ассет прогона. Best-effort: ошибку диска/БД глушим (не валим пайплайн).
export async function saveAsset(
  ctx: RunContext,
  opts: { role: AssetRole; mimeType: string; bytes: Buffer; stepId?: string },
): Promise<AssetRef | null> {
  const id = randomUUID();
  const storageKey = path.posix.join(ctx.runId, `${id}.${extFor(opts.mimeType)}`);
  try {
    const full = assetFullPath(storageKey);
    await fs.mkdir(path.dirname(full), { recursive: true });
    await fs.writeFile(full, opts.bytes);
    const row: AssetRow = {
      id, runId: ctx.runId, stepId: opts.stepId ?? null, role: opts.role,
      mimeType: opts.mimeType, storageKey, sizeBytes: opts.bytes.length, createdAt: new Date(),
    };
    await traceStore().insertAsset(row);
    return { id, url: `/api/trace/asset/${id}`, storageKey, mimeType: opts.mimeType, sizeBytes: opts.bytes.length };
  } catch (err) {
    // Best-effort: НЕ валим пайплайн, но и НЕ прячем сбой (иначе баг вроде «том закрыт на запись» тихо
    // копит 0 ассетов). Логируем без секретов — только роль/шаг/причина.
    console.warn(`[trace] saveAsset failed (role=${opts.role}, step=${opts.stepId ?? "-"}):`, err instanceof Error ? err.message : err);
    return null;
  }
}
