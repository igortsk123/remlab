import type { Metadata } from "next";
import { LandingHero } from "@/components/trial/LandingHero";
import { LandingCompare, LandingExample, LandingHow } from "@/components/trial/LandingSections";
import { LandingFaq, LandingFinal, LandingWaiting } from "@/components/trial/LandingWaiting";
import { TryShell } from "@/components/trial/TryShell";

// Лендинг пробы для агентов UK (план agent-trial-01, T-C): макет v3-en-final, согласованный владельцем (TG 420), с рабочей
// формой в первом экране. Пока не публичный — из поиска закрыт; Метрики на /try нет (`lib/metrika.ts:noMetrikaPath`).
export const metadata: Metadata = {
  title: "RemLab for Agents",
  description: "Upload a PDF or photo and get a tour link for buyers.",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function TryPage() {
  return (
    <TryShell>
      <LandingHero />
      <LandingHow />
      <LandingCompare />
      <LandingExample />
      <LandingWaiting />
      <LandingFaq />
      <LandingFinal />
    </TryShell>
  );
}
