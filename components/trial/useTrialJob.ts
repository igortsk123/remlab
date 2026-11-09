"use client";

// Опрос задания пробы раз в 1,5 с (`app/api/trial/[id]/route.ts`) до финального статуса. Сбой сети — повтор с паузой до 10 с
// и кнопка «Retry now»; 404 — нет такого, 410 — снят по сроку. Таймер — от `elapsedSec` сервера плюс время с ответа
// (часы телефона не участвуют: совпадает с `finished_at − created_at`).

import { useCallback, useEffect, useRef, useState } from "react";
import { trialJobView, type TrialJobView } from "@/contracts/trial";

export type JobState =
  | { kind: "loading" } | { kind: "missing" } | { kind: "expired" } | { kind: "error" }
  | { kind: "ok"; job: TrialJobView; at: number };

const POLL_MS = 1500;
const FINAL = new Set(["done", "failed", "cancelled", "expired"]);

export function useTrialJob(id: string): { state: JobState; offline: boolean; retry(): void } {
  const [state, setState] = useState<JobState>({ kind: "loading" });
  const [offline, setOffline] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fails = useRef(0);
  const alive = useRef(true);

  const poll = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    let next: number | null = POLL_MS;
    try {
      const res = await fetch(`/api/trial/${encodeURIComponent(id)}`, { cache: "no-store" });
      if (res.status === 404) { setState({ kind: "missing" }); next = null; }
      else if (res.status === 410) { setState({ kind: "expired" }); next = null; }
      else if (!res.ok) throw new Error(String(res.status));
      else {
        const body = (await res.json()) as { job?: unknown };
        const job = trialJobView.parse(body.job);
        setState({ kind: "ok", job, at: performance.now() });
        if (FINAL.has(job.status)) next = null;
      }
      fails.current = 0;
      setOffline(false);
    } catch {
      fails.current += 1;
      setOffline(true);
      setState((s) => (s.kind === "loading" && fails.current >= 3 ? { kind: "error" } : s));
      next = Math.min(10_000, POLL_MS * 2 ** fails.current);
    }
    if (alive.current && next !== null) timer.current = setTimeout(() => void poll(), next);
  }, [id]);

  useEffect(() => {
    alive.current = true;
    void poll();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [poll]);

  const retry = useCallback(() => {
    fails.current = 0;
    setState((s) => (s.kind === "error" ? { kind: "loading" } : s));
    void poll();
  }, [poll]);
  return { state, offline, retry };
}

/** Секунды с загрузки «сейчас»: тикает раз в секунду, пока задание не финальное. */
export function useElapsed(state: JobState): number {
  const [, tick] = useState(0);
  const running = state.kind === "ok" && !FINAL.has(state.job.status);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [running]);
  if (state.kind !== "ok") return 0;
  return running ? state.job.elapsedSec + (performance.now() - state.at) / 1000 : state.job.elapsedSec;
}

// Имя файла для строки «Plan received» (как в макете): сервер его не отдаёт, помним в этой вкладке. Хранилище может
// быть недоступно (приватный режим) — тогда строки просто нет.
const fileKey = (id: string) => `remlab-trial-file:${id}`;
export function rememberFileName(id: string, name: string): void {
  try { sessionStorage.setItem(fileKey(id), name.slice(0, 120)); } catch { /* нет хранилища — без имени */ }
}
export function useFileName(id: string): string | undefined {
  const [name, setName] = useState<string | undefined>(undefined);
  useEffect(() => {
    try { setName(sessionStorage.getItem(fileKey(id)) ?? undefined); } catch { /* нет хранилища */ }
  }, [id]);
  return name;
}
