// Фото тура у тура (T-20261112-115 Ф1, `db/init/034-trial-photo-urls.sql`): что заказ страницы оставляет в строке, что сервис кадров
// присылает по готовности (`POST /api/trial/worker/<id>/photo`) и что тур читает (`GET /api/trial/<id>/photos`).

import { z } from "zod";

/** Файл фото в папке тура `photos/`: 16 знаков sha256 содержимого, миниатюра — `.t`. */
export const PHOTO_FILE_RE = /^[a-f0-9]{16}(?:\.t)?\.(?:jpg|png|webp)$/;
/** Потолок одного кадра: реалистичное 2048 px JPEG 92 — до ~1,5 МБ; миниатюра 640 px — десятки КБ. */
export const PHOTO_MAX_BYTES = 6 * 1024 * 1024;
export const PHOTO_THUMB_MAX_BYTES = 1024 * 1024;
export const PHOTO_SHOTS_MAX = 4;
export const PHOTO_SOURCES = ["auto", "agent", "buyer"] as const;
export type PhotoSource = (typeof PHOTO_SOURCES)[number];

const b64 = (maxBytes: number) => z.string().min(100).max(Math.ceil((maxBytes * 4) / 3) + 4).regex(/^[A-Za-z0-9+/]+={0,2}$/);
const unit = z.number().finite().min(0).max(1);

/** Окно превью вида (`crop`, demo-22) — как `draft_service._crop_clean`: доли кадра и id предметов целиком. */
const cropBox = z.object({ x: unit, y: unit, w: unit, h: unit, keep: z.array(z.string().max(64)).max(40).optional() });
/** Поза камеры заказа (`index.html:payload().cams`): имя, место, поворот, угол обзора, версия позы. */
export const photoCam = z.object({
  name: z.string().regex(/^C[1-4]$/),
  x: z.number().finite(),
  y: z.number().finite(),
  rot: z.number().finite().optional(),
  fov: z.number().finite().positive().max(179).optional(),
  pose: z.number().int().min(0).max(1000).optional(),
  crop: z.record(z.string().regex(/^\d\.\d{3}$/), cropBox).optional(),
});
export type PhotoCam = z.infer<typeof photoCam>;
export const photoCams = z.array(photoCam).min(1).max(PHOTO_SHOTS_MAX);

/** Готово / не вышло — от сервиса кадров (`tools/scout/draft_trial.py:report`) или воркера. `draft_job` — номер его задания. */
export const trialPhotoDoneIn = z.object({
  draft_job: z.string().regex(/^[A-Za-z0-9_-]{1,64}$/),
  status: z.enum(["done", "failed"]),
  code: z.string().regex(/^[a-z_]{1,40}$/).optional(),
  shots: z.array(z.object({
    camera: z.string().regex(/^C[1-4]$/),
    img: b64(PHOTO_MAX_BYTES),
    thumb: b64(PHOTO_THUMB_MAX_BYTES).optional(),
  })).min(1).max(PHOTO_SHOTS_MAX).optional(),
});
export type TrialPhotoDoneIn = z.infer<typeof trialPhotoDoneIn>;

/** Запись для страницы — та же форма, что запись общего реестра кадров (`index.html:srvShotsOf`), чтобы тур и /demo читали одним кодом. */
export type TourPhotoRec = {
  id: string;
  ts: number;
  quality: string;
  room_id: string;
  variant_id: string;
  style: string;
  stateId: string;
  cams: PhotoCam[] | null;
  source: PhotoSource | null;
  shots: { camera: string; url: string; thumb: string }[];
};
