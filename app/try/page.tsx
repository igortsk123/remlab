import type { Metadata } from "next";
import { LandingHero } from "@/components/trial/LandingHero";
import { LandingCompare, LandingExample, LandingHow } from "@/components/trial/LandingSections";
import { LandingFaq, LandingFinal, LandingWaiting } from "@/components/trial/LandingWaiting";
import { TryShell } from "@/components/trial/TryShell";
import { textOf } from "@/lib/trial/i18n";
import { pageLang } from "@/lib/trial/page-lang";

// Лендинг пробы для агентов UK (план agent-trial-01, T-C): макет v3-en-final, согласованный владельцем (TG 420), с рабочей
// формой в первом экране. Два языка — `?lang=ru|en` (план agent-trial-08, П). Пока не публичный — из поиска закрыт;
// Метрики на /try нет (`lib/metrika.ts:noMetrikaPath`).
type Search = Promise<{ lang?: string | string[] }>;

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const { meta } = textOf((await pageLang(await searchParams)).lang);
  return { title: meta.title, description: meta.description, robots: { index: false, follow: false }, referrer: "no-referrer" };
}

export default async function TryPage({ searchParams }: { searchParams: Search }) {
  const { lang, explicit } = await pageLang(await searchParams);
  return (
    <TryShell lang={lang} explicit={explicit} path="/try">
      <LandingHero lang={lang} />
      <LandingHow lang={lang} />
      <LandingCompare lang={lang} />
      <LandingExample lang={lang} />
      <LandingWaiting lang={lang} />
      <LandingFaq lang={lang} />
      <LandingFinal lang={lang} />
    </TryShell>
  );
}
