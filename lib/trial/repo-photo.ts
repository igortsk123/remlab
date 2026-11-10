// Фото нейросети из тура пробы (план agent-trial-08 § «Правило фото»; T-20261109-34; `db/init/026-trial-photos.sql`). Право — у ссылки
// (агент и покупатель одинаково); решает сервер: комната с доверием к размерам (`photo_ok` в ПОСЛЕДНЕЙ версии данных задания, не слова
// страницы), её размеры совпадают с данными, два кадра из 3D браузера, суточный предел на задание. Счёт и заказ — под блокировкой строки
// задания (`for update`): два нажатия разом не проскочат предел. Заказ уходит в сервис кадров с сервера (`trial` — метка расхода и второй
// предел там же); ссылки магазина от страницы не передаём — фото товаров сервис кадров берёт сам.

import { sql, type SQL } from "drizzle-orm";
import type { TrialPhotoIn } from "@/contracts/trial";
import { db } from "@/lib/db";
import { randomToken } from "@/lib/token";
import { trialDir, trialDraftUrl, trialPhotoDaily } from "@/lib/trial/config";
import { latestBundle } from "@/lib/trial/repo-bundle";

export type PhotoAsk = { ok: true; job: string } | { ok: false; status: number; error: string; message?: string };
/** Ответ сервиса кадров: статус и тело JSON (или null — не JSON / нет связи). */
export type DraftReply = { status: number; body: Record<string, unknown> | null };
export type DraftSend = (payload: Record<string, unknown>, ip: string) => Promise<DraftReply>;

type Tx = Parameters<Parameters<ReturnType<typeof db>["transaction"]>[0]>[0];
const q = async <T>(tx: Tx, query: SQL): Promise<T[]> => (await tx.execute(query)) as unknown as T[];
const no = (status: number, error: string, message?: string): PhotoAsk => ({ ok: false, status, error, ...(message ? { message } : {}) });

type Geo = { w?: unknown; d?: unknown };
type Bundle = { apartment_rooms?: { id?: unknown; photo_ok?: unknown }[]; rooms_geo?: Record<string, Geo> };

/** Можно ли фото этой комнаты по данным задания: `photo_ok` и размеры страницы = размерам данных (±1 см). Иначе — код отказа. */
export function photoRoomProblem(json: string, roomId: string, room: { w: number; d: number }): string | null {
  let b: Bundle;
  try { b = JSON.parse(json) as Bundle; } catch { return "not_ready"; }
  const entry = (b.apartment_rooms ?? []).find((r) => r.id === roomId);
  if (!entry || entry.photo_ok !== true) return "photo_not_allowed";
  const geo = b.rooms_geo?.[roomId];
  const near = (a: unknown, x: number) => typeof a === "number" && Math.abs(a - x) <= 1;
  return geo && near(geo.w, room.w) && near(geo.d, room.d) ? null : "stale";
}

// поля магазина у предметов (сервис кадров для тура берёт фото товара сам, по модели) и служебные поля заказа, которые ставит только сервер
const SHOP = ["img", "img_hd", "url", "url_direct", "shop", "price", "brand"];
const SERVICE = ["async", "quality", "dry_run", "no_proxy", "_job", "trial", "no_registry", "cost_label"];

/** Заказ страницы → тело для сервиса кадров: реалистичное, в фон, с меткой задания, без записи в общий реестр кадров демо. */
export function draftPayload(id: string, inp: TrialPhotoIn): Record<string, unknown> {
  const out: Record<string, unknown> = { ...inp };
  for (const k of SERVICE) delete out[k];
  out.items = inp.items.map((it) => {
    const o: Record<string, unknown> = { ...it };
    for (const k of SHOP) delete o[k];
    return o;
  });
  return { ...out, quality: "realistic", async: 1, trial: id, no_registry: 1 };
}

/** Заказ в сервис кадров (`/render` — тот же вход, что у `/api/render`); адрес человека — для его IP-предела там. */
export const sendToDraft: DraftSend = async (payload, ip) => {
  try {
    const r = await fetch(`${trialDraftUrl()}/render`, {
      method: "POST", headers: { "content-type": "application/json", ...(ip ? { "x-forwarded-for": ip } : {}) },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(20_000),
    });
    const body = (await r.json().catch(() => null)) as Record<string, unknown> | null;
    return { status: r.status, body };
  } catch {
    return { status: 503, body: null };
  }
};

export async function askPhoto(id: string, inp: TrialPhotoIn, ip: string, send: DraftSend = sendToDraft, dir = trialDir(),
  env = process.env): Promise<PhotoAsk> {
  const latest = await latestBundle(id, dir);
  if (latest === "expired") return no(410, "expired");
  if (latest === "not_ready") return no(409, "not_ready");
  const problem = photoRoomProblem(latest.json, inp.room_id, inp.room);
  if (problem) return no(problem === "stale" ? 409 : 403, problem);
  return db().transaction(async (tx) => {
    const [job] = await q<{ status: string; past_term: boolean }>(tx, sql`select status,
        coalesce(result_expires_at < now(), false) as past_term from trial_jobs where id = ${id} for update`);
    if (!job) return no(404, "not_found");
    if (job.status === "expired" || job.past_term) return no(410, "expired");
    const [day] = await q<{ n: number }>(tx, sql`select count(*)::int as n from trial_photos
        where job_id = ${id} and created_at > now() - interval '24 hours'`);
    if ((day?.n ?? 0) >= trialPhotoDaily(env)) return no(429, "photo_limit");
    const r = await send(draftPayload(id, inp), ip);
    const jobId = r.body?.job;
    if (r.status === 200 && typeof jobId === "string" && jobId.length > 0 && jobId.length <= 64) {
      await tx.execute(sql`insert into trial_photos (id, job_id, room_id, draft_job) values (${randomToken()}, ${id}, ${inp.room_id}, ${jobId})`);
      return { ok: true, job: jobId };
    }
    // отказ сервиса — его код и текст как есть (нет денег, лимит адреса, свой суточный предел), без строки счёта
    const code = typeof r.body?.code === "string" ? r.body.code : "draft_failed";
    const msg = typeof r.body?.error === "string" ? r.body.error.slice(0, 300) : undefined;
    return no(r.status >= 400 && r.status < 600 ? r.status : 502, code, msg);
  });
}
