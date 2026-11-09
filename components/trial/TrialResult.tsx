"use client";

// Готовое задание пробы: JSON результата (`app/api/trial/[id]/result/route.ts`, проверка той же Zod-схемой, что у прода)
// → серый 3D-тур. three грузится отдельным куском только здесь (dynamic, без SSR). Состояния: loading / error+retry / тур.

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import l from "@/components/trial/landing.module.css";
import s from "@/components/trial/trial.module.css";
import { floorplanResult, type FloorplanResult, type TrialJobView } from "@/contracts/trial";
import { clock } from "@/lib/trial/steps";

const GreyTour = dynamic(() => import("@/components/trial/GreyTour").then((m) => m.GreyTour), {
  ssr: false,
  loading: () => <p className={s.note}>Loading 3D…</p>,
});

type Load = { kind: "loading" } | { kind: "error" } | { kind: "ok"; result: FloorplanResult };

export function TrialResult({ id, job, steps }: { id: string; job: TrialJobView; steps: ReactNode }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const fetchResult = useCallback(async () => {
    setLoad({ kind: "loading" });
    try {
      const res = await fetch(`/api/trial/${encodeURIComponent(id)}/result`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const body = (await res.json()) as { result?: unknown };
      setLoad({ kind: "ok", result: floorplanResult.parse(body.result) });
    } catch {
      setLoad({ kind: "error" });
    }
  }, [id]);
  useEffect(() => { void fetchResult(); }, [fetchResult, job.resultVersion]);

  const rooms = load.kind === "ok" ? load.result.panels.reduce((n, p) => n + p.rooms.length, 0) : 0;
  return (
    <div data-testid="trial-done">
      <div className={s.doneHead}>
        <h1>Your 3D is ready</h1>
        <span>
          Ready in {clock(job.elapsedSec)}
          {rooms ? ` · ${rooms} rooms` : ""}
        </span>
      </div>
      {load.kind === "loading" ? <p className={s.note} role="status">Loading 3D…</p> : null}
      {load.kind === "error" ? (
        <div className={`${l.card} ${l.wait} ${s.msgCard}`} role="alert">
          <p className={s.note}>We couldn&apos;t load the 3D. Please try again.</p>
          <button className={`${l.btn} ${l.btnPrimary}`} style={{ marginTop: 12 }} type="button" onClick={() => void fetchResult()}>Try again</button>
        </div>
      ) : null}
      {load.kind === "ok" ? <GreyTour result={load.result} /> : null}
      <details className={s.history}>
        <summary>How it went</summary>
        {steps}
      </details>
    </div>
  );
}
