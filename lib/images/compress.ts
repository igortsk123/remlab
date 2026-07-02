// Сжатие/уменьшение картинок через сервис imagor (Go+libvips) ПЕРЕД отправкой в LLM.
// Меньше пикселей → меньше токенов (LLM считает картинку по «плиткам» пикселей, не по байтам);
// webp q80 → меньше байт для хранения ассетов трейса. imagor internal-only на remlab-net
// (как в SUP2, ADR D18). Не настроен (IMAGOR_BASE_URL пуст) или ошибка → возвращаем исходник
// (best-effort: сжатие никогда не валит пайплайн).

import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { TRACE_DIR } from "@/lib/trace/assets";
import type { ImageData } from "@/lib/providers/types";

const IMAGOR_BASE_URL = process.env.IMAGOR_BASE_URL || ""; // напр. http://remlab-imagor:8000
const EXT_BY_MIME: Record<string, string> = {
  "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp",
};

export type CompressOpts = { maxDim?: number; quality?: number };

export async function compressForLLM(img: ImageData, opts: CompressOpts = {}): Promise<ImageData> {
  if (!IMAGOR_BASE_URL) return img;
  const maxDim = opts.maxDim ?? 1536; // длинная сторона; fit-in только уменьшает
  const quality = opts.quality ?? 80;
  const ext = EXT_BY_MIME[img.mimeType];
  if (!ext) return img; // неизвестный формат — не рискуем, шлём как есть

  // imagor читает файл из FILE_LOADER_BASE_DIR (= том TRACE_DIR) по относительному ключу.
  const key = path.posix.join("_tmp", `${randomUUID()}.${ext}`);
  const full = path.join(TRACE_DIR, key);
  try {
    await fs.mkdir(path.dirname(full), { recursive: true });
    await fs.writeFile(full, Buffer.from(img.base64, "base64"));
    const url =
      `${IMAGOR_BASE_URL}/unsafe/fit-in/${maxDim}x${maxDim}` +
      `/filters:format(webp):quality(${quality}):strip_exif()/${key}`;
    const res = await fetch(url);
    if (!res.ok) return img;
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length === 0) return img;
    return { mimeType: "image/webp", base64: buf.toString("base64") };
  } catch {
    return img;
  } finally {
    fs.unlink(full).catch(() => {}); // временный оригинал не храним
  }
}
