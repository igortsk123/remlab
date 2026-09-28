"use client";

// Режим «Фото»: та же конфигурация уезжает в СУЩЕСТВУЮЩИЙ конвейер кадров
// (`tools/scout/draft_service.py`, на проде Caddy отдаёт его как /api/render и /api/job).
// Ничего нового на той стороне не появляется — мы просто говорим на её языке.
//
// Платная генерация — ТОЛЬКО по кнопке (ADR-0158): сама по себе вкладка денег не тратит.

import { useCallback, useRef, useState } from "react";

import type { Apartment } from "@/contracts/apartment";
import type { ResolvedScene } from "@/lib/configurator/resolve";
import { toPhotoRequest } from "@/lib/configurator/photo";
import { t, type Lang } from "@/lib/configurator/i18n";

interface PhotoViewProps {
  apartment: Apartment;
  scene: ResolvedScene;
  roomId: string;
  lang: Lang;
}

type Status = "idle" | "running" | "done" | "error";

interface RenderShot {
  url?: string;
  camera?: string;
}

export function PhotoView({ apartment, scene, roomId, lang }: PhotoViewProps) {
  const L = t(lang);
  const [status, setStatus] = useState<Status>("idle");
  const [shots, setShots] = useState<RenderShot[]>([]);
  const [message, setMessage] = useState<string>("");
  const [seconds, setSeconds] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  const render = useCallback(async (quality: "draft" | "realistic" = "draft") => {
    const payload = toPhotoRequest(apartment, scene, roomId, { quality });
    if (!payload) return;
    setStatus("running");
    setShots([]);
    setMessage("");
    setSeconds(0);
    timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    try {
      const res = await fetch("/api/render", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...payload, async: 1 }),
      });
      if (!res.ok) throw new Error(res.status === 404 ? L.devPhoto : `HTTP ${res.status}`);
      let data = (await res.json()) as { job?: string; shots?: RenderShot[]; url?: string; error?: string };
      // фоновое задание: конвейер отдаёт номер и просит спрашивать «готово?» раз в 3 секунды
      let guard = 0;
      while (data.job && guard < 120) {
        await new Promise((r) => setTimeout(r, 3000));
        guard += 1;
        const poll = await fetch(`/api/job?id=${encodeURIComponent(data.job)}`);
        if (!poll.ok) continue;
        const next = (await poll.json()) as { status?: string; shots?: RenderShot[]; url?: string; error?: string; job?: string };
        if (next.status === "running") continue;
        data = next;
        break;
      }
      if (data.error) throw new Error(String(data.error));
      const list = data.shots?.length ? data.shots : data.url ? [{ url: data.url }] : [];
      if (!list.length) throw new Error(L.photoFailed);
      setShots(list);
      setStatus("done");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
      setStatus("error");
    } finally {
      stopTimer();
    }
  }, [apartment, scene, roomId, L, stopTimer]);

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 rounded-xl bg-secondary p-4">
      {status === "done" && shots.length > 0 ? (
        <div className="grid w-full gap-3 sm:grid-cols-2">
          {shots.map((s, i) => (
            // eslint-disable-next-line @next/next/no-img-element -- кадры приходят с конвейера по абсолютному URL
            <img key={i} src={s.url} alt={s.camera ?? ""} className="w-full rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="max-w-md text-center">
          <p className="text-sm text-secondary">{L.photoHint}</p>
          {status === "running" ? (
            <p className="mt-3 text-sm font-medium text-primary">
              {L.photoWait} · {seconds} c
            </p>
          ) : null}
          {status === "error" ? <p className="mt-3 text-sm text-error-primary">{message}</p> : null}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          onClick={() => void render("draft")}
          disabled={status === "running"}
          className="min-h-11 rounded-lg bg-brand-solid px-5 py-3 text-sm font-semibold text-white disabled:opacity-60"
        >
          {status === "running" ? L.photoWait : L.photoBtn}
        </button>
        {/* КРАСИВЫЙ КАДР — ПЛАТНЫЙ ШАГ, ТОЛЬКО ПО КНОПКЕ (ADR-0158): черновик бесплатный и
            быстрый, доводка моделью считается минутами и стоит денег */}
        <button
          type="button"
          onClick={() => void render("realistic")}
          disabled={status === "running"}
          className="min-h-11 rounded-lg px-4 py-3 text-sm font-medium text-secondary ring-1 ring-inset ring-secondary disabled:opacity-60"
        >
          {L.photoNice}
        </button>
      </div>
    </div>
  );
}
