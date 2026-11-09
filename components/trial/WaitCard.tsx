// Карточка «Getting your tour ready» — блок «waiting» лендинга (макет v3-en-final, TG 420). Одна разметка на два места:
// неподвижный образец на `/try` (`LandingWaiting`) и живое ожидание на `/try/<id>` (`TrialStatus`).

import type { ReactNode } from "react";
import l from "@/components/trial/landing.module.css";
import type { StepState } from "@/lib/trial/steps";

export type WaitStep = { key: string; title: string; sub?: string; state: StepState; at?: string };

export function WaitSteps({ steps, live }: { steps: WaitStep[]; live?: boolean }) {
  return (
    <ul className={`${l.wsteps} ${live ? l.spin : ""}`} aria-label="Progress">
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

type Props = { timer: string; progress: number; note: string; steps: WaitStep[]; live?: boolean; children?: ReactNode };

export function WaitCard({ timer, progress, note, steps, live, children }: Props) {
  return (
    <div className={`${l.card} ${l.wait}`} data-testid={live ? "trial-wait" : undefined}>
      <div className={l.waitH}>
        <b>Getting your tour ready</b>
        <span className={l.timer} aria-label="Time since upload">{timer}</span>
      </div>
      <div className={l.bar}><i style={{ width: `${Math.round(progress * 100)}%` }} /></div>
      <small role={live ? "status" : undefined}>{note}</small>
      <WaitSteps steps={steps} live={live} />
      {children}
    </div>
  );
}
