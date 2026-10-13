import { legalText, type LegalDoc, type LegalLang } from "@/lib/legal/texts";
import { POLICY_VERSION } from "@/lib/legal/policy";

// Страница политики/cookie/условий (план b2b-04): один шаблон на три документа и два языка.
export function LegalPage({ doc, lang }: { doc: LegalDoc; lang: LegalLang }) {
  const t = legalText(doc, lang);
  const other = lang === "en" ? "ru" : "en";
  return (
    <main className="container stack" style={{ paddingTop: 24, paddingBottom: 48, gap: 16, maxWidth: 760 }}>
      <div className="stack" style={{ gap: 4 }}>
        <h1 style={{ margin: 0 }}>{t.title}</h1>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          {t.draftNote} {lang === "en" ? "Version" : "Версия"}: {POLICY_VERSION}.{" "}
          <a href={`?lang=${other}`}>{other === "en" ? "English" : "Русский"}</a>
        </p>
      </div>
      {t.sections.map((s) => (
        <section key={s.h} className="stack" style={{ gap: 6 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>{s.h}</h2>
          {s.p.map((p) => <p key={p} style={{ margin: 0 }}>{p}</p>)}
        </section>
      ))}
    </main>
  );
}
