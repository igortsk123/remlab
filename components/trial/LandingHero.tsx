// Первый экран лендинга `/try` (макет v3-en-final, TG 420): заголовок, рабочая форма загрузки, три цифры, бета-строка
// и лента «одна квартира: план → 3D → мебель → AI-картинка». Картинки — `public/try/`.

import { UploadForm } from "@/components/trial/UploadForm";
import l from "@/components/trial/landing.module.css";

const STRIP = [
  { area: l.sP, frame: l.framePlan, src: "/try/plan.jpg", alt: "Floor plan of a 2-bed flat", cap: "Floor plan" },
  { area: l.sG, frame: l.frameGrey, src: "/try/grey3d.jpg", alt: "The same flat as a grey 3D model", cap: "3D", t: "first" },
  { area: l.sF, src: "/try/furnished.jpg", alt: "Its living room, furnished in 3D", cap: "Furniture", t: "added next", tag: "Walk round" },
  { area: l.sAi, src: "/try/ai.jpg", alt: "AI image of the same living room", cap: "AI image", t: "added later", ai: true },
];

export function LandingHero() {
  return (
    <section className={l.hero} id="top">
      <div className={`${l.wrap} ${l.heroGrid}`}>
        <div className={l.heroCopy}>
          <span className={l.eyebrow}>For estate agents and developers · Beta</span>
          <h1>Turn a floor plan into a furnished 3D tour in minutes</h1>
          <p className={l.lead}>Upload a PDF or photo and get a tour link for buyers.</p>
          <UploadForm />
        </div>

        <div className={l.heroMeta}>
          <div className={l.stats}>
            <div className={l.stat}><b>Minutes</b><span>to a 3D link</span></div>
            <div className={l.stat}><b>Free</b><span>during the beta</span></div>
            <div className={l.stat}><b>No sign-up</b><span>no app, no card</span></div>
          </div>
          <p className={l.beta}><i>BETA</i><span>For now we furnish living rooms and bedrooms.</span></p>
        </div>

        <div className={l.heroStrip}>
          <div className={l.strip} aria-label="One flat, from floor plan to AI image">
            {STRIP.map((x) => (
              <div className={x.area} key={x.src}>
                <div className={`${l.frame} ${x.frame ?? ""}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- статичные кадры макета, размеры задаёт рамка */}
                  <img src={x.src} alt={x.alt} />
                  {x.tag ? <span className={l.tag}>{x.tag}</span> : null}
                  {x.ai ? <span className={l.aiBadge}>AI visualisation, not a photo</span> : null}
                </div>
                <div className={l.stripCap}>{x.cap}{x.t ? <> <span className={l.t}>{x.t}</span></> : null}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
