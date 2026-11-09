// Общее для тестов пробы (agent-trial-01, T-A): годный результат, тело multipart руками, запрос потоком.

import { randomBytes } from "node:crypto";

export const PNG_HEAD = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
export const png = (size: number): Buffer => Buffer.concat([PNG_HEAD, Buffer.alloc(Math.max(0, size - PNG_HEAD.length), 7)]);

export function sampleResult(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    version: 1,
    units: "cm",
    source: { mime: "image/png", pages: 1, usedPages: 1, imageW: 1200, imageH: 900 },
    scale: { status: "not_verified", ppm: null, inliers: 0, n: 0 },
    panels: [{
      id: "p0", title: "Floor plan",
      rooms: [{
        id: "r1", name: "Living room", kind: "living", contour: [[0, 0], [400, 0], [400, 300], [0, 300]],
        bbox: { x: 0, y: 0, w: 400, d: 300 }, areaM2: 12, flags: ["scale_unverified"],
      }],
      walls: [{ z0: 0, z1: 270, polys: [{ outer: [[0, 0], [400, 0], [400, 10]], holes: [] }] }],
      openings: [{ kind: "door", c: [200, 0], widthCm: 80, exterior: true }],
    }],
    flags: [],
    timings: { raster: 1.2, walls: 3.4 },
    costUsd: 0.02,
    ...over,
  };
}

type Part = { name: string; value?: string; file?: Buffer; filename?: string };

/** Тело multipart/form-data руками — чтобы управлять байтами (лимит ±1, обрыв, ложная длина). */
export function multipart(parts: Part[]): { body: Buffer; type: string } {
  const b = `----t08${randomBytes(6).toString("hex")}`;
  const chunks: Buffer[] = [];
  for (const p of parts) {
    const disp = p.file
      ? `Content-Disposition: form-data; name="${p.name}"; filename="${p.filename ?? "plan.png"}"\r\nContent-Type: application/octet-stream`
      : `Content-Disposition: form-data; name="${p.name}"`;
    chunks.push(Buffer.from(`--${b}\r\n${disp}\r\n\r\n`), p.file ?? Buffer.from(p.value ?? ""), Buffer.from("\r\n"));
  }
  chunks.push(Buffer.from(`--${b}--\r\n`));
  return { body: Buffer.concat(chunks), type: `multipart/form-data; boundary=${b}` };
}

/** Запрос с телом-потоком (chunked: без Content-Length). `breakAt` — оборвать поток после стольких байт. */
export function streamRequest(
  body: Buffer, headers: Record<string, string>, opts: { breakAt?: number; url?: string } = {},
): Request {
  let off = 0;
  const step = 64 * 1024;
  const stream = new ReadableStream<Uint8Array>({
    pull(c) {
      if (opts.breakAt !== undefined && off >= opts.breakAt) { c.error(new Error("client went away")); return; }
      if (off >= body.length) { c.close(); return; }
      const end = Math.min(body.length, off + step, opts.breakAt ?? Infinity);
      c.enqueue(new Uint8Array(body.subarray(off, end)));
      off = end;
    },
  });
  return new Request(opts.url ?? "http://app/api/trial", { method: "POST", headers, body: stream, duplex: "half" } as RequestInit);
}

export const uploadParts = (file: Buffer, extra: Part[] = []): Part[] => [
  { name: "listing", value: "2 bed flat, living room 4.0 x 3.0 m" },
  { name: "consent", value: "yes" },
  { name: "file", file },
  ...extra,
];
