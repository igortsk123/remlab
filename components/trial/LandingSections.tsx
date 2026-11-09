// Средние блоки лендинга `/try` (макет v3-en-final, TG 420): «How it works», «Minutes, not days», пример для объявления.

import type { ReactNode } from "react";
import l from "@/components/trial/landing.module.css";

const STEPS = [
  ["Upload the plan", "PDF or photo."],
  ["We build the 3D", "We flag sizes we can't confirm."],
  ["We furnish it", "Living room and bedrooms."],
  ["Send the link", "It opens in the browser."],
];
const CMP = [
  ["First result", "Often quoted as 24 to 48 hours", "Minutes"],
  ["To get started", "Quote, call, brief", "Upload a plan"],
  ["Furniture", "Chosen by the studio", "With prices"],
  ["Buyers get", "Still images or an app", "A browser link"],
];
const ITEMS = [
  ["/try/item-0.jpg", "Three-seat sofa, grey fabric", "sofa", "£347"],
  ["/try/item-1.jpg", "Coffee table, walnut effect", "coffee table", "£454"],
  ["/try/item-3.jpg", "Floor lamp, white", "lighting", "£160"],
  ["/try/item-5.jpg", "TV unit, oak and grey", "storage", "£267"],
];
const svg = (d: ReactNode) => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">{d}</svg>
);
const GETS: { icon: ReactNode; title: string; body: ReactNode }[] = [
  { icon: svg(<><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>),
    title: "Two links", body: <><p><b>Yours:</b> see it as your client will.</p><p><b>For buyers:</b> starts with a style quiz.</p></> },
  { icon: svg(<><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 9h8M8 13h8M8 17h5" /></>),
    title: "Easy to share", body: <p>Into the listing, an email or WhatsApp.</p> },
  { icon: svg(<><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="10" r="2" /><path d="M21 16l-5-5-9 8" /></>),
    title: "AI images are labelled", body: <p>Even when downloaded.</p> },
  { icon: svg(<><path d="M4 18V9a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9" /><path d="M2 18h20M7 7V5h10v2" /></>),
    title: "Furniture with prices", body: <p>The same pieces as in the tour.</p> },
];

export function LandingHow() {
  return (
    <section id="how" style={{ paddingTop: 8 }}>
      <div className={l.wrap}>
        <h2>How it works</h2>
        <div className={l.steps}>
          {STEPS.map(([h, p], i) => (
            <div className={`${l.card} ${l.step}`} key={h}><div className={l.n}>{i + 1}</div><h3>{h}</h3><p>{p}</p></div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function LandingCompare() {
  return (
    <section className={l.alt}>
      <div className={l.wrap}>
        <h2>Minutes, not days</h2>
        <div className={`${l.card} ${l.cmp}`}>
          <div className={`${l.cmpRow} ${l.cmpHead}`}><div className={l.k} /><div>Made-to-order 3D</div><div className={l.new}>RemLab</div></div>
          {CMP.map(([k, o, n]) => (
            <div className={l.cmpRow} key={k}><div className={l.k}>{k}</div><div className={l.old}>{o}</div><div className={l.new}>{n}</div></div>
          ))}
        </div>
        <p className={l.cmpFoot}>Studio timings: from their own websites, November 2026.</p>
      </div>
    </section>
  );
}

export function LandingExample() {
  return (
    <section id="example">
      <div className={l.wrap}>
        <h2>What you get for each listing</h2>
        <div className={l.gets}>
          <div className={`${l.card} ${l.tour}`}>
            <div className={l.tourTop}><div className={l.url}>remont-lab.online/try/215</div><span>2-bed · 77.2 m²</span></div>
            <div className={l.frame}>
              {/* eslint-disable-next-line @next/next/no-img-element -- статичный кадр примера */}
              <img src="/try/ai.jpg" alt="Living room, AI image" />
              <span className={l.aiBadge}>AI visualisation, not a photo</span>
            </div>
            <div className={l.roomSum}><b>Living room · 14.4 m²</b><span>12 items · guide total £2,091</span></div>
            <div className={l.items}>
              {ITEMS.map(([src, name, kind, price]) => (
                <div className={l.item} key={src}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- миниатюра товара из макета */}
                  <img src={src} alt="" />
                  <div><b>{name}</b><span>{kind}</span></div><em>{price}</em>
                </div>
              ))}
            </div>
          </div>
          <div className={l.getList}>
            {GETS.map((g) => (
              <div className={`${l.card} ${l.get}`} key={g.title}><div className={l.ic}>{g.icon}</div><div><h3>{g.title}</h3>{g.body}</div></div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
