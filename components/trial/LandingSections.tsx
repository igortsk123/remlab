// Средние блоки лендинга `/try` (макет v3-en-final, TG 420): «How it works», «Minutes, not days», пример для объявления.
// Тексты на двух языках — `landing-text.ts`.

import type { ReactNode } from "react";
import { landingText } from "@/components/trial/landing-text";
import l from "@/components/trial/landing.module.css";
import type { TrialLang } from "@/lib/trial/i18n";

const ITEMS = [["/try/item-0.jpg", "£347"], ["/try/item-1.jpg", "£454"], ["/try/item-3.jpg", "£160"], ["/try/item-5.jpg", "£267"]];
const svg = (d: ReactNode) => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">{d}</svg>
);
const ICONS: ReactNode[] = [
  svg(<><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>),
  svg(<><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 9h8M8 13h8M8 17h5" /></>),
  svg(<><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="10" r="2" /><path d="M21 16l-5-5-9 8" /></>),
  svg(<><path d="M4 18V9a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9" /><path d="M2 18h20M7 7V5h10v2" /></>),
];

export function LandingHow({ lang }: { lang: TrialLang }) {
  const t = landingText(lang).how;
  return (
    <section id="how" style={{ paddingTop: 8 }}>
      <div className={l.wrap}>
        <h2>{t.h2}</h2>
        <div className={l.steps}>
          {t.steps.map(([h, p], i) => (
            <div className={`${l.card} ${l.step}`} key={h}><div className={l.n}>{i + 1}</div><h3>{h}</h3><p>{p}</p></div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function LandingCompare({ lang }: { lang: TrialLang }) {
  const t = landingText(lang).cmp;
  return (
    <section className={l.alt}>
      <div className={l.wrap}>
        <h2>{t.h2}</h2>
        <div className={`${l.card} ${l.cmp}`}>
          <div className={`${l.cmpRow} ${l.cmpHead}`}><div className={l.k} /><div>{t.old}</div><div className={l.new}>RemLab</div></div>
          {t.rows.map(([k, o, n]) => (
            <div className={l.cmpRow} key={k}><div className={l.k}>{k}</div><div className={l.old}>{o}</div><div className={l.new}>{n}</div></div>
          ))}
        </div>
        <p className={l.cmpFoot}>{t.foot}</p>
      </div>
    </section>
  );
}

export function LandingExample({ lang }: { lang: TrialLang }) {
  const t = landingText(lang).example;
  const aiBadge = landingText(lang).hero.aiBadge;
  return (
    <section id="example">
      <div className={l.wrap}>
        <h2>{t.h2}</h2>
        <div className={l.gets}>
          <div className={`${l.card} ${l.tour}`}>
            <div className={l.tourTop}><div className={l.url}>remont-lab.online/try/215</div><span>{t.flat}</span></div>
            <div className={l.frame}>
              {/* eslint-disable-next-line @next/next/no-img-element -- статичный кадр примера */}
              <img src="/try/ai.jpg" alt={t.alt} />
              <span className={l.aiBadge}>{aiBadge}</span>
            </div>
            <div className={l.roomSum}><b>{t.room}</b><span>{t.sum}</span></div>
            <div className={l.items}>
              {ITEMS.map(([src, price], i) => (
                <div className={l.item} key={src}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- миниатюра товара из макета */}
                  <img src={src} alt="" />
                  <div><b>{t.items[i]![0]}</b><span>{t.items[i]![1]}</span></div><em>{price}</em>
                </div>
              ))}
            </div>
          </div>
          <div className={l.getList}>
            {t.gets.map((g, i) => (
              <div className={`${l.card} ${l.get}`} key={g.title}>
                <div className={l.ic}>{ICONS[i]}</div>
                <div><h3>{g.title}</h3>{g.p.map(([b, p]) => <p key={p}>{b ? <><b>{b}</b> </> : null}{p}</p>)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
