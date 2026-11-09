// Первый экран лендинга `/try` (макет v3-en-final, TG 420): заголовок, рабочая форма загрузки, три цифры, бета-строка
// и лента «одна квартира: план → 3D → мебель → AI-картинка». Картинки — `public/try/`; тексты на двух языках — `landing-text.ts`.

import { landingText } from "@/components/trial/landing-text";
import { UploadForm } from "@/components/trial/UploadForm";
import l from "@/components/trial/landing.module.css";
import type { TrialLang } from "@/lib/trial/i18n";

const STRIP = [
  { area: l.sP, frame: l.framePlan, src: "/try/plan.jpg" },
  { area: l.sG, frame: l.frameGrey, src: "/try/grey3d.jpg" },
  { area: l.sF, src: "/try/furnished.jpg" },
  { area: l.sAi, src: "/try/ai.jpg", ai: true },
];

export function LandingHero({ lang }: { lang: TrialLang }) {
  const t = landingText(lang).hero;
  return (
    <section className={l.hero} id="top">
      <div className={`${l.wrap} ${l.heroGrid}`}>
        <div className={l.heroCopy}>
          <span className={l.eyebrow}>{t.eyebrow}</span>
          <h1>{t.h1}</h1>
          <p className={l.lead}>{t.lead}</p>
          <UploadForm lang={lang} />
        </div>

        <div className={l.heroMeta}>
          <div className={l.stats}>
            {t.stats.map(([b, s]) => <div className={l.stat} key={b}><b>{b}</b><span>{s}</span></div>)}
          </div>
          <p className={l.beta}><i>BETA</i><span>{t.beta}</span></p>
        </div>

        <div className={l.heroStrip}>
          <div className={l.strip} aria-label={t.stripLabel}>
            {STRIP.map((x, i) => {
              const c = t.strip[i]!;
              return (
                <div className={x.area} key={x.src}>
                  <div className={`${l.frame} ${x.frame ?? ""}`}>
                    {/* eslint-disable-next-line @next/next/no-img-element -- статичные кадры макета, размеры задаёт рамка */}
                    <img src={x.src} alt={c.alt} />
                    {c.tag ? <span className={l.tag}>{c.tag}</span> : null}
                    {x.ai ? <span className={l.aiBadge}>{t.aiBadge}</span> : null}
                  </div>
                  <div className={l.stripCap}>{c.cap}{c.t ? <> <span className={l.t}>{c.t}</span></> : null}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
