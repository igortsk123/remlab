// Нижние блоки лендинга `/try` (макет v3-en-final, TG 420): образец экрана ожидания, вопросы агентов и финальный призыв.
// Образец — картинка, а не форма: он `inert` (кнопки и поле почты не нажимаются; почты в пробе нет до T9).
// Тексты на двух языках — `landing-text.ts`.

import { landingText } from "@/components/trial/landing-text";
import { WaitCard, type WaitStep } from "@/components/trial/WaitCard";
import l from "@/components/trial/landing.module.css";
import { textOf, type TrialLang } from "@/lib/trial/i18n";

const SAMPLE: Pick<WaitStep, "key" | "state" | "at">[] = [
  { key: "a", state: "done", at: "0:04" },
  { key: "b", state: "done", at: "0:51" },
  { key: "c", state: "done", at: "1:18" },
  { key: "d", state: "run", at: "…" },
  { key: "e", state: "next" },
];

export function LandingWaiting({ lang }: { lang: TrialLang }) {
  const t = landingText(lang).waiting;
  const steps: WaitStep[] = SAMPLE.map((s, i) => ({ ...s, title: t.steps[i]![0], sub: t.steps[i]![1] || undefined }));
  return (
    <section className={l.alt} id="waiting">
      <div className={`${l.wrap} ${l.waitGrid}`}>
        <div>
          <h2>{t.h2}</h2>
          <p className={l.lead}>{t.lead}</p>
        </div>
        <div inert style={{ display: "contents" }}>
          <WaitCard text={textOf(lang).wait} timer="01:42" progress={0.68} note={t.note} steps={steps}>
            <div className={l.ready}><b>{t.ready}</b></div>
            <div className={l.links}>
              <div><a className={`${l.btn} ${l.btnPrimary}`} href="#example">{t.open}</a></div>
              <div><button className={`${l.btn} ${l.btnSecondary}`} type="button">{t.buyer}</button></div>
            </div>
            <div className={l.ph}><div><b>{t.phTitle}</b>{t.phText}</div></div>
            <div className={l.mail}>
              <b>{t.mailTitle}</b>
              <p>{t.mailText}</p>
              <div className={l.mailRow}>
                <input type="email" placeholder={t.mailPh} aria-label={t.mailLabel} />
                <button className={`${l.btn} ${l.btnSecondary}`} type="button">{t.mailBtn}</button>
              </div>
            </div>
          </WaitCard>
        </div>
      </div>
    </section>
  );
}

export function LandingFaq({ lang }: { lang: TrialLang }) {
  const t = landingText(lang).faq;
  return (
    <section id="faq">
      <div className={l.wrap}>
        <h2>{t.h2}</h2>
        <div className={l.faq}>
          {t.items.map(([q, a], i) => (
            <details className={l.card} open={i === 0} key={q}><summary>{q}</summary><p>{a}</p></details>
          ))}
        </div>
      </div>
    </section>
  );
}

export function LandingFinal({ lang }: { lang: TrialLang }) {
  const t = landingText(lang).final;
  return (
    <section className={l.final} style={{ paddingTop: 0 }}>
      <div className={l.wrap}>
        <div className={l.card}>
          <h2>{t.h2}</h2>
          <div className={l.actions}>
            <a className={`${l.btn} ${l.btnPrimary}`} href="#top">{t.upload}</a>
            <a className={`${l.btn} ${l.btnSecondary}`} href="#example">{t.example}</a>
          </div>
        </div>
      </div>
    </section>
  );
}
