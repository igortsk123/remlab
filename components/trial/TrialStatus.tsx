"use client";

// Страница задания пробы `/try/<id>` (план agent-trial-01, T-C): вид — блок «waiting» лендинга (`WaitCard`), шаги и таймер
// от загрузки, очередь и «машина занята», ошибка с понятным текстом, по готовности — серый 3D-тур (`TrialResult`).
// Состояния: loading / error+retry / нет такого / снят по сроку / очередь / идёт / не удалось / готово.

import Link from "next/link";
import { TrialResult } from "@/components/trial/TrialResult";
import { useElapsed, useFileName, useTrialJob } from "@/components/trial/useTrialJob";
import { WaitCard, WaitSteps, type WaitStep } from "@/components/trial/WaitCard";
import l from "@/components/trial/landing.module.css";
import s from "@/components/trial/trial.module.css";
import type { TrialJobView } from "@/contracts/trial";
import { clock, errorText, progressOf, stepsOf, timer, waitingNote } from "@/lib/trial/steps";

function Message({ title, text, retry }: { title: string; text: string; retry?: () => void }) {
  return (
    <div className={`${l.card} ${l.wait} ${s.msgCard}`} role="status">
      <h1 className={s.msgTitle}>{title}</h1>
      <p className={s.note}>{text}</p>
      <div className={l.links} style={{ marginTop: 12 }}>
        {retry ? <button className={`${l.btn} ${l.btnPrimary}`} type="button" onClick={retry}>Try again</button> : null}
        <Link className={`${l.btn} ${retry ? l.btnSecondary : l.btnPrimary}`} href="/try">Upload a floor plan</Link>
      </div>
    </div>
  );
}

export function jobSteps(job: TrialJobView, fileName?: string): WaitStep[] {
  return stepsOf(job).map((st) => ({
    key: st.key, title: st.title, state: st.state,
    sub: st.key === "received" ? fileName : undefined,
    at: st.atSec !== null ? clock(st.atSec) : st.state === "run" ? "…" : undefined,
  }));
}

function KeepLink() {
  const url = typeof window === "undefined" ? "" : window.location.href;
  return (
    <div className={l.mail}>
      <b>No need to wait here</b>
      <p>Keep this link. The tour will be on it when it&apos;s ready.</p>
      <div className={l.mailRow}>
        <span className={l.url}>{url.replace(/^https?:\/\//, "")}</span>
        <button className={`${l.btn} ${l.btnSecondary}`} type="button" onClick={() => void navigator.clipboard?.writeText(url)}>Copy link</button>
      </div>
    </div>
  );
}

function Body({ id }: { id: string }) {
  const { state, offline, retry } = useTrialJob(id);
  const elapsed = useElapsed(state);
  const fileName = useFileName(id);
  if (state.kind === "loading") return <div className={`${l.card} ${l.wait} ${s.msgCard}`} role="status"><p className={s.note}>Loading…</p></div>;
  if (state.kind === "error") return <Message title="We can't reach the server" text="Please check your connection." retry={retry} />;
  if (state.kind === "missing") return <Message title="We can't find this tour" text="Please check the link, or upload the plan again." />;
  if (state.kind === "expired") {
    return <Message title="This tour has expired" text="We keep tours for 30 days. Upload the plan again to make a new one." />;
  }
  const { job } = state;
  if (job.status === "done") return <TrialResult id={id} job={job} steps={<WaitSteps steps={jobSteps(job, fileName)} />} />;
  if (job.status === "failed" || job.status === "cancelled") {
    return (
      <Message title="We couldn't build this tour"
        text={job.status === "cancelled" ? "This upload was cancelled. Please upload the plan again." : errorText(job.errorCode)} />
    );
  }
  return (
    <WaitCard live timer={timer(elapsed)} progress={progressOf(job)} note={waitingNote(job)} steps={jobSteps(job, fileName)}>
      {offline ? (
        <p className={s.offline}>Connection lost. Trying again… <button className={s.linkBtn} type="button" onClick={retry}>Retry now</button></p>
      ) : null}
      <KeepLink />
    </WaitCard>
  );
}

export function TrialStatus({ id }: { id: string }) {
  return (
    <section className={s.page}>
      <div className={l.wrap}><Body id={id} /></div>
    </section>
  );
}
