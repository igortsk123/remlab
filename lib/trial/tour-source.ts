// Чертёж агента во вкладке тура «План квартиры» (T-20261112-52; владелец TG 855, 1000, 1002): `/try/<id>/tour/source` — превью WEBP
// (вырезы листа по этажам, `tools/floorplan/source_preview.py`), `/try/<id>/tour/source/file` — исходный файл («Открыть файл»).
// Видит ТОЛЬКО агент по своей ссылке: ключ `?k=` в адресе (`buyer-gate.ts:agentOnly`); cookie-пропуск и подтверждение не открывают.
// Без ключа — 404, как будто файла нет (покупатель не узнаёт, что он был); файл снят по сроку — 410.

import { Readable } from "node:stream";
import { agentOnly, type TourGate } from "@/lib/trial/buyer-gate";
import { TRIAL_HEADERS, trialDir } from "@/lib/trial/config";
import type { SourceRow } from "@/lib/trial/repo-source";
import { openInput, openPreview } from "@/lib/trial/storage";

export type SourceKind = "source" | "sourceFile";
export type SourceDeps = { gate?: TourGate; source?: (id: string) => Promise<SourceRow | undefined>; dir?: string };

const plain = (status: number, body: string): Response => new Response(body, { status, headers: {
  ...TRIAL_HEADERS, "Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex, nofollow" } });

/** Тип из базы → заголовок; только известные (тип при загрузке определён по байтам, `storage.ts:sniffMime`). */
const MIMES = new Set(["image/jpeg", "image/png", "image/webp", "image/avif", "application/pdf"]);

export async function sourceResponse(id: string, kind: SourceKind, deps: SourceDeps): Promise<Response> {
  if (!deps.source || !(await agentOnly(deps.gate, id))) return plain(404, "not found");
  const row = await deps.source(id);
  if (!row) return plain(404, "not found");
  const dir = deps.dir ?? trialDir();
  const preview = kind === "source";
  if (preview ? !row.preview : !row.input && !row.inputGone) return plain(404, "not found");
  if (!preview && (row.inputGone || !MIMES.has(row.mime))) return plain(410, "deleted");
  const f = preview ? await openPreview(dir, row.preview) : await openInput(dir, row.input);
  if (!f) return plain(410, "deleted");
  const body = Readable.toWeb(f.handle.createReadStream()) as unknown as ReadableStream<Uint8Array>;
  return new Response(body, { headers: {
    ...TRIAL_HEADERS,
    "Content-Type": preview ? "image/webp" : row.mime,
    "Content-Length": String(f.size),
    "Content-Disposition": "inline",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
    // файл чужой: в песочнице, без доступа к адресу сайта; PDF — только `sandbox` (бриф T-52; просмотрщику браузера прочее не нужно),
    // картинке — ещё и никаких загрузок, кроме самой картинки
    "Content-Security-Policy": !preview && row.mime === "application/pdf" ? "sandbox"
      : "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
  } });
}
