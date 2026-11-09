// Приём загрузки пробы ПОТОКОМ (поправки Codex 09.11): busboy → `<id>.part` на томе, без `request.formData()` (тело
// целиком в памяти app с лимитом 1 ГБ). Лимит файла 15 МБ — по реально прочитанным байтам (ложный Content-Length и
// chunked не обходят), всё тело ≤ 16 МБ; sha256 и сигнатура — на лету. Любой отказ/обрыв → `.part` удалён.
// Успех — `.part` остаётся до `commitUpload` (`lib/trial/repo-create.ts`): там атомарный rename после записи в базу.

import { createHash } from "node:crypto";
import { createWriteStream, promises as fs, type WriteStream } from "node:fs";
import path from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ReadableStream as WebReadableStream } from "node:stream/web";
import busboy from "busboy";
import { TRIAL_BODY_MAX_BYTES, TRIAL_FILE_MAX_BYTES, TRIAL_LISTING_MAX } from "@/lib/trial/config";
import { sniffMime, type TrialMime } from "@/lib/trial/storage";

export type Staged = { partPath: string; mime: TrialMime; bytes: number; inputHash: string; listing: string | null };
export type UploadError = { status: number; error: string };
export type UploadOutcome = ({ ok: true } & Staged) | ({ ok: false } & UploadError);

const CONSENT_YES = new Set(["yes", "1", "true", "on"]);

class Reject extends Error {
  constructor(readonly status: number, readonly code: string) { super(code); }
}

/** Ограничитель всего тела: считает байты, которые реально пришли. */
function bodyLimit(max: number): Transform {
  let total = 0;
  return new Transform({
    transform(chunk: Buffer, _enc, cb) {
      total += chunk.length;
      cb(total > max ? new Reject(413, "too_large") : null, chunk);
    },
  });
}

async function closeQuietly(out: WriteStream | null): Promise<void> {
  if (!out || out.closed) return;
  await new Promise<void>((res) => { out.once("close", () => res()); out.destroy(); });
}

export async function receiveUpload(req: Request, dir: string, id: string): Promise<UploadOutcome> {
  const ct = req.headers.get("content-type") ?? "";
  if (!/^multipart\/form-data/i.test(ct)) return { ok: false, status: 415, error: "multipart_required" };
  const declared = Number(req.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > TRIAL_BODY_MAX_BYTES) return { ok: false, status: 413, error: "too_large" };
  if (!req.body) return { ok: false, status: 400, error: "no_file" };
  await fs.mkdir(dir, { recursive: true });
  const partPath = path.join(dir, `${id}.part`);
  const hash = createHash("sha256");
  const fields = new Map<string, string>();
  const st = { bytes: 0, head: Buffer.alloc(0), sawFile: false, dead: false, out: null as WriteStream | null, fileDone: null as Promise<void> | null };
  const src = Readable.fromWeb(req.body as unknown as WebReadableStream);

  const parse = new Promise<void>((resolve, reject) => {
    const bb = busboy({
      headers: { "content-type": ct },
      // busboy зовёт `limit`, когда размер ДОСТИГ лимита: +1 — чтобы ровно 15 МБ проходили; точный счёт — в `tap`
      limits: { files: 1, fileSize: TRIAL_FILE_MAX_BYTES + 1, fields: 4, fieldSize: TRIAL_LISTING_MAX * 4 + 1, parts: 6 },
    });
    bb.on("file", (name, stream) => {
      if (name !== "file" || st.sawFile || st.dead) { stream.resume(); return; }
      st.sawFile = true;
      stream.on("limit", () => reject(new Reject(413, "too_large")));
      const tap = new Transform({
        transform(chunk: Buffer, _e, cb) {
          st.bytes += chunk.length;
          if (st.bytes > TRIAL_FILE_MAX_BYTES) { cb(new Reject(413, "too_large")); return; }
          hash.update(chunk);
          if (st.head.length < 16) st.head = Buffer.concat([st.head, chunk.subarray(0, 16)]);
          cb(null, chunk);
        },
      });
      st.out = createWriteStream(partPath, { flags: "wx" });
      st.fileDone = pipeline(stream, tap, st.out);
      st.fileDone.catch(reject);
    });
    bb.on("field", (name, value, info) => {
      if (info.valueTruncated) reject(new Reject(400, "listing_too_long"));
      else fields.set(name, value);
    });
    bb.on("filesLimit", () => reject(new Reject(400, "one_file_only")));
    bb.on("error", reject);
    bb.on("close", () => { (st.fileDone ?? Promise.resolve()).then(resolve, reject); });
    pipeline(src, bodyLimit(TRIAL_BODY_MAX_BYTES), bb).catch(reject);
  });

  try {
    await parse;
    const mime = sniffMime(st.head);
    const listing = (fields.get("listing") ?? "").trim();
    if (!st.sawFile || st.bytes === 0) throw new Reject(400, "no_file");
    if (!mime) throw new Reject(415, "unsupported_type");
    if (listing.length > TRIAL_LISTING_MAX) throw new Reject(400, "listing_too_long");
    if (!CONSENT_YES.has((fields.get("consent") ?? "").toLowerCase())) throw new Reject(400, "consent_required");
    const fileSha = hash.digest("hex");
    const inputHash = createHash("sha256").update(`${fileSha}\n${listing}`).digest("hex");
    return { ok: true, partPath, mime, bytes: st.bytes, inputHash, listing: listing || null };
  } catch (e) {
    st.dead = true;
    src.destroy(); // остаток тела не дочитываем (15 МБ+ мимо памяти и диска)
    await closeQuietly(st.out);
    await fs.rm(partPath, { force: true }).catch(() => undefined);
    if (e instanceof Reject) return { ok: false, status: e.status, error: e.code };
    return { ok: false, status: 400, error: "upload_aborted" }; // обрыв связи, битая разметка multipart
  }
}
