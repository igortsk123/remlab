// Карточка «Getting your tour ready» — блок «waiting» лендинга (макет v3-en-final, TG 420). Одна разметка на три места:
// неподвижный образец на `/try` (`LandingWaiting`), живое ожидание на `/try/<id>` (`TrialStatus`) и «готово» перед
// переходом в тур (`TrialResult`). Тексты — по языку страницы (`lib/trial/i18n.ts`, `wait`).

import type { ReactNode } from "react";
import l from "@/components/trial/landing.module.css";
import type { TrialText } from "@/lib/trial/i18n";
import type { StepState } from "@/lib/trial/steps";

export type WaitStep = { key: string; title: string; sub?: string; state: StepState; at?: string };
type Words = TrialText["wait"];

export function WaitSteps({ steps, live, label }: { steps: WaitStep[]; live?: boolean; label: string }) {
  return (
    <ul className={`${l.wsteps} ${live ? l.spin : ""}`} aria-label={label}>
      {steps.map((st) => (
        <li key={st.key} data-state={st.state}>
          <i className={l.d} aria-hidden="true">{st.state === "done" ? "✓" : ""}</i>
          <div>{st.title}{st.sub ? <span>{st.sub}</span> : null}</div>
          {st.at ? <span className={l.s}>{st.at}</span> : null}
        </li>
      ))}
    </ul>
  );
}

type Props = {
  text: Words; timer: string; progress: number; note: string; steps: WaitStep[]; live?: boolean;
  /** Заголовок карточки вместо «Getting your tour ready» (готово) и его уровень: на странице задания это `h1`. */
  title?: string; heading?: boolean; testId?: string; children?: ReactNode;
};

export function WaitCard({ text, timer, progress, note, steps, live, title, heading, testId, children }: Props) {
  const head = title ?? text.title;
  return (
    <div className={`${l.card} ${l.wait}`} data-testid={testId ?? (live ? "trial-wait" : undefined)}>
      <div className={l.waitH}>
        {heading ? <h1 className={l.waitTitle}>{head}</h1> : <b>{head}</b>}
        <span className={l.timer} aria-label={text.timerLabel}>{timer}</span>
      </div>
      <div className={l.bar}><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>
      <small role={live ? "status" : undefined}>{note}</small>
      <WaitSteps steps={steps} live={live} label={text.progressLabel} />
      {children}
    </div>
  );
}
