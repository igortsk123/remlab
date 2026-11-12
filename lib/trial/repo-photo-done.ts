// Готовое фото тура (T-20261112-115 Ф1): завершение заказа и чтение для страницы. Завершает сервис кадров (`draft_trial.report`) или
// воркер DEV — ручка `POST /api/trial/worker/<id>/photo` (Bearer воркера или внутренний ключ сервиса кадров). Сначала файлы в папку
// тура и проверка, что они на месте, потом строка → `done` с именами файлов; ошибка → `failed` с кодом. Повтор того же готового —
// без изменений (`repeated`). Блокировки строки тура нет: пишем только свою строку `trial_photos`.

import { sql } from "drizzle-orm";
import type { PhotoCam, PhotoSource, TourPhotoRec, TrialPhotoDoneIn } from "@/contracts/trial-photos";
import { trialDir } from "@/lib/trial/config";
import { iso, jsonOf, rows } from "@/lib/trial/sql";
import { writePhotos } from "@/lib/trial/tour-photos";

export type PhotoDone =
  | { ok: true; status: "done" | "failed"; repeated: boolean }
  | { ok: false; status: number; error: "not_found" | "expired" | "no_shots" | "not_image" | "write_failed" };

type Row = { id: string; status: string | null; alive: boolean; job_status: string };
const no = (status: number, error: Extract<PhotoDone, { ok: false }>["error"]): PhotoDone => ({ ok: false, status, error });

export async function finishPhoto(id: string, inp: TrialPhotoDoneIn, dir = trialDir()): Promise<PhotoDone> {
  const [r] = await rows<Row>(sql`select p.id, p.status, j.status as job_status,
      (j.result_expires_at is null or j.result_expires_at > now()) as alive
      from trial_photos p join trial_jobs j on j.id = p.job_id where p.job_id = ${id} and p.draft_job = ${inp.draft_job}
      order by p.created_at desc limit 1`);
  if (!r) return no(404, "not_found");
  if (r.job_status === "expired" || !r.alive) return no(410, "expired");
  if (r.status === "done") return { ok: true, status: "done", repeated: true };
  if (inp.status === "failed") {
    await rows(sql`update trial_photos set status = 'failed', fail_code = ${inp.code ?? "draft_failed"}
        where id = ${r.id} and status is distinct from 'done'`);
    return { ok: true, status: "failed", repeated: r.status === "failed" };
  }
  if (!inp.shots?.length) return no(400, "no_shots");
  const files = inp.shots.flatMap((s) => [{ buf: Buffer.from(s.img, "base64") }, ...(s.thumb ? [{ buf: Buffer.from(s.thumb, "base64"), thumb: true }] : [])]);
  const w = await writePhotos(dir, id, files);
  if (!w.ok) return no(w.error === "not_found" ? 404 : w.error === "not_image" ? 415 : 500, w.error);
  let k = 0;
  const shots = inp.shots.map((s) => {
    const file = w.names[k++]!;
    const thumb = s.thumb ? w.names[k++]! : file;
    return { camera: s.camera, file, thumb };
  });
  await rows(sql`update trial_photos set status = 'done', shots = ${JSON.stringify(shots)}::jsonb, done_at = now(), fail_code = null
      where id = ${r.id} and status is distinct from 'done'`);
  return { ok: true, status: "done", repeated: false };
}

type ListRow = { id: string; done: string; quality: string | null; room_id: string; variant_id: string | null; style: string | null;
  state_id: string | null; cams: unknown; source: PhotoSource | null; shots: unknown };

/** Готовые фото тура для страницы (старые сначала — страница берёт последний снятый кадр расстановки). Адреса — внутри тура. */
export async function tourPhotos(id: string, limit = 200): Promise<TourPhotoRec[]> {
  const list = await rows<ListRow>(sql`select id, ${iso(sql`done_at`)} as done, quality, room_id, variant_id, style, state_id, cams,
      source, shots from trial_photos where job_id = ${id} and status = 'done' order by done_at, id limit ${limit}`);
  const base = `/try/${id}/tour/photos/`;
  return list.map((p) => ({
    id: p.id, ts: Date.parse(p.done), quality: p.quality ?? "realistic", room_id: p.room_id, variant_id: p.variant_id ?? "",
    style: p.style ?? "", stateId: p.state_id ?? "", cams: p.cams ? jsonOf<PhotoCam[]>(p.cams) : null, source: p.source,
    shots: jsonOf<{ camera: string; file: string; thumb: string }[]>(p.shots ?? []).map((s) => ({
      camera: s.camera, url: base + s.file, thumb: base + s.thumb })),
  }));
}
