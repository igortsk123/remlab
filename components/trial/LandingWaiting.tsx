// Нижние блоки лендинга `/try` (макет v3-en-final, TG 420): образец экрана ожидания, вопросы агентов и финальный призыв.
// Образец — картинка, а не форма: он `inert` (кнопки и поле почты не нажимаются; почты в пробе нет до T9).

import { WaitCard, type WaitStep } from "@/components/trial/WaitCard";
import l from "@/components/trial/landing.module.css";

const DEMO: WaitStep[] = [
  { key: "a", state: "done", title: "Plan received", sub: "floorplan-flat-215.pdf", at: "0:04" },
  { key: "b", state: "done", title: "Rooms and sizes read", sub: "7 rooms · 77.2 m²", at: "0:51" },
  { key: "c", state: "done", title: "3D ready", at: "1:18" },
  { key: "d", state: "run", title: "Furnishing living room and bedrooms", at: "…" },
  { key: "e", state: "next", title: "AI image of the living room" },
];
const FAQ = [
  ["How accurate are the sizes?", "From the plan and your measurements. Sizes we're unsure of are flagged. Not for measuring."],
  ["What furniture is shown?", "From our catalogue, priced in pounds. Styles can be switched."],
  ["Which rooms are furnished?", "Living rooms and bedrooms. Up to two floors."],
  ["What happens to my floor plan?", "We delete your plan within 24 hours and the tour after 30 days. We share neither."],
];

export function LandingWaiting() {
  return (
    <section className={l.alt} id="waiting">
      <div className={`${l.wrap} ${l.waitGrid}`}>
        <div>
          <h2>While we finish the tour</h2>
          <p className={l.lead}>The 3D opens first, furniture and the image follow.</p>
        </div>
        <div inert style={{ display: "contents" }}>
          <WaitCard timer="01:42" progress={0.68} note="Times vary by floor plan" steps={DEMO}>
            <div className={l.ready}><b>Your links are ready</b></div>
            <div className={l.links}>
              <div><a className={`${l.btn} ${l.btnPrimary}`} href="#example">Open your link</a></div>
              <div><button className={`${l.btn} ${l.btnSecondary}`} type="button">Buyer link</button></div>
            </div>
            <div className={l.ph}><div><b>AI image loading…</b>it&apos;ll appear here</div></div>
            <div className={l.mail}>
              <b>Rather not wait?</b>
              <p>We&apos;ll email you the links.</p>
              <div className={l.mailRow}>
                <input type="email" placeholder="you@agency.co.uk" aria-label="Email" />
                <button className={`${l.btn} ${l.btnSecondary}`} type="button">Email me</button>
              </div>
            </div>
          </WaitCard>
        </div>
      </div>
    </section>
  );
}

export function LandingFaq() {
  return (
    <section id="faq">
      <div className={l.wrap}>
        <h2>Questions agents ask</h2>
        <div className={l.faq}>
          {FAQ.map(([q, a], i) => (
            <details className={l.card} open={i === 0} key={q}><summary>{q}</summary><p>{a}</p></details>
          ))}
        </div>
      </div>
    </section>
  );
}

export function LandingFinal() {
  return (
    <section className={l.final} style={{ paddingTop: 0 }}>
      <div className={l.wrap}>
        <div className={l.card}>
          <h2>Try it on your next listing</h2>
          <div className={l.actions}>
            <a className={`${l.btn} ${l.btnPrimary}`} href="#top">Upload a floor plan</a>
            <a className={`${l.btn} ${l.btnSecondary}`} href="#example">See an example</a>
          </div>
        </div>
      </div>
    </section>
  );
}
