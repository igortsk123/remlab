"use client";

// Страница задания пробы `/try/<id>` (план agent-trial-01, T-C): вид — блок «waiting» лендинга (`WaitCard`), шаги и таймер
// от загрузки, очередь и «машина занята», ошибка с понятным текстом; геометрия опубликована — переход в тур (`TrialResult`).
// Состояния: loading / error+retry / нет такого / снят по сроку / очередь / идёт / не удалось / готово. Все тексты — на
// языке страницы (план agent-trial-08, П).

import Link from "next/link";
import { TrialResult } from "@/components/trial/TrialResult";
import { useElapsed, useFileName, useTrialJob } from "@/components/trial/useTrialJob";
import { WaitCard, type WaitStep } from "@/components/trial/WaitCard";
import l from "@/components/trial/landing.module.css";
import s from "@/components/trial/trial.module.css";
import type { TrialJobView } from "@/contracts/trial";
import { textOf, withLang, type TrialLang, type TrialText } from "@/lib/trial/i18n";
import { clock, errorText, geometryReady, progressOf, stepsOf, timer, tourMissing, waitingNote } from "@/lib/trial/steps";

function Message({ t, lang, title, text, retry }: { t: TrialText["msg"]; lang: TrialLang; title: string; text: string; retry?: () => void }) {
  return (
    <div className={`${l.card} ${l.wait} ${s.msgCard}`} role="status">
      <h1 className={s.msgTitle}>{title}</h1>
      <p className={s.note}>{text}</p>
      <div className={l.links} style={{ marginTop: 12 }}>
        {retry ? <button className={`${l.btn} ${l.btnPrimary}`} type="button" onClick={retry}>{t.tryAgain}</button> : null}
        <Link className={`${l.btn} ${retry ? l.btnSecondary : l.btnPrimary}`} href={withLang("/try", lang)}>{t.upload}</Link>
      </div>
    </div>
  );
}

export function jobSteps(job: TrialJobView, lang: TrialLang, fileName?: string): WaitStep[] {
  return stepsOf(job, lang).map((st) => ({
    key: st.key, title: st.title, state: st.state,
    sub: st.key === "received" ? fileName : undefined,
    at: st.atSec !== null ? clock(st.atSec) : st.state === "run" ? "…" : undefined,
  }));
}

function KeepLink({ t }: { t: TrialText["wait"] }) {
  const url = typeof window === "undefined" ? "" : window.location.href;
  return (
    <div className={l.mail}>
      <b>{t.keepTitle}</b>
      <p>{t.keepText}</p>
      <div className={l.mailRow}>
        <span className={l.url}>{url.replace(/^https?:\/\//, "")}</span>
        <button className={`${l.btn} ${l.btnSecondary}`} type="button" onClick={() => void navigator.clipboard?.writeText(url)}>{t.copy}</button>
      </div>
    </div>
  );
}

function Body({ id, lang }: { id: string; lang: TrialLang }) {
  const t = textOf(lang);
  const { state, offline, retry } = useTrialJob(id);
  const elapsed = useElapsed(state);
  const fileName = useFileName(id);
  const m = { t: t.msg, lang };
  if (state.kind === "loading") return <div className={`${l.card} ${l.wait} ${s.msgCard}`} role="status"><p className={s.note}>{t.wait.loading}</p></div>;
  if (state.kind === "error") return <Message {...m} title={t.msg.errorTitle} text={t.msg.errorText} retry={retry} />;
  if (state.kind === "missing") return <Message {...m} title={t.msg.missingTitle} text={t.msg.missingText} />;
  if (state.kind === "expired") return <Message {...m} title={t.msg.expiredTitle} text={t.msg.expiredText} />;
  const { job } = state;
  if (geometryReady(job)) return <TrialResult id={id} job={job} lang={lang} steps={jobSteps(job, lang, fileName)} refresh={retry} />;
  if (tourMissing(job)) return <Message {...m} title={t.msg.failedTitle} text={t.msg.noTourText} />;
  if (job.status === "failed" || job.status === "cancelled") {
    return <Message {...m} title={t.msg.failedTitle} text={job.status === "cancelled" ? t.msg.cancelledText : errorText(job.errorCode, lang)} />;
  }
  return (
    <WaitCard text={t.wait} live timer={timer(elapsed)} progress={progressOf(job)} note={waitingNote(job, lang)} steps={jobSteps(job, lang, fileName)}>
      {offline ? (
        <p className={s.offline}>{t.wait.offline} <button className={s.linkBtn} type="button" onClick={retry}>{t.wait.retryNow}</button></p>
      ) : null}
      <KeepLink t={t.wait} />
    </WaitCard>
  );
}

export function TrialStatus({ id, lang }: { id: string; lang: TrialLang }) {
  return (
    <section className={s.page}>
      <div className={l.wrap}><Body id={id} lang={lang} /></div>
    </section>
  );
}
