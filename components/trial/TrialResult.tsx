"use client";

// Геометрия задания опубликована (план agent-trial-08: серый тур снят, итог пробы — `/try/<id>/tour/`, страница `/demo` под
// загруженный план): карточка ожидания со всеми галочками, «Открываем тур…», и через пару секунд — переход в тур на том же
// языке. Кнопка — для тех, кто не хочет ждать, и на случай, если переход не случился. Сводку (сколько комнат, подтверждён ли
// масштаб) берём из результата (`app/api/trial/[id]/result/route.ts`, та же Zod-схема, что у прода); не загрузился —
// переходу это не мешает, тур покажет своё.

import { useEffect, useState } from "react";
import { WaitCard, type WaitStep } from "@/components/trial/WaitCard";
import l from "@/components/trial/landing.module.css";
import s from "@/components/trial/trial.module.css";
import { floorplanResult, type TrialJobView } from "@/contracts/trial";
import { textOf, tourHref, type TrialLang } from "@/lib/trial/i18n";
import { clock, timer } from "@/lib/trial/steps";

/** Пауза перед переходом: видно, что все шаги готовы, и успеваешь прочесть плашку масштаба. */
export const OPEN_TOUR_DELAY_MS = 2500;

// scaleOk — масштаб не not_verified; scaleArea — он по общей площади (`area`): комнаты обставлены, размеры примерные — мягкая строка
type Summary = { rooms: number; scaleOk: boolean; scaleArea: boolean };

function useSummary(id: string, version: number): Summary | null {
  const [sum, setSum] = useState<Summary | null>(null);
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await fetch(`/api/trial/${encodeURIComponent(id)}/result`, { cache: "no-store" });
        if (!res.ok) return;
        const r = floorplanResult.parse(((await res.json()) as { result?: unknown }).result);
        if (alive) setSum({ rooms: r.panels.reduce((n, p) => n + p.rooms.length, 0), scaleOk: r.scale.status !== "not_verified",
          scaleArea: r.scale.status === "area" });
      } catch { /* сводки нет — карточка без неё */ }
    })();
    return () => { alive = false; };
  }, [id, version]);
  return sum;
}

export function TrialResult({ id, job, lang, steps }: { id: string; job: TrialJobView; lang: TrialLang; steps: WaitStep[] }) {
  const t = textOf(lang);
  // ключ правки агента едет из его ссылки `/try/<id>?k=…` в тур — без него «Обустроить» на странице нет (только просмотр)
  const k = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("k");
  const href = tourHref(id, lang, k);
  const sum = useSummary(id, job.resultVersion);
  useEffect(() => {
    const go = setTimeout(() => window.location.replace(href), OPEN_TOUR_DELAY_MS);
    return () => clearTimeout(go);
  }, [href]);

  const note = [t.done.readyIn(clock(job.elapsedSec)), sum?.rooms ? t.done.rooms(sum.rooms) : null].filter(Boolean).join(" · ");
  return (
    <WaitCard text={t.wait} title={t.done.title} heading testId="trial-done" timer={timer(job.elapsedSec)} progress={1} note={note} steps={steps}>
      {sum && !sum.scaleOk ? <p className={s.warn}><b>{t.done.scaleTitle}</b> {t.done.scaleText}</p> : null}
      {sum?.scaleArea ? <p className={s.note} data-testid="trial-scale-area">{t.done.scaleArea}</p> : null}
      <div className={l.ready} role="status"><b>{t.done.opening}</b></div>
      <a className={`${l.btn} ${l.btnPrimary}`} href={href} data-testid="trial-open-tour">{t.done.open}</a>
    </WaitCard>
  );
}
